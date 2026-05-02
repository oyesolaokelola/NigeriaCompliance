# workflow/extraction.py
from pathlib import Path
from typing import Dict, Any, Optional, List

import pandas as pd
from docx import Document
import pytesseract
from PIL import Image


def _safe_ocr_image(img: Image.Image) -> str:
    try:
        return pytesseract.image_to_string(img)
    except Exception:
        return ""


def extract_word(path: Path) -> Dict[str, Any]:
    doc = Document(path)
    text_lines = [p.text for p in doc.paragraphs]
    text = "\n".join(text_lines)
    tables: List[List[List[str]]] = []

    for t in doc.tables:
        table_data = []
        for row in t.rows:
            table_data.append([cell.text for cell in row.cells])
        tables.append(table_data)

    return {
        "raw_text": text,
        "raw_tables": tables,
        "source_path": str(path),
        "file_type": "docx",
    }


def extract_excel(path: Path) -> Dict[str, Any]:
    xls = pd.ExcelFile(path)
    tables = {}
    for sheet in xls.sheet_names:
        df = xls.parse(sheet)
        tables[sheet] = df.to_dict(orient="records")

    return {
        "raw_text": "",
        "raw_tables": tables,
        "source_path": str(path),
        "file_type": "xlsx",
    }


def extract_csv(path: Path) -> Dict[str, Any]:
    df = pd.read_csv(path)
    return {
        "raw_text": "",
        "raw_tables": {"csv": df.to_dict(orient="records")},
        "source_path": str(path),
        "file_type": "csv",
    }


def extract_text_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "raw_text": text,
        "raw_tables": [],
        "source_path": str(path),
        "file_type": "txt",
    }


def extract_pdf(path: Path) -> Dict[str, Any]:
    text_chunks = []
    tables: List[List[List[str]]] = []
    text_chars = 0

    # Primary method: use pdfplumber (best for text + tables + page images).
    # If pdfplumber import or usage fails (e.g., incompatible native dependencies),
    # fall back to PyPDF2 for text-only extraction.
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_chunks.append(t)
                text_chars += len(t)
                try:
                    page_tables = page.extract_tables() or []
                    for tbl in page_tables:
                        tables.append(tbl)
                except Exception:
                    pass
    except Exception:
        # Fallback: try PyPDF2 for basic text extraction (no table extraction).
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(str(path))
            for page in reader.pages:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                text_chunks.append(t)
                text_chars += len(t)
        except Exception:
            # Last-resort: leave text empty (OCR fallback below may also be skipped
            # if pdfplumber is not available to render page images).
            pass

    text = "\n".join(text_chunks)

    # If almost no text was extracted, try OCR via pdfplumber page images (only
    # possible when pdfplumber is available). If pdfplumber is not available,
    # we skip OCR fallback to avoid adding heavy native deps.
    if text_chars < 50:
        try:
            import pdfplumber

            images_text = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    pil_img = page.to_image(resolution=300).original
                    ocr_text = _safe_ocr_image(pil_img)
                    images_text.append(ocr_text)
            text = "\n".join(images_text)
        except Exception:
            pass

    return {
        "raw_text": text,
        "raw_tables": tables,
        "source_path": str(path),
        "file_type": "pdf",
    }


def extract_image(path: Path) -> Dict[str, Any]:
    img = Image.open(path)
    text = _safe_ocr_image(img)
    return {
        "raw_text": text,
        "raw_tables": [],
        "source_path": str(path),
        "file_type": "image",
    }


def extract_record(file_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    path = file_info["path"]
    suffix = path.suffix.lower()

    if suffix == ".docx":
        base = extract_word(path)
    elif suffix in [".xlsx", ".xls"]:
        base = extract_excel(path)
    elif suffix == ".pdf":
        base = extract_pdf(path)
    elif suffix == ".csv":
        base = extract_csv(path)
    elif suffix == ".txt":
        base = extract_text_file(path)
    elif suffix in [".png", ".jpg", ".jpeg"]:
        base = extract_image(path)
    else:
        return None

    # Minimal envelope; GenAI will classify department/period
    base.update(
        {
            "department": None,
            "period": None,
            "metrics": {},
            "notes": [],
        }
    )
    return base