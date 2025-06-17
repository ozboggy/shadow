import streamlit as st
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
import requests
import folium


# Fetch flight positions
positions = []

if tab == "Local ADS-B Feed":
    # Fetch local ADS-B
    try:
        data = requests.get(local_feed_url, timeout=5).json()
    except Exception as e:
        st.error(f"Local ADS-B feed error: {e}")
        st.stop()
    # Parse JSON: expect list of dicts or {'aircraft': [...]}
    aircraft_list = None
    if isinstance(data, dict) and 'aircraft' in data:
        aircraft_list = data['aircraft']
    elif isinstance(data, list):
        aircraft_list = data
    else:
        st.warning("Unrecognized local feed format")
        aircraft_list = []
    for entry in aircraft_list:
        if isinstance(entry, dict):
            lat = entry.get('lat') or entry.get('latitude')
            lon = entry.get('lon') or entry.get('longitude')
            cs = entry.get('flight') or entry.get('callsign') or entry.get('hex') or ''
            alt = entry.get('altitude') or entry.get('alt') or 0
            spd = entry.get('speed') or entry.get('spd') or 0
            hdg = entry.get('track') or entry.get('heading') or 0
        else:
            continue
        if lat is None or lon is None:
            continue
        positions.append({'lat': lat, 'lon': lon, 'callsign': str(cs).strip(), 'alt': alt, 'speed': spd, 'track': hdg})
    st.sidebar.markdown(f"**Local feed count:** {len(positions)}")

elif tab == "JS Feed Fallback":
    # FlightRadar24 website JSON
    url = f"https://data-live.flightradar24.com/zones/fcgi/feed.js?bounds={bounds}&array=1"
    try:
        data = requests.get(url, timeout=5).json()
    except Exception as e:
        st.error(f"JS feed error: {e}")
        st.stop()
    aircraft_list = data.get('aircraft') or []
    for entry in aircraft_list:
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        lat, lon = entry[1], entry[2]
        cs = str(entry[0])
        if lat is None or lon is None:
            continue
        positions.append({'lat': lat, 'lon': lon, 'callsign': cs, 'alt': 0, 'speed': 0, 'track': 0})
    st.sidebar.markdown(f"**JS feed count:** {len(positions)}")

else:
    # Use FR24 API
    api = FR24API(FR24_API_KEY)
    try:
        raw = api.get_flight_positions_light(bounds)
    except FR24AuthenticationError as e:
        st.error(f"FR24 auth failed: {e}")
        st.stop()
    except Exception as e:
        st.error(f"FR24 error: {e}")
        st.stop()
    for posobj in raw:
        lat = getattr(posobj, 'latitude', None)
        lon = getattr(posobj, 'longitude', None)
        alt = getattr(posobj, 'altitude', None) or 0
        spd = getattr(posobj, 'speed', None) or 0
        hdg = getattr(posobj, 'track', None) or getattr(posobj, 'heading', None) or 0
        cs = getattr(posobj, 'callsign', '') or getattr(posobj, 'flight', '')
        if None in (lat, lon):
            continue
        positions.append({'lat': lat, 'lon': lon, 'callsign': cs.strip(), 'alt': alt, 'speed': spd, 'track': hdg})
    st.sidebar.markdown(f"**FR24 API count:** {len(positions)}")

if debug:
    st.write("Positions sample:", positions[:5])
    st.write("Bounds:", bounds)

if not positions:
    st.warning("No aircraft found in selected source and bounds.")

# Plot raw positions
for p in positions:
    folium.Marker((p['lat'], p['lon']), icon=folium.Icon(color="blue", icon="plane", prefix="fa"), popup=p['callsign']).add_to(m)

# Log file init
def write_header():
    with open(LOG_FILE, 'w', newline='') as f:
        csv.writer(f).writerow(["Time UTC","Callsign","Alert Sec","Lat","Lon"])
LOG_FILE = os.path.join(os.path.dirname(__file__), "shadow_alerts.csv")
if not pathlib.Path(LOG_FILE).exists(): write_header()

# Projection utils
def haversine(lat1,lon1,lat2,lon2):
    R=6371000; dlat=radians(lat2-lat1); dlon=radians(lon2-lon1)
    a=sin(dlat/2)**2+cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R*2*asin(sqrt(a))

def move_position(lat,lon,bearing,dist):
    R=6371000; b=radians(bearing); φ1,λ1=radians(lat),radians(lon)
    d=dist/R; φ2=asin(sin(φ1)*cos(d)+cos(φ1)*sin(d)*cos(b))
    λ2=λ1+atan2(sin(b)*sin(d)*cos(φ1),cos(d)-sin(φ1)*sin(φ2))
    return degrees(φ2),degrees(λ2)

# Shadow projections + alerts
alerts=[]
for p in positions:
    lat, lon, alt, spd, hdg, cs = p['lat'], p['lon'], p.get('alt',0), p.get('speed',0), p.get('track',0), p['callsign']
    alt_m=alt*0.3048; spd_m=spd*0.514444; tr=[]; alerted=False
    for t in range(0,5*60+1,30):
        fx,fy=move_position(lat,lon,hdg,spd_m*t)
        if show_sun:
            sa=solar_altitude(fx,fy,t0+timedelta(seconds=t))
            if sa>0:
                az=solar_azimuth(fx,fy,t0+timedelta(seconds=t)); sd=alt_m/tan(radians(sa))
                sx,sy=move_position(fx,fy,az+180,sd); tr.append((sx,sy,'sun'))
                if not alerted and haversine(sx,sy,HOME_LAT,HOME_LON)<=alert_radius:
                    alerts.append((cs,t,sx,sy)); alerted=True
        if show_moon and MOON_AVAILABLE:
            obs=ephem.Observer(); obs.lat,obs.lon=str(fx),str(fy)
            obs.date=(t0+timedelta(seconds=t)).strftime('%Y/%m/%d %H:%M:%S')
            mobj=ephem.Moon(obs); ma=degrees(mobj.alt)
            if ma>0:
                maz=degrees(mobj.az); sd=alt_m/tan(radians(ma))
                sx,sy=move_position(fx,fy,maz+180,sd); tr.append((sx,sy,'moon'))
                if not alerted and haversine(sx,sy,HOME_LAT,HOME_LON)<=alert_radius:
                    alerts.append((cs,t,sx,sy)); alerted=True
    for sx,sy,typ in tr: folium.CircleMarker((sx,sy),radius=2,color='#FFA500' if typ=='sun' else '#AAAAAA',fill=True).add_to(m)

if alerts:
    st.error("🚨 Shadow Alert!")
    for cs,t,sx,sy in alerts:
        st.write(f"✈️ {cs} shadow in ~{t}s at {sx:.5f},{sy:.5f}")
        with open(LOG_FILE,'a',newline='') as f: csv.writer(f).writerow([datetime.utcnow().isoformat(),cs,t,sx,sy])
        try: requests.post("https://api.pushover.net/1/messages.json",data={"token":PUSHOVER_API_TOKEN,"user":PUSHOVER_USER_KEY,"message":f"{cs} shadow in{t}s"})
        except: pass
else: st.success("✅ No shadow passes predicted.")

# Render map
st_folium(m,800,600)

# Download log
if pathlib.Path(LOG_FILE).exists():
    st.sidebar.markdown("### Alert Log")
    with open(LOG_FILE,'rb') as f: st.sidebar.download_button("CSV",f,file_name="shadow_alerts.csv")
    df=pd.read_csv(LOG_FILE); st.sidebar.dataframe(df.tail(10))
