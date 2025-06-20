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
# Auto-refresh every second
from streamlit_autorefresh import st_autorefresh
try:
    st_autorefresh(interval=1_000, key="datarefresh")
except Exception:
    pass

# … your existing setup code …

# After you build df_ac:
if df_ac.empty:
    st.warning("No aircraft data available.")
else:
    df_ac['alt'] = pd.to_numeric(df_ac['alt'], errors='coerce').fillna(0)

# Prepare icon metadata for each row
icon_data = []
for _, row in df_ac.iterrows():
    icon_data.append({
        "lon": row["lon"],
        "lat": row["lat"],
        "icon": {
            "url": "https://img.icons8.com/ios-filled/50/000000/airplane-take-off.png",
            "width": 128,
            "height": 128,
            "anchorY": 128
        }
    })
icon_df = pd.DataFrame(icon_data)

# Build layers
view = pdk.ViewState(latitude=CENTER_LAT, longitude=CENTER_LON, zoom=DEFAULT_RADIUS_KM)
layers = []

# IconLayer for aircraft
layers.append(pdk.Layer(
    "IconLayer",
    icon_df,
    get_icon="icon",
    get_position=["lon", "lat"],
    size_scale=15,            # adjust to make the plane smaller or larger
    pickable=True
))

# Sun-shadow trails (unchanged)
if track_sun and trails:
    df_trails = pd.DataFrame(trails)
    layers.append(pdk.Layer(
        "PathLayer", df_trails,
        get_path="path",
        get_color=[0, 0, 0, 150],
        width_scale=10,
        width_min_pixels=2
    ))

# Home marker (unchanged)
layers.append(pdk.Layer(
    "ScatterplotLayer",
    pd.DataFrame([{"lat": CENTER_LAT, "lon": CENTER_LON}]),
    get_position=["lon", "lat"],
    get_color=[255, 0, 0, 200],
    get_radius=400
))

# Render deck.gl map
deck = pdk.Deck(layers=layers, initial_view_state=view, map_style="light")
st.pydeck_chart(deck, use_container_width=True)
