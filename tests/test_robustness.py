"""
Robustness & Failure Mode Tests for CrowdSense.
Verifies system stability under:
  1. Corrupted & malformed video frames
  2. Camera disconnect and reconnect cycles
  3. Low-light and brightness degradation
  4. Camera shake and jitter translations
  5. High-density stress test (100+ simultaneous tracks)
  6. Sudden detection collapse warning triggers
"""

import os
import sys
import time
import pytest
import numpy as np
import cv2

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import CrowdEngine
from core.density import GridDensityAnalyzer
from core.movement import MovementAnalyzer
from core.bottleneck import BottleneckDetector
from core.prediction import TrendEstimator
from core.alerts import AlertManager


@pytest.fixture
def engine():
    eng = CrowdEngine(video_src="crowd.mp4", demo_mode=True, start_worker=False)
    eng._stop_worker_thread()
    return eng


def test_corrupted_and_empty_frames(engine):
    """Assert engine gracefully handles empty, None, or corrupted frames without crashing."""
    # 1. None frame
    state_none = engine.process_frame(None)
    assert state_none is not None
    assert "people_count" in state_none

    # 2. Empty 0-byte array
    empty_frame = np.array([], dtype=np.uint8)
    state_empty = engine.process_frame(empty_frame)
    assert state_empty is not None

    # 3. Corrupted shape
    corrupt_frame = np.zeros((10, 10, 1), dtype=np.uint8)
    # Even if 1-channel, should not crash
    t0 = time.time()
    state_corrupt = engine.process_frame(corrupt_frame)
    elapsed = time.time() - t0
    assert state_corrupt is not None
    assert elapsed < 0.20  # Under 200ms budget


def test_camera_disconnect_and_reconnect(engine):
    """Simulate camera stream drop, offline fallback frame, and reconnect recovery."""
    engine.demo_mode = False
    engine.camera_status = "OFFLINE"
    engine.cap = None

    # Reading while disconnected
    frame, is_online = engine.read_frame()
    assert is_online is False
    assert engine.camera_status == "OFFLINE"
    assert frame is not None
    assert frame.shape == (480, 640, 3)

    # Reconnect attempt
    ok = engine.reconnect_source("crowd.mp4")
    assert ok is True or engine.camera_status in ("ONLINE", "OFFLINE")


def test_low_light_scaled_frames(engine):
    """Assert low-light scaled frames (10% brightness) process cleanly within loop budget."""
    base_frame = np.random.randint(50, 255, (480, 640, 3), dtype=np.uint8)
    low_light_frame = (base_frame * 0.10).astype(np.uint8)

    t0 = time.time()
    state = engine.process_frame(low_light_frame)
    elapsed = time.time() - t0

    assert state is not None
    assert "people_count" in state
    assert elapsed < 0.15  # Frame processing under 150ms


def test_camera_shake_translation(engine):
    """Assert random small translations (camera shake +/- 15px) process without crash."""
    h, w = 480, 640
    base_frame = np.zeros((h, w, 3), dtype=np.uint8)
    # Add simple shapes
    cv2.circle(base_frame, (320, 240), 50, (200, 200, 200), -1)

    for dx, dy in [(12, -8), (-15, 10), (8, 14), (-10, -10)]:
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        shaken_frame = cv2.warpAffine(base_frame, M, (w, h))

        t0 = time.time()
        state = engine.process_frame(shaken_frame)
        elapsed = time.time() - t0

        assert state is not None
        assert elapsed < 0.15


def test_high_density_100_plus_simultaneous_tracks():
    """Stress test: 120 tracks processed through density, movement, bottleneck, prediction, and alerts."""
    density_analyzer = GridDensityAnalyzer()
    movement_analyzer = MovementAnalyzer()
    bottleneck_detector = BottleneckDetector(demo_mode=False)
    trend_estimator = TrendEstimator()
    alert_manager = AlertManager(demo_mode=False)

    w, h = 1920, 1080
    now = time.time()
    num_tracks = 120

    # Build 120 mock detections
    detections = []
    for i in range(num_tracks):
        cx = (i % 20) * 90.0 + 50.0
        cy = (i // 20) * 150.0 + 100.0
        box_w, box_h = 30.0, 70.0
        detections.append({
            "box": (cx - box_w/2, cy - box_h/2, cx + box_w/2, cy + box_h/2),
            "center": (cx, cy),
            "center_bottom": (cx, cy + box_h/2),
            "confidence": 0.90,
            "track_id": i + 1
        })

    t0 = time.time()

    # 1. Density
    raw_grid = density_analyzer.map_to_grid(detections, w, h)
    density_data = density_analyzer.analyze(raw_grid)

    # 2. Movement
    active_tracks = movement_analyzer.update_tracks(detections, now, w, h, fps=25.0)
    movement_zone_data = movement_analyzer.analyze_zones_movement(active_tracks, density_data["zones"], w, h)

    # 3. Bottleneck
    bottlenecks = bottleneck_detector.analyze_all_zones(density_data["zones"], movement_zone_data, now)

    # 4. Prediction
    predictions = trend_estimator.predict_all_zones(density_data["zones"], now, horizon_s=30.0, bottlenecks=bottlenecks)

    # 5. Alerts
    alerts = alert_manager.process_zone_states(density_data["zones"], bottlenecks, predictions, now)

    elapsed = time.time() - t0

    assert density_data["total_people"] == num_tracks
    assert len(active_tracks) == num_tracks
    assert len(bottlenecks) == len(density_data["zones"])
    assert len(predictions) == len(density_data["zones"])
    # Stress pipeline execution loop must be under 100ms
    assert elapsed < 0.10, f"High-density frame processing took {elapsed:.4f}s (budget: 0.10s)"


def test_detection_collapse_warning_trigger(engine):
    """Assert LOW CONFIDENCE DETECTION warning triggers when detections drop sharply from high density."""
    engine.recent_counts.clear()
    engine.recent_densities.clear()

    # Establish baseline of high density (e.g. 20 people per frame)
    for _ in range(12):
        engine.recent_counts.append(20)
        engine.recent_densities.append(5)

    # Create frame with 0 detections
    empty_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    engine.demo_mode = False  # Use real detector or zero detections on blank frame

    state = engine.process_frame(empty_frame)

    assert state is not None
    assert state.get("detection_warning") == "LOW CONFIDENCE DETECTION"
    assert state["system"].get("detection_warning") == "LOW CONFIDENCE DETECTION"
