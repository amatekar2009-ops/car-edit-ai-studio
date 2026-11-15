import os
import tempfile
import subprocess
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

app = FastAPI(title="Car Edit AI Studio API", version="0.2.0")
ROOT = Path(__file__).resolve().parent.parent
RUNWAY_BASE = "https://api.dev.runwayml.com"
RUNWAY_VERSION = "2024-11-06"
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
JOBS = {}

def runway_headers():
    key = os.getenv("RUNWAY_API_KEY")
    if not key:
        raise HTTPException(
            status_code=503,
            detail="The video engine is not configured yet. An adult account owner must add a Runway API key to Render as RUNWAY_API_KEY."
        )
    return {
        "Authorization": f"Bearer {key}",
        "X-Runway-Version": RUNWAY_VERSION,
        "Content-Type": "application/json",
    }

async def upload_to_runway(client: httpx.AsyncClient, filename: str, data: bytes):
    headers = runway_headers()
    response = await client.post(
        f"{RUNWAY_BASE}/v1/uploads",
        headers=headers,
        json={"filename": filename, "type": "ephemeral"},
        timeout=30,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Runway upload setup failed ({response.status_code}). Check API access and credits.")
    info = response.json()
    upload_url = info.get("uploadUrl")
    fields = info.get("fields", {})
    uri = info.get("runwayUri")
    if not upload_url or not uri:
        raise HTTPException(status_code=502, detail="The video provider returned an incomplete upload response.")
    # Runway requires a fresh upload request for each file; do not retry a failed upload.
    form = {k: str(v) for k, v in fields.items()}
    files = {"file": (filename, data, "application/octet-stream")}
    uploaded = await client.post(upload_url, data=form, files=files, timeout=180)
    if uploaded.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"Media upload failed ({uploaded.status_code}). Please try again with a smaller file.")
    return uri

async def read_limited(upload: UploadFile, limit: int):
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"{upload.filename or 'File'} is too large.")
    if len(data) < 512:
        raise HTTPException(status_code=400, detail=f"{upload.filename or 'File'} is empty or too small.")
    return data

def extract_original_car_frame(video_bytes: bytes) -> bytes:
    # A representative still is used only when the user does not provide a separate
    # photo of the original vehicle. A clear original-car photo is strongly preferred.
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "source.mp4"
        frame = Path(folder) / "original-car.jpg"
        source.write_bytes(video_bytes)
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", "1", "-i", str(source), "-frames:v", "1", "-q:v", "3", str(frame)],
            capture_output=True, timeout=45
        )
        if result.returncode != 0 or not frame.exists():
            raise HTTPException(status_code=400, detail="Could not extract a frame. Upload a clear photo of the original car.")
        return frame.read_bytes()

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "car-edit-ai-studio",
        "engine_connected": bool(os.getenv("RUNWAY_API_KEY")),
        "engine": "Runway Product Swap" if os.getenv("RUNWAY_API_KEY") else "waiting_for_server_key",
    }

@app.get("/")
def home():
    page = ROOT / "index.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(page)

@app.post("/jobs")
async def create_job(
    video: UploadFile = File(...),
    references: List[UploadFile] = File(...),
    original_car: Optional[UploadFile] = File(None),
    duration: int = Form(8),
    quality: str = Form("720p"),
    notes: str = Form(""),
):
    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Please upload a video file.")
    if not references or len(references) > 10:
        raise HTTPException(status_code=400, detail="Upload between 1 and 10 replacement-car photos.")
    if duration < 4 or duration > 15:
        raise HTTPException(status_code=400, detail="Choose a duration between 4 and 15 seconds.")
    if quality not in ("720p", "1080p"):
        raise HTTPException(status_code=400, detail="Choose 720p or 1080p.")
    for photo in references:
        if not photo.content_type or not photo.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="All replacement references must be images.")
    video_bytes = await read_limited(video, MAX_VIDEO_BYTES)
    reference_data = []
    for photo in references:
        reference_data.append((photo.filename or "replacement.jpg", await read_limited(photo, MAX_IMAGE_BYTES)))
    if original_car is not None and original_car.filename:
        if not original_car.content_type or not original_car.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="The original-car reference must be an image.")
        original_bytes = await read_limited(original_car, MAX_IMAGE_BYTES)
        original_name = original_car.filename
    else:
        original_bytes = extract_original_car_frame(video_bytes)
        original_name = "original-car-frame.jpg"

    video_name = video.filename or "source.mp4"
    if Path(video_name).suffix.lower() not in (".mp4", ".mov", ".webm"):
        video_name += ".mp4"

    job_id = str(uuid4())
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "uploading",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video_filename": video.filename,
        "reference_filenames": [name for name, _ in reference_data],
        "duration": duration,
        "quality": quality,
        "notes": notes[:1000],
        "provider_task_id": None,
        "output_url": None,
    }

    try:
        async with httpx.AsyncClient() as client:
            video_uri = await upload_to_runway(client, video_name, video_bytes)
            original_uri = await upload_to_runway(client, original_name, original_bytes)
            new_images = []
            for name, data in reference_data:
                uri = await upload_to_runway(client, name, data)
                new_images.append({"uri": uri})
            body = {
                "version": "2026-06",
                "referenceVideo": {"uri": video_uri},
                "originalProductImage": {"uri": original_uri},
                "newProductImages": new_images,
                "duration": duration,
                "resolution": quality,
                "audio": True,
            }
            response = await client.post(
                f"{RUNWAY_BASE}/v1/recipes/product_swap",
                headers=runway_headers(),
                json=body,
                timeout=60,
            )
            if response.status_code >= 400:
                detail = "The video provider rejected the request. Check that the clip is 1.8–15 seconds, the images are valid, and the account has credits."
                try:
                    provider_error = response.json()
                    detail += " " + str(provider_error.get("error", provider_error.get("message", "")))[:300]
                except Exception:
                    pass
                raise HTTPException(status_code=502, detail=detail)
            task = response.json()
            task_id = task.get("id")
            if not task_id:
                raise HTTPException(status_code=502, detail="The video provider did not return a task ID.")
            JOBS[job_id]["provider_task_id"] = task_id
            JOBS[job_id]["status"] = "PENDING"
            JOBS[job_id]["estimated_cost"] = task.get("estimatedCost")
    except HTTPException:
        JOBS[job_id]["status"] = "FAILED"
        raise
    except httpx.TimeoutException:
        JOBS[job_id]["status"] = "FAILED"
        raise HTTPException(status_code=504, detail="The provider timed out while receiving the media. Please try again.")
    except Exception as exc:
        JOBS[job_id]["status"] = "FAILED"
        raise HTTPException(status_code=502, detail=f"Could not start the video edit: {str(exc)[:250]}")
    finally:
        await video.close()
        for photo in references:
            await photo.close()
        if original_car is not None:
            await original_car.close()
    return JOBS[job_id]

@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found. Jobs reset if the free server restarts.")
    task_id = job.get("provider_task_id")
    if task_id and job["status"] not in ("SUCCEEDED", "FAILED", "CANCELED"):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{RUNWAY_BASE}/v1/tasks/{task_id}",
                    headers=runway_headers(),
                    timeout=30,
                )
            if response.status_code < 400:
                task = response.json()
                job["status"] = task.get("status", job["status"])
                output = task.get("output") or []
                if job["status"] == "SUCCEEDED" and output:
                    job["output_url"] = output[0]
                if job["status"] == "FAILED":
                    job["error"] = task.get("failure", "The video provider could not complete this edit.")
        except Exception:
            # Keep the last known state; the browser can safely poll again.
            pass
    return job
