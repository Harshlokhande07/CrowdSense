"""
Android IP Webcam Stream Reader Module
Connects to phone running Android IP Webcam app (or compatible MJPEG/JPEG stream),
validates LAN SSRF boundaries, captures frames into a size-1 drop-oldest queue,
and provides automatic fallback and reconnect capabilities.
"""

import time
import logging
import threading
import urllib.parse
from collections import deque
from typing import Optional, Callable, Dict, Any, Tuple
import cv2
import numpy as np
import requests

from core.config import (
    IPCAM_URL,
    IPCAM_PATH,
    IPCAM_USER,
    IPCAM_PASS,
    IPCAM_RETRY_SEC,
    IPCAM_TIMEOUT_SEC,
    validate_ipcam_url
)

logger = logging.getLogger("CrowdSense.IPCam")


def mask_url_credentials(url: str) -> str:
    """Masks username and password from URLs for safe logging."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username}:******@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        return url
    except Exception:
        return "***"


class IPCamReader:
    """
    Dedicated background reader thread for IP Webcam stream.
    Pushes incoming frames into a size-1 drop-oldest queue.
    """
    def __init__(
        self,
        base_url: str = IPCAM_URL,
        path: str = IPCAM_PATH,
        user: str = IPCAM_USER,
        password: str = IPCAM_PASS,
        frame_queue: Optional[deque] = None,
        retry_sec: float = IPCAM_RETRY_SEC,
        timeout_sec: float = IPCAM_TIMEOUT_SEC,
        on_frame_callback: Optional[Callable[[np.ndarray, float], None]] = None
    ):
        self.base_url = base_url.strip().rstrip("/")
        self.path = path.strip() if path.startswith("/") else f"/{path.strip()}"
        self.user = user.strip()
        self.password = password.strip()
        self.retry_sec = max(1.0, float(retry_sec))
        self.timeout_sec = max(1.0, float(timeout_sec))
        self.on_frame_callback = on_frame_callback

        # Size-1 drop-oldest queue shared with engine
        self.frame_queue: deque = frame_queue if frame_queue is not None else deque(maxlen=1)

        self.cap: Optional[cv2.VideoCapture] = None
        self.is_connected = False
        self.last_frame_time = 0.0
        self.status_message = "Connecting to phone..."

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def get_stream_urls(self) -> Tuple[str, str, str]:
        """Returns candidate URLs: (primary_mjpeg, secondary_mjpeg, snapshot_jpg)."""
        base = self.base_url
        p1 = f"{base}{self.path}"
        p2 = f"{base}/videofeed" if self.path != "/videofeed" else f"{base}/video"
        shot = f"{base}/shot.jpg"
        return p1, p2, shot

    def _format_auth_url(self, url: str) -> str:
        """Injects auth into URL string if credentials are provided."""
        if not self.user or not self.password:
            return url
        try:
            parsed = urllib.parse.urlparse(url)
            auth_netloc = f"{urllib.parse.quote(self.user)}:{urllib.parse.quote(self.password)}@{parsed.netloc}"
            return urllib.parse.urlunparse((parsed.scheme, auth_netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        except Exception:
            return url

    def start(self):
        """Starts background reader thread."""
        self.stop()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True, name="IPCamReader")
        self._thread.start()
        logger.info(f"IPCamReader started for {mask_url_credentials(self.base_url)}")

    def stop(self):
        """Stops background reader thread and releases all video resources."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

        with self._lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception as e:
                    logger.debug(f"Error releasing IPCam VideoCapture: {e}")
                self.cap = None
            self.is_connected = False
        logger.info("IPCamReader stopped clean.")

    def _reader_loop(self):
        """Continuous stream reading loop with MJPEG capture and /shot.jpg fallback."""
        session = requests.Session()
        if self.user and self.password:
            session.auth = (self.user, self.password)

        while not self._stop_event.is_set():
            # Validate URL before attempting connection
            valid, reason = validate_ipcam_url(self.base_url)
            if not valid:
                with self._lock:
                    self.is_connected = False
                    self.status_message = f"SSRF Guard: {reason}"
                logger.warning(f"IPCam URL rejected by SSRF guard: {reason}")
                time.sleep(self.retry_sec)
                continue

            primary_url, fallback_url, shot_url = self.get_stream_urls()
            connected_via_cv2 = False

            # 1. Try MJPEG stream via cv2.VideoCapture
            for candidate_url in (primary_url, fallback_url):
                if self._stop_event.is_set():
                    break
                auth_candidate_url = self._format_auth_url(candidate_url)
                logger.debug(f"Attempting MJPEG stream on {mask_url_credentials(candidate_url)}")

                cap = None
                try:
                    cap = cv2.VideoCapture(auth_candidate_url)
                    if cap.isOpened():
                        ret, test_frame = cap.read()
                        if ret and test_frame is not None and test_frame.size > 0:
                            with self._lock:
                                self.cap = cap
                                self.is_connected = True
                                self.status_message = "LIVE"
                                now = time.time()
                                self.last_frame_time = now
                                self.frame_queue.append((test_frame, now))

                            if self.on_frame_callback:
                                try:
                                    self.on_frame_callback(test_frame, now)
                                except Exception as cb_err:
                                    logger.debug(f"Frame callback error: {cb_err}")

                            connected_via_cv2 = True
                            logger.info(f"Connected to IP Webcam MJPEG stream on {mask_url_credentials(candidate_url)}")
                            break
                        else:
                            cap.release()
                    else:
                        cap.release()
                except Exception as e:
                    logger.debug(f"VideoCapture attempt failed for {mask_url_credentials(candidate_url)}: {e}")
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass

            # 2. Continuous read while cv2 capture is healthy
            if connected_via_cv2:
                while not self._stop_event.is_set():
                    with self._lock:
                        active_cap = self.cap

                    if active_cap is None or not active_cap.isOpened():
                        break

                    try:
                        ret, frame = active_cap.read()
                    except Exception as read_err:
                        logger.warning(f"Error reading frame from IPCam: {read_err}")
                        ret, frame = False, None

                    if not ret or frame is None or frame.size == 0:
                        logger.warning(f"IPCam MJPEG stream disconnected from {mask_url_credentials(self.base_url)}")
                        break

                    now = time.time()
                    with self._lock:
                        self.is_connected = True
                        self.status_message = "LIVE"
                        self.last_frame_time = now
                        self.frame_queue.append((frame, now))

                    if self.on_frame_callback:
                        try:
                            self.on_frame_callback(frame, now)
                        except Exception as cb_err:
                            logger.debug(f"Frame callback error: {cb_err}")

                    time.sleep(0.01)

                with self._lock:
                    if self.cap is not None:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                        self.cap = None
                    self.is_connected = False
                    self.status_message = "Connecting to phone..."

            # 3. Fallback: Poll /shot.jpg if MJPEG failed or dropped
            if not self._stop_event.is_set():
                logger.debug(f"Attempting /shot.jpg snapshot fallback on {mask_url_credentials(shot_url)}")
                try:
                    resp = session.get(shot_url, timeout=self.timeout_sec, allow_redirects=False)
                    if resp.status_code == 200 and resp.content:
                        img_arr = np.frombuffer(resp.content, dtype=np.uint8)
                        frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
                        if frame is not None and frame.size > 0:
                            now = time.time()
                            with self._lock:
                                self.is_connected = True
                                self.status_message = "LIVE"
                                self.last_frame_time = now
                                self.frame_queue.append((frame, now))

                            if self.on_frame_callback:
                                try:
                                    self.on_frame_callback(frame, now)
                                except Exception as cb_err:
                                    logger.debug(f"Frame callback error: {cb_err}")
                            time.sleep(0.05)
                            continue
                except Exception as shot_err:
                    logger.debug(f"Snapshot poll failed for {mask_url_credentials(shot_url)}: {shot_err}")

            if not self._stop_event.is_set():
                with self._lock:
                    self.is_connected = False
                    self.status_message = "CAMERA OFFLINE - check phone Wi-Fi / IP Webcam app running"
                time.sleep(self.retry_sec)

        session.close()

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns snapshot telemetry for health reporting."""
        with self._lock:
            now = time.time()
            age = round(now - self.last_frame_time, 2) if self.last_frame_time > 0 else None
            return {
                "type": "ipcam",
                "state": "LIVE" if (self.is_connected and age is not None and age <= 3.0) else "OFFLINE",
                "last_frame_age_sec": age,
                "status_message": self.status_message,
                "base_url": mask_url_credentials(self.base_url)
            }
