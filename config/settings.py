"""Application settings loaded from environment / .env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root (parent of config/)
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _get_float(key: str, default: float) -> float:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return float(v)


def _get_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return int(v)


def _get_path(key: str, default: str) -> Path:
    p = os.getenv(key, default)
    path = Path(p)
    if not path.is_absolute():
        path = (_ROOT / path).resolve()
    return path


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # "ollama" | "claude"
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")
CLAUDE_SCREENER_MAX_WORKERS = _get_int("CLAUDE_SCREENER_MAX_WORKERS", 5)

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")


def _get_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# Set USE_NEWS_API=false to always use yfinance (good for large watchlists).
USE_NEWS_API = _get_bool("USE_NEWS_API", True)
# Minimum seconds between NewsAPI calls (free tier: keep >0 for small lists only).
NEWS_API_MIN_INTERVAL_SEC = _get_float("NEWS_API_MIN_INTERVAL_SEC", 0.0)

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")

SCHWAB_CLIENT_ID = os.getenv("SCHWAB_CLIENT_ID", "")
SCHWAB_CLIENT_SECRET = os.getenv("SCHWAB_CLIENT_SECRET", "")
SCHWAB_REDIRECT_URI = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1")
SCHWAB_TOKEN_PATH = _get_path("SCHWAB_TOKEN_PATH", "./schwab_token.json")

# Master switch — set false to use yfinance exclusively (no Schwab API calls).
USE_SCHWAB = _get_bool("USE_SCHWAB", True)
# Use Schwab intraday quotes for watchlist / buy-zone alert checks.
USE_SCHWAB_FOR_ALERTS = _get_bool("USE_SCHWAB_FOR_ALERTS", True)
# Use Schwab portfolio endpoint for dashboard Portfolio page.
USE_SCHWAB_FOR_PORTFOLIO = _get_bool("USE_SCHWAB_FOR_PORTFOLIO", True)
# In-memory quote cache TTL (seconds) — avoids N+1 Schwab calls per alert cycle.
SCHWAB_QUOTE_CACHE_SEC = _get_int("SCHWAB_QUOTE_CACHE_SEC", 15)
# Portfolio snapshot cache TTL (seconds) shown in the dashboard.
SCHWAB_PORTFOLIO_CACHE_SEC = _get_int("SCHWAB_PORTFOLIO_CACHE_SEC", 300)

# Market data features (all require USE_SCHWAB=true + valid token)
USE_SCHWAB_MARKET_DATA = _get_bool("USE_SCHWAB_MARKET_DATA", True)
USE_SCHWAB_FOR_CHARTS = _get_bool("USE_SCHWAB_FOR_CHARTS", True)
# Overwrite current_price in screening results with live Schwab quote (off by default).
USE_SCHWAB_FOR_SCREENING_PRICE = _get_bool("USE_SCHWAB_FOR_SCREENING_PRICE", False)
USE_SCHWAB_FOR_MOVERS = _get_bool("USE_SCHWAB_FOR_MOVERS", True)
USE_SCHWAB_FOR_OPTIONS = _get_bool("USE_SCHWAB_FOR_OPTIONS", True)
# Use Schwab get_market_hours for scheduler session gating (respects holidays/early close).
USE_SCHWAB_MARKET_HOURS = _get_bool("USE_SCHWAB_MARKET_HOURS", True)

# Optional market-data-only app credentials (leave blank to reuse main trading credentials).
SCHWAB_MARKET_DATA_CLIENT_ID = os.getenv("SCHWAB_MARKET_DATA_CLIENT_ID", "")
SCHWAB_MARKET_DATA_CLIENT_SECRET = os.getenv("SCHWAB_MARKET_DATA_CLIENT_SECRET", "")
SCHWAB_MARKET_DATA_TOKEN_PATH = _get_path("SCHWAB_MARKET_DATA_TOKEN_PATH", "./schwab_market_data_token.json")

# Cache TTLs for market data endpoints
SCHWAB_HISTORY_CACHE_SEC = _get_int("SCHWAB_HISTORY_CACHE_SEC", 3600)
SCHWAB_MOVERS_CACHE_SEC = _get_int("SCHWAB_MOVERS_CACHE_SEC", 300)

ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _get_int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

MAX_PE_RATIO = _get_float("MAX_PE_RATIO", 25.0)
MIN_PE_RATIO = _get_float("MIN_PE_RATIO", 5.0)
MIN_UPSIDE_PERCENT = _get_float("MIN_UPSIDE_PERCENT", 15.0)
MAX_DEBT_TO_EQUITY = _get_float("MAX_DEBT_TO_EQUITY", 2.0)
MIN_MARKET_CAP = _get_float("MIN_MARKET_CAP", 1_000_000_000.0)

_sectors_raw = os.getenv("SECTORS", "Technology,Healthcare,Consumer Discretionary")
SECTORS = [s.strip() for s in _sectors_raw.split(",") if s.strip()]

DB_PATH = _get_path("DB_PATH", "./storage/stocks.db")
TICKER_LIST_PATH = _get_path("TICKER_LIST", "./tickers/watchlist.txt")

EXPORTS_DIR = _ROOT / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Minimum seconds between Yahoo Finance requests (same process; lock enforces spacing).
YFIN_DELAY_SEC = _get_float("YFIN_DELAY_SEC", 1.25)
# Parallel ticker fetches; use 1 to minimize 429s on large lists.
YFIN_FETCH_WORKERS = _get_int("YFIN_FETCH_WORKERS", 1)
YFIN_MAX_RETRIES = _get_int("YFIN_MAX_RETRIES", 4)
YFIN_BACKOFF_BASE_SEC = _get_float("YFIN_BACKOFF_BASE_SEC", 2.5)

# Ensure DB parent exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
