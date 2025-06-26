import time
import streamlit as st
from dotenv import load_dotenv
load_dotenv()

import os, math, json, requests, pandas as pd
import pydeck as pdk
import plotly.express as px
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth

# Optional moon computations
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh every second
AUTOREFRESH_MS = 1000
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=AUTOREFRESH_MS, key="datarefresh")
except ImportError:
    pass

# ── CONFIG
LOG_PATH            = os.getenv("LOG_PATH", "alert_log.csv")
HOME_CFG            = os.getenv("HOME_CONFIG", "home_location.json")
RAPIDAPI_KEY        = os.getenv("RAPIDAPI_KEY")
MAPBOX_API_KEY      = os.getenv("MAPBOX_API_KEY")
DEFAULT_RADIUS_MI   = 10
RADIUS_KM           = DEFAULT_RADIUS_MI * 1.60934
FORECAST_INTERVAL_S = 1
FORECAST_DURATION_S = 60

# Set Mapbox key for pydeck
pdk.settings.mapbox_api_key = MAPBOX_API_KEY

# ── HOME LOAD / SAVE
def load_home():
    default = {"lat": -33.8544014, "lon": 151.2087668}
    if os.path.exists(HOME_CFG):
        try:
            cfg = json.load(open(HOME_CFG))
            return cfg.get("lat", default["lat"]), cfg.get("lon", default["lon"])
        except:
            pass
    return default["lat"], default["lon"]

def save_home(lat, lon):
    with open(HOME_CFG, "w") as f:
        json.dump({"lat": lat, "lon": lon}, f)
    st.experimental_rerun()

CENTER_LAT, CENTER_LON = load_home()

# ── ENSURE ALERT LOG EXISTS
if not os.path.exists(LOG_PATH):
    pd.DataFrame(columns=[
        "Time UTC", "Callsign", "Lat", "Lon", "Time Until Alert (sec)", "Distance (mi)"
    ]).to_csv(LOG_PATH, index=False)

# ── HELPER FUNCTIONS
def hav(lat1, lon1, lat2, lon2):
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return 2 * R * math.asin(math.sqrt(a))

def log_alert(callsign, lat, lon, time_until, distance_mi):
    try:
        df = pd.read_csv(LOG_PATH)
    except:
        df = pd.DataFrame(columns=[
            "Time UTC", "Callsign", "Lat", "Lon", "Time Until Alert (sec)", "Distance (mi)"
        ])
    new = pd.DataFrame([{
        "Time UTC": datetime.now(timezone.utc).isoformat(),
        "Callsign": callsign,
        "Lat": lat,
        "Lon": lon,
        "Time Until Alert (sec)": time_until,
        "Distance (mi)": distance_mi
    }])
    df = pd.concat([df, new], ignore_index=True)
    df.to_csv(LOG_PATH, index=False)

# ── SIDEBAR
with st.sidebar:
    st.header("Home & Map Options")
    lat_in = st.number_input("Home Lat", value=CENTER_LAT, format="%.6f")
    lon_in = st.number_input("Home Lon", value=CENTER_LON, format="%.6f")
    if st.button("Save Home"):
        save_home(lat_in, lon_in)

    st.markdown("---")
    on_screen_alerts = st.checkbox("Enable On-Screen Alerts", True)
    st.markdown(f"**Search Radius:** {DEFAULT_RADIUS_MI} mi")
    track_sun  = st.checkbox("Show Sun Shadows", True)
    track_moon = st.checkbox("Show Moon Shadows", False)
    alert_width = st.slider("Shadow Alert Width (m)", 10, 1000, 50)
    test_alert  = st.button("Test Alert")

    st.markdown("---")
    if os.path.exists(LOG_PATH):
        st.download_button(
            "Download alert_log.csv",
            open(LOG_PATH, "rb"),
            "alert_log.csv",
            "text/csv"
        )
    else:
        st.info("No alert log yet")

# ── TIMESTAMP & SOLAR/MOON ALTITUDES
now_utc = datetime.now(timezone.utc)
sun_alt  = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now_utc
    moon_alt = math.degrees(ephem.Moon(obs).alt)

# ── FETCH ADS-B DATA
aircraft_list = []
if RAPIDAPI_KEY:
    url = (f"https://adsbexchange-com1.p.rapidapi.com/v2/"
           f"lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{RADIUS_KM}/")
    headers = {"x-rapidapi-key": RAPIDAPI_KEY,
               "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json().get("ac", [])
    except:
        st.warning("Failed to fetch ADS-B data.")
        data = []
else:
    data = []

for ac in data:
    try:
        lat = float(ac["lat"]); lon = float(ac["lon"])
    except:
        continue
    cs = (ac.get("flight") or ac.get("hex") or "").strip()
    baro, geo = ac.get("alt_baro"), ac.get("alt_geo")
    try:
        if baro:
            alt_ft = int(float(baro))
        elif geo:
            alt_ft = int(float(geo) * 3.28084)
        else:
            alt_ft = 0
    except:
        alt_ft = 0
    vel = float(ac.get("gs") or ac.get("spd") or 0)
    hdg = float(ac.get("track") or ac.get("trak") or 0)
    if alt_ft > 0:
        aircraft_list.append({"lat": lat, "lon": lon,
                              "alt_ft": alt_ft, "vel": vel, "hdg": hdg,
                              "callsign": cs})

df_ac = pd.DataFrame(aircraft_list)

# ── STATUS DISPLAY
st.markdown(f"**Home:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
st.markdown(f"**Sun alt:** {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.markdown(f"**Moon alt:** {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.warning("Moon data unavailable")
st.metric("Aircraft tracked", len(df_ac))

# ── BUILD STATIC BACKGROUND (cached)
@st.cache_data(show_spinner=False)
def build_static():
    view = pdk.ViewState(
        latitude=CENTER_LAT, longitude=CENTER_LON,
        zoom=max(1, min(16, 14 - math.log(RADIUS_KM, 2)))
    )
    tile_layer = pdk.Layer(
        "TileLayer", data=None,
        get_tile_url="https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
        tile_size=256, pickable=False
    )
    rings = []
    for m in [1,2,5,10,20]:
        km = m * 1.60934
        lat_d = (km*1000)/111111
        lon_d = lat_d/math.cos(math.radians(CENTER_LAT))
        path = [[CENTER_LON+lon_d*math.sin(math.radians(a)),
                 CENTER_LAT+lat_d*math.cos(math.radians(a))]
                for a in range(0,360,5)]
        path.append(path[0])
        rings.append(pdk.Layer(
            "PathLayer", data=[{"path": path}],
            get_path="path", get_color=[0,200,0,120],
            width_scale=100, width_min_pixels=1, pickable=False
        ))
    return view, [tile_layer] + rings

view_state, static_layers = build_static()

# ── BUILD DYNAMIC LAYERS ───────────────────────────────────────────────────────
sun_trails, moon_trails = [], []
if not df_ac.empty:
    for _, r in df_ac.iterrows():
        s_path, m_path = [], []
        for i in range(FORECAST_DURATION_S+1):
            t = now_utc + timedelta(seconds=i)
            d = r["vel"]*i
            dlat = d*math.cos(math.radians(r["hdg"]))/
