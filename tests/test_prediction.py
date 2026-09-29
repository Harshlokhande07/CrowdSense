"""
Unit tests for Short-Term Trend Estimation & Linear Extrapolation.
"""

import pytest
from core.prediction import TrendEstimator

def test_trend_prediction():
    estimator = TrendEstimator(window_seconds=30.0)

    zone_id = "ZONE_A"
    # Feed rising count time-series data over 20 seconds (satisfying >= 15 samples requirement)
    for t_offset in range(20):
        t = 100.0 + t_offset
        count = 5 + t_offset * 2  # Increasing count: 5, 7, 9, 11...
        zones = [{"id": zone_id, "name": "Gate 3", "count": count}]
        estimator.update_history(zones, now=t)

    pred = estimator.predict_zone(zone_id, current_count=43, now=119.0, horizon_s=30.0)

    assert pred["trend"] == "RISING"
    assert pred["slope_per_sec"] > 0
    assert pred["predicted_count"] > 23
    assert pred["low_confidence"] is False
    assert "disclaimer" in pred
    assert pred["disclaimer"] == "Requires human verification"

def test_trend_zero_variance():
    """Zero variance (constant count over time) must yield R^2 = 1.0, slope = 0, low_confidence = False without NaN/division by zero."""
    estimator = TrendEstimator(window_seconds=30.0)
    zone_id = "ZONE_B"
    # Feed 20 identical count samples
    for t_offset in range(20):
        t = 100.0 + t_offset
        estimator.update_history([{"id": zone_id, "name": "Main", "count": 10}], now=t)

    pred = estimator.predict_zone(zone_id, current_count=10, now=119.0, horizon_s=30.0)
    assert pred["confidence_score"] == 1.0
    assert pred["slope_per_sec"] == 0.0
    assert pred["predicted_count"] == 10
    assert pred["low_confidence"] is False
    assert pred["trend"] == "STABLE"

def test_trend_insufficient_samples():
    """Less than 15 samples must report low_confidence = True."""
    estimator = TrendEstimator(window_seconds=30.0)
    zone_id = "ZONE_C"
    for t_offset in range(5):
        t = 100.0 + t_offset
        estimator.update_history([{"id": zone_id, "name": "East", "count": 10}], now=t)

    pred = estimator.predict_zone(zone_id, current_count=10, now=104.0, horizon_s=30.0)
    assert pred["low_confidence"] is True
    assert pred["confidence_score"] == 0.0

