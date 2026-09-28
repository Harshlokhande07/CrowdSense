"""
Short-Term Trend Estimation & Linear Extrapolation Module.
Extrapolates 15-30s per-zone density trend using linear regression over 45-60s history.
Computes mathematical confidence (R^2 fit quality, >=15 samples check) and marks predictions with human verification disclaimers.
"""

import math
import numpy as np
from typing import List, Dict, Any
from collections import defaultdict, deque

from core.config import PREDICTION_HISTORY_WINDOW_SEC, PREDICTION_HORIZON_SEC
from core.density import GridDensityAnalyzer

class TrendEstimator:
    def __init__(self, window_seconds: float = PREDICTION_HISTORY_WINDOW_SEC):
        self.window_seconds = window_seconds
        # Zone history: zone_id -> deque of (timestamp, count)
        self.history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=240))

    def reset(self):
        """Resets prediction history buffer on source switch."""
        self.history.clear()

    def update_history(self, zones: List[Dict[str, Any]], now: float):
        """Records current zone counts into time-series window."""
        for z in zones:
            z_id = z["id"]
            self.history[z_id].append((now, z["count"]))

    def predict_zone(
        self,
        zone_id: str,
        current_count: int,
        now: float,
        horizon_s: float = PREDICTION_HORIZON_SEC
    ) -> Dict[str, Any]:
        """
        Extrapolates short-term trend for a zone horizon_s seconds into the future.
        Requires >= 15 samples and R^2 >= 0.3 for confidence; otherwise reports Low Confidence.
        Clamps predicted count >= 0.
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
                "trend": "STABLE",
                "confidence": f"Low confidence (<15 samples, got {len(times)})",
                "confidence_score": 0.0,
                "horizon_s": horizon_s,
                "disclaimer": "Requires human verification"
            }

        x = np.array(times, dtype=float)
        y = np.array(counts, dtype=float)

        # Fit 1st order polynomial (slope * t + intercept)
        slope, intercept = np.polyfit(x, y, 1)

        # Calculate R^2 coefficient of determination
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)

        r_squared = 1.0 - (ss_res / max(ss_tot, 1e-6)) if ss_tot > 1e-6 else 1.0
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

        # Determine confidence status (ADDENDUM rule: Low confidence if R^2 < 0.3)
        if r_squared < 0.3:
            confidence = f"Low confidence (High noise, R²={r_squared:.2f})"
        elif r_squared >= 0.7:
            confidence = f"High confidence (R²={r_squared:.2f})"
        else:
            confidence = f"Moderate confidence (R²={r_squared:.2f})"

        predicted_level = GridDensityAnalyzer.get_density_level(predicted_count)

        return {
            "predicted_count": predicted_count,
            "predicted_level": predicted_level,
            "slope_per_sec": round(float(slope), 4),
            "trend": trend,
            "confidence": confidence,
            "confidence_score": round(float(r_squared), 2),
            "horizon_s": horizon_s,
            "disclaimer": "Requires human verification"
        }

    def predict_all_zones(
        self,
        zones: List[Dict[str, Any]],
        now: float,
        horizon_s: float = PREDICTION_HORIZON_SEC
    ) -> List[Dict[str, Any]]:
        """Generates short-term trend estimates for all zones."""
        self.update_history(zones, now)

        results = []
        for z in zones:
            z_id = z["id"]
            p_data = self.predict_zone(z_id, z["count"], now, horizon_s)
            p_data["zone_id"] = z_id
            p_data["zone_name"] = z["name"]
            results.append(p_data)
        return results
