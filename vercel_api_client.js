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

export { uploadFile, triggerProcess, getAggregated, artifactUrl };
