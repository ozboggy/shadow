import os
import math
import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone
from pysolar.solar import get_altitude, get_azimuth
from streamlit_autorefresh import st_autorefresh
import pydeck as pdk

# Optional moon computations
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh every second
st_autorefresh(interval=1000, key="refresh")

# --- Configuration ---
st.set_page_config(layout="wide", page_title="Aircraft Shadow Tracker")
DEFAULT_RADIUS_MI = 10
ALERT_TIMES = [60, 30, 15, 10, 5, 0]

# Initialize home location
default_home = {'lat': -33.8688, 'lon': 151.2093}
if 'home' not in st.session_state:
    st.session_state.home = default_home.copy()

# Sidebar for manual home coordinate entry
st.sidebar.header("Settings")
lat = st.sidebar.number_input("Home Latitude", value=st.session_state.home['lat'], format="%.6f")
lon = st.sidebar.number_input("Home Longitude", value=st.session_state.home['lon'], format="%.6f")
if (lat, lon) != (st.session_state.home['lat'], st.session_state.home['lon']):
    st.session_state.home = {'lat': lat, 'lon': lon}
home = st.session_state.home

# Fetch aircraft via OpenSky bounding box
def fetch_aircraft(lat, lon, radius_mi):
    dlat = radius_mi / 69.0
    dlon = radius_mi / (abs(math.cos(math.radians(lat))) * 69.0)
    url = (
        f"https://opensky-network.org/api/states/all"
        f"?lamin={lat-dlat}&lomin={lon-dlon}&lamax={lat+dlat}&lomax={lon+dlon}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except:
        return pd.DataFrame()
    states = data.get('states', [])
    rows = []
    for s in states:
        lat_s, lon_s = s[6], s[5]
        if lat_s and lon_s:
            rows.append({
                'lat': lat_s,
                'lon': lon_s,
                'alt': s[7] or 0,
                'callsign': s[1].strip() or s[0],
                'vel': (s[9] or 0) * 1.94384,
                'hdg': s[10] or 0
            })
    return pd.DataFrame(rows)

df_ac = fetch_aircraft(home['lat'], home['lon'], DEFAULT_RADIUS_MI)
now = datetime.now(timezone.utc)

# Build layers list
layers = []

# 1. Aircraft points
if not df_ac.empty:
    aircraft_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_ac,
        get_position=["lon", "lat"],
        get_fill_color=[0, 128, 255, 200],
        get_radius=150,
        pickable=True
    )
    layers.append(aircraft_layer)

# 2. Home location marker
home_df = pd.DataFrame([home])
home_layer = pdk.Layer(
    "ScatterplotLayer",
    data=home_df,
    get_position=["lon", "lat"],
    get_fill_color=[255, 0, 0, 200],
    get_radius=200,
    pickable=False
)
layers.append(home_layer)

# 3. Reference rings (1, 2, 5, 10 mi)
for r in [1, 2, 5, 10]:
    coords = []
    for angle in range(0, 360, 10):
        dlat = (r * 1609.34 * math.cos(math.radians(angle))) / 111111
        dlon = (r * 1609.34 * math.sin(math.radians(angle))) / (111111 * math.cos(math.radians(home['lat'])))
        coords.append([home['lon'] + dlon, home['lat'] + dlat])
    ring_layer = pdk.Layer(
        "LineLayer",
        data=[{"path": coords}],
        get_path="path",
        get_color=[0, 0, 255, 150],
        get_width=2,
        pickable=False
    )
    layers.append(ring_layer)

# 4. Shadow projections
shadow_data = []
for _, row in df_ac.iterrows():
    for kind, col in [("sun", [0, 0, 0]), ("moon", [128, 128, 128])]:
        if kind == "sun":
            alt_ang = get_altitude(home['lat'], home['lon'], now)
            az_ang = get_azimuth(home['lat'], home['lon'], now)
        else:
            if not ephem:
                continue
            obs = ephem.Observer()
            obs.lat, obs.lon = str(home['lat']), str(home['lon'])
            obs.date = now
            moon = ephem.Moon(obs)
            alt_ang = math.degrees(moon.alt)
            az_ang = math.degrees(moon.az)
        if alt_ang <= 0:
            continue
        distance = row['alt'] / math.tan(math.radians(alt_ang))
        bearing = (az_ang + 180) % 360
        # Calculate endpoint
        R = 6378137
        dr = distance / R
        lat1, lon1 = math.radians(row['lat']), math.radians(row['lon'])
        br = math.radians(bearing)
        lat2 = math.asin(math.sin(lat1)*math.cos(dr) + math.cos(lat1)*math.sin(dr)*math.cos(br))
        lon2 = lon1 + math.atan2(
            math.sin(br)*math.sin(dr)*math.cos(lat1),
            math.cos(dr) - math.sin(lat1)*math.sin(lat2)
        )
        shadow_data.append({
            "start": [row['lon'], row['lat']],
            "end": [math.degrees(lon2), math.degrees(lat2)],
            "color": col
        })
shadow_layer = pdk.Layer(
    "LineLayer",
    data=shadow_data,
    get_source_position="start",
    get_target_position="end",
    get_color="color",
    get_width=2,
    pickable=False
)
layers.append(shadow_layer)

# Render map with PyDeck
view_state = pdk.ViewState(latitude=home['lat'], longitude=home['lon'], zoom=12)
deck = pdk.Deck(
    layers=layers,
    initial_view_state=view_state,
    map_style="mapbox://styles/mapbox/light-v9",
    tooltip={"html": "<b>Callsign:</b> {callsign}<br/><b>Alt:</b> {alt:.0f} ft<br/><b>Spd:</b> {vel:.0f} kt"}
)
st.pydeck_chart(deck, use_container_width=True)

# TODO: Add on-screen alerts based on ALERT_TIMES

