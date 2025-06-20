import streamlit as st 
from dotenv 
import load_dotenv load_dotenv() 
import os import math import requests import pandas as pd 
import pydeck as pdk 
from datetime 
import datetime, timezone, timedelta 
from pysolar.solar 
import get_altitude, get_azimuth 
from skyfield.api 
import load,

Topos(latitude_degrees=lat0, longitude_degrees=lon0) ts_t = ts.utc(ft.year, ft.month, ft.day, ft.hour, ft.minute, ft.second) ast = t.at(ts_t).observe(moon).apparent() alt_moon, az_moon, _ = ast.altaz() if alt_moon.degrees > 0: m_dist = row['alt'] / math.tan(math.radians(alt_moon.degrees)) mlat = lat0 + (m_dist/111111) * math.cos(math.radians(az_moon.degrees+180)) mlon = lon0 + (m_dist/(111111 * math.cos(math.radians(lat0)))) * math.sin(math.radians(az_moon.degrees+180)) moon_path.append([mlon, mlat]) if moon_path: moon_trails.append({'path': moon_path, 'callsign': cs})

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

