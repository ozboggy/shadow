import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import folium
from folium.features import DivIcon
from streamlit_folium import st_folium
from datetime import datetime, timezone, timedelta
import math
import requests
import pandas as pd
import plotly.express as px
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth

# Cache the base map to avoid flickering
@st.cache_resource
def create_base_map(center_lat, center_lon, zoom, tile_style):
    fmap = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        tiles=tile_style,
        control_scale=True
    )
    folium.Marker(
        [center_lat, center_lon],
        icon=folium.Icon(color="red", icon="home", prefix="fa"),
        popup="Home"
    ).add_to(fmap)
    return fmap

# Sidebar and config
CENTER_LAT, CENTER_LON = -33.7602563, 150.9717434
with st.sidebar:
    st.header("Map Options")
    tile_style = st.selectbox("Tile Style", ["OpenStreetMap", "CartoDB positron"], index=0)
    zoom_level = st.slider("Initial Zoom Level", 1, 18, 11)
    map_width = st.number_input("Width (px)", 400, 2000, 1200)
    map_height = st.number_input("Height (px)", 300, 1500, 700)

# Cached map instance
fmap = create_base_map(CENTER_LAT, CENTER_LON, zoom_level, tile_style)

# Dynamic Aircraft markers (FeatureGroup to avoid re-rendering base map)
aircraft_fg = folium.FeatureGroup(name="Aircraft Positions")

# Dummy aircraft data for demonstration
aircraft_list = [
    {'lat': -33.76, 'lon': 150.97, 'baro': 1000, 'vel': 200, 'hdg': 90, 'callsign': 'AC123'},
    {'lat': -33.75, 'lon': 150.98, 'baro': 1200, 'vel': 250, 'hdg': 180, 'callsign': 'AC456'}
]

# Marker placement
for ac in aircraft_list:
    lat, lon, baro, vel, hdg, cs = ac.values()
    folium.Marker(
        location=(lat, lon),
        icon=DivIcon(
            icon_size=(30, 30), icon_anchor=(15, 15),
            html=f"<i class='fa fa-plane' style='transform:rotate({hdg-90}deg); color:blue; font-size:24px;'></i>"
        ),
        popup=f"{cs}\nAlt: {baro} m\nSpd: {vel} m/s"
    ).add_to(aircraft_fg)

aircraft_fg.add_to(fmap)

# Render map once
map_data = st_folium(
    fmap,
    width=map_width,
    height=map_height,
    returned_objects=['zoom', 'center'],
    key='aircraft_map'
)

# Preserve map zoom and center
if map_data:
    st.session_state.zoom = map_data.get('zoom', zoom_level)
    st.session_state.center = map_data.get('center', [CENTER_LAT, CENTER_LON])

# Display aircraft list
st.subheader("Tracked Aircraft")
st.table(pd.DataFrame(aircraft_list))
