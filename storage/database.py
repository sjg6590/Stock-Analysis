"""SQLite schema and engine via SQLAlchemy."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Float, Integer, MetaData, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import settings


class Base(DeclarativeBase):
    metadata = MetaData()


class ScreeningResult(Base):
    __tablename__ = "screening_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    screened_at: Mapped[str] = mapped_column(
        Text, server_default=text("(datetime('now'))"), nullable=False
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    valuation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    estimated_upside_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_buy_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    analyst_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    news_sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    news_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class WatchlistEntry(Base):
    __tablename__ = "watchlist"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    added_at: Mapped[str] = mapped_column(
        Text, server_default=text("(datetime('now'))"), nullable=False
    )
    target_buy_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    alert_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    triggered_at: Mapped[str] = mapped_column(
        Text, server_default=text("(datetime('now'))"), nullable=False
    )
    price_at_trigger: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


def get_engine():
    path: Path = settings.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False, future=True)


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_screening_ticker ON screening_results(ticker)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_screening_date ON screening_results(screened_at)"))
