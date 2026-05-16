"""Core RAG chatbot for the stock analyzer.

StockChatbot runs a Claude tool-use loop, accumulates sources from each tool
result, computes a rule-based confidence score, and returns a ChatResponse.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from dashboard.chatbot_tools import TOOL_DISPATCH, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 6
MAX_HISTORY_TURNS = 10  # keep last N turns to limit token cost

SYSTEM_PROMPT = """You are an expert stock analyst assistant embedded in an AI Stock Analyzer application.
You have access to real-time market data, the user's watchlist, their Schwab portfolio,
AI screening results, news, and a financial glossary.

## Tool usage rules
1. ALWAYS use tools to fetch current data before answering questions about specific stocks,
   prices, news, the user's watchlist, or portfolio. Do not answer from your training-data
   prices — they are stale and potentially months out of date.
2. For definitional questions ("What is P/E?", "What does P/L mean?"), call lookup_financial_term first.
3. For "what stocks from my watchlist should I watch?" — call get_watchlist and get_todays_buy_candidates.
4. For "should I sell a holding?" — call get_portfolio_holdings, then get_latest_screen_for_ticker
   for each holding to check the AI verdict, unrealized_pnl_pct, and estimated_upside_percent.
5. For "run a deep dive on X" or "fresh analysis of X" — call run_deep_dive_screen.
   This takes 10–20 seconds; that is expected and normal.
6. For "add X to my watchlist" or "can you add X?" — call add_to_watchlist and confirm explicitly.
7. For "what BUY candidates don't I own?" — call get_portfolio_overlap.
8. For "biggest movers today" or sector movement questions — call get_market_movers.
9. For comparing two stocks — call get_stock_fundamentals and get_stock_price for each.
10. You may call multiple tools in sequence when a question requires chaining data.

## Response style
- Write in clear, concise markdown. Use tables or bullet lists for multiple data points.
- Quote specific numbers from tool results (price, P/E, score, analyst target, etc.).
- Keep responses under 400 words unless the user explicitly asks for a deep dive or detailed report.
- Never hallucinate ticker symbols. If a ticker cannot be found, say so.
- Note data freshness when presenting cached screening results (check the screened_at timestamp).

## Disclaimer
You are a financial research assistant, not a licensed financial advisor. Always note that
users should consult a professional before making investment decisions when giving buy/sell guidance.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Response model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChatSource:
    label: str
    source_type: str = "live_data"  # "live_data" | "database" | "static_grounding"
    ticker: str = ""


@dataclass
class ChatResponse:
    text: str
    sources: list[ChatSource] = field(default_factory=list)
    confidence: int = 50
    confidence_label: str = "Medium"
    tools_called: list[str] = field(default_factory=list)
    action_taken: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Confidence scoring
# ─────────────────────────────────────────────────────────────────────────────

def _compute_confidence(
    tool_results: list[dict[str, Any]],
    tools_called: list[str],
    errors: list[str],
) -> tuple[int, str]:
    if not tools_called:
        score = 45
    elif tools_called == ["lookup_financial_term"]:
        found = any(r.get("found") for r in tool_results)
        score = 90 if found else 55
    else:
        # Check if any live market data was fetched
        live_tools = {
            "get_stock_fundamentals", "get_stock_price", "get_earnings_calendar",
            "get_market_movers", "get_market_status", "get_stock_news",
        }
        has_live = bool(set(tools_called) & live_tools)
        score = 75 if has_live else 60

        # Boost for fresh deep dive
        if "run_deep_dive_screen" in tools_called:
            has_error = any(
                r.get("verdict") == "ERROR"
                for r in tool_results
                if isinstance(r, dict)
            )
            score += 0 if has_error else 15

        # Penalise stale cached screening data (>48h old)
        for r in tool_results:
            screened_at = r.get("screened_at") or (r.get("result") or {}).get("screened_at")
            if screened_at:
                try:
                    ts_str = str(screened_at)
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
                    if age_h > 48:
                        score -= 15
                except Exception:
                    pass

        # Penalise disconnected Schwab
        for r in tool_results:
            if isinstance(r, dict) and r.get("connected") is False:
                score -= 20
                break

    # Penalise any tool errors
    if errors:
        score -= 25 * min(len(errors), 2)

    score = max(10, min(95, score))
    label = "High" if score >= 70 else ("Medium" if score >= 45 else "Low")
    return score, label


# ─────────────────────────────────────────────────────────────────────────────
# Main chatbot class
# ─────────────────────────────────────────────────────────────────────────────

class StockChatbot:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def chat(
        self,
        user_message: str,
        history: list[dict[str, Any]],
    ) -> ChatResponse:
        """Run the tool-use loop and return a structured ChatResponse."""
        # Trim history to keep token cost bounded
        trimmed = history[-(MAX_HISTORY_TURNS * 2):]
        messages: list[dict[str, Any]] = trimmed + [
            {"role": "user", "content": user_message}
        ]

        tools_called: list[str] = []
        tool_results_collected: list[dict[str, Any]] = []
        sources: list[ChatSource] = []
        action_taken: str | None = None
        errors: list[str] = []
        final_text = ""

        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                response = self._client.messages.create(
                    model=settings.CLAUDE_MODEL,
                    max_tokens=2048,
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tools=TOOL_SCHEMAS,
                    messages=messages,
                )
            except Exception as exc:
                logger.error("Claude API error: %s", exc)
                errors.append(str(exc))
                final_text = "I encountered an error connecting to the AI service. Please try again."
                break

            if response.stop_reason == "end_turn":
                final_text = _extract_text(response.content)
                break

            if response.stop_reason == "tool_use":
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                tool_result_parts: list[dict[str, Any]] = []

                for block in tool_use_blocks:
                    tools_called.append(block.name)
                    try:
                        fn = TOOL_DISPATCH[block.name]
                        result: dict[str, Any] = fn(**block.input)
                        source_meta = result.pop("_source", None)
                        if source_meta:
                            sources.append(
                                ChatSource(
                                    label=source_meta.get("source", block.name),
                                    source_type=source_meta.get("type", "live_data"),
                                    ticker=source_meta.get("ticker", ""),
                                )
                            )
                        tool_results_collected.append(result)

                        # Detect side-effect actions for confirmation banner
                        if block.name == "add_to_watchlist":
                            t = block.input.get("ticker", "")
                            price = block.input.get("target_buy_price")
                            action_taken = f"Added {t} to watchlist" + (
                                f" with target ${price:.2f}" if price else ""
                            )
                        elif block.name == "remove_from_watchlist":
                            action_taken = f"Removed {block.input.get('ticker', '')} from watchlist"
                        elif block.name == "toggle_watchlist_alert":
                            state = "enabled" if block.input.get("active") else "disabled"
                            action_taken = f"Alert {state} for {block.input.get('ticker', '')}"

                        tool_result_parts.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                            }
                        )
                    except Exception as exc:
                        logger.warning("Tool %s failed: %s", block.name, exc)
                        errors.append(str(exc))
                        tool_result_parts.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"error": str(exc)}),
                                "is_error": True,
                            }
                        )

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_result_parts})
            else:
                final_text = _extract_text(response.content)
                break
        else:
            final_text = (
                "I reached the maximum analysis steps. Here is what I found:\n\n"
                + final_text
            )

        confidence, confidence_label = _compute_confidence(
            tool_results_collected, tools_called, errors
        )

        return ChatResponse(
            text=final_text or "No response generated.",
            sources=sources,
            confidence=confidence,
            confidence_label=confidence_label,
            tools_called=tools_called,
            action_taken=action_taken,
        )


def _extract_text(content: list[Any]) -> str:
    return "\n".join(
        block.text for block in content if hasattr(block, "text") and block.text
    ).strip()
