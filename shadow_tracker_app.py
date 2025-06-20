import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth

# Pushover configuration
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        st.warning("Pushover credentials not set in environment.")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# Log file setup
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        f.write("Time UTC,Callsign,Time Until Alert (sec),Lat,Lon,Source\n")

# Defaults
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
DEFAULT_ZOOM = 11

# Sidebar controls
with st.sidebar:
    st.header("Map Options")
    tile_style = st.selectbox("Tile Style", ["OpenStreetMap", "CartoDB positron"], index=0)
    data_source = st.selectbox("Data Source", ["OpenSky", "ADS-B Exchange"], index=0)
    radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    st.markdown(f"**Search Radius:** {radius_km} km")
    alert_radius_m = st.slider("Shadow Alert Radius (m)", 1, 10000, 50)
    st.markdown(f"**Shadow Alert Radius:** {alert_radius_m} m")
    track_sun = st.checkbox("Show Sun Shadows", True)
    track_moon = st.checkbox("Show Moon Shadows", False)
    override_trails = st.checkbox("Show Trails Regardless of Sun/Moon", False)
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")
    st.header("Map Settings")
    zoom_level = st.slider("Initial Zoom Level", 1, 18, DEFAULT_ZOOM)
    map_width = st.number_input("Width (px)", 400, 2000, 600)
    map_height = st.number_input("Height (px)", 300, 1500, 600)
    st.markdown("---")
    st.markdown("### 📥 Download Log")
    if os.path.exists(log_path):
        with open(log_path, "rb") as f:
            st.download_button("Download alert_log.csv", f, file_name="alert_log.csv", mime="text/csv")
        df_log = pd.read_csv(log_path)
        if not df_log.empty:
            df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
            st.markdown("### 🕑 Recent Alerts")
            st.dataframe(
                df_log[['Time UTC', 'Callsign', 'Time Until Alert (sec)']]
                    .sort_values('Time UTC', ascending=False)
                    .head(5)
            )

# Auto-refresh every 30 seconds to update aircraft positions
from streamlit_autorefresh import st_autorefresh
# interval in milliseconds
st_autorefresh(interval=1_000, key="datarefresh")  # refresh every 10 seconds

# Current time
selected_time = datetime.utcnow().replace(tzinfo=timezone.utc)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

# Fetch aircraft data
aircraft_list = []
if data_source == "OpenSky":
    dr = radius_km / 111.0
    south, north = CENTER_LAT - dr, CENTER_LAT + dr
    dlon = dr / math.cos(math.radians(CENTER_LAT))
    west, east = CENTER_LON - dlon, CENTER_LON + dlon
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url); r.raise_for_status(); states = r.json().get("states", [])
    except:
        states = []
    for s in states:
        if len(s) < 11: continue
        cs = s[1].strip() if s[1] else s[0]
        lat, lon = s[6], s[5]
        baro = s[7] or 0.0
        vel = s[9] or 0.0
        hdg = s[10] or 0.0
        aircraft_list.append({"lat": lat, "lon": lon, "callsign": cs})
elif data_source == "ADS-B Exchange":
    api_key = os.getenv("RAPIDAPI_KEY")
    adsb = []
    if api_key:
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
        try:
            r2 = requests.get(url, headers=headers); r2.raise_for_status(); adsb = r2.json().get("ac", [])
        except:
            adsb = []
    for ac in adsb:
        try:
            lat = float(ac.get("lat")); lon = float(ac.get("lon"))
        except:
            continue
        cs = ac.get("flight") or ac.get("hex")
        aircraft_list.append({"lat": lat, "lon": lon, "callsign": cs.strip() if cs else None})

# Build DataFrame for Pydeck
df_ac = pd.DataFrame(aircraft_list)

# Simple map display using Streamlit's built-in st.map
# This will show aircraft positions on an OpenStreetMap background without flicker
if not df_ac.empty:
    # st.map expects columns 'latitude' and 'longitude'
    df_map = df_ac.rename(columns={"lat": "latitude", "lon": "longitude"})
    st.map(df_map[['latitude', 'longitude']])
else:
    st.warning("No aircraft data available")

# Continue to Test buttons
if test_alert:
    st.success("Test alert triggered")
    send_pushover("✈️ Test Alert", "This is a test shadow alert.")
if test_pushover:
    st.info("Sending test Pushover notification...")
    send_pushover("✈️ Test Push", "This is a test shadow alert.")
