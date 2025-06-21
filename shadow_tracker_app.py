import time
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

# Optional moon computations
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh every second
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except Exception:
    pass

# Pushover credentials
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title: str, message: str) -> bool:
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return False
    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": PUSHOVER_API_TOKEN,
                "user": PUSHOVER_USER_KEY,
                "title": title,
                "message": message
            }
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        st.error(f"Pushover API error: {e}")
        return False

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Defaults
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5

# Sidebar controls
with st.sidebar:
    st.header("Map Options")
    radius_km     = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun     = st.checkbox("Show Sun Shadows", True)
    track_moon    = st.checkbox("Show Moon Shadows", False)
    alert_width   = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert    = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

# Current UTC time
now_utc = datetime.now(timezone.utc)

# Compute sun & moon altitude
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon = str(CENTER_LAT), str(CENTER_LON)
    obs.date = now_utc
    moon_obs = ephem.Moon(obs)
    moon_alt = math.degrees(moon_obs.alt)
else:
    moon_alt = None

# Fetch ADS-B Exchange data
aircraft_list = []
api_key = os.getenv("RAPIDAPI_KEY")
if api_key:
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
    }
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        adsb = r.json().get("ac", [])
    except Exception:
        st.warning("Failed to fetch ADS-B Exchange data.")
        adsb = []
else:
    adsb = []

for ac in adsb:
    try:
        lat = float(ac.get("lat")); lon = float(ac.get("lon"))
    except:
        continue
    cs = (ac.get("flight") or ac.get("hex") or "").strip()
    try: alt_val = float(ac.get("alt_geo") or ac.get("alt_baro") or 0)
    except: alt_val = 0.0
    try: vel = float(ac.get("gs") or ac.get("spd") or 0)
    except: vel = 0.0
    try: hdg = float(ac.get("track") or ac.get("trak") or 0)
    except: hdg = 0.0

    aircraft_list.append({
        "lat": lat, "lon": lon,
        "alt": alt_val, "vel": vel,
        "hdg": hdg, "callsign": cs
    })

# Build DataFrame and filter out ground (altitude ≤ 0)
df_ac = pd.DataFrame(aircraft_list)
if not df_ac.empty:
    df_ac[['alt','vel','hdg']] = df_ac[['alt','vel','hdg']].apply(
        pd.to_numeric, errors='coerce'
    ).fillna(0)
    df_ac = df_ac[df_ac['alt'] > 0]

# Total airborne aircraft count
total_ac = len(df_ac)

# Sidebar status
st.sidebar.markdown("### Status")
st.sidebar.markdown(f"Sun altitude: {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.sidebar.markdown(f"Moon altitude: {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.sidebar.warning("Moon data unavailable")
st.sidebar.markdown(f"Total airborne aircraft: **{total_ac}**")

# Compute shadow trails
sun_trails = []
moon_trails = []
if not df_ac.empty:
    for _, row in df_ac.iterrows():
        cs = row['callsign']
        lat0, lon0 = row['lat'], row['lon']
        s_path = []
        m_path = []
        for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
            t = now_utc + timedelta(seconds=i)
            dist_m = row['vel'] * i
            dlat = dist_m * math.cos(math.radians(row['hdg'])) / 111111
            dlon = dist_m * math.sin(math.radians(row['hdg'])) / (111111 * math.cos(math.radians(lat0)))
            lat_i, lon_i = lat0 + dlat, lon0 + dlon

            # sun trail
            sa = get_altitude(lat_i, lon_i, t)
            saz = get_azimuth(lat_i, lon_i, t)
            if sa > 0 and track_sun:
                sd = row['alt'] / math.tan(math.radians(sa))
                sh_lat = lat_i + (sd / 111111) * math.cos(math.radians(saz + 180))
                sh_lon = lon_i + (sd / (111111 * math.cos(math.radians(lat_i)))) * math.sin(math.radians(saz + 180))
                s_path.append([sh_lon, sh_lat])

            # moon trail
            if ephem and track_moon:
                obs.date = t
                m = ephem.Moon(obs)
                ma = math.degrees(m.alt)
                maz = math.degrees(m.az)
                if ma > 0:
                    md = row['alt'] / math.tan(math.radians(ma))
                    mh_lat = lat_i + (md / 111111) * math.cos(math.radians(maz + 180))
                    mh_lon = lon_i + (md / (111111 * math.cos(math.radians(lat_i)))) * math.sin(math.radians(maz + 180))
                    m_path.append([mh_lon, mh_lat])

        if s_path:
            sun_trails.append({"path": s_path, "callsign": cs})
        if m_path:
            moon_trails.append({"path": m_path, "callsign": cs})

# Build pydeck layers
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []

if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", df_ac,
        get_position=["lon","lat"], get_color=[0,128,255,200],
        get_radius=100, pickable=True
    ))

if track_sun and sun_trails:
    df_sun = pd.DataFrame(sun_trails)
    layers.append(pdk.Layer(
        "PathLayer", df_sun,
        get_path="path", get_color=[255,215,0,150],
        width_scale=10, width_min_pixels=2, pickable=True
    ))

if track_moon and moon_trails:
    df_moon = pd.DataFrame(moon_trails)
    layers.append(pdk.Layer(
        "PathLayer", df_moon,
        get_path="path", get_color=[135,206,250,150],
        width_scale=10, width_min_pixels=2, pickable=True
    ))

# Alert circle polygon
circle = []
for ang in range(0, 360, 5):
    b = math.radians(ang)
    dy = (alert_width / 111111) * math.cos(b)
    dx = (alert_width / (111111 * math.cos(math.radians(CENTER_LAT)))) * math.sin(b)
    circle.append([CENTER_LON + dx, CENTER_LAT + dy])
circle.append(circle[0])
layers.append(pdk.Layer(
    "PolygonLayer", [{"polygon": circle}],
    get_polygon="polygon",
    get_fill_color=[255,0,0,50],
    stroked=True, get_line_color=[255,0,0], get_line_width=2
))

# Tooltip configuration
tooltip = {
    "html": "<b>Callsign:</b> {callsign}<br/>"
            "<b>Alt:</b> {alt:.0f} m<br/>"
            "<b>Speed:</b> {vel:.0f} m/s<br/>"
            "<b>Heading:</b> {hdg:.0f}°",
    "style": {"backgroundColor": "black", "color": "white"}
}

# Render map with tooltip
deck = pdk.Deck(
    layers=layers,
    initial_view_state=view,
    map_style="light",
    tooltip=tooltip
)
st.pydeck_chart(deck, use_container_width=True)

# Alerts with sound
if track_sun and sun_trails:
    for tr in sun_trails:
        for lon, lat in tr["path"]:
            if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
                st.error(f"🚨 Sun shadow of {tr['callsign']} over home!")
                st.markdown(
                    """<audio autoplay>
                         <source src="https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg" type="audio/ogg">
                       </audio>""",
                    unsafe_allow_html=True
                )
                send_pushover("✈️ Shadow Alert", f"{tr['callsign']} shadow at home")
                break

# Test buttons
if test_alert:
    st.success("Test alert triggered")

if test_pushover:
    ph = st.empty()
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        ph.error("⚠️ Missing Pushover credentials")
    else:
        ok = send_pushover("✈️ Test", "This is a test from your app.")
        ph.success("✅ Test Pushover sent!" if ok else "❌ Test Pushover failed")
    time.sleep(5)
    ph.empty()
