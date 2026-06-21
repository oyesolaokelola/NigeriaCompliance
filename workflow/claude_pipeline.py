import os
import json
import logging
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)


def _require_api_key():
    key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise EnvironmentError(
            "CLAUDE_API_KEY not set. Please set CLAUDE_API_KEY or ANTHROPIC_API_KEY as an environment variable."
        )
    return key


class ClaudeClientStub:
    """Minimal stub wrapper for the Claude/Anthropic client.

    This file assumes a real Anthropic client will be used in production.
    The stub raises helpful errors when the package or API key is missing.
    """

    def __init__(self):
        # Ensure an API key exists (CLAUDE_API_KEY or ANTHROPIC_API_KEY) and use it
        key = _require_api_key()
        try:
            import anthropic
        except Exception as e:
            raise ImportError(
                "Please install the 'anthropic' package and set CLAUDE_API_KEY."
            ) from e
        # Use the detected key (covers CLAUDE_API_KEY or ANTHROPIC_API_KEY)
        self._client = anthropic.Client(api_key=key)
        self._api_key = key

        # Log Anthropic package version and whether the Files API is available
        try:
            ver = getattr(anthropic, "__version__", None)
            logger.info(f"anthropic package version: {ver}")
        except Exception:
            logger.debug("Could not read anthropic.__version__")

        self._has_beta_files = hasattr(self._client, "beta") and hasattr(self._client.beta, "files")
        self._has_files_api = self._has_beta_files or hasattr(self._client, "files")
        logger.info(f"anthropic client has files API: {self._has_files_api}, beta.files: {self._has_beta_files}")

    def upload_file(self, file_bytes: bytes, filename: str, content_type: str = "application/pdf") -> str:
        # Upload a file to the Anthropic files API (beta). Returns a file_id string.
        # Implementation may change depending on the official SDK surface.
        if self._has_beta_files:
            try:
                resp = self._client.beta.files.upload(file=(filename, file_bytes, content_type))
                if isinstance(resp, dict):
                    return resp.get("id") or resp.get("file_id") or str(resp)
                return getattr(resp, "id", getattr(resp, "file_id", str(resp)))
            except Exception as e:
                logger.exception("File upload to Claude failed using beta.files.upload()")
                raise
        elif hasattr(self._client, "files"):
            try:
                resp = self._client.files.create(file=(filename, file_bytes, content_type))
                return getattr(resp, "id", getattr(resp, "file_id", str(resp)))
            except Exception as e:
                logger.exception("File upload to Claude failed using files.create()")
                raise
        else:
            try:
                # Fall back to raw HTTP upload if the SDK does not expose a files API.
                base_url = getattr(self._client, "base_url", "https://api.anthropic.com")
                if not base_url:
                    base_url = getattr(self._client, "_base_url", "https://api.anthropic.com")
                # Some client implementations expose URL objects; ensure string
                try:
                    base_url = str(base_url)
                except Exception:
                    base_url = "https://api.anthropic.com"

                headers = {}
                if callable(getattr(self._client, "auth_headers", None)):
                    try:
                        headers = self._client.auth_headers() or {}
                    except Exception:
                        headers = {}
                elif self._api_key:
                    headers = {"x-api-key": self._api_key}
                headers = headers.copy() if isinstance(headers, dict) else {}
                headers["Accept"] = "application/json"

                upload_url = base_url.rstrip("/") + "/v1/files"
                response = requests.post(
                    upload_url,
                    headers=headers,
                    files={"file": (filename, file_bytes, content_type)},
                    timeout=120,
                )
                response.raise_for_status()
                payload = response.json()
                file_id = payload.get("id") or payload.get("file_id")
                if not file_id:
                    raise RuntimeError(f"Unexpected Anthropic file upload response: {payload}")
                logger.info("Uploaded file via raw Anthropic HTTP fallback")
                return file_id
            except Exception as e:
                available = dir(self._client)
                logger.error(
                    "Anthropic SDK appears to be missing the Files API. "
                    "Use beta.files.upload() or ensure the installed SDK exposes a valid file upload method. "
                    f"Client attrs: {available}"
                )
                logger.exception("Raw Anthropic HTTP file upload fallback failed")
                raise RuntimeError(
                    "Anthropic SDK in runtime does not expose files.create() or beta.files.upload(), and raw HTTP upload fallback failed. "
                    "Please verify the Anthropic SDK version and API credentials."
                ) from e

    def create_message(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> Dict[str, Any]:
        # Send a chat-like message to Claude and return parsed JSON/text response.
        # Model selection order:
        # 1. explicit `model` argument
        # 2. environment variable `CLAUDE_MODEL`
        # 3. default fallback `claude-2`
        model = model or os.getenv("CLAUDE_MODEL", "claude-2")
        try:
            resp = self._client.chat.completions.create(model=model, messages=messages)
            return resp
        except Exception:
            # Try fallback to older API surface
            resp = self._client.completions.create(model=model, prompt=messages)
            return resp


class ClaudePipeline:
    def __init__(self, client: Optional[ClaudeClientStub] = None):
        self.client = client or ClaudeClientStub()

    def analyze_template(self, template_file_bytes: bytes, filename: str, mode: str = "structure_and_branding") -> Dict[str, Any]:
        """Upload template and ask Claude to extract structure and/or branding.

        Returns a JSON-like dict with keys `structure` and `branding` depending on mode.
        """
        file_id = self.client.upload_file(template_file_bytes, filename)

        prompt = {
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "file", "file_id": file_id}},
                {
                    "type": "text",
                    "text": (
                        f"Mode: {mode}\n\n"
                        "Extract template structure (sections, field names) and/or branding "
                        "(fonts, colors, logos, letterhead). Return JSON only."
                    ),
                },
            ],
        }

        resp = self.client.create_message([prompt])
        # Attempt to parse JSON from the response content
        try:
            # SDK response parsing may vary; try common paths
            text = getattr(resp, "choices", [])[0].message.content if hasattr(resp, "choices") else str(resp)
        except Exception:
            text = str(resp)

        # Fallback: try to extract JSON substring
        try:
            return json.loads(text)
        except Exception:
            # Best-effort: return raw text under key 'raw'
            return {"raw": text}

    def extract_and_interpret(self, dept_file_bytes_list: List[bytes], filenames: List[str], template_structure: Dict[str, Any] = None) -> Dict[str, Any]:
        file_ids = []
        for b, name in zip(dept_file_bytes_list, filenames):
            file_ids.append(self.client.upload_file(b, name))

        content = [
            {"type": "document", "source": {"type": "file", "file_id": fid}} for fid in file_ids
        ]
        content.append({"type": "text", "text": f"Template structure: {json.dumps(template_structure or {})}\n\nExtract metrics, period, department, and return JSON."})

        prompt = {"role": "user", "content": content}
        resp = self.client.create_message([prompt])

        try:
            text = getattr(resp, "choices", [])[0].message.content if hasattr(resp, "choices") else str(resp)
        except Exception:
            text = str(resp)

        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}

    def validate_pdf_against_template(self, generated_pdf_bytes: bytes, generated_name: str, template_file_bytes: bytes, template_name: str) -> Dict[str, Any]:
        # Upload both and ask Claude to compare structure/sections/headings and charts
        gen_id = self.client.upload_file(generated_pdf_bytes, generated_name, content_type="application/pdf")
        tpl_id = self.client.upload_file(template_file_bytes, template_name, content_type="application/pdf")

        prompt = {"role": "user", "content": [
            {"type": "document", "source": {"type": "file", "file_id": tpl_id}},
            {"type": "document", "source": {"type": "file", "file_id": gen_id}},
            {"type": "text", "text": "Compare the generated report against the template: list any structural or visual mismatches as JSON."}
        ]}

        resp = self.client.create_message([prompt])
        try:
            text = getattr(resp, "choices", [])[0].message.content if hasattr(resp, "choices") else str(resp)
        except Exception:
            text = str(resp)

        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}
