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

def test_growth_rate_smoothing_and_units():
    """Growth rate requires at least 5s window and evaluates in people/s."""
    detector = BottleneckDetector(persistence_sec=3.0)
    zone = {"id": "ZONE_B", "name": "Concourse", "count": 5, "max_cell_count": 2, "level": "NORMAL"}
    m_data = {"avg_speed": 0.05, "opposing_flow": False, "edge_count": 0}

    # t=100.0 (count=5)
    detector.evaluate_zone(zone, m_data, now=100.0)

    # t=103.0 (3s < 5s window, count surges to 10) -> Must NOT trigger growth score yet
    zone["count"] = 10
    res_3s = detector.evaluate_zone(zone, m_data, now=103.0)
    assert not any("accumulation" in r.lower() for r in res_3s["reasons"])

    # t=106.0 (6s >= 5s window, count=10 -> delta=5 in 6s = 0.83 p/s >= 0.8 p/s) -> Triggers Rapid accumulation
    res_6s = detector.evaluate_zone(zone, m_data, now=106.0)
    assert any("Rapid accumulation (+0.8 people/s)" in r for r in res_6s["reasons"])
    assert res_6s["score"] >= 20

def test_growth_rate_ignores_frame_edge_entries():
    """Count changes caused by people entering at the frame boundary must be ignored."""
    detector = BottleneckDetector(persistence_sec=3.0)
    zone = {"id": "ZONE_EDGE", "name": "Edge Zone", "count": 5, "max_cell_count": 2, "level": "NORMAL"}
    
    # t=100.0, 5 people inside, 0 at edge
    detector.evaluate_zone(zone, {"avg_speed": 0.05, "opposing_flow": False, "edge_count": 0}, now=100.0)

    # t=106.0, count increased to 12 (+7), but all 7 new people entered at frame boundary (edge_count = 7)
    zone["count"] = 12
    res = detector.evaluate_zone(zone, {"avg_speed": 0.05, "opposing_flow": False, "edge_count": 7}, now=106.0)
    # Net internal delta = (12 - 5) - (7 - 0) = 0 -> No growth score
    assert not any("accumulation" in r.lower() for r in res["reasons"])

def test_stagnation_min_count_rule():
    """Below 3 people in a zone, stagnation must never contribute to risk score."""
    detector = BottleneckDetector(persistence_sec=3.0)
    
    # Zone with 2 people (< 3) and very low speed 0.005 -> speed score must be 0
    zone_sparse = {"id": "ZONE_SPARSE", "name": "Sparse", "count": 2, "max_cell_count": 1, "level": "NORMAL"}
    res_sparse = detector.evaluate_zone(zone_sparse, {"avg_speed": 0.005, "opposing_flow": False}, now=100.0)
    assert not any("Stagnant" in r for r in res_sparse["reasons"])
    assert res_sparse["score"] == 0

    # Zone with 6 people (>= 3 and >= ELEVATED) and very low speed 0.005 -> triggers stagnation
    zone_dense = {"id": "ZONE_DENSE", "name": "Dense", "count": 6, "max_cell_count": 3, "level": "ELEVATED"}
    res_dense = detector.evaluate_zone(zone_dense, {"avg_speed": 0.005, "opposing_flow": False}, now=100.0)
    assert any("Stagnant movement speed" in r for r in res_dense["reasons"])
    assert res_dense["score"] >= 20

def test_demo_threshold_profile():
    """Demo profile lowers critical cell threshold to 4 for demo footage."""
    det_prod = BottleneckDetector(demo_mode=False)
    det_demo = BottleneckDetector(demo_mode=True)

    zone_4 = {"id": "ZONE_D", "name": "Demo", "count": 5, "max_cell_count": 4, "level": "NORMAL"}
    m_data = {"avg_speed": 0.05, "opposing_flow": False}

    res_prod = det_prod.evaluate_zone(zone_4, m_data, now=100.0)
    res_demo = det_demo.evaluate_zone(zone_4, m_data, now=100.0)

    # In prod, cell count 4 is ELEVATED (15 pts), total score = 15
    assert res_prod["score"] < 50
    assert not res_prod["is_bottleneck"]

    # In demo, cell count 4 is CRITICAL (>=4) -> floors at 85
    assert res_demo["score"] >= 85
    assert res_demo["state"] == "CRITICAL BOTTLENECK"
    assert res_demo["is_bottleneck"] is True

