
import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime
import math

st.set_page_config(layout="wide")
st.title("✈️ FlightRadar24 Aircraft Shadow Tracker - Western Sydney [DEBUG MODE]")

st.sidebar.header("🔧 Settings")

# FR24 token input
fr24_token = st.sidebar.text_input("Enter your FR24 session token", type="password")

# Bounding box around Western Sydney
north = st.sidebar.number_input("North Latitude", value=-33.0)
south = st.sidebar.number_input("South Latitude", value=-34.5)
west = st.sidebar.number_input("West Longitude", value=150.0)
east = st.sidebar.number_input("East Longitude", value=151.5)

# Fetch FR24 data
def fetch_fr24_aircraft(token, north, south, west, east):
    url = f"https://data-cloud.flightradar24.com/zones/fcgi/feed.js?bounds={north},{south},{west},{east}&faa=1&mlat=1&flarm=1&adsb=1&gnd=1&air=1&vehicles=0&estimated=1&maxage=14400"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Cookie": f"fr24_cookie={token}"
    }
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Error fetching FR24 data: {e}")
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

if fr24_token:
    data = fetch_fr24_aircraft(fr24_token, north, south, west, east)
    st.subheader("🔍 API Raw Response (DEBUG)")
    st.write(data)

    aircraft_data = {k: v for k, v in data.items() if isinstance(v, dict)}
    st.write(f"✅ Found {len(aircraft_data)} aircraft.")

    if not aircraft_data:
        st.warning("No aircraft found or token might be invalid. Try expanding the area or double-check your token.")

    map_center = [(north + south) / 2, (east + west) / 2]
    fmap = folium.Map(location=map_center, zoom_start=9)
    marker_cluster = MarkerCluster().add_to(fmap)

    now = datetime.utcnow()
    for k, ac in aircraft_data.items():
        if 'lat' in ac and 'lon' in ac and 'altitude' in ac:
            lat, lon, alt = ac['lat'], ac['lon'], ac['altitude']
            heading = ac.get('track', 0)
            callsign = ac.get('callsign', 'N/A')
            shadow_distance = alt / math.tan(math.radians(max(1, solar_elevation(lat, lon, now))))
            shadow_lat = lat - (shadow_distance / 111111) * math.cos(math.radians(heading))
            shadow_lon = lon - (shadow_distance / (111111 * math.cos(math.radians(lat)))) * math.sin(math.radians(heading))

            folium.Marker(
                location=(lat, lon),
                icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
                popup=f"Callsign: {callsign}\nAlt: {alt} ft"
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
else:
    st.info("Enter your FR24 token in the sidebar to begin.")
