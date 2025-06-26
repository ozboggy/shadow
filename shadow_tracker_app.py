import os
import math
import time
import requests
import ephem
import streamlit as st
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth
from streamlit_folium import st_folium
import folium

# --- Configuration ---
st.set_page_config(layout="wide", page_title="Aircraft Shadow Tracker")
DEFAULT_RADIUS_MI = 10
PREDICT_SECONDS = 60
ALERT_TIMES = [60, 30, 15, 10, 5, 0]  # seconds

# ADSB Exchange endpoint
ADSB_URL = (
    "https://public-api.adsbexchange.com/VirtualRadar/AircraftList.json"
    "?lat={lat}&lng={lng}&fDstL={dist}&fDstU={dist}&fAltL=0"
)

# Initialize session state
if 'home' not in st.session_state:
    st.session_state.home = {'lat':  -33.8688, 'lon': 151.2093}  # Sydney default

# Sidebar controls
st.sidebar.header("Settings")
st.sidebar.write(f"Search radius: {DEFAULT_RADIUS_MI} mi")
show_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
show_moon = st.sidebar.checkbox("Show Moon Shadows", value=True)

def fetch_aircraft(lat, lon, miles):
    url = ADSB_URL.format(lat=lat, lng=lon, dist=miles)
    resp = requests.get(url)
    data = resp.json().get('acList', [])
    return [ac for ac in data if 'Lat' in ac]

# Map for selecting/updating home location
st.sidebar.markdown("---")
st.sidebar.write("Click on the map to set your home location")
map_center = (st.session_state.home['lat'], st.session_state.home['lon'])
folium_map = folium.Map(location=map_center, zoom_start=12)
# draw rings
for r in [1, 2, 5, 10]:
    folium.Circle(
        location=map_center,
        radius=r * 1609.34,
        color='blue', fill=False,
        weight=1,
        dash_array='5'
    ).add_to(folium_map)
click_data = st_folium(folium_map, height=500, key='home_map')
if click_data and click_data.get('last_clicked'):
    lat, lon = click_data['last_clicked']['lat'], click_data['last_clicked']['lng']
    st.session_state.home = {'lat': lat, 'lon': lon}

# Container for map updates
map_container = st.empty()

# Auto-refresh every second
st_autorefresh = st.experimental_rerun if False else None
# continuous loop via Streamlit rerun
if True:
    # Fetch aircraft
    home = st.session_state.home
    ac_list = fetch_aircraft(home['lat'], home['lon'], DEFAULT_RADIUS_MI)
    now = datetime.now(timezone.utc)

    # Prepare map
    m = folium.Map(location=(home['lat'], home['lon']), zoom_start=12)
    # redraw rings
    for r in [1,2,5,10]:
        folium.Circle(location=(home['lat'], home['lon']), radius=r*1609.34,
                      color='blue', fill=False, weight=1, dash_array='5').add_to(m)
    # Home marker
    folium.Marker(location=(home['lat'], home['lon']), tooltip='Home', icon=folium.Icon(color='red')).add_to(m)

    # iterate aircraft
    for ac in ac_list:
        lat, lon = ac['Lat'], ac['Long']
        alt_m = ac.get('Alt', 0) * 0.3048
        track = ac.get('Trak', 0)
        vel_ms = ac.get('Spd', 0) * 0.51444

        # draw aircraft
        folium.Marker(location=(lat, lon), tooltip=f"{ac.get('Call','')}", icon=folium.Icon(icon='plane', prefix='fa')).add_to(m)

        # compute shadows
        shadows = []
        if show_sun:
            sun_alt = get_altitude(home['lat'], home['lon'], now)
            if sun_alt > 0:
                sun_az = get_azimuth(home['lat'], home['lon'], now)
                d = alt_m / math.tan(math.radians(sun_alt))
                brng = (sun_az + 180) % 360
                shadows.append(('sun', d, brng, 'black'))
        if show_moon and ephem:
            obs = ephem.Observer(); obs.lat, obs.lon = str(home['lat']), str(home['lon']); obs.date = now
            moon = ephem.Moon(obs)
            moon_alt = math.degrees(moon.alt)
            if moon_alt > 0:
                moon_az = math.degrees(moon.az)
                d = alt_m / math.tan(math.radians(moon_alt))
                brng = (moon_az + 180) % 360
                shadows.append(('moon', d, brng, 'gray'))

        # draw shadow predictions
        for kind, dist, brng, col in shadows:
            # project shadow point
            R = 6378137
            d_rad = dist / R
            lat1 = math.radians(lat)
            lon1 = math.radians(lon)
            brng_rad = math.radians(brng)
            lat2 = math.asin(math.sin(lat1)*math.cos(d_rad) + math.cos(lat1)*math.sin(d_rad)*math.cos(brng_rad))
            lon2 = lon1 + math.atan2(math.sin(brng_rad)*math.sin(d_rad)*math.cos(lat1), math.cos(d_rad)-math.sin(lat1)*math.sin(lat2))
            folium.PolyLine(locations=[(lat, lon), (math.degrees(lat2), math.degrees(lon2))],
                            color=col, weight=2).add_to(m)

        # schedule alerts based on predicted shadow at 60s
        # (omitted: compute predicted lat/lon at time offset and check proximity)

    map_container.write(st_folium(m, height=600))
    time.sleep(1)
