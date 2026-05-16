"""Lightweight valuation helpers (not full DCF)."""

from __future__ import annotations

from typing import Any


def implied_upside_percent(current: float | None, target: float | None) -> float | None:
    if current is None or target is None or current == 0:
        return None
    return (float(target) - float(current)) / float(current) * 100.0


def simple_fair_pe_value(
    eps: float | None,
    fair_pe: float,
) -> float | None:
    """Price = EPS * fair P/E when EPS known."""
    if eps is None or eps <= 0:
        return None
    return float(eps) * float(fair_pe)


def ratio_vs_sector(stock_pe: float | None, sector_pe: float | None) -> dict[str, Any]:
    if stock_pe is None or sector_pe is None or sector_pe == 0:
        return {"relative_pe": None, "label": "unknown"}
    rel = float(stock_pe) / float(sector_pe)
    if rel < 0.85:
        label = "below_sector"
    elif rel > 1.15:
        label = "above_sector"
    else:
        label = "inline_sector"
    return {"relative_pe": rel, "label": label}
