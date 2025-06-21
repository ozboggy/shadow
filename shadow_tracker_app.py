import time
import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import requests
import pandas as pd
import plotly.express as px
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

# Paths & credentials
log_path = os.getenv("LOG_PATH", "alert_log.csv")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title: str, message: str) -> bool:
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return False
    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY,
                  "title": title, "message": message}
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        st.error(f"Pushover API error: {e}")
        return False

def hav(lat1, lon1, lat2, lon2):
    R = 6_371_000  # Earth radius in meters
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

# Defaults
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5

# ───────── Sidebar Controls & Download ─────────
with st.sidebar:
    st.header("Map Options")
    radius_km    = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun    = st.checkbox("Show Sun Shadows", value=True)
    track_moon   = st.checkbox("Show Moon Shadows", value=False)
    alert_width  = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert   = st.button("Test Alert")
    test_pushover= st.button("Test Pushover")
    st.markdown("---")
    st.download_button(
        label="📥 Download alert_log.csv",
        data=open(log_path, "rb"),
        file_name="alert_log.csv",
        mime="text/csv"
    )

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

# ───────── Fetch ADS-B Exchange Data ─────────
aircraft_list = []
api_key = os.getenv("RAPIDAPI_KEY")
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
    except Exception:
        st.warning("Failed to fetch ADS-B data.")
        adsb = []
else:
    adsb = []

for ac in adsb:
    try:
        lat = float(ac.get("lat")); lon = float(ac.get("lon"))
    except (TypeError, ValueError):
        continue
    cs = (ac.get("flight") or ac.get("hex") or "").strip()
    alt_val = float(ac.get("alt_geo") or ac.get("alt_baro") or 0) if ac.get("alt_geo") or ac.get("alt_baro") else 0.0
    vel     = float(ac.get("gs") or ac.get("spd") or 0)
    hdg     = float(ac.get("track") or ac.get("trak") or 0)
    if alt_val > 0:
        aircraft_list.append({
            "lat": lat, "lon": lon,
            "alt": alt_val, "vel": vel,
            "hdg": hdg, "callsign": cs
        })

# Build aircraft DataFrame
df_ac = pd.DataFrame(aircraft_list)
if not df_ac.empty:
    df_ac[['alt','vel','hdg']] = df_ac[['alt','vel','hdg']].apply(
        pd.to_numeric, errors='coerce'
    ).fillna(0)

# ───────── Sidebar Status ─────────
st.sidebar.markdown("### Status")
st.sidebar.markdown(f"Sun altitude: {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.sidebar.markdown(f"Moon altitude: {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.sidebar.warning("Moon data unavailable")
st.sidebar.markdown(f"Total airborne aircraft: **{len(df_ac)}**")

# ───────── Compute Shadow Paths ─────────
sun_trails, moon_trails = [], []
if not df_ac.empty:
    for _, row in df_ac.iterrows():
        cs, lat0, lon0 = row['callsign'], row['lat'], row['lon']
        s_path, m_path = [], []
        for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1,
                       FORECAST_INTERVAL_SECONDS):
            t = now_utc + timedelta(seconds=i)
            # Move aircraft along track
            dist_m = row['vel'] * i
            dlat = dist_m * math.cos(math.radians(row['hdg'])) / 111111
            dlon = dist_m * math.sin(math.radians(row['hdg'])) / (
                111111 * math.cos(math.radians(lat0))
            )
            lat_i, lon_i = lat0 + dlat, lon0 + dlon
            # Sun shadow
            if track_sun:
                sa, saz = get_altitude(lat_i, lon_i, t), get_azimuth(lat_i, lon_i, t)
                if sa > 0:
                    sd = row['alt'] / math.tan(math.radians(sa))
                    sh_lat = lat_i + (sd/111111)*math.cos(math.radians(saz+180))
                    sh_lon = lon_i + (sd/(111111*math.cos(math.radians(lat_i))))*math.sin(math.radians(saz+180))
                    s_path.append([sh_lon, sh_lat])
            # Moon shadow
            if ephem and track_moon:
                obs.date = t
                m = ephem.Moon(obs)
                ma, maz = math.degrees(m.alt), math.degrees(m.az)
                if ma > 0:
                    md = row['alt'] / math.tan(math.radians(ma))
                    mh_lat = lat_i + (md/111111)*math.cos(math.radians(maz+180))
                    mh_lon = lon_i + (md/(111111*math.cos(math.radians(lat_i))))*math.sin(math.radians(maz+180))
                    m_path.append([mh_lon, mh_lat])
        if s_path:
            sun_trails.append({"path": s_path, "callsign": cs, "current": s_path[0]})
        if m_path:
            moon_trails.append({"path": m_path, "callsign": cs, "current": m_path[0]})

# ───────── Build Map Layers ─────────
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []

# Sun trails
if track_sun and sun_trails:
    df_sun = pd.DataFrame(sun_trails)
    layers.append(pdk.Layer(
        "PathLayer", df_sun, get_path="path",
        get_color=[50,50,50,255], width_scale=5, width_min_pixels=1, pickable=False
    ))
    sun_current = pd.DataFrame([{"lon": s["current"][0], "lat": s["current"][1]} for s in sun_trails])
    layers.append(pdk.Layer(
        "ScatterplotLayer", sun_current,
        get_position=["lon","lat"], get_fill_color=[50,50,50,255],
        get_radius=100, pickable=False
    ))

# Moon trails
if track_moon and moon_trails:
    df_moon = pd.DataFrame(moon_trails)
    layers.append(pdk.Layer(
        "PathLayer", df_moon, get_path="path",
        get_color=[180,180,180,200], width_scale=5, width_min_pixels=1, pickable=False
    ))
    moon_current = pd.DataFrame([{"lon": m["current"][0], "lat": m["current"][1]} for m in moon_trails])
    layers.append(pdk.Layer(
        "ScatterplotLayer", moon_current,
        get_position=["lon","lat"], get_fill_color=[180,180,180,200],
        get_radius=100, pickable=False
    ))

# Alert circle
circle = []
for ang in range(0, 360, 5):
    b = math.radians(ang)
    dy = (alert_width / 111111) * math.cos(b)
    dx = (alert_width / (111111 * math.cos(math.radians(CENTER_LAT)))) * math.sin(b)
    circle.append([CENTER_LON + dx, CENTER_LAT + dy])
circle.append(circle[0])
layers.append(pdk.Layer(
    "PolygonLayer", [{"polygon": circle}],
    get_polygon="polygon", get_fill_color=[255,0,0,100],
    stroked=True, get_line_color=[255,0,0], get_line_width=3, pickable=False
))

# Aircraft scatter
if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", df_ac,
        get_position=["lon","lat"], get_fill_color=[0,128,255,200],
        get_radius=300, pickable=True, auto_highlight=True,
        highlight_color=[255,255,0,255]
    ))

tooltip = {
    "html": (
        "<b>Callsign:</b> {callsign}<br/>"
        "<b>Alt:</b> {alt} m<br/>"
        "<b>Speed:</b> {vel} m/s<br/>"
        "<b>Heading:</b> {hdg}°"
    ),
    "style": {"backgroundColor":"black","color":"white"}
}

deck = pdk.Deck(layers=layers, initial_view_state=view, map_style="light", tooltip=tooltip)
st.pydeck_chart(deck, use_container_width=True)

# ───────── Recent Alerts Section ─────────
try:
    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        st.markdown("### 📊 Recent Alerts")
        st.dataframe(df_log.tail(10))

        fig = px.scatter(
            df_log,
            x="Time UTC",
            y="Callsign",
            size="Time Until Alert (sec)",
            hover_data=["Lat", "Lon"],
            title="Shadow Alerts Over Time"
        )
        st.plotly_chart(fig, use_container_width=True)
except FileNotFoundError:
    st.warning(f"Alert log not found at `{log_path}`")

# ───────── Alerts & Test Buttons ─────────
beep_html = """
<audio autoplay>
  <source src="https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg" type="audio/ogg">
</audio>
"""
# Real alerts
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

# Test alert button
if test_alert:
    ph = st.empty()
    ph.success("🔔 Test alert triggered!")
    st.markdown(beep_html, unsafe_allow_html=True)
    time.sleep(5)
    ph.empty()

# Test pushover button
if test_pushover:
    ph2 = st.empty()
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        ph2.error("⚠️ Missing Pushover credentials")
    else:
        ok = send_pushover("✈️ Test", "This is a test from your app.")
        ph2.success("✅ Test Pushover sent!" if ok else "❌ Test Pushover failed")
    time.sleep(5)
    ph2.empty()
