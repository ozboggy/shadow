import streamlit as st
# Must be first Streamlit command
st.set_page_config(layout="wide")

import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
from pysolar.solar import get_altitude, get_azimuth
from math import radians, sin, cos, asin, sqrt
import csv
import os
import pandas as pd
import plotly.express as px

# Attempt to import pyfr24
try:
    from pyfr24 import FR24API
    HAS_FR24API = True
except ImportError:
    HAS_FR24API = False

# Load environment vars
try:
    from dotenv import load_dotenv
    load_dotenv()
    DOTENV_LOADED = True
except ImportError:
    DOTENV_LOADED = False

# Sidebar warnings after config
if not HAS_FR24API:
    st.sidebar.warning("pyfr24 not installed; using feed.js fallback for FlightRadar24 data.")
if not DOTENV_LOADED:
    st.sidebar.warning("python-dotenv not installed; skipping .env loading.")

OPENSKY_USER = os.getenv("OPENSKY_USERNAME")
OPENSKY_PASS = os.getenv("OPENSKY_PASSWORD")
FR24_API_KEY = os.getenv("FLIGHTRADAR_API_KEY")

# Pushover setup
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY", "")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN", "")

def send_pushover(title: str, message: str):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
    except Exception:
        pass

# Title and refresh
st.markdown("<meta http-equiv='refresh' content='30'>", unsafe_allow_html=True)
st.title("✈️ Aircraft Shadow Forecast")

# Sidebar controls
st.sidebar.header("Select Time")
selected_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
selected_time = st.sidebar.time_input("Time (UTC)", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(selected_date, selected_time).replace(tzinfo=timezone.utc)

data_source = st.sidebar.selectbox("Data Source", ("OpenSky", "FlightRadar24"), index=1)

# Constants
TARGET_LAT = -33.7603831919607
TARGET_LON = 150.971709164045
HOME_LAT = -33.7603831919607
HOME_LON = 150.971709164045
RADIUS_KM = 20
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
ALERT_RADIUS_METERS = 50

# Helpers
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1); dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2*R*asin(sqrt(a))

def move_position(lat, lon, heading_deg, distance_m):
    R = 6371000
    heading_rad = math.radians(heading_deg)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(sin(lat1)*cos(distance_m/R) + cos(lat1)*sin(distance_m/R)*cos(heading_rad))
    lon2 = lon1 + math.atan2(sin(heading_rad)*sin(distance_m/R)*cos(lat1),
                             cos(distance_m/R)-sin(lat1)*sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

# Setup log file
log_file = "alert_log.csv"
if not os.path.exists(log_file):
    with open(log_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC","Callsign","Time Until Alert (sec)","Lat","Lon"])

# Initialize map state
if "zoom" not in st.session_state: st.session_state.zoom = 12
if "center" not in st.session_state: st.session_state.center = [HOME_LAT, HOME_LON]

try:
    center = [float(x) for x in st.session_state.center]
except:
    center = [HOME_LAT, HOME_LON]
    st.session_state.center = center

fmap = folium.Map(location=center, zoom_start=st.session_state.zoom)
marker_cluster = MarkerCluster().add_to(fmap)
folium.Marker((TARGET_LAT, TARGET_LON), icon=folium.Icon(color="red"), popup="Target").add_to(fmap)

# Fetch aircraft data
north, south, west, east = -33.0, -34.5, 150.0, 151.5
aircraft_states = []

if data_source == "OpenSky":
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url, auth=(OPENSKY_USER, OPENSKY_PASS))
        r.raise_for_status()
        aircraft_states = r.json().get("states", [])
    except Exception as e:
        st.error(f"Error fetching OpenSky data: {e}")
else:
    # FlightRadar24 fetch with feed.js fallback
    flights = []
    if HAS_FR24API and FR24_API_KEY:
        try:
            api = FR24API(FR24_API_KEY)
            resp = api.get_flight_positions_light(f"{south},{west},{north},{east}")
            if isinstance(resp, dict):
                flights = resp.get("data", [])
            elif isinstance(resp, list):
                flights = resp
        except Exception:
            flights = []
    if not flights:
        try:
            r2 = requests.get(
                "https://data-live.flightradar24.com/zones/fcgi/feed.js",
                params={"bounds":f"{south},{west},{north},{east}","adsb":1,"mlat":1,"flarm":1,"array":1}
            )
            r2.raise_for_status()
            raw = r2.json()
            for k, v in raw.items():
                if k in ("full_count","version","stats"): continue
                if isinstance(v, list) and v:
                    flights.extend(v if isinstance(v[0], list) else [v])
        except Exception:
            pass
    def safe_get(lst, idx, default=None):
        return lst[idx] if isinstance(lst, list) and idx < len(lst) else default
    for p in flights:
        lat = safe_get(p, 1); lon = safe_get(p, 2)
        if lat is None or lon is None: continue
        vel = safe_get(p, 4, 0) or 0; hdg = safe_get(p, 3, 0) or 0
        alt = safe_get(p, 13); alt = alt if alt is not None else (safe_get(p, 11, 0) or 0)
        cs = safe_get(p, -1, "") or "N/A"
        aircraft_states.append([None, cs, None, None, None, lon, lat, None, vel, hdg, alt, None, None, None, None])

# Process aircraft and calculate shadows
alerts_triggered = []
for state in aircraft_states:
    try:
        if data_source == "OpenSky":
            icao24, callsign, origin_country, time_position, last_contact, lon, lat, baro_altitude, on_ground, velocity, true_track, vertical_rate, sensors, geo_altitude, squawk, spi, position_source = state[:17]
            if lat is None or lon is None or velocity is None or true_track is None or baro_altitude is None:
                continue
            altitude_m = baro_altitude
            heading_deg = true_track
            speed_mps = velocity
        else:
            _, callsign, _, _, _, lon, lat, _, velocity, true_track, altitude_m = state[:11]
            if lat is None or lon is None:
                continue
            heading_deg = true_track if true_track else 0
            speed_mps = velocity if velocity else 0
            altitude_m = altitude_m if altitude_m else 0

        callsign = (callsign or "N/A").strip()

        # Calculate sun position
        sun_alt = get_altitude(lat, lon, selected_time)
        if sun_alt <= 0:
            continue  # No shadow if sun is below horizon
        sun_az = get_azimuth(lat, lon, selected_time)

        # Shadow offset from aircraft
        shadow_distance_m = altitude_m / math.tan(math.radians(sun_alt))
        shadow_bearing = (sun_az + 180) % 360

        shadow_lat, shadow_lon = move_position(lat, lon, shadow_bearing, shadow_distance_m)

        # Distance from shadow to target
        dist_to_target = haversine(shadow_lat, shadow_lon, TARGET_LAT, TARGET_LON)

        # Add aircraft marker
        popup_text = f"{callsign}<br>Alt: {altitude_m:.0f}m<br>Spd: {speed_mps:.1f}m/s<br>Hdg: {heading_deg:.0f}°<br>Shadow: {dist_to_target:.0f}m from target"
        folium.Marker(
            (lat, lon),
            icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
            popup=popup_text
        ).add_to(marker_cluster)

        # Add shadow marker
        shadow_color = "green" if dist_to_target > ALERT_RADIUS_METERS else "orange"
        folium.CircleMarker(
            (shadow_lat, shadow_lon),
            radius=3,
            color=shadow_color,
            fill=True,
            fillColor=shadow_color,
            fillOpacity=0.6,
            popup=f"Shadow of {callsign}"
        ).add_to(fmap)

        # Draw line from aircraft to shadow
        folium.PolyLine(
            [(lat, lon), (shadow_lat, shadow_lon)],
            color="gray",
            weight=1,
            opacity=0.5
        ).add_to(fmap)

        # Forecast future positions
        forecast_points = []
        alert_time = None

        for i in range(1, int(FORECAST_DURATION_MINUTES * 60 / FORECAST_INTERVAL_SECONDS) + 1):
            dt_seconds = i * FORECAST_INTERVAL_SECONDS
            future_time = selected_time + timedelta(seconds=dt_seconds)

            # Move aircraft
            distance_traveled = speed_mps * dt_seconds
            future_lat, future_lon = move_position(lat, lon, heading_deg, distance_traveled)

            # Recalculate sun position at future time
            future_sun_alt = get_altitude(future_lat, future_lon, future_time)
            if future_sun_alt <= 0:
                continue
            future_sun_az = get_azimuth(future_lat, future_lon, future_time)

            # Future shadow position
            future_shadow_dist = altitude_m / math.tan(math.radians(future_sun_alt))
            future_shadow_bearing = (future_sun_az + 180) % 360
            future_shadow_lat, future_shadow_lon = move_position(
                future_lat, future_lon, future_shadow_bearing, future_shadow_dist
            )

            forecast_points.append((future_shadow_lat, future_shadow_lon))

            # Check if shadow passes near target
            future_dist = haversine(future_shadow_lat, future_shadow_lon, TARGET_LAT, TARGET_LON)
            if future_dist < ALERT_RADIUS_METERS and alert_time is None:
                alert_time = dt_seconds
                alerts_triggered.append({
                    "callsign": callsign,
                    "time_until": dt_seconds,
                    "lat": future_shadow_lat,
                    "lon": future_shadow_lon
                })

                # Log alert
                with open(log_file, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        datetime.utcnow().isoformat(),
                        callsign,
                        dt_seconds,
                        future_shadow_lat,
                        future_shadow_lon
                    ])

                # Send pushover notification
                send_pushover(
                    "Aircraft Shadow Alert!",
                    f"{callsign} shadow will pass within {ALERT_RADIUS_METERS}m in {dt_seconds}s"
                )

        # Draw forecast path
        if forecast_points:
            folium.PolyLine(
                forecast_points,
                color="purple" if alert_time else "lightblue",
                weight=2,
                opacity=0.7,
                popup=f"{callsign} forecast"
            ).add_to(fmap)

            # Mark alert point if exists
            if alert_time:
                folium.CircleMarker(
                    forecast_points[int(alert_time / FORECAST_INTERVAL_SECONDS) - 1],
                    radius=5,
                    color="red",
                    fill=True,
                    fillColor="red",
                    fillOpacity=0.8,
                    popup=f"{callsign} alert in {alert_time}s"
                ).add_to(fmap)

    except Exception as e:
        st.sidebar.error(f"Error processing aircraft: {e}")
        continue

# Draw target radius
folium.Circle(
    (TARGET_LAT, TARGET_LON),
    radius=ALERT_RADIUS_METERS,
    color="red",
    fill=True,
    fillColor="red",
    fillOpacity=0.2,
    popup=f"Alert radius: {ALERT_RADIUS_METERS}m"
).add_to(fmap)

# Display map
map_output = st_folium(fmap, width=1400, height=700, key="map")

# Update map state if user interacted
if map_output and map_output.get("zoom"):
    st.session_state.zoom = map_output["zoom"]
if map_output and map_output.get("center"):
    st.session_state.center = map_output["center"]

# Display alerts
if alerts_triggered:
    st.warning(f"⚠️ {len(alerts_triggered)} shadow alert(s)!")
    for alert in alerts_triggered:
        st.error(f"🎯 **{alert['callsign']}** shadow will pass target in **{alert['time_until']}** seconds!")
else:
    st.success("✅ No shadow alerts in the forecast period.")

# Statistics
st.subheader("📊 Statistics")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Aircraft Tracked", len(aircraft_states))
with col2:
    st.metric("Shadows Visible", sum(1 for _ in aircraft_states))
with col3:
    st.metric("Active Alerts", len(alerts_triggered))

# Log viewer
st.subheader("📋 Alert Log")
if os.path.exists(log_file):
    try:
        df = pd.read_csv(log_file)
        if not df.empty:
            st.dataframe(df.tail(20), use_container_width=True)

            # Download button
            csv_data = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Full Log",
                data=csv_data,
                file_name="aircraft_shadow_alerts.csv",
                mime="text/csv"
            )

            # Visualization
            if len(df) > 1:
                st.subheader("📈 Alert Timeline")
                df['Time UTC'] = pd.to_datetime(df['Time UTC'])
                fig = px.scatter(
                    df,
                    x='Time UTC',
                    y='Callsign',
                    size='Time Until Alert (sec)',
                    color='Callsign',
                    title='Shadow Alerts Over Time',
                    hover_data=['Lat', 'Lon']
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No alerts logged yet.")
    except Exception as e:
        st.error(f"Error reading log: {e}")
else:
    st.info("No alert log file found.")

# Settings info
st.sidebar.subheader("⚙️ Settings")
st.sidebar.info(f"""
**Target Location:**
Lat: {TARGET_LAT}
Lon: {TARGET_LON}

**Search Radius:** {RADIUS_KM} km
**Alert Radius:** {ALERT_RADIUS_METERS} m
**Forecast Duration:** {FORECAST_DURATION_MINUTES} min
**Forecast Interval:** {FORECAST_INTERVAL_SECONDS} sec
""")
