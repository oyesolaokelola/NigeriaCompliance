# workflow/aggregation.py
from collections import Counter
from typing import List, Dict, Any, Optional


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def aggregate_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    combined: Dict[str, Any] = {
        "period": "Unknown",
        "metrics": {},
        "departmental": {},
        "notes": [],
    }

    periods: List[str] = []

    for rec in records:
        dept = rec.get("department") or "Other"
        period = rec.get("period")
        if period and period != "Unknown":
            periods.append(period)

        dept_bucket = combined["departmental"].setdefault(
            dept,
            {
                "department": dept,
                "period": period or "Unknown",
                "metrics": {},
                "notes": [],
                "source_paths": [],
            },
        )

        source_path = rec.get("source_path")
        if source_path:
            dept_bucket["source_paths"].append(source_path)

        notes = rec.get("notes", []) or []
        dept_bucket["notes"].extend(notes)
        combined["notes"].extend(notes)

        for key, value in (rec.get("metrics") or {}).items():
            number = _to_number(value)
            if number is None:
                continue
            combined["metrics"][key] = combined["metrics"].get(key, 0.0) + number
            dept_bucket["metrics"][key] = dept_bucket["metrics"].get(key, 0.0) + number

    if periods:
        combined["period"] = Counter(periods).most_common(1)[0][0]

    return combined