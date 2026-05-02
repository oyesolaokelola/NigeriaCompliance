import os
import requests
import json

BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "mistral:latest")

print("Ollama base:", BASE)
try:
    tags = requests.get(f"{BASE}/api/tags", timeout=5).json()
    print("models:", [m.get("model") or m.get("name") for m in tags.get("models", [])])
except Exception as e:
    print("could not list tags:", e)

endpoints = [
    "/api/generate",
    "/v1/generate",
    "/api/chat/completions",
    "/v1/chat/completions",
    "/chat/completions",
    "/api/completions",
]

payloads = [
    {"model": MODEL, "prompt": "Respond with JSON: {\"test\": \"ok\"} and a one-line summary."},
    {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a test assistant."},
            {"role": "user", "content": "Respond with JSON: {\"test\": \"ok\"} and a one-line summary."},
        ],
    },
]

headers = {"Authorization": "Bearer ollama", "Content-Type": "application/json"}

for ep in endpoints:
    url = BASE + ep
    for p in payloads:
        print("\nPOST", url)
        try:
            r = requests.post(url, json=p, headers=headers, timeout=20)
            print("STATUS", r.status_code)
            try:
                print(json.dumps(r.json(), indent=2))
            except Exception:
                print(r.text[:1000])
        except Exception as e:
            print("ERROR", e)

