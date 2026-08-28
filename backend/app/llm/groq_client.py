"""
Groq API client (primary LLM, README §4).

Sends one structured prompt per batch of ambiguous pairs and expects a
strict JSON array back. Raises on any failure (auth, rate limit, bad
JSON) so the caller (llm_adjudicate.py) can fail over to Gemini.
"""
from __future__ import annotations
import json
from typing import List, Dict, Any

import requests

from app.config import settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(Exception):
    pass


def adjudicate_batch(prompt: str) -> List[Dict[str, Any]]:
    if not settings.GROQ_API_KEY:
        raise GroqError("GROQ_API_KEY not configured")

    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "You are a meticulous financial reconciliation assistant. "
                                           "Respond with ONLY a valid JSON array, no prose, no markdown fences."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"} if False else None,
    }
    body = {k: v for k, v in body.items() if v is not None}

    resp = requests.post(GROQ_URL, headers=headers, json=body, timeout=30)
    if resp.status_code == 429:
        raise GroqError("Groq rate limit hit")
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_json_array(content)


def _parse_json_array(content: str) -> List[Dict[str, Any]]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json\n", "", 1) if cleaned.startswith("json") else cleaned
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            # some models wrap the array in a top-level object
            for v in parsed.values():
                if isinstance(v, list):
                    return v
            raise GroqError("Response JSON object did not contain an array")
        return parsed
    except json.JSONDecodeError as e:
        raise GroqError(f"Could not parse Groq response as JSON: {e}")
