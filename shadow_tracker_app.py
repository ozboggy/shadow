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
AUTOREFRESH_MS = 1000
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=AUTOREFRESH_MS, key="datarefresh")
except ImportError:
    pass

# ── CONFIG ─────────────────────────────────────────────────────────────────────
LOG_PATH           = os.getenv("LOG_PATH", "alert_log.csv")
HOME_CFG           = os.getenv("HOME_CONFIG", "home_location.json")
RAPIDAPI_KEY       = os.getenv("RAPIDAPI_KEY")
MAPBOX_API_KEY     = os.getenv("MAPBOX_API_KEY")
DEFAULT_RADIUS_MI  = 10
RADIUS_KM          = DEFAULT_RADIUS_MI * 1.60934
FORECAST_INTERVAL_S = 1
FORECAST_DURATION_S = 60

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
        "Time UTC","Callsign","Lat","Lon","Time Until Alert (sec)","Distance (mi)"
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
            "Time UTC","Callsign","Lat","Lon","Time Until Alert (sec)","Distance (mi)"
        ])
    new = pd.DataFrame([{
        "Time UTC": datetime.now(timezone.utc).isoformat(),
        "Callsign": cs, "Lat": lat, "Lon": lon,
        "Time Until Alert (sec)": tt, "Distance (mi)": dmi
    }])
    pd.concat([df,new], ignore_index=True).to_csv(LOG_PATH, index=False)

# ── SIDEBAR ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Home & Map Options")
    lat_in = st.number_input("Home Lat", value=CENTER_LAT, format="%.6f")
    lon_in = st.number_input("Home Lon", value=CENTER_LON, format="%.6f")
    if st.button("Save Home"):
        save_home(lat_in, lon_in)

    st.markdown("---")
    on_screen_alerts = st.checkbox("On-Screen Alerts", True)
    st.markdown(f"**Radius:** {DEFAULT_RADIUS_MI} mi")
    track_sun  = st.checkbox("Show Sun Shadows",  True)
    track_moon = st.checkbox("Show Moon Shadows", False)
    alert_width = st.slider("Shadow Alert Width (m)", 10, 1000, 50)
    test_alert  = st.button("Test Alert")

    st.markdown("---")
    if os.path.exists(LOG_PATH):
        st.download_button("Download alert_log.csv",
                           open(LOG_PATH, "rb"),
                           "alert_log.csv", "text/csv")
    else:
        st.info("No alert log yet")

# ── TIMESTAMP & SOLAR DATA ─────────────────────────────────────────────────────
now_utc = datetime.now(timezone.utc)
sun_alt  = get_altitude(CENTER_LAT, CENTER_LON, now_utc)
moon_alt = None
if ephem:
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.date = str(CENTER_LAT), str(CENTER_LON), now_utc
    moon_alt = math.degrees(ephem.Moon(obs).alt)

# ── FETCH ADS-B DATA ───────────────────────────────────────────────────────────
aircraft = []
if RAPIDAPI_KEY:
    url = (f"https://adsbexchange-com1.p.rapidapi.com/v2/"
           f"lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{RADIUS_KM}/")
    headers = {"x-rapidapi-key": RAPIDAPI_KEY,
               "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"}
    try:
        resp = requests.get(url, headers=headers); resp.raise_for_status()
        data = resp.json().get("ac", [])
    except:
        st.warning("ADS-B fetch failed"); data = []
else:
    data = []

for ac in data:
    try:
        lat = float(ac["lat"]); lon = float(ac["lon"])
    except:
        continue
    cs = (ac.get("flight") or ac.get("hex") or "").strip()
    baro, geo = ac.get("alt_baro"), ac.get("alt_geo")
    try:
        if baro:       alt_ft = int(float(baro))
        elif geo:      alt_ft = int(float(geo) * 3.28084)
        else:          alt_ft = 0
    except:
        alt_ft = 0
    vel = float(ac.get("gs") or ac.get("spd") or 0)
    hdg = float(ac.get("track") or ac.get("trak") or 0)
    if alt_ft > 0:
        aircraft.append({"lat": lat, "lon": lon,
                         "alt_ft": alt_ft, "vel": vel,
                         "hdg": hdg, "callsign": cs})

df_ac = pd.DataFrame(aircraft)

# ── STATUS DISPLAY ────────────────────────────────────────────────────────────
st.markdown(f"**Home:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
st.markdown(f"**Sun alt:** {'🟢' if sun_alt>0 else '🔴'} {sun_alt:.1f}°")
if moon_alt is not None:
    st.markdown(f"**Moon alt:** {'🟢' if moon_alt>0 else '🔴'} {moon_alt:.1f}°")
else:
    st.warning("Moon data unavailable")
st.metric("Aircraft tracked", len(df_ac))

# ── BUILD STATIC BACKGROUND (cached) ──────────────────────────────────────────
@st.cache_data(show_spinner=False)
def build_static():
    view = pdk.ViewState(
        latitude=CENTER_LAT, longitude=CENTER_LON,
        zoom=max(1, min(16, 14 - math.log(RADIUS_KM, 2)))
    )
    tile = pdk.Layer(
        "TileLayer", data=None,
        get_tile_url="https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
        tile_size=256, pickable=False
    )
    rings = []
    for m in [1,2,5,10,20]:
        km = m*1.60934
        lat_d = (km*1000)/111111
        lon_d = lat_d/math.cos(math.radians(CENTER_LAT))
        path = [[CENTER_LON+lon_d*math.sin(math.radians(a)),
                 CENTER_LAT+lat_d*math.cos(math.radians(a))]
                for a in range(0,360,5)]
        path.append(path[0])
        rings.append(pdk.Layer(
            "PathLayer", data=[{"path":path}],
            get_path="path", get_color=[0,200,0,120],
            width_scale=100, width_min_pixels=1, pickable=False
        ))
    return view, [tile] + rings

view_state, static_layers = build_static()

# ── BUILD DYNAMIC LAYERS ───────────────────────────────────────────────────────
sun_trails, moon_trails = [], []
if not df_ac.empty:
    for _, r in df_ac.iterrows():
        s_path, m_path = [], []
        for i in range(FORECAST_DURATION_S+1):
            t = now_utc + timedelta(seconds=i)
            d = r["vel"]*i
            dlat = d*math.cos(math.radians(r["hdg"]))/111111
            dlon = d*math.sin(math.radians(r["hdg"]))/(111111*math.cos(math.radians(r["lat"])))
            li, lo = r["lat"]+dlat, r["lon"]+dlon

            if track_sun:
                sa, saz = get_altitude(li,lo,t), get_azimuth(li,lo,t)
                if sa>0:
                    sd = r["alt_ft"]/math.tan(math.radians(sa))
                    s_path.append([lo + (sd/(111111*math.cos(math.radians(li))))*math.sin(math.radians(saz+180)),
                                   li + (sd/111111)*math.cos(math.radians(saz+180))])
            if track_moon and ephem:
                obs = ephem.Observer(); obs.lat,obs.lon,obs.date = str(li),str(lo),t
                pm = ephem.Moon(obs); ma,maz=math.degrees(pm.alt),math.degrees(pm.az)
                if ma>0:
                    md = r["alt_ft"]/math.tan(math.radians(ma))
                    m_path.append([lo + (md/(111111*math.cos(math.radians(li))))*math.sin(math.radians(maz+180)),
                                   li + (md/111111)*math.cos(math.radians(maz+180))])

        if s_path: sun_trails.append({"path":s_path,"callsign":r["callsign"],"current":s_path[0]})
        if m_path: moon_trails.append({"path":m_path,"callsign":r["callsign"],"current":m_path[0]})

dynamic_layers = []

for s in sun_trails:
    dynamic_layers.append(pdk.Layer("PathLayer", pd.DataFrame([s]), get_path="path",
                                   get_color=[50,50,50,255], width_scale=5, width_min_pixels=1))
for m in moon_trails:
    dynamic_layers.append(pdk.Layer("PathLayer", pd.DataFrame([m]), get_path="path",
                                   get_color=[200,200,200,200], width_scale=5, width_min_pixels=1))
if not df_ac.empty:
    dynamic_layers.append(pdk.Layer("ScatterplotLayer", df_ac,
                                   get_position=["lon","lat"],
                                   get_fill_color=[0,128,255,200], get_radius=300,
                                   pickable=True, auto_highlight=True, highlight_color=[255,255,0,255]))

# alert ring
ring = []
for a in range(0,360,5):
    b = math.radians(a)
    dy=(alert_width/111111)*math.cos(b)
    dx=(alert_width/(111111*math.cos(math.radians(CENTER_LAT))))*math.sin(b)
    ring.append([CENTER_LON+dx, CENTER_LAT+dy])
ring.append(ring[0])
dynamic_layers.append(pdk.Layer("PolygonLayer", data=[{"polygon":ring}],
                                get_polygon="polygon", get_fill_color=[255,0,0,100],
                                stroked=True, get_line_color=[255,0,0], get_line_width=3, pickable=False))

# ── RENDER ONE DECK ──────────────────────────────────────────────────────────
all_layers = static_layers + dynamic_layers
deck = pdk.Deck(
    layers=all_layers,
    initial_view_state=view_state,
    mapbox_key=MAPBOX_API_KEY,
    map_style="mapbox://styles/mapbox/streets-v11"
)
st.pydeck_chart(deck, use_container_width=True)

# ── RECENT ALERTS & LOGIC ─────────────────────────────────────────────────────
try:
    df_log = pd.read_csv(LOG_PATH)
    if not df_log.empty:
        df_log['Time UTC'] = pd.to_datetime(df_log['Time UTC'])
        df_log['y'] = 0
        disp = df_log[['Time UTC','Callsign','Distance (mi)','Time Until Alert (sec)']].copy()
        disp.rename(columns={'Time Until Alert (sec)':'Transit (s)'}, inplace=True)
        st.markdown("### 📊 Recent Alerts")
        st.dataframe(disp.tail(10))
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

for trail in sun_trails:
    for lon, lat in trail['path']:
        if hav(lat, lon, CENTER_LAT, CENTER_LON) <= alert_width:
            dmi = hav(lat, lon, CENTER_LAT, CENTER_LON)/1609.34
            idx = trail['path'].index([lon, lat])
            transit = idx * FORECAST_INTERVAL_S
            if on_screen_alerts:
                st.error(f"🚨 Sun shadow by {trail['callsign']}: {dmi:.2f} mi away, {transit} s transit")
                st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg")
            log_alert(trail['callsign'], lat, lon, transit, dmi)
            break

if test_alert:
    ph = st.empty(); ph.success("🔔 Test alert!"); time.sleep(2); ph.empty()
