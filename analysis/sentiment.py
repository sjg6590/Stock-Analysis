"""News sentiment via local Ollama (optional)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import ollama

from config import settings

logger = logging.getLogger(__name__)


def score_sentiment(headlines: list[str], host: str | None = None, model: str | None = None) -> dict[str, Any]:
    if not headlines:
        return {"sentiment": "NEUTRAL", "summary": "No headlines."}
    h = host or settings.OLLAMA_HOST
    m = model or settings.OLLAMA_MODEL
    client = ollama.Client(host=h.rstrip("/"))
    prompt = "Headlines:\n" + "\n".join(f"- {s[:200]}" for s in headlines[:15])
    prompt += '\nReturn JSON only: {"sentiment":"POSITIVE|NEUTRAL|NEGATIVE","one_line":"..."}'
    try:
        r = client.chat(
            model=m,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
            stream=False,
        )
        text = r["message"]["content"]
        mch = re.search(r"\{.*\}", text, re.DOTALL)
        if not mch:
            raise ValueError("no json")
        return json.loads(mch.group())
    except Exception as e:
        logger.warning("sentiment failed: %s", e)
        return {"sentiment": "NEUTRAL", "one_line": str(e)}
