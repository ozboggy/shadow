
import streamlit as st
import requests
import json
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime
from math import radians, cos, sin
import os

st.set_page_config(layout="wide")

# ---- Constants ----
DEFAULT_HOME = [-33.7608864, 150.9709575]
DEFAULT_ZOOM = 14

# ---- Load last map state if available ----
def load_map_config():
    try:
        with open("map_config.json", "r") as f:
            return json.load(f)
    except Exception:
        return {"zoom": DEFAULT_ZOOM, "center": DEFAULT_HOME}

# ---- Save map state ----
def save_map_config(zoom, center):
    try:
        with open("map_config.json", "w") as f:
            json.dump({"zoom": zoom, "center": center}, f)
    except Exception as e:
        st.warning(f"⚠️ Failed to save map config: {e}")

# ---- UI ----
st.sidebar.title("🧭 Map Controls")
home_lat = st.sidebar.number_input("Home Latitude", value=DEFAULT_HOME[0], format="%.7f")
home_lon = st.sidebar.number_input("Home Longitude", value=DEFAULT_HOME[1], format="%.7f")
zoom_lock = st.sidebar.checkbox("🔒 Lock Zoom to 3-Mile Radius from Home", value=False)

map_config = load_map_config()
start_center = map_config.get("center", DEFAULT_HOME)
start_zoom = map_config.get("zoom", DEFAULT_ZOOM if not zoom_lock else 15)

# ---- Create map ----
fmap = folium.Map(location=start_center, zoom_start=start_zoom, control_scale=True)

# ---- Example aircraft (you can replace this with real data feed later) ----
folium.CircleMarker(location=DEFAULT_HOME, radius=8, color="red", fill=True, fill_opacity=0.6, tooltip="Home").add_to(fmap)
folium.Marker(location=[home_lat + 0.01, home_lon + 0.01], tooltip="Aircraft A1").add_to(fmap)

# ---- Render map and capture state ----
map_output = st_folium(fmap, width=1400, height=800)

# ---- Save new center/zoom ----
if map_output and "zoom" in map_output and "center" in map_output:
    save_map_config(map_output["zoom"], map_output["center"])
