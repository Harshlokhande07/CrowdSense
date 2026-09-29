"""
Movement Analysis & Flow Vector Tracking Module.
Analyzes person tracking trajectories, calculates resolution-independent velocities,
determines dominant flow direction, detects opposing movement flows via vector axis splitting, and assigns movement status.
"""

import math
import numpy as np
from typing import List, Dict, Any, Tuple
from collections import defaultdict, deque

from core.config import (
    OPPOSING_FLOW_MIN_SPEED,
    OPPOSING_FLOW_MIN_COUNT,
    OPPOSING_FLOW_ANGLE_DEG,
    MIN_ZONE_COUNT_FOR_MOVEMENT,
    FRAME_EDGE_MARGIN_NORM
)

class MovementAnalyzer:
    def __init__(self, history_seconds: float = 3.0, default_fps: float = 25.0):
        self.history_seconds = history_seconds
        self.default_fps = default_fps

        # Track history map: track_id -> deque of (timestamp, cx, cy)
        self.track_history: Dict[int, deque] = defaultdict(lambda: deque(maxlen=30))
        # Zone speed history for sudden change detection: zone_id -> deque of average speeds
        self.zone_speed_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=60))

    def reset(self):
        """Resets movement trajectory histories on source switch."""
        self.track_history.clear()
        self.zone_speed_history.clear()

    def update_tracks(
        self,
        detections: List[Dict[str, Any]],
        timestamp: float,
        frame_w: int,
        frame_h: int,
        fps: float
    ) -> List[Dict[str, Any]]:
        """
        Updates motion trajectories for tracked persons and computes velocity vectors.
        Velocity is normalized: percentage of frame width/height per second (%/s).
        """
        effective_fps = max(fps, 1.0)
        norm_w = max(frame_w, 1.0)
        norm_h = max(frame_h, 1.0)

        active_tracks = []

        for det in detections:
            t_id = det.get("track_id")
            cx, cy = det["center"]

            # Normalized coordinates (0.0 to 1.0)
            norm_x = cx / norm_w
            norm_y = cy / norm_h

            vx_norm, vy_norm, speed_norm = 0.0, 0.0, 0.0

            if t_id is not None:
                history = self.track_history[t_id]
                history.append((timestamp, norm_x, norm_y))

                if len(history) >= 2:
                    t_old, x_old, y_old = history[0]
                    dt = max(timestamp - t_old, 1e-3)

                    # Velocity in normalized frame fraction per second (%/s)
                    vx_norm = (norm_x - x_old) / dt
                    vy_norm = (norm_y - y_old) / dt
                    speed_norm = math.sqrt(vx_norm ** 2 + vy_norm ** 2)

            active_tracks.append({
                "track_id": t_id,
                "norm_x": norm_x,
                "norm_y": norm_y,
                "vx_norm": vx_norm,
                "vy_norm": vy_norm,
                "speed_norm": speed_norm,
                "center_bottom": det.get("center_bottom", (cx, cy))
            })

        return active_tracks

    @staticmethod
    def get_cardinal_direction(vx: float, vy: float, speed_thresh: float = 0.02) -> str:
        """Converts velocity vector (vx, vy) into 8-point cardinal direction."""
        speed = math.sqrt(vx ** 2 + vy ** 2)
        if speed < speed_thresh:
            return "STATIONARY"

        angle_deg = math.degrees(math.atan2(-vy, vx))
        if angle_deg < 0:
            angle_deg += 360.0

        if 22.5 <= angle_deg < 67.5:
            return "NE"
        elif 67.5 <= angle_deg < 112.5:
            return "N"
        elif 112.5 <= angle_deg < 157.5:
            return "NW"
        elif 157.5 <= angle_deg < 202.5:
            return "W"
        elif 202.5 <= angle_deg < 247.5:
            return "SW"
        elif 247.5 <= angle_deg < 292.5:
            return "S"
        elif 292.5 <= angle_deg < 337.5:
            return "SE"
        else:
            return "E"

    @staticmethod
    def detect_opposing_flow(
        moving_vectors: List[Tuple[float, float]],
        min_speed: float = OPPOSING_FLOW_MIN_SPEED,
        min_count: int = OPPOSING_FLOW_MIN_COUNT,
        angle_thresh_deg: float = OPPOSING_FLOW_ANGLE_DEG
    ) -> bool:
        """
        Detects opposing flows by clustering 2D unit direction vectors into 2 angular groups.
        Flags opposing_flow when each group holds >= 25% of vectors (and >= min_count/2 each)
        and the angle between group mean directions is > angle_thresh_deg (default 120 deg).
        """
        # Filter vectors below min_speed
        valid_vecs = []
        for vx, vy in moving_vectors:
            spd = math.sqrt(vx ** 2 + vy ** 2)
            if spd >= min_speed:
                valid_vecs.append((vx / spd, vy / spd))

        total_valid = len(valid_vecs)
        if total_valid < min_count:
            return False

        # Cluster unit vectors into 2 angular direction groups
        # Seed 1: first vector
        c1 = valid_vecs[0]
        # Seed 2: vector with lowest dot product (most divergent) from seed 1
        dot_products = [c1[0] * v[0] + c1[1] * v[1] for v in valid_vecs]
        min_idx = int(np.argmin(dot_products))
        c2 = valid_vecs[min_idx]

        # 2-means clustering on unit circle (3 iterations is sufficient for convergence)
        for _ in range(3):
            g1, g2 = [], []
            for v in valid_vecs:
                dot1 = c1[0] * v[0] + c1[1] * v[1]
                dot2 = c2[0] * v[0] + c2[1] * v[1]
                if dot1 >= dot2:
                    g1.append(v)
                else:
                    g2.append(v)

            if not g1 or not g2:
                return False

            # Recompute cluster centers
            sum_x1 = sum(v[0] for v in g1)
            sum_y1 = sum(v[1] for v in g1)
            norm1 = math.sqrt(sum_x1 ** 2 + sum_y1 ** 2)
            if norm1 > 1e-6:
                c1 = (sum_x1 / norm1, sum_y1 / norm1)

            sum_x2 = sum(v[0] for v in g2)
            sum_y2 = sum(v[1] for v in g2)
            norm2 = math.sqrt(sum_x2 ** 2 + sum_y2 ** 2)
            if norm2 > 1e-6:
                c2 = (sum_x2 / norm2, sum_y2 / norm2)

        # Check conditions:
        # 1. Group size ratios >= 25% of total moving vectors
        # 2. Minimum counts in each group
        if (len(g1) / float(total_valid) < 0.25) or (len(g2) / float(total_valid) < 0.25):
            return False
        if len(g1) < 2 or len(g2) < 2:
            return False

        # 3. Angle between group mean directions > angle_thresh_deg
        mean_dot = c1[0] * c2[0] + c1[1] * c2[1]
        clamped_dot = max(min(mean_dot, 1.0), -1.0)
        separation_angle_deg = math.degrees(math.acos(clamped_dot))

        return separation_angle_deg > angle_thresh_deg

    def analyze_zones_movement(
        self,
        active_tracks: List[Dict[str, Any]],
        zones: List[Dict[str, Any]],
        frame_w: int,
        frame_h: int
    ) -> Dict[str, Dict[str, Any]]:
        """
        Analyzes zone-level speed, dominant flow direction, and opposing flow.
        """
        results = {}

        for z in zones:
            z_id = z["id"]
            c_start, c_end = z["col_range"]
            r_start, r_end = z["row_range"]

            # Filter tracks in this zone and check edge positioning
            z_tracks = []
            edge_count = 0
            for t in active_tracks:
                cx, y2 = t["center_bottom"]
                col = min(max(int(cx / float(frame_w) * 8), 0), 7)
                row = min(max(int(y2 / float(frame_h) * 8), 0), 7)

                if c_start <= col <= c_end and r_start <= row <= r_end:
                    z_tracks.append(t)
                    norm_x = t.get("norm_x", cx / float(frame_w))
                    norm_y = t.get("norm_y", y2 / float(frame_h))
                    if (
                        norm_x <= FRAME_EDGE_MARGIN_NORM or
                        norm_x >= (1.0 - FRAME_EDGE_MARGIN_NORM) or
                        norm_y <= FRAME_EDGE_MARGIN_NORM or
                        norm_y >= (1.0 - FRAME_EDGE_MARGIN_NORM)
                    ):
                        edge_count += 1

            track_count = len(z_tracks)
            if track_count == 0:
                results[z_id] = {
                    "avg_speed": 0.0,
                    "dominant_direction": "NONE",
                    "opposing_flow": False,
                    "movement_status": "EMPTY",
                    "surging": False,
                    "edge_count": 0
                }
                continue

            moving_tracks = [t for t in z_tracks if t["track_id"] is not None and t["speed_norm"] >= OPPOSING_FLOW_MIN_SPEED]
            speeds = [t["speed_norm"] for t in z_tracks if t["track_id"] is not None]
            avg_speed = float(np.mean(speeds)) if speeds else 0.0

            vxs = [t["vx_norm"] for t in moving_tracks]
            vys = [t["vy_norm"] for t in moving_tracks]

            mean_vx = float(np.mean(vxs)) if vxs else 0.0
            mean_vy = float(np.mean(vys)) if vys else 0.0

            dominant_dir = self.get_cardinal_direction(mean_vx, mean_vy)

            # Opposing Flow via Angular Vector Clustering
            vec_pairs = [(t["vx_norm"], t["vy_norm"]) for t in moving_tracks]
            opposing_flow = self.detect_opposing_flow(
                vec_pairs,
                min_speed=OPPOSING_FLOW_MIN_SPEED,
                min_count=OPPOSING_FLOW_MIN_COUNT,
                angle_thresh_deg=OPPOSING_FLOW_ANGLE_DEG
            )

            # Sudden speed surge detection
            speed_hist = self.zone_speed_history[z_id]
            surging = False
            if len(speed_hist) >= 10:
                baseline_speed = float(np.mean(speed_hist))
                if baseline_speed > 0.01 and avg_speed > baseline_speed * 2.0:
                    surging = True
            speed_hist.append(avg_speed)

            # Assign Movement Status
            if track_count < MIN_ZONE_COUNT_FOR_MOVEMENT:
                status = "LOW ACTIVITY"
            elif opposing_flow:
                status = "OPPOSING FLOW"
            elif surging:
                status = "SURGING"
            elif avg_speed > 0.08:
                status = "MOVING"
            elif avg_speed > 0.02:
                status = "SLOW"
            else:
                status = "STAGNANT"

            results[z_id] = {
                "avg_speed": round(avg_speed, 4),
                "dominant_direction": dominant_dir,
                "opposing_flow": opposing_flow,
                "movement_status": status,
                "surging": surging,
                "edge_count": edge_count
            }

        return results

