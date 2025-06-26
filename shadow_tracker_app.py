import os
import math
import time
import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone, timedelta
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
ALERT_WIDTH_M = 1609.34 * DEFAULT_RADIUS_MI
ALERT_TIMES = [60, 30, 15, 10, 5, 0]

# Session-state for home location
if 'home' not in st.session_state:
    st.session_state.home = {'lat': -33.8688, 'lon': 151.2093}

# Sidebar controls
st.sidebar.header("Settings")
# Manual home entry
lat = st.sidebar.number_input("Home Latitude", value=st.session_state.home['lat'], format="%.6f")
lon = st.sidebar.number_input("Home Longitude", value=st.session_state.home['lon'], format="%.6f")
if (lat, lon) != (st.session_state.home['lat'], st.session_state.home['lon']):
    st.session_state.home = {'lat': lat, 'lon': lon}

# ADS-B fetch via OpenSky bounding box
def fetch_aircraft(lat, lon, miles):
    dlat = miles / 69.0
    dlon = miles / (abs(math.cos(math.radians(lat))) * 69.0)
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
        if s[6] and s[5]:
            rows.append({
                'lat': s[6],
                'lon': s[5],
                'alt': s[7] or 0,
                'callsign': (s[1].strip() or s[0]),
                'vel': (s[9] or 0) * 1.94384,
                'hdg': s[10] or 0
            })
    return pd.DataFrame(rows)

# Get current data
home = st.session_state.home
df_ac = fetch_aircraft(home['lat'], home['lon'], DEFAULT_RADIUS_MI)
now = datetime.now(timezone.utc)

# Build PyDeck layers
layers = []
# Aircraft scatter
if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", data=df_ac,
        get_position=["lon","lat"], get_fill_color=[0,128,255,200], get_radius=150,
        pickable=True
    ))
# Home marker
layers.append(pdk.Layer(
    "ScatterplotLayer", data=pd.DataFrame([home]),
    get_position=["lon","lat"], get_fill_color=[255,0,0,200], get_radius=200,
    pickable=False
))
# Reference rings at 1,2,5,10 mi
for r in [1,2,5,10]:
    coords = []
    for ang in range(0,360,10):
        dlat = (r*1609.34*math.cos(math.radians(ang))) / 111111
        dlon = (r*1609.34*math.sin(math.radians(ang))) / (111111*math.cos(math.radians(home['lat'])))
        coords.append([home['lon']+dlon, home['lat']+dlat])
    layers.append(pdk.Layer(
        "LineLayer", data=[{"path": coords}], get_path="path",
        get_color=[0,0,255,150], get_width=2, pickable=False
    ))
# Shadow trails for sun and moon
shadow_lines = []
for _, row in df_ac.iterrows():
    for kind, color in [("sun", [0,0,0]), ("moon", [128,128,128])]:
        if kind=="sun":
            alt_ang = get_altitude(home['lat'], home['lon'], now)
            az_ang = get_azimuth(home['lat'], home['lon'], now)
        else:
            if not ephem: continue
            obs = ephem.Observer(); obs.lat, obs.lon = str(home['lat']), str(home['lon']); obs.date = now
            moon = ephem.Moon(obs)
            alt_ang = math.degrees(moon.alt)
            az_ang = math.degrees(moon.az)
        if alt_ang <= 0: continue
        d = row['alt'] / math.tan(math.radians(alt_ang))
        br = (az_ang+180)%360
        R=6378137; dr = d/R
        lat1, lon1 = math.radians(row['lat']), math.radians(row['lon'])
        b = math.radians(br)
        lat2 = math.asin(math.sin(lat1)*math.cos(dr)+math.cos(lat1)*math.sin(dr)*math.cos(b))
        lon2 = lon1+math.atan2(math.sin(b)*math.sin(dr)*math.cos(lat1), math.cos(dr)-math.sin(lat1)*math.sin(lat2))
        shadow_lines.append({
            "start": [row['lon'], row['lat']],
            "end": [math.degrees(lon2), math.degrees(lat2)],
            "color": color
        })
# Add shadow layer
layers.append(pdk.Layer(
    "LineLayer", data=shadow_lines,
    get_source_position="start", get_target_position="end",
    get_color="color", get_width=2, pickable=False
))

# Render map
view = pdk.ViewState(latitude=home['lat'], longitude=home['lon'], zoom=12)
deck = pdk.Deck(
    layers=layers,
    initial_view_state=view,
    map_style="mapbox://styles/mapbox/light-v9",
    tooltip={"html":"<b>Callsign:</b> {callsign}<br/><b>Alt:</b> {alt:.0f} ft<br/><b>Spd:</b> {vel:.0f} kt"}
)
st.pydeck_chart(deck, use_container_width=True)

# TODO: on-screen alerts at thresholds
