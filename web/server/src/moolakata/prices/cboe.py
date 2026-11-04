"""CBOE's delayed quotes (requirements S4.3, S4.5), from the JSON behind cboe.com's quote
pages, 15 minutes delayed, with no key. It isn't an official API: CBOE offers it for personal,
non-commercial use, and may change it.

- Options: an underlying's whole chain in one answer, asked once a day after the close, every
  held contract on it marked from that one answer.
- Stocks and ETFs listed on an exchange: daily closes back to 2010 for a backfill, and the
  day's close from the quote once the market has closed. Mutual funds aren't listed: Tiingo
  prices them.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from .. import clock
from .base import Ref, SourceError, TickerSource, register

BASE = "https://cdn-api.cboe.com/api/global/delayed_quotes"
API = f"{BASE}/options"
CENT = Decimal("0.01")
EASTERN = ZoneInfo("America/New_York")
# The day's close is final a little after 4:00 PM Eastern; before then the quote's "close" is
# the price so far.
CLOSED = dt.time(16, 15)

# Index options are listed under the index's chain, `_SPX`, whose weeklies (and PM-settled
# contracts) carry their own root: an SPX contract may be SPX or SPXW (S3.2).
INDEXES = {
    "SPX": ("_SPX", ("SPX", "SPXW")),
    "NDX": ("_NDX", ("NDX", "NDXP")),
    "RUT": ("_RUT", ("RUT", "RUTW")),
    "VIX": ("_VIX", ("VIX", "VIXW")),
    "XSP": ("_XSP", ("XSP",)),
    "DJX": ("_DJX", ("DJX",)),
}
# A contract an import names by its weekly root is in the same chain.
INDEXES |= {w: (chain, (w,)) for chain, roots in list(INDEXES.values()) for w in roots[1:]}


def split_occ(ticker: str) -> tuple[str, str]:
    """`O:MSFT261120P00480000` as its root and the 15 characters after it (expiry, side and
    strike)."""
    occ = ticker.removeprefix("O:")
    if len(occ) < 16:
        raise SourceError(f"{ticker} is not an OCC option ticker")
    return occ[:-15], occ[-15:]


def mark(row: dict) -> Decimal | None:
    """A contract's mark: the middle of the bid and the ask when both are quoted, else the
    last trade's price, rounded to the cent (half to even, as every amount is: S14.3)."""
    bid, ask = Decimal(str(row.get("bid") or 0)), Decimal(str(row.get("ask") or 0))
    if bid > 0 and ask >= bid:
        return ((bid + ask) / 2).quantize(CENT)
    last = Decimal(str(row.get("last_trade_price") or 0))
    return last.quantize(CENT) if last > 0 else None


@register
class Cboe(TickerSource):
    name = "cboe"
    label = "CBOE delayed quotes"
    classes = frozenset({"option", "equity", "etf"})
    limits = ((30, 60),)
    hosts = ("cdn-api.cboe.com",)
    terms = (
        "Not an official API: the delayed quotes behind cboe.com's pages, 15 minutes "
        "delayed, which CBOE offers for personal, non-commercial use and may change. Stocks "
        "and ETFs listed on an exchange, and options; not mutual funds."
    )
    terms_checked = dt.date(2026, 10, 14)

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        self._chains: dict[str, tuple[dt.date, dict[str, dict]]] = {}

    def chain(self, chain: str) -> tuple[dt.date, dict[str, dict]]:
        """An underlying's chain, fetched once for every contract on it: the market day it is
        from, and each contract's row by its OCC symbol."""
        if chain not in self._chains:
            body = self.get_json(f"{API}/{chain}.json")
            data = (body or {}).get("data") or {}
            when = data.get("last_trade_time") or (body or {}).get("timestamp") or ""
            try:
                day = dt.date.fromisoformat(when[:10])
            except ValueError:
                raise SourceError(f"{self.label} answered without a date for {chain}") from None
            self._chains[chain] = (day, {r["option"]: r for r in data.get("options") or []})
        return self._chains[chain]

    def listed(self, path: str, symbol: str):
        """A stock's or ETF's answer; a symbol CBOE doesn't list fails, so the next source
        that serves the class is asked."""
        if self.client is None:
            raise SourceError(f"{self.label} has no network client")
        self.wait()
        try:
            r, body = self.client.get_bytes(f"{BASE}/{path}/{symbol}.json")
        except Exception as e:
            raise SourceError(f"{self.label} could not be reached ({type(e).__name__})") from None
        if r.status_code in (403, 404):
            raise SourceError(f"{self.label} doesn't list {symbol}")
        if r.status_code >= 400:
            raise SourceError(f"{self.label} answered HTTP {r.status_code}")
        import json

        try:
            return json.loads(body, parse_float=Decimal).get("data")
        except ValueError, AttributeError:
            raise SourceError(f"{self.label} answered with something that is not JSON") from None

    def history(self, ref: Ref, start: dt.date, end: dt.date) -> list[tuple[dt.date, Decimal]]:
        if ref.instrumentClass == "option":
            return self.option(ref, start, end)
        symbol = ref.symbol.upper()
        rows = self.listed("charts/historical", symbol) or []
        out = {}
        for r in rows:
            day = dt.date.fromisoformat(r["date"])
            if start <= day <= end and r.get("close"):
                out[day] = Decimal(str(r["close"]))
        # Today's close isn't in the history until tomorrow: it comes from the quote, once
        # the market has closed.
        now = clock.now().astimezone(EASTERN)
        today = now.date()
        if start <= today <= end and today not in out and now.time() >= CLOSED:
            q = self.listed("quotes", symbol) or {}
            when = str(q.get("last_trade_time") or "")[:10]
            if when == today.isoformat() and q.get("close"):
                out[today] = Decimal(str(q["close"]))
        return sorted(out.items())

    def option(self, ref: Ref, start: dt.date, end: dt.date) -> list[tuple[dt.date, Decimal]]:
        """Only the latest close: CBOE gives the chain as it is now, not its history."""
        root, rest = split_occ(ref.symbol)
        # An adjusted contract's root (XYZ1) is listed in its underlying's chain (S3.10.5).
        base = root.rstrip("0123456789") or root
        chain, roots = INDEXES.get(root, (base, (root,)))
        day, rows = self.chain(chain)
        if not start <= day <= end:
            return []
        for r in roots:
            row = rows.get(r + rest)
            if row is not None:
                price = mark(row)
                return [(day, price)] if price is not None else []
        return []
