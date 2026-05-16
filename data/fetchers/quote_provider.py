"""Unified price API for alerts and UI.

Tries Schwab when enabled + token exists; falls back to yfinance.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


class QuoteProvider:
    """Single entry-point for last-trade prices.

    Cache is per-instance and keyed by ticker; TTL controlled by
    settings.SCHWAB_QUOTE_CACHE_SEC.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, float | None]] = {}  # ticker -> (ts, price)
        self._schwab: Any = None  # lazy SchwabFetcher
        self._yfinance: Any = None  # lazy StockFetcher

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True when Schwab is enabled and a valid token exists."""
        if not (settings.USE_SCHWAB and settings.USE_SCHWAB_FOR_ALERTS):
            return False
        try:
            from data.fetchers.schwab_fetcher import SchwabFetcher

            return SchwabFetcher().is_authenticated()
        except Exception:
            return False

    def get_last_price(self, ticker: str) -> float | None:
        prices = self.get_last_prices([ticker])
        return prices.get(ticker.upper())

    def get_last_prices(self, tickers: list[str]) -> dict[str, float | None]:
        """Return {TICKER: last_price_or_None} for each ticker.

        Batch Schwab when possible; fall back to yfinance per-ticker on failure.
        """
        if not tickers:
            return {}

        syms = [t.upper() for t in tickers]
        now = time.monotonic()
        ttl = settings.SCHWAB_QUOTE_CACHE_SEC

        # Split into cached vs needs-fetch
        result: dict[str, float | None] = {}
        stale: list[str] = []
        for sym in syms:
            cached_ts, cached_px = self._cache.get(sym, (0.0, None))
            if now - cached_ts < ttl and cached_px is not None:
                result[sym] = cached_px
            else:
                stale.append(sym)

        if not stale:
            return result

        # Try Schwab batch first
        if settings.USE_SCHWAB and settings.USE_SCHWAB_FOR_ALERTS:
            schwab_prices = self._fetch_schwab_batch(stale)
            fetched_ok: list[str] = []
            still_missing: list[str] = []
            for sym in stale:
                px = schwab_prices.get(sym)
                if px is not None:
                    result[sym] = px
                    self._cache[sym] = (now, px)
                    fetched_ok.append(sym)
                else:
                    still_missing.append(sym)
            stale = still_missing

        # yfinance fallback for anything still missing
        for sym in stale:
            px = self._fetch_yfinance(sym)
            result[sym] = px
            self._cache[sym] = (now, px)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_schwab_batch(self, tickers: list[str]) -> dict[str, float | None]:
        try:
            if self._schwab is None:
                from data.fetchers.schwab_fetcher import SchwabFetcher

                self._schwab = SchwabFetcher()
            return self._schwab.get_quotes_batch(tickers)
        except Exception as exc:
            logger.warning("Schwab batch quote failed, falling back to yfinance: %s", exc)
            return {}

    def _fetch_yfinance(self, ticker: str) -> float | None:
        try:
            if self._yfinance is None:
                from data.fetchers.yfinance_fetcher import StockFetcher

                self._yfinance = StockFetcher(delay_sec=0.3)
            fund = self._yfinance.get_fundamentals(ticker)
            px = fund.get("current_price")
            return float(px) if px is not None else None
        except Exception as exc:
            logger.warning("yfinance fallback failed for %s: %s", ticker, exc)
            return None
