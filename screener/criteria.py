"""Pre-filter stocks before LLM screening."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

# Yahoo sector names vs configured SECTORS labels
_SECTOR_ALIASES: dict[str, str] = {
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
}


class ScreeningCriteria:
    """Fast rules; log each rejection reason."""

    def __init__(self) -> None:
        self.allowed_sectors = {s.strip() for s in settings.SECTORS}
        self.min_cap = settings.MIN_MARKET_CAP
        self.min_pe = settings.MIN_PE_RATIO
        self.max_pe = settings.MAX_PE_RATIO
        self.max_de = settings.MAX_DEBT_TO_EQUITY

    def _normalize_sector(self, sector: str | None) -> str | None:
        if not sector:
            return None
        return _SECTOR_ALIASES.get(sector, sector)

    def check_reasons(self, ticker: str, fundamentals: dict[str, Any], earnings: dict[str, Any]) -> list[str]:
        """Return a list of human-readable rejection reasons; empty list means the ticker passes."""
        reasons: list[str] = []

        cap = fundamentals.get("market_cap")
        if cap is None or cap < self.min_cap:
            cap_str = f"${cap / 1e9:.2f}B" if cap else "N/A"
            min_str = f"${self.min_cap / 1e9:.2f}B"
            reasons.append(f"market cap {cap_str} is below minimum {min_str}")

        pe = fundamentals.get("pe_ratio")
        if pe is not None and pe > 0 and (pe < self.min_pe or pe > self.max_pe):
            reasons.append(
                f"P/E ratio {pe:.1f} is outside allowed range "
                f"[{self.min_pe}, {self.max_pe}] (too {'low' if pe < self.min_pe else 'high'})"
            )

        de = fundamentals.get("debt_to_equity")
        if de is not None and de > self.max_de:
            reasons.append(f"debt/equity {de:.2f} exceeds maximum {self.max_de}")

        sector = self._normalize_sector(fundamentals.get("sector"))
        if sector and self.allowed_sectors and sector not in self.allowed_sectors:
            allowed_str = ", ".join(sorted(self.allowed_sectors))
            reasons.append(
                f"sector '{fundamentals.get('sector')}' is not in the allowed list "
                f"[{allowed_str}]"
            )

        na = fundamentals.get("number_of_analyst_opinions")
        if na is not None and int(na) < 3:
            reasons.append(f"only {na} analyst opinion(s) — need at least 3 for reliable coverage")

        ned = earnings.get("next_earnings_date")
        if ned:
            try:
                if isinstance(ned, str) and " " in ned:
                    ned = ned.split()[0]
                dt = datetime.fromisoformat(str(ned).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days_until = (dt - datetime.now(timezone.utc)).days
                if 0 <= days_until <= 5:
                    reasons.append(
                        f"earnings report in {days_until} day(s) — screening within "
                        f"5 days of earnings is too risky"
                    )
            except Exception:
                pass

        if reasons:
            logger.info("%s rejected pre-filter: %s", ticker, "; ".join(reasons))
        return reasons

    def passes(self, ticker: str, fundamentals: dict[str, Any], earnings: dict[str, Any]) -> bool:
        return not bool(self.check_reasons(ticker, fundamentals, earnings))
