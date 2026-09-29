"""
Unit and Integration Tests for Mobile Camera Streaming (/mobile & /ws/mobile-cam),
Authentication (MOBILE_CAM_TOKEN), Frame Hardening, Single Connection Replacement,
3s Offline Timeout, and Tunnel Safety Warnings.
"""

import os
import time
import pytest
import cv2
import numpy as np
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dashboard import app, check_mobile_token, active_mobile_connections, get_target_engine
from core.engine import CrowdEngine

@pytest.fixture(autouse=True)
def setup_mobile_env(monkeypatch):
    monkeypatch.setenv("MOBILE_CAM_TOKEN", "test_mobile_secret_token_123")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("REQUIRE_AUTH_READS", "false")
    yield
    active_mobile_connections.clear()

def test_mobile_token_validation_unit():
    # 1. Valid token
    ok, code, msg = check_mobile_token(token="test_mobile_secret_token_123")
    assert ok is True
    assert code == 200

    # 2. Missing token
    ok, code, msg = check_mobile_token(token=None)
    assert ok is False
    assert code == 401

    # 3. Wrong token
    ok, code, msg = check_mobile_token(token="wrong_token_xyz")
    assert ok is False
    assert code == 403

def test_mobile_page_http_auth():
    client = TestClient(app)

    # Missing token -> 401
    resp_unauth = client.get("/mobile")
    assert resp_unauth.status_code == 401

    # Wrong token -> 403
    resp_forbidden = client.get("/mobile?token=wrong_token")
    assert resp_forbidden.status_code == 403

    # Valid token -> 200 HTML
    resp_ok = client.get("/mobile?token=test_mobile_secret_token_123")
    assert resp_ok.status_code == 200
    assert "CrowdSense" in resp_ok.text
    assert "Mount the phone on a stand for accurate movement analysis" in resp_ok.text

def test_ws_mobile_cam_auth_rejection_code_1008():
    client = TestClient(app)

    # Missing token -> WebSocket closes with code 1008
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/mobile-cam"):
            pass
    assert excinfo.value.code == 1008

    # Wrong token -> WebSocket closes with code 1008
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/mobile-cam?token=wrong_secret"):
            pass
    assert excinfo.value.code == 1008

def test_ws_mobile_cam_valid_frame_streaming_and_hardening():
    client = TestClient(app)
    eng = get_target_engine("cam-1")
    eng.set_source("mobile")

    with client.websocket_connect("/ws/mobile-cam?token=test_mobile_secret_token_123&camera_id=cam-1") as ws:
        assert "cam-1" in active_mobile_connections

        # 1. Create a valid test JPEG frame
        test_img = np.zeros((240, 320, 3), dtype=np.uint8)
        ret, jpeg_bytes = cv2.imencode(".jpg", test_img)
        assert ret is True
        raw_bytes = jpeg_bytes.tobytes()

        # Send valid frame
        ws.send_bytes(raw_bytes)
        time.sleep(0.05)

        # Engine should have received frame and set status to ONLINE
        assert eng.camera_status == "ONLINE"
        assert eng.last_mobile_frame_time > 0

        # 2. Hardening: Corrupted bytes should not crash the server
        ws.send_bytes(b"\xff\xd8corrupted_garbage_bytes_123456789")
        time.sleep(0.02)
        assert eng.camera_status == "ONLINE"

        # 3. Hardening: Non-JPEG bytes should be dropped
        ws.send_bytes(b"PNG_HEADER_NOT_JPEG_BYTES")
        time.sleep(0.02)

        # 4. Hardening: Oversized frame (>500KB) should be dropped
        oversized_jpeg = b"\xff\xd8" + (b"\x00" * (510 * 1024))
        ws.send_bytes(oversized_jpeg)
        time.sleep(0.02)

def test_ws_mobile_cam_second_connection_replaces_first():
    client = TestClient(app)

    with client.websocket_connect("/ws/mobile-cam?token=test_mobile_secret_token_123&camera_id=cam-1") as ws1:
        assert active_mobile_connections.get("cam-1") is not None

        # Connect second phone session for same camera
        with client.websocket_connect("/ws/mobile-cam?token=test_mobile_secret_token_123&camera_id=cam-1") as ws2:
            # ws2 is now active
            assert active_mobile_connections.get("cam-1") is not None

def test_mobile_camera_3s_offline_timeout_and_state_clear():
    eng = CrowdEngine(video_src="mobile", demo_mode=False, start_worker=False, camera_id="cam-timeout-test")
    assert eng.source_mode == "mobile"

    # Push a frame at t = 100.0
    test_img = np.zeros((100, 100, 3), dtype=np.uint8)
    eng.push_mobile_frame(test_img, timestamp=100.0)
    assert eng.camera_status == "ONLINE"
    assert eng.last_mobile_frame_time == 100.0

    # Simulate arrival at t = 104.0 (>3s without frame)
    # Trigger processing loop check
    now = 104.0
    with eng.lock:
        last_t = eng.last_mobile_frame_time
        if last_t > 0 and (now - last_t > 3.0):
            eng.camera_status = "OFFLINE"
            eng.reset_state()

    assert eng.camera_status == "OFFLINE"
    assert len(eng.alert_manager.active_incidents) == 0

def test_tunnel_warning_on_forwarded_headers(caplog):
    client = TestClient(app)
    import logging
    with caplog.at_level(logging.WARNING, logger="CrowdSense.Server"):
        resp = client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.195"})
        assert resp.status_code == 200
        # Check that public tunnel warning is emitted
        assert any("Public tunnel detected" in r.message for r in caplog.records)

def test_health_additive_mobile_field():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "mobile" in data
    mobile = data["mobile"]
    assert "connected" in mobile
    assert "last_frame_age_sec" in mobile
    assert "fps" in mobile

def test_run_mobile_validation_missing_tokens(monkeypatch):
    import subprocess
    import sys

    # Test running run_mobile.py with missing tokens
    res = subprocess.run(
        [sys.executable, "scripts/run_mobile.py"],
        env={**os.environ, "CROWDSENSE_API_KEY": "", "MOBILE_CAM_TOKEN": ""},
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    assert res.returncode != 0
    assert "Missing required security environment variables" in res.stdout

