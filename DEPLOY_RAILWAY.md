# Deploy to Railway and connect to Vercel (POC)

This guide shows how to push this repository to GitHub and deploy the POC to Railway, then call it from your Vercel-hosted site.

## 1) Prepare the repo and push to GitHub

Recommended: use GitHub CLI (`gh`) because it simplifies repo creation and pushing.

Commands (run from the repo root):

```bash
# initialize (if not already done locally)
cd path/to/NigeriaCompliance
git init
git add .
git commit -m "Initial POC: FastAPI + workflow"
# create remote repo with GH CLI and push
gh repo create YOUR_USER/NigeriaCompliance --public --source=. --push
```

If you don't have `gh`, create a new repo on GitHub web UI then:

```bash
git remote add origin git@github.com:YOUR_USER/NigeriaCompliance.git
git push -u origin main
```

## 2) Deploy to Railway (quick)

1. Sign in at https://railway.app using GitHub.
2. Click **New Project** → **Deploy from GitHub**.
3. Select the `NigeriaCompliance` repository.
4. Railway will detect the `Dockerfile` and build using it. If prompted, choose the Docker build option.
5. Set the following environment variables in Railway project settings:
   - `OPENAI_API_KEY` — your OpenAI API key (do NOT commit this anywhere)
   - `FRONTEND_ORIGINS` — your Vercel domain (e.g., `https://my-site.vercel.app`) or `*` for testing
   - `BASE_URL` — (optional) the Railway service base URL; you can leave blank and set later
6. Deploy. Railway will provide a public HTTPS URL for your service.

## 3) Configure Vercel (frontend)

- In your Vercel project settings, add any necessary environment variables (e.g., `API_BASE_URL`) pointing at the Railway service URL.
- Allow CORS by setting `FRONTEND_ORIGINS` in Railway to your Vercel domain.

### Example front-end usage (upload + trigger)

```javascript
// Upload file
async function uploadFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('department', 'finance');
  const res = await fetch(`${process.env.API_BASE_URL}/upload`, {
    method: 'POST',
    body: fd,
  });
  return res.json();
}

// Trigger processing
async function triggerProcessing() {
  const res = await fetch(`${process.env.API_BASE_URL}/process`, { method: 'POST' });
  return res.json();
}

// Fetch aggregated json
async function getAggregated() {
  const res = await fetch(`${process.env.API_BASE_URL}/aggregated`);
  return res.json();
}
```

## 4) Test with curl

```bash
# Upload a file
curl -F "file=@/path/to/doc.pdf" -F "department=finance" https://<railway-url>/upload
# Trigger processing
curl -X POST https://<railway-url>/process
# Download generated HTML
curl https://<railway-url>/artifact/Financial_Compliance_Report_Q1_2025.html -o report.html
```

## Notes
- Keep secrets in Railway environment settings; never commit keys. If a key is exposed, rotate immediately.
- For production readiness: replace local `repository/` and `output/` with cloud storage (S3/Azure Blob/GCS) and use a background worker for long-running tasks.
