"""News via NewsAPI with yfinance fallback and free-tier rate-limit handling."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import yfinance as yf

from config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_newsapi_disabled_until: datetime | None = None
_last_newsapi_call: float = 0.0
_rate_limit_logged = False


def _newsapi_allowed() -> bool:
    with _lock:
        if _newsapi_disabled_until is None:
            return True
        return datetime.now(timezone.utc) >= _newsapi_disabled_until


def _disable_newsapi_cooldown(hours: float = 12.0) -> None:
    global _newsapi_disabled_until, _rate_limit_logged
    with _lock:
        _newsapi_disabled_until = datetime.now(timezone.utc) + timedelta(hours=hours)
        if not _rate_limit_logged:
            _rate_limit_logged = True
            logger.warning(
                "NewsAPI rate limited or disabled for this process; using yfinance news only "
                "for ~%.0f h. For bulk screens set USE_NEWS_API=false or omit NEWS_API_KEY.",
                hours,
            )


def _throttle_newsapi() -> None:
    global _last_newsapi_call
    interval = max(0.0, float(settings.NEWS_API_MIN_INTERVAL_SEC))
    if interval <= 0:
        return
    with _lock:
        now = time.monotonic()
        wait = interval - (now - _last_newsapi_call)
        if wait > 0:
            time.sleep(wait)
        _last_newsapi_call = time.monotonic()


class NewsFetcher:
    def __init__(self) -> None:
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from newsapi import NewsApiClient

        self._client = NewsApiClient(api_key=settings.NEWS_API_KEY)
        return self._client

    def _try_newsapi(self, ticker: str, company_name: str, days: int) -> list[dict[str, Any]] | None:
        if not settings.NEWS_API_KEY or not settings.USE_NEWS_API:
            return None
        if not _newsapi_allowed():
            return None
        _throttle_newsapi()
        try:
            api = self._get_client()
            from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
            q = f'"{ticker}" OR "{company_name}"'
            resp = api.get_everything(
                q=q,
                language="en",
                sort_by="publishedAt",
                from_param=from_date,
                page_size=10,
            )
            if isinstance(resp, dict) and resp.get("status") == "error":
                code = resp.get("code", "")
                if code in ("rateLimited", "maximumResultsReached", "apiKeyInvalid"):
                    _disable_newsapi_cooldown(12.0 if code == "rateLimited" else 1.0)
                else:
                    logger.debug("NewsAPI error for %s: %s", ticker, resp)
                return None
            items: list[dict[str, Any]] = []
            for a in (resp.get("articles") or [])[:10]:
                items.append(
                    {
                        "title": a.get("title") or "",
                        "description": a.get("description") or "",
                        "url": a.get("url") or "",
                        "published_at": a.get("publishedAt") or "",
                        "source": (a.get("source") or {}).get("name", ""),
                    }
                )
            return items if items else None
        except Exception as e:
            err = str(e).lower()
            if "ratelimit" in err or "rate limited" in err or "too many requests" in err:
                _disable_newsapi_cooldown(12.0)
            else:
                logger.debug("NewsAPI failed for %s: %s", ticker, e)
            return None

    def _yfinance_news(self, ticker: str, days: int) -> list[dict[str, Any]]:
        from data.fetchers.yfinance_fetcher import yahoo_network_call

        def work() -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            t = yf.Ticker(ticker)
            raw = t.news or []
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            for n in raw[:20]:
                provider = n.get("content", {}) or {}
                title = provider.get("title") or n.get("title", "")
                pub = provider.get("pubDate") or n.get("providerPublishTime")
                if pub:
                    try:
                        if isinstance(pub, (int, float)):
                            dt = datetime.fromtimestamp(int(pub), tz=timezone.utc)
                        else:
                            dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
                        if dt < cutoff:
                            continue
                    except Exception:
                        pass
                items.append(
                    {
                        "title": title,
                        "description": provider.get("summary", "")[:500],
                        "url": provider.get("canonicalUrl", {}).get("url", "")
                        if isinstance(provider.get("canonicalUrl"), dict)
                        else str(provider.get("canonicalUrl", "")),
                        "published_at": str(pub),
                        "source": provider.get("provider", {}).get("displayName", "Yahoo")
                        if isinstance(provider.get("provider"), dict)
                        else "Yahoo",
                    }
                )
                if len(items) >= 10:
                    break
            return items[:10]

        try:
            return yahoo_network_call(work)
        except Exception as e:
            logger.warning("yfinance news failed for %s: %s", ticker, e)
            return []

    def get_recent_news(self, ticker: str, company_name: str, days: int = 7) -> list[dict[str, Any]]:
        """Up to 10 articles: NewsAPI when allowed, then yfinance .news."""
        items = self._try_newsapi(ticker, company_name, days)
        if items:
            return items
        return self._yfinance_news(ticker, days)
