# workflow/compliance.py
from typing import Dict, Any, List, Tuple


def run_compliance_checks(aggregated: Dict[str, Any]) -> Tuple[str, List[str]]:
    issues: List[str] = []
    m = aggregated["metrics"]

    revenue = m.get("revenue") or m.get("total_revenue")
    payroll = m.get("total_payroll") or m.get("payroll")
    if revenue and payroll:
        ratio = payroll / revenue
        if ratio > 0.6:
            issues.append(f"Payroll to revenue ratio too high: {ratio:.2%}")

    net = m.get("net_amount") or m.get("taxable_amount") or m.get("net_profit")
    vat = m.get("vat_amount") or m.get("vat") or m.get("vat_total")
    if net and vat:
        expected_vat = net * 0.20
        if abs(vat - expected_vat) > 1:
            issues.append(f"VAT mismatch on operations invoice. Expected {expected_vat}, got {vat}")

    hr_vendor_count = m.get("high_risk_vendor_count", 0)
    if hr_vendor_count > 0:
        issues.append(f"{hr_vendor_count} high-risk vendors detected in procurement.")

    status = "Compliant" if not issues else "Non-Compliant"
    return status, issues