import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import distance
from geopy import Point
from math import tan, radians
from datetime import datetime
from astral import LocationInfo
from astral.sun import sun

st.title("Live Aircraft Shadow Predictor ☀️✈️")

lat = st.number_input("Aircraft Latitude", value=35.6895)
lon = st.number_input("Aircraft Longitude", value=139.6917)
altitude = st.number_input("Altitude (in meters)", value=3000)

now = datetime.utcnow()

# Calculate sun position using Astral
location = LocationInfo(latitude=lat, longitude=lon)
s = sun(location.observer, date=now, tzinfo='UTC')
elevation_angle = location.solar_elevation(now)
azimuth_angle = location.solar_azimuth(now)

st.write(f"📅 UTC Time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
st.write(f"☀️ Sun Elevation: {elevation_angle:.2f}°")
st.write(f"🧭 Sun Azimuth: {azimuth_angle:.2f}°")

# Calculate shadow location
if elevation_angle > 0:
    shadow_distance = altitude / tan(radians(elevation_angle))
    aircraft_point = Point(lat, lon)
    shadow_point = distance(meters=shadow_distance).destination(aircraft_point, azimuth_angle)

    # Map
    m = folium.Map(location=[lat, lon], zoom_start=13)
    folium.Marker([lat, lon], popup="Aircraft", icon=folium.Icon(color="blue")).add_to(m)
    folium.Marker([shadow_point.latitude, shadow_point.longitude], popup="Shadow", icon=folium.Icon(color="black")).add_to(m)
    folium.PolyLine([(lat, lon), (shadow_point.latitude, shadow_point.longitude)], color="gray").add_to(m)

    st_folium(m, width=700, height=500)
else:
    st.warning("☀️ The sun is below the horizon. No shadow can be calculated at this time.")