# CrowdSense Video Ground-Truth Labelling Guide

This guide explains how to prepare ground-truth label CSV files for benchmarking CrowdSense detection accuracy, proactive warning lead time, and false alarm rates using `scripts/evaluate.py`.

---

## 1. CSV Format & Column Schema

The evaluation engine supports flexible column headers. A valid labels file should contain:

| Column Name | Required | Description | Example Values |
|---|---|---|---|
| `timestamp_sec` (or `timestamp`, `frame`) | Yes | Timestamp in seconds from the start of the video clip (or frame index / 25) | `0.0`, `2.5`, `10.0` |
| `count` (or `manual_count`, `gt_count`, `ground_truth`) | Yes | Exact manual count of people visible in the camera frame / monitored zone | `28`, `32`, `45` |
| `surge_start_sec` (or `incident_time_sec`, `incident_start_sec`) | Optional | Timestamp (sec) when the dangerous crowd surge, congestion, or incident begins | `14.5` |

### Sample CSV (`sample_labels.csv`)

```csv
timestamp_sec,manual_count,surge_start_sec
0.0,28,12.0
2.0,30,12.0
4.0,29,12.0
6.0,31,12.0
8.0,27,12.0
10.0,35,12.0
12.0,48,12.0
14.0,52,12.0
```

---

## 2. Labelling Workflow

1. **Clip Selection**:
   - Choose video clips (10–120 seconds) representing normal baseline crowd flow transitioning into a high-density bottleneck or surge.
2. **Periodic Sampling**:
   - Sample every 1.0–2.0 seconds. Pause the video and count all visible individuals whose feet or torso are inside the monitored zone.
3. **Incident Timestamp**:
   - Note the exact second when crowd compression, stoppage, or rapid accumulation crosses the safety threshold.
4. **Save CSV**:
   - Save the file as `<clip_name>_labels.csv` inside `scripts/` or `data/`.

---

## 3. Running the Evaluation Benchmark

Run evaluation on your labelled video:

```bash
# Single model evaluation
python scripts/evaluate.py --video path/to/video.mp4 --labels scripts/sample_labels.csv

# Multi-model and multi-resolution comparison
python scripts/evaluate.py --video path/to/video.mp4 --labels scripts/sample_labels.csv --model yolov8n.pt,yolov8s.pt --imgsz 640,960
```

The benchmark computes:
- **MAE (Mean Absolute Error)**: Average headcount error.
- **MAPE (%)**: Mean Absolute Percentage Error.
- **Count Bias**: Average signed error (under/over-counting).
- **Detection Recall (%)**: Percentage of ground-truth individuals detected.
- **Warning Lead Time (s)**: Seconds between first proactive warning and labelled surge time.
- **False Alarms / Hour**: Alert triggers occurring >60s away from any labelled incident.
- **JSON Export**: Results are saved to `results/eval_<timestamp>.json` and exposed at `GET /api/accuracy`.
