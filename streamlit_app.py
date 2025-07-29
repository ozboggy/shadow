import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Sun & Moon Transit Tracker", layout="wide")

st.title("ADS-B Sun & Moon Transit Prediction Map")
st.markdown(
    "Real-time ADS-B aircraft tracking and sun/moon shadow projection. "
)

# Read the static HTML file
with open("index.html", "r", encoding="utf-8") as f:
    html_content = f.read()

# Embed the HTML/JS app in Streamlit
components.html(html_content, height=800, scrolling=True)  

