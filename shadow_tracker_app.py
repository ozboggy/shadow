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
DEFAULT_TARGET_LAT = -33.7602563
DEFAULT_TARGET_LON = 150.9717434
DEFAULT_RADIUS_KM = 20
FORECAST_INTERVAL_SECONDS = 30
FORECAST_DURATION_MINUTES = 5
DEFAULT_SHADOW_WIDTH = 3

# Sidebar controls
tile_style = st.sidebar.selectbox(
    "Map Tile Style", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter", "Stamen Terrain", "Stamen Toner"],
    index=1
)
data_source = st.sidebar.selectbox(
    "Data Source", ["OpenSky", "ADS-B Exchange"], index=0
)
track_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", value=False)
override_trails = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", value=False)

# Time selection
t_sel_date = st.sidebar.date_input("Date (UTC)", value=datetime.utcnow().date())
t_sel_time = st.sidebar.time_input("Time (UTC)", value=dt_time(datetime.utcnow().hour, datetime.utcnow().minute))
selected_time = datetime.combine(t_sel_date, t_sel_time).replace(tzinfo=timezone.utc)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

# Create map
center = (DEFAULT_TARGET_LAT, DEFAULT_TARGET_LON)
fmap = folium.Map(location=center, zoom_start=8, tiles=tile_style, control_scale=True)
# Home
folium.Marker(
    location=center,
    icon=folium.Icon(color="red", icon="home", prefix="fa"),
    popup="Home"
).add_to(fmap)

# Utilities
def move_position(lat, lon, heading, dist):
    R = 6371000
    hdr = math.radians(heading)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(math.sin(lat1)*math.cos(dist/R) + math.cos(lat1)*math.sin(dist/R)*math.cos(hdr))
    lon2 = lon1 + math.atan2(math.sin(hdr)*math.sin(dist/R)*math.cos(lat1), math.cos(dist/R) - math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

def hav(lat1, lon1, lat2, lon2):
    R=6371000
    dlat=math.radians(lat2-lat1)
    dlon=math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

# Fetch flights
aircraft_list = []
if data_source == "OpenSky":
    # bounding box
    dr = DEFAULT_RADIUS_KM/111.0
    south = DEFAULT_TARGET_LAT - dr
    north = DEFAULT_TARGET_LAT + dr
    dlon = dr/math.cos(math.radians(DEFAULT_TARGET_LAT))
    west = DEFAULT_TARGET_LON - dlon
    east = DEFAULT_TARGET_LON + dlon
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url)
        r.raise_for_status()
        data = r.json().get("states", [])
    except Exception as e:
        st.error(f"OpenSky error: {e}")
        data = []
    for s in data:
        # Parse OpenSky state vector
        if len(s) < 11:
            continue
        icao = s[0]
        callsign = s[1].strip() if s[1] else icao
        lon = s[5]
        lat = s[6]
        baro = s[7] or 0
        vel = s[9]
        hdg = s[10]
        if None in (lat, lon, vel, hdg):
            continue
        aircraft_list.append({"lat": lat, "lon": lon, "baro": baro, "vel": vel, "hdg": hdg, "callsign": callsign})
elif data_source == "ADS-B Exchange":
    # Fetch from ADS-B Exchange via RapidAPI
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        st.error("Set RAPIDAPI_KEY in .env for ADS-B Exchange")
        j = []
    else:
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{DEFAULT_TARGET_LAT}/lon/{DEFAULT_TARGET_LON}/dist/{DEFAULT_RADIUS_KM}/"
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
        try:
            r2 = requests.get(url, headers=headers)
            r2.raise_for_status()
            j = r2.json().get("ac", [])
        except Exception as e:
            st.error(f"ADS-B Exchange error: {e}")
            j = []
    for ac in j:
        lat = ac.get("lat")
        lon = ac.get("lon")
        vel = ac.get("spd")
        hdg = ac.get("trak")
        baro = ac.get("alt_baro") if isinstance(ac.get("alt_baro"),(int,float)) else 0
        cs = ac.get("flight") or ac.get("hex")
        if None in (lat, lon, vel, hdg):
            continue
        callsign = cs.strip() if isinstance(cs, str) else cs
        aircraft_list.append({"lat": lat, "lon": lon, "baro": baro, "vel": vel, "hdg": hdg, "callsign": callsign})

# Plot
for ac in aircraft_list:
    lat, lon, baro, vel, hdg, cs = ac["lat"], ac["lon"], ac["baro"], ac["vel"], ac["hdg"], ac["callsign"]
    # marker
    folium.Marker(
        location=(lat, lon),
        icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
        popup=f"{cs}\nAlt: {baro} m\nSpd: {vel} m/s"
    ).add_to(fmap)
    # shadows
    if track_sun or track_moon or override_trails:
        trail=[]
        for i in range(0, FORECAST_DURATION_MINUTES*60+1, FORECAST_INTERVAL_SECONDS):
            ft=selected_time+timedelta(seconds=i)
            dist=vel*i
            f_lat,f_lon=move_position(lat,lon,hdg,dist)
            sun_alt=get_sun_altitude(f_lat,f_lon,ft)
            if track_sun and sun_alt>0:
                az=get_sun_azimuth(f_lat,f_lon,ft)
            elif track_moon and sun_alt<=0:
                az=get_sun_azimuth(f_lat,f_lon,ft)
            elif override_trails:
                az=get_sun_azimuth(f_lat,f_lon,ft)
            else:
                continue
            sd=baro/math.tan(math.radians(sun_alt if sun_alt>0 else 1))
            sh_lat=f_lat+(sd/111111)*math.cos(math.radians(az+180))
            sh_lon=f_lon+(sd/(111111*math.cos(math.radians(f_lat))))*math.sin(math.radians(az+180))
            trail.append((sh_lat,sh_lon))
        if trail:
            folium.PolyLine(locations=trail, color="black", weight=DEFAULT_SHADOW_WIDTH, opacity=0.6).add_to(fmap)

# Display
st_folium(fmap, width=1200, height=800)
