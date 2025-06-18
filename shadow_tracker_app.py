import streamlit as st
st.set_page_config(layout="wide")  # MUST be first Streamlit command

import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
import csv
import os
from dotenv import load_dotenv
load_dotenv()
import pandas as pd
import plotly.express as px
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth
from skyfield.api import load, Topos
from pyfr24 import FR24API
import base64
import requests

# Load ephemeris for moon calculations
eph = load('de421.bsp')
moon = eph['moon']
earth = eph['earth']
ts = load.timescale()

# Pushover setup
PUSHOVER_USER_KEY = "usasa4y2iuvz75krztrma829s21nvy"
PUSHOVER_API_TOKEN = "adxez5u3zqqxyta3pdvdi5sdvwovxv"

def send_pushover(title, message):
    try:
        url = "https://api.pushover.net/1/messages.json"
        payload = {
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message
        }
        requests.post(url, data=payload)
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# Constants
DEFAULT_TARGET_LAT = -33.7602563
DEFAULT_TARGET_LON = 150.9717434
DEFAULT_ALERT_RADIUS_METERS = 50
DEFAULT_RADIUS_KM = 20
DEFAULT_FORECAST_INTERVAL_SECONDS = 30
DEFAULT_FORECAST_DURATION_MINUTES = 5
DEFAULT_HOME_CENTER = [-33.76025, 150.9711666]
DEFAULT_SHADOW_WIDTH = 5
DEFAULT_ZOOM = 10

# Sidebar settings
map_theme = st.sidebar.selectbox("Map Theme", ["CartoDB Positron", "CartoDB Dark_Matter", "OpenStreetMap", "Stamen Toner", "Stamen Terrain", "Stamen Watercolor", "Esri WorldImagery", "CartoDB Voyager"], index=0)
override_trails = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", value=False)
show_debug = st.sidebar.checkbox("Show Aircraft Debug", value=False)
source_choice = st.sidebar.selectbox("Data Source", ["ADS-B Exchange", "OpenSky"], index=0)
track_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", value=True)
RADIUS_KM = st.sidebar.slider("Aircraft Search Radius (km)", 5, 100, DEFAULT_RADIUS_KM)
ALERT_RADIUS_METERS = st.sidebar.slider("Alert Radius (meters)", 10, 500, DEFAULT_ALERT_RADIUS_METERS)
zoom = st.sidebar.slider("Map Zoom Level", 5, 18, DEFAULT_ZOOM)
shadow_width = st.sidebar.slider("Shadow Line Width", 1, 10, DEFAULT_SHADOW_WIDTH)

# Static time setup (prevents re-runs on refresh)
if "selected_time" not in st.session_state:
    selected_date = datetime.utcnow().date()
    selected_time_only = dt_time(datetime.utcnow().hour, datetime.utcnow().minute)
    st.session_state.selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)
selected_time = st.session_state.selected_time

# Logging
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon", "Source"])

st.title("✈️ Aircraft Shadow Tracker")

if st.sidebar.button("🔔 Test Pushover Alert"):
    send_pushover("✅ Test Alert", "This is a test notification from the Shadow Tracker App")
    st.sidebar.success("Test notification sent!")

# Setup map
center = DEFAULT_HOME_CENTER
fmap = folium.Map(location=center, zoom_start=zoom, control_scale=True, tiles=None, prefer_canvas=True)

# Add selectable tile layers
folium.TileLayer("CartoDB Positron", name="CartoDB Positron").add_to(fmap)
folium.TileLayer("CartoDB Dark_Matter", name="CartoDB Dark_Matter").add_to(fmap)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(fmap)
folium.TileLayer("Stamen Toner", name="Stamen Toner", attr="Map tiles by Stamen Design, under CC BY 3.0. Data by OpenStreetMap, under ODbL.").add_to(fmap)
folium.TileLayer("Stamen Terrain", name="Stamen Terrain", attr="Map tiles by Stamen Design, under CC BY 3.0. Data by OpenStreetMap, under ODbL.").add_to(fmap)
folium.TileLayer("Stamen Watercolor", name="Stamen Watercolor", attr="Map tiles by Stamen Design, under CC BY 3.0. Data by OpenStreetMap, under ODbL.").add_to(fmap)
folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/World_Imagery/MapServer/tile/{z}/{y}/{x}", name="Esri WorldImagery", attr="Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community").add_to(fmap)
folium.TileLayer("CartoDB Voyager", name="CartoDB Voyager").add_to(fmap)

folium.LayerControl(position='topright', collapsed=False).add_to(fmap)

# Render the map
st_folium(fmap, width=1200, height=800)
