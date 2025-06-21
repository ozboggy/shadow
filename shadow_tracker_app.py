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

# Auto-refresh every second
st_autorefresh(interval=1_000, key="datarefresh")

# Pushover credentials
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title: str, message: str) -> bool:
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        return False
    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": PUSHOVER_API_TOKEN,
                "user": PUSHOVER_USER_KEY,
                "title": title,
                "message": message
            }
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
    return R * 2 * math.asin(math.sqrt(a))

# Defaults
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5

# Sidebar controls
with st.sidebar:
    st.header("Map Options")
    radius_km     = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun     = st.checkbox("Show Sun Shadows", True)
    track_moon    = st.checkbox("Show Moon Shadows", False)
    alert_width   = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert    = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

# Current time
now_utc = datetime.now(timezone.utc)

# Compute sun & moon altitude
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon = str(CENTER_LAT), str(CENTER_LON)
    obs.date = now_utc
    moon_obs = ephem.Moon(obs)
    moon_alt = math.degrees(moon_obs.alt)
else:
    moon_alt = None

# Fetch ADS-B Exchange data
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
    except:
        st.warning("Failed to fetch ADS-B Exchange data.")
        adsb = []
else:
    adsb = []

for ac in adsb:
    try:
        lat = float(ac.get("lat")); lon = float(ac.get("lon"))
    except:
        continue
    cs = (ac.get("flight") or ac.get("hex") or "").strip()
    try: alt_val = float(ac.get("alt_geo") or ac.get("alt_baro") or 0)
    except: alt_val = 0.0
    try: vel = float(ac.get("gs") or ac.get("spd") or 0)
    except: vel = 0.0
    try: hdg = float(ac.get("track") or ac.get("trak") or 0)
    except: hdg = 0.0
    if alt_val > 0:  # only airborne
        aircraft_list.append({
            "lat": lat, "lon": lon,
            "alt": alt_val, "vel": vel,
            "hdg": hdg, "callsign": cs
        })

# Total airborne aircraft count
total_ac = len(aircraft_list)

# Title and sidebar status
st.title("✈️ Aircraft Shadow Tracker")
st.sidebar.markdown("### Status")
st.sidebar.markdown(f"Sun altitude: {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.sidebar.markdown(f"Moon altitude: {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.sidebar.warning("Moon data unavailable")
st.sidebar.markdown(f"Total airborne aircraft: **{total_ac}**")

# Compute shadow trails with timestamps
sun_trails = []
moon_trails = []
for row in aircraft_list:
    cs = row["callsign"]
    lat0, lon0 = row["lat"], row["lon"]
    s_path = []
    m_path = []
    for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS):
        t = now_utc + timedelta(seconds=i)
        dist_m = row["vel"] * i
        dlat = dist_m * math.cos(math.radians(row["hdg"])) / 111111
        dlon = dist_m * math.sin(math.radians(row["hdg"])) / (111111 * math.cos(math.radians(lat0)))
        lat_i, lon_i = lat0 + dlat, lon0 + dlon

        sa = get_altitude(lat_i, lon_i, t)
        saz = get_azimuth(lat_i, lon_i, t)
        if sa > 0 and track_sun:
            sd = row["alt"] / math.tan(math.radians(sa))
            sh_lat = lat_i + (sd / 111111) * math.cos(math.radians(saz + 180))
            sh_lon = lon_i + (sd / (111111 * math.cos(math.radians(lat_i)))) * math.sin(math.radians(saz + 180))
            s_path.append({"time": t, "lon": sh_lon, "lat": sh_lat})

        if ephem and track_moon:
            obs.date = t
            m = ephem.Moon(obs)
            ma = math.degrees(m.alt)
            maz = math.degrees(m.az)
            if ma > 0:
                md = row["alt"] / math.tan(math.radians(ma))
                mh_lat = lat_i + (md / 111111) * math.cos(math.radians(maz + 180))
                mh_lon = lon_i + (md / (111111 * math.cos(math.radians(lat_i)))) * math.sin(math.radians(maz + 180))
                m_path.append({"time": t, "lon": mh_lon, "lat": mh_lat})

    if s_path:
        sun_trails.append({"callsign": cs, "path": s_path})
    if m_path:
        moon_trails.append({"callsign": cs, "path": m_path})

# Prepare map layers (no change to existing layers)
# … [pydeck layers for scatter, sun paths, moon paths, alert circle, tooltip] …

# Now compute next crossover events
def next_event(trails):
    soonest = None
    for tr in trails:
        for pt in tr["path"]:
            dist = hav(pt["lat"], pt["lon"], CENTER_LAT, CENTER_LON)
            if dist <= alert_width:
                dt = pt["time"] - now_utc
                if dt.total_seconds() >= 0:
                    if soonest is None or pt["time"] < soonest["time"]:
                        soonest = {"callsign": tr["callsign"], "time": pt["time"], "delta": dt}
                break
    return soonest

next_sun = next_event(sun_trails) if track_sun else None
next_moon = next_event(moon_trails) if (ephem and track_moon) else None

beep_html = """
<audio autoplay>
  <source src="https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg" type="audio/ogg">
</audio>"""

# Alert logic: continue alerting until crossover window ends
if next_sun:
    mins, secs = divmod(int(next_sun["delta"].total_seconds()), 60)
    st.error(f"🚨 Sun shadow ({next_sun['callsign']}) crosses in {mins}m{secs}s at {next_sun['time'].strftime('%H:%M:%S UTC')}")
    st.markdown(beep_html, unsafe_allow_html=True)
    send_pushover("✈️ Sun Shadow Alert", f"{next_sun['callsign']} in {mins}m{secs}s")

if next_moon:
    mins, secs = divmod(int(next_moon["delta"].total_seconds()), 60)
    st.error(f"🚨 Moon shadow ({next_moon['callsign']}) crosses in {mins}m{secs}s at {next_moon['time'].strftime('%H:%M:%S UTC')}")
    st.markdown(beep_html, unsafe_allow_html=True)
    send_pushover("✈️ Moon Shadow Alert", f"{next_moon['callsign']} in {mins}m{secs}s")

# Test alert: audio + screen
if test_alert:
    ph = st.empty()
    ph.success("🔔 Test alert triggered!")
    st.markdown(beep_html, unsafe_allow_html=True)
    time.sleep(5)
    ph.empty()

# Test pushover
if test_pushover:
    ph2 = st.empty()
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        ph2.error("⚠️ Missing Pushover credentials")
    else:
        ok = send_pushover("✈️ Test", "This is a test from your app.")
        ph2.success("✅ Test Pushover sent!" if ok else "❌ Test Pushover failed")
    time.sleep(5)
    ph2.empty()
