#!/usr/bin/env python3
"""AI Stock Analyzer — run from the `stock-analyzer` directory (or set PYTHONPATH)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

# Ensure project root is importable when executed as `python main.py`
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _normalize_argv() -> None:
    """Default to `screen`; allow `main.py --tickers AAPL` and `main.py AAPL MSFT`."""
    av = sys.argv[1:]
    if not av:
        sys.argv.append("screen")
        return
    if av[0] in ("screen", "alerts", "discover", "schwab", "-h", "--help"):
        return
    if av[0].startswith("-"):
        sys.argv = [sys.argv[0], "screen", *av]
    else:
        sys.argv = [sys.argv[0], "screen", "--tickers", *av]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _print_screening_table(console: Console, results: list[dict]) -> None:
    has_filtered = any(r.get("verdict") in ("FILTERED", "ERROR") for r in results)
    table = Table(title="Screening results")
    cols = ["Ticker", "Score", "Verdict", "Valuation", "Upside%", "Buy price", "Sentiment"]
    if has_filtered:
        cols.append("Reason")
    for col in cols:
        table.add_column(col)
    for r in results:
        verdict = str(r.get("verdict", ""))
        row_vals = [
            str(r.get("ticker", "")),
            str(r.get("score", "")),
            verdict,
            str(r.get("valuation_status", "")),
            str(r.get("estimated_upside_percent", "")),
            str(r.get("suggested_buy_price", "")),
            str(r.get("news_sentiment", "")),
        ]
        if has_filtered:
            reason = ""
            if verdict in ("FILTERED", "ERROR"):
                raw = str(r.get("reasoning", ""))
                reason = (raw[:77] + "…") if len(raw) > 80 else raw
            row_vals.append(reason)
        table.add_row(*row_vals)
    console.print(table)


def cmd_screen(args: argparse.Namespace) -> int:
    from config import settings
    from screener.batch_runner import load_tickers_from_file, run_pipeline, run_prescreen

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers if t.strip()]
    else:
        path = Path(args.list_file) if args.list_file else settings.TICKER_LIST_PATH
        tickers = load_tickers_from_file(path)
    if not tickers:
        logging.error("No tickers: pass symbols or populate %s", settings.TICKER_LIST_PATH)
        return 1

    console = Console()
    override_tickers: frozenset[str] = frozenset()
    prescreen_results = None

    if getattr(args, "interactive", False):
        console.print("[dim]Fetching fundamentals for pre-filter review…[/dim]")
        passing, filtered = run_prescreen(
            tickers,
            skip_prefilter=args.skip_prefilter,
            max_workers=getattr(args, "fetch_workers", None),
        )
        prescreen_results = (passing, filtered)

        if filtered:
            filter_table = Table(
                title=f"[bold yellow]{len(filtered)} ticker(s) blocked by pre-filter[/bold yellow]",
                show_lines=True,
            )
            filter_table.add_column("Ticker", style="bold cyan", no_wrap=True)
            filter_table.add_column("Why it was filtered out")
            for item in filtered:
                if item.get("fetch_error"):
                    reason_str = f"[red]Fetch error:[/red] {item['fetch_error']}"
                else:
                    bullet_lines = "\n".join(f"• {r}" for r in item["filter_reasons"])
                    reason_str = bullet_lines or "Unknown"
                filter_table.add_row(item["ticker"], reason_str)
            console.print(filter_table)

            overridable = [f for f in filtered if not f.get("fetch_error")]
            if overridable:
                console.print(
                    "\n[bold]Interactive override[/bold] — press [bold]y[/bold] to send a ticker "
                    "to the LLM screener anyway, or [bold]n[/bold] / Enter to skip it.\n"
                )
                override_set: set[str] = set()
                for item in overridable:
                    t = item["ticker"]
                    short_reasons = "; ".join(item["filter_reasons"])
                    try:
                        answer = console.input(
                            f"  [bold cyan]{t}[/bold cyan] — {short_reasons}\n"
                            f"  Screen anyway? [y/N] "
                        ).strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        console.print("\n[yellow]Cancelled.[/yellow]")
                        return 1
                    if answer == "y":
                        override_set.add(t)
                        console.print(f"    → [green]Will screen {t}[/green]\n")
                    else:
                        console.print(f"    → [dim]Skipping {t}[/dim]\n")
                override_tickers = frozenset(override_set)
        else:
            console.print(f"[green]All {len(passing)} ticker(s) passed pre-filter.[/green]\n")

    results = run_pipeline(
        tickers,
        skip_prefilter=args.skip_prefilter,
        save_db=not args.no_save,
        export_high_scores=not args.no_export,
        max_workers=getattr(args, "fetch_workers", None),
        override_tickers=override_tickers,
        prescreen_results=prescreen_results,
    )
    results = sorted(results, key=lambda r: r.get("score") or 0, reverse=True)
    _print_screening_table(console, results)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        console.print(f"Wrote {args.json_out}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from screener.batch_runner import run_pipeline
    from screener.thesis_screener import ThesisScreener

    thesis = " ".join(args.thesis)
    console = Console()
    console.print(f"\n[bold]Thesis:[/bold] {thesis}\n")

    ts = ThesisScreener()
    console.print("[dim]Asking LLM to identify relevant tickers…[/dim]")
    try:
        discovery = ts.discover(thesis)
    except RuntimeError as e:
        logging.error("%s", e)
        return 1

    console.print(f"[bold]Theme:[/bold] {discovery.get('theme', '')}\n")

    disc_table = Table(title="Discovered candidates")
    disc_table.add_column("Type")
    disc_table.add_column("Symbol")
    disc_table.add_column("Name")
    disc_table.add_column("Rationale")
    for item in discovery.get("stocks", []):
        disc_table.add_row("stock", item.get("symbol", ""), item.get("name", ""), item.get("rationale", ""))
    for item in discovery.get("etfs", []):
        disc_table.add_row("ETF", item.get("symbol", ""), item.get("name", ""), item.get("rationale", ""))
    console.print(disc_table)

    tickers = ts.tickers_from_discovery(discovery)
    if not tickers:
        logging.error("LLM returned no tickers.")
        return 1

    if args.list_only:
        console.print("\nTickers: " + ", ".join(tickers))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(discovery, indent=2), encoding="utf-8")
        return 0

    console.print(f"\n[dim]Screening {len(tickers)} tickers…[/dim]\n")
    results = run_pipeline(
        tickers,
        skip_prefilter=args.skip_prefilter,
        save_db=not args.no_save,
        export_high_scores=True,
        max_workers=getattr(args, "fetch_workers", None),
    )
    results = sorted(results, key=lambda r: r.get("score") or 0, reverse=True)
    _print_screening_table(console, results)

    if args.json_out:
        out = {"discovery": discovery, "screening": results}
        Path(args.json_out).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        console.print(f"Wrote {args.json_out}")
    return 0


def cmd_alerts(_: argparse.Namespace) -> int:
    from alerts.alert_manager import AlertManager

    mgr = AlertManager()
    a = mgr.check_screening_alerts()
    b = mgr.check_watchlist_prices()
    logging.info("Screening alerts: %s | Watchlist: %s", a, b)
    return 0


def cmd_schwab(args: argparse.Namespace) -> int:
    from rich.console import Console

    console = Console()
    sub = args.schwab_cmd

    if sub == "auth":
        from data.fetchers.schwab_fetcher import SchwabFetcher

        console.print("[dim]Starting Schwab OAuth flow…[/dim]")
        try:
            SchwabFetcher().authenticate()
            console.print("[green]Authentication successful. Token saved.[/green]")
        except Exception as exc:
            console.print(f"[red]Authentication failed: {exc}[/red]")
            return 1

    elif sub == "status":
        from data.fetchers.schwab_fetcher import SchwabFetcher
        from config import settings

        sf = SchwabFetcher()
        connected = sf.is_authenticated()
        token_path = settings.SCHWAB_TOKEN_PATH
        console.print(f"USE_SCHWAB             : {settings.USE_SCHWAB}")
        console.print(f"USE_SCHWAB_FOR_ALERTS  : {settings.USE_SCHWAB_FOR_ALERTS}")
        console.print(f"USE_SCHWAB_FOR_PORTFOLIO: {settings.USE_SCHWAB_FOR_PORTFOLIO}")
        console.print(f"Token path             : {token_path}")
        console.print(f"Token exists           : {token_path.exists()}")
        if connected:
            console.print("[green]Status: Connected[/green]")
        else:
            console.print("[red]Status: Not connected[/red]")

    elif sub == "portfolio":
        from data.schwab_service import SchwabNotConnectedError, SchwabService

        svc = SchwabService()
        try:
            positions = svc.get_positions_normalized()
        except SchwabNotConnectedError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        if not positions:
            console.print("No positions found.")
            return 0
        table = Table(title="Schwab Portfolio")
        for col in ("Ticker", "Qty", "Avg Price", "Market Value", "Day P/L", "Open P/L", "Unreal %", "Weight %"):
            table.add_column(col)
        for p in positions:
            table.add_row(
                str(p.get("ticker") or ""),
                str(p.get("quantity") or ""),
                f"{p['average_price']:.2f}" if p.get("average_price") else "",
                f"{p['market_value']:.2f}" if p.get("market_value") else "",
                f"{p['current_day_pnl']:.2f}" if p.get("current_day_pnl") else "",
                f"{p['open_pnl']:.2f}" if p.get("open_pnl") else "",
                f"{p['unrealized_pnl_pct']:.1f}%" if p.get("unrealized_pnl_pct") is not None else "",
                f"{p['weight_pct']:.1f}%" if p.get("weight_pct") is not None else "",
            )
        console.print(table)

    elif sub == "quote":
        from data.fetchers.schwab_fetcher import SchwabAuthError, SchwabFetcher

        ticker = args.ticker.upper()
        try:
            q = SchwabFetcher().get_quote(ticker)
            console.print(f"{ticker}: last={q.get('last_price')}  bid={q.get('bid')}  ask={q.get('ask')}  vol={q.get('volume')}")
        except SchwabAuthError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        except Exception as exc:
            console.print(f"[red]Quote failed: {exc}[/red]")
            return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    p = argparse.ArgumentParser(
        prog="main.py",
        description="Local AI stock screener (Ollama + yfinance + SQLite).",
        parents=[parent],
    )
    sub = p.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("screen", help="Run screening pipeline", parents=[parent])
    ps.add_argument("--tickers", nargs="*", metavar="SYM", help="Symbols; if omitted, uses TICKER_LIST from .env")
    ps.add_argument("--list-file", type=str, default=None, help="Path to ticker list (one per line)")
    ps.add_argument("--skip-prefilter", action="store_true", help="Send all tickers to the LLM")
    ps.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Show pre-filter results and prompt y/n to override each filtered ticker",
    )
    ps.add_argument("--no-save", action="store_true", help="Skip SQLite writes")
    ps.add_argument("--no-export", action="store_true", help="Skip Tier-2 JSON exports for high scores")
    ps.add_argument("--json-out", type=str, default=None, help="Write results JSON to this path")
    ps.add_argument(
        "--fetch-workers",
        type=int,
        default=None,
        metavar="N",
        help="Parallel ticker workers (default: YFIN_FETCH_WORKERS in .env; use 1 to reduce Yahoo 429s)",
    )
    ps.set_defaults(func=cmd_screen)

    pa = sub.add_parser("alerts", help="Check watchlist / buy-zone alerts once", parents=[parent])
    pa.set_defaults(func=cmd_alerts)

    pd_ = sub.add_parser(
        "discover",
        help="Find tickers from a natural-language investment thesis, then screen them",
        parents=[parent],
    )
    pd_.add_argument(
        "thesis",
        nargs="+",
        metavar="WORD",
        help='Investment thesis as free text, e.g. discover "AI hardware chips semiconductors"',
    )
    pd_.add_argument("--list-only", action="store_true", help="Print discovered tickers without screening")
    pd_.add_argument("--skip-prefilter", action="store_true", help="Send all tickers to the LLM screener")
    pd_.add_argument("--no-save", action="store_true", help="Skip SQLite writes")
    pd_.add_argument("--json-out", type=str, default=None, help="Write discovery + screening JSON to this path")
    pd_.add_argument("--fetch-workers", type=int, default=None, metavar="N")
    pd_.set_defaults(func=cmd_discover)

    ps_schwab = sub.add_parser("schwab", help="Schwab account tools", parents=[parent])
    schwab_sub = ps_schwab.add_subparsers(dest="schwab_cmd", required=True)
    schwab_sub.add_parser("auth", help="Run OAuth flow to authenticate with Schwab")
    schwab_sub.add_parser("status", help="Show connection status and feature flags")
    schwab_sub.add_parser("portfolio", help="Print current Schwab portfolio positions")
    sq = schwab_sub.add_parser("quote", help="Fetch live quote for a ticker")
    sq.add_argument("ticker", metavar="SYM")
    ps_schwab.set_defaults(func=cmd_schwab)

    return p


def main() -> int:
    _normalize_argv()
    parser = build_parser()
    args = parser.parse_args()
    _setup_logging(getattr(args, "verbose", False))
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
