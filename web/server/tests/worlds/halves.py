"""Generated loan-payment sequences (requirements S1.7, S1.9.3, CR3-22): one payment reaching
MoolaKata from both sides, in either order and by every path, drawn from a seed.
`test_halves_world` makes each sequence through the API and holds it to one rule: one real
payment is one loan row and one bank row, paired.

A **sequence**: the bank's half arrives by an imported statement or typed in the bank account;
the loan's by the payment dialog with *From account: None*, with *From account* the bank (which
pairs with the bank's half already there), or typed in the loan's account; one first and then
the other; the two amounts equal, near (within 2%) or apart; the two days the same, 3 days
apart or 5. After both, the user acts on *Looks like a payment* when it offers to pair.

The same payment is equal amounts at most 4 days apart (S1.7's rule): it must end paired, one
row each side. Any other sequence holds two payments' worth of rows, never more.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass
from decimal import Decimal

from worlds import Axes, decks

BANK = ("import", "typed")
LOAN = ("none", "from", "typed")
ORDERS = ("bank-first", "loan-first")
AMOUNTS = ("equal", "near", "apart")
DAYS = ("0", "3", "5")

_AXES = {"sequence": {"bank": BANK, "loan": LOAN, "order": ORDERS, "amount": AMOUNTS,
                      "days": DAYS}}  # fmt: skip
AXES = Axes(_AXES)
SEEDS = range(6)
PAYMENT = Decimal("1798.65")
TODAY = dt.date(2026, 10, 13)


@dataclass
class Sequence:
    axes: dict
    loan_day: dt.date
    bank_day: dt.date
    loan_amount: Decimal
    bank_amount: Decimal

    @property
    def same(self) -> bool:
        """The same payment by S1.7: equal amounts, at most 4 days apart."""
        return (
            self.loan_amount == self.bank_amount and abs((self.loan_day - self.bank_day).days) <= 4
        )


@dataclass
class World:
    seed: int
    sequences: list[Sequence]

    def records(self) -> dict[str, list[dict]]:
        return {"sequence": [s.axes for s in self.sequences]}


def world(seed: int) -> World:
    rnd = random.Random(seed)
    out = []
    for k, axes in enumerate(decks(rnd, _AXES["sequence"], 6)):
        loan_day = dt.date(2026, 10, 1)
        bank_day = loan_day + dt.timedelta(days=int(axes["days"]) * rnd.choice((1, -1)))
        # Each sequence its own amount, so no two of a world's can be taken for one another.
        pay = PAYMENT + k * 10
        bank = {"equal": pay, "near": pay + Decimal("1.35"), "apart": pay + 150}
        out.append(Sequence(axes, loan_day, bank_day, pay, bank[axes["amount"]]))
    return World(seed, out)


def ofx(day: dt.date, amount: Decimal, fitid: str, acct: str = "000123456789") -> bytes:
    """A bank statement holding one debit, for the bank account numbered `acct`."""
    d = day.strftime("%Y%m%d")
    return f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS><DTSERVER>{d}120000<LANGUAGE>ENG<FI><ORG>First Example Bank<FID>1234</FI></SONRS></SIGNONMSGSRSV1>
<BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS>
<STMTRS><CURDEF>USD<BANKACCTFROM><BANKID>021000021<ACCTID>{acct}<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST><DTSTART>{d}<DTEND>{d}
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>{d}<TRNAMT>-{amount}<FITID>{fitid}<NAME>ROCKET MORTGAGE</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>{Decimal(20000) - amount}<DTASOF>{d}</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
""".encode()  # noqa: E501
