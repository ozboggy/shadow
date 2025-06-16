# ---- Shadow Alert Utilities ----
LOG_FILE = "alert_log.csv"

def haversine(lat1, lon1, lat2, lon2):
    from math import radians, cos, sin, asin, sqrt
    R = 6371000  # meters
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def log_alert(callsign, shadow_lat, shadow_lon):
    try:
        with open(LOG_FILE, "a") as logf:
            logf.write(f"{datetime.utcnow()},{callsign},{shadow_lat},{shadow_lon}\n")
    except Exception as e:
        st.warning(f"⚠️ Failed to log alert: {e}")

import streamlit as st
import requests
import json
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime
from math import radians, cos, sin
from datetime import timezone
from pysolar.solar import get_altitude
import math
from time import time
import os
import time
import csv

st.set_page_config(layout="wide")

# ---- Constants ----
DEFAULT_HOME = [-33.7608864, 150.9709575]
DEFAULT_ZOOM = 14

# ---- Load last map state if available ----
def load_map_config():
    try:
        with open("map_config.json", "r") as f:
            cfg = json.load(f)
            center = cfg.get("center", DEFAULT_HOME)
            if (not isinstance(center, list) or len(center) != 2 or
                not all(isinstance(x, (int, float)) for x in center)):
                center = DEFAULT_HOME
            zoom = cfg.get("zoom", DEFAULT_ZOOM)
            return {"center": center, "zoom": zoom}
    except Exception:
        return {"zoom": DEFAULT_ZOOM, "center": DEFAULT_HOME}
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

# ---- Load aircraft from OpenSky ----
bounds = fmap.get_bounds() if hasattr(fmap, 'get_bounds') else None
home_latlon = [home_lat, home_lon]
aircraft_data = []
try:
    resp = requests.get(
        'https://opensky-network.org/api/states/all',
        params={'lamin': home_lat - 0.3, 'lamax': home_lat + 0.3,
                'lomin': home_lon - 0.3, 'lomax': home_lon + 0.3},
        timeout=10
    )
    data = resp.json() if resp.ok else {}
    states = data.get("states", [])
    for state in states:
        if not state or len(state) < 8: continue
        lat, lon, alt = state[6], state[5], state[7]
        if lat is None or lon is None or alt is None: continue
        aircraft_data.append((state[1], lat, lon, alt))
except Exception as e:
    st.warning(f"Failed to load aircraft: {e}")
# ---- Predict and display shadows ----
now = datetime.utcnow().replace(tzinfo=timezone.utc)
sun_elevation = get_altitude(home_lat, home_lon, now)
if sun_elevation > 0:
    for callsign, lat, lon, alt in aircraft_data:
        try:
            theta = radians(90 - sun_elevation)
            shadow_length = alt / math.tan(theta)
            dx = shadow_length * cos(radians(180))
            dy = shadow_length * sin(radians(180))
            shadow_lat = lat + (dy / 111111)
            shadow_lon = lon + (dx / (111111 * cos(radians(lat))))
            icon = folium.Icon(icon='plane', prefix='fa', color='blue')
            folium.Marker(location=[lat, lon], icon=icon, tooltip=callsign).add_to(fmap)
            folium.CircleMarker(location=[shadow_lat, shadow_lon], radius=3, color='gray',
                                fill=True, fill_opacity=0.5, tooltip='Shadow').add_to(fmap)
            if haversine(shadow_lat, shadow_lon, home_lat, home_lon) < alert_radius:
                log_alert(callsign, shadow_lat, shadow_lon)
                alert_log.append((callsign, shadow_lat, shadow_lon))
                alert_triggered = True
        except Exception as se:
            continue
# ---- Example aircraft (you can replace this with real data feed later) ----
folium.CircleMarker(location=DEFAULT_HOME, radius=8, color="red", fill=True, fill_opacity=0.6, tooltip="Home").add_to(fmap)
folium.Marker(location=[home_lat + 0.01, home_lon + 0.01], tooltip="Aircraft A1").add_to(fmap)
        folium.Marker(location=[lat, lon], icon=icon, tooltip=callsign).add_to(fmap)

# ---- Render map and capture state ----
map_output = st_folium(fmap, width=1400, height=800)

# ---- Save new center/zoom ----
if map_output and "zoom" in map_output and "center" in map_output:
    save_map_config(map_output["zoom"], map_output["center"])

# ---- Alert and Auto-Refresh ----
if alert_triggered:
    st.error("🚨 Shadow over home location!")

st.markdown("⏱ Auto-refresh every 30 seconds...")
time.sleep(30)
st.experimental_rerun()
