"""
API Endpoints & FastAPI TestClient Unit Tests.
"""

import pytest
from fastapi.testclient import TestClient
from dashboard import app

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

def test_websocket_connection():
    with client.websocket_connect("/ws") as websocket:
        data = websocket.receive_json()
        assert "system" in data
        assert "people_count" in data
        assert "grid" in data
