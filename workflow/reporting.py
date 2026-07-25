# workflow/reporting.py
from pathlib import Path
from typing import Dict, Any, List, Optional
import shutil
import textwrap
import re
from datetime import datetime

import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4, letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor


def _resolve_branding(template_profile: Optional[Any] = None, template_analysis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge branding from the extracted profile and Claude analysis without hard-coding a specific template."""
    branding: Dict[str, Any] = {
        "font_family": "Arial, sans-serif",
        "title_font_family": "Arial, sans-serif",
        "heading_font_family": "Arial, sans-serif",
        "title_color": "#000000",
        "heading_color": "#333333",
        "body_color": "#000000",
        "logo_src": None,
        "header_text": None,
        "footer_text": None,
    }

    if template_profile:
        body_font = getattr(template_profile, "body_font", None)
        title_font = getattr(template_profile, "title_font", None)
        heading_font = getattr(template_profile, "heading_font", None)
        color_scheme = getattr(template_profile, "color_scheme", None)
        header_content = getattr(template_profile, "header_content", None)
        footer_content = getattr(template_profile, "footer_content", None)
        logo_path_value = getattr(template_profile, "logo_path", None)

        if body_font and getattr(body_font, "name", None):
            branding["font_family"] = body_font.name
        if title_font and getattr(title_font, "name", None):
            branding["title_font_family"] = title_font.name
        if heading_font and getattr(heading_font, "name", None):
            branding["heading_font_family"] = heading_font.name
        if color_scheme:
            branding["title_color"] = f"#{color_scheme.get('primary', '000000')}"
            branding["heading_color"] = f"#{color_scheme.get('secondary', '333333')}"
            branding["body_color"] = f"#{color_scheme.get('body', '000000')}"
        branding["header_text"] = header_content or branding["header_text"]
        branding["footer_text"] = footer_content or branding["footer_text"]
        if logo_path_value:
            logo_path = Path(logo_path_value)
            if logo_path.exists():
                branding["logo_src"] = logo_path

    if template_analysis and template_analysis.get("branding"):
        analysis = template_analysis["branding"]
        if analysis.get("fonts") and isinstance(analysis["fonts"], dict):
            if analysis["fonts"].get("body"):
                branding["font_family"] = analysis["fonts"]["body"]
            if analysis["fonts"].get("heading"):
                branding["heading_font_family"] = analysis["fonts"]["heading"]
        if analysis.get("primary_color"):
            branding["title_color"] = analysis["primary_color"]
        if analysis.get("secondary_color"):
            branding["heading_color"] = analysis["secondary_color"]
        if analysis.get("body_color"):
            branding["body_color"] = analysis["body_color"]
        branding["header_text"] = analysis.get("header_text") or analysis.get("letterhead") or branding["header_text"]
        branding["footer_text"] = analysis.get("footer_text") or branding["footer_text"]
        logo_value = analysis.get("logo") or analysis.get("logo_path")
        if isinstance(logo_value, str) and Path(logo_value).exists():
            branding["logo_src"] = Path(logo_value)
        elif isinstance(logo_value, str) and not branding["header_text"]:
            branding["header_text"] = logo_value

    return branding


def _as_rgb(color_value: str):
    try:
        normalized = color_value.lstrip("#")
        return tuple(int(normalized[i:i+2], 16) / 255 for i in (0, 2, 4))
    except Exception:
        return (0, 0, 0)


def _resolve_report_heading(template_profile: Optional[Any] = None, template_analysis: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Resolve a template-specific title and subtitle without hard-coded brand text."""
    title = None
    subtitle = None

    if template_analysis and template_analysis.get("structure"):
        for section in template_analysis["structure"].get("sections", []):
            section_name = str(section.get("name", "")).strip().lower()
            content = section.get("content") or []
            combined = " ".join(str(item).strip() for item in content if str(item).strip())
            if section_name == "report title" and combined:
                title = combined
            elif section_name in {"header/letterhead", "letterhead", "header"} and combined and not subtitle:
                subtitle = combined

    if not title and template_profile:
        template_insights = getattr(template_profile, "template_insights", None) or {}
        header_content = getattr(template_profile, "header_content", None)
        title = template_insights.get("report_title")
        if not title and header_content:
            title = header_content.splitlines()[-1].strip()

    if not subtitle and template_profile:
        template_insights = getattr(template_profile, "template_insights", None) or {}
        subtitle = getattr(template_profile, "footer_content", None) or template_insights.get("subtitle")

    return {
        "title": title or "Compliance Report",
        "subtitle": subtitle or "Financial compliance summary",
    }


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _lookup_metric(metrics: Dict[str, Any], field_name: str):
    if not isinstance(metrics, dict) or not field_name:
        return None
    wanted = _normalize_token(field_name)
    if not wanted:
        return None
    for key, value in metrics.items():
        norm_key = _normalize_token(key)
        if norm_key == wanted or wanted in norm_key or norm_key in wanted:
            return value
    return None


def _format_metric(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _resolve_reporting_period(aggregated: Dict[str, Any]) -> str:
    periods = aggregated.get("periods") if isinstance(aggregated, dict) else None
    if isinstance(periods, list) and periods:
        return ", ".join(str(p) for p in periods if p)
    if isinstance(periods, str) and periods:
        return periods
    return "Unknown"


def _collect_template_section_rows(
    section: Dict[str, Any],
    aggregated: Dict[str, Any],
    narrative: str,
    status: str,
    issues: List[str],
) -> List[str]:
    """Build display rows for a template section without hard-coding one template schema."""
    rows: List[str] = []
    section_name = str(section.get("name", "")).strip().lower()
    global_metrics = aggregated.get("metrics", {}) if isinstance(aggregated, dict) else {}
    departmental = aggregated.get("departmental", {}) if isinstance(aggregated, dict) else {}

    # Include explicit template content first.
    for item in section.get("content", []) or []:
        if str(item).strip():
            rows.append(str(item).strip())

    # Fill declared fields using aggregated metrics where possible.
    for field in section.get("fields", []) or []:
        value = _lookup_metric(global_metrics, field)
        rows.append(f"{field}: {_format_metric(value)}")

    if "metadata" in section_name:
        rows.append(f"Report Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        rows.append(f"Reporting Period: {_resolve_reporting_period(aggregated)}")
        rows.append(f"Compliance Status: {status}")

    if "executive summary" in section_name and narrative:
        rows.append(narrative)

    if "compliance" in section_name and "issue" in section_name:
        if issues:
            rows.extend([f"- {issue}" for issue in issues])
        else:
            rows.append("No issues detected.")

    # Departmental subsection support
    subsections = section.get("subsections") or []
    if isinstance(subsections, list) and subsections:
        for sub in subsections:
            sub_name = str(sub.get("name", "")).strip()
            if not sub_name:
                continue
            rows.append(f"{sub_name}")
            dept_metrics = {}
            for dept_key, dept_payload in departmental.items():
                if _normalize_token(dept_key) == _normalize_token(sub_name):
                    dept_metrics = (dept_payload or {}).get("metrics", {}) if isinstance(dept_payload, dict) else {}
                    break
            for field in sub.get("fields", []) or []:
                rows.append(f"  {field}: {_format_metric(_lookup_metric(dept_metrics, field))}")

    return rows


def create_summary_charts(aggregated: Dict[str, Any], output_dir: Path, template_profile: Optional[Any] = None, template_analysis: Optional[Dict[str, Any]] = None) -> Dict[str, Path]:
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

    # Override with extracted template_analysis branding if available
    if template_analysis and template_analysis.get("branding"):
        branding = template_analysis["branding"]
        if branding.get("primary_color"):
            title_color = branding["primary_color"]
        if branding.get("secondary_color"):
            label_color = branding["secondary_color"]
        bar_color = title_color

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
    template_analysis: Optional[Dict[str, Any]] = None,
) -> Path:
    path = output_dir / "Financial_Compliance_Report_Q1_2025.html"
    branding = _resolve_branding(template_profile, template_analysis)
    heading = _resolve_report_heading(template_profile, template_analysis)
    font_family = branding["font_family"]
    title_font_family = branding["title_font_family"]
    heading_font_family = branding["heading_font_family"]
    title_color = branding["title_color"]
    heading_color = branding["heading_color"]
    body_color = branding["body_color"]
    logo_src = None
    if isinstance(branding["logo_src"], Path):
        logo_path = branding["logo_src"]
        dest_logo = output_dir / logo_path.name
        if logo_path.exists():
            shutil.copy(logo_path, dest_logo)
            logo_src = dest_logo.name
    elif isinstance(branding["logo_src"], str):
        logo_src = branding["logo_src"]

    banner_text = branding["header_text"]

    finance = aggregated.get("departmental", {}).get("Finance", {}).get("metrics", {})
    procurement = aggregated.get("departmental", {}).get("Procurement", {}).get("metrics", {})
    hr = aggregated.get("departmental", {}).get("HR", {}).get("metrics", {})
    ops = aggregated.get("departmental", {}).get("Operations", {}).get("metrics", {})
    template_sections = []
    if template_analysis and isinstance(template_analysis.get("structure"), dict):
        template_sections = template_analysis["structure"].get("sections", []) or []
    if not template_sections and template_profile and getattr(template_profile, "template_insights", None):
        inferred_headings = template_profile.template_insights.get("headings", [])
        if inferred_headings:
            template_sections = [{"name": heading} for heading in inferred_headings[:8] if str(heading).strip()]

    def img_tag(p: Optional[Path]) -> str:
        return f'<img src="{p.name}" alt="{p.name}" style="max-width:400px;">' if p else ""

    with open(path, "w", encoding="utf-8") as f:
        f.write("<html><head><title>Financial Compliance Report Q1 2025</title>")
        f.write("<style>")
        f.write("body { font-family: %s; color: %s; padding: 24px; line-height: 1.5; }" % (font_family, body_color))
        f.write("h1 { font-family: %s; font-size: 2.2em; color: %s; margin-bottom: 0.2em; }" % (title_font_family, title_color))
        f.write("h2 { font-family: %s; font-size: 1.5em; color: %s; margin-top: 1.2em; }" % (heading_font_family, heading_color))
        f.write("h3, h4 { font-family: %s; color: %s; margin-top: 1.2em; }" % (heading_font_family, heading_color))
        f.write(".letterhead { background: %s; color: %s; padding: 18px 20px; margin-bottom: 18px; }" % (title_color, branding.get('secondary_color', '#FFFFFF')))
        f.write(".letterhead .brand { font-size: 1.35em; font-weight: 700; line-height: 1.1; }")
        f.write(".letterhead .subtitle { font-size: 1em; opacity: 0.95; margin-top: 4px; }")
        f.write("table { border-collapse: collapse; width: 100%; margin-bottom: 16px; }")
        f.write("table td, table th { border: 1px solid #ccc; padding: 8px; }")
        f.write("img.logo { max-width: 200px; margin-bottom: 16px; }")
        f.write(".report-header { margin-bottom: 16px; color: %s; }" % body_color)
        f.write(".report-footer { margin-top: 40px; padding-top: 12px; border-top: 1px solid #ddd; color: %s; font-size: 0.9em; }" % body_color)
        f.write("</style></head><body>")
        if banner_text:
            brand_lines = [line.strip() for line in str(banner_text).splitlines() if line.strip()]
            if brand_lines:
                f.write("<div class='letterhead'>")
                f.write(f"<div class='brand'>{brand_lines[0]}</div>")
                if len(brand_lines) > 1:
                    f.write(f"<div class='subtitle'>{' '.join(brand_lines[1:])}</div>")
                f.write("</div>")
        if logo_src:
            f.write(f'<img class="logo" src="{logo_src}" alt="Logo">')
        elif template_analysis and template_analysis.get("branding", {}).get("logo"):
            logo_text = template_analysis["branding"]["logo"]
            if isinstance(logo_text, str):
                f.write(f'<div class="report-header">{logo_text}</div>')
        if template_profile and getattr(template_profile, 'header_content', None) and not banner_text:
            f.write(f'<div class="report-header">{template_profile.header_content}</div>')
        f.write(f"<h1>{heading['title']}</h1>")
        f.write(f"<h2>{heading['subtitle']}</h2>")

        if template_sections:
            for idx, section in enumerate(template_sections, start=1):
                section_name = section.get("name") or f"Section {idx}"
                f.write(f"<h3>Section {idx}: {section_name}</h3>")
                rows = _collect_template_section_rows(section, aggregated, narrative, status, issues)

                # Heuristic: render as table if it looks like metric rows.
                metric_rows = [r for r in rows if ":" in r and not r.strip().startswith("-")]
                if metric_rows and len(metric_rows) >= max(2, len(rows) // 2):
                    f.write("<table border='1' cellpadding='4'><tr><th>Field</th><th>Value</th></tr>")
                    for row in metric_rows:
                        k, v = row.split(":", 1)
                        f.write(f"<tr><td>{k.strip()}</td><td>{v.strip()}</td></tr>")
                    f.write("</table>")
                    extra_rows = [r for r in rows if r not in metric_rows]
                    for row in extra_rows:
                        if row.strip().startswith("-"):
                            f.write(f"<p>{row}</p>")
                        elif row.strip():
                            f.write(f"<p>{row}</p>")
                else:
                    for row in rows:
                        if row.strip():
                            f.write(f"<p>{row}</p>")

            f.write("<h3>Visual Summaries</h3>")
            f.write("<div>")
            f.write(img_tag(charts.get("revenue_vs_payroll")))
            f.write(img_tag(charts.get("vendor_spend")))
            f.write("</div>")
        else:
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
            for note in aggregated.get("notes", []):
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
    template_analysis: Optional[Dict[str, Any]] = None,
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
    banner_text = None
    banner_fill = (0, 0, 0)
    banner_text_color = (1, 1, 1)

    branding = _resolve_branding(template_profile, template_analysis)
    heading = _resolve_report_heading(template_profile, template_analysis)
    banner_text = branding.get("header_text")
    banner_fill = _as_rgb(branding.get("title_color", "#000000"))
    banner_text_color = _as_rgb(branding.get("heading_color", "#FFFFFF")) if branding.get("heading_color") else (1, 1, 1)

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
    elif template_analysis:
        title_color = _as_rgb(branding.get("title_color", "#000000"))
        heading_color = _as_rgb(branding.get("heading_color", "#000000"))
        body_color = _as_rgb(branding.get("body_color", "#000000"))

    # Calculate margins
    left_margin = 50
    right_margin = 50
    if template_profile:
        left_margin = template_profile.margin_left / 20 if template_profile.margin_left else 50
        right_margin = template_profile.margin_right / 20 if template_profile.margin_right else 50
    
    y = height - 40

    # Letterhead banner
    if banner_text:
        banner_lines = [line.strip() for line in str(banner_text).splitlines() if line.strip()]
        if banner_lines:
            banner_height = min(70, 18 + 16 * len(banner_lines))
            c.setFillColorRGB(*banner_fill)
            c.rect(left_margin, y - banner_height + 8, width - left_margin - right_margin, banner_height, fill=1, stroke=0)
            c.setFillColorRGB(*banner_text_color)
            c.setFont(title_font, max(title_size, 11))
            text_y = y - 16
            for idx, line in enumerate(banner_lines[:3]):
                c.drawString(left_margin + 12, text_y, line[:120])
                text_y -= 16 if idx == 0 else 14
            y -= banner_height + 10
    
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
    c.drawString(left_margin, y, heading["title"][:120])
    y -= max(24, title_size + 4)
    
    # Subtitle
    c.setFont(heading_font, heading_size)
    c.drawString(left_margin, y, heading["subtitle"][:120])
    y -= max(28, heading_size + 6)

    template_sections = []
    if template_analysis and isinstance(template_analysis.get("structure"), dict):
        template_sections = template_analysis["structure"].get("sections", []) or []
    if not template_sections and template_profile and getattr(template_profile, "template_insights", None):
        inferred_headings = template_profile.template_insights.get("headings", [])
        if inferred_headings:
            template_sections = [{"name": heading} for heading in inferred_headings[:8] if str(heading).strip()]

    c.setFont(body_font, body_size)
    c.setFillColorRGB(*body_color)
    line_height = body_size * line_spacing

    if template_sections:
        for idx, section in enumerate(template_sections, start=1):
            c.setFont(heading_font, heading_size)
            c.setFillColorRGB(*heading_color)
            c.drawString(left_margin, y, f"Section {idx}: {(section.get('name') or '')[:100]}")
            y -= 18
            c.setFont(body_font, body_size)
            c.setFillColorRGB(*body_color)
            rows = _collect_template_section_rows(section, aggregated, narrative, status, issues)
            for row in rows:
                for line in textwrap.wrap(str(row), width=110):
                    c.drawString(left_margin, y, line[:110])
                    y -= line_height
                    if y < 80:
                        if template_profile and getattr(template_profile, 'footer_content', None):
                            c.setFont(body_font, max(8, body_size - 1))
                            c.drawString(left_margin, 40, str(template_profile.footer_content)[:100])
                        c.showPage()
                        y = height - 50
                        c.setFont(body_font, body_size)
                        c.setFillColorRGB(*body_color)
            y -= 8
    else:
        # Status
        c.setFont(heading_font, heading_size)
        c.drawString(left_margin, y, f"Compliance Status: {status}")
        y -= 20

        # Narrative
        c.setFont(body_font, body_size)
        c.setFillColorRGB(*body_color)
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