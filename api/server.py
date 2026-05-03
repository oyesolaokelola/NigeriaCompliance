from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os
import sys
import uuid
import json
import threading
import time
from datetime import datetime
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

PROCESS_LOCK = threading.Lock()
PROCESS_STATUS = {
    "running": False,
    "last_started": None,
    "last_finished": None,
    "last_error": None,
    "last_error_type": None,
    "last_message": None,
}


def _update_status(**kwargs):
    with PROCESS_LOCK:
        PROCESS_STATUS.update(kwargs)


def _start_background_process():
    with PROCESS_LOCK:
        if PROCESS_STATUS["running"]:
            return False
        PROCESS_STATUS.update(
            {
                "running": True,
                "last_started": datetime.utcnow().isoformat() + "Z",
                "last_finished": None,
                "last_error": None,
                "last_error_type": None,
                "last_message": "Processing started",
            }
        )

    def _target():
        try:
            result = process_repository()
            _update_status(
                last_finished=datetime.utcnow().isoformat() + "Z",
                last_message="Processing completed successfully",
            )
            return result
        except Exception as exc:
            _update_status(
                last_finished=datetime.utcnow().isoformat() + "Z",
                last_error=str(exc),
                last_error_type=type(exc).__name__,
                last_message="Processing failed",
            )
        finally:
            _update_status(running=False)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return True


@app.get("/")
def root():
    return {
        "message": "NigeriaCompliance API is running.",
        "endpoints": [
            "/health",
            "/upload",
            "/process",
            "/process/status",
            "/aggregated",
            "/artifact/{filename}",
            "/debug/files",
            "/debug/test-extraction",
            "/debug/env",
            "/debug/output",
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


@app.get("/debug/env")
def debug_env():
    """Show runtime environment variables used by the app."""
    return {
        "OPENAI_API_KEY_present": bool(os.getenv("OPENAI_API_KEY")),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL"),
        "OLLAMA_BASE_URL": os.getenv("OLLAMA_BASE_URL"),
        "OLLAMA_MODEL": os.getenv("OLLAMA_MODEL"),
        "FRONTEND_ORIGINS": os.getenv("FRONTEND_ORIGINS"),
        "BASE_URL": os.getenv("BASE_URL"),
    }


@app.get("/debug/output")
def debug_output():
    """Show what files are in the output directory."""
    files = []
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.iterdir():
            if f.is_file():
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "suffix": f.suffix,
                })
    return {
        "output_path": str(OUTPUT_DIR),
        "files": files,
        "total_files": len(files),
    }


@app.post("/process")
def process_endpoint():
    started = _start_background_process()
    if not started:
        return {
            "success": True,
            "message": "Processing is already running.",
            "running": True,
        }

    return {
        "success": True,
        "message": "Processing started in the background.",
        "running": True,
        "status_url": "/process/status",
        "aggregated_url": "/aggregated",
    }


@app.get("/process/status")
def process_status():
    with PROCESS_LOCK:
        return {
            "running": PROCESS_STATUS["running"],
            "last_started": PROCESS_STATUS["last_started"],
            "last_finished": PROCESS_STATUS["last_finished"],
            "last_error": PROCESS_STATUS["last_error"],
            "last_error_type": PROCESS_STATUS["last_error_type"],
            "last_message": PROCESS_STATUS["last_message"],
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
