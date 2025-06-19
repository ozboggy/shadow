import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import folium
from folium.plugins import PolyLineTextPath
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
DEFAULT_SHADOW_WIDTH = 1.5
DEFAULT_ZOOM = 10

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
    index=0
)

zoom_level = st.sidebar.slider("Map Zoom", min_value=1, max_value=18, value=DEFAULT_ZOOM)
track_sun = st.sidebar.checkbox("Show Sun Shadows", value=True)
track_moon = st.sidebar.checkbox("Show Moon Shadows", value=False)
override_trails = st.sidebar.checkbox("Show Trails Regardless of Sun/Moon", value=False)

radius_km = st.sidebar.slider("Search Radius (km)", min_value=1, max_value=100, value=DEFAULT_RADIUS_KM)
forecast_interval = st.sidebar.slider("Forecast Interval (sec)", min_value=5, max_value=60, value=DEFAULT_INTERVAL_SEC, step=5)
forecast_duration = st.sidebar.slider("Forecast Duration (min)", min_value=1, max_value=60, value=DEFAULT_DURATION_MIN, step=1)
shadow_width = st.sidebar.slider("Shadow Width (px)", min_value=0.5, max_value=10.0, value=DEFAULT_SHADOW_WIDTH, step=0.5)
debug_mode = st.sidebar.checkbox("Debug raw response", value=False)
refresh_interval = st.sidebar.number_input("Auto-refresh Interval (sec)", min_value=0, max_value=300, value=0, step=10,
                                        help="0 = no auto-refresh; >0 to refresh")

# Pushover configuration
pushover_user_key = st.sidebar.text_input("Pushover User Key", os.getenv("PUSHOVER_USER_KEY", ""))
pushover_app_token = st.sidebar.text_input("Pushover App Token", os.getenv("PUSHOVER_APP_TOKEN", ""))
enable_pushover = st.sidebar.checkbox("Enable Pushover Alerts", value=False)
if st.sidebar.button("Send Test Push"):
    if pushover_user_key and pushover_app_token:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"user": pushover_user_key, "token": pushover_app_token,
                  "message": f"Test notification from Shadow Tracker at {datetime.utcnow().isoformat()}UTC"}
        )
        if resp.status_code == 200:
            st.sidebar.success("Test notification sent.")
        else:
            st.sidebar.error(f"Test failed: {resp.text}")
    else:
        st.sidebar.error("Provide both user key and app token.")
if st.sidebar.button("Send Alert Push"):
    if enable_pushover and pushover_user_key and pushover_app_token:
        # Use current aircraft count
        # placeholder, actual count set below
        st.session_state.send_alert = True
    else:
        st.sidebar.error("Enable pushover and set keys first.")

# Timestamp for calculation
selected_time = datetime.utcnow().replace(tzinfo=timezone.utc)

# Auto-refresh tag
if refresh_interval > 0:
    st.markdown(f'<meta http-equiv="refresh" content="{refresh_interval}">', unsafe_allow_html=True)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

# Utility functions
def move_position(lat: float, lon: float, heading: float, dist: float) -> tuple:
    R = 6371000
    try:
        hdr = math.radians(heading)
        lat1, lon1 = math.radians(lat), math.radians(lon)
    except:
        return lat, lon
    lat2 = math.asin(math.sin(lat1)*math.cos(dist/R) + math.cos(lat1)*math.sin(dist/R)*math.cos(hdr))
    lon2 = lon1 + math.atan2(math.sin(hdr)*math.sin(dist/R)*math.cos(lat1), math.cos(dist/R)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

def fetch_opensky(lat: float, lon: float, radius: float) -> list:
    dr = radius/111.0; south, north = lat-dr, lat+dr
    dlon = dr/math.cos(math.radians(lat)); west, east = lon-dlon, lon+dlon
    url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}"
    try:
        r = requests.get(url); r.raise_for_status()
        if debug_mode: st.write(r.text)
        states = r.json().get("states", [])
    except Exception as e:
        st.error(f"OpenSky error: {e}"); return []
    acs=[]
    for s in states:
        if len(s)<11: continue
        try:
            cs=s[1].strip() or s[0]; lat_f,lon_f=float(s[6]),float(s[5]); baro=float(s[7]or0)
            vel,hdg=float(s[9]),float(s[10])
        except:
            continue
        acs.append({"lat":lat_f,"lon":lon_f,"baro":baro,"vel":vel,"hdg":hdg,"callsign":cs})
    return acs

def fetch_adsb(lat: float, lon: float, radius: float) -> list:
    key=os.getenv("RAPIDAPI_KEY");
    if not key: st.error("Set RAPIDAPI_KEY"); return []
    url=f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{lat}/lon/{lon}/dist/{radius}/"
    h={"x-rapidapi-key":key,"x-rapidapi-host":"adsbexchange-com1.p.rapidapi.com"}
    try:
        r=requests.get(url,headers=h);r.raise_for_status()
        if debug_mode: st.write(r.text)
        ac_list=r.json().get("ac",[])
    except Exception as e:
        st.error(f"ADS-B error: {e}"); return []
    acs=[]
    for ac in ac_list:
        try:
            cs=(ac.get("flight")orac.get("hex")or"").strip();lat_f,lon_f=float(ac.get("lat")),float(ac.get("lon"))
            baro=float(ac.get("alt_baro")or0);vel=float(ac.get("gs")orac.get("spd")or0)
            hdg=float(ac.get("track")orac.get("trak")or0)
        except:
            continue
        acs.append({"lat":lat_f,"lon":lon_f,"baro":baro,"vel":vel,"hdg":hdg,"callsign":cs})
    return acs

def calculate_trail(lat,lon,baro,vel,hdg)->list:
    pts=[]
    for i in range(0,int(forecast_duration*60)+1,forecast_interval):
        ft=selected_time+timedelta(seconds=i)
        dist=vel*i;f_lat,f_lon=move_position(lat,lon,hdg,dist)
        sun_alt=get_sun_altitude(f_lat,f_lon,ft)
        if (track_sun and sun_alt>0) or (track_moon and sun_alt<=0) or override_trails:
            az=get_sun_azimuth(f_lat,f_lon,ft)
        else: continue
        angle=sun_alt if sun_alt>0 else1
        sd=baro/math.tan(math.radians(angle))
        sh_lat=f_lat+(sd/111111)*math.cos(math.radians(az+180))
        sh_lon=f_lon+(sd/(111111*math.cos(math.radians(f_lat))))*math.sin(math.radians(az+180))
        pts.append((sh_lat,sh_lon))
    return pts

# Map init
fmap=folium.Map(location=(TARGET_LAT,TARGET_LON),zoom_start=zoom_level,tiles=tile_style,control_scale=True)
folium.Marker((TARGET_LAT,TARGET_LON),icon=folium.Icon(color="red",icon="home",prefix="fa"),popup="Home").add_to(fmap)

# Data fetch
aircraft_list=fetch_opensky(TARGET_LAT,TARGET_LON,radius_km)if data_source=="OpenSky"else fetch_adsb(TARGET_LAT,TARGET_LON,radius_km)

# Pushover alert trigger
if 'send_alert' in st.session_state and st.session_state.send_alert:
    cnt=len(aircraft_list)
    msg=f"{cnt} aircraft in range: {', '.join([ac['callsign']for ac in aircraft_list])}"
    if enable_pushover and pushover_user_key and pushover_app_token:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"user":pushover_user_key,"token":pushover_app_token,"message":msg}
        )
        st.sidebar.success("Alert sent.")
    st.session_state.send_alert=False

# Sidebar aircraft list
st.sidebar.markdown("### Tracked Aircraft")
cnt=len(aircraft_list)
st.sidebar.write(f"{cnt} aircraft in range")
with st.sidebar.expander("Show details"):
    if cnt>0:
        for ac in aircraft_list:
            st.write(f"• {ac['callsign']} — Alt {ac['baro']} m, Spd {ac['vel']} m/s")
    else: st.sidebar.write("No aircraft in range.")

# Plot
for ac in aircraft_list:
    lat,lon,baro,vel,hdg,cs=ac.values()
    # Rotated plane icon
    folium.map.Marker((lat,lon),icon=DivIcon(icon_size=(20,20),icon_anchor=(10,10),
        html=f'<i class="fa fa-plane" style="color:blue;transform:rotate({hdg-90}deg);'
             f'transform-origin:center;font-size:20px"></i>'),popup=f"{cs}\nAlt:{baro}m\nSpd:{vel}m/s").add_to(fmap)
    # Label
    folium.map.Marker((lat,lon),icon=DivIcon(icon_size=(150,36),icon_anchor=(0,0),
        html=f'<div style="font-size:12px">{cs}</div>')).add_to(fmap)
    # Trail
    trail=calculate_trail(lat,lon,baro,vel,hdg)
    if trail:
        line=folium.PolyLine(locations=trail,color="black",weight=shadow_width,opacity=0.6)
        fmap.add_child(line)
        arrow=PolyLineTextPath(line,'▶',repeat=True,offset=10,attributes={'fill':'blue','font-weight':'bold','font-size':'6px'})
        fmap.add_child(arrow)

# Render
st_folium(fmap,width=900,height=600)
