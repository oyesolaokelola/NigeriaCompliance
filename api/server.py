from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os
import sys
import uuid
import json
from pathlib import Path

# Ensure project root is importable
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from workflow.run_workflow import process_repository
except Exception:
    # fallback if executed from within the workflow package
    from run_workflow import process_repository

app = FastAPI(title="NigeriaCompliance POC API")

origins_env = os.getenv("FRONTEND_ORIGINS", "*")
if origins_env == "*":
    origins = ["*"]
else:
    origins = [o.strip() for o in origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPO_DIR = BASE_DIR / "repository"
OUTPUT_DIR = BASE_DIR / "output"
REPO_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload(file: UploadFile = File(...), department: str = Form("other")):
    dept = department.lower()
    dest_dir = REPO_DIR / dept
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    dest_path = dest_dir / filename
    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)
    return {"stored_path": str(dest_path), "department": dept, "filename": filename}


@app.post("/process")
def process_endpoint():
    try:
        res = process_repository()
        base_url = os.getenv("BASE_URL", "").rstrip("/")

        def make_url(p):
            if not p:
                return None
            if base_url:
                return f"{base_url}/artifact/{Path(p).name}"
            return str(p)

        return {
            "aggregated": res.get("aggregated"),
            "status": res.get("status"),
            "issues": res.get("issues"),
            "html_report": make_url(res.get("html_report")),
            "pdf_report": make_url(res.get("pdf_report")),
            "aggregated_json": make_url(res.get("aggregated_json")),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/artifact/{filename}")
def artifact(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)


@app.get("/aggregated")
def get_aggregated():
    path = OUTPUT_DIR / "aggregated_data.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Aggregated data not found")
    with open(path, "r", encoding="utf-8") as f:
        j = json.load(f)
    return j
