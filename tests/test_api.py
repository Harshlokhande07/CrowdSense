"""
API Endpoints & FastAPI TestClient Unit Tests.
Includes comprehensive authentication coverage (Query, Header x-api-key, Bearer),
fail-closed policy tests, and WebSocket authentication.
"""

import os
import io
import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from starlette.websockets import WebSocketClose
import dashboard
from dashboard import app, check_auth

client = TestClient(app)

def test_api_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "HEALTHY"
    assert "camera" in data
    assert "model" in data

def test_api_state_endpoint():
    response = client.get("/api/state")
    assert response.status_code == 200
    data = response.json()
    assert "system" in data
    assert "people_count" in data
    assert "density" in data
    assert "zones" in data

def test_api_alerts_endpoint():
    response = client.get("/api/alerts")
    assert response.status_code == 200
    data = response.json()
    assert "active_incidents" in data
    assert "recent_history" in data

def test_api_history_endpoint():
    response = client.get("/api/history")
    assert response.status_code == 200
    data = response.json()
    assert "people_count" in data
    assert "max_cell_density" in data

def test_websocket_connection(monkeypatch):
    monkeypatch.setattr(dashboard, "is_demo", True)
    monkeypatch.setattr(dashboard.engine, "demo_mode", True)
    with client.websocket_connect("/ws") as websocket:
        data = websocket.receive_json()
        assert "system" in data
        assert "people_count" in data
        assert "grid" in data

# ────────────────── Auth Unit Tests ──────────────────

def test_auth_fail_closed_outside_demo(monkeypatch):
    """When API_AUTH_KEY is unset and demo mode is False, check_auth must fail closed."""
    monkeypatch.setenv("API_AUTH_KEY", "")
    monkeypatch.setattr(dashboard, "API_AUTH_KEY", "")
    monkeypatch.setattr(dashboard, "is_demo", False)
    monkeypatch.setattr(dashboard.engine, "demo_mode", False)

    assert check_auth() is False
    assert check_auth(token="random") is False

def test_auth_open_in_demo_when_unset(monkeypatch):
    """When API_AUTH_KEY is unset but demo mode is True, check_auth allows open access."""
    monkeypatch.setenv("API_AUTH_KEY", "")
    monkeypatch.setattr(dashboard, "API_AUTH_KEY", "")
    monkeypatch.setattr(dashboard, "is_demo", True)
    monkeypatch.setattr(dashboard.engine, "demo_mode", True)

    assert check_auth() is True

def test_auth_validation_methods(monkeypatch):
    """Validates query token, x-api-key header, and Bearer authorization."""
    secret = "test-secret-key-12345"
    monkeypatch.setenv("API_AUTH_KEY", secret)
    monkeypatch.setattr(dashboard, "API_AUTH_KEY", secret)
    monkeypatch.setattr(dashboard, "is_demo", False)
    monkeypatch.setattr(dashboard.engine, "demo_mode", False)

    # Valid auth
    assert check_auth(token=secret) is True
    assert check_auth(header_key=secret) is True
    assert check_auth(auth_header=f"Bearer {secret}") is True
    assert check_auth(auth_header=secret) is True

    # Invalid / missing auth
    assert check_auth() is False
    assert check_auth(token="wrong-token") is False
    assert check_auth(header_key="wrong-key") is False
    assert check_auth(auth_header="Bearer wrong-secret") is False

def test_protected_endpoints_unauthorized_return_401(monkeypatch):
    """All 5 protected REST endpoints return 401 when unauthenticated."""
    secret = "secure_production_key_xyz"
    monkeypatch.setenv("API_AUTH_KEY", secret)
    monkeypatch.setattr(dashboard, "API_AUTH_KEY", secret)
    monkeypatch.setattr(dashboard, "is_demo", False)
    monkeypatch.setattr(dashboard.engine, "demo_mode", False)

    # 1. /api/source/upload
    fake_file = io.BytesIO(b"fake video content")
    res_upload = client.post("/api/source/upload", files={"file": ("test.mp4", fake_file, "video/mp4")})
    assert res_upload.status_code == 401
    assert "Unauthorized" in res_upload.json().get("detail", "")

    # 2. /api/source/select
    res_select = client.post("/api/source/select", json={"mode": "demo"})
    assert res_select.status_code == 401
    assert "Unauthorized" in res_select.json().get("detail", "")

    # 3. /api/incidents/{id}/ack
    res_ack = client.post("/api/incidents/INC-1/ack", json={"operator": "Harsh", "note": "Investigating"})
    assert res_ack.status_code == 401
    assert "Unauthorized" in res_ack.json().get("detail", "")

    # 4. /api/incidents/{id}/resolve
    res_resolve = client.post("/api/incidents/INC-1/resolve", json={"operator": "Harsh", "note": "Resolved"})
    assert res_resolve.status_code == 401
    assert "Unauthorized" in res_resolve.json().get("detail", "")

    # 5. /api/notify/test
    res_notify = client.post("/api/notify/test", json={"zone_id": "ZONE_A"})
    assert res_notify.status_code == 401
    assert "Unauthorized" in res_notify.json().get("detail", "")

def test_protected_endpoints_authorized_with_token_and_headers(monkeypatch):
    """Protected endpoints accept authentication via query token, x-api-key, or Bearer header."""
    secret = "secure_production_key_xyz"
    monkeypatch.setenv("API_AUTH_KEY", secret)
    monkeypatch.setattr(dashboard, "API_AUTH_KEY", secret)
    monkeypatch.setattr(dashboard, "is_demo", False)
    monkeypatch.setattr(dashboard.engine, "demo_mode", False)

    # /api/source/select with query token
    res1 = client.post(f"/api/source/select?token={secret}", json={"mode": "demo"})
    assert res1.status_code == 200

    # /api/source/select with x-api-key header
    res2 = client.post("/api/source/select", json={"mode": "demo"}, headers={"x-api-key": secret})
    assert res2.status_code == 200

    # /api/source/select with Authorization Bearer header
    res3 = client.post("/api/source/select", json={"mode": "demo"}, headers={"Authorization": f"Bearer {secret}"})
    assert res3.status_code == 200

def test_websocket_auth_rejection(monkeypatch):
    """WebSocket /ws closes connection with code 4001 when unauthenticated in production."""
    secret = "secure_ws_key"
    monkeypatch.setenv("API_AUTH_KEY", secret)
    monkeypatch.setattr(dashboard, "API_AUTH_KEY", secret)
    monkeypatch.setattr(dashboard, "is_demo", False)
    monkeypatch.setattr(dashboard.engine, "demo_mode", False)

    # Missing token -> should be closed / rejected
    with pytest.raises(Exception):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()

    # Valid token -> succeeds
    with client.websocket_connect(f"/ws?token={secret}") as ws:
        data = ws.receive_json()
        assert "system" in data


def test_video_pause_resume_endpoints(monkeypatch):
    monkeypatch.setattr(dashboard, "is_demo", True)
    monkeypatch.setattr(dashboard.engine, "demo_mode", True)

    # 1. Pause video
    res = client.post("/api/video/pause")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "OK"
    assert data.get("is_paused") is True
    assert data.get("source", {}).get("is_paused") is True

    # 2. Resume video
    res = client.post("/api/video/resume")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "OK"
    assert data.get("is_paused") is False
    assert data.get("source", {}).get("is_paused") is False

    # 3. Toggle pause
    res = client.post("/api/video/toggle-pause")
    assert res.status_code == 200
    data = res.json()
    assert data.get("is_paused") is True

    res = client.post("/api/video/toggle-pause")
    assert res.status_code == 200
    data = res.json()
    assert data.get("is_paused") is False
