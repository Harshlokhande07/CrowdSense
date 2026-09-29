import cv2
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from core.config import (
    GRID_SIZE,
    DENSITY_NORMAL_MAX,
    DENSITY_ELEVATED_MAX,
    DENSITY_HIGH_MAX,
    ZONES_CONFIG,
    CAMERA_CALIBRATION_POINTS,
    get_density_thresholds
)

class DensityMapEstimatorHook:
    """
    Documented Extension Hook for Density-Map Regression (e.g. CSRNet, DM-Count, MCNN).
    When visual crowd density exceeds individual bounding box detection capability (e.g. > 5 people/m²),
    this interface can be registered to provide continuous density map integration.
    """
    def estimate_density_map(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Takes input BGR frame and returns continuous 2D density map array of shape (H, W).
        Returns None when fallback model is not active.
        """
        return None

class GridDensityAnalyzer:
    def __init__(
        self,
        grid_size: int = GRID_SIZE,
        alpha_ema: float = 0.3,
        calibration_points: Optional[str] = CAMERA_CALIBRATION_POINTS,
        demo_mode: bool = False
    ):
        self.grid_size = grid_size
        self.alpha_ema = alpha_ema  # Exponential Moving Average factor for temporal smoothing
        self.smoothed_grid = np.zeros((grid_size, grid_size), dtype=float)
        self.calibration_matrix = None
        self.ground_area_sq_m = 100.0  # Default nominal 10m x 10m monitored area
        self.density_map_hook: Optional[DensityMapEstimatorHook] = None
        self.demo_mode = demo_mode

        self._init_calibration(calibration_points)

    def set_demo_mode(self, demo_mode: bool):
        """Updates active demo mode threshold profile."""
        self.demo_mode = demo_mode

    def _init_calibration(self, points_str: Optional[str]):
        """Parses optional 4-point ground calibration points (x1,y1;x2,y2;x3,y3;x4,y4)."""
        if not points_str:
            return
        try:
            # Format expected: x1,y1;x2,y2;x3,y3;x4,y4 (top-left, top-right, bottom-right, bottom-left)
            pairs = points_str.strip().split(";")
            if len(pairs) == 4:
                src_pts = []
                for p in pairs:
                    x, y = map(float, p.strip().split(","))
                    src_pts.append([x, y])
                src_np = np.array(src_pts, dtype=np.float32)
                # Map to standard metric 10x10 meter square ground plane
                dst_np = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=np.float32)
                self.calibration_matrix = cv2.getPerspectiveTransform(src_np, dst_np)
        except Exception:
            self.calibration_matrix = None

    def register_density_hook(self, hook: DensityMapEstimatorHook):
        """Registers an optional density-map estimation hook."""
        self.density_map_hook = hook

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

            if self.calibration_matrix is not None:
                # Transform point via ground homography
                pt = np.array([[[cx, y2]]], dtype=np.float32)
                mapped = cv2.perspectiveTransform(pt, self.calibration_matrix)[0][0]
                gx, gy = mapped[0], mapped[1]
                col = min(max(int(gx / 10.0 * self.grid_size), 0), self.grid_size - 1)
                row = min(max(int(gy / 10.0 * self.grid_size), 0), self.grid_size - 1)
            else:
                col = min(max(int(cx / float(frame_width) * self.grid_size), 0), self.grid_size - 1)
                row = min(max(int(y2 / float(frame_height) * self.grid_size), 0), self.grid_size - 1)

            raw_grid[row, col] += 1

        return raw_grid

    def update_smoothing(self, raw_grid: np.ndarray) -> np.ndarray:
        """Applies Exponential Moving Average (EMA) smoothing across frames to prevent jitter."""
        self.smoothed_grid = self.alpha_ema * raw_grid + (1.0 - self.alpha_ema) * self.smoothed_grid
        return self.smoothed_grid

    @staticmethod
    def get_density_level(count: float, demo_mode: bool = False) -> str:
        """
        Classifies cell count into risk levels using active threshold profile:
        Prod: NORMAL (0-2), ELEVATED (3-4), HIGH (5-6), CRITICAL (7+)
        Demo: NORMAL (0-1), ELEVATED (2), HIGH (3), CRITICAL (4+)
        """
        thresh = get_density_thresholds(demo_mode)
        if count <= thresh["DENSITY_NORMAL_MAX"]:
            return "NORMAL"
        elif count <= thresh["DENSITY_ELEVATED_MAX"]:
            return "ELEVATED"
        elif count <= thresh["DENSITY_HIGH_MAX"]:
            return "HIGH"
        else:
            return "CRITICAL"

    def compute_density_per_m2(self, raw_grid: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Computes people per m² per cell and overall average.
        Uses calibrated cell area if available; otherwise uses perspective row weighting.
        """
        cell_area_m2 = self.ground_area_sq_m / (self.grid_size * self.grid_size)  # ~1.56 m² per cell
        grid_m2 = np.zeros((self.grid_size, self.grid_size), dtype=float)

        for r in range(self.grid_size):
            # Perspective row weight: upper rows (r=0..2) cover larger physical ground footprint in perspective
            row_weight = 1.0 if self.calibration_matrix is not None else (1.0 + (self.grid_size - 1 - r) * 0.15)
            effective_area = cell_area_m2 * row_weight
            for c in range(self.grid_size):
                grid_m2[r, c] = round(float(raw_grid[r, c]) / max(effective_area, 0.1), 2)

        avg_m2 = float(grid_m2.mean())
        return grid_m2, round(avg_m2, 2)

    def analyze(self, raw_grid: np.ndarray) -> Dict[str, Any]:
        """
        Computes overall grid density statistics, physical density per m², and zone aggregations.
        """
        smoothed_grid = self.update_smoothing(raw_grid)
        density_m2_grid, avg_density_m2 = self.compute_density_per_m2(raw_grid)

        total_people = int(raw_grid.sum())
        avg_density = float(raw_grid.mean())
        max_density = int(raw_grid.max())
        max_density_m2 = float(density_m2_grid.max())

        thresh = get_density_thresholds(self.demo_mode)
        # Hot cells count (cells at or above ELEVATED threshold)
        hot_cells_count = int((raw_grid > thresh["DENSITY_ELEVATED_MAX"]).sum())
        overall_level = self.get_density_level(max_density, self.demo_mode)

        # Aggregate metrics for predefined ZONES
        zones_status = []
        for z in ZONES_CONFIG:
            c_start, c_end = z["col_range"]
            r_start, r_end = z["row_range"]

            sub_grid = raw_grid[r_start:r_end + 1, c_start:c_end + 1]
            sub_smoothed = smoothed_grid[r_start:r_end + 1, c_start:c_end + 1]
            sub_m2 = density_m2_grid[r_start:r_end + 1, c_start:c_end + 1]

            z_count = int(sub_grid.sum())
            z_avg_density = float(sub_grid.mean())
            z_max_cell = int(sub_grid.max())
            z_density_m2 = float(sub_m2.mean())
            z_level = self.get_density_level(z_max_cell, self.demo_mode)

            zones_status.append({
                "id": z["id"],
                "name": z["name"],
                "count": z_count,
                "density_avg": round(z_avg_density, 2),
                "density_per_m2": round(z_density_m2, 2),
                "max_cell_count": z_max_cell,
                "level": z_level,
                "col_range": z["col_range"],
                "row_range": z["row_range"]
            })

        return {
            "raw_grid": raw_grid.tolist(),
            "smoothed_grid": np.round(smoothed_grid, 2).tolist(),
            "density_m2_grid": density_m2_grid.tolist(),
            "total_people": total_people,
            "avg_density": round(avg_density, 2),
            "avg_density_per_m2": avg_density_m2,
            "max_density": max_density,
            "max_density_per_m2": round(max_density_m2, 2),
            "hot_cells_count": hot_cells_count,
            "overall_level": overall_level,
            "calibrated": self.calibration_matrix is not None,
            "zones": zones_status
        }

