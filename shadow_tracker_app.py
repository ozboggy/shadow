
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

try:
    import ephem
except ImportError:
    ephem = None

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
        r = requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message
        })
        return r.status_code == 200
    except:
        return False

# Helpers
def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Config
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
alert_times = [60, 30, 15, 10, 5, 0]
FORECAST_INTERVAL_SECONDS = 5
FORECAST_DURATION_MINUTES = 5

# Sidebar
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

# Sun & moon alt
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon = str(CENTER_LAT), str(CENTER_LON)
    obs.date = now_utc
    moon_obs = ephem.Moon(obs)
    moon_alt = math.degrees(moon_obs.alt)

# Aircraft
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
        for ac in r.json().get("ac", []):
            try:
                lat, lon = float(ac["lat"]), float(ac["lon"])
                alt = float(ac.get("alt_geo") or ac.get("alt_baro") or 0)
                vel = float(ac.get("gs") or 0)
                hdg = float(ac.get("track") or 0)
                cs = ac.get("flight") or ac.get("hex") or ""
                if alt > 0:
                    aircraft_list.append({"lat": lat, "lon": lon, "alt": alt, "vel": vel, "hdg": hdg, "callsign": cs})
            except:
                continue
    except:
        st.warning("Failed to fetch aircraft")

df_ac = pd.DataFrame(aircraft_list)

# Shadow calculation
sun_trails, moon_trails = [], []
sun_export, moon_export = [], []

for _, row in df_ac.iterrows():
    path = []
    for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
        t = now_utc + timedelta(seconds=i)
        dist_m = row['vel'] * i
        dlat = dist_m * math.cos(math.radians(row['hdg'])) / 111111
        dlon = dist_m * math.sin(math.radians(row['hdg'])) / (111111 * math.cos(math.radians(row['lat'])))
        lat_i, lon_i = row['lat'] + dlat, row['lon'] + dlon

        if show_sun:
            sa = get_altitude(lat_i, lon_i, t)
            if sa > 0:
                saz = get_azimuth(lat_i, lon_i, t)
                sd = row['alt'] / math.tan(math.radians(sa))
                sh_lat = lat_i + (sd / 111111) * math.cos(math.radians(saz + 180))
                sh_lon = lon_i + (sd / (111111 * math.cos(math.radians(lat_i)))) * math.sin(math.radians(saz + 180))
                path.append((sh_lat, sh_lon, i))
                sun_export.append({"callsign": row['callsign'], "lat": sh_lat, "lon": sh_lon, "time_offset_sec": i})
    if path:
        sun_trails.append((row, path))

# Alerts
beep_html = """<audio autoplay>
  <source src=\"https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg\" type=\"audio/ogg\">
</audio>"""

for row, trail in sun_trails:
    for lat, lon, sec in trail:
        if sec in alert_times:
            dist = hav(lat, lon, CENTER_LAT, CENTER_LON)
            if dist <= alert_width:
                msg = (
                    f"✈️ {row['callsign']} sun shadow alert\n"
                    f"⏱ Transit in {sec}s\n"
                    f"📏 Distance: {int(dist)}m\n"
                    f"🛬 Altitude: {int(row['alt'])} ft\n"
                    f"🚀 Speed: {int(row['vel'])} knots"
                )
                st.error(f"🚨 Shadow over home in {sec}s!")
                st.markdown(beep_html, unsafe_allow_html=True)
                send_pushover("✈️ Shadow Alert", msg)
                break

# Layers
layers = []

if not df_ac.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=df_ac,
        get_position=["lon", "lat"],
        get_fill_color=[0, 128, 255, 200],
        get_radius=300,
        pickable=True,
        auto_highlight=True
    ))

layers.append(pdk.Layer(
    "ScatterplotLayer",
    data=pd.DataFrame([{"lat": CENTER_LAT, "lon": CENTER_LON}]),
    get_position=["lon", "lat"],
    get_fill_color=[255, 0, 0, 128],
    get_radius=alert_width,
    pickable=False
))

if show_sun_lines:
    for ac, trail in sun_trails:
        layers.append(pdk.Layer(
            "PathLayer",
            data=[{
                "path": [(lon, lat) for lat, lon, _ in trail],
                "callsign": ac["callsign"]
            }],
            get_path="path",
            get_color=[255, 255, 0],
            width_scale=ac["alt"] / 10000 + 1,
            width_min_pixels=2,
            pickable=False
        ))

if show_moon and ephem:
    for _, row in df_ac.iterrows():
        m_path = []
        for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
            t = now_utc + timedelta(seconds=i)
            dist_m = row['vel'] * i
            dlat = dist_m * math.cos(math.radians(row['hdg'])) / 111111
            dlon = dist_m * math.sin(math.radians(row['hdg'])) / (111111 * math.cos(math.radians(row['lat'])))
            lat_i, lon_i = row['lat'] + dlat, row['lon'] + dlon
            try:
                obs.date = t
                moon = ephem.Moon(obs)
                ma = math.degrees(moon.alt)
                maz = math.degrees(moon.az)
                if ma > 0:
                    md = row['alt'] / math.tan(math.radians(ma))
                    mh_lat = lat_i + (md / 111111) * math.cos(math.radians(maz + 180))
                    mh_lon = lon_i + (md / (111111 * math.cos(math.radians(lat_i)))) * math.sin(math.radians(maz + 180))
                    m_path.append((mh_lat, mh_lon, i))
                    moon_export.append({"callsign": row['callsign'], "lat": mh_lat, "lon": mh_lon, "time_offset_sec": i})
            except:
                continue
        if m_path:
            moon_trails.append((row, m_path))
            if show_moon_lines:
                layers.append(pdk.Layer(
                    "PathLayer",
                    data=[{
                        "path": [(lon, lat) for lat, lon, _ in m_path],
                        "callsign": row["callsign"]
                    }],
                    get_path="path",
                    get_color=[200, 200, 255],
                    width_scale=row["alt"] / 10000 + 1,
                    width_min_pixels=2,
                    pickable=False
                ))

# Map
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=12)
st.pydeck_chart(pdk.Deck(
    layers=layers,
    initial_view_state=view,
    map_style="light",
    tooltip={
        "html": "<b>Callsign:</b> {callsign}<br/><b>Altitude:</b> {alt} ft<br/><b>Speed:</b> {vel} kts<br/><b>Heading:</b> {hdg}°",
        "style": {"backgroundColor": "black", "color": "white", "cursor": "pointer"}
    }
), use_container_width=True)

# Buttons
if test_alert:
    st.warning("Test alert triggered")
    st.markdown(beep_html, unsafe_allow_html=True)


if test_push:
    if not df_ac.empty:
        sample = df_ac.sample(1).iloc[0]
        distance = hav(CENTER_LAT, CENTER_LON, sample['lat'], sample['lon'])
        msg = (
            f"✈️ Test Alert: {sample['callsign']}\n"
            f"📍 Lat/Lon: {sample['lat']:.4f}, {sample['lon']:.4f}\n"
            f"🛬 Altitude: {int(sample['alt'])} ft\n"
            f"🚀 Speed: {int(sample['vel'])} knots\n"
            f"🧭 Heading: {int(sample['hdg'])}°\n"
            f"📏 Distance from home: {distance:.1f} meters"
        )
        st.info(f"Random aircraft selected: {sample['callsign']} — Distance: {distance:.1f} m")
    else:
        msg = "✈️ Test alert with no aircraft data available."
    ok = send_pushover("✈️ Test", msg)



# Export
if sun_export or moon_export:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        if sun_export:
            df_sun = pd.DataFrame(sun_export)
            zip_file.writestr("sun_shadows.csv", df_sun.to_csv(index=False))
        if moon_export:
            df_moon = pd.DataFrame(moon_export)
            zip_file.writestr("moon_shadows.csv", df_moon.to_csv(index=False))
    st.download_button("Download Shadow Trails (ZIP)", zip_buffer.getvalue(), "shadow_trails.zip", "application/zip")
