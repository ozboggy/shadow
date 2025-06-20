import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import requests
import pydeck as pdk
import pandas as pd
import numpy as np
import time
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth

# Attempt to import astral for moon calculations
try:
    from astral import moon
    MOON_AVAILABLE = True
except ImportError:
    MOON_AVAILABLE = False
    moon = None

# Load API credentials from .env
ADSBEX_USER = os.getenv("ADSBEXCHANGE_API_USER")
ADSBEX_TOKEN = os.getenv("ADSBEXCHANGE_API_TOKEN")
PUSH_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSH_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

# Fixed home location
HOME_LAT, HOME_LON = -33.7605327, 150.9715184

# Streamlit page config
st.set_page_config(page_title="Aircraft Shadow Forecast", layout="wide")

# Sidebar controls
st.sidebar.title("Controls")
search_radius_km = st.sidebar.slider("Search Radius (km)", 10, 200, 50)
alert_radius_m = st.sidebar.slider("Alert Radius (meters)", 100, 5000, 1000)
show_sun = st.sidebar.checkbox("Sun Shadows", value=True)
show_moon = st.sidebar.checkbox("Moon Shadows", value=False, disabled=not MOON_AVAILABLE)
if not MOON_AVAILABLE and show_moon:
    st.sidebar.warning("Astral library not installed: Moon shadows disabled.")
refresh_sec = st.sidebar.slider("Refresh Interval (seconds)", 1, 60, 5)

st.sidebar.markdown("---")
if st.sidebar.button("Test On-Screen Alert"):
    st.warning("🔔 This is a test on-screen alert")

if st.sidebar.button("Test Pushover Alert"):
    def send_pushover(title, message):
        payload = {
            "token": PUSH_API_TOKEN,
            "user": PUSH_USER_KEY,
            "title": title,
            "message": message
        }
        requests.post("https://api.pushover.net/1/messages.json", data=payload)
    send_pushover("Test Alert", "This is a test pushover message.")
    st.success("Pushover test sent!")

debug = st.sidebar.checkbox("Debug Raw Data")

# Placeholder for the map / chart
map_placeholder = st.empty()
# Sidebar status
status_placeholder = st.sidebar.empty()

# Function to fetch live aircraft from ADSB-Exchange
@st.cache_data(ttl=refresh_sec)
def fetch_aircraft(lat, lon, radius_km):
    url = "https://public-api.adsbexchange.com/VirtualRadar/AircraftList.json"
    params = {"lat": lat, "lng": lon, "fDstL": 0, "fDstU": radius_km}
    try:
        resp = requests.get(url, params=params, auth=(ADSBEX_USER, ADSBEX_TOKEN), timeout=10)
        resp.raise_for_status()
        try:
            data = resp.json().get('acList', [])
        except ValueError:
            st.sidebar.error("Error: Received invalid JSON from ADSB-Exchange.")
            data = []
    except requests.exceptions.RequestException as e:
        st.sidebar.error(f"Error fetching ADSB data: {e}")
        data = []
    return data

# Main rendering
def main():
    raw = fetch_aircraft(HOME_LAT, HOME_LON, search_radius_km)
    if debug:
        st.sidebar.json(raw)

    df = pd.DataFrame([{ 'lat': ac.get('Lat'), 'lon': ac.get('Long'), 'alt': ac.get('Alt'),
                         'track': ac.get('Trak'), 'callsign': ac.get('Call') } for ac in raw])

    shadows = []
    now = pd.Timestamp.utcnow()
    for _, row in df.iterrows():
        lat, lon, alt = row['lat'], row['lon'], row['alt']
        # Sun shadow
        if show_sun:
            solar_elev = get_sun_altitude(HOME_LAT, HOME_LON, now)
            solar_azi = get_sun_azimuth(HOME_LAT, HOME_LON, now)
            if solar_elev > 0:
                d = alt / np.tan(np.radians(solar_elev))
                bearing = solar_azi - 180
                end_lat = lat + (d/111320) * np.cos(np.radians(bearing))
                end_lon = lon + (d/(40075000*np.cos(np.radians(lat))/360)) * np.sin(np.radians(bearing))
                shadows.append({'start_lat': lat, 'start_lon': lon,
                                'end_lat': end_lat, 'end_lon': end_lon,
                                'color': [212,175,55]})
        # Moon shadow if available
        if show_moon and MOON_AVAILABLE:
            moon_azi = moon.azimuth(now, HOME_LAT, HOME_LON)
            moon_elev = moon.altitude(now, HOME_LAT, HOME_LON)
            if moon_elev > 0:
                d = alt / np.tan(np.radians(moon_elev))
                bearing = moon_azi - 180
                end_lat = lat + (d/111320) * np.cos(np.radians(bearing))
                end_lon = lon + (d/(40075000*np.cos(np.radians(lat))/360)) * np.sin(np.radians(bearing))
                shadows.append({'start_lat': lat, 'start_lon': lon,
                                'end_lat': end_lat, 'end_lon': end_lon,
                                'color': [128,128,128]})

    df_shadows = pd.DataFrame(shadows)

    layers = []
    # Home
    layers.append(pdk.Layer("ScatterplotLayer", data=pd.DataFrame([{'lat': HOME_LAT, 'lon': HOME_LON}]),
                            get_position='[lon, lat]', get_radius=alert_radius_m, radius_units='meters',
                            get_fill_color=[255, 0, 0]))
    # Aircraft
    layers.append(pdk.Layer("ScatterplotLayer", data=df,
                            get_position='[lon, lat]', get_radius=50, radius_units='meters',
                            get_fill_color=[0, 0, 255], pickable=True, auto_highlight=True))
    # Shadows
    if not df_shadows.empty:
        layers.append(pdk.Layer("LineLayer", data=df_shadows,
                                get_source_position='[start_lon, start_lat]',
                                get_target_position='[end_lon, end_lat]', get_color='color', get_width=2))

    view_state = pdk.ViewState(latitude=HOME_LAT, longitude=HOME_LON, zoom=12)
    deck = pdk.Deck(layers=layers, initial_view_state=view_state, map_style='mapbox://styles/mapbox/light-v9')
    map_placeholder.pydeck_chart(deck, use_container_width=False, width=600, height=600)

    status_placeholder.markdown(f"**Tracked Aircraft:** {len(df)}")

if __name__ == "__main__":
    if not MOON_AVAILABLE:
        st.warning("Install 'astral' via pip to enable moon shadow calculations.")
    main()
