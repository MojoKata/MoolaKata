"""Brokerage and plan statements (requirements S1.3.3.8): a Schwab, Fidelity or Vanguard
brokerage statement, or a 401(k) statement as Empower lays it out, read from a PDF's text layer
into three parts:

- the **summary**: starting and ending value, deposits, withdrawals, income and the change in
  value, from the labelled lines near the top;
- the **positions** on the last day: a symbol (or CUSIP, or a fund's name), quantity, price and
  market value, and a cost basis where the statement shows one; a row split over two lines
  (the name, then its figures) is read as one, and a sweep or money-market line is the cash;
- the **cash activity**: dated lines of deposits, withdrawals, dividends, interest and fees.
  Trades, options activity, corporate actions and margin lines are not read: each comes back
  with its figures, for the trade dialog.

The layouts share these section headings closely enough for one set of rules, with the words
each institution uses; what the person leaves out is learned per institution, as for banks.
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .statements import LEAD_DATE, _date_of, _institution, _period, parse_amount

NUMBER = re.compile(r"(?<![\w.,/])(\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?)(?![\w/])")
STARTING = re.compile(r"\b(starting|beginning|opening)\s+(account\s+)?(value|balance)\b", re.I)
ENDING = re.compile(r"\b(ending|closing)\s+(account\s+)?(value|balance)\b", re.I)
DEPOSITS = re.compile(r"^\s*(deposits?|contributions?|additions)\b", re.I)
WITHDRAWALS = re.compile(r"^\s*(withdrawals?|distributions?|subtractions)\b", re.I)
INCOME = re.compile(
    r"^\s*(dividends?\s*(?:and|&|,)\s*interest|dividends?,?\s+interest|income|"
    r"dividends?\s+and\s+other\s+income)\b",
    re.I,
)
CHANGE = re.compile(
    r"\b(change\s+in\s+(?:market\s+)?value(?:\s+of\s+investments)?|investment\s+(?:gain|change)|"
    r"market\s+(?:gain|change))\b",
    re.I,
)
POSITIONS = re.compile(
    r"^\s*(positions|holdings|investment\s+detail|your\s+holdings|your\s+investments|"
    r"fund\s+balances|investments|portfolio\s+holdings|account\s+holdings)\b",
    re.I,
)
ACTIVITY = re.compile(
    r"^\s*(transactions|transaction\s+detail|activity|cash\s+activity|account\s+activity|"
    r"transaction\s+history|core\s+account\s+activity)\b",
    re.I,
)
OTHER = re.compile(
    r"^\s*(account\s+summary|change\s+in\s+account\s+value|income\s+summary|realized\s+gain|"
    r"disclosures|important\s+information|messages|footnotes|endnotes|year[- ]to[- ]date)\b",
    re.I,
)
CASH = re.compile(
    r"\b(cash|sweep|money\s*market|money\s+(?:inv|fund)|bank\s+deposit|core\s+position)\b", re.I
)
SYMBOL = re.compile(r"^([A-Z][A-Z0-9.]{0,5})\s+(?=\S)")
CUSIP = re.compile(r"^([0-9A-Z]{9})\s+")
TOTAL = re.compile(r"^\s*(total|subtotal)\b", re.I)

NOT_READ = (
    ("option", re.compile(r"\b(call|put|options?|assigned|exercised|expired)\b", re.I)),
    (
        "trade",
        re.compile(r"\b(bought|buy|sold|sell|purchased?|reinvest(?:ed)?\s+shares)\b", re.I),
    ),
    ("corporate-action", re.compile(r"\b(split|merger|spin-?off|reorg\w*|exchanged?)\b", re.I)),
    ("margin", re.compile(r"\bmargin\b", re.I)),
)
ACTIONS = {"BUY", "SELL", "SOLD", "CALL", "PUT", "ETF", "INC", "CORP", "CO", "LLC", "FUND"}
KINDS = (
    ("dividend", re.compile(r"\b(dividends?|div|qualified\s+div|capital\s+gain\s+dist)", re.I)),
    ("interest", re.compile(r"\binterest\b", re.I)),
    ("fee", re.compile(r"\bfees?\b", re.I)),
    (
        "deposit",
        re.compile(r"\b(deposit|contribution|transfer\s+in|funds\s+received|journal\s+in)", re.I),
    ),
    (
        "withdrawal",
        re.compile(
            r"\b(withdraw\w*|distribution|transfer\s+out|funds\s+paid|journal\s+out|check\s+paid)",
            re.I,
        ),
    ),
)


@dataclass
class Summary:
    starting: Decimal | None = None
    ending: Decimal | None = None
    deposits: Decimal | None = None
    withdrawals: Decimal | None = None
    income: Decimal | None = None
    change: Decimal | None = None


@dataclass
class Position:
    label: str  # as the statement names it
    symbol: str | None
    cusip: str | None
    quantity: Decimal | None
    price: Decimal | None
    value: Decimal | None
    cost: Decimal | None = None
    cash: bool = False  # the sweep or cash line


@dataclass
class Activity:
    date: dt.date
    description: str
    amount: Decimal
    kind: str  # deposit, withdrawal, dividend, interest, fee; or what isn't read
    notRead: bool = False
    symbol: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    # The start of a line the person asked to ignore (S1.3.3.4) that this line has: it is shown,
    # left out, never dropped unseen.
    ignored: str | None = None


@dataclass
class Brokerage:
    periodStart: dt.date | None = None
    periodEnd: dt.date | None = None
    institution: str | None = None
    summary: Summary = field(default_factory=Summary)
    positions: list[Position] = field(default_factory=list)
    activity: list[Activity] = field(default_factory=list)

    @property
    def read(self) -> bool:
        """Whether it looks like a brokerage or plan statement at all."""
        return self.summary.ending is not None and bool(self.positions or self.activity)


def _figures(text: str) -> list[Decimal]:
    """A position's figures: a bare whole number in a fund's name (*2045*) is not one, unless
    the line has three or more numbers."""
    raws = NUMBER.findall(text)
    if len(raws) < 3:
        raws = [r for r in raws if "." in r or "," in r]
    return _numbers(" ".join(raws))


def _numbers(text: str) -> list[Decimal]:
    out = []
    for raw in NUMBER.findall(text):
        neg = raw.startswith("(") or raw.startswith("-")
        try:
            v = Decimal(raw.strip("()$-").replace("$", "").replace(",", ""))
        except ArithmeticError:
            continue
        out.append(-v if neg else v)
    return out


def _first_amount(line: str, label: re.Pattern) -> Decimal | None:
    m = label.search(line)
    if not m:
        return None
    found = _numbers(line[m.end() :])
    return found[0] if found else None


def _summary(lines: list[str]) -> Summary:
    out = Summary()
    for line in lines[:150]:
        for name, label in (
            ("starting", STARTING),
            ("ending", ENDING),
            ("deposits", DEPOSITS),
            ("withdrawals", WITHDRAWALS),
            ("income", INCOME),
            ("change", CHANGE),
        ):
            if getattr(out, name) is None:
                v = _first_amount(line, label)
                if v is not None:
                    setattr(out, name, v)
    if out.withdrawals is not None:
        out.withdrawals = -abs(out.withdrawals)
    return out


def _heading(line: str) -> str | None:
    if len(line) > 60 or _numbers(line):
        return None
    if POSITIONS.match(line):
        return "positions"
    if ACTIVITY.match(line):
        return "activity"
    if OTHER.match(line):
        return "other"
    return None


def _position(label: str, figures: list[Decimal], first: str, group: str = "") -> Position:
    symbol = cusip = None
    m = CUSIP.match(first)
    if m and any(ch.isdigit() for ch in m.group(1)):
        cusip = m.group(1)
    else:
        m = SYMBOL.match(first)
        if m:
            symbol = m.group(1)
    cash = bool(CASH.search(label) or CASH.search(group))
    qty = price = value = cost = None
    if len(figures) >= 4:
        qty, price, value, cost = figures[0], figures[1], figures[2], figures[3]
    elif len(figures) == 3:
        qty, price, value = figures
    elif len(figures) == 2:
        qty, value = figures
    elif figures:
        value = figures[0]
    if cash and value is not None:
        qty, price = value, Decimal(1)
    return Position(label, symbol, cusip, qty, price, value, cost, cash)


def _activity(line: str, lead, period_end, fallback_year) -> Activity | None:
    day = _date_of(lead.groups(), period_end, fallback_year)
    if day is None:
        return None
    rest = line[lead.end() :]
    figures = _numbers(rest)
    if not figures:
        return None
    first = NUMBER.search(rest)
    description = re.sub(r"\s{2,}", " ", rest[: first.start()].strip(" .*")) if first else rest
    amount = figures[-1]
    for kind, words in NOT_READ:
        if words.search(description):
            sym = next(
                (t for t in re.findall(r"\b([A-Z]{1,5})\b", description) if t not in ACTIONS),
                None,
            )
            qty = figures[0] if len(figures) >= 3 else None
            price = figures[1] if len(figures) >= 3 else None
            return Activity(
                day,
                description[:200],
                amount,
                kind,
                True,
                sym,
                abs(qty) if qty is not None else None,
                abs(price) if price is not None else None,
            )
    kind = "deposit" if amount > 0 else "withdrawal"
    for k, words in KINDS:
        if words.search(description):
            kind = k
            break
    if kind in ("withdrawal", "fee"):
        amount = -abs(amount)
    elif kind in ("deposit", "dividend", "interest"):
        amount = abs(amount)
    sym = re.search(r"\b([A-Z]{2,5})\b", description) if kind == "dividend" else None
    return Activity(day, description[:200], amount, kind, False, sym.group(1) if sym else None)


def parse(lines: list[str], today: dt.date, layout: dict | None = None) -> Brokerage:
    skip = [x.lower() for x in ((layout or {}).get("brokerage") or {}).get("skip", [])]
    out = Brokerage()
    out.periodStart, out.periodEnd = _period(lines)
    out.institution = _institution(lines)
    out.summary = _summary(lines)
    fallback_year = (out.periodEnd or today).year
    section = None
    pending: str | None = None  # a name whose figures are on the next line
    group = ""  # the heading over a run of positions: *Cash and Cash Investments*
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        head = _heading(line)
        if head is not None:
            section, pending, group = head, None, ""
            continue
        if section == "positions":
            if TOTAL.match(line):
                pending = None
                continue
            figures = _figures(line)
            marks = [m for m in NUMBER.finditer(line) if "." in m.group(1) or "," in m.group(1)]
            first = marks[0] if marks else NUMBER.search(line)
            label = line[: first.start()].strip() if first and figures else line
            if not figures:
                pending = line[:120]
                continue
            if not label and pending:
                label, line = pending, pending + " " + line
            elif pending and not SYMBOL.match(line) and not CUSIP.match(line):
                label, line = f"{pending} {label}".strip(), pending + " " + line
            elif pending:
                group = pending  # a row of its own under it: it was a heading
            pending = None
            if not label:
                continue
            out.positions.append(_position(label[:120], figures, line, group))
        elif section == "activity":
            lead = LEAD_DATE.match(line)
            if not lead:
                continue
            a = _activity(line, lead, out.periodEnd, fallback_year)
            if a is None:
                continue
            a.ignored = next((x for x in skip if a.description.lower().startswith(x)), None)
            out.activity.append(a)
    if out.periodStart is None and out.activity:
        out.periodStart = min(a.date for a in out.activity)
        out.periodEnd = max(a.date for a in out.activity)
    return out


def totals(b: Brokerage) -> dict[str, Decimal]:
    """The cash lines read, by what the summary calls them, to check against it."""
    t = {"deposits": Decimal(0), "withdrawals": Decimal(0), "income": Decimal(0)}
    for a in b.activity:
        if a.notRead:
            continue
        if a.kind == "deposit":
            t["deposits"] += a.amount
        elif a.kind in ("withdrawal",):
            t["withdrawals"] += a.amount
        elif a.kind in ("dividend", "interest"):
            t["income"] += a.amount
    return t


def learn(layout: dict | None, remember: list[str] = (), forget: list[str] = ()) -> dict:
    """The lines of an institution's brokerage statements to ignore, only as the person asked
    (S1.3.3.4), never learned from what they left out."""
    from .statements import ignoring

    out = dict(layout or {})
    mine = dict(out.get("brokerage") or {})
    mine["skip"] = ignoring(list(mine.get("skip", [])), list(remember), list(forget))
    out["brokerage"] = mine
    return out


__all__ = ["Activity", "Brokerage", "Position", "Summary", "learn", "parse", "parse_amount"]
