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

# Optional moon support
try:
    import ephem
except ImportError:
    ephem = None

# Auto‐refresh every second
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except:
    pass

# Environment variables
PUSHOVER_USER_KEY   = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN  = os.getenv("PUSHOVER_API_TOKEN")
ADSBEX_TOKEN        = os.getenv("ADSBEX_TOKEN")

def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        st.error("🔒 Missing PUSHOVER_USER_KEY or PUSHOVER_API_TOKEN in environment")
        return False

    payload = {
        "token":   PUSHOVER_API_TOKEN,
        "user":    PUSHOVER_USER_KEY,
        "title":   title,
        "message": message
    }
    resp = requests.post("https://api.pushover.net/1/messages.json", data=payload)

    # try to parse JSON error details
    try:
        result = resp.json()
    except ValueError:
        result = None

    if resp.status_code != 200:
        if result and "errors" in result:
            st.error(f"Pushover error: {result['errors']}")
        else:
            st.error(f"Pushover HTTP {resp.status_code}: {resp.text}")
        return False

    return True

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

# Constants
CENTER_LAT            = -33.7602563
CENTER_LON            = 150.9717434
DEFAULT_RADIUS_KM     = 10
FORECAST_INTERVAL_SEC = 30
FORECAST_DURATION_MIN = 5

# Current UTC time
now = datetime.now(timezone.utc)

# Compute sun altitude at home
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now)

# Compute moon altitude at home if PyEphem is available
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now
    moon_alt = math.degrees(float(ephem.Moon(obs).alt))
else:
    moon_alt = None

# Sidebar
with st.sidebar:
    st.header("Map Options")

    # Sun altitude display
    sun_color = "green" if sun_alt > 0 else "red"
    st.markdown(
        f"**Sun altitude:** <span style='color:{sun_color};'>{sun_alt:.1f}°</span>",
        unsafe_allow_html=True
    )

    # Moon altitude display
    if moon_alt is not None:
        moon_color = "green" if moon_alt > 0 else "red"
        st.markdown(
            f"**Moon altitude:** <span style='color:{moon_color};'>{moon_alt:.1f}°</span>",
            unsafe_allow_html=True
        )
    else:
        st.markdown("**Moon altitude:** _(PyEphem not installed)_")

    # Controls
    radius_km           = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    military_radius_km  = st.slider("Military Alert Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun           = st.checkbox("Show Sun Shadows", True)
    show_moon           = st.checkbox("Show Moon Shadows", False)
    alert_width         = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert          = st.button("Test Alert")
    test_pushover       = st.button("Test Pushover")

st.title("✈️ Aircraft Shadow Tracker (ADS-B Exchange)")

# Fetch live ADS-B Exchange data
aircraft_list = []
if not ADSBEX_TOKEN:
    st.warning("Please set ADSBEX_TOKEN in your environment.")
else:
    try:
        url = f"https://adsbexchange.com/api/aircraft/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        headers = {"api-auth": ADSBEX_TOKEN}
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json().get("ac", [])
    except Exception as e:
        st.warning(f"ADS-B fetch failed: {e}")
        data = []

    for ac in data:
        try:
            lat   = float(ac.get("lat"))
            lon   = float(ac.get("lon"))
            alt   = float(ac.get("alt_geo") or ac.get("alt_baro") or 0.0)
            angle = float(ac.get("track")  or ac.get("trk")      or 0.0)
            cs    = str(ac.get("flight") or ac.get("hex") or "").strip()
            mil   = bool(ac.get("mil", False))
        except (TypeError, ValueError):
            continue
        aircraft_list.append({
            "lat": lat, "lon": lon, "alt": alt,
            "angle": angle, "callsign": cs, "mil": mil
        })

# Build DataFrame & show count
df_ac = pd.DataFrame(aircraft_list)
st.sidebar.markdown(f"**Tracked Aircraft:** {len(df_ac)}")
if not df_ac.empty:
    df_ac["alt"] = pd.to_numeric(df_ac["alt"], errors="coerce").fillna(0)
else:
    st.warning("No aircraft data available.")

# (…rest of your trail computation, layers, and alerts remains unchanged…)

# Test buttons
if test_alert:
    st.error(f"🚨 Test Shadow Alert: within {alert_width} m!")

if test_pushover:
    if send_pushover("✈️ Test Shadow Alert", f"Test within {alert_width} m"):
        st.success("✅ Pushover test succeeded")
    else:
        st.error("❌ Pushover test failed – see above for details")
