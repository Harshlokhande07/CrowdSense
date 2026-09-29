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

    # 3. Resolve Alert when normal (feed normal for >= 3s to satisfy hysteresis resolution)
    zones_normal = [{"id": "ZONE_C", "name": "East Lane", "count": 1, "level": "NORMAL"}]
    bottlenecks_normal = [{"zone_id": "ZONE_C", "score": 0, "reasons": [], "is_bottleneck": False}]

    # At t=110.0, resolution timer begins
    manager.process_zone_states(zones_normal, bottlenecks_normal, predictions, now=110.0)
    # At t=114.0 (>3s), resolution commits
    alerts3 = manager.process_zone_states(zones_normal, bottlenecks_normal, predictions, now=114.0)
    assert len(alerts3) == 0
    assert len(manager.alerts_history) >= 1
    assert manager.alerts_history[0]["status"] == "RESOLVED"

def test_escalation_during_cooldown():
    """Escalations (e.g. HIGH -> CRITICAL) must dispatch immediately, bypassing cooldown."""
    manager = AlertManager()
    zone = [{"id": "ZONE_A", "name": "Gate 3", "count": 6, "level": "HIGH"}]
    bn_high = [{"zone_id": "ZONE_A", "score": 35, "reasons": ["High density"], "is_bottleneck": False}]
    preds = [{"zone_id": "ZONE_A", "predicted_count": 8, "trend": "RISING"}]

    # Trigger HIGH alert at t=100.0
    alerts1 = manager.process_zone_states(zone, bn_high, preds, now=100.0)
    assert alerts1[0]["severity"] == "HIGH"
    assert manager.last_notify_level["ZONE_A"] == "HIGH"
    assert manager.last_notify_time["ZONE_A"] == 100.0

    # Repeat at same level within 5 seconds -> must be throttled (no timestamp change)
    alerts_repeat = manager.process_zone_states(zone, bn_high, preds, now=105.0)
    assert alerts_repeat[0]["severity"] == "HIGH"
    assert manager.last_notify_time["ZONE_A"] == 100.0

    # Escalation to CRITICAL at t=106.0 (within 30s cooldown) -> must dispatch immediately!
    bn_crit = [{"zone_id": "ZONE_A", "score": 85, "reasons": ["Critical surge"], "is_bottleneck": True}]
    zone[0]["level"] = "CRITICAL"
    alerts_escalate = manager.process_zone_states(zone, bn_crit, preds, now=106.0)
    assert alerts_escalate[0]["severity"] == "CRITICAL"
    assert manager.last_notify_level["ZONE_A"] == "CRITICAL"
    assert manager.last_notify_time["ZONE_A"] == 106.0

def test_hysteresis_flapping_prevention():
    """Score fluctuating slightly around threshold must not cause severity flapping."""
    manager = AlertManager()
    zone = [{"id": "ZONE_B", "name": "Concourse", "count": 10, "level": "CRITICAL"}]
    bn_crit = [{"zone_id": "ZONE_B", "score": 75, "reasons": ["High congestion"], "is_bottleneck": True}]
    preds = [{"zone_id": "ZONE_B", "predicted_count": 12, "trend": "STABLE"}]

    # Enter CRITICAL at t=100
    alerts = manager.process_zone_states(zone, bn_crit, preds, now=100.0)
    assert alerts[0]["severity"] == "CRITICAL"

    # Score dips to 68 at t=101 (below 70, but within hysteresis margin >= 65) -> stays CRITICAL
    zone[0]["level"] = "HIGH"
    bn_dip = [{"zone_id": "ZONE_B", "score": 68, "reasons": [], "is_bottleneck": False}]
    alerts2 = manager.process_zone_states(zone, bn_dip, preds, now=101.0)
    assert alerts2[0]["severity"] == "CRITICAL"

    # Score dips to 60 at t=102 (<65), but only for 1 second (<3s hysteresis duration) -> stays CRITICAL
    bn_low = [{"zone_id": "ZONE_B", "score": 60, "reasons": [], "is_bottleneck": False}]
    alerts3 = manager.process_zone_states(zone, bn_low, preds, now=102.0)
    assert alerts3[0]["severity"] == "CRITICAL"

    # Score sustains low for >= 3s at t=105.5 -> successfully de-escalates to CONGESTION
    alerts4 = manager.process_zone_states(zone, bn_low, preds, now=105.5)
    assert alerts4[0]["severity"] == "CONGESTION"

def test_queue_overflow_handling():
    """When notification queue is full, AlertManager must drop and log without raising exception."""
    manager = AlertManager()
    # Fill queue to maximum capacity
    for i in range(60):
        try:
            manager.notify_queue.put_nowait({"zone_id": f"Z_{i}", "severity": "CRITICAL"})
        except Exception:
            pass

    # Triggering another notification must increment dropped count
    incident = {"zone_id": "ZONE_OVERFLOW", "zone_name": "Gate X", "severity": "CRITICAL", "current_count": 20}
    manager._trigger_notifications(incident, now=200.0, is_escalation=True)
    status = manager.get_system_notifications_status()
    assert status["dropped_notifications"] >= 1

