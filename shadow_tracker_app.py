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

# Auto‐refresh every second
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except:
    pass

# Environment variables
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
ADSBEX_TOKEN       = os.getenv("ADSBEX_TOKEN")

def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        st.warning("🔒 Pushover credentials not set.")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token":   PUSHOVER_API_TOKEN,
                "user":    PUSHOVER_USER_KEY,
                "title":   title,
                "message": message
            }
        )
    except Exception as e:
        st.warning(f"Pushover failed: {e}")

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

# Constants
CENTER_LAT            = -33.7602563
CENTER_LON            = 150.9717434
DEFAULT_RADIUS_KM     = 10
FORECAST_INTERVAL_SEC = 30
FORECAST_DURATION_MIN = 5

# Current UTC time
now = datetime.now(timezone.utc)

# Compute sun altitude at home
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now)
# Compute moon altitude at home if available
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now
    moon_alt = math.degrees(float(ephem.Moon(obs).alt))
else:
    moon_alt = None

# Initialize in‐memory history log
if 'history' not in st.session_state:
    st.session_state.history = []

# Sidebar controls
with st.sidebar:
    st.header("Map & Alert Settings")

    # Sun / Moon altitude
    sun_color = "green" if sun_alt > 0 else "red"
    st.markdown(
        f"**Sun altitude:** <span style='color:{sun_color};'>{sun_alt:.1f}°</span>",
        unsafe_allow_html=True
    )
    if moon_alt is not None:
        moon_color = "green" if moon_alt > 0 else "red"
        st.markdown(
            f"**Moon altitude:** <span style='color:{moon_color};'>{moon_alt:.1f}°</span>",
            unsafe_allow_html=True
        )
    else:
        st.markdown("**Moon altitude:** _(PyEphem not installed)_")

    radius_km           = st.slider("Search Radius (km)", 0, 1000, DEFAULT_RADIUS_KM)
    military_radius_km  = st.slider("Military Alert Radius (km)", 0, 1000, DEFAULT_RADIUS_KM)
    track_sun           = st.checkbox("Show Sun Shadows", True)
    show_moon           = st.checkbox("Show Moon Shadows", False)
    alert_width         = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    enable_onscreen     = st.checkbox("Enable Onscreen Alert", True)
    debug_adsb          = st.checkbox("Debug ADS-B Raw Data", False)

    if st.button("Send Pushover Test"):
        send_pushover("✈️ Test Alert", "This is a Pushover test notification.")
        st.success("Pushover test sent!")

    if st.button("Test Onscreen Alert"):
        if enable_onscreen:
            st.error("🚨 TEST Shadow ALERT!")
            st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
            st.markdown(
                """
                <script>
                if (Notification.permission === 'granted') {
                    new Notification("✈️ Shadow Alert", { body: "This is a test onscreen alert." });
                } else {
                    Notification.requestPermission().then(p => {
                        if (p === 'granted') {
                            new Notification("✈️ Shadow Alert", { body: "This is a test onscreen alert." });
                        }
                    });
                }
                </script>
                """,
                unsafe_allow_html=True
            )
            st.write("🚨 This is a test onscreen alert!")
        else:
            st.warning("Onscreen alerts are disabled.")

st.title("✈️ Aircraft Shadow Tracker (ADS-B Exchange)")

# Fetch live ADS-B Exchange data
aircraft_list = []
ac_data = []
if ADSBEX_TOKEN:
    try:
        url = f"https://adsbexchange.com/api/aircraft/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        headers = {"api-auth": ADSBEX_TOKEN}
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        ac_data = resp.json().get("ac", [])
    except Exception as e:
        st.warning(f"ADS-B fetch failed: {e}")
else:
    st.info("No ADS-B Exchange key; cannot fetch live data.")

# Debug: show raw ADS-B JSON
if debug_adsb:
    st.subheader("Raw ADS-B Data")
    st.write(ac_data)

# Process aircraft list
for ac in ac_data:
    try:
        lat   = float(ac.get("lat"))
        lon   = float(ac.get("lon"))
        alt   = float(ac.get("alt_geo") or ac.get("alt_baro") or 0.0)
        angle = float(ac.get("track") or ac.get("trk") or 0.0)
        cs    = str(ac.get("flight") or ac.get("hex") or "").strip()
        mil   = bool(ac.get("mil", False))
    except (TypeError, ValueError):
        continue
    aircraft_list.append({
        "lat": lat, "lon": lon, "alt": alt,
        "angle": angle, "callsign": cs, "mil": mil
    })

# Build DataFrame & show count
df_ac = pd.DataFrame(aircraft_list)
st.sidebar.markdown(f"**Tracked Aircraft:** {len(df_ac)}")
if not df_ac.empty:
    df_ac["alt"] = pd.to_numeric(df_ac["alt"], errors="coerce").fillna(0)
else:
    st.warning("No aircraft data available.")

# Forecast trails
trails_sun, trails_moon = [], []
if track_sun and not df_ac.empty:
    for _, row in df_ac.iterrows():
        path, times = [], []
        for i in range(0, FORECAST_INTERVAL_SEC * FORECAST_DURATION_MIN + 1, FORECAST_INTERVAL_SEC):
            ft    = now + timedelta(seconds=i)
            sun_a = get_altitude(row["lat"], row["lon"], ft)
            sun_z = get_azimuth(row["lat"], row["lon"], ft)
            if sun_a > 0:
                dist   = row["alt"] / math.tan(math.radians(sun_a))
                sh_lat = row["lat"] + (dist/111111)*math.cos(math.radians(sun_z+180))
                sh_lon = row["lon"] + (dist/(111111*math.cos(math.radians(row["lat"]))))*math.sin(math.radians(sun_z+180))
                path.append((sh_lon, sh_lat)); times.append(i)
        if path:
            trails_sun.append({"callsign": row["callsign"], "path": path, "times": times})

if show_moon and ephem and not df_ac.empty:
    for _, row in df_ac.iterrows():
        path, times = [], []
        for i in range(0, FORECAST_INTERVAL_SEC * FORECAST_DURATION_MIN + 1, FORECAST_INTERVAL_SEC):
            ft   = now + timedelta(seconds=i)
            obs  = ephem.Observer(); obs.lat,obs.lon,obs.date = str(row["lat"]),str(row["lon"]),ft
            m    = ephem.Moon(obs)
            m_alt = math.degrees(float(m.alt)); m_az = math.degrees(float(m.az))
            if m_alt > 0:
                dist   = row["alt"] / math.tan(math.radians(m_alt))
                sh_lat = row["lat"] + (dist/111111)*math.cos(math.radians(m_az+180))
                sh_lon = row["lon"] + (dist/(111111*math.cos(math.radians(row["lat"]))))*math.sin(math.radians(m_az+180))
                path.append((sh_lon, sh_lat)); times.append(i)
        if path:
            trails_moon.append({"callsign": row["callsign"], "path": path, "times": times})

# Build map layers
view   = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []
if not df_ac.empty:
    icon_df = pd.DataFrame([{
        "lon": r["lon"], "lat": r["lat"],
        "icon": {"url":"https://img.icons8.com/ios-filled/50/000000/airplane-take-off.png",
                 "width":128,"height":128,"anchorX":64,"anchorY":64},
        "angle": r["angle"]
    } for _, r in df_ac.iterrows()])
    layers.append(pdk.Layer("IconLayer", icon_df,
                            get_icon="icon", get_position=["lon","lat"], get_angle="angle",
                            size_scale=15, pickable=True))
if track_sun:
    layers.append(pdk.Layer("PathLayer", pd.DataFrame(trails_sun),
                            get_path="path", get_color=[255,215,0,150],
                            width_scale=10, width_min_pixels=2))
if show_moon:
    layers.append(pdk.Layer("PathLayer", pd.DataFrame(trails_moon),
                            get_path="path", get_color=[100,100,100,150],
                            width_scale=10, width_min_pixels=2))
layers.append(pdk.Layer("ScatterplotLayer",
                        pd.DataFrame([{"lat":CENTER_LAT,"lon":CENTER_LON}]),
                        get_position=["lon","lat"], get_color=[255,0,0,200], get_radius=alert_width))
st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_style="light"),
                use_container_width=True)

# Collect and fire alerts
alerts = []
for tr in trails_sun:
    for (lon,lat), t in zip(tr["path"], tr["times"]):
        if hav(lat,lon,CENTER_LAT,CENTER_LON) <= alert_width:
            alerts.append((tr["callsign"], t))
            send_pushover("✈️ Shadow Alert", f"{tr['callsign']} in ~{t}s")
            break
if show_moon:
    for tr in trails_moon:
        for (lon,lat), t in zip(tr["path"], tr["times"]):
            if hav(lat,lon,CENTER_LAT,CENTER_LON) <= alert_width:
                alerts.append((tr["callsign"], t))
                send_pushover("🌑 Moon Shadow Alert", f"{tr['callsign']} in ~{t}s")
                break
for _, row in df_ac.iterrows():
    if row["mil"] and hav(row["lat"],row["lon"],CENTER_LAT,CENTER_LON) <= military_radius_km*1000:
        alerts.append((row["callsign"], 0))
        send_pushover("✈️ Military Alert", f"{row['callsign']} within {military_radius_km}km")
        break

# Onscreen & desktop notifications
if alerts and enable_onscreen:
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
    st.markdown(
        """
        <script>
        if (Notification.permission === 'granted') {
            new Notification("✈️ Shadow Alert",{body:"Aircraft shadow passing over target!"});
        } else {
            Notification.requestPermission().then(p=>{if(p==='granted') new Notification("✈️ Shadow Alert",{body:"Aircraft shadow passing over target!"});});
        }
        </script>
        """,
        unsafe_allow_html=True
    )
for cs, t in alerts:
    st.write(f"✈️ {cs} — in approx. {t} seconds")
if not alerts:
    st.success("✅ No forecast shadow paths intersect target area.")

# Update and display history
st.session_state.history.append({"time":now, "tracked":len(df_ac), "shadow_events":len(alerts)})
hist_df = pd.DataFrame(st.session_state.history).set_index("time")
st.subheader("📈 Tracked vs Shadow Events Over Time")
st.line_chart(hist_df)
