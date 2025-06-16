
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
PUSHOVER_USER_KEY = "your_user_key"
PUSHOVER_API_TOKEN = "your_api_token"

def send_pushover(title, message, user_key, api_token):
    try:
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

    # Streamlit UI
st.set_page_config(layout="wide")


config_file = "map_config.json"
default_center = [-33.7608864, 150.9709575]
default_zoom = 14

# Load saved zoom/center if available
if os.path.exists(config_file):
try:
try:
except Exception as e:
    st.error(f"Error fetching OpenSky data: {e}")
    data = {}

if not isinstance(data, dict):
    data = {}

aircraft_states = data.get("states", [])

if zoom_lock:
    st.session_state.zoom = 12
    st.session_state.center = [-33.7608864, 150.9709575]


try:
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
try:
try:
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



map_data = st_folium(fmap, width=1000, height=700)

if map_data and "zoom" in map_data and "center" in map_data:
    if not zoom_lock:
        st.session_state.zoom = map_data["zoom"]
        st.session_state.center = map_data["center"]
    with open(config_file, "w") as f:
try:
    json.dump({"zoom": st.session_state.zoom, "center": st.session_state.center}, f)
except Exception as e:
        st.warning(f"Failed to save map state: {e}")

    st.session_state.zoom = map_data["zoom"]
    st.session_state.center = map_data["center"]