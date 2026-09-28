"""
Heatmap & Grid Matrix Overlay Generator.
Visualizes per-cell density heatmap overlays onto raw video frames using real detection data.
"""

import cv2
import numpy as np
from typing import Tuple, List, Dict, Any

from core.config import GRID_SIZE, DENSITY_NORMAL_MAX, DENSITY_ELEVATED_MAX, DENSITY_HIGH_MAX

# Standard BGR Color Palette
COLOR_LOW      = (0, 200, 0)      # Green (NORMAL)
COLOR_ELEVATED = (0, 215, 255)    # Yellow (ELEVATED)
COLOR_HIGH     = (0, 120, 255)    # Orange (HIGH)
COLOR_CRITICAL = (0, 0, 255)      # Red (CRITICAL)
COLOR_GRID     = (255, 255, 255)  # White

class HeatmapVisualizer:
    def __init__(self, grid_size: int = GRID_SIZE, alpha: float = 0.35):
        self.grid_size = grid_size
        self.alpha = alpha

    def draw_heatmap(self, frame: np.ndarray, raw_grid: np.ndarray, draw_labels: bool = True) -> np.ndarray:
        """
        Overlays a color-coded density heatmap onto the frame.
        Uses real detections and per-cell counts.
        """
        if frame is None or frame.size == 0:
            return frame

        h, w = frame.shape[:2]
        cell_w = w // self.grid_size
        cell_h = h // self.grid_size

        overlay = frame.copy()

        for gy in range(self.grid_size):
            for gx in range(self.grid_size):
                count = raw_grid[gy, gx]
                if count == 0:
                    continue

                if count > DENSITY_HIGH_MAX:
                    color = COLOR_CRITICAL
                elif count > DENSITY_ELEVATED_MAX:
                    color = COLOR_HIGH
                elif count > DENSITY_NORMAL_MAX:
                    color = COLOR_ELEVATED
                else:
                    color = COLOR_LOW

                x1 = gx * cell_w
                y1 = gy * cell_h
                x2 = (gx + 1) * cell_w if gx < self.grid_size - 1 else w
                y2 = (gy + 1) * cell_h if gy < self.grid_size - 1 else h

                cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)

        # Blend heatmap layer with main image
        blended = cv2.addWeighted(overlay, self.alpha, frame, 1.0 - self.alpha, 0)

        # Draw grid lines and optional count text
        if draw_labels:
            for gy in range(self.grid_size):
                for gx in range(self.grid_size):
                    count = raw_grid[gy, gx]
                    x1 = gx * cell_w
                    y1 = gy * cell_h

                    # Draw subtle grid boundary line
                    cv2.rectangle(blended, (x1, y1), (x1 + cell_w, y1 + cell_h), (80, 80, 80), 1)

                    if count > 0:
                        cv2.putText(
                            blended,
                            str(count),
                            (x1 + 8, y1 + cell_h // 2 + 5),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 255, 255),
                            1,
                            cv2.LINE_AA
                        )

        return blended
