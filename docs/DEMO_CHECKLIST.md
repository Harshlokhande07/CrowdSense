# 🛡️ CrowdSense — 3-Minute Hackathon & Presentation Demo Script

> **Safety Disclaimer**: CrowdSense outputs **prototype risk indicators** designed to assist security personnel. All automated alerts **require human verification** prior to deploying physical crowd management interventions.

---

## 📋 Pre-Demo Setup Checklist (1 Minute Before Presentation)

1. **Environment & Virtual Environment**:
   - Open terminal in project root: `c:\Users\HARSH\Desktop\crowdsense harsh`
   - Activate Virtual Environment:
     - **Windows PowerShell**: `.\venv\Scripts\Activate.ps1`
     - **Windows CMD**: `.\venv\Scripts\activate.bat`
     - **Or run directly**: `.\venv\Scripts\python.exe dashboard.py`

2. **Verify Verification Suite**:
   ```bash
   .\venv\Scripts\python.exe scripts/verify_all.py
   ```
   *Confirm all 27 checks pass.*

3. **Start Primary Server in Demo Simulation Mode**:
   ```bash
   .\venv\Scripts\python.exe dashboard.py --demo
   ```
   *Open browser to:* **`http://localhost:8000`**

---

## ⏱️ 3-Minute Demo Presentation Script

### 0:00 – 0:45 | Phase 1: Problem Statement & Live Command Center Overview
- **What to Show**: Open `http://localhost:8000` showing Tab 0 (Command Center). Point out the header status chips, KPI cards (People Detected, Avg Density, Max Cell Count, Active Alerts), and the live 8×8 grid matrix.
- **What to Say**:
  > *"Hello everyone. Large public events, festivals, and transit hubs often suffer from sudden crowd surges and dangerous congestion bottlenecks. Traditional monitoring is purely reactive — operators notice overcrowding only after a crush begins.*
  >
  > *This is CrowdSense — an intelligent crowd safety platform that shifts security teams from reactive monitoring to proactive intervention. On our command center dashboard, you can see live system telemetry: camera feed status, YOLOv8 model readiness, database connectivity, and our overall risk indicator."*

---

### 0:45 – 1:45 | Phase 2: Computer Vision Pipeline & Spatial 8×8 Grid Mapping
- **What to Show**: Hover over cells in the 8×8 Spatial Density Grid. Show how ground foot positioning $(c_x, y_2)$ maps detections into grid cells, and how Exponential Moving Average (EMA) smoothing prevents single-frame noise jitter.
- **What to Say**:
  > *"Let's look at how the computer vision pipeline works. CrowdSense runs YOLOv8 ByteTrack person detection. Rather than using bounding box centers which can skew when people walk, we map each person's ground foot coordinates $(c_x, y_2)$ into a dynamic 8×8 spatial cell matrix.*
  >
  > *Every cell evaluates prototype risk thresholds: green for normal, yellow for elevated, orange for high, and red for critical density. Notice how our live heatmap overlay visually highlights high-density sectors on the floor plan in real time."*

---

### 1:45 – 2:30 | Phase 3: Bottlenecks, Movement Vectors & Short-Term Trend Estimation
- **What to Show**: Switch to Tab 2 (Trend Forecast) or point to the Bottleneck Panel in Command Center. Highlight the multi-signal score (0–100), vector velocity tracking (%/s), opposing flow detection, and the 30-second linear regression trend extrapolation line.
- **What to Say**:
  > *"To catch bottlenecks before stampedes form, CrowdSense doesn't look at static counts alone. Our bottleneck engine evaluates a multi-signal risk score combining cell density, accumulation rate, stagnation speed, opposing crowd flow vectors, and persistence duration.*
  >
  > *Furthermore, our short-term trend estimator runs linear regression over a 45-to-60 second rolling history window to project crowd growth 30 seconds into the future. Each forecast is rated with an $R^2$ mathematical confidence score."*

---

### 2:30 – 3:00 | Phase 4: Incident Dispatch, Safety Disclaimers & Q&A Wrap-Up
- **What to Show**: Switch to Tab 3 (Incidents & Alerts). Show an active incident card with severity badge, zone location, and recommended security actions (e.g., *"Pause entry at Gate 3 for 2 minutes; deploy staff to East Lane"*). Point to the footer disclaimer.
- **What to Say**:
  > *"When a zone condition persists past our prototype risk thresholds, CrowdSense triggers a single active incident per zone. The incident automatically recommends clear, actionable procedures for field security teams and dispatches instant mobile alerts via ntfy push notifications and Twilio SMS.*
  >
  > *Most importantly, CrowdSense is designed as a decision-support tool for human operators. All risk indicators and automated alerts explicitly require human verification before field deployment.*
  >
  > *Thank you! We're ready for your questions."*

---

## ⚡ Quick Troubleshooting & Fail-Safe Tips During Live Demo

| Issue During Presentation | Cause | Instant Fix |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'fastapi'` | Ran system Python instead of virtualenv | Run with `.\venv\Scripts\python.exe dashboard.py` or run `.\venv\Scripts\activate` first. |
| Camera webcam feed disconnected | Webcam in use by another app or missing | Server automatically defaults to `DEMO_MODE` simulation. Toggle `--demo` flag. |
| Web page shows `LIVE CONNECTION LOST` | Backend server stopped | Restart server with `.\venv\Scripts\python.exe dashboard.py`. Auto-reconnect will re-establish WS feed in 1s. |
