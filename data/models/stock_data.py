"""Dataclass-style schema for stock screening payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StockRecord:
    """Structured stock data passed to the screener."""

    ticker: str
    fundamentals: dict[str, Any] = field(default_factory=dict)
    news: list[dict[str, Any]] = field(default_factory=list)
    sector_pe: float | None = None

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "fundamentals": self.fundamentals,
            "news": self.news,
            "sector_pe": self.sector_pe,
        }
