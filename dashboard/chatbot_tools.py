"""Tool implementations for the RAG chatbot widget.

Each function wraps an existing data-fetcher or DB helper and attaches a
``_source`` metadata dict so the caller can build ChatResponse.sources.
TOOL_DISPATCH maps Claude tool names to their Python callables.
TOOL_SCHEMAS contains the JSON tool-definition list sent to the Claude API.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GLOSSARY_PATH = ROOT / "data" / "grounding" / "financial_glossary.md"


# ─────────────────────────────────────────────────────────────────────────────
# Source metadata helper
# ─────────────────────────────────────────────────────────────────────────────

def _src(label: str, ticker: str = "", source_type: str = "live_data") -> dict[str, str]:
    return {"source": label, "ticker": ticker, "type": source_type}


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────

def tool_get_stock_fundamentals(ticker: str) -> dict[str, Any]:
    from data.fetchers.yfinance_fetcher import StockFetcher
    data = StockFetcher().get_fundamentals(ticker.upper())
    data["_source"] = _src("yfinance/fundamentals", ticker.upper())
    return data


def tool_get_stock_news(ticker: str, company_name: str, days: int = 7) -> dict[str, Any]:
    from data.fetchers.news_fetcher import NewsFetcher
    articles = NewsFetcher().get_recent_news(ticker.upper(), company_name, days)
    return {
        "ticker": ticker.upper(),
        "articles": articles,
        "_source": _src("NewsAPI/yfinance-news", ticker.upper()),
    }


def tool_get_stock_price(tickers: list[str]) -> dict[str, Any]:
    from data.fetchers.quote_provider import QuoteProvider
    clean = [t.upper() for t in tickers]
    prices = QuoteProvider().get_last_prices(clean)
    return {
        "prices": prices,
        "_source": _src("QuoteProvider(Schwab/yfinance)"),
    }


def tool_get_earnings_calendar(ticker: str) -> dict[str, Any]:
    from data.fetchers.yfinance_fetcher import StockFetcher
    cal = StockFetcher().get_earnings_calendar(ticker.upper())
    if cal is None:
        cal = {}
    cal["_source"] = _src("yfinance/earnings-calendar", ticker.upper())
    return cal


def tool_get_market_movers(
    index: str = "$SPX",
    sort: str = "PERCENT_CHANGE_UP",
    limit: int = 10,
) -> dict[str, Any]:
    from data.market_data_provider import MarketDataProvider
    try:
        movers = MarketDataProvider().get_movers(index=index, sort=sort, limit=limit)
    except Exception as exc:
        movers = []
        return {
            "index": index,
            "sort": sort,
            "movers": movers,
            "error": str(exc),
            "_source": _src("MarketDataProvider(Schwab/yfinance)"),
        }
    return {
        "index": index,
        "sort": sort,
        "movers": movers,
        "_source": _src("MarketDataProvider(Schwab/yfinance)"),
    }


def tool_get_market_status() -> dict[str, Any]:
    from data.market_data_provider import MarketDataProvider
    try:
        is_open = MarketDataProvider().is_market_open_now()
    except Exception:
        is_open = None
    return {
        "is_open": is_open,
        "_source": _src("MarketDataProvider/market-hours"),
    }


def tool_get_watchlist() -> dict[str, Any]:
    from storage import queries
    rows = queries.list_watchlist()
    return {
        "watchlist": rows,
        "count": len(rows),
        "_source": _src("SQLite/watchlist", source_type="database"),
    }


def tool_add_to_watchlist(
    ticker: str,
    target_buy_price: float | None = None,
    notes: str | None = None,
    alert_active: bool = True,
) -> dict[str, Any]:
    from storage import queries
    queries.upsert_watchlist(ticker.upper(), target_buy_price, notes, alert_active)
    return {
        "success": True,
        "ticker": ticker.upper(),
        "action": "added_or_updated",
        "_source": _src("SQLite/watchlist", ticker.upper(), source_type="database"),
    }


def tool_remove_from_watchlist(ticker: str) -> dict[str, Any]:
    from storage import queries
    queries.remove_watchlist(ticker.upper())
    return {
        "success": True,
        "ticker": ticker.upper(),
        "action": "removed",
        "_source": _src("SQLite/watchlist", ticker.upper(), source_type="database"),
    }


def tool_toggle_watchlist_alert(ticker: str, active: bool) -> dict[str, Any]:
    from storage import queries
    queries.set_watchlist_alert(ticker.upper(), active)
    return {
        "success": True,
        "ticker": ticker.upper(),
        "alert_active": active,
        "_source": _src("SQLite/watchlist", ticker.upper(), source_type="database"),
    }


def tool_get_todays_buy_candidates(limit: int = 10) -> dict[str, Any]:
    from storage import queries
    rows = queries.today_top_buy_candidates(limit)
    return {
        "candidates": rows,
        "count": len(rows),
        "_source": _src("SQLite/screening_results", source_type="database"),
    }


def tool_get_recent_screening_results(hours: int = 24, limit: int = 20) -> dict[str, Any]:
    from storage import queries
    rows = queries.recent_screening_results(hours, limit)
    return {
        "results": rows,
        "lookback_hours": hours,
        "_source": _src("SQLite/screening_results", source_type="database"),
    }


def tool_get_latest_screen_for_ticker(ticker: str) -> dict[str, Any]:
    from storage import queries
    row = queries.latest_screening_for_ticker(ticker.upper())
    return {
        "result": row,
        "_source": _src("SQLite/screening_results", ticker.upper(), source_type="database"),
    }


def tool_run_deep_dive_screen(ticker: str) -> dict[str, Any]:
    """Fetch fresh fundamentals + news and run a Claude AI screen."""
    from config import settings
    from data.fetchers.news_fetcher import NewsFetcher
    from data.fetchers.yfinance_fetcher import StockFetcher
    from screener.claude_screener import ClaudeScreener

    fetcher = StockFetcher()
    fund = fetcher.get_fundamentals(ticker.upper())
    fund["_sector_pe"] = fetcher.get_sector_pe(str(fund.get("sector") or ""))
    company_name = fund.get("company_name", ticker)
    news = NewsFetcher().get_recent_news(ticker.upper(), company_name)

    sc = ClaudeScreener(
        model=settings.CLAUDE_MODEL,
        api_key=settings.ANTHROPIC_API_KEY,
        max_workers=1,
    )
    result = sc.screen_stock(ticker.upper(), fund, news)
    result["_source"] = _src("ClaudeScreener+yfinance", ticker.upper())
    return result


def tool_get_portfolio_holdings() -> dict[str, Any]:
    from data.schwab_service import SchwabNotConnectedError, SchwabService
    try:
        positions = SchwabService().get_positions_normalized()
        return {
            "positions": positions,
            "connected": True,
            "_source": _src("SchwabService/portfolio"),
        }
    except SchwabNotConnectedError:
        return {
            "positions": [],
            "connected": False,
            "note": "Schwab not connected. Run: python main.py schwab auth",
            "_source": _src("SchwabService/portfolio"),
        }


def tool_get_portfolio_overlap() -> dict[str, Any]:
    from data.schwab_service import SchwabNotConnectedError, SchwabService
    try:
        overlap = SchwabService().get_overlap_with_screening()
        return {
            "held_tickers": list(overlap.get("held_tickers", [])),
            "buy_candidates_owned": overlap.get("buy_candidates_owned", []),
            "buy_candidates_not_owned": overlap.get("buy_candidates_not_owned", []),
            "watchlist_with_held": overlap.get("watchlist_with_held", []),
            "_source": _src("SchwabService+SQLite/overlap"),
        }
    except SchwabNotConnectedError:
        return {
            "error": "Schwab not connected — portfolio overlap unavailable.",
            "_source": _src("SchwabService+SQLite/overlap"),
        }


def tool_discover_stocks_by_thesis(thesis: str) -> dict[str, Any]:
    from screener.thesis_screener import ThesisScreener
    result = ThesisScreener().discover(thesis)
    result["_source"] = _src("ThesisScreener(Claude)")
    return result


def tool_lookup_financial_term(term: str) -> dict[str, Any]:
    if not GLOSSARY_PATH.exists():
        return {
            "term": term,
            "definition": None,
            "found": False,
            "_source": _src("financial_glossary.md", source_type="static_grounding"),
        }
    content = GLOSSARY_PATH.read_text(encoding="utf-8")
    escaped = re.escape(term)
    pattern = re.compile(
        rf"^##\s+{escaped}\b(.*?)(?=^##\s|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)
    if match:
        definition = match.group(1).strip()[:1200]
        return {
            "term": term,
            "definition": definition,
            "found": True,
            "_source": _src("financial_glossary.md", source_type="static_grounding"),
        }
    # Fuzzy fallback: search for the term anywhere in headings
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## ") and term.lower() in line.lower():
            # Collect text until next heading
            block: list[str] = []
            for subsequent in lines[i + 1:]:
                if subsequent.startswith("## "):
                    break
                block.append(subsequent)
            definition = "\n".join(block).strip()[:1200]
            return {
                "term": term,
                "definition": definition,
                "found": True,
                "_source": _src("financial_glossary.md", source_type="static_grounding"),
            }
    return {
        "term": term,
        "definition": None,
        "found": False,
        "_source": _src("financial_glossary.md", source_type="static_grounding"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch table
# ─────────────────────────────────────────────────────────────────────────────

TOOL_DISPATCH: dict[str, Any] = {
    "get_stock_fundamentals": tool_get_stock_fundamentals,
    "get_stock_news": tool_get_stock_news,
    "get_stock_price": tool_get_stock_price,
    "get_earnings_calendar": tool_get_earnings_calendar,
    "get_market_movers": tool_get_market_movers,
    "get_market_status": tool_get_market_status,
    "get_watchlist": tool_get_watchlist,
    "add_to_watchlist": tool_add_to_watchlist,
    "remove_from_watchlist": tool_remove_from_watchlist,
    "toggle_watchlist_alert": tool_toggle_watchlist_alert,
    "get_todays_buy_candidates": tool_get_todays_buy_candidates,
    "get_recent_screening_results": tool_get_recent_screening_results,
    "get_latest_screen_for_ticker": tool_get_latest_screen_for_ticker,
    "run_deep_dive_screen": tool_run_deep_dive_screen,
    "get_portfolio_holdings": tool_get_portfolio_holdings,
    "get_portfolio_overlap": tool_get_portfolio_overlap,
    "discover_stocks_by_thesis": tool_discover_stocks_by_thesis,
    "lookup_financial_term": tool_lookup_financial_term,
}

# ─────────────────────────────────────────────────────────────────────────────
# Claude tool schemas (sent to the API)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_stock_fundamentals",
        "description": (
            "Fetch key fundamental metrics for a single stock ticker: P/E, forward P/E, PEG, "
            "P/B, P/S, EV/EBITDA, margins, ROE, ROA, debt/equity, revenue growth, earnings growth, "
            "52-week range, analyst target price and recommendation, sector, and market cap. "
            "Use this when the user asks about a specific company's valuation, financials, or whether to invest."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol, e.g. 'AAPL'",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_stock_news",
        "description": (
            "Fetch recent news headlines and summaries for a specific stock. "
            "Use this when the user asks about recent news, catalysts, or sentiment for a company."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol, e.g. 'NVDA'"},
                "company_name": {
                    "type": "string",
                    "description": "Full company name for better news matching, e.g. 'NVIDIA Corporation'",
                },
                "days": {
                    "type": "integer",
                    "description": "Lookback window in days (default 7)",
                    "default": 7,
                },
            },
            "required": ["ticker", "company_name"],
        },
    },
    {
        "name": "get_stock_price",
        "description": (
            "Get the current last-trade price for one or more tickers. "
            "Use this for quick price checks or when building a stock comparison."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ticker symbols, e.g. ['AAPL', 'MSFT']",
                }
            },
            "required": ["tickers"],
        },
    },
    {
        "name": "get_earnings_calendar",
        "description": (
            "Get the next earnings date, EPS estimate, and revenue estimate for a stock. "
            "Use this when the user asks about upcoming earnings or near-term catalysts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_market_movers",
        "description": (
            "Fetch today's top movers for a market index sorted by percent change or volume. "
            "Use this when the user asks what moved in a sector or the broader market today."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "string",
                    "description": "Market index: '$SPX', '$COMPX', '$DJI', 'NYSE', or 'NASDAQ' (default '$SPX')",
                    "default": "$SPX",
                },
                "sort": {
                    "type": "string",
                    "description": "Sort order: 'PERCENT_CHANGE_UP', 'PERCENT_CHANGE_DOWN', 'VOLUME', or 'TRADES' (default 'PERCENT_CHANGE_UP')",
                    "default": "PERCENT_CHANGE_UP",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of movers to return (default 10)",
                    "default": 10,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_market_status",
        "description": (
            "Check whether the US stock market is currently open. "
            "Use this for time-sensitive questions about live data availability."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_watchlist",
        "description": (
            "Return all stocks on the user's watchlist with target buy prices, notes, and alert status. "
            "Use this for any question about the user's watchlist or tracked stocks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "add_to_watchlist",
        "description": (
            "Add or update a stock on the user's watchlist, optionally with a target buy price and notes. "
            "Only call this when the user explicitly asks to add or track a stock."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol to add"},
                "target_buy_price": {
                    "type": "number",
                    "description": "Target price to buy at (optional)",
                },
                "notes": {
                    "type": "string",
                    "description": "Notes about the stock or reason for watching (optional)",
                },
                "alert_active": {
                    "type": "boolean",
                    "description": "Whether to enable price alerts (default true)",
                    "default": True,
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "remove_from_watchlist",
        "description": (
            "Remove a stock from the user's watchlist. "
            "Only call this when the user explicitly asks to remove or delete a ticker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol to remove"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "toggle_watchlist_alert",
        "description": (
            "Enable or disable the price alert for a watchlist entry. "
            "Use this when the user wants to turn alerts on or off for a stock."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol"},
                "active": {"type": "boolean", "description": "True to enable alerts, False to disable"},
            },
            "required": ["ticker", "active"],
        },
    },
    {
        "name": "get_todays_buy_candidates",
        "description": (
            "Return today's top AI-screened BUY candidates from the database, sorted by score. "
            "Use this when the user asks for today's best opportunities, top picks, or recommendations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of candidates to return (default 10)",
                    "default": 10,
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_recent_screening_results",
        "description": (
            "Return the most recent AI screening result per ticker within the last N hours. "
            "Use this for questions about recently analyzed stocks or screening history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "Lookback window in hours (default 24)",
                    "default": 24,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 20)",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_latest_screen_for_ticker",
        "description": (
            "Fetch the most recent AI screening result (score, verdict, reasoning, valuation) for a specific ticker "
            "from the database. Use this before recommending whether to buy/sell/hold a specific stock, "
            "and before running a fresh deep dive."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "run_deep_dive_screen",
        "description": (
            "Run a fresh AI analysis (fundamentals + news + Claude scoring) on a specific ticker. "
            "This takes 10–20 seconds. Only call this when the user explicitly asks for a "
            "'deep dive', 'fresh screen', or 'full analysis', or when no cached result exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol to analyze"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_portfolio_holdings",
        "description": (
            "Fetch the user's current Schwab portfolio positions with unrealized P&L percent and portfolio weight. "
            "Returns an empty list with a note if Schwab is not connected. "
            "Use this for questions about current holdings, sell decisions, or portfolio composition."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_portfolio_overlap",
        "description": (
            "Compare the user's current holdings against today's BUY candidates and watchlist. "
            "Returns which holdings are also BUY signals (buy_candidates_owned) and which BUY candidates "
            "are not yet owned (buy_candidates_not_owned). "
            "Use this for 'what BUY candidates don't I own yet?' or portfolio vs screener questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "discover_stocks_by_thesis",
        "description": (
            "Given a natural-language investment thesis, identify relevant stocks and ETFs. "
            "Use this when the user wants ideas related to a theme, sector, or macro trend "
            "rather than asking about a specific ticker. Returns a theme summary, 10-20 stocks, and 3-6 ETFs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "thesis": {
                    "type": "string",
                    "description": "Natural language investment thesis, e.g. 'AI infrastructure buildout: chips and data centers'",
                }
            },
            "required": ["thesis"],
        },
    },
    {
        "name": "lookup_financial_term",
        "description": (
            "Look up a financial term, ratio, or concept from the local glossary. "
            "Use this for definitional questions like 'What is P/E ratio?', 'What does PEG mean?', "
            "'What is P/L?', 'Explain EV/EBITDA'. This is fast and uses no external API."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "The financial term to look up, e.g. 'P/E Ratio', 'P/L', 'EBITDA'",
                }
            },
            "required": ["term"],
        },
    },
]
