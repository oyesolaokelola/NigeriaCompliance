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
