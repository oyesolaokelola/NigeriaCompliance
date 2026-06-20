# workflow/reporting.py
from pathlib import Path
from typing import Dict, Any, List, Optional
import shutil
import textwrap

import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4, letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor


def create_summary_charts(aggregated: Dict[str, Any], output_dir: Path, template_profile: Optional[Any] = None) -> Dict[str, Path]:
    charts: Dict[str, Path] = {}

    m = aggregated["metrics"]

    rev = m.get("revenue")
    payroll = m.get("total_payroll")
    # Apply template styling to matplotlib if provided
    title_color = "#222222"
    label_color = "#333333"
    if template_profile:
        try:
            import matplotlib
            # Font
            if template_profile.body_font and getattr(template_profile.body_font, "name", None):
                matplotlib.rcParams["font.family"] = template_profile.body_font.name
            # Colors
            if getattr(template_profile, "color_scheme", None):
                color_primary = template_profile.color_scheme.get("primary")
                color_secondary = template_profile.color_scheme.get("secondary")
                title_color = f"#{color_primary}" if color_primary else title_color
                label_color = f"#{color_secondary}" if color_secondary else label_color
            bar_color = title_color
        except Exception:
            bar_color = None
    else:
        bar_color = None

    if rev and payroll:
        chart_path = output_dir / "Summary_Revenue_vs_Payroll.png"
        fig, ax = plt.subplots(figsize=(4, 3))
        colors = [bar_color or "#4C72B0", bar_color or "#55A868"]
        ax.bar(["Revenue", "Payroll"], [rev, payroll], color=colors)
        ax.set_ylabel("Amount", color=label_color)
        ax.set_title("Revenue vs Payroll", color=title_color)
        ax.tick_params(colors=label_color)
        for spine in ax.spines.values():
            spine.set_edgecolor(label_color)
        fig.tight_layout()
        fig.savefig(chart_path, dpi=150)
        plt.close(fig)
        charts["revenue_vs_payroll"] = chart_path

    vendor_spend = m.get("total_vendor_spend")
    if vendor_spend:
        chart_path = output_dir / "Summary_Vendor_Spend.png"
        fig, ax = plt.subplots(figsize=(4, 3))
        ax.bar(["Vendor Spend"], [vendor_spend], color=bar_color or "#DD8452")
        ax.set_ylabel("Amount", color=label_color)
        ax.set_title("Total Vendor Spend", color=title_color)
        ax.tick_params(colors=label_color)
        for spine in ax.spines.values():
            spine.set_edgecolor(label_color)
        fig.tight_layout()
        fig.savefig(chart_path, dpi=150)
        plt.close(fig)
        charts["vendor_spend"] = chart_path

    return charts


def generate_html_report(
    aggregated: Dict[str, Any],
    status: str,
    issues: List[str],
    charts: Dict[str, Path],
    narrative: str,
    output_dir: Path,
    template_profile: Optional[Any] = None,
) -> Path:
    path = output_dir / "Financial_Compliance_Report_Q1_2025.html"

    font_family = "Arial, sans-serif"
    title_font_family = "Arial, sans-serif"
    heading_font_family = "Arial, sans-serif"
    title_color = "#000000"
    heading_color = "#333333"
    body_color = "#000000"
    logo_src = None

    if template_profile:
        if template_profile.body_font and template_profile.body_font.name:
            font_family = template_profile.body_font.name
        if template_profile.color_scheme:
            title_color = f"#{template_profile.color_scheme.get('primary', '000000')}"
            heading_color = f"#{template_profile.color_scheme.get('secondary', '333333')}"
            body_color = f"#{template_profile.color_scheme.get('body', '000000')}"
        if template_profile.logo_path:
            logo_path = Path(template_profile.logo_path)
            if logo_path.exists():
                dest_logo = output_dir / logo_path.name
                shutil.copy(logo_path, dest_logo)
                logo_src = dest_logo.name

    finance = aggregated["departmental"].get("Finance", {}).get("metrics", {})
    procurement = aggregated["departmental"].get("Procurement", {}).get("metrics", {})
    hr = aggregated["departmental"].get("HR", {}).get("metrics", {})
    ops = aggregated["departmental"].get("Operations", {}).get("metrics", {})

    def img_tag(p: Optional[Path]) -> str:
        return f'<img src="{p.name}" alt="{p.name}" style="max-width:400px;">' if p else ""

    with open(path, "w", encoding="utf-8") as f:
        f.write("<html><head><title>Financial Compliance Report Q1 2025</title>")
        f.write("<style>")
        f.write("body { font-family: %s; color: %s; padding: 24px; line-height: 1.5; }" % (font_family, body_color))
        f.write("h1 { font-family: %s; font-size: 2.2em; color: %s; margin-bottom: 0.2em; }" % (title_font_family, title_color))
        f.write("h2 { font-family: %s; font-size: 1.5em; color: %s; margin-top: 1.2em; }" % (heading_font_family, heading_color))
        f.write("h3, h4 { font-family: %s; color: %s; margin-top: 1.2em; }" % (heading_font_family, heading_color))
        f.write("table { border-collapse: collapse; width: 100%; margin-bottom: 16px; }")
        f.write("table td, table th { border: 1px solid #ccc; padding: 8px; }")
        f.write("img.logo { max-width: 200px; margin-bottom: 16px; }")
        f.write(".report-header { margin-bottom: 16px; color: %s; }" % body_color)
        f.write(".report-footer { margin-top: 40px; padding-top: 12px; border-top: 1px solid #ddd; color: %s; font-size: 0.9em; }" % body_color)
        f.write("</style></head><body>")
        if logo_src:
            f.write(f'<img class="logo" src="{logo_src}" alt="Logo">')
        if template_profile and getattr(template_profile, 'header_content', None):
            f.write(f'<div class="report-header">{template_profile.header_content}</div>')
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
        if template_profile and getattr(template_profile, 'footer_content', None):
            f.write(f'<div class="report-footer">{template_profile.footer_content}</div>')
        f.write("</body></html>")

    return path


def generate_pdf_report(
    aggregated: Dict[str, Any],
    status: str,
    issues: List[str],
    charts: Dict[str, Path],
    narrative: str,
    output_dir: Path,
    template_profile: Optional[Any] = None,
) -> Path:
    """
    PDF template version of the same report structure with optional custom styling.
    
    Args:
        aggregated: Aggregated data
        status: Compliance status
        issues: List of compliance issues
        charts: Dictionary of chart paths
        narrative: Narrative text
        output_dir: Output directory
        template_profile: Optional TemplateProfile for custom styling
    """
    path = output_dir / "Financial_Compliance_Report_Q1_2025.pdf"
    
    # Determine page size and margins from template or use defaults
    pagesize = A4
    if template_profile:
        if template_profile.page_width > 0 and template_profile.page_height > 0:
            pagesize = (template_profile.page_width * inch, template_profile.page_height * inch)
    c = canvas.Canvas(str(path), pagesize=pagesize)
    width, height = pagesize
    
    # Get styling from template
    title_font = "Helvetica-Bold"
    heading_font = "Helvetica-Bold"
    body_font = "Helvetica"
    title_size = 16
    heading_size = 12
    body_size = 10
    title_color = (0, 0, 0)
    heading_color = (0, 0, 0)
    body_color = (0, 0, 0)
    line_spacing = 1.2
    logo_path = None

    if template_profile:
        title_font = _map_pdf_font_name(template_profile.title_font.name) if getattr(template_profile, 'title_font', None) else title_font
        heading_font = _map_pdf_font_name(template_profile.heading_font.name) if getattr(template_profile, 'heading_font', None) else heading_font
        body_font = _map_pdf_font_name(template_profile.body_font.name) if getattr(template_profile, 'body_font', None) else body_font
        title_size = template_profile.title_font.size or title_size
        heading_size = template_profile.heading_font.size or heading_size
        body_size = template_profile.body_font.size or body_size
        title_color_hex = template_profile.title_font.color or "000000"
        heading_color_hex = template_profile.heading_font.color or title_color_hex
        body_color_hex = template_profile.body_font.color or "000000"
        try:
            title_color = tuple(int(title_color_hex[i:i+2], 16) / 255 for i in (0, 2, 4))
        except Exception:
            title_color = (0, 0, 0)
        try:
            heading_color = tuple(int(heading_color_hex[i:i+2], 16) / 255 for i in (0, 2, 4))
        except Exception:
            heading_color = title_color
        try:
            body_color = tuple(int(body_color_hex[i:i+2], 16) / 255 for i in (0, 2, 4))
        except Exception:
            body_color = (0, 0, 0)
        line_spacing = getattr(template_profile.paragraph_style, 'line_spacing', line_spacing) or line_spacing
        if getattr(template_profile, 'logo_path', None):
            logo_path = Path(template_profile.logo_path)
            if logo_path.exists():
                logo_dest = output_dir / logo_path.name
                shutil.copy(logo_path, logo_dest)
                logo_path = logo_dest
            else:
                logo_path = None

    # Calculate margins
    left_margin = 50
    right_margin = 50
    if template_profile:
        left_margin = template_profile.margin_left / 20 if template_profile.margin_left else 50
        right_margin = template_profile.margin_right / 20 if template_profile.margin_right else 50
    
    y = height - 40
    
    # Logo
    if logo_path and logo_path.exists():
        try:
            logo_width = min(180, width - left_margin - right_margin)
            c.drawImage(str(logo_path), left_margin, y - 80, width=logo_width, height=60, preserveAspectRatio=True, mask='auto')
            y -= 90
        except Exception:
            pass

    # Header content
    if template_profile and getattr(template_profile, 'header_content', None):
        c.setFillColorRGB(*body_color)
        c.setFont(body_font, max(8, body_size - 1))
        for line in str(template_profile.header_content).splitlines():
            c.drawString(left_margin, y, line[:100])
            y -= body_size * 1.1
        y -= 10

    # Title
    c.setFont(title_font, title_size)
    c.setFillColorRGB(*title_color)
    c.drawString(left_margin, y, "Northbridge Holdings Ltd")
    y -= max(24, title_size + 4)
    
    # Subtitle
    c.setFont(heading_font, heading_size)
    c.drawString(left_margin, y, "Financial Compliance Report – Q1 2025")
    y -= max(28, heading_size + 6)

    # Status
    c.setFont(heading_font, heading_size)
    c.drawString(left_margin, y, f"Compliance Status: {status}")
    y -= 20

    # Narrative
    c.setFont(body_font, body_size)
    c.setFillColorRGB(*body_color)
    line_height = body_size * line_spacing
    for line in narrative.splitlines():
        c.drawString(left_margin, y, line[:110])
        y -= line_height
        if y < 80:
            if template_profile and getattr(template_profile, 'footer_content', None):
                c.setFont(body_font, max(8, body_size - 1))
                c.drawString(left_margin, 40, str(template_profile.footer_content)[:100])
            c.showPage()
            y = height - 50
            c.setFont(body_font, body_size)

    # Footer content for first page if present
    if template_profile and getattr(template_profile, 'footer_content', None):
        c.setFont(body_font, max(8, body_size - 1))
        c.drawString(left_margin, 40, str(template_profile.footer_content)[:100])

    # New page for charts and issues
    c.showPage()
    y = height - 50
    c.setFont(heading_font, heading_size)
    c.drawString(left_margin, y, "Compliance Issues")
    y -= 20
    c.setFont(body_font, body_size)
    if not issues:
        c.drawString(left_margin, y, "No issues detected.")
        y -= 14
    else:
        for issue in issues:
            c.drawString(left_margin, y, f"- {issue[:110]}")
            y -= 14
            if y < 80:
                c.showPage()
                y = height - 50
                c.setFont(body_font, body_size)

    # Charts
    c.showPage()
    y = height - 50
    c.setFont(heading_font, heading_size)
    c.drawString(left_margin, y, "Visual Summaries")
    y -= 20

    for key in ["revenue_vs_payroll", "vendor_spend"]:
        chart_path = charts.get(key)
        if chart_path and chart_path.exists():
            c.drawImage(str(chart_path), left_margin, y - 220, width=300, preserveAspectRatio=True, mask="auto")
            y -= 240
            if y < 100:
                c.showPage()
                y = height - 50

    c.showPage()
    c.save()
    return path


def generate_assessment_report(
    assessment_text: str,
    output_dir: Path,
    template_profile: Optional[Any] = None,
) -> Dict[str, Path]:
    html_path = output_dir / "Assessment_Page.html"
    pdf_path = output_dir / "Assessment_Page.pdf"

    font_family = "Arial, sans-serif"
    title_color = "#000000"
    heading_color = "#333333"
    body_color = "#000000"
    logo_src = None

    if template_profile:
        if template_profile.body_font and template_profile.body_font.name:
            font_family = template_profile.body_font.name
        if template_profile.color_scheme:
            title_color = f"#{template_profile.color_scheme.get('primary', '000000')}"
            heading_color = f"#{template_profile.color_scheme.get('secondary', '333333')}"
            body_color = f"#{template_profile.color_scheme.get('body', '000000')}"
        if template_profile.logo_path:
            logo_path = Path(template_profile.logo_path)
            if logo_path.exists():
                dest_logo = output_dir / logo_path.name
                shutil.copy(logo_path, dest_logo)
                logo_src = dest_logo.name

    with open(html_path, "w", encoding="utf-8") as f:
        f.write("<html><head><title>Assessment Page</title>")
        f.write("<style>")
        f.write("body { font-family: %s; color: %s; padding: 24px; line-height: 1.6; }" % (font_family, body_color))
        f.write("h1 { font-size: 2.0em; color: %s; margin-bottom: 0.3em; }" % title_color)
        f.write("h2 { font-size: 1.3em; color: %s; margin-top: 1.2em; }" % heading_color)
        f.write("img.logo { max-width: 180px; margin-bottom: 16px; }")
        f.write("</style></head><body>")
        if logo_src:
            f.write(f'<img class="logo" src="{logo_src}" alt="Template Logo">')
        f.write("<h1>Assessment Page</h1>")
        f.write("<h2>Template-Based Processing Summary</h2>")
        for paragraph in assessment_text.split("\n\n"):
            safe_paragraph = paragraph.strip().replace("\n", "<br>")
            if safe_paragraph:
                f.write(f"<p>{safe_paragraph}</p>")
        f.write("</body></html>")

    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4
    y = height - 50
    if logo_src:
        try:
            c.drawImage(str(output_dir / logo_src), 50, y - 80, width=180, height=60, preserveAspectRatio=True, mask='auto')
            y -= 90
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, "Assessment Page")
    y -= 28
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Template-Based Processing Summary")
    y -= 24

    c.setFont("Helvetica", 10)
    line_height = 14
    wrapped_lines = []
    for paragraph in assessment_text.split("\n\n"):
        wrapped_lines.extend(textwrap.wrap(paragraph.replace("\n", " "), width=100))
        wrapped_lines.append("")

    for line in wrapped_lines:
        if y < 60:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 10)
        c.drawString(50, y, line)
        y -= line_height

    c.save()
    return {"html": html_path, "pdf": pdf_path}


def _map_pdf_font_name(font_name: Optional[str]) -> str:
    if not font_name:
        return "Helvetica"
    normalized = font_name.lower()
    if "times" in normalized or "serif" in normalized:
        return "Times-Roman"
    if "courier" in normalized or "mono" in normalized:
        return "Courier"
    if "arial" in normalized or "helvetica" in normalized or "calibri" in normalized:
        return "Helvetica"
    return "Helvetica"