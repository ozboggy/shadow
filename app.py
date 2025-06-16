import os
from dotenv import load_dotenv
load_dotenv()
USERNAME = os.getenv('OPENSKY_USERNAME')
PASSWORD = os.getenv('OPENSKY_PASSWORD')

import requests
url = "https://opensky-network.org/api/states/all"
r = requests.get(url, auth=(USERNAME, PASSWORD))
data = r.json()
print(data)

import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
from pysolar.solar import get_altitude, get_azimuth

from math import radians, cos, sin, asin, sqrt
import csv
import os
import pandas as pd
import plotly.express as px

# Pushover setup
PUSHOVER_USER_KEY = "usasa4y2iuvz75krztrma829s21nvy"
PUSHOVER_API_TOKEN = "adxez5u3zqqxyta3pdvdi5sdvwovxv"

def send_pushover(title, message, user_key, api_token):
    try:
        url = "https://api.pushover.net/1/messages.json"
        payload = {
            "token": api_token,
            "user": user_key,
            "title": title,
            "message": message
        }
        requests.post(url, data=payload)
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# Streamlit UI
st.set_page_config(layout="wide")
st.markdown("<meta http-equiv='refresh' content='30'>", unsafe_allow_html=True)
st.title("✈️ Aircraft Shadow Forecast")

st.sidebar.header("Select Time")
selected_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
selected_time_only = st.sidebar.time_input("Time (UTC)", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)

# Constants
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
TARGET_LAT = -33.7603831919607
TARGET_LON = 150.971709164045
ALERT_RADIUS_METERS = 50
HOME_LAT = -33.7603831919607
HOME_LON = 150.971709164045
RADIUS_KM = 20

# Utils
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

def move_position(lat, lon, heading_deg, distance_m):
    R = 6371000
    heading_rad = math.radians(heading_deg)
    d = distance_m
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1)*math.cos(d/R) + math.cos(lat1)*math.sin(d/R)*math.cos(heading_rad))
    lon2 = lon1 + math.atan2(math.sin(heading_rad)*math.sin(d/R)*math.cos(lat1), math.cos(d/R)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

# Logging
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon"])

# Fetch aircraft
north, south, west, east = -33.0, -34.5, 150.0, 151.5
url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
try:
import os
from dotenv import load_dotenv
load_dotenv()
USERNAME = os.getenv('OPENSKY_USERNAME')
PASSWORD = os.getenv('OPENSKY_PASSWORD')

import requests
    r = requests.get(url, auth=(USERNAME, PASSWORD))
    r.raise_for_status()
    data = r.json()
except Exception as e:
    st.error(f"Error fetching OpenSky data: {e}")
    data = {}

aircraft_states = data.get("states", [])

if "zoom" not in st.session_state:
    st.session_state.zoom = 12
if "center" not in st.session_state:
    st.session_state.center = [(north + south)/2, (east + west)/2]


try:
    location_center = [float(x) for x in st.session_state.center]
except Exception:
    location_center = [(north + south)/2, (east + west)/2]
    st.session_state.center = location_center

fmap = folium.Map(location=location_center, zoom_start=st.session_state.zoom)


marker_cluster = MarkerCluster().add_to(fmap)
folium.Marker((TARGET_LAT, TARGET_LON), icon=folium.Icon(color="red"), popup="Target").add_to(fmap)

alerts_triggered = []

# Filter aircraft within radius
filtered_states = []
for ac in aircraft_states:
    try:
        _, _, _, _, _, lon, lat, *_ = ac
        if lat and lon:
            if haversine(lat, lon, HOME_LAT, HOME_LON) / 1000 <= RADIUS_KM:
                filtered_states.append(ac)
    except:
        continue

# Process each aircraft
for ac in filtered_states:
    try:
        icao24, callsign, _, _, _, lon, lat, baro_altitude, _, velocity, heading, _, _, geo_altitude, *_ = ac
        if None in (lat, lon, velocity, heading):
            continue
        alt = geo_altitude or 0
        callsign = callsign.strip() if callsign else "N/A"
        trail = []
        shadow_alerted = False

        for i in range(0, FORECAST_DURATION_MINUTES * 60 + 1, FORECAST_INTERVAL_SECONDS):
            future_time = selected_time + timedelta(seconds=i)
            dist_moved = velocity * i
            future_lat, future_lon = move_position(lat, lon, heading, dist_moved)
            sun_alt = get_altitude(future_lat, future_lon, future_time)
            sun_az = get_azimuth(future_lat, future_lon, future_time)
            if sun_alt > 0 and alt > 0:
                shadow_dist = alt / math.tan(math.radians(sun_alt))
                shadow_lat = future_lat + (shadow_dist / 111111) * math.cos(math.radians(sun_az + 180))
                shadow_lon = future_lon + (shadow_dist / (111111 * math.cos(math.radians(future_lat)))) * math.sin(math.radians(sun_az + 180))
                trail.append((shadow_lat, shadow_lon))

                if not shadow_alerted and haversine(shadow_lat, shadow_lon, TARGET_LAT, TARGET_LON) <= ALERT_RADIUS_METERS:
                    alerts_triggered.append((callsign, int(i), shadow_lat, shadow_lon))
                    with open(log_path, "a", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow([datetime.utcnow().isoformat(), callsign, int(i), shadow_lat, shadow_lon])
                    try:
                        send_pushover(
                            title="✈️ Shadow Alert",
                            message=f"{callsign} will pass over target in {int(i)} sec",
                            user_key=PUSHOVER_USER_KEY,
                            api_token=PUSHOVER_API_TOKEN
                        )
                    except Exception as e:
                        st.warning(f"Pushover failed: {e}")
                    shadow_alerted = True

        if trail:
            folium.PolyLine(trail, color="black", weight=2, opacity=0.7, dash_array="5,5",
                            tooltip=f"{callsign} (shadow)").add_to(fmap)
        folium.Marker((lat, lon), icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
                      popup=f"{callsign}\nAlt: {round(alt)}m").add_to(marker_cluster)
    except Exception as e:
        st.warning(f"⚠️ Error processing aircraft: {e}")

# Alert UI
if alerts_triggered:
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
    st.markdown("""
    <script>
    if (Notification.permission === 'granted') {
        new Notification("✈️ Shadow Alert", { body: "Aircraft shadow passing over target!" });
    } else {
        Notification.requestPermission().then(p => {
            if (p === 'granted') {
                new Notification("✈️ Shadow Alert", { body: "Aircraft shadow passing over target!" });
            }
        });
    }
    </script>
    """, unsafe_allow_html=True)
    for cs, t, _, _ in alerts_triggered:
        st.write(f"✈️ {cs} — in approx. {t} seconds")
else:
    st.success("✅ No forecast shadow paths intersect target area.")

# Logs
if os.path.exists(log_path):
    st.sidebar.markdown("### 📥 Download Log")
    with open(log_path, "rb") as f:
        st.sidebar.download_button("Download alert_log.csv", f, file_name="alert_log.csv", mime="text/csv")

    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        st.markdown("### 📊 Recent Alerts")
        st.dataframe(df_log.tail(10))

        fig = px.scatter(df_log, x="Time UTC", y="Callsign", size="Time Until Alert (sec)",
                         hover_data=["Lat", "Lon"], title="Shadow Alerts Over Time")
        st.plotly_chart(fig, use_container_width=True)


map_data = st_folium(fmap, width=2000, height=1400)
if map_data and "zoom" in map_data and "center" in map_data:
    st.session_state.zoom = map_data["zoom"]
    st.session_state.center = map_data["center"]

