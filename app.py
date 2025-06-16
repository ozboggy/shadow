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

def send_pushover(title, message, user_key, api_token):
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": api_token, "user": user_key, "title": title, "message": message}
        )
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# Streamlit UI setup
st.set_page_config(layout="wide")
st.markdown("<meta http-equiv='refresh' content='30'>", unsafe_allow_html=True)
st.title("✈️ Aircraft Shadow Forecast")

# Time selector (UTC)
st.sidebar.header("Select Time")
selected_date = st.sidebar.date_input("Date", value=datetime.utcnow().date())
selected_time = st.sidebar.time_input("Time", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_dt = datetime.combine(selected_date, selected_time).replace(tzinfo=timezone.utc)

# Data source selector (default FlightRadar24)
data_source = st.sidebar.selectbox("Data Source", ("OpenSky", "FlightRadar24"), index=1)

# Constants
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
TARGET_LAT = -33.7603831919607
TARGET_LON = 150.971709164045
ALERT_RADIUS_METERS = 50
HOME_LAT = -33.7603831919607
HOME_LON = 150.971709164045
RADIUS_KM = 20  # kilometers

# Utility functions
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
        math.sin(lat1)*math.cos(distance_m/R) +
        math.cos(lat1)*math.sin(distance_m/R)*math.cos(heading_rad)
    )
    lon2 = lon1 + math.atan2(
        math.sin(heading_rad)*math.sin(distance_m/R)*math.cos(lat1),
        math.cos(distance_m/R)-math.sin(lat1)*math.sin(lat2)
    )
    return math.degrees(lat2), math.degrees(lon2)

# Logging setup
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon"])

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
    if not FR24_API_KEY:
        st.error("Please set FLIGHTRADAR_API_KEY in environment.")
    else:
        try:
            fr_api = FR24API(FR24_API_KEY)
            bounds = f"{south},{west},{north},{east}"
            resp = fr_api.get_flight_positions_light(bounds)
            data_list = resp.get("data", resp) if isinstance(resp, dict) else (resp if isinstance(resp, list) else [])
            for p in data_list:
                lat = p.get("lat"); lon = p.get("lon")
                if lat is None or lon is None: continue
                callsign = p.get("flight", p.get("callsign", "N/A")).strip()
                velocity = p.get("speed", 0)
                heading = p.get("track", p.get("heading", 0))
                alt = p.get("altitude", 0)
                aircraft_states.append([None, callsign, None, None, None, lon, lat, None, velocity, heading, alt, None, None, None, None])
        except Exception as e:
            st.error(f"Error fetching FlightRadar24 data: {e}")

# Filter current aircraft within 20 miles
filtered_states = [ac for ac in aircraft_states if ac[6] is not None and ac[5] is not None \
                   and haversine(ac[6], ac[5], HOME_LAT, HOME_LON)/1000 <= RADIUS_KM]

# Display log of current aircraft
st.markdown("### Aircraft within 20 miles of Home")
if filtered_states:
    df_aircraft = pd.DataFrame([{
        'Callsign': ac[1],
        'Latitude': ac[6],
        'Longitude': ac[5],
        'Velocity (m/s)': ac[8],
        'Heading (°)': ac[9],
        'Altitude (m)': ac[10]
    } for ac in filtered_states])
    st.dataframe(df_aircraft)
else:
    st.info("No aircraft currently within 20 miles.")

# History of alerts
st.markdown("### Alert History")
if os.path.exists(log_path):
    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        st.dataframe(df_log)
    else:
        st.info("No alerts logged yet.")
else:
    st.info("Alert log file not found.")

# Initialize map center and zoom with validation
if "zoom" not in st.session_state:
    st.session_state.zoom = 12
center = st.session_state.get("center")
if not (isinstance(center, (list, tuple)) and len(center) == 2 
        and all(isinstance(x, (int, float)) for x in center)):
    st.session_state.center = [HOME_LAT, HOME_LON]

# Create map
fmap = folium.Map(location=st.session_state.center, zoom_start=st.session_state.zoom)
MarkerCluster().add_to(fmap)
folium.Marker((TARGET_LAT, TARGET_LON), icon=folium.Icon(color="red"), popup="Target").add_to(fmap)

# Forecast and alerts
alerts = []
for ac in filtered_states:
    callsign, lon, lat, velocity, heading, alt = ac[1], ac[5], ac[6], ac[8], ac[9], ac[10] or 0
    trail = []
    alerted_flag = False
    for i in range(0, FORECAST_DURATION_MINUTES*60+1, FORECAST_INTERVAL_SECONDS):
        future_time = selected_dt + timedelta(seconds=i)
        fl_lat, fl_lon = move_position(lat, lon, heading, velocity*i)
        sun_alt = get_altitude(fl_lat, fl_lon, future_time)
        if sun_alt <= 0 or alt <= 0: continue
        sun_az = get_azimuth(fl_lat, fl_lon, future_time)
        shadow_dist = alt / math.tan(math.radians(sun_alt))
        slat = fl_lat + (shadow_dist/111111)*math.cos(math.radians(sun_az+180))
        slon = fl_lon + (shadow_dist/(111111*math.cos(math.radians(fl_lat))))*math.sin(math.radians(sun_az+180))
        trail.append((slat, slon))
        if not alerted_flag and haversine(slat, slon, TARGET_LAT, TARGET_LON) <= ALERT_RADIUS_METERS:
            alerts.append((callsign, i))
            with open(log_path, "a", newline="") as f:
                csv.writer(f).writerow([datetime.utcnow().isoformat(), callsign, i, slat, slon])
            send_pushover("✈️ Shadow Alert", f"{callsign} will pass over target in {i} sec", 
                         PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN)
            alerted_flag = True
    if trail:
        folium.PolyLine(trail, color="black", weight=2, opacity=0.7, dash_array="5,5").add_to(fmap)
    folium.Marker((lat, lon), icon=folium.Icon(color="blue", icon="plane", prefix="fa"), popup=callsign).add_to(fmap)

# Display alerts
if alerts:
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
    for cs, t in alerts:
        st.write(f"✈️ {cs} in ~{t}s")
else:
    st.success("✅ No shadows crossing target.")

# Download log button
if os.path.exists(log_path):
    st.sidebar.markdown("### 📥 Download Log")
    with open(log_path, "rb") as file:
        st.sidebar.download_button("Download log", file, "alert_log.csv", mime="text/csv")

# Render map and update session state
md = st_folium(fmap, width=700, height=500)
if md and "center" in md and "zoom" in md:
    st.session_state.center = md["center"]
    st.session_state.zoom = md["zoom"]
