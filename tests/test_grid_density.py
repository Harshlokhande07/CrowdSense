"""
Unit tests for 8x8 Grid Mapping and Density Analysis.
"""

import numpy as np
import pytest
from core.density import GridDensityAnalyzer

def test_grid_mapping_edge_cases():
    analyzer = GridDensityAnalyzer(grid_size=8)
    frame_w, frame_h = 640, 480

    detections = [
        {"center_bottom": (0.0, 0.0)},            # Top-Left corner (0,0)
        {"center_bottom": (640.0, 480.0)},        # Bottom-Right corner (W, H)
        {"center_bottom": (320.0, 240.0)},        # Center (320, 240)
        {"center_bottom": (-10.0, -10.0)},        # Out-of-bounds negative
        {"center_bottom": (700.0, 500.0)}         # Out-of-bounds positive
    ]

    grid = analyzer.map_to_grid(detections, frame_w, frame_h)

    assert grid.shape == (8, 8)
    assert grid[0, 0] >= 1  # Top-left cell
    assert grid[7, 7] >= 1  # Bottom-right cell (clamped)
    assert grid.sum() == 5   # All 5 mapped safely without out-of-index error

def test_density_levels():
    assert GridDensityAnalyzer.get_density_level(0) == "NORMAL"
    assert GridDensityAnalyzer.get_density_level(2) == "NORMAL"
    assert GridDensityAnalyzer.get_density_level(3) == "ELEVATED"
    assert GridDensityAnalyzer.get_density_level(4) == "ELEVATED"
    assert GridDensityAnalyzer.get_density_level(5) == "HIGH"
    assert GridDensityAnalyzer.get_density_level(6) == "HIGH"
    assert GridDensityAnalyzer.get_density_level(7) == "CRITICAL"
    assert GridDensityAnalyzer.get_density_level(15) == "CRITICAL"

def test_ema_smoothing():
    analyzer = GridDensityAnalyzer(grid_size=8, alpha_ema=0.5)
    raw1 = np.zeros((8, 8), dtype=int)
    raw1[0, 0] = 10

    smoothed1 = analyzer.update_smoothing(raw1)
    assert smoothed1[0, 0] == 5.0  # 0.5 * 10 + 0.5 * 0 = 5.0

    raw2 = np.zeros((8, 8), dtype=int)
    smoothed2 = analyzer.update_smoothing(raw2)
    assert smoothed2[0, 0] == 2.5  # 0.5 * 0 + 0.5 * 5.0 = 2.5
