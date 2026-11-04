"""Lots and gains (requirements S2.2, S2.3): replaying an account's transactions consumes its
lots by the lot method in force at each sale. A holding snapshot from a broker's file is the
holdings of an account kept by snapshots (R3.2), with stand-in lots marked as such; in an
account with trades of its own it is a check, and changes no lot (S1.3.3.8.2)."""

import datetime as dt
from dataclasses import dataclass, field, replace
from decimal import Decimal

ZERO = Decimal(0)
CENT = Decimal("0.01")


@dataclass
class OpenLot:
    lotId: str | None
    instrumentId: str
    acquiredOn: dt.date
    quantity: Decimal
    basis: Decimal | None  # what remains of the cost basis; None while it is missing
    standIn: bool = False  # made from a holding snapshot, not a transaction
    # A wash sale's replacement (S3.8.4): held from the sold shares' purchase, for the term
    # only; the lot is still acquired, and taken in order, by the day it was bought.
    heldFrom: dt.date | None = None
    # Shares moved in whose day bought isn't known: `acquiredOn` is the day they arrived, the
    # term unknown until the day is typed (S2.2, CR3-73).
    acquiredMissing: bool = False

    @property
    def basisMissing(self) -> bool:
        return self.basis is None

    @property
    def unitBasis(self) -> Decimal | None:
        return None if self.basis is None or not self.quantity else self.basis / self.quantity


@dataclass
class Disposal:
    saleId: str | None
    lotId: str | None
    instrumentId: str
    acquiredOn: dt.date
    soldOn: dt.date
    quantity: Decimal
    proceeds: Decimal
    basis: Decimal | None
    method: str
    adjustment: Decimal = ZERO  # a wash sale's disallowed loss, added back (code W, S3.8)
    heldFrom: dt.date | None = None  # a replacement's tacked holding period (S3.8.4)
    written: bool = False  # a written option closed: short-term whatever its days (S3.3)
    standIn: bool = False  # from a lot a snapshot stood in for: when it was bought is unknown
    # From shares moved in whose day bought isn't known: its term is unknown (S2.2, CR3-399).
    acquiredMissing: bool = False
    # Sold without a lot to match (S8.4): when it was bought is missing, as its basis is; its
    # acquiredOn is the sale's day only to place it, never written on a form (CR3-415).
    lotMissing: bool = False

    @property
    def gain(self) -> Decimal | None:
        if self.basis is None:
            return None
        return (self.proceeds - self.basis + self.adjustment).quantize(CENT)

    @property
    def raw_gain(self) -> Decimal | None:
        """The gain before this sale's own wash-sale adjustment."""
        if self.basis is None:
            return None
        return (self.proceeds - self.basis).quantize(CENT)

    @property
    def longTerm(self) -> bool:
        """Held more than a year (S3.1), from the tacked day for a wash sale's replacement; a
        written option's gain is short-term however long it was open (IRC §1234(b), S3.3)."""
        return not self.written and long_term(self.heldFrom or self.acquiredOn, self.soldOn)


def _sold(t, lot: OpenLot, quantity, proceeds, basis, method: str, **kw) -> Disposal:
    """A sale's part from one lot: what is known of the lot (a replacement's held-from day, a
    stand-in, a day bought missing) goes with it."""
    return Disposal(t.id, lot.lotId, t.instrumentId, lot.acquiredOn, t.date, quantity, proceeds,
                    basis, method, heldFrom=lot.heldFrom, standIn=lot.standIn,
                    acquiredMissing=lot.acquiredMissing, **kw)  # fmt: skip


def long_term(acquired: dt.date, sold: dt.date) -> bool:
    """Held more than a year: sold after the anniversary of the day acquired (S3.1), the one
    rule for every holding period, shares, coins, items and donations alike."""
    try:
        anniversary = acquired.replace(year=acquired.year + 1)
    except ValueError:  # 29 February
        anniversary = acquired.replace(year=acquired.year + 1, day=28)
    return sold > anniversary


@dataclass
class Problem:
    """Missing or doubtful data (S8.4): a sale without a lot, a snapshot that explains a gap."""

    kind: str
    instrumentId: str
    date: dt.date
    transactionId: str | None
    quantity: Decimal


@dataclass
class Replay:
    open: list[OpenLot] = field(default_factory=list)
    disposals: list[Disposal] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    # Lots an adjusted contract gave up, waiting for its new contract (S3.10).
    carried: dict = field(default_factory=dict)
    # What each transfer out took with it: (acquired, quantity, basis), by transaction, so a
    # matched transfer in can open the same lots (S1.7.1).
    moved: dict = field(default_factory=dict)
    # An assignment's or exercise's stock trades, by the option's end, and the premium each
    # takes into its basis or proceeds once the end is replayed (S3.4); None while the
    # option's basis is missing.
    legs: dict = field(default_factory=dict)
    premium: dict = field(default_factory=dict)
    leg_ids: set = field(default_factory=set)
    # Corporate actions: the old legs a new leg follows, and a merger's cash by its old leg.
    paired: set = field(default_factory=set)
    cash: dict = field(default_factory=dict)

    def quantity(self, instrument_id: str) -> Decimal:
        # An empty sum's int 0 equals Decimal 0 in every caller's comparison, arithmetic and text.
        return sum(
            (lot.quantity for lot in self.open if lot.instrumentId == instrument_id),
            ZERO,
        )  # pragma: no mutate

    def positions(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for lot in self.open:
            out[lot.instrumentId] = out.get(lot.instrumentId, ZERO) + lot.quantity
        return {k: v for k, v in out.items() if v}


def _order(method: str, lots: list[OpenLot]) -> list[OpenLot]:
    if method == "lifo":
        return sorted(lots, key=lambda x: x.acquiredOn, reverse=True)
    if method == "hifo":
        return sorted(lots, key=lambda x: (x.unitBasis is None, -(x.unitBasis or ZERO)))
    return sorted(lots, key=lambda x: x.acquiredOn)


def _take(lot: OpenLot, qty: Decimal) -> Decimal | None:
    """Take qty from a lot; returns the basis that goes with it."""
    if lot.basis is None:
        lot.quantity -= qty
        return None
    if qty == lot.quantity:
        basis, lot.basis = lot.basis, ZERO
    else:
        basis = (lot.basis * qty / lot.quantity).quantize(CENT)
        lot.basis -= basis
    lot.quantity -= qty
    return basis


def kept_by_snapshots(transactions: list) -> bool:
    """No trades of its own: no transaction that makes or takes away a lot (every lot is made
    by one, S2.2)."""
    return not any(t.instrumentId and t.kind in TRADES for t in transactions)


# What average cost applies to (S2.3): fund shares and coins.
AVERAGED = ("mutual-fund", "money-market", "crypto")


def replay(
    account_method: str,
    transactions: list,
    lots: list,
    picks: list,
    snapshots: list,
    washes: list = (),
    by_snapshots: bool | None = None,
    basis_added: bool = True,
    averaged: frozenset = frozenset(),
    sale_at: dict | None = None,
    carried_in: dict | None = None,
) -> Replay:
    """Transactions, lots (acquisitions), specific-identification picks and holding
    snapshots of one account, as entities; returns the open lots, disposals and problems.
    The snapshots count only for an account kept by them (`by_snapshots`, worked out from
    the transactions and lots when not given)."""
    if by_snapshots is None:
        by_snapshots = kept_by_snapshots(transactions)
    if not by_snapshots:
        snapshots = []
    lots_by_txn: dict[str, list] = {}
    for lot in lots:
        if not lot.transactionId:
            raise ValueError(f"lot {lot.id} has no transaction: every lot is made by one (S2.2)")
        lots_by_txn.setdefault(lot.transactionId, []).append(lot)
    picks_by_sale: dict[str, list] = {}
    for p in picks:
        picks_by_sale.setdefault(p.saleId, []).append(p)

    events: list[tuple] = []
    ends = {t.id for t in transactions if t.kind in ("assign", "exercise")}
    for t in transactions:
        # An assignment's stock trades come after it on its day, to take its premium; the new
        # leg of a pair that moves lots, after the old one.
        leg = getattr(t, "optionTransactionId", None) in ends or (
            t.kind in (*CORPORATE, "option-adjust") and getattr(t, "transferId", None)
        )
        events.append((t.date, 1 if leg else 0, t.createdAt, t.id, "txn", t))
    for h in snapshots:
        events.append((h.asOf, 2, h.createdAt, h.id, "snapshot", h))  # at the day's end
    # A wash sale settles on its replacement right after the loss sale (CR3-388): a replacement
    # bought before it is a plain lot until then, so the sale never picks its own lots by the
    # loss it is about to have disallowed. `sale_at` is each sale's day and making, from any
    # account; a sale not in it settles at the buy.
    for w in washes:
        at = (sale_at or {}).get(w.saleId)
        if at is not None:
            events.append((at[0], 0, at[1], f"{w.saleId}~{w.id}", "settle", w))
    # Ids are unique, so the first four decide: no sort key changes the order.
    events.sort(key=lambda e: e[:4])  # pragma: no mutate

    replaced: dict[str, list] = {}
    for w in washes:
        replaced.setdefault(w.replacementId, []).append(w)
    pending: dict[str, OpenLot] = {}  # a replacement's split, waiting for its sale
    settled: set[str] = set()  # wash sales whose sale has been passed
    out = Replay()
    for t in transactions:
        end = getattr(t, "optionTransactionId", None)
        if end and t.kind in ("buy", "sell"):
            out.legs.setdefault(end, []).append(t)
            if end in ends:
                out.leg_ids.add(t.id)
        if t.kind in CORPORATE and t.transferId:
            out.paired.add(t.transferId)
    for _, _, _, _, what, obj in events:
        if what == "snapshot":
            _snapshot(out, obj)
        elif what == "settle":
            settled.add(obj.id)
            lot = pending.pop(obj.id, None)
            if lot is not None:
                _settle(lot, obj, basis_added)
        elif carried_in and obj.kind == "transfer-in" and obj.id in carried_in:
            # A pair from another account: the lots its transfer out took, whole (CR3-73).
            for lot in carried_in[obj.id]:
                out.open.append(replace(lot, lotId=None, instrumentId=obj.instrumentId))
        else:
            before = len(out.open)
            _transaction(
                out,
                obj,
                account_method,
                lots_by_txn.get(obj.id, []),
                picks_by_sale.get(obj.id, []),
                averaged,
            )
            if obj.id in replaced:
                rows = replaced[obj.id]
                for row, lot in _replacement(out, before, rows):
                    if sale_at is None or row.saleId not in sale_at or row.id in settled:
                        _settle(lot, row, basis_added)
                    else:
                        pending[row.id] = lot
    _disallow(out, washes)
    out.open = [lot for lot in out.open if lot.quantity]
    return out


def adds_basis(account_type: str) -> bool:
    """Whether a wash sale's replacement in this account takes the disallowed loss into its
    basis: not in an IRA or a Roth IRA, where it is lost for good (S3.8.3, Rev. Rul.
    2008-5)."""
    return account_type not in ("ira", "roth-ira")


def _replacement(out: Replay, before: int, rows: list) -> list[tuple]:
    """A wash sale's replacement (S3.8): the shares bought that replace, split from the rest of
    the lot, each with the wash sale it settles; their basis and day follow on `_settle`."""
    made = out.open[before:]
    split = []
    for row in rows:
        left = row.quantity
        for lot in made:
            # `left` is 0 here only for a wash sale of no shares: its part of none is dropped.
            if left <= 0 or lot.quantity <= 0:  # pragma: no mutate
                continue
            take = min(left, lot.quantity)
            # Never read again: the loop breaks right after.
            left -= take  # pragma: no mutate
            share = None
            if lot.basis is not None:
                share = (lot.basis * take / lot.quantity).quantize(CENT)
                lot.basis -= share
            lot.quantity -= take
            part = replace(lot, quantity=take, basis=share)
            out.open.append(part)
            split.append((row, part))
            break
    return split


def _settle(lot: OpenLot, row, basis_added: bool) -> None:
    """The replacement takes the disallowed loss into its basis (for what of it is still held)
    and the sold shares' holding period. In an IRA or a Roth IRA the loss is disallowed for
    good, and no basis is added (S3.8.3)."""
    # A part with no shares left would take a share of 0, and is dropped at the end anyway.
    if lot.basis is not None and basis_added and lot.quantity > 0:  # pragma: no mutate
        share = row.disallowed
        if lot.quantity != row.quantity:
            share = (row.disallowed * lot.quantity / row.quantity).quantize(CENT)
        lot.basis += share
    lot.heldFrom = row.heldFrom


def _disallow(out: Replay, washes) -> None:
    """A loss sale's disallowed part, on the disposals of the sold lot whose loss it is
    (CR3-390): spread by loss over that lot's losing parts (a lot a wash sale split may sell
    in two), or over the sale's when the wash sale names no lot."""
    by: dict[tuple[str, str | None], Decimal] = {}
    for w in washes:
        key = (w.saleId, getattr(w, "lotId", None))
        by[key] = by.get(key, ZERO) + w.disallowed
    for (sale, lot_id), amount in by.items():
        losing = [
            d
            for d in out.disposals
            if d.saleId == sale
            and (lot_id is None or d.lotId == lot_id)
            and (d.raw_gain or ZERO) < 0
        ]
        total = -sum((d.raw_gain for d in losing), ZERO)
        given = ZERO
        for i, d in enumerate(losing):
            part = (
                amount - given
                if i == len(losing) - 1
                else (amount * -d.raw_gain / total).quantize(CENT)
            )
            d.adjustment += part
            given += part


def _transaction(
    out: Replay, t, account_method: str, made: list, picks: list, averaged: frozenset = frozenset()
) -> None:
    if not t.instrumentId:
        return
    if t.kind in OPTION_TRADES:
        _option(out, t)
        return
    if t.kind == "option-adjust":
        _adjust(out, t)
        return
    if t.kind in CORPORATE:
        _corporate(out, t)
        return
    if t.kind in ("buy", "reinvest", "transfer-in", "reward"):
        if made:
            for lot in made:
                out.open.append(
                    OpenLot(
                        lot.id,
                        lot.instrumentId,
                        lot.acquiredOn,
                        lot.quantity,
                        None if lot.basisMissing else lot.costBasis,
                        acquiredMissing=bool(getattr(lot, "acquiredMissing", False)),
                    )
                )
            if t.id in out.premium:
                # A long call's premium adds to the shares' basis; a short put's credit comes
                # off it (S3.4). The stock trade's lots are the last ones made.
                prem = out.premium.pop(t.id)
                for lot in out.open[-len(made) :]:
                    share = (
                        None if prem is None else (prem * lot.quantity / t.quantity).quantize(CENT)
                    )
                    lot.basis = None if share is None or lot.basis is None else lot.basis + share
        elif t.quantity:
            basis = -t.amount if t.kind != "transfer-in" and t.amount else None
            if t.kind == "reward":
                basis = (t.quantity * t.price).quantize(CENT) if t.price else None
            out.open.append(OpenLot(None, t.instrumentId, t.date, t.quantity, basis))
        if t.kind == "buy":
            _cover_short_stock(out, t, len(made) if made else 1)
    elif t.kind in ("sell", "transfer-out"):
        qty = abs(t.quantity or ZERO)
        if not qty:
            return
        # Lots picked make the sale specific identification, whatever the method (S2.3).
        method = "specific" if picks else (t.lotMethod or account_method)
        if method == "average" and t.instrumentId not in averaged:
            method = "fifo"  # average cost is for funds and coins; a share goes first in (S2.3)
        proceeds = (
            t.amount + (getattr(t, "proceedsAdjustment", None) or ZERO)
            if t.kind == "sell"
            else ZERO
        )
        # A short call's credit adds to the proceeds; a long put's premium comes off them.
        proceeds -= out.premium.pop(t.id, None) or ZERO
        _consume(out, t, qty, method, proceeds, realize=t.kind == "sell", picks=picks)
    elif t.kind == "split" and t.splitRatio:
        for lot in out.open:
            if lot.instrumentId == t.instrumentId:
                lot.quantity *= t.splitRatio
    elif t.kind == "return-of-capital":
        _return_of_capital(out, t)


def _return_of_capital(out: Replay, t) -> None:
    """Spread over every lot held, by quantity (S2.4), the last taking what rounding leaves. A
    lot without a basis keeps its share, which applies once its basis is entered (the replay
    works it out again); what exceeds a lot's basis is a capital gain, held as long as the lot
    (IRS Pub. 550, nondividend distributions)."""
    held = [x for x in out.open if x.instrumentId == t.instrumentId and x.quantity > 0]
    # An empty sum's int 0 is only tested for truth; a sum of lots is a Decimal either way.
    total = sum((x.quantity for x in held), ZERO)  # pragma: no mutate
    amount = abs(t.amount or ZERO)
    if not total or not amount:
        return
    given = ZERO
    for i, lot in enumerate(held):
        cut = (
            amount - given if i == len(held) - 1 else (amount * lot.quantity / total).quantize(CENT)
        )
        given += cut
        if lot.basis is None:
            continue
        excess = cut - lot.basis
        lot.basis = max(ZERO, lot.basis - cut)
        if excess > 0:
            out.disposals.append(_sold(t, lot, ZERO, excess, ZERO, "return-of-capital"))


def _adjust(out: Replay, t) -> None:
    """An adjusted contract (S3.10): the old contract's lots leave with no sale, and open on
    the new one with their days held and their whole basis, the contracts times the ratio."""
    if t.splitRatio is None:
        gone = [lot for lot in out.open if lot.instrumentId == t.instrumentId]
        out.open = [lot for lot in out.open if lot.instrumentId != t.instrumentId]
        out.carried[t.id] = gone
        return
    for lot in out.carried.pop(t.transferId, []):
        out.open.append(
            replace(lot, instrumentId=t.instrumentId, quantity=lot.quantity * t.splitRatio)
        )


# Corporate actions (S2.4) that move lots between instruments, each a pair of transactions
# linked by transferId: the old instrument's, then the new one's with its ratio.
CORPORATE = ("symbol-change", "spin-off", "merger")


def _corporate(out: Replay, t) -> None:
    """A symbol change carries the lots whole; a spin-off moves the share of each lot's basis
    the old leg names (its splitRatio) to new shares, the parent's kept; a merger carries the
    lots to the acquirer at its ratio, any cash it paid (the old leg's amount) a gain only as
    far as it and the gain go (IRC §356), and all cash a sale. Days held carry over."""
    # A lot of no shares carries nothing: its copy has no shares, boot or gain, and is dropped.
    # pragma: no mutate start
    held = [x for x in out.open if x.instrumentId == t.instrumentId and x.quantity > 0]
    # pragma: no mutate end
    if t.transferId is None:
        if t.kind == "spin-off":
            f = t.splitRatio or ZERO
            moved = []
            for lot in held:
                part = None if lot.basis is None else (lot.basis * f).quantize(CENT)
                if part is not None:
                    lot.basis -= part
                # The new leg sets each carried lot's instrument; the one kept here is never read.
                # pragma: no mutate start
                moved.append(replace(lot, instrumentId=t.instrumentId, basis=part))
                # pragma: no mutate end
            out.carried[t.id] = moved
            return
        if t.kind == "merger" and t.id not in out.paired:
            # An empty sum's int 0 is only tested for truth.
            qty = sum((x.quantity for x in held), ZERO)  # pragma: no mutate
            if qty:
                _consume(out, t, qty, "fifo", t.amount, realize=True)
            return
        out.open = [x for x in out.open if x not in held]
        out.carried[t.id] = held
        out.cash[t.id] = t.amount if t.kind == "merger" else ZERO
        return
    lots = out.carried.pop(t.transferId, [])
    # None and ZERO are both no cash: it is only tested for truth.
    cash = out.cash.pop(t.transferId, ZERO)  # pragma: no mutate
    ratio = t.splitRatio or Decimal(1)
    # An empty sum's int 0 is only tested for truth, with no lots to spread over.
    total = sum((x.quantity for x in lots), ZERO)  # pragma: no mutate
    for lot in lots:
        basis = lot.basis
        if cash and total and basis is not None:
            boot = (cash * lot.quantity / total).quantize(CENT)
            value = (lot.quantity * ratio * (t.price or ZERO)).quantize(CENT)
            recognized = max(ZERO, min(boot, boot + value - basis))
            basis = basis - boot + recognized
            if recognized:
                out.disposals.append(_sold(t, lot, ZERO, recognized, ZERO, "merger"))
        out.open.append(
            replace(lot, instrumentId=t.instrumentId, quantity=lot.quantity * ratio, basis=basis)
        )


# What consumes lots by a method: the method in force when it was made is recorded on it
# (S2.3), so a later change of the account's method leaves it as it was.
DISPOSALS = ("sell", "transfer-out")
# The lot methods (S2.3), as the account's column allows them.
METHODS = ("fifo", "lifo", "hifo", "specific", "average")


# Option trades (S3.2, S3.3): a long contract is a lot like a share's; a short one is a
# negative lot whose basis is the credit received, negative; closing or expiry realizes it.
OPTION_TRADES = (
    "buy-to-open",
    "sell-to-open",
    "buy-to-close",
    "sell-to-close",
    "expire",
    "assign",
    "exercise",
)

# What makes or takes away a lot (kept_by_snapshots): an account with none of these, and no
# lot typed on its own, is kept by snapshots (R3.2). Income and fees on an instrument (a cash
# dividend, interest, a distribution) and what only changes the lots there are (a split, a
# corporate action) aren't.
TRADES = ("buy", "sell", "reinvest", "transfer-in", "transfer-out", "reward", *OPTION_TRADES)


def _option(out: Replay, t) -> None:
    qty = abs(t.quantity or ZERO)
    if not qty:
        return
    if t.kind == "buy-to-open":
        out.open.append(OpenLot(None, t.instrumentId, t.date, qty, -t.amount))
    elif t.kind == "sell-to-open":
        out.open.append(OpenLot(None, t.instrumentId, t.date, -qty, -t.amount))
    elif t.kind == "sell-to-close":
        _consume(out, t, qty, "fifo", t.amount, realize=True)
    elif t.kind == "buy-to-close":
        _cover(out, t, qty, t.amount)
    elif t.kind in ("assign", "exercise"):
        # The contract ends without a gain of its own: its premium goes into the stock's basis
        # or proceeds, on the stock trades made with it (S3.4), worked out here so an edit to
        # the opening trade follows through.
        left = qty
        premium: Decimal | None = ZERO
        for lot in sorted(
            (x for x in out.open if x.instrumentId == t.instrumentId and x.quantity),
            key=lambda x: x.acquiredOn,
        ):
            if left <= 0:
                break
            take = min(left, abs(lot.quantity))
            if lot.basis is None:
                premium = None
            else:
                part = (lot.basis * take / abs(lot.quantity)).quantize(CENT)
                lot.basis -= part
                premium = None if premium is None else premium + part
            # No lot here is at 0 (the filter above, each seen once): `< 0` and `<= 0` agree.
            lot.quantity += take if lot.quantity < 0 else -take  # pragma: no mutate
            left -= take
        _spread_premium(out, t.id, premium)
    elif t.kind == "expire":
        # Worthless: what is left of the long lots is lost; the short lots keep their credit.
        # A lot of none adds nothing to the sum, and an empty sum's 0 is only tested for truth.
        # pragma: no mutate start
        longs = sum(
            (x.quantity for x in out.open if x.instrumentId == t.instrumentId and x.quantity > 0),
            ZERO,
        )
        # pragma: no mutate end
        if longs:
            _consume(out, t, min(qty, longs), "fifo", ZERO, realize=True)
        else:
            _cover(out, t, qty, ZERO)


def _spread_premium(out: Replay, end_id: str, premium: Decimal | None) -> None:
    """The premium over the end's stock trades, by their cash (S3.10.4); the last takes what
    rounding leaves."""
    legs = out.legs.get(end_id, [])
    # An empty sum's int 0 is only tested for truth.
    total = sum((abs(x.amount) for x in legs), ZERO)  # pragma: no mutate
    given = ZERO
    for i, leg in enumerate(legs):
        if premium is None:
            out.premium[leg.id] = None
            continue
        last = i == len(legs) - 1
        share = (
            premium - given
            if last or not total
            else (premium * abs(leg.amount) / total).quantize(CENT)
        )
        given += share
        out.premium[leg.id] = share


def _cover_short_stock(out: Replay, t, n_made: int) -> None:
    """Shares bought while the account is short them (from an assignment or exercise with
    none held, S3.4) close the short first; the rest stay long. The lots just made are the
    last ones open."""
    short = -sum(
        (x.quantity for x in out.open if x.instrumentId == t.instrumentId and x.quantity < 0),
        ZERO,
    )
    qty = abs(t.quantity or ZERO)
    cover = min(short, qty)
    if cover <= 0:
        return
    _cover(out, t, cover, (t.amount * cover / qty).quantize(CENT))
    left = cover
    for lot in out.open[-n_made:]:
        if left <= 0 or lot.quantity <= 0:
            continue
        take = min(left, lot.quantity)
        _take(lot, take)
        left -= take


def _cover(out: Replay, t, qty: Decimal, proceeds: Decimal) -> None:
    """Close short lots, oldest first: each realizes its credit less the share of the cost to
    close (proceeds, negative or zero)."""
    shorts = sorted(
        (x for x in out.open if x.instrumentId == t.instrumentId and x.quantity < 0),
        key=lambda x: x.acquiredOn,
    )
    left, allotted = qty, ZERO
    for lot in shorts:
        if left <= 0:
            # A return here skips only the check below, false once `left` is used up.
            break  # pragma: no mutate
        take = min(left, -lot.quantity)
        left -= take
        last = left <= 0
        share = proceeds - allotted if last else (proceeds * take / qty).quantize(CENT)
        allotted += share
        basis = None
        if lot.basis is not None:
            basis = (lot.basis * take / -lot.quantity).quantize(CENT)
            lot.basis -= basis
        lot.quantity += take
        out.disposals.append(_sold(t, lot, take, share, basis, "fifo", written=True))
    if left > 0:
        out.problems.append(Problem("close-without-open", t.instrumentId, t.date, t.id, left))


def _consume(
    out: Replay, t, qty: Decimal, method: str, proceeds: Decimal, *, realize: bool, picks=()
) -> None:
    """Take a sale's quantity from the open lots: the picked lots for specific
    identification, else in the method's order; average cost pools the basis (S2.3). A
    method not known is refused, never taken for first in (R3.11); picks count only for a
    sale, the only trade that has them."""
    if method not in METHODS:
        raise ValueError(f"lot method {method!r} is none of {', '.join(METHODS)}")
    held = [lot for lot in out.open if lot.instrumentId == t.instrumentId and lot.quantity > 0]
    total, left = qty, qty
    plan: list[tuple[OpenLot, Decimal]] = []
    if method == "specific" and picks:
        # A picked lot is every part of it: one a wash sale split takes from its parts in turn
        # (CR3-26), never from another lot.
        for p in picks:
            want = p.quantity
            for lot in (x for x in held if x.lotId == p.lotId):
                take = min(want, lot.quantity, left)
                if take > 0:
                    plan.append((lot, take))
                    left -= take
                    want -= take
    order = method if method in ("fifo", "lifo", "hifo") else "fifo"
    for lot in _order(order, held):
        if left <= 0:
            break
        room = lot.quantity - sum((q for p, q in plan if p is lot), ZERO)
        take = min(left, room)
        if take > 0:
            plan.append((lot, take))
            left -= take
    if method == "average" and held and all(lot.basis is not None for lot in held):
        # Average cost (S2.3): at each sale every share held is re-based to the pool's average,
        # so later sales take the same average, however the earlier ones fell.
        pool = sum((lot.quantity for lot in held), ZERO)
        whole = sum((lot.basis for lot in held), ZERO)
        given = ZERO
        for i, lot in enumerate(held):
            if i == len(held) - 1:
                lot.basis = whole - given
            else:
                lot.basis = (whole * lot.quantity / pool).quantize(CENT)
                given += lot.basis
    used = (
        method
        if method in ("fifo", "lifo", "hifo", "average")
        else ("specific" if picks else "fifo")
    )
    allotted = ZERO
    for i, (lot, take) in enumerate(plan):
        last = i == len(plan) - 1 and left <= 0
        share = proceeds - allotted if last else (proceeds * take / total).quantize(CENT)
        allotted += share
        basis = _take(lot, take)
        if not realize:
            # What a transfer out takes, whole: its day, basis, holding period and whether it
            # stood in for a snapshot, so its pair carries them (CR3-73).
            out.moved.setdefault(t.id, []).append(
                replace(lot, lotId=None, quantity=take, basis=basis)
            )
        if realize:
            out.disposals.append(_sold(t, lot, take, share, basis, used))
    if left > 0 and realize and t.id in out.leg_ids:
        # Assigned a call, or a put exercised, with no shares held: a short sale at the
        # strike, its credit the basis of a short stock lot (S3.4).
        out.open.append(OpenLot(None, t.instrumentId, t.date, -left, -(proceeds - allotted)))
    elif left > 0:
        _unmatched(out, t, left, proceeds - allotted, realize, used)


def _unmatched(out: Replay, t, qty: Decimal, proceeds: Decimal, realize: bool, method: str) -> None:
    """More sold than held: a sale without a matching lot (S8.4)."""
    out.problems.append(Problem("sale-without-lot", t.instrumentId, t.date, t.id, qty))
    if realize:
        out.disposals.append(
            Disposal(
                t.id,
                None,
                t.instrumentId,
                t.date,
                t.date,
                qty,
                proceeds.quantize(CENT),
                None,
                method,
                lotMissing=True,
            )
        )


def _snapshot(out: Replay, h) -> None:
    """A broker's file says how much is held on a day; what the transactions can't explain
    becomes a stand-in lot with its basis missing, or is taken away."""
    have = out.quantity(h.instrumentId)
    delta = h.quantity - have
    if delta > 0:
        out.open.append(OpenLot(None, h.instrumentId, h.asOf, delta, None, standIn=True))
        out.problems.append(Problem("history-missing", h.instrumentId, h.asOf, None, delta))
    elif delta < 0:
        qty = -delta
        # _order goes first in for any method but lifo and hifo.
        for lot in _order("fifo", [
            x for x in out.open if x.instrumentId == h.instrumentId
        ]):  # pragma: no mutate  # fmt: skip
            if qty <= 0:
                break
            take = min(qty, lot.quantity)
            _take(lot, take)
            qty -= take
        out.problems.append(Problem("history-missing", h.instrumentId, h.asOf, None, delta))
