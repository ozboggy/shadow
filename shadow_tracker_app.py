import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth
from streamlit_autorefresh import st_autorefresh

# Optional moon support
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except:
    pass

# Env vars
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

# Home location
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434

# Defaults
DEFAULT_RADIUS_KM     = 10
FORECAST_INTERVAL_SEC = 30
FORECAST_DURATION_MIN = 5

def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        st.warning("🔒 Missing Pushover creds")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": PUSHOVER_API_TOKEN,
                "user":  PUSHOVER_USER_KEY,
                "title": title,
                "message": message
            }
        )
    except Exception as e:
        st.warning(f"Pushover failed: {e}")

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

now = datetime.now(timezone.utc)

# compute sun / moon altitude at home
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now)
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now
    moon_alt = math.degrees(float(ephem.Moon(obs).alt))
else:
    moon_alt = None

# history
if "history" not in st.session_state:
    st.session_state.history = []

# Sidebar
with st.sidebar:
    st.header("Map & Alert Settings")
    # Sun / Moon
    sc = "green" if sun_alt > 0 else "red"
    st.markdown(f"**Sun alt:** <span style='color:{sc};'>{sun_alt:.1f}°</span>",
                unsafe_allow_html=True)
    if moon_alt is not None:
        mc = "green" if moon_alt > 0 else "red"
        st.markdown(f"**Moon alt:** <span style='color:{mc};'>{moon_alt:.1f}°</span>",
                    unsafe_allow_html=True)
    else:
        st.markdown("**Moon alt:** _(PyEphem missing)_")

    radius_km           = st.slider("Search Radius (km)", 0, 1000, DEFAULT_RADIUS_KM)
    military_radius_km  = st.slider("Military Alert Radius (km)", 0, 1000, DEFAULT_RADIUS_KM)
    track_sun           = st.checkbox("Show Sun Shadows", True)
    show_moon           = st.checkbox("Show Moon Shadows", False)
    alert_width         = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    enable_onscreen     = st.checkbox("Enable Onscreen Alert", True)

    debug_adsb          = st.checkbox("🔍 Debug raw ADS-B JSON", False)
    debug_df            = st.checkbox("🔍 Debug processed DataFrame", False)

    if st.button("Test Pushover"):
        send_pushover("✈️ Test", "This is a test notification.")
        st.success("Pushover sent!")
    if st.button("Test Onscreen"):
        if enable_onscreen:
            st.error("🚨 TEST ALERT!")
            st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
        else:
            st.warning("Onscreen disabled.")

st.title("✈️ Aircraft Shadow Tracker")

# ─── FETCH VIA VIRTUALRADAR PUBLIC API ─────────────────────────
ac_data = []
try:
    vr_url = (
        "https://public-api.adsbexchange.com/VirtualRadar/AircraftList.json"
        f"?lat={CENTER_LAT}&lng={CENTER_LON}&fDstL=0&fDstU={radius_km}"
    )
    r = requests.get(vr_url, timeout=10)
    r.raise_for_status()
    ac_data = r.json().get("acList", [])
except Exception as e:
    st.warning(f"Fetch failed: {e}")

if debug_adsb:
    st.subheader("Raw ADS-B JSON")
    st.write(ac_data)

# ─── PROCESS INTO DATAFRAME ───────────────────────────────────
aircraft = []
for ac in ac_data:
    try:
        lat   = float(ac["Lat"])
        lon   = float(ac["Long"])
        alt   = float(ac.get("Alt", 0))
        angle = float(ac.get("Trak", 0))
        cs    = ac.get("Callsign", "").strip()
        mil   = bool(ac.get("Mil", False))
    except:
        continue
    aircraft.append(dict(lat=lat, lon=lon, alt=alt, angle=angle, callsign=cs, mil=mil))

df = pd.DataFrame(aircraft)
if debug_df:
    st.subheader("Processed DataFrame")
    st.write(df)

st.sidebar.markdown(f"**Tracked Aircraft:** {len(df)}")
if not df.empty:
    df["alt"] = pd.to_numeric(df["alt"], errors="coerce").fillna(0)

# ─── FORECAST TRAILS ──────────────────────────────────────────
trails_sun, trails_moon = [], []
if track_sun:
    for i,row in df.iterrows():
        path,times = [],[]
        for s in range(0, FORECAST_INTERVAL_SEC*FORECAST_DURATION_MIN+1, FORECAST_INTERVAL_SEC):
            ft = now + timedelta(seconds=s)
            sa = get_altitude(row.lat, row.lon, ft)
            sz = get_azimuth(row.lat, row.lon, ft)
            if sa>0:
                d = row.alt / math.tan(math.radians(sa))
                sh_lat = row.lat + (d/111111)*math.cos(math.radians(sz+180))
                sh_lon = row.lon + (d/(111111*math.cos(math.radians(row.lat))))*math.sin(math.radians(sz+180))
                path.append((sh_lon, sh_lat)); times.append(s)
        if path:
            trails_sun.append({"callsign":row.callsign,"path":path,"times":times})
if show_moon and ephem:
    for i,row in df.iterrows():
        path,times = [],[]
        for s in range(0, FORECAST_INTERVAL_SEC*FORECAST_DURATION_MIN+1, FORECAST_INTERVAL_SEC):
            ft = now + timedelta(seconds=s)
            obs = ephem.Observer(); obs.lat,obs.lon,obs.date=str(row.lat),str(row.lon),ft
            m   = ephem.Moon(obs)
            ma  = math.degrees(float(m.alt)); mz = math.degrees(float(m.az))
            if ma>0:
                d = row.alt / math.tan(math.radians(ma))
                sh_lat = row.lat + (d/111111)*math.cos(math.radians(mz+180))
                sh_lon = row.lon + (d/(111111*math.cos(math.radians(row.lat))))*math.sin(math.radians(mz+180))
                path.append((sh_lon, sh_lat)); times.append(s)
        if path:
            trails_moon.append({"callsign":row.callsign,"path":path,"times":times})

# ─── RENDER MAP ────────────────────────────────────────────────
view  = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers=[]
if not df.empty:
    icon_df = pd.DataFrame([{
        "lon":r.lon,"lat":r.lat,
        "icon":{"url":"https://img.icons8.com/ios-filled/50/000000/airplane-take-off.png",
                "width":128,"height":128,"anchorX":64,"anchorY":64},
        "angle":r.angle
    } for _,r in df.iterrows()])
    layers.append(pdk.Layer("IconLayer", icon_df,
                            get_icon="icon", get_position=["lon","lat"],
                            get_angle="angle", size_scale=15, pickable=True))
if track_sun:
    layers.append(pdk.Layer("PathLayer", pd.DataFrame(trails_sun),
                            get_path="path", get_color=[255,215,0,150],
                            width_scale=10, width_min_pixels=2))
if show_moon:
    layers.append(pdk.Layer("PathLayer", pd.DataFrame(trails_moon),
                            get_path="path", get_color=[100,100,100,150],
                            width_scale=10, width_min_pixels=2))
layers.append(pdk.Layer("ScatterplotLayer",
                        pd.DataFrame([{"lat":CENTER_LAT,"lon":CENTER_LON}]),
                        get_position=["lon","lat"], get_color=[255,0,0,200],
                        get_radius=alert_width))
st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_style="light"),
                use_container_width=True)

# ─── ALERTS ────────────────────────────────────────────────────
alerts=[]
for tr in trails_sun:
    for (lon,lat),t in zip(tr["path"],tr["times"]):
        if hav(lat,lon,CENTER_LAT,CENTER_LON)<=alert_width:
            alerts.append((tr["callsign"],t))
            send_pushover("✈️ Shadow Alert",f"{tr['callsign']} in ~{t}s")
            break
if show_moon:
    for tr in trails_moon:
        for (lon,lat),t in zip(tr["path"],tr["times"]):
            if hav(lat,lon,CENTER_LAT,CENTER_LON)<=alert_width:
                alerts.append((tr["callsign"],t))
                send_pushover("🌑 Moon Shadow",f"{tr['callsign']} in ~{t}s")
                break
for _,row in df.iterrows():
    if row.mil and hav(row.lat,row.lon,CENTER_LAT,CENTER_LON)<=military_radius_km*1000:
        alerts.append((row.callsign,0))
        send_pushover("✈️ Military Alert",f"{row.callsign} within {military_radius_km}km")
        break

if alerts and enable_onscreen:
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
for cs,t in alerts:
    st.write(f"✈️ {cs} — in ~{t}s")
if not alerts:
    st.success("✅ No shadows intersect")

# ─── HISTORY CHART ─────────────────────────────────────────────
st.session_state.history.append({"time":now,"tracked":len(df),"shadow":len(alerts)})
hist = pd.DataFrame(st.session_state.history).set_index("time")
st.subheader("📈 Tracked vs Shadow Events Over Time")
st.line_chart(hist)
