"""Anthropic Claude API screening — faster than local Ollama via concurrent API calls."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import anthropic
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from screener.ollama_screener import SYSTEM_PROMPT, safe_parse_llm_json

logger = logging.getLogger(__name__)


class ClaudeScreener:
    def __init__(self, model: str, api_key: str = "", max_workers: int = 5) -> None:
        self.model = model
        self.max_workers = max(1, max_workers)
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

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
                resp = self._client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user_content}],
                )
                text = next(
                    (block.text for block in resp.content if block.type == "text"), ""
                )
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
        results: dict[str, dict[str, Any]] = {}
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("Screening (Claude)", total=len(stocks))
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {
                    pool.submit(
                        self.screen_stock,
                        item["ticker"],
                        item["fundamentals"],
                        item.get("news", []),
                    ): item["ticker"]
                    for item in stocks
                }
                for fut in as_completed(futures):
                    ticker = futures[fut]
                    try:
                        results[ticker] = fut.result()
                    except Exception as e:
                        logger.error("screen_batch unexpected error %s: %s", ticker, e)
                        results[ticker] = {
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
                            "reasoning": str(e),
                        }
                    progress.advance(task)
        # Restore original input order
        ticker_order = {item["ticker"]: i for i, item in enumerate(stocks)}
        return sorted(results.values(), key=lambda r: ticker_order.get((r.get("ticker") or "").upper(), 0))
