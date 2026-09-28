"""
Bottleneck & Congestion Multi-Signal Risk Analyzer.
Combines density, growth rate, movement speed, opposing flows, and persistence duration
into a 0-100 risk score and human-readable warning reasons.
"""

import time
import numpy as np
from typing import List, Dict, Any, Tuple
from collections import defaultdict, deque

from core.config import PERSISTENCE_REQUIRED_SEC, DENSITY_ELEVATED_MAX, DENSITY_HIGH_MAX

class BottleneckDetector:
    def __init__(self, persistence_sec: float = PERSISTENCE_REQUIRED_SEC):
        self.persistence_sec = persistence_sec
        # Zone high-density start times: zone_id -> timestamp float
        self.zone_high_density_start: Dict[str, float] = {}
        # Zone count history for density growth rate: zone_id -> deque of (timestamp, count)
        self.zone_count_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=60))

    def reset(self):
        """Resets bottleneck timers and history on source switch."""
        self.zone_high_density_start.clear()
        self.zone_count_history.clear()

    def evaluate_zone(
        self,
        zone: Dict[str, Any],
        movement_data: Dict[str, Any],
        now: float
    ) -> Dict[str, Any]:
        """
        Evaluates a single zone's multi-signal bottleneck risk score and state.
        """
        z_id = zone["id"]
        z_name = zone["name"]
        count = zone["count"]
        max_cell = zone["max_cell_count"]
        level = zone["level"]

        avg_speed = movement_data.get("avg_speed", 0.0)
        opposing_flow = movement_data.get("opposing_flow", False)

        reasons = []

        # 1. Density Score (up to 40 pts)
        density_score = 0
        if max_cell >= 7:  # CRITICAL
            density_score = 40
            reasons.append(f"Critical cell density ({max_cell} people in single cell)")
        elif max_cell >= 5:  # HIGH
            density_score = 30
            reasons.append(f"High cell density ({max_cell} people in cell)")
        elif max_cell >= 3:  # ELEVATED
            density_score = 15
            reasons.append(f"Elevated cell density ({max_cell} people in cell)")

        # 2. Accumulation Trend / Growth Rate Score (up to 20 pts)
        history = self.zone_count_history[z_id]
        history.append((now, count))

        growth_score = 0
        if len(history) >= 5:
            t_old, count_old = history[0]
            dt = max(now - t_old, 1e-3)
            rate_per_min = (count - count_old) / dt * 60.0

            if rate_per_min > 5.0 and count > DENSITY_ELEVATED_MAX:
                growth_score = 20
                reasons.append(f"Rapid accumulation (+{int(rate_per_min)} people/min)")
            elif rate_per_min > 2.0 and count > DENSITY_ELEVATED_MAX:
                growth_score = 10
                reasons.append(f"Accumulating count (+{int(rate_per_min)} people/min)")

        # 3. Movement / Stagnation Score (up to 20 pts)
        speed_score = 0
        if count >= DENSITY_ELEVATED_MAX:
            if avg_speed < 0.02:
                speed_score = 20
                reasons.append("Stagnant movement speed (<0.02 %/s)")
            elif avg_speed < 0.05:
                speed_score = 10
                reasons.append("Slowing movement speed")

        # 4. Opposing Flow Score (up to 10 pts)
        opposing_score = 0
        if opposing_flow:
            opposing_score = 10
            reasons.append("Opposing crowd flow vectors detected")

        # 5. Persistence Duration Score (up to 10 pts)
        persistence_score = 0
        duration = 0.0

        if max_cell >= DENSITY_ELEVATED_MAX:
            if z_id not in self.zone_high_density_start:
                self.zone_high_density_start[z_id] = now
            duration = now - self.zone_high_density_start[z_id]

            if duration >= 10.0:
                persistence_score = 10
                reasons.append(f"High density persisting for {int(duration)}s")
            elif duration >= self.persistence_sec:
                persistence_score = 5
                reasons.append(f"High density persisting for {int(duration)}s")
        else:
            self.zone_high_density_start.pop(z_id, None)

        # Total multi-signal risk score (0 to 100)
        total_score = min(
            density_score + growth_score + speed_score + opposing_score + persistence_score,
            100
        )

        # Determine bottleneck state
        is_bottleneck = False
        if total_score >= 70 and duration >= self.persistence_sec:
            state = "CRITICAL BOTTLENECK"
            is_bottleneck = True
        elif total_score >= 45 and duration >= self.persistence_sec:
            state = "POTENTIAL BOTTLENECK"
            is_bottleneck = True
        elif total_score >= 25:
            state = "MONITORING"
        else:
            state = "CLEAR"

        return {
            "zone_id": z_id,
            "zone_name": z_name,
            "score": total_score,
            "state": state,
            "is_bottleneck": is_bottleneck,
            "persistence_duration_s": round(duration, 1),
            "reasons": reasons if reasons else ["Normal flow conditions"]
        }

    def analyze_all_zones(
        self,
        zones: List[Dict[str, Any]],
        movement_data: Dict[str, Dict[str, Any]],
        now: float
    ) -> List[Dict[str, Any]]:
        """Evaluates bottleneck risk for all configured zones."""
        results = []
        for z in zones:
            z_id = z["id"]
            m_data = movement_data.get(z_id, {})
            results.append(self.evaluate_zone(z, m_data, now))
        return results
