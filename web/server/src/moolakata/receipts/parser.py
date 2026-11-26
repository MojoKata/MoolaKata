"""The field parser (requirements S9.8.2.4–5): from a receipt's lines of text, in reading order,
the total, the date, the merchant, the tax and the card's last four digits, each with a
confidence. Rules, not a model, and tested on their own.
"""

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal

MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}
# An amount: 1,234.56 or 142.18, with a $ or a minus allowed; whole dollars aren't amounts here.
AMOUNT = re.compile(r"(?<![\d.,])-?\$?\s?(\d{1,3}(?:,\d{3})+|\d+)[.,](\d{2})(?!\d)")
TOTAL = re.compile(
    r"\b(grand\s*total|total\s*due|amount\s*due|balance\s*due|order\s*total|total\s*amount|"
    r"amount\s*paid|total)\b",
    re.I,
)
NOT_TOTAL = re.compile(
    r"\b(sub\s*-?\s*total|tax|change|cash|savings|you\s*saved|tip|gratuity|discount|"
    r"items?\s*sold|points|balance\s*forward|previous)\b",
    re.I,
)
TAX = re.compile(r"\b(sales\s*tax|tax|hst|gst|vat)\b", re.I)
CARD = re.compile(
    r"(?:[x*•]{4}[\s-]?|ending\s+(?:in\s+)?|acct\s*#?\s*[x*]*|card\s*#?\s*[x*]+)(\d{4})\b", re.I
)
DATE_PATTERNS = [
    # 2026-10-09
    (re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})"), ("y", "m", "d")),
    # 10/09/2026 or 10-09-26 (US: month first)
    (
        re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](20\d{2}|\d{2})(?!\d{0,1}[/\-])"),
        ("m", "d", "y"),
    ),
    # 09 OCT 26, 9 October 2026
    (
        re.compile(r"(?<!\d)(\d{1,2})\s*([A-Za-z]{3,9})\.?,?\s*(20\d{2}|\d{2})(?!\d)"),
        ("d", "mon", "y"),
    ),
    # Oct 9, 2026
    (
        re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:,\s*|\s+)(20\d{2}|\d{2})(?!\d)"),
        ("mon", "d", "y"),
    ),
]


@dataclass
class Field:
    value: object
    confidence: int  # 0–100


@dataclass
class Fields:
    total: Field | None = None
    date: Field | None = None
    merchant: Field | None = None
    tax: Field | None = None
    card: Field | None = None

    def as_dict(self) -> dict:
        return {
            k: {"value": str(v.value), "confidence": v.confidence}
            for k, v in self.__dict__.items()
            if v is not None
        }


def amounts(line: str) -> list[Decimal]:
    # AMOUNT's groups are digits (any script's, which Decimal reads too), so each is a number.
    return [Decimal(m.group(1).replace(",", "") + "." + m.group(2)) for m in AMOUNT.finditer(line)]


def join_split_amounts(line: str) -> str:
    """The recognizer sometimes splits a number at a space: `14 2.18` is 142.18."""
    return re.sub(r"(?<![\d.,])(\d{1,3}) (\d{1,3}[.,]\d{2})(?!\d)", r"\1\2", line)


def find_total(lines: list[str]) -> Field | None:
    """The amount on the last line labelled TOTAL (or AMOUNT DUE …), skipping subtotals,
    tax, change and the like; failing that, the largest amount."""
    best: Field | None = None
    for i, line in enumerate(lines):
        if not TOTAL.search(line) or NOT_TOTAL.search(line):
            continue
        found = amounts(line)
        if not found and i + 1 < len(lines):
            # The label on one line, its amount on the next.
            found = amounts(lines[i + 1])
        if found:
            best = Field(found[-1], 92)
    if best:
        return best
    every = [a for line in lines for a in amounts(line)]
    return Field(max(every), 55) if every else None


def find_tax(lines: list[str]) -> Field | None:
    for line in lines:
        if TAX.search(line) and not re.search(r"\b(total|pre-?tax)\b", line, re.I):
            found = amounts(line)
            if found:
                return Field(found[-1], 85)
    return None


def _year(y: str) -> int:
    n = int(y)
    return 2000 + n if n < 100 else n


def find_date(lines: list[str], today: dt.date, not_before: dt.date | None = None) -> Field | None:
    """Every common format; the most plausible: not in the future, not before the account
    opened, the first such on the receipt."""
    for line in lines:
        for pattern, order in DATE_PATTERNS:
            for m in pattern.finditer(line):
                parts = dict(zip(order, m.groups(), strict=True))
                try:
                    if "mon" in parts:
                        month = MONTHS.get(parts["mon"].lower().rstrip("."))
                        if month is None:
                            continue
                    else:
                        month = int(parts["m"])
                    day = dt.date(_year(parts["y"]), month, int(parts["d"]))
                except ValueError:
                    continue
                if day > today or (not_before and day < not_before):
                    continue
                if (today - day).days > 3 * 366:
                    continue
                return Field(day, 90 if "mon" in parts or len(parts["y"]) == 4 else 75)
    return None


def find_card(lines: list[str]) -> Field | None:
    for line in lines:
        m = CARD.search(line)
        if m:
            return Field(m.group(1), 88)
    return None


def find_merchant(lines: list[str]) -> Field | None:
    """The first line near the top that is a name: letters, not an address, phone, date or
    amount."""
    for line in lines[:6]:
        text = line.strip()
        letters = sum(ch.isalpha() for ch in text)
        if letters < 3 or letters < len(text) * 0.5:
            continue
        if re.search(r"\b(st|street|ave|road|rd|blvd|suite|www|http|tel|phone)\b", text, re.I):
            continue
        if amounts(text) or re.search(r"\d{3}[-. )]\d{3}[-. ]\d{4}", text):
            continue
        name = re.sub(r"\s*(#\s*\d+|store\s*\d+)\s*$", "", text, flags=re.I).strip(" -*")
        return Field(name.title() if name.isupper() else name, 70)
    return None


def _words(name: str) -> frozenset[str]:
    """A name's words as payees are compared: lower case, leaving out store numbers and words
    of one or two letters (`#042`, `SF`)."""
    return frozenset(
        w for w in re.findall(r"[\w']+", name.lower()) if len(w) > 2 and not re.search(r"\d", w)
    )


def known_payee(read: str, payees: list[str]) -> str | None:
    """The payee, of those given (most used first), that a merchant read from a receipt names
    (S9.8.2.5.3): the same words, or all of the shorter name's when it has two or more (*Whole
    Foods* in *Whole Foods Market*), never one word in a longer name (*Kroger*, *Kroger Fuel*).
    The closest wins, the first among equals; None when none does."""
    mine = _words(read)
    best, score = None, 0.0
    for payee in payees:
        theirs = _words(payee)
        common, short = len(mine & theirs), min(len(mine), len(theirs))
        if not common or (mine != theirs and (common < short or short < 2)):
            continue
        alike = common / len(mine | theirs)
        if alike > score:
            best, score = payee, alike
    return best


def parse(lines: list[str], today: dt.date, not_before: dt.date | None = None) -> Fields:
    lines = [join_split_amounts(x) for x in lines if x.strip()]
    return Fields(
        total=find_total(lines),
        date=find_date(lines, today, not_before),
        merchant=find_merchant(lines),
        tax=find_tax(lines),
        card=find_card(lines),
    )
