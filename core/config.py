"""
CrowdSense Configuration Module
Loads environment variables, defines prototype risk thresholds, zone cell-range groups, and system defaults.
"""

import os
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
MODEL_PATH: str = os.getenv("MODEL_PATH", "yolov8n.pt")
CONF_THRESHOLD: float = float(os.getenv("CONF_THRESHOLD", os.getenv("CONFIDENCE_THRESHOLD", "0.35")))
INFERENCE_RESIZE_WIDTH: int = int(os.getenv("INFERENCE_RESIZE_WIDTH", "640"))
GRID_SIZE: int = int(os.getenv("GRID_SIZE", "8"))
DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")

# Prototype Risk Thresholds (Cell density person counts)
# Note: Labelled as prototype risk thresholds. All alerts require human verification.
DENSITY_NORMAL_MAX: int = int(os.getenv("DENSITY_NORMAL_MAX", "2"))
DENSITY_ELEVATED_MAX: int = int(os.getenv("DENSITY_ELEVATED_MAX", "4"))
DENSITY_HIGH_MAX: int = int(os.getenv("DENSITY_HIGH_MAX", "6"))
# Count >= 7 is CRITICAL

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

TWILIO_SID: str = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN: str = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM: str = os.getenv("TWILIO_FROM", "")
TWILIO_TO: str = os.getenv("TWILIO_TO", os.getenv("ALERT_PHONE", ""))
ALERT_PHONE: str = TWILIO_TO

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
PREDICTION_HISTORY_WINDOW_SEC: float = float(os.getenv("PREDICTION_HISTORY_WINDOW_SEC", "45.0"))  # 45-60s window
PREDICTION_HORIZON_SEC: float = float(os.getenv("PREDICTION_HORIZON_SEC", "30.0"))  # 15-30s horizon
