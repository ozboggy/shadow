import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
# Auto-refresh every second
from streamlit_autorefresh import st_autorefresh
st_autorefresh(interval=1_000, key="datarefresh")

# Pushover configuration
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
DEFAULT_ZOOM = 11

# Sidebar controls
with st.sidebar:
    st.header("Map Options")
    data_source = st.selectbox("Data Source", ["OpenSky", "ADS-B Exchange"], index=0)
    radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    alert_radius_m = st.slider("Shadow Alert Radius (m)", 1, 10000, 50)
    track_sun = st.checkbox("Show Sun Shadows", True)
    track_moon = st.checkbox("Show Moon Shadows", False)
    override_trails = st.checkbox("Show Trails Regardless of Sun/Moon", False)
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

# Current UTC time
selected_time = datetime.utcnow().replace(tzinfo=timezone.utc)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

# Fetch aircraft data
aircraft_list = []
if data_source == "OpenSky":
    dr = radius_km / 111.0
    south, north = CENTER_LAT - dr, CENTER_LAT + dr
    dlon = dr / math.cos(math.radians(CENTER_LAT))
    west, east = CENTER_LON - dlon, CENTER_LON + dlon
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url)
        r.raise_for_status()
        states = r.json().get("states", [])
    except:
        states = []
    for s in states:
        if len(s) < 11:
            continue
        cs = (s[1] or "").strip() or s[0]
        lat, lon = s[6], s[5]
        aircraft_list.append({"latitude": lat, "longitude": lon, "callsign": cs})
elif data_source == "ADS-B Exchange":
    api_key = os.getenv("RAPIDAPI_KEY")
    adsb = []
    if api_key:
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
        try:
            r2 = requests.get(url, headers=headers)
            r2.raise_for_status()
            adsb = r2.json().get("ac", [])
        except:
            adsb = []
    for ac in adsb:
        try:
            lat = float(ac.get("lat")); lon = float(ac.get("lon"))
        except:
            continue
        cs = ac.get("flight") or ac.get("hex") or ""
        aircraft_list.append({"latitude": lat, "longitude": lon, "callsign": cs.strip()})

# Prepare DataFrame for mapping
import pandas as pd  # ensure pandas imported here

df_map = pd.DataFrame(aircraft_list)

# Use Pydeck for light-themed map, home pin, and shadow lines
import pydeck as pdk

# Prepare scatter data for aircraft and home
df_ac = df_map.rename(columns={'latitude':'lat','longitude':'lon'})
# Home as a separate point
home = pd.DataFrame([{'lat': CENTER_LAT, 'lon': CENTER_LON, 'callsign': 'Home'}])

# Build paths (shadow lines) from each aircraft to home when tracking shadows
paths = []
if track_sun or track_moon or override_trails:
    for row in df_ac.itertuples():
        paths.append({'path': [(row.lon, row.lat), (CENTER_LON, CENTER_LAT)], 'callsign': row.callsign})
df_paths = pd.DataFrame(paths)

# Define layers
aircraft_layer = pdk.Layer(
    'ScatterplotLayer',
    df_ac,
    get_position=['lon','lat'],
    get_color=[0, 128, 255, 200],
    get_radius=500,
    pickable=True
)
home_layer = pdk.Layer(
    'ScatterplotLayer',
    home,
    get_position=['lon','lat'],
    get_color=[255, 0, 0, 200],
    get_radius=1000,
    pickable=False
)
path_layer = pdk.Layer(
    'PathLayer',
    df_paths,
    get_path='path',
    get_color=[0, 0, 0, 100],
    width_scale=10,
    width_min_pixels=2
)

# Ensure zoom_level is defined
zoom = zoom_level if 'zoom_level' in locals() else DEFAULT_ZOOM
view_state = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=zoom)

deck = pdk.Deck(
    layers=[aircraft_layer, home_layer, path_layer],
    initial_view_state=view_state,
    map_style='light',
    tooltip={'text': '{callsign}'}
)

st.pydeck_chart(deck, use_container_width=True)

# Test alerts
if test_alert:
    st.success("Test alert triggered")
    send_pushover("✈️ Test Alert", "This is a test shadow alert.")
if test_pushover:
    st.info("Sending test Pushover notification...")
    send_pushover("✈️ Test Push", "This is a test shadow alert.")

# Alert history in sidebar
with st.sidebar:
    st.markdown("---")
    st.markdown("### 📥 Download Log")
    if os.path.exists(log_path):
        with open(log_path, "rb") as f:
            st.download_button("Download alert_log.csv", f, file_name="alert_log.csv", mime="text/csv")
        df_log = pd.read_csv(log_path)
        if not df_log.empty:
            df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
            st.markdown("### 🕑 Recent Alerts")
            st.dataframe(
                df_log[['Time UTC', 'Callsign', 'Time Until Alert (sec)']]
                    .sort_values('Time UTC', ascending=False)
                    .head(5)
            )
