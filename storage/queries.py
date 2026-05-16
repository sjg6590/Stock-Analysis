"""Read/write helpers for screening results and watchlist."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from storage.database import AlertHistory, ScreeningResult, WatchlistEntry, get_engine, init_db


def ensure_db() -> None:
    init_db()


def _parse_db_datetime(value: str) -> datetime | None:
    """Parse SQLite ISO timestamps as UTC-aware (server_default uses naive UTC)."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def save_screening_result(row: dict[str, Any]) -> None:
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        sr = ScreeningResult(
            ticker=row.get("ticker", ""),
            score=int(row["score"]) if row.get("score") is not None else None,
            verdict=row.get("verdict"),
            valuation_status=row.get("valuation_status"),
            estimated_upside_percent=row.get("estimated_upside_percent"),
            suggested_buy_price=row.get("suggested_buy_price"),
            current_price=row.get("current_price"),
            pe_ratio=row.get("pe_ratio"),
            forward_pe=row.get("forward_pe"),
            analyst_target=row.get("analyst_target"),
            news_sentiment=row.get("news_sentiment"),
            news_summary=row.get("news_summary"),
            reasoning=row.get("reasoning"),
            raw_json=json.dumps(row) if row else None,
        )
        session.add(sr)
        session.commit()


def latest_screening_for_ticker(ticker: str) -> dict[str, Any] | None:
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        q = (
            select(ScreeningResult)
            .where(ScreeningResult.ticker == ticker.upper())
            .order_by(ScreeningResult.id.desc())
            .limit(1)
        )
        r = session.scalars(q).first()
        if not r:
            return None
        return {
            "ticker": r.ticker,
            "score": r.score,
            "verdict": r.verdict,
            "valuation_status": r.valuation_status,
            "estimated_upside_percent": r.estimated_upside_percent,
            "suggested_buy_price": r.suggested_buy_price,
            "current_price": r.current_price,
            "pe_ratio": r.pe_ratio,
            "news_sentiment": r.news_sentiment,
            "news_summary": r.news_summary,
            "reasoning": r.reasoning,
            "screened_at": r.screened_at,
        }


def today_top_buy_candidates(limit: int = 50) -> list[dict[str, Any]]:
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        q = (
            select(ScreeningResult)
            .where(
                ScreeningResult.verdict == "BUY_CANDIDATE",
                func.substr(ScreeningResult.screened_at, 1, 10) == today,
            )
            .order_by(ScreeningResult.screened_at.desc(), ScreeningResult.score.desc())
        )
        rows = session.scalars(q).all()

    # Deduplicate: rows are newest-first, so first occurrence per ticker is most recent
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for r in rows:
        if r.ticker not in seen:
            seen.add(r.ticker)
            results.append(
                {
                    "ticker": r.ticker,
                    "score": r.score,
                    "verdict": r.verdict,
                    "valuation_status": r.valuation_status,
                    "estimated_upside_percent": r.estimated_upside_percent,
                    "suggested_buy_price": r.suggested_buy_price,
                    "current_price": r.current_price,
                    "pe_ratio": r.pe_ratio,
                    "forward_pe": r.forward_pe,
                    "analyst_target": r.analyst_target,
                    "news_sentiment": r.news_sentiment,
                    "news_summary": r.news_summary,
                    "reasoning": r.reasoning,
                    "screened_at": r.screened_at,
                }
            )
        if len(results) >= limit:
            break

    return sorted(results, key=lambda x: x.get("score") or 0, reverse=True)


def list_watchlist() -> list[dict[str, Any]]:
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        rows = session.scalars(select(WatchlistEntry)).all()
        return [
            {
                "ticker": r.ticker,
                "added_at": r.added_at,
                "target_buy_price": r.target_buy_price,
                "notes": r.notes,
                "alert_active": bool(r.alert_active),
            }
            for r in rows
        ]


def upsert_watchlist(
    ticker: str, target_buy_price: float | None = None, notes: str | None = None, alert_active: bool = True
) -> None:
    ensure_db()
    engine = get_engine()
    t = ticker.upper()
    with Session(engine) as session:
        existing = session.get(WatchlistEntry, t)
        if existing:
            existing.target_buy_price = target_buy_price if target_buy_price is not None else existing.target_buy_price
            if notes is not None:
                existing.notes = notes
            existing.alert_active = 1 if alert_active else 0
        else:
            session.add(
                WatchlistEntry(
                    ticker=t,
                    target_buy_price=target_buy_price,
                    notes=notes or "",
                    alert_active=1 if alert_active else 0,
                )
            )
        session.commit()


def remove_watchlist(ticker: str) -> None:
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        r = session.get(WatchlistEntry, ticker.upper())
        if r:
            session.delete(r)
            session.commit()


def set_watchlist_alert(ticker: str, active: bool) -> None:
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        session.execute(
            update(WatchlistEntry).where(WatchlistEntry.ticker == ticker.upper()).values(alert_active=1 if active else 0)
        )
        session.commit()


def log_alert(ticker: str, alert_type: str, price: float | None, message: str) -> None:
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        session.add(
            AlertHistory(ticker=ticker.upper(), alert_type=alert_type, price_at_trigger=price, message=message)
        )
        session.commit()


def recent_alerts(hours: int = 168) -> list[dict[str, Any]]:
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = session.scalars(
            select(AlertHistory)
            .where(AlertHistory.triggered_at >= cutoff)
            .order_by(AlertHistory.id.desc())
            .limit(200)
        ).all()
        return [
            {
                "ticker": r.ticker,
                "alert_type": r.alert_type,
                "triggered_at": r.triggered_at,
                "price_at_trigger": r.price_at_trigger,
                "message": r.message,
            }
            for r in rows
        ]


def recent_screening_results(hours: int = 24, limit: int = 500) -> list[dict[str, Any]]:
    """Return the most recent screening result per ticker within the lookback window."""
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = session.scalars(
            select(ScreeningResult)
            .where(ScreeningResult.screened_at >= cutoff)
            .order_by(ScreeningResult.screened_at.desc(), ScreeningResult.score.desc())
            .limit(limit)
        ).all()

    # Deduplicate: rows are newest-first, so first occurrence per ticker is most recent
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for r in rows:
        if r.ticker not in seen:
            seen.add(r.ticker)
            results.append(
                {
                    "ticker": r.ticker,
                    "score": r.score,
                    "verdict": r.verdict,
                    "valuation_status": r.valuation_status,
                    "estimated_upside_percent": r.estimated_upside_percent,
                    "suggested_buy_price": r.suggested_buy_price,
                    "current_price": r.current_price,
                    "pe_ratio": r.pe_ratio,
                    "forward_pe": r.forward_pe,
                    "analyst_target": r.analyst_target,
                    "news_sentiment": r.news_sentiment,
                    "news_summary": r.news_summary,
                    "reasoning": r.reasoning,
                    "screened_at": r.screened_at,
                }
            )

    return sorted(results, key=lambda x: x.get("score") or 0, reverse=True)


def last_alert_time(ticker: str) -> datetime | None:
    ensure_db()
    engine = get_engine()
    with Session(engine) as session:
        q = (
            select(AlertHistory)
            .where(AlertHistory.ticker == ticker.upper())
            .order_by(AlertHistory.id.desc())
            .limit(1)
        )
        r = session.scalars(q).first()
        if not r or not r.triggered_at:
            return None
        return _parse_db_datetime(r.triggered_at)
