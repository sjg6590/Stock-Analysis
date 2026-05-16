"""
Schwab Trader API via schwab-py.

OAuth tokens are cached locally (see SCHWAB_TOKEN_PATH in settings).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


class SchwabAuthError(RuntimeError):
    """Raised when the Schwab token is missing or expired."""


class SchwabFetcher:
    def __init__(self) -> None:
        self._client: Any = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def authenticate(self) -> Any:
        """Interactive OAuth; tokens saved to schwab_token.json."""
        try:
            from schwab import auth
        except ImportError as e:
            raise RuntimeError("Install schwab-py: pip install schwab-py") from e

        token_path = str(settings.SCHWAB_TOKEN_PATH)
        api_key = settings.SCHWAB_CLIENT_ID or os.getenv("SCHWAB_CLIENT_ID", "")
        secret = settings.SCHWAB_CLIENT_SECRET or os.getenv("SCHWAB_CLIENT_SECRET", "")
        callback = settings.SCHWAB_REDIRECT_URI
        if not api_key or not secret:
            raise RuntimeError("Set SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET in .env")

        # Auto-capture redirect on callback port (codes expire in ~30s; manual paste often fails).
        self._client = auth.client_from_login_flow(
            api_key=api_key,
            app_secret=secret,
            callback_url=callback,
            token_path=token_path,
        )
        return self._client

    def is_authenticated(self) -> bool:
        """Return True if the token file exists and the client loads without error."""
        if not settings.SCHWAB_TOKEN_PATH.exists():
            return False
        try:
            from schwab import auth

            auth.client_from_token_file(
                token_path=str(settings.SCHWAB_TOKEN_PATH),
                api_key=settings.SCHWAB_CLIENT_ID,
                app_secret=settings.SCHWAB_CLIENT_SECRET,
            )
            return True
        except Exception:
            return False

    def ensure_authenticated(self) -> Any:
        """Load token or raise SchwabAuthError with a re-auth hint."""
        if not settings.SCHWAB_TOKEN_PATH.exists():
            raise SchwabAuthError(
                "No Schwab token found. Run: python main.py schwab auth"
            )
        try:
            return self._get_client()
        except Exception as exc:
            raise SchwabAuthError(
                f"Schwab token invalid or expired ({exc}). Re-run: python main.py schwab auth"
            ) from exc

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from schwab import auth
        except ImportError as e:
            raise RuntimeError("Install schwab-py: pip install schwab-py") from e
        token_path = str(settings.SCHWAB_TOKEN_PATH)
        if not settings.SCHWAB_TOKEN_PATH.exists():
            raise SchwabAuthError(
                "No Schwab token found. Run: python main.py schwab auth"
            )
        try:
            self._client = auth.client_from_token_file(
                token_path=token_path,
                api_key=settings.SCHWAB_CLIENT_ID,
                app_secret=settings.SCHWAB_CLIENT_SECRET,
            )
        except Exception as exc:
            raise SchwabAuthError(
                f"Schwab token load failed ({exc}). Re-run: python main.py schwab auth"
            ) from exc
        return self._client

    # ------------------------------------------------------------------
    # Quotes
    # ------------------------------------------------------------------

    def get_quote(self, ticker: str) -> dict[str, Any]:
        c = self._get_client()
        r = c.get_quote(ticker).json()
        q = r.get(ticker.upper(), r.get(ticker, {}))
        rt = q.get("regular", {}) if isinstance(q, dict) else {}
        return {
            "ticker": ticker.upper(),
            "last_price": rt.get("regularMarketLastPrice") or q.get("lastPrice"),
            "bid": q.get("bidPrice"),
            "ask": q.get("askPrice"),
            "volume": rt.get("regularMarketVolume") or q.get("totalVolume"),
            "raw": q,
        }

    def get_quotes_batch(self, tickers: list[str]) -> dict[str, float | None]:
        """Fetch last prices for multiple tickers in a single API call.

        Returns {TICKER: last_price_or_None}.
        """
        if not tickers:
            return {}
        c = self._get_client()
        syms = [t.upper() for t in tickers]
        try:
            r = c.get_quotes(symbols=syms).json()
        except Exception:
            # Fallback: try get_quotes with positional arg (older schwab-py versions)
            try:
                r = c.get_quotes(syms).json()
            except Exception as exc:
                logger.warning("Schwab batch quotes failed: %s", exc)
                return {t: None for t in syms}

        result: dict[str, float | None] = {}
        for sym in syms:
            q = r.get(sym, {})
            if not isinstance(q, dict):
                result[sym] = None
                continue
            rt = q.get("regular", {}) or {}
            price = rt.get("regularMarketLastPrice") or q.get("lastPrice")
            result[sym] = float(price) if price is not None else None
        return result

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    def get_portfolio_positions(self) -> list[dict[str, Any]]:
        """Holdings with cost basis and P/L when API returns them."""
        c = self._get_client()
        accts = c.get_account_numbers().json()
        out: list[dict[str, Any]] = []
        for a in accts:
            aid = a.get("hashValue") or a.get("accountNumber")
            if not aid:
                continue
            r = c.get_account(aid, fields=c.Account.Fields.POSITIONS).json()
            for p in r.get("securitiesAccount", {}).get("positions", []) or []:
                inst = p.get("instrument", {}) or {}
                out.append(
                    {
                        "ticker": inst.get("symbol"),
                        "quantity": p.get("longQuantity") or p.get("shortQuantity"),
                        "average_price": p.get("averagePrice"),
                        "market_value": p.get("marketValue"),
                        "current_day_pnl": p.get("currentDayProfitLoss"),
                        "long_open_profit_loss": p.get("longOpenProfitLoss"),
                    }
                )
        return out

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_price_history_daily(self, ticker: str, days: int = 365) -> pd.DataFrame:
        """Return daily OHLCV bars as a DataFrame with a DatetimeIndex.

        Columns: open, high, low, close, volume.
        Returns empty DataFrame on failure.
        """
        c = self._get_client()
        try:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=days)
            r = c.get_price_history(
                symbol=ticker.upper(),
                period_type=c.PriceHistory.PeriodType.YEAR,
                frequency_type=c.PriceHistory.FrequencyType.DAILY,
                frequency=c.PriceHistory.Frequency.DAILY,
                start_datetime=start_dt,
                end_datetime=end_dt,
                need_extended_hours_data=False,
            ).json()
        except Exception as exc:
            logger.warning("get_price_history_daily(%s) failed: %s", ticker, exc)
            return pd.DataFrame()

        candles = r.get("candles") or []
        if not candles:
            return pd.DataFrame()

        rows = []
        for c_ in candles:
            rows.append(
                {
                    "date": pd.to_datetime(c_["datetime"], unit="ms", utc=True).normalize(),
                    "open": c_.get("open"),
                    "high": c_.get("high"),
                    "low": c_.get("low"),
                    "close": c_.get("close"),
                    "volume": c_.get("volume"),
                }
            )
        df = pd.DataFrame(rows).set_index("date")
        df.index = df.index.tz_localize(None)
        return df

    def get_options_chain(self, ticker: str) -> dict[str, Any]:
        c = self._get_client()
        r = c.get_option_chain(ticker).json()
        return r if isinstance(r, dict) else {"raw": r}

    @staticmethod
    def _resolve_mover_index(client: Any, index: str) -> Any:
        """Map $SPX / SPX strings to schwab-py Movers.Index enum."""
        if not index:
            return client.Movers.Index.SPX
        raw = index.strip().upper()
        key = raw.lstrip("$")
        try:
            return client.Movers.Index[key]
        except KeyError:
            for member in client.Movers.Index:
                if member.value.upper() in (raw, f"${key}", key):
                    return member
            logger.warning("Unknown mover index %s, defaulting to SPX", index)
            return client.Movers.Index.SPX

    @staticmethod
    def _resolve_mover_sort_order(client: Any, sort_order: str) -> Any:
        try:
            return client.Movers.SortOrder[sort_order]
        except (AttributeError, KeyError):
            return sort_order

    def get_movers(self, index: str = "$SPX", sort_order: str = "PERCENT_CHANGE_UP") -> list[dict[str, Any]]:
        """Index movers normalized to stable dicts.

        sort_order: PERCENT_CHANGE_UP | PERCENT_CHANGE_DOWN | VOLUME | TRADES
        index: $SPX | $COMPX | $DJI | NYSE | NASDAQ (schwab Movers.Index values)
        """
        c = self._get_client()
        try:
            idx = self._resolve_mover_index(c, index)
            so = self._resolve_mover_sort_order(c, sort_order)
            r = c.get_movers(idx, sort_order=so).json()
        except Exception as e:
            logger.warning("get_movers(%s) failed: %s", index, e)
            return []

        # Response shape: {"screeners": [...]} or a list directly
        items: list[Any] = []
        if isinstance(r, list):
            items = r
        elif isinstance(r, dict):
            items = r.get("screeners") or r.get("movers") or []

        result: list[dict[str, Any]] = []
        for m in items:
            if not isinstance(m, dict):
                continue
            net_change = m.get("netChange")
            # netPercentChange is a decimal (e.g. -0.0196 = -1.96%); multiply for display.
            raw_pct = m.get("netPercentChange")
            change_pct = round(float(raw_pct) * 100, 2) if raw_pct is not None else None
            # direction not in response — derive from sign of netChange.
            direction: str | None = None
            if net_change is not None:
                direction = "up" if float(net_change) >= 0 else "down"
            result.append(
                {
                    "ticker": m.get("symbol"),
                    "description": m.get("description"),
                    "last_price": m.get("lastPrice"),
                    "change": net_change,
                    "change_pct": change_pct,
                    # volume = per-stock shares traded; totalVolume = market-wide aggregate (same for all rows).
                    "volume": m.get("volume"),
                    "trades": m.get("trades"),
                    "market_share_pct": m.get("marketShare"),
                    "direction": direction,
                }
            )
        return result

    def get_market_hours(self, markets: list[str] | None = None, date: str | None = None) -> dict[str, Any]:
        """Return market hours for the given markets (default: equity) and date (default: today)."""
        import datetime as _dt

        c = self._get_client()
        # schwab-py requires datetime.date for date param
        if date is None:
            date_obj = _dt.date.today()
        elif isinstance(date, str):
            date_obj = _dt.date.fromisoformat(date)
        else:
            date_obj = date
        # schwab-py requires enum values for markets; resolve strings to enums when possible.
        market_names = markets or ["equity"]
        try:
            Market = c.MarketHours.Market
            resolved = []
            for m in market_names:
                try:
                    resolved.append(Market(m.lower()))
                except (ValueError, KeyError):
                    resolved.append(m)
        except AttributeError:
            resolved = market_names
        try:
            r = c.get_market_hours(markets=resolved, date=date_obj).json()
            return r if isinstance(r, dict) else {}
        except Exception as exc:
            logger.warning("get_market_hours failed: %s", exc)
            return {}

    def is_equity_session_open(self) -> bool | None:
        """Return True/False if Schwab confirms session status, None on failure."""
        try:
            hours = self.get_market_hours(["equity"])
            eq = hours.get("equity") or {}
            # Key varies: "equity" -> {"EQ": {...}} or direct
            for v in eq.values():
                if isinstance(v, dict) and "isOpen" in v:
                    return bool(v["isOpen"])
        except Exception:
            pass
        return None
