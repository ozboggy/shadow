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

# Auto-refresh every second
AUTOREFRESH_MS = 1000
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=AUTOREFRESH_MS, key="datarefresh")
except ImportError:
    pass

# Paths & credentials
log_path = os.getenv("LOG_PATH", "alert_log.csv")
home_config = os.getenv("HOME_CONFIG", "home_location.json")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# Load or set default home location
def load_home():
    default = {'lat': -33.8544014, 'lon': 151.2087668}
    if os.path.exists(home_config):
        try:
            cfg = json.load(open(home_config))
            return cfg.get('lat', default['lat']), cfg.get('lon', default['lon'])
        except:
            return default['lat'], default['lon']
    return default['lat'], default['lon']

CENTER_LAT, CENTER_LON = load_home()

# Ensure the alert log exists
if not os.path.exists(log_path):
    pd.DataFrame(columns=[
        "Time UTC", "Callsign", "Lat", "Lon", "Time Until Alert (sec)", "Distance (mi)"
    ]).to_csv(log_path, index=False)

# Helper functions
def hav(lat1, lon1, lat2, lon2):
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

def log_alert(callsign, lat, lon, time_until, distance_mi):
    try:
        df = pd.read_csv(log_path)
    except Exception:
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
    df.to_csv(log_path, index=False)

# Defaults & fixed radius
DEFAULT_RADIUS_MI = 10
radius_km = DEFAULT_RADIUS_MI * 1.60934
FORECAST_INTERVAL_S = 1
FORECAST_DURATION_S = 60

# Sidebar: Home & Map Options (minus Pushover & radius slider)
with st.sidebar:
    st.header("Home & Map Options")
    st.subheader("Home Location")
    st.markdown(f"**Current:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
    new_lat = st.number_input("New Home Latitude", value=float(CENTER_LAT), format="%.6f")
    new_lon = st.number_input("New Home Longitude", value=float(CENTER_LON), format="%.6f")
    if st.button("Save Home Location"):
        with open(home_config, "w") as f:
            json.dump({"lat": new_lat, "lon": new_lon}, f)
        st.success(f"Home updated to {new_lat:.6f}, {new_lon:.6f}")
        CENTER_LAT, CENTER_LON = new_lat, new_lon
        st.experimental_rerun()

    st.markdown("---")
    on_screen_alerts = st.checkbox("Enable On-Screen Alerts", value=True)
    st.markdown(f"**Search Radius:** {DEFAULT_RADIUS_MI} mi")
    track_sun = st.checkbox("Show Sun Shadows", value=True)
    track_moon = st.checkbox("Show Moon Shadows", value=False)
    alert_width = st.slider("Shadow Alert Width (m)", 10, 1000, 50)
    test_alert = st.button("Test Alert")

    st.markdown("---")
    if os.path.exists(log_path):
        st.download_button("📥 Download alert_log.csv", open(log_path, 'rb'), "alert_log.csv", "text/csv")
    else:
        st.info("No alert_log.csv yet")

now_utc = datetime.now(timezone.utc)

# Sun & moon altitude
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now_utc
    moon = ephem.Moon(obs)
    moon_alt = math.degrees(moon.alt)

# Fetch ADS-B data
aircraft_list = []
if RAPIDAPI_KEY:
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
    }
    try:
        r = requests.get(url, headers=headers); r.raise_for_status()
        data = r.json().get("ac", [])
    except Exception:
        st.warning("Failed to fetch ADS-B data."); data = []
else:
    data = []

for ac in data:
    try:
        lat = float(ac.get('lat')); lon = float(ac.get('lon'))
    except (TypeError, ValueError):
        continue
    cs = (ac.get('flight') or ac.get('hex') or '').strip()
    baro, geo = ac.get('alt_baro'), ac.get('alt_geo')
    try:
        if baro not in (None, ''):
            alt_ft = int(float(baro))
        elif geo not in (None, ''):
            alt_ft = int(float(geo) * 3.28084)
        else:
            alt_ft = 0
    except:
        alt_ft = 0
    vel = float(ac.get('gs') or ac.get('spd') or 0)
    hdg = float(ac.get('track') or ac.get('trak') or 0)
    if alt_ft > 0:
        aircraft_list.append({
            'lat': lat, 'lon': lon,
            'alt_ft': alt_ft, 'vel': vel, 'hdg': hdg,
            'callsign': cs
        })

df_ac = pd.DataFrame(aircraft_list)
mil_count = 0
if not df_ac.empty:
    df_ac[['alt_ft','vel','hdg']] = df_ac[['alt_ft','vel','hdg']].apply(pd.to_numeric, errors='coerce').fillna(0)
    df_ac['vel_kt'] = df_ac['vel'].round().astype(int)
    df_ac['alt_ft'] = df_ac['alt_ft'].astype(int)
    df_ac['distance_m'] = df_ac.apply(lambda r: hav(r['lat'], r['lon'], CENTER_LAT, CENTER_LON), axis=1)
    df_ac['distance_mi'] = df_ac['distance_m'] / 1609.34
    mil_df = df_ac[
        df_ac['callsign'].str.contains(r'^(MIL|USAF|RAF|RCAF)', na=False) &
        (df_ac['distance_mi'] <= 200)
    ]
    mil_count = len(mil_df)

# Display status
st.markdown(f"**Home:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
st.markdown(f"**Sun altitude:** {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.markdown(f"**Moon altitude:** {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.warning("Moon data unavailable")
st.metric("Total airborne aircraft", len(df_ac))
st.metric("Military (≤200 mi)", mil_count)

# Build shadow trails
sun_trails, moon_trails = [], []
if not df_ac.empty:
    for _, row in df_ac.iterrows():
        cs, lat0, lon0 = row['callsign'], row['lat'], row['lon']
        s_path, m_path = [], []
        for i in range(0, FORECAST_DURATION_S+1, FORECAST_INTERVAL_S):
            t = now_utc + timedelta(seconds=i)
            d = row['vel'] * i
            dlat = d * math.cos(math.radians(row['hdg'])) / 111111
            dlon = d * math.sin(math.radians(row['hdg'])) / (111111 * math.cos(math.radians(lat0)))
            li, lo = lat0 + dlat, lon0 + dlon

            # Sun shadow
            sa, saz = get_altitude(li, lo, t), get_azimuth(li, lo, t)
            if sa > 0:
                sd = row['alt_ft'] / math.tan(math.radians(sa))
                s_path.append([
                    lo + (sd/(111111*math.cos(math.radians(li))))*math.sin(math.radians(saz+180)),
                    li + (sd/111111)*math.cos(math.radians(saz+180))
                ])

            # Moon shadow
            if ephem:
                obs = ephem.Observer()
                obs.lat, obs.lon, obs.date = str(li), str(lo), t
                pm = ephem.Moon(obs)
                ma = math.degrees(pm.alt); maz = math.degrees(pm.az)
                if ma > 0:
                    md = row['alt_ft'] / math.tan(math.radians(ma))
                    m_path.append([
                        lo + (md/(111111*math.cos(math.radians(li))))*math.sin(math.radians(maz+180)),
                        li + (md/111111)*math.cos(math.radians(maz+180))
                    ])

        if s_path:
            sun_trails.append({"path": s_path, "callsign": cs, "current": s_path[0]})
        if m_path:
            moon_trails.append({"path": m_path, "callsign": cs, "current": m_path[0]})

# Prepare layers...
# (rest of your mapping + alerts logic remains exactly as before,
#  except that any `if pushover_alerts:` blocks and Pushover calls are removed)

