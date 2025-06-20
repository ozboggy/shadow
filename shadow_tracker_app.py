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

# Sidebar: auto‐refresh
st.sidebar.header("Refresh Settings")
auto_refresh     = st.sidebar.checkbox("Auto Refresh Map", True)
refresh_interval = st.sidebar.number_input("Refresh Interval (s)", 1, 60, 1)
if auto_refresh:
    st_autorefresh(interval=refresh_interval * 1000, key="refresh")

# Environment & constants
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
ADSBEX_TOKEN       = os.getenv("ADSBEX_TOKEN")

CENTER_LAT, CENTER_LON = -33.7602563, 150.9717434
DEFAULT_RADIUS_KM     = 10
FORECAST_INTERVAL_SEC = 30
FORECAST_DURATION_MIN = 5

def send_pushover(title, message):
    if not (PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN):
        st.warning("🔒 Missing Pushover credentials")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY,
                  "title": title, "message": message},
            timeout=5
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

# Compute Sun/Moon altitude at home
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now)
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now
    moon_alt = math.degrees(float(ephem.Moon(obs).alt))
else:
    moon_alt = None

# Sidebar: map & alert settings
st.sidebar.header("Map & Alert Settings")
st.sidebar.markdown(f"**Sun altitude:** {sun_alt:.1f}°")
if moon_alt is not None:
    st.sidebar.markdown(f"**Moon altitude:** {moon_alt:.1f}°")

radius_km          = st.sidebar.slider("Search Radius (km)", 0, 1000, DEFAULT_RADIUS_KM)
military_radius_km = st.sidebar.slider("Military Alert Radius (km)", 0, 1000, DEFAULT_RADIUS_KM)
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

# Fetch ADS-B Exchange data
raw = []
if ADSBEX_TOKEN:
    try:
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        headers = {
            "x-rapidapi-key": ADSBEX_TOKEN,
            "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
        }
        r = requests.get(url, headers=headers, timeout=10); r.raise_for_status()
        raw = r.json().get("ac", [])
    except Exception as e:
        st.warning(f"ADS-B fetch failed: {e}")

# Fallback to OpenSky if ADS-B empty
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
        st.warning(f"OpenSky fetch failed: {e}"); states = []
    raw = [
        {"lat": s[6], "lon": s[5], "alt": s[13] or 0.0,
         "track": s[10] or 0.0, "callsign": (s[1].strip() or s[0]), "mil": False}
        for s in states if len(s) >= 11
    ]

# Build DataFrame
ac_list = []
for ac in raw:
    try:
        lat   = float(ac.get("lat") or ac.get("Lat") or 0)
        lon   = float(ac.get("lon") or ac.get("Long") or 0)
        alt   = float(ac.get("alt") or ac.get("alt_geo", 0))
        angle = float(ac.get("track") or ac.get("Trak") or 0)
        cs    = ac.get("callsign") or ac.get("flight") or ac.get("Callsign") or ""
        mil   = bool(ac.get("mil", False))
    except:
        continue
    ac_list.append({"lat": lat, "lon": lon, "alt": alt, "angle": angle, "callsign": cs.strip(), "mil": mil})

df = pd.DataFrame(ac_list)
st.sidebar.markdown(f"**Tracked Aircraft:** {len(df)}")
st.sidebar.markdown(f"**Tracked Military:** {int(df['mil'].sum())}")
if not df.empty:
    df["alt"] = pd.to_numeric(df["alt"], errors="coerce").fillna(0)

# Compute shadow trails (lists of [lon, lat])
trails_sun, trails_moon = [], []
if track_sun:
    for _, r in df.iterrows():
        path = []
        for sec in range(0, FORECAST_INTERVAL_SEC * FORECAST_DURATION_MIN + 1, FORECAST_INTERVAL_SEC):
            ft = now + timedelta(seconds=sec)
            sa, az = get_altitude(r.lat, r.lon, ft), get_azimuth(r.lat, r.lon, ft)
            if sa > 0:
                d = r.alt / math.tan(math.radians(sa))
                sh_lat = r.lat + (d / 111111) * math.cos(math.radians(az + 180))
                sh_lon = r.lon + (d / (111111 * math.cos(math.radians(r.lat)))) * math.sin(math.radians(az + 180))
                path.append([sh_lon, sh_lat])
        if path:
            trails_sun.append({"callsign": r.callsign, "path": path})

if track_moon and ephem:
    for _, r in df.iterrows():
        path = []
        for sec in range(0, FORECAST_INTERVAL_SEC * FORECAST_DURATION_MIN + 1, FORECAST_INTERVAL_SEC):
            ft = now + timedelta(seconds=sec)
            obs = ephem.Observer(); obs.lat, obs.lon, obs.date = str(r.lat), str(r.lon), ft
            m = ephem.Moon(obs)
            ma, mz = math.degrees(float(m.alt)), math.degrees(float(m.az))
            if ma > 0:
                d = r.alt / math.tan(math.radians(ma))
                sh_lat = r.lat + (d / 111111) * math.cos(math.radians(mz + 180))
                sh_lon = r.lon + (d / (111111 * math.cos(math.radians(r.lat)))) * math.sin(math.radians(mz + 180))
                path.append([sh_lon, sh_lat])
        if path:
            trails_moon.append({"callsign": r.callsign, "path": path})

# Debug trails
if debug_trails:
    st.sidebar.write("Sun trails sample:", trails_sun[:2])
    st.sidebar.write("Moon trails sample:", trails_moon[:2])

# Determine which aircraft will shadow home
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

# Build pydeck layers
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []

# Aircraft dots
if not df_safe.empty:
    layers.append(pdk.Layer("ScatterplotLayer", df_safe,
                            get_position=["lon","lat"], get_color=[0,0,255,200], get_radius=100))
if not df_warn.empty:
    layers.append(pdk.Layer("ScatterplotLayer", df_warn,
                            get_position=["lon","lat"], get_color=[255,0,0,200], get_radius=100))

# Sun shadow paths atop everything
if track_sun and trails_sun:
    layers.append(pdk.Layer("PathLayer", trails_sun,
                            get_path="path",
                            get_color=[255,215,0,255],
                            get_width=3,
                            width_min_pixels=3))

# Moon shadow paths
if track_moon and trails_moon:
    layers.append(pdk.Layer("PathLayer", trails_moon,
                            get_path="path",
                            get_color=[100,100,100,255],
                            get_width=3,
                            width_min_pixels=3))

# Home marker
layers.append(pdk.Layer("ScatterplotLayer",
                        pd.DataFrame([{"lat":CENTER_LAT,"lon":CENTER_LON}]),
                        get_position=["lon","lat"], get_color=[255,0,0,200], get_radius=alert_width))

# Render map
st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_style="light"),
                use_container_width=True)

# Onscreen alerts
if alerts and enable_onscreen:
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
for cs in alerts:
    st.write(f"✈️ {cs} — shadow predicted")
if not alerts:
    st.success("✅ No shadows predicted.")

# History chart
st.session_state.history.append({"time": now, "tracked": len(df), "shadows": len(alerts)})
hist_df = pd.DataFrame(st.session_state.history).set_index("time")
st.subheader("📈 Tracked vs Shadow Events")
st.line_chart(hist_df)
