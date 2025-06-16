import os
import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone
import math
from pysolar.solar import get_altitude, get_azimuth
from math import radians, cos, sin, asin, sqrt
import csv
import pandas as pd
import plotly.express as px

# FlightRadar24 support
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

# Pushover config
PUSHOVER_API_TOKEN = "adxez5u3zqqxyta3pdvdi5sd"
PUSHOVER_USER_KEY = "u1i3fvca8o3ztrma829s21nvy"

def send_pushover(title: str, message: str):
    try:
        url = "https://api.pushover.net/1/messages.json"
        requests.post(url, data={
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message
        })
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# Streamlit UI
st.set_page_config(layout="wide")
st.markdown("<meta http-equiv='refresh' content='30'>", unsafe_allow_html=True)
st.title("✈️ Aircraft Shadow Forecast")

# Time selector
st.sidebar.header("Select Time")
selected_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
selected_time_only = st.sidebar.time_input(
    "Time (UTC)",
    value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute)
)
selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)

# Data source selector
data_source = st.sidebar.selectbox("Data Source", ("OpenSky", "FlightRadar24"))

# Constants
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
    d = distance_m
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1)*math.cos(d/R) +
        math.cos(lat1)*math.sin(d/R)*math.cos(heading_rad)
    )
    lon2 = lon1 + math.atan2(
        math.sin(heading_rad)*math.sin(d/R)*math.cos(lat1),
        math.cos(d/R)-math.sin(lat1)*math.sin(lat2)
    )
    return math.degrees(lat2), math.degrees(lon2)

# Prepare log file
log_file = "alert_log.csv"
if not os.path.exists(log_file):
    with open(log_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon"])

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
else:
    if not FR24_API_KEY:
        st.error("Please set your FLIGHTRADAR_API_KEY environment variable.")
    else:
        try:
            fr_api = FR24API(FR24_API_KEY)
            bounds = f"{south},{west},{north},{east}"
            # Correct method for live positions in a bbox
            resp = fr_api.get_flight_positions_light(bounds)
            data_list = resp.get("data", resp)
            for p in data_list:
                lat = p.get("lat"); lon = p.get("lon")
                if lat is None or lon is None:
                    continue
                callsign = p.get("flight", p.get("callsign", "N/A")).strip()
                velocity = p.get("speed", 0)
                heading  = p.get("track", p.get("heading", 0))
                alt      = p.get("altitude", 0)
                # normalize to OpenSky-style tuple
                aircraft_states.append([
                    None, callsign, None, None, None,
                    lon, lat, None, velocity, heading,
                    alt, None, None, None, None
                ])
        except Exception as e:
            st.error(f"Error fetching FlightRadar24 data: {e}")

# … the rest of your map, prediction loops, alert logic, etc. …
