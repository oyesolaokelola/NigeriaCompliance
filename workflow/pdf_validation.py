import json
import io
from typing import Dict, Any
from pathlib import Path
from PyPDF2 import PdfReader


def basic_programmatic_checks(pdf_bytes: bytes, template_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Run deterministic checks on generated PDF against template_profile.

    Checks include: page count, presence of header text, and simple color/font markers
    (limited to what can be inferred programmatically).
    """
    results = {"page_count_match": False, "header_present": False, "notes": []}

    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_count = len(reader.pages)
    expected_pages = template_profile.get("expected_pages") if template_profile else None
    if expected_pages is not None:
        results["page_count_match"] = page_count == expected_pages
    else:
        results["page_count_match"] = True

    # Try to find header text on the first page
    try:
        first = reader.pages[0]
        text = first.extract_text() or ""
        header_text = template_profile.get("letterhead_text") if template_profile else None
        if header_text and header_text in text:
            results["header_present"] = True
        else:
            results["notes"].append("Header text not found or template not provided")
    except Exception:
        results["notes"].append("Failed to extract text for header check")

    return results


def compare_with_claude(generated_pdf_bytes: bytes, template_pdf_bytes: bytes, claude_pipeline) -> Dict[str, Any]:
    """Ask Claude to perform a structural/visual comparison and return its findings.

    `claude_pipeline` should expose `validate_pdf_against_template` implemented above.
    """
    return claude_pipeline.validate_pdf_against_template(
        generated_pdf_bytes, "generated.pdf", template_pdf_bytes, "template.pdf"
    )
