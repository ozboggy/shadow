import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import folium
from streamlit_folium import st_folium
from datetime import datetime, time as dt_time, timezone, timedelta
import math
import requests
from pysolar.solar import get_altitude as get_sun_altitude, get_azimuth as get_sun_azimuth

# Constants
DEFAULT_RADIUS_KM = 20
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
DEFAULT_SHADOW_WIDTH = 3

# Sidebar controls
tile_style = st.sidebar.selectbox(
    "Map Tile Style",
    ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter", "Stamen Terrain", "Stamen Toner"],
    index=1
)
data_source = st.sidebar.selectbox(
    "Data Source",
    ["OpenSky", "ADS-B Exchange"],
    index=0
)
track_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", value=False)
override_trails = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", value=False)

# Time selection
sel_date = st.sidebar.date_input("Date (UTC)", datetime.utcnow().date())
sel_time = st.sidebar.time_input("Time (UTC)", dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(sel_date, sel_time).replace(tzinfo=timezone.utc)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

# Initialize map
center = (-33.7554186, 150.9656457)
fmap = folium.Map(location=center, zoom_start=10, tiles=tile_style, control_scale=True)
# Home marker
folium.Marker(
    location=center,
    icon=folium.Icon(color="red", icon="home", prefix="fa"),
    popup="Home"
).add_to(fmap)

# Utils

def move_position(lat, lon, heading, dist):
    R = 6371000
    try:
        hdr = math.radians(float(heading))
    except:
        hdr = 0.0
    try:
        lat1 = math.radians(float(lat)); lon1 = math.radians(float(lon))
    except:
        return lat, lon
    lat2 = math.asin(math.sin(lat1)*math.cos(dist/R) + math.cos(lat1)*math.sin(dist/R)*math.cos(hdr))
    lon2 = lon1 + math.atan2(math.sin(hdr)*math.sin(dist/R)*math.cos(lat1), math.cos(dist/R)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Fetch aircraft
aircraft_list = []

if data_source == "OpenSky":
    dr = DEFAULT_RADIUS_KM / 111.0
    south = target_lat - dr; north = target_lat + dr
    dlon = dr / math.cos(math.radians(target_lat))
    west = target_lon - dlon; east = target_lon + dlon
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url); r.raise_for_status()
        states = r.json().get("states", [])
    except Exception as e:
        st.error(f"OpenSky error: {e}")
        states = []
    for s in states:
        if len(s) < 11: continue
        try:
            icao = s[0]; cs = s[1].strip() if s[1] else icao
            lon = float(s[5]); lat = float(s[6])
            baro = float(s[7]) if s[7] is not None else 0.0
            vel = float(s[9]); hdg = float(s[10])
        except:
            continue
        aircraft_list.append({"lat": lat, "lon": lon, "baro": baro, "vel": vel, "hdg": hdg, "callsign": cs})

elif data_source == "ADS-B Exchange":
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        st.error("Set RAPIDAPI_KEY in .env for ADS-B Exchange")
        adsb = []
    else:
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{target_lat}/lon/{target_lon}/dist/{DEFAULT_RADIUS_KM}/"
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
        try:
            r2 = requests.get(url, headers=headers); r2.raise_for_status()
            adsb = r2.json().get("ac", [])
        except Exception as e:
            st.error(f"ADS-B Exchange error: {e}")
            adsb = []
    for ac in adsb:
        try:
            lat = float(ac.get("lat")); lon = float(ac.get("lon"))
            # Speed: try 'gs' then 'spd'
            vel_raw = ac.get("gs") if ac.get("gs") is not None else ac.get("spd")
            vel = float(vel_raw)
            # Heading: try 'track' then 'trak'
            hdg_raw = ac.get("track") if ac.get("track") is not None else ac.get("trak")
            hdg = float(hdg_raw)
            raw = ac.get("alt_baro")
            baro = float(raw) if isinstance(raw, (int, float, str)) and str(raw).replace('.', '', 1).isdigit() else 0.0
            cs = ac.get("flight") or ac.get("hex")
        except Exception:
            continue
        callsign = cs.strip() if isinstance(cs, str) else cs
        aircraft_list.append({"lat": lat, "lon": lon, "baro": baro, "vel": vel, "hdg": hdg, "callsign": callsign})

# Plot aircraft and shadows
for ac in aircraft_list:
    lat = ac["lat"]; lon = ac["lon"]; baro = ac["baro"]
    vel = ac["vel"]; hdg = ac["hdg"]; cs = ac["callsign"]
    folium.Marker(
        location=(lat, lon),
        icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
        popup=f"{cs}\nAlt: {baro} m\nSpd: {vel} m/s"
    ).add_to(fmap)
    if track_sun or track_moon or override_trails:
        trail = []
        for i in range(0, FORECAST_DURATION_MINUTES*60+1, FORECAST_INTERVAL_SECONDS):
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
            sd = baro / math.tan(math.radians(sun_alt if sun_alt>0 else 1))
            sh_lat = f_lat + (sd/111111)*math.cos(math.radians(az+180))
            sh_lon = f_lon + (sd/(111111*math.cos(math.radians(f_lat))))*math.sin(math.radians(az+180))
            trail.append((sh_lat, sh_lon))
        if trail:
            folium.PolyLine(locations=trail, color="black", weight=DEFAULT_SHADOW_WIDTH, opacity=0.6).add_to(fmap)

# Render map
st_folium(fmap, width=1200, height=800)
