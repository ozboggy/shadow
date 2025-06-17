import streamlit as st
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
from pyfr24 import FR24API, FR24AuthenticationError
import requests
import folium
from streamlit_folium import st_folium
from math import radians, sin, cos, asin, sqrt, tan, atan2, degrees
from pysolar.solar import get_altitude as solar_altitude, get_azimuth as solar_azimuth
try:
    import ephem
    MOON_AVAILABLE = True
except ImportError:
    MOON_AVAILABLE = False
import csv
import pandas as pd
import pathlib

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

# Credentials
FR24_API_KEY = os.getenv("FLIGHTRADAR_API_KEY")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

# Log file
LOG_FILE = os.path.join(os.path.dirname(__file__), "shadow_alerts.csv")
if not pathlib.Path(LOG_FILE).exists():
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time UTC", "Callsign", "Time Until Alert (sec)", "Lat", "Lon"])

# Verify API key
if not FR24_API_KEY:
    st.error("FLIGHTRADAR_API_KEY not found in .env. Please set it and restart.")
    st.stop()

# Home coordinates
HOME_LAT, HOME_LON = -33.7608288, 150.9713948

# Sidebar settings
st.sidebar.title("Aircraft Shadow Forecast Settings")
selected_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
selected_time = st.sidebar.time_input("Time (UTC)", value=datetime.utcnow().time().replace(second=0, microsecond=0))
t0 = datetime.combine(selected_date, selected_time).replace(tzinfo=timezone.utc)
show_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
if MOON_AVAILABLE:
    show_moon = st.sidebar.checkbox("Show Moon Shadows", value=False)
else:
    show_moon = False
    st.sidebar.markdown("*Moon shadows unavailable: `pip install ephem`*")
alert_radius = st.sidebar.slider("Alert Radius (m)", 10, 200, 50, 5)
radius_km = st.sidebar.slider("Flight Search Radius (km)", 10, 200, 50, 10)
zoom = st.sidebar.slider("Map Zoom Level", 6, 15, 12)
# Optional debug toggle
debug = st.sidebar.checkbox("Debug Mode", value=False)

# Compute bounding box in degrees based on correct scaling
# 1° latitude ≈ 110.574 km; 1° longitude ≈ 111.320 km × cos(lat)
delta_lat = radius_km / 110.574
delta_lon = radius_km / (111.320 * cos(radians(HOME_LAT)))
bounds = f"{HOME_LAT - delta_lat:.6f},{HOME_LON - delta_lon:.6f},{HOME_LAT + delta_lat:.6f},{HOME_LON + delta_lon:.6f}"

# Debug info in sidebar
if debug:
    st.sidebar.markdown("### Debug Info")
    st.sidebar.write("FR24 API Key:", FR24_API_KEY[:4] + "****")
    st.sidebar.write("Bounds:", bounds)

# Initialize Folium map
m = folium.Map(location=[HOME_LAT, HOME_LON], zoom_start=zoom)
folium.Marker([HOME_LAT, HOME_LON], icon=folium.Icon(color="red", icon="home", prefix="fa"), popup="Home").add_to(m)

# Fetch live flights
api = FR24API(FR24_API_KEY)
try:
    positions = api.get_flight_positions_light(bounds)
except FR24AuthenticationError as e:
    st.error(f"Authentication failed: {e}")
    st.stop()
except Exception as e:
    st.error(f"Error fetching flights: {e}")
    st.stop()

# Debug raw data
if debug:
    st.write(f"Raw positions count: {len(positions)}")
    sample = [p.__dict__ for p in positions[:5]]
    st.write("Sample positions:", sample)

# Sidebar flight count and warning
st.sidebar.markdown(f"**Flights found:** {len(positions)} within {radius_km} km")
if not positions:
    st.warning("No flights found. Try increasing the search radius or check your API key.")

# Utility functions
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

def move_position(lat, lon, bearing_deg, distance_m):
    R = 6371000
    bearing = radians(bearing_deg)
    lat1 = radians(lat)
    lon1 = radians(lon)
    d = distance_m / R
    lat2 = sin(lat1)*cos(d) + cos(lat1)*sin(d)*cos(bearing)
    lat2 = asin(lat2)
    lon2 = lon1 + atan2(sin(bearing)*sin(d)*cos(lat1), cos(d) - sin(lat1)*sin(lat2))
    return degrees(lat2), degrees(lon2)

# Process each flight and project shadows
alerts = []
for pos in positions:
    lat = getattr(pos, 'latitude', None)
    lon = getattr(pos, 'longitude', None)
    alt = getattr(pos, 'altitude', None)  # feet
    speed = getattr(pos, 'speed', None)   # knots
    track = getattr(pos, 'track', None) or getattr(pos, 'heading', None)
    callsign = getattr(pos, 'callsign', '').strip()
    if None in (lat, lon, alt, speed, track):
        continue
    alt_m = alt * 0.3048
    speed_mps = speed * 0.514444
    trail = []
    alerted = False
    for t in range(0, 5*60+1, 30):
        f_lat, f_lon = move_position(lat, lon, track, speed_mps * t)
        # Sun shadow
        if show_sun:
            sa = solar_altitude(f_lat, f_lon, t0 + timedelta(seconds=t))
            if sa > 0:
                az = solar_azimuth(f_lat, f_lon, t0 + timedelta(seconds=t))
                sd = alt_m / tan(radians(sa))
                sh_lat, sh_lon = move_position(f_lat, f_lon, az + 180, sd)
                trail.append((sh_lat, sh_lon, 'sun'))
                if not alerted and haversine(sh_lat, sh_lon, HOME_LAT, HOME_LON) <= alert_radius:
                    alerts.append((callsign, t, sh_lat, sh_lon))
                    alerted = True
        # Moon shadow
        if show_moon and MOON_AVAILABLE:
            obs = ephem.Observer()
            obs.lat, obs.lon = str(f_lat), str(f_lon)
            obs.date = (t0 + timedelta(seconds=t)).strftime('%Y/%m/%d %H:%M:%S')
            mobj = ephem.Moon(obs)
            ma = degrees(mobj.alt)
            if ma > 0:
                maz = degrees(mobj.az)
                sd = alt_m / tan(radians(ma))
                sh_lat, sh_lon = move_position(f_lat, f_lon, maz + 180, sd)
                trail.append((sh_lat, sh_lon, 'moon'))
                if not alerted and haversine(sh_lat, sh_lon, HOME_LAT, HOME_LON) <= alert_radius:
                    alerts.append((callsign, t, sh_lat, sh_lon))
                    alerted = True
    folium.Marker((lat, lon), icon=folium.Icon(color="blue", icon="plane", prefix="fa"), popup=callsign).add_to(m)
    for s_lat, s_lon, typ in trail:
        color = '#FFA500' if typ=='sun' else '#AAAAAA'
        folium.CircleMarker((s_lat, s_lon), radius=2, color=color, fill=True, fill_opacity=0.7).add_to(m)

# Display alerts and send notifications
if alerts:
    st.error("🚨 Shadow Alert!")
    for cs, tsec, lat_s, lon_s in alerts:
        st.write(f"✈️ {cs} shadow in ~{tsec}s at {lat_s:.5f},{lon_s:.5f}")
        with open(LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([datetime.utcnow().isoformat(), cs, tsec, lat_s, lon_s])
        try:
            requests.post(
                "https://api.pushover.net/1/messages.json",
                data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "message": f"{cs} shadow over home in {tsec}s"}
            )
        except:
            pass
else:
    st.success("✅ No shadow passes predicted.")

# Render map
st_folium(m, width=800, height=600)

# Log download section
if pathlib.Path(LOG_FILE).exists():
    st.sidebar.markdown("## Alert Log")
    with open(LOG_FILE, 'rb') as f:
        st.sidebar.download_button("Download CSV", f, file_name="shadow_alerts.csv")
    df = pd.read_csv(LOG_FILE)
    st.sidebar.dataframe(df.tail(10))
