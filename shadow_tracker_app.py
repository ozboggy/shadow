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

# Session‐persistent alert log
if "alert_log" not in st.session_state:
    st.session_state.alert_log = []

# Auto-refresh every second
st_autorefresh(interval=1_000, key="datarefresh")

# Pushover creds
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title: str, message: str) -> bool:
    if not (PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN):
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
    return 2 * R * math.asin(math.sqrt(a))

# Constants
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5

# Sidebar
with st.sidebar:
    st.header("Map Options")
    radius_km   = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun   = st.checkbox("Show Sun Shadows", True)
    track_moon  = st.checkbox("Show Moon Shadows", False)
    alert_width = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert  = st.button("Test Alert")
    test_push   = st.button("Test Pushover")

now_utc = datetime.now(timezone.utc)

# Sun/Moon altitudes
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
if ephem:
    obs = ephem.Observer(); obs.lat, obs.lon = str(CENTER_LAT), str(CENTER_LON); obs.date = now_utc
    moon_alt = math.degrees(ephem.Moon(obs).alt)
else:
    moon_alt = None

# Fetch ADS-B Exchange
aircraft_list = []
api_key = os.getenv("RAPIDAPI_KEY")
if api_key:
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
    try:
        r = requests.get(url, headers=headers); r.raise_for_status()
        adsb = r.json().get("ac", [])
    except:
        st.warning("ADS-B fetch failed"); adsb = []
else:
    adsb = []

for ac in adsb:
    try:
        lat, lon = float(ac.get("lat")), float(ac.get("lon"))
    except:
        continue
    cs = (ac.get("flight") or ac.get("hex") or "").strip()
    alt_val = float(ac.get("alt_geo") or ac.get("alt_baro") or 0) if ac.get("alt_geo") or ac.get("alt_baro") else 0
    vel = float(ac.get("gs") or ac.get("spd") or 0)
    hdg = float(ac.get("track") or ac.get("trak") or 0)
    if alt_val > 0:
        aircraft_list.append({"lat": lat, "lon": lon, "alt": alt_val, "vel": vel, "hdg": hdg, "callsign": cs})

df_ac = pd.DataFrame(aircraft_list)
if not df_ac.empty:
    df_ac[['alt','vel','hdg']] = df_ac[['alt','vel','hdg']].apply(pd.to_numeric, errors='coerce').fillna(0)
total_ac = len(df_ac)

# Sidebar status
st.sidebar.markdown("### Status")
st.sidebar.markdown(f"Sun: {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.sidebar.markdown(f"Moon: {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.sidebar.warning("Moon data N/A")
st.sidebar.markdown(f"Airborne aircraft: **{total_ac}**")

# Compute trails & events
sun_trails, moon_trails = [], []
for row in aircraft_list:
    cs, lat0, lon0 = row['callsign'], row['lat'], row['lon']
    events_s, events_m = [], []
    path_s, path_m = [], []
    for i in range(0, FORECAST_INTERVAL_SECONDS*FORECAST_DURATION_MINUTES+1, FORECAST_INTERVAL_SECONDS):
        t = now_utc + timedelta(seconds=i)
        dist_m = row['vel']*i
        dlat = dist_m*math.cos(math.radians(row['hdg']))/111111
        dlon = dist_m*math.sin(math.radians(row['hdg']))/(111111*math.cos(math.radians(lat0)))
        lat_i, lon_i = lat0+dlat, lon0+dlon

        # Sun
        sa, saz = get_altitude(lat_i, lon_i, t), get_azimuth(lat_i, lon_i, t)
        if sa>0 and track_sun:
            sd = row['alt']/math.tan(math.radians(sa))
            sh_lat = lat_i+(sd/111111)*math.cos(math.radians(saz+180))
            sh_lon = lon_i+(sd/(111111*math.cos(math.radians(lat_i))))*math.sin(math.radians(saz+180))
            path_s.append([sh_lon, sh_lat])
            events_s.append((t, sh_lat, sh_lon))

        # Moon
        if ephem and track_moon:
            obs.date = t
            m = ephem.Moon(obs)
            ma, maz = math.degrees(m.alt), math.degrees(m.az)
            if ma>0:
                md = row['alt']/math.tan(math.radians(ma))
                mh_lat = lat_i+(md/111111)*math.cos(math.radians(maz+180))
                mh_lon = lon_i+(md/(111111*math.cos(math.radians(lat_i))))*math.sin(math.radians(maz+180))
                path_m.append([mh_lon, mh_lat])
                events_m.append((t, mh_lat, mh_lon))

    if path_s:
        sun_trails.append({"path": path_s, "callsign": cs, "events": events_s})
    if path_m:
        moon_trails.append({"path": path_m, "callsign": cs, "events": events_m})

# Build layers
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = [pdk.Layer("ScatterplotLayer", df_ac, get_position=["lon","lat"], get_color=[0,128,255,200], get_radius=100, pickable=True)]

if track_sun and sun_trails:
    df_sun = pd.DataFrame([{"path": tr["path"], "callsign": tr["callsign"]} for tr in sun_trails])
    layers.append(pdk.Layer("PathLayer", df_sun, get_path="path", get_color=[255,215,0,150], width_scale=10, width_min_pixels=2, pickable=True))

if track_moon and moon_trails:
    df_moon = pd.DataFrame([{"path": tr["path"], "callsign": tr["callsign"]} for tr in moon_trails])
    layers.append(pdk.Layer("PathLayer", df_moon, get_path="path", get_color=[135,206,250,150], width_scale=10, width_min_pixels=2, pickable=True))

# Alert circle
circle = [[CENTER_LON + (alert_width/111111)*math.sin(math.radians(a))/(math.cos(math.radians(CENTER_LAT))),
           CENTER_LAT + (alert_width/111111)*math.cos(math.radians(a))] for a in range(0,360,5)]
circle.append(circle[0])
layers.append(pdk.Layer("PolygonLayer", [{"polygon": circle}], get_polygon="polygon", get_fill_color=[255,0,0,50], stroked=True, get_line_color=[255,0,0], get_line_width=2))

tooltip = {"html":"<b>Callsign:</b> {callsign}<br/><b>Alt:</b> {alt:.0f} m<br/><b>Speed:</b> {vel:.0f} m/s<br/><b>Heading:</b> {hdg:.0f}°","style":{"backgroundColor":"black","color":"white"}}

deck = pdk.Deck(layers=layers, initial_view_state=view, map_style="light", tooltip=tooltip)
st.pydeck_chart(deck, use_container_width=True)

# Alert & log
beep = '<audio autoplay><source src="https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg" type="audio/ogg"></audio>'

def fire(trails, label):
    for tr in trails:
        for t, lat, lon in tr["events"]:
            if hav(lat, lon, CENTER_LAT, CENTER_LON)<=alert_width:
                delta = t-now_utc; mins,secs=divmod(int(delta.total_seconds()),60)
                msg=f"{label} shadow of {tr['callsign']} in {mins}m{secs}s"
                st.error("🚨 "+msg); st.markdown(beep, unsafe_allow_html=True)
                send_pushover(f"✈️ {label} Shadow Alert",msg)
                st.session_state.alert_log.append({"time":t.isoformat(),"callsign":tr["callsign"],"Event":label})
                return

if track_sun: fire(sun_trails,"Sun")
if track_moon: fire(moon_trails,"Moon")

# Timeline in sidebar
st.sidebar.markdown("### Alert Timeline")
if st.session_state.alert_log:
    df_log = (pd.DataFrame(st.session_state.alert_log)
                .assign(time=lambda d: pd.to_datetime(d["time"]))
                .query("time.dt.date == @now_utc.date()")
                .sort_values("time"))
    st.sidebar.table(df_log[["time","callsign","Event"]])
else:
    st.sidebar.info("No alerts today.")

# Test buttons
if test_alert:
    ph=st.empty(); ph.success("🔔 Test alert"); st.markdown(beep,unsafe_allow_html=True)
    st.session_state.alert_log.append({"time":now_utc.isoformat(),"callsign":"TEST","Event":"Test"}); time.sleep(5); ph.empty()
if test_push:
    ph2=st.empty()
    if not (PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN): ph2.error("⚠️ Missing creds")
    else: ph2.success("✅ Pushover sent" if send_pushover("✈️Test","Test") else "❌ Fail")
    time.sleep(5); ph2.empty()

