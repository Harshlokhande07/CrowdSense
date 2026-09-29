"""
Bottleneck & Congestion Multi-Signal Risk Analyzer.
Combines density, growth rate, movement speed, opposing flows, and persistence duration
into a 0-100 risk score and human-readable warning reasons.
"""

import time
import numpy as np
from typing import List, Dict, Any, Tuple
from collections import defaultdict, deque

from core.config import (
    PERSISTENCE_REQUIRED_SEC,
    MIN_ZONE_COUNT_FOR_MOVEMENT,
    GROWTH_WINDOW_SEC,
    GROWTH_RATE_RAPID_PER_SEC,
    GROWTH_RATE_MODERATE_PER_SEC,
    get_density_thresholds
)

class BottleneckDetector:
    def __init__(self, persistence_sec: float = PERSISTENCE_REQUIRED_SEC, demo_mode: bool = False):
        self.persistence_sec = persistence_sec
        self.demo_mode = demo_mode
        # Zone high-density start times: zone_id -> timestamp float
        self.zone_high_density_start: Dict[str, float] = {}
        # Zone count history for density growth rate: zone_id -> deque of (timestamp, count, edge_count)
        self.zone_count_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=60))

    def reset(self):
        """Resets bottleneck timers and history on source switch."""
        self.zone_high_density_start.clear()
        self.zone_count_history.clear()

    def set_demo_mode(self, demo_mode: bool):
        """Updates active threshold profile mode."""
        self.demo_mode = demo_mode

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
        edge_count = movement_data.get("edge_count", 0)

        # Active threshold profile
        thresh = get_density_thresholds(self.demo_mode)
        elev_max = thresh["DENSITY_ELEVATED_MAX"]
        crit_cell_thresh = thresh["CRITICAL_CELL_CONCENTRATION"]
        high_cell_thresh = 3 if self.demo_mode else 5
        elev_cell_thresh = 2 if self.demo_mode else 3

        reasons = []

        # 1. Density Score (up to 40 pts)
        density_score = 0
        if max_cell >= crit_cell_thresh:  # CRITICAL
            density_score = 40
            reasons.append(f"Critical cell density ({max_cell} people in single cell)")
        elif max_cell >= high_cell_thresh:  # HIGH
            density_score = 30
            reasons.append(f"High cell density ({max_cell} people in cell)")
        elif max_cell >= elev_cell_thresh:  # ELEVATED
            density_score = 15
            reasons.append(f"Elevated cell density ({max_cell} people in cell)")

        # 2. Accumulation Trend / Growth Rate Score (up to 20 pts)
        # Consistent units: people/s. Smoothed over a window of at least GROWTH_WINDOW_SEC (5s).
        # Ignores boundary count changes caused by people entering/leaving frame edge.
        history = self.zone_count_history[z_id]
        history.append((now, count, edge_count))

        growth_score = 0
        target_record = None
        for t_hist, c_hist, e_hist in history:
            if (now - t_hist) >= GROWTH_WINDOW_SEC:
                target_record = (t_hist, c_hist, e_hist)
                break

        if target_record is not None:
            t_old, count_old, edge_old = target_record
            dt = max(now - t_old, 1e-3)
            edge_delta = edge_count - edge_old
            total_delta = count - count_old
            internal_delta = max(total_delta - edge_delta, 0)
            rate_per_sec = internal_delta / dt

            if rate_per_sec >= GROWTH_RATE_RAPID_PER_SEC and count > elev_max:
                growth_score = 20
                reasons.append(f"Rapid accumulation (+{rate_per_sec:.1f} people/s)")
            elif rate_per_sec >= GROWTH_RATE_MODERATE_PER_SEC and count > elev_max:
                growth_score = 10
                reasons.append(f"Accumulating count (+{rate_per_sec:.1f} people/s)")

        # 3. Movement / Stagnation Score (up to 20 pts)
        # Stagnation is evaluated ONLY when zone has >= MIN_ZONE_COUNT_FOR_MOVEMENT (default 3)
        speed_score = 0
        if count >= MIN_ZONE_COUNT_FOR_MOVEMENT and count >= elev_max:
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

        if max_cell >= elev_cell_thresh:
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

        # CRITICAL Override: When max single-cell count >= crit_cell_thresh, guarantee minimum score of 85 (CRITICAL)
        if max_cell >= crit_cell_thresh:
            total_score = max(total_score, 85)
            override_msg = f"Critical cell density override ({max_cell} people in single cell)"
            if override_msg not in reasons and f"Critical cell density ({max_cell} people in single cell)" not in reasons:
                reasons.append(override_msg)

        # Determine bottleneck state consistently from composite risk score
        is_bottleneck = False
        if total_score >= 70:
            state = "CRITICAL BOTTLENECK"
            is_bottleneck = True
        elif total_score >= 45:
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
