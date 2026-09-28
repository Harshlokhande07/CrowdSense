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
