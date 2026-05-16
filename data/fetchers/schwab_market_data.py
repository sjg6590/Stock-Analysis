"""Normalized Schwab market data API.

All public methods return stable dicts/DataFrames regardless of
underlying schwab-py response shape changes.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

# Schwab Movers.Index — no $VIX in API
_INDEX_CHOICES = ("$SPX", "$COMPX", "$DJI", "NYSE", "NASDAQ")


class SchwabMarketData:
    """Thin wrapper around SchwabFetcher that normalises market data responses."""

    def __init__(self) -> None:
        self._fetcher: Any = None

    def _f(self) -> Any:
        if self._fetcher is None:
            from data.fetchers.schwab_fetcher import SchwabFetcher

            self._fetcher = SchwabFetcher()
        return self._fetcher

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def get_daily_bars(self, ticker: str, period_days: int = 365) -> pd.DataFrame:
        """Daily OHLCV bars, DatetimeIndex, columns: open high low close volume.

        Returns empty DataFrame if unavailable.
        """
        try:
            return self._f().get_price_history_daily(ticker, period_days)
        except Exception as exc:
            logger.warning("get_daily_bars(%s): %s", ticker, exc)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Quotes
    # ------------------------------------------------------------------

    def get_quote_enriched(self, ticker: str) -> dict[str, Any]:
        """Last trade with spread, day change %, 52-week range."""
        try:
            raw = self._f().get_quote(ticker)
        except Exception as exc:
            logger.warning("get_quote_enriched(%s): %s", ticker, exc)
            return {"ticker": ticker.upper(), "error": str(exc)}

        q = raw.get("raw") or {}
        rt = q.get("regular") or {}
        ext = q.get("extended") or {}

        last = raw.get("last_price")
        prev_close = q.get("closePrice") or rt.get("regularMarketLastPrice")
        day_change_pct: float | None = None
        if last and prev_close and float(prev_close) != 0:
            day_change_pct = (float(last) - float(prev_close)) / float(prev_close) * 100

        return {
            "ticker": ticker.upper(),
            "last_price": last,
            "bid": raw.get("bid"),
            "ask": raw.get("ask"),
            "volume": raw.get("volume"),
            "day_change_pct": day_change_pct,
            "52_week_high": q.get("52WeekHigh") or q.get("fiftyTwoWeekHigh"),
            "52_week_low": q.get("52WeekLow") or q.get("fiftyTwoWeekLow"),
            "prev_close": prev_close,
        }

    def get_quote_fundamentals(self, ticker: str) -> dict[str, Any]:
        """Fundamental fields (PE, EPS, etc.) from Schwab if available."""
        try:
            c = self._f()._get_client()
            # Request FUNDAMENTAL field group if schwab-py exposes it
            try:
                fields = [c.Quote.Fields.FUNDAMENTAL]
            except AttributeError:
                fields = None
            if fields:
                r = c.get_quote(ticker.upper(), fields=fields).json()
            else:
                r = c.get_quote(ticker.upper()).json()
            q = r.get(ticker.upper(), r.get(ticker, {}))
            fund = q.get("fundamental") or {}
            return {
                "ticker": ticker.upper(),
                "pe_ratio": fund.get("peRatio") or fund.get("trailingPE"),
                "eps": fund.get("eps"),
                "eps_ttm": fund.get("epsTTM"),
                "dividend_yield": fund.get("dividendYield"),
                "52_week_high": fund.get("high52") or fund.get("fiftyTwoWeekHigh"),
                "52_week_low": fund.get("low52") or fund.get("fiftyTwoWeekLow"),
                "beta": fund.get("beta"),
                "market_cap": fund.get("marketCap") or fund.get("marketCapitalization"),
            }
        except Exception as exc:
            logger.warning("get_quote_fundamentals(%s): %s", ticker, exc)
            return {"ticker": ticker.upper(), "error": str(exc)}

    # ------------------------------------------------------------------
    # Movers
    # ------------------------------------------------------------------

    def get_movers(
        self,
        index: str = "$SPX",
        sort: str = "PERCENT_CHANGE_UP",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Top movers for an index, normalised.

        sort: PERCENT_CHANGE_UP | PERCENT_CHANGE_DOWN | VOLUME | TRADES
        """
        if index not in _INDEX_CHOICES:
            index = "$SPX"
        try:
            rows = self._f().get_movers(index, sort_order=sort)
            return rows[:limit]
        except Exception as exc:
            logger.warning("get_movers(%s): %s", index, exc)
            return []

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    def get_options_summary(self, ticker: str) -> dict[str, Any]:
        """ATM IV, put/call OI ratio, nearest expiry — from top 5 strikes."""
        try:
            raw = self._f().get_options_chain(ticker)
        except Exception as exc:
            logger.warning("get_options_summary(%s): %s", ticker, exc)
            return {"ticker": ticker.upper(), "error": str(exc)}

        underlying = raw.get("underlyingPrice") or raw.get("underlying", {}).get("mark")
        expiry_dates: list[str] = []
        call_vol = put_vol = 0
        call_oi = put_oi = 0

        for side, key in (("call", "callExpDateMap"), ("put", "putExpDateMap")):
            exp_map = raw.get(key) or {}
            for expiry, strikes in exp_map.items():
                date_part = expiry.split(":")[0] if ":" in expiry else expiry
                if date_part not in expiry_dates:
                    expiry_dates.append(date_part)
                for contracts in strikes.values():
                    for contract in (contracts if isinstance(contracts, list) else [contracts]):
                        vol = contract.get("totalVolume") or 0
                        oi = contract.get("openInterest") or 0
                        if side == "call":
                            call_vol += int(vol)
                            call_oi += int(oi)
                        else:
                            put_vol += int(vol)
                            put_oi += int(oi)

        nearest_expiry = min(expiry_dates) if expiry_dates else None
        total_vol = call_vol + put_vol
        put_call_ratio = put_vol / call_vol if call_vol else None

        # ATM IV: find nearest strike to underlying in first expiry's calls
        atm_iv: float | None = None
        if underlying and expiry_dates:
            first_exp = min(expiry_dates)
            for exp_key, strikes in (raw.get("callExpDateMap") or {}).items():
                if not exp_key.startswith(first_exp):
                    continue
                best_strike: float | None = None
                best_iv: float | None = None
                for strike_str, contracts in strikes.items():
                    try:
                        strike = float(strike_str)
                    except ValueError:
                        continue
                    if best_strike is None or abs(strike - float(underlying)) < abs(best_strike - float(underlying)):
                        for c_ in (contracts if isinstance(contracts, list) else [contracts]):
                            iv = c_.get("volatility") or c_.get("impliedVolatility")
                            if iv is not None:
                                best_strike = strike
                                best_iv = float(iv)
                atm_iv = best_iv
                break

        return {
            "ticker": ticker.upper(),
            "underlying_price": underlying,
            "nearest_expiry": nearest_expiry,
            "atm_iv": atm_iv,
            "call_volume": call_vol,
            "put_volume": put_vol,
            "total_volume": total_vol,
            "put_call_volume_ratio": put_call_ratio,
            "call_open_interest": call_oi,
            "put_open_interest": put_oi,
        }

    # ------------------------------------------------------------------
    # Market hours
    # ------------------------------------------------------------------

    def get_market_hours(self, markets: list[str] | None = None, date: str | None = None) -> dict[str, Any]:
        try:
            return self._f().get_market_hours(markets=markets, date=date)
        except Exception as exc:
            logger.warning("get_market_hours: %s", exc)
            return {}

    def is_market_open_now(self) -> bool | None:
        """Return True/False from Schwab; None if unavailable."""
        try:
            return self._f().is_equity_session_open()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Instrument search
    # ------------------------------------------------------------------

    def search_symbols(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Symbol search; returns list of {ticker, description, exchange, type}."""
        try:
            c = self._f()._get_client()
            try:
                proj = c.Instrument.Projection.SYMBOL_SEARCH
            except AttributeError:
                proj = "symbol-search"
            r = c.search_instruments(symbols=query, projection=proj).json()
        except Exception as exc:
            logger.warning("search_symbols(%s): %s", query, exc)
            return []

        # Response: {"instruments": [...]} or dict keyed by ticker
        items: list[Any] = []
        if isinstance(r, list):
            items = r
        elif isinstance(r, dict):
            items = list(r.get("instruments") or r.values())

        out: list[dict[str, Any]] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "ticker": item.get("symbol") or item.get("ticker"),
                    "description": item.get("description") or item.get("name"),
                    "exchange": item.get("exchange"),
                    "type": item.get("assetType") or item.get("instrumentType") or item.get("type"),
                }
            )
        return out
