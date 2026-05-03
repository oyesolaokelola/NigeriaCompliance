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

from workflow.run_workflow import process_repository

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


@app.get("/")
def root():
    return {
        "message": "NigeriaCompliance API is running.",
        "endpoints": [
            "/health",
            "/upload",
            "/process",
            "/aggregated",
            "/artifact/{filename}",
        ],
        "note": "Use the Railway service URL with these endpoints. POST /upload and POST /process are the main workflow actions.",
    }


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


@app.get("/debug/files")
def debug_files():
    """List all files in the repository for debugging."""
    files_by_dept = {}
    for dept_dir in REPO_DIR.iterdir():
        if dept_dir.is_dir():
            dept_name = dept_dir.name
            files = [{"name": f.name, "size": f.stat().st_size, "suffix": f.suffix} 
                     for f in dept_dir.iterdir() if f.is_file()]
            files_by_dept[dept_name] = files
    return {
        "repository_path": str(REPO_DIR),
        "files_by_department": files_by_dept,
        "total_files": sum(len(v) for v in files_by_dept.values()),
    }


@app.get("/debug/test-extraction")
def debug_test_extraction():
    """Test extraction on a single file for debugging."""
    from workflow.extraction import extract_record
    from pathlib import Path
    
    try:
        # Find first file in repository
        first_file = None
        for dept_dir in REPO_DIR.iterdir():
            if dept_dir.is_dir():
                for f in dept_dir.iterdir():
                    if f.is_file():
                        first_file = f
                        break
            if first_file:
                break
        
        if not first_file:
            return {"error": "No files found in repository"}
        
        file_info = {"path": first_file, "department": first_file.parent.name}
        result = extract_record(file_info)
        
        return {
            "success": True,
            "tested_file": first_file.name,
            "file_type": result.get("file_type"),
            "text_length": len(result.get("raw_text", "")),
            "tables_count": len(result.get("raw_tables", [])),
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


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
            "success": True,
            "aggregated": res.get("aggregated"),
            "status": res.get("status"),
            "issues": res.get("issues"),
            "html_report": make_url(res.get("html_report")),
            "pdf_report": make_url(res.get("pdf_report")),
            "aggregated_json": make_url(res.get("aggregated_json")),
        }
    except Exception as exc:
        import traceback
        return {
            "success": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
            "hint": "Check /debug/files and /debug/test-extraction for more details"
        }


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
