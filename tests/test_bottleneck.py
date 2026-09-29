"""
Unit tests for Bottleneck Multi-Signal Congestion Risk Detector.
"""

import pytest
from core.bottleneck import BottleneckDetector

def test_bottleneck_scoring():
    detector = BottleneckDetector(persistence_sec=3.0)

    zone = {
        "id": "ZONE_C",
        "name": "East Lane Merge",
        "count": 10,
        "max_cell_count": 8,
        "level": "CRITICAL"
    }

    movement_data = {
        "avg_speed": 0.01,  # Stagnant speed
        "opposing_flow": True
    }

    # First evaluation (t=100.0) -> high score, persistence starting
    res1 = detector.evaluate_zone(zone, movement_data, now=100.0)
    assert res1["score"] >= 50
    assert "Critical cell density" in res1["reasons"][0] or "Critical cell density" in str(res1["reasons"])

    # Second evaluation after 4 seconds (t=104.0) -> persistence score added, bottleneck confirmed
    res2 = detector.evaluate_zone(zone, movement_data, now=104.0)
    assert res2["score"] >= 70
    assert res2["is_bottleneck"] is True
    assert res2["state"] in ("POTENTIAL BOTTLENECK", "CRITICAL BOTTLENECK")

def test_bottleneck_critical_override():
    """When max single-cell count >= 7, score must floor at 85 (CRITICAL) with consistent state."""
    detector = BottleneckDetector(persistence_sec=3.0)
    zone = {
        "id": "ZONE_A",
        "name": "Gate 3",
        "count": 7,
        "max_cell_count": 7,
        "level": "CRITICAL"
    }
    movement_data = {"avg_speed": 0.05, "opposing_flow": False}
    res = detector.evaluate_zone(zone, movement_data, now=100.0)
    assert res["score"] >= 85
    assert res["state"] == "CRITICAL BOTTLENECK"
    assert any("Critical" in r for r in res["reasons"])

