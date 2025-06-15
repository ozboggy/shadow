
import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone
import math
from pysolar.solar import get_altitude, get_azimuth

st.set_page_config(layout="wide")
st.title("🔎 DEBUG: OpenSky Aircraft Shadow Tracker (Fixed Timezone)")

st.sidebar.header("🔧 Settings")

north = st.sidebar.number_input("North Latitude", value=-33.0)
south = st.sidebar.number_input("South Latitude", value=-34.5)
west = st.sidebar.number_input("West Longitude", value=150.0)
east = st.sidebar.number_input("East Longitude", value=151.5)

username = st.sidebar.text_input("OpenSky Username (optional)")
password = st.sidebar.text_input("OpenSky Password", type="password")

selected_date = st.sidebar.date_input("📅 Select UTC Date", value=datetime.utcnow().date())
selected_time_only = st.sidebar.time_input("⏰ Select UTC Time", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)

st.sidebar.caption("Use this to simulate time of day for sun position.")

def fetch_opensky_aircraft(north, south, west, east, username=None, password=None):
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url, auth=(username, password)) if username and password else requests.get(url)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Error fetching OpenSky data: {e}")
        return {}

data = fetch_opensky_aircraft(north, south, west, east, username, password)
st.subheader("🧾 Raw API Response")
st.json(data)

aircraft_states = data.get("states", [])
st.write(f"✅ Found {len(aircraft_states)} aircraft entries.")

fmap = folium.Map(location=[(north + south)/2, (east + west)/2], zoom_start=9)
marker_cluster = MarkerCluster().add_to(fmap)

sun_state_message_shown = False

for ac in aircraft_states:
    try:
        icao24, callsign, origin_country, time_position, last_contact, lon, lat, baro_altitude, on_ground, velocity, heading, vertical_rate, sensors, geo_altitude, squawk, spi, position_source = ac

        if lat is not None and lon is not None:
            alt = geo_altitude if geo_altitude is not None else 0
            callsign = callsign.strip() if callsign else "N/A"

            sun_alt = get_altitude(lat, lon, selected_time)
            sun_az = get_azimuth(lat, lon, selected_time)

            st.write(f"🛩️ {callsign}: lat={lat}, lon={lon}, alt={alt}m, sun_elev={sun_alt:.2f}°, sun_az={sun_az:.2f}°")

            folium.Marker(
                location=(lat, lon),
                icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
                popup=f"Callsign: {callsign}\nAlt: {round(alt)} m"
            ).add_to(marker_cluster)

            folium.Marker(
                location=(lat + 0.01, lon + 0.01),
                icon=folium.DivIcon(html=f"<div style='font-size: 10pt'>{callsign}</div>")
            ).add_to(fmap)

            if sun_alt > 0 and alt > 0:
                shadow_dist = alt / math.tan(math.radians(sun_alt))
                shadow_lat = lat + (shadow_dist / 111111) * math.cos(math.radians(sun_az + 180))
                shadow_lon = lon + (shadow_dist / (111111 * math.cos(math.radians(lat)))) * math.sin(math.radians(sun_az + 180))

                st.write(f"    ➤ Shadow at lat={shadow_lat:.5f}, lon={shadow_lon:.5f}, dist={shadow_dist:.1f}m")

                folium.CircleMarker(
                    location=(shadow_lat, shadow_lon),
                    radius=5,
                    color='black',
                    fill=True,
                    fill_color='black',
                    fill_opacity=0.6,
                    popup=f"Shadow of {callsign}"
                ).add_to(fmap)

                folium.PolyLine(
                    locations=[(lat, lon), (shadow_lat, shadow_lon)],
                    color='gray',
                    weight=2,
                    opacity=0.6,
                    tooltip=f"{callsign} ➝ Shadow"
                ).add_to(fmap)
            else:
                st.write("    🚫 Sun is below horizon — shadow not drawn.")
    except Exception as e:
        st.warning(f"⚠️ Error processing aircraft: {e}")

st_folium(fmap, width=1000, height=700)
