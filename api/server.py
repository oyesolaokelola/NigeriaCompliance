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
from workflow.template_styling import TemplateManager

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
TEMPLATES_DIR = BASE_DIR / "templates"
REPO_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

# Initialize template manager
template_manager = TemplateManager(TEMPLATES_DIR)

PROCESSED_FILES_NAME = ".processed_files.json"


def _load_processed_paths() -> set[str]:
    processed_file_path = OUTPUT_DIR / PROCESSED_FILES_NAME
    if not processed_file_path.exists():
        return set()
    try:
        with open(processed_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return set(data.get("processed_files", []))
    except Exception:
        pass
    return set()


PROCESS_LOCK = threading.Lock()
PROCESS_STATUS = {
    "running": False,
    "last_started": None,
    "last_finished": None,
    "last_error": None,
    "last_error_type": None,
    "last_message": None,
    "active_template": None,
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

    active_template = PROCESS_STATUS.get("active_template")

    def _target():
        try:
            result = process_repository(template_name=active_template)
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
        "message": "NigeriaCompliance API is running with Dynamic Template Styling Support",
        "core_endpoints": [
            "/health",
            "/upload (POST) - Upload document to process",
            "/process (POST) - Start processing workflow",
            "/process/status (GET) - Get processing status",
            "/aggregated (GET) - Get aggregated results",
            "/artifact/{filename} (GET) - Download output file",
        ],
        "template_endpoints": [
            "/templates/upload (POST) - Upload style template",
            "/templates (GET) - List all templates",
            "/templates/{template_name}/activate (POST) - Activate template",
            "/templates/info/{template_name} (GET) - Get template details",
        ],
        "debug_endpoints": [
            "/debug/files",
            "/debug/test-extraction",
            "/debug/env",
            "/debug/output",
            "/debug/processing-files",
        ],
        "workflow": "Upload style template → Upload documents → Activate template → Process with styling",
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


@app.post("/templates/upload")
async def upload_template(file: UploadFile = File(...), template_name: str = Form(None)):
    """Upload and register a style template document"""
    try:
        # Store template file
        filename = template_name or file.filename
        template_path = TEMPLATES_DIR / f"{uuid.uuid4().hex}_{filename}"
        content = await file.read()
        with open(template_path, "wb") as f:
            f.write(content)
        
        # Extract and register styling
        profile = template_manager.register_template(str(template_path), template_name or filename)
        
        return {
            "success": True,
            "template_name": profile.template_name,
            "template_path": str(template_path),
            "message": f"Template '{profile.template_name}' registered successfully",
            "styles": {
                "title_font": {
                    "name": profile.title_font.name,
                    "size": profile.title_font.size,
                    "bold": profile.title_font.bold
                },
                "heading_font": {
                    "name": profile.heading_font.name,
                    "size": profile.heading_font.size,
                    "bold": profile.heading_font.bold
                },
                "body_font": {
                    "name": profile.body_font.name,
                    "size": profile.body_font.size
                }
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Template upload failed: {str(e)}")


@app.get("/templates")
def list_templates():
    """List all registered templates"""
    try:
        templates = template_manager.list_templates()
        active = PROCESS_STATUS.get("active_template")
        return {
            "templates": templates,
            "active_template": active,
            "total_templates": len(templates)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to list templates: {str(e)}")


@app.post("/templates/{template_name}/activate")
def activate_template(template_name: str):
    """Activate a template for use in document processing"""
    try:
        profile = template_manager.get_template_profile(template_name)
        if not profile:
            raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")
        
        _update_status(active_template=template_name)
        return {
            "success": True,
            "active_template": template_name,
            "message": f"Template '{template_name}' activated",
            "profile": {
                "template_name": profile.template_name,
                "title_font": profile.title_font.name if profile.title_font else "Default",
                "heading_font": profile.heading_font.name if profile.heading_font else "Default",
                "body_font": profile.body_font.name if profile.body_font else "Default",
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to activate template: {str(e)}")


@app.get("/templates/info/{template_name}")
def get_template_info(template_name: str):
    """Get detailed information about a specific template"""
    try:
        profile = template_manager.get_template_profile(template_name)
        if not profile:
            raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")
        
        return {
            "template_name": profile.template_name,
            "margins": {
                "left": profile.margin_left,
                "right": profile.margin_right,
                "top": profile.margin_top,
                "bottom": profile.margin_bottom
            },
            "fonts": {
                "title": {
                    "name": profile.title_font.name,
                    "size": profile.title_font.size,
                    "bold": profile.title_font.bold,
                    "italic": profile.title_font.italic,
                    "color": profile.title_font.color
                },
                "heading": {
                    "name": profile.heading_font.name,
                    "size": profile.heading_font.size,
                    "bold": profile.heading_font.bold,
                    "italic": profile.heading_font.italic,
                    "color": profile.heading_font.color
                },
                "body": {
                    "name": profile.body_font.name,
                    "size": profile.body_font.size,
                    "bold": profile.body_font.bold,
                    "italic": profile.body_font.italic,
                    "color": profile.body_font.color
                }
            },
            "page": {
                "width": profile.page_width,
                "height": profile.page_height,
                "orientation": profile.orientation
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to get template info: {str(e)}")


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


@app.get("/debug/processing-files")
def debug_processing_files():
    """Show which files would be processed by the workflow."""
    from workflow.ingestion import discover_files

    all_files = discover_files(REPO_DIR)
    processed_paths = _load_processed_paths()

    def _relative_repo_path(path: Path) -> str:
        return str(path.relative_to(REPO_DIR).as_posix())

    unprocessed = []
    for f in all_files:
        rel_path = _relative_repo_path(f["path"])
        unprocessed.append(
            {
                "department": f["department"],
                "filename": Path(f["path"]).name,
                "path": str(f["path"]),
                "relative_path": rel_path,
                "size": Path(f["path"]).stat().st_size,
                "processed": rel_path in processed_paths,
            }
        )

    return {
        "repository_path": str(REPO_DIR),
        "files_found": unprocessed,
        "total_files": len(unprocessed),
        "unprocessed_files": [f for f in unprocessed if not f["processed"]],
        "total_unprocessed": len([f for f in unprocessed if not f["processed"]]),
        "note": "Only unprocessed files will be included in the next workflow run.",
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
