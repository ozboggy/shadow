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

# OpenSky anonymous API endpoint template
OPENSKY_URL = (
    "https://opensky-network.org/api/states/all"
    "?lamin={lat_min}&lomin={lon_min}&lamax={lat_max}&lomax={lon_max}"
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

# Function to fetch aircraft via OpenSky
def fetch_aircraft(lat, lon, miles):
    # bounding box in degrees (~1 deg lat ~69 mi)
    dlat = miles / 69.0
    dlon = miles / (abs(math.cos(math.radians(lat))) * 69.0)
    url = OPENSKY_URL.format(
        lat_min=lat - dlat,
        lon_min=lon - dlon,
        lat_max=lat + dlat,
        lon_max=lon + dlon,
    )
    try:
        resp = requests.get(url, timeout=10)
    except Exception as e:
        st.error(f"Error fetching aircraft data: {e}")
        return []
    if resp.status_code != 200:
        st.warning(f"OpenSky API returned status {resp.status_code}")
        return []
    try:
        data = resp.json()
    except ValueError:
        text_snippet = resp.text[:200].replace('\n', ' ')
        st.warning(f"Invalid JSON from OpenSky: {text_snippet}")
        return []
    states = data.get('states', [])
    result = []
    for s in states:
        # state vector indices: [latitude=6, longitude=5, altitude=7, callsign=1, velocity=9]
        lat_s = s[6]
        lon_s = s[5]
        alt_m = (s[7] or 0)  # meters
        icao = s[0]
        call = s[1].strip() if s[1] else icao
        spd_ms = s[9] or 0
        if lat_s and lon_s:
            result.append({
                'Lat': lat_s,
                'Long': lon_s,
                'Alt': alt_m / 0.3048,  # convert to feet for consistency
                'Call': call,
                'Spd': spd_ms * 1.94384,  # m/s to knots
            })
    return result

# Main data fetch and map build
title = "Aircraft Shadow Tracker"
st.header(title)
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
    callsign = ac.get('Call', '')

    # Aircraft icon
    folium.Marker(
        location=(lat, lon),
        tooltip=f"{callsign} | Alt: {ac.get('Alt', 0):.0f} ft | Spd: {ac.get('Spd', 0):.0f} kt",
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

# TODO: implement on-screen alerts at 60 s, 30 s, 15 s, 10 s, 5 s and impact
