import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
import csv
import os
import pandas as pd
import plotly.express as px
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth
from skyfield.api import load, Topos

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
TARGET_LAT = -33.7602563
TARGET_LON = 150.9717434
ALERT_RADIUS_METERS = 50
RADIUS_KM = 20
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
HOME_CENTER = [-33.7602563, 150.9717434]

# Logging
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon", "Source"])

# UI
st.set_page_config(layout="wide")
st.title("✈️ Aircraft Shadow Tracker")

selected_date = datetime.utcnow().date()
selected_time_only = dt_time(datetime.utcnow().hour, datetime.utcnow().minute)
selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)
shadow_source = st.sidebar.radio("Shadow Source", ["Sun", "Moon"], horizontal=True)

# Fetch aircraft (OpenSky fallback)
north, south, west, east = -33.0, -34.5, 150.0, 151.5
url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
try:
    r = requests.get(url)
    r.raise_for_status()
    data = r.json()
except Exception as e:
    st.error(f"Error fetching OpenSky data: {e}")
    data = {}

# Setup map
center = HOME_CENTER
zoom = 10
fmap = folium.Map(location=center, zoom_start=zoom, control_scale=True)
marker_cluster = MarkerCluster().add_to(fmap)
folium.Marker((TARGET_LAT, TARGET_LON), icon=folium.Icon(color="red"), popup="Target").add_to(fmap)

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
    lat2 = math.asin(math.sin(lat1)*math.cos(distance_m/R) + math.cos(lat1)*math.sin(distance_m/R)*math.cos(heading_rad))
    lon2 = lon1 + math.atan2(math.sin(heading_rad)*math.sin(distance_m/R)*math.cos(lat1), math.cos(distance_m/R)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

def get_shadow(lat, lon, alt_m, timestamp):
    if shadow_source == "Sun":
        sun_alt = get_sun_altitude(lat, lon, timestamp)
        sun_az = get_sun_azimuth(lat, lon, timestamp)
    else:
        observer = earth + Topos(latitude_degrees=lat, longitude_degrees=lon, elevation_m=0)
        t = ts.utc(timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second)
        astrometric = observer.at(t).observe(moon).apparent()
        alt, az, _ = astrometric.altaz()
        sun_alt, sun_az = alt.degrees, az.degrees

    if sun_alt <= 0:
        return None, None

    shadow_dist = alt_m / math.tan(math.radians(sun_alt))
    shadow_lat = lat + (shadow_dist / 111111) * math.cos(math.radians(sun_az + 180))
    shadow_lon = lon + (shadow_dist / (111111 * math.cos(math.radians(lat)))) * math.sin(math.radians(sun_az + 180))
    return shadow_lat, shadow_lon

# Aircraft rendering
alerts_triggered = []
aircraft_states = data.get("states", [])
for ac in aircraft_states:
    try:
        icao24, callsign, _, _, _, lon, lat, baro_altitude, _, velocity, heading, _, _, geo_altitude, *_ = ac
        if None in (lat, lon, velocity, heading):
            continue
        alt = geo_altitude or 0
        callsign = callsign.strip() if callsign else "N/A"

        # Only render live aircraft
        folium.Marker((lat, lon), icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
                      popup=f"{callsign}
Alt: {round(alt)}m").add_to(marker_cluster)
    except Exception as e:
        st.warning(f"Error processing aircraft: {e}")

# Display map
st_folium(fmap, width=2000, height=1400)

# Logs
if os.path.exists(log_path):
    st.sidebar.markdown("### 📅 Download Log")
    with open(log_path, "rb") as f:
        st.sidebar.download_button("Download alert_log.csv", f, file_name="alert_log.csv", mime="text/csv")

    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        st.markdown("### 📊 Recent Alerts")
        st.dataframe(df_log.tail(10))

        fig = px.scatter(df_log, x="Time UTC", y="Callsign", size="Time Until Alert (sec)",
                         color="Source", hover_data=["Lat", "Lon"], title="Shadow Alerts Over Time")
        st.plotly_chart(fig, use_container_width=True)
