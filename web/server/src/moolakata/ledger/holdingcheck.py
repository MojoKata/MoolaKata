"""The holdings check (requirements S1.3.3.8.2): the positions a brokerage statement shows on
its last day against what MoolaKata holds then. A quantity that differs is shown with the
difference, as an anchor shows a cash difference; the statement's cost basis is shown beside
the lots' and never written over them."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from . import lots

ZERO = Decimal(0)


def held_on(ledger, day: dt.date) -> dict[str, tuple[Decimal, Decimal | None]]:
    """Each instrument's quantity and remaining basis at the end of a day."""
    rp = lots.replay(
        ledger.account.lotMethod,
        [t for t in ledger.transactions if t.date <= day],
        [x for x in ledger.lots if x.acquiredOn <= day],
        ledger.picks,
        [h for h in ledger.snapshots if h.asOf <= day],
        # Wash sales whose loss sale is past by the day's end.
        [
            w
            for w in ledger.washes
            if w.saleId in ledger.sale_at and ledger.sale_at[w.saleId][0] <= day
        ],
        lots.kept_by_snapshots(ledger.transactions),
        lots.adds_basis(ledger.account.type),
        ledger.averaged,
        ledger.sale_at,
    )
    out: dict[str, tuple[Decimal, Decimal | None]] = {}
    for lot in rp.open:
        q, b = out.get(lot.instrumentId, (ZERO, ZERO))
        basis = None if b is None or lot.basis is None else b + lot.basis
        out[lot.instrumentId] = (q + lot.quantity, basis)
    return out


@dataclass
class Line:
    label: str
    instrumentId: str | None
    statement: Decimal | None  # its quantity, or the cash
    held: Decimal | None  # MoolaKata's; none when not matched
    statementBasis: Decimal | None
    heldBasis: Decimal | None
    cash: bool
    hint: str | None = None

    @property
    def difference(self) -> Decimal | None:
        if self.statement is None or self.held is None:
            return None
        return self.statement - self.held

    @property
    def ok(self) -> bool:
        return self.difference == 0


def compare(ledger, day: dt.date, rows: list, trades: list | None = None) -> list[Line]:
    """Each statement row against the ledger that day; the cash line against its cash. A
    difference the statement's own trade lines account for (a reinvestment, a buy not yet
    entered) is pointed at: `trades` are (date, instrument id, signed quantity, what)."""
    held = held_on(ledger, day)
    out = []
    for r in rows:
        if r.cash:
            out.append(Line(r.label, None, r.marketValue, ledger.balance(day), None, None, True))
            continue
        q, basis = held.get(r.instrumentId, (ZERO, ZERO)) if r.instrumentId else (None, None)
        line = Line(r.label, r.instrumentId, r.quantity, q, r.costBasis, basis, False)
        diff = line.difference
        if diff:
            mine = [t for t in trades or [] if t[1] == r.instrumentId]
            one = next((t for t in mine if t[2] == diff), None)
            if one is not None:
                line.hint = f"the {one[0]:%b %-d} {one[3]} of {abs(one[2])} isn't entered yet"
            elif mine and sum((t[2] for t in mine), ZERO) == diff:
                line.hint = "the statement's trades in it aren't entered yet"
        out.append(line)
    return out
