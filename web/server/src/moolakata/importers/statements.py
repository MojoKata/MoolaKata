"""Statements (requirements S1.3.3): a bank or card statement, as a PDF read from its text
layer or a photo or scan read by OCR, turned into its period, its opening and closing balances
and its transactions, for the person to check before anything is saved.

Built for the layouts most statements share (a UMB checking account, a Schwab Bank account, a
card's monthly statement):

- the **period** from *Statement Period*, *Opening/Closing Date* or a date range near the top;
  else the first and last transaction;
- the **balances** from *Beginning/Opening/Previous/Starting Balance* and
  *Ending/Closing/New Balance*;
- the **transactions**: a line that starts with a date (`09/03`, `09/03/26`, `Sep 3`) and ends
  in amounts. With two or more, the last is the running balance and the change in it gives the
  sign. Else an explicit sign (`-`, `( )`, `CR`) gives it, else the section the line is in
  (*Deposits and Other Credits*, *Withdrawals*, *Checks Paid*, *Purchases*, *Payments and
  Credits*), else a few words in the description.
- Summary and daily-balance sections are skipped.

A card statement shows what is owed: its amounts and balances are turned to the account's
side (a purchase takes money away; the balance owed is negative).

What is learned per institution (the layout) is kept: which section heading means money in or
out, and descriptions that are never transactions. The next statement from the same
institution applies it first.
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from ..receipts.parser import MONTHS

AMOUNT = re.compile(
    r"(?<![\w.,/])(\(?-?\+?\$?\s?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?(?:\s?(?:CR|DR)\b)?-?)"
)
LEAD_DATE = re.compile(
    r"^\s*(?:(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?|([A-Za-z]{3,9})\.?\s+(\d{1,2}))\b\s*"
)
OPENING = re.compile(r"\b(beginning|opening|previous|starting|prior)\s+balance\b", re.I)
CLOSING = re.compile(r"\b(ending|closing|new|statement)\s+balance\b", re.I)
PERIOD_LABEL = re.compile(
    r"\b(statement\s+period|period|opening\s*/\s*closing\s+date|for\s+the\s+period|"
    r"statement\s+dates?|billing\s+(?:period|cycle))\b",
    re.I,
)
SKIP_SECTION = re.compile(
    r"\b(daily\s+(?:ending\s+)?balances?|balance\s+summary|account\s+summary|summary\s+of|"
    r"interest\s+summary|year[- ]to[- ]date|fees\s+summary|totals?\s+for)\b",
    re.I,
)
IN_SECTION = re.compile(
    r"\b(deposits?|credits?|additions|payments?\s+and\s+(?:other\s+)?credits|money\s+in|"
    r"interest\s+paid|refunds?)\b",
    re.I,
)
OUT_SECTION = re.compile(
    r"\b(withdrawals?|debits?|subtractions|checks?(?:\s+paid)?|purchases?|fees?\s+charged|"
    r"interest\s+charged|money\s+out|electronic\s+payments|atm|card\s+transactions?)\b",
    re.I,
)
IN_WORDS = re.compile(
    r"\b(deposit|payroll|direct\s+dep|credit|refund|interest\s+paid|transfer\s+from|"
    r"payment\s+thank\s+you|payment\s+received)\b",
    re.I,
)
DATE_IN_TEXT = re.compile(
    r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})|([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s*(\d{4})?"
)
CENT = Decimal("0.01")


@dataclass
class StatementRow:
    date: dt.date
    description: str
    amount: Decimal
    balance: Decimal | None = None
    confidence: int = 90  # how sure the sign and amount are, 0–100
    section: str | None = None
    # The sign came from the statement's own figures (a sign, the running balance), which on a
    # card statement are what is owed; or from a section or the words, which are the account's.
    owedSide: bool = False


@dataclass
class Statement:
    periodStart: dt.date | None = None
    periodEnd: dt.date | None = None
    opening: Decimal | None = None
    closing: Decimal | None = None
    rows: list[StatementRow] = field(default_factory=list)
    institution: str | None = None
    card: bool = False

    @property
    def difference(self) -> Decimal | None:
        """What the transactions don't account for between the balances; 0 when they add up."""
        if self.opening is None or self.closing is None:
            return None
        return self.closing - self.opening - sum((r.amount for r in self.rows), Decimal(0))


def parse_amount(text: str) -> Decimal | None:
    t = text.strip()
    negative = t.startswith("(") or t.startswith("-") or t.endswith("-")
    credit = t.upper().endswith("CR")
    debit = t.upper().endswith("DR")
    digits = re.sub(r"[^\d.]", "", t.replace(",", ""))
    try:
        value = Decimal(digits).quantize(CENT)
    except InvalidOperation:
        return None
    return -value if (negative or debit) and not credit else value


def _explicit(text: str) -> bool:
    t = text.strip().upper()
    return t.startswith(("(", "-", "+")) or t.endswith(("-", "CR", "DR"))


def _year_for(month: int, period_end: dt.date | None, fallback: int) -> int:
    if period_end is None:
        return fallback
    # A December line on a January statement belongs to the year before.
    return period_end.year - 1 if month > period_end.month + 1 else period_end.year


def _date_of(groups, period_end: dt.date | None, fallback_year: int) -> dt.date | None:
    m1, d1, y1, mon, d2 = groups
    try:
        if mon:
            month = MONTHS.get(mon.lower().rstrip("."))
            if month is None:
                return None
            return dt.date(_year_for(month, period_end, fallback_year), month, int(d2))
        month, day = int(m1), int(d1)
        if y1:
            year = int(y1)
            year = 2000 + year if year < 100 else year
        else:
            year = _year_for(month, period_end, fallback_year)
        return dt.date(year, month, day)
    except ValueError:
        return None


def _dates_in(text: str) -> list[dt.date]:
    out = []
    for m in DATE_IN_TEXT.finditer(text):
        try:
            if m.group(1):
                y = int(m.group(3))
                out.append(dt.date(2000 + y if y < 100 else y, int(m.group(1)), int(m.group(2))))
            else:
                month = MONTHS.get(m.group(4).lower().rstrip("."))
                if month and m.group(6):
                    out.append(dt.date(int(m.group(6)), month, int(m.group(5))))
        except ValueError:
            continue
    return out


def _period(lines: list[str]) -> tuple[dt.date | None, dt.date | None]:
    """From a labelled line; `September 1 - 30, 2026` and `Sep 1 - Sep 30, 2026` too."""
    for line in lines[:40]:
        if not PERIOD_LABEL.search(line):
            continue
        found = _dates_in(line)
        if len(found) >= 2:
            return min(found), max(found)
        m = re.search(
            r"([A-Za-z]{3,9})\.?\s+(\d{1,2})\s*[-–]\s*(?:([A-Za-z]{3,9})\.?\s+)?(\d{1,2}),?\s*(\d{4})",
            line,
        )
        if m:
            m1 = MONTHS.get(m.group(1).lower().rstrip("."))
            m2 = MONTHS.get((m.group(3) or m.group(1)).lower().rstrip("."))
            if m1 and m2:
                year = int(m.group(5))
                try:
                    end = dt.date(year, m2, int(m.group(4)))
                    start = dt.date(year - 1 if m1 > m2 else year, m1, int(m.group(2)))
                    return start, end
                except ValueError:
                    pass
    return None, None


def _balance(lines: list[str], label: re.Pattern) -> Decimal | None:
    for line in lines:
        if label.search(line):
            found = AMOUNT.findall(line)
            if found:
                return parse_amount(found[-1])
    return None


def parse(
    lines: list[str],
    today: dt.date,
    layout: dict | None = None,
    card: bool = False,
    institution: str | None = None,
    period: tuple[dt.date | None, dt.date | None] | None = None,
) -> Statement:
    """`period`: the whole statement's, for a part of one that doesn't repeat it."""
    layout = layout or {}
    learned = {k.lower(): v for k, v in layout.get("signs", {}).items()}
    skip = [x.lower() for x in layout.get("skip", [])]
    st = Statement(institution=institution, card=card)
    st.periodStart, st.periodEnd = _period(lines)
    if st.periodStart is None and period is not None:
        st.periodStart, st.periodEnd = period
    st.opening = _balance(lines, OPENING)
    st.closing = _balance(lines, CLOSING)
    fallback_year = (st.periodEnd or today).year
    section_sign = 0
    section = None
    skipping = False
    last_balance = st.opening
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        amounts = AMOUNT.findall(line)
        lead = LEAD_DATE.match(line)
        if not lead or not amounts:
            # A heading: the section the next lines are in.
            if not amounts and not lead and len(line) < 60:
                key = line.lower()
                if key in learned:
                    section, section_sign, skipping = key, learned[key], learned[key] == 0
                elif SKIP_SECTION.search(line):
                    section, section_sign, skipping = key, 0, True
                elif OUT_SECTION.search(line):
                    section, section_sign, skipping = key, -1, False
                elif IN_SECTION.search(line):
                    section, section_sign, skipping = key, 1, False
            continue
        if skipping or OPENING.search(line) or CLOSING.search(line):
            continue
        day = _date_of(lead.groups(), st.periodEnd, fallback_year)
        if day is None:
            continue
        rest = line[lead.end() :]
        first = AMOUNT.search(rest)
        description = rest[: first.start()].strip(" .*") if first else rest
        description = re.sub(r"\s{2,}", " ", description)
        if any(description.lower().startswith(x) for x in skip):
            continue
        values = [parse_amount(a) for a in amounts]
        values = [v for v in values if v is not None]
        if not values:
            continue
        balance = None
        amount = values[0]
        confidence = 70
        owed_side = True
        if len(values) >= 2:
            balance = values[-1]
            amount = values[-2]
            if last_balance is not None:
                delta = balance - last_balance
                if abs(delta) == abs(amount):
                    amount, confidence = delta, 97
            last_balance = balance
        if confidence < 97:
            text = amounts[0] if len(values) == 1 else amounts[-2]
            if _explicit(text):
                confidence = 92
                # CR and DR say the account's side already (a card's payment is a credit);
                # a minus or brackets are the statement's own, turned once below.
                if text.strip().upper().endswith(("CR", "DR")):
                    owed_side = False
            elif section_sign:
                amount, confidence, owed_side = abs(amount) * section_sign, 88, False
            else:
                amount = abs(amount) if IN_WORDS.search(description) else -abs(amount)
                confidence, owed_side = 60, False
        st.rows.append(
            StatementRow(day, description[:200], amount, balance, confidence, section, owed_side)
        )
    if card:
        # A card statement shows what is owed: its own figures are turned to the account's side.
        for r in st.rows:
            if r.owedSide:
                r.amount = -r.amount
            if r.balance is not None:
                r.balance = -r.balance
        st.opening = -st.opening if st.opening is not None else None
        st.closing = -st.closing if st.closing is not None else None
    if st.rows and st.periodStart is None:
        st.periodStart = min(r.date for r in st.rows)
        st.periodEnd = max(r.date for r in st.rows)
    if st.institution is None:
        st.institution = _institution(lines)
    return st


def _institution(lines: list[str]) -> str | None:
    """The first line near the top that names a bank or card issuer."""
    for line in lines[:8]:
        if re.search(r"\b(bank|credit\s+union|card|schwab|financial|n\.a\.)\b", line, re.I):
            return line.strip()[:80]
    return None


# A header naming one account's part of a combined statement (S1.3.3.5): *Account Number
# XXXX-1234*, *Account ending in 9030*, *Acct # ...5521*, or a name followed by its number.
ACCOUNT_HEADER = re.compile(
    r"\b(?:account\s+(?:number|no\.?|#)|account\s+ending(?:\s+in)?|acct\.?\s*(?:#|no\.?|"
    r"ending(?:\s+in)?))\s*:?\s*[xX*•.\-\s\d]*?(\d{4})\b(?!\s*[/-]\d)",
    re.I,
)
NAMED_HEADER = re.compile(
    r"^\s*(?:[A-Z][\w'&]*\s+){0,4}(?:checking|savings|money\s+market|brokerage|card)\b[^\d]{0,20}"
    r"[xX*•.\-]{2,}\s?(\d{4})\s*$",
    re.I,
)


@dataclass
class Part:
    """One account's part of a statement, from the header naming it."""

    last4: str
    header: str
    lines: list[str]


def split(lines: list[str]) -> list[Part]:
    """The parts of a statement of several accounts, each from a header naming an account to
    the next naming another; a header repeated on later pages stays in its part. A statement of
    one account gives one part, or none when no header names an account."""
    parts: list[Part] = []
    by_last4: dict[str, Part] = {}
    current: Part | None = None
    for line in lines:
        m = ACCOUNT_HEADER.search(line) or NAMED_HEADER.match(line)
        if m and (current is None or m.group(1) != current.last4):
            current = by_last4.get(m.group(1))
            if current is None:
                current = Part(m.group(1), line.strip()[:120], [])
                by_last4[current.last4] = current
                parts.append(current)
        if current is not None:
            current.lines.append(line)
    return parts


def period_and_institution(lines: list[str]) -> tuple[dt.date | None, dt.date | None, str | None]:
    """What a statement kept without reading is named by: its period and institution, where
    they can be read (S1.3.3.6)."""
    start, end = _period(lines)
    if start is None:
        days = [d for line in lines[:60] for d in _dates_in(line)]
        if len(days) >= 2:
            start, end = min(days), max(days)
    return start, end, _institution(lines)


def name(institution: str | None, start: dt.date | None, end: dt.date | None) -> str:
    """A statement's name, from its period: *UMB statement, Sep 1 – Sep 30, 2026*."""
    who = f"{institution} statement" if institution else "Statement"
    if start is None or end is None:
        return who
    if start.year == end.year:
        return f"{who}, {start:%b %-d} – {end:%b %-d, %Y}"
    return f"{who}, {start:%b %-d, %Y} – {end:%b %-d, %Y}"


def learn(
    layout: dict | None,
    kept: list[StatementRow],
    left: list[StatementRow],
    present: set = frozenset(),
) -> dict:
    """What a checked statement teaches about its institution's layout (S1.3.3.4): the sign
    each section heading gave the rows the person kept, and the first words of the lines they
    took out by choice. `kept` and `left` are the lines as they were read (a kept line with the
    sign the person gave it), so a corrected description teaches nothing. A line left out
    because it was already in the account (`present`, by date and amount) teaches nothing, and
    neither does one whose first words start a line the person kept, which the skip would drop
    next time."""
    out = {
        "signs": dict((layout or {}).get("signs", {})),
        "skip": list((layout or {}).get("skip", [])),
    }
    for r in kept:
        if r.section:
            out["signs"][r.section] = 1 if r.amount > 0 else -1
    kept_text = [r.description.lower() for r in kept]
    for r in left:
        if (r.date, r.amount) in present or not r.description:
            continue
        words = " ".join(r.description.lower().split()[:3])
        if not words or words in out["skip"]:
            continue
        if any(k.startswith(words) for k in kept_text):
            continue
        out["skip"].append(words)
    return out
