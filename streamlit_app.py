"""
CrowdSense — Streamlit Live Monitoring Application
Run:
    streamlit run streamlit_app.py
Uses shared core.engine.CrowdEngine pipeline.
"""

import time
import cv2
import numpy as np
import streamlit as st
from core.config import VIDEO_SRC, DEMO_MODE
from core.engine import CrowdEngine

st.set_page_config(page_title="CrowdSense Monitor", layout="wide", page_icon="🛡️")

st.title("🛡️ CrowdSense — Live Monitor")

# Sidebar Controls
st.sidebar.header("⚙️ Controls")
demo_opt = st.sidebar.checkbox("🎮 Enable Demo Simulation Mode", value=DEMO_MODE)
run_app = st.sidebar.checkbox("▶ Start Monitoring", value=False)

if not run_app:
    st.info("👈 Check 'Start Monitoring' in the sidebar to launch live monitoring.")
    st.stop()

@st.cache_resource
def get_engine(demo_mode: bool):
    return CrowdEngine(video_src=VIDEO_SRC, demo_mode=demo_mode)

engine = get_engine(demo_opt)

col1, col2 = st.columns([3, 1])

with col1:
    video_box = st.empty()

with col2:
    st.markdown("### 📈 Live Metrics")
    m_people = st.empty()
    m_risk = st.empty()
    m_density = st.empty()
    m_fps = st.empty()

st.markdown("### 🚨 Active Alerts & Incident Log")
alerts_box = st.empty()
disclaimer_box = st.caption("🛡️ Prototype risk indicators. All alerts require human verification.")

while True:
    state = engine.process_next_frame()

    # Retrieve video frame
    frame = engine.latest_processed_frame
    if frame is not None:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_box.image(rgb_frame, channels="RGB", use_container_width=True)

    # Update Streamlit metrics
    people = state.get("people_count", 0)
    risk_level = state.get("risk", {}).get("level", "NORMAL")
    max_density = state.get("density", {}).get("max", 0)
    fps = state.get("system", {}).get("fps", 0.0)

    m_people.metric("👥 Total People", people)
    m_risk.metric("⚠️ Risk Level", risk_level)
    m_density.metric("🔴 Max Cell Count", max_density)
    m_fps.metric("⚡ Engine FPS", f"{fps:.1f}")

    # Display Alerts
    alerts = state.get("alerts_active", [])
    if alerts:
        alert_lines = [
            f"🚨 **{a['severity']}** — {a['zone_name']}: {a['current_count']} people ({a['action_recommended']})"
            for a in alerts
        ]
        alerts_box.markdown("\n\n".join(alert_lines))
    else:
        alerts_box.success("✅ Crowd density normal across all monitored zones.")

    time.sleep(0.04)
