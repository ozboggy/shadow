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

# Optional moon support
try:
    import ephem
except ImportError:
    ephem = None

# Ensure history list exists
if "history" not in st.session_state:
    st.session_state.history = []

# Sidebar: auto-refresh settings
st.sidebar.header("Refresh Settings")
auto_refresh     = st.sidebar.checkbox("Auto Refresh Map", True)
refresh_interval = st.sidebar.number_input("Refresh Interval (s)", 1, 60, 1)
if auto_refresh:
    st_autorefresh(interval=refresh_interval * 1000, key="datarefresh")

# Environment variables
PUSHOVER_USER_KEY   = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN  = os.getenv("PUSHOVER_API_TOKEN")
ADSBEX_TOKEN        = os.getenv("ADSBEX_TOKEN")

# Home location & defaults
CENTER_LAT            = -33.7602563
CENTER_LON            = 150.9717434
DEFAULT_RADIUS_KM     = 10
FORECAST_INTERVAL_SEC = 30
FORECAST_DURATION_MIN = 5

def send_pushover(title: str, message: str):
    if not (PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN):
        st.warning("🔒 Missing Pushover credentials")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token":   PUSHOVER_API_TOKEN,
                "user":    PUSHOVER_USER_KEY,
                "title":   title,
                "message": message
            },
            timeout=5
        )
    except Exception as e:
        st.warning(f"Pushover failed: {e}")

def hav(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

now = datetime.now(timezone.utc)

# Compute sun & moon altitudes at home
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now)
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now
    moon_alt = math.degrees(float(ephem.Moon(obs).alt))
else:
    moon_alt = None

# Sidebar: map & alert settings
st.sidebar.header("Map & Alert Settings")
sc = "green" if sun_alt > 0 else "red"
st.sidebar.markdown(f"**Sun altitude:** <span style='color:{sc};'>{sun_alt:.1f}°</span>",
                    unsafe_allow_html=True)
if moon_alt is not None:
    mc = "green" if moon_alt > 0 else "red"
    st.sidebar.markdown(f"**Moon altitude:** <span style='color:{mc};'>{moon_alt:.1f}°</span>",
                        unsafe_allow_html=True)
else:
    st.sidebar.markdown("**Moon altitude:** _(PyEphem not installed)_")

radius_km           = st.sidebar.slider("Search Radius (km)", 0, 1000, DEFAULT_RADIUS_KM)
military_radius_km  = st.sidebar.slider("Military Alert Radius (km)", 0, 1000, DEFAULT_RADIUS_KM)
track_sun           = st.sidebar.checkbox("Show Sun Shadows", True)
track_moon          = st.sidebar.checkbox("Show Moon Shadows", False)
alert_width         = st.sidebar.slider("Shadow Alert Width (m)", 0, 1000, 50)
enable_onscreen     = st.sidebar.checkbox("Enable Onscreen Alert", True)

if st.sidebar.button("Test Pushover"):
    send_pushover("✈️ Test Alert", "This is a test notification.")
    st.sidebar.success("Pushover test sent!")
if st.sidebar.button("Test Onscreen"):
    if enable_onscreen:
        st.error("🚨 TEST ALERT!")
        st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
    else:
        st.sidebar.warning("Onscreen alerts disabled.")

st.title("✈️ Aircraft Shadow Tracker")

# Fetch ADS-B Exchange data
raw = []
if ADSBEX_TOKEN:
    try:
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        headers = {
            "x-rapidapi-key": ADSBEX_TOKEN,
            "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        raw = resp.json().get("ac", [])
    except Exception as e:
        st.warning(f"ADS-B fetch failed: {e}")
else:
    st.info("No ADS-B key; skipping fetch.")

# Fallback to OpenSky if no ADS-B data
if not raw:
    dr = radius_km / 111
    south, north = CENTER_LAT - dr, CENTER_LAT + dr
    dlon = dr / math.cos(math.radians(CENTER_LAT))
    west, east = CENTER_LON - dlon, CENTER_LON + dlon
    try:
        r2 = requests.get(
            f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}",
            timeout=10
        )
        r2.raise_for_status()
        states = r2.json().get("states", [])
    except Exception as e:
        st.warning(f"OpenSky fetch failed: {e}")
        states = []
    raw = [
        {"lat": s[6], "lon": s[5], "alt": s[13] or 0.0,
         "track": s[10] or 0.0, "callsign": (s[1].strip() or s[0]),
         "mil": False}
        for s in states if len(s) >= 11
    ]

# Process into DataFrame
aircraft = []
for ac in raw:
    try:
        lat   = float(ac.get("lat") or ac.get("Lat") or 0)
        lon   = float(ac.get("lon") or ac.get("Long") or 0)
        alt   = float(ac.get("alt") or ac.get("alt_geo", 0))
        angle = float(ac.get("track") or ac.get("Trak") or 0)
        cs    = ac.get("callsign") or ac.get("flight") or ac.get("Callsign") or ""
        mil   = bool(ac.get("mil", False))
    except:
        continue
    aircraft.append({
        "lat": lat, "lon": lon, "alt": alt,
        "angle": angle, "callsign": cs.strip(), "mil": mil
    })

df = pd.DataFrame(aircraft)
st.sidebar.markdown(f"**Tracked Aircraft:** {len(df)}")
st.sidebar.markdown(f"**Tracked Military Aircraft:** {int(df['mil'].sum())}")
if not df.empty:
    df["alt"] = pd.to_numeric(df["alt"], errors="coerce").fillna(0)

# Forecast shadow trails
trails_sun, trails_moon = [], []
if track_sun:
    for _, r in df.iterrows():
        path, times = [], []
        for s in range(0, FORECAST_INTERVAL_SEC * FORECAST_DURATION_MIN + 1, FORECAST_INTERVAL_SEC):
            ft = now + timedelta(seconds=s)
            sa, az = get_altitude(r.lat, r.lon, ft), get_azimuth(r.lat, r.lon, ft)
            if sa > 0:
                d = r.alt / math.tan(math.radians(sa))
                sh_lat = r.lat + (d / 111111) * math.cos(math.radians(az + 180))
                sh_lon = r.lon + (d / (111111 * math.cos(math.radians(r.lat)))) * math.sin(math.radians(az + 180))
                path.append((sh_lon, sh_lat))
                times.append(s)
        if path:
            trails_sun.append({"callsign": r.callsign, "path": path, "times": times})

if track_moon and ephem:
    for _, r in df.iterrows():
        path, times = [], []
        for s in range(0, FORECAST_INTERVAL_SEC * FORECAST_DURATION_MIN + 1, FORECAST_INTERVAL_SEC):
            ft = now + timedelta(seconds=s)
            obs = ephem.Observer()
            obs.lat, obs.lon, obs.date = str(r.lat), str(r.lon), ft
            m = ephem.Moon(obs)
            ma, mz = math.degrees(float(m.alt)), math.degrees(float(m.az))
            if ma > 0:
                d = r.alt / math.tan(math.radians(ma))
                sh_lat = r.lat + (d / 111111) * math.cos(math.radians(mz + 180))
                sh_lon = r.lon + (d / (111111 * math.cos(math.radians(r.lat)))) * math.sin(math.radians(mz + 180))
                path.append((sh_lon, sh_lat))
                times.append(s)
        if path:
            trails_moon.append({"callsign": r.callsign, "path": path, "times": times})

# Compute alerts
alerts = []
for tr in trails_sun:
    for (lon, lat), t in zip(tr["path"], tr["times"]):
        if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
            alerts.append((tr["callsign"], t))
            send_pushover("✈️ Shadow Alert", f"{tr['callsign']} in ~{t}s")
            break

shadow_calls = {cs for cs, _ in alerts}
df["will_shadow"] = df["callsign"].isin(shadow_calls)
df_safe  = df[~df["will_shadow"]]
df_alert = df[df["will_shadow"]]

# Render map with shadow paths
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []

# Aircraft dots
if not df_safe.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", df_safe,
        get_position=["lon", "lat"], get_color=[0, 0, 255, 200],
        get_radius=100
    ))
if not df_alert.empty:
    layers.append(pdk.Layer(
        "ScatterplotLayer", df_alert,
        get_position=["lon", "lat"], get_color=[255, 0, 0, 200],
        get_radius=100
    ))

# Sun shadow trails
if track_sun:
    layers.append(pdk.Layer(
        "PathLayer", pd.DataFrame(trails_sun),
        get_path="path", get_color=[255, 215, 0, 180],
        get_width=4, width_min_pixels=3
    ))

# Moon shadow trails
if track_moon:
    layers.append(pdk.Layer(
        "PathLayer", pd.DataFrame(trails_moon),
        get_path="path", get_color=[100, 100, 100, 180],
        get_width=4, width_min_pixels=3
    ))

# Home marker
layers.append(pdk.Layer(
    "ScatterplotLayer",
    pd.DataFrame([{"lat": CENTER_LAT, "lon": CENTER_LON}]),
    get_position=["lon", "lat"], get_color=[255, 0, 0, 200],
    get_radius=alert_width
))

st.pydeck_chart(
    pdk.Deck(layers=layers, initial_view_state=view, map_style="light"),
    use_container_width=True
)

# Onscreen alerts
if alerts and enable_onscreen:
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
for cs, t in alerts:
    st.write(f"✈️ {cs} — in approx. {t} seconds")
if not alerts:
    st.success("✅ No shadow paths intersect target area.")

# Update & display history
st.session_state.history.append({
    "time":         now,
    "tracked":      len(df),
    "shadow_events": len(alerts)
})
hist_df = pd.DataFrame(st.session_state.history).set_index("time")
st.subheader("📈 Tracked vs Shadow Events Over Time")
st.line_chart(hist_df)
