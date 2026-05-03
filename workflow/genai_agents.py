# workflow/genai_agents.py
import json
import os
import re
import time
from typing import List, Dict, Any

# Ollama configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")

# LLM call tuning (per-attempt timeout, retries, backoff)
# Defaults can be overridden via environment variables.
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_CALL_TIMEOUT = int(os.getenv("LLM_CALL_TIMEOUT", "60"))
LLM_BACKOFF_FACTOR = float(os.getenv("LLM_BACKOFF_FACTOR", "1.5"))


def _ollama_available() -> bool:
    """Check if Ollama server is reachable."""
    import urllib.request
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags", method="GET"
        )
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def call_llm(system_prompt: str, user_prompt: str) -> str:
    # Priority 1: OpenAI API (if key is set)
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if api_key:
        print(f"Starting LLM call with OpenAI model {model}")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            print(f"OpenAI call succeeded with model {model}")
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"OpenAI API call failed: {type(e).__name__}: {e}")
            pass
    else:
        print("No OPENAI_API_KEY found, will try Ollama")

    # Priority 2: Local Ollama
    if _ollama_available():
        print(f"Starting LLM call with Ollama model {OLLAMA_MODEL}")
        print("Ollama available, using local /v1/chat/completions")
        try:
            import requests

            url = OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            }
            headers = {"Authorization": "Bearer ollama", "Content-Type": "application/json"}
            session = requests.Session()
            last_exc = None
            for attempt in range(1, LLM_MAX_RETRIES + 1):
                try:
                    print(f"Attempt {attempt}/{LLM_MAX_RETRIES} posting to {url} with timeout {LLM_CALL_TIMEOUT}s")
                    resp = session.post(url, json=payload, headers=headers, timeout=LLM_CALL_TIMEOUT)
                    print("HTTP request sent, waiting for response")
                    resp.raise_for_status()
                    j = resp.json()
                    print("LLM raw JSON response:", json.dumps(j)[:2000])
                    if isinstance(j, dict):
                        choices = j.get("choices")
                        if isinstance(choices, list) and choices:
                            first = choices[0]
                            if isinstance(first.get("message"), dict) and "content" in first["message"]:
                                return first["message"]["content"] or ""
                            if "text" in first:
                                return first.get("text") or ""
                        if "error" in j:
                            print("Ollama /v1/chat returned error object:", j["error"])
                    print("LLM HTTP call returned unexpected structure:", j)
                    return ""
                except Exception as exc:
                    last_exc = exc
                    print(f"Ollama HTTP call attempt {attempt} failed: {exc}")
                    if attempt < LLM_MAX_RETRIES:
                        backoff = LLM_BACKOFF_FACTOR ** (attempt - 1)
                        print(f"Backing off {backoff} seconds before retry")
                        time.sleep(backoff)
            session.close()
            print(f"Ollama HTTP call failed after {LLM_MAX_RETRIES} attempts: {last_exc}")
        except ModuleNotFoundError:
            print("requests package not installed for Ollama HTTP call")
        except Exception as exc:
            print(f"Ollama HTTP call setup failed: {exc}")

    # Priority 3: Fallback stubs
    if "Respond ONLY with valid JSON" in system_prompt:
        return json.dumps(
            {
                "department": "Other",
                "period": None,
                "metrics": {},
                "notes": ["LLM unavailable: used fallback extraction."],
                "missing_fields": ["revenue", "total_payroll", "period"],
                "confidence": None,
            }
        )

    if "financial compliance officer" in system_prompt:
        if issues_text := user_prompt.split("Detected issues:\n")[-1].strip():
            return (
                "Risk analysis generated with fallback mode. "
                "Review detected issues manually and validate source documents before final sign-off. "
                f"Detected issues payload: {issues_text[:700]}"
            )
        return "Risk analysis generated with fallback mode. No deterministic issues were detected."

    if "financial reporting specialist" in system_prompt:
        return (
            "Executive summary generated in fallback mode due to unavailable LLM provider. "
            "The report should be treated as a draft pending analyst review."
        )

    return ""


def interpretation_agent(raw_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Agent 1: classify department, period, extract metrics, notes,
    missing fields, and confidence scores.
    """
    system_prompt = (
        "You are a senior financial analyst and document classifier. "
        "You receive JSON with raw_text and raw_tables from a financial document. "
        "Your tasks:\n"
        "1) Identify the most likely department (Finance, HR, Procurement, Operations, or Other).\n"
        "2) Identify the reporting period (e.g., 'Q1 2025', 'FY 2024') if present.\n"
        "3) Extract key financial metrics as a flat object (e.g., revenue, net_profit, total_payroll, total_vendor_spend).\n"
        "4) Extract important notes as an array of strings.\n"
        "5) Identify missing critical fields (e.g., revenue, total_payroll, VAT, period) as an array of field names.\n"
        "6) Provide a confidence score between 0 and 1 for your overall extraction.\n\n"
        "Respond ONLY with valid JSON with keys:\n"
        "`department` (string), `period` (string or null), `metrics` (object),\n"
        "`notes` (array of strings), `missing_fields` (array of strings),\n"
        "`confidence` (number between 0 and 1)."
    )

    user_prompt = (
        "Here is the raw document data:\n\n"
        f"{json.dumps(raw_doc, indent=2)}"
    )

    content = call_llm(system_prompt, user_prompt)

    def _extract_json_from_text(text: str):
        # Try direct JSON
        try:
            return json.loads(text)
        except Exception:
            pass
        # Try fenced code block (```json ... ``` or ``` ... ```)
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            try:
                return json.loads(candidate)
            except Exception:
                pass
        # Try triple tildes
        m = re.search(r"~~~(?:json)?\s*(\{.*?\})\s*~~~", text, re.DOTALL | re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            try:
                return json.loads(candidate)
            except Exception:
                pass
        # Fallback: extract first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass
        return None

    parsed = _extract_json_from_text(content)
    if parsed is None:
        print("Interpretation agent returned non-JSON output:")
        print(content[:2000])
        parsed = {
            "department": "Other",
            "period": None,
            "metrics": {},
            "notes": [content],
            "missing_fields": [],
            "confidence": None,
        }
        return parsed

    # Normalize confidence: ensure numeric or None
    conf = parsed.get("confidence", None)
    if conf is None:
        print("Parsed JSON missing confidence field:", parsed)
        parsed["confidence"] = None
    else:
        try:
            parsed["confidence"] = float(conf)
        except Exception:
            parsed["confidence"] = None
    return parsed


def risk_analysis_agent(aggregated: Dict[str, Any], issues: List[str]) -> str:
    system_prompt = (
        "You are a financial compliance officer. "
        "You receive structured financial data and a list of detected issues. "
        "Write a concise risk analysis in professional tone. "
        "Explain why each issue matters and its potential impact. "
        "Do NOT invent new numbers."
    )
    user_prompt = (
        "Aggregated data:\n"
        f"{json.dumps(aggregated, indent=2)}\n\n"
        "Detected issues:\n"
        f"{json.dumps(issues, indent=2)}"
    )
    return call_llm(system_prompt, user_prompt)


def report_writer_agent(
    aggregated: Dict[str, Any],
    status: str,
    risk_narrative: str,
) -> str:
    system_prompt = (
        "You are a senior financial reporting specialist. "
        "Write an executive summary for a financial compliance report. "
        "Audience: CFO and internal audit. "
        "Use clear, structured paragraphs. "
        "Do NOT invent numbers; refer to them qualitatively only. "
        "You are given: (1) structured data, (2) compliance status, "
        "(3) a risk analysis written by a compliance officer."
    )
    user_prompt = (
        f"Compliance status: {status}\n\n"
        "Aggregated data:\n"
        f"{json.dumps(aggregated, indent=2)}\n\n"
        "Risk analysis:\n"
        f"{risk_narrative}"
    )
    return call_llm(system_prompt, user_prompt)