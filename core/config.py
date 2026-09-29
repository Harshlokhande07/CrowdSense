"""
CrowdSense Configuration Module
Loads environment variables, defines prototype risk thresholds, zone cell-range groups, and system defaults.
"""

import os
import re
import json
import ipaddress
import urllib.parse
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Server Settings
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
CORS_ORIGINS: List[str] = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if origin.strip()
]

# Computer Vision & Detection
VIDEO_SRC: str = os.getenv("VIDEO_SRC", "crowd.mp4")
YOLO_MODEL: str = os.getenv("YOLO_MODEL", os.getenv("MODEL_PATH", "yolov8n.pt"))
MODEL_PATH: str = YOLO_MODEL
CONF_THRESHOLD: float = float(os.getenv("CONF_THRESHOLD", os.getenv("CONFIDENCE_THRESHOLD", "0.35")))
YOLO_IMGSZ: int = int(os.getenv("YOLO_IMGSZ", os.getenv("INFERENCE_IMGSZ", os.getenv("INFERENCE_RESIZE_WIDTH", "640"))))
INFERENCE_RESIZE_WIDTH: int = YOLO_IMGSZ
INFERENCE_IMGSZ: int = YOLO_IMGSZ
GRID_SIZE: int = int(os.getenv("GRID_SIZE", "8"))
DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")

# Prototype Risk Threshold Profiles (Cell density person counts)
# Note: Labelled as prototype risk thresholds. All alerts require human verification.
PROD_DENSITY_THRESHOLDS: Dict[str, int] = {
    "DENSITY_NORMAL_MAX": int(os.getenv("DENSITY_NORMAL_MAX", "2")),
    "DENSITY_ELEVATED_MAX": int(os.getenv("DENSITY_ELEVATED_MAX", "4")),
    "DENSITY_HIGH_MAX": int(os.getenv("DENSITY_HIGH_MAX", "6")),
    "CRITICAL_CELL_CONCENTRATION": 7
}

DEMO_DENSITY_THRESHOLDS: Dict[str, int] = {
    "DENSITY_NORMAL_MAX": 1,
    "DENSITY_ELEVATED_MAX": 2,
    "DENSITY_HIGH_MAX": 3,
    "CRITICAL_CELL_CONCENTRATION": 4
}

def get_density_thresholds(demo_mode: bool = False) -> Dict[str, int]:
    """Returns active density threshold profile (DEMO vs PRODUCTION)."""
    return DEMO_DENSITY_THRESHOLDS if demo_mode else PROD_DENSITY_THRESHOLDS

# Backward-compatible production constants
DENSITY_NORMAL_MAX: int = PROD_DENSITY_THRESHOLDS["DENSITY_NORMAL_MAX"]
DENSITY_ELEVATED_MAX: int = PROD_DENSITY_THRESHOLDS["DENSITY_ELEVATED_MAX"]
DENSITY_HIGH_MAX: int = PROD_DENSITY_THRESHOLDS["DENSITY_HIGH_MAX"]
CRITICAL_CELL_CONCENTRATION: int = PROD_DENSITY_THRESHOLDS["CRITICAL_CELL_CONCENTRATION"]

# Movement & Stagnation Constraints
MIN_ZONE_COUNT_FOR_MOVEMENT: int = int(os.getenv("MIN_ZONE_COUNT_FOR_MOVEMENT", "3"))

# Growth Rate & Edge Filtering Parameters
GROWTH_WINDOW_SEC: float = float(os.getenv("GROWTH_WINDOW_SEC", "5.0"))  # Window of at least 5s
GROWTH_RATE_RAPID_PER_SEC: float = float(os.getenv("GROWTH_RATE_RAPID_PER_SEC", "0.8"))  # 0.8 people/s
GROWTH_RATE_MODERATE_PER_SEC: float = float(os.getenv("GROWTH_RATE_MODERATE_PER_SEC", "0.4"))  # 0.4 people/s
FRAME_EDGE_MARGIN_NORM: float = float(os.getenv("FRAME_EDGE_MARGIN_NORM", "0.06"))  # 6% margin from frame edge

# Zone Definitions (Editable cell-range groupings on 8x8 grid)
ZONES_CONFIG: List[Dict[str, Any]] = [
    {
        "id": "ZONE_A",
        "name": "Gate 3 Entry (NW)",
        "col_range": (0, 3),
        "row_range": (0, 3)
    },
    {
        "id": "ZONE_B",
        "name": "Main Concourse (NE)",
        "col_range": (4, 7),
        "row_range": (0, 3)
    },
    {
        "id": "ZONE_C",
        "name": "East Lane Merge (SW)",
        "col_range": (0, 3),
        "row_range": (4, 7)
    },
    {
        "id": "ZONE_D",
        "name": "West Exit Area (SE)",
        "col_range": (4, 7),
        "row_range": (4, 7)
    }
]

# Alerts & Notification Integrations
NTFY_TOPIC: str = os.getenv("NTFY_TOPIC", "crowdsense_demo_alerts")
ENABLE_MOBILE_ALERT: bool = os.getenv("ENABLE_MOBILE_ALERT", "true").lower() in ("true", "1", "yes")

# ────────────────── Twilio Multi-Channel SMS / WhatsApp Configuration ──────────────────
import re
import json
import logging
config_logger = logging.getLogger("CrowdSense.Config")

TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", os.getenv("TWILIO_SID", "")).strip()
TWILIO_API_KEY_SID: str = os.getenv("TWILIO_API_KEY_SID", "").strip()
TWILIO_API_KEY_SECRET: str = os.getenv("TWILIO_API_KEY_SECRET", "").strip()
TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", os.getenv("TWILIO_TOKEN", "")).strip()

TWILIO_MESSAGING_SERVICE_SID: str = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "").strip()
TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", os.getenv("TWILIO_FROM", "")).strip()

# Priority sender determination
TWILIO_SENDER: str = TWILIO_MESSAGING_SERVICE_SID if TWILIO_MESSAGING_SERVICE_SID else TWILIO_FROM_NUMBER

# Backward-compatible aliases
TWILIO_SID: str = TWILIO_ACCOUNT_SID
TWILIO_TOKEN: str = TWILIO_AUTH_TOKEN
TWILIO_FROM: str = TWILIO_FROM_NUMBER

# Alert recipients
_raw_recipients = os.getenv("ALERT_PHONE_NUMBERS", os.getenv("TWILIO_TO", os.getenv("ALERT_PHONE", ""))).strip()
ALERT_PHONE_NUMBERS: List[str] = [
    num.strip() for num in _raw_recipients.split(",") if num.strip()
]
TWILIO_TO: str = ALERT_PHONE_NUMBERS[0] if ALERT_PHONE_NUMBERS else ""
ALERT_PHONE: str = TWILIO_TO

# Optional Zone-specific recipients mapping
_raw_zone_recipients = os.getenv("ZONE_RECIPIENTS", "").strip()
ZONE_RECIPIENTS: Dict[str, List[str]] = {}
if _raw_zone_recipients:
    try:
        parsed_zone_rec = json.loads(_raw_zone_recipients)
        if isinstance(parsed_zone_rec, dict):
            ZONE_RECIPIENTS = {str(k): list(v) for k, v in parsed_zone_rec.items()}
    except Exception as _e:
        config_logger.warning(f"Could not parse ZONE_RECIPIENTS JSON: {_e}")

SMS_MIN_LEVEL: str = os.getenv("SMS_MIN_LEVEL", "HIGH").upper().strip()
SMS_COOLDOWN_SEC: float = float(os.getenv("SMS_COOLDOWN_SEC", "30.0"))
SMS_SEND_RESOLVED: bool = os.getenv("SMS_SEND_RESOLVED", "true").lower() in ("true", "1", "yes")
TWILIO_CHANNEL: str = os.getenv("TWILIO_CHANNEL", "sms").lower().strip()
if TWILIO_CHANNEL not in ("sms", "whatsapp"):
    TWILIO_CHANNEL = "sms"

# Multi-Camera configuration (supports 1 to 4 cameras)
# Format in .env: CAMERAS='[{"id": "cam-1", "name": "Main Concourse", "source": "crowd.mp4"}, ...]'
_raw_cameras = os.getenv("CAMERAS", "").strip()
CAMERAS: List[Dict[str, Any]] = []
if _raw_cameras:
    try:
        parsed_cams = json.loads(_raw_cameras)
        if isinstance(parsed_cams, list) and len(parsed_cams) > 0:
            CAMERAS = parsed_cams
    except Exception as _e:
        config_logger.warning(f"Could not parse CAMERAS JSON: {_e}")

if not CAMERAS:
    CAMERAS = [
        {
            "id": "cam-1",
            "name": os.getenv("CAMERA_NAME", "Main Entrance Camera"),
            "source": VIDEO_SRC,
            "zones": ZONES_CONFIG
        }
    ]

def is_valid_e164(number: str) -> bool:
    """Validates international E.164 phone format (e.g. +12345678901)."""
    if not number:
        return False
    # Strip whatsapp: prefix if present for validation
    clean_num = number.replace("whatsapp:", "").strip()
    return bool(re.match(r"^\+[1-9]\d{6,14}$", clean_num))

def mask_phone_number(phone: str) -> str:
    """Masks phone number for privacy/observability logs, e.g. +91******1234."""
    if not phone:
        return "***"
    is_wa = phone.startswith("whatsapp:")
    clean = phone.replace("whatsapp:", "")
    if len(clean) <= 5:
        masked = "***"
    elif clean.startswith("+") and len(clean) >= 8:
        prefix = clean[:3]
        suffix = clean[-4:]
        masked = f"{prefix}******{suffix}"
    else:
        prefix = clean[:2]
        suffix = clean[-2:]
        masked = f"{prefix}****{suffix}"
    return f"whatsapp:{masked}" if is_wa else masked

# Check credential completeness
_has_auth = bool(TWILIO_ACCOUNT_SID and ((TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET) or TWILIO_AUTH_TOKEN))
_has_sender = bool(TWILIO_SENDER)
_has_recipients = bool(ALERT_PHONE_NUMBERS or ZONE_RECIPIENTS)

TWILIO_ENABLED: bool = bool(_has_auth and _has_sender and _has_recipients)

# Startup validation & diagnostic logging (NEVER logs secret values)
_missing_vars = []
if not TWILIO_ACCOUNT_SID:
    _missing_vars.append("TWILIO_ACCOUNT_SID")
if not (TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET) and not TWILIO_AUTH_TOKEN:
    _missing_vars.append("TWILIO_API_KEY_SID+TWILIO_API_KEY_SECRET or TWILIO_AUTH_TOKEN")
if not TWILIO_SENDER:
    _missing_vars.append("TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM_NUMBER")
if not _has_recipients:
    _missing_vars.append("ALERT_PHONE_NUMBERS")

if TWILIO_ENABLED:
    # Validate recipient numbers
    for _num in ALERT_PHONE_NUMBERS:
        if not is_valid_e164(_num):
            config_logger.warning(f"Configured ALERT_PHONE_NUMBER '{mask_phone_number(_num)}' is not in valid E.164 format (+[country][number]).")
    for _z, _nums in ZONE_RECIPIENTS.items():
        for _num in _nums:
            if not is_valid_e164(_num):
                config_logger.warning(f"Configured ZONE_RECIPIENTS for {_z} '{mask_phone_number(_num)}' is not in valid E.164 format.")
    _auth_type = "API Key" if (TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET) else "Auth Token"
    config_logger.info(f"Twilio Notifications ENABLED (Channel: {TWILIO_CHANNEL.upper()}, Auth: {_auth_type}, MinLevel: {SMS_MIN_LEVEL}).")
else:
    config_logger.info(f"Twilio Notifications DISABLED. Missing configuration variables: {', '.join(_missing_vars) if _missing_vars else 'None'}")

FIREBASE_KEY_PATH: str = os.getenv("FIREBASE_KEY_PATH", "")

# Upload & Incident Limits
MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
ALLOWED_UPLOAD_EXTENSIONS = {".mp4", ".avi", ".mov"}
MAX_OPERATOR_NAME_LEN: int = 40
MAX_NOTE_LEN: int = 200

# Video Processing & Pacing Config
PROCESS_EVERY_N_FRAMES: int = int(os.getenv("PROCESS_EVERY_N_FRAMES", "1"))
INFERENCE_IMGSZ: int = int(os.getenv("INFERENCE_IMGSZ", "640"))
MAX_PROCESS_FPS: float = float(os.getenv("MAX_PROCESS_FPS", "30.0"))
LOOP_VIDEO: bool = os.getenv("LOOP_VIDEO", "true").lower() in ("true", "1", "yes")

# Pipeline parameters
PERSISTENCE_REQUIRED_SEC: float = float(os.getenv("PERSISTENCE_REQUIRED_SEC", "8.0"))  # Default 8s bottleneck persistence
ALERT_COOLDOWN_SEC: float = float(os.getenv("ALERT_COOLDOWN_SEC", "30.0"))
DEESCALATION_HYSTERESIS_SEC: float = float(os.getenv("DEESCALATION_HYSTERESIS_SEC", "3.0"))
DEESCALATION_HYSTERESIS_MARGIN: float = float(os.getenv("DEESCALATION_HYSTERESIS_MARGIN", "5.0"))
PREDICTION_HISTORY_WINDOW_SEC: float = float(os.getenv("PREDICTION_HISTORY_WINDOW_SEC", "45.0"))  # 45-60s window
PREDICTION_HORIZON_SEC: float = float(os.getenv("PREDICTION_HORIZON_SEC", "30.0"))  # 15-30s horizon
R2_CONFIDENCE_THRESHOLD: float = float(os.getenv("R2_CONFIDENCE_THRESHOLD", "0.30"))

# Opposing Flow Parameters
OPPOSING_FLOW_MIN_SPEED: float = float(os.getenv("OPPOSING_FLOW_MIN_SPEED", "0.01"))  # 1.0 %/s
OPPOSING_FLOW_MIN_COUNT: int = int(os.getenv("OPPOSING_FLOW_MIN_COUNT", "4"))
OPPOSING_FLOW_ANGLE_DEG: float = float(os.getenv("OPPOSING_FLOW_ANGLE_DEG", "120.0"))

# Telemetry and Calibration
WS_BROADCAST_HZ: float = float(os.getenv("WS_BROADCAST_HZ", "8.0"))
CROWDSENSE_API_KEY: str = os.getenv("CROWDSENSE_API_KEY", os.getenv("API_AUTH_KEY", "")).strip()
API_AUTH_KEY: str = CROWDSENSE_API_KEY  # Backward-compatible alias
MOBILE_CAM_TOKEN: str = os.getenv("MOBILE_CAM_TOKEN", "").strip()
MOBILE_FPS: int = int(os.getenv("MOBILE_FPS", "10"))
REQUIRE_AUTH_READS: bool = os.getenv("REQUIRE_AUTH_READS", "false").lower() in ("true", "1", "yes")
CAMERA_CALIBRATION_POINTS: str = os.getenv("CAMERA_CALIBRATION_POINTS", "")

# Local Webcam Hardware Configuration
WEBCAM_INDEX: int = int(os.getenv("WEBCAM_INDEX", "0"))
WEBCAM_WIDTH: int = int(os.getenv("WEBCAM_WIDTH", "1280"))
WEBCAM_HEIGHT: int = int(os.getenv("WEBCAM_HEIGHT", "720"))
WEBCAM_FPS: int = int(os.getenv("WEBCAM_FPS", "30"))
WEBCAM_AUTOSTART: bool = os.getenv("WEBCAM_AUTOSTART", "true").lower() in ("true", "1", "yes")

# Android IP Webcam Source Configuration
IPCAM_URL: str = os.getenv("IPCAM_URL", "http://192.168.1.100:8080").strip()
IPCAM_PATH: str = os.getenv("IPCAM_PATH", "/video").strip()
IPCAM_USER: str = os.getenv("IPCAM_USER", "").strip()
IPCAM_PASS: str = os.getenv("IPCAM_PASS", "").strip()
IPCAM_RETRY_SEC: float = float(os.getenv("IPCAM_RETRY_SEC", "3.0"))
IPCAM_TIMEOUT_SEC: float = float(os.getenv("IPCAM_TIMEOUT_SEC", "5.0"))


def validate_ipcam_url(url: str) -> tuple[bool, str]:
    """
    Validates IP Webcam URL for SSRF protection:
    - Must be http:// or https://
    - Host must be private LAN IP (10.x, 172.16-31.x, 192.168.x) or localhost/127.0.0.1
    - Rejects public IPs and public domain names.
    Returns (is_valid, error_or_sanitized_url)
    """
    if not url:
        return False, "URL cannot be empty."

    url_str = url.strip()
    try:
        parsed = urllib.parse.urlparse(url_str)
    except Exception as e:
        return False, f"Invalid URL format: {e}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL missing valid host/IP."

    hostname_clean = hostname.strip().lower()
    if hostname_clean in ("localhost", "127.0.0.1", "::1"):
        return True, url_str

    try:
        ip_obj = ipaddress.ip_address(hostname_clean)
        if ip_obj.is_private or ip_obj.is_loopback:
            return True, url_str
        else:
            return False, f"SSRF Protection: Host IP '{hostname_clean}' is not a private LAN IP or localhost."
    except ValueError:
        return False, f"SSRF Protection: Host '{hostname_clean}' is not a valid private LAN IP address."


