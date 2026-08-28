"""
Gemini Flash client (automatic failover, README §4, §6).

Used only when Groq fails or rate-limits mid-batch. Same contract as
groq_client.adjudicate_batch: takes a prompt, returns a parsed JSON list.
"""
from __future__ import annotations
import json
from typing import List, Dict, Any

import requests

from app.config import settings


class GeminiError(Exception):
    pass


def adjudicate_batch(prompt: str) -> List[Dict[str, Any]]:
    if not settings.GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY not configured")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    resp = requests.post(url, json=body, timeout=30)
    if resp.status_code == 429:
        raise GeminiError("Gemini rate limit hit")
    resp.raise_for_status()

    data = resp.json()
    content = data["candidates"][0]["content"]["parts"][0]["text"]
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v
            raise GeminiError("Response JSON object did not contain an array")
        return parsed
    except json.JSONDecodeError as e:
        raise GeminiError(f"Could not parse Gemini response as JSON: {e}")
