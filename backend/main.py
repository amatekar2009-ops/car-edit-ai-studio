from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from typing import List

app = FastAPI(title="Car Edit AI Studio API", version="0.1.0")
ROOT = Path(__file__).resolve().parent.parent
JOBS = {}

@app.get("/health")
def health():
    return {"ok": True, "service": "car-edit-ai-studio", "engine_connected": False}

@app.get("/")
def home():
    page = ROOT / "index.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(page)

@app.post("/jobs")
async def create_job(video: UploadFile = File(...), references: List[UploadFile] = File(...),
                     quality: str = Form("1080p"), aspect_ratio: str = Form("Keep original"),
                     notes: str = Form("")):
    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Please upload a video file.")
    if not references or len(references) > 8:
        raise HTTPException(status_code=400, detail="Upload between 1 and 8 reference photos.")
    for photo in references:
        if not photo.content_type or not photo.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="All references must be image files.")
    job_id = str(uuid4())
    JOBS[job_id] = {"job_id": job_id, "status": "queued_demo",
      "created_at": datetime.now(timezone.utc).isoformat(), "video_filename": video.filename,
      "reference_filenames": [p.filename for p in references], "quality": quality,
      "aspect_ratio": aspect_ratio, "notes": notes[:1000], "rendered_file": None}
    await video.close()
    for photo in references: await photo.close()
    return JOBS[job_id]

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found; demo jobs reset when server restarts.")
    return JOBS[job_id]

@app.post("/jobs/{job_id}/process")
def process_job(job_id: str):
    if job_id not in JOBS: raise HTTPException(status_code=404, detail="Job not found.")
    raise HTTPException(status_code=501, detail="Video AI engine is not connected. No car replacement or MP4 render has been performed.")
