import streamlit as st
from streamlit_folium import st_folium
import requests
import pandas as pd
import folium
from pysolar.solar import get_altitude, get_azimuth
from datetime import datetime, timezone
import os
import csv
import math

# --- CONFIGURATION ---
HOME_LAT = st.sidebar.number_input("Home Latitude", value=YOUR_HOME_LAT)
HOME_LON = st.sidebar.number_input("Home Longitude", value=YOUR_HOME_LON)
RADIUS_MI = st.sidebar.slider("Tracking Radius (mi)", min_value=1, max_value=50, value=10)
REFRESH_SECONDS = 30
LOG_FILE = "alert_log.csv"
CACHE_FILE = "map_state.json"

# Initialize session state for map
if 'map_center' not in st.session_state:
    st.session_state.map_center = (HOME_LAT, HOME_LON)
if 'zoom' not in st.session_state:
    st.session_state.zoom = 12

st.title("✈️ Aircraft Shadow Tracker")

# Auto-refresh
count = st.experimental_data_editor([], num_rows=0)  # hack to trigger rerun
st.experimental_rerun() if st.button("Refresh Now") else None

# Fetch aircraft data
@st.experimental_memo(ttl=REFRESH_SECONDS)
def fetch_aircraft(lat, lon, radius_m):
    url = f"https://opensky-network.org/api/states/all?lamin={lat - radius_m}&lomin={lon - radius_m}&lamax={lat + radius_m}&lomax={lon + radius_m}"
    resp = requests.get(url, timeout=10)
    data = resp.json().get('states', [])
    columns = ['icao24', 'callsign', 'origin_country', 'time_position',
               'last_contact', 'lon', 'lat', 'baro_altitude', 'velocity',
               'true_track', 'vertical_rate', 'sensors', 'geo_altitude']
    return pd.DataFrame(data, columns=columns)

# Utility: project shadow endpoint
def project_shadow(lat, lon, altitude_m, solar_elev, solar_azim):
    if solar_elev <= 0:
        return None
    shadow_length = altitude_m / math.tan(math.radians(solar_elev))
    # Convert to degrees approx
    meters_per_deg = 111_000
    dx = shadow_length * math.sin(math.radians(solar_azim))
    dy = shadow_length * math.cos(math.radians(solar_azim))
    dlat = dy / meters_per_deg
    dlon = dx / (meters_per_deg * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon

# Main map creation
def create_map(df):
    fmap = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.zoom)
    # Home marker
    folium.Marker([HOME_LAT, HOME_LON], icon=folium.Icon(color='red'), tooltip='Home').add_to(fmap)

    for _, row in df.iterrows():
        lat, lon = row['lat'], row['lon']
        alt_m = row['baro_altitude'] or 0
        now = datetime.now(timezone.utc)
        elev = get_altitude(HOME_LAT, HOME_LON, now)
        azim = get_azimuth(HOME_LAT, HOME_LON, now)
        shadow_pt = project_shadow(lat, lon, alt_m, elev, azim)

        # Plot plane
        folium.Marker([lat, lon], icon=folium.Icon(icon='plane', prefix='fa'),
                      tooltip=row['callsign'].strip() or row['icao24']).add_to(fmap)
        # Plot shadow
        if shadow_pt:
            folium.CircleMarker(shadow_pt, radius=5, color='gray', fill=True,
                                fill_opacity=0.7, tooltip='Shadow').add_to(fmap)
            # Alert check
            meters_per_deg = 111_000
            dist = math.hypot((shadow_pt[0]-HOME_LAT)*meters_per_deg,
                              (shadow_pt[1]-HOME_LON)*meters_per_deg*math.cos(math.radians(HOME_LAT)))
            if dist < 50:  # within ~50m
                st.warning(f"Shadow from {row['callsign'].strip() or row['icao24']} is over home!")
                # Log alert
                with open(LOG_FILE, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([datetime.utcnow().isoformat(), row['icao24'], row['callsign']])
    return fmap

# Fetch & render
df = fetch_aircraft(HOME_LAT, HOME_LON, RADIUS_MI * 1609)
fmap = create_map(df)

# Render map and capture state
map_data = st_folium(fmap, width=700, height=500)
if map_data and 'center' in map_data:
    st.session_state.map_center = (map_data['center']['lat'], map_data['center']['lng'])
if map_data and 'zoom' in map_data:
    st.session_state.zoom = map_data['zoom']

# Show log
if st.sidebar.checkbox("Show Alert Log"):
    if os.path.exists(LOG_FILE):
        log_df = pd.read_csv(LOG_FILE, header=None, names=['timestamp', 'icao24', 'callsign'])
        st.sidebar.dataframe(log_df)
    else:
        st.sidebar.write("No alerts yet.")
