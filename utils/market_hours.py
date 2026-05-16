"""US market session helpers (NYSE / Nasdaq regular hours).

is_us_equity_session_open() is the primary function:
- If USE_SCHWAB_MARKET_HOURS=true and Schwab token exists, asks the API
  (respects holidays and early close).
- Falls back to hard-coded Mon–Fri 09:30–16:00 ET when Schwab unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)


def us_market_regular_session_now() -> bool:
    """Hard-coded session check (Mon–Fri, 09:30–16:00 ET). No network call."""
    now = datetime.now(_ET)
    if now.weekday() >= 5:
        return False
    return _OPEN <= now.time() <= _CLOSE


def is_us_equity_session_open() -> bool:
    """True when the US equity market is in regular session.

    Tries Schwab get_market_hours when USE_SCHWAB_MARKET_HOURS=true so that
    holidays and early-close days are handled correctly.  Falls back to the
    hard-coded time check on any failure.
    """
    from config import settings

    if settings.USE_SCHWAB and settings.USE_SCHWAB_MARKET_HOURS:
        try:
            from data.fetchers.schwab_fetcher import SchwabFetcher

            sf = SchwabFetcher()
            if sf.is_authenticated():
                result = sf.is_equity_session_open()
                if result is not None:
                    return result
        except Exception as exc:
            logger.debug("Schwab market hours check failed, using fallback: %s", exc)

    return us_market_regular_session_now()
