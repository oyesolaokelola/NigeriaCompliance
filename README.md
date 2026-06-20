# NigeriaCompliance — POC Server

Quick POC to run the workflow as an API for your Vercel-hosted site.

Run locally (Windows example):
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:OPENAI_API_KEY = "your_key_here"
uvicorn api.server:app --reload --host 0.0.0.0 --port 8000
```

Endpoints
- `GET /health` — health check
- `POST /upload` — multipart file upload (field `file`, optional `department`)
- `POST /process` — runs processing on `repository/` and generates reports
- `GET /artifact/{filename}` — download generated files
- `GET /aggregated` — returns `aggregated_data.json`

For deployment, set `OPENAI_API_KEY` and `BASE_URL` environment variables. Use the provided `Dockerfile` to containerize.

Claude Integration (Optional)
--------------------------------
This project supports using Anthropic's Claude Files API to perform unified document parsing, template analysis, risk analysis and narrative generation.

Setup:
- Set the `CLAUDE_API_KEY` environment variable in your local shell or in Railway/Vercel environment settings.

Examples (PowerShell):
```powershell
$env:CLAUDE_API_KEY = "your_claude_api_key_here"
```

New endpoint added:
- `POST /process_with_claude` — upload an optional `template_file` and `department_docs` (multipart form-data) and set `mode` as form field (`structure_only`, `structure_and_branding`, `branding_only`).

Notes:
- Install the `anthropic` package and `PyPDF2` with `pip install -r requirements.txt` before using the Claude integration.
- For security, set the `CLAUDE_API_KEY` in your deployment environment (Railway, Vercel) rather than hardcoding it.

