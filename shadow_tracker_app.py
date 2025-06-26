import time
import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import json
import requests
import pandas as pd
import plotly.express as px
import pydeck as pdk
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth

# Optional moon computations
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh every second
AUTOREFRESH_MS = 1000
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=AUTOREFRESH_MS, key="datarefresh")
except ImportError:
    pass

# Paths & credentials
log_path = os.getenv("LOG_PATH", "alert_log.csv")
home_config = os.getenv("HOME_CONFIG", "home_location.json")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

# Load or set default home location
def load_home():
    default = {'lat': -33.8544014, 'lon': 151.2087668}
    if os.path.exists(home_config):
        try:
            cfg = json.load(open(home_config))
            return cfg.get('lat', default['lat']), cfg.get('lon', default['lon'])
        except:
            return default['lat'], default['lon']
    return default['lat'], default['lon']

CENTER_LAT, CENTER_LON = load_home()

# Ensure the alert log exists
if not os.path.exists(log_path):
    pd.DataFrame(columns=[
        "Time UTC", "Callsign", "Lat", "Lon", "Time Until Alert (sec)", "Distance (mi)"
    ]).to_csv(log_path, index=False)

# Haversine
def hav(lat1, lon1, lat2, lon2):
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

def log_alert(callsign, lat, lon, time_until, distance_mi):
    try:
        df = pd.read_csv(log_path)
    except:
        df = pd.DataFrame(columns=[
            "Time UTC","Callsign","Lat","Lon","Time Until Alert (sec)","Distance (mi)"
        ])
    new = pd.DataFrame([{
        "Time UTC": datetime.now(timezone.utc).isoformat(),
        "Callsign": callsign,
        "Lat": lat,
        "Lon": lon,
        "Time Until Alert (sec)": time_until,
        "Distance (mi)": distance_mi
    }])
    pd.concat([df,new], ignore_index=True).to_csv(log_path, index=False)

# Fixed radius & forecast settings
DEFAULT_RADIUS_MI = 10
radius_km = DEFAULT_RADIUS_MI * 1.60934
FORECAST_INTERVAL_S = 1
FORECAST_DURATION_S = 60

# Sidebar: only home, on-screen toggles, fixed radius
with st.sidebar:
    st.header("Home & Map Options")
    st.subheader("Home Location")
    st.markdown(f"**Current:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
    new_lat = st.number_input("New Home Latitude", value=CENTER_LAT, format="%.6f")
    new_lon = st.number_input("New Home Longitude", value=CENTER_LON, format="%.6f")
    if st.button("Save Home Location"):
        with open(home_config,"w") as f:
            json.dump({"lat":new_lat,"lon":new_lon}, f)
        st.success(f"Home updated to {new_lat:.6f}, {new_lon:.6f}")
        st.experimental_rerun()

    st.markdown("---")
    on_screen_alerts = st.checkbox("Enable On-Screen Alerts", value=True)
    st.markdown(f"**Search Radius:** {DEFAULT_RADIUS_MI} mi")
    track_sun = st.checkbox("Show Sun Shadows", value=True)
    track_moon = st.checkbox("Show Moon Shadows", value=False)
    alert_width = st.slider("Shadow Alert Width (m)", 10, 1000, 50)
    test_alert = st.button("Test Alert")

    st.markdown("---")
    if os.path.exists(log_path):
        st.download_button("Download alert_log.csv", open(log_path,"rb"),
                           "alert_log.csv","text/csv")
    else:
        st.info("No alert log yet")

now_utc = datetime.now(timezone.utc)

# Sun & Moon altitudes
sun_alt = get_altitude(CENTER_LAT,CENTER_LON,now_utc)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now_utc
    moon_alt = math.degrees(ephem.Moon(obs).alt)

# Fetch ADS-B data
aircraft_list = []
if RAPIDAPI_KEY:
    url = (
        f"https://adsbexchange-com1.p.rapidapi.com/v2/"
        f"lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    )
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
    }
    try:
        resp = requests.get(url,headers=headers); resp.raise_for_status()
        data = resp.json().get("ac",[])
    except:
        st.warning("Failed to fetch ADS-B data."); data=[]
else:
    data=[]

for ac in data:
    try:
        lat,lon = float(ac.get('lat')), float(ac.get('lon'))
    except:
        continue
    cs = (ac.get('flight') or ac.get('hex') or "").strip()
    baro,geo = ac.get('alt_baro'), ac.get('alt_geo')
    try:
        if baro: alt_ft=int(float(baro))
        elif geo: alt_ft=int(float(geo)*3.28084)
        else: alt_ft=0
    except:
        alt_ft=0
    vel = float(ac.get('gs') or ac.get('spd') or 0)
    hdg = float(ac.get('track') or ac.get('trak') or 0)
    if alt_ft>0:
        aircraft_list.append({
            'lat':lat,'lon':lon,
            'alt_ft':alt_ft,'vel':vel,'hdg':hdg,
            'callsign':cs
        })

df_ac = pd.DataFrame(aircraft_list)

# Status
st.markdown(f"**Home:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
st.markdown(f"**Sun alt:** {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.markdown(f"**Moon alt:** {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.warning("Moon data unavailable")
st.metric("Aircraft tracked", len(df_ac))

# Build sun/moon shadow trails
sun_trails, moon_trails = [], []
if not df_ac.empty:
    for _,r in df_ac.iterrows():
        s_path, m_path = [], []
        for i in range(FORECAST_DURATION_S+1):
            t = now_utc + timedelta(seconds=i)
            d = r['vel']*i
            dlat = d*math.cos(math.radians(r['hdg']))/111111
            dlon = d*math.sin(math.radians(r['hdg']))/(111111*math.cos(math.radians(r['lat'])))
            li,lo = r['lat']+dlat, r['lon']+dlon

            if track_sun:
                sa, saz = get_altitude(li,lo,t), get_azimuth(li,lo,t)
                if sa>0:
                    sd = r['alt_ft']/math.tan(math.radians(sa))
                    s_path.append([
                        lo + (sd/(111111*math.cos(math.radians(li))))*math.sin(math.radians(saz+180)),
                        li + (sd/111111)*math.cos(math.radians(saz+180))
                    ])

            if track_moon and ephem:
                obs = ephem.Observer()
                obs.lat,obs.lon,obs.date = str(li), str(lo), t
                pm = ephem.Moon(obs)
                ma, maz = math.degrees(pm.alt), math.degrees(pm.az)
                if ma>0:
                    md = r['alt_ft']/math.tan(math.radians(ma))
                    m_path.append([
                        lo + (md/(111111*math.cos(math.radians(li))))*math.sin(math.radians(maz+180)),
                        li + (md/111111)*math.cos(math.radians(maz+180))
                    ])

        if s_path: sun_trails.append({'path':s_path,'callsign':r['callsign'],'current':s_path[0]})
        if m_path: moon_trails.append({'path':m_path,'callsign':r['callsign'],'current':m_path[0]})

# Prepare map layers
layers = []

# Distance rings
for m in [1,2,5,10,20]:
    km = m*1.60934
    lat_d = (km*1000)/111111
    lon_d = lat_d/math.cos(math.radians(CENTER_LAT))
    ring = [[CENTER_LON+lon_d*math.sin(math.radians(a)),
             CENTER_LAT+lat_d*math.cos(math.radians(a))]
            for a in range(0,360,5)]
    ring.append(ring[0])
    layers.append(pdk.Layer("PathLayer", data=[{"path":ring}],
                            get_path="path", get_color=[0,200,0,120],
                            width_scale=100, width_min_pixels=1, pickable=False))
    layers.append(pdk.Layer("TextLayer",
                            data=[{"text":f"{m} mi","position":[CENTER_LON, CENTER_LAT+lat_d*1.02]}],
                            get_position="position", get_text="text",
                            get_color=[0,200,0,200], get_size=16, pickable=False))

# Sun shadows
if sun_trails:
    df_s = pd.DataFrame(sun_trails)
    layers.append(pdk.Layer("PathLayer", df_s, get_path="path",
                            get_color=[50,50,50,255], width_scale=5, width_min_pixels=1))
    curr_s = pd.DataFrame([{'lon':s['current'][0],'lat':s['current'][1]} for s in sun_trails])
    layers.append(pdk.Layer("ScatterplotLayer", curr_s,
                            get_position=["lon","lat"], get_fill_color=[50,50,50,255],
                            get_radius=100, pickable=True))

# Moon shadows
if moon_trails:
    df_m = pd.DataFrame(moon_trails)
    layers.append(pdk.Layer("PathLayer", df_m, get_path="path",
                            get_color=[200,200,200,200], width_scale=5, width_min_pixels=1))
    curr_m = pd.DataFrame([{'lon':m['current'][0],'lat':m['current'][1]} for m in moon_trails])
    layers.append(pdk.Layer("ScatterplotLayer", curr_m,
                            get_position=["lon","lat"], get_fill_color=[200,200,200,200],
                            get_radius=100, pickable=True))

# Alert ring
circle = []
for a in range(0,360,5):
    b = math.radians(a)
    dy = (alert_width/111111)*math.cos(b)
    dx = (alert_width/(111111*math.cos(math.radians(CENTER_LAT))))*math.sin(b)
    circle.append([CENTER_LON+dx, CENTER_LAT+dy])
circle.append(circle[0])
layers.append(pdk.Layer("PolygonLayer", data=[{"polygon":circle}],
                        get_polygon="polygon", get_fill_color=[255,0,0,100],
                        stroked=True, get_line_color=[255,0,0], get_line_width=3, pickable=False))

# Aircraft dots
if not df_ac.empty:
    layers.append(pdk.Layer("ScatterplotLayer", df_ac,
                            get_position=["lon","lat"],
                            get_fill_color=[0,128,255,200], get_radius=300,
                            pickable=True, auto_highlight=True, highlight_color=[255,255,0,255]))

# Render map with OSM tiles
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON,
                     zoom=max(1, min(16, 14 - math.log(radius_km,2))))
tooltip = {
    "html": (
        "<b>Callsign:</b> {callsign}<br/>"
        "<b>Alt:</b> {alt_ft} ft<br/>"
        "<b>Speed:</b> {vel_kt} kt<br/>"
        "<b>Heading:</b> {hdg}°"
    ),
    "style": {"backgroundColor":"black","color":"white"}
}
st.pydeck_chart(pdk.Deck(
    layers=layers,
    initial_view_state=view,
    map_style="open-street-map",
    tooltip=tooltip
), use_container_width=True)

# Recent Alerts table + chart
try:
    df_log = pd.read_csv(log_path)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        df_log['y'] = 0
        df_disp = df_log[['Time UTC','Callsign','Distance (mi)','Time Until Alert (sec)']].copy()
        df_disp.rename(columns={'Time Until Alert (sec)':'Transit (s)'}, inplace=True)
        st.markdown("### Recent Alerts")
        st.dataframe(df_disp.tail(10))
        fig = px.scatter(df_log, x='Time UTC', y='y',
                         size='Distance (mi)', size_max=40,
                         hover_name='Callsign',
                         hover_data={'Time Until Alert (sec)':True},
                         title="Alert Proximity Timeline")
        fig.add_hline(y=0, line_color='lightgray', line_width=1)
        fig.update_yaxes(visible=False, range=[-0.5,0.5])
        st.plotly_chart(fig, use_container_width=True)
except FileNotFoundError:
    st.warning("No alert log file found")

# On-screen alerts & logging
for trail in sun_trails:
    for lon,lat in trail['path']:
        if hav(lat,lon,CENTER_LAT,CENTER_LON) <= alert_width:
            cs = trail['callsign']
            dist = hav(lat,lon,CENTER_LAT,CENTER_LON)/1609.34
            idx = trail['path'].index([lon,lat])
            transit = idx * FORECAST_INTERVAL_S
            if on_screen_alerts:
                st.error(f"🚨 Sun shadow by {cs}: {dist:.2f} mi away, {transit} s transit")
                st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg")
            log_alert(cs,lat,lon,transit,dist)
            break

# Test alert button
if test_alert:
    ph = st.empty()
    ph.success("🔔 Test alert!")
    time.sleep(2)
    ph.empty()
