from pathlib import Path
from workflow.reporting import create_summary_charts, generate_html_report

class FontStub:
    def __init__(self, name="DejaVu Sans", size=12, color="000000"):
        self.name = name
        self.size = size
        self.color = color

class TemplateProfileStub:
    def __init__(self):
        self.body_font = FontStub(name="DejaVu Sans", size=11)
        self.title_font = FontStub(name="DejaVu Sans", size=18)
        self.heading_font = FontStub(name="DejaVu Sans", size=14)
        self.color_scheme = {"primary": "1f77b4", "secondary": "2ca02c", "body": "000000"}
        self.logo_path = None


def run_smoke():
    out = Path("output")
    out.mkdir(exist_ok=True)

    aggregated = {
        "metrics": {"revenue": 5000000, "total_payroll": 2000000, "total_vendor_spend": 750000},
        "departmental": {
            "Finance": {"metrics": {"revenue": 5000000, "total_payroll": 2000000}},
            "Procurement": {"metrics": {"total_vendor_spend": 750000}},
            "HR": {"metrics": {}},
            "Operations": {"metrics": {}},
        },
        "notes": ["Generated for smoke test"]
    }

    tpl = TemplateProfileStub()
    charts = create_summary_charts(aggregated, out, template_profile=tpl)
    html = generate_html_report(aggregated, "Compliant", [], charts, "Narrative from smoke test", out, template_profile=tpl)
    print("Charts generated:", charts)
    print("HTML report:", html)

if __name__ == '__main__':
    run_smoke()
