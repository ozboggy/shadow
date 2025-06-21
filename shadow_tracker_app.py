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

# Auto-refresh every second
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except Exception:
    pass

# Pushover
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        st.warning("Pushover credentials not set.")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
    except Exception as e:
        st.warning(f"Pushover failed: {e}")

# Haversine
def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Defaults
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5

# Sidebar
with st.sidebar:
    st.header("Map Options")
    radius_km     = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun     = st.checkbox("Show Sun Shadows", True)
    alert_width   = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert    = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

# Current UTC time
time_now = datetime.now(timezone.utc)

st.title("✈️ Aircraft Shadow Tracker (ADS-B Exchange)")

# --- Fetch ADS-B Exchange data -----------------------------------------------
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
    # parse lat/lon
    try:
        lat = float(ac.get("lat"))
        lon = float(ac.get("lon"))
    except Exception:
        continue

    cs = (ac.get("flight") or ac.get("hex") or "").strip()

    # robust altitude
    alt_raw = ac.get("alt_geo") or ac.get("alt_baro") or 0.0
    try:
        alt_val = float(alt_raw)
    except Exception:
        alt_val = 0.0

    # robust groundspeed
    try:
        vel = float(ac.get("gs") or ac.get("spd") or 0)
    except Exception:
        vel = 0.0

    # robust heading
    try:
        hdg = float(ac.get("track") or ac.get("trak") or 0)
    except Exception:
        hdg = 0.0

    aircraft_list.append({
        "lat": lat, "lon": lon,
        "alt": alt_val, "vel": vel,
        "hdg": hdg, "callsign": cs
    })

# Build DataFrame
df_ac = pd.DataFrame(aircraft_list)
if df_ac.empty:
    st.warning("No aircraft data.")
else:
    df_ac[['alt','vel','hdg']] = df_ac[['alt','vel','hdg']].apply(
        pd.to_numeric, errors='coerce'
    ).fillna(0)

# --- Compute shadow trails --------------------------------------------------
trails = []
if track_sun and not df_ac.empty:
    for _, row in df_ac.iterrows():
        cs = row['callsign']
        lat0, lon0 = row['lat'], row['lon']
        path = []
        for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
            ft = time_now + timedelta(seconds=i)
            # project aircraft movement
            dist_m = row['vel'] * i
            dlat = dist_m * math.cos(math.radians(row['hdg'])) / 111111
            dlon = dist_m * math.sin(math.radians(row['hdg'])) / (111111 * math.cos(math.radians(lat0)))
            lat_i, lon_i = lat0 + dlat, lon0 + dlon

            sun_alt = get_altitude(lat_i, lon_i, ft)
            sun_az  = get_azimuth(lat_i, lon_i, ft)
            if sun_alt > 0:
                shadow_dist = row['alt'] / math.tan(math.radians(sun_alt))
                sh_lat = lat_i + (shadow_dist / 111111) * math.cos(math.radians(sun_az + 180))
                sh_lon = lon_i + (shadow_dist / (111111 * math.cos(math.radians(lat_i)))) * math.sin(math.radians(sun_az + 180))
                path.append([sh_lon, sh_lat])

        if path:
            trails.append({"path": path, "callsign": cs})

# --- Build pydeck layers ----------------------------------------------------
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []

# Aircraft scatter layer
if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        df_ac,
        get_position=["lon","lat"],
        get_color=[0,128,255,200],
        get_radius=100,
        pickable=True
    ))

# Shadow paths
if track_sun and trails:
    df_trails = pd.DataFrame(trails)
    layers.append(pdk.Layer(
        "PathLayer",
        df_trails,
        get_path="path",
        get_color=[0,0,0,150],
        width_scale=10,
        width_min_pixels=2,
        pickable=False
    ))

# Alert‐radius circle polygon
circle = []
for angle in range(0, 360, 5):
    bearing = math.radians(angle)
    dy = (alert_width / 111111) * math.cos(bearing)
    dx = (alert_width / (111111 * math.cos(math.radians(CENTER_LAT)))) * math.sin(bearing)
    circle.append([CENTER_LON + dx, CENTER_LAT + dy])
circle.append(circle[0])

layers.append(pdk.Layer(
    "PolygonLayer",
    data=[{"polygon": circle}],
    get_polygon="polygon",
    get_fill_color=[255, 0, 0, 50],
    stroked=True,
    get_line_color=[255, 0, 0],
    get_line_width=2
))

# Render map
deck = pdk.Deck(layers=layers, initial_view_state=view, map_style="light")
st.pydeck_chart(deck)

# --- Alerts ---------------------------------------------------------------
if track_sun and trails:
    for tr in trails:
        for lon, lat in tr["path"]:
            if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
                st.error(f"🚨 Shadow of {tr['callsign']} over home!")
                send_pushover("✈️ Shadow Alert", f"{tr['callsign']} shadow at home")
                break

# --- Test buttons ---------------------------------------------------------
if test_alert:
    st.success("Test alert triggered")
if test_pushover:
    send_pushover("✈️ Test", "This is a test Pushover message")
    st.info("Test Pushover sent")
