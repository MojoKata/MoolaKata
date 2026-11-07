"""Generated account worlds (requirements S1.9, S1.10, S4, S5.1, S5.2, S6.1, S6.4.2.2): a
household's accounts of every kind (bank, investing with stocks, funds, bonds, coins and
options, loans of every shape, physical assets), some shared with a viewer, and a decoy household
holding the same symbols, drawn from a seed. A world is a plain description (`World`), its pairs
checked without a server (`AXES.missing`); `value` works out, from the description alone, what
each account is worth today, as plainly as possible; `test_account_world` makes each world
through the API and holds every figure built on accounts to it and to each other.

An **account** record's axes: its kind, whether the viewer sees it, how old it is, a rounding
shape (whole or fractional amounts) and a move in its last month (money or shares in or out, an
item added or sold, a HELOC draw), which the series' flows are held to.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

from worlds import Axes, Plant, decks

TODAY = dt.date(2026, 10, 13)
D = Decimal
CENT = D("0.01")

BANK = ("checking", "savings")
INVESTING = ("brokerage", "options", "crypto")
LOANS = ("mortgage", "heloc-draw", "heloc-repay", "car-daily", "arm", "recast", "no-terms",
         "paid-off")  # fmt: skip
ITEMS = ("metals", "real-estate", "vehicle")
KINDS = BANK + INVESTING + LOANS + ITEMS
SEEN = ("seen", "unseen")
AGES = ("new", "old")
ROUNDING = ("whole", "fractional")
MOVES = ("none", "in", "out")
# Calendar edges (16.4): opened on a month's last day, on a leap day, or valued over a weekend
# (the last close a Friday's, carried forward).
EDGES = ("plain", "month-end", "leap-day", "weekend")
VIEWERS = ("owner", "viewer")

_AXES = {
    "account": {"viewer": VIEWERS, "kind": KINDS, "seen": SEEN, "age": AGES,
                "rounding": ROUNDING, "move": MOVES, "edge": EDGES},
}  # fmt: skip

SEEDS = range(24)

# The account type each kind is made as.
TYPE = {"checking": "checking", "savings": "savings", "brokerage": "brokerage",
        "options": "brokerage", "crypto": "crypto-exchange", "mortgage": "mortgage",
        "heloc-draw": "heloc", "heloc-repay": "heloc", "car-daily": "auto-loan", "arm": "mortgage",
        "recast": "mortgage", "no-terms": "personal-loan", "paid-off": "personal-loan",
        "metals": "precious-metals", "real-estate": "real-estate",
        "vehicle": "vehicle"}  # fmt: skip

FINE = D(".9999")  # every metal item's purity
STOCKS = ("VTI", "AAPL", "MSFT", "BND", "VXUS", "VNQ", "JNJ", "KO")
COINS = ("BTC", "ETH")
UNDERLYINGS = ("SPY", "QQQ", "IWM")


def _impossible(kind: str, a: tuple[str, str], b: tuple[str, str]) -> bool:
    k = {a[0]: a[1], b[0]: b[1]}
    get = k.get
    # The owner sees every account: "unseen" is a viewer's case.
    if get("viewer") == "owner" and get("seen") == "unseen":
        return True
    loan = get("kind") in LOANS
    # A loan's move is a HELOC's draw (in) or a payment beyond the schedule (out); a loan
    # with no terms or paid off has none.
    if get("kind") in ("no-terms", "paid-off") and get("move") not in (None, "none"):
        return True
    if loan and get("kind") not in ("heloc-draw", "heloc-repay") and get("move") == "in":
        return True
    # A new loan of these shapes can't have reset, recast or left its draw period yet.
    if get("kind") in ("arm", "recast", "heloc-repay", "paid-off") and get("age") == "new":
        return True
    # A loan's amounts are cents; fractional is a security's or a metal's shape.
    whole = loan or get("kind") in ("real-estate", "vehicle")
    if whole and get("rounding") == "fractional":
        return True
    # A leap day opened it in 2024: not new.
    if get("edge") == "leap-day" and get("age") == "new":
        return True
    # A weekend's carried close is a priced holding's: an investing account's, which moves.
    return bool(get("edge") == "weekend" and "kind" in k and get("kind") not in INVESTING)


AXES = Axes(_AXES, _impossible)


@dataclass
class Txn:
    day: dt.date
    amount: D
    kind: str = "deposit"
    symbol: str | None = None
    quantity: D | None = None
    price: D | None = None
    # An option's contract: right, strike, expiry, multiplier.
    option: tuple | None = None


@dataclass
class Loan:
    principal: D
    start: dt.date
    months: int
    rate: D
    method: str = "monthly"
    draw_months: int = 0
    resets: list = field(default_factory=list)  # (date, rate)
    recasts: list = field(default_factory=list)  # (date, fee)


@dataclass
class ItemD:
    name: str
    acquired: dt.date
    cost: D
    valuation: str = "valuations"  # "spot", "depreciation", or "valuations" (else its cost)
    metal: str | None = None
    ounces: D | None = None  # fine ounces
    rate: D | None = None  # depreciation a year, %
    valuations: list = field(default_factory=list)  # (date, value)
    sold: dt.date | None = None


@dataclass
class Account:
    name: str
    axes: dict
    txns: list[Txn] = field(default_factory=list)
    loan: Loan | None = None
    items: list[ItemD] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return self.axes["kind"]

    @property
    def type(self) -> str:
        return TYPE[self.kind]


@dataclass
class World:
    seed: int
    viewer: str
    accounts: list[Account]
    # Stored closes by symbol (and an option's contract key), {day: close}; spot by metal.
    closes: dict[str, dict[dt.date, D]] = field(default_factory=dict)
    spot: dict[str, D] = field(default_factory=dict)

    def records(self) -> dict[str, list[dict]]:
        return {"account": [{"viewer": self.viewer, **a.axes} for a in self.accounts]}

    def seen(self) -> list[Account]:
        """The accounts the world's viewer sees in the portfolio."""
        if self.viewer == "owner":
            return list(self.accounts)
        return [a for a in self.accounts if a.axes["seen"] == "seen"]


# ---------- drawing a world ----------


def world(seed: int) -> World:
    """A world drawn from a seed: its viewer alternates; eight accounts' axes are dealt from
    shuffled decks, then made consistent."""
    rnd = random.Random(seed)
    viewer = VIEWERS[seed % 2]
    n = 10
    rows = decks(rnd, {k: v for k, v in _AXES["account"].items() if k != "viewer"}, n)
    # Every kind in turn across the worlds, so each meets every other axis.
    for i, r in enumerate(rows):
        r["kind"] = KINDS[((seed // 2) * n + i) % len(KINDS)]
        if r["kind"] in INVESTING:
            # Few accounts can be valued over a weekend: give them every edge in turn.
            r["edge"] = EDGES[(seed // 2 * 3 + seed % 2 + i) % len(EDGES)]
    w = World(seed, viewer, [])
    for i, axes in enumerate(rows):
        axes = _fit(axes, viewer)
        a = Account(f"{axes['kind'].title()} {i + 1}", axes)
        _fill(w, a, rnd)
        w.accounts.append(a)
    return w


def _fit(axes: dict, viewer: str) -> dict:
    """The dealt axes changed, least first, until no pair of them is impossible."""
    axes = dict(axes)
    if viewer == "owner":
        axes["seen"] = "seen"
    kind = axes["kind"]
    if kind in ("no-terms", "paid-off"):
        axes["move"] = "none"
    elif kind in LOANS and kind not in ("heloc-draw", "heloc-repay") and axes["move"] == "in":
        axes["move"] = "out"
    if kind in ("arm", "recast", "heloc-repay", "paid-off"):
        axes["age"] = "old"
    if kind in (*LOANS, "real-estate", "vehicle"):
        axes["rounding"] = "whole"
    if axes["edge"] == "leap-day" and axes["age"] == "new":
        axes["age"] = "old"
    if axes["edge"] == "weekend" and kind not in INVESTING:
        axes["edge"] = "month-end"
    return axes


def _money(rnd, lo: int, hi: int, fractional: bool = False) -> D:
    cents = rnd.randint(lo * 100, hi * 100)
    return (D(cents) / 100).quantize(CENT)


def _start(a: Account) -> dt.date:
    edge = a.axes["edge"]
    if edge == "leap-day":
        return dt.date(2024, 2, 29)
    if a.axes["age"] == "new":
        return dt.date(2026, 1, 31) if edge == "month-end" else dt.date(2026, 2, 1)
    return dt.date(2021, 3, 31) if edge == "month-end" else dt.date(2021, 3, 1)


def _last_close(a: Account) -> dt.date:
    """The day of a holding's last close: yesterday, or last Friday over a weekend."""
    if a.axes["edge"] == "weekend":
        return TODAY - dt.timedelta(days=(TODAY.weekday() - 4) % 7 or 7)
    return TODAY - dt.timedelta(days=1)


def _fill(w: World, a: Account, rnd: random.Random) -> None:
    start, frac = _start(a), a.axes["rounding"] == "fractional"
    move, last_month = a.axes["move"], TODAY - dt.timedelta(days=12)
    if a.kind in BANK:
        a.txns.append(Txn(start, _money(rnd, 2000, 20000)))
        a.txns.append(Txn(start + dt.timedelta(days=40), -_money(rnd, 50, 900), "withdrawal"))
        if move == "in":
            a.txns.append(Txn(last_month, _money(rnd, 100, 3000)))
        elif move == "out":
            a.txns.append(Txn(last_month, -_money(rnd, 100, 1500), "withdrawal"))
    elif a.kind in ("brokerage", "crypto"):
        a.txns.append(Txn(start, D(50000)))
        pool = COINS if a.kind == "crypto" else STOCKS
        for sym in rnd.sample(pool, 2):
            qty = D(rnd.randint(1, 40)) + (D(rnd.randint(1, 9999)) / 10000 if frac else 0)
            price = D(rnd.randint(30, 400)) + (D(rnd.randint(1, 9999)) / 10000 if frac else 0)
            if a.kind == "crypto":
                # A fraction of a coin: about $3,000 to $40,000 of it.
                qty = (qty / (4000 if sym == "BTC" else 400)).quantize(D("0.00000001"))
                price = price * (300 if sym == "BTC" else 10)
            cost = (qty * price).quantize(CENT, ROUND_HALF_UP)
            a.txns.append(Txn(start + dt.timedelta(days=3), -cost, "buy", sym, qty, price))
            # Most have closes; one in five is valued from its own last trade alone.
            if rnd.random() < 0.8:
                close = (price * D(rnd.randint(70, 160)) / 100).quantize(D("0.0001"))
                w.closes.setdefault(sym, {})[_last_close(a)] = close
        if move == "in":
            a.txns.append(Txn(last_month, _money(rnd, 500, 5000)))
        elif move == "out":
            a.txns.append(Txn(last_month, -_money(rnd, 500, 5000), "withdrawal"))
    elif a.kind == "options":
        a.txns.append(Txn(start, D(80000)))
        under = rnd.choice(UNDERLYINGS)
        expiry = dt.date(2026, 12, 18)
        strike = D(rnd.randint(40, 60)) * 10
        # A long call and a short put, each marked by a close of its own.
        for action, right, premium in (("buy-to-open", "call", D("4.20")),
                                       ("sell-to-open", "put", D("3.10"))):  # fmt: skip
            contracts = D(rnd.randint(1, 3))
            sign = -1 if action == "buy-to-open" else 1
            amount = sign * contracts * premium * 100
            a.txns.append(Txn(start + dt.timedelta(days=5), amount, action, under, contracts,
                              premium, (right, strike, expiry, 100)))  # fmt: skip
            mark = (premium * D(rnd.randint(40, 180)) / 100).quantize(CENT)
            w.closes.setdefault(_occ(under, right, strike, expiry), {})[_last_close(a)] = mark
        if move != "none":
            a.txns.append(Txn(last_month, _money(rnd, 500, 5000) * (1 if move == "in" else -1),
                              "deposit" if move == "in" else "withdrawal"))  # fmt: skip
    elif a.kind in LOANS:
        _loan(a, rnd, start, move, last_month)
    else:
        _items(w, a, rnd, start, move, last_month, frac)


def _occ(under: str, right: str, strike: D, expiry: dt.date) -> str:
    return f"{under} {expiry.strftime('%d%b%y').upper()} {strike.normalize():f} {right[0].upper()}"


def _loan(a: Account, rnd, start: dt.date, move: str, last_month: dt.date) -> None:
    kind = a.kind
    principal = D(rnd.randint(50, 200)) * 1000
    if kind == "car-daily":
        principal = D(rnd.randint(15, 40)) * 1000
    if kind in ("heloc-draw", "heloc-repay"):
        principal = D(0)
    months = 60 if kind == "car-daily" else 360
    rate = D(rnd.choice(("5.875", "6.25", "6.875", "7.125")))
    loan = Loan(principal, start, months, rate)
    if kind == "car-daily":
        loan.method = "daily"
    if kind in ("heloc-draw", "heloc-repay"):
        loan.months, loan.draw_months = 240, 120 if kind == "heloc-draw" else 36
        if kind == "heloc-repay":
            loan.start = dt.date(2022, 9, 1)
    if kind == "arm":
        loan.resets = [(dt.date(2026, 3, 1), rate + D("1.25"))]
    if kind == "recast":
        loan.recasts = [(dt.date(2025, 6, 1), D(250))]
    a.loan = None if kind == "no-terms" else loan
    if kind in ("heloc-draw", "heloc-repay"):
        a.txns.append(Txn(loan.start + dt.timedelta(days=20), -D(rnd.randint(20, 60)) * 1000,
                          "withdrawal"))  # fmt: skip
    # Payments: the last three months', each the schedule's amount or a little more.
    if kind == "paid-off":
        a.loan = Loan(D(3000), dt.date(2025, 1, 1), 12, D(6))
        for m in range(1, 13):
            a.txns.append(Txn(_month(dt.date(2025, 1, 1), m), D("258.20")))
        return
    for back in (3, 2, 1):
        day = _month(TODAY.replace(day=1), -back)
        if day <= (a.loan.start if a.loan else start):
            continue
        a.txns.append(Txn(day, D(rnd.randint(13, 30)) * 100))
    if move == "out" and a.loan:
        a.txns.append(Txn(last_month, D(rnd.randint(5, 50)) * 100))  # an overpayment
    elif move == "in" and kind in ("heloc-draw", "heloc-repay"):
        a.txns.append(Txn(last_month, -D(rnd.randint(2, 9)) * 1000, "withdrawal"))


def _month(day: dt.date, n: int) -> dt.date:
    y, m = divmod(day.year * 12 + day.month - 1 + n, 12)
    return dt.date(y, m + 1, min(day.day, 28))


def _items(w: World, a: Account, rnd, start: dt.date, move: str, last_month: dt.date,
           frac: bool) -> None:  # fmt: skip
    if a.kind == "metals":
        for metal in ("gold", "silver"):
            oz = D(rnd.randint(1, 20)) + (D(rnd.randint(1, 999)) / 1000 if frac else 0)
            a.items.append(ItemD(f"{metal.title()} coins", start, _money(rnd, 500, 20000),
                                 "spot", metal, oz))  # fmt: skip
        w.spot = {"gold": D("2650.40"), "silver": D("31.12")}
    elif a.kind == "real-estate":
        it = ItemD("1428 Elm St", start, D(rnd.randint(300, 900)) * 1000)
        if rnd.random() < 0.7:
            it.valuations.append((TODAY - dt.timedelta(days=60), it.cost + D(25000)))
        a.items.append(it)
    else:
        cost = D(rnd.randint(18, 60)) * 1000
        a.items.append(ItemD("Car", start, cost, "depreciation", rate=D(12)))
    if move == "in":
        a.items.append(ItemD("Added this month", last_month, D(rnd.randint(2, 20)) * 100))
    elif move == "out":
        a.items[0].sold = last_month


# ---------- what each account is worth: the reference ----------


def _cents(x: D) -> D:
    """Money to the cent, half to even, as every figure is (S14.3)."""
    return x.quantize(CENT, rounding=ROUND_HALF_EVEN)


def _interest(x: D) -> D:
    """A loan's interest, half up (S1.9.2)."""
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def price_of(w: World, a: Account, symbol: str, day: dt.date = TODAY) -> D | None:
    """An owner's holding's price (S4): the last stored close on or before the day, else the
    owner's own last trade in it. The decoy's data never counts."""
    closes = [(d, v) for d, v in w.closes.get(symbol, {}).items() if d <= day]
    if closes:
        return max(closes)[1]
    trades = [
        t
        for x in w.accounts
        for t in x.txns
        if t.symbol == symbol and t.price is not None and not t.option and t.day <= day
    ]
    return max(trades, key=lambda t: t.day).price if trades else None


GRACE = dt.timedelta(days=15)  # a servicer's usual grace period (S1.9.3)


def pay_day(loan: Loan, k: int) -> dt.date:
    """The loan's k-th payment day. App convention: the start's day of the month, k months on,
    or that month's last day when it is shorter (a loan started on the 31st)."""
    y, m = divmod(loan.start.year * 12 + loan.start.month - 1 + k, 12)
    m += 1
    last = (dt.date(y + m // 12, m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, min(loan.start.day, last))


def goes_with(loan: Loan, day: dt.date) -> int:
    """The payment day a payment made on this day goes with: the one whose grace it is made in,
    from 15 days after one payment day to 15 days after the next (S1.9.3)."""
    k = 1
    while pay_day(loan, k) + GRACE < day:
        k += 1
    return k


def _rate_on(loan: Loan, day: dt.date) -> D:
    rate = loan.rate
    for d, r in sorted(loan.resets):
        if d <= day:
            rate = r
    return rate


def _level(balance: D, rate: D, n: int) -> D:
    """The monthly payment that pays the balance off in n months. App convention: the
    annuity formula at a twelfth of the yearly rate, half up to the cent (also the payment of
    a loan with daily interest)."""
    r = rate / 100 / 12
    if r == 0:
        return _interest(balance / n)
    return _interest(balance * r / (1 - (1 + r) ** -n))


def _owed(loan: Loan, paid: list[tuple[dt.date, D]], draws: list[tuple[dt.date, D]],
          day: dt.date) -> D:  # fmt: skip
    """The principal (nothing before the start) and the draws, less the principal paid, on a
    day."""
    bal = loan.principal if loan.start <= day else D(0)
    bal += sum((x for d, x in draws if d <= day), D(0))
    bal -= sum((p for d, p in paid if d <= day), D(0))
    return max(bal, D(0))


def _effects(loan: Loan, draws: list[tuple[dt.date, D]] = ()) -> list[int]:
    """The payment days (their numbers) on which the principal and interest due is worked out
    again (S1.9.2): the first after each reset, each recast and each HELOC draw in its
    repayment period, and a HELOC's first repayment day, its draw period's end."""
    out = set()
    late = [(d, x) for d, x in draws
            if loan.draw_months and d >= pay_day(loan, loan.draw_months)]  # fmt: skip
    for c, _ in (*loan.resets, *loan.recasts, *late):
        k = 1
        while pay_day(loan, k) <= c:
            k += 1
        out.add(k)
    if loan.draw_months:
        out.add(loan.draw_months)
    return sorted(out)


def _scheduled(loan: Loan, k: int, bal: D, interest: D, paid: list[tuple[dt.date, D]],
               draws: list[tuple[dt.date, D]]) -> D:  # fmt: skip
    """The principal the schedule has due on payment day k, from what was owed the day before
    (S1.9.1, S1.9.2): none in a HELOC's draw period; else the level payment less the interest.
    The level is the original terms' until a day that works it out again (`_effects`); from
    the latest such day on, the payment that pays what was owed before that day off at its
    rate by the term's last payment day, counting that day, so the end stays; it holds until
    the next. The last payment, or one leaving less than $1, takes what is left."""
    if k < loan.draw_months:
        return D(0)
    e = max((x for x in _effects(loan, draws) if x <= k), default=None)
    if e is None:
        pi = _level(loan.principal, loan.rate, loan.months)
    else:
        day = pay_day(loan, e)
        before = [(d, p) for d, p in paid if d < day]
        then = _owed(loan, before, draws, day - dt.timedelta(days=1))
        pi = _level(then, _rate_on(loan, day), max(1, loan.months - e + 1))
    principal = max(min(pi - interest, bal), D(0))
    if k >= loan.months or bal - principal < 1:
        principal = bal
    return principal


def loan_payments(loan: Loan, txns: list[Txn], today: dt.date = TODAY) -> list[tuple[dt.date, D]]:
    """Each payment's day and principal, in date order, as the loan's Payments setting reads
    them today (S1.9.3). The world sets none: Automatic, which is *Recorded here* once a
    payment is recorded, else *Assumed as scheduled*. Recorded here, the record starts at the
    first payment recorded: every payment day before that payment's own day counts as paid as
    scheduled; a day after it with nothing recorded is missed, which leaves the balance as it
    was. A recorded payment pays the payment day it goes with, or, made after a day missed, the
    oldest missed first (as a servicer applies a late one). Interest is due once per payment
    day (CR3-417): a month's on what was owed before the day's first payment, less what earlier
    payments toward it paid; on a daily-interest loan, the days since the last payment. The
    rest is principal."""
    draws = [(t.day, -t.amount) for t in txns if t.amount < 0]
    made = sorted((t for t in txns if t.amount > 0), key=lambda t: t.day)
    until = pay_day(loan, goes_with(loan, made[0].day)) if made else today
    # (day, recorded first on a day, amount recorded or None, payment day assumed)
    events: list[tuple[dt.date, int, D | None, int]] = [(t.day, 0, t.amount, 0) for t in made]
    k = 1
    while pay_day(loan, k) < min(until, today):
        events.append((pay_day(loan, k), 1, None, k))
        k += 1
    events.sort(key=lambda e: (e[0], e[1]))
    paid: list[tuple[dt.date, D]] = []
    low = k  # recorded here: the oldest payment day not paid since the record started
    taken: set[int] = set()
    due: dict[int, tuple[D, D]] = {}  # a payment day's interest, and what was paid of it
    for day, _, amount, k in events:
        # What was owed before the payment: payments on earlier days, and earlier ones that day.
        bal = max(
            _owed(loan, paid, draws, day - dt.timedelta(days=1))
            - sum((p for d, p in paid if d == day), D(0)),
            D(0),
        )
        rate = _rate_on(loan, day)
        if loan.method == "daily":
            last = paid[-1][0] if paid else loan.start
            interest = _interest(bal * rate / 100 * (day - last).days / 365)
        else:
            interest = _interest(bal * rate / 100 / 12)
        if amount is None:
            if bal <= 0:
                continue  # nothing owed: nothing assumed
            paid.append((day, _scheduled(loan, k, bal, interest, paid, draws)))
            continue
        k = goes_with(loan, day)
        if low < k and pay_day(loan, low) + GRACE < day:
            k = low  # a late payment pays the oldest day missed first
        taken.add(k)
        while low in taken:
            low += 1
        if loan.method != "daily":
            whole, already = due.get(k, (interest, D(0)))
            interest = max(whole - already, D(0))
            due[k] = (whole, already + min(interest, amount))
        # A recorded payment pays its interest first; the rest is principal, up to what is
        # owed.
        paid.append((day, min(max(amount - interest, D(0)), bal)))
    return paid


def owed(loan: Loan, txns: list[Txn], day: dt.date = TODAY) -> D:
    """What is owed on a day: the principal and the draws less the principal of each payment
    up to then, recorded or assumed as today's reading of the Payments setting has them."""
    draws = [(t.day, -t.amount) for t in txns if t.amount < 0]
    return _owed(loan, loan_payments(loan, txns), draws, day)


def item_value(it: ItemD, w: World, day: dt.date = TODAY) -> D:
    """S1.10: nothing before acquired or once sold; a metal at spot; the latest valuation; a
    depreciating item from its cost; else its cost."""
    if day < it.acquired or (it.sold is not None and day >= it.sold):
        return D(0)
    if it.valuation == "spot":
        spot = w.spot.get(it.metal)
        return _cents(it.ounces * FINE * spot) if spot is not None else it.cost
    past = [(d, v) for d, v in it.valuations if d <= day]
    if past:
        return max(past)[1]
    if it.valuation == "depreciation":
        years = D((day - it.acquired).days) / D("365.25")
        return _cents(it.cost * (1 - it.rate / 100) ** years)
    return it.cost


@dataclass
class Part:
    kind: str  # cash, security, option, loan, item
    name: str
    value: D | None


def parts(w: World, a: Account, day: dt.date = TODAY) -> list[Part]:
    """What an account holds, part by part, from the description."""
    if a.kind in LOANS:
        if a.loan is None:
            return [Part("loan", a.name, D(0))]
        return [Part("loan", a.name, -owed(a.loan, a.txns, day))]
    if a.kind in ITEMS:
        return [Part("item", it.name, item_value(it, w, day)) for it in a.items]
    cash = sum((t.amount for t in a.txns if t.day <= day), D(0))
    out = [Part("cash", a.name, cash)]
    held: dict[str, D] = {}
    opts: dict[str, tuple[D, tuple]] = {}
    for t in a.txns:
        if t.day > day or t.symbol is None:
            continue
        if t.option:
            key = _occ(t.symbol, *t.option[:3])
            sign = 1 if t.kind == "buy-to-open" else -1
            q, c = opts.get(key, (D(0), t.option))
            opts[key] = (q + sign * t.quantity, c)
        else:
            held[t.symbol] = held.get(t.symbol, D(0)) + t.quantity
    for sym, qty in held.items():
        p = price_of(w, a, sym, day)
        out.append(Part("security", sym, None if p is None else _cents(qty * p)))
    for key, (qty, contract) in opts.items():
        mark = max(w.closes.get(key, {}).items())[1] if w.closes.get(key) else None
        out.append(Part("option", key, None if mark is None else _cents(qty * mark * contract[3])))
    return out


def value(w: World, a: Account, day: dt.date = TODAY) -> D:
    return sum((p.value or D(0) for p in parts(w, a, day)), D(0))


def left_out(w: World, accounts: list[Account]) -> list[tuple[str, D]]:
    """What a projection built on these accounts leaves out, by name, with its value
    (S6.4.2.2): a loan, an item other than a metal, an account's options together."""
    out = []
    for a in accounts:
        for p in parts(w, a):
            if p.value and p.kind == "loan":
                out.append((p.name, p.value))
        for it in a.items:
            v = item_value(it, w)
            if v and not it.metal:
                out.append((it.name, v))
        opts = [p.value for p in parts(w, a) if p.kind == "option" and p.value]
        if opts:
            n = len(opts)
            out.append((f"{n} option position{'s' if n != 1 else ''}", sum(opts, D(0))))
    return sorted(out)


def flows(w: World, a: Account, first: dt.date, last: dt.date) -> D:
    """The money that came into an account from outside after `first` up to `last` (S5.2.1,
    CR3-28): cash in and out; for a loan, its opening balance owed and its draws out, its
    payments in; for items, one added at its worth then and one sold at what it brought."""

    def within(d: dt.date) -> bool:
        return first < d <= last

    total = D(0)
    if a.kind in LOANS:
        if a.loan is None:
            return total
        if within(a.loan.start):
            total -= a.loan.principal
        return total + sum((t.amount for t in a.txns if within(t.day)), D(0))
    if a.kind in ITEMS:
        for it in a.items:
            if within(it.acquired):
                total += item_value(it, w, it.acquired)
            if it.sold and within(it.sold):
                total -= it.cost  # what its sale brought: the world sells at cost
        return total
    return total + sum(
        (t.amount for t in a.txns if within(t.day) and t.kind in ("deposit", "withdrawal")), D(0)
    )


# ---------- bugs an account world must catch (`test_worlds`) ----------


def _ledger_balance_parts(s, ledger, investing, day=None):
    """CR3-30, CR3-32 put back: every account's parts are its ledger's cash and holdings, a
    loan's payments counted as cash and items left out."""
    from moolakata import valuation

    out = [valuation.Part("cash", ledger.account.name, ledger.balance(day))]
    if investing:
        for p in valuation.positions(s, ledger, day):
            out.append(valuation.Part("security", p.instrumentId, p.value, position=p))
    return out


def _cash_flows_alone(s, ledger, investing, first, last):
    """CR3-28 put back: the ledger's cash in and out the only flows; shares, items and a
    loan's opening moved in count as growth."""
    from moolakata.ledger import performance as perf

    return {d: v for d, v in perf.flows(ledger.transactions).items() if first < d <= last}


PLANTS = [
    (
        Plant(
            "loans and items valued by the ledger",
            "moolakata.valuation:parts",
            _ledger_balance_parts,
            "CR3-30, CR3-32",
        ),
        (0,),
    ),
    (
        Plant(
            "flows from the ledger's cash alone",
            "moolakata.valuation:flows",
            _cash_flows_alone,
            "CR3-28",
        ),
        (2,),
    ),
]
