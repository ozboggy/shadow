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
# Will inject 'api-auth' header if provided
ADSB_HEADERS = {"User-Agent": "Mozilla/5.0"}

# ─── HELPERS ────────────────────────────────────────────────────────────────────
def send_pushover(message: str, title: str = "Shadow Alert") -> bool:
    """Send a Pushover notification. Returns True on HTTP 200."""
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        return False
    resp = requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": PUSHOVER_TOKEN,
            "user":  PUSHOVER_USER,
            "message": message,
            "title":   title,
        }
    )
    return resp.status_code == 200


def haversine(lat1, lon1, lat2, lon2):
    """Return distance between two (lat,lon) points in meters."""
    # ensure numeric types
    if any(v is None for v in (lat1, lon1, lat2, lon2)):
        return float('inf')
    R = 6371000  # Earth radius in meters
    φ1, φ2 = radians(lat1), radians(lat2)
    dφ = radians(lat2 - lat1)
    dλ = radians(lon2 - lon1)
    a = sin(dφ/2)**2 + cos(φ1)*cos(φ2)*sin(dλ/2)**2
    return R * (2 * atan2(sqrt(a), sqrt(1-a)))

# ─── SIDEBAR ────────────────────────────────────────────────────────────────────
st.sidebar.title("🛰️ Shadow Tracker Settings")

data_source = st.sidebar.selectbox(
    "Data Source",
    ["ADS-B Exchange", "OpenSky"],
    index=0
)

RADIUS_KM      = st.sidebar.slider("Aircraft Search Radius (km)", 5, 200, DEFAULT_RADIUS_KM)
ALERT_RADIUS_M = st.sidebar.slider("Alert Radius (m)", 1, 1000, DEFAULT_ALERT_RADIUS_M)
MAP_ZOOM       = st.sidebar.slider("Map Zoom Level", 2, 18, 10)
AUTO_REFRESH   = st.sidebar.checkbox("Auto Refresh Map", value=True)
REFRESH_INTERVAL = st.sidebar.number_input("Refresh Interval (s)", 1, 3600, 10)
DEBUG_MODE     = st.sidebar.checkbox("Debug Mode (show raw JSON)", value=False)

# Enter ADS-B Exchange API Lite key
adsb_key_input = st.sidebar.text_input(
    "ADS-B Exchange API Key (api-auth)",
    value=ADSBEX_API_KEY or "",
    type="password"
)
if adsb_key_input:
    ADSB_HEADERS["api-auth"] = adsb_key_input
elif data_source == "ADS-B Exchange":
    st.sidebar.warning("No ADS-B Exchange API key provided. ADS-B Exchange fetch will be skipped.")

if st.sidebar.button("Test Pushover"):
    ok = send_pushover("🔔 This is a Pushover test from Shadow Tracker.")
    if ok:
        st.sidebar.success("✅ Pushover sent!")
    else:
        st.sidebar.error("❌ Pushover failed.")

# ─── FETCH AIRCRAFT DATA ─────────────────────────────────────────────────────────
data = {}
acs  = []

if data_source == "ADS-B Exchange":
    # skip if no API key
    if "api-auth" not in ADSB_HEADERS:
        st.error("Missing ADS-B Exchange API key. Please enter it in the sidebar.")
    else:
        url = (
            "https://adsbexchange.com/api/aircraft/"
            f"lat/{HOME_LAT}/lon/{HOME_LON}/dist/{RADIUS_KM}/"
        )
        try:
            resp = requests.get(url, headers=ADSB_HEADERS, timeout=10)
            if resp.status_code != 200:
                st.error(f"ADS-B Exchange returned {{resp.status_code}}: {{resp.text}}")
            else:
                text = resp.text.strip()
                if not text:
                    st.error("ADS-B Exchange returned an empty response.")
                else:
                    try:
                        data = resp.json()
                        # Lite endpoint returns { "ac": [...] }
                        acs = data.get("ac", [])
                    except JSONDecodeError as jde:
                        st.error(f"JSON parse error: {{jde}}. Raw: {{text}}")
        except Exception as e:
            st.error(f"Error fetching ADS-B Exchange: {{e}}")

elif data_source == "OpenSky":
    url = f"https://{OPENSKY_HOST}/api/states/all"
    try:
        resp = requests.get(
            url,
            auth=(OPENSKY_USERNAME, OPENSKY_PASSWORD),
            timeout=10
        )
        resp.raise_for_status()
        raw_states = resp.json().get("states", [])
        for s in raw_states:
            acs.append({
                "lat":      s[6],
                "lon":      s[5],
                "callsign": (s[1] or "").strip(),
                "hex":      s[0],
            })
    except Exception as e:
        st.error(f"Error fetching OpenSky: {{e}}")

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

# Home marker
folium.Marker(
    [HOME_LAT, HOME_LON],
    tooltip="Home",
    icon=folium.Icon(icon="home", prefix="fa")
).add_to(m)

# Aircraft markers & alerts
for ac in acs:
    # normalize coordinate keys
    lat = ac.get("lat") if isinstance(ac.get("lat"), (int,float)) else ac.get("Lat")
    lon = ac.get("lon") if isinstance(ac.get("lon"), (int,float)) else ac.get("Long")
    if lat is None or lon is None:
        continue

    callsign = ac.get("Call") or ac.get("callsign") or ac.get("hex") or "?"
    folium.Marker(
        [lat, lon],
        tooltip=callsign,
        icon=folium.Icon(icon="plane", prefix="fa")
    ).add_to(m)

    dist_m = haversine(HOME_LAT, HOME_LON, lat, lon)
    if dist_m <= ALERT_RADIUS_M:
        msg = f"🚨 {callsign} is {int(dist_m)} m from home!"
        st.sidebar.warning(msg)
        send_pushover(msg)

# render map
st_folium(m, width=1200, height=700)

# auto-refresh
if AUTO_REFRESH:
    time.sleep(REFRESH_INTERVAL)
    st.experimental_rerun()
