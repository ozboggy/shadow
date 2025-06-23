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

# Paths
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
            pass
    return default['lat'], default['lon']

CENTER_LAT, CENTER_LON = load_home()

# Ensure alert log
if not os.path.exists(log_path):
    pd.DataFrame(columns=["Time UTC","Callsign","Lat","Lon","Time Until Alert (s)","Distance (mi)"]).to_csv(log_path,index=False)

# Helper: haversine
def hav(lat1, lon1, lat2, lon2):
    R=6371000
    dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

# Log alert
def log_alert(cs, lat, lon, t, d):
    df=pd.read_csv(log_path)
    df=pd.concat([df,pd.DataFrame([{"Time UTC":datetime.now(timezone.utc).isoformat(),"Callsign":cs,"Lat":lat,"Lon":lon,"Time Until Alert (s)":t,"Distance (mi)":d}])],ignore_index=True)
    df.to_csv(log_path,index=False)

# Defaults
DEFAULT_RADIUS_MI=25
RADIUS_KM=DEFAULT_RADIUS_MI*1.60934
FORECAST_S=60
INTERVAL_S=1

# Sidebar
with st.sidebar:
    st.header("Settings")
    st.subheader("Home Location")
    st.markdown(f"**Current:** {CENTER_LAT:.6f}, {CENTER_LON:.6f}")
    new_lat=st.number_input("New Latitude",value=CENTER_LAT,format="%.6f")
    new_lon=st.number_input("New Longitude",value=CENTER_LON,format="%.6f")
    if st.button("Save Home"    ):
        with open(home_config,'w') as f: json.dump({'lat':new_lat,'lon':new_lon},f)
        CENTER_LAT, CENTER_LON=new_lat,new_lon
        st.success("Home updated")
    st.markdown("---")
    on_screen=st.checkbox("On-Screen Alerts",True)
    show_alerts=st.checkbox("Show Recent Alerts",True)

# Main
now=datetime.now(timezone.utc)
# Sun/Moon alt
sun_alt=get_altitude(CENTER_LAT,CENTER_LON,now)
moon_alt=None
if ephem:
    obs=ephem.Observer(); obs.lat,obs.lon,obs.date=str(CENTER_LAT),str(CENTER_LON),now
    moon_alt=math.degrees(ephem.Moon(obs).alt)

# Fetch ADS-B
aircraft=[]
if RAPIDAPI_KEY:
    try:
        r=requests.get(f"https://adsbexchange-com1.p.rapidapi.com/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{RADIUS_KM}/",headers={"x-rapidapi-key":RAPIDAPI_KEY})
        data=r.json().get('ac',[])
    except:
        data=[]
else:
    data=[]
for ac in data:
    try: lat,lon=float(ac['lat']),float(ac['lon'])
    except: continue
    cs=(ac.get('flight')or ac.get('hex')or '').strip()
    baro=ac.get('alt_baro'); geo=ac.get('alt_geo')
    try:
        alt_ft=int(baro) if baro else int(float(geo)*3.28084)
    except: alt_ft=0
    try: vel=float(ac.get('gs')or ac.get('spd')or 0)
    except: vel=0
    try: hdg=float(ac.get('track')or ac.get('trak')or 0)
    except: hdg=0
    if alt_ft>0: aircraft.append({'lat':lat,'lon':lon,'alt_ft':alt_ft,'vel':vel,'hdg':hdg,'cs':cs})

df=pd.DataFrame(aircraft)
if not df.empty:
    df['vel_kt']=df['vel'].round().astype(int)
    df['dist_m']=df.apply(lambda r:hav(r['lat'],r['lon'],CENTER_LAT,CENTER_LON),axis=1)
    df['dist_mi']=df['dist_m']/1609.34

# Build trails
sun_trails=[]
if not df.empty:
    for _,r in df.iterrows():
        path=[]
        for i in range(0,FORECAST_S+1,INTERVAL_S):
            t=now+timedelta(seconds=i)
            d=r['vel']*i
            dlat=d*math.cos(math.radians(r['hdg']))/111111
            dlon=d*math.sin(math.radians(r['hdg']))/(111111*math.cos(math.radians(r['lat'])))
            li,lo=r['lat']+dlat,r['lon']+dlon
            sa,saz=get_altitude(li,lo,t),get_azimuth(li,lo,t)
            if sa>0:
                sd=r['alt_ft']/math.tan(math.radians(sa))
                path.append([lo+(sd/(111111*math.cos(math.radians(li))))*math.sin(math.radians(saz+180)),li+(sd/111111)*math.cos(math.radians(saz+180)),i])
        if path: sun_trails.append({'path':[pt[:2] for pt in path],'times':[pt[2] for pt in path],'cs':r['cs']})

# Layers
layers=[]
# rings\invest=[]
for m in [1,2,5,10,20]:
    km=m*1.60934; dkm=km*1000/111111; ring=[[CENTER_LON+dkm*math.sin(math.radians(a)),CENTER_LAT+dkm*math.cos(math.radians(a))] for a in range(0,360,5)]; ring.append(ring[0])
    layers.append(pdk.Layer("PathLayer",data=[{'path':ring}],get_path='path',get_color=[0,200,0,160],width_scale=100,width_min_pixels=1))

if sun_trails:
    df_s=pd.DataFrame(sun_trails)
    layers.append(pdk.Layer("PathLayer",df_s,get_path='path',get_color=[50,50,50,255],width_scale=5,width_min_pixels=1))

# View
view=pdk.ViewState(latitude=CENTER_LAT,longitude=CENTER_LON,zoom=12)
# Render
st.pydeck_chart(pdk.Deck(layers=layers,initial_view_state=view,map_style='light'),use_container_width=True)

# Alerts
if on_screen and not df.empty:
    for tr in sun_trails:
        for dist_pt,pt in zip(tr['times'],tr['path']):
            dmi=hav(pt[1],pt[0],CENTER_LAT,CENTER_LON)/1609.34
            if dmi*1609.34<=RADIUS_KM*1000:
                if dist_pt<=5: st.error(f"🚨 {dist_pt}s to shadow by {tr['cs']}, {dmi:.1f} mi")
                elif dist_pt<=10: st.warning(f"⏳ {dist_pt}s to shadow by {tr['cs']}, {dmi:.1f} mi")
                break

# Recent alerts
if show_alerts:
    df_log=pd.read_csv(log_path)
    df_log['Time UTC']=pd.to_datetime(df_log['Time UTC'])
    st.markdown("### 📊 Recent Alerts")
    st.dataframe(df_log.tail(10))
    fig=px.scatter(df_log,x='Time UTC',y=[0]*len(df_log),size='Distance (mi)')
    st.plotly_chart(fig,use_container_width=True)
