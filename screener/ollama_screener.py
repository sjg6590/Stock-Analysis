"""Local LLM screening via Ollama."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import ollama
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a financial analyst assistant. You will be given structured data about a stock.
Your job is to analyze it and return a JSON object with exactly these fields:
{
  "ticker": "string",
  "score": 0-100,
  "verdict": "BUY_CANDIDATE" | "WATCH" | "AVOID",
  "valuation_status": "UNDERVALUED" | "FAIRLY_VALUED" | "OVERVALUED",
  "estimated_upside_percent": float,
  "key_strengths": ["string", ...],
  "key_risks": ["string", ...],
  "news_sentiment": "POSITIVE" | "NEUTRAL" | "NEGATIVE",
  "news_summary": "string (2 sentences max)",
  "suggested_buy_price": float or null,
  "reasoning": "string (3-4 sentences)"
}
Return ONLY valid JSON. No markdown, no explanation outside the JSON.
"""


def safe_parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    cleaned = cleaned.replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in LLM output: {cleaned[:200]}")
    return json.loads(match.group())


class OllamaScreener:
    def __init__(self, model: str, host: str) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self._client = ollama.Client(host=self.host)

    def build_prompt(self, stock_data: dict[str, Any], news_items: list[dict[str, Any]], sector_pe: float | None) -> str:
        f = stock_data
        name = f.get("company_name", f.get("ticker"))
        lines = [
            f"Company: {name} ({f.get('ticker')})",
            f"Sector: {f.get('sector')} | Industry: {f.get('industry')}",
            "",
            "Ratios:",
            f"  P/E trailing: {f.get('pe_ratio')} | forward: {f.get('forward_pe')} | PEG: {f.get('peg_ratio')}",
            f"  P/B: {f.get('price_to_book')} | P/S: {f.get('price_to_sales')} | EV/EBITDA: {f.get('ev_to_ebitda')}",
            f"  Market cap: {f.get('market_cap')} | EV: {f.get('enterprise_value')}",
            f"  Debt/Equity: {f.get('debt_to_equity')} | Current ratio: {f.get('current_ratio')}",
            f"  Margins profit/operating: {f.get('profit_margin')} / {f.get('operating_margin')}",
            f"  ROE/ROA: {f.get('roe')} / {f.get('roa')} | Div yield: {f.get('dividend_yield')}",
            f"  Revenue YoY growth: {f.get('revenue_growth')} | Earnings YoY growth: {f.get('earnings_growth')}",
            "",
            f"Price: {f.get('current_price')} (prev close {f.get('previous_close')})",
            f"52w high/low: {f.get('52_week_high')} / {f.get('52_week_low')}",
        ]
        hi, lo, px = f.get("52_week_high"), f.get("52_week_low"), f.get("current_price")
        if hi and lo and px:
            try:
                d_hi = (float(hi) - float(px)) / float(hi) * 100
                d_lo = (float(px) - float(lo)) / float(lo) * 100
                lines.append(f"Distance from 52w high: {d_hi:.1f}% | from 52w low: +{d_lo:.1f}%")
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        if sector_pe is not None and f.get("pe_ratio"):
            lines.append(f"Sector P/E proxy: {sector_pe:.2f} vs stock P/E: {f.get('pe_ratio')}")
        tgt = f.get("analyst_target_price")
        if tgt and px:
            try:
                up = (float(tgt) - float(px)) / float(px) * 100
                lines.append(f"Analyst target: {tgt} ({up:+.1f}% vs current)")
            except (TypeError, ValueError, ZeroDivisionError):
                lines.append(f"Analyst target: {tgt}")
        lines.append(f"Analyst recommendation key: {f.get('analyst_recommendation')}")
        lines.extend(["", "Recent headlines (max 5):"])
        for n in news_items[:5]:
            lines.append(f"  - [{n.get('published_at', '')}] {n.get('title', '')[:120]}")
        prompt = "\n".join(lines)
        if len(prompt) > 12000:
            prompt = prompt[:12000] + "\n...[truncated]"
        return prompt

    def screen_stock(self, ticker: str, stock_data: dict[str, Any], news: list[dict[str, Any]]) -> dict[str, Any]:
        sector = stock_data.get("sector")
        sector_pe = stock_data.get("_sector_pe")
        if sector_pe is None and sector:
            from data.fetchers.yfinance_fetcher import StockFetcher

            sector_pe = StockFetcher(delay_sec=0).get_sector_pe(str(sector))
        user_content = self.build_prompt(stock_data, news, sector_pe)
        last_err: str | None = None
        for attempt in range(3):
            try:
                resp = self._client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    options={"temperature": 0.1},
                    stream=False,
                )
                text = resp["message"]["content"]
                parsed = safe_parse_llm_json(text)
                parsed["ticker"] = ticker.upper()
                return parsed
            except Exception as e:
                last_err = str(e)
                logger.warning("screen_stock %s attempt %s: %s", ticker, attempt + 1, e)
        return {
            "ticker": ticker.upper(),
            "score": 0,
            "verdict": "ERROR",
            "valuation_status": "FAIRLY_VALUED",
            "estimated_upside_percent": 0.0,
            "key_strengths": [],
            "key_risks": [],
            "news_sentiment": "NEUTRAL",
            "news_summary": "",
            "suggested_buy_price": None,
            "reasoning": last_err or "parse failure",
        }

    def screen_batch(self, stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("Screening", total=len(stocks))
            for item in stocks:
                t = item["ticker"]
                res = self.screen_stock(t, item["fundamentals"], item.get("news", []))
                results.append(res)
                progress.advance(task)
        # Preserve input order; callers may sort for display.
        return results
