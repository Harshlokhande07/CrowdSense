"""
Unit tests for Alert Pipeline & Incident State Machine.
"""

import pytest
from core.alerts import AlertManager

def test_incident_state_machine():
    manager = AlertManager()

    zones = [{"id": "ZONE_C", "name": "East Lane", "count": 12, "level": "CRITICAL"}]
    bottlenecks = [{"zone_id": "ZONE_C", "score": 85, "reasons": ["Critical cell density"], "is_bottleneck": True}]
    predictions = [{"zone_id": "ZONE_C", "predicted_count": 15, "trend": "RISING"}]

    # 1. Trigger Alert
    alerts1 = manager.process_zone_states(zones, bottlenecks, predictions, now=100.0)
    assert len(alerts1) == 1
    assert alerts1[0]["severity"] == "CRITICAL"
    assert alerts1[0]["status"] == "ACTIVE"

    # 2. Update Persisting Alert
    zones[0]["count"] = 15  # Count increased to peak 15
    alerts2 = manager.process_zone_states(zones, bottlenecks, predictions, now=105.0)
    assert len(alerts2) == 1
    assert alerts2[0]["peak_count"] == 15
    assert alerts2[0]["duration_s"] == 5.0

    # 3. Resolve Alert when normal
    zones_normal = [{"id": "ZONE_C", "name": "East Lane", "count": 1, "level": "NORMAL"}]
    bottlenecks_normal = [{"zone_id": "ZONE_C", "score": 0, "reasons": [], "is_bottleneck": False}]

    alerts3 = manager.process_zone_states(zones_normal, bottlenecks_normal, predictions, now=110.0)
    assert len(alerts3) == 0
    assert len(manager.alerts_history) >= 1
    assert manager.alerts_history[0]["status"] == "RESOLVED"
