"""APScheduler jobs for screening and watchlist checks."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from alerts.alert_manager import AlertManager
from alerts.notifier import send_email
from config import settings
from screener.batch_runner import load_tickers_from_file, run_pipeline
from utils.market_hours import is_us_equity_session_open

logger = logging.getLogger(__name__)


def job_premarket_scan() -> None:
    tickers = load_tickers_from_file(settings.TICKER_LIST_PATH)
    if not tickers:
        logger.warning("No tickers in %s", settings.TICKER_LIST_PATH)
        return
    results = run_pipeline(tickers, save_db=True)
    buys = [r for r in results if r.get("verdict") == "BUY_CANDIDATE"]
    buys.sort(key=lambda x: x.get("score") or 0, reverse=True)
    top = buys[:10]
    body_lines = [f"{r['ticker']}: score={r.get('score')} — {r.get('reasoning', '')[:300]}" for r in top]
    send_email(
        f"Pre-market scan {datetime.now().isoformat()}",
        "\n\n".join(body_lines) or "No BUY_CANDIDATE today.",
    )


def job_intraday_watchlist() -> None:
    if not is_us_equity_session_open():
        logger.debug("Skipping intraday watchlist: market not in regular session")
        return
    AlertManager().check_watchlist_prices()


def job_weekly_deep() -> None:
    p = _ROOT / "tickers" / "sp500.txt"
    tickers = load_tickers_from_file(p)
    if not tickers:
        tickers = load_tickers_from_file(settings.TICKER_LIST_PATH)
    results = run_pipeline(tickers[:100], save_db=True)  # cap to avoid very long runs
    buys = sorted(
        [r for r in results if r.get("verdict") == "BUY_CANDIDATE"],
        key=lambda x: x.get("score") or 0,
        reverse=True,
    )[:20]
    logger.info("Weekly top 20: %s", [b.get("ticker") for b in buys])


def main() -> None:
    from zoneinfo import ZoneInfo

    logging.basicConfig(level=logging.INFO)
    sched = BlockingScheduler()
    cron_tz = ZoneInfo("America/New_York")
    sched.add_job(
        job_premarket_scan,
        CronTrigger(day_of_week="mon-fri", hour=6, minute=30, timezone=cron_tz),
    )
    # Fires every 15m; actual watchlist polling only occurs during US regular session (see job body).
    sched.add_job(job_intraday_watchlist, IntervalTrigger(minutes=15))
    sched.add_job(
        job_weekly_deep,
        CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=cron_tz),
    )
    tz_key = getattr(cron_tz, "key", "America/New_York")
    logger.info(
        "Scheduler started: pre-market & weekly cron in %s; intraday gated to US session.",
        tz_key,
    )
    sched.start()


if __name__ == "__main__":
    main()
