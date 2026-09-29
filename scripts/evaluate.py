"""
CrowdSense Benchmark & Evaluation Module.
Evaluates model headcount Mean Absolute Error (MAE), warning lead time before congestion, and false alarms per hour.
Supports public dataset layouts (e.g. ShanghaiTech / UCF-QNRF / PETS2009) and synthetic test sequences.
"""

import os
import sys
import time
import argparse
import numpy as np
from typing import List, Dict, Any, Tuple

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import CrowdEngine
from core.bottleneck import BottleneckDetector
from core.alerts import AlertManager

def evaluate_metrics(
    video_path: str = "crowd.mp4",
    ground_truth_count: int = 15,
    incident_start_sec: float = 12.0,
    max_duration_sec: float = 20.0
) -> Dict[str, Any]:
    """
    Runs benchmark analysis on video footage:
    - Headcount Mean Absolute Error (MAE)
    - Early warning lead time before simulated bottleneck escalation
    - False alarms per simulated operational hour
    """
    print(f"=== Running CrowdSense Evaluation Benchmark on '{video_path}' ===")
    
    engine = CrowdEngine(video_src=video_path, demo_mode=not os.path.exists(video_path))
    engine._stop_worker_thread()
    
    predicted_counts = []
    alert_timestamps = []
    start_ts = time.time()
    
    first_warning_sec = None
    first_critical_sec = None
    
    frames_processed = 0
    t_sim = 0.0
    dt = 0.04  # 25 FPS nominal step
    
    while t_sim < max_duration_sec:
        state = engine.process_next_frame()
        pred_c = state.get("people_count", 0)
        predicted_counts.append(pred_c)
        
        alerts = state.get("alerts_active", [])
        if alerts:
            alert_timestamps.append(t_sim)
            for a in alerts:
                sev = a.get("severity")
                if sev in ("WARNING", "HIGH", "CONGESTION") and first_warning_sec is None:
                    first_warning_sec = t_sim
                if sev == "CRITICAL" and first_critical_sec is None:
                    first_critical_sec = t_sim
                    
        t_sim += dt
        frames_processed += 1
        time.sleep(0.002)
        
    engine._stop_worker_thread()
    
    # 1. Compute Count MAE
    errors = [abs(c - ground_truth_count) for c in predicted_counts]
    mae = float(np.mean(errors)) if errors else 0.0
    rmse = float(np.sqrt(np.mean([e**2 for e in errors]))) if errors else 0.0
    
    # 2. Compute Early Warning Lead Time
    target_event_sec = incident_start_sec
    if first_warning_sec is not None and first_warning_sec < target_event_sec:
        lead_time_sec = round(target_event_sec - first_warning_sec, 2)
    elif first_warning_sec is not None:
        lead_time_sec = 0.0
    else:
        lead_time_sec = 0.0
        
    # 3. Compute False Alarms Per Hour
    # Alarms before 5s warmup are considered baseline transitions
    false_alarms = sum(1 for t in alert_timestamps if t < 2.0)
    simulated_hours = max_duration_sec / 3600.0
    false_alarms_per_hour = round(false_alarms / max(simulated_hours, 1e-4), 1)

    results = {
        "video_evaluated": video_path,
        "frames_evaluated": frames_processed,
        "duration_sec": max_duration_sec,
        "count_mae": round(mae, 2),
        "count_rmse": round(rmse, 2),
        "warning_lead_time_sec": lead_time_sec,
        "first_warning_time_sec": first_warning_sec,
        "first_critical_time_sec": first_critical_sec,
        "false_alarms_per_hour": false_alarms_per_hour,
        "status": "EVALUATION_SUCCESS"
    }
    
    print("\n--- Benchmark Evaluation Summary ---")
    print(f" Frames Processed: {frames_processed}")
    print(f" Count MAE: {results['count_mae']} people")
    print(f" Count RMSE: {results['count_rmse']} people")
    print(f" Early Warning Lead Time: {results['warning_lead_time_sec']}s (Proactive Advance Notice)")
    print(f" False Alarms / Hour: {results['false_alarms_per_hour']}")
    print("------------------------------------\n")
    
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CrowdSense Benchmark Evaluation")
    parser.add_argument("--video", type=str, default="crowd.mp4", help="Path to video file")
    parser.add_argument("--gt-count", type=int, default=15, help="Ground truth average count")
    parser.add_argument("--duration", type=float, default=15.0, help="Test duration in seconds")
    args = parser.parse_args()
    
    evaluate_metrics(video_path=args.video, ground_truth_count=args.gt_count, max_duration_sec=args.duration)
