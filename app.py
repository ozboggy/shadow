import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
from pysolar.solar import get_altitude, get_azimuth
from math import radians, sin, cos, asin, sqrt
import csv
import os
import pandas as pd
import plotly.express as px
from pyfr24 import FR24API

# Load environment vars
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    st.warning("python-dotenv not installed; skipping .env loading.")

OPENSKY_USER = os.getenv("OPENSKY_USERNAME")
OPENSKY_PASS = os.getenv("OPENSKY_PASSWORD")
FR24_API_KEY = os.getenv("FLIGHTRADAR_API_KEY")

# Pushover setup
PUSHOVER_USER_KEY = "usasa4y2iuvz75krztrma829s21nvy"
PUSHOVER_API_TOKEN = "adxez5u3zqqxyta3pdvdi5sdvwovxv"

def send_pushover(title: str, message: str, user_key: str, api_token: str):
    try:
        url = "https://api.pushover.net/1/messages.json"
        requests.post(url, data={"token": api_token, "user": user_key, "title": title, "message": message})
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# Streamlit UI
st.set_page_config(layout="wide")
st.markdown("<meta http-equiv='refresh' content='30'>", unsafe_allow_html=True)
st.title("✈️ Aircraft Shadow Forecast")

st.sidebar.header("Select Time")
selected_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
selected_time_only = st.sidebar.time_input(
    "Time (UTC)",
    value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute)
)
selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)

# Data source selector (default to FlightRadar24)
data_source = st.sidebar.selectbox("Data Source", ("OpenSky", "FlightRadar24"), index=1)

# Constants
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
TARGET_LAT = -33.7603831919607
TARGET_LON = 150.971709164045
ALERT_RADIUS_METERS = 50
HOME_LAT = -33.7603831919607
HOME_LON = 150.971709164045
RADIUS_KM = 20

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

def move_position(lat, lon, heading_deg, distance_m):
    R = 6371000
    heading_rad = math.radians(heading_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        sin(lat1)*cos(distance_m/R) +
        cos(lat1)*sin(distance_m/R)*cos(heading_rad)
    )
    lon2 = lon1 + math.atan2(
        sin(heading_rad)*sin(distance_m/R)*cos(lat1),
        cos(distance_m/R)-sin(lat1)*sin(lat2)
    )
    return math.degrees(lat2), math.degrees(lon2)

# Logging setup
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon"])

# Initialize map session state
if "zoom" not in st.session_state:
    st.session_state.zoom = 12
if "center" not in st.session_state:
    st.session_state.center = [HOME_LAT, HOME_LON]

# Prepare map
try:
    location_center = [float(x) for x in st.session_state.center]
except:
    location_center = [HOME_LAT, HOME_LON]
    st.session_state.center = location_center

fmap = folium.Map(location=location_center, zoom_start=st.session_state.zoom)
marker_cluster = MarkerCluster().add_to(fmap)
folium.Marker((TARGET_LAT, TARGET_LON), icon=folium.Icon(color="red"), popup="Target").add_to(fmap)

# Fetch aircraft data
north, south, west, east = -33.0, -34.5, 150.0, 151.5
aircraft_states = []

if data_source == "OpenSky":
    url = (
        f"https://opensky-network.org/api/states/all"
        f"?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    )
    try:
        r = requests.get(url, auth=(OPENSKY_USER, OPENSKY_PASS))
        r.raise_for_status()
        aircraft_states = r.json().get("states", [])
    except Exception as e:
        st.error(f"Error fetching OpenSky data: {e}")
else:  # FlightRadar24
    if not FR24_API_KEY:
        st.error("Please set FLIGHTRADAR_API_KEY in your environment.")
    else:
        try:
            fr_api = FR24API(FR24_API_KEY)
            bounds = f"{south},{west},{north},{east}"
            resp = fr_api.get_flight_positions_light(bounds)

            # normalize into a list
            if isinstance(resp, dict):
                flights = resp.get("data", [])
            elif isinstance(resp, list):
                flights = resp
            else:
                flights = []

            # fallback to feed.js if empty
            if not flights:
                st.sidebar.warning("FR24API empty — falling back to feed.js")
                fr_url = "https://data-live.flightradar24.com/zones/fcgi/feed.js"
                params = {"bounds": bounds, "adsb": 1, "mlat": 1, "flarm": 1, "array": 1}
                r2 = requests.get(fr_url, params=params)
                r2.raise_for_status()
                raw = r2.json()
                flights = [v for k, v in raw.items() if k not in ("full_count", "version", "stats")]

            def safe_get(lst, idx, default=None):
                return lst[idx] if isinstance(lst, list) and idx < len(lst) else default

            for p in flights:
                lat = safe_get(p, 1)
                lon = safe_get(p, 2)
                if lat is None or lon is None:
                    continue
                velocity = safe_get(p, 4, 0) or 0
                heading  = safe_get(p, 3, 0) or 0
                alt = safe_get(p, 13)
                if alt is None:
                    alt = safe_get(p, 11, 0) or 0
                raw_cs = safe_get(p, -1, "")
                callsign = raw_cs.strip() or "N/A"
                aircraft_states.append([
                    None, callsign, None, None, None,
                    lon, lat, None, velocity, heading,
                    alt, None, None, None, None
                ])
        except Exception as e:
            st.error(f"Error fetching FlightRadar24 data: {e}")

# Process and display data (unchanged)...
# [The rest of your existing forecasting, mapping, and alert code follows here]
