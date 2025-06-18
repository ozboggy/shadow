import os
import time
import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
from math import radians, sin, cos, atan2, sqrt
from json import JSONDecodeError

# ─── CONFIG ─────────────────────────────────────────────────────────────────────
HOME_LAT = -33.76025
HOME_LON = 150.9711666
DEFAULT_RADIUS_KM      = 50
DEFAULT_ALERT_RADIUS_M = 100

# OpenSky credentials
OPENSKY_HOST     = "opensky-network.org"
OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD")

# Pushover credentials
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN")
PUSHOVER_USER  = os.getenv("PUSHOVER_USER")

# ADS-B Exchange API Lite key (your UUID)
ADSBEX_API_KEY = os.getenv("ADSBEXCHANGE_API_KEY")
ADSB_HEADERS = {"User-Agent": "Mozilla/5.0"}

# ─── HELPERS ────────────────────────────────────────────────────────────────────
def send_pushover(message: str, title: str = "Shadow Alert") -> bool:
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        return False
    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_TOKEN, "user": PUSHOVER_USER, "message": message, "title": title}
        )
        return resp.status_code == 200
    except Exception:
        return False


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points (in meters)."""
    R = 6371000  # Earth radius in meters
    φ1 = radians(lat1)
    φ2 = radians(lat2)
    dφ = radians(lat2 - lat1)
    dλ = radians(lon2 - lon1)
    a = sin(dφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(dλ / 2) ** 2
    return R * (2 * atan2(sqrt(a), sqrt(1 - a)))

# ─── SIDEBAR ────────────────────────────────────────────────────────────────────
st.sidebar.title("🛰️ Shadow Tracker Settings-test-1.1")

data_source = st.sidebar.selectbox("Data Source", ["ADS-B Exchange", "OpenSky"], index=0)
RADIUS_KM = st.sidebar.slider("Aircraft Search Radius (km)", 5, 200, DEFAULT_RADIUS_KM)
ALERT_RADIUS_M = st.sidebar.slider("Alert Radius (m)", 1, 1000, DEFAULT_ALERT_RADIUS_M)
MAP_ZOOM = st.sidebar.slider("Map Zoom Level", 2, 18, 10)
AUTO_REFRESH = st.sidebar.checkbox("Auto Refresh Map", value=True)
REFRESH_INTERVAL = st.sidebar.number_input("Refresh Interval (s)", 1, 3600, 10)
DEBUG_MODE = st.sidebar.checkbox("Debug Mode (show raw JSON)", value=False)

adsb_key_input = st.sidebar.text_input("ADS-B Exchange API Key (api-auth)", value=ADSBEX_API_KEY or "", type="password")
if adsb_key_input:
    ADSB_HEADERS["api-auth"] = adsb_key_input
elif data_source == "ADS-B Exchange":
    st.sidebar.warning("Missing ADS-B Exchange API key; skipping ADS-B Exchange fetch.")

if st.sidebar.button("Test Pushover"):
    ok = send_pushover("🔔 Pushover test from Shadow Tracker.")
    st.sidebar.success("✅ Pushover sent!") if ok else st.sidebar.error("❌ Pushover failed.")

# ─── FETCH AIRCRAFT DATA ─────────────────────────────────────────────────────────
data = {}
acs = []

if data_source == "ADS-B Exchange":
    if "api-auth" not in ADSB_HEADERS:
        st.error("Provide ADS-B Exchange API key to fetch.")
    else:
        url = f"https://adsbexchange.com/api/aircraft/lat/{HOME_LAT}/lon/{HOME_LON}/dist/{RADIUS_KM}/"
        try:
            resp = requests.get(url, headers=ADSB_HEADERS, timeout=10)
            if resp.status_code != 200:
                st.error(f"ADS-B Exchange status {resp.status_code}: {resp.text}")
            else:
                body = resp.text.strip()
                if body:
                    try:
                        data = resp.json()
                        acs = data.get("ac", [])
                    except JSONDecodeError as jde:
                        st.error(f"JSON error: {jde}\nRaw body: {body}")
                else:
                    st.error("Empty response from ADS-B Exchange.")
        except Exception as e:
            st.error(f"Error fetching ADS-B Exchange: {e}")
elif data_source == "OpenSky":
    try:
        resp = requests.get(
            f"https://{OPENSKY_HOST}/api/states/all",
            auth=(OPENSKY_USERNAME, OPENSKY_PASSWORD),
            timeout=10
        )
        resp.raise_for_status()
        for s in resp.json().get("states", []):
            acs.append({"lat": s[6], "lon": s[5], "callsign": (s[1] or "").strip(), "hex": s[0]})
    except Exception as e:
        st.error(f"Error fetching OpenSky: {e}")

if DEBUG_MODE:
    st.sidebar.json(data)

# ─── BUILD MAP ──────────────────────────────────────────────────────────────────
m = folium.Map(location=[HOME_LAT, HOME_LON], zoom_start=MAP_ZOOM, width=1200, height=700)
folium.Marker([HOME_LAT, HOME_LON], tooltip="Home", icon=folium.Icon(icon="home", prefix="fa")).add_to(m)

for ac in acs:
    # extract and convert coordinates
    raw_lat = ac.get("lat") if isinstance(ac.get("lat"), (int, float)) else ac.get("Lat")
    raw_lon = ac.get("lon") if isinstance(ac.get("lon"), (int, float)) else ac.get("Long")
    try:
        lat = float(raw_lat)
        lon = float(raw_lon)
    except (TypeError, ValueError):
        continue

    callsign = ac.get("flight") or ac.get("callsign") or ac.get("hex") or "?"
    folium.Marker([lat, lon], tooltip=callsign, icon=folium.Icon(icon="plane", prefix="fa")).add_to(m)

    dist_m = haversine(HOME_LAT, HOME_LON, lat, lon)
    if dist_m <= ALERT_RADIUS_M:
        msg = f"🚨 {callsign} is {int(dist_m)} m from home!"
        st.sidebar.warning(msg)
        send_pushover(msg)

# render map and auto-refresh
st_folium(m, width=1200, height=700)
if AUTO_REFRESH:
    time.sleep(REFRESH_INTERVAL)
    st.experimental_rerun()
