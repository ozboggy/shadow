
import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone
import math
from pysolar.solar import get_altitude, get_azimuth

st.set_page_config(layout="wide")
st.title("✈️ Aircraft Shadow Tracker with Alert")

st.sidebar.header("🕒 Select Time")

selected_date = st.sidebar.date_input("📅 UTC Date", value=datetime.utcnow().date())
selected_time_only = st.sidebar.time_input("⏰ UTC Time", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)

st.sidebar.caption("Simulates sunlight and aircraft shadows.")

TARGET_LAT = -33.7575936
TARGET_LON = 150.9687296
ALERT_RADIUS_METERS = 300

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # meters
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# OpenSky bounding box (Sydney region)
north, south, west, east = -33.0, -34.5, 150.0, 151.5
url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
try:
    r = requests.get(url)
    r.raise_for_status()
    data = r.json()
except Exception as e:
    st.error(f"Error fetching OpenSky data: {e}")
    data = {}

aircraft_states = data.get("states", [])
st.write(f"✅ Found {len(aircraft_states)} aircraft entries.")
fmap = folium.Map(location=[(north + south)/2, (east + west)/2], zoom_start=9)
marker_cluster = MarkerCluster().add_to(fmap)

folium.Marker(
    location=(TARGET_LAT, TARGET_LON),
    icon=folium.Icon(color="red", icon="flag"),
    popup="Target Alert Location"
).add_to(fmap)

alerts_triggered = []

for ac in aircraft_states:
    try:
        icao24, callsign, origin_country, time_position, last_contact, lon, lat, baro_altitude, on_ground, velocity, heading, vertical_rate, sensors, geo_altitude, squawk, spi, position_source = ac
        if lat is not None and lon is not None:
            alt = geo_altitude if geo_altitude is not None else 0
            callsign = callsign.strip() if callsign else "N/A"
            sun_alt = get_altitude(lat, lon, selected_time)
            sun_az = get_azimuth(lat, lon, selected_time)

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

                dist = haversine(TARGET_LAT, TARGET_LON, shadow_lat, shadow_lon)
                if dist <= ALERT_RADIUS_METERS:
                    alerts_triggered.append((callsign, dist))
    except Exception as e:
        st.warning(f"⚠️ Error processing aircraft: {e}")

if alerts_triggered:
    st.error("🚨 ALERT! Shadow over target location:")
    for cs, d in alerts_triggered:
        st.write(f"✈️ {cs} — approx. {int(d)} meters away")
else:
    st.success("✅ No aircraft shadows over the target at this time.")

st_folium(fmap, width=1000, height=700)
