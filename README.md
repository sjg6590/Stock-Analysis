# AI Stock Analyzer

Local-first stock screening with Ollama, yfinance, optional Schwab, and Streamlit.

## Virtual environment (required)

From the `stock-analyzer` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

On Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Always run the app, scheduler, and Streamlit with the venv activated so dependencies resolve to `.venv` only.

```bash
cp .env.example .env
# edit .env, then:
python main.py --help
python main.py                    # screen tickers from TICKER_LIST / watchlist.txt
python main.py AAPL MSFT          # shorthand: screen these tickers
python main.py screen --tickers NVDA TSLA
python main.py alerts             # one-off watchlist / buy-zone check
```

Large watchlists: Yahoo may return HTTP 429 if you hammer it. Defaults use `YFIN_FETCH_WORKERS=1`, spacing (`YFIN_DELAY_SEC`), and retries with backoff (see `.env.example`). Increase `YFIN_DELAY_SEC` (e.g. `2.0`) if you still see throttling.

## Scheduler (APScheduler)

Run from the `stock-analyzer` directory with the same venv as `main.py`:

```bash
source .venv/bin/activate
python scheduler/daily_job.py
```

This starts a blocking process until you stop it. Configure SMTP and related keys in `.env` if you rely on emailed summaries or alerts.

| Job | Schedule | Behavior |
| --- | --- | --- |
| Pre-market scan | Weekdays **06:30** `America/New_York` | Screens tickers from `TICKER_LIST` (watchlist path by default); emails top BUY candidates |
| Intraday watchlist | Every **15 minutes** (24×7 ticks; gated in code) | During **US regular session** (Mon–Fri **09:30–16:00** ET only), checks DB watchlist targets and notifies on hits |
| Weekly deep | Sundays **20:00** `America/New_York` | Screens up to 100 symbols from `tickers/sp500.txt` (fallback: `TICKER_LIST`), logs top 20 |

Cron times use **America/New_York**. Edit `scheduler/daily_job.py` to change hours or add early-close handling if you need it.

One-off alerting without the scheduler remains: `python main.py alerts`.

## Streamlit

```bash
source .venv/bin/activate
streamlit run dashboard/app.py
```

## Ollama

Install [Ollama](https://ollama.com), pull a model (e.g. `ollama pull qwen3:8b`), then set `OLLAMA_MODEL` in `.env`.
