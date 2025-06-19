import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import folium
from folium.features import DivIcon
from streamlit_folium import st_folium
from datetime import datetime, timezone, timedelta
import math
import requests
import pandas as pd
import plotly.express as px
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth

# Pushover configuration (set these in your .env)
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
DEFAULT_RADIUS_KM = 10  # default search radius now 10 km
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
DEFAULT_SHADOW_WIDTH = 2
DEFAULT_ZOOM = 11

# Sidebar
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

# Current UTC time
selected_time = datetime.utcnow().replace(tzinfo=timezone.utc)
# Alert History section above the main title
if os.path.exists(log_path):
    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        st.markdown("### 🖼 Previous Shadow Alert History")
        st.dataframe(
            df_log[['Time UTC', 'Callsign', 'Time Until Alert (sec)']]
                .sort_values('Time UTC', ascending=False)
                .head(10)
        )
        st.markdown("### 📊 Alert Timeline")
        fig_hist = px.scatter(
            df_log,
            x="Time UTC", y="Callsign",
            size="Time Until Alert (sec)",
            hover_data=["Lat", "Lon"],
            title="Historical Shadow Alerts Over Time"
        )
        st.plotly_chart(fig_hist, use_container_width=True)

# Main app title
st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")
