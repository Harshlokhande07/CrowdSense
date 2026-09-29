"""
Short-Term Trend Estimation & Linear Extrapolation Module.
Extrapolates 15-30s per-zone density trend using linear regression over 45-60s history.
Computes mathematical confidence (R^2 fit quality, >=15 samples check) and marks predictions with human verification disclaimers.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional
from collections import defaultdict, deque

from core.config import (
    PREDICTION_HISTORY_WINDOW_SEC,
    PREDICTION_HORIZON_SEC,
    R2_CONFIDENCE_THRESHOLD
)
from core.density import GridDensityAnalyzer

class TrendEstimator:
    def __init__(self, window_seconds: float = PREDICTION_HISTORY_WINDOW_SEC):
        self.window_seconds = window_seconds
        # Zone count history: zone_id -> deque of (timestamp, count)
        self.history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=240))
        # Zone risk score history: zone_id -> deque of (timestamp, score)
        self.risk_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=240))

    def reset(self):
        """Resets prediction history buffer on source switch."""
        self.history.clear()
        self.risk_history.clear()

    def update_history(self, zones: List[Dict[str, Any]], now: float, bottlenecks: Optional[List[Dict[str, Any]]] = None):
        """Records current zone counts and risk scores into time-series window."""
        bn_map = {b["zone_id"]: b.get("score", 0) for b in (bottlenecks or [])}
        for z in zones:
            z_id = z["id"]
            self.history[z_id].append((now, z["count"]))
            self.risk_history[z_id].append((now, float(bn_map.get(z_id, z.get("risk_score", 0)))))

    def predict_zone(
        self,
        zone_id: str,
        current_count: int,
        now: float,
        horizon_s: float = PREDICTION_HORIZON_SEC,
        current_risk_score: float = 0.0
    ) -> Dict[str, Any]:
        """
        Extrapolates short-term trend for a zone horizon_s seconds into the future.
        Guards against zero-variance history (returns R^2=1.0 and slope=0.0 when counts are constant).
        Exposes low_confidence: bool and computes time_to_threshold_sec for proactive alerts.
        """
        buf = self.history[zone_id]

        # Filter points within history window (e.g. 45-60s)
        times = []
        counts = []
        for t, c in buf:
            if now - t <= self.window_seconds:
                times.append(t - now)  # Relative time in seconds
                counts.append(float(c))

        # Check sample count requirement (ADDENDUM rule: < 15 samples = Low confidence)
        if len(times) < 15:
            return {
                "predicted_count": current_count,
                "predicted_level": GridDensityAnalyzer.get_density_level(current_count),
                "slope_per_sec": 0.0,
                "trend": "STABLE",
                "confidence": f"Low confidence (<15 samples, got {len(times)})",
                "confidence_score": 0.0,
                "low_confidence": True,
                "horizon_s": horizon_s,
                "time_to_threshold_sec": None,
                "forecast_message": None,
                "disclaimer": "Requires human verification"
            }

        x = np.array(times, dtype=float)
        y = np.array(counts, dtype=float)

        # Variance guard: when all historical values are identical, ss_tot == 0
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        if ss_tot < 1e-6:
            # Constant sequence: slope is exactly 0.0, linear model fits perfectly (R² = 1.0)
            slope = 0.0
            intercept = float(y[0])
            r_squared = 1.0
        else:
            # Fit 1st order polynomial (slope * t + intercept)
            slope, intercept = np.polyfit(x, y, 1)
            y_pred = slope * x + intercept
            ss_res = float(np.sum((y - y_pred) ** 2))
            r_squared = 1.0 - (ss_res / ss_tot)
            r_squared = max(min(r_squared, 1.0), 0.0)

        # Extrapolate horizon_s seconds ahead and clamp >= 0
        raw_predicted_count = slope * horizon_s + current_count
        predicted_count = max(int(round(raw_predicted_count)), 0)

        # Trend direction
        if slope > 0.05:
            trend = "RISING"
        elif slope < -0.05:
            trend = "FALLING"
        else:
            trend = "STABLE"

        # Determine low_confidence boolean
        is_low_confidence = bool(r_squared < R2_CONFIDENCE_THRESHOLD)

        if is_low_confidence:
            confidence = f"Low confidence (High noise, R²={r_squared:.2f})"
        elif r_squared >= 0.7:
            confidence = f"High confidence (R²={r_squared:.2f})"
        else:
            confidence = f"Moderate confidence (R²={r_squared:.2f})"

        predicted_level = GridDensityAnalyzer.get_density_level(predicted_count)

        # Risk score slope & proactive time_to_threshold calculation
        # Forecast guard: time_to_threshold_sec is null when slope <= 0, R² is below threshold, or result is negative.
        time_to_threshold_sec = None
        forecast_message = None

        if (slope > 0) and (r_squared >= R2_CONFIDENCE_THRESHOLD) and (not is_low_confidence):
            risk_buf = self.risk_history[zone_id]
            risk_times, risk_scores = [], []
            for t, s in risk_buf:
                if now - t <= self.window_seconds:
                    risk_times.append(t - now)
                    risk_scores.append(float(s))

            if len(risk_times) >= 15:
                rx = np.array(risk_times, dtype=float)
                ry = np.array(risk_scores, dtype=float)
                rss_tot = float(np.sum((ry - np.mean(ry)) ** 2))
                if rss_tot >= 1e-6:
                    r_slope, _ = np.polyfit(rx, ry, 1)
                    if r_slope > 0.05:  # Positive rising risk score per second
                        # Target next severity state
                        if current_risk_score < 55:
                            target_name, target_score = "HIGH", 55.0
                        elif current_risk_score < 70:
                            target_name, target_score = "CONGESTION", 70.0
                        elif current_risk_score < 85:
                            target_name, target_score = "CRITICAL", 85.0
                        else:
                            target_name, target_score = None, None

                        if target_name is not None and target_score > current_risk_score:
                            delta = target_score - current_risk_score
                            est_sec = delta / r_slope
                            # Guard: Must be strictly positive and within horizon
                            if est_sec > 0 and est_sec <= 300:
                                time_to_threshold_sec = round(float(est_sec), 1)
                                forecast_message = f"Reaches {target_name} in ~{int(time_to_threshold_sec)}s"

        # Final guard: ensure null if invalid or negative
        if time_to_threshold_sec is not None and time_to_threshold_sec <= 0:
            time_to_threshold_sec = None
            forecast_message = None

        return {
            "predicted_count": predicted_count,
            "predicted_level": predicted_level,
            "slope_per_sec": round(float(slope), 4),
            "trend": trend,
            "confidence": confidence,
            "confidence_score": round(float(r_squared), 2),
            "low_confidence": is_low_confidence,
            "horizon_s": horizon_s,
            "time_to_threshold_sec": time_to_threshold_sec,
            "forecast_message": forecast_message,
            "disclaimer": "Requires human verification"
        }

    def predict_all_zones(
        self,
        zones: List[Dict[str, Any]],
        now: float,
        horizon_s: float = PREDICTION_HORIZON_SEC,
        bottlenecks: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """Generates short-term trend estimates for all zones."""
        self.update_history(zones, now, bottlenecks)

        bn_map = {b["zone_id"]: b.get("score", 0) for b in (bottlenecks or [])}
        results = []
        for z in zones:
            z_id = z["id"]
            c_score = float(bn_map.get(z_id, z.get("risk_score", 0)))
            p_data = self.predict_zone(z_id, z["count"], now, horizon_s, current_risk_score=c_score)
            p_data["zone_id"] = z_id
            p_data["zone_name"] = z["name"]
            results.append(p_data)
        return results

