import streamlit as st
# Must be first Streamlit command
st.set_page_config(layout="wide")

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

# Attempt to import pyfr24
try:
    from pyfr24 import FR24API
    HAS_FR24API = True
except ImportError:
    HAS_FR24API = False

# Load environment vars
try:
    from dotenv import load_dotenv
    load_dotenv()
    DOTENV_LOADED = True
except ImportError:
    DOTENV_LOADED = False

# Sidebar warnings after config
if not HAS_FR24API:
    st.sidebar.warning("pyfr24 not installed; using feed.js fallback for FlightRadar24 data.")
if not DOTENV_LOADED:
    st.sidebar.warning("python-dotenv not installed; skipping .env loading.")

OPENSKY_USER = os.getenv("OPENSKY_USERNAME")
OPENSKY_PASS = os.getenv("OPENSKY_PASSWORD")
FR24_API_KEY = os.getenv("FLIGHTRADAR_API_KEY")

# Pushover setup
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY", "")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN", "")

def send_pushover(title: str, message: str):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
    except Exception:
        pass

# Title and refresh
st.markdown("<meta http-equiv='refresh' content='30'>", unsafe_allow_html=True)
st.title("✈️ Aircraft Shadow Forecast")

# Sidebar controls
st.sidebar.header("Select Time")
selected_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
selected_time = st.sidebar.time_input("Time (UTC)", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(selected_date, selected_time).replace(tzinfo=timezone.utc)

data_source = st.sidebar.selectbox("Data Source", ("OpenSky", "FlightRadar24"), index=1)

# Constants
TARGET_LAT = -33.7603831919607
TARGET_LON = 150.971709164045
HOME_LAT = -33.7603831919607
HOME_LON = 150.971709164045
RADIUS_KM = 20
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
ALERT_RADIUS_METERS = 50

# Helpers
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1); dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2*R*asin(sqrt(a))

def move_position(lat, lon, heading_deg, distance_m):
    R = 6371000
    heading_rad = math.radians(heading_deg)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(sin(lat1)*cos(distance_m/R) + cos(lat1)*sin(distance_m/R)*cos(heading_rad))
    lon2 = lon1 + math.atan2(sin(heading_rad)*sin(distance_m/R)*cos(lat1),
                             cos(distance_m/R)-sin(lat1)*sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

# Setup log file
log_file = "alert_log.csv"
if not os.path.exists(log_file):
    with open(log_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC","Callsign","Time Until Alert (sec)","Lat","Lon"])

# Initialize map state
if "zoom" not in st.session_state: st.session_state.zoom = 12
if "center" not in st.session_state: st.session_state.center = [HOME_LAT, HOME_LON]

try:
    center = [float(x) for x in st.session_state.center]
except:
    center = [HOME_LAT, HOME_LON]
    st.session_state.center = center

fmap = folium.Map(location=center, zoom_start=st.session_state.zoom)
marker_cluster = MarkerCluster().add_to(fmap)
folium.Marker((TARGET_LAT, TARGET_LON), icon=folium.Icon(color="red"), popup="Target").add_to(fmap)

# Fetch aircraft data
north, south, west, east = -33.0, -34.5, 150.0, 151.5
aircraft_states = []

if data_source == "OpenSky":
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url, auth=(OPENSKY_USER, OPENSKY_PASS))
        r.raise_for_status()
        aircraft_states = r.json().get("states", [])
    except Exception as e:
        st.error(f"Error fetching OpenSky data: {e}")
else:
    # FlightRadar24 fetch with feed.js fallback
    flights = []
    if HAS_FR24API and FR24_API_KEY:
        try:
            api = FR24API(FR24_API_KEY)
            resp = api.get_flight_positions_light(f"{south},{west},{north},{east}")
            if isinstance(resp, dict):
                flights = resp.get("data", [])
            elif isinstance(resp, list):
                flights = resp
        except Exception:
            flights = []
    if not flights:
        try:
            r2 = requests.get(
                "https://data-live.flightradar24.com/zones/fcgi/feed.js",
                params={"bounds":f"{south},{west},{north},{east}","adsb":1,"mlat":1,"flarm":1,"array":1}
            )
            r2.raise_for_status()
            raw = r2.json()
            for k, v in raw.items():
                if k in ("full_count","version","stats"): continue
                if isinstance(v, list) and v:
                    flights.extend(v if isinstance(v[0], list) else [v])
        except Exception:
            pass
    def safe_get(lst, idx, default=None):
        return lst[idx] if isinstance(lst, list) and idx < len(lst) else default
    for p in flights:
        lat = safe_get(p, 1); lon = safe_get(p, 2)
        if lat is None or lon is None: continue
        vel = safe_get(p, 4, 0) or 0; hdg = safe_get(p, 3, 0) or 0
        alt = safe_get(p, 13); alt = alt if alt is not None else (safe_get(p, 11, 0) or 0)
        cs = safe_get(p, -1, "") or "N/A"
        aircraft_states.append([None, cs, None, None, None, lon, lat, None, vel, hdg, alt, None, None, None, None])

# The rest of your processing, mapping, alerts, and log download code...
# omitted for brevity
