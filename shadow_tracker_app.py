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

# Auto-refresh every second
try:
    st_autorefresh(interval=1000, key="refresh")
except:
    pass

# Env
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# Alert function
def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return False
    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
        return resp.status_code == 200
    except:
        return False

# Audio snippet for on-screen alert
dot_html = """<audio autoplay>
  <source src=\"https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg\" type=\"audio/ogg\">
</audio>"""

# Helpers
def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Config
CENTER_LAT, CENTER_LON = -33.7602563, 150.9717434
alert_times = [60, 30, 15, 10, 5, 0]
FORECAST_INTERVAL_SECONDS = 5
FORECAST_DURATION_MINUTES = 5
SUN_FORECAST_MINUTES = int(FORECAST_DURATION_MINUTES * 1.5)

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

# Current time
now_utc = datetime.now(timezone.utc)

# Fetch aircraft via RapidAPI
aircraft_list = []
if RAPIDAPI_KEY:
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        ac_list = r.json().get("ac", [])
        for ac in ac_list:
            try:
                lat = float(ac.get("lat", 0))
                lon = float(ac.get("lon", 0))
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

# DataFrame of aircraft
df_ac = pd.DataFrame(aircraft_list)

# Compute shadow trails
sun_trails, moon_trails = [], []
for _, row in df_ac.iterrows():
    # Sun shadows
    if show_sun:
        sun_path = []
        for i in range(0, FORECAST_INTERVAL_SECONDS * SUN_FORECAST_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
            t = now_utc + timedelta(seconds=i)
            dx = row['vel'] * i * math.sin(math.radians(row['hdg']))
            dy = row['vel'] * i * math.cos(math.radians(row['hdg']))
            lat_i = row['lat'] + dy/111111
            lon_i = row['lon'] + dx/(111111*math.cos(math.radians(row['lat'])))
            sa = get_altitude(lat_i, lon_i, t)
            if sa > 0:
                saz = get_azimuth(lat_i, lon_i, t)
                sd = row['alt'] / math.tan(math.radians(sa))
                sh_lat = lat_i + (sd/111111)*math.cos(math.radians(saz+180))
                sh_lon = lon_i + (sd/(111111*math.cos(math.radians(lat_i))))*math.sin(math.radians(saz+180))
                sun_path.append((sh_lat, sh_lon, i))
        if sun_path:
            sun_trails.append((row, sun_path))
    # Moon shadows
    if show_moon and ephem:
        moon_path = []
        obs = ephem.Observer()
        obs.lat, obs.lon = str(CENTER_LAT), str(CENTER_LON)
        for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
            t = now_utc + timedelta(seconds=i)
            dx = row['vel'] * i * math.sin(math.radians(row['hdg']))
            dy = row['vel'] * i * math.cos(math.radians(row['hdg']))
            lat_i = row['lat'] + dy/111111
            lon_i = row['lon'] + dx/(111111*math.cos(math.radians(row['lat'])))
            obs.date = t
            moon = ephem.Moon(obs)
            ma = math.degrees(moon.alt)
            if ma > 0:
                maz = math.degrees(moon.az)
                md = row['alt'] / math.tan(math.radians(ma))
                mh_lat = lat_i + (md/111111)*math.cos(math.radians(maz+180))
                mh_lon = lon_i + (md/(111111*math.cos(math.radians(lat_i))))*math.sin(math.radians(maz+180))
                moon_path.append((mh_lat, mh_lon, i))
        if moon_path:
            moon_trails.append((row, moon_path))

# Build pydeck layers
layers = []
# Blue aircraft dots
if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", data=df_ac,
        get_position=["lon","lat"],
        get_fill_color=[0,0,255,200],
        get_radius=100,
        pickable=True,
        auto_highlight=True
    ))
# White arrows on top
if not df_ac.empty:
    layers.append(pdk.Layer(
        "TextLayer", data=df_ac,
        get_position=["lon","lat"],
        get_text="'➤'",
        get_color=[255,255,255],
        get_size=16,
        get_angle="hdg",
        billboard=False,
        get_alignment_baseline="'center'"
    ))
# Home radius
layers.append(pdk.Layer(
    "ScatterplotLayer",
    data=pd.DataFrame([{"lat":CENTER_LAT,"lon":CENTER_LON}]),
    get_position=["lon","lat"],
    get_fill_color=[255,0,0,128],
    get_radius=alert_width,
    pickable=False
))
# Sun shadow trails
if show_sun_lines:
    for ac, trail in sun_trails:
        layers.append(pdk.Layer(
            "PathLayer", data=[{"path": [(lon,lat) for lat,lon,_ in trail]}],
            get_path="path", get_color=[0,0,0], width_scale=(ac['alt']/10000+1)*0.5, width_min_pixels=1, pickable=False
        ))
        slat, slon,_ = trail[0]
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=pd.DataFrame([{"lat":slat,"lon":slon}]),
            get_position=["lon","lat"], get_fill_color=[0,0,0,255], get_radius=50, pickable=False
        ))
# Moon shadow trails
if show_moon_lines:
    for ac, trail in moon_trails:
        layers.append(pdk.Layer(
            "PathLayer", data=[{"path": [(lon,lat) for lat,lon,_ in trail]}],
            get_path="path", get_color=[128,128,128], width_scale=ac['alt']/10000+1, width_min_pixels=2, pickable=False
        ))

# Render map
view = pdk.ViewState(latitude=CENTER_LAT,longitude=CENTER_LON,zoom=12)
st.pydeck_chart(pdk.Deck(
    layers=layers,
    initial_view_state=view,
    map_style="light",
    tooltip={"html":"<b>Callsign:</b> {callsign}<br/><b>Alt:</b> {alt} ft","style":{"backgroundColor":"black","color":"white"}}
),use_container_width=True)

# Shadow proximity alerts based on shadow trails
for row, trail in sun_trails:
    for lat, lon, sec in trail:
        if sec in alert_times:
            dist = hav(lat, lon, CENTER_LAT, CENTER_LON)
            if dist <= alert_width:
                msg = (
                    f"✈️ {row['callsign']} shadow alert
"
                    f"⏱ Shadow over home in {sec}s
"
                    f"📏 Distance: {int(dist)} m
"
                    f"🛬 Altitude: {int(row['alt'])} ft
"
                    f"🚀 Speed: {int(row['vel'])} knots"
                )
                st.error(f"🚨 Shadow in {sec}s! ({row['callsign']})")
                st.markdown(dot_html, unsafe_allow_html=True)
                send_pushover("✈️ Shadow Alert", msg)
                # stop further alerts for this interval
                break
# Export unchanged

