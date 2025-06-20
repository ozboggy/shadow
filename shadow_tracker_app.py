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

# Ensure history exists
if "history" not in st.session_state:
    st.session_state.history = []

# Sidebar: auto-refresh
st.sidebar.header("Refresh Settings")
auto_refresh     = st.sidebar.checkbox("Auto Refresh Map", True)
refresh_interval = st.sidebar.number_input("Refresh Interval (s)", 1, 60, 1)
if auto_refresh:
    st_autorefresh(interval=refresh_interval * 1000, key="refresh")

# Env & constants
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
ADSBEX_TOKEN       = os.getenv("ADSBEX_TOKEN")

CENTER_LAT, CENTER_LON   = -33.7602563, 150.9717434
DEFAULT_RADIUS_KM         = 10
FORECAST_INTERVAL_SEC     = 30
FORECAST_DURATION_MIN     = 5

def send_pushover(title, message):
    if not (PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN):
        st.warning("🔒 Missing Pushover credentials")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": PUSHOVER_API_TOKEN,
                "user":  PUSHOVER_USER_KEY,
                "title": title,
                "message": message
            },
            timeout=5,
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

# Compute sun/moon altitudes
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now)
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now
    moon_alt = math.degrees(float(ephem.Moon(obs).alt))
else:
    moon_alt = None

# Sidebar: map & alert settings
st.sidebar.header("Map & Alert Settings")
st.sidebar.markdown(f"**Sun alt:** {sun_alt:.1f}°")
if moon_alt is not None:
    st.sidebar.markdown(f"**Moon alt:** {moon_alt:.1f}°")

radius_km          = st.sidebar.slider("Search Radius (km)", 0, 1000, DEFAULT_RADIUS_KM)
track_sun          = st.sidebar.checkbox("Show Sun Shadows", True)
track_moon         = st.sidebar.checkbox("Show Moon Shadows", False)
alert_width        = st.sidebar.slider("Shadow Alert Width (m)", 0, 1000, 50)
enable_onscreen    = st.sidebar.checkbox("Enable Onscreen Alert", True)
debug_trails       = st.sidebar.checkbox("Debug Trails Data", False)

if st.sidebar.button("Test Pushover"):
    send_pushover("✈️ Test Alert", "This is a test notification.")
    st.sidebar.success("Pushover test sent!")
if st.sidebar.button("Test Onscreen"):
    if enable_onscreen:
        st.error("🚨 TEST ALERT!")
        st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)

st.title("✈️ Aircraft Shadow Tracker")

# Fetch ADS-B Exchange
raw = []
if ADSBEX_TOKEN:
    try:
        url = (
            f"https://adsbexchange-com1.p.rapidapi.com/"
            f"v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        )
        headers = {
            "x-rapidapi-key": ADSBEX_TOKEN,
            "x-rapidapi-host":"adsbexchange-com1.p.rapidapi.com"
        }
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        raw = r.json().get("ac", [])
    except Exception as e:
        st.warning(f"ADS-B fetch failed: {e}")

# Fallback to OpenSky
if not raw:
    dr = radius_km / 111
    south, north = CENTER_LAT - dr, CENTER_LAT + dr
    dlon = dr / math.cos(math.radians(CENTER_LAT))
    west, east = CENTER_LON - dlon, CENTER_LON + dlon
    try:
        r2 = requests.get(
            f"https://opensky-network.org/api/states/all?"
            f"lamin={south}&lomin={west}&lamax={north}&lomax={east}",
            timeout=10
        )
        r2.raise_for_status()
        states = r2.json().get("states", [])
    except Exception as e:
        st.warning(f"OpenSky failed: {e}")
        states = []
    raw = [
        {
          "lat": s[6], "lon": s[5],
          "alt": s[13] or 0.0,
          "track": s[10] or 0.0,
          "callsign": (s[1].strip() or s[0])
        }
        for s in states if len(s) >= 11
    ]

# Build aircraft DataFrame
ac_list = []
for ac in raw:
    try:
        lat   = float(ac.get("lat"))
        lon   = float(ac.get("lon"))
        alt   = float(ac.get("alt", 0))
        angle = float(ac.get("track", 0))
        cs    = ac.get("callsign", "")
    except:
        continue
    ac_list.append({"lat":lat, "lon":lon, "alt":alt, "angle":angle, "callsign":cs})

df = pd.DataFrame(ac_list)
st.sidebar.markdown(f"**Tracked:** {len(df)}")
if not df.empty:
    df["alt"] = pd.to_numeric(df["alt"], errors="coerce").fillna(0)

# Compute shadow trails: lists of [lon, lat]
trails_sun, trails_moon = [], []
if track_sun:
    for _, r in df.iterrows():
        path = []
        for sec in range(0, FORECAST_INTERVAL_SEC * FORECAST_DURATION_MIN + 1, FORECAST_INTERVAL_SEC):
            ft = now + timedelta(seconds=sec)
            sa = get_altitude(r.lat, r.lon, ft)
            if sa > 0:
                az = get_azimuth(r.lat, r.lon, ft)
                d  = r.alt / math.tan(math.radians(sa))
                sh_lat = r.lat + (d/111111)*math.cos(math.radians(az+180))
                sh_lon = r.lon + (d/(111111*math.cos(math.radians(r.lat))))*math.sin(math.radians(az+180))
                path.append([sh_lon, sh_lat])
        if path:
            trails_sun.append({"callsign": r.callsign, "path": path})

if track_moon and ephem:
    for _, r in df.iterrows():
        path = []
        for sec in range(0, FORECAST_INTERVAL_SEC * FORECAST_DURATION_MIN + 1, FORECAST_INTERVAL_SEC):
            ft = now + timedelta(seconds=sec)
            obs = ephem.Observer(); obs.lat, obs.lon, obs.date = str(r.lat), str(r.lon), ft
            m   = ephem.Moon(obs)
            ma  = math.degrees(float(m.alt))
            if ma > 0:
                mz = math.degrees(float(m.az))
                d  = r.alt / math.tan(math.radians(ma))
                sh_lat = r.lat + (d/111111)*math.cos(math.radians(mz+180))
                sh_lon = r.lon + (d/(111111*math.cos(math.radians(r.lat))))*math.sin(math.radians(mz+180))
                path.append([sh_lon, sh_lat])
        if path:
            trails_moon.append({"callsign": r.callsign, "path": path})

# Debug trails
if debug_trails:
    st.sidebar.write("Sun trails:", trails_sun[:1])
    st.sidebar.write("Moon trails:", trails_moon[:1])

# Determine alerts
alerts = []
for tr in trails_sun:
    for lon, lat in tr["path"]:
        if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
            alerts.append(tr["callsign"])
            send_pushover("✈️ Shadow Alert", f"{tr['callsign']} predicted")
            break

df["will_shadow"] = df["callsign"].isin(alerts)
df_safe = df[~df["will_shadow"]]
df_warn = df[df["will_shadow"]]

# Build layers
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []

# Aircraft dots
if not df_safe.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", df_safe,
        get_position=["lon","lat"], get_color=[0,0,255,200], get_radius=80
    ))
if not df_warn.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", df_warn,
        get_position=["lon","lat"], get_color=[255,0,0,200], get_radius=80
    ))

# Sun shadows (above dots)
if track_sun and trails_sun:
    df_ps = pd.DataFrame(trails_sun)
    layers.append(pdk.Layer(
        "PathLayer", df_ps,
        get_path="path",
        get_color=[255,215,0],
        width_scale=15,
        width_min_pixels=4
    ))

# Moon shadows
if track_moon and trails_moon:
    df_pm = pd.DataFrame(trails_moon)
    layers.append(pdk.Layer(
        "PathLayer", df_pm,
        get_path="path",
        get_color=[100,100,100],
        width_scale=10,
        width_min_pixels=3
    ))

# Home
layers.append(pdk.Layer(
    "ScatterplotLayer",
    pd.DataFrame([{"lat":CENTER_LAT,"lon":CENTER_LON}]),
    get_position=["lon","lat"], get_color=[255,0,0,200],
    get_radius=alert_width
))

# Render
st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_style="light"),
                use_container_width=True)

# Alerts UI
if alerts and enable_onscreen:
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
for cs in alerts:
    st.write(f"✈️ {cs} — shadow predicted")
if not alerts:
    st.success("✅ No shadows predicted.")

# History
st.session_state.history.append({"time":now, "tracked":len(df), "shadows":len(alerts)})
hist = pd.DataFrame(st.session_state.history).set_index("time")
st.subheader("📈 Tracked vs Shadow Events Over Time")
st.line_chart(hist)

