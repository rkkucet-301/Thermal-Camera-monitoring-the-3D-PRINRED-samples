from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CAPTURES_DIR = BASE_DIR / "captures"

# Server configuration
HOST = "0.0.0.0"
PORT = 8000

# Capture & Alert Settings
DEFAULT_INTERVAL_SECONDS = 3.0
HOTEND_MAX_ALERT_TEMP = 275.0   # °C (triggers audible/visual warning)
BED_MAX_ALERT_TEMP = 110.0      # °C
ENCLOSURE_MAX_ALERT_TEMP = 65.0 # °C

# Create default storage directories
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
