import streamlit as st from dotenv import load_dotenv load_dotenv() import os import math import requests import pandas as pd import pydeck as pdk from datetime import datetime, timezone, timedelta from pysolar.solar import get_altitude, get_azimuth

Auto-refresh every second

from streamlit_autorefresh import st_autorefresh try: st_autorefresh(interval=1_000, key="datarefresh") except Exception: pass

Ephemeris for moon calculations

from skyfield.api import load, Topos _eph = load('de421.bsp') _ts = load.timescale() _earth = _eph['earth'] _moon = _eph['moon']

Pushover

PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY") PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title, message): if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN: st.warning("Pushover credentials not set.") return try: requests.post( "https://api.pushover.net/1/messages.json", data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message} ) except Exception as e: st.warning(f"Pushover failed: {e}")

Haversine

def hav(lat1, lon1, lat2, lon2): R = 6371000 dlat = math.radians(lat2 - lat1) dlon = math.radians(lon2 - lon1) a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2 return R * 2 * math.asin(math.sqrt(a))

Defaults

CENTER_LAT = -33.7602563 CENTER_LON = 150.9717434 DEFAULT_RADIUS_KM = 10 FORECAST_INTERVAL_SECONDS = 30 FORECAST_DURATION_MINUTES = 5

Sidebar

with st.sidebar: st.header("Map Options") data_source = st.selectbox("Data Source", ["OpenSky", "ADS-B Exchange"], index=0) radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM) track_sun = st.checkbox("Show Sun Shadows", True) alert_width = st.slider("Shadow Alert Width (m)", 0, 1000, 50) test_alert = st.button("Test Alert") test_pushover = st.button("Test Pushover")

Time

time_now = datetime.now(timezone.utc)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

Fetch

aircraft_list = [] if data_source == "OpenSky": dr = radius_km/111 south, north = CENTER_LAT-dr, CENTER_LAT+dr dlon = dr/math.cos(math.radians(CENTER_LAT)) west, east = CENTER_LON-dlon, CENTER_LON+dlon url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}" try: r = requests.get(url); r.raise_for_status(); states = r.json().get("states",[]) except: states = [] for s in states: if len(s)<11: continue cs = (s[1] or "").strip() or s[0] lat, lon = s[6], s[5] alt = s[13] or s[7] or 0.0 try: vel = float(s[9]) except: vel = 0.0 try: hdg = float(s[10]) except: hdg = 0.0 aircraft_list.append({"lat":lat,"lon":lon,"alt":float(alt),"vel":vel,"hdg":hdg,"callsign":cs}) elif data_source == "ADS-B Exchange": api_key=os.getenv("RAPIDAPI_KEY"); adsb=[] if api_key: url=f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/" headers={"x-rapidapi-key":api_key,"x-rapidapi-host":"adsbexchange-com1.p.rapidapi.com"} try: r2=requests.get(url,headers=headers); r2.raise_for_status(); adsb=r2.json().get("ac",[]) except: adsb=[] for ac in adsb: try: lat=float(ac.get("lat")); lon=float(ac.get("lon")) except: continue cs = (ac.get("flight") or ac.get("hex") or "").strip() alt_raw = ac.get("alt_geo") or ac.get("alt_baro") or 0.0 try: alt_val=float(alt_raw) except: alt_val=0.0 try: vel=float(ac.get("gs") or ac.get("spd") or 0) except: vel=0.0 try: hdg=float(ac.get("track") or ac.get("trak") or 0) except: hdg=0.0 aircraft_list.append({"lat":lat,"lon":lon,"alt":alt_val,"vel":vel,"hdg":hdg,"callsign":cs})

DataFrame

df_ac=pd.DataFrame(aircraft_list) if df_ac.empty: st.warning("No aircraft data.") else: df_ac[['alt','vel','hdg']]=df_ac[['alt','vel','hdg']].apply(pd.to_numeric,errors='coerce').fillna(0)

Forecast trails

trails=[] if track_sun and not df_ac.empty: for _, row in df_ac.iterrows(): cs=row['callsign']; path=[] lat0,lon0=row['lat'],row['lon'] for i in range(0,FORECAST_INTERVAL_SECONDSFORECAST_DURATION_MINUTES+1,FORECAST_INTERVAL_SECONDS): ft=time_now+timedelta(seconds=i) # move plane dist_m=row['vel']i dlat=dist_mmath.cos(math.radians(row['hdg']))/111111 dlon=dist_mmath.sin(math.radians(row['hdg']))/(111111*math.cos(math.radians(lat0))) lat_i=lat0+dlat; lon_i=lon0+dlon sun_alt=get_altitude(lat_i,lon_i,ft); sun_az=get_azimuth(lat_i,lon_i,ft) if sun_alt>0: shadow_dist=row['alt']/math.tan(math.radians(sun_alt)) sh_lat=lat_i+(shadow_dist/111111)math.cos(math.radians(sun_az+180)) sh_lon=lon_i+(shadow_dist/(111111math.cos(math.radians(lat_i))))*math.sin(math.radians(sun_az+180)) path.append([sh_lon,sh_lat]) if path: trails.append({'path':path,'callsign':cs})

Build map

view=pdk.ViewState(latitude=CENTER_LAT,longitude=CENTER_LON,zoom=DEFAULT_RADIUS_KM) layers=[] if not df_ac.empty: layers.append(pdk.Layer("ScatterplotLayer",df_ac,get_position=["lon","lat"],get_color=[0,128,255,200],get_radius=100,pickable=True)) if track_sun and trails: df_trails=pd.DataFrame(trails) layers.append(pdk.Layer("PathLayer",df_trails,get_path="path",get_color=[0,0,0,150],width_scale=10,width_min_pixels=2,pickable=False))

home

layers.append(pdk.Layer("ScatterplotLayer",pd.DataFrame([{"lat":CENTER_LAT,"lon":CENTER_LON}]),get_position=["lon","lat"],get_color=[255,0,0,200],get_radius=400))

render

deck=pdk.Deck(layers=layers,initial_view_state=view,map_style="light") st.pydeck_chart(deck)

Alerts

if track_sun and trails: for tr in trails: for lon,lat in tr['path']: if hav(lat,lon,CENTER_LAT,CENTER_LON)<=alert_width: st.error(f"🚨 Shadow of {tr['callsign']} over home!") send_pushover("✈️ Shadow Alert",f"{tr['callsign']} shadow at home") break

test

if test_alert: st.success("Test alert triggered") if test_pushover: st.info("Sending test Pushover")

