import streamlit as st
st.set_page_config(layout="wide")  # MUST be first Streamlit command

import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
import requests
import os
from dotenv import load_dotenv
load_dotenv()
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth

# Constants
DEFAULT_TARGET_LAT = -33.7602563
DEFAULT_TARGET_LON = 150.9717434
DEFAULT_RADIUS_KM = 20
DEFAULT_ALERT_RADIUS_METERS = 50
DEFAULT_FORECAST_INTERVAL_SECONDS = 30
DEFAULT_FORECAST_DURATION_MINUTES = 5
DEFAULT_SHADOW_WIDTH = 3

# Sidebar controls
map_theme = st.sidebar.selectbox("Map Theme", ["CartoDB Positron", "CartoDB Dark_Matter", "OpenStreetMap"], index=0)
RADIUS_KM = st.sidebar.slider("Aircraft Search Radius (km)", 5, 100, DEFAULT_RADIUS_KM)
alert_rad = st.sidebar.slider("Alert Radius (m)", 10, 500, DEFAULT_ALERT_RADIUS_METERS)
ofs = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", value=False)
track_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", value=False)

# Time selection
sel_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
sel_time = st.sidebar.time_input("Time (UTC)", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(sel_date, sel_time).replace(tzinfo=timezone.utc)

st.title("✈️ Aircraft Shadow Tracker (OpenSky)")

# Map init
center = (DEFAULT_TARGET_LAT, DEFAULT_TARGET_LON)
fmap = folium.Map(location=center, zoom_start=8, tiles=None, control_scale=True, prefer_canvas=True)
folium.TileLayer(map_theme, name=map_theme).add_to(fmap)
folium.TileLayer("CartoDB Positron", name="Positron").add_to(fmap)
folium.TileLayer("CartoDB Dark_Matter", name="Dark Matter").add_to(fmap)
folium.TileLayer("OpenStreetMap", name="OSM").add_to(fmap)
folium.LayerControl(collapsed=False).add_to(fmap)

# Home marker
folium.Marker(center, icon=folium.Icon(color="red", icon="home", prefix="fa"), popup="Home").add_to(fmap)

# Fetch OpenSky data
delta = RADIUS_KM / 111.0
south, north = DEFAULT_TARGET_LAT - delta, DEFAULT_TARGET_LAT + delta
delta_lon = delta / math.cos(math.radians(DEFAULT_TARGET_LAT))
west, east = DEFAULT_TARGET_LON - delta_lon, DEFAULT_TARGET_LON + delta_lon
url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
try:
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    states = data.get("states", [])
except:
    st.error("Failed to fetch OpenSky data.")
    states = []

# Rendering layers
ac_layer = folium.FeatureGroup(name="Airplanes", show=True)
trail_layer = folium.FeatureGroup(name="Shadows", show=True)
fmap.add_child(ac_layer)
fmap.add_child(trail_layer)

# Utils
def move_position(lat, lon, heading, dist):
    R=6371000; hdr=math.radians(heading)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(math.sin(lat1)*math.cos(dist/R)+math.cos(lat1)*math.sin(dist/R)*math.cos(hdr))
    lon2 = lon1+math.atan2(math.sin(hdr)*math.sin(dist/R)*math.cos(lat1), math.cos(dist/R)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

def hav(lat1, lon1, lat2, lon2):
    R=6371000
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

# Loop
for st_data in states:
    icao, callsign, _, _, _, lon, lat, baro, _, vel, hdg, *_ = st_data
    if None in (lat, lon, vel, hdg): continue
    callsign = callsign.strip() or icao
    # Draw marker
    folium.Marker(location=(lat, lon), icon=folium.Icon(color="blue", icon="plane", prefix="fa"), popup=f"{callsign}\nAlt: {baro}m\nSpd: {vel} m/s").add_to(ac_layer)
    # Trail
    if (track_sun or track_moon or ofs):
        trail=[]
        for i in range(0, DEFAULT_FORECAST_DURATION_MINUTES*60+1, DEFAULT_FORECAST_INTERVAL_SECONDS):
            ft = selected_time + timedelta(seconds=i)
            dist = vel*i
            fl_lat, fl_lon = move_position(lat, lon, hdg, dist)
            sun_alt = get_sun_altitude(fl_lat, fl_lon, ft)
            if track_sun and sun_alt>0:
                az = get_sun_azimuth(fl_lat, fl_lon, ft)
            elif track_moon and sun_alt<=0:
                az = get_sun_azimuth(fl_lat, fl_lon, ft)
            elif ofs:
                az = get_sun_azimuth(fl_lat, fl_lon, ft)
            else:
                continue
            sd = baro/math.tan(math.radians(sun_alt if sun_alt>0 else 1))
            sh_lat = fl_lat + (sd/111111)*math.cos(math.radians(az+180))
            sh_lon = fl_lon + (sd/(111111*math.cos(math.radians(fl_lat))))*math.sin(math.radians(az+180))
            trail.append((sh_lat, sh_lon))
        if trail:
            folium.PolyLine(trail, color="black", weight=DEFAULT_SHADOW_WIDTH, opacity=0.6).add_to(trail_layer)

# Display map
st_map = st_folium(fmap, width=1200, height=800)
