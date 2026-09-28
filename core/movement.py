"""
Movement Analysis & Flow Vector Tracking Module.
Analyzes person tracking trajectories, calculates resolution-independent velocities,
determines dominant flow direction, detects opposing movement flows via vector axis splitting, and assigns movement status.
"""

import math
import numpy as np
from typing import List, Dict, Any, Tuple
from collections import defaultdict, deque

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

    def analyze_zones_movement(
        self,
        active_tracks: List[Dict[str, Any]],
        zones: List[Dict[str, Any]],
        frame_w: int,
        frame_h: int
    ) -> Dict[str, Dict[str, Any]]:
        """
        Analyzes zone-level speed, dominant flow direction, and opposing flow.
        Opposing flow: split vectors by dominant axis into two groups; flag when the smaller group
        is >25% of total and both groups maintain meaningful speed (>0.02 %/s).
        """
        results = {}

        for z in zones:
            z_id = z["id"]
            c_start, c_end = z["col_range"]
            r_start, r_end = z["row_range"]

            # Filter tracks in this zone
            z_tracks = []
            for t in active_tracks:
                cx, y2 = t["center_bottom"]
                col = min(max(int(cx / float(frame_w) * 8), 0), 7)
                row = min(max(int(y2 / float(frame_h) * 8), 0), 7)

                if c_start <= col <= c_end and r_start <= row <= r_end:
                    z_tracks.append(t)

            if not z_tracks:
                results[z_id] = {
                    "avg_speed": 0.0,
                    "dominant_direction": "STATIONARY",
                    "opposing_flow": False,
                    "movement_status": "STAGNANT",
                    "surging": False
                }
                continue

            moving_tracks = [t for t in z_tracks if t["track_id"] is not None and t["speed_norm"] >= 0.02]
            speeds = [t["speed_norm"] for t in z_tracks if t["track_id"] is not None]
            avg_speed = float(np.mean(speeds)) if speeds else 0.0

            vxs = [t["vx_norm"] for t in moving_tracks]
            vys = [t["vy_norm"] for t in moving_tracks]

            mean_vx = float(np.mean(vxs)) if vxs else 0.0
            mean_vy = float(np.mean(vys)) if vys else 0.0

            dominant_dir = self.get_cardinal_direction(mean_vx, mean_vy)

            # Opposing Flow via Dominant Axis Vector Splitting:
            # 1. Determine dominant movement axis (X or Y) from standard deviation or total variance
            # 2. Split vectors into Positive group vs Negative group along that axis
            # 3. Check if smaller group > 25% of total moving vectors and both groups have avg speed > 0.02
            opposing_flow = False
            if len(moving_tracks) >= 4:
                std_x = float(np.std(vxs)) if vxs else 0.0
                std_y = float(np.std(vys)) if vys else 0.0

                dominant_axis_v = vxs if std_x >= std_y else vys

                pos_group = [v for v in dominant_axis_v if v > 0.01]
                neg_group = [v for v in dominant_axis_v if v < -0.01]

                total_moving = len(moving_tracks)
                min_group_size = min(len(pos_group), len(neg_group))

                if (min_group_size / float(total_moving)) >= 0.25:
                    pos_speed = float(np.mean(pos_group)) if pos_group else 0.0
                    neg_speed = float(np.abs(np.mean(neg_group))) if neg_group else 0.0
                    if pos_speed > 0.02 and neg_speed > 0.02:
                        opposing_flow = True

            # Sudden speed surge detection
            speed_hist = self.zone_speed_history[z_id]
            surging = False
            if len(speed_hist) >= 10:
                baseline_speed = float(np.mean(speed_hist))
                if baseline_speed > 0.01 and avg_speed > baseline_speed * 2.0:
                    surging = True
            speed_hist.append(avg_speed)

            # Assign Movement Status
            if opposing_flow:
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
                "surging": surging
            }

        return results
