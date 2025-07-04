# cnisp_streamlit.py
import streamlit as st
import socket
import json
import time
import threading
import random

HOST = "127.0.0.1"
PORT = 35000
running = False

def generate_packet():
    return {
        "timestamp": time.time(),
        "airspeed": round(random.uniform(180, 290), 1),
        "altitude": round(random.uniform(5000, 25000), 1),
        "heading": round(random.uniform(0, 359), 1),
        "engine_rpm": [round(random.uniform(95, 100), 2) for _ in range(4)],
        "nav_status": random.choice(["GPS", "INS", "LOST"]),
        "system_health": "OK"
    }

def send_loop(callback):
    global running
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        while running:
            packet = generate_packet()
            sock.sendto(json.dumps(packet).encode(), (HOST, PORT))
            callback(packet)
            time.sleep(1)

# Streamlit GUI
st.set_page_config(page_title="C-130J CNISP Emulator", layout="centered")
st.title("🛩️ C-130J CNISP Emulator")

if "data" not in st.session_state:
    st.session_state.data = {}

placeholder = st.empty()
status = st.empty()

def start_emulator():
    global running
    if not running:
        running = True
        threading.Thread(target=send_loop, args=(update_display,), daemon=True).start()

def stop_emulator():
    global running
    running = False

def update_display(packet):
    st.session_state.data = packet

# Sidebar Controls
with st.sidebar:
    st.markdown("### Control Panel")
    if st.button("▶️ Start Emulator", disabled=running):
        start_emulator()
    if st.button("⏹️ Stop Emulator", disabled=not running):
        stop_emulator()
    st.markdown("---")
    st.text(f"Sending to {HOST}:{PORT}")

# Live display
with placeholder.container():
    if st.session_state.get("data"):
        p = st.session_state.data
        st.metric("Airspeed", f"{p['airspeed']} kt")
        st.metric("Altitude", f"{p['altitude']} ft")
        st.metric("Heading", f"{p['heading']}°")
        st.metric("Navigation Status", p['nav_status'])
        st.metric("System Health", p['system_health'])

        st.markdown("#### Engine RPM")
        cols = st.columns(4)
        for i in range(4):
            cols[i].metric(f"Engine {i+1}", f"{p['engine_rpm'][i]} %")

    else:
        st.info("Click ▶️ Start Emulator to begin.")
