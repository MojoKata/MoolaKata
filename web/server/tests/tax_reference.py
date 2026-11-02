"""A reference model of Form 8949 (requirements S2.2, S2.3, S3.1, S3.8, S8.1), written apart from
the app and as plainly as possible: it reads a generated tax world (`tax_world`) and works out,
for each tax book, the rows its Form 8949 must have. It imports nothing of MoolaKata, so a rule
the app gets wrong everywhere the same way still fails against it.

The rules, each as the requirements state it:

1. **Lots** (S2.2, S2.3): each buy is a lot. A sale takes its shares by the account's lot method
   (first in, last in, highest cost, or the average cost of all shares held: for funds and
   coins only, a share in such an account going first in), or from the lots picked, the rest
   first in. Proceeds and basis are shared by quantity, to the cent, the last
   part taking what is left of the proceeds.
2. **Term** (S3.1): long-term when sold after the anniversary of the day acquired (the 28th for
   a lot bought on 29 February), counted from the day a wash sale's replacement takes on.
3. **Wash sales** (S3.8): a loss sale of a share or fund (not a coin) with the same instrument
   bought within 30 days before or after, in any account of the seller or of their spouse
   (IRAs included), but not the shares sold, nor shares of a buy the same sale sold (S3.8.2:
   never their own replacement). Buys nearest the sale replace first, the sold shares they
   replace taken in the order acquired, the earliest first (Treas. Reg. §1.1091-1(c)); a buy
   replaces as many shares as it bought, once. The loss disallowed is the sold shares' loss in
   proportion to the shares replaced; it is added to the replacement's basis (not in an IRA,
   where it is lost) and the replacement is held from the day that makes its holding period
   include the sold shares', from the loss sale on (a replacement bought before the sale is a
   plain lot until then, so the sale never picks its lots by the loss it is about to have
   disallowed). A replacement's own loss sale may be a wash sale in turn: worked out again
   until nothing changes.
4. **Boxes** (S8.1): a coin from 2025 has boxes of its own (G–L): a self-custody wallet's I/L;
   an exchange's G/J when acquired from 2026, else H/K. A share or fund: basis reported (A/D)
   for shares acquired from 2011 and funds from 2012, else not reported (B/E). Short term
   first.
5. **A tax book** (S8.14.2) holds the sales in the year of its filers' taxable accounts.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal

import tax_world as tw

CENT = Decimal("0.01")
WINDOW = 30


def cents(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_EVEN)


# A merger's new shares are of the class the old ones were (S2.4): the world being worked out
# names them, `_merged(w)`.
_MERGED: dict[str, str] = {}


def _merged(w: tw.World) -> None:
    _MERGED.clear()
    _MERGED.update({t.new_symbol: t.symbol for t in w.trades if t.kind == "merger"})


def class_of(symbol: str) -> str:
    """A hand-typed symbol's class (CR3-14): five letters ending in X is a fund; an option's
    contract (SPY 18DEC26 500 C) an option; a merger's new shares the old ones' class."""
    symbol = _MERGED.get(symbol, symbol)
    if " " in symbol:
        return "option"
    if len(symbol) == 5 and symbol.isalpha() and symbol.endswith("X"):
        return "mutual-fund"
    return "equity"


@dataclass
class Lot:
    buy: int  # the buy's index in the world's trades
    symbol: str
    acquired: dt.date
    quantity: Decimal
    basis: Decimal
    held_from: dt.date | None = None


@dataclass
class Part:
    """One lot's share of a sale."""

    sale: int
    buy: int
    account: str
    symbol: str
    acquired: dt.date
    sold: dt.date
    quantity: Decimal
    proceeds: Decimal
    basis: Decimal
    held_from: dt.date | None
    adjustment: Decimal = Decimal(0)
    written: bool = False  # a contract sold to open: short term however long (S3.3)

    @property
    def raw(self) -> Decimal:
        return self.proceeds - self.basis


@dataclass(frozen=True)
class Replacement:
    sale: int
    lot: int  # the sold lot's buy: its loss is the one disallowed
    buy: int
    quantity: Decimal
    disallowed: Decimal
    held_from: dt.date


@dataclass
class Row:
    account: str
    description: str
    acquired: dt.date
    sold: dt.date
    proceeds: Decimal
    basis: Decimal
    adjustment: Decimal
    long_term: bool
    box: str

    def key(self) -> tuple:
        return (self.account, self.description, self.acquired, self.sold, self.proceeds,
                self.basis, self.adjustment, self.long_term, self.box)  # fmt: skip


@dataclass
class Household:
    world: tw.World
    parts: list[Part] = field(default_factory=list)
    replacements: list[Replacement] = field(default_factory=list)


def _owner(account: str) -> str:
    return tw.ACCOUNTS[account][0]


def _type(account: str) -> str:
    return tw.ACCOUNTS[account][1]


def _washable(symbol: str, account: str) -> bool:
    return _type(account) in ("brokerage", "ira") and class_of(symbol) in ("equity", "mutual-fund")


OPENS = ("buy-to-open", "sell-to-open")
CLOSES = ("sell-to-close", "buy-to-close", "expire", "assign", "exercise")


def _anniversary(d: dt.date) -> dt.date:
    if d.month == 2 and d.day == 29:
        return dt.date(d.year + 1, 2, 28)
    return dt.date(d.year + 1, d.month, d.day)


def long_term(held_from: dt.date, sold: dt.date) -> bool:
    return sold > _anniversary(held_from)


def _replay(w: tw.World, account: str, replacements: list[Replacement]) -> list[Part]:
    """One account's sales, lot by lot, with the wash sales so far applied. A replacement's
    shares split off their lot when bought; the loss joins their basis, and their holding
    period moves, from the loss sale on: a replacement bought before the sale is a plain lot
    until then, so the sale it replaces never chooses its lots by the loss it is about to
    have disallowed."""
    method = w.methods[account]
    adds = _type(account) != "ira"
    events: list[tuple] = []
    for i, t in enumerate(w.trades):
        if t.account == account:
            events.append((t.date, i, 0, t))
    for r in replacements:
        if w.trades[r.buy].account == account:
            sale = w.trades[r.sale]
            events.append((sale.date, r.sale, 1, r))
            if (w.trades[r.buy].date, r.buy) > (sale.date, r.sale):
                events.append((w.trades[r.buy].date, r.buy, 1, r))  # bought after: at the buy
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    pieces: dict[Replacement, Lot] = {}
    done: set[Replacement] = set()
    lots: list[Lot] = []
    parts: list[Part] = []
    premium: dict[int, Decimal] = {}  # an assignment's or exercise's premium, by the end
    for _, i, what, t in events:
        if what == 1:
            r = t
            x = pieces.get(r)
            if x is None or r in done:
                continue
            done.add(r)
            if x.quantity > 0 and adds:
                x.basis += cents(r.disallowed * x.quantity / r.quantity)
            x.held_from = r.held_from
            continue
        if t.kind in OPENS or t.kind in CLOSES:
            _contract(t, i, account, lots, parts, premium)
            continue
        if t.kind == "merger":
            _merger(t, i, account, lots, parts)
            continue
        if t.kind == "split":
            # Each share held becomes `ratio`: quantities grow, basis stays (S2.4).
            for x in lots:
                if x.symbol == t.symbol:
                    x.quantity *= t.ratio
            continue
        if t.kind == "buy":
            # Shares bought by an exercised call or an assigned put take its premium (S3.4).
            extra = premium.get(t.leg_of, Decimal(0)) if t.leg_of is not None else Decimal(0)
            whole = Lot(i, t.symbol, t.date, Decimal(t.quantity), Decimal(t.cents) / 100 + extra)
            lots.append(whole)
            for r in [r for r in replacements if r.buy == i]:
                take = min(r.quantity, whole.quantity)
                if take <= 0:
                    continue
                share = cents(whole.basis * take / whole.quantity)
                whole.basis -= share
                whole.quantity -= take
                pieces[r] = Lot(i, t.symbol, t.date, take, share)
                lots.append(pieces[r])
            continue
        held = [x for x in lots if x.symbol == t.symbol and x.quantity > 0]
        qty = Decimal(t.quantity)
        plan: list[tuple[Lot, Decimal]] = []
        left = qty
        for buy, n in t.picks:
            # A picked lot is every piece of it, the shares that replaced a sale's included.
            for x in [x for x in held if x.buy == buy]:
                take = min(Decimal(n) - sum((q for y, q in plan if y.buy == buy), Decimal(0)),
                           x.quantity, left)  # fmt: skip
                if take > 0:
                    plan.append((x, take))
                    left -= take
        order = "fifo" if t.picks else method
        crypto = _type(account) in ("crypto-exchange", "crypto-wallet")
        if order == "average" and not crypto and class_of(t.symbol) != "mutual-fund":
            order = "fifo"  # average cost is for funds and coins (S2.3); a share goes first in
        if order == "average":
            pool = sum((x.quantity for x in held), Decimal(0))
            whole = sum((x.basis for x in held), Decimal(0))
            given = Decimal(0)
            for k, x in enumerate(held):
                x.basis = whole - given if k == len(held) - 1 else cents(whole * x.quantity / pool)
                given += x.basis if k < len(held) - 1 else 0
            order = "fifo"
        if order == "fifo":
            ranked = sorted(held, key=lambda x: x.acquired)
        elif order == "lifo":
            ranked = sorted(held, key=lambda x: x.acquired, reverse=True)
        else:  # hifo
            ranked = sorted(held, key=lambda x: -(x.basis / x.quantity))
        for x in ranked:
            if left <= 0:
                break
            room = x.quantity - sum((q for y, q in plan if y is x), Decimal(0))
            take = min(left, room)
            if take > 0:
                plan.append((x, take))
                left -= take
        assert left == 0, ("sold more than held", t)
        proceeds = Decimal(t.cents) / 100
        if t.leg_of is not None:
            # Shares sold by an assigned call or an exercised put: the premium in the proceeds.
            proceeds -= premium.get(t.leg_of, Decimal(0))
        given = Decimal(0)
        for k, (x, take) in enumerate(plan):
            share = proceeds - given if k == len(plan) - 1 else cents(proceeds * take / qty)
            given += share
            basis = x.basis if take == x.quantity else cents(x.basis * take / x.quantity)
            x.basis -= basis
            x.quantity -= take
            parts.append(Part(i, x.buy, account, t.symbol, x.acquired, t.date, take, share, basis,
                              x.held_from))  # fmt: skip
    return parts


def _contract(t: tw.Trade, i: int, account: str, lots: list[Lot], parts: list[Part],
              premium: dict[int, Decimal]) -> None:  # fmt: skip
    """An option trade (S3.2–S3.4). Long: a lot like a share's, its cost the basis. Short:
    a lot of what was received. Closing or expiry realizes either, first in; a written one is
    short term, its proceeds the credit and its basis the cost to close. An assignment or an
    exercise realizes nothing itself: its premium goes into the stock trade made with it."""
    sym = t.option
    n = Decimal(t.quantity)
    cash = Decimal(t.cents) / 100
    if t.kind == "buy-to-open":
        lots.append(Lot(i, sym, t.date, n, cash))
        return
    if t.kind == "sell-to-open":
        lots.append(Lot(i, sym, t.date, -n, cash))  # a short lot: its basis the credit
        return
    longs = sorted(
        (x for x in lots if x.symbol == sym and x.quantity > 0), key=lambda x: x.acquired
    )
    shorts = sorted((x for x in lots if x.symbol == sym and x.quantity < 0),
                    key=lambda x: x.acquired)  # fmt: skip
    day = t.expiry if t.kind == "expire" else t.date
    if t.kind in ("assign", "exercise"):
        got = Decimal(0)
        left = n
        for x in longs or shorts:
            take = min(left, abs(x.quantity))
            if take <= 0:
                continue
            part = x.basis if take == abs(x.quantity) else cents(x.basis * take / abs(x.quantity))
            x.basis -= part
            x.quantity += -take if x.quantity > 0 else take
            left -= take
            # A long contract's premium was paid; a short one's received.
            got += part if longs else -part
        premium[i] = got
        return
    if longs:
        proceeds = cash if t.kind == "sell-to-close" else Decimal(0)
        left, given = n, Decimal(0)
        for x in longs:
            take = min(left, x.quantity)
            if take <= 0:
                continue
            left -= take
            share = proceeds - given if left <= 0 else cents(proceeds * take / n)
            given += share
            basis = x.basis if take == x.quantity else cents(x.basis * take / x.quantity)
            x.basis -= basis
            x.quantity -= take
            parts.append(Part(i, x.buy, account, sym, x.acquired, day, take, share, basis, None))
        return
    cost = cash if t.kind == "buy-to-close" else Decimal(0)
    left, given = n, Decimal(0)
    for x in shorts:
        take = min(left, -x.quantity)
        if take <= 0:
            continue
        left -= take
        share = cost - given if left <= 0 else cents(cost * take / n)
        given += share
        credit = x.basis if take == -x.quantity else cents(x.basis * take / -x.quantity)
        x.basis -= credit
        x.quantity += take
        parts.append(Part(i, x.buy, account, sym, x.acquired, day, take, credit, share, None,
                          written=True))  # fmt: skip


def _merger(t: tw.Trade, i: int, account: str, lots: list[Lot], parts: list[Part]) -> None:
    """A merger for shares and cash (S2.4, IRC §356): each lot becomes `ratio` new shares a
    share, held from the same day; its share of the cash is a gain only as far as both the cash
    and the gain go, the rest taken off the basis."""
    held = [x for x in lots if x.symbol == t.symbol and x.quantity > 0]
    total = sum((x.quantity for x in held), Decimal(0))
    cash = cents(Decimal(t.cash_cents) / 100 * total)
    price = Decimal(t.new_price)
    for x in held:
        boot = cents(cash * x.quantity / total)
        value = cents(x.quantity * t.ratio * price)
        recognized = max(Decimal(0), min(boot, boot + value - x.basis))
        if recognized:
            parts.append(Part(i, x.buy, account, t.new_symbol, x.acquired, t.date, Decimal(0),
                              recognized, Decimal(0), x.held_from))  # fmt: skip
        x.basis = x.basis - boot + recognized
        x.symbol = t.new_symbol
        x.quantity *= t.ratio


def _spouses(w: tw.World, a: str, b: str) -> bool:
    return a == b or w.married


def household(w: tw.World) -> Household:
    """Every account's sales, with the wash sales found again until nothing changes."""
    _merged(w)
    accounts = [a for a in tw.ACCOUNTS if _type(a) in tw.TAXABLE]
    # Shares that came through an option never replace (S3.8.5.3: flagged for review).
    buys = [(i, t) for i, t in enumerate(w.trades) if t.kind == "buy" and t.leg_of is None]
    found: list[Replacement] = []
    for _ in range(20):
        parts = [p for a in accounts for p in _replay(w, a, found)]
        losses = [p for p in parts if p.raw < 0 and _washable(p.symbol, p.account)]
        losses.sort(key=lambda p: (p.sold, p.sale, p.acquired))
        room = {i: Decimal(t.quantity) for i, t in buys}
        # What each sale took of each buy: shares sold in a sale never replace it.
        taken: dict[tuple[int, int], Decimal] = {}
        for q in parts:
            taken[(q.sale, q.buy)] = taken.get((q.sale, q.buy), Decimal(0)) + q.quantity
        nxt: list[Replacement] = []
        for p in losses:
            left = p.quantity
            near = [(abs((t.date - p.sold).days), i, t) for i, t in buys
                    if t.symbol == p.symbol and abs((t.date - p.sold).days) <= WINDOW
                    and i != p.buy and _washable(t.symbol, t.account)
                    and _spouses(w, _owner(p.account), _owner(t.account))]  # fmt: skip
            for _, i, t in sorted(near, key=lambda x: (x[0], x[1])):
                if left <= 0:
                    break
                take = min(left, room[i], Decimal(t.quantity) - taken.get((p.sale, i), 0))
                if take <= 0:
                    continue
                room[i] -= take
                left -= take
                start = p.held_from or p.acquired
                nxt.append(Replacement(p.sale, p.buy, i, take, cents(-p.raw * take / p.quantity),
                                       t.date - (p.sold - start)))  # fmt: skip
        if sorted(nxt, key=repr) == sorted(found, key=repr):
            break
        found = nxt
    else:
        raise AssertionError("the wash sales never settled")
    parts = [p for a in accounts for p in _replay(w, a, found)]
    # Each disallowed loss on the sold lot's losing parts, spread by their losses.
    by_lot: dict[tuple[int, int], Decimal] = {}
    for r in found:
        by_lot[(r.sale, r.lot)] = by_lot.get((r.sale, r.lot), Decimal(0)) + r.disallowed
    for (sale, lot), amount in by_lot.items():
        losing = [p for p in parts if p.sale == sale and p.buy == lot and p.raw < 0]
        total = -sum((p.raw for p in losing), Decimal(0))
        given = Decimal(0)
        for k, p in enumerate(losing):
            share = amount - given if k == len(losing) - 1 else cents(amount * -p.raw / total)
            p.adjustment += share
            given += share
    return Household(w, parts, found)


def counted(w: tw.World, year: int, filers: tuple[str, ...]) -> set[str]:
    """The accounts a book counts (S8.14.2): its filers' own, but one left out."""
    out = {a for a, (owner, _) in tw.ACCOUNTS.items() if owner in filers}
    if w.left_out and year == 2026 and "alice" in filers:
        out.discard("Second")
    return out


@dataclass
class IncomeTotals:
    interest: Decimal = Decimal(0)
    ordinary: Decimal = Decimal(0)  # qualified included (1099-DIV box 1a includes 1b)
    qualified: Decimal = Decimal(0)
    gain_distributions: Decimal = Decimal(0)


def income(w: tw.World, year: int, filers: tuple[str, ...]) -> IncomeTotals:
    """The book's income (S8.5): interest; dividends paid or reinvested, a dividend typed as
    neither qualified nor anything else ordinary; capital-gain distributions."""
    out = IncomeTotals()
    accounts = counted(w, year, filers)
    for i in w.incomes:
        if i.date.year != year or i.account not in accounts:
            continue
        amount = Decimal(i.cents) / 100
        if i.kind == "interest":
            out.interest += amount
        elif i.kind == "capital-gain":
            out.gain_distributions += amount
        else:
            out.ordinary += amount
            if i.dividend_type == "qualified":
                out.qualified += amount
    return out


def box(p: Part, year: int) -> str:
    lt = not p.written and long_term(p.held_from or p.acquired, p.sold)
    kind = _type(p.account)
    if kind in ("crypto-exchange", "crypto-wallet"):
        if kind == "crypto-wallet":
            return "L" if lt else "I"
        if p.acquired >= dt.date(2026, 1, 1):
            return "J" if lt else "G"
        return "K" if lt else "H"
    reported_from = {"equity": dt.date(2011, 1, 1), "mutual-fund": dt.date(2012, 1, 1)}.get(
        class_of(p.symbol), dt.date(2014, 1, 1)
    )
    if p.acquired >= reported_from:
        return "D" if lt else "A"
    return "E" if lt else "B"


def _qty(q: Decimal) -> str:
    return f"{q.normalize():f}"


def rows(h: Household, year: int, filers: tuple[str, ...]) -> list[Row]:
    """The Form 8949 rows of the book of these filers for the year."""
    _merged(h.world)
    out = []
    for p in h.parts:
        if p.sold.year != year or p.account not in counted(h.world, year, filers):
            continue
        out.append(
            Row(
                account=p.account,
                description=f"{_qty(p.quantity)} {p.symbol}",
                acquired=p.acquired,
                sold=p.sold,
                proceeds=cents(p.proceeds),
                basis=cents(p.basis),
                adjustment=cents(p.adjustment),
                long_term=not p.written and long_term(p.held_from or p.acquired, p.sold),
                box=box(p, year),
            )
        )
    return out
