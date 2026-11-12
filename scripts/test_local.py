#!/usr/bin/env python3
"""
Test & Simulation Script for 3D Printer Remote Monitoring System.
Performs:
  1. Automated validation of PC Server REST endpoints.
  2. Mock generation of Cam 1 (12 MP) and Cam 2 (16 MP) frames.
  3. Realistic thermal simulation of 3D printer bed (60°C) and hotend nozzle (215°C).
  4. Disk capture verification in captures/YYYY-MM-DD/.
  5. Optional continuous loop (--simulate-live) to feed the live dashboard.
"""

import argparse
import io
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

SERVER_URL = "http://127.0.0.1:8000"


def generate_mock_camera_image(cam_name: str, width: int = 1280, height: int = 720, is_cam1: bool = True) -> bytes:
    """Generates a realistic test image simulating bed or nozzle view with timestamp overlays."""
    img = Image.new("RGB", (width, height), color=(18, 22, 30))
    draw = ImageDraw.Draw(img)

    # Draw simulated printer geometry
    if is_cam1:
        # Cam 1: Bed Wide View
        draw.rectangle([100, 300, 1180, 650], fill=(35, 42, 54), outline=(0, 210, 255), width=3)
        # Grid lines on bed
        for x in range(150, 1150, 100):
            draw.line([(x, 300), (x, 650)], fill=(48, 58, 74), width=1)
        for y in range(350, 650, 60):
            draw.line([(100, y), (1180, y)], fill=(48, 58, 74), width=1)
        # 3D printed object on bed (e.g. calibration cube)
        draw.rectangle([560, 420, 720, 580], fill=(240, 140, 0), outline=(255, 200, 50), width=2)
    else:
        # Cam 2: Close-up Toolhead View
        draw.rectangle([480, 100, 800, 400], fill=(60, 65, 75), outline=(157, 78, 221), width=4)
        # Brass Nozzle triangle
        draw.polygon([(600, 400), (680, 400), (640, 490)], fill=(212, 175, 55), outline=(255, 230, 100))
        # Filament bead
        draw.ellipse([636, 490, 644, 520], fill=(240, 140, 0))

    # Text banner overlay
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    draw.rectangle([30, 30, 600, 95], fill=(0, 0, 0, 180))
    draw.text((45, 38), f"SOURCE: {cam_name}", fill=(0, 255, 200))
    draw.text((45, 62), f"TIMESTAMP: {ts_str} | MJPEG MEMORY STREAM", fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def generate_mock_thermal_array(hotend_temp: float = 215.0, bed_temp: float = 60.0) -> Tuple[List[float], float, float, float]:
    """Generates 768 floats (32x24 grid) with a hot nozzle hotspot and heated bed profile."""
    thermal_data = []
    min_temp = 1000.0
    max_temp = -100.0

    nozzle_gx, nozzle_gy = 16, 12  # Center nozzle hotspot
    ambient = 24.5

    for y in range(24):
        for x in range(32):
            # Distance to nozzle
            dist_nozzle = math.sqrt((x - nozzle_gx) ** 2 + (y - nozzle_gy) ** 2)
            # Distance to bed center
            dist_bed = math.sqrt((x - 16) ** 2 + (y - 18) ** 2)

            # Hotend heat gradient
            t_hotend = (hotend_temp - ambient) * math.exp(-0.35 * (dist_nozzle ** 2))
            # Bed heat gradient
            t_bed = (bed_temp - ambient) * math.exp(-0.06 * (dist_bed ** 2))

            temp = round(ambient + t_hotend + t_bed, 1)

            if temp < min_temp:
                min_temp = temp
            if temp > max_temp:
                max_temp = temp

            thermal_data.append(temp)

    center_temp = thermal_data[12 * 32 + 16]
    return thermal_data, min_temp, max_temp, center_temp


def run_unit_tests():
    print("=" * 60)
    print("  AUTOMATED VERIFICATION TEST FOR 3D PRINTER MONITOR HUB")
    print("=" * 60)

    # 1. Check Server Ping
    try:
        r = requests.get(f"{SERVER_URL}/api/status", timeout=3.0)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        print("[PASS] 1. PC Server Status Endpoint online.")
    except Exception as e:
        print(f"[FAIL] Cannot reach PC server at {SERVER_URL}: {e}")
        print("Please start the server first with: python app.py inside pc_server/")
        sys.exit(1)

    # 2. Upload Cam 1 Frame
    cam1_bytes = generate_mock_camera_image("UC-726 12MP Bed View", is_cam1=True)
    r = requests.post(
        f"{SERVER_URL}/api/upload/camera/cam1",
        files={"file": ("test_cam1.jpg", cam1_bytes, "image/jpeg")},
        data={"resolution": "1920x1080"},
    )
    assert r.status_code == 200, f"Cam 1 upload failed: {r.text}"
    print(f"[PASS] 2. Cam 1 (12MP) multipart in-memory upload succeeded ({len(cam1_bytes)} bytes).")

    # 3. Upload Cam 2 Frame
    cam2_bytes = generate_mock_camera_image("UC-726 16MP Toolhead View", is_cam1=False)
    r = requests.post(
        f"{SERVER_URL}/api/upload/camera/cam2",
        files={"file": ("test_cam2.jpg", cam2_bytes, "image/jpeg")},
        data={"resolution": "1920x1080"},
    )
    assert r.status_code == 200, f"Cam 2 upload failed: {r.text}"
    print(f"[PASS] 3. Cam 2 (16MP) multipart in-memory upload succeeded ({len(cam2_bytes)} bytes).")

    # 4. Upload Thermal JSON Payload
    data_768, min_t, max_t, center_t = generate_mock_thermal_array(hotend_temp=215.4, bed_temp=62.0)
    thermal_payload = {
        "device_id": "esp32_s3_mlx90640",
        "timestamp": datetime.now().isoformat(),
        "min_temp": min_t,
        "max_temp": max_t,
        "center_temp": center_t,
        "ambient_temp": 24.5,
        "thermal_data": data_768,
    }
    r = requests.post(f"{SERVER_URL}/api/upload/thermal", json=thermal_payload)
    assert r.status_code == 200, f"Thermal upload failed: {r.text}"
    print(f"[PASS] 4. ESP32-S3 MLX90640 768-pixel JSON upload succeeded (Max: {max_t}°C, Min: {min_t}°C).")

    # 5. Verify Latest Frame retrieval
    r = requests.get(f"{SERVER_URL}/api/latest/cam1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    print("[PASS] 5. Latest Cam 1 image retrieval validated.")

    r = requests.get(f"{SERVER_URL}/api/latest/cam2")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    print("[PASS] 6. Latest Cam 2 image retrieval validated.")

    # 6. Verify Latest Thermal Rendering
    r = requests.get(f"{SERVER_URL}/api/latest/thermal/image")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    print(f"[PASS] 7. Thermal heatmap PNG rendering validated ({len(r.content)} bytes).")

    # 7. Verify Control Endpoints
    r = requests.post(
        f"{SERVER_URL}/api/control",
        json={"interval_seconds": 3.5, "alert_threshold_c": 260.0},
    )
    assert r.status_code == 200
    ctrl_data = r.json()["control"]
    assert ctrl_data["interval_seconds"] == 3.5
    assert ctrl_data["alert_threshold_c"] == 260.0
    print("[PASS] 8. Remote control bidirectional synchronization verified.")

    # 8. Check Disk Captures
    date_str = datetime.now().strftime("%Y-%m-%d")
    captures_dir = Path(__file__).resolve().parent.parent / "captures" / date_str
    assert (captures_dir / "cam1").exists()
    assert (captures_dir / "cam2").exists()
    assert (captures_dir / "thermal").exists()
    print(f"[PASS] 9. Zero-wear disk archiving verified at: {captures_dir}")

    print("\n>>> ALL TESTS PASSED SUCCESSFULLY! <<<")


def run_live_simulation(interval: float = 3.0):
    print("=" * 60)
    print(f"  STARTING LIVE TELEMETRY SIMULATOR (Interval: {interval}s)")
    print("  Press Ctrl+C to stop.")
    print("  Open browser at: http://127.0.0.1:8000")
    print("=" * 60)

    step = 0
    while True:
        try:
            step += 1
            # Simulate hotend temperature fluctuating slightly around 215°C
            hotend_t = 215.0 + 3.0 * math.sin(step * 0.3)
            bed_t = 60.0 + 0.5 * math.cos(step * 0.2)

            # Cam 1 (t = 0.0s)
            cam1_bytes = generate_mock_camera_image("UC-726 12MP Bed View", is_cam1=True)
            requests.post(
                f"{SERVER_URL}/api/upload/camera/cam1",
                files={"file": ("sim_cam1.jpg", cam1_bytes, "image/jpeg")},
                data={"resolution": "1920x1080"},
                timeout=2.0,
            )

            time.sleep(1.0)  # 1.0s stagger

            # Cam 2 (t = 1.0s)
            cam2_bytes = generate_mock_camera_image("UC-726 16MP Toolhead View", is_cam1=False)
            requests.post(
                f"{SERVER_URL}/api/upload/camera/cam2",
                files={"file": ("sim_cam2.jpg", cam2_bytes, "image/jpeg")},
                data={"resolution": "1920x1080"},
                timeout=2.0,
            )

            # Thermal Telemetry (t = 1.5s)
            data_768, min_t, max_t, center_t = generate_mock_thermal_array(hotend_temp=hotend_t, bed_temp=bed_t)
            thermal_payload = {
                "device_id": "esp32_s3_mlx90640",
                "timestamp": datetime.now().isoformat(),
                "min_temp": min_t,
                "max_temp": max_t,
                "center_temp": center_t,
                "ambient_temp": 24.5,
                "thermal_data": data_768,
            }
            requests.post(f"{SERVER_URL}/api/upload/thermal", json=thermal_payload, timeout=2.0)

            print(f"[Sim Cycle #{step}] Sent Cam1 + Cam2 + Thermal (Max: {max_t:.1f}°C, Center: {center_t:.1f}°C)")

            # Rest of interval
            time.sleep(max(0.5, interval - 1.0))
        except KeyboardInterrupt:
            print("\nSimulation stopped.")
            break
        except Exception as e:
            print(f"[Sim Error] {e}")
            time.sleep(2.0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test and simulation runner for 3D printer monitor")
    parser.add_argument("--simulate-live", action="store_true", help="Run continuous mock data feed for live UI testing")
    parser.add_argument("--interval", type=float, default=3.0, help="Cycle interval in seconds for live simulation")
    args = parser.parse_args()

    if args.simulate_live:
        run_live_simulation(interval=args.interval)
    else:
        run_unit_tests()
