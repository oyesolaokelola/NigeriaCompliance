# workflow/run_workflow.py
import json
import logging
import runpy
from pathlib import Path
from typing import Optional, Set

from .ingestion import discover_files
from .extraction import extract_record
from .aggregation import aggregate_records
from .compliance import run_compliance_checks
from .genai_agents import interpretation_agent, risk_analysis_agent, report_writer_agent
from .reporting import create_summary_charts, generate_html_report, generate_pdf_report
from .template_styling import TemplateManager, StyleApplier

logger = logging.getLogger(__name__)

PROCESSED_FILES_NAME = ".processed_files.json"


def _load_processed_files(processed_file_path: Path) -> Set[str]:
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


def _save_processed_files(processed_file_path: Path, processed_files: Set[str]):
    with open(processed_file_path, "w", encoding="utf-8") as f:
        json.dump({"processed_files": sorted(processed_files)}, f, indent=2)


def _relative_repo_path(path: Path, repo_dir_path: Path) -> str:
    return str(path.relative_to(repo_dir_path).as_posix())


def process_repository(base_dir: Optional[str] = None, repo_dir: Optional[str] = None, output_dir: Optional[str] = None, template_name: Optional[str] = None):
    """
    Process documents in a repository and return results as a dict.
    This is a programmatic entrypoint intended for API/POC use.
    
    Args:
        base_dir: Base directory (defaults to project root)
        repo_dir: Repository directory with documents (defaults to base_dir/repository)
        output_dir: Output directory for results (defaults to base_dir/output)
        template_name: Optional template name for styling output documents
    """
    base_dir_path = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    repo_dir_path = Path(repo_dir) if repo_dir else base_dir_path / "repository"
    output_dir_path = Path(output_dir) if output_dir else base_dir_path / "output"
    output_dir_path.mkdir(exist_ok=True, parents=True)
    
    # Initialize template manager if template requested
    template_profile = None
    if template_name:
        templates_dir = base_dir_path / "templates"
        template_manager = TemplateManager(templates_dir)
        template_profile = template_manager.get_template_profile(template_name)
        if template_profile:
            logger.info(f"Using template: {template_name}")
        else:
            logger.warning(f"Template '{template_name}' not found, proceeding without template styling")

    processed_file_path = output_dir_path / PROCESSED_FILES_NAME
    processed_paths = _load_processed_files(processed_file_path)

    files = discover_files(repo_dir_path)
    if not files:
        generator_path = base_dir_path / "generate_sample_documents.py"
        if generator_path.exists():
            try:
                runpy.run_path(str(generator_path), run_name="__main__")
                files = discover_files(repo_dir_path)
            except Exception as exc:
                print(f"Sample document generation failed: {exc}")

    unprocessed_files = []
    for fi in files:
        try:
            rel_path = _relative_repo_path(fi["path"], repo_dir_path)
        except Exception:
            continue
        if rel_path not in processed_paths:
            unprocessed_files.append(fi)

    if not unprocessed_files:
        raise RuntimeError(
            "No new input files found since the last processing run. "
            "Upload new documents under repository/<department>/ to process only fresh files."
        )

    records = []
    files = unprocessed_files

    for index, fi in enumerate(files, start=1):
        dept = fi.get("department") or "Unknown"
        path = fi.get("path")
        logger.debug("Processing file %d/%d: department=%s file=%s", index, len(files), dept, path)

        logger.debug("Stage: extraction")
        raw_doc = extract_record(fi)
        if not raw_doc:
            logger.warning("Skipping file because extraction returned no data: %s", path)
            continue

        logger.debug("Stage: interpretation")
        try:
            interp = interpretation_agent(raw_doc)
        except Exception as exc:
            logger.warning("Interpretation agent failed for %s: %s", path, exc)
            interp = {
                "department": "Other",
                "period": None,
                "metrics": {},
                "notes": [f"interpretation failed: {exc}"],
                "missing_fields": [],
                "confidence": None,
            }

        conf_val = interp.get("confidence", None)
        conf_display = conf_val if conf_val is not None else "N/A"
        logger.debug(
            "Interpretation complete: department=%s period=%s confidence=%s",
            interp.get('department', 'Other'),
            interp.get('period', 'Unknown'),
            conf_display,
        )

        record = {
            "period": interp.get("period") or "Unknown",
            "department": interp.get("department") or "Other",
            "metrics": interp.get("metrics") or {},
            "notes": interp.get("notes") or [],
            "missing_fields": interp.get("missing_fields") or [],
            "confidence": interp.get("confidence", None),
            "source_path": raw_doc.get("source_path"),
            "file_type": raw_doc.get("file_type"),
        }
        records.append(record)
        processed_paths.add(_relative_repo_path(path, repo_dir_path))
        _save_processed_files(processed_file_path, processed_paths)

    aggregated = aggregate_records(records)

    # Deterministic compliance checks
    status, issues = run_compliance_checks(aggregated)

    # Agent 2: risk analysis
    risk_narrative = risk_analysis_agent(aggregated, issues)

    # Agent 3: executive summary
    narrative = report_writer_agent(aggregated, status, risk_narrative)

    # Charts
    charts = create_summary_charts(aggregated, output_dir_path)

    # Save aggregated JSON
    aggregated_json_path = output_dir_path / "aggregated_data.json"
    with open(aggregated_json_path, "w", encoding="utf-8") as f:
        json.dump(aggregated, f, indent=2)

    # Reports - with optional template styling
    html_path = generate_html_report(aggregated, status, issues, charts, narrative, output_dir_path)
    pdf_path = generate_pdf_report(aggregated, status, issues, charts, narrative, output_dir_path, template_profile)

    result = {
        "aggregated": aggregated,
        "status": status,
        "issues": issues,
        "risk_narrative": risk_narrative,
        "narrative": narrative,
        "charts": {k: str(v) for k, v in charts.items()},
        "aggregated_json": str(aggregated_json_path),
        "html_report": str(html_path),
        "pdf_report": str(pdf_path),
        "template_used": template_name,
    }
    return result


def main():
    res = process_repository()
    print(f"HTML report: {res.get('html_report')}")
    print(f"PDF report:  {res.get('pdf_report')}")


if __name__ == "__main__":
    main()