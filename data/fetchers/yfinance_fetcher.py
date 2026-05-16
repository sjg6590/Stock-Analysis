"""Yahoo Finance fundamentals and price history (rate-limit friendly)."""

from __future__ import annotations

import logging
import random
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, TypeVar

import pandas as pd
import yfinance as yf

from config import settings

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# One in-process Yahoo session at a time (avoids 429s when using thread pools).
_yahoo_lock = threading.Lock()


def _jittered_delay(seconds: float) -> None:
    if seconds <= 0:
        return
    time.sleep(seconds + random.uniform(0, min(0.35, seconds * 0.25)))


def yahoo_network_call(fn: Callable[[], _T], delay_sec: float | None = None) -> _T:
    """Run one yfinance operation with global lock + pacing (e.g. news fallback)."""
    d = settings.YFIN_DELAY_SEC if delay_sec is None else delay_sec
    with _yahoo_lock:
        _jittered_delay(d)
        return fn()


def _transient_yahoo_error(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    needles = (
        "429",
        "too many requests",
        "rate limit",
        "503",
        "502",
        "504",
        "timeout",
        "temporarily unavailable",
        "unexpected end",
        "connection reset",
        "connection aborted",
        "jsondecode",
        "failed to decrypt",
        "blocked",
        "forbidden",
        "curl",
    )
    return any(n in msg for n in needles)


# Approximate sector median P/E when basket lookup is unavailable (rough guide only).
_SECTOR_PE_MEDIANS: dict[str, float] = {
    "Technology": 28.0,
    "Healthcare": 22.0,
    "Consumer Cyclical": 20.0,
    "Consumer Defensive": 18.0,
    "Consumer Discretionary": 20.0,
    "Financial Services": 14.0,
    "Industrials": 19.0,
    "Energy": 12.0,
    "Utilities": 16.0,
    "Real Estate": 17.0,
    "Basic Materials": 16.0,
    "Communication Services": 18.0,
}


class StockFetcher:
    """Pull fundamentals and OHLCV via yfinance."""

    def __init__(
        self,
        delay_sec: float | None = None,
        max_retries: int | None = None,
        backoff_base: float | None = None,
    ) -> None:
        self._delay_sec = settings.YFIN_DELAY_SEC if delay_sec is None else delay_sec
        self._max_retries = settings.YFIN_MAX_RETRIES if max_retries is None else max_retries
        self._backoff_base = settings.YFIN_BACKOFF_BASE_SEC if backoff_base is None else backoff_base
        self._sector_pe_cache: dict[str, float] = {}

    def _with_yahoo(self, operation: str, fn: Callable[[], _T]) -> _T:
        last: BaseException | None = None
        for attempt in range(self._max_retries):
            try:
                with _yahoo_lock:
                    _jittered_delay(self._delay_sec)
                    return fn()
            except Exception as e:
                last = e
                if not _transient_yahoo_error(e) or attempt >= self._max_retries - 1:
                    raise
                wait = self._backoff_base * (2**attempt) + random.uniform(0, 1.0)
                logger.warning(
                    "yfinance %s attempt %s/%s: %s — backoff %.1fs",
                    operation,
                    attempt + 1,
                    self._max_retries,
                    e,
                    wait,
                )
                time.sleep(wait)
        assert last is not None
        raise last

    def get_fundamentals(self, ticker: str) -> dict[str, Any]:
        """Return normalized fundamentals dict for screening."""

        def work() -> dict[str, Any]:
            t = yf.Ticker(ticker)
            info: dict[str, Any] = dict(t.info or {})

            def _num(key: str) -> float | None:
                v = info.get(key)
                if v is None or v == "N/A":
                    return None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            fin = t.financials
            revenue_growth: float | None = None
            earnings_growth: float | None = None
            if fin is not None and not fin.empty and fin.shape[1] >= 2:
                try:
                    rev = fin.loc["Total Revenue"] if "Total Revenue" in fin.index else None
                    if rev is not None:
                        y0, y1 = rev.iloc[0], rev.iloc[1]
                        if y1 and y1 != 0:
                            revenue_growth = float((y0 - y1) / abs(y1))
                except Exception:
                    revenue_growth = None

            inc = t.income_stmt
            if inc is not None and not inc.empty and inc.shape[1] >= 2:
                try:
                    ni = inc.loc["Net Income"] if "Net Income" in inc.index else None
                    if ni is not None:
                        y0, y1 = ni.iloc[0], ni.iloc[1]
                        if y1 and y1 != 0:
                            earnings_growth = float((y0 - y1) / abs(y1))
                except Exception:
                    earnings_growth = None

            return {
                "ticker": ticker,
                "current_price": _num("currentPrice") or _num("regularMarketPrice"),
                "previous_close": _num("previousClose"),
                "52_week_high": _num("fiftyTwoWeekHigh"),
                "52_week_low": _num("fiftyTwoWeekLow"),
                "pe_ratio": _num("trailingPE"),
                "forward_pe": _num("forwardPE"),
                "peg_ratio": _num("pegRatio"),
                "price_to_book": _num("priceToBook"),
                "price_to_sales": _num("priceToSalesTrailing12Months"),
                "ev_to_ebitda": _num("enterpriseToEbitda") or _num("enterpriseToRevenue"),
                "market_cap": _num("marketCap"),
                "enterprise_value": _num("enterpriseValue"),
                "debt_to_equity": _num("debtToEquity"),
                "current_ratio": _num("currentRatio"),
                "quick_ratio": _num("quickRatio"),
                "revenue_growth": revenue_growth,
                "earnings_growth": earnings_growth,
                "profit_margin": _num("profitMargins"),
                "operating_margin": _num("operatingMargins"),
                "roe": _num("returnOnEquity"),
                "roa": _num("returnOnAssets"),
                "dividend_yield": _num("dividendYield"),
                "payout_ratio": _num("payoutRatio"),
                "analyst_target_price": _num("targetMeanPrice"),
                "analyst_recommendation": info.get("recommendationKey"),
                "sector": info.get("sector") or info.get("industry"),
                "industry": info.get("industry"),
                "company_name": info.get("longName") or info.get("shortName") or ticker,
                "number_of_analyst_opinions": info.get("numberOfAnalystOpinions"),
            }

        return self._with_yahoo(f"fundamentals({ticker})", work)

    def get_price_history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        def work() -> pd.DataFrame:
            df = yf.download(ticker, period=period, progress=False, auto_adjust=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            return df

        return self._with_yahoo(f"history({ticker})", work)

    def get_sector_pe(self, sector: str) -> float:
        """Estimate sector average P/E via ETF proxy or hardcoded median."""
        if not sector:
            return 20.0
        if sector in self._sector_pe_cache:
            return self._sector_pe_cache[sector]

        etf_map = {
            "Technology": "XLK",
            "Healthcare": "XLV",
            "Consumer Cyclical": "XLY",
            "Consumer Discretionary": "XLY",
            "Financial Services": "XLF",
            "Communication Services": "XLC",
            "Industrials": "XLI",
            "Energy": "XLE",
        }
        sym = etf_map.get(sector)
        if sym:

            def work() -> float | None:
                etf = yf.Ticker(sym)
                pe = etf.info.get("trailingPE")
                return float(pe) if pe else None

            try:
                pe = self._with_yahoo(f"sector_etf({sym})", work)
                if pe:
                    self._sector_pe_cache[sector] = pe
                    return pe
            except Exception:
                pass
        med = float(_SECTOR_PE_MEDIANS.get(sector, 20.0))
        self._sector_pe_cache[sector] = med
        return med

    def get_earnings_calendar(self, ticker: str) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            t = yf.Ticker(ticker)
            cal = getattr(t, "calendar", None)
            out: dict[str, Any] = {"next_earnings_date": None, "eps_estimate": None, "revenue_estimate": None}
            if cal is None:
                return out
            try:
                if isinstance(cal, dict):
                    if "Earnings Date" in cal:
                        ed = cal["Earnings Date"]
                        if hasattr(ed, "iloc"):
                            out["next_earnings_date"] = str(ed.iloc[0]) if len(ed) else None
                        elif isinstance(ed, (list, tuple)) and ed:
                            out["next_earnings_date"] = str(ed[0])
                    if "EPS Estimate" in cal:
                        e = cal["EPS Estimate"]
                        out["eps_estimate"] = float(e.iloc[0]) if hasattr(e, "iloc") and len(e) else None
                else:
                    df = cal
                    if hasattr(df, "empty") and not df.empty:
                        out["next_earnings_date"] = str(df.index[0]) if len(df.index) else None
            except Exception:
                pass
            return out

        return self._with_yahoo(f"calendar({ticker})", work)
