import os
import time
import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
from math import radians, sin, cos, atan2, sqrt

# ─── CONFIG ─────────────────────────────────────────────────────────────────────
HOME_LAT = -33.76025
HOME_LON = 150.9711666
DEFAULT_RADIUS_KM = 50
DEFAULT_ALERT_RADIUS_M = 100

# OpenSky credentials (if you want to use OpenSky)
OPENSKY_HOST     = "opensky-network.org"
OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD")

# Pushover credentials (for notifications)
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN")
PUSHOVER_USER  = os.getenv("PUSHOVER_USER")

# ADS-B Exchange headers
ADSB_HEADERS = {"User-Agent": "Mozilla/5.0"}


# ─── HELPERS ────────────────────────────────────────────────────────────────────
def send_pushover(message: str, title: str = "Shadow Alert") -> bool:
    """Send a Pushover notification. Returns True on HTTP 200."""
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        return False
    payload = {
        "token":   PUSHOVER_TOKEN,
        "user":    PUSHOVER_USER,
        "message": message,
        "title":   title,
    }
    resp = requests.post("https://api.pushover.net/1/messages.json", data=payload)
    return resp.status_code == 200

def haversine(lat1, lon1, lat2, lon2):
    """Return distance between two (lat,lon) points in meters."""
    R = 6371000  # Earth radius in m
    φ1, φ2 = radians(lat1), radians(lat2)
    dφ = radians(lat2 - lat1)
    dλ = radians(lon2 - lon1)
    a = sin(dφ/2)**2 + cos(φ1)*cos(φ2)*sin(dλ/2)**2
    return R * (2 * atan2(sqrt(a), sqrt(1-a)))


# ─── SIDEBAR ────────────────────────────────────────────────────────────────────
st.sidebar.title("🛰️ Shadow Tracker Settings")

data_source    = st.sidebar.selectbox(
    "Data Source",
    ["ADS-B Exchange", "OpenSky"],
    index=0
)

RADIUS_KM      = st.sidebar.slider(
    "Aircraft Search Radius (km)",
    min_value=5, max_value=200, value=DEFAULT_RADIUS_KM
)

ALERT_RADIUS_M = st.sidebar.slider(
    "Alert Radius (m)",
    min_value=1, max_value=1000, value=DEFAULT_ALERT_RADIUS_M
)

MAP_ZOOM       = st.sidebar.slider(
    "Map Zoom Level", min_value=2, max_value=18, value=10
)

AUTO_REFRESH   = st.sidebar.checkbox(
    "Auto Refresh Map", value=True
)

REFRESH_INTERVAL = st.sidebar.number_input(
    "Refresh Interval (s)",
    min_value=1, max_value=3600, value=10
)

DEBUG_MODE     = st.sidebar.checkbox(
    "Debug Mode (show raw JSON)", value=False
)

# ─── PUSHPUSHER TEST ─────────────────────────────────────────────────────────────
if st.sidebar.button("Test Pushover"):
    ok = send_pushover("🔔 This is a Pushover test from Shadow Tracker.")
    if ok:
        st.sidebar.success("✅ Pushover notification sent!")
    else:
        st.sidebar.error("❌ Pushover failed (check TOKEN/USER).")


# ─── FETCH AIRCRAFT DATA ─────────────────────────────────────────────────────────
data = {}
acs  = []

if data_source == "ADS-B Exchange":
    url = (
        "https://public-api.adsbexchange.com/VirtualRadar/AircraftList.json"
        f"?lat={HOME_LAT}&lng={HOME_LON}"
        f"&fDstL=0&fDstU={RADIUS_KM}"
    )
    try:
        resp = requests.get(url, headers=ADSB_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        acs  = data.get("acList", [])
    except Exception as e:
        st.error(f"Error fetching ADS-B Exchange: {e}")

elif data_source == "OpenSky":
    url = f"https://{OPENSKY_HOST}/api/states/all"
    try:
        resp = requests.get(
            url,
            auth=(OPENSKY_USERNAME, OPENSKY_PASSWORD),
            timeout=10
        )
        resp.raise_for_status()
        raw = resp.json().get("states", [])
        # Map to same shape as ADS-B Exchange for simplicity
        for s in raw:
            acs.append({
                "hex":      s[0],
                "callsign": (s[1] or "").strip(),
                "lat":      s[6],
                "lon":      s[5],
            })
    except Exception as e:
        st.error(f"Error fetching OpenSky: {e}")

# ─── DEBUG RAW JSON ──────────────────────────────────────────────────────────────
if DEBUG_MODE:
    st.sidebar.write("Raw JSON:")
    st.sidebar.json(data)


# ─── BUILD FOLIUM MAP ────────────────────────────────────────────────────────────
m = folium.Map(
    location=[HOME_LAT, HOME_LON],
    zoom_start=MAP_ZOOM,
    width=1200,
    height=700
)

# Home marker (house icon)
folium.Marker(
    [HOME_LAT, HOME_LON],
    tooltip="Home",
    icon=folium.Icon(icon="home", prefix="fa")
).add_to(m)


# Aircraft markers + alert checks
for ac in acs:
    lat = ac.get("Lat")  or ac.get("lat")
    lon = ac.get("Long") or ac.get("lon")
    if lat is None or lon is None:
        continue

    callsign = ac.get("Call") or ac.get("callsign") or ac.get("hex") or "?"
    # Place plane marker with tooltip = callsign
    folium.Marker(
        [lat, lon],
        tooltip=callsign,
        icon=folium.Icon(icon="plane", prefix="fa")
    ).add_to(m)

    # Distance check for alerts
    dist_m = haversine(HOME_LAT, HOME_LON, lat, lon)
    if dist_m <= ALERT_RADIUS_M:
        msg = f"🚨 {callsign} is {int(dist_m)} m from home!"
        st.sidebar.warning(msg)
        send_pushover(msg)


# ─── RENDER & AUTO-REFRESH ───────────────────────────────────────────────────────
st_data = st_folium(m, width=1200, height=700)

if AUTO_REFRESH:
    time.sleep(REFRESH_INTERVAL)
    st.experimental_rerun()
