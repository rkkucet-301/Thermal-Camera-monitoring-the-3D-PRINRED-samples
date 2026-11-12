#!/usr/bin/env python3
"""
Camera Auto-Detection Utility for Dual UC-726 rev.c USB Cameras on Raspberry Pi.
Distinguishes between:
  - Cam 1: 12 MP Sensor (Sony IMX477, max ~4056x3040) -> Assigned to Bed View
  - Cam 2: 16 MP Sensor (Sony IMX298/IMX519, max ~4656x3496) -> Assigned to Toolhead / Nozzle View
"""

import glob
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

MAP_FILE = Path(__file__).resolve().parent / "camera_map.json"


def query_v4l2_device_capabilities(device_path: str) -> Tuple[int, int, str]:
    """Queries max resolution and format support of a /dev/video device via v4l2-ctl."""
    max_w, max_h = 0, 0
    device_name = "Generic UVC Camera"

    # Check device name from sysfs
    dev_name_path = Path("/sys/class/video4linux") / Path(device_path).name / "name"
    if dev_name_path.exists():
        try:
            device_name = dev_name_path.read_text().strip()
        except Exception:
            pass

    # Attempt to query formats via v4l2-ctl if installed
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "-d", device_path, "--list-formats-ext"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3.0,
        )
        # Parse resolution lines: e.g. "Size: Discrete 4656x3496" or "4056x3040"
        matches = re.findall(r"Size:\s+Discrete\s+(\d+)x(\d+)", out)
        for w_str, h_str in matches:
            w, h = int(w_str), int(h_str)
            if w * h > max_w * max_h:
                max_w, max_h = w, h
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return max_w, max_h, device_name


def probe_with_opencv(device_index: int) -> Tuple[int, int]:
    """Fallback probe using OpenCV to request high resolution and check reported capabilities."""
    try:
        import cv2

        cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2 if hasattr(cv2, "CAP_V4L2") else cv2.CAP_ANY)
        if not cap.isOpened():
            return 0, 0

        # Request maximum known dimension
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 4656)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 3496)

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        return actual_w, actual_h
    except Exception:
        return 0, 0


def detect_dual_cameras() -> Dict[str, str]:
    """
    Scans /dev/video* devices and classifies them as Cam 1 (12MP) or Cam 2 (16MP).
    Returns dict: {'cam1': '/dev/video0', 'cam2': '/dev/video2'} or device indices.
    """
    video_nodes = sorted(glob.glob("/dev/video*"))
    candidates = {}

    print(f"[*] Scanning V4L2 video nodes: {video_nodes}")

    for dev in video_nodes:
        # Check if node supports video capture
        max_w, max_h, name = query_v4l2_device_capabilities(dev)
        if max_w > 0 and max_h > 0:
            # Verify that the node can actually capture a frame (filters out metadata nodes)
            try:
                import cv2
                test_cap = cv2.VideoCapture(dev, cv2.CAP_V4L2 if hasattr(cv2, "CAP_V4L2") else cv2.CAP_ANY)
                if test_cap.isOpened():
                    test_cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    ret = test_cap.grab()
                    test_cap.release()
                    if ret:
                        candidates[dev] = {
                            "max_width": max_w,
                            "max_height": max_h,
                            "total_pixels": max_w * max_h,
                            "name": name,
                        }
            except Exception:
                pass

    # If v4l2-ctl returned empty (e.g. tool not installed), fallback to OpenCV probe
    if not candidates and video_nodes:
        for idx in range(min(len(video_nodes), 6)):
            dev_path = f"/dev/video{idx}"
            if os.path.exists(dev_path):
                w, h = probe_with_opencv(idx)
                if w > 0 and h > 0:
                    candidates[dev_path] = {
                        "max_width": w,
                        "max_height": h,
                        "total_pixels": w * h,
                        "name": f"V4L2 Device {idx}",
                    }

    camera_map = {"cam1": None, "cam2": None}

    if len(candidates) >= 2:
        # Sort candidates by max resolution (total pixels)
        # 16 MP sensor (~15-16 million pixels) > 12 MP sensor (~12 million pixels)
        sorted_cams = sorted(candidates.items(), key=lambda x: x[1]["total_pixels"])

        # The lower resolution among the two is the 12 MP (Cam 1)
        camera_map["cam1"] = sorted_cams[0][0]
        # The higher resolution is the 16 MP (Cam 2)
        camera_map["cam2"] = sorted_cams[-1][0]

        print(f"[+] Detected 12 MP Camera (Cam 1 - Bed): {camera_map['cam1']} ({sorted_cams[0][1]['max_width']}x{sorted_cams[0][1]['max_height']})")
        print(f"[+] Detected 16 MP Camera (Cam 2 - Toolhead): {camera_map['cam2']} ({sorted_cams[-1][1]['max_width']}x{sorted_cams[-1][1]['max_height']})")

    elif len(candidates) == 1:
        single_dev = list(candidates.keys())[0]
        print(f"[!] Only 1 camera detected: {single_dev}. Assigning to Cam 1.")
        camera_map["cam1"] = single_dev
        camera_map["cam2"] = single_dev

    else:
        # Default fallback for simulation or unmapped dev nodes
        print("[!] No physical V4L2 camera nodes detected. Using defaults /dev/video0 and /dev/video2.")
        camera_map["cam1"] = "/dev/video0"
        camera_map["cam2"] = "/dev/video2"

    # Save to cached camera_map.json
    try:
        with open(MAP_FILE, "w") as f:
            json.dump(camera_map, f, indent=2)
        print(f"[+] Cached camera mapping to {MAP_FILE}")
    except Exception as e:
        print(f"[!] Warning: Could not write cache file: {e}")

    return camera_map


def load_or_detect_cameras() -> Dict[str, str]:
    """Loads cached camera map if exists and devices still exist; otherwise runs detection."""
    if MAP_FILE.exists():
        try:
            with open(MAP_FILE, "r") as f:
                cached = json.load(f)
            if os.path.exists(cached.get("cam1", "")) and os.path.exists(cached.get("cam2", "")):
                return cached
        except Exception:
            pass
    return detect_dual_cameras()


if __name__ == "__main__":
    cams = detect_dual_cameras()
    print("\nResulting Camera Mapping:")
    print(json.dumps(cams, indent=2))
