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
def get_opensky_url(lat, lon, miles):
    dlat = miles / 69.0
    dlon = miles / (abs(math.cos(math.radians(lat))) * 69.0)
    return (
        f"https://opensky-network.org/api/states/all"
        f"?lamin={lat-dlat}&lomin={lon-dlon}&lamax={lat+dlat}&lomax={lon+dlon}"
    )

# Default home location
if 'home' not in st.session_state:
    st.session_state.home = {'lat': -33.8688, 'lon': 151.2093}

# Sidebar controls
st.sidebar.header("Settings")
st.sidebar.write(f"Search radius: {DEFAULT_RADIUS_MI} mi")
show_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
show_moon = st.sidebar.checkbox("Show Moon Shadows", value=True)

# Manual home entry
lat_input = st.sidebar.number_input(
    "Home Latitude", value=st.session_state.home['lat'], format="%.6f"
)
lon_input = st.sidebar.number_input(
    "Home Longitude", value=st.session_state.home['lon'], format="%.6f"
)
if (lat_input, lon_input) != (st.session_state.home['lat'], st.session_state.home['lon']):
    st.session_state.home = {'lat': lat_input, 'lon': lon_input}

# Fetch aircraft with caching
def fetch_aircraft(lat, lon, miles):
    url = get_opensky_url(lat, lon, miles)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    ac_list = []
    for s in data.get('states', []):
        lat_s, lon_s = s[6], s[5]
        if lat_s and lon_s:
            ac_list.append({
                'lat': lat_s,
                'lon': lon_s,
                'alt_m': s[7] or 0,
                'call': (s[1].strip() or s[0]),
                'spd_kt': (s[9] or 0) * 1.94384
            })
    return ac_list

# Main
home = st.session_state.home
ac_list = fetch_aircraft(home['lat'], home['lon'], DEFAULT_RADIUS_MI)
now = datetime.now(timezone.utc)

# Setup PyDeck view
view_state = pdk.ViewState(
    latitude=home['lat'], longitude=home['lon'], zoom=12, pitch=0, bearing=0
)
layers = []

# Reference rings
for r in [1,2,5,10]:
    coords = []
    for angle in range(0, 360, 5):
        dlat = (r * math.cos(math.radians(angle))) / 69.0
        dlon = (r * math.sin(math.radians(angle))) / (abs(math.cos(math.radians(home['lat']))) * 69.0)
        coords.append([home['lon']+dlon, home['lat']+dlat])
    layers.append(
        pdk.Layer(
            "LineLayer", data=[{"path": coords}], get_path="path",
            get_width=1, get_color=[0,0,255]
        )
    )

# Home marker
layers.append(
    pdk.Layer(
        "ScatterplotLayer", data=[{'lon': home['lon'], 'lat': home['lat']}],
        get_position="[lon, lat]", get_radius=200, get_color=[255,0,0]
    )
)

# Aircraft and shadows
shadow_lines = []
for ac in ac_list:
    # Aircraft
    layers.append(
        pdk.Layer(
            "ScatterplotLayer", data=[ac],
            get_position="[lon, lat]", get_radius=100, get_color=[0,255,0],
            pickable=True
        )
    )
    # Shadows
    for kind, color in [("sun", [0,0,0]), ("moon", [128,128,128])]:
        if (kind=="sun" and not show_sun) or (kind=="moon" and not show_moon):
            continue
        if kind=="sun":
            alt = get_altitude(home['lat'], home['lon'], now)
            az = get_azimuth(home['lat'], home['lon'], now)
        else:
            obs = ephem.Observer(); obs.lat, obs.lon = str(home['lat']), str(home['lon']); obs.date = now
            moon = ephem.Moon(obs)
            alt = math.degrees(moon.alt); az = math.degrees(moon.az)
        if alt > 0:
            d = ac['alt_m'] / math.tan(math.radians(alt))
            brng = (az + 180) % 360
            R = 6378137; dr = d / R
            lat1, lon1 = math.radians(ac['lat']), math.radians(ac['lon'])
            b = math.radians(brng)
            lat2 = math.asin(math.sin(lat1)*math.cos(dr) + math.cos(lat1)*math.sin(dr)*math.cos(b))
            lon2 = lon1 + math.atan2(math.sin(b)*math.sin(dr)*math.cos(lat1), math.cos(dr)-math.sin(lat1)*math.sin(lat2))
            shadow_lines.append({
                'start': [ac['lon'], ac['lat']],
                'end': [math.degrees(lon2), math.degrees(lat2)],
                'color': color
            })

# Shadow layer
layers.append(
    pdk.Layer(
        "LineLayer", data=shadow_lines,
        get_source_position="start", get_target_position="end",
        get_color="color", get_width=2
    )
)

# Render without specifying mapbox style (uses default tiles)
deck = pdk.Deck(
    initial_view_state=view_state,
    layers=layers,
    tooltip={"text": "{call}"}
)
st.pydeck_chart(deck, use_container_width=True)

# TODO: Alerts at 60s/30s/... based on predicted intercept
