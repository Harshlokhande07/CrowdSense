"""
Contract Test verifying that all JSON keys accessed in Frontend/script.js
exist in the backend engine JSON payload contract.
"""

import os
import re
import pytest
from core.engine import CrowdEngine

def test_frontend_backend_contract():
    # 1. Obtain backend JSON payload state snapshot
    engine = CrowdEngine(demo_mode=True)
    payload = engine.process_next_frame()

    # Define flatten keys extractor helper
    def get_all_keys(d, prefix=""):
        keys = set()
        if isinstance(d, dict):
            for k, v in d.items():
                full_key = f"{prefix}.{k}" if prefix else k
                keys.add(full_key)
                if isinstance(v, dict):
                    keys.update(get_all_keys(v, full_key))
                elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                    keys.update(get_all_keys(v[0], full_key))
        return keys

    backend_keys = get_all_keys(payload)

    # Core required schema contract keys
    required_keys = {
        "timestamp",
        "system",
        "system.camera",
        "system.model",
        "system.database",
        "system.fps",
        "system.demo_mode",
        "people_count",
        "density",
        "density.avg",
        "density.max",
        "density.level",
        "risk",
        "risk.level",
        "risk.score",
        "grid",
        "zones",
        "zones.id",
        "zones.name",
        "zones.count",
        "zones.density_avg",
        "zones.max_cell_count",
        "zones.level",
        "zones.movement",
        "zones.risk_score",
        "zones.reasons",
        "zones.prediction",
        "movement",
        "movement.direction",
        "movement.avg_speed",
        "movement.status",
        "bottlenecks",
        "alerts_active",
        "alerts_history",
        "notifications"
    }

    missing_keys = required_keys - backend_keys
    assert not missing_keys, f"Backend payload is missing schema contract keys: {missing_keys}"
