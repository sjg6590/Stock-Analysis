"""Thin orchestration layer above SchwabFetcher.

Normalises positions, computes overlap with screener/watchlist, and
surfaces a single is_connected() check for the UI.
"""

from __future__ import annotations

import logging
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


class SchwabNotConnectedError(RuntimeError):
    """Raised when Schwab is unavailable (token missing or disabled)."""


class SchwabService:
    def __init__(self) -> None:
        self._fetcher: Any = None  # lazy SchwabFetcher

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """True when USE_SCHWAB_FOR_PORTFOLIO is on and a valid token exists."""
        if not (settings.USE_SCHWAB and settings.USE_SCHWAB_FOR_PORTFOLIO):
            return False
        return self._get_fetcher().is_authenticated()

    def _get_fetcher(self) -> Any:
        if self._fetcher is None:
            from data.fetchers.schwab_fetcher import SchwabFetcher

            self._fetcher = SchwabFetcher()
        return self._fetcher

    def _require_connection(self) -> Any:
        fetcher = self._get_fetcher()
        if not fetcher.is_authenticated():
            raise SchwabNotConnectedError(
                "Schwab not connected. Run: python main.py schwab auth"
            )
        return fetcher

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    def get_positions_normalized(self) -> list[dict[str, Any]]:
        """Holdings enriched with unrealized_pnl_pct and weight_pct."""
        fetcher = self._require_connection()
        try:
            raw = fetcher.get_portfolio_positions()
        except Exception as exc:
            logger.warning("Schwab get_portfolio_positions failed: %s", exc)
            raise SchwabNotConnectedError(str(exc)) from exc

        # Compute total market value for weight calculation
        total_mv = sum(float(p.get("market_value") or 0) for p in raw)

        normalized: list[dict[str, Any]] = []
        for p in raw:
            avg = p.get("average_price")
            mv = p.get("market_value")
            qty = p.get("quantity")
            pnl_open = p.get("long_open_profit_loss")

            unrealized_pnl_pct: float | None = None
            if avg and qty and avg > 0:
                cost = float(avg) * float(qty)
                if cost > 0 and mv is not None:
                    unrealized_pnl_pct = (float(mv) - cost) / cost * 100

            weight_pct: float | None = None
            if total_mv and total_mv > 0 and mv is not None:
                weight_pct = float(mv) / total_mv * 100

            normalized.append(
                {
                    "ticker": p.get("ticker"),
                    "quantity": qty,
                    "average_price": avg,
                    "market_value": mv,
                    "current_day_pnl": p.get("current_day_pnl"),
                    "open_pnl": pnl_open,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "weight_pct": weight_pct,
                }
            )
        return normalized

    # ------------------------------------------------------------------
    # Screener overlap
    # ------------------------------------------------------------------

    def get_overlap_with_screening(self) -> dict[str, Any]:
        """Join held positions with today's BUY candidates and watchlist.

        Returns:
            {
                "held_tickers": set[str],
                "buy_candidates_owned": list[dict],   # BUY candidates you hold
                "buy_candidates_not_owned": list[dict],
                "watchlist_with_held": list[dict],    # watchlist rows + "held" bool
            }
        """
        from storage import queries

        positions = self.get_positions_normalized()
        held_tickers = {p["ticker"] for p in positions if p.get("ticker")}

        buy_candidates = queries.today_top_buy_candidates(100)
        watchlist = queries.list_watchlist()

        owned = [r for r in buy_candidates if r.get("ticker") in held_tickers]
        not_owned = [r for r in buy_candidates if r.get("ticker") not in held_tickers]

        wl_with_held = [
            {**w, "held": w.get("ticker") in held_tickers}
            for w in watchlist
        ]

        return {
            "held_tickers": held_tickers,
            "buy_candidates_owned": owned,
            "buy_candidates_not_owned": not_owned,
            "watchlist_with_held": wl_with_held,
        }
