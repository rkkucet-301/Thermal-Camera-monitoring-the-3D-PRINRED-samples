/**
 * 3D Printer Remote Monitor Hub - Dashboard Client Script
 * Handles real-time polling, HTML5 canvas thermal interpolation, hover probe, and controls.
 */

// DOM Elements
const pillPi = document.getElementById('pill-pi');
const pillThermal = document.getElementById('pill-thermal');
const alarmBanner = document.getElementById('alarm-banner');
const alarmText = document.getElementById('alarm-text');

const cam1Img = document.getElementById('cam1-img');
const cam1Meta = document.getElementById('cam1-meta');
const cam1Timestamp = document.getElementById('cam1-timestamp');

const cam2Img = document.getElementById('cam2-img');
const cam2Meta = document.getElementById('cam2-meta');
const cam2Timestamp = document.getElementById('cam2-timestamp');

const thermalCanvas = document.getElementById('thermal-canvas');
const thermalTooltip = document.getElementById('thermal-tooltip');
const tempMaxVal = document.getElementById('temp-max-val');
const tempCenterVal = document.getElementById('temp-center-val');
const tempMinVal = document.getElementById('temp-min-val');
const scaleMin = document.getElementById('scale-min');
const scaleMax = document.getElementById('scale-max');

const intervalSlider = document.getElementById('interval-slider');
const intervalDisplay = document.getElementById('interval-display');
const thresholdInput = document.getElementById('threshold-input');
const thresholdDisplay = document.getElementById('threshold-display');
const btnSetThreshold = document.getElementById('btn-set-threshold');
const btnTogglePause = document.getElementById('btn-toggle-pause');
const btnTriggerSnapshot = document.getElementById('btn-trigger-snapshot');

const diagCam1Count = document.getElementById('diag-cam1-count');
const diagCam2Count = document.getElementById('diag-cam2-count');
const diagThermalCount = document.getElementById('diag-thermal-count');
const diagPiPing = document.getElementById('diag-pi-ping');

// Global cache
let currentThermalData = [];
let currentMinTemp = 20.0;
let currentMaxTemp = 250.0;
let isPaused = false;
const ctx = thermalCanvas.getContext('2d');

// --- Ironbow Colormap Palette ---
function getIronbowColor(norm) {
  const v = Math.max(0.0, Math.min(1.0, norm));
  let r, g, b;

  if (v < 0.25) {
    const t = v / 0.25;
    r = Math.floor(t * 90);
    g = 0;
    b = Math.floor(80 + t * 60);
  } else if (v < 0.50) {
    const t = (v - 0.25) / 0.25;
    r = Math.floor(90 + t * 140);
    g = Math.floor(t * 40);
    b = Math.floor(140 - t * 140);
  } else if (v < 0.75) {
    const t = (v - 0.50) / 0.25;
    r = Math.floor(230 + t * 25);
    g = Math.floor(40 + t * 160);
    b = 0;
  } else {
    const t = (v - 0.75) / 0.25;
    r = 255;
    g = Math.floor(200 + t * 55);
    b = Math.floor(t * 255);
  }
  return [r, g, b];
}

// --- Render 32x24 Thermal Array to Canvas with Smoothing ---
function renderThermalCanvas(data, minT, maxT) {
  if (!data || data.length < 768) return;

  const width = 32;
  const height = 24;
  const delta = Math.max(maxT - minT, 0.5);

  // Create offscreen image buffer for 32x24 pixels
  const imgData = ctx.createImageData(width, height);
  for (let i = 0; i < 768; i++) {
    const temp = data[i];
    const norm = (temp - minT) / delta;
    const [r, g, b] = getIronbowColor(norm);
    const pixelIndex = i * 4;
    imgData.data[pixelIndex] = r;
    imgData.data[pixelIndex + 1] = g;
    imgData.data[pixelIndex + 2] = b;
    imgData.data[pixelIndex + 3] = 255;
  }

  // Draw scaled onto 320x240 canvas with bilinear smoothing
  createImageBitmap(imgData).then((bmp) => {
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(bmp, 0, 0, thermalCanvas.width, thermalCanvas.height);
  });
}

// --- Hover on Canvas: Extract exact temperature ---
thermalCanvas.addEventListener('mousemove', (e) => {
  if (!currentThermalData || currentThermalData.length < 768) return;

  const rect = thermalCanvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;
  const mouseY = e.clientY - rect.top;

  const gridX = Math.floor((mouseX / thermalCanvas.width) * 32);
  const gridY = Math.floor((mouseY / thermalCanvas.height) * 24);

  if (gridX >= 0 && gridX < 32 && gridY >= 0 && gridY < 24) {
    const idx = gridY * 32 + gridX;
    const temp = currentThermalData[idx];
    thermalTooltip.textContent = `[${gridX}, ${gridY}]: ${temp.toFixed(1)} °C`;
  }
});

thermalCanvas.addEventListener('mouseleave', () => {
  thermalTooltip.textContent = 'Hover over pixel';
});

// --- Telemetry Polling Loop ---
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const data = await res.json();

    // Edge Node status
    const piNode = data.nodes.pi_edge_node;
    if (piNode.active) {
      pillPi.classList.remove('offline');
      pillPi.classList.add('online');
    } else {
      pillPi.classList.remove('online');
      pillPi.classList.add('offline');
    }

    const espNode = data.nodes.esp32_thermal_node;
    if (espNode.active) {
      pillThermal.classList.remove('offline');
      pillThermal.classList.add('online');
    } else {
      pillThermal.classList.remove('online');
      pillThermal.classList.add('offline');
    }

    // Alarm indicator
    if (data.alert.active) {
      alarmBanner.className = 'alarm-pill triggered';
      alarmText.textContent = `OVERHEAT: ${data.alert.current_max_c.toFixed(1)}°C >= ${data.alert.threshold_c}°C`;
    } else {
      alarmBanner.className = 'alarm-pill normal';
      alarmText.textContent = 'TEMP NORMAL';
    }

    // Diagnostics
    diagCam1Count.textContent = piNode.cam1.frames_total;
    diagCam2Count.textContent = piNode.cam2.frames_total;
    diagThermalCount.textContent = espNode.frames_total;

    const minPing = Math.min(
      piNode.cam1.last_seen_seconds_ago ?? 999,
      piNode.cam2.last_seen_seconds_ago ?? 999
    );
    diagPiPing.textContent = minPing < 999 ? `${minPing}s ago` : 'Offline';

    // Update pause state button text
    isPaused = data.control.is_paused;
    btnTogglePause.textContent = isPaused ? '▶ Resume Capture' : '⏸ Pause Capture';
    btnTogglePause.className = isPaused ? 'btn btn-primary' : 'btn btn-warning';

  } catch (err) {
    console.warn('Status poll error:', err);
  }
}

async function fetchLatestCameraFrames() {
  const nonce = Date.now();
  // Cam 1
  try {
    const res1 = await fetch(`/api/latest/cam1?t=${nonce}`, { cache: 'no-store' });
    if (res1.ok) {
      const blob = await res1.blob();
      cam1Img.src = URL.createObjectURL(blob);
      const ts = res1.headers.get('X-Timestamp');
      if (ts) {
        cam1Timestamp.textContent = ts.split('T')[1]?.substring(0, 8) || ts;
      }
      cam1Meta.textContent = '1920x1080 | Live';
    }
  } catch (e) {}

  // Cam 2
  try {
    const res2 = await fetch(`/api/latest/cam2?t=${nonce}`, { cache: 'no-store' });
    if (res2.ok) {
      const blob = await res2.blob();
      cam2Img.src = URL.createObjectURL(blob);
      const ts = res2.headers.get('X-Timestamp');
      if (ts) {
        cam2Timestamp.textContent = ts.split('T')[1]?.substring(0, 8) || ts;
      }
      cam2Meta.textContent = '1920x1080 | Live';
    }
  } catch (e) {}
}

async function fetchLatestThermal() {
  try {
    const res = await fetch('/api/latest/thermal', { cache: 'no-store' });
    if (!res.ok) return;
    const payload = await res.json();
    if (!payload.active || !payload.thermal_data) return;

    currentThermalData = payload.thermal_data;
    currentMinTemp = payload.min_temp;
    currentMaxTemp = payload.max_temp;

    tempMaxVal.textContent = `${payload.max_temp.toFixed(1)} °C`;
    tempCenterVal.textContent = `${payload.center_temp.toFixed(1)} °C`;
    tempMinVal.textContent = `${payload.min_temp.toFixed(1)} °C`;

    scaleMin.textContent = `${Math.floor(payload.min_temp)}°C`;
    scaleMax.textContent = `${Math.ceil(payload.max_temp)}°C`;

    renderThermalCanvas(payload.thermal_data, payload.min_temp, payload.max_temp);
  } catch (err) {
    console.warn('Thermal poll error:', err);
  }
}

// --- Control Event Handlers ---
intervalSlider.addEventListener('input', (e) => {
  intervalDisplay.textContent = `${parseFloat(e.target.value).toFixed(1)} s`;
});

intervalSlider.addEventListener('change', async (e) => {
  const val = parseFloat(e.target.value);
  await fetch('/api/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interval_seconds: val })
  });
});

btnSetThreshold.addEventListener('click', async () => {
  const val = parseFloat(thresholdInput.value);
  if (!isNaN(val)) {
    thresholdDisplay.textContent = `${val.toFixed(1)} °C`;
    await fetch('/api/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alert_threshold_c: val })
    });
  }
});

btnTogglePause.addEventListener('click', async () => {
  await fetch('/api/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_paused: !isPaused })
  });
  fetchStatus();
});

btnTriggerSnapshot.addEventListener('click', async () => {
  btnTriggerSnapshot.textContent = '⏳ Requesting...';
  btnTriggerSnapshot.disabled = true;
  await fetch('/api/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ trigger_snapshot: true })
  });
  setTimeout(() => {
    btnTriggerSnapshot.textContent = '📸 Trigger Snapshot Now';
    btnTriggerSnapshot.disabled = false;
  }, 2000);
});

// Periodic Timers
setInterval(fetchStatus, 2000);
setInterval(fetchLatestCameraFrames, 2500);
setInterval(fetchLatestThermal, 2000);

// Initial Load
fetchStatus();
fetchLatestCameraFrames();
fetchLatestThermal();
