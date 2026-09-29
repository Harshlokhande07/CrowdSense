"""
Unit tests for Movement Analysis and Vector Tracking.
"""

import pytest
from core.movement import MovementAnalyzer

def test_cardinal_directions():
    assert MovementAnalyzer.get_cardinal_direction(0.0, 0.0) == "STATIONARY"
    assert MovementAnalyzer.get_cardinal_direction(0.1, 0.0) == "E"
    assert MovementAnalyzer.get_cardinal_direction(-0.1, 0.0) == "W"
    assert MovementAnalyzer.get_cardinal_direction(0.0, -0.1) == "N"  # Negative Y points up in screen coords
    assert MovementAnalyzer.get_cardinal_direction(0.0, 0.1) == "S"

def test_track_movement_vectors():
    analyzer = MovementAnalyzer()
    detections_t1 = [{"track_id": 1, "center": (100, 100), "center_bottom": (100, 120)}]
    detections_t2 = [{"track_id": 1, "center": (150, 100), "center_bottom": (150, 120)}]

    # Frame 1 at t=0.0
    tracks1 = analyzer.update_tracks(detections_t1, timestamp=0.0, frame_w=1000, frame_h=1000, fps=25)
    assert tracks1[0]["speed_norm"] == 0.0

    # Frame 2 at t=1.0 s (moved 50px = 0.05 normalized distance in 1s)
    tracks2 = analyzer.update_tracks(detections_t2, timestamp=1.0, frame_w=1000, frame_h=1000, fps=25)
    assert round(tracks2[0]["vx_norm"], 2) == 0.05
    assert round(tracks2[0]["speed_norm"], 2) == 0.05

def test_opposing_flow_two_equal_streams():
    """Two equal opposing streams (+X vs -X) must flag opposing flow."""
    analyzer = MovementAnalyzer()
    # 3 vectors going East (+X), 3 vectors going West (-X) with equal speed 0.05
    vectors = [
        (0.05, 0.0), (0.05, 0.01), (0.05, -0.01),
        (-0.05, 0.0), (-0.05, 0.01), (-0.05, -0.01)
    ]
    res = analyzer.detect_opposing_flow(vectors, min_speed=0.01, min_count=4, angle_thresh_deg=120.0)
    assert res is True

def test_opposing_flow_one_directional():
    """One-directional flow (all East) must NOT flag opposing flow."""
    analyzer = MovementAnalyzer()
    vectors = [(0.05, 0.0), (0.06, 0.01), (0.04, -0.01), (0.05, 0.02)]
    res = analyzer.detect_opposing_flow(vectors, min_speed=0.01, min_count=4, angle_thresh_deg=120.0)
    assert res is False

def test_opposing_flow_stationary_crowd():
    """Stationary crowd (speeds below min_speed) must NOT flag opposing flow."""
    analyzer = MovementAnalyzer()
    vectors = [(0.002, 0.0), (-0.002, 0.0), (0.0, 0.003), (0.0, -0.003)]
    res = analyzer.detect_opposing_flow(vectors, min_speed=0.01, min_count=4, angle_thresh_deg=120.0)
    assert res is False

def test_opposing_flow_noisy_jitter():
    """Small angle scatter / jitter (separation angle < 60 deg) must NOT flag opposing flow."""
    analyzer = MovementAnalyzer()
    vectors = [(0.05, 0.0), (0.05, 0.02), (0.04, 0.01), (0.06, 0.02)]
    res = analyzer.detect_opposing_flow(vectors, min_speed=0.01, min_count=4, angle_thresh_deg=120.0)
    assert res is False

def test_movement_labels_empty_and_low_activity():
    """Empty zones show EMPTY; 1-2 people show LOW ACTIVITY; 3+ evaluated for movement."""
    analyzer = MovementAnalyzer()
    zones = [
        {"id": "ZONE_A", "name": "Zone A", "col_range": (0, 3), "row_range": (0, 3)},
        {"id": "ZONE_B", "name": "Zone B", "col_range": (4, 7), "row_range": (0, 3)},
        {"id": "ZONE_C", "name": "Zone C", "col_range": (0, 3), "row_range": (4, 7)},
    ]

    # ZONE_A has 0 tracks -> EMPTY
    # ZONE_B has 2 tracks (col 5, row 2) -> LOW ACTIVITY
    # ZONE_C has 4 tracks (col 1, row 5) with very low speed -> STAGNANT
    active_tracks = [
        # Zone B (2 people)
        {"track_id": 1, "center_bottom": (500, 200), "vx_norm": 0.01, "vy_norm": 0.0, "speed_norm": 0.01},
        {"track_id": 2, "center_bottom": (520, 210), "vx_norm": 0.01, "vy_norm": 0.0, "speed_norm": 0.01},
        # Zone C (4 people)
        {"track_id": 3, "center_bottom": (100, 500), "vx_norm": 0.005, "vy_norm": 0.0, "speed_norm": 0.005},
        {"track_id": 4, "center_bottom": (110, 510), "vx_norm": 0.005, "vy_norm": 0.0, "speed_norm": 0.005},
        {"track_id": 5, "center_bottom": (120, 520), "vx_norm": 0.005, "vy_norm": 0.0, "speed_norm": 0.005},
        {"track_id": 6, "center_bottom": (130, 530), "vx_norm": 0.005, "vy_norm": 0.0, "speed_norm": 0.005},
    ]

    res = analyzer.analyze_zones_movement(active_tracks, zones, frame_w=800, frame_h=800)
    assert res["ZONE_A"]["movement_status"] == "EMPTY"
    assert res["ZONE_B"]["movement_status"] == "LOW ACTIVITY"
    assert res["ZONE_C"]["movement_status"] == "STAGNANT"


