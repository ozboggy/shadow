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

# Log file setup
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
debug = st.sidebar.checkbox("Debug Mode", value=False)
use_fallback = st.sidebar.checkbox("Use JS feed fallback", value=False)

# Compute bounding box in degrees
# 1° lat ≈ 110.574 km; 1° lon ≈ 111.320 km × cos(lat)
delta_lat = radius_km / 110.574
delta_lon = radius_km / (111.320 * cos(radians(HOME_LAT)))
lat_min = HOME_LAT - delta_lat
lat_max = HOME_LAT + delta_lat
lon_min = HOME_LON - delta_lon
lon_max = HOME_LON + delta_lon
bounds = f"{lat_min:.6f},{lon_min:.6f},{lat_max:.6f},{lon_max:.6f}"

# Initialize map
m = folium.Map(location=[HOME_LAT, HOME_LON], zoom_start=zoom)
folium.Marker([HOME_LAT, HOME_LON], icon=folium.Icon(color="red", icon="home", prefix="fa"), popup="Home").add_to(m)
# Draw bounding rectangle
folium.Rectangle([[lat_min, lon_min], [lat_max, lon_max]], color="blue", fill=False, weight=2).add_to(m)

# Debug info
if debug:
    st.sidebar.markdown("### Debug Info")
    st.sidebar.write("Bounds:", bounds)
    st.sidebar.write("Fallback:", use_fallback)

# Fetch positions
positions = []
if use_fallback:
    feed_url = (
        f"https://data-live.flightradar24.com/zones/fcgi/feed.js?bounds={bounds}"
        "&faa=1&mlat=1&flarm=1&adsb=1&air=1&vehicle=0&estimated=1&stats=0"
    )
    try:
        data = requests.get(feed_url).json()
    except Exception as e:
        st.error(f"JS feed error: {e}")
        st.stop()
    if debug:
        st.write("Feed.js keys:", list(data.keys())[:10])
    # Parse feed entries
    meta_keys = {"version","full_count","stats"}
    for key, val in data.items():
        if key in meta_keys or not isinstance(val, list):
            continue
        lat = val[1]; lon = val[2]
        callsign = val[9] if len(val) > 9 else key
        positions.append({"lat":lat, "lon":lon, "callsign":callsign})
    st.sidebar.markdown(f"**Feed.js count:** {len(positions)}")
else:
    api = FR24API(FR24_API_KEY)
    try:
        raw = api.get_flight_positions_light(bounds)
    except FR24AuthenticationError as e:
        st.error(f"Authentication failed: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Error fetching FR24: {e}")
        st.stop()
    positions = list(raw)
    st.sidebar.markdown(f"**FR24API count:** {len(positions)}")

# Warn if empty
if not positions:
    st.warning("No flights found. Toggle fallback or increase radius.")

# Utility functions
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

def move_position(lat, lon, bearing_deg, distance_m):
    R = 6371000
    b = radians(bearing_deg)
    φ1, λ1 = radians(lat), radians(lon)
    d = distance_m / R
    φ2 = asin(sin(φ1)*cos(d) + cos(φ1)*sin(d)*cos(b))
    λ2 = λ1 + atan2(sin(b)*sin(d)*cos(φ1), cos(d) - sin(φ1)*sin(φ2))
    return degrees(φ2), degrees(λ2)

# Process each position
alerts = []
for pos in positions:
    # Fallback dict
    if isinstance(pos, dict):
        folium.Marker((pos['lat'], pos['lon']),
            icon=folium.Icon(color="green", icon="plane", prefix="fa"),
            popup=pos['callsign']).add_to(m)
        continue
    # FR24API object
    lat = getattr(pos, 'lat', getattr(pos, 'latitude', None))
    lon = getattr(pos, 'lon', getattr(pos, 'longitude', None))
    alt = getattr(pos, 'alt', getattr(pos, 'altitude', None))
    speed = getattr(pos, 'spd', getattr(pos, 'speed', None))
    track = getattr(pos, 'track', getattr(pos, 'hdg', getattr(pos, 'heading', None)))
    cs = getattr(pos, 'flight', getattr(pos, 'callsign', getattr(pos, 'reg', ''))).strip()
    if None in (lat, lon, alt, speed, track):
        continue
    alt_m = alt * 0.3048
    speed_mps = speed * 0.514444
    trail = []
    alerted = False
    # Forecast
    for t in range(0, 5*60+1, 30):
        fx, fy = move_position(lat, lon, track, speed_mps * t)
        if show_sun:
            sa = solar_altitude(fx, fy, t0 + timedelta(seconds=t))
            if sa > 0:
                az = solar_azimuth(fx, fy, t0 + timedelta(seconds=t))
                sd = alt_m / tan(radians(sa))
                sx, sy = move_position(fx, fy, az+180, sd)
                trail.append((sx, sy, 'sun'))
                if not alerted and haversine(sx, sy, HOME_LAT, HOME_LON) <= alert_radius:
                    alerts.append((cs, t, sx, sy)); alerted=True
        if show_moon and MOON_AVAILABLE:
            obs = ephem.Observer(); obs.lat, obs.lon = str(fx), str(fy)
            obs.date = (t0 + timedelta(seconds=t)).strftime('%Y/%m/%d %H:%M:%S')
            mobj = ephem.Moon(obs); ma = degrees(mobj.alt)
            if ma > 0:
                maz = degrees(mobj.az)
                sd = alt_m / tan(radians(ma))
                sx, sy = move_position(fx, fy, maz+180, sd)
                trail.append((sx, sy, 'moon'))
                if not alerted and haversine(sx, sy, HOME_LAT, HOME_LON) <= alert_radius:
                    alerts.append((cs, t, sx, sy)); alerted=True
    folium.Marker((lat, lon), icon=folium.Icon(color="blue", icon="plane", prefix="fa"), popup=cs).add_to(m)
    for sx, sy, typ in trail:
        color = '#FFA500' if typ=='sun' else '#AAAAAA'
        folium.CircleMarker((sx, sy), radius=2, color=color, fill=True, fill_opacity=0.7).add_to(m)

# Alerts UI
if alerts:
    st.error("🚨 Shadow Alert!")
    for cs, tsec, sx, sy in alerts:
        st.write(f"✈️ {cs} shadow in ~{tsec}s at {sx:.5f},{sy:.5f}")
        with open(LOG_FILE, 'a', newline='') as f: csv.writer(f).writerow([datetime.utcnow().isoformat(), cs, tsec, sx, sy])
        try:
            requests.post("https://api.pushover.net/1/messages.json",
                data={"token":PUSHOVER_API_TOKEN, "user":PUSHOVER_USER_KEY, "message":f"{cs} shadow over home in {tsec}s"})
        except: pass
else:
    st.success("✅ No shadow passes predicted.")

# Render map
st_folium(m, width=800, height=600)

# Log download
if pathlib.Path(LOG_FILE).exists():
    st.sidebar.markdown("## Alert Log")
    with open(LOG_FILE, 'rb') as f: st.sidebar.download_button("Download CSV", f, file_name="shadow_alerts.csv")
    df = pd.read_csv(LOG_FILE); st.sidebar.dataframe(df.tail(10))
