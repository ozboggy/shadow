import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import requests
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth
from folium.features import DivIcon

# Constants
TARGET_LAT = -33.7571158
TARGET_LON = 150.9779155
DEFAULT_RADIUS_KM = 20
DEFAULT_INTERVAL_SEC = 30
DEFAULT_DURATION_MIN = 5
DEFAULT_SHADOW_WIDTH = 3

# Sidebar controls
st.sidebar.header("Configuration")

data_source = st.sidebar.selectbox(
    "Data Source",
    ["OpenSky", "ADS-B Exchange"],
    index=0
)

tile_style = st.sidebar.selectbox(
    "Map Tile Style",
    ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter", "Stamen Terrain", "Stamen Toner"],
    index=1
)

track_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", value=False)
override_trails = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", value=False)

radius_km = st.sidebar.slider("Search Radius (km)", min_value=1, max_value=100, value=DEFAULT_RADIUS_KM)
forecast_interval = st.sidebar.slider("Forecast Interval (sec)", min_value=5, max_value=60, value=DEFAULT_INTERVAL_SEC, step=5)
forecast_duration = st.sidebar.slider("Forecast Duration (min)", min_value=1, max_value=60, value=DEFAULT_DURATION_MIN, step=1)
shadow_width = st.sidebar.slider("Shadow Width (px)", min_value=1, max_value=10, value=DEFAULT_SHADOW_WIDTH)
debug_mode = st.sidebar.checkbox("Debug raw response", value=False)
refresh_interval = st.sidebar.number_input("Auto-refresh Interval (sec)", min_value=0, max_value=300, value=0, step=10,
                                        help="0 = no auto-refresh; >0 to refresh")

# Time selection fixed to current UTC
today = datetime.utcnow().replace(tzinfo=timezone.utc)
selected_time = today

# Auto-refresh via HTML meta
if refresh_interval > 0:
    st.markdown(f'<meta http-equiv="refresh" content="{refresh_interval}">', unsafe_allow_html=True)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")


def move_position(lat: float, lon: float, heading: float, dist: float) -> tuple:
    """
    Move a point from (lat, lon) by distance `dist` (meters) along bearing `heading` (degrees).
    Returns new (latitude, longitude).
    """
    R = 6371000  # Earth radius in meters
    try:
        hdr = math.radians(float(heading))
        lat1 = math.radians(float(lat)); lon1 = math.radians(float(lon))
    except (ValueError, TypeError):
        return lat, lon
    lat2 = math.asin(math.sin(lat1)*math.cos(dist/R) + math.cos(lat1)*math.sin(dist/R)*math.cos(hdr))
    lon2 = lon1 + math.atan2(
        math.sin(hdr)*math.sin(dist/R)*math.cos(lat1),
        math.cos(dist/R) - math.sin(lat1)*math.sin(lat2)
    )
    return math.degrees(lat2), math.degrees(lon2)


def fetch_opensky(lat: float, lon: float, radius: float) -> list:
    """
    Fetch aircraft from OpenSky Network within `radius` km of (lat, lon).
    """
    dr = radius / 111.0
    south = lat - dr; north = lat + dr
    dlon = dr / math.cos(math.radians(lat))
    west = lon - dlon; east = lon + dlon
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url)
        r.raise_for_status()
        if debug_mode:
            st.write("OpenSky raw response:", r.text)
        states = r.json().get("states", [])
    except Exception as e:
        st.error(f"OpenSky error: {e}")
        return []

    aircraft = []
    for s in states:
        if len(s) < 11:
            continue
        try:
            icao = s[0]; cs = s[1].strip() or icao
            lon_f, lat_f = float(s[5]), float(s[6])
            baro = float(s[7]) if s[7] is not None else 0.0
            vel, hdg = float(s[9]), float(s[10])
        except (ValueError, TypeError):
            continue
        aircraft.append({"lat": lat_f, "lon": lon_f, "baro": baro, "vel": vel, "hdg": hdg, "callsign": cs})
    return aircraft


def fetch_adsb(lat: float, lon: float, radius: float) -> list:
    """
    Fetch aircraft from ADS-B Exchange via RapidAPI within `radius` km of (lat, lon).
    """
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        st.error("Set RAPIDAPI_KEY in .env for ADS-B Exchange")
        return []

    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{lat}/lon/{lon}/dist/{radius}/"
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        if debug_mode:
            st.write("ADS-B raw response:", r.text)
        ac_list = r.json().get("ac", [])
    except Exception as e:
        st.error(f"ADS-B Exchange error: {e}")
        return []

    aircraft = []
    for ac in ac_list:
        try:
            lat_f = float(ac.get("lat")); lon_f = float(ac.get("lon"))
            vel = float(ac.get("gs") or ac.get("spd") or 0)
            hdg = float(ac.get("track") or ac.get("trak") or 0)
            baro = float(ac.get("alt_baro") or 0)
            cs = (ac.get("flight") or ac.get("hex") or "").strip()
        except (ValueError, TypeError):
            continue
        aircraft.append({"lat": lat_f, "lon": lon_f, "baro": baro, "vel": vel, "hdg": hdg, "callsign": cs})
    return aircraft


def calculate_trail(lat: float, lon: float, baro: float, vel: float, hdg: float) -> list:
    """
    Calculate a shadow-trail polyline of points for a single aircraft.
    """
    points = []
    for i in range(0, int(forecast_duration*60) + 1, forecast_interval):
        ft = selected_time + timedelta(seconds=i)
        dist = vel * i
        f_lat, f_lon = move_position(lat, lon, hdg, dist)
        sun_alt = get_sun_altitude(f_lat, f_lon, ft)
        if track_sun and sun_alt > 0:
            az = get_sun_azimuth(f_lat, f_lon, ft)
        elif track_moon and sun_alt <= 0:
            az = get_sun_azimuth(f_lat, f_lon, ft)
        elif override_trails:
            az = get_sun_azimuth(f_lat, f_lon, ft)
        else:
            continue

        # avoid zero or negative altitude
        angle = sun_alt if sun_alt > 0 else 1
        sd = baro / math.tan(math.radians(angle))
        sh_lat = f_lat + (sd/111111)*math.cos(math.radians(az+180))
        sh_lon = f_lon + (sd/(111111*math.cos(math.radians(f_lat))))*math.sin(math.radians(az+180))
        points.append((sh_lat, sh_lon))
    return points

# Initialize map centered at constant target
fmap = folium.Map(location=(TARGET_LAT, TARGET_LON), zoom_start=11, tiles=tile_style, control_scale=True)
# Home marker
folium.Marker(
    location=(TARGET_LAT, TARGET_LON),
    icon=folium.Icon(color="red", icon="home", prefix="fa"),
    popup="Home"
).add_to(fmap)

# Fetch and plot aircraft
if data_source == "OpenSky":
    aircraft_list = fetch_opensky(TARGET_LAT, TARGET_LON, radius_km)
else:
    aircraft_list = fetch_adsb(TARGET_LAT, TARGET_LON, radius_km)

# Indicate tracked aircraft in sidebar
st.sidebar.markdown("### Tracked Aircraft")
if aircraft_list:
    for ac in aircraft_list:
        st.sidebar.write(f"• {ac['callsign']} — Alt {ac['baro']} m, Spd {ac['vel']} m/s")
else:
    st.sidebar.write("No aircraft in range.")

for ac in aircraft_list:
    lat = ac["lat"]; lon = ac["lon"]; baro = ac["baro"]
    vel = ac["vel"]; hdg = ac["hdg"]; cs = ac["callsign"]

    # Aircraft icon
    folium.Marker(
        location=(lat, lon),
        icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
        popup=f"{cs}\nAlt: {baro} m\nSpd: {vel} m/s"
    ).add_to(fmap)
    # Permanent label
    folium.map.Marker(
        location=(lat, lon),
        icon=DivIcon(
            icon_size=(150,36), icon_anchor=(0,0),
            html=f'<div style="font-size:12px; color:black">{cs}</div>'
        )
    ).add_to(fmap)

    # Shadow trail
    trail_pts = calculate_trail(lat, lon, baro, vel, hdg)
    if trail_pts:
        folium.PolyLine(locations=trail_pts, color="black", weight=shadow_width, opacity=0.6).add_to(fmap)

# Render map
st_folium(fmap, width=900, height=600)
