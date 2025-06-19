import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import folium
from folium.plugins import PolyLineTextPath
from streamlit_folium import st_folium
import math
import requests
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth
from folium.features import DivIcon

# Constants
TARGET_LAT = -33.7571158
TARGET_LON = 150.9779155
DEFAULT_RADIUS_KM = 20
DEFAULT_INTERVAL_SEC = 30
DEFAULT_DURATION_MIN = 5
DEFAULT_SHADOW_WIDTH = 3
DEFAULT_ZOOM = 11

# Sidebar controls
st.sidebar.header("Configuration")

data_source = st.sidebar.selectbox(
    "Data Source",
    ["OpenSky", "ADS-B Exchange"],
    index=0
)

tile_style = st.sidebar.selectbox(
    "Map Tile Style",
    ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter", "Stamen Terrain", "Stamen Toner"],
    index=0
)

zoom_level = st.sidebar.slider("Map Zoom", min_value=1, max_value=18, value=DEFAULT_ZOOM)

track_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", value=False)
override_trails = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", value=False)

radius_km = st.sidebar.slider("Search Radius (km)", min_value=1, max_value=100, value=DEFAULT_RADIUS_KM)
forecast_interval = st.sidebar.slider("Forecast Interval (sec)", min_value=5, max_value=60, value=DEFAULT_INTERVAL_SEC, step=5)
forecast_duration = st.sidebar.slider("Forecast Duration (min)", min_value=1, max_value=60, value=DEFAULT_DURATION_MIN, step=1)
shadow_width = st.sidebar.slider("Shadow Width (px)", min_value=1, max_value=10, value=DEFAULT_SHADOW_WIDTH)
debug_mode = st.sidebar.checkbox("Debug raw response", value=False)
refresh_interval = st.sidebar.number_input("Auto-refresh Interval (sec)", min_value=0, max_value=300, value=0, step=10,
                                        help="0 = no auto-refresh; >0 to refresh")

# Use current UTC timestamp for calculations
today = datetime.utcnow().replace(tzinfo=timezone.utc)
selected_time = today

# Auto-refresh meta tag
if refresh_interval > 0:
    st.markdown(f'<meta http-equiv="refresh" content="{refresh_interval}">', unsafe_allow_html=True)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

# Helper to move position along bearing
def move_position(lat: float, lon: float, heading: float, dist: float) -> tuple:
    R = 6371000
    try:
        hdr = math.radians(float(heading))
        lat1 = math.radians(lat); lon1 = math.radians(lon)
    except:
        return lat, lon
    lat2 = math.asin(math.sin(lat1)*math.cos(dist/R) + math.cos(lat1)*math.sin(dist/R)*math.cos(hdr))
    lon2 = lon1 + math.atan2(
        math.sin(hdr)*math.sin(dist/R)*math.cos(lat1),
        math.cos(dist/R) - math.sin(lat1)*math.sin(lat2)
    )
    return math.degrees(lat2), math.degrees(lon2)

# Fetch from OpenSky
def fetch_opensky(lat: float, lon: float, radius: float) -> list:
    dr = radius / 111.0
    south, north = lat - dr, lat + dr
    dlon = dr / math.cos(math.radians(lat))
    west, east = lon - dlon, lon + dlon
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url); r.raise_for_status()
        if debug_mode: st.write("OpenSky raw:", r.text)
        states = r.json().get("states", [])
    except Exception as e:
        st.error(f"OpenSky error: {e}")
        return []
    acs = []
    for s in states:
        if len(s) < 11: continue
        try:
            cs = s[1].strip() or s[0]
            lat_f, lon_f = float(s[6]), float(s[5])
            baro = float(s[7] or 0)
            vel, hdg = float(s[9]), float(s[10])
        except:
            continue
        acs.append({"lat": lat_f, "lon": lon_f, "baro": baro, "vel": vel, "hdg": hdg, "callsign": cs})
    return acs

# Fetch from ADS-B Exchange
def fetch_adsb(lat: float, lon: float, radius: float) -> list:
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        st.error("Set RAPIDAPI_KEY in .env")
        return []
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{lat}/lon/{lon}/dist/{radius}/"
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
    try:
        r = requests.get(url, headers=headers); r.raise_for_status()
        if debug_mode: st.write("ADS-B raw:", r.text)
        ac_list = r.json().get("ac", [])
    except Exception as e:
        st.error(f"ADS-B error: {e}")
        return []
    acs = []
    for ac in ac_list:
        try:
            cs = (ac.get("flight") or ac.get("hex") or "").strip()
            lat_f, lon_f = float(ac.get("lat")), float(ac.get("lon"))
            baro = float(ac.get("alt_baro") or 0)
            vel = float(ac.get("gs") or ac.get("spd") or 0)
            hdg = float(ac.get("track") or ac.get("trak") or 0)
        except:
            continue
        acs.append({"lat": lat_f, "lon": lon_f, "baro": baro, "vel": vel, "hdg": hdg, "callsign": cs})
    return acs

# Calculate shadow trail
def calculate_trail(lat, lon, baro, vel, hdg) -> list:
    pts = []
    for i in range(0, int(forecast_duration*60)+1, forecast_interval):
        ft = selected_time + timedelta(seconds=i)
        dist = vel * i
        f_lat, f_lon = move_position(lat, lon, hdg, dist)
        sun_alt = get_sun_altitude(f_lat, f_lon, ft)
        if (track_sun and sun_alt>0) or (track_moon and sun_alt<=0) or override_trails:
            az = get_sun_azimuth(f_lat, f_lon, ft)
        else:
            continue
        angle = sun_alt if sun_alt>0 else 1
        sd = baro / math.tan(math.radians(angle))
        sh_lat = f_lat + (sd/111111)*math.cos(math.radians(az+180))
        sh_lon = f_lon + (sd/(111111*math.cos(math.radians(f_lat))))*math.sin(math.radians(az+180))
        pts.append((sh_lat, sh_lon))
    return pts

# Initialize and center map
fmap = folium.Map(location=(TARGET_LAT, TARGET_LON), zoom_start=zoom_level, tiles=tile_style, control_scale=True)
folium.Marker((TARGET_LAT, TARGET_LON), icon=folium.Icon(color="red", icon="home", prefix="fa"), popup="Home").add_to(fmap)

# Fetch aircraft
aircraft_list = fetch_opensky(TARGET_LAT, TARGET_LON, radius_km) if data_source=="OpenSky" else fetch_adsb(TARGET_LAT, TARGET_LON, radius_km)

# Sidebar aircraft count
st.sidebar.markdown("### Tracked Aircraft")
cnt = len(aircraft_list)
st.sidebar.write(f"{cnt} aircraft in range")
with st.sidebar.expander("Show details"):
    if cnt>0:
        for ac in aircraft_list:
            st.write(f"• {ac['callsign']} — Alt {ac['baro']} m, Spd {ac['vel']} m/s")
    else:
        st.write("No aircraft in range.")

# Plot aircraft and trails with direction arrows
for ac in aircraft_list:
    lat, lon, baro, vel, hdg, cs = ac['lat'], ac['lon'], ac['baro'], ac['vel'], ac['hdg'], ac['callsign']
    # Aircraft icon and label
    folium.Marker((lat, lon), icon=folium.Icon(color="blue", icon="plane", prefix="fa"), popup=f"{cs}\nAlt:{baro}m\nSpd:{vel}m/s").add_to(fmap)
    folium.map.Marker((lat,lon), icon=DivIcon(icon_size=(150,36), icon_anchor=(0,0), html=f'<div style="font-size:12px">{cs}</div>')).add_to(fmap)
    # Shadow trail
    trail = calculate_trail(lat, lon, baro, vel, hdg)
    if trail:
        # Add polyline
        line = folium.PolyLine(locations=trail, color="black", weight=shadow_width, opacity=0.6)
        line.add_to(fmap)
        # Add directional arrows as a separate layer
        arrow = PolyLineTextPath(
            line,
            '▶',
            repeat=True,
            offset=10,
            attributes={
                'fill': 'blue',
                'font-weight': 'bold',
                'font-size': '6px'
            }
        )
        arrow.add_to(fmap)

# Render map
st_folium(fmap, width=900, height=600)
