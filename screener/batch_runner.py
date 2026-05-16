"""Fetch data, pre-filter, screen with Ollama/Claude, persist results."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import settings
from data.fetchers.news_fetcher import NewsFetcher
from data.fetchers.yfinance_fetcher import StockFetcher
from screener.criteria import ScreeningCriteria
from screener.ollama_screener import OllamaScreener
from storage import queries

logger = logging.getLogger(__name__)


def load_tickers_from_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip().upper() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _merge_for_db(
    ticker: str, fundamentals: dict[str, Any], llm: dict[str, Any]
) -> dict[str, Any]:
    return {
        **llm,
        "ticker": ticker,
        "score": llm.get("score"),
        "verdict": llm.get("verdict"),
        "valuation_status": llm.get("valuation_status"),
        "estimated_upside_percent": llm.get("estimated_upside_percent"),
        "suggested_buy_price": llm.get("suggested_buy_price"),
        "current_price": fundamentals.get("current_price"),
        "pe_ratio": fundamentals.get("pe_ratio"),
        "forward_pe": fundamentals.get("forward_pe"),
        "analyst_target": fundamentals.get("analyst_target_price"),
        "news_sentiment": llm.get("news_sentiment"),
        "news_summary": llm.get("news_summary"),
        "reasoning": llm.get("reasoning"),
    }


def export_tier2_summary(ticker: str, fundamentals: dict[str, Any], llm: dict[str, Any]) -> Path:
    d = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = settings.EXPORTS_DIR / f"{ticker}_{d}_summary.json"
    payload = {
        "ticker": ticker,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "fundamentals": fundamentals,
        "llm": llm,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _make_error_row(ticker: str, verdict: str, reason: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "score": 0,
        "verdict": verdict,
        "valuation_status": "FAIRLY_VALUED",
        "estimated_upside_percent": 0.0,
        "key_strengths": [],
        "key_risks": [],
        "news_sentiment": "NEUTRAL",
        "news_summary": "" if verdict == "ERROR" else "Pre-filter reject",
        "suggested_buy_price": None,
        "reasoning": reason,
    }


def _fetch_fundamentals(ticker: str, fetcher: StockFetcher) -> dict[str, Any]:
    """Fetch fundamentals and earnings calendar for one ticker (no news)."""
    t = ticker.strip().upper()
    try:
        fund = fetcher.get_fundamentals(t)
        cal = fetcher.get_earnings_calendar(t)
        sector = fund.get("sector") or ""
        fund["_sector_pe"] = fetcher.get_sector_pe(str(sector)) if sector else None
        return {"ticker": t, "fundamentals": fund, "earnings_cal": cal, "fetch_error": None}
    except Exception as e:
        logger.exception("fetch failed %s", t)
        return {"ticker": t, "fundamentals": {}, "earnings_cal": {}, "fetch_error": str(e)}


def _fetch_one(
    ticker: str,
    fetcher: StockFetcher,
    news_fetcher: NewsFetcher,
    criteria: ScreeningCriteria,
    skip_prefilter: bool,
) -> dict[str, Any]:
    raw = _fetch_fundamentals(ticker, fetcher)
    t = raw["ticker"]

    if raw["fetch_error"]:
        return {
            "ticker": t, "fundamentals": {}, "news": [], "skipped_llm": True,
            "filter_reasons": [],
            "llm": _make_error_row(t, "ERROR", raw["fetch_error"]),
        }

    fund = raw["fundamentals"]
    cal = raw["earnings_cal"]

    if not skip_prefilter:
        reasons = criteria.check_reasons(t, fund, cal)
        if reasons:
            return {
                "ticker": t, "fundamentals": fund, "news": [], "skipped_llm": True,
                "filter_reasons": reasons,
                "llm": _make_error_row(t, "FILTERED", "; ".join(reasons)),
            }

    company = str(fund.get("company_name") or t)
    news = news_fetcher.get_recent_news(t, company)
    return {"ticker": t, "fundamentals": fund, "news": news, "skipped_llm": False, "filter_reasons": []}


def run_prescreen(
    tickers: list[str],
    *,
    skip_prefilter: bool = False,
    max_workers: Optional[int] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Phase 1: fetch fundamentals and apply pre-filter criteria.

    Returns ``(passing, filtered)`` where each item contains:
      ``ticker``, ``fundamentals``, ``earnings_cal``, ``filter_reasons``, ``fetch_error``.

    ``passing`` items have an empty ``filter_reasons`` list.
    ``filtered`` items have one or more human-readable reasons, or a ``fetch_error``.
    """
    workers = settings.YFIN_FETCH_WORKERS if max_workers is None else max(1, int(max_workers))
    fetcher = StockFetcher()
    criteria = ScreeningCriteria()

    clean = [t.strip().upper() for t in tickers if t.strip()]
    ticker_order = {t: i for i, t in enumerate(clean)}

    raw_map: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_fundamentals, t, fetcher): t for t in clean}
        for fut in as_completed(futures):
            r = fut.result()
            raw_map[r["ticker"]] = r

    passing: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []

    for t in sorted(clean, key=lambda x: ticker_order.get(x, 0)):
        raw = raw_map.get(t)
        if raw is None or raw.get("fetch_error"):
            filtered.append({
                "ticker": t,
                "fundamentals": {},
                "earnings_cal": {},
                "filter_reasons": [],
                "fetch_error": (raw or {}).get("fetch_error") or "missing from fetch results",
            })
            continue

        fund = raw["fundamentals"]
        cal = raw["earnings_cal"]

        if skip_prefilter:
            passing.append({
                "ticker": t, "fundamentals": fund, "earnings_cal": cal,
                "filter_reasons": [], "fetch_error": None,
            })
        else:
            reasons = criteria.check_reasons(t, fund, cal)
            item = {
                "ticker": t, "fundamentals": fund, "earnings_cal": cal,
                "filter_reasons": reasons, "fetch_error": None,
            }
            (filtered if reasons else passing).append(item)

    return passing, filtered


def run_pipeline(
    tickers: list[str],
    *,
    skip_prefilter: bool = False,
    save_db: bool = True,
    export_high_scores: bool = True,
    max_workers: Optional[int] = None,
    override_tickers: frozenset[str] = frozenset(),
    prescreen_results: Optional[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = None,
) -> list[dict[str, Any]]:
    """Full pipeline: fundamentals → news → criteria → LLM → SQLite → optional exports.

    If ``prescreen_results`` is supplied (from :func:`run_prescreen`), the fundamentals
    fetch phase is skipped — news is still fetched for passing tickers.
    ``override_tickers`` moves named filtered tickers back into the LLM queue.
    """
    queries.ensure_db()
    workers = settings.YFIN_FETCH_WORKERS if max_workers is None else max(1, int(max_workers))
    news_fetcher = NewsFetcher()

    if settings.LLM_PROVIDER == "claude":
        from screener.claude_screener import ClaudeScreener
        screener = ClaudeScreener(
            model=settings.CLAUDE_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
            max_workers=settings.CLAUDE_SCREENER_MAX_WORKERS,
        )
    else:
        screener = OllamaScreener(settings.OLLAMA_MODEL, settings.OLLAMA_HOST)

    if prescreen_results is not None:
        passing, filtered = prescreen_results

        # Move overridden tickers from filtered → passing (only those without fetch errors)
        if override_tickers:
            still_filtered = [f for f in filtered if f["ticker"] not in override_tickers]
            now_passing = [
                {**f, "filter_reasons": []}
                for f in filtered
                if f["ticker"] in override_tickers and not f.get("fetch_error")
            ]
            passing = passing + now_passing
            filtered = still_filtered

        ticker_order = {t: i for i, t in enumerate(tickers)}

        def _fetch_news(item: dict[str, Any]) -> dict[str, Any]:
            t = item["ticker"]
            fund = item["fundamentals"]
            company = str(fund.get("company_name") or t)
            news = news_fetcher.get_recent_news(t, company)
            return {**item, "news": news, "skipped_llm": False}

        passing_with_news: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch_news, p): p["ticker"] for p in passing}
            for fut in as_completed(futures):
                passing_with_news.append(fut.result())

        prepared: list[dict[str, Any]] = []
        for item in filtered:
            t = item["ticker"]
            if item.get("fetch_error"):
                prepared.append({
                    "ticker": t, "fundamentals": {}, "news": [], "skipped_llm": True,
                    "filter_reasons": [],
                    "llm": _make_error_row(t, "ERROR", item["fetch_error"]),
                })
            else:
                reasons = item["filter_reasons"]
                reason_str = "; ".join(reasons) if reasons else "Did not pass ScreeningCriteria"
                prepared.append({
                    "ticker": t, "fundamentals": item["fundamentals"], "news": [], "skipped_llm": True,
                    "filter_reasons": reasons,
                    "llm": _make_error_row(t, "FILTERED", reason_str),
                })
        prepared.extend(passing_with_news)
        prepared.sort(key=lambda p: ticker_order.get(p["ticker"], 0))

    else:
        fetcher = StockFetcher()
        criteria = ScreeningCriteria()
        clean = [t.strip().upper() for t in tickers if t.strip()]
        ticker_order = {t: i for i, t in enumerate(clean)}

        prepared_map: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_fetch_one, t, fetcher, news_fetcher, criteria, skip_prefilter): t
                for t in clean
            }
            for fut in as_completed(futures):
                result = fut.result()
                prepared_map[result["ticker"]] = result

        prepared = sorted(prepared_map.values(), key=lambda p: ticker_order.get(p["ticker"], 0))

    for p in prepared:
        if p.get("skipped_llm") and p.get("llm", {}).get("verdict") in ("FILTERED", "ERROR") and save_db:
            err_row = p["llm"]
            queries.save_screening_result(
                _merge_for_db(p["ticker"], p["fundamentals"], err_row) | {"raw_json": json.dumps(err_row)}
            )

    llm_inputs = [p for p in prepared if not p.get("skipped_llm")]
    llm_out: dict[str, dict[str, Any]] = {}
    if llm_inputs:
        batch_payload = [
            {"ticker": p["ticker"], "fundamentals": p["fundamentals"], "news": p["news"]}
            for p in llm_inputs
        ]
        screened = screener.screen_batch(batch_payload)
        by_ticker = {(r.get("ticker") or "").upper(): r for r in screened}
        for p in llm_inputs:
            llm_out[p["ticker"]] = by_ticker.get(p["ticker"].upper(), {})

    final: list[dict[str, Any]] = []
    for p in prepared:
        t = p["ticker"]
        if p.get("skipped_llm") and "llm" in p:
            final.append(p["llm"])
            continue
        llm = llm_out.get(t) or {}
        fund = p["fundamentals"]
        row = _merge_for_db(t, fund, llm)
        if save_db:
            queries.save_screening_result(row | {"raw_json": json.dumps(llm, default=str)})
        if export_high_scores and int(llm.get("score") or 0) >= 80 and llm.get("verdict") == "BUY_CANDIDATE":
            export_tier2_summary(t, fund, llm)
        final.append(llm)
    return final
