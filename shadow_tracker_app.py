import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import folium
from folium.plugins import PolyLineTextPath
from streamlit_folium import st_folium
import math
import requests
import numpy as np
import io
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth
from folium.features import DivIcon

# Constants
TARGET_LAT = -33.7571158
TARGET_LON = 150.9779155
DEFAULT_RADIUS_KM = 20
DEFAULT_INTERVAL_SEC = 30
DEFAULT_DURATION_MIN = 5
DEFAULT_SHADOW_WIDTH = 1.5
DEFAULT_ZOOM = 10
HOME_ALERT_THRESHOLD_M = 100  # meters

# Pushover credentials
PUSHOVER_USER_KEY = "usasa4y2iuvz75krztrma829s21nvy"
PUSHOVER_APP_TOKEN = "adxez5u3zqqxyta3pdvdi5sdvwovxv"

# Audio generation utility
def generate_beep(duration_s=0.5, freq=440, sample_rate=44100):
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), False)
    tone = np.sin(freq * 2 * np.pi * t)
    audio = (tone * 32767).astype(np.int16)
    buf = io.BytesIO()
    import wave
    wf = wave.open(buf, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sample_rate)
    wf.writeframes(audio.tobytes())
    wf.close()
    buf.seek(0)
    return buf.read()

# Sidebar controls
st.sidebar.header("Configuration")
data_source = st.sidebar.selectbox("Data Source", ["OpenSky", "ADS-B Exchange"], index=0)
tile_style = st.sidebar.selectbox(
    "Map Tile Style",
    ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter", "Stamen Terrain", "Stamen Toner"],
    index=0
)
zoom_level = st.sidebar.slider("Map Zoom", 1, 18, DEFAULT_ZOOM)
track_sun = st.sidebar.checkbox("Show Sun Shadows", True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", False)
override_trails = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", False)
radius_km = st.sidebar.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
forecast_interval = st.sidebar.slider("Forecast Interval (sec)", 5, 60, DEFAULT_INTERVAL_SEC, 5)
forecast_duration = st.sidebar.slider("Forecast Duration (min)", 1, 60, DEFAULT_DURATION_MIN, 1)
shadow_width = st.sidebar.slider("Shadow Width (px)", 0.5, 10.0, DEFAULT_SHADOW_WIDTH, 0.5)
debug_mode = st.sidebar.checkbox("Debug raw response", False)
refresh_interval = st.sidebar.number_input("Auto-refresh Interval (sec)", 0, 300, 0, 10)
enable_pushover = st.sidebar.checkbox("Enable Pushover Alerts", False)
enable_audio = st.sidebar.checkbox("Enable Audio Alert at Home", False)
# Test on-screen alert
if st.sidebar.button("Send Test Home Alert"):
    st.session_state['test_home_alert'] = True

if st.sidebar.button("Send Test Push"):
    resp = requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "user": PUSHOVER_USER_KEY,
            "token": PUSHOVER_APP_TOKEN,
            "message": f"Test from Shadow Tracker at {datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC"
        }
    )
    if resp.status_code == 200:
        st.sidebar.success("Test notification sent.")
    else:
        st.sidebar.error(f"Test failed: {resp.text}")

if st.sidebar.button("Send Test Audio"):
    beep = generate_beep()
    st.sidebar.audio(beep, format='audio/wav')

if st.sidebar.button("Send Alert Push"):
    st.session_state['send_alert'] = True

# Auto-refresh
if refresh_interval > 0:
    st.markdown(f'<meta http-equiv="refresh" content="{refresh_interval}">', unsafe_allow_html=True)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")
selected_time = datetime.utcnow().replace(tzinfo=timezone.utc)

# Helper functions

def move_position(lat, lon, heading, dist):
    R = 6371000
    hdr = math.radians(heading)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1)*math.cos(dist/R) + math.cos(lat1)*math.sin(dist/R)*math.cos(hdr)
    )
    lon2 = lon1 + math.atan2(
        math.sin(hdr)*math.sin(dist/R)*math.cos(lat1),
        math.cos(dist/R) - math.sin(lat1)*math.sin(lat2)
    )
    return math.degrees(lat2), math.degrees(lon2)


def fetch_opensky(lat, lon, radius):
    dr = radius / 111.0
    south, north = lat - dr, lat + dr
    dlon = dr / math.cos(math.radians(lat))
    west, east = lon - dlon, lon + dlon
    url = (
        f"https://opensky-network.org/api/states/all?"
        f"lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    )
    try:
        r = requests.get(url)
        r.raise_for_status()
        if debug_mode:
            st.write("OpenSky raw response:\n", r.text)
        states = r.json().get("states", [])
    except Exception as e:
        st.error(f"OpenSky error: {e}")
        return []
    acs = []
    for s in states:
        if len(s) < 11:
            continue
        try:
            cs = s[1].strip() or s[0]
            lat_f, lon_f = float(s[6]), float(s[5])
            baro = float(s[7]) if s[7] is not None else 0.0
            vel = float(s[9])
            hdg = float(s[10])
        except Exception:
            continue
        acs.append({"lat":lat_f,"lon":lon_f,"baro":baro,"vel":vel,"hdg":hdg,"callsign":cs})
    return acs


def fetch_adsb(lat, lon, radius):
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        st.error("Set RAPIDAPI_KEY in .env for ADS-B Exchange")
        return []
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{lat}/lon/{lon}/dist/{radius}/"
    headers = {"x-rapidapi-key":api_key,"x-rapidapi-host":"adsbexchange-com1.p.rapidapi.com"}
    try:
        r = requests.get(url,headers=headers)
        r.raise_for_status()
        if debug_mode:
            st.write("ADS-B raw response:\n", r.text)
        ac_list = r.json().get("ac",[])
    except Exception as e:
        st.error(f"ADS-B error: {e}")
        return []
    acs = []
    for ac in ac_list:
        try:
            cs=(ac.get("flight") or ac.get("hex") or "").strip()
            lat_f, lon_f = float(ac.get("lat")), float(ac.get("lon"))
            baro_val = ac.get("alt_baro")
            baro = float(baro_val) if baro_val is not None else 0.0
            vel = float(ac.get("gs") or ac.get("spd") or 0)
            hdg = float(ac.get("track") or ac.get("trak") or 0)
        except Exception:
            continue
        acs.append({"lat":lat_f,"lon":lon_f,"baro":baro,"vel":vel,"hdg":hdg,"callsign":cs})
    return acs


def calculate_trail(lat, lon, baro, vel, hdg):
    pts=[]
    for i in range(0,int(forecast_duration*60)+1,forecast_interval):
        ft=selected_time+timedelta(seconds=i)
        dist=vel*i
        f_lat,f_lon=move_position(lat,lon,hdg,dist)
        sun_alt=get_sun_altitude(f_lat,f_lon,ft)
        if(track_sun and sun_alt>0) or (track_moon and sun_alt<=0) or override_trails:
            az=get_sun_azimuth(f_lat,f_lon,ft)
        else:
            continue
        angle=sun_alt if sun_alt>0 else 1
        sd=baro/math.tan(math.radians(angle))
        sh_lat=f_lat+(sd/111111)*math.cos(math.radians(az+180))
        sh_lon=f_lon+(sd/(111111*math.cos(math.radians(f_lat))))*math.sin(math.radians(az+180))
        pts.append((sh_lat,sh_lon))
    return pts

# Initialize map
fmap=folium.Map(location=(TARGET_LAT,TARGET_LON),zoom_start=zoom_level,tiles=tile_style,control_scale=True)
folium.Marker(
        (lat, lon),
        icon=DivIcon(
            icon_size=(20,20),
            icon_anchor=(10,10),
            html=f'<i class="fa fa-plane" style="color:blue;transform:rotate({hdg-90}deg);transform-origin:center;font-size:20px"></i>'
        ),
        popup=f"{cs}
Alt: {baro} m
Spd: {vel} m/s"
    ).add_to(fmap)
    folium.Marker((lat,lon), icon=DivIcon(icon_size=(150,36),icon_anchor=(0,0),html=f'<div style="font-size:12px">{cs}</div>')).add_to(fmap)
    trail_pts = calculate_trail(lat,lon,baro,vel,hdg)
    if trail_pts:
        line = folium.PolyLine(locations=trail_pts,color="black",weight=shadow_width,opacity=0.6)
        fmap.add_child(line)
        PolyLineTextPath(line,'▶',repeat=True,offset=10,attributes={'fill':'blue','font-weight':'bold','font-size':'6px'}).add_to(fmap)
        for s_lat,s_lon in trail_pts:
            d_lat=(s_lat-TARGET_LAT)*111111
            d_lon=(s_lon-TARGET_LON)*111111*math.cos(math.radians(TARGET_LAT))
            if math.hypot(d_lat,d_lon)<=HOME_ALERT_THRESHOLD_M:
                home_alert=True

# Render map
st_folium(fmap,width=900,height=600)

# On-screen alert for home proximity
if home_alert:
    st.warning("⚠️ Aircraft shadow over home!")

# Audio alert if condition met
if enable_audio and home_alert:
    beep = generate_beep()
    st.audio(beep, format='audio/wav')
st_folium(fmap,width=900,height=600)

# On-screen alert for home proximity
if home_alert:
    st.warning("⚠️ Aircraft shadow over home!")

# Audio alert if condition met
if enable_audio and home_alert:
    beep = generate_beep()
    st.audio(beep, format='audio/wav')
