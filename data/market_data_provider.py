"""Schwab / yfinance facade for market data.

Single entry-point for OHLCV charts, movers, and live quotes.
Falls back to yfinance when Schwab is disabled or unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """Delegates to Schwab when enabled, otherwise yfinance.

    Usage:
        mdp = MarketDataProvider()
        df = mdp.get_ohlcv("AAPL")         # daily bars
        source = mdp.source_label()         # "Schwab" or "Yahoo Finance (fallback)"
    """

    def __init__(self) -> None:
        self._schwab: Any = None   # lazy SchwabMarketData
        self._yfinance: Any = None  # lazy StockFetcher
        self._last_source = "unknown"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def source_label(self) -> str:
        return self._last_source

    def schwab_available(self) -> bool:
        """True when market data features are enabled and token exists."""
        if not (settings.USE_SCHWAB and settings.USE_SCHWAB_MARKET_DATA):
            return False
        try:
            from data.fetchers.schwab_fetcher import SchwabFetcher

            return SchwabFetcher().is_authenticated()
        except Exception:
            return False

    def get_ohlcv(self, ticker: str, period_days: int = 365) -> pd.DataFrame:
        """Daily OHLCV bars. Columns: open, high, low, close, volume. DatetimeIndex."""
        if settings.USE_SCHWAB_FOR_CHARTS and self.schwab_available():
            try:
                df = self._schwab_md().get_daily_bars(ticker, period_days)
                if not df.empty:
                    self._last_source = "Schwab"
                    return df
                logger.debug("Schwab returned empty history for %s; falling back", ticker)
            except Exception as exc:
                logger.warning("Schwab OHLCV(%s) failed, falling back: %s", ticker, exc)

        df = self._yfinance_ohlcv(ticker)
        self._last_source = "Yahoo Finance (fallback)"
        return df

    def get_live_quote(self, ticker: str) -> dict[str, Any]:
        """Enriched live quote dict."""
        if self.schwab_available():
            try:
                q = self._schwab_md().get_quote_enriched(ticker)
                if "error" not in q:
                    self._last_source = "Schwab"
                    return q
            except Exception as exc:
                logger.warning("Schwab quote(%s) failed: %s", ticker, exc)

        # yfinance fallback
        try:
            fund = self._yf().get_fundamentals(ticker)
            self._last_source = "Yahoo Finance (fallback)"
            return {
                "ticker": ticker.upper(),
                "last_price": fund.get("current_price"),
                "52_week_high": fund.get("52_week_high"),
                "52_week_low": fund.get("52_week_low"),
                "prev_close": fund.get("previous_close"),
            }
        except Exception as exc:
            logger.warning("yfinance quote(%s) failed: %s", ticker, exc)
            return {"ticker": ticker.upper(), "error": str(exc)}

    def get_movers(self, index: str = "$SPX", sort: str = "PERCENT_CHANGE_UP", limit: int = 20) -> list[dict[str, Any]]:
        """Index movers. Returns empty list when Schwab unavailable."""
        if not (settings.USE_SCHWAB_FOR_MOVERS and self.schwab_available()):
            return []
        try:
            return self._schwab_md().get_movers(index=index, sort=sort, limit=limit)
        except Exception as exc:
            logger.warning("get_movers(%s): %s", index, exc)
            return []

    def is_market_open_now(self) -> bool | None:
        """Schwab session status; None if unavailable."""
        if not (settings.USE_SCHWAB_MARKET_HOURS and self.schwab_available()):
            return None
        return self._schwab_md().is_market_open_now()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _schwab_md(self) -> Any:
        if self._schwab is None:
            from data.fetchers.schwab_market_data import SchwabMarketData

            self._schwab = SchwabMarketData()
        return self._schwab

    def _yf(self) -> Any:
        if self._yfinance is None:
            from data.fetchers.yfinance_fetcher import StockFetcher

            self._yfinance = StockFetcher()
        return self._yfinance

    def _yfinance_ohlcv(self, ticker: str) -> pd.DataFrame:
        try:
            raw = self._yf().get_price_history(ticker)
            # Normalise column names to lowercase to match Schwab output
            raw.columns = [c.lower() for c in raw.columns]
            if "adj close" in raw.columns and "close" not in raw.columns:
                raw = raw.rename(columns={"adj close": "close"})
            return raw
        except Exception as exc:
            logger.warning("yfinance OHLCV(%s) failed: %s", ticker, exc)
            return pd.DataFrame()
