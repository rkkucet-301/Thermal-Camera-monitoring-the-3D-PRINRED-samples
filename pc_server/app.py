import io
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import sys

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

try:
    from pc_server.config import (
        CAPTURES_DIR,
        DEFAULT_INTERVAL_SECONDS,
        HOTEND_MAX_ALERT_TEMP,
        BED_MAX_ALERT_TEMP,
        ENCLOSURE_MAX_ALERT_TEMP,
    )
except ImportError:
    from config import (
        CAPTURES_DIR,
        DEFAULT_INTERVAL_SECONDS,
        HOTEND_MAX_ALERT_TEMP,
        BED_MAX_ALERT_TEMP,
        ENCLOSURE_MAX_ALERT_TEMP,
    )

app = FastAPI(title="3D Printer Remote Monitor Hub", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static and Templates
SERVER_DIR = Path(__file__).resolve().parent
STATIC_DIR = SERVER_DIR / "static"
TEMPLATES_DIR = SERVER_DIR / "templates"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "js").mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# In-memory latest state buffer
latest_state = {
    "cam1": {
        "bytes": None,
        "timestamp": None,
        "content_type": "image/jpeg",
        "resolution": "1920x1080",
        "cam_name": "UC-726 12MP (Bed View)",
        "frames_total": 0,
        "last_seen": 0,
    },
    "cam2": {
        "bytes": None,
        "timestamp": None,
        "content_type": "image/jpeg",
        "resolution": "1920x1080",
        "cam_name": "UC-726 16MP (Toolhead View)",
        "frames_total": 0,
        "last_seen": 0,
    },
    "thermal": {
        "device_id": "esp32_s3_mlx90640",
        "timestamp": None,
        "min_temp": 0.0,
        "max_temp": 0.0,
        "center_temp": 0.0,
        "ambient_temp": 0.0,
        "thermal_data": [],
        "rendered_png": None,
        "frames_total": 0,
        "last_seen": 0,
    },
    "control": {
        "interval_seconds": DEFAULT_INTERVAL_SECONDS,
        "is_paused": False,
        "trigger_snapshot": False,
        "alert_threshold_c": HOTEND_MAX_ALERT_TEMP,
        "last_command_time": time.time(),
    },
}


class ThermalPayload(BaseModel):
    device_id: Optional[str] = "esp32_s3_mlx90640"
    timestamp: Optional[str] = None
    min_temp: float
    max_temp: float
    center_temp: float
    ambient_temp: Optional[float] = 25.0
    thermal_data: List[float] = Field(..., description="768 float temperature readings (32x24 grid)")


class ControlUpdatePayload(BaseModel):
    interval_seconds: Optional[float] = None
    is_paused: Optional[bool] = None
    trigger_snapshot: Optional[bool] = None
    alert_threshold_c: Optional[float] = None


# --- Heatmap Image Generation (Pure Python / PIL fallback) ---
def render_ironbow_heatmap(thermal_data: List[float], min_t: float, max_t: float, width=320, height=240) -> bytes:
    """Renders 32x24 thermal float values into an upscaled smooth PNG using an Ironbow palette."""
    try:
        from PIL import Image
    except ImportError:
        return b""

    # MLX90640 sensor dimensions
    src_w, src_h = 32, 24
    if len(thermal_data) < src_w * src_h:
        return b""

    # Ironbow color map gradient keypoints (Normalized 0.0 to 1.0 -> RGB)
    # 0.00: Dark Blue (0, 0, 80)
    # 0.25: Violet / Purple (90, 0, 140)
    # 0.50: Bright Red / Orange (230, 40, 0)
    # 0.75: Bright Yellow (255, 200, 0)
    # 1.00: White (255, 255, 255)
    def ironbow(val: float):
        v = max(0.0, min(1.0, val))
        if v < 0.25:
            t = v / 0.25
            return (int(0 + t * 90), 0, int(80 + t * 60))
        elif v < 0.50:
            t = (v - 0.25) / 0.25
            return (int(90 + t * 140), int(t * 40), int(140 - t * 140))
        elif v < 0.75:
            t = (v - 0.50) / 0.25
            return (int(230 + t * 25), int(40 + t * 160), 0)
        else:
            t = (v - 0.75) / 0.25
            return (255, int(200 + t * 55), int(t * 255))

    delta_t = max(max_t - min_t, 0.1)
    # Build 32x24 raw PIL Image
    img = Image.new("RGB", (src_w, src_h))
    pixels = img.load()

    for y in range(src_h):
        for x in range(src_w):
            idx = y * src_w + x
            temp = thermal_data[idx]
            norm = (temp - min_t) / delta_t
            pixels[x, y] = ironbow(norm)

    # Upscale smoothly with bicubic interpolation
    upscaled = img.resize((width, height), resample=Image.BICUBIC)

    out_buf = io.BytesIO()
    upscaled.save(out_buf, format="PNG", optimize=True)
    return out_buf.getvalue()


# --- Storage Utility ---
def save_frame_to_disk(folder_name: str, filename_prefix: str, ext: str, data: bytes) -> str:
    """Saves binary data to captures/YYYY-MM-DD/{folder_name}/{prefix}_{timestamp}.ext"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    target_dir = CAPTURES_DIR / date_str / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%H-%M-%S-%f")[:-3]
    file_path = target_dir / f"{filename_prefix}_{timestamp_str}.{ext}"

    with open(file_path, "wb") as f:
        f.write(data)
    return str(file_path)


# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    index_file = TEMPLATES_DIR / "index.html"
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@app.post("/api/upload/camera/{cam_id}")
async def upload_camera_frame(
    cam_id: str,
    file: UploadFile = File(...),
    resolution: Optional[str] = Form("1920x1080"),
    timestamp: Optional[str] = Form(None),
):
    if cam_id not in ["cam1", "cam2"]:
        raise HTTPException(status_code=400, detail="Invalid cam_id. Use 'cam1' or 'cam2'.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty image payload received.")

    # Save to disk on host (PC side has ample storage)
    save_frame_to_disk(cam_id, cam_id, "jpg", contents)

    # Update in-memory state
    now_ts = timestamp or datetime.now().isoformat()
    latest_state[cam_id]["bytes"] = contents
    latest_state[cam_id]["timestamp"] = now_ts
    latest_state[cam_id]["resolution"] = resolution
    latest_state[cam_id]["frames_total"] += 1
    latest_state[cam_id]["last_seen"] = time.time()

    return {
        "status": "ok",
        "cam_id": cam_id,
        "bytes_received": len(contents),
        "total_frames": latest_state[cam_id]["frames_total"],
        "timestamp": now_ts,
    }


@app.post("/api/upload/thermal")
async def upload_thermal_payload(payload: ThermalPayload):
    if len(payload.thermal_data) != 768:
        raise HTTPException(status_code=400, detail="thermal_data must contain exactly 768 float readings.")

    now_ts = payload.timestamp or datetime.now().isoformat()

    # Save raw telemetry JSON to disk
    json_bytes = json.dumps(payload.dict(), indent=2).encode("utf-8")
    save_frame_to_disk("thermal", "mlx90640", "json", json_bytes)

    # Generate smooth PNG heatmap and save image copy
    heatmap_bytes = render_ironbow_heatmap(payload.thermal_data, payload.min_temp, payload.max_temp)
    if heatmap_bytes:
        save_frame_to_disk("thermal", "heatmap", "png", heatmap_bytes)

    # Update state
    latest_state["thermal"]["device_id"] = payload.device_id
    latest_state["thermal"]["timestamp"] = now_ts
    latest_state["thermal"]["min_temp"] = payload.min_temp
    latest_state["thermal"]["max_temp"] = payload.max_temp
    latest_state["thermal"]["center_temp"] = payload.center_temp
    latest_state["thermal"]["ambient_temp"] = payload.ambient_temp
    latest_state["thermal"]["thermal_data"] = payload.thermal_data
    latest_state["thermal"]["rendered_png"] = heatmap_bytes
    latest_state["thermal"]["frames_total"] += 1
    latest_state["thermal"]["last_seen"] = time.time()

    return {
        "status": "ok",
        "device_id": payload.device_id,
        "min_temp": payload.min_temp,
        "max_temp": payload.max_temp,
        "center_temp": payload.center_temp,
        "frames_total": latest_state["thermal"]["frames_total"],
        "timestamp": now_ts,
    }


@app.get("/api/latest/{cam_id}")
async def get_latest_camera_image(cam_id: str):
    if cam_id not in ["cam1", "cam2"]:
        raise HTTPException(status_code=400, detail="Invalid cam_id.")

    frame = latest_state[cam_id]["bytes"]
    if not frame:
        raise HTTPException(status_code=404, detail="No frame captured yet for this camera.")

    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Timestamp": str(latest_state[cam_id]["timestamp"]),
        },
    )


@app.get("/api/latest/thermal/image")
async def get_latest_thermal_image():
    png_bytes = latest_state["thermal"]["rendered_png"]
    if not png_bytes:
        # Generate placeholder or render on-demand
        data = latest_state["thermal"]["thermal_data"]
        if data:
            png_bytes = render_ironbow_heatmap(
                data, latest_state["thermal"]["min_temp"], latest_state["thermal"]["max_temp"]
            )
        if not png_bytes:
            raise HTTPException(status_code=404, detail="No thermal image rendered yet.")

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/latest/thermal")
async def get_latest_thermal_data():
    if not latest_state["thermal"]["thermal_data"]:
        return JSONResponse(
            status_code=200,
            content={
                "device_id": "esp32_s3_mlx90640",
                "timestamp": None,
                "min_temp": 0.0,
                "max_temp": 0.0,
                "center_temp": 0.0,
                "thermal_data": [],
                "active": False,
            },
        )
    return {
        "device_id": latest_state["thermal"]["device_id"],
        "timestamp": latest_state["thermal"]["timestamp"],
        "min_temp": latest_state["thermal"]["min_temp"],
        "max_temp": latest_state["thermal"]["max_temp"],
        "center_temp": latest_state["thermal"]["center_temp"],
        "ambient_temp": latest_state["thermal"]["ambient_temp"],
        "thermal_data": latest_state["thermal"]["thermal_data"],
        "active": True,
    }


@app.get("/api/status")
async def get_system_status():
    now = time.time()
    pi_active = (now - latest_state["cam1"]["last_seen"] < 12.0) or (now - latest_state["cam2"]["last_seen"] < 12.0)
    thermal_active = (now - latest_state["thermal"]["last_seen"] < 12.0)

    is_temp_alert = latest_state["thermal"]["max_temp"] >= latest_state["control"]["alert_threshold_c"]

    return {
        "server_time": datetime.now().isoformat(),
        "nodes": {
            "pi_edge_node": {
                "active": pi_active,
                "cam1": {
                    "last_seen_seconds_ago": round(now - latest_state["cam1"]["last_seen"], 1)
                    if latest_state["cam1"]["last_seen"] > 0
                    else None,
                    "frames_total": latest_state["cam1"]["frames_total"],
                    "resolution": latest_state["cam1"]["resolution"],
                },
                "cam2": {
                    "last_seen_seconds_ago": round(now - latest_state["cam2"]["last_seen"], 1)
                    if latest_state["cam2"]["last_seen"] > 0
                    else None,
                    "frames_total": latest_state["cam2"]["frames_total"],
                    "resolution": latest_state["cam2"]["resolution"],
                },
            },
            "esp32_thermal_node": {
                "active": thermal_active,
                "last_seen_seconds_ago": round(now - latest_state["thermal"]["last_seen"], 1)
                if latest_state["thermal"]["last_seen"] > 0
                else None,
                "frames_total": latest_state["thermal"]["frames_total"],
                "min_temp": latest_state["thermal"]["min_temp"],
                "max_temp": latest_state["thermal"]["max_temp"],
                "center_temp": latest_state["thermal"]["center_temp"],
            },
        },
        "control": latest_state["control"],
        "alert": {
            "active": is_temp_alert,
            "threshold_c": latest_state["control"]["alert_threshold_c"],
            "current_max_c": latest_state["thermal"]["max_temp"],
        },
    }


@app.get("/api/control")
async def get_control_settings():
    """Polled by Edge Nodes to check current interval or snapshot triggers."""
    return latest_state["control"]


@app.post("/api/control")
async def update_control_settings(payload: ControlUpdatePayload):
    if payload.interval_seconds is not None:
        latest_state["control"]["interval_seconds"] = max(1.0, min(60.0, payload.interval_seconds))
    if payload.is_paused is not None:
        latest_state["control"]["is_paused"] = payload.is_paused
    if payload.trigger_snapshot is not None:
        latest_state["control"]["trigger_snapshot"] = payload.trigger_snapshot
    if payload.alert_threshold_c is not None:
        latest_state["control"]["alert_threshold_c"] = payload.alert_threshold_c

    latest_state["control"]["last_command_time"] = time.time()
    return {"status": "ok", "control": latest_state["control"]}


@app.post("/api/control/ack_snapshot")
async def acknowledge_snapshot():
    """Edge client calls this once it executes the on-demand snapshot."""
    latest_state["control"]["trigger_snapshot"] = False
    return {"status": "acknowledged"}


if __name__ == "__main__":
    import uvicorn
    from config import HOST, PORT

    uvicorn.run("app:app", host=HOST, port=PORT, reload=True)
