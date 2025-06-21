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
import folium
from streamlit_folium import st_folium
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
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# Load or set default home location
def load_home():
    default = {'lat': -33.7602563, 'lon': 150.9717434}
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
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def log_alert(callsign, lat, lon, time_until, distance_mi):
    df = pd.read_csv(log_path)
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

# Defaults
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_S = 30
FORECAST_DURATION_MIN = 5

# Sidebar: Home & Map Options
with st.sidebar:
    st.header("Home & Map Options")
    # Home Location inputs
    st.subheader("Home Location")
    st.markdown(f"**Current:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
    new_lat = st.number_input("New Home Latitude", value=CENTER_LAT, format="%.6f")
    new_lon = st.number_input("New Home Longitude", value=CENTER_LON, format="%.6f")
    if st.button("Save Home Location"):
        with open(home_config, "w") as f:
            json.dump({"lat": new_lat, "lon": new_lon}, f)
        st.success(f"Home updated to {new_lat:.6f}, {new_lon:.6f}")
        CENTER_LAT, CENTER_LON = new_lat, new_lon

    st.markdown("---")
    # Alert preferences
    on_screen_alerts = st.checkbox("Enable On-Screen Alerts", value=True)
    pushover_alerts = st.checkbox("Enable Pushover Alerts", value=True)

    st.markdown("---")
    # Map settings
    radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun = st.checkbox("Show Sun Shadows", value=True)
    track_moon = st.checkbox("Show Moon Shadows", value=False)
    alert_width = st.slider("Shadow Alert Width (m)", 0, 1000, 50)

    # Test buttons
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

    st.markdown("---")
    # Download
    if os.path.exists(log_path):
        st.download_button("📥 Download alert_log.csv", open(log_path, 'rb'), "alert_log.csv", "text/csv")
    else:
        st.info("No alert_log.csv yet")

# Main app continues below
now_utc = datetime.now(timezone.utc)
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
    headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
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
        lat, lon = float(ac.get('lat')), float(ac.get('lon'))
    except:
        continue
    cs = (ac.get('flight') or ac.get('hex') or '').strip()
    # handle missing altitude gracefully
    alt_raw = ac.get('alt_geo') if ac.get('alt_geo') not in (None, '') else ac.get('alt_baro')
    try:
        alt_val = float(alt_raw)
    except (TypeError, ValueError):
        alt_val = 0.0
    vel = float(ac.get('gs') or ac.get('spd') or 0)
    hdg = float(ac.get('track') or ac.get('trak') or 0)
    if alt_val > 0:
        aircraft_list.append({'lat': lat, 'lon': lon, 'alt': alt_val,
                              'vel': vel, 'hdg': hdg, 'callsign': cs})

# Create DataFrame & metrics
import pandas as pd

df_ac = pd.DataFrame(aircraft_list)
# default military count
mil_count = 0
if not df_ac.empty:
    # ensure numeric types
    df_ac[['alt', 'vel', 'hdg']] = df_ac[['alt', 'vel', 'hdg']].apply(
        pd.to_numeric, errors='coerce').fillna(0)
    # convert altitude to feet and round to nearest ft
    df_ac['alt_ft'] = (df_ac['alt'] * 3.28084).round().astype(int)
    # convert speed to knots and round to nearest kt
    df_ac['vel_kt'] = (df_ac['vel'] * 1.94384).round().astype(int)
    # compute distances
    df_ac['distance_m'] = df_ac.apply(
        lambda r: hav(r['lat'], r['lon'], CENTER_LAT, CENTER_LON), axis=1
    )
    df_ac['distance_mi'] = df_ac['distance_m'] / 1609.34
    # military count
    mil_df = df_ac[
        df_ac['callsign'].str.contains(r'^(MIL|USAF|RAF|RCAF)', na=False) &
        (df_ac['distance_mi'] <= 200)
    ]
    mil_count = len(mil_df)

# Sidebar status
st.sidebar.markdown("### Status")
st.sidebar.markdown(f"Sun altitude: {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.sidebar.markdown(f"Moon altitude: {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.sidebar.warning("Moon data unavailable")
st.sidebar.markdown(f"Total airborne aircraft: **{len(df_ac)}**")
# Military aircraft count metric
st.sidebar.metric(label="Military (≤200 mi)", value=f"{mil_count}")

# Build shadow trails
sun_trails = []
if not df_ac.empty and track_sun:
    for _, row in df_ac.iterrows():
        cs, lat0, lon0 = row['callsign'], row['lat'], row['lon']
        s_path = []
        for i in range(0, FORECAST_INTERVAL_S*FORECAST_DURATION_MIN+1, FORECAST_INTERVAL_S):
            t = now_utc + timedelta(seconds=i)
            d = row['vel'] * i
            dlat = d * math.cos(math.radians(row['hdg'])) / 111111
            dlon = d * math.sin(math.radians(row['hdg'])) / (111111 * math.cos(math.radians(lat0)))
            li, lo = lat0 + dlat, lon0 + dlon
            sa, saz = get_altitude(li, lo, t), get_azimuth(li, lo, t)
            if sa > 0:
                sd = row['alt'] / math.tan(math.radians(sa))
                shlat = li + (sd/111111) * math.cos(math.radians(saz+180))
                shlon = lo + (sd/(111111 * math.cos(math.radians(li)))) * math.sin(math.radians(saz+180))
                s_path.append([shlon, shlat])
        if s_path:
            sun_trails.append({"path": s_path, "callsign": cs, "current": s_path[0]})

# Prepare layers
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []
if sun_trails:
    df_s = pd.DataFrame(sun_trails)
    layers.append(pdk.Layer(
        "PathLayer", df_s, get_path="path",
        get_color=[50,50,50,255], width_scale=5, width_min_pixels=1
    ))
    curr = pd.DataFrame([{"lon": s["current"][0], "lat": s["current"][1]} for s in sun_trails])
    layers.append(pdk.Layer(
        "ScatterplotLayer", curr,
        get_position=["lon","lat"],
        get_fill_color=[50,50,50,255], get_radius=100,
        pickable=True
    ))
# Alert circle
circle = []
for ang in range(0,360,5):
    b = math.radians(ang)
    dy = (alert_width/111111)*math.cos(b)
    dx = (alert_width/(111111*math.cos(math.radians(CENTER_LAT))))*math.sin(b)
    circle.append([CENTER_LON+dx, CENTER_LAT+dy])
circle.append(circle[0])
layers.append(pdk.Layer(
    "PolygonLayer", [{"polygon": circle}],
    get_polygon="polygon", get_fill_color=[255,0,0,100], stroked=True,
    get_line_color=[255,0,0], get_line_width=3, pickable=False
))
# Aircraft scatter layer
if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", df_ac,
        get_position=["lon","lat"],
        get_fill_color=[0,128,255,200], get_radius=300,
        pickable=True, auto_highlight=True,
        highlight_color=[255,255,0,255]
    ))
# Tooltip
tooltip = {
    "html": (
        "<b>Callsign:</b> {callsign}<br/>"
        "<b>Alt:</b> {alt_ft} ft<br/>"
        "<b>Speed:</b> {vel_kt} kt<br/>"
        "<b>Heading:</b> {hdg}°"
    ),
    "style": {"backgroundColor":"black","color":"white"}
}
# Render map
st.pydeck_chart(pdk.Deck(
    layers=layers,
    initial_view_state=view,
    map_style="light",
    tooltip=tooltip
), use_container_width=True)

# Alert detection & logging
for trail in sun_trails:
    for lon, lat in trail['path']:
        if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
            cs = trail['callsign']
            dist_mi = hav(lat, lon, CENTER_LAT, CENTER_LON)/1609.34
            idx = trail['path'].index([lon, lat])
            transit = idx * FORECAST_INTERVAL_S
            # on-screen alert
            if on_screen_alerts:
                st.error(f"🚨 Sun shadow by {cs}: {dist_mi:.1f} mi away, {transit} sec transit")
                st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg")
            # log
            log_alert(cs, lat, lon, transit, dist_mi)
            # pushover
            if pushover_alerts:
                send_pushover("✈️ Shadow Alert", f"{cs}: {dist_mi:.1f} mi away, {transit} sec transit")
            break

# Recent Alerts Section
try:
    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        df_log['y'] = 0
        df_disp = df_log[['Time UTC','Callsign','Distance (mi)','Time Until Alert (sec)']].copy()
        df_disp.rename(columns={'Time Until Alert (sec)':'Transit (s)'}, inplace=True)
        st.markdown("### 📊 Recent Alerts")
        st.dataframe(df_disp.tail(10))
        fig = px.scatter(df_log, x='Time UTC', y='y', size='Distance (mi)', size_max=40,
                         hover_name='Callsign', hover_data={'Transit (s)':True}, title="Alert Proximity Timeline")
        fig.add_hline(y=0, line_color='lightgray', line_width=1)
        fig.update_yaxes(visible=False, range=[-0.5,0.5])
        st.plotly_chart(fig, use_container_width=True)
except FileNotFoundError:
    st.warning(f"Alert log not found at `{log_path}`")

# Test buttons
if test_alert:
    ph = st.empty(); ph.success("🔔 Test alert triggered!"); time.sleep(2); ph.empty()
if test_pushover:
    ph2 = st.empty();
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        ph2.error("⚠️ Missing Pushover credentials")
    else:
        ok = send_pushover("✈️ Test", "This is a test from your app.")
        ph2.success("✅ Test Pushover sent!" if ok else "❌ Test Pushover failed")
    time.sleep(2); ph2.empty()
