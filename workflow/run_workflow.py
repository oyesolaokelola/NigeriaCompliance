# workflow/run_workflow.py
import json
import runpy
from pathlib import Path
from typing import Optional

from ingestion import discover_files
from extraction import extract_record
from aggregation import aggregate_records
from compliance import run_compliance_checks
from genai_agents import interpretation_agent, risk_analysis_agent, report_writer_agent
from reporting import create_summary_charts, generate_html_report, generate_pdf_report


def process_repository(base_dir: Optional[str] = None, repo_dir: Optional[str] = None, output_dir: Optional[str] = None):
    """
    Process documents in a repository and return results as a dict.
    This is a programmatic entrypoint intended for API/POC use.
    """
    base_dir_path = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    repo_dir_path = Path(repo_dir) if repo_dir else base_dir_path / "repository"
    output_dir_path = Path(output_dir) if output_dir else base_dir_path / "output"
    output_dir_path.mkdir(exist_ok=True, parents=True)

    files = discover_files(repo_dir_path)
    if not files:
        generator_path = base_dir_path / "generate_sample_documents.py"
        if generator_path.exists():
            try:
                runpy.run_path(str(generator_path), run_name="__main__")
                files = discover_files(repo_dir_path)
            except Exception as exc:
                print(f"Sample document generation failed: {exc}")

    if not files:
        raise RuntimeError(
            "No input files found in repository folders. "
            "Add source documents under repository/<department>/ or fix sample generation."
        )

    records = []

    for index, fi in enumerate(files, start=1):
        dept = fi.get("department") or "Unknown"
        path = fi.get("path")
        print(f"\nProcessing file {index}/{len(files)}: department={dept} file={path}")

        print("  Stage: extraction")
        raw_doc = extract_record(fi)
        if not raw_doc:
            print("  Skipping file: extraction returned no data")
            continue

        print("  Stage: interpretation")
        try:
            interp = interpretation_agent(raw_doc)
        except Exception as exc:
            print(f"  Interpretation agent failed: {exc}")
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
        print(
            f"  Interpretation complete: department={interp.get('department', 'Other')} "
            f"period={interp.get('period', 'Unknown')} confidence={conf_display}"
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

    # Reports
    html_path = generate_html_report(aggregated, status, issues, charts, narrative, output_dir_path)
    pdf_path = generate_pdf_report(aggregated, status, issues, charts, narrative, output_dir_path)

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
    }
    return result


def main():
    res = process_repository()
    print(f"HTML report: {res.get('html_report')}")
    print(f"PDF report:  {res.get('pdf_report')}")


if __name__ == "__main__":
    main()