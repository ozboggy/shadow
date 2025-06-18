import streamlit as st
st.set_page_config(layout="wide")  # Must be first Streamlit command

import folium
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
import requests
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth

# Constants
DEFAULT_TARGET_LAT = -33.7602563
DEFAULT_TARGET_LON = 150.9717434
DEFAULT_RADIUS_KM = 20
DEFAULT_ALERT_RADIUS_METERS = 50
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5

# Sidebar controls
tile_style = st.sidebar.selectbox(
    "Map Tile Style", 
    ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter", "Stamen Terrain", "Stamen Toner"],
    index=1
)
track_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", value=False)
override_trails = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", value=False)

# Time selection
sel_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
sel_time = st.sidebar.time_input("Time (UTC)", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(sel_date, sel_time).replace(tzinfo=timezone.utc)

st.title("✈️ Aircraft Shadow Tracker (OpenSky)")

# Fetch OpenSky data
halfrange = DEFAULT_RADIUS_KM / 111.0
south = DEFAULT_TARGET_LAT - halfrange
north = DEFAULT_TARGET_LAT + halfrange
delta_lon = halfrange / math.cos(math.radians(DEFAULT_TARGET_LAT))
west = DEFAULT_TARGET_LON - delta_lon
east = DEFAULT_TARGET_LON + delta_lon
url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
try:
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    states = data.get("states", [])
except Exception as e:
    st.error(f"Failed to fetch OpenSky data: {e}")
    states = []

# Initialize map with chosen style
center = (DEFAULT_TARGET_LAT, DEFAULT_TARGET_LON)
fmap = folium.Map(location=center, zoom_start=8, tiles=tile_style, control_scale=True)
# Home marker
folium.Marker(
    location=center,
    icon=folium.Icon(color="red", icon="home", prefix="fa"),
    popup="Home"
).add_to(fmap)

# Utilities
def move_position(lat, lon, heading, dist):
    R = 6371000
    hdr = math.radians(heading)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(math.sin(lat1)*math.cos(dist/R) + math.cos(lat1)*math.sin(dist/R)*math.cos(hdr))
    lon2 = lon1 + math.atan2(math.sin(hdr)*math.sin(dist/R)*math.cos(lat1), math.cos(dist/R) - math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Plot aircraft and shadows
for st_data in states:
    icao, callsign, _, _, _, lon, lat, baro, _, vel, hdg, *_ = st_data
    if None in (lat, lon, vel, hdg):
        continue
    callsign = callsign.strip() or icao
    # Marker
    folium.Marker(
        location=(lat, lon),
        icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
        popup=f"{callsign}\nAlt: {baro} m\nSpd: {vel} m/s"
    ).add_to(fmap)
    # Shadow trail
    if (track_sun or track_moon or override_trails):
        trail = []
        for i in range(0, FORECAST_DURATION_MINUTES*60+1, FORECAST_INTERVAL_SECONDS):
            future_t = selected_time + timedelta(seconds=i)
            dist_moved = vel * i
            f_lat, f_lon = move_position(lat, lon, hdg, dist_moved)
            sun_alt = get_sun_altitude(f_lat, f_lon, future_t)
            if track_sun and sun_alt > 0:
                az = get_sun_azimuth(f_lat, f_lon, future_t)
            elif track_moon and sun_alt <= 0:
                az = get_sun_azimuth(f_lat, f_lon, future_t)
            elif override_trails:
                az = get_sun_azimuth(f_lat, f_lon, future_t)
            else:
                continue
            sd = baro / math.tan(math.radians(sun_alt if sun_alt > 0 else 1))
            sh_lat = f_lat + (sd/111111)*math.cos(math.radians(az+180))
            sh_lon = f_lon + (sd/(111111*math.cos(math.radians(f_lat))))*math.sin(math.radians(az+180))
            trail.append((sh_lat, sh_lon))
        if trail:
            folium.PolyLine(
                locations=trail,
                color="black",
                weight=DEFAULT_SHADOW_WIDTH,
                opacity=0.6
            ).add_to(fmap)

# Display map
st_data = st_folium(fmap, width=1200, height=800)
