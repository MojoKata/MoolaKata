"""Physical assets (requirements S1.10): what an item is worth on a day (at spot, from its
valuations, or depreciated), its cost basis with improvements, a sale's gain, and an account's
items in total, over time."""

import datetime as dt
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import valuation
from ..store.entities.accounts import Account, Instrument
from ..store.entities.assets import Improvement, Item, ItemValuation
from ..store.repos import ledger as repo

TYPES = ("precious-metals", "collectables", "real-estate", "vehicle", "other-asset")
ZERO = Decimal(0)
CENT = Decimal("0.01")
METAL_SYMBOLS = {"gold": "XAU", "silver": "XAG", "platinum": "XPT", "palladium": "XPD"}
METAL_NAMES = {
    "gold": "Gold spot",
    "silver": "Silver spot",
    "platinum": "Platinum spot",
    "palladium": "Palladium spot",
}
# Troy ounces in one of each unit.
OUNCES = {
    "ozt": Decimal(1),
    "g": Decimal(1) / Decimal("31.1034768"),
    "kg": Decimal(1000) / Decimal("31.1034768"),
}
STALE_DAYS = 365  # a valuation older than 12 months is marked stale


def is_physical(account_type: str) -> bool:
    return account_type in TYPES


def parse_purity(text: str) -> Decimal:
    """'.9999', '0.925', '99.99%' or '22k' as a fraction; ValueError when it is none."""
    try:
        return _purity(text)
    except InvalidOperation as e:
        raise ValueError("not a purity") from e


def _purity(text: str) -> Decimal:
    t = text.strip().lower().replace(" ", "")
    if t.endswith("k"):
        k = Decimal(t[:-1])
        if not 0 < k <= 24:
            raise ValueError("karats are 1 to 24")
        return (k / 24).quantize(Decimal("0.0001"))
    if t.endswith("%"):
        v = Decimal(t[:-1]) / 100
    else:
        v = Decimal(t)
        if v > 1:
            v = v / 1000 if v > 100 else v / 100  # 999.9 fine, or 99.99
    if not 0 < v <= 1:
        raise ValueError("a purity up to 1")
    return v


def fine_ounces(item: Item) -> Decimal:
    if item.unitWeight is None or item.purity is None or item.weightUnit is None:
        return ZERO
    return item.unitWeight * OUNCES[item.weightUnit] * item.purity * item.quantity


def metal_instrument(s: Session, metal: str) -> Instrument:
    return repo.instrument(s, METAL_SYMBOLS[metal], METAL_NAMES[metal], "metal")


@dataclass
class Detail:
    """What an item's value rests on: its valuations and improvements, oldest first."""

    valuations: list[ItemValuation]
    improvements: list[Improvement]


def details(s: Session, items: list[Item]) -> dict[str, Detail]:
    ids = [i.id for i in items]
    out = {i: Detail([], []) for i in ids}
    if not ids:
        return out
    for v in s.scalars(
        select(ItemValuation)
        .where(ItemValuation.itemId.in_(ids), ItemValuation.deleted == false())
        .order_by(ItemValuation.date, ItemValuation.createdAt)
    ):
        out[v.itemId].valuations.append(v)
    for m in s.scalars(
        select(Improvement)
        .where(Improvement.itemId.in_(ids), Improvement.deleted == false())
        .order_by(Improvement.date)
    ):
        out[m.itemId].improvements.append(m)
    return out


def items_of(s: Session, account: Account) -> list[Item]:
    return list(
        s.scalars(
            select(Item)
            .where(Item.accountId == account.id, Item.deleted == false())
            .order_by(Item.acquiredOn, Item.name)
        )
    )


def basis(item: Item, d: Detail, day: dt.date | None = None) -> Decimal:
    """Cost basis: the cost, a property's closing costs, and improvements made by the day."""
    return (
        item.costBasis
        + (item.closingCosts or ZERO)
        + sum((m.amount for m in d.improvements if day is None or m.date <= day), ZERO)
    )


def latest_valuation(d: Detail, day: dt.date) -> ItemValuation | None:
    return next((v for v in reversed(d.valuations) if v.date <= day), None)


def value_on(item: Item, d: Detail, day: dt.date, spot: Decimal | None) -> Decimal:
    """What the item is worth on the day: nothing before it was acquired or once sold."""
    if day < item.acquiredOn or (item.soldOn is not None and day >= item.soldOn):
        return ZERO
    if item.valuation == "spot":
        if spot is None:
            return basis(item, d, day)
        return (fine_ounces(item) * spot * (1 + item.sellPremium / 100)).quantize(CENT)
    v = latest_valuation(d, day)
    if v is not None:
        return v.value
    if item.valuation == "depreciation" and item.depreciationRate:
        years = Decimal((day - item.acquiredOn).days) / Decimal("365.25")
        # A decimal power, to 34 digits: no amount passes through a float (S14.3).
        factor = max(1 - item.depreciationRate / 100, Decimal(0)) ** years
        return (item.costBasis * factor).quantize(CENT)
    return basis(item, d, day)


def is_stale(item: Item, d: Detail, day: dt.date) -> bool:
    """A value from a valuation over a year old (S1.10.2)."""
    if item.valuation == "spot" or item.soldOn is not None:
        return False
    v = latest_valuation(d, day)
    return v is not None and (day - v.date).days > STALE_DAYS


def gain(item: Item, d: Detail) -> Decimal | None:
    """A sale's realized gain or loss: proceeds less fees, less the cost basis."""
    if item.soldOn is None or item.proceeds is None:
        return None
    return item.proceeds - (item.saleFees or ZERO) - basis(item, d, item.soldOn)


def is_collectable(account_type: str, item: Item) -> bool:
    """Taxed at the collectables rate: metals and collectables (S1.10.5)."""
    return account_type in ("precious-metals", "collectables") or item.valuation == "spot"


def find_metal(s: Session, metal: str) -> Instrument | None:
    """The metal's spot instrument, made when an item of it was saved."""
    return s.scalars(
        select(Instrument).where(
            Instrument.symbol == METAL_SYMBOLS[metal], Instrument.deleted == false()
        )
    ).first()


def _spot_ids(s: Session, items: list[Item]) -> dict[str, str]:
    metals = {i.metal for i in items if i.valuation == "spot" and i.metal}
    found = {m: find_metal(s, m) for m in metals}
    return {m: inst.id for m, inst in found.items() if inst is not None}


def spots(s: Session, items: list[Item], day: dt.date) -> dict[str, valuation.Price]:
    """Each metal's spot on the day, by metal."""
    ids = _spot_ids(s, items)
    got = valuation.prices(s, list(ids.values()), day)
    return {m: got[iid] for m, iid in ids.items() if iid in got}


def worth(s: Session, account: Account, day: dt.date | None = None) -> list[tuple[Item, Decimal]]:
    """Each of the account's items with what it is worth on the day."""
    from .. import clock

    day = day or clock.today()
    items = items_of(s, account)
    ds = details(s, items)
    sp = spots(s, items, day)
    return [
        (i, value_on(i, ds[i.id], day, sp[i.metal].price if i.metal in sp else None)) for i in items
    ]


def value(s: Session, account: Account, day: dt.date | None = None) -> Decimal:
    return sum((v for _, v in worth(s, account, day)), ZERO)


def series(
    s: Session,
    account: Account,
    first: dt.date,
    last: dt.date,
    step_days: int = 1,
    only: Callable[[Item], bool] | None = None,
) -> list[tuple[dt.date, Decimal]]:
    """The items' total value each day (or every step_days), spot carried forward; with
    `only`, of the items it keeps."""
    items = [i for i in items_of(s, account) if only is None or only(i)]
    ds = details(s, items)
    ids = _spot_ids(s, items)
    points = valuation.price_points(s, list(ids.values()), first, last)
    by_metal = {m: points.get(iid, []) for m, iid in ids.items()}
    cursor: dict[str, int] = defaultdict(int)
    current: dict[str, Decimal | None] = {m: None for m in ids}
    out = []
    day = first
    while day <= last:
        for m, pts in by_metal.items():
            while cursor[m] < len(pts) and pts[cursor[m]][0] <= day:
                current[m] = pts[cursor[m]][1]
                cursor[m] += 1
        out.append(
            (
                day,
                sum((value_on(i, ds[i.id], day, current.get(i.metal or "")) for i in items), ZERO),
            )
        )
        nxt = day + dt.timedelta(days=step_days)
        if day < last < nxt:
            nxt = last
        day = nxt
    return out


@dataclass
class MetalSummary:
    metal: str
    ounces: Decimal  # fine troy ounces held
    cost: Decimal
    averageCost: Decimal | None  # a fine ounce
    spot: Decimal | None
    spotAsOf: dt.date | None
    value: Decimal
    gain: Decimal


def metals(s: Session, items: list[Item], day: dt.date) -> list[MetalSummary]:
    """Precious metals by metal (S1.10.3): what is held now, not what was sold."""
    ds = details(s, items)
    sp = spots(s, items, day)
    out = []
    for metal in METAL_SYMBOLS:
        held = [i for i in items if i.metal == metal and i.soldOn is None]
        if not held:
            continue
        oz = sum((fine_ounces(i) for i in held), ZERO)
        cost = sum((basis(i, ds[i.id]) for i in held), ZERO)
        price = sp.get(metal)
        worth = sum(
            (value_on(i, ds[i.id], day, price.price if price else None) for i in held), ZERO
        )
        out.append(
            MetalSummary(
                metal=metal,
                ounces=oz.quantize(Decimal("0.0001")),
                cost=cost,
                averageCost=(cost / oz).quantize(CENT) if oz else None,
                spot=price.price if price else None,
                spotAsOf=price.asOf if price else None,
                value=worth,
                gain=worth - cost,
            )
        )
    return out
