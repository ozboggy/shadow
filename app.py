import streamlit as st
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
import requests
import folium
from streamlit_folium import st_folium
from math import radians, sin, cos, asin, sqrt, tan, atan2, degrees
from pysolar.solar import get_altitude as solar_altitude, get_azimuth as solar_azimuth
from pyfr24 import FR24API, FR24AuthenticationError
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

# Validate FR24 API key
if not FR24_API_KEY:
    st.error("FLIGHTRADAR_API_KEY missing in .env. Please set and restart.")
    st.stop()

# Home coordinates
HOME_LAT, HOME_LON = -33.7608288, 150.9713948

# Sidebar UI
st.sidebar.title("☀️🌙 Shadow Forecast Settings")
selected_date = st.sidebar.date_input("Date (UTC)", datetime.utcnow().date())
selected_time = st.sidebar.time_input("Time (UTC)", datetime.utcnow().time().replace(second=0, microsecond=0))
t0 = datetime.combine(selected_date, selected_time).replace(tzinfo=timezone.utc)
show_sun = st.sidebar.checkbox("Show Sun Shadows", True)
show_moon = False
if MOON_AVAILABLE:
    show_moon = st.sidebar.checkbox("Show Moon Shadows", False)
else:
    st.sidebar.markdown("*Install `pip install ephem` for moon shadows*")
alert_radius = st.sidebar.slider("Alert Radius (m)", 10, 200, 50, 5)
radius_km = st.sidebar.slider("Search Radius (km)", 10, 200, 50, 10)
zoom = st.sidebar.slider("Map Zoom Level", 6, 15, 12)
debug = st.sidebar.checkbox("Debug Mode", False)

# Data source selector
tab = st.sidebar.radio(
    "Data Source:",
    ["FR24 API", "JS Feed Fallback", "Local ADS-B Feed"]
)

# Build local feed URL
def get_local_url():
    host = st.sidebar.text_input("Local ADS-B Host", "localhost")
    port = st.sidebar.text_input("Local ADS-B Port", "8080")
    path = st.sidebar.text_input("Local ADS-B Path", "/data/aircraft.json")
    url = f"http://{host}:{port}{path}"
    st.sidebar.write("Using Local feed URL:", url)
    return url

# Compute bounding box
delta_lat = radius_km / 110.574
delta_lon = radius_km / (111.320 * cos(radians(HOME_LAT)))
lat_min, lat_max = HOME_LAT - delta_lat, HOME_LAT + delta_lat
lon_min, lon_max = HOME_LON - delta_lon, HOME_LON + delta_lon
bounds = f"{lat_min:.6f},{lon_min:.6f},{lat_max:.6f},{lon_max:.6f}"

# Initialize map
m = folium.Map(location=[HOME_LAT, HOME_LON], zoom_start=zoom)
folium.Marker([HOME_LAT, HOME_LON], popup="Home", icon=folium.Icon(color="red", icon="home", prefix="fa")).add_to(m)

# Fetch flight positions
positions = []
if tab == "Local ADS-B Feed":
    url = get_local_url()
    try:
        data = requests.get(url, timeout=5).json()
    except Exception as e:
        st.error(f"Local ADS-B feed error: {e}")
        st.stop()
    aircraft = data.get("aircraft") if isinstance(data, dict) else data
    for ent in aircraft or []:
        if not isinstance(ent, dict):
            continue
        lat = ent.get('lat') or ent.get('latitude')
        lon = ent.get('lon') or ent.get('longitude')
        if lat is None or lon is None:
            continue
        positions.append({
            'lat': lat,
            'lon': lon,
            'callsign': (ent.get('flight') or ent.get('callsign') or ent.get('hex') or "").strip(),
            'alt': ent.get('altitude', 0),
            'speed': ent.get('speed', 0),
            'track': ent.get('track') or ent.get('heading', 0)
        })
    st.sidebar.markdown(f"**Local feed count:** {len(positions)}")
elif tab == "JS Feed Fallback":
    url = f"https://data-live.flightradar24.com/zones/fcgi/feed.js?bounds={bounds}&array=1"
    try:
        data = requests.get(url, timeout=5).json()
    except Exception as e:
        st.error(f"JS feed error: {e}")
        st.stop()
    for entry in data.get('aircraft', []):
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        lat, lon = entry[1], entry[2]
        if lat is None or lon is None:
            continue
        positions.append({
            'lat': lat,
            'lon': lon,
            'callsign': str(entry[0]).strip(),
            'alt': 0,
            'speed': 0,
            'track': 0
        })
    st.sidebar.markdown(f"**JS feed count:** {len(positions)}")
else:
    api = FR24API(FR24_API_KEY)
    try:
        raw = api.get_flight_positions_light(bounds)
    except FR24AuthenticationError as e:
        st.error(f"FR24 error: {e}")
        st.stop()
    except Exception as e:
        st.error(f"FR24 error: {e}")
        st.stop()
    for obj in raw:
        lat = getattr(obj, 'latitude', None)
        lon = getattr(obj, 'longitude', None)
        if lat is None or lon is None:
            continue
        positions.append({
            'lat': lat,
            'lon': lon,
            'callsign': (getattr(obj, 'callsign', '') or getattr(obj, 'flight', '')).strip(),
            'alt': getattr(obj, 'altitude', 0),
            'speed': getattr(obj, 'speed', 0),
            'track': getattr(obj, 'track', getattr(obj, 'heading', 0))
        })
    st.sidebar.markdown(f"**FR24 API count:** {len(positions)}")

# Debug info
if debug:
    st.write("Positions sample:", positions[:5])
    st.write("Bounds:", bounds)

if not positions:
    st.warning("No aircraft found in selected source and bounds.")

# Plot raw positions
for p in positions:
    folium.Marker(
        (p['lat'], p['lon']),
        icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
        popup=p['callsign']
    ).add_to(m)

# Log file initialization
LOG_FILE = os.path.join(os.path.dirname(__file__), "shadow_alerts.csv")
def write_header():
    with open(LOG_FILE, 'w', newline='') as f:
        csv.writer(f).writerow(["Time UTC", "Callsign", "Alert Sec", "Lat", "Lon"])
if not pathlib.Path(LOG_FILE).exists():
    write_header()

# Utility functions
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

def move_position(lat, lon, bearing, distance):
    R = 6371000
    b = radians(bearing)
    φ1, λ1 = radians(lat), radians(lon)
    d = distance / R
    φ2 = asin(sin(φ1)*cos(d) + cos(φ1)*sin(d)*cos(b))
    λ2 = λ1 + atan2(sin(b)*sin(d)*cos(φ1), cos(d) - sin(φ1)*sin(φ2))
    return degrees(φ2), degrees(λ2)

# Shadow projections & alerts
alerts = []
for p in positions:
    lat, lon = p['lat'], p['lon']
    alt_m = p['alt'] * 0.3048
    spd_m = p['speed'] * 0.514444
    track = p['track']
    cs = p['callsign']
    trail = []
    alerted = False
    for t in range(0, 5*60+1, 30):
        fx, fy = move_position(lat, lon, track, spd_m * t)
        if show_sun:
            sa = solar_altitude(fx, fy, t0 + timedelta(seconds=t))
            if sa > 0:
                az = solar_azimuth(fx, fy, t0 + timedelta(seconds=t))
                sd = alt_m / tan(radians(sa))
                sx, sy = move_position(fx, fy, az + 180, sd)
                trail.append((sx, sy, 'sun'))
                if not alerted and haversine(sx, sy, HOME_LAT, HOME_LON) <= alert_radius:
                    alerts.append((cs, t, sx, sy))
                    alerted = True
        if show_moon and MOON_AVAILABLE:
            obs = ephem.Observer(); obs.lat, obs.lon = str(fx), str(fy)
            obs.date = (t0 + timedelta(seconds=t)).strftime('%Y/%m/%d %H:%M:%S')
            mobj = ephem.Moon(obs); ma = degrees(mobj.alt)
            if ma > 0:
                maz = degrees(mobj.az)
                sd = alt_m / tan(radians(ma))
                sx, sy = move_position(fx, fy, maz + 180, sd)
                trail.append((sx, sy, 'moon'))
                if not alerted and haversine(sx, sy, HOME_LAT, HOME_LON) <= alert_radius:
                    alerts.append((cs, t, sx, sy))
                    alerted = True
    for sx, sy, typ in trail:
        color = '#FFA500' if typ == 'sun' else '#AAAAAA'
        folium.CircleMarker((sx, sy), radius=2, color=color, fill=True, fill_opacity=0.7).add_to(m)

if alerts:
    st.error("🚨 Shadow Alert!")
    for cs, t, sx, sy in alerts:
        st.write(f"✈️ {cs} shadow in ~{t}s at {sx:.5f},{sy:.5f}")
        with open(LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([datetime.utcnow().isoformat(), cs, t, sx, sy])
        try:
            requests.post(
                "https://api.pushover.net/1/messages.json",
                data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "message": f"{cs} shadow over home in {t}s"}
            )
        except:
            pass
else:
    st.success("✅ No shadow passes predicted.")

# Render map
st_folium(m, width=800, height=600)

# Download alert log
if pathlib.Path(LOG_FILE).exists():
    st.sidebar.markdown("### Alert Log")
    with open(LOG_FILE, 'rb') as f:
        st.sidebar.download_button("Download CSV", f, file_name="shadow_alerts.csv")
    df = pd.read_csv(LOG_FILE)
    st.sidebar.dataframe(df.tail(10))
