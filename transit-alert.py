import streamlit as st
import requests
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
from pysolar.solar import get_altitude, get_azimuth
import csv
import os
import pandas as pd
import plotly.express as px

# ---------------- Pushover setup ----------------
PUSHOVER_USER_KEY = "usasa4y2iuvz75krztrma829s21nvy"
PUSHOVER_API_TOKEN = "adxez5u3zqqxyta3pdvdi5sdvwovxv"

def send_pushover(title, message, user_key, api_token):
    try:
        url = "https://api.pushover.net/1/messages.json"
        payload = {"token": api_token, "user": user_key, "title": title, "message": message}
        requests.post(url, data=payload)
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# -------------- Streamlit Page Config -------------
st.set_page_config(layout="wide")
auto_refresh = st.sidebar.checkbox("Auto Refresh Map", value=True)
refresh_interval = st.sidebar.number_input("Refresh Interval (s)", min_value=1, value=10)
if auto_refresh:
    st.markdown(f"<meta http-equiv='refresh' content='{refresh_interval}'>", unsafe_allow_html=True)
st.title("✈️ Aircraft Shadow Forecast")

# ---------------- Sidebar Inputs ------------------
st.sidebar.header("Select Time (UTC)")
selected_date = st.sidebar.date_input("Date", value=datetime.utcnow().date())
selected_time_only = st.sidebar.time_input("Time", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(selected_date, selected_time_only).replace(tzinfo=timezone.utc)

# ---------------- Map & Alert Settings ----------------
st.sidebar.header("Map & Alert Settings")
zoom_level = st.sidebar.slider("Map Zoom Level", 1, 18, st.session_state.get("zoom", 11))
search_radius_km = st.sidebar.slider("Search Radius (km)", 1, 100, 20)
shadow_width = st.sidebar.slider("Shadow Path Width", 1, 10, 2)
target_radius_m = st.sidebar.slider("Alert Radius (m)", 1, 1000, 50)
enable_onscreen_alert = st.sidebar.checkbox("Enable Onscreen Alert", True)
debug_mode = st.sidebar.checkbox("Debug Mode", False)
if st.sidebar.button("Send Pushover Test"):
    send_pushover("✈️ Test Alert", "This is a Pushover test notification.", PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN)
    st.sidebar.success("Pushover test sent!")
if st.sidebar.button("Test Onscreen Alert"):
    if enable_onscreen_alert:
        st.error("🚨 TEST Shadow ALERT!")
        st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
        st.markdown(
            """
            <script>
            if (Notification.permission === 'granted') {
                new Notification("✈️ Shadow Alert", { body: "This is a test onscreen alert." });
            } else {
                Notification.requestPermission().then(p => {
                    if (p === 'granted') {
                        new Notification("✈️ Shadow Alert", { body: "This is a test onscreen alert." });
                    }
                });
            }
            </script>
            """, unsafe_allow_html=True)
        st.write("🚨 This is a test onscreen alert!")
    else:
        st.sidebar.warning("Onscreen alerts are disabled.")

# ---------------- Additional Sidebar Controls ----------------
tile_style = st.sidebar.selectbox(
    "Map Tile Style",
    ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter", "Stamen Terrain", "Stamen Toner"],
    index=1
)
# Data source selection
data_source = st.sidebar.selectbox(
    "Data Source",
    [ "OpenSky", "ADS-B Exchange" ],
    index=0
)
track_sun = st.sidebar.checkbox("Show Sun Shadows", True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", False)
override_trails = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", False)

# ---------------- Constants ----------------
FORECAST_INTERVAL_SECONDS = 10
FORECAST_DURATION_MINUTES = 5
HOME_LAT = -33.7597655
HOME_LON = 150.9723678
TARGET_LAT = HOME_LAT
TARGET_LON = HOME_LON
RADIUS_KM = search_radius_km

# ---------------- Utils Functions ---------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def move_position(lat, lon, heading_deg, distance_m):
    R = 6371000
    heading_rad = math.radians(heading_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    d = distance_m
    lat2 = math.asin(math.sin(lat1)*math.cos(d/R) + math.cos(lat1)*math.sin(d/R)*math.cos(heading_rad))
    lon2 = lon1 + math.atan2(math.sin(heading_rad)*math.sin(d/R)*math.cos(lat1), math.cos(d/R)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

# ---------------- Logging setup ----------------
log_path = os.path.join(os.path.dirname(__file__), "alert_log.csv")
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon"])

# ---------------- Fetch Aircraft Data ------------
aircraft_states = []
# Attempt to fetch from ADS-B Exchange if selected
if data_source == "ADS-B Exchange":
    adsb_url = f"https://public-api.adsbexchange.com/VirtualRadar/AircraftList.json?lat={HOME_LAT}&lng={HOME_LON}&fDstL=0&fDstU={RADIUS_KM}"
    try:
        r = requests.get(adsb_url, timeout=10)
        r.raise_for_status()
        adsb_data = r.json()
        ac_list = adsb_data.get("acList")
        if not ac_list:
            raise ValueError("Empty acList")
        for ac in ac_list:
            aircraft_states.append({
                "callsign": ac.get("Callsign"),
                "lat": ac.get("Lat"),
                "lon": ac.get("Long"),
                "velocity": ac.get("Spd"),
                "heading": ac.get("Trak"),
                "alt": ac.get("Alt")
            })
    except Exception as e:
        st.warning(f"ADS-B Exchange error ({e}), falling back to OpenSky")
        data_source = "OpenSky"
# Fetch from OpenSky if selected or fallback
if data_source == "OpenSky":
    north = HOME_LAT + 0.5
    south = HOME_LAT - 1.0
    west = HOME_LON - 1.0
    east = HOME_LON + 1.0
    opensky_url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(opensky_url, timeout=10)
        r.raise_for_status()
        opensky_data = r.json()
        states = opensky_data.get("states", []) or []
        for ac in states:
            aircraft_states.append({
                "callsign": (ac[1].strip() or "N/A"),
                "lat": ac[6],
                "lon": ac[5],
                "velocity": ac[9],
                "heading": ac[10],
                "alt": ac[13] or 0
            })
    except Exception as e:
        st.error(f"Error fetching data from OpenSky: {e}")
        aircraft_states = []
# ---------------- Initialize Map ----------------
st.session_state.zoom = zoom_level
fmap = folium.Map(location=[HOME_LAT, HOME_LON], zoom_start=zoom_level, tiles=tile_style)
marker_cluster = MarkerCluster().add_to(fmap)
folium.Marker((TARGET_LAT, TARGET_LON), icon=folium.Icon(color="red", icon="home", prefix="fa"), popup="Home").add_to(fmap)

# ---------------- Process each aircraft -------------
alerts_triggered = []
for ac in aircraft_states:
    cs = ac["callsign"]
    lat = ac["lat"]
    lon = ac["lon"]
    velocity = ac["velocity"]
    heading = ac["heading"]
    alt = ac["alt"]
    if None in (lat, lon, velocity, heading) or velocity <= 0 or alt <= 0:
        continue
    if haversine(lat, lon, HOME_LAT, HOME_LON)/1000 > RADIUS_KM:
        continue
    trail = []
    shadow_alerted = False
    for i in range(0, FORECAST_DURATION_MINUTES*60+1, FORECAST_INTERVAL_SECONDS):
        future_time = selected_time + timedelta(seconds=i)
        fut_lat, fut_lon = move_position(lat, lon, heading, velocity * i)
        sun_alt = get_altitude(fut_lat, fut_lon, future_time)
        sun_az = get_azimuth(fut_lat, fut_lon, future_time)
        if debug_mode and track_sun:
            st.sidebar.write(f"Debug: {cs} t+{i}s pos=({fut_lat:.4f},{fut_lon:.4f}), sun_alt={sun_alt:.2f}")
            st.sidebar.write(ac)
        if sun_alt > 0 and track_sun:
            shadow_dist = alt / math.tan(math.radians(sun_alt))
            s_lat = fut_lat + (shadow_dist/111111) * math.cos(math.radians(sun_az+180))
            s_lon = fut_lon + (shadow_dist/(111111*math.cos(math.radians(fut_lat)))) * math.sin(math.radians(sun_az+180))
            trail.append((s_lat, s_lon))
            if not shadow_alerted and haversine(s_lat, s_lon, TARGET_LAT, TARGET_LON) <= target_radius_m:
                alerts_triggered.append((cs, i, s_lat, s_lon))
                with open(log_path, "a", newline="") as f:
                    csv.writer(f).writerow([datetime.utcnow().isoformat(), cs, i, s_lat, s_lon])
                shadow_alerted = True
    if trail and (track_sun or override_trails):
        folium.PolyLine(trail, weight=shadow_width, dash_array="5,5", tooltip=cs).add_to(fmap)
    folium.Marker((lat, lon), icon=folium.Icon(color="blue", icon="plane", prefix="fa"), popup=f"{cs} Alt:{round(alt)}m").add_to(marker_cluster)

# ---------------- Alerts & Pushover ----------------
if alerts_triggered and enable_onscreen_alert:
    for cs, t, la, lo in alerts_triggered:
        send_pushover("✈️ Shadow Alert", f"{cs} in {t}s at ({la:.4f},{lo:.4f})", PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN)
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
    st.markdown("""
    <script>
    if(Notification.permission==='granted') new Notification("✈️ Shadow Alert",{body:"Aircraft shadow over home!"});
    else Notification.requestPermission().then(p=>{if(p==='granted') new Notification("✈️ Shadow Alert",{body:"Aircraft shadow over home!"});});
    </script>
    """, unsafe_allow_html=True)
    for cs, t, _, _ in alerts_triggered:
        st.write(f"✈️ {cs} — in approx. {t} seconds")
else:
    st.success("✅ No forecast shadow paths intersect home area.")

# ---------------- Logs & Charts ----------------
if os.path.exists(log_path):
    st.sidebar.markdown("### 📥 Download Log")
    with open(log_path,'rb') as f:
        st.sidebar.download_button("Download alert_log.csv",f,file_name="alert_log.csv",mime="text/csv")
    df = pd.read_csv(log_path)
    if not df.empty:
        df['Time UTC'] = pd.to_datetime(df['Time UTC'])
        st.markdown("### 📊 Recent Alerts")
        st.dataframe(df.tail(10))
        fig = px.scatter(df, x="Time UTC", y="Callsign", size="Time Until Alert (sec)", hover_data=["Lat","Lon"], title="Shadow Alerts Over Time")
        st.plotly_chart(fig, use_container_width=True)

# ---------------- Render Map ----------------
map_data = st_folium(fmap, width=1000, height=700)
if map_data and "zoom" in map_data:
    st.session_state.zoom = map_data["zoom"]
    st.session_state.center = map_data.get("center")
