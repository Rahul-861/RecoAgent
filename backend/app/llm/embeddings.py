"""
Semantic embeddings for Stage 2 (README §4, §6).

Tries a free hosted embedding endpoint (Gemini's embedding model) when
GEMINI_API_KEY is configured. If no key is set -- or the call fails -- it
falls back to a dependency-free local embedding (character n-gram hashing
vector), so the pipeline still produces meaningful semantic-similarity
matches offline / without any API key, which matters for a live demo that
must not die if a key is missing or a free tier is briefly exhausted.
"""
from __future__ import annotations
import hashlib
import math
import re
from typing import List

import requests

from app.config import settings

_VECTOR_DIM = 256


def _local_embedding(text: str) -> List[float]:
    """Cheap, deterministic, dependency-free embedding via hashed character n-grams."""
    text = re.sub(r"\s+", " ", (text or "").lower()).strip()
    vec = [0.0] * _VECTOR_DIM
    if not text:
        return vec
    n = 3
    grams = [text[i:i + n] for i in range(max(len(text) - n + 1, 1))]
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest(), 16)
        vec[h % _VECTOR_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _gemini_embedding(text: str) -> List[float] | None:
    if not settings.GEMINI_API_KEY:
        return None
    try:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/embedding-001:embedContent"
            f"?key={settings.GEMINI_API_KEY}"
        )
        resp = requests.post(
            url,
            json={"model": "models/embedding-001", "content": {"parts": [{"text": text}]}},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]["value"]
    except Exception:
        return None


def get_embedding(text: str) -> List[float]:
    embedding = _gemini_embedding(text)
    if embedding is not None:
        return embedding
    return _local_embedding(text)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)
