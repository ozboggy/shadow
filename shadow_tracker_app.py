import os
import math
import time
import requests
import ephem
import streamlit as st
from datetime import datetime, timezone
from pysolar.solar import get_altitude, get_azimuth
from streamlit_folium import st_folium
import folium

# --- Configuration ---
st.set_page_config(layout="wide", page_title="Aircraft Shadow Tracker")
DEFAULT_RADIUS_MI = 10
PREDICT_SECONDS = 60
ALERT_TIMES = [60, 30, 15, 10, 5, 0]  # seconds

# ADSB Exchange endpoint (min/max distance both set to radius)
ADSB_URL = (
    "https://public-api.adsbexchange.com/VirtualRadar/AircraftList.json"
    "?lat={lat}&lng={lng}&fDstL={dist}&fDstU={dist}&fAltL=0"
)

# Initialize session state for home location
if 'home' not in st.session_state:
    st.session_state.home = {'lat': -33.8688, 'lon': 151.2093}  # Sydney default

# Sidebar controls
st.sidebar.header("Settings")
st.sidebar.write(f"Search radius: {DEFAULT_RADIUS_MI} mi")
show_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
show_moon = st.sidebar.checkbox("Show Moon Shadows", value=True)

# Manual home location entry
lat_input = st.sidebar.number_input(
    "Home Latitude", value=st.session_state.home['lat'], format="%.6f"
)
lon_input = st.sidebar.number_input(
    "Home Longitude", value=st.session_state.home['lon'], format="%.6f"
)
# Update session state if changed
if lat_input != st.session_state.home['lat'] or lon_input != st.session_state.home['lon']:
    st.session_state.home = {'lat': lat_input, 'lon': lon_input}

# Function to fetch aircraft safely
def fetch_aircraft(lat, lon, miles):
    url = ADSB_URL.format(lat=lat, lng=lon, dist=miles)
    try:
        resp = requests.get(url, timeout=10)
    except Exception as e:
        st.error(f"Error fetching aircraft data: {e}")
        return []
    if resp.status_code != 200:
        st.warning(f"ADS-B API returned status {resp.status_code}")
        return []
    try:
        payload = resp.json()
    except ValueError:
        text_snippet = resp.text[:200].replace('\n', ' ')
        st.warning(f"Invalid JSON response: {text_snippet}")
        return []
    data = payload.get('acList', [])
    return [ac for ac in data if 'Lat' in ac]

# Main data fetch and map build
home = st.session_state.home
ac_list = fetch_aircraft(home['lat'], home['lon'], DEFAULT_RADIUS_MI)
now = datetime.now(timezone.utc)

# Create map
m = folium.Map(location=(home['lat'], home['lon']), zoom_start=12)
# Reference rings
for r in [1, 2, 5, 10]:
    folium.Circle(
        location=(home['lat'], home['lon']),
        radius=r * 1609.34,
        color='blue', fill=False,
        weight=1,
        dash_array='5'
    ).add_to(m)
# Home marker
folium.Marker(
    location=(home['lat'], home['lon']),
    tooltip='Home',
    icon=folium.Icon(color='red', icon='home', prefix='fa')
).add_to(m)

# Plot aircraft and shadows
for ac in ac_list:
    lat, lon = ac['Lat'], ac['Long']
    alt_m = ac.get('Alt', 0) * 0.3048
    callsign = ac.get('Call', '').strip()

    # Aircraft icon
    folium.Marker(
        location=(lat, lon),
        tooltip=f"{callsign} | Alt: {ac.get('Alt', 0)} ft | Spd: {ac.get('Spd', 0)} kt",
        icon=folium.Icon(icon='plane', prefix='fa')
    ).add_to(m)

    # Compute shadows
    shadows = []
    if show_sun:
        sun_alt = get_altitude(home['lat'], home['lon'], now)
        if sun_alt > 0:
            sun_az = get_azimuth(home['lat'], home['lon'], now)
            d = alt_m / math.tan(math.radians(sun_alt))
            brng = (sun_az + 180) % 360
            shadows.append(('sun', d, brng, 'black'))
    if show_moon and ephem:
        obs = ephem.Observer()
        obs.lat, obs.lon = str(home['lat']), str(home['lon'])
        obs.date = now
        moon = ephem.Moon(obs)
        moon_alt = math.degrees(moon.alt)
        if moon_alt > 0:
            moon_az = math.degrees(moon.az)
            d = alt_m / math.tan(math.radians(moon_alt))
            brng = (moon_az + 180) % 360
            shadows.append(('moon', d, brng, 'gray'))

    # Draw shadow lines
    for kind, dist, brng, col in shadows:
        R = 6378137
        d_rad = dist / R
        lat1 = math.radians(lat)
        lon1 = math.radians(lon)
        brng_rad = math.radians(brng)
        lat2 = math.asin(
            math.sin(lat1) * math.cos(d_rad)
            + math.cos(lat1) * math.sin(d_rad) * math.cos(brng_rad)
        )
        lon2 = lon1 + math.atan2(
            math.sin(brng_rad) * math.sin(d_rad) * math.cos(lat1),
            math.cos(d_rad) - math.sin(lat1) * math.sin(lat2)
        )
        folium.PolyLine(
            locations=[(lat, lon), (math.degrees(lat2), math.degrees(lon2))],
            color=col, weight=2
        ).add_to(m)

# Render map
st_folium(m, height=700)
