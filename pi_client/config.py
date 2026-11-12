import os

# --- Raspberry Pi Edge Node Configuration ---

# IP address or hostname of the remote PC/Server hosting the dashboard
# Replace with your PC's local IP address (e.g., "192.168.1.100")
PC_SERVER_URL = os.getenv("PC_SERVER_URL", "http://192.168.1.107:8000")

# Capture Settings
DEFAULT_INTERVAL_SECONDS = 3.0
STAGGER_DELAY_SECONDS = 1.0  # Delay between Cam 1 and Cam 2 triggers

# Resolution (1080p MJPEG is optimal for Pi 3B USB 2.0 bus & dual sensors)
CAPTURE_WIDTH = int(os.getenv("CAPTURE_WIDTH", "1920"))
CAPTURE_HEIGHT = int(os.getenv("CAPTURE_HEIGHT", "1080"))

# MJPEG compression quality (1-100, 80-85 provides excellent detail with low memory)
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "85"))

# Network retry / timeout settings (in seconds)
HTTP_TIMEOUT = 4.0
MAX_CONSECUTIVE_DROPS = 5

# Optional local control listening port on Pi
CONTROL_LISTEN_PORT = 5001
