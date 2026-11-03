"""Options (requirements S3.2–S3.4, S3.6): contracts as instruments, and what a trade's cash
comes to."""

import datetime as dt
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import ids
from ..store.entities.accounts import Instrument, OptionContract
from ..store.repos import ledger as repo

ACTIONS = ("buy-to-open", "sell-to-open", "buy-to-close", "sell-to-close")
CENT = Decimal("0.01")


def symbol(underlying: str, expiry: dt.date, right: str, strike: Decimal) -> str:
    """A contract's symbol as people read it: MSFT 20NOV26 480 P."""
    k = f"{strike.normalize():f}"
    return f"{underlying} {expiry:%d%b%y}".upper() + f" {k} {'C' if right == 'call' else 'P'}"


def occ(underlying: str, c: OptionContract) -> str:
    """The contract's OCC ticker, as option data sources name it: O:MSFT261120P00480000."""
    strike = int((c.strike * 1000).to_integral_value())
    side = "C" if c.right == "call" else "P"
    return f"O:{underlying}{c.expiry:%y%m%d}{side}{strike:08d}"


def contract_of(s: Session, instrument_id: str) -> OptionContract | None:
    return s.scalars(
        select(OptionContract).where(
            OptionContract.instrumentId == instrument_id, OptionContract.deleted == false()
        )
    ).first()


def contract(
    s: Session,
    underlying: str,
    right: str,
    strike: Decimal,
    expiry: dt.date,
    multiplier: int = 100,
) -> tuple[Instrument, OptionContract]:
    """The option instrument for these terms, made the first time."""
    under = repo.instrument(s, underlying, None, "equity")
    sym = symbol(under.symbol, expiry, right, strike)
    inst = repo.instrument(s, sym, None, "option")
    c = contract_of(s, inst.id)
    if c is None:
        c = OptionContract(
            id=ids.new_id("OptCt"),
            instrumentId=inst.id,
            underlyingId=under.id,
            right=right,
            strike=strike,
            expiry=expiry,
            multiplier=multiplier,
        )
        s.add(c)
        s.flush()
    if not inst.name:
        inst.name = (
            f"{under.symbol} {'call' if right == 'call' else 'put'} {strike.normalize():f}, "
            f"expiring {expiry:%b %-d, %Y}"
        )
    return inst, c


def cash(action: str, contracts: Decimal, premium: Decimal, fees: Decimal, mult: int) -> Decimal:
    """What a trade does to the account's cash: paid out to buy, received to sell, less fees."""
    gross = (contracts * premium * mult).quantize(CENT)
    if action in ("buy-to-open", "buy-to-close"):
        return -gross - fees
    return gross - fees


# ---------- expiry, assignment and exercise (S3.4, S3.6) ----------


def settle(s: Session, user_id: str, account, inst, how: str, day: dt.date, contracts=None):
    """Record an option's end: expired, assigned (a short one) or exercised (a long one). An
    assignment or exercise also makes the stock trade at the strike, with the premium folded
    into its basis or proceeds as the IRS rules say (S3.4); returns the transactions made."""
    from ..errors import refuse
    from ..store.entities.accounts import Lot, Transaction

    c = contract_of(s, inst.id)
    if c is None:
        raise refuse("instrumentId", "not-an-option", "That isn't an option.")
    replay = repo.load(s, account).replay()
    held = replay.quantity(inst.id)
    if not held:
        raise refuse("instrumentId", "nothing-open", "Nothing of it is open in this account.")
    n = Decimal(contracts) if contracts else abs(held)
    if n <= 0 or n > abs(held):
        raise refuse("contracts", "contracts-invalid", f"Up to {abs(held)} contracts.")
    if how == "exercise" and held < 0:
        raise refuse("how", "short-exercise", "A short option is assigned, not exercised.")
    if how == "assign" and held > 0:
        raise refuse("how", "long-assign", "A long option is exercised, not assigned.")
    made = []
    end = Transaction(
        id=ids.new_id("Txn"),
        accountId=account.id,
        date=day,
        kind=how if how != "expired" else "expire",
        amount=Decimal(0),
        payee=f"{({'expired': 'Expired', 'assign': 'Assigned', 'exercise': 'Exercised'})[how]} "
        f"{inst.symbol}",
        instrumentId=inst.id,
        quantity=n,
        createdById=user_id,
    )
    s.add(end)
    s.flush()
    made.append(end)
    if how == "expired":
        return made
    paid = (c.strike * n * c.multiplier).quantize(CENT)  # the strike on every contract
    buys = (how == "exercise" and c.right == "call") or (how == "assign" and c.right == "put")
    parts = deliverable(s, c, day, account.ownerId)
    extra = ((c.deliverableCash or Decimal(0)) * n).quantize(CENT)
    word = "assigned" if how == "assign" else "exercised"
    given = Decimal(0)
    for i, (under, per, weight) in enumerate(parts):
        shares = per * n
        # The strike and the deliverable's cash are spread over its parts by their value
        # that day (S3.10.4); the last takes what rounding leaves. The premium goes into the
        # basis or proceeds as the account is replayed, so an edit to the opening trade
        # follows through (S3.4).
        last = i == len(parts) - 1
        cash = paid - given if last else (paid * weight).quantize(CENT)
        given += cash
        extra_part = (extra * weight).quantize(CENT)
        stock = Transaction(
            id=ids.new_id("Txn"),
            accountId=account.id,
            date=day,
            kind="buy" if buys else "sell",
            amount=-cash if buys else cash,
            payee=f"{'Buy' if buys else 'Sell'} {under.symbol} at {c.strike.normalize():f} "
            f"({word})",
            instrumentId=under.id,
            quantity=shares,
            price=(cash / shares).quantize(Decimal("0.0001")) if shares else c.strike,
            lotMethod=None if buys else account.lotMethod,
            optionTransactionId=end.id,
            createdById=user_id,
        )
        if not buys and extra_part:
            stock.proceedsAdjustment = -extra_part  # cash the deliverable carries goes with it
        s.add(stock)
        s.flush()
        if buys:
            # Cash the deliverable brings comes off the basis.
            s.add(
                Lot(
                    id=ids.new_id("Lot"),
                    accountId=account.id,
                    instrumentId=under.id,
                    transactionId=stock.id,
                    acquiredOn=day,
                    quantity=shares,
                    costBasis=cash - extra_part,
                    basisMissing=False,
                )
            )
        made.append(stock)
    if extra:
        cash_txn = Transaction(
            id=ids.new_id("Txn"),
            accountId=account.id,
            date=day,
            kind="deposit" if buys else "withdrawal",
            amount=extra if buys else -extra,
            payee=f"Deliverable cash ({word} {inst.symbol})",
            optionTransactionId=end.id,
            createdById=user_id,
        )
        s.add(cash_txn)
        s.flush()
        made.append(cash_txn)
    return made


def deliverable(s: Session, c: OptionContract, day: dt.date, owner: str) -> list:
    """What one contract delivers: (instrument, shares, its share of the value). An adjusted
    contract's parts are weighed by their value that day, or by their shares without prices."""
    import json

    from .. import valuation

    if not c.deliverable:
        return [(s.get(Instrument, c.underlyingId), Decimal(c.multiplier), Decimal(1))]
    rows = [
        (s.get(Instrument, x["instrumentId"]), Decimal(str(x["shares"])))
        for x in json.loads(c.deliverable)
    ]
    found = valuation.prices(s, [i.id for i, _ in rows], day, owner=owner)
    if all(i.id in found for i, _ in rows):
        values = [found[i.id].price * q for i, q in rows]
    else:
        values = [q for _, q in rows]
    total = sum(values, Decimal(0)) or Decimal(1)
    return [(i, q, v / total) for (i, q), v in zip(rows, values, strict=True)]


def expire_due(s: Session, today: dt.date) -> int:
    """Options past their expiry that the underlying's close on the expiry day itself left out
    of the money expire the day after (S3.6); those in the money, or without that day's
    close, wait for the user, who is asked."""
    from ..ledger import types as atypes
    from ..store.entities.accounts import Account

    done = 0
    for a in s.scalars(select(Account).where(Account.deleted == false())):
        if not atypes.investing(a.type):
            continue
        replay = repo.load(s, a).replay()
        for iid in replay.positions():
            c = contract_of(s, iid)
            if c is None or c.expiry >= today:
                continue
            close = market_close(s, c, c.expiry)
            if close is None or close[1] != c.expiry:
                continue  # only the expiry day's close decides (S3.6)
            if in_the_money(c, close[0]):
                continue
            settle(s, a.ownerId, a, s.get(Instrument, iid), "expired", c.expiry)
            done += 1
    return done


def market_close(s: Session, c: OptionContract, day: dt.date):
    """What a contract delivers, per share of its multiplier, at the market's stored closes of
    the day alone, and the oldest close used: what decides an automatic expiry (S3.6, CR3-24).
    No one's typed price, statement or trade. None without closes."""
    import json

    from .. import valuation

    if not c.deliverable:
        p = valuation.closes(s, [c.underlyingId], day).get(c.underlyingId)
        return (p.price, p.asOf) if p is not None else None
    rows = json.loads(c.deliverable)
    found = valuation.closes(s, [x["instrumentId"] for x in rows], day)
    if any(x["instrumentId"] not in found for x in rows):
        return None
    worth = sum(
        (found[x["instrumentId"]].price * Decimal(str(x["shares"])) for x in rows), Decimal(0)
    ) + (c.deliverableCash or Decimal(0))
    return worth / c.multiplier, min(found[x["instrumentId"]].asOf for x in rows)


def per_share(s: Session, c: OptionContract, day: dt.date | None, owner: str):
    """What a contract delivers, per share of its multiplier, at a day's closes, and the
    oldest close used: the underlying's price, or for an adjusted contract its deliverable's
    value (its shares and cash) divided by the multiplier (S3.10.5). None without closes."""
    import json

    from .. import valuation

    if not c.deliverable:
        p = valuation.prices(s, [c.underlyingId], day, owner=owner).get(c.underlyingId)
        return (p.price, p.asOf) if p is not None else None
    rows = json.loads(c.deliverable)
    found = valuation.prices(s, [x["instrumentId"] for x in rows], day, owner=owner)
    if any(x["instrumentId"] not in found for x in rows):
        return None
    worth = sum(
        (found[x["instrumentId"]].price * Decimal(str(x["shares"])) for x in rows), Decimal(0)
    ) + (c.deliverableCash or Decimal(0))
    asof = min(found[x["instrumentId"]].asOf for x in rows)
    return worth / c.multiplier, asof


def in_the_money(c: OptionContract, price: Decimal) -> bool:
    return price > c.strike if c.right == "call" else price < c.strike
