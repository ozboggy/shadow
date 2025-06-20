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

# Pushover configuration
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

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Constants
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5

# Sidebar controls
with st.sidebar:
    st.header("Map Options")
    radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun = st.checkbox("Show Sun Shadows", True)
    alert_width = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

st.title("✈️ Aircraft Shadow Tracker (ADS-B Exchange)")
time_now = datetime.now(timezone.utc)

# Fetch ADS-B Exchange data
aircraft_list = []
api_key = os.getenv("RAPIDAPI_KEY")
adsb = []
if api_key:
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
    }
    try:
        r2 = requests.get(url, headers=headers)
        r2.raise_for_status()
        adsb = r2.json().get("ac", [])
    except Exception:
        adsb = []

for ac in adsb:
    try:
        lat = float(ac.get("lat"))
        lon = float(ac.get("lon"))
    except (TypeError, ValueError):
        continue
    cs = str(ac.get("flight") or ac.get("hex") or "").strip()
    try:
        alt_val = float(ac.get("alt_geo") or ac.get("alt_baro") or 0.0)
    except (TypeError, ValueError):
        alt_val = 0.0
    try:
        heading = float(ac.get("track") or ac.get("trk") or 0.0)
    except (TypeError, ValueError):
        heading = 0.0
    aircraft_list.append({
        "lat": lat,
        "lon": lon,
        "alt": alt_val,
        "callsign": cs,
        "angle": heading
    })

# Build DataFrame
df_ac = pd.DataFrame(aircraft_list)
if df_ac.empty:
    st.warning("No aircraft data available.")
else:
    df_ac['alt'] = pd.to_numeric(df_ac['alt'], errors='coerce').fillna(0)

# Forecast shadow trails
trails = []
if track_sun and not df_ac.empty:
    for _, row in df_ac.iterrows():
        path = []
        for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
            ft = time_now + timedelta(seconds=i)
            sun_alt = get_altitude(row['lat'], row['lon'], ft)
            sun_az = get_azimuth(row['lat'], row['lon'], ft)
            if sun_alt > 0:
                dist = row['alt'] / math.tan(math.radians(sun_alt))
                sh_lat = row['lat'] + (dist/111111) * math.cos(math.radians(sun_az + 180))
                sh_lon = row['lon'] + (dist/(111111 * math.cos(math.radians(row['lat'])))) * math.sin(math.radians(sun_az + 180))
                path.append((sh_lon, sh_lat))
        if path:
            trails.append({"path": path, "callsign": row['callsign']})

# Prepare IconLayer data
icon_df = pd.DataFrame([])
if not df_ac.empty:
    icon_data = []
    for _, row in df_ac.iterrows():
        icon_data.append({
            "lon": row["lon"],
            "lat": row["lat"],
            "icon": {
                "url": "https://img.icons8.com/ios-filled/50/000000/airplane-take-off.png",
                "width": 128,
                "height": 128,
                "anchorX": 64,
                "anchorY": 64
            },
            "angle": row["angle"]
        })
    icon_df = pd.DataFrame(icon_data)

# Build Deck.gl layers
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []

if not icon_df.empty:
    layers.append(pdk.Layer(
        "IconLayer",
        icon_df,
        get_icon="icon",
        get_position=["lon", "lat"],
        get_angle="angle",
        size_scale=15,
        pickable=True
    ))

if track_sun and trails:
    df_trails = pd.DataFrame(trails)
    layers.append(pdk.Layer(
        "PathLayer",
        df_trails,
        get_path="path",
        get_color=[0, 0, 0, 150],
        width_scale=10,
        width_min_pixels=2
    ))

# Home marker
layers.append(pdk.Layer(
    "ScatterplotLayer",
    pd.DataFrame([{"lat": CENTER_LAT, "lon": CENTER_LON}]),
    get_position=["lon", "lat"],
    get_color=[255, 0, 0, 200],
    get_radius=400
))

# Render map
deck = pdk.Deck(layers=layers, initial_view_state=view, map_style="light")
st.pydeck_chart(deck, use_container_width=True)

# Alerts for shadows over home
if track_sun and trails:
    for tr in trails:
        for lon, lat in tr["path"]:
            if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
                st.error(f"🚨 Shadow of {tr['callsign']} over home!")
                send_pushover("✈️ Shadow Alert", f"{tr['callsign']} shadow at home")
                break

# Test buttons
if test_alert:
    st.success("Test alert triggered")
if test_pushover:
    st.info("Test Pushover sent")
