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
map_theme = st.sidebar.selectbox("Map Theme", ["CartoDB Positron", "CartoDB Dark_Matter", "OpenStreetMap", "Stamen Toner", "Stamen Terrain"], index=0)
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

folium.LayerControl(position='topright', collapsed=False).add_to(fmap)
folium.Marker((DEFAULT_TARGET_LAT, DEFAULT_TARGET_LON), icon=folium.Icon(color="red", icon="home", prefix="fa"), popup="Home").add_to(fmap)
aircraft_layer = folium.FeatureGroup(name="Aircraft Markers", show=True)
sun_layer = folium.FeatureGroup(name="Sun Shadows", show=True)
moon_layer = folium.FeatureGroup(name="Moon Shadows", show=True)
marker_cluster = MarkerCluster().add_to(aircraft_layer)
fmap.add_child(aircraft_layer)
fmap.add_child(sun_layer)
fmap.add_child(moon_layer)

# Fetch aircraft based on user choice
flights = []
if source_choice == "ADS-B Exchange":
    try:
        RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
        if not RAPIDAPI_KEY:
            raise ValueError("RAPIDAPI_KEY not set in environment variables.")

        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{DEFAULT_TARGET_LAT}/lon/{DEFAULT_TARGET_LON}/dist/{RADIUS_KM}/"
        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        # st.write("ADS-B Exchange raw response:", data)
        aircraft = data.get("ac", [])
        if show_debug:
            st.subheader("Raw ADS-B Exchange Aircraft")
            for i, ac in enumerate(aircraft):
                st.markdown(f"**Raw Aircraft {i+1}:**")
                st.json(ac)

        class RapidAPIAircraft:
            def __init__(self, ac):
                self.latitude = ac.get("lat")
                self.longitude = ac.get("lon")
                self.heading = ac.get("trak") or 0
                self.ground_speed = ac.get("spd") or 0
                self.alt_status = "airborne" if ac.get("alt_baro") != "ground" else "ground"
                self.baro_altitude = ac.get("alt_baro") or 0
                self.callsign = ac.get("flight")
                self.identification = ac.get("hex")
                self.airline = None

        flights = [RapidAPIAircraft(ac) for ac in aircraft if ac.get("lat") is not None and ac.get("lon") is not None and ac.get("spd") is not None and ac.get("trak") is not None]

    except Exception as e:
        st.warning(f"ADS-B Exchange via RapidAPI failed: {e} — falling back to OpenSky")
        try:
            north, south, west, east = DEFAULT_TARGET_LAT + 1, DEFAULT_TARGET_LAT - 1, DEFAULT_TARGET_LON - 1, DEFAULT_TARGET_LON + 1
            url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            states = data.get("states", [])

            class OpenSkyFlight:
                def __init__(self, state):
                    self.identification = state[0]
                    self.callsign = state[1].strip() if state[1] else ""
                    self.longitude = state[5]
                    self.latitude = state[6]
                    self.baro_altitude = state[7]
                    self.ground_speed = state[9]
                    self.heading = state[10]
                    self.airline = None

            flights = [OpenSkyFlight(s) for s in states if s[5] and s[6] and s[9] and s[10]]
        except Exception as fallback_error:
            st.error(f"Fallback to OpenSky also failed: {fallback_error}")

elif source_choice == "OpenSky":
    try:
        north, south, west, east = DEFAULT_TARGET_LAT + 1, DEFAULT_TARGET_LAT - 1, DEFAULT_TARGET_LON - 1, DEFAULT_TARGET_LON + 1
        url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        states = data.get("states", [])

        class OpenSkyFlight:
            def __init__(self, state):
                self.identification = state[0]
                self.callsign = state[1].strip() if state[1] else ""
                self.longitude = state[5]
                self.latitude = state[6]
                self.baro_altitude = state[7]
                self.ground_speed = state[9]
                self.heading = state[10]
                self.airline = None

        flights = [OpenSkyFlight(s) for s in states if s[5] and s[6] and s[9] and s[10]]

    except Exception as e:
        st.error(f"Error fetching OpenSky data: {e}")

# Utility functions
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

def get_shadow(lat, lon, alt_m, timestamp, source):
    if source == "Sun":
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

# Count nearby aircraft within 5 miles (8046 meters)
NEARBY_RADIUS_METERS = 8046
nearby_count = 0
for f in flights:
    dist = haversine(f.latitude, f.longitude, DEFAULT_TARGET_LAT, DEFAULT_TARGET_LON)
    if dist <= NEARBY_RADIUS_METERS:
        nearby_count += 1

# Show sidebar aircraft indicators
st.sidebar.metric(label="✈️ Tracked Aircraft", value=len(flights))
st.sidebar.metric(label="🟢 Nearby (≤5 mi)", value=nearby_count)

if show_debug:
    with st.expander("✈️ Debug: Listing all aircraft", expanded=False):
        for i, f in enumerate(flights):
            st.markdown(f"**Aircraft {i+1}:**")
            st.json(vars(f))

# Aircraft rendering
alerts_triggered = []
for f in flights:
    try:
        if show_debug:
            st.text(f"Attempting to render {getattr(f, 'callsign', 'N/A')} at lat={f.latitude}, lon={f.longitude}")
        lat, lon = f.latitude, f.longitude
        heading = f.heading
        velocity = f.ground_speed
        alt = f.baro_altitude or 0
        callsign = f.callsign or f.identification or "N/A"
        airline_logo_url = f.airline.get("logo", "") if f.airline else ""
        shadow_alerted = False

        color = "green" if getattr(f, 'baro_altitude', 0) not in ("ground", 0) else "gray"

        for source in [s for s in ("Sun", "Moon") if ((s == "Sun" and track_sun) or (s == "Moon" and track_moon)) or override_trails]:
            trail = []
            for i in range(0, DEFAULT_FORECAST_DURATION_MINUTES * 60 + 1, DEFAULT_FORECAST_INTERVAL_SECONDS):
                future_time = selected_time + timedelta(seconds=i)
                dist_moved = velocity * i
                future_lat, future_lon = move_position(lat, lon, heading, dist_moved)
                s_lat, s_lon = get_shadow(future_lat, future_lon, alt, future_time, source)
                if s_lat is not None and s_lon is not None:
                    trail.append((s_lat, s_lon))
                    if not shadow_alerted and haversine(s_lat, s_lon, DEFAULT_TARGET_LAT, DEFAULT_TARGET_LON) <= ALERT_RADIUS_METERS:
                        alerts_triggered.append((callsign, int(i), s_lat, s_lon))
                        with open(log_path, "a", newline="") as f_log:
                            writer = csv.writer(f_log)
                            writer.writerow([datetime.utcnow().isoformat(), callsign, int(i), s_lat, s_lon, source])
                        send_pushover("✈️ Shadow Alert", f"{callsign} shadow ({source}) over target in {int(i)}s")
                        shadow_alerted = True

            if trail:
                dash = "5,5" if source == "Sun" else "2,8"
                layer_target = sun_layer if source == "Sun" else moon_layer
                folium.PolyLine(trail, color=color, weight=shadow_width, opacity=0.7, dash_array=dash,
                                tooltip=f"{callsign} ({source})").add_to(layer_target)

        # Always add aircraft marker regardless of trail
        logo_html = f'<img src="{airline_logo_url}" width="50"><br>' if airline_logo_url else ""
        popup_content = f"{logo_html}{callsign}<br>Alt: {round(alt)}m<br>Spd: {velocity} kt<br>Hdg: {heading}°"

        folium.Marker(location=(lat, lon), icon=folium.Icon(color=color, icon="plane", prefix="fa"),
                      popup=popup_content).add_to(marker_cluster)

    except Exception as e:
        st.warning(f"Error processing aircraft: {e}")

# Display map
st_folium(fmap, width=1200, height=700)

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
