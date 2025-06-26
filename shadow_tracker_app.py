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
        return resp.status_code == 200
    except Exception:
        return False

# Home location (edit as required)
CENTER_LAT = float(os.getenv("HOME_LAT", "-33.8688"))
CENTER_LON = float(os.getenv("HOME_LON", "151.2093"))
HOME_ALT = float(os.getenv("HOME_ALT", "10"))

# Fixed search radius (miles)
RADIUS_MI = 10
RADIUS_KM = RADIUS_MI * 1.60934

# Alert radius for aircraft (m)
ALERT_WIDTH = 100

st.set_page_config(page_title="Live Aircraft Shadow Tracker", layout="wide")
st.title("✈️ Live Aircraft Shadow Tracker")

# --- SIDEBAR (info only, no controls) ---
with st.sidebar:
    # Aircraft count will be added after data fetch
    st.markdown("### Tracker Info")
    # Sun altitude
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
    sun_az = get_azimuth(CENTER_LAT, CENTER_LON, now_utc)
    sun_col = "green" if sun_alt > 0 else "red"
    st.markdown(f"<span style='color:{sun_col}'>☀️ Sun Altitude: {sun_alt:.1f}°</span>", unsafe_allow_html=True)

    # Moon altitude (if ephem available)
    if ephem:
        obs = ephem.Observer()
        obs.lat, obs.lon, obs.elevation = str(CENTER_LAT), str(CENTER_LON), HOME_ALT
        moon = ephem.Moon(obs)
        moon_alt = math.degrees(moon.alt)
        moon_col = "green" if moon_alt > 0 else "red"
        st.markdown(f"<span style='color:{moon_col}'>🌕 Moon Altitude: {moon_alt:.1f}°</span>", unsafe_allow_html=True)
    st.write("---")  # Divider for aircraft count

# Aircraft data source
def fetch_adsb_data(lat, lon, radius_km):
    try:
        url = f"https://public-api.adsbexchange.com/VirtualRadar/AircraftList.json?lat={lat}&lng={lon}&fDstL=0&fDstU={radius_km}"
        resp = requests.get(url, timeout=10)
        # If the content is not JSON, raise error for user feedback
        try:
            data = resp.json()
        except Exception:
            st.error("❌ Unable to fetch aircraft data (API returned invalid response). This is usually temporary—try again soon.")
            return pd.DataFrame([])
        ac_list = []
        for ac in data.get('acList', []):
            if 'Lat' in ac and 'Long' in ac and ac.get('Alt') is not None:
                ac_list.append({
                    'lat': ac['Lat'],
                    'lon': ac['Long'],
                    'alt': ac['Alt'],
                    'callsign': ac.get('Call', 'N/A'),
                    'vel': ac.get('Spd', 0),
                    'hdg': ac.get('Trak', 0),
                    'icao': ac.get('Icao', ''),
                })
        return pd.DataFrame(ac_list)
    except Exception as e:
        st.error(f"❌ Failed to fetch aircraft data: {e}")
        return pd.DataFrame([])

df_ac = fetch_adsb_data(CENTER_LAT, CENTER_LON, RADIUS_KM)

# Update aircraft count in the sidebar
with st.sidebar:
    st.markdown(f"**Tracked Aircraft:** {len(df_ac)}")

# Draw radius circles for 1, 2, 5, 10 miles
def get_circle(lat, lon, radius_m):
    steps = 72
    return [
        [
            lon + (radius_m/111320) * math.cos(2*math.pi/steps*x) / math.cos(math.radians(lat)),
            lat + (radius_m/110540) * math.sin(2*math.pi/steps*x)
        ]
        for x in range(steps+1)
    ]

# Build map layers
layers = []

# Radius circles (1,2,5,10 miles only)
circle_mile_radii = [1, 2, 5, 10]
for r_mi in circle_mile_radii:
    r_m = r_mi * 1609.34
    circle = get_circle(CENTER_LAT, CENTER_LON, r_m)
    layers.append(
        pdk.Layer(
            "PolygonLayer",
            data=[{"polygon": circle}],
            get_polygon="polygon",
            get_fill_color=[0, 0, 0, 0],
            get_line_color=[200, 200, 200, 180],
            get_line_width=2,
            pickable=False
        )
    )

# Home marker
layers.append(
    pdk.Layer(
        "ScatterplotLayer",
        data=pd.DataFrame([{"lat": CENTER_LAT, "lon": CENTER_LON}]),
        get_position="[lon, lat]",
        get_radius=ALERT_WIDTH,
        get_fill_color=[0, 128, 255, 120],
        pickable=True,
        opacity=0.7
    )
)

# Aircraft icons
if not df_ac.empty:
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=df_ac,
            get_position="[lon, lat]",
            get_radius=70,
            get_fill_color=[255, 0, 0, 200],
            pickable=True,
            opacity=0.85
        )
    )

# Map view
view = pdk.ViewState(
    longitude=CENTER_LON,
    latitude=CENTER_LAT,
    zoom=10,
    pitch=0,
    bearing=0
)

# Map rendering
st.pydeck_chart(
    pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style="mapbox://styles/mapbox/dark-v11",
        tooltip={
            "html": "<b>Callsign:</b> {callsign}<br/><b>Alt:</b> {alt} ft<br/><b>Speed:</b> {vel} kts<br/><b>Heading:</b> {hdg}",
            "style": {"backgroundColor": "black", "color": "white"}
        }
    ),
    use_container_width=True
)

st.caption(f"Tracking aircraft within **{RADIUS_MI} miles** of home.")

