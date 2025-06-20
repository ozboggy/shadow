import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
import math
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timezone, timedelta
from pysolar.solar import get_altitude, get_azimuth
from streamlit_autorefresh import st_autorefresh

# Optional moon support
try:
    import ephem
except ImportError:
    ephem = None

# Ensure history exists
if "history" not in st.session_state:
    st.session_state.history = []

# Sidebar: auto‐refresh
st.sidebar.header("Refresh Settings")
auto_refresh     = st.sidebar.checkbox("Auto Refresh Map", True)
refresh_interval = st.sidebar.number_input("Refresh Interval (s)", 1, 60, 1)
if auto_refresh:
    st_autorefresh(interval=refresh_interval * 1000, key="refresh")

# Env & constants
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
ADSBEX_TOKEN       = os.getenv("ADSBEX_TOKEN")
CENTER_LAT         = -33.7602563
CENTER_LON         = 150.9717434
DEFAULT_RADIUS_KM  = 10
FORECAST_INTERVAL  = 30
FORECAST_DURATION  = 5

def send_pushover(t,m):
    if not (PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN):
        st.warning("🔒 Missing Pushover creds")
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token":PUSHOVER_API_TOKEN,"user":PUSHOVER_USER_KEY,"title":t,"message":m},
            timeout=5
        )
    except Exception as e:
        st.warning(f"Pushover failed: {e}")

def hav(lat1, lon1, lat2, lon2):
    R=6371000
    dlat,dlon=math.radians(lat2-lat1),math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

now = datetime.now(timezone.utc)

# Compute Sun/Moon altitude
sun_alt = get_altitude(CENTER_LAT, CENTER_LON, now)
if ephem:
    obs = ephem.Observer(); obs.lat,obs.lon,obs.date=str(CENTER_LAT),str(CENTER_LON),now
    moon_alt = math.degrees(float(ephem.Moon(obs).alt))
else:
    moon_alt = None

# Sidebar: map & alert
st.sidebar.header("Map & Alert Settings")
sc="green" if sun_alt>0 else "red"
st.sidebar.markdown(f"**Sun alt:** <span style='color:{sc};'>{sun_alt:.1f}°</span>",unsafe_allow_html=True)
if moon_alt is not None:
    mc="green" if moon_alt>0 else "red"
    st.sidebar.markdown(f"**Moon alt:** <span style='color:{mc};'>{moon_alt:.1f}°</span>",unsafe_allow_html=True)
else:
    st.sidebar.markdown("**Moon alt:** _(PyEphem not installed)_")

radius_km          = st.sidebar.slider("Search Radius (km)",0,1000,DEFAULT_RADIUS_KM)
mil_radius_km      = st.sidebar.slider("Military Radius (km)",0,1000,DEFAULT_RADIUS_KM)
track_sun          = st.sidebar.checkbox("Show Sun Shadows",True)
track_moon         = st.sidebar.checkbox("Show Moon Shadows",False)
alert_width        = st.sidebar.slider("Alert Radius (m)",0,1000,50)
enable_onscreen    = st.sidebar.checkbox("Enable Onscreen Alert",True)

if st.sidebar.button("Test Pushover"):
    send_pushover("✈️ Test","This is a test")
    st.sidebar.success("Sent!")
if st.sidebar.button("Test Onscreen"):
    if enable_onscreen:
        st.error("🚨 TEST ALERT!")
        st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg",autoplay=True)
    else:
        st.sidebar.warning("Disabled")

st.title("✈️ Aircraft Shadow Tracker")

# Fetch ADS-B
raw=[]
if ADSBEX_TOKEN:
    try:
        url=f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{radius_km}/"
        hdr={"x-rapidapi-key":ADSBEX_TOKEN,"x-rapidapi-host":"adsbexchange-com1.p.rapidapi.com"}
        r=requests.get(url,headers=hdr,timeout=10); r.raise_for_status()
        raw=r.json().get("ac",[])
    except Exception as e:
        st.warning(f"ADS-B failed: {e}")

# Fallback OpenSky
if not raw:
    dr=radius_km/111; south,north=CENTER_LAT-dr,CENTER_LAT+dr
    dlon=dr/math.cos(math.radians(CENTER_LAT))
    west,east=CENTER_LON-dlon,CENTER_LON+dlon
    try:
        r2=requests.get(f"https://opensky-network.org/api/states/all?lamin={south}&lomin={west}&lamax={north}&lomax={east}",timeout=10)
        r2.raise_for_status()
        states=r2.json().get("states",[])
    except Exception as e:
        st.warning(f"OpenSky failed: {e}"); states=[]
    raw=[{"lat":s[6],"lon":s[5],"alt":s[13] or 0,"track":s[10] or 0,"callsign":(s[1].strip() or s[0]),"mil":False} for s in states if len(s)>=11]

# Process
ac_list=[]
for ac in raw:
    try:
        lat=float(ac.get("lat") or ac.get("Lat")); lon=float(ac.get("lon") or ac.get("Long"))
        alt=float(ac.get("alt_geo",ac.get("alt",0))); ang=float(ac.get("track") or ac.get("Trak") or 0)
        cs=ac.get("flight") or ac.get("callsign") or ac.get("Callsign") or ""
        mil=bool(ac.get("mil",False))
    except:
        continue
    ac_list.append({"lat":lat,"lon":lon,"alt":alt,"angle":ang,"callsign":cs.strip(),"mil":mil})

df=pd.DataFrame(ac_list)
st.sidebar.markdown(f"**Tracked:** {len(df)}")
st.sidebar.markdown(f"**Military:** {int(df['mil'].sum())}")
if not df.empty:
    df["alt"]=pd.to_numeric(df["alt"],errors="coerce").fillna(0)

# Compute shadows
trails_sun=[]; trails_moon=[]
if track_sun:
    for _,r in df.iterrows():
        path,times=[],[]
        for s in range(0,FORECAST_INTERVAL*FORECAST_DURATION+1,FORECAST_INTERVAL):
            ft=now+timedelta(seconds=s)
            sa,az=get_altitude(r.lat,r.lon,ft),get_azimuth(r.lat,r.lon,ft)
            if sa>0:
                d=r.alt/math.tan(math.radians(sa))
                shlat=r.lat+(d/111111)*math.cos(math.radians(az+180))
                shlon=r.lon+(d/(111111*math.cos(math.radians(r.lat))))*math.sin(math.radians(az+180))
                path.append((shlon,shlat)); times.append(s)
        if path: trails_sun.append({"callsign":r.callsign,"path":path,"times":times})
if track_moon and ephem:
    for _,r in df.iterrows():
        path,times=[],[]
        for s in range(0,FORECAST_INTERVAL*FORECAST_DURATION+1,FORECAST_INTERVAL):
            ft=now+timedelta(seconds=s)
            obs=ephem.Observer(); obs.lat,obs.lon,obs.date=str(r.lat),str(r.lon),ft
            m=ephem.Moon(obs); ma,mz=math.degrees(float(m.alt)),math.degrees(float(m.az))
            if ma>0:
                d=r.alt/math.tan(math.radians(ma))
                shlat=r.lat+(d/111111)*math.cos(math.radians(mz+180))
                shlon=r.lon+(d/(111111*math.cos(math.radians(r.lat))))*math.sin(math.radians(mz+180))
                path.append((shlon,shlat)); times.append(s)
        if path: trails_moon.append({"callsign":r.callsign,"path":path,"times":times})

# Alerts
alerts=[]
for tr in trails_sun:
    for (lon,lat),t in zip(tr["path"],tr["times"]):
        if hav(lat,lon,CENTER_LAT,CENTER_LON)<=alert_width:
            alerts.append((tr["callsign"],t)); break
# mark shadows
shadow_cs={cs for cs,_ in alerts}
df["will_shadow"]=df["callsign"].isin(shadow_cs)
df_safe=df[~df["will_shadow"]]; df_warn=df[df["will_shadow"]]

# Build layers
view=pdk.ViewState(latitude=CENTER_LAT,longitude=CENTER_LON,zoom=DEFAULT_RADIUS_KM)
layers=[]
if not df_safe.empty:
    layers.append(pdk.Layer("ScatterplotLayer",df_safe,get_position=["lon","lat"],get_color=[0,0,255,200],get_radius=100))
if not df_warn.empty:
    layers.append(pdk.Layer("ScatterplotLayer",df_warn,get_position=["lon","lat"],get_color=[255,0,0,200],get_radius=100))
if track_sun:
    layers.append(pdk.Layer("PathLayer",pd.DataFrame(trails_sun),get_path="path",get_color=[255,215,0,150],width_scale=10,width_min_pixels=2))
if track_moon:
    layers.append(pdk.Layer("PathLayer",pd.DataFrame(trails_moon),get_path="path",get_color=[100,100,100,150],width_scale=10,width_min_pixels=2))
layers.append(pdk.Layer("ScatterplotLayer",pd.DataFrame([{"lat":CENTER_LAT,"lon":CENTER_LON}]),get_position=["lon","lat"],get_color=[255,0,0,200],get_radius=alert_width))
st.pydeck_chart(pdk.Deck(layers=layers,initial_view_state=view,map_style="light"),use_container_width=True)

# Onscreen alert
if alerts and enable_onscreen:
    st.error("🚨 Shadow ALERT!")
    st.audio("https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg",autoplay=True)
for cs,t in alerts:
    st.write(f"✈️ {cs} in ~{t}s")
if not alerts:
    st.success("✅ No shadows")

# History
st.session_state.history.append({"time":now,"tracked":len(df),"shadow":len(alerts)})
hist=pd.DataFrame(st.session_state.history).set_index("time")
st.subheader("📈 Tracked vs Shadow Events")
st.line_chart(hist)
