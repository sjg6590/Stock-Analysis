"""SEC EDGAR filing downloads."""

from __future__ import annotations

import logging
from pathlib import Path

from sec_edgar_downloader import Downloader

logger = logging.getLogger(__name__)


class SecFetcher:
    """Download 10-K / 10-Q filings to local disk."""

    def __init__(self, company_name: str = "StockAnalyzer", email: str = "user@example.com") -> None:
        self._dl = Downloader(company_name, email)

    def download_filings(
        self,
        ticker: str,
        filing_type: str = "10-K",
        limit: int = 1,
        download_folder: str | Path | None = None,
    ) -> Path:
        """Download latest filings; returns destination directory."""
        dest = Path(download_folder or "./data/sec_filings").resolve()
        dest.mkdir(parents=True, exist_ok=True)
        try:
            self._dl.get(filing_type, ticker, limit=limit, download_folder=str(dest))
        except Exception as e:
            logger.error("SEC download failed for %s: %s", ticker, e)
            raise
        return dest
