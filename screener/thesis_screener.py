"""Discover tickers from a natural-language investment thesis via Ollama or Claude."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

_SYSTEM = """
You are a financial research assistant. Given an investment thesis, identify the most
relevant publicly-traded US stocks and ETFs that give direct exposure to that theme.

Return ONLY a JSON object with this exact structure — no markdown, no explanation:
{
  "theme": "one-line summary of the investment theme",
  "stocks": [
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "rationale": "one sentence"},
    ...
  ],
  "etfs": [
    {"symbol": "SOXX", "name": "iShares Semiconductor ETF", "rationale": "one sentence"},
    ...
  ]
}

Rules:
- stocks: 10–20 individual equities with the most direct exposure
- etfs: 3–6 thematic or sector ETFs for broad exposure
- US-listed only (NYSE / NASDAQ / AMEX)
- Order by relevance to the thesis (most relevant first)
- Prefer liquid, well-known names; include smaller names only when highly relevant
"""


def _parse(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip().replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON in LLM response: {cleaned[:300]}")
    return json.loads(match.group())


class ThesisScreener:
    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        self._use_claude = settings.LLM_PROVIDER == "claude"
        if self._use_claude:
            import anthropic
            self._claude = anthropic.Anthropic(
                api_key=settings.ANTHROPIC_API_KEY or None
            )
            self.model = model or settings.CLAUDE_MODEL
        else:
            import ollama
            self.model = model or settings.OLLAMA_MODEL
            self.host = (host or settings.OLLAMA_HOST).rstrip("/")
            self._ollama = ollama.Client(host=self.host)

    def _call_ollama(self, thesis: str) -> str:
        resp = self._ollama.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Investment thesis:\n{thesis.strip()}"},
            ],
            options={"temperature": 0.3},
            stream=False,
        )
        return resp["message"]["content"]

    def _call_claude(self, thesis: str) -> str:
        resp = self._claude.messages.create(
            model=self.model,
            max_tokens=2048,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"Investment thesis:\n{thesis.strip()}"}],
        )
        return next((block.text for block in resp.content if block.type == "text"), "")

    def discover(self, thesis: str) -> dict[str, Any]:
        """
        Returns {"theme": str, "stocks": [...], "etfs": [...]} with tickers and rationales.
        Raises on complete failure.
        """
        last_err: str | None = None
        for attempt in range(3):
            try:
                text = self._call_claude(thesis) if self._use_claude else self._call_ollama(thesis)
                parsed = _parse(text)
                parsed.setdefault("stocks", [])
                parsed.setdefault("etfs", [])
                return parsed
            except Exception as e:
                last_err = str(e)
                logger.warning("thesis discovery attempt %d: %s", attempt + 1, e)
        raise RuntimeError(f"Thesis discovery failed after 3 attempts: {last_err}")

    def tickers_from_discovery(self, discovery: dict[str, Any]) -> list[str]:
        """Flatten stocks + ETFs into a deduplicated ticker list (stocks first)."""
        seen: set[str] = set()
        out: list[str] = []
        for item in [*discovery.get("stocks", []), *discovery.get("etfs", [])]:
            sym = str(item.get("symbol", "")).strip().upper()
            if sym and sym not in seen:
                seen.add(sym)
                out.append(sym)
        return out
