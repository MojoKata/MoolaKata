"""Tiingo (requirements S4.3): US stocks, ETFs and mutual funds' daily closes and NAVs. A free
key; for personal use."""

import datetime as dt
from decimal import Decimal
from urllib.parse import quote

from .base import Ref, SourceError, TickerSource, register

API = "https://api.tiingo.com"


@register
class Tiingo(TickerSource):
    name = "tiingo"
    label = "Tiingo"
    classes = frozenset({"equity", "etf", "mutual-fund"})
    needs_key = True
    key_url = "https://www.tiingo.com/account/api/token"
    limits = ((50, 3600), (1000, 86400))
    hosts = ("api.tiingo.com",)
    terms = (
        "Free plan: 500 symbols a month, 50 requests an hour and 1,000 a day, for "
        "personal use. Mutual fund NAVs post around midnight Eastern."
    )
    terms_checked = dt.date(2026, 10, 1)

    def _headers(self) -> dict:
        if not self.key:
            raise SourceError("Tiingo needs its API key")
        return {"Authorization": f"Token {self.key}", "Content-Type": "application/json"}

    def history(self, ref: Ref, start: dt.date, end: dt.date) -> list[tuple[dt.date, Decimal]]:
        url = (
            f"{API}/tiingo/daily/{quote(ref.symbol.lower())}/prices"
            f"?startDate={start.isoformat()}&endDate={end.isoformat()}"
        )
        rows = self.get_json(url, headers=self._headers())
        if not rows:
            return []
        out = []
        for row in rows:
            close = row.get("close")
            if close is None:
                continue
            out.append((dt.date.fromisoformat(row["date"][:10]), Decimal(str(close))))
        return sorted(out)
