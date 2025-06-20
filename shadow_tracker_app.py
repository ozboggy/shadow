import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
# Auto-refresh every second
from streamlit_autorefresh import st_autorefresh
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except Exception:
    pass  # ignore duplicate key errors

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
    data_source = st.selectbox("Data Source", ["OpenSky", "ADS-B Exchange"], index=0)
    radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    alert_radius_m = st.slider("Shadow Alert Radius (m)", 1, 10000, 50)
    track_sun = st.checkbox("Show Sun Shadows", True)
    track_moon = st.checkbox("Show Moon Shadows", False)
    override_trails = st.checkbox("Show Trails Regardless of Sun/Moon", False)
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

# Current UTC time
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
        r = requests.get(url)
        r.raise_for_status()
        states = r.json().get("states", [])
    except:
        states = []
    for s in states:
        if len(s) < 11:
            continue
        cs = (s[1] or "").strip() or s[0]
        lat, lon = s[6], s[5]
        alt = s[13] or s[7] or 0.0  # use geo altitude if available, else baro
        aircraft_list.append({"latitude": lat, "longitude": lon, "altitude": alt, "callsign": cs.strip()})
