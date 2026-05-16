"""Price / screening alert rules backed by SQLite."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from analysis.thinkscript_generator import ThinkScriptGenerator
from config import settings
from data.fetchers.quote_provider import QuoteProvider
from storage import queries

logger = logging.getLogger(__name__)

_SCRIPTS_DIR = settings.EXPORTS_DIR.parent / "thinkscripts"
_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


class AlertManager:
    """
    When DB rows match:
    - current_price <= suggested_buy_price * 1.02
    - score >= 70
    - verdict == BUY_CANDIDATE
    notify, log, dedupe 24h, save ThinkScript snippet.

    Price source: Schwab (intraday) when USE_SCHWAB_FOR_ALERTS=true and token exists;
    otherwise yfinance.
    """

    def __init__(self) -> None:
        self.quotes = QuoteProvider()
        self.ts_gen = ThinkScriptGenerator()

    def check_screening_alerts(self) -> list[str]:
        rows = queries.today_top_buy_candidates(limit=100)
        triggered: list[str] = []
        for r in rows:
            if (r.get("score") or 0) < 70:
                continue
            if r.get("verdict") != "BUY_CANDIDATE":
                continue
            sb = r.get("suggested_buy_price")
            if sb is None:
                continue
            t = r["ticker"]
            # Prefer live Schwab price; fall back to price recorded at screen time.
            px = self.quotes.get_last_price(t) or r.get("current_price")
            if px is None:
                continue
            if float(px) > float(sb) * 1.02:
                continue
            last = queries.last_alert_time(t)
            if last and datetime.now(timezone.utc) - last < timedelta(hours=24):
                continue
            msg = f"{t} at {px} within buy zone (target {sb})"
            logger.info("ALERT %s", msg)
            from alerts.notifier import desktop_notify, send_email

            send_email(f"Stock alert: {t}", msg)
            desktop_notify("Stock Analyzer", msg)
            queries.log_alert(t, "BUY_ZONE", float(px) if px else None, msg)
            code = self.ts_gen.generate_buy_signal_alert(t, float(sb), ["volume > volume[1]"])
            path = _SCRIPTS_DIR / f"{t}_alert.ts"
            path.write_text(code, encoding="utf-8")
            triggered.append(t)
        return triggered

    def check_watchlist_prices(self) -> list[str]:
        wl = queries.list_watchlist()
        active = [w for w in wl if w.get("alert_active") and w.get("target_buy_price") is not None]
        if not active:
            return []

        tickers = [w["ticker"] for w in active]
        # Single batch call — avoids N+1 requests per watchlist cycle.
        prices = self.quotes.get_last_prices(tickers)

        out: list[str] = []
        for w in active:
            t = w["ticker"]
            tgt = w.get("target_buy_price")
            px = prices.get(t)
            if px is None:
                continue
            if float(px) <= float(tgt):
                last = queries.last_alert_time(t)
                if last and datetime.now(timezone.utc) - last < timedelta(hours=24):
                    continue
                msg = f"{t} at {px} <= watchlist target {tgt}"
                from alerts.notifier import desktop_notify, send_email

                send_email(f"Watchlist: {t}", msg)
                desktop_notify("Watchlist", msg)
                queries.log_alert(t, "WATCHLIST_TARGET", float(px), msg)
                out.append(t)
        return out
