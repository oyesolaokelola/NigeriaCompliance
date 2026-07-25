from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import logging
import os
import sys
import uuid
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.parse import quote

# Ensure project root is importable
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from workflow.run_workflow import process_repository
from workflow.template_styling import TemplateManager
from workflow.claude_pipeline import ClaudePipeline
from workflow.aggregation import aggregate_records
from workflow.compliance import run_compliance_checks
from workflow.reporting import create_summary_charts, generate_html_report

app = FastAPI(title="NigeriaCompliance POC API")

logger = logging.getLogger(__name__)


@app.on_event("startup")
async def log_anthropic_startup():
    """Log the installed Anthropic package version and whether the client exposes the Files API.

    This helps identify mismatches between `requirements.txt` and the runtime environment
    when viewing Railway build/runtime logs.
    """
    try:
        import anthropic
    except Exception as e:
        logger.info(f"Anthropic import failed at startup: {e}")
        return

    ver = getattr(anthropic, "__version__", None)
    has_files = False
    try:
        key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        if key:
            client_cls = getattr(anthropic, "Anthropic", None) or getattr(anthropic, "Client", None)
            if client_cls is not None:
                try:
                    client = client_cls(api_key=key)
                    has_files = hasattr(client, "files") or (hasattr(client, "beta") and hasattr(client.beta, "files"))
                except Exception as e:
                    logger.info(f"Anthropic client construction failed at startup: {e}")
    except Exception:
        pass

    logger.info(f"Anthropic at startup: version={ver}, client_has_files={has_files}")

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
    "generation_mode": "apply",
    "uploaded_files": [],
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
    uploaded_files = PROCESS_STATUS.get("uploaded_files", [])
    generation_mode = PROCESS_STATUS.get("generation_mode", "apply")

    def _target():
        try:
            # Pass uploaded files to process only those, or None to process all
            file_paths = uploaded_files if uploaded_files else None
            result = process_repository(template_name=active_template, file_paths=file_paths)
            _update_status(
                last_finished=datetime.utcnow().isoformat() + "Z",
                last_message="Processing completed successfully",
                uploaded_files=[],  # Clear uploaded files after processing
            )
            return result
        except Exception as exc:
            _update_status(
                last_finished=datetime.utcnow().isoformat() + "Z",
                last_error=str(exc),
                last_error_type=type(exc).__name__,
                last_message="Processing failed",
                uploaded_files=[],  # Clear uploaded files even on failure
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
            "/artifacts (GET) - List generated artifact URLs",
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
    
    # Store uploaded file path for processing
    with PROCESS_LOCK:
        PROCESS_STATUS["uploaded_files"].append(str(dest_path))
    
    return {"stored_path": str(dest_path), "department": dept, "filename": filename}


@app.post("/templates/upload")
async def upload_template(file: UploadFile = File(...), template_name: str = Form(None)):
    """Upload and register a style template document"""
    try:
        # Determine filename with proper extension
        base_filename = template_name or file.filename or "template"
        
        # Ensure filename has correct extension based on content-type
        content_type = file.content_type or ""
        is_pdf = False
        if not Path(base_filename).suffix:
            if "pdf" in content_type:
                base_filename += ".pdf"
                is_pdf = True
            elif "wordprocessingml" in content_type or "docx" in base_filename.lower():
                base_filename += ".docx"
            else:
                # Try to detect from file content (PDF files start with %PDF-)
                content = await file.read(10)
                await file.seek(0)  # Reset file pointer
                if content.startswith(b"%PDF-"):
                    base_filename += ".pdf"
                    is_pdf = True
                else:
                    raise ValueError("Could not determine template file format. Please ensure the file has a .pdf or .docx extension.")
        else:
            is_pdf = Path(base_filename).suffix.lower() == ".pdf"
        
        filename = f"{uuid.uuid4().hex}_{base_filename}"
        template_path = TEMPLATES_DIR / filename
        content = await file.read()
        with open(template_path, "wb") as f:
            f.write(content)
        
        # Extract and register styling
        profile = template_manager.register_template(str(template_path), template_name or Path(base_filename).stem)
        
        response_data = {
            "success": True,
            "template_name": profile.template_name,
            "template_path": str(template_path),
            "message": f"Template '{profile.template_name}' registered successfully",
            "pdf_converted": is_pdf,
            "conversion_method": None,
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
        
        # Add conversion info if PDF was converted
        if is_pdf:
            response_data["pdf_converted"] = True
            response_data["conversion_method"] = "pdf2docx"
            response_data["message"] = f"PDF converted to DOCX for enhanced extraction. Template '{profile.template_name}' registered successfully"
        
        return response_data
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Template upload failed: {str(e)}")


@app.get("/templates")
def list_templates():
    """List all registered templates"""
    try:
        templates = template_manager.list_templates()
        active = PROCESS_STATUS.get("active_template") or ""
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
        
        # Helper function to convert FontStyle to dict
        def font_style_to_dict(font):
            return {
                "name": font.name,
                "size": font.size,
                "bold": font.bold,
                "italic": font.italic,
                "underline": font.underline,
                "color": font.color,
                "highlight_color": font.highlight_color,
                "strike_through": font.strike_through,
                "subscript": font.subscript,
                "superscript": font.superscript
            }
        
        # Helper function to convert TableStyle to dict
        def table_style_to_dict(table_style):
            return {
                "style_name": table_style.style_name,
                "border_color": table_style.border_color,
                "border_width": table_style.border_width,
                "cell_padding": table_style.cell_padding,
                "header_background_color": table_style.header_background_color,
                "header_font": font_style_to_dict(table_style.header_font) if table_style.header_font else None,
                "body_font": font_style_to_dict(table_style.body_font) if table_style.body_font else None,
                "banding": table_style.banding,
                "banding_color": table_style.banding_color
            }
        
        # Helper function to convert ListStyle to dict
        def list_style_to_dict(list_style):
            return {
                "list_type": list_style.list_type,
                "bullet_char": list_style.bullet_char,
                "numbering_format": list_style.numbering_format,
                "indent_level": list_style.indent_level,
                "indent_hanging": list_style.indent_hanging,
                "space_before": list_style.space_before,
                "space_after": list_style.space_after
            }
        
        # Helper function to convert ImageStyle to dict
        def image_style_to_dict(image_style):
            return {
                "width": image_style.width,
                "height": image_style.height,
                "alignment": image_style.alignment,
                "wrap_text": image_style.wrap_text,
                "position_x": image_style.position_x,
                "position_y": image_style.position_y
            }
        
        # Helper function to convert ParagraphStyle to dict
        def paragraph_style_to_dict(para_style):
            return {
                "alignment": para_style.alignment,
                "line_spacing": para_style.line_spacing,
                "space_before": para_style.space_before,
                "space_after": para_style.space_after,
                "indent_left": para_style.indent_left,
                "indent_right": para_style.indent_right,
                "indent_first_line": para_style.indent_first_line,
                "keep_with_next": para_style.keep_with_next,
                "page_break_before": para_style.page_break_before,
                "widow_control": para_style.widow_control,
                "shading_color": para_style.shading_color
            }
        
        # Convert list styles dict to serializable format
        list_styles_serializable = {}
        for key, value in profile.list_styles.items():
            list_styles_serializable[key] = list_style_to_dict(value)
        
        # Convert image styles list to serializable format
        image_styles_serializable = [image_style_to_dict(img) for img in profile.image_styles]
        
        return {
            "template_name": profile.template_name,
            "template_path": profile.template_path,
            "margins": {
                "left": profile.margin_left,
                "right": profile.margin_right,
                "top": profile.margin_top,
                "bottom": profile.margin_bottom
            },
            "fonts": {
                "title": font_style_to_dict(profile.title_font),
                "heading": font_style_to_dict(profile.heading_font),
                "body": font_style_to_dict(profile.body_font)
            },
            "paragraph_style": paragraph_style_to_dict(profile.paragraph_style),
            "table_style": table_style_to_dict(profile.table_style),
            "list_styles": list_styles_serializable,
            "image_styles": image_styles_serializable,
            "logo_style": image_style_to_dict(profile.logo_style) if profile.logo_style else None,
            "logo_path": profile.logo_path,
            "page": {
                "width": profile.page_width,
                "height": profile.page_height,
                "orientation": profile.orientation
            },
            "header_content": profile.header_content,
            "footer_content": profile.footer_content,
            "has_page_numbers": profile.has_page_numbers,
            "color_scheme": profile.color_scheme,
            "implied_rules": profile.implied_rules,
            "template_insights": profile.template_insights,
            "custom_styles_count": len(profile.custom_styles) if profile.custom_styles else 0
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


@app.get("/debug/anthropic")
def debug_anthropic():
    """Return installed Anthropic package version and whether the client exposes the Files API.

    Does not return secrets. Useful for verifying runtime matches `requirements.txt`.
    """
    try:
        import anthropic
    except Exception as e:
        return {"installed": False, "error": str(e)}

    ver = getattr(anthropic, "__version__", None)
    client_has_files = None
    detected_key = None

    try:
        if os.getenv("CLAUDE_API_KEY"):
            detected_key = "CLAUDE_API_KEY"
        elif os.getenv("ANTHROPIC_API_KEY"):
            detected_key = "ANTHROPIC_API_KEY"

        # Try to construct a client if a key is present; do not log the key value
        if detected_key:
            client_cls = getattr(anthropic, "Anthropic", None) or getattr(anthropic, "Client", None)
            if client_cls is not None:
                try:
                    client = client_cls(api_key=os.getenv(detected_key))
                    client_has_files = (
                        hasattr(client, "files")
                        or (hasattr(client, "beta") and hasattr(client.beta, "files"))
                    )
                except Exception:
                    client_has_files = False
    except Exception:
        client_has_files = False

    return {"installed": True, "version": ver, "client_has_files": client_has_files, "detected_key": detected_key}


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
def process_endpoint(generation_mode: str = Form("apply")):
    """
    Start processing with the active template.
    
    Args:
        generation_mode: "apply" to apply styles to new document, "modify" to modify template in-place
    """
    # Validate generation_mode
    if generation_mode not in ["apply", "modify"]:
        raise HTTPException(status_code=400, detail="generation_mode must be 'apply' or 'modify'")
    
    # Store generation_mode in process status
    _update_status(generation_mode=generation_mode)
    
    started = _start_background_process()
    if not started:
        return {
            "success": True,
            "message": "Processing is already running.",
            "running": True,
        }

    return {
        "success": True,
        "message": f"Processing started in the background with generation_mode='{generation_mode}'.",
        "running": True,
        "generation_mode": generation_mode,
        "status_url": "/process/status",
        "aggregated_url": "/aggregated",
        "artifact_list_url": "/artifacts",
        "artifact_template": "/artifact/{filename}",
    }


@app.post("/process_with_claude")
async def process_with_claude(
    template_file: UploadFile = File(None),
    department_docs: List[UploadFile] = File(...),
    mode: str = Form("structure_and_branding"),
):
    """Process documents end-to-end using the Claude pipeline.

    - `template_file` is optional; if omitted, the active template will be used.
    - `department_docs` is a list of uploaded department files.
    - `mode` controls template usage: structure_only, structure_and_branding, branding_only
    """
    if mode not in ["structure_only", "structure_and_branding", "branding_only"]:
        raise HTTPException(status_code=400, detail="mode must be one of: structure_only, structure_and_branding, branding_only")

    try:
        import anthropic
        print("ANTHROPIC VERSION AT RUNTIME:", getattr(anthropic, "__version__", None))
        print("PYTHON:", sys.executable)
        client_cls = getattr(anthropic, "Anthropic", None) or getattr(anthropic, "Client", None)
        has_beta_files = False
        if client_cls is not None:
            try:
                client_test = client_cls(api_key=os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))
                has_beta_files = hasattr(client_test, "beta") and hasattr(client_test.beta, "files")
            except Exception:
                has_beta_files = False
        print("HAS beta.files.upload:", has_beta_files)

        pipeline = ClaudePipeline()

        # Read template if provided
        template_profile = None
        template_bytes = None
        template_name = None
        template_analysis = {"structure": {}, "branding": {}}
        
        if template_file:
            template_bytes = await template_file.read()
            template_name = template_file.filename
            template_filename = template_name or "template"
            if not Path(template_filename).suffix:
                template_filename += ".pdf" if template_file.content_type and "pdf" in template_file.content_type.lower() else ".docx"
            saved_template_path = TEMPLATES_DIR / f"{uuid.uuid4().hex}_{template_filename}"
            with open(saved_template_path, "wb") as f:
                f.write(template_bytes)
            template_profile = template_manager.register_template(str(saved_template_path), Path(template_filename).stem)
            template_analysis = pipeline.analyze_template(template_bytes, template_name, mode=mode)
        else:
            # Use active template if any
            active = PROCESS_STATUS.get("active_template")
            template_profile = template_manager.get_template_or_default(active)
            if active and template_profile:
                template_analysis = {
                    "structure": {},
                    "branding": {
                        "template_name": template_profile.template_name,
                        "header_text": template_profile.header_content,
                        "footer_text": template_profile.footer_content,
                        "logo_path": template_profile.logo_path,
                    },
                }

        branding = template_analysis.setdefault("branding", {})
        if template_profile:
            branding.setdefault("header_text", template_profile.header_content)
            branding.setdefault("letterhead", template_profile.header_content)
            branding.setdefault("footer_text", template_profile.footer_content)
            branding.setdefault("logo_path", template_profile.logo_path)

        # Read department docs
        dept_bytes = []
        filenames = []
        for f in department_docs:
            b = await f.read()
            dept_bytes.append(b)
            filenames.append(f.filename)

        extraction = pipeline.extract_and_interpret(
            dept_bytes,
            filenames,
            template_structure=template_analysis.get("structure"),
            template_branding=template_analysis.get("branding"),
        )

        # Build a single record or list to aggregate
        records = []
        if isinstance(extraction, dict) and extraction.get("department"):
            records.append(extraction)
        elif isinstance(extraction, list):
            records.extend(extraction)
        else:
            records.append({"department": "Unknown", "metrics": extraction.get("metrics") if isinstance(extraction, dict) else {}})

        aggregated = aggregate_records(records)
        status, issues = run_compliance_checks(aggregated)

        # Create summary charts and a simple HTML narrative using Claude's interpretation if present
        output_dir = OUTPUT_DIR
        charts = create_summary_charts(aggregated, output_dir, template_profile=template_profile, template_analysis=template_analysis)

        narrative = extraction.get("narrative") if isinstance(extraction, dict) else ""
        # Ensure narrative is always a string to avoid NoneType.replace errors
        if narrative is None:
            narrative = ""
        html_path = generate_html_report(
            aggregated,
            status,
            issues,
            charts,
            narrative,
            output_dir,
            template_profile=template_profile,
            template_analysis=template_analysis,
        )

        # Save aggregated data
        with open(output_dir / "aggregated_data.json", "w", encoding="utf-8") as f:
            json.dump(aggregated, f, indent=2)

        return {
            "success": True,
            "aggregated": aggregated,
            "compliance_status": status,
            "issues": issues,
            "report_path": str(html_path),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude processing failed: {e}")


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


def _artifact_type_from_suffix(suffix: str) -> str:
    ext = (suffix or "").lower()
    if ext == ".pdf":
        return "pdf"
    if ext in {".html", ".htm"}:
        return "html"
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".svg"}:
        return "image"
    if ext in {".docx", ".doc", ".txt"}:
        return "document"
    if ext == ".json":
        return "json"
    return "unknown"


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


@app.get("/artifacts")
def list_artifacts():
    files = []
    if OUTPUT_DIR.exists():
        for f in sorted(OUTPUT_DIR.iterdir()):
            if f.is_file():
                download_url = f"/artifact/{quote(f.name)}"
                files.append({
                    "name": f.name,
                    "filename": f.name,
                    "label": f.name,
                    "url": download_url,
                    "download_url": download_url,
                    "suffix": f.suffix,
                    "type": _artifact_type_from_suffix(f.suffix),
                    "size": f.stat().st_size,
                    "is_assessment": f.name.startswith("Assessment_Page"),
                })
    return {
        "output_path": str(OUTPUT_DIR),
        "artifacts": files,
        "assessment_html": next((f"/artifact/{quote(f['name'])}" for f in files if f['name'] == 'Assessment_Page.html'), None),
        "assessment_pdf": next((f"/artifact/{quote(f['name'])}" for f in files if f['name'] == 'Assessment_Page.pdf'), None),
    }
