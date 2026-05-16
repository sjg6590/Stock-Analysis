"""Generate ThinkScript via Ollama with basic validation."""

from __future__ import annotations

import logging
import re
from typing import Any

import ollama

from config import settings

logger = logging.getLogger(__name__)

_REQUIRED_KEYWORDS = ("def", "plot", "Alert", "alert", "condition")


class ThinkScriptGenerator:
    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        self.model = model or settings.OLLAMA_MODEL
        self.host = (host or settings.OLLAMA_HOST).rstrip("/")
        self._client = ollama.Client(host=self.host)

    def _chat(self, user: str) -> str:
        r = self._client.chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write thinkScript for thinkorswim scans and alerts. "
                        "Output only valid thinkScript code, no markdown. "
                        "Use AddLabel for debug. Combine conditions with AND for a single alert."
                    ),
                },
                {"role": "user", "content": user},
            ],
            options={"temperature": 0.2},
            stream=False,
        )
        return r["message"]["content"]

    def _strip_fences(self, text: str) -> str:
        t = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        t = re.sub(r"```(?:thinkscript|text)?\s*", "", t, flags=re.IGNORECASE).strip()
        return t.replace("```", "").strip()

    def _validate(self, code: str) -> bool:
        lower = code.lower()
        return any(k.lower() in lower for k in _REQUIRED_KEYWORDS) and len(code) > 20

    def generate_alert(self, criteria: dict[str, Any]) -> str:
        user = f"Generate thinkScript for a study that fires an alert when ALL are true:\n{criteria!r}\nInclude AddLabel debug lines."
        raw = self._chat(user)
        code = self._strip_fences(raw)
        if not self._validate(code):
            logger.warning("ThinkScript validation weak; returning best-effort output")
        return code

    def generate_buy_signal_alert(self, ticker: str, target_price: float, conditions: list[str]) -> str:
        cond = ", ".join(conditions) if conditions else "close crosses above reference level"
        user = (
            f"thinkScript for symbol context {ticker}: alert when price is within 2% below {target_price} "
            f"and ({cond}). Use def variables and AddLabel for debug."
        )
        return self._strip_fences(self._chat(user))
