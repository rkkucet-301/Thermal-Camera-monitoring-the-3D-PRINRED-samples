#!/usr/bin/env python3
"""
Main Entry Point for Raspberry Pi 3B 3D Printer Client Node.
Runs camera auto-detection, initializes in-memory staggered capture loop,
and coordinates with PC server.
"""

import argparse
import sys
from camera_detector import detect_dual_cameras
from capture_service import StaggeredCaptureService
from config import PC_SERVER_URL


def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi 3D Printer Remote Monitor Client")
    parser.add_argument(
        "--server",
        type=str,
        default=PC_SERVER_URL,
        help=f"PC Server URL endpoint (default: {PC_SERVER_URL})",
    )
    parser.add_argument(
        "--detect-only",
        action="store_true",
        help="Run camera auto-detection and display detected 12 MP & 16 MP ports without streaming",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  3D PRINTER REMOTE MONITORING - PI 3B EDGE CLIENT")
    print(f"  Target PC Server: {args.server}")
    print("  Strategy: Zero SD Card Wear (100% In-Memory MJPEG Stream)")
    print("=" * 60)

    if args.detect_only:
        cams = detect_dual_cameras()
        print("\nAuto-detection complete.")
        print(f"Cam 1 (12 MP Bed):      {cams['cam1']}")
        print(f"Cam 2 (16 MP Toolhead): {cams['cam2']}")
        sys.exit(0)

    service = StaggeredCaptureService(pc_url=args.server)
    service.run_loop()


if __name__ == "__main__":
    main()
