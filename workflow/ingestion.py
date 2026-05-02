# workflow/ingestion.py
from pathlib import Path
from typing import List, Dict, Any


def discover_files(repo_dir: Path) -> List[Dict[str, Any]]:
    files = []
    for dept in ["finance", "procurement", "hr", "operations"]:
        dept_dir = repo_dir / dept
        if not dept_dir.exists():
            continue
        for f in dept_dir.iterdir():
            if f.is_file():
                files.append({"department": dept.capitalize(), "path": f})
    return files