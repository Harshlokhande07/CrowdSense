"""
Test suite for Local Webcam source and Camera ON/OFF controls.
Mocks cv2.VideoCapture so tests run headlessly and deterministically without physical hardware.
"""

import os
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from dashboard import app, engine, _camera_toggle_rate_limit_history
from core.engine import CrowdEngine

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_toggle_rate_limiter():
    """Resets the in-memory camera toggle rate limiter before each test."""
    _camera_toggle_rate_limit_history.clear()
    yield
    _camera_toggle_rate_limit_history.clear()


def test_camera_start_stop_auth_guards(monkeypatch):
    """Verifies that /api/camera/start and /api/camera/stop enforce API key auth."""
    monkeypatch.setenv("CROWDSENSE_API_KEY", "test_secret_key_123")
    monkeypatch.setenv("DEMO_MODE", "false")
    engine.demo_mode = False

    # 1. Missing key -> 401
    resp_start = client.post("/api/camera/start")
    assert resp_start.status_code == 401

    resp_stop = client.post("/api/camera/stop")
    assert resp_stop.status_code == 401

    # 2. Wrong key -> 403
    resp_start_wrong = client.post("/api/camera/start", headers={"X-API-Key": "wrong_key"})
    assert resp_start_wrong.status_code == 403

    resp_stop_wrong = client.post("/api/camera/stop", headers={"X-API-Key": "wrong_key"})
    assert resp_stop_wrong.status_code == 403

    # 3. Valid key -> 200
    resp_start_valid = client.post("/api/camera/start", headers={"X-API-Key": "test_secret_key_123"})
    assert resp_start_valid.status_code == 200
    assert resp_start_valid.json()["status"] == "OK"
    assert resp_start_valid.json()["camera"]["enabled"] is True

    resp_stop_valid = client.post("/api/camera/stop", headers={"X-API-Key": "test_secret_key_123"})
    assert resp_stop_valid.status_code == 200
    assert resp_stop_valid.json()["status"] == "OK"
    assert resp_stop_valid.json()["camera"]["enabled"] is False
    assert resp_stop_valid.json()["camera"]["status"] == "STOPPED"


def test_camera_start_idempotent(monkeypatch):
    """Verifies that calling start repeatedly is idempotent and safe."""
    monkeypatch.setenv("CROWDSENSE_API_KEY", "test_secret_key_123")
    headers = {"X-API-Key": "test_secret_key_123"}

    r1 = client.post("/api/camera/start", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["camera"]["enabled"] is True

    r2 = client.post("/api/camera/start", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["camera"]["enabled"] is True


def test_camera_stop_releases_capture_and_resets_state():
    """Verifies that stopping the camera releases the hardware capture and resets state."""
    eng = CrowdEngine(demo_mode=False, start_worker=False)
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    eng.cap = mock_cap
    eng.camera_status = "ONLINE"
    eng.camera_enabled = True

    # Artificially trigger an active incident to test reset
    eng.alert_manager.active_incidents["TEST_INC"] = {
        "incident_id": "TEST_INC",
        "zone_id": "ZONE_A",
        "zone_name": "Gate 3",
        "status": "ACTIVE"
    }

    info = eng.stop_camera()
    assert info["enabled"] is False
    assert info["status"] == "STOPPED"
    assert mock_cap.release.called
    assert eng.cap is None
    assert len(eng.alert_manager.active_incidents) == 0
    assert eng.latest_state["system"]["camera"] == "STOPPED"


def test_stopped_is_distinct_from_offline():
    """Verifies that STOPPED (deliberate user action) is distinct from OFFLINE (hardware/network fault)."""
    eng = CrowdEngine(demo_mode=False, start_worker=False)

    # 1. Stopped state
    eng.stop_camera()
    frame_stopped, ok_stopped = eng.read_frame()
    assert ok_stopped is False
    assert eng.camera_status == "STOPPED"
    assert eng.get_camera_info()["status"] == "STOPPED"

    # 2. Offline state (enabled but device failed to open)
    eng.camera_enabled = True
    eng.cap = None
    eng.camera_status = "OFFLINE"
    frame_offline, ok_offline = eng.read_frame()
    assert ok_offline is False
    assert eng.camera_status == "OFFLINE"
    assert eng.get_camera_info()["status"] == "OFFLINE"


def test_webcam_open_failure_sets_offline_and_retries():
    """Verifies that failed webcam open sets OFFLINE without crashing."""
    with patch("cv2.VideoCapture") as mock_vc:
        mock_instance = MagicMock()
        mock_instance.isOpened.return_value = False
        mock_vc.return_value = mock_instance

        eng = CrowdEngine(video_src="webcam", demo_mode=False, start_worker=False)
        assert eng.source_mode == "webcam"
        assert eng.camera_status == "OFFLINE"
        assert eng.cap is None


def test_api_health_camera_field_additive():
    """Verifies that /api/health contains the additive camera control dictionary."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "camera" in data
    assert isinstance(data["camera"], dict)
    assert "source" in data["camera"]
    assert "enabled" in data["camera"]
    assert "status" in data["camera"]
    assert "fps" in data["camera"]


def test_source_switch_releases_previous_capture():
    """Verifies that switching source releases any existing VideoCapture."""
    eng = CrowdEngine(demo_mode=False, start_worker=False)
    mock_cap = MagicMock()
    eng.cap = mock_cap

    eng.set_source("demo")
    assert mock_cap.release.called
    assert eng.source_mode == "demo"
    assert eng.camera_status == "DEMO_MODE"


def test_camera_toggle_rate_limiting(monkeypatch):
    """Verifies that toggling camera more than 10 times in 60s returns HTTP 429."""
    monkeypatch.setenv("CROWDSENSE_API_KEY", "test_secret_key_123")
    headers = {"X-API-Key": "test_secret_key_123"}

    # 10 successful toggles within rate limit
    for _ in range(10):
        resp = client.post("/api/camera/start", headers=headers)
        assert resp.status_code == 200

    # 11th toggle should trigger 429 Too Many Requests
    resp_11 = client.post("/api/camera/start", headers=headers)
    assert resp_11.status_code == 429
    assert "Rate limit exceeded" in resp_11.json()["detail"]
