import time
import streamlit as st
from dotenv import load_dotenv
load_dotenv()

import os, math, json, requests, pandas as pd
import pydeck as pdk
import plotly.express as px
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth

# Optional moon computations
try:
    import ephem
except ImportError:
    ephem = None

# Auto-refresh every second
from streamlit_autorefresh import st_autorefresh
st_autorefresh(interval=1000, key="refresh")

# ── CONFIG ─────────────────────────────────────────────────────────────────────
LOG_PATH          = os.getenv("LOG_PATH", "alert_log.csv")
HOME_CFG          = os.getenv("HOME_CONFIG", "home_location.json")
RAPIDAPI_KEY      = os.getenv("RAPIDAPI_KEY")
DEFAULT_RADIUS_MI = 10
RADIUS_KM         = DEFAULT_RADIUS_MI * 1.60934
FORECAST_INTERVAL = 1    # seconds
FORECAST_DURATION = 60   # seconds

# ── HOME LOAD / SAVE ───────────────────────────────────────────────────────────
def load_home():
    default = {"lat": -33.8544014, "lon": 151.2087668}
    if os.path.exists(HOME_CFG):
        try:
            cfg = json.load(open(HOME_CFG))
            return cfg.get("lat", default["lat"]), cfg.get("lon", default["lon"])
        except:
            pass
    return default["lat"], default["lon"]

def save_home(lat, lon):
    with open(HOME_CFG, "w") as f:
        json.dump({"lat": lat, "lon": lon}, f)
    st.experimental_rerun()

CENTER_LAT, CENTER_LON = load_home()

# ── ENSURE LOG ─────────────────────────────────────────────────────────────────
if not os.path.exists(LOG_PATH):
    pd.DataFrame(columns=[
        "Time UTC","Callsign","Lat","Lon",
        "Time Until Alert (sec)","Distance (mi)"
    ]).to_csv(LOG_PATH, index=False)

# ── HELPERS ────────────────────────────────────────────────────────────────────
def hav(lat1, lon1, lat2, lon2):
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return 2 * R * math.asin(math.sqrt(a))

def log_alert(cs, lat, lon, tt, dmi):
    try:
        df = pd.read_csv(LOG_PATH)
    except:
        df = pd.DataFrame(columns=[
            "Time UTC","Callsign","Lat","Lon",
            "Time Until Alert (sec)","Distance (mi)"
        ])
    new = pd.DataFrame([{
        "Time UTC": datetime.now(timezone.utc).isoformat(),
        "Callsign": cs, "Lat": lat, "Lon": lon,
        "Time Until Alert (sec)": tt, "Distance (mi)": dmi
    }])
    pd.concat([df, new], ignore_index=True).to_csv(LOG_PATH, index=False)

# ── SIDEBAR ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Home & Map Options")
    lat_in = st.number_input("Home Lat", value=CENTER_LAT, format="%.6f")
    lon_in = st.number_input("Home Lon", value=CENTER_LON, format="%.6f")
    if st.button("Save Home"):
        save_home(lat_in, lon_in)

    st.markdown("---")
    on_screen = st.checkbox("On-Screen Alerts", True)
    st.markdown(f"**Radius:** {DEFAULT_RADIUS_MI} mi")
    show_sun  = st.checkbox("Show Sun Shadows", True)
    show_moon = st.checkbox("Show Moon Shadows", False)
    alert_w   = st.slider("Shadow Alert Width (m)", 10, 1000, 50)
    test_btn  = st.button("Test Alert")

    st.markdown("---")
    if os.path.exists(LOG_PATH):
        st.download_button("Download alert_log.csv",
                           open(LOG_PATH, "rb"),
                           "alert_log.csv", "text/csv")
    else:
        st.info("No alerts logged yet")

# ── TIMESTAMP & SOLAR/MOON ALT ─────────────────────────────────────────────────
now_utc = datetime.now(timezone.utc)
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now_utc
    moon_alt = math.degrees(ephem.Moon(obs).alt)

# ── FETCH ADS-B DATA ───────────────────────────────────────────────────────────
ac_list = []
if RAPIDAPI_KEY:
    url = (f"https://adsbexchange-com1.p.rapidapi.com/v2/"
           f"lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{RADIUS_KM}/")
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host":"adsbexchange-com1.p.rapidapi.com"
    }
    try:
        r = requests.get(url, headers=headers); r.raise_for_status()
        data = r.json().get("ac", [])
    except:
        st.warning("Failed to fetch ADS-B data"); data = []
else:
    data = []

for ac in data:
    try:
        lat, lon = float(ac["lat"]), float(ac["lon"])
    except:
        continue
    cs = (ac.get("flight") or ac.get("hex") or "").strip()
    baro, geo = ac.get("alt_baro"), ac.get("alt_geo")
    try:
        if baro:       alt_ft = int(float(baro))
        elif geo:      alt_ft = int(float(geo)*3.28084)
        else:          alt_ft = 0
    except:
        alt_ft = 0
    vel = float(ac.get("gs") or ac.get("spd") or 0)
    hdg = float(ac.get("track") or ac.get("trak") or 0)
    if alt_ft>0:
        ac_list.append({
            "lat": lat, "lon": lon,
            "alt_ft": alt_ft, "vel": vel, "hdg": hdg,
            "callsign": cs
        })

df_ac = pd.DataFrame(ac_list)

# ── STATUS ─────────────────────────────────────────────────────────────────────
st.markdown(f"**Home:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
st.markdown(f"**Sun alt:** {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.markdown(f"**Moon alt:** {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.warning("Moon data unavailable")
st.metric("Tracked aircraft", len(df_ac))

# ── BUILD SHADOW TRAILS ────────────────────────────────────────────────────────
sun_trails, moon_trails = [], []
if not df_ac.empty:
    for _, r in df_ac.iterrows():
        s_path, m_path = [], []
        for i in range(FORECAST_DURATION+1):
            t = now_utc + timedelta(seconds=i)
            d = r["vel"]*i
            dlat = d*math.cos(math.radians(r["hdg"])) / 111111
            dlon = d*math.sin(math.radians(r["hdg"])) / (111111*math.cos(math.radians(r["lat"])))
            li, lo = r["lat"]+dlat, r["lon"]+dlon

            if show_sun:
                sa, saz = get_altitude(li, lo, t), get_azimuth(li, lo, t)
                if sa>0:
                    sd = r["alt_ft"]/math.tan(math.radians(sa))
                    s_path.append([
                        lo + (sd/(111111*math.cos(math.radians(li))))*math.sin(math.radians(saz+180)),
                        li + (sd/111111)*math.cos(math.radians(saz+180))
                    ])

            if show_moon and ephem:
                obs = ephem.Observer()
                obs.lat, obs.lon, obs.date = str(li), str(lo), t
                pm = ephem.Moon(obs)
                ma, maz = math.degrees(pm.alt), math.degrees(pm.az)
                if ma>0:
                    md = r["alt_ft"]/math.tan(math.radians(ma))
                    m_path.append([
                        lo + (md/(111111*math.cos(math.radians(li))))*math.sin(math.radians(maz+180)),
                        li + (md/111111)*math.cos(math.radians(maz+180))
                    ])

        if s_path:
            sun_trails.append({"path": s_path, "callsign": r["callsign"], "current": s_path[0]})
        if m_path:
            moon_trails.append({"path": m_path, "callsign": r["callsign"], "current": m_path[0]})

# ── ASSEMBLE LAYERS ────────────────────────────────────────────────────────────
layers = []

# OSM base + rings
layers.append(pdk.Layer("TileLayer", data=None,
                        get_tile_url="https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
                        tile_size=256, pickable=False))
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
    layers.append(pdk.Layer("TextLayer", data=[{"text":f"{m} mi",
                                                "position":[CENTER_LON, CENTER_LON+lat_d*1.02]}],
                            get_position="position", get_text="text",
                            get_color=[0,200,0,200], get_size=16, pickable=False))

# Shadow trails
if sun_trails:
    df_s = pd.DataFrame(sun_trails)
    layers.append(pdk.Layer("PathLayer", df_s, get_path="path",
                            get_color=[50,50,50,255], width_scale=5, width_min_pixels=1))
    curr_s = pd.DataFrame([{"lon":s["current"][0],"lat":s["current"][1]} for s in sun_trails])
    layers.append(pdk.Layer("ScatterplotLayer", curr_s,
                            get_position=["lon","lat"], get_fill_color=[50,50,50,255],
                            get_radius=100, pickable=True))
if moon_trails:
    df_m = pd.DataFrame(moon_trails)
    layers.append(pdk.Layer("PathLayer", df_m, get_path="path",
                            get_color=[200,200,200,200], width_scale=5, width_min_pixels=1))
    curr_m = pd.DataFrame([{"lon":m["current"][0],"lat":m["current"][1]} for m in moon_trails])
    layers.append(pdk.Layer("ScatterplotLayer", curr_m,
                            get_position=["lon","lat"], get_fill_color=[200,200,200,200],
                            get_radius=100, pickable=True))

# Aircraft
if not df_ac.empty:
    layers.append(pdk.Layer("ScatterplotLayer", df_ac,
                            get_position=["lon","lat"],
                            get_fill_color=[0,128,255,200], get_radius=300,
                            pickable=True, auto_highlight=True, highlight_color=[255,255,0,255]))

# Alert ring
ring=[]
for a in range(0,360,5):
    b=math.radians(a)
    dy=(alert_w/111111)*math.cos(b)
    dx=(alert_w/(111111*math.cos(math.radians(CENTER_LAT))))*math.sin(b)
    ring.append([CENTER_LON+dx,CENTER_LAT+dy])
ring.append(ring[0])
layers.append(pdk.Layer("PolygonLayer", data=[{"polygon":ring}],
                        get_polygon="polygon", get_fill_color=[255,0,0,100],
                        stroked=True, get_line_color=[255,0,0], get_line_width=3, pickable=False))

# ── RENDER DECK ───────────────────────────────────────────────────────────────
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON,
                     zoom=max(1, min(16, 14-math.log(RADIUS_KM,2))))
st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view,
                         map_provider="openstreetmap"),
                use_container_width=True)

# ── RECENT ALERTS + ON-SCREEN ─────────────────────────────────────────────────
try:
    df_log = pd.read_csv(LOG_PATH)
    if not df_log.empty:
        df_log['Time UTC']=pd.to_datetime(df_log['Time UTC'])
        df_log['y']=0
        disp=df_log[['Time UTC','Callsign','Distance (mi)','Time Until Alert (sec)']]
        disp.rename(columns={'Time Until Alert (sec)':'Transit (s)'}, inplace=True)
        st.markdown("### 📊 Recent Alerts") 
        st.dataframe(disp.tail(10))
        fig=px.scatter(df_log, x='Time UTC', y='y', size='Distance (mi)',size_max=40,
                       hover_name='Callsign', hover_data={'Time Until Alert (sec)':True},
                       title="Alert Proximity Timeline")
        fig.add_hline(y=0,line_color='lightgray',line_width=1)
        fig.update_yaxes(visible=False,range=[-0.5,0.5])
        st.plotly_chart(fig,use_container_width=True)
except FileNotFoundError:
    st.warning("No alert log found")

for trail in sun_trails:
    for lon,lat in trail['path']:
        if hav(lat,lat,CENTER_LAT,CENTER_LON)<=alert_w:
            dmi=hav(lat,lon,CENTER_LAT,CENTER_LON)/1609.34
            idx=trail['path'].index([lon,lat])
            ts=idx*FORECAST_INTERVAL
            if on_screen:
                st.error(f"🚨 Shadow by {trail['callsign']}: {dmi:.2f} mi, {ts}s")
                st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg")
            log_alert(trail['callsign'],lat,lon,ts,dmi)
            break

if test_btn:
    ph=st.empty()
    ph.success("🔔 Test alert!")
    time.sleep(2)
    ph.empty()
