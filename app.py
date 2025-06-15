import streamlit as st
import requests
from datetime import datetime
from math import tan, radians, cos, sin
from geopy.distance import distance
from geopy import Point
import folium
from streamlit_folium import st_folium
from astral import LocationInfo
from astral.location import Location

st.set_page_config(layout="wide")
st.title("Enhanced Aircraft Shadow Tracker ✈️ with OpenSky")

# Settings
st.sidebar.header("🔍 Filter Settings")
center_lat = st.sidebar.number_input("Center Latitude", value=35.6895)
center_lon = st.sidebar.number_input("Center Longitude", value=139.6917)
radius_km = st.sidebar.slider("Search Radius (km)", 10, 300, 100)
min_altitude = st.sidebar.number_input("Minimum Altitude (m)", value=500)
max_aircraft = st.sidebar.slider("Max Aircraft to Show", 1, 25, 5)
callsign_filter = st.sidebar.text_input("Filter by Callsign (optional)")
refresh_interval = st.sidebar.selectbox("Auto-Refresh Interval", [0, 10, 30, 60], index=2)

# Refresh
if refresh_interval > 0:
    st.experimental_rerun()

now = datetime.utcnow()
st.write(f"🕒 **Current UTC Time:** {now.strftime('%Y-%m-%d %H:%M:%S')}")

# Bounding box
lat_margin = radius_km / 111
lon_margin = radius_km / (111 * abs(cos(radians(center_lat))))
min_lat = center_lat - lat_margin
max_lat = center_lat + lat_margin
min_lon = center_lon - lon_margin
max_lon = center_lon + lon_margin

@st.cache_data(ttl=refresh_interval if refresh_interval else 60)
def fetch_opensky():
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

aircraft_data = fetch_opensky()

m = folium.Map(location=[center_lat, center_lon], zoom_start=7)
count = 0

for ac in aircraft_data:
    try:
        icao, callsign, origin_country, _, _, lon, lat, geo_alt, _, heading = ac[:10]
        if not all([lat, lon, geo_alt]) or geo_alt < min_altitude:
            continue
        if callsign_filter and callsign_filter.upper() not in (callsign or ""):
            continue

        # Sun position
        location = LocationInfo(latitude=lat, longitude=lon)
        loc = Location(location)
        loc.timezone = 'UTC'
        elev_angle = loc.solar_elevation(now, observer_elevation=0)
        az_angle = loc.solar_azimuth(now, observer_elevation=0)

        if elev_angle <= 0:
            continue

        # Shadow point
        shadow_dist = geo_alt / tan(radians(elev_angle))
        aircraft_pt = Point(lat, lon)
        shadow_pt = distance(meters=shadow_dist).destination(aircraft_pt, az_angle)

        # Heading vector
        heading_point = distance(meters=5000).destination(aircraft_pt, heading or 0)

        # Markers
        folium.Marker([lat, lon],
                      popup=f"{callsign or 'N/A'} ({origin_country})\nAlt: {int(geo_alt)} m",
                      icon=folium.Icon(color="blue")).add_to(m)
        folium.Marker([shadow_pt.latitude, shadow_pt.longitude],
                      popup="Shadow",
                      icon=folium.Icon(color="black")).add_to(m)
        folium.PolyLine([(lat, lon), (shadow_pt.latitude, shadow_pt.longitude)], color="gray").add_to(m)
        folium.PolyLine([(lat, lon), (heading_point.latitude, heading_point.longitude)], color="green", dash_array="5").add_to(m)

        count += 1
        if count >= max_aircraft:
            break

    except Exception as e:
        continue

st.success(f"🛩️ Displaying {count} aircraft with shadow projections")
st_folium(m, width=1000, height=600)