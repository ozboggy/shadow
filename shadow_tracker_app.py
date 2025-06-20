import streamlit as st from dotenv import load_dotenv load_dotenv() import os import math import requests import pandas as pd import pydeck as pdk from datetime import datetime, timezone, timedelta from pysolar.solar import get_altitude, get_azimuth from skyfield.api import load, Topos

Auto-refresh helper

from streamlit_autorefresh import st_autorefresh

Load ephemeris for moon calculations

eph = load('de421.bsp') ts = load.timescale() earth = eph['earth'] moon = eph['moon']

Auto-refresh every second

try: st_autorefresh(interval=1_000, key="datarefresh") except Exception: pass

Pushover configuration

PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY") PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

def send_pushover(title, message): if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN: st.warning("Pushover credentials not set.") return try: requests.post( "https://api.pushover.net/1/messages.json", data={"token": PUSHOVER_API_TOKEN, "user": PUSHOVER_USER_KEY, "title": title, "message": message} ) except Exception as e: st.warning(f"Pushover failed: {e}")

Haversine helper

def hav(lat1, lon1, lat2, lon2): R = 6371000 dlat = math.radians(lat2 - lat1) dlon = math.radians(lon2 - lon1) a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2 return R * 2 * math.asin(math.sqrt(a))

Constants

CENTER_LAT = -33.7602563 CENTER_LON = 150.9717434 DEFAULT_RADIUS_KM = 10 FORECAST_INTERVAL_SECONDS = 30 FORECAST_DURATION_MINUTES = 5

Sidebar controls

with st.sidebar: st.header("Map Options") data_source = st.selectbox("Data Source", ["OpenSky", "ADS-B Exchange"], index=0) radius_km = st.slider("Search Radius (km)", 1, 100, DEFAULT_RADIUS_KM) track_sun = st.checkbox("Show Sun Shadows", True) track_moon = st.checkbox("Show Moon Shadows", False) alert_width = st.slider("Shadow Alert Width (m)", 0, 1000, 50) test_alert = st.button("Test Alert") test_pushover = st.button("Test Pushover")

Current time

now = datetime.now(timezone.utc)

st.title(f"✈️ Aircraft Shadow Tracker ({data_source})")

Fetch aircraft data

aircraft_list = [] if data_source == "OpenSky": dr = radius_km / 111.0 south, north = CENTER_LAT - dr, CENTER_LAT + dr dlon = dr / math.cos(math.radians(CENTER_LAT)) west, east = CENTER_LON - dlon, CENTER_LON + dlon url = f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}" try: r = requests.get(url); r.raise_for_status() states = r.json().get("states", []) except: states = [] for s in states: if len(s) < 11: continue cs = (s[1] or "").strip() or s[0] lat, lon = s[6], s[5] alt = s[13] or s[7] or 0.0 vel = float(s[9] or 0.0) hdg = float(s[10] or 0.0) aircraft_list.append({"lat": lat, "lon": lon, "alt": alt, "vel": vel, "hdg": hdg, "callsign": cs}) elif data_source == "ADS-B Exchange": api_key = os.getenv("RAPIDAPI_KEY") adsb = [] if api_key: url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_lon}/dist/{radius_km}/" headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"} try: r2 = requests.get(url, headers=headers); r2.raise_for_status() adsb = r2.json().get("ac", []) except: adsb = [] for ac in adsb: try: lat = float(ac.get("lat")); lon = float(ac.get("lon")) except: continue cs = (ac.get("flight") or ac.get("hex") or "").strip() try: alt = float(ac.get("alt_geo") or ac.get("alt_baro") or 0.0) except: alt = 0.0 vel = float(ac.get("gs") or ac.get("spd") or 0.0) hdg = float(ac.get("track") or ac.get("trak") or 0.0) aircraft_list.append({"lat": lat, "lon": lon, "alt": alt, "vel": vel, "hdg": hdg, "callsign": cs})

Build DataFrame

df_ac = pd.DataFrame(aircraft_list) if not df_ac.empty: df_ac[['alt','vel','hdg']] = df_ac[['alt','vel','hdg']].apply(pd.to_numeric, errors='coerce').fillna(0) else: st.warning("No aircraft data available.")

Forecast trails

sun_trails = [] moon_trails = [] if not df_ac.empty: for _, row in df_ac.iterrows(): cs = row['callsign'] # Sun trail if track_sun: path = [] lat0, lon0 = row['lat'], row['lon'] for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS): ft = now + timedelta(seconds=i) dist = row['vel'] * i dlat = dist * math.cos(math.radians(row['hdg'])) / 111111 dlon = dist * math.sin(math.radians(row['hdg'])) / (111111 * math.cos(math.radians(lat0))) lat_i = lat0 + dlat lon_i = lon0 + dlon sun_alt = get_altitude(lat_i, lon_i, ft) sun_az = get_azimuth(lat_i, lon_i, ft) if sun_alt > 0: shadow_dist = row['alt'] / math.tan(math.radians(sun_alt)) sh_lat = lat_i + (shadow_dist/111111) * math.cos(math.radians(sun_az+180)) sh_lon = lon_i + (shadow_dist/(111111 * math.cos(math.radians(lat_i)))) * math.sin(math.radians(sun_az+180)) path.append([sh_lon, sh_lat]) if path: sun_trails.append({'path': path, 'callsign': cs}) # Moon trail if track_moon: moon_path = [] lat0, lon0 = row['lat'], row['lon'] for i in range(0, FORECAST_INTERVAL_SECONDS * FORECAST_DURATION_MINUTES + 1, FORECAST_INTERVAL_SECONDS): ft = now + timedelta(seconds=i) t = earth + Topos(latitude_degrees=lat0, longitude_degrees=lon0) ts_t = ts.utc(ft.year, ft.month, ft.day, ft.hour, ft.minute, ft.second) ast = t.at(ts_t).observe(moon).apparent() alt_moon, az_moon, _ = ast.altaz() if alt_moon.degrees > 0: m_dist = row['alt'] / math.tan(math.radians(alt_moon.degrees)) mlat = lat0 + (m_dist/111111) * math.cos(math.radians(az_moon.degrees+180)) mlon = lon0 + (m_dist/(111111 * math.cos(math.radians(lat0)))) * math.sin(math.radians(az_moon.degrees+180)) moon_path.append([mlon, mlat]) if moon_path: moon_trails.append({'path': moon_path, 'callsign': cs})

Build map layers

view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM) layers = [] if not df_ac.empty: layers.append(pdk.Layer( "ScatterplotLayer", df_ac, get_position=["lon","lat"], get_color=[0,128,255,200], get_radius=100, pickable=True ))

Sun shadows

if track_sun and sun_trails: df_sun = pd.DataFrame(sun_trails) layers.append(pdk.Layer( "PathLayer", df_sun, get_path="path", get_color=[255,165,0,200], width_scale=10, width_min_pixels=2 ))

Moon shadows

if track_moon and moon_trails: df_moon = pd.DataFrame(moon_trails) layers.append(pdk.Layer( "PathLayer", df_moon, get_path="path", get_color=[192,192,192,200], width_scale=10, width_min_pixels=2 ))

Home marker

layers.append(pdk.Layer( "ScatterplotLayer", pd.DataFrame([{"lon":CENTER_LON,"lat":CENTER_LAT,"callsign":"Home"}]), get_position=["lon","lat"], get_color=[255,0,0,200], get_radius=300, pickable=False ))

deck = pdk.Deck( layers=layers, initial_view_state=view, map_style="light", tooltip={"text":"{callsign}"} ) st.pydeck_chart(deck, use_container_width=True)

Alerts

if track_sun and sun_trails: for tr in sun_trails: for lon, lat in tr['path']: if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width: st.error(f"🚨 Sun shadow of {tr['callsign']} over home!") send_pushover("✈️ Shadow Alert", f"{tr['callsign']} sun shadow at home") break if track_moon and moon_trails: for tr in moon_trails: for lon, lat in tr['path']: if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width: st.error(f"🚨 Moon shadow of {tr['callsign']} over home!") send_pushover("🌙 Shadow Alert", f"{tr['callsign']} moon shadow at home") break

Test buttons

if test_alert: st.success("Test alert triggered") if test_pushover: st.info("Sending test Pushover notification...")

