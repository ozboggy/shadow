import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import time
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth
from streamlit_autorefresh import st_autorefresh

# Optional: moon shadows
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh every second
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except:
    pass

# Env vars
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
ADSBEX_TOKEN       = os.getenv("ADSBEX_TOKEN")

def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        st.error("🔒 Pushover credentials not set.")
        return False

    # Debug: show masked creds
    st.write(f"Sending Pushover with token {PUSHOVER_API_TOKEN[:4]}… and user {PUSHOVER_USER_KEY[:4]}…")

    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": PUSHOVER_API_TOKEN,
                "user": PUSHOVER_USER_KEY,
                "title": title,
                "message": message
            }
        )
        # Debug: HTTP status + body
        st.write(f"Pushover HTTP {resp.status_code}")
        st.write(resp.text)

        resp.raise_for_status()
        return True
    except Exception as e:
        st.error(f"Pushover request failed: {e}")
        return False

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Constants & UI
CENTER_LAT, CENTER_LON = -33.7602563, 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SEC, FORECAST_DURATION_MIN = 30, 5

with st.sidebar:
    st.header("Map Options")
    radius_km     = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun     = st.checkbox("Show Sun Shadows", True)
    show_moon     = st.checkbox("Show Moon Shadows", False)
    alert_width   = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert    = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

st.title("✈️ Aircraft Shadow Tracker (ADS-B Exchange)")
now = datetime.now(timezone.utc)

if show_moon and ephem is None:
    st.warning("PyEphem not installed; moon shadows unavailable.")
if not ADSBEX_TOKEN:
    st.warning("Please set ADSBEX_TOKEN in your environment.")

# Fetch live ADS-B data
aircraft = []
try:
    url = f"https://adsbexchange.com/api/aircraft/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {"api-auth": ADSBEX_TOKEN}
    r = requests.get(url, headers=headers); r.raise_for_status()
    data = r.json().get("ac", [])
except Exception as e:
    st.warning(f"ADS-B fetch failed: {e}")
    data = []

for ac in data:
    try:
        lat = float(ac.get("lat")); lon = float(ac.get("lon"))
        alt = float(ac.get("alt_geo") or ac.get("alt_baro") or 0.0)
        hdg = float(ac.get("track")  or ac.get("trk")      or 0.0)
        cs  = str(ac.get("flight") or ac.get("hex") or "").strip()
    except:
        continue
    aircraft.append({"lat":lat,"lon":lon,"alt":alt,"angle":hdg,"callsign":cs})

df = pd.DataFrame(aircraft)
st.sidebar.markdown(f"**Tracked Aircraft:** {len(df)}")
if df.empty:
    st.warning("No aircraft data.")
else:
    df["alt"] = pd.to_numeric(df["alt"], errors="coerce").fillna(0)

# Compute sun & moon trails (omitted for brevity; same as before…)

# Prepare IconLayer, PathLayers, Home marker (same as before, with get_radius=alert_width)

# … build and render deck.gl map …

# Real shadow alerts (same as before)…

# ——— Test buttons ———

# 1) Test Alert: on-screen + audible beep for 5 s
if test_alert:
    placeholder = st.empty()
    with placeholder:
        st.error(f"🚨 Test Shadow within {alert_width} m of home!")
        st.audio("https://www.soundjay.com/button/sounds/beep-07.wav", start_time=0)
    time.sleep(5)
    placeholder.empty()

# 2) Test Pushover: call send_pushover() and report result
if test_pushover:
    ok = send_pushover(
        "✈️ Test Shadow Alert",
        f"Test: shadow within {alert_width} m of home"
    )
    if ok:
        st.success("✅ Test Pushover sent successfully")
    else:
        st.error("❌ Test Pushover failed – check logs above")
