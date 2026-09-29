"""
Trend module alias forwarding to core.prediction.
Provides backward-compatible imports for TrendEstimator.
"""

from core.prediction import TrendEstimator

__all__ = ["TrendEstimator"]
