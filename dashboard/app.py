"""Streamlit UI for screening results and tools."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.thinkscript_generator import ThinkScriptGenerator
from config import settings
from dashboard.chatbot import ChatResponse, StockChatbot
from data.fetchers.news_fetcher import NewsFetcher
from data.fetchers.yfinance_fetcher import StockFetcher
from data.market_data_provider import MarketDataProvider
from data.schwab_service import SchwabNotConnectedError, SchwabService
from screener.batch_runner import run_pipeline
from screener.ollama_screener import OllamaScreener
from screener.thesis_screener import ThesisScreener
from storage import queries
from storage.database import ScreeningResult, get_engine

st.set_page_config(page_title="AI Stock Analyzer", layout="wide")


def _inject_chat_fab() -> None:
    """Inject JS to pin the 💬 button to the bottom-right.

    Finds the button by its exact text content, so no other button is affected.
    """
    st.html(
        """
        <script>
        (function () {
            function applyFab() {
                try {
                    const btns = document.querySelectorAll(
                        'button[kind="secondary"]'
                    );
                    for (const btn of btns) {
                        if (btn.textContent.trim() === '💬') {
                            btn.style.setProperty('position', 'fixed', 'important');
                            btn.style.setProperty('bottom', '2rem', 'important');
                            btn.style.setProperty('right', '2rem', 'important');
                            btn.style.setProperty('z-index', '99999', 'important');
                            btn.style.setProperty('width', '56px', 'important');
                            btn.style.setProperty('height', '56px', 'important');
                            btn.style.setProperty('border-radius', '50%', 'important');
                            btn.style.setProperty('font-size', '22px', 'important');
                            btn.style.setProperty('padding', '0', 'important');
                            btn.style.setProperty('background-color', '#1a56db', 'important');
                            btn.style.setProperty('color', 'white', 'important');
                            btn.style.setProperty('border', 'none', 'important');
                            btn.style.setProperty('box-shadow', '0 4px 16px rgba(0,0,0,0.35)', 'important');
                            btn.style.setProperty('line-height', '1', 'important');
                            btn.style.setProperty('cursor', 'pointer', 'important');
                            // Also fix the parent wrapper so it doesn't push layout
                            const wrapper = btn.closest('div[data-testid="stButton"]');
                            if (wrapper) {
                                wrapper.style.setProperty('position', 'fixed', 'important');
                                wrapper.style.setProperty('bottom', '2rem', 'important');
                                wrapper.style.setProperty('right', '2rem', 'important');
                                wrapper.style.setProperty('z-index', '99999', 'important');
                                wrapper.style.setProperty('width', '56px', 'important');
                                wrapper.style.setProperty('height', '56px', 'important');
                            }
                            break;
                        }
                    }
                } catch (e) { /* cross-origin guard */ }
            }
            applyFab();
            const obs = new MutationObserver(applyFab);
            obs.observe(document.body, { childList: true, subtree: true });
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def _verdict_row_cell_css(verdict: str | None) -> str:
    """Row highlight for st.dataframe: dark fills + light text (pastels + Streamlit default text = poor contrast)."""
    v = verdict or ""
    if v == "BUY_CANDIDATE":
        return "background-color: #146c43; color: #f8fafc"
    if v == "WATCH":
        return "background-color: #a16207; color: #f8fafc"
    if v == "AVOID":
        return "background-color: #9f1239; color: #f8fafc"
    return ""


def _score_history(ticker: str, limit: int = 30) -> pd.DataFrame:
    engine = get_engine()
    with Session(engine) as session:
        rows = session.scalars(
            select(ScreeningResult)
            .where(ScreeningResult.ticker == ticker.upper())
            .order_by(ScreeningResult.screened_at.desc())
            .limit(limit)
        ).all()
    if not rows:
        return pd.DataFrame()
    data = [{"screened_at": r.screened_at, "score": r.score, "verdict": r.verdict} for r in reversed(rows)]
    df = pd.DataFrame(data)
    df["screened_at"] = pd.to_datetime(df["screened_at"], errors="coerce")
    return df.set_index("screened_at")


def page_shortlist() -> None:
    st.header("Daily shortlist")
    rows = queries.today_top_buy_candidates(100)
    if not rows:
        st.info("No screening rows yet. Run `python main.py` from the project folder.")
        return

    col_info, col_btn = st.columns([4, 1])
    with col_info:
        st.caption(f"{len(rows)} unique BUY candidates today")
    with col_btn:
        if st.button("Re-screen all", help="Re-run the full screening pipeline for every ticker in today's shortlist"):
            tickers = [r["ticker"] for r in rows]
            with st.spinner(f"Re-screening {len(tickers)} tickers…"):
                updated = run_pipeline(tickers, save_db=True, export_high_scores=True)
            updated = sorted(updated, key=lambda x: x.get("score") or 0, reverse=True)
            st.session_state["shortlist_refresh"] = updated
            st.rerun()

    display_rows = st.session_state.get("shortlist_refresh") or rows
    df = pd.DataFrame(display_rows)

    def style_row(row: pd.Series) -> list[str]:
        css = _verdict_row_cell_css(row.get("verdict", ""))
        return [css] * len(row) if css else [""] * len(row)

    st.dataframe(df.style.apply(style_row, axis=1), width="stretch", height=400)
    pick = st.selectbox("Expand reasoning", df["ticker"].tolist())
    r = next(x for x in display_rows if x["ticker"] == pick)
    st.markdown(r.get("reasoning") or "_No reasoning_")

    st.subheader(f"Score history — {pick}")
    hist = _score_history(pick)
    if not hist.empty and "score" in hist.columns:
        st.line_chart(hist["score"])


def _build_notes_default(result: dict) -> str:
    """Build a default notes string from a screening result."""
    strengths = result.get("key_strengths")
    if isinstance(strengths, list) and strengths:
        return "; ".join(str(s) for s in strengths)
    return result.get("reasoning") or ""


def _add_to_watchlist_ui(results: list[dict], key_prefix: str = "main") -> None:
    """Inline form to add a screened ticker to the watchlist with pre-populated fields."""
    ticker_opts = [r["ticker"] for r in results if r.get("ticker")]
    if not ticker_opts:
        return

    selected = st.selectbox("Ticker", ticker_opts, key=f"{key_prefix}_wl_sel")
    r = next((x for x in results if x.get("ticker") == selected), {})

    suggested = r.get("suggested_buy_price")
    default_notes = _build_notes_default(r)

    c1, c2 = st.columns([1, 2])
    with c1:
        price = st.number_input(
            "Target buy price",
            value=float(suggested) if suggested else 0.0,
            min_value=0.0,
            step=0.5,
            key=f"{key_prefix}_wl_price_{selected}",
        )
    with c2:
        notes = st.text_area(
            "Notes",
            value=default_notes,
            height=80,
            key=f"{key_prefix}_wl_notes_{selected}",
        )

    if st.button("Add to Watchlist", key=f"{key_prefix}_wl_btn"):
        queries.upsert_watchlist(selected, price or None, notes or None, True)
        st.success(f"{selected} added to watchlist with target buy ${price:.2f}")


def _show_screening_table(results: list[dict], key_prefix: str = "main") -> None:
    """Render a color-coded screening results table, reasoning expander, and watchlist form."""
    if not results:
        return

    df = pd.DataFrame(results)

    def _style(row: pd.Series) -> list[str]:
        css = _verdict_row_cell_css(row.get("verdict", ""))
        return [css] * len(row) if css else [""] * len(row)

    st.subheader("Screening results")
    st.dataframe(df.style.apply(_style, axis=1), width="stretch", height=400)

    tickers = [r["ticker"] for r in results if r.get("ticker")]
    if tickers:
        pick = st.selectbox("Expand reasoning", tickers, key=f"{key_prefix}_reason_pick")
        r = next((x for x in results if x.get("ticker") == pick), {})
        st.markdown(r.get("reasoning") or "_No reasoning_")

    st.subheader("Add to Watchlist")
    _add_to_watchlist_ui(results, key_prefix=key_prefix)


def page_watchlist() -> None:
    st.header("Watchlist")
    rows = queries.list_watchlist()
    st.dataframe(pd.DataFrame(rows), width="stretch")
    c1, c2, c3 = st.columns(3)
    with c1:
        t = st.text_input("Ticker").upper().strip()
    with c2:
        price = st.number_input("Target buy", min_value=0.0, value=0.0, step=0.5)
    with c3:
        notes = st.text_input("Notes")
    if st.button("Add / update"):
        if t:
            queries.upsert_watchlist(t, price or None, notes or None, True)
            st.success("Saved")
            st.rerun()
    rem = st.text_input("Remove ticker").upper().strip()
    if st.button("Remove") and rem:
        queries.remove_watchlist(rem)
        st.rerun()
    st.subheader("Alert history")
    st.dataframe(pd.DataFrame(queries.recent_alerts()), width="stretch")


@st.cache_data(ttl=settings.SCHWAB_HISTORY_CACHE_SEC)
def _load_ohlcv(ticker: str) -> tuple[pd.DataFrame, str]:
    mdp = MarketDataProvider()
    df = mdp.get_ohlcv(ticker)
    return df, mdp.source_label()


def page_deep_dive() -> None:
    st.header("Stock deep dive")
    t = st.text_input("Ticker", value="AAPL").upper().strip()
    if not t:
        return
    fetcher = StockFetcher()
    nf = NewsFetcher()

    fund_key = f"fund_{t}"
    news_key = f"news_{t}"

    if st.button("Load fundamentals"):
        fund = fetcher.get_fundamentals(t)
        st.session_state[fund_key] = fund
        hist, hist_source = _load_ohlcv(t)
        if not hist.empty:
            close_col = "close" if "close" in hist.columns else ("Close" if "Close" in hist.columns else None)
            if close_col:
                st.line_chart(hist[close_col])
                st.caption(f"Prices: {hist_source}")
        st.json(fund)

    if fund_key not in st.session_state:
        st.info("Click 'Load fundamentals' to fetch data.")

    news = st.session_state.get(news_key)
    if news is None:
        news = nf.get_recent_news(t, t)
        st.session_state[news_key] = news
    st.subheader("News")
    st.dataframe(pd.DataFrame(news), width="stretch")

    if st.button("Run LLM screen (on demand)"):
        fund = st.session_state.get(fund_key)
        if fund is None:
            with st.spinner("Fetching fundamentals…"):
                fund = fetcher.get_fundamentals(t)
                st.session_state[fund_key] = fund
        spinner_msg = "Calling Claude…" if settings.LLM_PROVIDER == "claude" else "Calling Ollama…"
        with st.spinner(spinner_msg):
            fund["_sector_pe"] = fetcher.get_sector_pe(str(fund.get("sector") or ""))
            if settings.LLM_PROVIDER == "claude":
                from screener.claude_screener import ClaudeScreener
                sc = ClaudeScreener(
                    model=settings.CLAUDE_MODEL,
                    api_key=settings.ANTHROPIC_API_KEY,
                    max_workers=1,
                )
            else:
                sc = OllamaScreener(settings.OLLAMA_MODEL, settings.OLLAMA_HOST)
            res = sc.screen_stock(t, fund, news)
        st.json(res)


def page_discover() -> None:
    st.header("Discover by thesis")
    st.caption(
        "Describe an investment idea in plain English. The LLM will suggest relevant stocks and ETFs, "
        "then run them through the full screening pipeline."
    )

    thesis = st.text_area(
        "Investment thesis",
        placeholder=(
            "e.g. AI is replacing SaaS — I want to invest in the hardware layer: chips, "
            "semiconductors, GPUs, and data center infrastructure."
        ),
        height=120,
        key="discover_thesis",
    )

    col1, col2 = st.columns(2)
    with col1:
        skip_prefilter = st.checkbox("Skip pre-filter (send all discovered tickers to LLM screener)")
    with col2:
        list_only = st.checkbox("Show tickers only — skip screening")

    btn_col1, btn_col2 = st.columns([3, 1])
    with btn_col1:
        discover_clicked = st.button("Discover", disabled=not thesis.strip())
    with btn_col2:
        has_cached = st.session_state.get("discover_results") or st.session_state.get("discover_discovery")
        if has_cached and st.button("Clear results"):
            for k in ("discover_results", "discover_discovery", "discover_tickers"):
                st.session_state.pop(k, None)
            st.rerun()

    if discover_clicked:
        ts = ThesisScreener()

        with st.spinner("Asking LLM to identify relevant tickers…"):
            try:
                discovery = ts.discover(thesis)
            except RuntimeError as e:
                st.error(str(e))
                return

        st.session_state["discover_discovery"] = discovery
        tickers = ts.tickers_from_discovery(discovery)
        st.session_state["discover_tickers"] = tickers
        st.session_state.pop("discover_results", None)

        if not list_only and tickers:
            with st.spinner(f"Screening {len(tickers)} tickers…"):
                results = run_pipeline(
                    tickers,
                    skip_prefilter=skip_prefilter,
                    save_db=True,
                    export_high_scores=True,
                )
            results = sorted(results, key=lambda r: r.get("score") or 0, reverse=True)
            st.session_state["discover_results"] = results

    # Always render from session state — persists across page navigation
    discovery = st.session_state.get("discover_discovery")
    tickers = st.session_state.get("discover_tickers", [])
    results = st.session_state.get("discover_results", [])

    if discovery:
        st.success(f"**Theme:** {discovery.get('theme', '')}")
        stocks = discovery.get("stocks", [])
        etfs = discovery.get("etfs", [])
        if stocks:
            st.subheader("Stocks")
            st.dataframe(pd.DataFrame(stocks), width="stretch")
        if etfs:
            st.subheader("ETFs")
            st.dataframe(pd.DataFrame(etfs), width="stretch")
        if tickers:
            st.info(f"Discovered {len(tickers)} tickers: {', '.join(tickers)}")

    if results:
        _show_screening_table(results, key_prefix="discover")

    # ------------------------------------------------------------------
    # Screening history (loads from SQLite)
    # ------------------------------------------------------------------
    with st.expander("Screening history"):
        st.caption("Load previously screened tickers from the database.")
        h_col1, h_col2 = st.columns([2, 1])
        with h_col1:
            lookback_label = st.selectbox(
                "Lookback window",
                options=["Last 24 hours", "Last 48 hours", "Last 7 days", "Last 30 days"],
                key="hist_window",
            )
        lookback_map = {
            "Last 24 hours": 24,
            "Last 48 hours": 48,
            "Last 7 days": 168,
            "Last 30 days": 720,
        }
        with h_col2:
            st.write("")
            if st.button("Load history", key="load_hist_btn"):
                hist = queries.recent_screening_results(hours=lookback_map[lookback_label])
                st.session_state["history_results"] = hist

        hist_results = st.session_state.get("history_results")
        if hist_results is not None:
            if hist_results:
                _show_screening_table(hist_results, key_prefix="history")
            else:
                st.info("No results found in this time window.")

    # ------------------------------------------------------------------
    # Market movers (Schwab)
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("Today's market movers")
    st.caption("Schwab API returns the top 10 movers per index/sort combination.")

    if not (settings.USE_SCHWAB and settings.USE_SCHWAB_FOR_MOVERS):
        st.info("Enable `USE_SCHWAB=true` and `USE_SCHWAB_FOR_MOVERS=true` in `.env` to see movers.")
    else:
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            mover_index = st.selectbox(
                "Index", ["$SPX", "$COMPX", "$DJI", "NYSE", "NASDAQ"], key="mover_index"
            )
        with m_col2:
            mover_sort = st.selectbox(
                "Sort by",
                ["PERCENT_CHANGE_UP", "PERCENT_CHANGE_DOWN", "VOLUME", "TRADES"],
                key="mover_sort",
            )

        if st.button("Load movers"):
            with st.spinner("Fetching movers from Schwab…"):
                mdp = MarketDataProvider()
                movers = mdp.get_movers(index=mover_index, sort=mover_sort)
            st.session_state["movers_data"] = movers
            st.session_state.pop("movers_results", None)

        movers = st.session_state.get("movers_data")
        if movers:
            display_cols = ["ticker", "description", "last_price", "change", "change_pct", "volume", "trades", "market_share_pct", "direction"]
            df_movers = pd.DataFrame(movers)[[c for c in display_cols if c in pd.DataFrame(movers).columns]]
            df_movers = df_movers.rename(columns={
                "ticker": "Ticker",
                "description": "Name",
                "last_price": "Last",
                "change": "Change $",
                "change_pct": "Change %",
                "volume": "Volume",
                "trades": "Trades",
                "market_share_pct": "Mkt Share %",
                "direction": "Dir",
            })
            st.dataframe(df_movers, width="stretch")

            screen_tickers = [m["ticker"] for m in movers if m.get("ticker")]
            if screen_tickers and st.button(f"Screen all {len(screen_tickers)} movers"):
                with st.spinner(f"Screening {len(screen_tickers)} movers…"):
                    mover_results = run_pipeline(screen_tickers, save_db=True, export_high_scores=True)
                mover_results = sorted(mover_results, key=lambda x: x.get("score") or 0, reverse=True)
                st.session_state["movers_results"] = mover_results

        movers_results = st.session_state.get("movers_results", [])
        if movers_results:
            _show_screening_table(movers_results, key_prefix="movers")
        elif movers is not None and not movers:
            st.info("No movers returned — market may be closed or Schwab token needs refresh.")


@st.cache_data(ttl=settings.SCHWAB_PORTFOLIO_CACHE_SEC)
def _load_positions() -> list[dict]:
    svc = SchwabService()
    return svc.get_positions_normalized()


def page_portfolio() -> None:
    st.header("Portfolio")

    if not (settings.USE_SCHWAB and settings.USE_SCHWAB_FOR_PORTFOLIO):
        st.info("Schwab portfolio disabled. Set `USE_SCHWAB=true` and `USE_SCHWAB_FOR_PORTFOLIO=true` in `.env`.")
        return

    svc = SchwabService()

    # Connection banner
    if svc.is_connected():
        st.success("Schwab connected")
    else:
        st.warning(
            "Schwab not connected or token missing.  \n"
            "Re-authenticate from a terminal:  \n"
            "```\npython main.py schwab auth\n```"
        )
        return

    # Holdings table
    st.subheader("Holdings")
    col_refresh, _ = st.columns([1, 5])
    with col_refresh:
        if st.button("Refresh"):
            st.cache_data.clear()
            st.rerun()

    try:
        positions = _load_positions()
    except SchwabNotConnectedError as exc:
        st.error(f"Could not load positions: {exc}")
        return

    if not positions:
        st.info("No positions found in your Schwab account.")
    else:
        df_pos = pd.DataFrame(positions)
        # Friendly column order / rename
        col_map = {
            "ticker": "Ticker",
            "quantity": "Qty",
            "average_price": "Avg Price",
            "market_value": "Market Value",
            "current_day_pnl": "Day P/L",
            "open_pnl": "Open P/L",
            "unrealized_pnl_pct": "Unreal. P/L %",
            "weight_pct": "Weight %",
        }
        display_cols = [c for c in col_map if c in df_pos.columns]
        df_pos = df_pos[display_cols].rename(columns=col_map)
        st.dataframe(df_pos, width="stretch")

    # ------------------------------------------------------------------
    # Overlap with screener
    # ------------------------------------------------------------------
    st.subheader("Overlap with screener")

    try:
        overlap = svc.get_overlap_with_screening()
    except SchwabNotConnectedError as exc:
        st.error(f"Could not compute overlap: {exc}")
        return

    owned = overlap.get("buy_candidates_owned", [])
    not_owned = overlap.get("buy_candidates_not_owned", [])
    wl = overlap.get("watchlist_with_held", [])

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"**BUY candidates you own** ({len(owned)})")
        if owned:
            df_owned = pd.DataFrame(owned)[["ticker", "score", "verdict", "suggested_buy_price", "current_price"]]
            st.dataframe(df_owned, width="stretch")
        else:
            st.info("None of today's BUY candidates are in your portfolio.")

    with col_b:
        st.markdown(f"**BUY candidates not yet owned** ({len(not_owned)})")
        if not_owned:
            df_not = pd.DataFrame(not_owned)[["ticker", "score", "verdict", "suggested_buy_price", "current_price"]]
            st.dataframe(df_not, width="stretch")
        else:
            st.info("No BUY candidates outside your portfolio today.")

    st.markdown("**Watchlist vs portfolio**")
    if wl:
        df_wl = pd.DataFrame(wl)
        df_wl["held"] = df_wl["held"].map({True: "Y", False: "N"})
        st.dataframe(df_wl[["ticker", "held", "target_buy_price", "notes", "alert_active"]], width="stretch")
    else:
        st.info("Watchlist is empty.")


def page_thinkscript() -> None:
    st.header("ThinkScript generator")
    rsi = st.number_input("RSI below", value=35)
    vol = st.number_input("Volume multiplier vs SMA20", value=1.5)
    macd = st.checkbox("MACD bullish cross", value=False)
    if st.button("Generate"):
        gen = ThinkScriptGenerator()
        code = gen.generate_alert(
            {"rsi_below": rsi, "volume_multiplier": vol, "macd_crossover": macd, "time_window": "10:00"}
        )
        st.code(code, language="text")
        out = ROOT / "thinkscripts" / "last_generated.ts"
        out.parent.mkdir(exist_ok=True)
        out.write_text(code, encoding="utf-8")
        st.caption(f"Saved to {out}")


def page_settings() -> None:
    st.header("Settings")
    st.write("Thresholds come from `.env` (reload app after edits).")
    st.json(
        {
            "OLLAMA_HOST": settings.OLLAMA_HOST,
            "OLLAMA_MODEL": settings.OLLAMA_MODEL,
            "MIN_PE": settings.MIN_PE_RATIO,
            "MAX_PE": settings.MAX_PE_RATIO,
            "MIN_MARKET_CAP": settings.MIN_MARKET_CAP,
            "SECTORS": settings.SECTORS,
            "DB_PATH": str(settings.DB_PATH),
            "USE_SCHWAB": settings.USE_SCHWAB,
            "USE_SCHWAB_FOR_ALERTS": settings.USE_SCHWAB_FOR_ALERTS,
            "USE_SCHWAB_FOR_PORTFOLIO": settings.USE_SCHWAB_FOR_PORTFOLIO,
            "SCHWAB_TOKEN_PATH": str(settings.SCHWAB_TOKEN_PATH),
        }
    )
    if st.button("Test Ollama"):
        import ollama

        try:
            c = ollama.Client(host=settings.OLLAMA_HOST.rstrip("/"))
            st.success(c.list())
        except Exception as e:
            st.error(str(e))

    st.subheader("Schwab")
    svc = SchwabService()
    if svc.is_connected():
        st.success(f"Connected — token: `{settings.SCHWAB_TOKEN_PATH}`")
    else:
        st.error("Not connected or token missing.")
        st.code("python main.py schwab auth", language="bash")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Test quote (SPY)"):
            try:
                from data.fetchers.schwab_fetcher import SchwabFetcher

                q = SchwabFetcher().get_quote("SPY")
                st.success(f"SPY last price: {q.get('last_price')}")
            except Exception as exc:
                st.error(str(exc))
    with col2:
        if st.button("Test portfolio"):
            try:
                positions = svc.get_positions_normalized()
                st.success(f"{len(positions)} position(s) found.")
            except Exception as exc:
                st.error(str(exc))


def _render_response_meta(response: ChatResponse) -> None:
    """Render confidence badge, sources, action confirmation, and tools expander."""
    col1, col2 = st.columns([1, 3])
    with col1:
        color = {"High": "green", "Medium": "orange", "Low": "red"}.get(
            response.confidence_label, "gray"
        )
        st.markdown(
            f'<span style="color:{color};font-size:0.80rem;font-weight:600">'
            f"Confidence: {response.confidence_label} ({response.confidence}%)</span>",
            unsafe_allow_html=True,
        )
    with col2:
        if response.sources:
            parts = []
            for s in response.sources:
                label = f"`{s.label}`"
                if s.ticker:
                    label += f" ({s.ticker})"
                parts.append(label)
            st.caption("Sources: " + " · ".join(parts))

    if response.action_taken:
        st.success(f"✓ {response.action_taken}")

    if response.tools_called:
        with st.expander("Tools used", expanded=False):
            st.caption(", ".join(response.tools_called))


@st.dialog("AI Stock Assistant", width="large")
def chatbot_dialog() -> None:
    """Full chat interface rendered inside a Streamlit modal dialog."""
    if "chatbot_messages" not in st.session_state:
        st.session_state.chatbot_messages = []
    if "chatbot_bot" not in st.session_state:
        st.session_state.chatbot_bot = StockChatbot()

    @st.fragment
    def _chat() -> None:
        bot: StockChatbot = st.session_state.chatbot_bot

        # ── Chat history ──────────────────────────────────────────────────────
        chat_container = st.container(height=400)
        with chat_container:
            if not st.session_state.chatbot_messages:
                st.caption(
                    "Ask me anything about your stocks, portfolio, watchlist, or market data. "
                    "I can also run deep-dive analyses, find stocks by theme, and manage your watchlist."
                )
            for msg in st.session_state.chatbot_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    if msg["role"] == "assistant" and msg.get("meta"):
                        _render_response_meta(msg["meta"])

        # ── Quick-action chips ────────────────────────────────────────────────
        qa_cols = st.columns(4)
        quick_actions = [
            ("📈 Today's picks", "What are today's top BUY candidates?"),
            ("👁 My watchlist", "Show me my current watchlist"),
            ("📊 My portfolio", "Show me my current holdings and unrealized P&L"),
            ("🌍 Market movers", "What are the biggest movers in the market today?"),
        ]
        triggered_prompt: str | None = None
        for col, (label, prompt) in zip(qa_cols, quick_actions):
            with col:
                if st.button(label, key=f"_qa_{label}", use_container_width=True):
                    triggered_prompt = prompt

        # ── Input bar ────────────────────────────────────────────────────────
        user_input = st.chat_input(
            "Ask about stocks, your portfolio, watchlist, or market data...",
            key="chatbot_input",
        )
        user_input = user_input or triggered_prompt

        # ── Process ──────────────────────────────────────────────────────────
        if user_input:
            api_history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.chatbot_messages
            ]
            st.session_state.chatbot_messages.append(
                {"role": "user", "content": user_input}
            )
            with st.spinner("Analyzing…"):
                response = bot.chat(user_input, api_history)
            st.session_state.chatbot_messages.append(
                {"role": "assistant", "content": response.text, "meta": response}
            )
            # scope="fragment" reruns only this fragment — the dialog stays open
            st.rerun(scope="fragment")

    _chat()


def main() -> None:
    pages = {
        "Daily shortlist": page_shortlist,
        "Portfolio": page_portfolio,
        "Discover": page_discover,
        "Watchlist": page_watchlist,
        "Deep dive": page_deep_dive,
        "ThinkScript": page_thinkscript,
        "Settings": page_settings,
    }
    choice = st.sidebar.radio("Page", list(pages.keys()))
    pages[choice]()

    # Floating chat button — rendered last so JS can find it by text content
    if st.button("💬", key="open_chatbot", help="AI Stock Assistant"):
        chatbot_dialog()
    _inject_chat_fab()


if __name__ == "__main__":
    main()
