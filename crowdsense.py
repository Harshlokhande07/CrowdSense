"""
CrowdSense — OpenCV Window Standalone Desktop Application
Run:
    python crowdsense.py [--demo]
Uses shared core.engine.CrowdEngine pipeline.
"""

import sys
import cv2
import time
from core.config import VIDEO_SRC, DEMO_MODE
from core.engine import CrowdEngine

def main():
    demo_flag = "--demo" in sys.argv or DEMO_MODE
    print("\n[CrowdSense] Launching Desktop Window Application...")
    print(f"[CrowdSense] Mode: {'DEMO' if demo_flag else 'LIVE CAMERA'}")
    print("[CrowdSense] Controls: Press 'q' or ESC to quit, 'h' to toggle heatmap.\n")

    engine = CrowdEngine(video_src=VIDEO_SRC, demo_mode=demo_flag)
    show_heatmap = True

    while True:
        state = engine.process_next_frame()

        if show_heatmap and engine.latest_processed_frame is not None:
            frame = engine.latest_processed_frame.copy()
        elif engine.latest_frame is not None:
            frame = engine.latest_frame.copy()
        else:
            time.sleep(0.04)
            continue

        # Draw HUD stats overlay
        h, w = frame.shape[:2]
        people = state.get("people_count", 0)
        risk_level = state.get("risk", {}).get("level", "NORMAL")
        fps = state.get("system", {}).get("fps", 0.0)

        # Banner at top
        banner_color = (0, 200, 0) if risk_level == "NORMAL" else (0, 120, 255) if risk_level == "HIGH" else (0, 0, 255)
        cv2.rectangle(frame, (0, 0), (w, 45), banner_color, -1)
        cv2.putText(
            frame,
            f"CrowdSense | Risk: {risk_level} | People: {people} | FPS: {fps:.1f}",
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2
        )

        cv2.imshow("CrowdSense - Control Room Feed", frame)

        key = cv2.waitKey(30) & 0xFF
        if key in [ord('q'), 27]:
            break
        elif key == ord('h'):
            show_heatmap = not show_heatmap

    engine.release()
    cv2.destroyAllWindows()
    print("[CrowdSense] Window closed.")

if __name__ == "__main__":
    main()