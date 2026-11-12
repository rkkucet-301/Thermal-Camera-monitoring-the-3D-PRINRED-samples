# Comprehensive Thermal Camera Setup & Engineering Guide
### ESP32-S3 + MLX90640 32×24 Far-Infrared (FIR) Array

This guide details the complete hardware integration, electrical wiring, optical considerations, firmware configuration, and thermal safety monitoring for Edge Node 2 in the 3D printer remote monitoring system.

---

## 1. Sensor Overview: Melexis MLX90640

The MLX90640 is a fully calibrated 768-pixel ($32 \times 24$) thermal infrared array housed in an industry-standard 4-lead TO-39 package with an integrated digital interface.

```
MLX90640 Sensor View (Bottom Pinout):
       +-------+
      /  (Tab)  \      Tab indicates Pin 1 (VDD)
     |  1     2  |     1: VDD (3.0V - 3.6V strictly)
     |           |     2: GND
     |  4     3  |     3: SCL (I2C Clock)
      \         /      4: SDA (I2C Data)
       +-------+
```

### 1.1 Field of View (FOV) Selection for 3D Printers
Melexis manufactures two optical package variants:

| Sensor Variant | Field of View (FOV) | Best Mounting Position | Coverage at 300 mm Distance |
| :--- | :--- | :--- | :--- |
| **MLX90640-BAA** | **$55^\circ \times 35^\circ$** (Standard) | Frame rail pointing at Hotend + Bed at 30°–45° | $\sim 310 \text{ mm} \times 190 \text{ mm}$ (**Recommended**) |
| **MLX90640-BAB** | **$110^\circ \times 75^\circ$** (Wide Angle) | Enclosure roof directly top-down ($Z \ge 250\text{ mm}$) | $\sim 850 \text{ mm} \times 460 \text{ mm}$ (covers entire bed + motors) |

> **Recommendation for 3D Printers:** The **$55^\circ$ (BAA)** version offers significantly higher angular resolution ($\approx 1.7^\circ$ per pixel vs $3.4^\circ$ per pixel). This allows individual pixels to resolve small targets such as the heater block and nozzle tip rather than averaging them across ambient chamber air.

---

## 2. Electrical Wiring & Circuit Requirements

```
       ESP32-S3 Development Board                   MLX90640 Breakout Board
     +---------------------------+                 +-----------------------+
     |                      3.3V |---------------->| VIN / VDD (3.3V ONLY) |
     |                       GND |---------------->| GND                   |
     |        GPIO 8 (I2C SDA)   |---------------->| SDA                   |
     |        GPIO 9 (I2C SCL)   |---------------->| SCL                   |
     +---------------------------+                 +-----------------------+
                |           |
             [4.7kΩ]     [4.7kΩ]  <-- Pull-up resistors to 3.3V
                |           |         (Pre-installed on Adafruit / Waveshare
              (3.3V)      (3.3V)       breakout boards)
```

### 2.1 Critical Voltage Warning: 3.3V Strict!
- **Absolute Maximum Operating Voltage:** $3.6\text{ V}$.
- **Do NOT connect the MLX90640 to 5V.** Connecting to the 5V rail will permanently damage the internal analog multiplexers and EEPROM calibration registers.
- If using an ESP32-S3 dev board powered from 5V USB, connect the MLX90640 VDD pin to the board's onboard **3.3V regulated output pin**.

### 2.2 I2C Bus Frequency & Wire Length
- The MLX90640 transfers $768 \times 2 = 1536\text{ bytes}$ of raw ADC data per sub-page over I2C.
- Configure I2C speed to **$400\text{ kHz}$** (Fast Mode) or **$800\text{ kHz}$** (Fast Mode Plus). At $100\text{ kHz}$, the bus cannot sustain 2 Hz – 4 Hz frame rates without timing dropouts.
- **Cable Length:** Keep I2C hookup wires $\le 25\text{ cm}$ ($\le 10\text{ inches}$). If longer runs are required through printer cable chains, use shielded twisted pair (SDA with GND, SCL with 3.3V) or an active I2C bus extender (e.g., PCA9615).

---

## 3. Optical & Thermal Physics in a 3D Printer

### 3.1 Surface Emissivity Considerations
Thermal cameras measure infrared radiation emitted from surfaces, which depends on surface emissivity ($\epsilon$):

| 3D Printer Component | Surface Type | Typical Emissivity ($\epsilon$) | Thermal Camera Reading Note |
| :--- | :--- | :--- | :--- |
| **Heated Bed (Textured PEI)** | Black / Gold Powder Coat | $\approx 0.92 - 0.95$ | **Extremely accurate** ($\pm 1.5^\circ\text{C}$) |
| **Heated Bed (Bare Glass / Mirror)** | Clean Glass | $\approx 0.85 - 0.90$ | Accurate, but reflections of hotend can appear |
| **Hotend Heater Block** | Anodized Black / Silicone Sock | $\approx 0.90 - 0.95$ | **Accurate** when silicone sock is installed |
| **Bare Aluminum / Polished Brass Nozzle**| Shiny Metal | $\approx 0.05 - 0.15$ | Under-reports real temp unless silicone sock installed |

> **Pro Tip:** Always keep the **silicone sock** installed on your hotend heater block. Silicone has an emissivity of $\approx 0.94$, giving the MLX90640 an accurate temperature reading while shielding the thermopile from cooling fan turbulence.

---

## 4. Flashing Firmware to the ESP32-S3

The firmware project is located in `esp32_thermal/`.

### Method A: Flashing via PlatformIO (Recommended)
1. Install [VS Code](https://code.visualstudio.com/) and add the **PlatformIO IDE** extension.
2. In VS Code, choose **File $\to$ Open Folder** and select `esp32_thermal`.
3. Open `esp32_thermal/src/main.cpp` and edit lines 20–24:
   ```cpp
   const char* WIFI_SSID     = "YOUR_WIFI_SSID";
   const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
   const char* SERVER_URL    = "http://192.168.1.107:8000/api/upload/thermal";
   ```
4. Connect the ESP32-S3 to your PC with a USB-C data cable.
5. Click the **PlatformIO: Upload** arrow (bottom toolbar) or run in terminal:
   ```bash
   cd esp32_thermal
   pio run --target upload
   pio device monitor
   ```

### Method B: Flashing via Arduino IDE 2.x
1. Open Arduino IDE $\to$ **Tools $\to$ Board $\to$ Boards Manager** $\to$ install `esp32` by Espressif.
2. Select Board: **ESP32S3 Dev Module**.
3. Install required libraries via **Sketch $\to$ Include Library $\to$ Manage Libraries**:
   - `Adafruit MLX90640`
   - `Adafruit BusIO`
   - `ArduinoJson` (v7.x)
4. Open `esp32_thermal/src/main.cpp`, update your Wi-Fi credentials and PC Server URL, and click **Upload**.

---

## 5. Thermal Runaway & 3D Printer Alarm Thresholds

The PC server dashboard includes automated thermal threshold evaluation. Configure these limits in `pc_server/config.py` or directly from the live dashboard control slider:

```
+-------------------------------------------------------------------------+
|                  TYPICAL 3D PRINTER TEMPERATURE PROFILES                |
+-------------------------------------------------------------------------+
 Ambient Chamber:   22°C - 35°C (PLA) / 40°C - 60°C (ABS/ASA enclosed)
 Heated Bed:        55°C - 65°C (PLA) / 75°C - 85°C (PETG) / 100°C - 110°C (ABS)
 Extruder Nozzle:   190°C - 215°C (PLA) / 230°C - 250°C (PETG) / 255°C - 275°C (ABS)
 Thermal Runaway:   > 280°C on hotend, or heater on while temp drops (Decoupled)
+-------------------------------------------------------------------------+
```

### Safety Alert Rules Configured in Hub:
1. **Extruder Maximum Limit Alarm:** If `max_temp` $\ge 275.0^\circ\text{C}$ (customizable), the dashboard flashes a bold red alarm and triggers visual warnings.
2. **Heated Bed Maximum Limit Alarm:** If bed center $\ge 115.0^\circ\text{C}$, alerts against bed heater MOSFET failure (stuck ON).
3. **Heat Creep Detection:** If the cold-end heatsink (top 4 rows of the thermal matrix above the nozzle) exceeds $50^\circ\text{C}$, alerts to hotend fan failure before filament jams occur.

---

## 6. Testing Without Physical ESP32 Hardware (Simulator Mode)

You can run the built-in realistic telemetry simulator on your PC anytime:

```powershell
# In your project folder
& "C:\Users\RANJITH\AppData\Local\Programs\Python\Python312\python.exe" scripts\test_local.py --simulate-live
```

This generates synthetic 768-float matrices matching real 3D printer thermal physics (60°C bed + 215°C nozzle hot spot + Gaussian thermal dissipation), rendering the live Ironbow canvas on the dashboard for testing.
