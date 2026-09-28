"""
Accuracy Measurement Script for CrowdSense Person Detector.
Evaluates YOLOv8 detector against manually-labeled frame counts from a sample video.

Outputs:
  - Terminal metrics table
  - results/accuracy_latest.json
"""

import os
import sys
import argparse
import csv
import json
import time
from typing import List, Dict, Any, Tuple
import cv2
import numpy as np

# Ensure project root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import CONF_THRESHOLD, MODEL_PATH
from core.detector import PersonDetector

def compute_accuracy_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes MAE, MAPE, bias, and per-row statistics from labeled vs detected pairs.

    Parameters:
        rows: List of dicts containing 'manual_count' and 'detected_count'.

    Returns:
        Dict with keys: n_samples, mae, mape, bias, per_row
    """
    n_samples = len(rows)
    if n_samples == 0:
        return {
            "n_samples": 0,
            "mae": 0.0,
            "mape": 0.0,
            "bias": 0.0,
            "per_row": []
        }

    total_abs_error = 0.0
    total_diff = 0.0
    ape_list = []
    per_row_out = []

    for r in rows:
        m = int(r["manual_count"])
        d = int(r["detected_count"])
        ts = float(r.get("timestamp_sec", 0.0))

        diff = d - m
        abs_err = abs(diff)

        total_abs_error += abs_err
        total_diff += diff

        if m > 0:
            ape = (abs_err / float(m)) * 100.0
            ape_list.append(ape)

        per_row_out.append({
            "timestamp_sec": ts,
            "manual_count": m,
            "detected_count": d,
            "abs_error": abs_err,
            "diff": diff
        })

    mae = total_abs_error / float(n_samples)
    bias = total_diff / float(n_samples)
    mape = (sum(ape_list) / float(len(ape_list))) if len(ape_list) > 0 else 0.0

    return {
        "n_samples": n_samples,
        "mae": round(mae, 2),
        "mape": round(mape, 2),
        "bias": round(bias, 2),
        "per_row": per_row_out
    }

def main():
    parser = argparse.ArgumentParser(description="CrowdSense Person Detector Accuracy Measurement")
    parser.add_argument("--video", type=str, default="crowd.mp4", help="Path to evaluation video file")
    parser.add_argument("--labels", type=str, required=True, help="Path to CSV file with timestamp_sec,manual_count")
    parser.add_argument("--output", type=str, default="results/accuracy_latest.json", help="JSON output filepath")
    args = parser.parse_args()

    # 1. Validate labels file presence
    if not os.path.exists(args.labels):
        sys.stderr.write(f"[ERROR] Labeled CSV file '{args.labels}' not found on disk.\n")
        sys.exit(1)

    # 2. Validate video file presence
    if not os.path.exists(args.video):
        sys.stderr.write(f"[ERROR] Video file '{args.video}' not found on disk.\n")
        sys.exit(1)

    # 3. Initialize Person Detector
    detector = PersonDetector(model_path=MODEL_PATH, conf_threshold=CONF_THRESHOLD)
    if detector.status != "READY" or detector.model is None:
        sys.stderr.write(f"[ERROR] Person detector AI model is unavailable. Status: {detector.status}\n")
        sys.exit(1)

    # 4. Open video
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.stderr.write(f"[ERROR] Could not open video file '{args.video}'.\n")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0

    # 5. Read CSV labels
    eval_rows = []
    with open(args.labels, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = float(row["timestamp_sec"])
                mc = int(row["manual_count"])
                eval_rows.append({"timestamp_sec": ts, "manual_count": mc})
            except (KeyError, ValueError) as e:
                sys.stderr.write(f"[WARNING] Skipping malformed CSV row {row}: {e}\n")

    if not eval_rows:
        sys.stderr.write("[ERROR] No valid rows found in labels CSV file.\n")
        sys.exit(1)

    # 6. Process frame evaluation
    processed_samples = []
    for r in eval_rows:
        ts = r["timestamp_sec"]
        m_count = r["manual_count"]
        frame_idx = int(ts * fps)

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            sys.stderr.write(f"[WARNING] Could not seek/read frame at timestamp {ts}s (frame {frame_idx}).\n")
            continue

        detections, _ = detector.detect_and_track(frame)
        d_count = len(detections)

        processed_samples.append({
            "timestamp_sec": ts,
            "manual_count": m_count,
            "detected_count": d_count
        })

    cap.release()

    # 7. Compute metrics
    metrics = compute_accuracy_metrics(processed_samples)
    video_name = os.path.basename(args.video)

    out_payload = {
        "video_filename": video_name,
        "conf_threshold": CONF_THRESHOLD,
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_samples": metrics["n_samples"],
        "mae": metrics["mae"],
        "mape": metrics["mape"],
        "bias": metrics["bias"],
        "disclaimer": f"Measured on {metrics['n_samples']} frames of 1 video. Not a general accuracy claim.",
        "per_row": metrics["per_row"]
    }

    # 8. Save output JSON
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2)

    # 9. Print Terminal Summary
    print("\n" + "=" * 70)
    print(" 🎯 CROWDSENSE DETECTOR ACCURACY MEASUREMENT REPORT")
    print("=" * 70)
    print(f" Video File:      {video_name}")
    print(f" Confidence Thresh: {CONF_THRESHOLD}")
    print(f" Sample Frames:    {metrics['n_samples']}")
    print("-" * 70)
    print(f" MAE (Mean Abs Error):           {metrics['mae']} people")
    print(f" MAPE (Mean Abs % Error):        {metrics['mape']}%")
    print(f" Bias (Detected - Manual):       {metrics['bias']} (Negative = Undercounting)")
    print("-" * 70)
    print(f" Saved to: {args.output}")
    print(" Disclaimer: Measured on 1 video. Not a general accuracy claim.")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
