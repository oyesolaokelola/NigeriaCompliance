# workflow/reporting.py
from pathlib import Path
from typing import Dict, Any, List, Optional

import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def create_summary_charts(aggregated: Dict[str, Any], output_dir: Path) -> Dict[str, Path]:
    charts: Dict[str, Path] = {}

    m = aggregated["metrics"]

    rev = m.get("revenue")
    payroll = m.get("total_payroll")
    if rev and payroll:
        chart_path = output_dir / "Summary_Revenue_vs_Payroll.png"
        plt.figure(figsize=(4, 3))
        plt.bar(["Revenue", "Payroll"], [rev, payroll])
        plt.ylabel("Amount")
        plt.title("Revenue vs Payroll")
        plt.tight_layout()
        plt.savefig(chart_path, dpi=150)
        plt.close()
        charts["revenue_vs_payroll"] = chart_path

    vendor_spend = m.get("total_vendor_spend")
    if vendor_spend:
        chart_path = output_dir / "Summary_Vendor_Spend.png"
        plt.figure(figsize=(4, 3))
        plt.bar(["Vendor Spend"], [vendor_spend])
        plt.ylabel("Amount")
        plt.title("Total Vendor Spend")
        plt.tight_layout()
        plt.savefig(chart_path, dpi=150)
        plt.close()
        charts["vendor_spend"] = chart_path

    return charts


def generate_html_report(
    aggregated: Dict[str, Any],
    status: str,
    issues: List[str],
    charts: Dict[str, Path],
    narrative: str,
    output_dir: Path,
) -> Path:
    path = output_dir / "Financial_Compliance_Report_Q1_2025.html"

    finance = aggregated["departmental"].get("Finance", {}).get("metrics", {})
    procurement = aggregated["departmental"].get("Procurement", {}).get("metrics", {})
    hr = aggregated["departmental"].get("HR", {}).get("metrics", {})
    ops = aggregated["departmental"].get("Operations", {}).get("metrics", {})

    def img_tag(p: Optional[Path]) -> str:
        return f'<img src="{p.name}" alt="{p.name}" style="max-width:400px;">' if p else ""

    with open(path, "w", encoding="utf-8") as f:
        f.write("<html><head><title>Financial Compliance Report Q1 2025</title></head><body>")
        f.write("<h1>Northbridge Holdings Ltd</h1>")
        f.write("<h2>Financial Compliance Report – Q1 2025</h2>")

        f.write("<h3>Section 1: Executive Summary</h3>")
        f.write(f"<p><strong>Compliance Status:</strong> {status}</p>")
        f.write(f"<p>{narrative.replace(chr(10), '<br>')}</p>")

        f.write("<h3>Section 2: Key Metrics (Tables)</h3>")

        def write_table(title: str, metrics: Dict[str, Any]):
            f.write(f"<h4>{title}</h4>")
            f.write("<table border='1' cellpadding='4'><tr><th>Metric</th><th>Value</th></tr>")
            for k, v in metrics.items():
                if isinstance(v, (int, float)):
                    val = f"{v:,}"
                else:
                    val = str(v)
                f.write(f"<tr><td>{k}</td><td>{val}</td></tr>")
            f.write("</table>")

        write_table("Finance", finance)
        write_table("Procurement", procurement)
        write_table("HR", hr)
        write_table("Operations", ops)

        f.write("<h3>Section 3: Compliance Issues</h3>")
        if not issues:
            f.write("<p>No issues detected.</p>")
        else:
            f.write("<ul>")
            for issue in issues:
                f.write(f"<li>{issue}</li>")
            f.write("</ul>")

        f.write("<h3>Section 4: Visual Summaries (Graphs)</h3>")
        f.write("<div>")
        f.write(img_tag(charts.get("revenue_vs_payroll")))
        f.write(img_tag(charts.get("vendor_spend")))
        f.write("</div>")

        f.write("<h3>Section 5: Notes</h3>")
        f.write("<ul>")
        for note in aggregated["notes"]:
            f.write(f"<li>{note}</li>")
        f.write("</ul>")

        f.write("</body></html>")

    return path


def generate_pdf_report(
    aggregated: Dict[str, Any],
    status: str,
    issues: List[str],
    charts: Dict[str, Path],
    narrative: str,
    output_dir: Path,
) -> Path:
    """
    PDF template version of the same report structure.
    Not a full HTML renderer, but aligned sections.
    """
    path = output_dir / "Financial_Compliance_Report_Q1_2025.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4

    y = height - 40
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "Northbridge Holdings Ltd")
    y -= 24
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Financial Compliance Report – Q1 2025")
    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, f"Compliance Status: {status}")
    y -= 20

    c.setFont("Helvetica", 10)
    for line in narrative.splitlines():
        c.drawString(50, y, line[:110])
        y -= 14
        if y < 80:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 10)

    # New page for charts and issues
    c.showPage()
    y = height - 50
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Compliance Issues")
    y -= 20
    c.setFont("Helvetica", 10)
    if not issues:
        c.drawString(50, y, "No issues detected.")
        y -= 14
    else:
        for issue in issues:
            c.drawString(50, y, f"- {issue[:110]}")
            y -= 14
            if y < 80:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 10)

    # Charts
    c.showPage()
    y = height - 50
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Visual Summaries")
    y -= 20

    for key in ["revenue_vs_payroll", "vendor_spend"]:
        chart_path = charts.get(key)
        if chart_path and chart_path.exists():
            c.drawImage(str(chart_path), 50, y - 220, width=300, preserveAspectRatio=True, mask="auto")
            y -= 240
            if y < 100:
                c.showPage()
                y = height - 50

    c.showPage()
    c.save()
    return path