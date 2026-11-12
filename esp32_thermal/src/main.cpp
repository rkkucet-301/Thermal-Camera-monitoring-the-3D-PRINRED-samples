/**
 * ESP32-S3 + MLX90640 (32x24 IR Array) Thermal Telemetry Node
 * 3D Printer Remote Monitoring System - Edge Node 2
 *
 * Transmits 768-pixel thermal array and min/max/center metrics to PC Server.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_MLX90640.h>
#include <ArduinoJson.h>

// =============================================================================
// USER CONFIGURATION (Set Wi-Fi & PC Host IP)
// =============================================================================
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// PC Server Endpoint (Port 8000 default)
const char* SERVER_URL    = "http://192.168.1.100:8000/api/upload/thermal";

// I2C Pin Assignment for ESP32-S3
#define I2C_SDA_PIN 8
#define I2C_SCL_PIN 9
#define I2C_CLOCK_FREQ 400000 // 400 kHz Fast Mode (or 800000)

// Loop timing
const unsigned long CAPTURE_INTERVAL_MS = 3000;
unsigned long lastCaptureTime = 0;

// Hardware Objects
Adafruit_MLX90640 mlx;
float frameBuffer[768]; // 32 * 24 pixels

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

void connectToWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.print("[WiFi] Connecting to: ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected! IP Address: " + WiFi.localIP().toString());
  } else {
    Serial.println("\n[WiFi] Connection timeout. Retrying in background...");
  }
}

bool initializeMLX90640() {
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, I2C_CLOCK_FREQ);

  Serial.println("[MLX90640] Initializing I2C bus...");
  if (!mlx.begin(MLX90640_I2CADDR_DEFAULT, &Wire)) {
    Serial.println("[MLX90640] ERROR: Sensor not found! Check 3.3V/GND/SDA/SCL wiring.");
    return false;
  }

  Serial.println("[MLX90640] Sensor detected successfully!");
  mlx.setMode(MLX90640_CHESS);
  mlx.setResolution(MLX90640_ADC_18BIT);
  mlx.setRefreshRate(MLX90640_2_HZ); // 2 frames per second
  return true;
}

void postThermalTelemetry(float minT, float maxT, float centerT) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] Wi-Fi not connected. Skipping upload.");
    return;
  }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(4000);

  // Allocate JSON document
  // 768 floats + metadata requires ~12 KB JSON buffer
  JsonDocument doc;
  doc["device_id"] = "esp32_s3_mlx90640";
  doc["min_temp"] = serialized(String(minT, 2));
  doc["max_temp"] = serialized(String(maxT, 2));
  doc["center_temp"] = serialized(String(centerT, 2));
  doc["ambient_temp"] = 25.0; // Standard nominal ambient

  JsonArray array = doc["thermal_data"].to<JsonArray>();
  for (int i = 0; i < 768; i++) {
    // Round to 1 decimal place to optimize JSON payload size over Wi-Fi
    array.add(serialized(String(frameBuffer[i], 1)));
  }

  String requestBody;
  serializeJson(doc, requestBody);

  int httpCode = http.POST(requestBody);
  if (httpCode > 0) {
    Serial.printf("[HTTP] POST Result: %d | Size: %d bytes\n", httpCode, requestBody.length());
  } else {
    Serial.printf("[HTTP] POST failed, error: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end();
}

// =============================================================================
// ARDUINO SETUP & LOOP
// =============================================================================

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- ESP32-S3 MLX90640 Thermal Sensor Node Starting ---");

  connectToWiFi();

  while (!initializeMLX90640()) {
    Serial.println("[MLX90640] Retrying sensor initialization in 3 seconds...");
    delay(3000);
  }

  Serial.println("[System] Ready. Commencing 3-second thermal telemetry loop.");
}

void loop() {
  // Maintain Wi-Fi
  if (WiFi.status() != WL_CONNECTED) {
    connectToWiFi();
  }

  unsigned long currentMillis = millis();
  if (currentMillis - lastCaptureTime >= CAPTURE_INTERVAL_MS) {
    lastCaptureTime = currentMillis;

    // Capture thermal frame
    if (mlx.getFrame(frameBuffer) != 0) {
      Serial.println("[MLX90640] Frame capture error!");
      return;
    }

    // Calculate Min, Max, and Center Temperatures
    float minTemp = 1000.0;
    float maxTemp = -100.0;

    for (int i = 0; i < 768; i++) {
      float t = frameBuffer[i];
      if (t < minTemp) minTemp = t;
      if (t > maxTemp) maxTemp = t;
    }

    // Center pixel: Row 12, Column 16 -> index = 12 * 32 + 16 = 400
    float centerTemp = frameBuffer[400];

    Serial.printf("[Telemetry] Min: %.1f °C | Max: %.1f °C | Center: %.1f °C\n", minTemp, maxTemp, centerTemp);

    // POST telemetry to PC server
    postThermalTelemetry(minTemp, maxTemp, centerTemp);
  }

  delay(20); // Small task yield
}
