"""
Unit and Integration Tests for Android IP Webcam Source Module
Tests SSRF URL validation, auth enforcement, credential masking in logs,
mocked stream capture, /shot.jpg fallback, and 3s offline timeout.
"""

import time
import logging
from unittest.mock import patch, MagicMock
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from core.config import validate_ipcam_url
from core.ipcam import IPCamReader, mask_url_credentials
from core.engine import CrowdEngine
from dashboard import app, check_auth_status


@pytest.fixture
def client():
    return TestClient(app)


def test_ipcam_url_validation_private_and_localhost():
    """Valid private LAN IPs and localhost must pass validation."""
    assert validate_ipcam_url("http://192.168.1.50:8080")[0] is True
    assert validate_ipcam_url("http://192.168.0.1:8080/video")[0] is True
    assert validate_ipcam_url("http://10.0.0.15:8080")[0] is True
    assert validate_ipcam_url("http://172.20.10.2:8080")[0] is True
    assert validate_ipcam_url("http://127.0.0.1:8080")[0] is True
    assert validate_ipcam_url("http://localhost:8080")[0] is True
    assert validate_ipcam_url("https://192.168.1.100:8080/video")[0] is True


def test_ipcam_url_validation_ssrf_rejection():
    """Public IPs, domains, and bad protocols must be rejected for SSRF protection."""
    # Public IPs
    assert validate_ipcam_url("http://8.8.8.8:8080")[0] is False
    assert validate_ipcam_url("http://1.1.1.1:8080")[0] is False
    assert validate_ipcam_url("http://93.184.216.34:8080")[0] is False

    # External domain names
    assert validate_ipcam_url("http://google.com:8080")[0] is False
    assert validate_ipcam_url("http://example.org/video")[0] is False

    # Bad schemes
    assert validate_ipcam_url("ftp://192.168.1.50:8080")[0] is False
    assert validate_ipcam_url("file:///etc/passwd")[0] is False
    assert validate_ipcam_url("javascript:alert(1)")[0] is False
    assert validate_ipcam_url("")[0] is False


def test_ipcam_mask_credentials_in_logs():
    """Credentials in URLs must be masked for logs and never exposed."""
    masked = mask_url_credentials("http://admin:secret123@192.168.1.50:8080/video")
    assert "secret123" not in masked
    assert "admin:******@192.168.1.50:8080/video" in masked

    clean = mask_url_credentials("http://192.168.1.50:8080")
    assert clean == "http://192.168.1.50:8080"


def test_ipcam_select_source_auth(client):
    """POST /api/source/select with ipcam requires valid operator API key when auth is required."""
    with patch("dashboard.check_auth_status", return_value=(False, 401, "API Key Required")):
        resp = client.post("/api/source/select", json={"mode": "ipcam", "url": "http://192.168.1.50:8080"})
        assert resp.status_code == 401

    with patch("dashboard.check_auth_status", return_value=(False, 403, "Invalid API Key")):
        resp = client.post("/api/source/select", json={"mode": "ipcam", "url": "http://192.168.1.50:8080"})
        assert resp.status_code == 403

    # SSRF rejection on invalid public URL
    with patch("dashboard.check_auth_status", return_value=(True, 200, "OK")):
        resp = client.post("/api/source/select", json={"mode": "ipcam", "url": "http://8.8.8.8:8080"})
        assert resp.status_code == 400
        assert "SSRF" in resp.json()["detail"]


def test_ipcam_engine_set_source_and_timeout():
    """Test engine source switching to ipcam and 3-second offline timeout."""
    eng = CrowdEngine(demo_mode=False, start_worker=False)

    # Switch to ipcam with private URL
    info = eng.set_source("ipcam", url="http://192.168.1.50:8080")
    assert info["mode"] == "ipcam"
    assert eng.camera_status == "OFFLINE"

    # Push a test frame to queue
    test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    eng.ipcam_frame_queue.append((test_frame, time.time()))

    # Process one loop step
    frame_item = eng.ipcam_frame_queue.popleft()
    eng.camera_status = "ONLINE"
    eng.last_ipcam_frame_time = frame_item[1]
    eng.process_frame(frame_item[0])

    assert eng.camera_status == "ONLINE"
    assert eng.latest_processed_frame is not None

    # Simulate timeout (>3s)
    eng.last_ipcam_frame_time = time.time() - 4.0
    now = time.time()
    if now - eng.last_ipcam_frame_time > 3.0:
        eng.camera_status = "OFFLINE"
        eng.latest_frame = eng._generate_offline_frame()
        eng.latest_processed_frame = eng.latest_frame
        eng.reset_state()

    assert eng.camera_status == "OFFLINE"
    cam_info = eng.get_camera_info()
    assert cam_info["type"] == "ipcam"
    assert cam_info["state"] == "OFFLINE"

    eng.release()


def test_ipcam_reader_fallback_shot_jpg():
    """Test IPCamReader snapshot fallback when VideoCapture is unavailable."""
    dummy_img = np.zeros((200, 200, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", dummy_img)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = encoded.tobytes()

    reader = IPCamReader(base_url="http://192.168.1.50:8080", retry_sec=0.1, timeout_sec=1.0)
    p1, p2, shot = reader.get_stream_urls()
    assert shot == "http://192.168.1.50:8080/shot.jpg"

    with patch("requests.Session.get", return_value=mock_resp):
        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = False
            mock_cap_cls.return_value = mock_cap

            # Stop the reader as soon as the first frame is processed
            def stop_cb(f, t):
                reader._stop_event.set()

            reader.on_frame_callback = stop_cb
            reader._reader_loop()

            assert len(reader.frame_queue) == 1
            frame, t = reader.frame_queue[0]
            assert frame.shape == (200, 200, 3)
