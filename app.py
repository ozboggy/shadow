import streamlit as st
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
from pyfr24 import FR24API, FR24AuthenticationError
import requests
import folium
from streamlit_folium import st_folium
from math import radians, sin, cos, asin, sqrt, tan, atan2, degrees
from pysolar.solar import get_altitude as solar_altitude, get_azimuth as solar_azimuth
try:
    import ephem
    MOON_AVAILABLE = True
except ImportError:
    MOON_AVAILABLE = False
import csv
import pandas as pd
import pathlib

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

# Credentials (set these in your .env file)
FR24_API_KEY = os.getenv("FLIGHTRADAR_API_KEY")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

if not FR24_API_KEY:
    st.error("FLIGHTRADAR_API_KEY not found in environment. Please set it in your .env file.")
    st.stop()

# Home coordinates
default_home = (-33.7608288, 150.9713948)
HOME_LAT, HOME_LON = default_home

# Forecast settings
FORECAST_DURATION_MINUTES = 5
FORECAST_INTERVAL_SECONDS = 30

# Log file
LOG_FILE = os.path.join(os.path.dirname(__file__), "shadow_alerts.csv")
if not pathlib.Path(LOG_FILE).exists():
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_utc", "callsign", "time_to_pass_sec", "shadow_lat", "shadow_lon"])

# Sidebar UI
st.sidebar.title("☀️🌙 Aircraft Shadow Forecast Settings")
selected_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
selected_time = st.sidebar.time_input("Time (UTC)", value=datetime.utcnow().time().replace(second=0, microsecond=0))
t0 = datetime.combine(selected_date, selected_time).replace(tzinfo=timezone.utc)
# Shadow toggles
show_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
if MOON_AVAILABLE:
    show_moon = st.sidebar.checkbox("Show Moon Shadows", value=False)
else:
    show_moon = False
    st.sidebar.markdown("**Moon shadows unavailable:** install `pip install ephem` to enable")
# Alert and search settings
alert_radius = st.sidebar.slider("Alert Radius (m)", min_value=10, max_value=200, value=50, step=5)
radius_km = st.sidebar.slider("Flight Search Radius (km)", min_value=10, max_value=200, value=50, step=10)
zoom = st.sidebar.slider("Map Zoom Level", min_value=6, max_value=15, value=12)

# Compute bounding box (degrees) from radius
delta = radius_km / 111.0  # approx degrees per km
bounds = f"{HOME_LAT-delta},{HOME_LON-delta},{HOME_LAT+delta},{HOME_LON+delta}"

# Initialize Folium Map
m = folium.Map(location=[HOME_LAT, HOME_LON], zoom_start=zoom)
folium.Marker([HOME_LAT, HOME_LON], icon=folium.Icon(color="red", icon="home", prefix="fa"), popup="Home").add_to(m)

# Utility functions
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

def move_position(lat, lon, bearing_deg, distance_m):
    R = 6371000
    bearing = radians(bearing_deg)
    lat1 = radians(lat)
    lon1 = radians(lon)
    d = distance_m / R
    lat2 = sin(lat1)*cos(d) + cos(lat1)*sin(d)*cos(bearing)
    lat2 = asin(lat2)
    lon2 = lon1 + atan2(sin(bearing)*sin(d)*cos(lat1), cos(d) - sin(lat1)*sin(lat2))
    return degrees(lat2), degrees(lon2)

# Fetch live flights via FlightRadar24 API
api = FR24API(FR24_API_KEY)
try:
    positions = api.get_flight_positions_light(bounds)
except FR24AuthenticationError as e:
    st.error(f"FlightRadar24 authentication failed: {e}")
    st.stop()
except Exception as e:
    st.error(f"Error fetching FlightRadar24 data: {e}")
    st.stop()

# Show number of flights found
st.sidebar.markdown(f"**Flights found:** {len(positions)} within {radius_km} km")
if not positions:
    st.warning(f"No flights found within {radius_km} km of home. Try increasing the search radius.")

alerts = []

# Process each aircraft
for pos in positions:
    lat = getattr(pos, 'latitude', None)
    lon = getattr(pos, 'longitude', None)
    alt = getattr(pos, 'altitude', None)  # in feet
    speed = getattr(pos, 'speed', None)   # in knots
    track = getattr(pos, 'track', None) or getattr(pos, 'heading', None)
    callsign = getattr(pos, 'callsign', '')
    if None in (lat, lon, alt, speed, track):
        continue
    # Convert units
    alt_m = alt * 0.3048
    speed_mps = speed * 0.514444
    trail = []
    alerted = False

    for t in range(0, FORECAST_DURATION_MINUTES*60+1, FORECAST_INTERVAL_SECONDS):
        dist = speed_mps * t
        f_lat, f_lon = move_position(lat, lon, track, dist)
        # Sun shadow
        if show_sun:
            sun_alt = solar_altitude(f_lat, f_lon, t0 + timedelta(seconds=t))
            if sun_alt > 0:
                sun_az = solar_azimuth(f_lat, f_lon, t0 + timedelta(seconds=t))
                shadow_dist = alt_m / tan(radians(sun_alt))
                sh_lat, sh_lon = move_position(f_lat, f_lon, sun_az+180, shadow_dist)
                trail.append(((sh_lat, sh_lon), 'sun'))
                if not alerted and haversine(sh_lat, sh_lon, HOME_LAT, HOME_LON) <= alert_radius:
                    alerts.append((callsign.strip(), t, sh_lat, sh_lon))
                    alerted = True
        # Moon shadow
        if show_moon and MOON_AVAILABLE:
            obs = ephem.Observer()
            obs.lat, obs.lon = str(f_lat), str(f_lon)
            obs.date = (t0 + timedelta(seconds=t)).strftime('%Y/%m/%d %H:%M:%S')
            mobj = ephem.Moon(obs)
            moon_alt = degrees(mobj.alt)
            if moon_alt > 0:
                moon_az = degrees(mobj.az)
                shadow_dist = alt_m / tan(radians(moon_alt))
                sh_lat, sh_lon = move_position(f_lat, f_lon, moon_az+180, shadow_dist)
                trail.append(((sh_lat, sh_lon), 'moon'))
                if not alerted and haversine(sh_lat, sh_lon, HOME_LAT, HOME_LON) <= alert_radius:
