"""Dev mode's projections (requirements S17.7): Alice and Bob's retirement, active on their
Retirement portfolio, two scenarios beside it, and a savings target over the emergency fund."""

import json

from sqlalchemy import select

from .. import clock, ids, projections, sharing
from .. import people as household
from ..store.entities.accounts import Account
from ..store.entities.projections import Projection
from ..store.entities.sharing import Portfolio


def seed_projections(s, people: dict) -> None:
    alice, bob = people["alice"], people["bob"]
    retirement = s.scalars(select(Portfolio).where(Portfolio.name == "Retirement")).first()
    couple = [
        {"name": u.displayName, "birthYear": household.birth_year(s, u.id), "retireAge": 62}
        for u in (alice, bob)
    ]
    base = {
        "contribution": {"amount": 30000, "growth": 3},
        "withdrawal": {"method": "fixed", "amount": 70000},
        "income": [
            {"label": "Alice's Social Security", "person": 0, "fromAge": 67, "monthly": 2900},
            {"label": "Bob's Social Security", "person": 1, "fromAge": 67, "monthly": 2400},
        ],
        "fees": 0.1,
    }
    built = (
        {"kind": "portfolio", "id": retirement.id}
        if retirement
        else {"kind": "typed", "amount": 480000}
    )

    def make(name, goal, inputs, on=built, active=False):
        p = Projection(
            id=ids.new_id("Prjct"),
            ownerId=alice.id,
            name=name,
            goal=goal,
            builtOn=json.dumps(on),
            inputs=json.dumps(inputs),
        )
        s.add(p)
        s.flush()
        if active:
            p.active = True
            p.baseline = json.dumps(projections.make_baseline(projections.compute(s, p, alice.id)))
            p.baselineAt = clock.now()
        return p

    ret = make("Retire at 62", "retirement", {**base, "people": couple}, active=True)
    make(
        "Retire at 60",
        "retirement",
        {**base, "people": [{**x, "retireAge": 60} for x in couple]},
    )
    make(
        "Retire at 65",
        "retirement",
        {**base, "people": [{**x, "retireAge": 65} for x in couple]},
    )
    fund = s.scalars(select(Account).where(Account.name == "Emergency savings")).first()
    if fund is not None:
        make(
            "House deposit",
            "savings",
            {"target": 22000, "date": f"{clock.today().year + 2}-06-01", "monthly": 800},
            on={"kind": "accounts", "ids": [fund.id]},
            active=True,
        )
    # Bob follows the retirement plan with Alice.
    s.add(
        sharing.new_share(
            "projection",
            ret.id,
            "write",
            user_id=bob.id,
            by=alice.id,
        )
    )
