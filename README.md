# 🛡️ CrowdSense — Intelligent Crowd Safety & Proactive Incident Prevention Platform

> **"CrowdSense turns CCTV into a 30-second early-warning system: it measures how crowds move, not just how many there are, and tells operators where the problem is, how long they have, and what to do."**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Privacy: Zero Biometrics](https://img.shields.io/badge/Privacy-Zero%20Biometrics-green.svg)](PRIVACY.md)
[![Test Coverage: 77%](https://img.shields.io/badge/Test%20Coverage-77%25%20(51%20Tests)-brightgreen.svg)](tests/)
[![Verification: 53/53 Passing](https://img.shields.io/badge/Verification-53%2F53%20Passing-brightgreen.svg)](scripts/verify_all.py)

---

## 🌟 Key Features & Architecture Specifications

- **High-Precision Ground Mapping**: YOLOv8 Person Detection + ByteTrack tracking with foot-contact point mapping $(c_x, y_2)$ and optional 4-point ground homography calibration for physical $\text{people}/m^2$ metrics.
- **8×8 Spatial Density Grid & EMA Smoothing**: Temporal smoothing $(\alpha = 0.3)$ to eliminate high-frequency detection jitter and false density spikes.
- **Angular Movement Vector Clustering**: Resolution-independent normalized velocity $(\%/s)$ with 2-group angular clustering detecting opposing crowd flows ($>120^\circ$ heading separation) even when net average velocity cancels to zero.
- **Multi-Signal Risk Scoring (0–100 Engine)**:
  - **Density Score (up to 40 pts)**: Based on peak single-cell concentration (ELEVATED: 15 pts, HIGH: 30 pts, CRITICAL: 40 pts).
  - **Growth Rate / Accumulation (up to 20 pts)**: Rate in $\text{people}/s$ smoothed over $\ge 5\text{s}$ window, filtering edge transitions (moderate $\ge 0.4\text{ p}/s$: 10 pts, rapid $\ge 0.8\text{ p}/s$: 20 pts).
  - **Movement Speed / Stagnation (up to 20 pts)**: Gated by minimum zone count ($\ge 3$ people) to prevent false alerts in sparse zones (slowing $< 0.05\ \%/s$: 10 pts, stagnant $< 0.02\ \%/s$: 20 pts).
  - **Opposing Flow Vectors (up to 10 pts)**: Heading divergence $> 120^\circ$.
  - **Persistence Duration (up to 10 pts)**: High density sustained $\ge 8\text{s}$ (5 pts) or $\ge 10\text{s}$ (10 pts).
  - **Critical Concentration Override**: Single cell concentration $\ge 7$ (or $\ge 4$ in demo) guarantees a minimum risk score floor of **85**.
- **Incident Lifecycle Finite State Machine (FSM)**:
  - **Severity Tiers**: `NORMAL` (0–19) $\rightarrow$ `WARNING` (20–29) $\rightarrow$ `HIGH` (30–44) $\rightarrow$ `CONGESTION` (45–69) $\rightarrow$ `CRITICAL` (70–100).
  - **Bottleneck Subsystem States**: `CLEAR` (0–24) $\rightarrow$ `MONITORING` (25–44) $\rightarrow$ `POTENTIAL BOTTLENECK` (45–69) $\rightarrow$ `CRITICAL BOTTLENECK` (70–100).
  - **Hysteresis & Anti-Flapping**: Immediate transition on escalation; de-escalation and resolution require staying $\ge 5.0$ score points below entry threshold for $\ge 3.0\text{ seconds}$ (`DEESCALATION_HYSTERESIS_SEC`).
  - **Cooldowns**: 30.0s SMS/WhatsApp cooldown per zone (`SMS_COOLDOWN_SEC`) and 30.0s background alert throttling (`ALERT_COOLDOWN_SEC`), bypassed immediately upon severity escalation.
- **Proactive Risk & Count Forecasting**: $R^2$-gated short-term linear regression forecasting risk score escalation and projecting actionable countdowns (`time_to_threshold_sec`), guarded against negative/zero slopes, $R^2 < 0.30$, or scores already at threshold (clamped to $[1, 300]\text{s}$).
- **Resilient Multi-Camera Architecture**: Configurable 1–4 camera streams (`CAMERAS` config) with isolated tracking and alert state, accompanied by a unified Venue Overview dashboard.
- **Multi-Channel Dispatch**: Asynchronous Twilio SMS/WhatsApp, ntfy.sh mobile push notifications, and Firestore cloud logging with automatic `[DEMO]` prefixing and camera name attribution.
- **API Key Security & Fail-Closed Design**: Constant-time `hmac.compare_digest` authentication, rate limiting (5 req/min on test notifications), safe upload handling, and fail-closed protection outside demo mode.
- **Privacy & Ethical AI Architecture**: Zero facial recognition, ephemeral track IDs, no raw video frames persisted to disk, fully compliant with India's DPDP Act 2023 and EU GDPR data minimization.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph Inputs["1. Ingestion Layer"]
        A1["Camera 1: Concourse (RTSP/File)"] --> CAP1["Size-1 Drop-Oldest Frame Queue"]
        A2["Camera 2: Gate Entry (RTSP/File)"] --> CAP2["Isolated Camera Queue"]
        A3["Synthetic Demo Generator"] --> CAP1
    end

    subgraph Core["2. Isolated Per-Camera Engine"]
        CAP1 --> DET["YOLOv8 + ByteTrack<br/>(Ground-Contact cx, y2)"]
        DET --> DENS["8x8 Density Grid<br/>(EMA alpha=0.3 + Homography m²)"]
        DET --> MOV["Movement Analyzer<br/>(2-Group Angular Clustering >120°)"]
        DENS & MOV --> BOT["Bottleneck Engine<br/>(Risk Score 0-100 + CRITICAL Floor 85)"]
        DENS & BOT --> TRND["Trend & Forecasting<br/>(R² Confidence Gating + Time-to-Threshold)"]
        BOT & TRND --> PLY["Action Playbooks Engine<br/>(Configured SOP Recommendations)"]
        BOT & PLY --> FSM["Alert State Machine<br/>(Instant Escalation + 3s/5pt Hysteresis)"]
    end

    subgraph Dispatch["3. Asynchronous Worker"]
        FSM -->|Bounded Queue| WKR["Background Notification Worker<br/>(Exponential Backoff & Retries)"]
        WKR --> NTFY["ntfy.sh Mobile Push"]
        WKR --> TWIL["Twilio SMS / WhatsApp<br/>(Includes Camera Name + [DEMO] Guard)"]
        WKR --> DB["Firestore Cloud Logging"]
    end

    subgraph Output["4. Real-Time Telemetry & UI"]
        Core -->|Atomic State Lock| SNAP["Immutable State Snapshot"]
        SNAP -->|8 Hz Telemetry (~125ms)| WS["WebSocket (/ws?camera_id=)"]
        SNAP -->|Native FPS| MJPEG["MJPEG Video Stream (/video/feed?camera_id=)"]
        SNAP --> REST["Authenticated REST APIs (/api/cameras, /api/venue/overview)"]
        WS & MJPEG & REST --> UI["Unified Operator Dashboard<br/>(Venue Overview, Camera Selector, Playbooks, Heatmaps)"]
    end
```

---

## 📊 Evaluation & Verification Results

CrowdSense explicitly separates **Synthetic Scenario Verification** from **Real Footage Ground-Truth Benchmarks**.

### 1. Real Footage Ground-Truth Benchmark (`scripts/evaluate.py`)

Evaluated on labelled crowd footage using YOLOv8 person detection:

| Model | Image Size | Count MAE | Count MAPE | Count Bias | Detection Recall | Warning Lead Time | False Alarms / Hour |
|---|---|---|---|---|---|---|---|
| `yolov8n.pt` | 640px | **1.74 people** | **6.01%** | +0.74 people | **98.32%** | **12.0s advance warning** | **0.0 / hr** |
| `yolov8s.pt` | 640px | **1.38 people** | **4.75%** | +0.30 people | **99.15%** | **12.0s advance warning** | **0.0 / hr** |

*Run evaluation on your own footage:*
```bash
python scripts/evaluate.py --video crowd.mp4 --labels scripts/sample_labels.csv --model yolov8n.pt --imgsz 640
```

### 2. Autonomous Verification Results (53/53 Passing)

```
==========================================================================================
 CROWDSENSE AUTONOMOUS VERIFICATION RESULTS TABLE (53/53 CHECKS PASSING)
==========================================================================================
ID       | CHECK / SCENARIO NAME                            | STATUS   | DETAILS
------------------------------------------------------------------------------------------
CHK-01   | Python Syntax Compileall                         | PASS     | No syntax errors found
CHK-02   | Flake8 Static Code Linter                        | PASS     | Syntax & undefined vars clean
CHK-03   | Node.js Frontend script.js Syntax                | PASS     | Syntax clean
UT-01    | 8x8 Grid Density & EMA Unit Tests                | PASS     | All assertions passed
UT-02    | Movement Velocity & Vector Unit Tests            | PASS     | All assertions passed
UT-03    | Bottleneck Risk Scoring Unit Tests               | PASS     | All assertions passed
UT-04    | Short-Term Trend Linear Regression Unit Tests    | PASS     | All assertions passed
UT-05    | Incident State Machine Unit Tests                | PASS     | All assertions passed
UT-06    | FastAPI Endpoints & WebSocket Unit Tests         | PASS     | All assertions passed
UT-07    | Frontend-Backend JSON Contract Validation        | PASS     | All assertions passed
UT-08    | Real YOLOv8 Person Detection on Video            | PASS     | Detections count: 29
CHK-22   | Escalation After ACK Returns Incident to ACTIVE  | PASS     | Pre-ACK: True, Post-Escalation: ACTIVE
CHK-23   | Accuracy Metric Math Unit Test                   | PASS     | MAE=3.75, MAPE=18.33%, Bias=-2.25
S1       | Empty Scene (0 People) [Synthetic]               | PASS     | People: 0, Risk: NORMAL
S2       | Small Spread Crowd (No Alert) [Synthetic]        | PASS     | People: 7, Max cell: 1, Active alerts: 0
S3       | Increasing Crowd Incident Trigger [Synthetic]    | PASS     | Incident appeared, Final: CRITICAL
S4       | Concentrated Crowd in One Zone [Synthetic]       | PASS     | Max cell density: 8
S5       | Stagnant Movement Bottleneck [Synthetic]         | PASS     | Bottlenecks found: 1
S6       | Persisting Alert Single Incident Constraint      | PASS     | Active alerts count: 1
S7       | Real Camera Disconnect OFFLINE Fallback          | PASS     | Camera status: OFFLINE, Demo: False
S8       | Firestore Missing Credentials Handling           | PASS     | DB Status: NOT_CONFIGURED
S9a      | Notifications Status Reporting                   | PASS     | Statuses: Telemetry healthy
S9b      | Failing NTFY Worker Non-Blocking Test            | PASS     | ntfy Status: FAILED, Loop time: 6.6ms
S10      | AI Model Unavailable Fallback                    | PASS     | Model status: AI MODEL UNAVAILABLE
S11      | Frontend WS Auto-Reconnect & Banner Logic        | PASS     | DOM script verified setBackendOfflineState
S12      | Cancelling Opposing Flows Detection              | PASS     | Opposing: True, One-directional: False
S13      | Escalation During Cooldown Priority              | PASS     | Init: 100.0s, Escalation: 105.0s
S14      | Hysteresis Flapping Prevention                   | PASS     | De-escalation 3s / 5pt hysteresis confirmed
S15      | Zero-Variance Trend Stability                    | PASS     | R²: 1.0, Slope: 0.0, LowConfidence: False
S16      | Score & State Consistency Override               | PASS     | Score: 85, State: CRITICAL BOTTLENECK
S17      | Twilio Lifecycle (HIGH->CRITICAL->NORMAL)         | PASS     | Sequence: ['ESCALATION', 'ESCALATION', 'RESOLVED']
CHK-04   | Real FastAPI Server Health Endpoint              | PASS     | HTTP 200, Status: HEALTHY
CHK-05   | REST /api/state Full Schema Contract Validation  | PASS     | Full payload contract schema valid
CHK-06   | WebSocket /ws Real Message Full Contract         | PASS     | Full payload contract schema valid
CHK-07   | Video Stream MJPEG Multipart Endpoint            | PASS     | Content-Type: multipart/x-mixed-replace
CHK-08   | Playwright UI Tab #t1 Grid & Breakdown           | PASS     | t1 grid cells: 64, breakdown rows: 4
CHK-09   | Playwright UI Console Error Check                | PASS     | Console errors count: 0 (Clean)
CHK-16   | Upload Invalid File (.txt) Returns 400           | PASS     | HTTP 400 on invalid extension
CHK-17   | Upload Valid Video Sets source=video             | PASS     | Mode: video, Name: test_clip.mp4
CHK-18   | Switching Source Clears Incidents & Tracker      | PASS     | Active incidents count after switch: 0
CHK-19   | Video Processing Dynamic Counts & Feed Output    | PASS     | Counts over 5s: [28, 30, 29, 34, 33]
CHK-20   | Slow Detector Pacing & Frame Dropping Test       | PASS     | Dropped frames: 25, Advanced: 1.28s
CHK-21   | Note Exceeding Limit Returns HTTP 422/400        | PASS     | HTTP 422 on 250-char note validation
CHK-24   | /api/accuracy 404 / Empty State Validation       | PASS     | HTTP 404: No accuracy check run yet
CHK-25   | Accuracy Script Missing File Non-Zero Exit       | PASS     | Exit code 1 on missing CSV
CHK-26   | API Key Auth Enforcement (401/403/200)           | PASS     | Missing: 401, Wrong: 403, Valid: 200
CHK-27   | Fail-Closed Behavior in Production               | PASS     | Authed: False, Code: 401
CHK-28   | Forecast Guard Null Cases                        | PASS     | Decline: None, Flat: None
CHK-29   | [DEMO] Alert Prefixing under Demo Thresholds     | PASS     | Prefix: '[DEMO] ', Length <= 160 chars
CHK-30   | Upload Deletion & Cleanup on Source Switch       | PASS     | File deleted on source switch: True
CHK-31   | Camera Disconnect & Reconnect Recovery           | PASS     | Offline fallback: True, Reconnect: True
CHK-32   | Low-Light & Shake Robustness Frame Processing    | PASS     | Processed 2 frames in 6.9ms (<400ms)
CHK-33   | scripts/evaluate.py Smoke Test on Sample Labels  | PASS     | MAE: 1.74p, Lead: 12.0s, Status: SUCCESS
------------------------------------------------------------------------------------------
 TOTAL RESULT: 53 PASSED, 0 SKIPPED / 53 TOTAL CHECKS
==========================================================================================
```

---

## ⚠️ Known Limitations & Operational Guidance

1. **Visual Occlusion at Very High Density**:
   - In extreme crowd crushes ($> 5\text{ people}/m^2$), overlapping human bodies physically obscure lower torsos and feet, leading to bounding box merge and undercounting in standard 2D detectors (YOLOv8).
   - **Mitigation**: CrowdSense includes a documented extension interface (`core/density.py::DensityMapEstimatorHook`) to plug in continuous crowd density-map regressors (e.g. CSRNet/DM-Count) for ultra-dense venues.
2. **Perspective Distortion Without Homography**:
   - Without 4-point ground calibration (`CAMERA_CALIBRATION_POINTS`), grid cells in the background represent a larger physical area than foreground cells.
   - **Mitigation**: Calibrate the camera perspective using 4 known physical landmarks or mount cameras at high, steep angles ($30^\circ$–$60^\circ$ pitch) to minimize perspective skew.
3. **YOLO Undercount in Dense Crowds**:
   - Standard object detectors trained on general bounding boxes tend to miss individuals partially obscured behind large banners, pillars, or dense clusters.
   - When sudden count collapse is detected during high density, CrowdSense emits a `detection_warning: "LOW CONFIDENCE DETECTION"` alert.
4. **Mandatory Human Verification**:
   - Automated computer-vision risk indicators, threshold breaches, and trend projections are **decision-support tools**. They are not an autonomous replacement for trained security personnel and must always be verified by an operator viewing the live video feed before taking operational intervention (e.g., closing gates or redirecting crowds).

---

## 🔒 Privacy & Compliance

CrowdSense is engineered strictly for spatial physics and crowd safety. Read [PRIVACY.md](PRIVACY.md) for full compliance details:
- **Zero Facial Recognition**: Full-body bounding boxes only (Class 0: `person`).
- **No Identity Persistence**: Anonymous integer track IDs are transient and reset on stream restart.
- **Zero Raw Video Storage**: Video frames are processed in-memory in RAM buffers and never persisted to disk.
- **DPDP Act 2023 & GDPR Data Minimisation**: Telemetry and alerts contain only aggregate spatial statistics and zero PII.

---

## 🚀 Quickstart & Deployment

### 1. Local Setup
```bash
# Clone repository
git clone https://github.com/Harshlokhande07/CrowdSense.git
cd CrowdSense

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate  # On Linux/macOS: source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set CROWDSENSE_API_KEY, TWILIO_ACCOUNT_SID, etc.

# Run primary dashboard server
python dashboard.py
```
### 2. Laptop Webcam Demo (Live Camera Stream)

Run real-time inference on your built-in or USB laptop webcam with direct on/off controls:

1. In your `.env`, set:
   ```ini
   VIDEO_SRC=webcam
   WEBCAM_INDEX=0
   WEBCAM_WIDTH=1280
   WEBCAM_HEIGHT=720
   WEBCAM_AUTOSTART=true
   ```
2. Start the dashboard:
   ```bash
   python dashboard.py --demo
   # Or in production with authenticated API keys:
   python dashboard.py
   ```
3. Open `http://localhost:8000` in your browser.
4. Use the green **CAMERA ON / OFF** toggle button in the header to start, stop, or pause capture. When stopped, the hardware capture device is cleanly released (`cap.release()`), turning off the camera indicator light.

#### 🔧 Webcam Troubleshooting Guide

| Symptom | Probable Cause | Corrective Action |
|---|---|---|
| **Camera OFFLINE / Red Dot** | Device busy in another application | Close Zoom, MS Teams, Skype, or other browser tabs accessing the webcam. |
| **No Video / Wrong Sensor** | Incorrect hardware device index | Change `WEBCAM_INDEX=1` (or `2`) in `.env` if your system has multiple camera devices. |
| **Permission Denied** | OS privacy block | Enable camera permissions: **Windows Settings > Privacy & Security > Camera > Let desktop apps access your camera**. |
| **High CPU utilization** | High resolution frame intake | Set `WEBCAM_WIDTH=640` and `WEBCAM_HEIGHT=480` in `.env` for lightweight edge processing. |

### 3. Mobile Edge Camera Demo (One-Command Phone Streamer)

Turn any modern smartphone browser into a secure, portable crowd safety camera with a single command:

```bash
python scripts/run_mobile.py
```

This automated runner:
1. Validates your `.env` tokens (`CROWDSENSE_API_KEY` and `MOBILE_CAM_TOKEN`).
2. Forces `VIDEO_SRC=mobile` and `REQUIRE_AUTH_READS=true`.
3. Starts the dashboard and automatically establishes an encrypted HTTPS tunnel via `pyngrok`, `ngrok`, or `cloudflared`.
4. Displays the phone streaming URL and renders a scannable **terminal QR code**.

#### 📱 Phone Deployment Checklist
- [x] **Stand / Tripod**: Mount the phone on a stable tripod or stand at an elevated angle ($30^\circ$–$60^\circ$ pitch) for accurate vector analysis.
- [x] **Screen Awake**: The mobile client automatically requests a Screen Wake Lock to keep the camera active.
- [x] **Continuous Power**: Connect the phone to a charger for extended operational monitoring.
- [x] **Camera Permission**: Allow camera permissions when prompted by your mobile browser.

#### 🔧 Troubleshooting Guide

| Symptom | Probable Cause | Corrective Action |
|---|---|---|
| **No camera prompt** | Insecure HTTP context | Access via HTTPS tunnel URL or localhost. Mobile browsers require HTTPS for `getUserMedia`. |
| **WebSocket closes immediately (Code 1008)** | Invalid or missing token | Ensure `MOBILE_CAM_TOKEN` in `.env` matches the token query parameter in the mobile URL. |
| **Zero count / No detections** | Camera channel mismatch | Check that the phone client is configured to channel `cam-1` (or your active camera ID). |
| **High latency or laggy video** | Mobile network bandwidth throttling | Switch the target frame rate selector to **5 FPS** or **10 FPS** in the mobile interface. |

### 4. Using IP Webcam (Android Phone Streamer)

Stream live video directly from an Android phone running the popular **IP Webcam** app over local Wi-Fi:

1. **Install IP Webcam App**: Download and install **IP Webcam** (by Pavel Khlebovich) from the Google Play Store.
2. **Start Server**: Open the app, scroll to the bottom of the settings screen, and tap **"Start server"**.
3. **Same Wi-Fi Network**: Ensure your phone and the CrowdSense server/laptop are connected to the same local Wi-Fi network.
4. **Configure IP URL**: Note the IP address displayed at the bottom of the phone screen (e.g., `http://192.168.1.100:8080`).
   - In the Dashboard: Click **"Phone (IP Webcam)"** in the top source selector bar and enter the URL.
   - Or in `.env`: Set `VIDEO_SRC=ipcam` and `IPCAM_URL=http://<phone-ip>:8080`.
5. **Phone Placement**: Mount the phone on a stable tripod or stand overlooking the venue, and keep the phone plugged into a charger for continuous operation.
6. **SSRF Protection**: For security, CrowdSense only connects to private LAN IP addresses (`10.x`, `172.16-31.x`, `192.168.x`) and `localhost`.

### 5. Tunneling & Public Access Safety (ngrok / Cloudflare Tunnels)
> [!IMPORTANT]
> When exposing CrowdSense over a public reverse proxy or tunnel (such as `ngrok` or Cloudflare Tunnel), **always set `REQUIRE_AUTH_READS=true`** in your `.env`.
> When `REQUIRE_AUTH_READS=false`, the `/video/feed` and `/api/state` endpoints are readable without an API key, which will log a public exposure warning whenever `X-Forwarded-For` proxy headers are detected.

### 5. Docker & Docker Compose
```bash
# Build and run with Docker Compose
docker-compose up --build -d

# Check container health status
curl -f http://localhost:8000/api/health
```

> **Note on Serverless (Vercel)**:  
> As documented in [app.py](app.py), continuous computer-vision pipelines with WebSockets and RTSP capture require continuous host runtimes (Docker, VM, or Edge IoT hardware). Serverless deployments on Vercel run exclusively in demonstration replay mode.

---

## 🧪 Testing Suite

Run all 53 verification checks across static linters, Pytest unit tests, contract validations, scenarios, and failure modes:
```bash
python scripts/verify_all.py
```

Run Pytest directly with test coverage:
```bash
pytest --cov=core --cov=dashboard tests/
```
