# 3D Printer Remote Monitoring System
### Dual UVC Vision (Raspberry Pi 3B) + Thermal Telemetry (ESP32-S3 MLX90640)

A production-ready, low-power remote monitoring and telemetry architecture designed for 3D printer enclosures.

---

## Architecture Highlights
- **Edge Node 1 (Raspberry Pi 3 Model B v1.2, 1GB RAM, Debian 13 aarch64):**
  - **Zero SD Card Wear:** 100% in-memory frame encoding and streaming over HTTP. No image writes to the Pi's flash card.
  - **USB 2.0 & Power Bus Guard:** Dual UC-726 rev.c cameras (12 MP & 16 MP) share a single 480 Mbps bus. Captures in hardware MJPEG mode and staggers triggers by 1.0s within the 3.0s interval loop, staying under the 1.2A USB current threshold.
  - **Auto-Detection:** Discovers and distinguishes the 12 MP (Bed Wide View) and 16 MP (Toolhead/Nozzle) sensors automatically via V4L2 capability querying.
- **Edge Node 2 (Modular ESP32-S3 + MLX90640):**
  - Captures 768-point (32x24) infrared thermal array over 400 kHz I2C.
  - Transmits Min, Max, and Center target temperatures to the PC Server every 3 seconds over Wi-Fi.
- **Remote Host (PC / Laptop):**
  - Lightweight FastAPI server with real-time dashboard UI.
  - Smooth Ironbow thermal heatmap interpolation with interactive temperature hover probe.
  - Overheat alarm thresholding, interval adjustment, and on-demand snapshot triggers.
  - Organized date-stamped image and telemetry archiving (`captures/YYYY-MM-DD/`).

---

## Project Structure
```
├── docs/
│   ├── HARDWARE_SETUP.md        # ASCII schematics, pinout, power budget, enclosure safety
│   ├── THERMAL_CAMERA_SETUP.md  # ESP32-S3 + MLX90640 wiring, FOV, flashing, thermal safety
│   └── DEPLOYMENT_AND_OPERATIONS.md # SSH reboot persistence, static IP, systemd, firewall
├── pc_server/                   # FastAPI Server & Live Web Dashboard
│   ├── app.py                   # REST API receiver & thermal heatmap renderer
│   ├── config.py                # Host port, capture paths, default alarm limits
│   ├── requirements.txt         # PC server dependencies
│   ├── templates/index.html     # Real-time telemetry dashboard
│   └── static/                  # CSS styles, SVGs, and dashboard client script
├── pi_client/                   # Raspberry Pi 3B Capture Service
│   ├── camera_detector.py       # V4L2 12 MP vs 16 MP auto-detection
│   ├── capture_service.py       # Zero-wear in-memory staggered capture loop
│   ├── printer_monitor_client.py# Client main entry point
│   ├── printer_monitor.service  # Systemd daemon configuration
│   ├── setup_pi.sh              # 1-click deployment script for Debian 13 Pi OS
│   └── requirements.txt
├── esp32_thermal/               # ESP32-S3 + MLX90640 Firmware
│   ├── platformio.ini           # PlatformIO project config
│   └── src/main.cpp             # Arduino C++ telemetry transmitter
├── scripts/
│   └── test_local.py            # Local endpoint verification & live telemetry simulator
└── README.md
```

---

## 1. Quick Start: Testing Locally on PC

You can test the entire pipeline on your PC right now with simulated cameras and thermal data:

```bash
# 1. Install PC Server dependencies
cd pc_server
pip install -r requirements.txt

# 2. Start the PC Telemetry Server
python app.py
# Server will listen on http://0.0.0.0:8000
```

Open a second terminal window to run the verification and mock simulation:

```bash
# Run automated verification tests
python scripts/test_local.py

# Or start continuous live mock telemetry stream
python scripts/test_local.py --simulate-live
```

Now open your browser to **`http://localhost:8000`** to view the live dashboard!

---

## 2. Raspberry Pi 3B Client Setup

Based on your terminal display (`kucet@raspberrypi` on Debian 13 aarch64):

### Step 1: Unblock Wi-Fi on the Pi
```bash
sudo rfkill unblock wifi
sudo raspi-config
# Under Localisation Options -> WLAN Country, set your country.
```

### Step 2: Deploy and Start Client
1. Copy the `pi_client/` folder to `/home/kucet/printer_monitor/pi_client` on your Raspberry Pi:
   ```bash
   scp -r pi_client kucet@raspberrypi.local:/home/kucet/printer_monitor/pi_client
   ```
2. SSH into your Raspberry Pi:
   ```bash
   ssh kucet@raspberrypi.local
   cd /home/kucet/printer_monitor/pi_client
   chmod +x setup_pi.sh
   ./setup_pi.sh
   ```
3. Update your PC's IP address in `/etc/systemd/system/printer_monitor.service`:
   ```bash
   sudo nano /etc/systemd/system/printer_monitor.service
   # Change PC_SERVER_URL to: http://<YOUR_PC_IP>:8000
   sudo systemctl daemon-reload
   sudo systemctl restart printer_monitor.service
   ```
4. View real-time Pi capture logs:
   ```bash
   journalctl -u printer_monitor.service -f
   ```

---

## 3. ESP32-S3 Thermal Node Setup (Phase 2 Add-On)

### Hardware Connections
| MLX90640 Pin | ESP32-S3 Pin | Notes |
| :--- | :--- | :--- |
| **VIN / VDD** | **3.3V** | Operating range 3.0V – 3.6V |
| **GND** | **GND** | Common ground |
| **SDA** | **GPIO 8** | I2C Data (4.7kΩ pull-up to 3.3V) |
| **SCL** | **GPIO 9** | I2C Clock (4.7kΩ pull-up to 3.3V) |

### Flash Firmware with PlatformIO
1. Open `esp32_thermal/src/main.cpp` and set your Wi-Fi credentials and PC Server IP:
   ```cpp
   const char* WIFI_SSID     = "YOUR_WIFI_SSID";
   const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
   const char* SERVER_URL    = "http://<YOUR_PC_IP>:8000/api/upload/thermal";
   ```
2. Build and flash to the ESP32-S3:
   ```bash
   cd esp32_thermal
   pio run --target upload
   pio device monitor
   ```

---

## 4. REST API Reference

| Endpoint | Method | Payload / Description |
| :--- | :--- | :--- |
| `/api/upload/camera/{cam_id}` | `POST` | Multipart/form-data (`file`: JPEG bytes, `resolution`, `timestamp`). |
| `/api/upload/thermal` | `POST` | JSON telemetry (`min_temp`, `max_temp`, `center_temp`, `thermal_data` [768 floats]). |
| `/api/latest/{cam_id}` | `GET` | Returns latest raw JPEG frame (`image/jpeg`). |
| `/api/latest/thermal` | `GET` | Returns latest thermal telemetry JSON packet. |
| `/api/latest/thermal/image` | `GET` | Returns server-rendered smooth Ironbow PNG heatmap. |
| `/api/status` | `GET` | Heartbeat & connection metrics for all active edge nodes. |
| `/api/control` | `POST` | Updates `interval_seconds`, `is_paused`, or `alert_threshold_c`. |

---

## 5. Thermal & Enclosure Safety Guidelines
- Mount the **Raspberry Pi 3B on the exterior** of the 3D printer enclosure. Enclosure temperatures for ABS/ASA/Nylon (45°C - 65°C) will cause SoC thermal throttling (>80°C).
- Mount cameras in **PETG or ABS brackets**; maintain $\ge 80\text{ mm}$ clearance from the hotend heater block.
- For detailed electrical diagrams and power budget calculations, see [docs/HARDWARE_SETUP.md](file:///C:/Users/RANJITH/OneDrive/Desktop/Sannith%203d%20printer%20monitor/docs/HARDWARE_SETUP.md).
