
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

try:
    import ephem
except ImportError:
    ephem = None

try:
    st_autorefresh(interval=1000, key="refresh")
except:
    pass

PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title: str, message: str) -> bool:
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return False
    try:
        r = requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message
        })
        r.raise_for_status()
        return True
    except Exception as e:
        st.error(f"Pushover Error: {e}")
        return False

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 5
FORECAST_DURATION_MINUTES = 5
alert_times = [60, 30, 15, 10, 5, 0]

with st.sidebar:
    st.header("Map Options")
    radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun = st.checkbox("Show Sun Shadows", True)
    track_moon = st.checkbox("Show Moon Shadows", False)
    alert_width = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

now_utc = datetime.now(timezone.utc)
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
moon_alt = None

if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon = str(CENTER_LAT), str(CENTER_LON)
    obs.date = now_utc
    moon_obs = ephem.Moon(obs)
    moon_alt = math.degrees(moon_obs.alt)

aircraft_list = []
api_key = os.getenv("RAPIDAPI_KEY")
adsb = []
if api_key:
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
    }
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        adsb = r.json().get("ac", [])
    except:
        st.warning("ADS-B fetch failed")

for ac in adsb:
    try:
        lat = float(ac.get("lat")); lon = float(ac.get("lon"))
        cs = (ac.get("flight") or ac.get("hex") or "").strip()
        alt = float(ac.get("alt_geo") or ac.get("alt_baro") or 0)
        vel = float(ac.get("gs") or ac.get("spd") or 0)
        hdg = float(ac.get("track") or ac.get("trak") or 0)
        if alt > 0:
            aircraft_list.append({"lat": lat, "lon": lon, "alt": alt, "vel": vel, "hdg": hdg, "callsign": cs})
    except:
        continue

df_ac = pd.DataFrame(aircraft_list)
if not df_ac.empty:
    df_ac[['alt', 'vel', 'hdg']] = df_ac[['alt', 'vel', 'hdg']].apply(pd.to_numeric, errors='coerce').fillna(0)

st.sidebar.markdown("### Status")
st.sidebar.markdown(f"Sun altitude: {'🟢' if sun_alt > 0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.sidebar.markdown(f"Moon altitude: {'🟢' if moon_alt > 0 else '🔴'} {moon_alt:.1f}°")
st.sidebar.markdown(f"Tracking **{len(df_ac)}** aircraft")

# Home location marker
home_df = pd.DataFrame([{"lat": CENTER_LAT, "lon": CENTER_LON}])

# Layers
layers = []

# Aircraft
if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=df_ac,
        get_position=["lon", "lat"],
        get_fill_color=[0, 128, 255, 200],
        get_radius=300,
        pickable=True,
        auto_highlight=True
    ))

# Home marker
layers.append(pdk.Layer(
    "ScatterplotLayer",
    data=home_df,
    get_position=["lon", "lat"],
    get_fill_color=[255, 0, 0],
    get_radius=alert_width,
    pickable=False
))

# Map
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
deck = pdk.Deck(
    layers=layers,
    initial_view_state=view,
    map_style="light",
    tooltip={
        "html": (
            "<b>Callsign:</b> {callsign}<br/>"
            "<b>Altitude:</b> {alt} ft<br/>"
            "<b>Speed:</b> {vel} kts<br/>"
            "<b>Heading:</b> {hdg}°"
        ),
        "style": {
            "backgroundColor": "black",
            "color": "white",
            "cursor": "pointer"
        }
    }
)

st.pydeck_chart(deck, use_container_width=True)
