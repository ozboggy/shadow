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

# Constants
# Pushover configuration (set these in your .env)
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

# Function to send Pushover notifications
def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        st.warning("Pushover credentials not set in environment.")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": PUSHOVER_API_TOKEN,
                "user": PUSHOVER_USER_KEY,
                "title": title,
                "message": message
            }
        )
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# Log file setup
log_file = "alert_log.csv"
log_path = os.path.join(os.path.dirname(__file__), log_file)
if not os.path.exists(log_path):
    with open(log_path, "w", newline="") as f:
        f.write("Time UTC,Callsign,Time Until Alert (sec),Lat,Lon,Source\n")

CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 20
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
DEFAULT_SHADOW_WIDTH = 2
DEFAULT_ZOOM = 11

# Sidebar controls
with st.sidebar:
    st.header("Map Options")
    tile_style = st.selectbox(
        "Tile Style",
        ["OpenStreetMap", "CartoDB positron"],
        index=0
    )
    data_source = st.selectbox(
        "Data Source",
        ["OpenSky", "ADS-B Exchange"],
        index=0
    )
    radius_km = st.slider("Search Radius (km)", min_value=1, max_value=100, value=DEFAULT_RADIUS_KM)
    st.markdown(f"**Search Radius:** {radius_km} km")
    alert_radius_m = st.slider("Shadow Alert Radius (m)", min_value=0, max_value=1000, value=50)
    st.markdown(f"**Shadow Alert Radius:** {alert_radius_m} m")
    track_sun = st.checkbox("Show Sun Shadows", value=True)
    track_moon = st.checkbox("Show Moon Shadows", value=False)
    override_trails = st.checkbox("Show Trails Regardless of Sun/Moon", value=False)
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")
    st.header("Map Settings")
    zoom_level = st.slider("Initial Zoom Level", min_value=1, max_value=18, value=DEFAULT_ZOOM)
    map_width = st.number_input("Width (px)", min_value=400, max_value=2000, value=600)
    map_height = st.number_input("Height (px)", min_value=300, max_value=1500, value=600)

# Use current UTC time for calculations
selected_time = datetime.utcnow().replace(tzinfo=timezone.utc)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

# Initialize map centered at Home with initial zoom
fmap = folium.Map(
    location=[CENTER_LAT, CENTER_LON],
    zoom_start=zoom_level,
    tiles=tile_style,
    control_scale=True
)
# Home marker
folium.Marker(
    location=[CENTER_LAT, CENTER_LON],
    icon=folium.Icon(color="red", icon="home", prefix="fa"),
    popup="Home"
).add_to(fmap)

# Set shadow line width constant
shadow_width = DEFAULT_SHADOW_WIDTH

# Utils
def move_position(lat, lon, heading, dist):
    R = 6371000
    try:
        hdr = math.radians(float(heading))
    except:
        hdr = 0.0
    try:
        lat1 = math.radians(float(lat)); lon1 = math.radians(float(lon))
    except:
        return lat, lon
    lat2 = math.asin(math.sin(lat1)*math.cos(dist/R) + math.cos(lat1)*math.sin(dist/R)*math.cos(hdr))
    lon2 = lon1 + math.atan2(math.sin(hdr)*math.sin(dist/R)*math.cos(lat1), math.cos(dist/R)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Fetch and process aircraft data
aircraft_list = []
if data_source == "OpenSky":
    dr = radius_km / 111.0
    south, north = CENTER_LAT - dr, CENTER_LAT + dr
    dlon = dr / math.cos(math.radians(CENTER_LAT))
    west, east = CENTER_LON - dlon, CENTER_LON + dlon
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url); r.raise_for_status()
        states = r.json().get("states", [])
    except Exception as e:
        st.error(f"OpenSky error: {e}")
        states = []
    for s in states:
        if len(s) < 11: continue
        _, cs_raw, _, _, _, lon, lat, baro_raw, _, vel, hdg = s[:11]
        cs = cs_raw.strip() if cs_raw else s[0]
        aircraft_list.append({"lat": float(lat), "lon": float(lon),
                              "baro": float(baro_raw) if baro_raw else 0.0,
                              "vel": float(vel), "hdg": float(hdg), "callsign": cs})
elif data_source == "ADS-B Exchange":
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        st.error("Set RAPIDAPI_KEY in .env for ADS-B Exchange")
        adsb = []
    else:
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
        try:
            r2 = requests.get(url, headers=headers); r2.raise_for_status()
            adsb = r2.json().get("ac", [])
        except Exception as e:
            st.error(f"ADS-B Exchange error: {e}")
            adsb = []
    for ac in adsb:
        lat = float(ac.get("lat")); lon = float(ac.get("lon"))
        vel_raw = ac.get("gs") or ac.get("spd")
        hdg_raw = ac.get("track") or ac.get("trak")
        baro_raw = ac.get("alt_baro")
        cs = ac.get("flight") or ac.get("hex")
        aircraft_list.append({"lat": lat, "lon": lon,
                              "baro": float(baro_raw) if baro_raw else 0.0,
                              "vel": float(vel_raw) if vel_raw else 0.0,
                              "hdg": float(hdg_raw) if hdg_raw else 0.0,
                              "callsign": cs.strip() if cs else None})

# Display aircraft count with icon
st.sidebar.markdown(f"✈️ **Tracked Aircraft:** {len(aircraft_list)}")

# Plot aircraft and shadow trails
alerts = []
for ac in aircraft_list:
    lat, lon = ac["lat"], ac["lon"]
    baro, vel, hdg, cs = ac["baro"], ac["vel"], ac["hdg"], ac["callsign"]
    alert = False
    trail = []
    for i in range(0, FORECAST_DURATION_MINUTES*60+1, FORECAST_INTERVAL_SECONDS):
        ft = selected_time + timedelta(seconds=i)
        f_lat, f_lon = move_position(lat, lon, hdg, vel * i)
        sun_alt = get_sun_altitude(f_lat, f_lon, ft)
        if (track_sun and sun_alt > 0) or (track_moon and sun_alt <= 0) or override_trails:
            az = get_sun_azimuth(f_lat, f_lon, ft)
            sd = baro / math.tan(math.radians(sun_alt if sun_alt>0 else 1))
            sh_lat = f_lat + (sd/111111)*math.cos(math.radians(az+180))
            sh_lon = f_lon + (sd/(111111*math.cos(math.radians(f_lat))))*math.sin(math.radians(az+180))
            trail.append((sh_lat, sh_lon))
            if hav(sh_lat, sh_lon, CENTER_LAT, CENTER_LON) <= alert_radius_m:
                alert = True
    if alert:
        alerts.append(cs)
    # Aircraft marker with rotation and alert coloring
    folium.Marker(
        location=(lat, lon),
        icon=DivIcon(
            icon_size=(30,30), icon_anchor=(15,15),
            html=f'<i class="fa fa-plane" style="transform: rotate({hdg-90}deg); color: {'red' if alert else 'blue'}; font-size: 24px;"></i>'
        ),
        popup=f"{cs}\nAlt: {baro} m\nSpd: {vel} m/s"
    ).add_to(fmap)
    # Shadow trail polyline
    if trail:
        folium.PolyLine(locations=trail, color="red" if alert else "black", weight=shadow_width, opacity=0.6).add_to(fmap)

# Trigger alerts and notifications
if alerts:
    alert_list = ", ".join(alerts)
    st.error(f"🚨 Shadow ALERT for: {alert_list}")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
    # Desktop notification snippet
    st.markdown("""
    <script>
    if (Notification.permission === 'granted') {
        new Notification("✈️ Shadow Alert", { body: "Aircraft shadow passing over target!" });
    } else {
        Notification.requestPermission().then(p => {
            if (p === 'granted') {
                new Notification("✈️ Shadow Alert", { body: "Aircraft shadow passing over target!" });
            }
        });
    }
    </script>
    """, unsafe_allow_html=True)
    send_pushover("✈️ Shadow ALERT", f"Shadows detected for: {alert_list}")
else:
    st.success("✅ No forecast shadow paths intersect target area.")

# Logs
if os.path.exists(log_path):
    st.sidebar.markdown("### 📥 Download Log")
    with open(log_path, "rb") as f:
        st.sidebar.download_button("Download alert_log.csv", f, file_name="alert_log.csv", mime="text/csv")

    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        st.markdown("### 📊 Recent Alerts")
        st.dataframe(df_log.tail(10))

        fig = px.scatter(df_log, x="Time UTC", y="Callsign", size="Time Until Alert (sec)",
                         hover_data=["Lat", "Lon"], title="Shadow Alerts Over Time")
        st.plotly_chart(fig, use_container_width=True)

# Test alert and Pushover buttons handling
if test_alert:
    st.error("🚨 Test Alert Triggered!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)

if test_pushover:
    st.info("🔔 Sending test Pushover notification...")
    send_pushover("✈️ Test Push", "This is a test Pushover notification from your tracker.")

# Render map
st_folium(fmap, width=map_width, height=map_height)
