import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timezone, timedelta
# Auto-refresh every second
from streamlit_autorefresh import st_autorefresh
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except Exception:
    pass

# Pushover configuration
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title, message):
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        st.warning("Pushover credentials not set in environment.")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message}
        )
    except Exception as e:
        st.warning(f"Pushover notification failed: {e}")

# Defaults
CENTER_LAT = -33.7602563
CENTER_LON = 150.9717434
DEFAULT_RADIUS_KM = 10

# Sidebar
with st.sidebar:
    st.header("Map Options")
    data_source = st.selectbox("Data Source", ["OpenSky", "ADS-B Exchange"], index=0)
    radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM)
    track_sun = st.checkbox("Show Sun Shadows", True)
    # New: shadow alert width
    alert_width = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    test_alert = st.button("Test Alert")
    test_pushover = st.button("Test Pushover")

# Helpers
def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Current UTC time
selected_time = datetime.utcnow().replace(tzinfo=timezone.utc)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

# Fetch aircraft
aircraft_list = []
if data_source == "OpenSky":
    dr = radius_km / 111
    south, north = CENTER_LAT - dr, CENTER_LAT + dr
    dlon = dr / math.cos(math.radians(CENTER_LAT))
    west, east = CENTER_LON - dlon, CENTER_LON + dlon
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url); r.raise_for_status(); states = r.json().get("states", [])
    except:
        states = []
    for s in states:
        if len(s) < 11: continue
        cs = (s[1] or "").strip() or s[0]
        lat, lon = s[6], s[5]
        alt = s[13] or s[7] or 0.0
        aircraft_list.append({"lat": lat, "lon": lon, "alt": alt, "callsign": cs})
elif data_source == "ADS-B Exchange":
    api_key = os.getenv("RAPIDAPI_KEY")
    if api_key:
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        headers={"x-rapidapi-key":api_key,"x-rapidapi-host":"adsbexchange-com1.p.rapidapi.com"}
        try:
            r2 = requests.get(url, headers=headers); r2.raise_for_status(); adsb = r2.json().get("ac",[])
        except:
            adsb = []
        for ac in adsb:
            try: lat=float(ac.get("lat")); lon=float(ac.get("lon"))
            except: continue
            cs = ac.get("flight") or ac.get("hex") or ""
            alt = ac.get("alt_geo") or ac.get("alt_baro") or 0.0
            aircraft_list.append({"lat": lat, "lon": lon, "alt": alt, "callsign": cs.strip()})

# Build DataFrame
df_ac = pd.DataFrame(aircraft_list)
# Ensure altitude is numeric
if 'alt' in df_ac.columns:
    df_ac['alt'] = pd.to_numeric(df_ac['alt'], errors='coerce').fillna(0.0)
else:
    df_ac['alt'] = 0.0

# Compute shadow points using safe loop
shadows = []
if track_sun and not df_ac.empty:
    from pysolar.solar import get_altitude, get_azimuth
    for _, row in df_ac.iterrows():
        # Safely parse altitude
        try:
            alt_m = float(row['alt'])
        except Exception:
            continue
        if alt_m > 0:
            sun_alt = get_altitude(row['lat'], row['lon'], selected_time)
            sun_az = get_azimuth(row['lat'], row['lon'], selected_time)
            if sun_alt > 0:
                dist = alt_m / math.tan(math.radians(sun_alt))
                sh_lat = row['lat'] + (dist / 111111) * math.cos(math.radians(sun_az + 180))
                sh_lon = row['lon'] + (dist / (111111 * math.cos(math.radians(row['lat'])))) * math.sin(math.radians(sun_az + 180))
                shadows.append({"lat": sh_lat, "lon": sh_lon, "callsign": row['callsign']})
# Build shadow DataFrame
df_sh = pd.DataFrame(shadows)
df_sh = pd.DataFrame(shadows)
df_sh = pd.DataFrame(shadows)

# Build shadow path lines
paths = []
if track_sun and not df_ac.empty and not df_sh.empty:
    for (i, ac_row), (_, sh_row) in zip(df_ac.iterrows(), df_sh.iterrows()):
        paths.append({
            "path": [(ac_row['lon'], ac_row['lat']), (sh_row['lon'], sh_row['lat'])],
            "callsign": ac_row['callsign']
        })
    df_paths = pd.DataFrame(paths)

# Pydeck layers
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=10)
layers = []
# Aircraft layer represented by small blue dots
if not df_ac.empty:
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            df_ac,
            get_position=["lon", "lat"],
            get_color=[0, 128, 255, 200],
            get_radius=100,  # smaller dot for plane
            pickable=True
        )
    )
# Shadow scatter layer
if track_sun and not df_sh.empty:
    layers.append(
        pdk.Layer(
            "ScatterplotLayer", df_sh,
            get_position=["lon","lat"],
            get_color=[0,0,0,150],
            get_radius=200
        )
    )
# Shadow path lines
if track_sun and 'df_paths' in locals() and not df_paths.empty:
    layers.append(
        pdk.Layer(
            "PathLayer", df_paths,
            get_path="path",
            get_color=[0,0,0,100],
            width_scale=20,
            width_min_pixels=2,
            pickable=True
        )
    )
# Home marker
layers.append(
    pdk.Layer(
        "ScatterplotLayer", pd.DataFrame([{"lon":CENTER_LON,"lat":CENTER_LAT}]),
        get_position=["lon","lat"],
        get_color=[255,0,0,200],
        get_radius=400
    )
)

layers.append(
    pdk.Layer("ScatterplotLayer", pd.DataFrame([{"lon":CENTER_LON,"lat":CENTER_LAT}]), get_position=["lon","lat"], get_color=[255,0,0,200], get_radius=400)
)

deck=pdk.Deck(layers=layers, initial_view_state=view, map_style="light")
st.pydeck_chart(deck)

# Test alerts
if test_alert:
    st.success("Test alert triggered")
if test_pushover:
    st.info("Sending test Pushover")
