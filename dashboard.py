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
import numpy as np
import hmac
from typing import Set, Optional, Tuple, List, Dict, Any
from collections import deque
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
    WS_BROADCAST_HZ, API_AUTH_KEY, CROWDSENSE_API_KEY,
    MOBILE_CAM_TOKEN, REQUIRE_AUTH_READS, CAMERAS,
    IPCAM_URL, validate_ipcam_url
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

# Initialize Camera Pipelines (Multi-Camera registry)
cameras_registry: Dict[str, CrowdEngine] = {}
for cam_cfg in CAMERAS:
    c_id = cam_cfg.get("id", "cam-1")
    c_name = cam_cfg.get("name", "Main Camera")
    c_src = cam_cfg.get("source", VIDEO_SRC)
    cameras_registry[c_id] = CrowdEngine(
        video_src=c_src,
        demo_mode=is_demo,
        camera_id=c_id,
        camera_name=c_name
    )

# Primary default engine for single-camera backward compatibility
engine = cameras_registry.get("cam-1") or list(cameras_registry.values())[0]

def get_target_engine(camera_id: Optional[str] = None) -> CrowdEngine:
    if camera_id and camera_id in cameras_registry:
        return cameras_registry[camera_id]
    return engine

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

# Active WebSocket Clients Set & Mobile Camera Connections
active_websockets: Set[WebSocket] = set()
active_mobile_connections: Dict[str, WebSocket] = {}

# Rate limiting tracker for /api/notify/test (5 calls per 60s)
_test_notify_rate_limit_history: deque = deque(maxlen=20)
_rate_limit_lock = threading.Lock()

# Rate limiting tracker for /api/camera/start and /api/camera/stop (10 calls per 60s)
_camera_toggle_rate_limit_history: deque = deque(maxlen=20)
_camera_toggle_lock = threading.Lock()

def check_camera_toggle_rate_limit() -> bool:
    """Rate limits camera start/stop toggles to max 10 calls per 60 seconds."""
    with _camera_toggle_lock:
        now = time.time()
        while _camera_toggle_rate_limit_history and (now - _camera_toggle_rate_limit_history[0] > 60.0):
            _camera_toggle_rate_limit_history.popleft()
        if len(_camera_toggle_rate_limit_history) >= 10:
            return False
        _camera_toggle_rate_limit_history.append(now)
        return True

_tunnel_warning_logged = False

@app.middleware("http")
async def tunnel_security_middleware(request: Request, call_next):
    global _tunnel_warning_logged
    if not _tunnel_warning_logged and not REQUIRE_AUTH_READS:
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("x-forwarded-proto")
        if forwarded:
            _tunnel_warning_logged = True
            logger.warning(
                "[WARNING] Public tunnel detected (X-Forwarded-For present) with REQUIRE_AUTH_READS=False. "
                "/video/feed and /api/state are publicly readable. Set REQUIRE_AUTH_READS=true in production."
            )
    response = await call_next(request)
    return response

def get_auth_status_for_health() -> str:
    auth_key = (os.getenv("CROWDSENSE_API_KEY") or os.getenv("API_AUTH_KEY") or CROWDSENSE_API_KEY or "").strip()
    if auth_key:
        return "ENABLED"
    if is_demo or (hasattr(engine, 'demo_mode') and engine.demo_mode):
        return "DEMO - AUTH OFF"
    return "FAIL_CLOSED"

def check_auth_status(
    token: Optional[str] = None,
    key: Optional[str] = None,
    header_key: Optional[str] = None,
    auth_header: Optional[str] = None
) -> Tuple[bool, int, str]:
    """
    Validates API authentication token using constant-time hmac.compare_digest.
    Returns (is_authorized, status_code, message).
    Never logs secret key values.
    """
    auth_key = (os.getenv("CROWDSENSE_API_KEY") or os.getenv("API_AUTH_KEY") or CROWDSENSE_API_KEY or "").strip()
    supplied_key = key or token or header_key
    if not supplied_key and auth_header:
        if auth_header.startswith("Bearer "):
            supplied_key = auth_header[7:].strip()
        else:
            supplied_key = auth_header.strip()

    demo_active = is_demo or (hasattr(engine, 'demo_mode') and engine.demo_mode) or (os.getenv("DEMO_MODE", "false").lower() in ("true", "1"))
    if not auth_key:
        if demo_active:
            return True, 200, "OK (Demo Open Access)"
        return False, 401, "Unauthorized: Missing API key. System is in fail-closed mode."

    if not supplied_key:
        return False, 401, "Unauthorized: Missing API key. Provide ?key=, ?token=, X-API-Key header, or Bearer token."

    # Constant-time comparison to prevent timing attacks
    if hmac.compare_digest(supplied_key.encode("utf-8"), auth_key.encode("utf-8")):
        return True, 200, "OK"

    return False, 403, "Forbidden: Invalid API key."

def check_mobile_token(
    token: Optional[str] = None,
    header_token: Optional[str] = None
) -> Tuple[bool, int, str]:
    """
    Validates mobile camera token using constant-time hmac.compare_digest.
    Used only by GET /mobile and WS /ws/mobile-cam.
    Never logs secret token values.
    """
    configured_token = os.getenv("MOBILE_CAM_TOKEN", MOBILE_CAM_TOKEN).strip()
    supplied = token or header_token
    demo_active = is_demo or (hasattr(engine, 'demo_mode') and engine.demo_mode) or (os.getenv("DEMO_MODE", "false").lower() in ("true", "1"))

    if not configured_token:
        if demo_active:
            return True, 200, "OK (Demo Open Access)"
        return False, 401, "Unauthorized: Missing MOBILE_CAM_TOKEN. System is in fail-closed mode."

    if not supplied:
        return False, 401, "Unauthorized: Missing mobile camera token. Provide ?token= or X-Mobile-Token header."

    if hmac.compare_digest(supplied.encode("utf-8"), configured_token.encode("utf-8")):
        return True, 200, "OK"

    return False, 403, "Forbidden: Invalid mobile camera token."

def check_auth(
    token: Optional[str] = None,
    key: Optional[str] = None,
    header_key: Optional[str] = None,
    auth_header: Optional[str] = None
) -> bool:
    """Boolean helper for backward compatibility."""
    authorized, _, _ = check_auth_status(token=token, key=key, header_key=header_key, auth_header=auth_header)
    return authorized

# ────────────────── WebSocket Endpoint ──────────────────
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None)
):
    token_param = key or token or websocket.query_params.get("key") or websocket.query_params.get("token")
    header_key = websocket.headers.get("x-api-key")
    auth_header = websocket.headers.get("authorization")
    authorized, status_code, msg = check_auth_status(token=token_param, header_key=header_key, auth_header=auth_header)
    if not authorized:
        await websocket.close(code=4003 if status_code == 403 else 4001)
        return

    await websocket.accept()
    active_websockets.add(websocket)
    logger.info(f"WebSocket client connected. Total clients: {len(active_websockets)}")

    target_cid = camera_id or websocket.query_params.get("camera_id")
    target_eng = get_target_engine(target_cid)

    sleep_interval = 1.0 / max(WS_BROADCAST_HZ, 1.0)

    try:
        while True:
            # Broadcast current engine state
            state_data = target_eng.latest_state
            if state_data:
                await websocket.send_json(state_data)

            await asyncio.sleep(sleep_interval)
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
        logger.info(f"WebSocket client disconnected. Remaining clients: {len(active_websockets)}")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        active_websockets.discard(websocket)

# ────────────────── Mobile Camera Web Endpoints ──────────────────
@app.get("/mobile", response_class=HTMLResponse)
def get_mobile_page(
    token: Optional[str] = Query(None),
    x_mobile_token: Optional[str] = Header(None)
):
    """Serves the mobile camera streamer interface."""
    authorized, status_code, msg = check_mobile_token(token=token, header_token=x_mobile_token)
    if not authorized:
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Unauthorized - CrowdSense Mobile</title>
            <style>body {{ font-family: sans-serif; background: #0F172A; color: #F8FAFC; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }}</style>
            </head>
            <body>
                <div>
                    <h2>🔒 Access Restricted</h2>
                    <p>{msg}</p>
                    <p style="color: #94A3B8; font-size: 14px;">Provide a valid mobile token: <code>/mobile?token=&lt;MOBILE_CAM_TOKEN&gt;</code></p>
                </div>
            </body>
            </html>
            """,
            status_code=status_code
        )
    mobile_file_path = os.path.join("Frontend", "mobile.html")
    if os.path.exists(mobile_file_path):
        with open(mobile_file_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h2>Mobile camera interface not found.</h2>", status_code=404)

@app.websocket("/ws/mobile-cam")
async def websocket_mobile_cam(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None)
):
    """
    WebSocket endpoint for mobile camera frame ingestion.
    - Authenticates via check_mobile_token (closes with code 1008 on failure).
    - Ensures only one active phone connection per camera (new replaces old).
    - Rate limits incoming frames to ~12 FPS.
    - Enforces max frame size of 500 KB and JPEG format check.
    - Decodes safely inside try/except.
    """
    token_param = token or websocket.query_params.get("token")
    header_token = websocket.headers.get("x-mobile-token")
    authorized, status_code, msg = check_mobile_token(token=token_param, header_token=header_token)
    if not authorized:
        await websocket.close(code=1008, reason=msg)
        return

    await websocket.accept()

    target_cid = camera_id or websocket.query_params.get("camera_id") or "cam-1"
    target_eng = get_target_engine(target_cid)

    # Ensure only one active phone connection per camera: close old connection
    if target_cid in active_mobile_connections:
        old_ws = active_mobile_connections.pop(target_cid, None)
        if old_ws is not None:
            try:
                await old_ws.close(code=1000, reason="New mobile connection replaced previous session")
            except Exception:
                pass

    active_mobile_connections[target_cid] = websocket
    logger.info(f"Mobile camera connection established for '{target_cid}'.")

    last_processed_time = 0.0
    min_frame_interval = 1.0 / 14.0  # Rate limit to ~12-14 FPS

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"]:
                data = message["bytes"]
            elif "text" in message and message["text"]:
                import base64
                text_data = message["text"]
                if "," in text_data:
                    text_data = text_data.split(",", 1)[1]
                try:
                    data = base64.b64decode(text_data)
                except Exception:
                    continue
            else:
                continue

            now = time.time()
            if (now - last_processed_time) < min_frame_interval:
                continue

            # Hardening: Frame size limit (500 KB)
            if len(data) > 500 * 1024:
                logger.warning(f"Dropped oversized mobile frame ({len(data)} bytes > 500KB)")
                continue

            # Hardening: Reject non-JPEG bytes (JPEG starts with 0xFF 0xD8)
            if len(data) < 4 or data[:2] != b"\xff\xd8":
                logger.warning("Dropped non-JPEG mobile frame")
                continue

            # Hardening: Safe decode in try/except
            try:
                np_arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is None or frame.size == 0:
                    continue
            except Exception as e:
                logger.warning(f"Error decoding mobile camera frame: {e}")
                continue

            # Timestamp: Server receive time
            target_eng.push_mobile_frame(frame, timestamp=now)
            last_processed_time = now

    except WebSocketDisconnect:
        logger.info(f"Mobile camera disconnected for '{target_cid}'.")
    except Exception as e:
        logger.error(f"Mobile camera connection error: {e}")
    finally:
        if active_mobile_connections.get(target_cid) == websocket:
            active_mobile_connections.pop(target_cid, None)

# ────────────────── Video Stream Endpoint ──────────────────
@app.get("/video/feed")
def video_feed(camera_id: Optional[str] = Query(None)):
    """MJPEG Video Stream Endpoint supporting multi-camera feeds."""
    target_eng = get_target_engine(camera_id)

    def frame_generator():
        while True:
            frame = target_eng.latest_processed_frame
            if frame is None or frame.size == 0:
                if target_eng.demo_mode:
                    frame = target_eng._generate_synthetic_frame()
                elif not target_eng.camera_enabled:
                    frame = target_eng._generate_stopped_frame()
                else:
                    frame = target_eng._generate_offline_frame()
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
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Uploads a video file (.mp4, .avi, .mov), validates type, size, safe decode, and switches engine source."""
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

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

    # Clean up any previous uploads to prevent disk exhaustion
    try:
        for f in os.listdir(upload_dir):
            fp = os.path.join(upload_dir, f)
            if os.path.isfile(fp) and (time.time() - os.path.getmtime(fp) > 3600):
                os.remove(fp)
    except Exception as e:
        logger.debug(f"Upload dir cleanup warning: {e}")

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


@app.post("/api/camera/start")
def start_camera_endpoint(
    camera_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Starts/enables camera capture stream for requested camera (idempotent, rate-limited)."""
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

    if not check_camera_toggle_rate_limit():
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded for camera toggle (max 10/min)."})

    target_eng = get_target_engine(camera_id)
    cam_info = target_eng.start_camera()
    return JSONResponse(content={"status": "OK", "camera": cam_info})


@app.post("/api/camera/stop")
def stop_camera_endpoint(
    camera_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Stops camera capture stream, releases hardware device, and resets state (rate-limited)."""
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

    if not check_camera_toggle_rate_limit():
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded for camera toggle (max 10/min)."})

    target_eng = get_target_engine(camera_id)
    cam_info = target_eng.stop_camera()
    return JSONResponse(content={"status": "OK", "camera": cam_info})


@app.post("/api/video/pause")
def pause_video_endpoint(
    camera_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Pauses video playback and inference processing for requested camera."""
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

    target_eng = get_target_engine(camera_id)
    res = target_eng.pause_video()
    return JSONResponse(content=res)


@app.post("/api/video/resume")
def resume_video_endpoint(
    camera_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Resumes video playback and inference processing for requested camera."""
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

    target_eng = get_target_engine(camera_id)
    res = target_eng.resume_video()
    return JSONResponse(content=res)


@app.post("/api/video/toggle-pause")
def toggle_pause_video_endpoint(
    camera_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Toggles video pause/resume state for requested camera."""
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

    target_eng = get_target_engine(camera_id)
    res = target_eng.toggle_pause()
    return JSONResponse(content=res)


@app.post("/api/source/select")
def select_source_mode(
    payload: dict,
    camera_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Selects input source mode ('demo', 'video', 'webcam', 'mobile', 'ipcam') and resets state."""
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

    mode = (payload.get("mode") or payload.get("source")) if isinstance(payload, dict) else None
    if mode not in ("demo", "video", "webcam", "mobile", "ipcam"):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid source mode. Allowed modes: demo, video, webcam, mobile, ipcam"}
        )

    target_eng = get_target_engine(camera_id)
    url = payload.get("url") if isinstance(payload, dict) else None
    if mode == "ipcam" and url:
        valid, reason = validate_ipcam_url(url)
        if not valid:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Invalid IP Webcam URL: {reason}"}
            )

    src_info = target_eng.set_source(mode, url=url)
    return JSONResponse({"status": "OK", "source": src_info})

@app.get("/api/health")
def get_health():
    """Returns system health and component connectivity status."""
    notifications = engine.alert_manager.get_system_notifications_status()
    uptime_sec = time.time() - start_time
    
    mob_connected = bool(len(active_mobile_connections) > 0)
    last_frame_t = getattr(engine, "last_mobile_frame_time", 0.0)
    last_frame_age = round(time.time() - last_frame_t, 2) if last_frame_t > 0 else None
    mob_fps = round(engine.current_fps, 1) if (engine.source_mode == "mobile" and engine.camera_status == "ONLINE") else 0.0

    mobile_info = {
        "connected": mob_connected,
        "last_frame_age_sec": last_frame_age,
        "fps": mob_fps
    }

    cam_info = engine.get_camera_info() if hasattr(engine, "get_camera_info") else {
        "source": engine.source_mode,
        "enabled": getattr(engine, "camera_enabled", True),
        "status": engine.camera_status,
        "fps": round(engine.current_fps, 1)
    }

    return {
        "status": "HEALTHY",
        "auth": get_auth_status_for_health(),
        "uptime_seconds": round(uptime_sec, 1),
        "demo_mode": engine.demo_mode,
        "camera": cam_info,
        "camera_status": engine.camera_status,
        "source": engine.get_source_info(),
        "model": engine.detector.status,
        "database": notifications["database"],
        "twilio": notifications["twilio"],
        "sms": notifications.get("sms", "DISABLED"),
        "ntfy": notifications["ntfy"],
        "fps": round(engine.current_fps, 1),
        "active_ws_clients": len(active_websockets),
        "mobile": mobile_info
    }

@app.get("/api/state")
def get_state(
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Returns latest complete engine state snapshot for requested camera."""
    if REQUIRE_AUTH_READS:
        authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
        if not authorized:
            return JSONResponse(status_code=status_code, content={"detail": msg})
    return get_target_engine(camera_id).latest_state

@app.get("/api/cameras")
def get_cameras(
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Returns list of configured camera feeds and their active statuses."""
    if REQUIRE_AUTH_READS:
        authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
        if not authorized:
            return JSONResponse(status_code=status_code, content={"detail": msg})
    return [
        {
            "id": c_id,
            "name": eng.camera_name,
            "status": eng.camera_status,
            "source": eng.video_src,
            "people_count": eng.latest_state.get("people_count", 0),
            "risk_level": eng.latest_state.get("risk", {}).get("level", "NORMAL")
        }
        for c_id, eng in cameras_registry.items()
    ]

@app.get("/api/venue/overview")
def get_venue_overview(
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Returns venue overview showing highest-risk zone across each camera source."""
    if REQUIRE_AUTH_READS:
        authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
        if not authorized:
            return JSONResponse(status_code=status_code, content={"detail": msg})

    overview = []
    for c_id, eng in cameras_registry.items():
        st = eng.latest_state
        zones = st.get("zones", [])
        highest_risk_z = max(zones, key=lambda z: z.get("risk_score", 0)) if zones else None
        overview.append({
            "camera_id": c_id,
            "camera_name": eng.camera_name,
            "status": eng.camera_status,
            "people_count": st.get("people_count", 0),
            "max_density": st.get("density", {}).get("max", 0),
            "risk_level": st.get("risk", {}).get("level", "NORMAL"),
            "highest_risk_zone": {
                "id": highest_risk_z.get("id") if highest_risk_z else None,
                "name": highest_risk_z.get("name") if highest_risk_z else "N/A",
                "risk_score": highest_risk_z.get("risk_score", 0) if highest_risk_z else 0,
                "level": highest_risk_z.get("level", "NORMAL") if highest_risk_z else "NORMAL"
            } if highest_risk_z else None
        })

    return {
        "total_cameras": len(overview),
        "cameras": overview,
        "max_venue_risk": max([c["highest_risk_zone"]["risk_score"] for c in overview if c["highest_risk_zone"]], default=0)
    }

class TestNotifyRequest(BaseModel):
    zone_id: Optional[str] = Field("ZONE_A", description="Target zone ID for test")
    message: Optional[str] = Field(None, description="Custom test message body (optional)")

@app.post("/api/notify/test")
def test_notification(
    payload: Optional[TestNotifyRequest] = None,
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """
    Protected test endpoint to trigger a sample Twilio SMS/WhatsApp alert without waiting for a real crowd surge.
    Rate limited to 5 requests per minute.
    """
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

    # Rate limiting: max 5 requests per 60 seconds
    now = time.time()
    with _rate_limit_lock:
        while _test_notify_rate_limit_history and now - _test_notify_rate_limit_history[0] > 60.0:
            _test_notify_rate_limit_history.popleft()
        if len(_test_notify_rate_limit_history) >= 5:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests: Test notification rate limit of 5 requests per minute exceeded."}
            )
        _test_notify_rate_limit_history.append(now)

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
        recommended_actions=["Verify phone reception"],
        demo_mode=engine.demo_mode
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
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Acknowledges an active incident with operator name and note."""
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

    now = time.time()
    success, resp_code, message, inc = engine.alert_manager.acknowledge_incident(
        incident_id, payload.operator, payload.note, now
    )
    if not success:
        return JSONResponse(status_code=resp_code, content={"detail": message})
    return JSONResponse(content={"status": "OK", "incident": inc})

@app.post("/api/incidents/{incident_id}/resolve")
def resolve_incident(
    incident_id: str,
    payload: ResolveRequest,
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Manually resolves an active incident with note."""
    authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
    if not authorized:
        return JSONResponse(status_code=status_code, content={"detail": msg})

    now = time.time()
    success, resp_code, message, inc = engine.alert_manager.resolve_incident(
        incident_id, payload.note, payload.operator, now
    )
    if not success:
        return JSONResponse(status_code=resp_code, content={"detail": message})
    return JSONResponse(content={"status": "OK", "incident": inc})

@app.get("/api/accuracy")
def get_accuracy_metrics(
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Returns latest accuracy check metrics from results/accuracy_latest.json if available."""
    if REQUIRE_AUTH_READS:
        authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
        if not authorized:
            return JSONResponse(status_code=status_code, content={"detail": msg})
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
def get_alerts(
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Returns currently active incidents and recent alert log history."""
    if REQUIRE_AUTH_READS:
        authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
        if not authorized:
            return JSONResponse(status_code=status_code, content={"detail": msg})
    return {
        "active_incidents": list(engine.alert_manager.active_incidents.values()),
        "recent_history": engine.alert_manager.alerts_history
    }

@app.get("/api/history")
def get_history(
    token: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """Returns short-term history for frontend trend charts."""
    if REQUIRE_AUTH_READS:
        authorized, status_code, msg = check_auth_status(token=token, key=key, header_key=x_api_key, auth_header=authorization)
        if not authorized:
            return JSONResponse(status_code=status_code, content={"detail": msg})
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
    for eng in cameras_registry.values():
        eng.release()

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