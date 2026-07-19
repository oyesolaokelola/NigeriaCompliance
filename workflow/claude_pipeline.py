import os
import json
import logging
import base64
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

        # Prefer the new Anthropic class if available, otherwise fall back to classic Client.
        AnthropicClass = getattr(anthropic, "Anthropic", None) or getattr(anthropic, "Client", None)
        if AnthropicClass is None:
            raise ImportError(
                "Installed Anthropic package does not expose Anthropic or Client. "
                "Please install a compatible version >=0.50.0."
            )

        self._client = AnthropicClass(api_key=key)
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

    def _encode_file_as_base64(self, file_bytes: bytes) -> str:
        return base64.b64encode(file_bytes).decode("utf-8")

    def _build_inline_document_source(self, file_bytes: bytes, filename: str, content_type: str) -> Dict[str, Any]:
        encoded = self._encode_file_as_base64(file_bytes)
        source_type = "image" if content_type.startswith("image/") else "document"
        return {
            "type": source_type,
            "source": {
                "type": "base64",
                "media_type": content_type,
                "data": encoded,
            },
        }

    def build_document_source(self, file_bytes: bytes, filename: str, content_type: str = "application/pdf") -> Dict[str, Any]:
        # Use inline base64-encoded document sources for messages to avoid
        # mismatches in expected 'source' tags across Anthropic SDK versions.
        # Uploading via the Files API can still be done with `upload_file()` when
        # needed, but messages typically expect base64/content/text/url tags.
        try:
            return self._build_inline_document_source(file_bytes, filename, content_type)
        except Exception:
            logger.exception("Failed to build inline document source; falling back to minimal text source.")
            return {"type": "text", "text": f"(file: {filename})"}

    def _messages_to_prompt_text(self, messages: List[Dict[str, Any]]) -> str:
        if not messages:
            return ""
        lines = []
        for message in messages:
            if not isinstance(message, dict):
                lines.append(str(message))
                continue
            role = message.get("role") or message.get("type") or "user"
            content = message.get("content") or message.get("text") or ""
            if isinstance(content, list):
                pieces = []
                for item in content:
                    if isinstance(item, dict):
                        pieces.append(item.get("text", json.dumps(item)))
                    else:
                        pieces.append(str(item))
                content = "\n".join(pieces)
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def _extract_text_from_response(self, response: Any) -> str:
        if response is None:
            return ""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            if "choices" in response and response["choices"]:
                choice = response["choices"][0]
                if isinstance(choice, dict) and "message" in choice:
                    return self._extract_text_from_response(choice["message"].get("content"))
            if "content" in response:
                return self._extract_text_from_response(response["content"])
            return json.dumps(response)
        if hasattr(response, "choices"):
            choices = getattr(response, "choices")
            if choices:
                first = choices[0]
                if hasattr(first, "message"):
                    return self._extract_text_from_response(getattr(first.message, "content", None))
        if hasattr(response, "message"):
            return self._extract_text_from_response(getattr(response.message, "content", None))
        if hasattr(response, "content"):
            return self._extract_text_from_response(getattr(response, "content"))
        if isinstance(response, list) and response:
            first = response[0]
            if isinstance(first, dict):
                return first.get("text") or first.get("content") or json.dumps(first)
        return str(response)

    def create_message(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> Dict[str, Any]:
        # Send a chat-like message to Claude and return parsed JSON/text response.
        model = model or os.getenv("CLAUDE_MODEL", "claude-opus-4-8")
        fallback_model = "claude-opus-4-8"
        last_error = None
        errors = []

        if hasattr(self._client, "messages"):
            try:
                resp = self._client.messages.create(
                    model=model,
                    messages=messages,
                    max_tokens=4096,
                )
                return resp
            except Exception as e:
                last_error = e
                errors.append(("messages.create", str(e)))
                logger.warning(f"Anthropic client.messages.create() failed: {e}")
                logger.warning("Falling back to alternative Anthropic request paths.")
                # If the failure indicates the model is not available, retry with a known-accessible fallback.
                try:
                    err_text = str(e).lower()
                except Exception:
                    err_text = ""
                if "not_found" in err_text or "model" in err_text and "not found" in err_text or "model:" in err_text:
                    logger.warning(f"Model '{model}' appears unavailable. Retrying with fallback model '{fallback_model}'.")
                    try:
                        resp = self._client.messages.create(
                            model=fallback_model,
                            messages=messages,
                            max_tokens=4096,
                        )
                        return resp
                    except Exception as e2:
                        last_error = e2
                        errors.append(("messages.create.fallback", str(e2)))
                        logger.warning(f"Fallback Anthropic messages.create() also failed: {e2}")

        if hasattr(self._client, "chat") and hasattr(self._client.chat, "completions"):
            try:
                resp = self._client.chat.completions.create(model=model, messages=messages, max_tokens=4096)
                return resp
            except Exception as e:
                last_error = e
                errors.append(("chat.completions.create", str(e)))
                logger.warning("Anthropic client.chat.completions.create() failed, falling back to alternative Anthropic request paths.")

        if hasattr(self._client, "completions"):
            try:
                prompt_text = self._messages_to_prompt_text(messages)
                resp = self._client.completions.create(model=model, prompt=prompt_text, max_tokens=4096)
                return resp
            except Exception as e:
                last_error = e
                errors.append(("completions.create", str(e)))
                logger.warning(f"Anthropic client.completions.create() failed: {e}")

        error_details = "; ".join([f"{name}: {msg}" for name, msg in errors])
        raise RuntimeError(
            f"Unable to send Claude message through Anthropic. Tried {len(errors)} methods. Last error: {last_error}. Details: {error_details}"
        ) from last_error


class ClaudePipeline:
    def __init__(self, client: Optional[ClaudeClientStub] = None):
        self.client = client or ClaudeClientStub()

    def analyze_template(self, template_file_bytes: bytes, filename: str, mode: str = "structure_and_branding") -> Dict[str, Any]:
        """Upload template and ask Claude to extract structure and/or branding.

        Returns a JSON-like dict with keys `structure` and `branding` depending on mode.
        """
        template_source = self.client.build_document_source(template_file_bytes, filename)

        prompt = {
            "role": "user",
            "content": [
                template_source,
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

    def extract_and_interpret(
        self,
        dept_file_bytes_list: List[bytes],
        filenames: List[str],
        template_structure: Dict[str, Any] = None,
        template_branding: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        content = []
        for b, name in zip(dept_file_bytes_list, filenames):
            content.append(self.client.build_document_source(b, name))

        prompt_text = (
            f"Template structure: {json.dumps(template_structure or {})}\n"
            f"Template branding: {json.dumps(template_branding or {})}\n\n"
            "Extract metrics, period, department, and return JSON. "
            "Apply the template structure and branding to the generated report output when available."
        )
        content.append({"type": "text", "text": prompt_text})

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
        gen_source = self.client.build_document_source(generated_pdf_bytes, generated_name, content_type="application/pdf")
        tpl_source = self.client.build_document_source(template_file_bytes, template_name, content_type="application/pdf")

        prompt = {"role": "user", "content": [
            tpl_source,
            gen_source,
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
