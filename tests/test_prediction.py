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
    assert "disclaimer" in pred
    assert pred["disclaimer"] == "Requires human verification"
