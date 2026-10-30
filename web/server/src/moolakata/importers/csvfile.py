"""CSV files (requirements S1.3.2), read with a column mapping saved per institution. A first
file gets a proposed mapping from its header row; the user checks it, and it is kept.

A mapping names the columns: the date (and its format), the amount (or debit and credit
columns), the payee, and optionally the memo, a running balance, the institution's own id,
and for brokers' and exchanges' trade histories the action, symbol, quantity, price and fees.
"""

import csv
import datetime as dt
import io
import re
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from .parsed import ParsedFile, ReadError, Row, Security, occ_symbol

DATE_FORMATS = [
    "%m/%d/%Y",
    "%Y-%m-%d",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%b %d, %Y",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
]
FIELDS = (
    "date",
    "amount",
    "debit",
    "credit",
    "payee",
    "memo",
    "balance",
    "id",
    "action",
    "symbol",
    "quantity",
    "price",
    "fees",
)
GUESSES = {
    "date": [
        "date",
        "posted date",
        "posting date",
        "transaction date",
        "trade date",
        "timestamp",
        "run date",
    ],
    "amount": [
        "amount",
        "amount (usd)",
        "net amount",
        "total",
        "total (inclusive of fees and/or spread)",
        "subtotal",
        "value",
    ],
    "debit": ["debit", "withdrawal", "withdrawals", "debit amount", "money out"],
    "credit": ["credit", "deposit", "deposits", "credit amount", "money in"],
    "payee": ["description", "payee", "name", "merchant", "details", "transaction"],
    "memo": ["memo", "note", "notes", "category"],
    "balance": ["balance", "running balance", "running bal.", "available balance"],
    "id": ["transaction id", "reference", "ref", "id", "fitid"],
    "action": ["action", "transaction type", "type", "activity"],
    "symbol": ["symbol", "ticker", "asset", "security"],
    "quantity": ["quantity", "shares", "units", "qty", "quantity transacted"],
    "price": ["price", "spot price at transaction", "unit price", "price ($)"],
    "fees": ["fees", "commission", "fees and/or spread", "fee"],
}
ACTIONS = [
    ("reinvest", "reinvest"),
    ("dividend", "dividend"),
    ("div", "dividend"),
    ("interest", "interest"),
    ("buy", "buy"),
    ("bought", "buy"),
    ("sell", "sell"),
    ("sold", "sell"),
    ("fee", "fee"),
    ("deposit", "deposit"),
    ("withdraw", "withdrawal"),
    ("transfer", "transfer"),
    ("receive", "transfer-in"),
    ("send", "transfer-out"),
    ("split", "split"),
]


def decode(data: bytes) -> str:
    if b"\x00" in data[:4096]:
        raise ReadError("This is not a text file.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ReadError("The file's text can't be read.")


def looks_like_csv(data: bytes) -> bool:
    """Whether its longest stretch of lines between blank ones (its header and rows, not the
    notes a bank writes above or below them) reads as a table."""
    try:
        text = decode(data[:65536])
    except ReadError:
        return False
    blocks = [b.splitlines() for b in re.split(r"\r?\n[ \t]*\r?\n", text) if b.strip()]
    lines = [x for x in max(blocks, key=len, default=[]) if x.strip()][:10]
    return len(lines) >= 2 and all(("," in x or ";" in x or "\t" in x) for x in lines[-2:])


def _table(text: str) -> tuple[str, list[list[str]], list[bool]]:
    """The delimiter, the rows that hold anything, and for each whether a blank line came
    before it."""
    sample = text[:8192]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delim = ","
    return delim, *_rows(text, delim)


def _rows(text: str, delim: str) -> tuple[list[list[str]], list[bool]]:
    rows, gaps, blank = [], [], False
    for r in csv.reader(io.StringIO(text), delimiter=delim):
        if any(c.strip() for c in r):
            rows.append(r)
            gaps.append(blank)
            blank = False
        else:
            blank = True
    return rows, gaps


def _body_end(gaps: list[bool], header: int) -> int:
    """Where the rows below the header end: at the first blank line after the first of them.
    What follows is a trailer (a disclaimer, the time the file was downloaded), not rows."""
    for i in range(header + 2, len(gaps)):
        if gaps[i]:
            return i
    return len(gaps)


def header_row(rows: list[list[str]]) -> int:
    """The first row that names a date column: banks put account details above it."""
    for i, r in enumerate(rows[:15]):
        cells = [c.strip().lower() for c in r]
        if any(c in GUESSES["date"] or "date" in c for c in cells) and len(cells) >= 2:
            return i
    return 0


TRADE_FIELDS = ("action", "symbol", "quantity", "price", "fees")


def propose(data: bytes, trades: bool = False) -> dict:
    """A mapping guessed from the header row, with a preview for the user to check. A trade
    history's columns are guessed only for an account that holds instruments (`trades`)."""
    delim, rows, gaps = _table(decode(data))
    if not rows:
        raise ReadError("The file is empty.")
    h = header_row(rows)
    end = _body_end(gaps, h)
    trailer, rows = len(rows) - end, rows[:end]
    headers = [c.strip() for c in rows[h]]
    lower = [c.lower() for c in headers]
    mapping: dict = {"delimiter": delim, "skipRows": h, "negateAmounts": False}
    for f in FIELDS:
        mapping[f] = None
        for want in GUESSES[f]:
            if want in lower and headers[lower.index(want)] not in mapping.values():
                mapping[f] = headers[lower.index(want)]
                break
    if mapping["amount"] and (mapping["debit"] or mapping["credit"]):
        mapping["debit"] = mapping["credit"] = None
    body = rows[h + 1 :]
    dates = [
        r[lower.index(mapping["date"].lower())]
        for r in body
        if mapping["date"] and len(r) > lower.index(mapping["date"].lower())
    ]
    mapping["dateFormat"] = date_format(dates)
    if not trades:
        for f in TRADE_FIELDS:
            mapping[f] = None
    return {"headers": headers, "sample": body[:8], "mapping": mapping, "trailer": trailer}


def date_format(values: list[str]) -> str | None:
    """The first format that reads every value; month first wins over day first."""
    values = [v.strip() for v in values if v.strip()]
    for fmt in DATE_FORMATS:
        try:
            for v in values:
                dt.datetime.strptime(v, fmt)
        except ValueError:
            continue
        return fmt
    return None


def amount(text: str | None) -> Decimal | None:
    """ "$1,234.56", "(12.00)", "-12.00", "12.00-" and "1.234,56" are all read."""
    if text is None:
        return None
    t = text.strip().replace("$", "").replace("USD", "").replace(" ", "").replace("−", "-")
    if not t or t in ("-", "--"):
        return None
    negative = (t.startswith("(") and t.endswith(")")) or t.endswith("-")
    t = t.strip("()").rstrip("-")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+,\d+", t):
        t = t.replace(".", "").replace(",", ".")
    t = t.replace(",", "")
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise ReadError(f"{text!r} is not an amount") from None
    return -abs(d) if negative else d


def check_mapping(mapping: dict) -> list[tuple[str, str]]:
    """What is missing from a mapping, as (field, message)."""
    problems = []
    if not mapping.get("date"):
        problems.append(("date", "Choose the date column."))
    if not mapping.get("dateFormat"):
        problems.append(("dateFormat", "Choose how the dates are written."))
    if not (mapping.get("amount") or mapping.get("debit") or mapping.get("credit")):
        problems.append(("amount", "Choose the amount column, or the debit and credit columns."))
    if not mapping.get("payee") and not mapping.get("symbol"):
        problems.append(("payee", "Choose the description or payee column."))
    return problems


def read(data: bytes, mapping: dict) -> ParsedFile:
    problems = check_mapping(mapping)
    if problems:
        raise ReadError(problems[0][1])
    rows, gaps = _rows(decode(data), mapping.get("delimiter") or ",")
    skip = int(mapping.get("skipRows") or 0)
    rows = rows[: _body_end(gaps, skip)]
    if len(rows) <= skip:
        raise ReadError("The file has no rows below its header.")
    headers = [c.strip() for c in rows[skip]]
    index = {h: i for i, h in enumerate(headers)}
    for f in FIELDS:
        col = mapping.get(f)
        if col and col not in index:
            raise ReadError(f"The file has no column called {col!r}.")

    def cell(r: list[str], f: str) -> str | None:
        col = mapping.get(f)
        if not col:
            return None
        i = index[col]
        return r[i].strip() if i < len(r) else None

    out = ParsedFile(format="csv")
    negate = bool(mapping.get("negateAmounts"))
    for n, r in enumerate(rows[skip + 1 :], start=skip + 2):
        raw_date = cell(r, "date")
        if not raw_date:
            continue
        try:
            day = dt.datetime.strptime(raw_date, mapping["dateFormat"]).date()
        except ValueError:
            raise ReadError(
                f"Row {n}: the date is not written as {mapping['dateFormat']}."
            ) from None
        try:
            if mapping.get("amount"):
                value = amount(cell(r, "amount")) or Decimal(0)
            else:
                value = (amount(cell(r, "credit")) or Decimal(0)) - abs(
                    amount(cell(r, "debit")) or Decimal(0)
                )
            if negate:
                value = -value
            running = amount(cell(r, "balance"))
            quantity = amount(cell(r, "quantity"))
            price = amount(cell(r, "price"))
            fees = amount(cell(r, "fees"))
        except ReadError as e:
            raise ReadError(f"Row {n}: {e}") from None
        symbol = (cell(r, "symbol") or "").upper() or None
        if symbol == "USD":
            symbol = None  # the account's own currency: cash, not an instrument
        option = occ_symbol(symbol) if mapping.get("symbol") else None
        symbol = option or symbol
        kind = (
            _kind(cell(r, "action"), value)
            if mapping.get("symbol")
            else ("deposit" if value > 0 else "withdrawal")
        )
        if option:
            # An option is a contract (S3.2): its row says whether it opens or closes, or how
            # it ended; a plain buy or sell can't say which, so it is refused by name.
            kind = _option_kind(cell(r, "action"))
            if kind is None:
                raise ReadError(
                    f"Row {n}: {symbol} is an option, and its action doesn't say whether it "
                    "opens or closes (Buy to Open, Sell to Close, Expired, Assigned). Record "
                    "it on Positions, or fix the file's action."
                )
        # A trade's cash follows its action, whatever sign the file wrote: an exchange writes
        # a buy's total as a positive number. Shares or coins moved in or out move no cash.
        if symbol and kind in ("buy", "fee"):
            value = -abs(value)
        elif symbol and kind == "sell":
            value = abs(value)
        elif symbol and kind in ("transfer-in", "transfer-out"):
            value = Decimal(0)
        if (
            symbol
            and symbol not in out.securities
            and kind not in ("deposit", "withdrawal", "fee", "transfer")
        ):
            out.securities[symbol] = Security(
                key=symbol,
                symbol=symbol,
                name=None,
                instrumentClass="option" if option else "other",
            )
        out.rows.append(
            Row(
                date=day,
                kind=kind,
                amount=value,
                fitId=cell(r, "id") or None,
                payee=cell(r, "payee"),
                memo=cell(r, "memo"),
                security=symbol if symbol in out.securities else None,
                quantity=abs(quantity) if quantity is not None else None,
                price=price,
                fees=abs(fees) if fees else None,
                runningBalance=running,
            )
        )
    # A newest-first export (most banks') is read oldest first, so each day's last running
    # balance is its last row's (S1.11.2), and rows go in in the order they happened. When the
    # dates can't tell (a single day's), the running balances do.
    if len(out.rows) > 1 and (
        out.rows[0].date > out.rows[-1].date
        or (out.rows[0].date == out.rows[-1].date and _newest_first(out.rows))
    ):
        out.rows.reverse()
    out.cover()
    return out


def _newest_first(rows: list[Row]) -> bool:
    """Whether the running balances chain only from the bottom up: each row's balance, less its
    amount, is the next row's (CR3-171)."""
    pairs = [
        (a, b)
        for a, b in pairwise(rows)
        if a.runningBalance is not None and b.runningBalance is not None
    ]
    if not pairs:
        return False
    down = all(b.runningBalance == a.runningBalance + b.amount for a, b in pairs)
    up = all(a.runningBalance - a.amount == b.runningBalance for a, b in pairs)
    return up and not down


def _option_kind(action: str | None) -> str | None:
    a = " ".join((action or "").lower().replace("-", " ").split())
    for word, kind in (("expire", "expire"), ("assign", "assign"), ("exercise", "exercise")):
        if word in a:
            return kind
    side = (
        "buy" if ("buy" in a or "bought" in a) else "sell" if ("sell" in a or "sold" in a) else None
    )
    end = "open" if "open" in a else "close" if "clos" in a else None
    return f"{side}-to-{end}" if side and end else None


def _kind(action: str | None, value: Decimal) -> str:
    a = (action or "").lower()
    for word, kind in ACTIONS:
        if word in a:
            return kind
    return "deposit" if value > 0 else "withdrawal"
