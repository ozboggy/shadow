import time
import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import json
import requests
import pandas as pd
import plotly.express as px
import pydeck as pdk
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth

# Optional moon computations
try:
    import ephem
except ImportError:
    ephem = None

# Paths and config
log_path = os.getenv("LOG_PATH", "alert_log.csv")
home_config = os.getenv("HOME_CONFIG", "home_location.json")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# Defaults
DEFAULT_RADIUS_MI = 25
RADIUS_KM = DEFAULT_RADIUS_MI * 1.60934
FORECAST_S = 60
INTERVAL_S = 1

# Load home location
def load_home():
    default = {'lat': -33.8544014, 'lon': 151.2087668}
    if os.path.exists(home_config):
        try:
            cfg = json.load(open(home_config))
            return cfg.get('lat', default['lat']), cfg.get('lon', default['lon'])
        except:
            pass
    return default['lat'], default['lon']

CENTER_LAT, CENTER_LON = load_home()

# Initialize log
if not os.path.exists(log_path):
    pd.DataFrame(columns=["Time UTC","Callsign","Lat","Lon","Time Until Alert (s)","Distance (mi)"]).to_csv(log_path,index=False)

# Haversine
def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

# Log alert
def log_alert(cs, lat, lon, t, d):
    df = pd.read_csv(log_path)
    df = pd.concat([df, pd.DataFrame([{
        "Time UTC": datetime.now(timezone.utc).isoformat(),
        "Callsign": cs,
        "Lat": lat,
        "Lon": lon,
        "Time Until Alert (s)": t,
        "Distance (mi)": d
    }])], ignore_index=True)
    df.to_csv(log_path, index=False)

# Sidebar
with st.sidebar:
    st.header("Settings")
    st.subheader("Home Location")
    st.markdown(f"**Current:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
    new_lat = st.number_input("Latitude", value=CENTER_LAT, format="%.6f")
    new_lon = st.number_input("Longitude", value=CENTER_LON, format="%.6f")
    if st.button("Save Home Location"):
        with open(home_config, 'w') as f:
            json.dump({'lat': new_lat, 'lon': new_lon}, f)
        CENTER_LAT, CENTER_LON = new_lat, new_lon
        st.success("Home updated")
    st.markdown("---")
    on_screen = st.checkbox("On-Screen Alerts", True)
    show_alerts = st.checkbox("Show Recent Alerts", True)

# Main
now = datetime.now(timezone.utc)
# Sun/Moon
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now
    moon_alt = math.degrees(ephem.Moon(obs).alt)

# Fetch data
ac_list = []
if RAPIDAPI_KEY:
    try:
        r = requests.get(
            f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{RADIUS_KM}/",
            headers={"x-rapidapi-key": RAPIDAPI_KEY}
        )
        ac_list = r.json().get('ac', [])
    except:
        st.warning("Failed ADS-B fetch.")

df = pd.DataFrame([{
    'lat': float(a['lat']),
    'lon': float(a['lon']),
    'alt_ft': int(a.get('alt_baro') or 0) or int(float(a.get('alt_geo') or 0)*3.28084),
    'vel': float(a.get('gs') or a.get('spd') or 0),
    'hdg': float(a.get('track') or a.get('trak') or 0),
    'cs': (a.get('flight') or a.get('hex') or '').strip()
} for a in ac_list if a.get('lat')])

if not df.empty:
    df['vel_kt'] = df['vel'].round().astype(int)
    df['dist_m'] = df.apply(lambda r: hav(r['lat'], r['lon'], CENTER_LAT, CENTER_LON), axis=1)
    df['dist_mi'] = df['dist_m']/1609.34

# Build trails
sun_trails = []
if not df.empty:
    for _, r in df.iterrows():
        path, times = [], []
        for i in range(0, FORECAST_S+1, INTERVAL_S):
            t = now + timedelta(seconds=i)
            d = r['vel']*i
            dlat = d*math.cos(math.radians(r['hdg']))/111111
            dlon = d*math.sin(math.radians(r['hdg']))/(111111*math.cos(math.radians(r['lat'])))
            li, lo = r['lat']+dlat, r['lon']+dlon
            sa = get_altitude(li, lo, t)
            if sa>0:
                sd = r['alt_ft']/math.tan(math.radians(sa))
                shlon = lo + (sd/(111111*math.cos(math.radians(li))))*math.sin(math.radians(180))
                shlat = li + (sd/111111)*math.cos(math.radians(180))
                path.append([shlon, shlat])
                times.append(i)
        if path:
            sun_trails.append({'path': path, 'times': times, 'cs': r['cs']})

# Layers
layers = []
# distance rings
for m in [1,2,5,10,20]:
    km = m*1.60934
    dkm = km*1000/111111
    circle = [[CENTER_LON + dkm*math.sin(math.radians(a)), CENTER_LAT + dkm*math.cos(math.radians(a))] for a in range(0,360,5)]
    circle.append(circle[0])
    layers.append(pdk.Layer("PathLayer", data=[{'path': circle}], get_path='path', get_color=[0,200,0,160], width_scale=100, width_min_pixels=1))
# sun shadows
if sun_trails:
    df_s = pd.DataFrame(sun_trails)
    layers.append(pdk.Layer("PathLayer", df_s, get_path='path', get_color=[50,50,50,255], width_scale=5, width_min_pixels=1))

# View and render
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=12)
st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_style='light'), use_container_width=True)

# Alerts
if on_screen and not df.empty:
    for tr in sun_trails:
        for t, pt in zip(tr['times'], tr['path']):
            dmi = hav(pt[1], pt[0], CENTER_LAT, CENTER_LON)/1609.34
            if dmi*1609.34 <= RADIUS_KM*1000:
                if t<=5: st.error(f"🚨 {t}s to shadow by {tr['cs']}, {dmi:.1f} mi")
                elif t<=10: st.warning(f"⏳ {t}s to shadow by {tr['cs']}, {dmi:.1f} mi")
                break

# Recent Alerts
if show_alerts:
    df_log = pd.read_csv(log_path)
    df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
    st.markdown("### 📊 Recent Alerts")
    st.dataframe(df_log.tail(10))
    fig = px.scatter(df_log, x='Time UTC', y=0, size='Distance (mi)')
    st.plotly_chart(fig, use_container_width=True)
