import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import folium
from folium.features import DivIcon
from streamlit_folium import st_folium
from datetime import datetime, timezone, timedelta
import math
import requests
import pandas as pd
import plotly.express as px
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth

# Pushover configuration (set these in your .env)
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        st.warning("Pushover credentials not set in environment.")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# Log file setup
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        f.write("Time UTC,Callsign,Time Until Alert (sec),Lat,Lon,Source\n")

# Defaults
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
DEFAULT_SHADOW_WIDTH = 2
DEFAULT_ZOOM = 11

# Sidebar
with st.sidebar:
    st.header("Map Options")
    tile_style = st.selectbox("Tile Style", ["OpenStreetMap", "CartoDB positron"], index=0)
    data_source = st.selectbox("Data Source", ["OpenSky", "ADS-B Exchange"], index=0)
    radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    st.markdown(f"**Search Radius:** {radius_km} km")
    alert_radius_m = st.slider("Shadow Alert Radius (m)", 1, 10000, 50)
    st.markdown(f"**Shadow Alert Radius:** {alert_radius_m} m")
    track_sun = st.checkbox("Show Sun Shadows", True)
    track_moon = st.checkbox("Show Moon Shadows", False)
    override_trails = st.checkbox("Show Trails Regardless of Sun/Moon", False)
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")
    st.header("Map Settings")
    zoom_level = st.slider("Initial Zoom Level", 1, 18, DEFAULT_ZOOM)
    map_width = st.number_input("Width (px)", 400, 2000, 600)
    map_height = st.number_input("Height (px)", 300, 1500, 600)
    
        # Alert History in sidebar
    st.markdown("---")
    st.markdown("### 📥 Download Log")
    if os.path.exists(log_path):
        with open(log_path, "rb") as log_file_obj:
            st.download_button(
                "Download alert_log.csv",
                log_file_obj,
                file_name="alert_log.csv",
                mime="text/csv"
            )
        df_log = pd.read_csv(log_path)
        if not df_log.empty:
            df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
            st.markdown("### 🕑 Recent Alerts")
            recent = (
                df_log[['Time UTC', 'Callsign', 'Time Until Alert (sec)']]
                .sort_values('Time UTC', ascending=False)
                .head(5)
            )
            st.dataframe(recent)
    st.markdown("---")
    st.markdown("### 🕑 Recent Alerts")
    if os.path.exists(log_path):
        df_log = pd.read_csv(log_path)
        if not df_log.empty:
            df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
            recent = df_log[['Time UTC', 'Callsign', 'Time Until Alert (sec)']].sort_values('Time UTC', ascending=False).head(5)
            st.dataframe(recent)
    st.markdown("---")
# Current UTC time"
selected_time = datetime.utcnow().replace(tzinfo=timezone.utc)

# Title
st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

# Pydeck map with incremental aircraft updates
df_ac = pd.DataFrame(aircraft_list)
# Base view
view_state = pdk.ViewState(
    latitude=CENTER_LAT,
    longitude=CENTER_LON,
    zoom=zoom_level,
    pitch=0
)
# Icon data: use a plane icon URL or emojis
df_ac['icon_data'] = df_ac.apply(lambda ac: {
    "url": "https://raw.githubusercontent.com/Concept211/Google-Maps-Markers/master/images/marker_plane.png",
    "width": 128,
    "height": 128,
    "anchorY": 128
}, axis=1)
# Icon layer
icon_layer = pdk.Layer(
    "IconLayer",
    df_ac,
    get_icon="icon_data",
    get_size=4,
    size_scale=15,
    get_position=["lon", "lat"],
    pickable=True
)
# Trail Layer (Scatterplot for end points)
trail_points = []
for ac in aircraft_list:
    lat, lon, baro, vel, hdg, cs = ac.values()
    # only plot current position for pydeck
    trail_points.append({"lat": lat, "lon": lon, "callsign": cs})
df_trail = pd.DataFrame(trail_points)
trail_layer = pdk.Layer(
    "ScatterplotLayer",
    df_trail,
    get_position=["lon", "lat"],
    get_color=[0, 0, 255, 160],
    get_radius=50,
)
# Render pydeck chart
deck = pdk.Deck(
    layers=[icon_layer, trail_layer],
    initial_view_state=view_state,
    tooltip={"text": "{callsign}"}
)
st.pydeck_chart(deck)

# Alerts UI will follow
alerts = []
for ac in aircraft_list:
    lat, lon, baro, vel, hdg, cs = ac.values()
    alert = False; trail = []
    for i in range(0, FORECAST_DURATION_MINUTES*60+1, FORECAST_INTERVAL_SECONDS):
        ft = selected_time + timedelta(seconds=i)
        f_lat, f_lon = move_position(lat, lon, hdg, vel * i)
        sun_alt = get_sun_altitude(f_lat, f_lon, ft)
        if (track_sun and sun_alt > 0) or (track_moon and sun_alt <= 0) or override_trails:
            az = get_sun_azimuth(f_lat, f_lon, ft)
            sd = baro / math.tan(math.radians(sun_alt if sun_alt>0 else 1))
            sh_lat = f_lat + (sd/111111) * math.cos(math.radians(az+180))
            sh_lon = f_lon + (sd/(111111*math.cos(math.radians(f_lat)))) * math.sin(math.radians(az+180))
            trail.append((sh_lat, sh_lon))
            if hav(sh_lat, sh_lon, CENTER_LAT, CENTER_LON) <= alert_radius_m:
                alert = True
    if alert: alerts.append(cs)
    folium.Marker(
        location=(lat, lon),
        icon=DivIcon(
            icon_size=(30,30), icon_anchor=(15,15),
            html=(
                f"<i class='fa fa-plane' style='transform:rotate({hdg-90}deg); "
                f"color:{'red' if alert else 'blue'}; font-size:24px;'></i>"
            )
        ),
        popup=f"{cs}\nAlt: {baro} m\nSpd: {vel} m/s"
    ).add_to(fmap)
    if trail:
        folium.PolyLine(locations=trail, color="red" if alert else "black", weight=shadow_width, opacity=0.6).add_to(fmap)

# Alerts UI
if alerts:
    alist = ", ".join(alerts)
    st.error(f"🚨 Shadow ALERT for: {alist}")
    st.markdown(
        """
        <audio autoplay loop>
          <source src='https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg' type='audio/ogg'>
        </audio>
        """, unsafe_allow_html=True
    )
    send_pushover("✈️ Shadow ALERT", f"Shadows detected for: {alist}")
else:
    st.success("✅ No forecast shadow paths intersect target area.")

# Render map and preserve view
map_data = st_folium(
    fmap,
    width=map_width,
    height=map_height,
    returned_objects=['zoom', 'center'],
    key='aircraft_map'
)
if map_data and 'zoom' in map_data and 'center' in map_data:
    st.session_state.zoom = map_data['zoom']
    st.session_state.center = map_data['center']

# Remove expander block (history now in sidebar)

# Test buttons
if test_alert:
    st.error("🚨 Test Alert Triggered!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
if test_pushover:
    st.info("🔔 Sending test Pushover notification...")
    send_pushover("✈️ Test Push", "This is a test shadow alert.")
if test_alert:
    st.error("🚨 Test Alert Triggered!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
if test_pushover:
    st.info("🔔 Sending test Pushover notification...")
    send_pushover("✈️ Test Push", "This is a test shadow alert.")
