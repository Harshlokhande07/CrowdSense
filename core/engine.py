"""
CrowdSense Core Pipeline Engine.
Coordinates frame capture, synthetic generation (Demo Mode), YOLO detection, grid mapping,
movement vectors, bottleneck evaluation, short-term trend forecasting, and incident alerts.
Supports real-time video upload processing with native FPS pacing and frame dropping.
"""

import os
import time
import math
import random
import logging
import threading
import cv2
import numpy as np
from typing import Tuple, List, Dict, Any, Optional

from core.config import (
    VIDEO_SRC,
    MODEL_PATH,
    GRID_SIZE,
    DEMO_MODE,
    CONF_THRESHOLD,
    ZONES_CONFIG,
    PROCESS_EVERY_N_FRAMES,
    INFERENCE_IMGSZ,
    MAX_PROCESS_FPS,
    LOOP_VIDEO
)
from core.detector import PersonDetector
from core.density import GridDensityAnalyzer
from core.heatmap import HeatmapVisualizer
from core.movement import MovementAnalyzer
from core.bottleneck import BottleneckDetector
from core.prediction import TrendEstimator
from core.alerts import AlertManager

logger = logging.getLogger("CrowdSense.Engine")

class CrowdEngine:
    def __init__(self, video_src: str = VIDEO_SRC, demo_mode: bool = DEMO_MODE, start_worker: bool = True):
        self.video_src = video_src
        self.demo_mode = demo_mode
        self.lock = threading.RLock()

        # Initialize sub-modules
        self.detector = PersonDetector(model_path=MODEL_PATH, conf_threshold=CONF_THRESHOLD)
        self.grid_analyzer = GridDensityAnalyzer(grid_size=GRID_SIZE)
        self.heatmap_visualizer = HeatmapVisualizer(grid_size=GRID_SIZE)
        self.movement_analyzer = MovementAnalyzer()
        self.bottleneck_detector = BottleneckDetector()
        self.trend_estimator = TrendEstimator()
        self.alert_manager = AlertManager()

        # Camera VideoCapture instance
        self.cap: Optional[cv2.VideoCapture] = None
        self.camera_status = "OFFLINE"

        # Source mode state ("demo", "video", "webcam")
        self.source_mode: str = "demo" if demo_mode else ("video" if os.path.exists(video_src) else "webcam")
        self.display_filename: str = "SIMULATION" if self.source_mode == "demo" else (os.path.basename(video_src) if self.source_mode == "video" else "Live Webcam")
        self.uploaded_file_path: Optional[str] = None

        # Real-time processing & pacing telemetry
        self.video_fps: float = 25.0
        self.current_fps: float = 0.0
        self.dropped_frames: int = 0
        self.frame_position_sec: float = 0.0
        self.total_frames: int = 0

        self._init_camera()

        # Engine state & telemetry
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_processed_frame: Optional[np.ndarray] = None
        self.latest_state: Dict[str, Any] = self._get_default_state()

        self.prev_time = time.time()

        # Synthetic simulation state for demo mode
        self.sim_step = 0
        self.sim_tracks: List[Dict[str, Any]] = []

        # Worker thread control
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        if start_worker:
            self._start_worker_thread()

    def _get_default_state(self) -> Dict[str, Any]:
        """Generates an initial default state schema ensuring all required keys are always present."""
        now = time.time()
        notifications_status = self.alert_manager.get_system_notifications_status()
        source_info = {
            "mode": self.source_mode,
            "display_name": self.display_filename,
            "video_fps": round(self.video_fps, 1),
            "processing_fps": round(self.current_fps, 1),
            "dropped_frames": self.dropped_frames,
            "frame_position_sec": round(self.frame_position_sec, 2)
        }
        empty_grid = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]
        empty_zones = []
        for z in ZONES_CONFIG:
            empty_zones.append({
                "id": z["id"],
                "name": z["name"],
                "count": 0,
                "density_avg": 0.0,
                "density_per_m2": 0.0,
                "max_cell_count": 0,
                "level": "NORMAL",
                "movement": "STAGNANT",
                "risk_score": 0,
                "reasons": ["Normal flow conditions"],
                "prediction": {
                    "predicted_count": 0,
                    "predicted_level": "NORMAL",
                    "confidence": "Low confidence (<15 samples)",
                    "trend": "STABLE",
                    "horizon_s": 30,
                    "low_confidence": True,
                    "time_to_threshold_sec": None,
                    "forecast_message": None,
                    "disclaimer": "Requires human verification"
                },
                "forecast": {
                    "predicted_count": 0,
                    "predicted_level": "NORMAL",
                    "confidence": "Low confidence",
                    "trend": "STABLE",
                    "low_confidence": True,
                    "time_to_threshold_sec": None,
                    "message": None,
                    "horizon_s": 30
                }
            })

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "system": {
                "camera": self.camera_status,
                "model": "YOLOv8n",
                "database": notifications_status["database"],
                "fps": round(self.current_fps, 1),
                "demo_mode": self.demo_mode,
                "source": source_info
            },
            "people_count": 0,
            "density": {
                "avg": 0.0,
                "avg_density_per_m2": 0.0,
                "max": 0,
                "max_density_per_m2": 0.0,
                "level": "NORMAL",
                "hot_cells": 0
            },
            "risk": {
                "level": "NORMAL",
                "score": 0
            },
            "grid": empty_grid,
            "zones": empty_zones,
            "movement": {
                "direction": "STATIONARY",
                "avg_speed": 0.0,
                "status": "STAGNANT",
                "opposing_flow": False
            },
            "bottlenecks": [],
            "source": source_info,
            "alerts_active": [],
            "alerts_history": [],
            "notifications": notifications_status
        }

    def reset_state(self):
        """Resets tracker, grid density EMA, movement history, trend history, and active incidents on source switch."""
        if hasattr(self.detector, "reset"):
            self.detector.reset()
        self.grid_analyzer.reset()
        self.movement_analyzer.reset()
        self.bottleneck_detector.reset()
        self.trend_estimator.reset()
        self.alert_manager.reset()
        self.sim_step = 0
        self.sim_tracks.clear()
        self.dropped_frames = 0
        self.frame_position_sec = 0.0
        with self.lock:
            self.latest_state = self._get_default_state()


    def _start_worker_thread(self):
        self._stop_worker_thread()
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._processing_loop, daemon=True)
        self._worker_thread.start()
        logger.info(f"Started background processing thread for source mode '{self.source_mode}'.")

    def _stop_worker_thread(self):
        if hasattr(self, "_worker_thread") and self._worker_thread is not None and self._worker_thread.is_alive():
            self._stop_event.set()
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None
            logger.info("Stopped background processing thread.")

    def set_source(self, mode: str, file_path: Optional[str] = None, display_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Switches engine source mode ("demo", "video", "webcam"), resets state, and restarts worker thread.
        """
        allowed_modes = {"demo", "video", "webcam"}
        if mode not in allowed_modes:
            raise ValueError(f"Invalid source mode '{mode}'. Allowed modes: {allowed_modes}")

        self._stop_worker_thread()

        with self.lock:
            old_cap = self.cap
            self.cap = None
            if old_cap is not None:
                old_cap.release()

            if file_path and self.uploaded_file_path and os.path.exists(self.uploaded_file_path) and self.uploaded_file_path != file_path:
                try:
                    os.remove(self.uploaded_file_path)
                    logger.info(f"Removed previous upload file {self.uploaded_file_path}")
                except OSError as e:
                    logger.warning(f"Could not remove old upload file {self.uploaded_file_path}: {e}")

            self.source_mode = mode

            if mode == "demo":
                self.demo_mode = True
                self.video_src = ""
                self.display_filename = "SIMULATION"
                self.camera_status = "DEMO_MODE"
                self.video_fps = 25.0
            elif mode == "webcam":
                self.demo_mode = False
                self.video_src = "0"
                self.display_filename = "Live Webcam"
                self.video_fps = 30.0
                self._init_camera()
            elif mode == "video":
                self.demo_mode = False
                target_path = file_path if file_path else (self.video_src if self.video_src and self.video_src != "0" else VIDEO_SRC)
                self.video_src = target_path
                self.display_filename = display_name if display_name else os.path.basename(target_path)
                if file_path:
                    self.uploaded_file_path = file_path
                self._init_camera()

            self.reset_state()

        self._start_worker_thread()
        logger.info(f"Engine source set to mode '{self.source_mode}' ({self.display_filename}). State reset clean.")
        return self.get_source_info()

    def get_source_info(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "mode": self.source_mode,
                "display_name": self.display_filename,
                "video_fps": round(self.video_fps, 1),
                "processing_fps": round(self.current_fps, 1),
                "dropped_frames": self.dropped_frames,
                "frame_position_sec": round(self.frame_position_sec, 2)
            }

    def _init_camera(self):
        """Initializes VideoCapture from file or camera index."""
        if self.demo_mode:
            self.camera_status = "DEMO_MODE"
            logger.info("Engine running in DEMO / SIMULATION mode.")
            return

        try:
            src = int(self.video_src) if self.video_src.isdigit() else self.video_src
            self.cap = cv2.VideoCapture(src)

            if self.cap.isOpened():
                self.camera_status = "ONLINE"
                if self.source_mode == "video":
                    fps_val = self.cap.get(cv2.CAP_PROP_FPS)
                    self.video_fps = fps_val if (fps_val and fps_val > 0 and not math.isnan(fps_val)) else 25.0
                    self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
                logger.info(f"VideoCapture opened successfully: {self.video_src} (FPS: {self.video_fps})")
            else:
                logger.warning(f"Failed to open video source '{self.video_src}'. Setting camera status to OFFLINE.")
                self.camera_status = "OFFLINE"
                self.cap = None
        except Exception as e:
            logger.error(f"Error opening camera: {e}. Setting camera status to OFFLINE.")
            self.camera_status = "OFFLINE"
            self.cap = None

    def _processing_loop(self):
        """Background thread running real-time video processing loop with frame dropping and pacing."""
        logger.info(f"Processing loop active for mode '{self.source_mode}'.")
        while not self._stop_event.is_set():
            t_start = time.time()

            with self.lock:
                mode = self.source_mode
                demo = self.demo_mode
                cap = self.cap

            if demo:
                self.process_next_frame()
                t_proc = time.time() - t_start
                sleep_time = max(0.0, 0.04 - t_proc)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                continue

            if cap is None or not cap.isOpened():
                with self.lock:
                    self.camera_status = "OFFLINE"
                    self.latest_frame = self._generate_offline_frame()
                    self.latest_processed_frame = self.latest_frame
                time.sleep(0.1)
                continue

            if mode == "video":
                v_fps = max(self.video_fps, 1.0)
                frame_interval = 1.0 / v_fps

                ret, frame = cap.read()
                if not ret:
                    if LOOP_VIDEO:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = cap.read()

                if not ret or frame is None:
                    with self.lock:
                        self.camera_status = "OFFLINE"
                        self.latest_frame = self._generate_offline_frame()
                        self.latest_processed_frame = self.latest_frame
                    time.sleep(0.1)
                    continue

                curr_frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                self.frame_position_sec = round(curr_frame_idx / v_fps, 2)

                with self.lock:
                    self.camera_status = "ONLINE"

                # Run full detection & analysis pipeline
                self.process_frame(frame)

                t_proc = time.time() - t_start
                self.current_fps = 1.0 / max(t_proc, 1e-5)

                if t_proc < frame_interval:
                    time.sleep(frame_interval - t_proc)
                else:
                    frames_passed = int(t_proc / frame_interval)
                    skipped = max(0, frames_passed - 1)
                    if skipped > 0:
                        self.dropped_frames += skipped
                        next_idx = curr_frame_idx + skipped
                        cap.set(cv2.CAP_PROP_POS_FRAMES, next_idx)

            elif mode == "webcam":
                ret, frame = cap.read()
                if not ret or frame is None:
                    with self.lock:
                        self.camera_status = "OFFLINE"
                        self.latest_frame = self._generate_offline_frame()
                        self.latest_processed_frame = self.latest_frame
                    time.sleep(0.1)
                    continue

                with self.lock:
                    self.camera_status = "ONLINE"
                self.process_frame(frame)

                t_proc = time.time() - t_start
                self.current_fps = 1.0 / max(t_proc, 1e-5)
                time.sleep(0.01)

    def read_frame(self) -> Tuple[Optional[np.ndarray], bool]:
        """Reads next frame from video capture or returns offline/demo synthetic frame."""
        if self.demo_mode:
            return self._generate_synthetic_frame(), True

        if self.cap is None or not self.cap.isOpened() or self.camera_status == "OFFLINE":
            self.camera_status = "OFFLINE"
            return self._generate_offline_frame(), False

        ret, frame = self.cap.read()
        if not ret:
            if LOOP_VIDEO:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()

        if not ret or frame is None:
            self.camera_status = "OFFLINE"
            return self._generate_offline_frame(), False

        self.camera_status = "ONLINE"
        return frame, True

    def _generate_offline_frame(self) -> np.ndarray:
        w, h = 640, 480
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (15, 15, 30)
        cv2.putText(frame, "CAMERA OFFLINE", (180, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        return frame

    def _generate_synthetic_frame(self) -> np.ndarray:
        w, h = 640, 480
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (20, 24, 40)

        for x in range(0, w, w // 8):
            cv2.line(frame, (x, 0), (x, h), (40, 48, 70), 1)
        for y in range(0, h, h // 8):
            cv2.line(frame, (0, y), (w, y), (40, 48, 70), 1)

        cv2.putText(frame, "DEMO MODE — SIMULATED FEED", (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 215, 255), 2)
        return frame

    def _generate_synthetic_detections(self, w: int, h: int, now: float) -> List[Dict[str, Any]]:
        self.sim_step += 1
        num_people = 30 + int(10 * math.sin(self.sim_step / 20.0))

        detections = []
        for i in range(num_people):
            if i % 2 == 0:
                cx = random.uniform(20.0, w * 0.45)
                cy = random.uniform(h * 0.55, h - 20.0)
            else:
                cx = random.uniform(30.0, w - 30.0)
                cy = random.uniform(30.0, h - 30.0)

            box_w, box_h = 24, 50
            x1, y1 = cx - box_w / 2, cy - box_h / 2
            x2, y2 = cx + box_w / 2, cy + box_h / 2

            detections.append({
                "box": (x1, y1, x2, y2),
                "center": (cx, cy),
                "center_bottom": (cx, y2),
                "confidence": 0.88,
                "track_id": i + 1
            })
        return detections

    def process_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Executes full pipeline for a specific video frame:
        Detection -> Grid Density -> Heatmap -> Movement -> Bottleneck -> Trend -> Alerts -> JSON state.
        """
        now = time.time()

        if frame is None or frame.size == 0:
            return self.latest_state

        h, w = frame.shape[:2]

        if self.demo_mode:
            detections = self._generate_synthetic_detections(w, h, now)
            model_status = "READY (SIMULATED)"
        else:
            detections, model_status = self.detector.detect_and_track(frame)

        # Draw detection bounding boxes + track IDs on visual frame
        vis_frame = frame.copy()
        for det in detections:
            x1, y1, x2, y2 = map(int, det["box"])
            cv2.rectangle(vis_frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
            t_id = det.get("track_id")
            if t_id is not None:
                cv2.putText(vis_frame, f"ID:{t_id}", (x1, max(y1 - 5, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

        # 2. Grid Density Mapping
        raw_grid = self.grid_analyzer.map_to_grid(detections, w, h)
        density_data = self.grid_analyzer.analyze(raw_grid)

        # 3. Heatmap Overlay + Grid Labels
        processed_frame = self.heatmap_visualizer.draw_heatmap(vis_frame, raw_grid, draw_labels=True)

        # 4. Movement Analysis
        active_tracks = self.movement_analyzer.update_tracks(detections, now, w, h, self.current_fps)
        movement_zone_data = self.movement_analyzer.analyze_zones_movement(
            active_tracks, density_data["zones"], w, h
        )

        overall_vxs = [t["vx_norm"] for t in active_tracks if t["track_id"] is not None]
        overall_vys = [t["vy_norm"] for t in active_tracks if t["track_id"] is not None]
        overall_dir = MovementAnalyzer.get_cardinal_direction(
            float(np.mean(overall_vxs)) if overall_vxs else 0.0,
            float(np.mean(overall_vys)) if overall_vys else 0.0
        )
        overall_speed = float(np.mean([t["speed_norm"] for t in active_tracks])) if active_tracks else 0.0

        # 5. Bottleneck & Congestion Evaluation
        bottlenecks = self.bottleneck_detector.analyze_all_zones(
            density_data["zones"], movement_zone_data, now
        )

        # 6. Short-Term Trend Estimation (Passing bottlenecks for risk score forecasting)
        predictions = self.trend_estimator.predict_all_zones(
            density_data["zones"], now, horizon_s=30.0, bottlenecks=bottlenecks
        )

        bn_map = {b["zone_id"]: b for b in bottlenecks}
        pred_map = {p["zone_id"]: p for p in predictions}

        combined_zones = []
        for z in density_data["zones"]:
            z_id = z["id"]
            m_data = movement_zone_data.get(z_id, {})
            b_data = bn_map.get(z_id, {})
            p_data = pred_map.get(z_id, {})

            combined_zones.append({
                "id": z_id,
                "name": z["name"],
                "count": z["count"],
                "density_avg": z["density_avg"],
                "density_per_m2": z.get("density_per_m2", z["density_avg"]),
                "max_cell_count": z["max_cell_count"],
                "level": z["level"],
                "movement": m_data.get("movement_status", "STAGNANT"),
                "risk_score": b_data.get("score", 0),
                "reasons": b_data.get("reasons", []),
                "prediction": {
                    "predicted_count": p_data.get("predicted_count", z["count"]),
                    "predicted_level": p_data.get("predicted_level", z["level"]),
                    "confidence": p_data.get("confidence", "Low confidence"),
                    "trend": p_data.get("trend", "STABLE"),
                    "horizon_s": 30,
                    "low_confidence": p_data.get("low_confidence", True),
                    "time_to_threshold_sec": p_data.get("time_to_threshold_sec"),
                    "forecast_message": p_data.get("forecast_message"),
                    "disclaimer": "Requires human verification"
                },
                "forecast": {
                    "predicted_count": p_data.get("predicted_count", z["count"]),
                    "predicted_level": p_data.get("predicted_level", z["level"]),
                    "confidence": p_data.get("confidence", "Low confidence"),
                    "trend": p_data.get("trend", "STABLE"),
                    "low_confidence": p_data.get("low_confidence", True),
                    "time_to_threshold_sec": p_data.get("time_to_threshold_sec"),
                    "message": p_data.get("forecast_message"),
                    "horizon_s": 30
                }
            })

        # 7. Incident State Machine & Notifications
        active_alerts = self.alert_manager.process_zone_states(
            density_data["zones"], bottlenecks, predictions, now
        )

        max_risk_score = max([b["score"] for b in bottlenecks], default=0)
        overall_risk_level = (
            "CRITICAL" if max_risk_score >= 70
            else "HIGH" if max_risk_score >= 45
            else "WARNING" if max_risk_score >= 25
            else "NORMAL"
        )

        notifications_status = self.alert_manager.get_system_notifications_status()

        source_info = {
            "mode": self.source_mode,
            "display_name": self.display_filename,
            "video_fps": round(self.video_fps, 1),
            "processing_fps": round(self.current_fps, 1),
            "dropped_frames": self.dropped_frames,
            "frame_position_sec": round(self.frame_position_sec, 2)
        }

        with self.lock:
            self.latest_frame = frame
            self.latest_processed_frame = processed_frame
            self.latest_state = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "system": {
                    "camera": self.camera_status,
                    "model": model_status,
                    "database": notifications_status["database"],
                    "fps": round(self.current_fps, 1),
                    "demo_mode": self.demo_mode,
                    "source": source_info
                },
                "people_count": density_data["total_people"],
                "density": {
                    "avg": density_data["avg_density"],
                    "avg_density_per_m2": density_data.get("avg_density_per_m2", 0.0),
                    "max": density_data["max_density"],
                    "max_density_per_m2": density_data.get("max_density_per_m2", 0.0),
                    "level": density_data["overall_level"],
                    "hot_cells": density_data["hot_cells_count"]
                },
                "risk": {
                    "level": overall_risk_level,
                    "score": max_risk_score
                },
                "grid": density_data["raw_grid"],
                "zones": combined_zones,
                "movement": {
                    "direction": overall_dir,
                    "avg_speed": round(overall_speed, 4),
                    "status": "MOVING" if overall_speed > 0.04 else "SLOW" if overall_speed > 0.01 else "STAGNANT",
                    "opposing_flow": any(m.get("opposing_flow", False) for m in movement_zone_data.values())
                },
                "bottlenecks": [b for b in bottlenecks if b["is_bottleneck"] or b["score"] >= 25],
                "source": source_info,
                "alerts_active": active_alerts,
                "alerts_history": self.alert_manager.alerts_history[:10],
                "notifications": notifications_status
            }

        return self.latest_state

    def process_next_frame(self) -> Dict[str, Any]:
        frame, ok = self.read_frame()
        if frame is None:
            return self.latest_state
        return self.process_frame(frame)

    def release(self):
        """Releases camera resources, stops processing thread, and cleans up temporary upload files on shutdown."""
        self._stop_worker_thread()
        with self.lock:
            if self.cap is not None and self.cap.isOpened():
                self.cap.release()
                self.camera_status = "OFFLINE"
                logger.info("VideoCapture released.")
            if self.uploaded_file_path and os.path.exists(self.uploaded_file_path):
                try:
                    os.remove(self.uploaded_file_path)
                    logger.info(f"Cleaned up temporary upload file {self.uploaded_file_path} on shutdown.")
                except OSError as e:
                    logger.warning(f"Failed to remove uploaded file {self.uploaded_file_path}: {e}")
