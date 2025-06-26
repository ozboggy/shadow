import os
import math
import requests
import ephem
import streamlit as st
from datetime import datetime, timezone
from pysolar.solar import get_altitude, get_azimuth
import pydeck as pdk

# --- Configuration ---
st.set_page_config(layout="wide", page_title="Aircraft Shadow Tracker")
DEFAULT_RADIUS_MI = 10
ALERT_TIMES = [60, 30, 15, 10, 5, 0]

# OpenSky anonymous API endpoint
OPENSKY_URL = (
    "https://opensky-network.org/api/states/all"
    "?lamin={lat_min}&lomin={lon_min}&lamax={lat_max}&lomax={lon_max}"
)

# Session default home location
default_home = {'lat': -33.8688, 'lon': 151.2093}
if 'home' not in st.session_state:
    st.session_state.home = default_home.copy()

# Sidebar for settings
st.sidebar.header("Settings")
st.sidebar.write(f"Search radius: {DEFAULT_RADIUS_MI} mi")
show_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
show_moon = st.sidebar.checkbox("Show Moon Shadows", value=True)

# Manual home entry
dlat = 0
lat_input = st.sidebar.number_input(
    "Home Latitude", value=st.session_state.home['lat'], format="%.6f"
)
lon_input = st.sidebar.number_input(
    "Home Longitude", value=st.session_state.home['lon'], format="%.6f"
)
if lat_input != st.session_state.home['lat'] or lon_input != st.session_state.home['lon']:
    st.session_state.home = {'lat': lat_input, 'lon': lon_input}

# Fetch aircraft via OpenSky API
@st.cache_data(ttl=5)
def fetch_aircraft(lat, lon, miles):
    dlat = miles / 69.0
    dlon = miles / (abs(math.cos(math.radians(lat))) * 69.0)
    url = OPENSKY_URL.format(
        lat_min=lat - dlat, lon_min=lon - dlon,
        lat_max=lat + dlat, lon_max=lon + dlon
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    states = data.get('states', [])
    ac_list = []
    for s in states:
        lat_s, lon_s = s[6], s[5]
        if lat_s and lon_s:
            ac_list.append({
                'lat': lat_s,
                'lon': lon_s,
                'alt_m': (s[7] or 0),
                'call': s[1].strip() or s[0],
                'spd_kt': (s[9] or 0) * 1.94384
            })
    return ac_list

# Main display
home = st.session_state.home
ac_list = fetch_aircraft(home['lat'], home['lon'], DEFAULT_RADIUS_MI)
now = datetime.now(timezone.utc)

# PyDeck view state
view_state = pdk.ViewState(
    latitude=home['lat'],
    longitude=home['lon'],
    zoom=12,
    pitch=0,
    bearing=0
)
layers = []

# Reference rings as ScatterplotLayer of circle points
theta = [i for i in range(0, 360, 10)]
for r in [1,2,5,10]:
    coords = []
    for angle in theta:
        dlat = (r * math.cos(math.radians(angle))) / 69.0
        dlon = (r * math.sin(math.radians(angle))) / (abs(math.cos(math.radians(home['lat'])))*69.0)
        coords.append([home['lon']+dlon, home['lat']+dlat])
    layers.append(
        pdk.Layer(
            "LineLayer",
            data=[{"path": coords}],
            get_path="path",
            get_width=1,
            get_color=[0,0,255],
            pickable=False
        )
    )

# Home marker
layers.append(
    pdk.Layer(
        "ScatterplotLayer",
        data=[home],
        get_position="[lon, lat]",
        get_color=[255,0,0],
        get_radius=200,
        pickable=False
    )
)

# Aircraft points and shadow lines
shadow_lines = []
for ac in ac_list:
    # Aircraft
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=[ac],
            get_position="[lon, lat]",
            get_color=[0,255,0],
            get_radius=100,
            pickable=True
        )
    )
    # Shadows
    for kind, col in [("sun","[0,0,0]"),("moon","[128,128,128]")]:
        if (kind=="sun" and not show_sun) or (kind=="moon" and not show_moon):
            continue
        if kind=="sun":
            alt = get_altitude(home['lat'], home['lon'], now)
            az = get_azimuth(home['lat'], home['lon'], now)
        else:
            obs = ephem.Observer(); obs.lat, obs.lon = str(home['lat']), str(home['lon']); obs.date = now
            moon = ephem.Moon(obs)
            alt = math.degrees(moon.alt)
            az = math.degrees(moon.az)
        if alt > 0:
            d = ac['alt_m'] / math.tan(math.radians(alt))
            brng = (az+180)%360
            # compute endpoint
            R=6378137; d_rad=d/R
            lat1, lon1 = math.radians(ac['lat']), math.radians(ac['lon'])
            br = math.radians(brng)
            lat2 = math.asin(math.sin(lat1)*math.cos(d_rad)+math.cos(lat1)*math.sin(d_rad)*math.cos(br))
            lon2 = lon1+math.atan2(math.sin(br)*math.sin(d_rad)*math.cos(lat1),math.cos(d_rad)-math.sin(lat1)*math.sin(lat2))
            shadow_lines.append({
                "start": [ac['lon'], ac['lat']],
                "end": [math.degrees(lon2), math.degrees(lat2)],
                "color": eval(col)
            })

# Add shadow line layer
layers.append(
    pdk.Layer(
        "LineLayer",
        data=shadow_lines,
        get_source_position="start",
        get_target_position="end",
        get_color="color",
        get_width=2
    )
)

# Render map without flicker
deck = pdk.Deck(
    map_style="mapbox://styles/mapbox/light-v9",
    initial_view_state=view_state,
    layers=layers,
    tooltip={"text": "{call}"}
)
st.pydeck_chart(deck, use_container_width=True)

# TODO: implement timed alerts based on distance to home and PREDICT_SECONDS thresholds
