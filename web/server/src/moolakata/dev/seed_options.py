"""Dev mode's options (requirements S17.7): in Jane's taxable brokerage, a covered call
written and bought back, a cash-secured put still open, a call bought and sold, and an iron
condor on SPY grouped as a strategy (S3.5)."""

import datetime as dt
from decimal import Decimal as D

from sqlalchemy import select

from .. import clock, ids, options
from ..store.entities.accounts import (
    Account,
    Instrument,
    Strategy,
    StrategyLeg,
    Transaction,
)


def seed_options(s, people: dict) -> None:
    brk = s.scalars(select(Account).where(Account.name == "Taxable brokerage")).first()
    if brk is None:
        return
    today = clock.today()
    jane = people["jane"]

    def trade(days_ago, action, under, right, strike, expiry, contracts, premium, fees="0.65"):
        inst, c = options.contract(s, under, right, D(strike), expiry)
        made.append(inst.id)
        day = today - dt.timedelta(days=days_ago)
        s.add(
            Transaction(
                id=ids.new_id("Txn"),
                accountId=brk.id,
                date=day,
                kind=action,
                amount=options.cash(action, D(contracts), D(premium), D(fees), c.multiplier),
                payee=f"{action.replace('-', ' ').capitalize()} {inst.symbol}",
                instrumentId=inst.id,
                quantity=D(contracts),
                price=D(premium),
                fees=D(fees),
                createdById=jane.id,
            )
        )

    made: list[str] = []
    month = today + dt.timedelta(days=37)
    gone = today - dt.timedelta(days=20)
    trade(80, "sell-to-open", "VTI", "call", "320", gone, "1", "4.10")
    trade(45, "buy-to-close", "VTI", "call", "320", gone, "1", "1.25")
    trade(30, "sell-to-open", "MSFT", "put", "480", month, "2", "6.40")
    trade(60, "buy-to-open", "AAPL", "call", "250", today + dt.timedelta(days=90), "2", "5.20")
    trade(15, "sell-to-close", "AAPL", "call", "250", today + dt.timedelta(days=90), "1", "7.80")
    made.clear()
    for action, right, strike, premium in (
        ("buy-to-open", "put", "530", "1.20"),
        ("sell-to-open", "put", "540", "2.00"),
        ("sell-to-open", "call", "600", "1.90"),
        ("buy-to-open", "call", "610", "0.60"),
    ):
        trade(12, action, "SPY", right, strike, month, "1", premium)
    condor = list(made)
    s.flush()
    st = Strategy(
        id=ids.new_id("Strat"),
        accountId=brk.id,
        underlyingId=s.scalars(select(Instrument).where(Instrument.symbol == "SPY")).one().id,
        openedOn=today - dt.timedelta(days=12),
    )
    s.add(st)
    s.flush()
    for iid in condor:
        s.add(
            StrategyLeg(
                strategyId=st.id, instrumentId=iid, addedOn=st.openedOn, createdAt=clock.now()
            )
        )
    s.flush()
