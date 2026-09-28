"""
8x8 Grid Density Mapping and Zone Aggregation Module.
Maps ground person detections to dynamic grid cells, applies temporal smoothing (EMA),
and evaluates prototype risk density levels per zone.
"""

import numpy as np
from typing import List, Dict, Any, Tuple
from core.config import (
    GRID_SIZE,
    DENSITY_NORMAL_MAX,
    DENSITY_ELEVATED_MAX,
    DENSITY_HIGH_MAX,
    ZONES_CONFIG
)

class GridDensityAnalyzer:
    def __init__(self, grid_size: int = GRID_SIZE, alpha_ema: float = 0.3):
        self.grid_size = grid_size
        self.alpha_ema = alpha_ema  # Exponential Moving Average factor for temporal smoothing
        self.smoothed_grid = np.zeros((grid_size, grid_size), dtype=float)

    def reset(self):
        """Resets smoothed EMA grid on source switch."""
        self.smoothed_grid = np.zeros((self.grid_size, self.grid_size), dtype=float)

    def map_to_grid(self, detections: List[Dict[str, Any]], frame_width: int, frame_height: int) -> np.ndarray:
        """
        Maps bounding box bottom-center coordinates to an 8x8 cell grid.
        Dynamically handles any frame resolution W x H.
        """
        raw_grid = np.zeros((self.grid_size, self.grid_size), dtype=int)
        if frame_width <= 0 or frame_height <= 0:
            return raw_grid

        for det in detections:
            # Prefer bottom-center of bounding box for ground position
            cx, y2 = det.get("center_bottom", det.get("center", (0, 0)))

            col = min(max(int(cx / float(frame_width) * self.grid_size), 0), self.grid_size - 1)
            row = min(max(int(y2 / float(frame_height) * self.grid_size), 0), self.grid_size - 1)

            raw_grid[row, col] += 1

        return raw_grid

    def update_smoothing(self, raw_grid: np.ndarray) -> np.ndarray:
        """Applies Exponential Moving Average (EMA) smoothing across frames to prevent jitter."""
        self.smoothed_grid = self.alpha_ema * raw_grid + (1.0 - self.alpha_ema) * self.smoothed_grid
        return self.smoothed_grid

    @staticmethod
    def get_density_level(count: float) -> str:
        """
        Classifies cell count into prototype risk levels:
        NORMAL: 0 - 2
        ELEVATED: 3 - 4
        HIGH: 5 - 6
        CRITICAL: 7+
        """
        if count <= DENSITY_NORMAL_MAX:
            return "NORMAL"
        elif count <= DENSITY_ELEVATED_MAX:
            return "ELEVATED"
        elif count <= DENSITY_HIGH_MAX:
            return "HIGH"
        else:
            return "CRITICAL"

    def analyze(self, raw_grid: np.ndarray) -> Dict[str, Any]:
        """
        Computes overall grid density statistics and zone aggregations.
        """
        smoothed_grid = self.update_smoothing(raw_grid)
        total_people = int(raw_grid.sum())
        avg_density = float(raw_grid.mean())
        max_density = int(raw_grid.max())

        # Hot cells count (cells at or above HIGH threshold)
        hot_cells_count = int((raw_grid > DENSITY_ELEVATED_MAX).sum())
        overall_level = self.get_density_level(max_density)

        # Aggregate metrics for predefined ZONES
        zones_status = []
        for z in ZONES_CONFIG:
            c_start, c_end = z["col_range"]
            r_start, r_end = z["row_range"]

            sub_grid = raw_grid[r_start:r_end + 1, c_start:c_end + 1]
            sub_smoothed = smoothed_grid[r_start:r_end + 1, c_start:c_end + 1]

            z_count = int(sub_grid.sum())
            z_avg_density = float(sub_grid.mean())
            z_max_cell = int(sub_grid.max())
            z_level = self.get_density_level(z_max_cell)

            zones_status.append({
                "id": z["id"],
                "name": z["name"],
                "count": z_count,
                "density_avg": round(z_avg_density, 2),
                "max_cell_count": z_max_cell,
                "level": z_level,
                "col_range": z["col_range"],
                "row_range": z["row_range"]
            })

        return {
            "raw_grid": raw_grid.tolist(),
            "smoothed_grid": np.round(smoothed_grid, 2).tolist(),
            "total_people": total_people,
            "avg_density": round(avg_density, 2),
            "max_density": max_density,
            "hot_cells_count": hot_cells_count,
            "overall_level": overall_level,
            "zones": zones_status
        }
