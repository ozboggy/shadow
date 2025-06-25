
import time
import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth
from streamlit_autorefresh import st_autorefresh
import io
import zipfile

# Optional moon computations
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh every second
try:
    st_autorefresh(interval=1000, key="refresh")
except:
    pass

# Environment variables
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# Forecast/Alert config
FORECAST_INTERVAL_SECONDS = 5
FORECAST_DURATION_MINUTES = 5
SUN_FORECAST_MINUTES = int(FORECAST_DURATION_MINUTES * 1.5)
alert_times = [60, 30, 15, 10, 5, 0]

# Center coordinates
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434

# Session-state for alerts
if 'alerted' not in st.session_state:
    st.session_state.alerted = set()

# Helper: haversine distance
def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Pushover notification
def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return False
    try:
        r = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
        return r.status_code == 200
    except:
        return False

# Sidebar controls
with st.sidebar:
    st.header("Shadow Tracker")
    radius_km = st.slider("Search Radius (km)", 1, 100, 10)
    alert_width = st.slider("Shadow Alert Width (m)", 10, 1000, 100)
    show_sun = st.checkbox("Track Sun", True)
    show_moon = st.checkbox("Track Moon", False)
    show_sun_lines = st.checkbox("Show Sun Shadows", True)
    show_moon_lines = st.checkbox("Show Moon Shadows", True)
    test_alert = st.button("Test Alert")
    test_push = st.button("Test Pushover")

# Current UTC time
now_utc = datetime.now(timezone.utc)

# Sun & Moon altitudes
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon = str(CENTER_LAT), str(CENTER_LON)
    obs.date = now_utc
    moon_obs = ephem.Moon(obs)
    moon_alt = math.degrees(moon_obs.alt)

# Fetch aircraft data
aircraft_list = []
if RAPIDAPI_KEY:
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        for ac in r.json().get("ac", []):
            try:
                lat = float(ac.get("lat", 0)); lon = float(ac.get("lon", 0))
                alt = float(ac.get("alt_geo") or ac.get("alt_baro") or 0)
                vel = float(ac.get("gs") or 0)
                hdg = float(ac.get("track") or 0)
                cs = ac.get("flight") or ac.get("hex") or ""
                if alt > 0:
                    aircraft_list.append({"lat": lat, "lon": lon, "alt": alt, "vel": vel, "hdg": hdg, "callsign": cs})
            except:
                continue
    except:
        st.warning("Failed to fetch aircraft data.")
df_ac = pd.DataFrame(aircraft_list)
# Aircraft count
st.sidebar.markdown(f"**Tracked Aircraft:** {len(df_ac)}")
