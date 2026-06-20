// vercel_api_client.js
// Frontend helper for Vercel sites to call the Railway-hosted NigeriaCompliance API.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.API_BASE_URL;

if (!API_BASE_URL) {
  console.warn('API_BASE_URL is not set. Set NEXT_PUBLIC_API_BASE_URL in Vercel environment variables.');
}

async function uploadFile(file, department = 'other') {
  if (!API_BASE_URL) {
    throw new Error('API_BASE_URL is not configured.');
  }

  const formData = new FormData();
  formData.append('file', file);
  formData.append('department', department);

  const response = await fetch(`${API_BASE_URL}/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Upload failed: ${response.status} ${errorText}`);
  }

  return response.json();
}

async function triggerProcess() {
  if (!API_BASE_URL) {
    throw new Error('API_BASE_URL is not configured.');
  }

  const response = await fetch(`${API_BASE_URL}/process`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Process request failed: ${response.status} ${errorText}`);
  }

  return response.json();
}

async function processWithClaude({ templateFile = null, departmentFiles = [], mode = 'structure_and_branding' } = {}) {
  if (!API_BASE_URL) {
    throw new Error('API_BASE_URL is not configured.');
  }

  const formData = new FormData();
  if (templateFile) {
    formData.append('template_file', templateFile);
  }
  for (const f of departmentFiles) {
    formData.append('department_docs', f);
  }
  formData.append('mode', mode);

  const response = await fetch(`${API_BASE_URL}/process_with_claude`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`process_with_claude failed: ${response.status} ${errorText}`);
  }

  return response.json();
}

async function getProcessStatus() {
  if (!API_BASE_URL) {
    throw new Error('API_BASE_URL is not configured.');
  }

  const response = await fetch(`${API_BASE_URL}/process/status`, {
    method: 'GET',
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Process status failed: ${response.status} ${errorText}`);
  }

  return response.json();
}

async function triggerProcessAndWait({ intervalMs = 2000, timeoutMs = 180000 } = {}) {
  const res = await triggerProcess();
  if (!res.success) {
    throw new Error(`Process start failed: ${res.message || 'unknown error'}`);
  }

  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    const status = await getProcessStatus();
    if (!status.running) {
      if (status.last_error) {
        throw new Error(`Processing failed: ${status.last_error_type} ${status.last_error}`);
      }
      return status;
    }
  }

  throw new Error('Processing timed out waiting for completion.');
}

async function getAggregated() {
  if (!API_BASE_URL) {
    throw new Error('API_BASE_URL is not configured.');
  }

  const response = await fetch(`${API_BASE_URL}/aggregated`, {
    method: 'GET',
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Aggregated fetch failed: ${response.status} ${errorText}`);
  }

  return response.json();
}

function artifactUrl(filename) {
  if (!API_BASE_URL) {
    throw new Error('API_BASE_URL is not configured.');
  }
  return `${API_BASE_URL}/artifact/${encodeURIComponent(filename)}`;
}

export { uploadFile, triggerProcess, getProcessStatus, triggerProcessAndWait, getAggregated, artifactUrl };
