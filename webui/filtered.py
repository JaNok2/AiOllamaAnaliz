from fastapi import APIRouter, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import json, re

router = APIRouter()

BASE = Path(__file__).resolve().parent
UPLOAD = BASE / "uploads"
TEMPLATES = BASE / "templates"
FILTERED_JSON = UPLOAD / "filtered_download.json"
UPLOAD.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=BASE / "templates")

@router.get("/filter-download", response_class=HTMLResponse)
async def filter_download_page(request: Request):
    return templates.TemplateResponse("filter_download.html", {"request": request})


@router.post("/filter-download", response_class=HTMLResponse)
async def filter_download_process(request: Request,
                                  logfile: UploadFile = File(...),
                                  min_level: int = Form(6),
                                  agent_name_contains: str = Form("")):
    try:
        lines = logfile.file.read().decode("utf-8").splitlines()
        raw = [json.loads(line) for line in lines if line.strip()]

        filtered = [
            log for log in raw
            if log.get("rule", {}).get("level", 0) >= min_level and
               (agent_name_contains.lower() in log.get("agent", {}).get("name", "").lower())
        ]

        with FILTERED_JSON.open("w", encoding="utf-8") as f:
            json.dump(filtered, f, ensure_ascii=False, separators=(',', ':'))


        return templates.TemplateResponse("filter_download_result.html", {
            "request": request,
            "before_count": len(raw),
            "after_count": len(filtered),
            "can_download": True
        })

    except Exception as e:
        return HTMLResponse(f"<h3>Błąd podczas filtrowania: {e}</h3>", status_code=500)


@router.get("/filtered/download-json")
async def download_filtered_json():
    if FILTERED_JSON.exists():
        return FileResponse(FILTERED_JSON, media_type="application/json", filename="filtered_logs.json")
    return HTMLResponse("<h3>Plik nie istnieje.</h3>", status_code=404)
