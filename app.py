
import streamlit as st
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
import requests
import pandas as pd
import pydeck as pdk
from math import radians, sin, cos, asin, sqrt, tan
from pysolar.solar import get_altitude as solar_altitude, get_azimuth as solar_azimuth
try:
    import ephem
    MOON_AVAILABLE = True
except ImportError:
    MOON_AVAILABLE = False

# Load env
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

# Credentials for Pushover
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

# Home coords
HOME_LAT, HOME_LON = -33.7608288, 150.9713948

# Sidebar controls
st.sidebar.title("☀️🌙 Shadow Forecast Settings")
selected_date = st.sidebar.date_input("Date (UTC)", datetime.utcnow().date())
selected_time = st.sidebar.time_input("Time (UTC)", datetime.utcnow().time().replace(second=0, microsecond=0))
t0 = datetime.combine(selected_date, selected_time).replace(tzinfo=timezone.utc)
show_sun = st.sidebar.checkbox("Show Sun Shadows", True)
show_moon = False
if MOON_AVAILABLE:
    show_moon = st.sidebar.checkbox("Show Moon Shadows", False)
else:
    st.sidebar.markdown("*Install `pip install ephem` for moon shadows*")
alert_radius = st.sidebar.slider("Alert Radius (m)", 10, 200, 50, 5)
radius_km = st.sidebar.slider("Search Radius (km)", 10, 200, 50, 10)
zoom = st.sidebar.slider("Map Zoom Level", 1, 20, 12)
debug = st.sidebar.checkbox("Debug Mode", False)

# Local ADS-B feed URL
host = st.sidebar.text_input("ADS-B Host", "localhost")
port = st.sidebar.text_input("ADS-B Port", "8080")
path = st.sidebar.text_input("ADS-B Path", "/data/aircraft.json")
feed_url = f"http://{host}:{port}{path}"
st.sidebar.write("Using feed URL:", feed_url)

# Fetch positions
try:
    raw = requests.get(feed_url, timeout=5).json()
except Exception as e:
    st.error(f"Local ADS-B feed error: {e}")
    st.stop()

aircraft = raw.get("aircraft") if isinstance(raw, dict) else raw
positions = []
for ent in aircraft or []:
    if not isinstance(ent, dict): continue
    lat = ent.get("lat") or ent.get("latitude")
    lon = ent.get("lon") or ent.get("longitude")
    if lat is None or lon is None: continue
    positions.append({
        "lat": lat,
        "lon": lon,
        "callsign": (ent.get("flight") or ent.get("callsign") or ent.get("hex") or "").strip(),
        "alt": ent.get("altitude", 0),
        "speed": ent.get("speed", 0),
        "track": ent.get("track") or ent.get("heading", 0)
    })

if debug:
    st.write("Sample positions:", positions[:5])

if not positions:
    st.warning("No aircraft found in ADS-B feed.")

# Create DataFrame for aircraft
df_ac = pd.DataFrame(positions)
if not df_ac.empty:
    df_ac["position"] = df_ac.apply(lambda r: [r["lon"], r["lat"]], axis=1)

# Shadow projections
lines = []
for idx, r in df_ac.iterrows():
    lat, lon = r["lat"], r["lon"]
    alt_m = r["alt"] * 0.3048
    spd_m = r["speed"] * 0.514444
    trk = r["track"]
    alerted = False
    for t in range(0, 300+1, 30):
        # move along track
        d = spd_m * t
        # haversine move (approx)
        def move(lat1, lon1, bear, dist):
            R=6371000
            b=radians(bear)
            φ1,λ1=radians(lat1),radians(lon1)
            dlat = dist/R
            φ2 = asin(sin(φ1)*cos(dlat)+cos(φ1)*sin(dlat)*cos(b))
            λ2 = λ1 + atan2(sin(b)*sin(dlat)*cos(φ1),cos(dlat)-sin(φ1)*sin(φ2))
            return degrees(φ2), degrees(λ2)
        fx, fy = move(lat, lon, trk, d)
        if show_sun:
            sa = solar_altitude(fx, fy, t0 + timedelta(seconds=t))
            if sa > 0:
                az = solar_azimuth(fx, fy, t0 + timedelta(seconds=t))
                sd = alt_m / tan(radians(sa))
                sx, sy = move(fx, fy, az+180, sd)
                lines.append({"start": [lon, lat], "end": [sx, sy]})
        if show_moon and MOON_AVAILABLE:
            obs = ephem.Observer(); obs.lat, obs.lon = str(fx), str(fy)
            obs.date = (t0 + timedelta(seconds=t)).strftime("%Y/%m/%d %H:%M:%S")
            mobj = ephem.Moon(obs); ma = degrees(mobj.alt)
            if ma > 0:
                maz = degrees(mobj.az)
                sd = alt_m / tan(radians(ma))
                sx, sy = move(fx, fy, maz+180, sd)
                lines.append({"start": [lon, lat], "end": [sx, sy]})

# DataFrame for lines
df_ln = pd.DataFrame(lines)

# Define PyDeck layers
layers = []
if not df_ln.empty:
    layers.append(pdk.Layer(
        "LineLayer",
        data=df_ln,
        get_source_position="start",
        get_target_position="end",
        get_color=[255,165,0],
        get_width=2
    ))
if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=df_ac,
        get_position="position",
        get_fill_color=[0, 128, 255],
        get_radius=200,
        pickable=True
    ))

# Initial view
view_state = pdk.ViewState(
    latitude=HOME_LAT,
    longitude=HOME_LON,
    zoom=zoom,
    pitch=0
)

# Render map with PyDeck
r = pdk.Deck(
    layers=layers,
    initial_view_state=view_state,
    map_style="mapbox://styles/mapbox/light-v9"
)
st.pydeck_chart(r)
