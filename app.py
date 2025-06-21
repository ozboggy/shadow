import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import requests
import pydeck as pdk
import pandas as pd
import numpy as np
import math
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth
from streamlit_autorefresh import st_autorefresh

# Attempt to import astral for moon calculations
try:
    from astral import moon
    MOON_AVAILABLE = True
except ImportError:
    MOON_AVAILABLE = False
    moon = None

# Auto-refresh data only
st_autorefresh(interval=1000, key="datarefresh")

# Load API credentials
ADSBEX_USER = os.getenv("ADSBEXCHANGE_API_USER")
ADSBEX_TOKEN = os.getenv("ADSBEXCHANGE_API_TOKEN")
PUSH_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSH_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

# Fixed home location
HOME_LAT, HOME_LON = -33.7605327, 150.9715184

# Forecast settings
FORECAST_INTERVAL_SECONDS = st.sidebar.number_input("Forecast Interval (s)", min_value=1, max_value=60, value=30)
FORECAST_DURATION_MINUTES = st.sidebar.number_input("Forecast Duration (min)", min_value=1, max_value=60, value=5)

# Sidebar controls
st.sidebar.title("Controls")
radius_km = st.sidebar.slider("Search Radius (km)", 1, 200, 50)
alert_width = st.sidebar.slider("Shadow Alert Width (m)", 0, 5000, 50)
show_sun = st.sidebar.checkbox("Show Sun Shadows", True)
show_moon = st.sidebar.checkbox("Show Moon Shadows", False, disabled=not MOON_AVAILABLE)

st.sidebar.markdown("---")
if st.sidebar.button("Test On-Screen Alert"):
    st.warning("🔔 Test on-screen alert")
if st.sidebar.button("Test Pushover Alert"):
    def send_pushover(title, message):
        if not PUSH_USER_KEY or not PUSH_API_TOKEN:
            st.error("Pushover credentials missing.")
            return
        try:
            requests.post(
                "https://api.pushover.net/1/messages.json",
                data={"token": PUSH_API_TOKEN, "user": PUSH_USER_KEY, "title": title, "message": message}
            )
        except Exception as e:
            st.error(f"Pushover failed: {e}")
    send_pushover("Test Alert", "This is a test pushover message.")
    st.success("Pushover test sent")

# Haversine for alerts
def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Fetch ADS-B Exchange data
@st.cache_data(ttl=1)
def fetch_adsb():
    url = f"https://public-api.adsbexchange.com/VirtualRadar/AircraftList.json"
    params = {"lat": HOME_LAT, "lng": HOME_LON, "fDstL": 0, "fDstU": radius_km}
    try:
        resp = requests.get(url, params=params, auth=(ADSBEX_USER, ADSBEX_TOKEN), timeout=10)
        resp.raise_for_status()
        return resp.json().get('acList', [])
    except Exception:
        return []

# Main logic
st.title("✈️ Aircraft Shadow Tracker")
raw = fetch_adsb()
if not raw:
    st.warning("No aircraft data.")

# Parse
df = pd.DataFrame([{ 'lat': ac.get('Lat'), 'lon': ac.get('Long'), 'alt': ac.get('Alt'),
                    'track': ac.get('Trak'), 'spd': ac.get('Spd') or 0, 'callsign': ac.get('Call') }
                   for ac in raw])
if not df.empty:
    df[['alt','spd','track']] = df[['alt','spd','track']].apply(pd.to_numeric, errors='coerce').fillna(0)

# Forecast trails
trails = []
now = datetime.now(timezone.utc)
if show_sun or (show_moon and MOON_AVAILABLE):
    for _, row in df.iterrows():
        path = []
        lat0, lon0 = row['lat'], row['lon']
        for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
            t = now + timedelta(seconds=i)
            # Move aircraft
            d_m = row['spd'] * i
            dlat = d_m * math.cos(math.radians(row['track'])) / 111111
            dlon = d_m * math.sin(math.radians(row['track'])) / (111111 * math.cos(math.radians(lat0)))
            lat_i = lat0 + dlat; lon_i = lon0 + dlon
            # Sun
            if show_sun:
                elev = get_sun_altitude(lat_i, lon_i, t)
                azi = get_sun_azimuth(lat_i, lon_i, t)
                if elev > 0:
                    sd = row['alt'] / math.tan(math.radians(elev))
                    sh_lat = lat_i + (sd/111111) * math.cos(math.radians(azi+180))
                    sh_lon = lon_i + (sd/(111111 * math.cos(math.radians(lat_i)))) * math.sin(math.radians(azi+180))
                    path.append([sh_lon, sh_lat])
        if path:
            trails.append({'path': path, 'callsign': row['callsign']})

# Build map layers
layers = []
layers.append(pdk.Layer("ScatterplotLayer", data=df,
                         get_position=["lon","lat"], get_radius=50, radius_units="meters",
                         get_fill_color=[0,0,255], pickable=True))
if trails:
    layers.append(pdk.Layer("PathLayer", data=pd.DataFrame(trails), get_path="path",
                             get_color=[212,175,55], width_scale=10, width_min_pixels=2))
layers.append(pdk.Layer("ScatterplotLayer", data=pd.DataFrame([{"lat": HOME_LAT, "lon": HOME_LON}]),
                         get_position=["lon","lat"], get_radius=alert_width, radius_units="meters",
                         get_fill_color=[255,0,0,50]))

view = pdk.ViewState(latitude=HOME_LAT, longitude=HOME_LON, zoom=12)
deck = pdk.Deck(layers=layers, initial_view_state=view, map_style="mapbox://styles/mapbox/light-v9")
st.pydeck_chart(deck, use_container_width=False, width=600, height=600)

# Alerts
if trails:
    for tr in trails:
        for lon, lat in tr['path']:
            if hav(lat, lon, HOME_LAT, HOME_LON) <= alert_width:
                st.error(f"🚨 Shadow of {tr['callsign']} over home!")
                # Pushover
                if PUSH_USER_KEY and PUSH_API_TOKEN:
                    try:
                        requests.post(
                            "https://api.pushover.net/1/messages.json",
                            data={"token": PUSH_API_TOKEN, "user": PUSH_USER_KEY,
                                  "title": "✈️ Shadow Alert", "message": f"{tr['callsign']} shadow at home"}
                        )
                    except:
                        pass
                break

st.sidebar.markdown(f"**Tracked Aircraft:** {len(df)}")
