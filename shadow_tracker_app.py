```python
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
import io
import zipfile

# Optional moon computations
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh every second
try:
    st_autorefresh(interval=1000, key="refresh")
except:
    pass

# Environment variables
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# Forecast/Alert config
FORECAST_INTERVAL_SECONDS = 5
FORECAST_DURATION_MINUTES = 5
SUN_FORECAST_MINUTES = int(FORECAST_DURATION_MINUTES * 1.5)
alert_times = [60, 30, 15, 10, 5, 0]

# Center coordinates
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434

# Session-state for alerts
if 'alerted' not in st.session_state:
    st.session_state.alerted = set()

# Helper: haversine distance
def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Pushover notification
def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return False
    try:
        r = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
        return r.status_code == 200
    except:
        return False

# Sidebar controls
with st.sidebar:
    st.header("Shadow Tracker")
    radius_km = st.slider("Search Radius (km)", 1, 100, 10)
    alert_width = st.slider("Shadow Alert Width (m)", 10, 1000, 100)
    show_sun = st.checkbox("Track Sun", True)
    show_moon = st.checkbox("Track Moon", False)
    show_sun_lines = st.checkbox("Show Sun Shadows", True)
    show_moon_lines = st.checkbox("Show Moon Shadows", True)
    test_alert = st.button("Test Alert")
    test_push = st.button("Test Pushover")

# Current UTC time
now_utc = datetime.now(timezone.utc)

# Sun & Moon altitudes
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon = str(CENTER_LAT), str(CENTER_LON)
    obs.date = now_utc
    moon_obs = ephem.Moon(obs)
    moon_alt = math.degrees(moon_obs.alt)

# Fetch aircraft data
aircraft_list = []
if RAPIDAPI_KEY:
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        for ac in r.json().get("ac", []):
            try:
                lat = float(ac.get("lat", 0)); lon = float(ac.get("lon", 0))
                alt = float(ac.get("alt_geo") or ac.get("alt_baro") or 0)
                vel = float(ac.get("gs") or 0)
                hdg = float(ac.get("track") or 0)
                cs = ac.get("flight") or ac.get("hex") or ""
                if alt > 0:
                    aircraft_list.append({"lat": lat, "lon": lon, "alt": alt, "vel": vel, "hdg": hdg, "callsign": cs})
            except:
                continue
    except:
        st.warning("Failed to fetch aircraft data.")
df_ac = pd.DataFrame(aircraft_list)

# Prepare exports and on-screen alerts
sun_export, moon_export = [], []
alert_msgs = []

# Compute shadow trails & alerts
sun_trails, moon_trails = [], []
for _, row in df_ac.iterrows():
    if show_sun:
        path = []
        for i in range(0, FORECAST_INTERVAL_SECONDS * SUN_FORECAST_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
            t = now_utc + timedelta(seconds=i)
            dist = row['vel'] * i
            dlat = dist * math.cos(math.radians(row['hdg'])) / 111111
            dlon = dist * math.sin(math.radians(row['hdg'])) / (111111 * math.cos(math.radians(row['lat'])))
            lat_i, lon_i = row['lat'] + dlat, row['lon'] + dlon
            sa = get_altitude(lat_i, lon_i, t)
            if sa > 0:
                saz = get_azimuth(lat_i, lon_i, t)
                sd = row['alt'] / math.tan(math.radians(sa))
                sh_lat = lat_i + (sd/111111) * math.cos(math.radians(saz+180))
                sh_lon = lon_i + (sd/(111111*math.cos(math.radians(lat_i)))) * math.sin(math.radians(saz+180))
                sun_export.append({"callsign":row['callsign'],"lat":sh_lat,"lon":sh_lon,"time_offset_sec":i})
                dist_center = hav(sh_lat, sh_lon, CENTER_LAT, CENTER_LON)
                key = f"sun-{row['callsign']}-{i}"
                if dist_center <= alert_width and i in alert_times and key not in st.session_state.alerted:
                    msg = f"✈️ {row['callsign']} sun shadow in {i}s"
                    alert_msgs.append(msg)
                    send_pushover("Sun Shadow Alert", msg)
                    st.session_state.alerted.add(key)
                path.append((sh_lat, sh_lon, i))
        if path:
            sun_trails.append((row, path))
    if show_moon and ephem:
        path = []
        for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
            t = now_utc + timedelta(seconds=i)
            dist = row['vel'] * i
            dlat = dist * math.cos(math.radians(row['hdg'])) / 111111
            dlon = dist * math.sin(math.radians(row['hdg'])) / (111111 * math.cos(math.radians(row['lat'])))
            lat_i, lon_i = row['lat'] + dlat, row['lon'] + dlon
            obs.date = t
            moon = ephem.Moon(obs)
            ma = math.degrees(moon.alt); maz = math.degrees(moon.az)
            if ma > 0:
                md = row['alt']/math.tan(math.radians(ma))
                mh_lat = lat_i + (md/111111)*math.cos(math.radians(maz+180))
                mh_lon = lon_i + (md/(111111*math.cos(math.radians(lat_i))))*math.sin(math.radians(maz+180))
                moon_export.append({"callsign":row['callsign'],"lat":mh_lat,"lon":mh_lon,"time_offset_sec":i})
                dist_center = hav(mh_lat, mh_lon, CENTER_LAT, CENTER_LON)
                key = f"moon-{row['callsign']}-{i}"
                if dist_center <= alert_width and i in alert_times and key not in st.session_state.alerted:
                    msg = f"✈️ {row['callsign']} moon shadow in {i}s"
                    alert_msgs.append(msg)
                    send_pushover("Moon Shadow Alert", msg)
                    st.session_state.alerted.add(key)
                path.append((mh_lat, mh_lon, i))
        if path:
            moon_trails.append((row, path))

# Build map layers
layers = []
if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", data=df_ac,
        get_position=["lon","lat"], get_fill_color=[0,128,255,255],
        get_radius=200, pickable=True
    ))
layers.append(pdk.Layer(
    "ScatterplotLayer", data=pd.DataFrame([{"lat":CENTER_LAT,"lon":CENTER_LON}]),
    get_position=["lon","lat"], get_fill_color=[255,0,0,128], get_radius=alert_width,
    pickable=False
))
if show_sun_lines:
    for ac, trail in sun_trails:
        layers.append(pdk.Layer(
            "PathLayer", data=[{"path":[(lon,lat) for lat,lon,_ in trail]}],
            get_path="path", get_color=[0,0,0], width_scale=(ac["alt"]/10000+1)*0.5,
            width_min_pixels=1, pickable=False
        ))
        slat, slon, _ = trail[0]
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=pd.DataFrame([{"lat":slat,"lon":slon}]),
            get_position=["lon","lat"], get_fill_color=[0,0,0,255], get_radius=50,
            pickable=False
        ))
if show_moon_lines:
    for ac, trail in moon_trails:
        layers.append(pdk.Layer(
            "PathLayer", data=[{"path":[(lon,lat) for lat,lon,_ in trail]}],
            get_path="path", get_color=[128,128,128], width_scale=ac["alt"]/10000+1,
            width_min_pixels=2, pickable=False
        ))

# Render pydeck map
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=12)
st.pydeck_chart(
    pdk.Deck(layers=layers, initial_view_state=view, map_style="light",
             tooltip={"html":"<b>Callsign:</b> {callsign}<br/><b>Altitude:</b> {alt} ft<br/><b>Speed:</b> {vel} kts<br/><b>Heading:</b> {hdg}°","style":{"backgroundColor":"black","color":"white"}}),
    use_container_width=True
)

# On-screen alerts
for msg in alert_msgs:
    st.warning(msg)

# Trigger test alerts
if test_alert:
    st.success("Test shadow alert triggered!")
if test_push:
    ok = send_pushover("Test Alert","This is a test Pushover message.")
    st.info("Pushover sent" if ok else "Pushover failed")

# Export shadow logs
if sun_export or moon_export:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if sun_export:
            z.writestr("sun_shadows.csv", pd.DataFrame(sun_export).to_csv(index=False))
        if moon_export:
            z.writestr("moon_shadows.csv", pd.DataFrame(moon_export).to_csv(index=False))
    buf.seek(0)
    st.download_button("Download Shadow Exports", buf, file_name="shadow_exports.zip")
```
