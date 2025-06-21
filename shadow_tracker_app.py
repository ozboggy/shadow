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

# Optional moon computations
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh every second
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except Exception:
    pass

# Pushover credentials
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title: str, message: str) -> bool:
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return False
    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        st.error(f"Pushover API error: {e}")
        return False

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Defaults
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5

# Sidebar controls
with st.sidebar:
    st.header("Map Options")
    radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun = st.checkbox("Show Sun Shadows", True)
    track_moon = st.checkbox("Show Moon Shadows", False)
    alert_width = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

# Current UTC time
now_utc = datetime.now(timezone.utc)

# Compute sun & moon altitude at center
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon = str(CENTER_LAT), str(CENTER_LON)
    obs.date = now_utc
    moon_obs = ephem.Moon(obs)
    moon_alt = math.degrees(moon_obs.alt)

# Fetch ADS-B Exchange data
aircraft_list = []
api_key = os.getenv("RAPIDAPI_KEY")
adsb = []
if api_key:
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        adsb = r.json().get("ac", [])
    except Exception:
        st.warning("Failed to fetch ADS-B data.")

for ac in adsb:
    try:
        lat = float(ac.get("lat")); lon = float(ac.get("lon"))
    except (TypeError, ValueError):
        continue
    cs = (ac.get("flight") or ac.get("hex") or "").strip()
    try:
        alt_val = float(ac.get("alt_geo") or ac.get("alt_baro") or 0)
    except (TypeError, ValueError):
        alt_val = 0.0
    try:
        vel = float(ac.get("gs") or ac.get("spd") or 0)
    except (TypeError, ValueError):
        vel = 0.0
    try:
        hdg = float(ac.get("track") or ac.get("trak") or 0)
    except (TypeError, ValueError):
        hdg = 0.0

    # —— NEW: detect military flag if present —— #
    mil = bool(ac.get("mil", False))

    if alt_val > 0:
        aircraft_list.append({
            "lat": lat,
            "lon": lon,
            "alt": alt_val,
            "vel": vel,
            "hdg": hdg,
            "callsign": cs,
            "mil": mil
        })

# Build DataFrame
df_ac = pd.DataFrame(aircraft_list)
if not df_ac.empty:
    df_ac[['alt', 'vel', 'hdg']] = (
        df_ac[['alt', 'vel', 'hdg']]
        .apply(pd.to_numeric, errors='coerce')
        .fillna(0)
    )
    # Map boolean to human label for tooltip
    df_ac['type'] = df_ac['mil'].map({True: 'Military', False: 'Civilian'})

# Sidebar status
st.sidebar.markdown("### Status")
st.sidebar.markdown(f"Sun altitude: {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.sidebar.markdown(f"Moon altitude: {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.sidebar.warning("Moon data unavailable")
st.sidebar.markdown(f"Total airborne aircraft: **{len(df_ac)}**")
st.sidebar.markdown(f"Military aircraft: **{df_ac['mil'].sum()}**")

# Compute shadow paths (unchanged) …
# [your existing shadow‐calculation code here]

# Build map layers
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []

# [your existing shadow layers for sun_trails & moon_trails here]

# Alert circle: brighter red (unchanged)
# [your existing alert-circle layer here]

# —— UPDATED: split aircraft into civilian vs military layers —— #
if not df_ac.empty:
    # Civilian aircraft (blue)
    df_civ = df_ac[~df_ac['mil']]
    if not df_civ.empty:
        layers.append(pdk.Layer(
            "ScatterplotLayer", df_civ,
            get_position=["lon","lat"],
            get_fill_color=[0,128,255,200],
            get_radius=300,
            pickable=True, auto_highlight=True, highlight_color=[255,255,0,255]
        ))
    # Military aircraft (red, larger)
    df_mil = df_ac[df_ac['mil']]
    if not df_mil.empty:
        layers.append(pdk.Layer(
            "ScatterplotLayer", df_mil,
            get_position=["lon","lat"],
            get_fill_color=[255,0,0,255],
            get_radius=400,
            pickable=True, auto_highlight=True, highlight_color=[255,255,0,255]
        ))

# Tooltip now includes type
tooltip = {
    "html": (
        "<b>Callsign:</b> {callsign}<br/>"
        "<b>Type:</b> {type}<br/>"
        "<b>Alt:</b> {alt} m<br/>"
        "<b>Speed:</b> {vel} m/s<br/>"
        "<b>Heading:</b> {hdg}°"
    ),
    "style": {"backgroundColor":"black","color":"white"}
}

# Render
deck = pdk.Deck(layers=layers, initial_view_state=view, map_style="light", tooltip=tooltip)
st.pydeck_chart(deck, use_container_width=True)

# [your existing alert‐loop and test buttons here]


# Alerts with screen, audio, and pushover
beep_html = """
<audio autoplay>
  <source src="https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg" type="audio/ogg">
</audio>
"""
if track_sun and sun_trails:
    for tr in sun_trails:
        for lon, lat in tr["path"]:
            if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
                st.error(f"🚨 Sun shadow of {tr['callsign']} over home!")
                st.markdown(beep_html, unsafe_allow_html=True)
                send_pushover("✈️ Shadow Alert", f"{tr['callsign']} shadow at home")
                break
if track_moon and moon_trails:
    for tr in moon_trails:
        for lon, lat in tr["path"]:
            if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
                st.error(f"🚨 Moon shadow of {tr['callsign']} over home!")
                st.markdown(beep_html, unsafe_allow_html=True)
                send_pushover("✈️ Moon Shadow Alert", f"{tr['callsign']} moon shadow at home")
                break

# Test alert with audio
if test_alert:
    ph = st.empty()
    ph.success("🔔 Test alert triggered!")
    st.markdown(beep_html, unsafe_allow_html=True)
    time.sleep(5)
    ph.empty()

# Test pushover
if test_pushover:
    ph2 = st.empty()
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        ph2.error("⚠️ Missing Pushover credentials")
    else:
        ok = send_pushover("✈️ Test", "This is a test from your app.")
        ph2.success("✅ Test Pushover sent!" if ok else "❌ Test Pushover failed")
    time.sleep(5)
    ph2.empty()
