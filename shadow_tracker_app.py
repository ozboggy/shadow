import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os, math, requests, pandas as pd, pydeck as pdk
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth
from streamlit_autorefresh import st_autorefresh

try:
    import ephem
except ImportError:
    ephem = None

# Auto‐refresh toggle
auto_refresh = st.sidebar.checkbox("Auto Refresh Map", value=True)
if auto_refresh:
    st_autorefresh(interval=1_000, key="datarefresh")

# Config / env
PUSHOVER_USER_KEY   = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN  = os.getenv("PUSHOVER_API_TOKEN")
ADSBEX_TOKEN        = os.getenv("ADSBEX_TOKEN")
CENTER_LAT, CENTER_LON = -33.7602563, 150.9717434
DEFAULT_RADIUS_KM     = 10
FORECAST_INTERVAL_SEC = 30
FORECAST_DURATION_MIN = 5

# Utilities
def send_pushover(title, message):
    if not (PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN):
        st.warning("🔒 Missing Pushover credentials")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token":  PUSHOVER_API_TOKEN,
                "user":   PUSHOVER_USER_KEY,
                "title":  title,
                "message":message
            },
            timeout=5
        )
    except Exception as e:
        st.warning(f"Pushover failed: {e}")

def hav(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

# Cache the fetch for 5min per radius
@st.cache_data(ttl=300, show_spinner=False)
def fetch_adsb(radius_km):
    url = f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
    headers = {
        "x-rapidapi-key": ADSBEX_TOKEN,
        "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
    }
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json().get("ac", [])

# Compute sun/moon altitude once per run
now = datetime.now(timezone.utc)
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now)
if ephem:
    obs = ephem.Observer(); obs.lat,obs.lon,obs.date = str(CENTER_LAT),str(CENTER_LON),now
    moon_alt = math.degrees(float(ephem.Moon(obs).alt))
else:
    moon_alt = None

# Sidebar controls
with st.sidebar:
    st.header("Settings")
    sc = "green" if sun_alt>0 else "red"
    st.markdown(f"**Sun alt:** <span style='color:{sc};'>{sun_alt:.1f}°</span>", unsafe_allow_html=True)
    if moon_alt is not None:
        mc = "green" if moon_alt>0 else "red"
        st.markdown(f"**Moon alt:** <span style='color:{mc};'>{moon_alt:.1f}°</span>", unsafe_allow_html=True)
    else:
        st.markdown("**Moon alt:** _(PyEphem missing)_")

    # step=10 reduces rapid-repeat fetches
    radius_km          = st.slider("Search Radius (km)", 0, 1000, DEFAULT_RADIUS_KM, step=10)
    military_radius_km = st.slider("Military Alert Radius (km)", 0, 1000, DEFAULT_RADIUS_KM, step=10)
    track_sun          = st.checkbox("Show Sun Shadows", True)
    show_moon          = st.checkbox("Show Moon Shadows", False)
    alert_width        = st.slider("Shadow Alert Width (m)", 0, 1000, 50)
    enable_onscreen    = st.checkbox("Enable Onscreen Alert", True)
    debug_raw          = st.checkbox("🔍 Debug raw ADS-B JSON", False)
    debug_df           = st.checkbox("🔍 Debug processed DataFrame", False)

    if st.button("Test Pushover"):
        send_pushover("✈️ Test Alert", "This is a test notification.")
        st.success("Sent!")
    if st.button("Test Onscreen"):
        if enable_onscreen:
            st.error("🚨 TEST ALERT!")
            st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
        else:
            st.warning("Disabled")

st.title("✈️ Aircraft Shadow Tracker")

# Fetch under spinner
with st.spinner("Loading aircraft…"):
    try:
        raw = fetch_adsb(radius_km) if ADSBEX_TOKEN else []
    except Exception as e:
        st.warning(f"ADS-B fetch failed: {e}")
        raw = []

if debug_raw:
    st.subheader("Raw ADS-B JSON")
    st.write(raw)

# Fallback to OpenSky only if ADS-B gave no results
if not raw and ADSBEX_TOKEN:
    dr = radius_km/111
    south,north=CENTER_LAT-dr,CENTER_LAT+dr
    dlon = dr/math.cos(math.radians(CENTER_LAT))
    west,east=CENTER_LON-dlon,CENTER_LON+dlon
    try:
        r2 = requests.get(
            f"https://opensky-network.org/api/states/all?"
            f"lamin={south}&lomin={west}&lamax={north}&lomax={east}",
            timeout=10
        )
        r2.raise_for_status()
        states = r2.json().get("states",[])
    except Exception as e:
        st.warning(f"OpenSky fetch failed: {e}")
        states = []
    # normalize to same schema
    raw = [{"lat":s[6],"lon":s[5],"alt_geo":s[13] or 0,"track":s[10] or 0,
            "flight":(s[1].strip() or s[0]),"mil":False}
           for s in states if len(s)>=11]

# Process
aircraft=[]
for ac in raw:
    try:
        lat   = float(ac.get("lat") or ac.get("Lat") or 0)
        lon   = float(ac.get("lon") or ac.get("Long") or 0)
        alt   = float(ac.get("alt_geo", ac.get("Alt",0)))
        angle = float(ac.get("track", ac.get("Trak",0)))
        cs    = ac.get("flight") or ac.get("Callsign") or ""
        mil   = bool(ac.get("mil", False))
    except:
        continue
    aircraft.append(dict(lat=lat,lon=lon,alt=alt,angle=angle,callsign=cs.strip(),mil=mil))

df = pd.DataFrame(aircraft)
if debug_df:
    st.subheader("Processed DataFrame")
    st.write(df)

st.sidebar.markdown(f"**Tracked Aircraft:** {len(df)}")

# Forecast trails
trails_sun=[] 
if track_sun:
    for _,r in df.iterrows():
        path,times=[],[]
        for s in range(0,FORECAST_INTERVAL_SEC*FORECAST_DURATION_MIN+1,FORECAST_INTERVAL_SEC):
            ft=now+timedelta(seconds=s)
            sa,sz = get_altitude(r.lat,r.lon,ft), get_azimuth(r.lat,r.lon,ft)
            if sa>0:
                d=r.alt/math.tan(math.radians(sa))
                sh_lat=r.lat+(d/111111)*math.cos(math.radians(sz+180))
                sh_lon=r.lon+(d/(111111*math.cos(math.radians(r.lat))))*math.sin(math.radians(sz+180))
                path.append((sh_lon,sh_lat)); times.append(s)
        if path:
            trails_sun.append({"callsign":r.callsign,"path":path,"times":times})

# Compute alerts
alerts=[]
for tr in trails_sun:
    for (lon,lat),t in zip(tr["path"],tr["times"]):
        if hav(lat,lon,CENTER_LAT,CENTER_LON)<=alert_width:
            alerts.append((tr["callsign"],t))
            send_pushover("✈️ Shadow Alert",f"{tr['callsign']} in ~{t}s")
            break

# Split DataFrame for coloring
will_shadow={cs for cs,_ in alerts}
df["will_shadow"]=df["callsign"].isin(will_shadow)
df_safe=df[~df["will_shadow"]]; df_alert=df[df["will_shadow"]]

# Build map
view=pdk.ViewState(latitiude=CENTER_LAT,longitude=CENTER_LON,zoom=DEFAULT_RADIUS_KM)
layers=[]
if not df_safe.empty:
    layers.append(pdk.Layer("ScatterplotLayer",df_safe,
                            get_position=["lon","lat"],get_color=[0,0,255,200],
                            get_radius=100))
if not df_alert.empty:
    layers.append(pdk.Layer("ScatterplotLayer",df_alert,
                            get_position=["lon","lat"],get_color=[255,0,0,200],
                            get_radius=100))
if track_sun:
    layers.append(pdk.Layer("PathLayer",pd.DataFrame(trails_sun),
                            get_path="path",get_color=[255,215,0,150],
                            width_scale=10,width_min_pixels=2))
layers.append(pdk.Layer("ScatterplotLayer",
                        pd.DataFrame([{"lat":CENTER_LAT,"lon":CENTER_LON}]),
                        get_position=["lon","lat"],
                        get_color=[255,0,0,200],
                        get_radius=alert_width))

st.pydeck_chart(pdk.Deck(layers=layers,initial_view_state=view,map_style="light"),
                use_container_width=True)

# Onscreen alert
if alerts and enable_onscreen:
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg", autoplay=True)
for cs,t in alerts:
    st.write(f"✈️ {cs} — in approx. {t}s")
if not alerts:
    st.success("✅ No shadows intersect")

# History
st.session_state.history.append({"time":now,"tracked":len(df),"shadow":len(alerts)})
hist=pd.DataFrame(st.session_state.history).set_index("time")
st.subheader("📈 Tracked vs Shadow Events")
st.line_chart(hist)
