"""
Person Detection & Tracking Module using YOLOv8.
Handles graceful model initialization, frame resizing, class filtering, and ByteTrack object tracking.
"""

import os
import logging
import numpy as np
import cv2
from typing import Tuple, List, Dict, Any

from core.config import MODEL_PATH, CONF_THRESHOLD, INFERENCE_RESIZE_WIDTH

logger = logging.getLogger("CrowdSense.Detector")

class PersonDetector:
    def __init__(self, model_path: str = MODEL_PATH, conf_threshold: float = CONF_THRESHOLD):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.model = None
        self.status = "UNINITIALIZED"

        self._load_model()

    def _load_model(self):
        """Attempts to load the YOLOv8 model safely."""
        if not os.path.exists(self.model_path):
            logger.warning(f"Model file '{self.model_path}' not found on disk.")
            self.status = "AI MODEL UNAVAILABLE"
            self.model = None
            return

        try:
            from ultralytics import YOLO
            self.model = YOLO(self.model_path)
            self.status = "READY"
            logger.info(f"YOLOv8 model successfully loaded from {self.model_path}")
        except Exception as e:
            logger.error(f"Failed to initialize YOLO model: {e}")
            self.status = "AI MODEL UNAVAILABLE"
            self.model = None

    def detect_and_track(self, frame: np.ndarray) -> Tuple[List[Dict[str, Any]], str]:
        """
        Runs ByteTrack detection and tracking on a single video frame.

        Returns:
            detections: List of dicts containing:
                - 'box': (x1, y1, x2, y2)
                - 'center_bottom': (cx, y2) -> foot level location for ground density
                - 'center': (cx, cy)
                - 'confidence': float
                - 'track_id': int or None
            status: Model status string ("READY" or "AI MODEL UNAVAILABLE")
        """
        if self.model is None or self.status != "READY":
            return [], self.status

        if frame is None or frame.size == 0:
            return [], self.status

        try:
            h_orig, w_orig = frame.shape[:2]
            
            # Optional resize for fast inference
            if INFERENCE_RESIZE_WIDTH > 0 and w_orig > INFERENCE_RESIZE_WIDTH:
                scale = INFERENCE_RESIZE_WIDTH / float(w_orig)
                target_h = int(h_orig * scale)
                resized_frame = cv2.resize(frame, (INFERENCE_RESIZE_WIDTH, target_h))
            else:
                scale = 1.0
                resized_frame = frame

            # Run tracking with ByteTrack, filtering strictly for class 0 (person)
            results = self.model.track(
                resized_frame,
                persist=True,
                tracker="bytetrack.yaml",
                classes=[0],
                conf=self.conf_threshold,
                verbose=False
            )[0]

            detections = []
            if results.boxes is not None and len(results.boxes) > 0:
                boxes_xyxy = results.boxes.xyxy.cpu().numpy()
                confs = results.boxes.conf.cpu().numpy() if results.boxes.conf is not None else [1.0] * len(boxes_xyxy)
                
                track_ids = None
                if results.boxes.id is not None:
                    track_ids = results.boxes.id.int().cpu().numpy().tolist()

                for idx, box in enumerate(boxes_xyxy):
                    # Rescale box back to original frame dimensions
                    x1 = float(box[0] / scale)
                    y1 = float(box[1] / scale)
                    x2 = float(box[2] / scale)
                    y2 = float(box[3] / scale)

                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0

                    t_id = int(track_ids[idx]) if track_ids is not None and idx < len(track_ids) else None

                    detections.append({
                        "box": (x1, y1, x2, y2),
                        "center": (cx, cy),
                        "center_bottom": (cx, y2),  # Bottom-center is preferable for ground position
                        "confidence": float(confs[idx]),
                        "track_id": t_id
                    })

            return detections, "READY"

        except Exception as e:
            logger.error(f"Error during detection inference: {e}")
            return [], "READY"
