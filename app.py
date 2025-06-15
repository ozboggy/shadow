import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import distance
from geopy import Point
from math import tan, radians

st.title("Aircraft Shadow Predictor 🌞✈️")

lat = st.number_input("Aircraft Latitude", value=35.6895)
lon = st.number_input("Aircraft Longitude", value=139.6917)
altitude = st.number_input("Altitude (in meters)", value=3000)
elevation = st.slider("Sun Elevation Angle (°)", 1, 89, 55)
azimuth = st.slider("Sun Azimuth Angle (° from North)", 0, 359, 150)

# Calculate shadow location
shadow_distance = altitude / tan(radians(elevation))
aircraft_point = Point(lat, lon)
shadow_point = distance(meters=shadow_distance).destination(aircraft_point, azimuth)

# Create folium map
m = folium.Map(location=[lat, lon], zoom_start=13)
folium.Marker([lat, lon], popup="Aircraft", icon=folium.Icon(color="blue")).add_to(m)
folium.Marker([shadow_point.latitude, shadow_point.longitude], popup="Shadow", icon=folium.Icon(color="black")).add_to(m)
folium.PolyLine([(lat, lon), (shadow_point.latitude, shadow_point.longitude)], color="gray").add_to(m)

# Display map
st_folium(m, width=700, height=500)