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

# Fixed radius & defaults
DEFAULT_RADIUS_MI = 10
radius_km = DEFAULT_RADIUS_MI * 1.60934
FORECAST_INTERVAL_S = 1
FORECAST_DURATION_S = 60

# Sidebar: Home & Map Options (no Pushover, fixed radius)
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
        st.download_button("📥 Download alert_log.csv", open(log_path, 'rb'),
                           "alert_log.csv", "text/csv")
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
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        data = r.json().get("ac", [])
    except Exception:
        st.warning("Failed to fetch ADS-B data.")
        data = []
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
    df_ac[['alt_ft','vel','hdg']] = df_ac[['alt_ft','vel','hdg']].apply(
        pd.to_numeric, errors='coerce').fillna(0)
    df_ac['vel_kt'] = df_ac['vel'].round().astype(int)
    df_ac['alt_ft'] = df_ac['alt_ft'].astype(int)
    df_ac['distance_m'] = df_ac.apply(
        lambda r: hav(r['lat'], r['lon'], CENTER_LAT, CENTER_LON), axis=1
    )
    df_ac['distance_mi'] = df_ac['distance_m'] / 1609.34
    mil_df = df_ac[
        df_ac['callsign'].str.contains(r'^(MIL|USAF|RAF|RCAF)', na=False) &
        (df_ac['distance_mi'] <= 200)
    ]
    mil_count = len(mil_df)

# Status display
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
                shlat = li + (sd/111111) * math.cos(math.radians(saz+180))
                shlon = lo + (sd/(111111 * math.cos(math.radians(li)))) * math.sin(math.radians(saz+180))
                s_path.append([shlon, shlat])

            # Moon shadow
            if ephem:
                obs = ephem.Observer()
                obs.lat, obs.lon, obs.date = str(li), str(lo), t
                pm = ephem.Moon(obs)
                ma = math.degrees(pm.alt); maz = math.degrees(pm.az)
                if ma > 0:
                    md = row['alt_ft'] / math.tan(math.radians(ma))
                    mlat = li + (md/111111) * math.cos(math.radians(maz+180))
                    mlon = lo + (md/(111111 * math.cos(math.radians(li)))) * math.sin(math.radians(maz+180))
                    m_path.append([mlon, mlat])

        if s_path:
            sun_trails.append({"path": s_path, "callsign": cs, "current": s_path[0]})
        if m_path:
            moon_trails.append({"path": m_path, "callsign": cs, "current": m_path[0]})

# Prepare map layers
layers = []

# Distance rings
for m in [1,2,5,10,20]:
    km = m * 1.60934
    lat_diff = (km*1000)/111111
    lon_diff = lat_diff/math.cos(math.radians(CENTER_LAT))
    ring = [[CENTER_LON + lon_diff*math.sin(math.radians(a)),
             CENTER_LAT + lat_diff*math.cos(math.radians(a))]
            for a in range(0,360,5)]
    ring.append(ring[0])
    layers.append(pdk.Layer("PathLayer", data=[{"path":ring}],
                            get_path="path", get_color=[0,200,0,120],
                            width_scale=100, width_min_pixels=1, pickable=False))
    layers.append(pdk.Layer("TextLayer",
                            data=[{"text":f"{m} mi","position":[CENTER_LON, CENTER_LAT+lat_diff*1.02]}],
                            get_position="position", get_text="text",
                            get_color=[0,200,0,200], get_size=16, pickable=False))

# Shadow trails & current dots
if sun_trails:
    layers.append(pdk.Layer("PathLayer", pd.DataFrame(sun_trails), get_path="path",
                            get_color=[50,50,50,255], width_scale=5, width_min_pixels=1))
    layers.append(pdk.Layer("ScatterplotLayer",
                            pd.DataFrame([{"lon":s["current"][0],"lat":s["current"][1]} for s in sun_trails]),
                            get_position=["lon","lat"], get_fill_color=[50,50,50,255],
                            get_radius=100, pickable=True))
if moon_trails:
    layers.append(pdk.Layer("PathLayer", pd.DataFrame(moon_trails), get_path="path",
                            get_color=[200,200,200,200], width_scale=5, width_min_pixels=1))
    layers.append(pdk.Layer("ScatterplotLayer",
                            pd.DataFrame([{"lon":m["current"][0],"lat":m["current"][1]} for m in moon_trails]),
                            get_position=["lon","lat"], get_fill_color=[200,200,200,200],
                            get_radius=100, pickable=True))

# Alert ring
circle = []
for a in range(0,360,5):
    b = math.radians(a)
    dy = (alert_width/111111)*math.cos(b)
    dx = (alert_width/(111111*math.cos(math.radians(CENTER_LAT))))*math.sin(b)
    circle.append([CENTER_LON+dx, CENTER_LAT+dy])
circle.append(circle[0])
layers.append(pdk.Layer("PolygonLayer", data=[{"polygon":circle}],
                        get_polygon="polygon", get_fill_color=[255,0,0,100],
                        stroked=True, get_line_color=[255,0,0], get_line_width=3, pickable=False))

# Aircraft layer
if not df_ac.empty:
    layers.append(pdk.Layer("ScatterplotLayer", df_ac,
                            get_position=["lon","lat"],
                            get_fill_color=[0,128,255,200], get_radius=300,
                            pickable=True, auto_highlight=True, highlight_color=[255,255,0,255]))

# Render map
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON,
                     zoom=max(1, min(16, 14 - math.log(radius_km,2))))
tooltip = {
    "html": ("<b>Callsign:</b> {callsign}<br/>"
             "<b>Alt:</b> {alt_ft} ft<br/>"
             "<b>Speed:</b> {vel_kt} kt<br/>"
             "<b>Heading:</b> {hdg}°"),
    "style": {"backgroundColor":"black","color":"white"}
}
st.pydeck_chart(pdk.Deck(
    layers=layers,
    initial_view_state=view,
    map_style="light",
    tooltip=tooltip
), use_container_width=True)

# Recent Alerts table + chart (unchanged)
try:
    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        df_log['y'] = 0
        df_disp = df_log[['Time UTC','Callsign','Distance (mi)','Time Until Alert (sec)']]
        df_disp = df_disp.rename(columns={'Time Until Alert (sec)':'Transit (s)'})
        st.markdown("### 📊 Recent Alerts")
        st.dataframe(df_disp.tail(10))
        fig = px.scatter(df_log, x='Time UTC', y='y',
                         size='Distance (mi)', size_max=40,
                         hover_name='Callsign',
                         hover_data={'Time Until Alert (sec)':True},
                         title="Alert Proximity Timeline")
        fig.add_hline(y=0, line_color='lightgray', line_width=1)
        fig.update_yaxes(visible=False, range=[-0.5,0.5])
        st.plotly_chart(fig, use_container_width=True)
except FileNotFoundError:
    st.warning(f"Alert log not found at `{log_path}`")

# On-screen alert detection & logging
for trail in sun_trails:
    for lon, lat in trail['path']:
        if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
            cs = trail['callsign']
            dist_mi = hav(lat, lon, CENTER_LAT, CENTER_LON)/1609.34
            idx = trail['path'].index([lon, lat])
            transit = idx * FORECAST_INTERVAL_S
            if on_screen_alerts:
                st.error(f"🚨 Sun shadow by {cs}: {dist_mi:.2f} mi away, {transit} sec transit")
                st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg")
            log_alert(cs, lat, lon, transit, dist_mi)
            break  # one alert per run

# Test button
if test_alert:
    ph = st.empty()
    ph.success("🔔 Test alert triggered!")
    time.sleep(2)
    ph.empty()
