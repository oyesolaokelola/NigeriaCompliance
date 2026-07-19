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
- If you already have `ANTHROPIC_API_KEY` configured, this backend will also accept that as a fallback.

Examples (PowerShell):
```powershell
$env:CLAUDE_API_KEY = "your_claude_api_key_here"
```

New endpoint added:
- `POST /process_with_claude` — upload an optional `template_file` and `department_docs` (multipart form-data) and set `mode` as form field (`structure_only`, `structure_and_branding`, `branding_only`).

Notes:
- Install the `anthropic` package and `PyPDF2` with `pip install -r requirements.txt` before using the Claude integration.
- For security, set the `CLAUDE_API_KEY` in your deployment environment (Railway, Vercel) rather than hardcoding it.

Model selection (optional):
---------------------------
You can control which Claude model the pipeline uses via an environment variable named `CLAUDE_MODEL`.

Behavior:
- If `CLAUDE_MODEL` is set, the code will use that model string when calling Claude.
- If `CLAUDE_MODEL` is not set, the pipeline falls back to `claude-opus-4-8` (recommended for this key).

Recommended values:
- `claude-opus-4-8` — default/fallback for this deployment and known-accessible with the current key.
- `claude-opus-4-7` — another strong option for rich document understanding.
- `claude-sonnet-5` — lower-cost, general-purpose Claude model.

How to set in Railway / Vercel (example):
1. In your Railway project, go to Settings → Variables and add `CLAUDE_API_KEY` and `CLAUDE_MODEL`.
2. Example values:
	- `CLAUDE_API_KEY`: "sk-..." (your Claude API key)
	- `CLAUDE_MODEL`: `claude-opus-4-8`

PowerShell example (local):
```powershell
$env:CLAUDE_API_KEY = "your_claude_api_key_here"
$env:CLAUDE_MODEL = "claude-opus-4-8"  # optional
```

Notes and best practices:
- Pin a specific `CLAUDE_MODEL` value in production to avoid unexpected behavior from model rollouts.
- If you want to experiment, set `CLAUDE_MODEL` in a staging environment first and validate outputs.
- Keep `CLAUDE_API_KEY` secret and rotate keys periodically.

