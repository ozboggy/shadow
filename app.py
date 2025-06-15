import streamlit as st
import requests
from datetime import datetime
from math import tan, radians
from geopy.distance import distance
from geopy import Point
import folium
from streamlit_folium import st_folium
from astral import LocationInfo
from astral.location import Location

st.set_page_config(layout="wide")
st.title("Live Aircraft Shadow Predictor with OpenSky ✈️🌍")

# User inputs for bounding box
col1, col2 = st.columns(2)
with col1:
    center_lat = st.number_input("Center Latitude", value=35.6895)
    center_lon = st.number_input("Center Longitude", value=139.6917)
    radius_km = st.slider("Search Radius (km)", 10, 300, 100)

with col2:
    now = datetime.utcnow()
    st.markdown(f"**Current UTC Time:** {now.strftime('%Y-%m-%d %H:%M:%S')}")
    show_all = st.checkbox("Show All Aircraft in Range", value=False)

# Compute bounding box
lat_margin = radius_km / 111  # approx 1 deg ≈ 111 km
lon_margin = radius_km / (111 * abs(radians(center_lat)))

min_lat = center_lat - lat_margin
max_lat = center_lat + lat_margin
min_lon = center_lon - lon_margin
max_lon = center_lon + lon_margin

# Fetch data from OpenSky API
@st.cache_data(ttl=30)
def fetch_opensky_aircraft():
    url = "https://opensky-network.org/api/states/all"
    params = {
        "lamin": min_lat,
        "lamax": max_lat,
        "lomin": min_lon,
        "lomax": max_lon
    }
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json().get("states", [])
    except Exception as e:
        st.error(f"OpenSky API error: {e}")
        return []

aircraft_data = fetch_opensky_aircraft()

# Create map
m = folium.Map(location=[center_lat, center_lon], zoom_start=7)

count = 0
for ac in aircraft_data:
    if not all([ac[5], ac[6], ac[7]]):  # skip if lat/lon/alt missing
        continue
    callsign = ac[1].strip() if ac[1] else "N/A"
    lat, lon, geo_alt = ac[6], ac[5], ac[7]

    # Get sun position
    try:
        location = LocationInfo(latitude=lat, longitude=lon)
        loc = Location(location)
        loc.timezone = 'UTC'
        elevation_angle = loc.solar_elevation(now, observer_elevation=0)
        azimuth_angle = loc.solar_azimuth(now, observer_elevation=0)
    except:
        continue

    if elevation_angle <= 0:
        continue

    # Compute shadow
    shadow_dist = geo_alt / tan(radians(elevation_angle))
    shadow_point = distance(meters=shadow_dist).destination(Point(lat, lon), azimuth_angle)

    folium.Marker([lat, lon], popup=f"Aircraft: {callsign}", icon=folium.Icon(color="blue")).add_to(m)
    folium.Marker([shadow_point.latitude, shadow_point.longitude], popup="Shadow", icon=folium.Icon(color="black")).add_to(m)
    folium.PolyLine([(lat, lon), (shadow_point.latitude, shadow_point.longitude)], color="gray").add_to(m)

    count += 1
    if not show_all and count >= 1:
        break

st.write(f"🛫 Showing {count} aircraft in range")
st_folium(m, width=1000, height=600)