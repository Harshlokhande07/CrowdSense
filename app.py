"""
CrowdSense — Application Entrypoint for Cloud / Vercel & Production Deployments.

NOTE ON SERVERLESS (Vercel / Cloud Functions):
In serverless environments lacking GPU acceleration, OpenCV video capture, and continuous background
worker threads, CrowdSense operates in synthetic demonstration / demo replay mode.
The live continuous computer-vision pipeline (YOLOv8 + RTSP / Hardware Capture + WebSocket Streaming)
must run on a dedicated VM, Docker host, or Edge IoT device (NVIDIA Jetson / x86 Server).
"""

import os
from dashboard import app

__all__ = ["app"]