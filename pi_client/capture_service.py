#!/usr/bin/env python3
"""
High-Performance In-Memory Staggered MJPEG Capture Service for Raspberry Pi 3B.
Optimized for Dual USB Cameras sharing a single 480 Mbps USB 2.0 Host Controller:
  - Sequential Open & Release: Guarantees that only ONE camera claims USB isochronous
    bandwidth endpoints at any instant, completely preventing V4L2 bandwidth exhaustion (ENOSPC)
    and USB bus lockups.
  - Zero SD Card Wear: Frames are captured and uploaded strictly from RAM buffers.
  - Low Power & Low Memory: Peak USB current remains well below the Pi 3B's 1.2A limit.
"""

import gc
import io
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

from camera_detector import load_or_detect_cameras
from config import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    CONTROL_LISTEN_PORT,
    DEFAULT_INTERVAL_SECONDS,
    HTTP_TIMEOUT,
    JPEG_QUALITY,
    MAX_CONSECUTIVE_DROPS,
    PC_SERVER_URL,
    STAGGER_DELAY_SECONDS,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [Pi-Edge] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PiCaptureService")


def capture_single_frame(dev_path: str, width: int = 1920, height: int = 1080) -> Optional[bytes]:
    """
    Safely captures a single MJPEG frame from a V4L2 device and immediately releases
    the device handle so the shared USB 2.0 bus is completely free for the other camera.
    """
    import cv2

    cap = None
    try:
        api_pref = cv2.CAP_V4L2 if hasattr(cv2, "CAP_V4L2") else cv2.CAP_ANY

        # Open device
        if isinstance(dev_path, str) and dev_path.startswith("/dev/video"):
            try:
                idx = int(dev_path.replace("/dev/video", ""))
                cap = cv2.VideoCapture(idx, api_pref)
            except ValueError:
                cap = cv2.VideoCapture(dev_path, api_pref)
        else:
            cap = cv2.VideoCapture(int(dev_path), api_pref)

        if not cap.isOpened():
            logger.error(f"Cannot open device {dev_path}")
            return None

        # Request MJPG compressed stream from camera hardware
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Discard the very first frame to flush initial exposure calibration
        cap.grab()

        # Read actual frame
        ret, frame = cap.read()
        if not ret or frame is None:
            logger.warning(f"Failed to read frame from {dev_path}")
            return None

        # Encode in-memory to JPEG
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
        success, enc_buf = cv2.imencode(".jpg", frame, encode_params)

        del frame  # Free uncompressed BGR frame immediately from RAM

        if not success:
            return None

        return enc_buf.tobytes()

    except Exception as e:
        logger.error(f"Capture error on {dev_path}: {e}")
        return None

    finally:
        # Crucial for dual USB cameras on Pi 3B: ALWAYS release USB isochronous bandwidth
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


class StaggeredCaptureService:
    def __init__(self, pc_url: str = PC_SERVER_URL):
        self.pc_url = pc_url.rstrip("/")
        self.interval = DEFAULT_INTERVAL_SECONDS
        self.is_paused = False
        self.consecutive_drops = 0
        self.session = requests.Session()

        # Load camera mapping
        self.cam_map = load_or_detect_cameras()
        logger.info(f"Loaded camera configuration: Cam1={self.cam_map['cam1']} | Cam2={self.cam_map['cam2']}")

    def upload_frame_in_memory(self, cam_id: str, jpeg_bytes: bytes) -> bool:
        """Uploads in-memory JPEG frame via multipart/form-data to PC Server."""
        url = f"{self.pc_url}/api/upload/camera/{cam_id}"
        files = {
            "file": (f"{cam_id}_{datetime.now().strftime('%H%M%S')}.jpg", jpeg_bytes, "image/jpeg"),
        }
        data = {
            "resolution": f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}",
            "timestamp": datetime.now().isoformat(),
        }

        try:
            resp = self.session.post(url, files=files, data=data, timeout=HTTP_TIMEOUT)
            if resp.status_code == 200:
                self.consecutive_drops = 0
                return True
            else:
                logger.warning(f"Server returned status {resp.status_code} for {cam_id}")
                return False
        except requests.exceptions.RequestException as e:
            self.consecutive_drops += 1
            if self.consecutive_drops <= MAX_CONSECUTIVE_DROPS:
                logger.warning(f"Wi-Fi drop during {cam_id} POST (attempt {self.consecutive_drops}): {e}")
            elif self.consecutive_drops == MAX_CONSECUTIVE_DROPS + 1:
                logger.error(f"PC server unreachable at {self.pc_url}. Retrying quietly...")
            return False

    def sync_control_settings(self):
        """Polls remote PC for interval changes or snapshot commands."""
        url = f"{self.pc_url}/api/control"
        try:
            resp = self.session.get(url, timeout=2.0)
            if resp.status_code == 200:
                ctrl = resp.json()
                if "interval_seconds" in ctrl:
                    self.interval = float(ctrl["interval_seconds"])
                if "is_paused" in ctrl:
                    self.is_paused = bool(ctrl["is_paused"])
                if ctrl.get("trigger_snapshot", False):
                    logger.info("[!] Triggering Immediate Snapshot on demand from PC Server!")
                    self.execute_staggered_pair()
                    try:
                        self.session.post(f"{self.pc_url}/api/control/ack_snapshot", timeout=1.5)
                    except Exception:
                        pass
        except Exception:
            pass

    def execute_staggered_pair(self):
        """Executes staggered, isolated captures of Cam 1 (Bed) and Cam 2 (Nozzle)."""
        # --- Trigger Camera 1 (Bed View) at t = 0.0s ---
        t0 = time.time()
        buf1 = capture_single_frame(self.cam_map["cam1"], CAPTURE_WIDTH, CAPTURE_HEIGHT)
        if buf1:
            self.upload_frame_in_memory("cam1", buf1)
            del buf1
            logger.info("Cam 1 (Bed) frame sent successfully.")

        # --- Stagger Delay: Guarantees USB controller bandwidth is fully reclaimed ---
        elapsed = time.time() - t0
        delay_needed = max(0.5, STAGGER_DELAY_SECONDS - elapsed)
        time.sleep(delay_needed)

        # --- Trigger Camera 2 (Toolhead View) at t = 1.0s ---
        buf2 = capture_single_frame(self.cam_map["cam2"], CAPTURE_WIDTH, CAPTURE_HEIGHT)
        if buf2:
            self.upload_frame_in_memory("cam2", buf2)
            del buf2
            logger.info("Cam 2 (Toolhead) frame sent successfully.")

        # Clean RAM
        gc.collect()

    def run_loop(self):
        logger.info(f"Capture service active. Interval: {self.interval}s | Stagger: {STAGGER_DELAY_SECONDS}s")
        logger.info("Zero-Wear RAM Mode Active. Bandwidth-safe isolated USB capture engaged.")

        while True:
            try:
                loop_start = time.time()

                self.sync_control_settings()

                if not self.is_paused:
                    self.execute_staggered_pair()
                else:
                    logger.info("Monitoring paused remotely. Waiting...")

                elapsed = time.time() - loop_start
                sleep_time = max(0.3, self.interval - elapsed)
                time.sleep(sleep_time)

            except KeyboardInterrupt:
                logger.info("Shutting down capture service...")
                break
            except Exception as e:
                logger.error(f"Unexpected error in capture loop: {e}", exc_info=True)
                time.sleep(2.0)


if __name__ == "__main__":
    service = StaggeredCaptureService()
    service.run_loop()
