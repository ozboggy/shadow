import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import distance
from geopy import Point
from math import tan, radians
from datetime import datetime
from astral import LocationInfo
from astral.location import Location

st.set_page_config(layout="wide")
st.title("Advanced Aircraft Shadow Predictor ☀️✈️")

col1, col2 = st.columns(2)

with col1:
    lat = st.number_input("Aircraft Latitude", value=35.6895)
    lon = st.number_input("Aircraft Longitude", value=139.6917)
    altitude = st.number_input("Altitude (in meters)", value=3000)
    heading = st.slider("Aircraft Heading (° from North)", 0, 359, 90)

with col2:
    now = st.datetime_input("Select Date and Time (UTC)", value=datetime.utcnow())
    st.markdown("Note: All times are in UTC")

# Calculate sun position using Astral
location = LocationInfo(name="Custom", region="Nowhere", latitude=lat, longitude=lon)
loc = Location(location)
loc.timezone = 'UTC'

try:
    elevation_angle = loc.solar_elevation(now)
    azimuth_angle = loc.solar_azimuth(now)
except:
    elevation_angle = 0
    azimuth_angle = 0

st.write(f"🕒 **UTC Time:** {now.strftime('%Y-%m-%d %H:%M:%S')}")
st.write(f"☀️ **Sun Elevation:** {elevation_angle:.2f}°")
st.write(f"🧭 **Sun Azimuth:** {azimuth_angle:.2f}°")

# Calculate shadow position
if elevation_angle > 0:
    shadow_distance = altitude / tan(radians(elevation_angle))
    aircraft_point = Point(lat, lon)
    shadow_point = distance(meters=shadow_distance).destination(aircraft_point, azimuth_angle)

    # Map rendering
    m = folium.Map(location=[lat, lon], zoom_start=13)
    folium.Marker([lat, lon], popup="Aircraft", icon=folium.Icon(color="blue")).add_to(m)
    folium.Marker([shadow_point.latitude, shadow_point.longitude], popup="Shadow", icon=folium.Icon(color="black")).add_to(m)
    folium.PolyLine([(lat, lon), (shadow_point.latitude, shadow_point.longitude)], color="gray").add_to(m)

    st_folium(m, width=1000, height=600)
else:
    st.warning("☀️ The sun is below the horizon. No shadow can be calculated at this time.")