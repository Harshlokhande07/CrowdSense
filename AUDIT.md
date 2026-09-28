# CrowdSense — Codebase Audit Report (AUDIT.md)

## 1. Directory & File Inventory

| File / Path | Purpose | Status | Migration Strategy |
| :--- | :--- | :--- | :--- |
| `app.py` | Streamlit live monitoring frontend | Partial | Keep as thin Streamlit wrapper importing `core.engine.CrowdEngine`. |
| `crowdsense.py` | OpenCV GUI standalone window app | Partial | Keep as thin OpenCV wrapper importing `core.engine.CrowdEngine`. |
| `dashboard.py` | Primary FastAPI backend & static server | Working | Update to host primary control center server importing `core.engine.CrowdEngine`. |
| `backend/main.py` | Legacy FastAPI backend entry point | Duplicate | Re-export `dashboard.app` for backward compatibility. |
| `backend/alerts.py` | Legacy Firestore / Twilio alert module | Broken | Re-export `core.alerts.AlertManager` with safe lazy initialization. |
| `backend/requirements.txt` | Incomplete dependencies list | Partial | Consolidated into root `requirements.txt`. |
| `Frontend/index.html` | Control room dashboard HTML layout | Partial | Update to use `textContent` DOM nodes and display explicit system state indicators. |
| `Frontend/script.js` | Dashboard client interaction script | Partial | Rebuilt with WebSocket client, auto-reconnect, and safe `textContent` data binding. |
| `Frontend/style.css` | Control room CSS styles | Working | Retained and expanded with dark control room styling. |
| `Frontend/format.py` | HTML formatting helper tool | Unused | Retain intact; not used during runtime execution. |
| `croud1.mp4`, `crowd.mp4` | Test video media files | Working | Retained as default sample inputs. |
| `yolov8n.pt` | YOLOv8 weights file | Working | Retained for detector inference. |

---

## 2. Identified Problems & Concrete Fixes

1. **Top-Level Import Crash (`backend/alerts.py`)**:
   - *Problem*: Calling `firebase_admin.initialize_app()` and `Client(...)` on module import caused immediate crashes if env vars were missing.
   - *Fix*: Implemented lazy initialization with status reporting (`NOT_CONFIGURED` / `DISCONNECTED`).

2. **Prediction Mathematics**:
   - *Problem*: Compares current density against old density with `new > old * 1.5`, triggering false alarms on noisy single-person shifts (1 &rarr; 2 people).
   - *Fix*: Implemented linear regression extrapolation over a 45–60s window with 15–30s horizon and $R^2$ fit quality checks ($\ge 15$ samples required).

3. **Bottleneck Persistence Duration**:
   - *Problem*: Conditions triggered instant alerts on noisy single frames.
   - *Fix*: Added configurable persistence requirement (default **8 seconds**) before declaring a potential bottleneck.

4. **Opposing Flow Calculation**:
   - *Problem*: Simplified vector angle check triggered false positives.
   - *Fix*: Implemented vector splitting along dominant movement axis into two directional groups; flags opposing flow when smaller group $> 25\%$ of total active vectors and both groups maintain speed $> 0.02\ \%/s$.

5. **Grid Mapping Location**:
   - *Problem*: Mapped bounding box centers $(c_x, c_y)$ instead of ground foot position $(c_x, y_2)$.
   - *Fix*: Mapped bottom-center $(c_x, y_2)$ to 8×8 grid cells dynamically.

6. **Frontend Safety & Disclaimers**:
   - *Problem*: Static mock data and missing explicit state banners.
   - *Fix*: Updated UI to use `textContent` safe bindings and explicit badges: `CAMERA OFFLINE`, `AI MODEL UNAVAILABLE`, `BACKEND OFFLINE`, `DATABASE DISCONNECTED`, `LIVE CONNECTION LOST`, `0 PEOPLE DETECTED`, `DEMO MODE`.

---

## 3. Architecture & Migration Decision
All core CV, grid density, vector tracking, bottleneck detection, short-term forecasting, and incident alert state machines are centralized under `core/`. All frontends (`dashboard.py`, `app.py`, `crowdsense.py`) import `core.engine.CrowdEngine` to ensure identical prototype risk indicator calculations.
