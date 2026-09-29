"""
CrowdSense Primary Command Center Server (FastAPI + WebSocket + MJPEG Streaming).

Run directly:
    python dashboard.py
Or with uvicorn:
    uvicorn dashboard:app --host 0.0.0.0 --port 8000

Serves the frontend dashboard at http://localhost:8000
"""

import sys
import os
import time
import argparse
import asyncio
import logging
import threading
import cv2
from typing import Set, Optional
from pydantic import BaseModel, Field

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, File, UploadFile, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uuid

from core.config import (
    HOST, PORT, CORS_ORIGINS, DEMO_MODE, VIDEO_SRC,
    MAX_UPLOAD_MB, ALLOWED_UPLOAD_EXTENSIONS,
    MAX_OPERATOR_NAME_LEN, MAX_NOTE_LEN,
    WS_BROADCAST_HZ, API_AUTH_KEY
)
from core.engine import CrowdEngine

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("CrowdSense.Server")

# Parse CLI flags
parser = argparse.ArgumentParser(description="CrowdSense Command Center Server")
parser.add_argument("--demo", action="store_true", help="Run in DEMO / SIMULATION mode")
parser.add_argument("--port", type=int, default=PORT, help="Port to run server on")
parser.add_argument("--host", type=str, default=HOST, help="Host interface to bind")
cli_args, _ = parser.parse_known_args()

is_demo = cli_args.demo or DEMO_MODE

# Initialize Core Pipeline Engine (manages processing thread internally)
engine = CrowdEngine(video_src=VIDEO_SRC, demo_mode=is_demo)
start_time = time.time()

# FastAPI Application
app = FastAPI(
    title="CrowdSense API",
    description="Intelligent Crowd Safety Monitoring & Early Warning Platform",
    version="2.1.0"
)

# Configure CORS
origins = CORS_ORIGINS if CORS_ORIGINS else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active WebSocket Clients Set
active_websockets: Set[WebSocket] = set()

def check_auth(token: Optional[str] = None, header_key: Optional[str] = None, auth_header: Optional[str] = None) -> bool:
    """Validates API authentication token when API_AUTH_KEY is configured."""
    if not API_AUTH_KEY:
        return True  # Open access in local demo mode
    if token and token == API_AUTH_KEY:
        return True
    if header_key and header_key == API_AUTH_KEY:
        return True
    if auth_header and auth_header.startswith("Bearer ") and auth_header[7:].strip() == API_AUTH_KEY:
        return True
    return False

# ────────────────── WebSocket Endpoint ──────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
    if not check_auth(token=token):
        await websocket.close(code=4001)
        return

    await websocket.accept()
    active_websockets.add(websocket)
    logger.info(f"WebSocket client connected. Total clients: {len(active_websockets)}")

    sleep_interval = 1.0 / max(WS_BROADCAST_HZ, 1.0)

    try:
        while True:
            # Broadcast current engine state
            state_data = engine.latest_state
            if state_data:
                await websocket.send_json(state_data)

            await asyncio.sleep(sleep_interval)
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
        logger.info(f"WebSocket client disconnected. Remaining clients: {len(active_websockets)}")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        active_websockets.discard(websocket)

# ────────────────── Video Stream Endpoint ──────────────────
@app.get("/video/feed")
def video_feed():
    """MJPEG Video Stream Endpoint."""
    def frame_generator():
        while True:
            frame = engine.latest_processed_frame
            if frame is not None and frame.size > 0:
                ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
                    )
            time.sleep(0.033)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# ────────────────── REST API Endpoints ──────────────────
@app.post("/api/source/upload")
def upload_source_video(
    file: UploadFile = File(...),
    token: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None)
):
    """Uploads a video file (.mp4, .avi, .mov), validates type, size, safe decode, and switches engine source."""
    if not check_auth(token=token, header_key=x_api_key):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized: Invalid or missing API key."})

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid file type '{ext}'. Allowed extensions: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"}
        )

    contents = file.file.read()
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    if len(contents) > max_bytes:
        return JSONResponse(
            status_code=400,
            content={"detail": f"File size exceeds maximum limit of {MAX_UPLOAD_MB}MB."}
        )

    upload_dir = os.path.join("scratch", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"up_{uuid.uuid4().hex}{ext}"
    saved_path = os.path.abspath(os.path.join(upload_dir, safe_name))

    with open(saved_path, "wb") as f:
        f.write(contents)

    # Safe decode validation with timeout / try-except
    try:
        test_cap = cv2.VideoCapture(saved_path)
        if not test_cap.isOpened():
            test_cap.release()
            if os.path.exists(saved_path):
                os.remove(saved_path)
            return JSONResponse(status_code=400, content={"detail": "Uploaded video could not be decoded."})
        ret, test_frame = test_cap.read()
        test_cap.release()
        if not ret or test_frame is None:
            if os.path.exists(saved_path):
                os.remove(saved_path)
            return JSONResponse(status_code=400, content={"detail": "Uploaded video contains no readable frames."})
    except Exception as e:
        if os.path.exists(saved_path):
            os.remove(saved_path)
        return JSONResponse(status_code=400, content={"detail": f"Video validation failed: {e}"})

    src_info = engine.set_source("video", file_path=saved_path, display_name=filename)
    return JSONResponse({"status": "OK", "source": src_info})


@app.post("/api/source/select")
def select_source_mode(payload: dict):
    """Selects input source mode ('demo', 'video', 'webcam') and resets state."""
    mode = payload.get("mode") if isinstance(payload, dict) else None
    if mode not in ("demo", "video", "webcam"):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid source mode. Allowed modes: demo, video, webcam"}
        )

    src_info = engine.set_source(mode)
    return JSONResponse({"status": "OK", "source": src_info})

@app.get("/api/health")
def get_health():
    """Returns system health and component connectivity status."""
    notifications = engine.alert_manager.get_system_notifications_status()
    uptime_sec = time.time() - start_time
    return {
        "status": "HEALTHY",
        "uptime_seconds": round(uptime_sec, 1),
        "demo_mode": engine.demo_mode,
        "camera": engine.camera_status,
        "source": engine.get_source_info(),
        "model": engine.detector.status,
        "database": notifications["database"],
        "twilio": notifications["twilio"],
        "sms": notifications.get("sms", "DISABLED"),
        "ntfy": notifications["ntfy"],
        "fps": round(engine.current_fps, 1),
        "active_ws_clients": len(active_websockets)
    }

@app.get("/api/state")
def get_state():
    """Returns latest complete engine state snapshot."""
    return engine.latest_state

class TestNotifyRequest(BaseModel):
    zone_id: Optional[str] = Field("ZONE_A", description="Target zone ID for test")
    message: Optional[str] = Field(None, description="Custom test message body (optional)")

@app.post("/api/notify/test")
def test_notification(
    payload: Optional[TestNotifyRequest] = None,
    token: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None)
):
    """
    Protected test endpoint to trigger a sample Twilio SMS/WhatsApp alert without waiting for a real crowd surge.
    """
    if not check_auth(token=token, header_key=x_api_key):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized: Invalid or missing API key."})

    from core.notifier import twilio_notifier
    from core.config import TWILIO_ENABLED

    if not TWILIO_ENABLED:
        return JSONResponse(
            status_code=400,
            content={
                "status": "DISABLED",
                "detail": "Twilio is not configured. Set TWILIO_ACCOUNT_SID, credentials, sender, and ALERT_PHONE_NUMBERS in .env."
            }
        )

    zone_id = payload.zone_id if payload and payload.zone_id else "ZONE_A"
    reasons = ["Manual System Test", "Admin Verification"]

    queued = twilio_notifier.send_alert(
        zone_id=zone_id,
        zone_name="Test Zone",
        level="HIGH",
        score=75,
        reasons=reasons,
        kind="ESCALATION",
        recommended_actions=["Verify phone reception"]
    )

    if queued:
        return JSONResponse(content={
            "status": "QUEUED",
            "message": "Test alert successfully enqueued for delivery.",
            "recipients_count": len(twilio_notifier.get_recipients_for_zone(zone_id)),
            "diagnostics": twilio_notifier.get_diagnostics()
        })
    else:
        return JSONResponse(status_code=500, content={
            "status": "FAILED",
            "detail": "Failed to enqueue test alert. Check server logs."
        })

# ────────────────── Incident Management Models & Endpoints ──────────────────
# PROTOTYPE LIMITS: No authentication in this prototype; operator name is free text.

class AcknowledgeRequest(BaseModel):
    operator: str = Field(..., max_length=MAX_OPERATOR_NAME_LEN, description="Operator name (max 40 chars)")
    note: str = Field(..., max_length=MAX_NOTE_LEN, description="Acknowledgement note (max 200 chars)")

class ResolveRequest(BaseModel):
    operator: Optional[str] = Field(None, max_length=MAX_OPERATOR_NAME_LEN, description="Operator name (max 40 chars)")
    note: str = Field(..., max_length=MAX_NOTE_LEN, description="Resolution note (max 200 chars)")

@app.post("/api/incidents/{incident_id}/ack")
def acknowledge_incident(
    incident_id: str,
    payload: AcknowledgeRequest,
    token: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None)
):
    """Acknowledges an active incident with operator name and note."""
    if not check_auth(token=token, header_key=x_api_key):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized: Invalid or missing API key."})

    now = time.time()
    success, status_code, message, inc = engine.alert_manager.acknowledge_incident(
        incident_id, payload.operator, payload.note, now
    )
    if not success:
        return JSONResponse(status_code=status_code, content={"detail": message})
    return JSONResponse(content={"status": "OK", "incident": inc})

@app.post("/api/incidents/{incident_id}/resolve")
def resolve_incident(
    incident_id: str,
    payload: ResolveRequest,
    token: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None)
):
    """Manually resolves an active incident with note."""
    if not check_auth(token=token, header_key=x_api_key):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized: Invalid or missing API key."})

    now = time.time()
    success, status_code, message, inc = engine.alert_manager.resolve_incident(
        incident_id, payload.note, payload.operator, now
    )
    if not success:
        return JSONResponse(status_code=status_code, content={"detail": message})
    return JSONResponse(content={"status": "OK", "incident": inc})

@app.get("/api/accuracy")
def get_accuracy_metrics():
    """Returns latest accuracy check metrics from results/accuracy_latest.json if available."""
    acc_path = os.path.join("results", "accuracy_latest.json")
    if not os.path.exists(acc_path):
        return JSONResponse(
            status_code=404,
            content={"status": "NOT_FOUND", "message": "No accuracy check run yet."}
        )
    try:
        import json
        with open(acc_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Error reading accuracy results file: {e}"}
        )

@app.get("/api/alerts")
def get_alerts():
    """Returns currently active incidents and recent alert log history."""
    return {
        "active_incidents": list(engine.alert_manager.active_incidents.values()),
        "recent_history": engine.alert_manager.alerts_history
    }

@app.get("/api/history")
def get_history():
    """Returns short-term history for frontend trend charts."""
    state = engine.latest_state
    zones = state.get("zones", [])
    people_count = state.get("people_count", 0)
    max_density = state.get("density", {}).get("max", 0)

    return {
        "timestamp": time.strftime("%H:%M:%S"),
        "people_count": people_count,
        "max_cell_density": max_density,
        "zones": zones
    }

# ────────────────── Frontend Static Files & Web Interface ──────────────────
frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Frontend")

if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

@app.on_event("shutdown")
def shutdown_event():
    logger.info("Shutting down CrowdSense server...")
    engine.release()

if __name__ == "__main__":
    import uvicorn
    port = cli_args.port
    host = cli_args.host
    url = f"http://localhost:{port}"

    print("\n" + "=" * 60)
    print(" 🛡️  CROWDSENSE — PROACTIVE CROWD SAFETY PLATFORM")
    print(f" Status: SERVER READY")
    print(f" Demo Mode: {'ENABLED' if is_demo else 'DISABLED'}")
    print(f" Access Dashboard URL: {url}")
    print("=" * 60 + "\n")

    uvicorn.run(app, host=host, port=port, log_level="info")