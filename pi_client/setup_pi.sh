#!/usr/bin/env bash
# ==============================================================================
# Setup Script for Raspberry Pi 3 Model B (Raspberry Pi OS Lite / Debian 13 aarch64)
# Configures camera tools, Python virtual environment, dependencies, and systemd service.
# ==============================================================================

set -e

echo "=== [1/5] Updating APT Repositories & Installing V4L2 Tools ==="
sudo apt-get update
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    v4l-utils \
    libgl1 \
    libglib2.0-0 \
    rfkill

echo "=== [2/5] Ensuring Wi-Fi is Unblocked ==="
sudo rfkill unblock wifi || true

echo "=== [3/5] Setting up Python Virtual Environment in ~/printer_monitor/venv ==="
TARGET_DIR="$HOME/printer_monitor"
mkdir -p "$TARGET_DIR"

if [ ! -d "$TARGET_DIR/venv" ]; then
    python3 -m venv "$TARGET_DIR/venv"
fi

source "$TARGET_DIR/venv/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [4/5] Testing Camera Auto-Detection ==="
python3 camera_detector.py || true

echo "=== [5/5] Installing and Enabling Systemd Service ==="
sudo cp printer_monitor.service /etc/systemd/system/printer_monitor.service
sudo systemctl daemon-reload
sudo systemctl enable printer_monitor.service

echo "======================================================================"
echo " Setup complete! Update PC_SERVER_URL in:"
echo "   /etc/systemd/system/printer_monitor.service"
echo " Then start the service with:"
echo "   sudo systemctl start printer_monitor.service"
echo " Check service logs with:"
echo "   journalctl -u printer_monitor.service -f"
echo "======================================================================"
