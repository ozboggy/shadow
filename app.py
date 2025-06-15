
import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
from pysolar.solar import get_altitude, get_azimuth

import math
from math import radians, cos, sin, asin, sqrt


st.set_page_config(layout="wide")
st.markdown("""
    <meta http-equiv="refresh" content="30">
""", unsafe_allow_html=True)

st.title("🔮 Aircraft Shadow Forecast (5-min Prediction)")

st.sidebar.header("🕒 Select Time")
selected_date = st.sidebar.date_input("📅 UTC Date", value=datetime.utcnow().date())
selected_time_only = st.sidebar.time_input("⏰ UTC Time", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)

FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5

TARGET_LAT = -33.7575936
TARGET_LON = 150.9687296
ALERT_RADIUS_METERS = 300

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

def move_position(lat, lon, heading_deg, distance_m):
    R = 6371000
    heading_rad = math.radians(heading_deg)
    d = distance_m

    lat1 = math.radians(lat)
    lon1 = math.radians(lon)

    lat2 = math.asin(math.sin(lat1)*math.cos(d/R) + math.cos(lat1)*math.sin(d/R)*math.cos(heading_rad))
    lon2 = lon1 + math.atan2(math.sin(heading_rad)*math.sin(d/R)*math.cos(lat1), math.cos(d/R)-math.sin(lat1)*math.sin(lat2))

    return math.degrees(lat2), math.degrees(lon2)

# Sydney bounding box
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


import csv
import os

alerts_triggered = []
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)

# Ensure file exists with header
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon"])



home_lat = -33.7608864
home_lon = 150.9709575
RADIUS_KM = 24.14

filtered_states = []
for ac in aircraft_states:
    try:
        _, _, _, _, _, lon, lat, *_ = ac
        if lat is not None and lon is not None:
            distance_km = haversine(lat, lon, home_lat, home_lon) / 1000
            if distance_km <= RADIUS_KM:
                filtered_states.append(ac)
    except:
        continue

for ac in filtered_states:

    try:
        icao24, callsign, origin_country, time_position, last_contact, lon, lat, baro_altitude, on_ground, velocity, heading, vertical_rate, sensors, geo_altitude, squawk, spi, position_source = ac

        if lat is not None and lon is not None and heading is not None and velocity is not None:
            alt = geo_altitude if geo_altitude is not None else 0
            callsign = callsign.strip() if callsign else "N/A"

            trail = []
            shadow_alerted = False

            for i in range(0, FORECAST_DURATION_MINUTES * 60 + 1, FORECAST_INTERVAL_SECONDS):
                future_time = selected_time + timedelta(seconds=i)
                dist_moved = velocity * i
                future_lat, future_lon = move_position(lat, lon, heading, dist_moved)
                sun_alt = get_altitude(future_lat, future_lon, future_time)
                sun_az = get_azimuth(future_lat, future_lon, future_time)

                if sun_alt > 0 and alt > 0:
                    shadow_dist = alt / math.tan(math.radians(sun_alt))
                    shadow_lat = future_lat + (shadow_dist / 111111) * math.cos(math.radians(sun_az + 180))
                    shadow_lon = future_lon + (shadow_dist / (111111 * math.cos(math.radians(future_lat)))) * math.sin(math.radians(sun_az + 180))

                    trail.append((shadow_lat, shadow_lon))

                    if not shadow_alerted and haversine(shadow_lat, shadow_lon, TARGET_LAT, TARGET_LON) <= ALERT_RADIUS_METERS:
                        
alerts_triggered.append((callsign, int(i), shadow_lat, shadow_lon))
with open(log_path, "a", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([datetime.utcnow().isoformat(), callsign, int(i), shadow_lat, shadow_lon])

                        shadow_alerted = True

            if trail:
                folium.PolyLine(
                    trail,
                    color="black",
                    weight=2,
                    opacity=0.7,
                    dash_array="5,5",
                    tooltip=f"{callsign} (shadow forecast)"
                ).add_to(fmap)

            folium.Marker(
                location=(lat, lon),
                icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
                popup=f"Callsign: {callsign}\\nAlt: {round(alt)} m"
            ).add_to(marker_cluster)

    except Exception as e:
        st.warning(f"⚠️ Error processing aircraft: {e}")

if alerts_triggered:
    
    st.error("🚨 Forecast ALERT! Shadow will cross target:")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
    st.markdown(f'''
    <script>
        new Notification("✈️ Shadow Alert", {{
            body: "An aircraft shadow will pass over the target area!",
            icon: "https://cdn-icons-png.flaticon.com/512/684/684908.png"
        }});
    </script>
    ''', unsafe_allow_html=True)
    
        for cs, t, _, _ in alerts_triggered:
    
        st.write(f"✈️ {cs} — in approx. {t} seconds")
else:
    st.success("✅ No forecast shadow paths intersect target area.")

st_folium(fmap, width=1000, height=700)


import pandas as pd
import plotly.express as px

if os.path.exists(log_path):
    st.sidebar.markdown("### 📥 Download Alert Log")
    with open(log_path, "rb") as f:
        st.sidebar.download_button(
            label="Download alert_log.csv",
            data=f,
            file_name="alert_log.csv",
            mime="text/csv"
        )

    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        df_recent = df_log.sort_values(by="Time UTC", ascending=False).head(10)

        st.markdown("### 📊 Recent Shadow Alerts (Last 10)")
        st.dataframe(df_recent)

        st.markdown("### ⏳ Alerts Over Time")
        fig = px.scatter(df_log, x="Time UTC", y="Callsign", size="Time Until Alert (sec)",
                         hover_data=["Lat", "Lon"], title="Alert Timing vs Aircraft")
        st.plotly_chart(fig, use_container_width=True)
