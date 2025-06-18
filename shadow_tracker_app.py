import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
from pysolar.solar import get_altitude, get_azimuth
import csv
import os
import pandas as pd
import plotly.express as px

# ---------------- Pushover setup ----------------
PUSHOVER_USER_KEY = "usasa4y2iuvz75krztrma829s21nvy"
PUSHOVER_API_TOKEN = "adxez5u3zqqxyta3pdvdi5sdvwovxv"

def send_pushover(title, message, user_key, api_token):
    try:
        url = "https://api.pushover.net/1/messages.json"
        payload = {"token": api_token, "user": user_key, "title": title, "message": message}
        requests.post(url, data=payload)
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# -------------- Streamlit Page Config -------------
st.set_page_config(layout="wide")
st.markdown("<meta http-equiv='refresh' content='30'>", unsafe_allow_html=True)
st.title("✈️ Aircraft Shadow Forecast")

# ---------------- Sidebar Inputs ------------------
st.sidebar.header("Select Time (UTC)")
selected_date = st.sidebar.date_input("Date", value=datetime.utcnow().date())
selected_time_only = st.sidebar.time_input("Time", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)

# Default settings
DEFAULT_RADIUS_KM = 20
DEFAULT_ZOOM = 12
DEFAULT_SHADOW_WIDTH = 2

st.sidebar.header("Map & Alert Settings")
# Map zoom level
zoom_level = st.sidebar.slider("Map Zoom Level", min_value=1, max_value=18, value=st.session_state.get("zoom", DEFAULT_ZOOM))
# Search radius around home (km)
search_radius_km = st.sidebar.slider("Search Radius (km)", min_value=1, max_value=100, value=DEFAULT_RADIUS_KM)
# Shadow path line width
shadow_width = st.sidebar.slider("Shadow Path Width", min_value=1, max_value=10, value=DEFAULT_SHADOW_WIDTH)
# Toggle onscreen alert
enable_onscreen_alert = st.sidebar.checkbox("Enable Onscreen Alert", value=True)
# Debug mode toggle
debug_mode = st.sidebar.checkbox("Debug Mode", value=False)
# Pushover test
if st.sidebar.button("Send Pushover Test"):
    send_pushover("✈️ Test Alert", "This is a Pushover test notification.", PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN)
    st.sidebar.success("Pushover test sent!")

# ---------------- Constants ----------------
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
# Home/target location
HOME_LAT = -33.7597655
HOME_LON = 150.9723678
TARGET_LAT = HOME_LAT
TARGET_LON = HOME_LON
# Apply user settings
RADIUS_KM = search_radius_km

# ---------------- Utils Functions ---------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def move_position(lat, lon, heading_deg, distance_m):
    R = 6371000
    heading_rad = math.radians(heading_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    d = distance_m
    lat2 = math.asin(math.sin(lat1)*math.cos(d/R) + math.cos(lat1)*math.sin(d/R)*math.cos(heading_rad))
    lon2 = lon1 + math.atan2(math.sin(heading_rad)*math.sin(d/R)*math.cos(lat1), math.cos(d/R)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

# ---------------- Logging setup ----------------
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon"])

# ---------------- Fetch Aircraft Data ------------
north, south, west, east = -33.0, -34.5, 150.0, 151.5
url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
try:
    r = requests.get(url)
    r.raise_for_status()
    data = r.json()
except Exception as e:
    st.error(f"Error fetching OpenSky data: {e}")
    data = {}
aircraft_states = data.get("states", [])

# ---------------- Initialize Map ----------------
st.session_state.zoom = zoom_level
fmap = folium.Map(location=[HOME_LAT, HOME_LON], zoom_start=zoom_level)
marker_cluster = MarkerCluster().add_to(fmap)
# Mark target
folium.Marker((TARGET_LAT, TARGET_LON), icon=folium.Icon(color="red"), popup="Target/Home").add_to(fmap)

alerts_triggered = []
# Filter by radius
filtered_states = []
for ac in aircraft_states:
    try:
        _, callsign, _, _, _, lon, lat, *_ = ac
        if lat and lon:
            if haversine(lat, lon, HOME_LAT, HOME_LON) / 1000 <= RADIUS_KM:
                filtered_states.append(ac)
    except:
        continue

# ---------------- Process each aircraft -------------
for ac in filtered_states:
    try:
        icao24, callsign, _, _, _, lon, lat, baro_alt, _, velocity, heading, _, _, geo_alt, *_ = ac
        if None in (lat, lon, velocity, heading):
            continue
        alt = geo_alt or 0
        callsign = callsign.strip() if callsign else "N/A"
        trail = []
        shadow_alerted = False
        for i in range(0, FORECAST_DURATION_MINUTES * 60 + 1, FORECAST_INTERVAL_SECONDS):
            future_time = selected_time + timedelta(seconds=i)
            dist_moved = velocity * i
            future_lat, future_lon = move_position(lat, lon, heading, dist_moved)
            sun_alt = get_altitude(future_lat, future_lon, future_time)
            sun_az = get_azimuth(future_lat, future_lon, future_time)
            if debug_mode:
                st.sidebar.write(f"Debug: {callsign} @ t+{i}s -> pos=({
