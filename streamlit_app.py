import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="ADS-B Sun & Moon Transit Tracker", layout="wide")

st.title("ADS-B Sun & Moon Transit Prediction Map")
st.markdown(
    "This app embeds the existing Leaflet-based HTML map for real-time ADS-B aircraft tracking and sun/moon shadow projection. "
    "Adjust controls in the sidebar above the map."
)

# Read the static HTML file
with open("index.html", "r", encoding="utf-8") as f:
    html_content = f.read()

# Embed the HTML/JS app in Streamlit
components.html(html_content, height=800, scrolling=True)  

st.markdown(
    "---\n"
    "**Instructions**: Place your `index.html` in the same directory as this script. "
    "Install dependencies with `pip install streamlit` and run with `streamlit run streamlit_app.py`."
)
