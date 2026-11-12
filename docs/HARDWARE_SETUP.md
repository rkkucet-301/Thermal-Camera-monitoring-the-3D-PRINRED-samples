# Hardware Setup & Electrical Wiring Guide: 3D Printer Monitoring System

## 1. System Architecture Overview

```
 +-------------------------------------------------------------------------------+
 |                            POWER DISTRIBUTION (5V)                            |
 |                     10,000 mAh Li-ion Power Bank (5V / 2.4A - 3.0A)           |
 +-----------------------------------+-------------------------------------------+
                                     |
           +-------------------------+-------------------------+
           | (Micro-USB 5V / 2.5A)                             | (USB-C 5V / 1.0A)
           v                                                   v
+--------------------------+                         +--------------------------+
|  EDGE NODE 1: RASPBERRY  |                         |  EDGE NODE 2: ESP32-S3   |
|  PI 3 MODEL B v1.2       |                         |  (Thermal Sensor Node)   |
|  - 1 GB LPDDR2 RAM       |                         |  - Tensilica Xtensa Dual |
|  - Shared USB 2.0 Bus    |                         |  - 2.4 GHz 802.11 b/g/n  |
|  - 2.4 GHz Wi-Fi         |                         +------------+-------------+
+------------+-------------+                                      |
             |                                                    | I2C (3.3V)
    +--------+--------+                                           v
    |                 |                               +--------------------------+
    v (USB 2.0)       v (USB 2.0)                     | MLX90640 Thermal Array   |
+-----------+   +-----------+                         | 32 x 24 IR Pixels (55°)  |
| UC-726    |   | UC-726    |                         +--------------------------+
| rev.c     |   | rev.c     |
| 12 MP     |   | 16 MP     |
| (Bed Cam) |   | (Nozzle)  |
+-----------+   +-----------+
    |                 |                                           |
    | (HTTP POSTs)    | (HTTP POSTs)                              | (HTTP POSTs)
    +-----------------+---------------------+---------------------+
                                            |
                                            v (Wi-Fi 802.11 b/g/n)
                            +-------------------------------+
                            | REMOTE HOST (PC / LAPTOP)     |
                            | - FastAPI Receiver (Port 8000)|
                            | - Web Dashboard               |
                            | - Zero Wear Disk Archive      |
                            +-------------------------------+
```

---

## 2. Edge Node 1: Raspberry Pi 3 Model B + Dual UC-726 Cameras

### 2.1 Physical Interconnect & Port Assignment

The Raspberry Pi 3 Model B v1.2 uses a LAN9514/SMSC9514 controller which connects the 10/100 Ethernet port and all 4 USB ports to the BCM2837 SoC through a single high-speed USB 2.0 upstream channel (**480 Mbps total shared bandwidth**).

```
Raspberry Pi 3B Rear / Side View:
+-------------------------------------------------------+
|  [GPIO Header - 40 Pins]                              |
|                                                       |
|                     +-------+ [USB Top Left: 12 MP]   |
|                     | USB 0 | <--- UC-726 12 MP       |
|                     +-------+                         |
|                     | USB 1 | <--- Leave Empty        |
|                     +-------+ [USB Bottom Left]       |
|  [Micro-USB 5V IN]  +-------+                         |
|   <--- Power Bank   | USB 2 | <--- UC-726 16 MP       |
|                     +-------+ [USB Top Right: 16 MP]  |
|                     | USB 3 | <--- Leave Empty        |
|                     +-------+ [USB Bottom Right]      |
|  [HDMI]  [AUDIO]    |  ETH  | [Ethernet Jack]         |
+-------------------------------------------------------+
```

> **USB Current Limit Note:** The Raspberry Pi 3 Model B implements an onboard power switch (AP2553 / RT9742) configured to cap total USB bus draw at **1.2 A**.

---

## 3. Edge Node 2: ESP32-S3 to MLX90640 I2C Wiring

### 3.1 Pinout Mapping

| MLX90640 Sensor Pin | ESP32-S3 Development Board | Description / Electrical Requirement |
| :--- | :--- | :--- |
| **VIN / VDD** | **3.3V** | Operating range: 3.0V – 3.6V (**Never 5V!**) |
| **GND** | **GND** | Common ground reference |
| **SDA** | **GPIO 8** (or GPIO 4) | I2C Data line with 4.7 kΩ pull-up to 3.3V |
| **SCL** | **GPIO 9** (or GPIO 5) | I2C Clock line with 4.7 kΩ pull-up to 3.3V |

```
    ESP32-S3 Node Pinout             MLX90640 Thermal Sensor
  +-----------------------+           +--------------------+
  |                  3.3V |---------->| VDD (3.0V - 3.6V)  |
  |                   GND |---------->| GND                |
  | GPIO 8 (I2C SDA)      |---------->| SDA                |
  | GPIO 9 (I2C SCL)      |---------->| SCL                |
  |                       |           +--------------------+
  |      [3.3V]  [3.3V]   |
  |        |       |      |
  |       [4.7k]  [4.7k]  |
  |        |       |      |
  | SDA ---+       |      | (Pull-ups usually integrated on
  | SCL -----------+      |  standard Adafruit/Waveshare boards)
  +-----------------------+
```

### 3.2 I2C Bus Frequency Configuration
The MLX90640 generates a 768-pixel frame (32 × 24 pixels) across two sub-pages (RAM addresses `0x0400` to `0x06FF`). To achieve a consistent 2 Hz – 4 Hz refresh rate without buffer overrun, set the I2C bus speed in firmware to **400 kHz** (Fast Mode) or **800 kHz** (Fast Mode Plus).

---

## 4. Power Budget Analysis & Battery Runtime

### 4.1 System Power Consumption Breakdown

| Subsystem / Component | Operating State | Voltage | Current (Typ) | Power (Typ) |
| :--- | :--- | :--- | :--- | :--- |
| **Raspberry Pi 3B** | Idle (OS Lite, Wi-Fi connected) | 5.0 V | 420 mA | 2.10 W |
| **Raspberry Pi 3B** | Active MJPEG encoding & TLS | 5.0 V | 650 mA | 3.25 W |
| **UC-726 12 MP Camera**| Standby / Sensor Readout | 5.0 V | 180 mA – 240 mA| 1.10 W |
| **UC-726 16 MP Camera**| Standby / Sensor Readout | 5.0 V | 200 mA – 260 mA| 1.20 W |
| **ESP32-S3 + MLX90640**| Active Wi-Fi TX + 400kHz I2C | 5.0 V | 140 mA – 220 mA| 0.90 W |
| **Staggered Peak Draw**| Pi 3B + Single Active Sensor| 5.0 V | **~1.10 A** | **~5.50 W** |
| **Simultaneous Firing**| (Avoided by design) | 5.0 V | ~1.65 A *(exceeds 1.2A USB limit)* | ~8.25 W |

### 4.2 Battery Life Calculation (10,000 mAh Li-ion Bank)
- Nominal Cell Energy: $10,000\text{ mAh} \times 3.7\text{ V} = 37.0\text{ Wh}$
- Boost Converter Efficiency (3.7 V $\to$ 5.1 V): $\sim 85\%$
- Usable Output Energy: $37.0\text{ Wh} \times 0.85 \approx 31.45\text{ Wh}$
- Average System Power (with staggered 3-second duty cycle): $\sim 5.2\text{ W}$
- **Estimated Continuous Runtime:**
  $$\text{Runtime} = \frac{31.45\text{ Wh}}{5.2\text{ W}} \approx \mathbf{6.0\text{ hours}}$$

---

## 5. 3D Printer Enclosure Placement & Thermal Safety

1. **Raspberry Pi 3B Placement:**
   - **Enclosure Exterior Mounting:** Never place the Raspberry Pi inside an active heated enclosure (enclosures frequently reach 40°C – 65°C for ABS/ASA/Nylon).
   - The BCM2837 SoC begins thermal throttling at **80°C** and halts at **85°C**. Inside a 55°C enclosure, SoC junction temperature under Wi-Fi and USB load will rapidly exceed thermal limits.
   - Mount the Pi on the outside of the printer frame using a 3D-printed bracket or DIN rail clip. Route USB cables through sealed silicone grommets into the chamber.

2. **UC-726 Camera Mounts:**
   - **Camera 1 (12 MP - Wide Angle Bed View):** Mount to the front corner extrusion of the printer frame at a 30° downward tilt. Distance to build plate: $\ge 250\text{ mm}$.
   - **Camera 2 (16 MP - Close-up Toolhead View):** Mount either to the X-gantry or top frame rail pointing toward the hotend nozzle. Keep at least $80\text{ mm}$ clear of the hotend heater block to prevent lens deformation.
   - **Material Recommendation:** Print camera mounts in **PETG, ABS, or ASA** (do not use PLA near heated beds or hotends).

3. **ESP32-S3 + MLX90640 Thermal Sensor:**
   - Mount above the build plate with a direct line-of-sight to both the hotend block and the heated bed.
   - Operating temperature limit for MLX90640: $-40^\circ\text{C}$ to $+85^\circ\text{C}$.
   - Lens Field of View (FOV): 55° horizontal $\times$ 35° vertical (or 110° $\times$ 75° depending on MLX90640 model suffix). At 300 mm distance, a 55° lens covers a footprint of $\approx 310\text{ mm} \times 190\text{ mm}$, ideally encompassing standard $220 \times 220\text{ mm}$ to $300 \times 300\text{ mm}$ build plates.

---

## 6. Raspberry Pi OS Wi-Fi Unblocking & First-Time Setup

As observed during installation (`Debian GNU/Linux 13 raspberrypi tty1`):
```bash
# 1. Unblock Wi-Fi blocked by rfkill
sudo rfkill unblock wifi

# 2. Set WLAN regulatory country (mandatory for 2.4 GHz channels 1-11/13)
sudo raspi-config
# Navigate to: Localisation Options -> WLAN Country -> Select your country code (e.g., US, IN, GB)

# 3. Connect to your local 2.4 GHz Wi-Fi SSID
sudo nmcli dev wifi connect "YOUR_WIFI_SSID" password "YOUR_WIFI_PASSWORD"
# Or edit /etc/wpa_supplicant/wpa_supplicant.conf
```


---

## 7. Dual Camera USB Bandwidth Architecture (Sequential Capture)

The Raspberry Pi 3 Model B routes all 4 USB ports and the 10/100 Ethernet interface through a single internal SMSC LAN9514 USB 2.0 controller with a shared **480 Mbps total physical bandwidth** and a strict **1.2 A aggregate current limit**.

### The Isochronous Bandwidth Problem:
- UVC cameras negotiate USB isochronous bandwidth endpoints with the kernel driver upon opening.
- When two high-resolution cameras (such as the UC-726 12 MP and 16 MP) are held open simultaneously, the Linux kernel exhausts its periodic bandwidth allocation table, causing `select timeout` or starvation of the second camera.

### The Isolated Sequential Capture Solution:
To ensure 100% reliable continuous streaming from both cameras:
1. **Cam 1 (Bed):** Device opened $\to$ single MJPEG frame grabbed $\to$ **`cap.release()` invoked immediately**.
2. **Stagger Delay (1.0s):** Kernel completely closes the USB isochronous endpoints and reclaims all bus bandwidth.
3. **Cam 2 (Toolhead):** Device opened $\to$ single MJPEG frame grabbed $\to$ **`cap.release()` invoked immediately**.
4. **Result:** Only one CMOS sensor streams data across the USB 2.0 PHY at any given millisecond. Zero bus contention, zero current spikes, and zero local SD card wear.

---

## 8. Related Documentation
- [docs/THERMAL_CAMERA_SETUP.md](file:///C:/Users/RANJITH/OneDrive/Desktop/Sannith%203d%20printer%20monitor/docs/THERMAL_CAMERA_SETUP.md): Deep-dive guide for ESP32-S3 + MLX90640 wiring, FOV selection, firmware flashing, and 3D printing thermal runaway thresholds.
- [docs/DEPLOYMENT_AND_OPERATIONS.md](file:///C:/Users/RANJITH/OneDrive/Desktop/Sannith%203d%20printer%20monitor/docs/DEPLOYMENT_AND_OPERATIONS.md): SSH reboot persistence, static IP MAC reservation, Windows firewall rule, and systemd service troubleshooting.
