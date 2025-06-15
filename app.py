
import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime
import math

st.set_page_config(layout="wide")
st.title("✈️ OpenSky Aircraft Shadow Tracker - Western Sydney")

st.sidebar.header("🔧 Settings")

# Define bounding box for Western Sydney
north = st.sidebar.number_input("North Latitude", value=-33.0)
south = st.sidebar.number_input("South Latitude", value=-34.5)
west = st.sidebar.number_input("West Longitude", value=150.0)
east = st.sidebar.number_input("East Longitude", value=151.5)

# Optional: OpenSky Basic Auth (optional, helps with rate limit)
username = st.sidebar.text_input("OpenSky Username (optional)")
password = st.sidebar.text_input("OpenSky Password", type="password")

# Fetch OpenSky data
def fetch_opensky_aircraft(north, south, west, east, username=None, password=None):
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        if username and password:
            r = requests.get(url, auth=(username, password))
        else:
            r = requests.get(url)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Error fetching OpenSky data: {e}")
        return {}

# Calculate solar elevation angle
def solar_elevation(lat, lon, date_time):
    day_of_year = date_time.timetuple().tm_yday
    decl = 23.44 * math.cos(math.radians((360 / 365) * (day_of_year - 81)))
    hour_angle = 15 * (date_time.hour + date_time.minute / 60 - 12)
    elevation = math.degrees(math.asin(
        math.sin(math.radians(lat)) * math.sin(math.radians(decl)) +
        math.cos(math.radians(lat)) * math.cos(math.radians(decl)) * math.cos(math.radians(hour_angle))
    ))
    return elevation

# Main logic
data = fetch_opensky_aircraft(north, south, west, east, username, password)
aircraft_states = data.get("states", [])
st.write(f"✅ Found {len(aircraft_states)} aircraft in the selected region.")

map_center = [(north + south) / 2, (east + west) / 2]
fmap = folium.Map(location=map_center, zoom_start=9)
marker_cluster = MarkerCluster().add_to(fmap)

now = datetime.utcnow()
for ac in aircraft_states:
    icao24, callsign, origin_country, time_position, last_contact, lon, lat, baro_altitude, on_ground, velocity, heading, vertical_rate, sensors, geo_altitude, squawk, spi, position_source = ac

    if lat is not None and lon is not None and geo_altitude is not None:
        alt = geo_altitude
        heading = heading or 0
        callsign = callsign.strip() if callsign else "N/A"

        shadow_distance = alt / math.tan(math.radians(max(1, solar_elevation(lat, lon, now))))
        shadow_lat = lat - (shadow_distance / 111111) * math.cos(math.radians(heading))
        shadow_lon = lon - (shadow_distance / (111111 * math.cos(math.radians(lat)))) * math.sin(math.radians(heading))

        folium.Marker(
            location=(lat, lon),
            icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
            popup=f"Callsign: {callsign}\nAlt: {round(alt)} m"
        ).add_to(marker_cluster)

        folium.CircleMarker(
            location=(shadow_lat, shadow_lon),
            radius=5,
            color='black',
            fill=True,
            fill_color='black',
            fill_opacity=0.5,
            popup=f"Shadow of {callsign}"
        ).add_to(fmap)

st_folium(fmap, width=1000, height=700)
