"""Dev mode's giving (requirements S17.7): Alice's plan for this year, 10% of a typed gross
income, shared with the household; her organisations with their causes and pledges, one not
deductible; donations of each type this year and last, one missing its acknowledgement; and a
donor-advised fund with a contribution and its grants."""

import datetime as dt
import json
from decimal import Decimal as D

from sqlalchemy import select

from .. import clock, ids, sharing
from ..store.entities.accounts import Account
from ..store.entities.giving import Donation, GivingPlan, Organisation
from ..store.entities.users import Group
from .seed_accounts import Book


def seed_giving(s, people: dict) -> None:
    alice = people["alice"]
    today = clock.today()
    year = today.year
    b = Book(s, today)
    plan = GivingPlan(
        id=ids.new_id("GvPln"),
        ownerId=alice.id,
        year=year,
        targetKind="percent",
        percent=D(10),
        incomeBasis="gross",
        income=D(185000),
    )
    s.add(plan)
    household = s.scalars(select(Group).where(Group.name == "Household")).one()
    s.add(
        sharing.new_share(
            "giving-plan",
            plan.id,
            "write",
            group_id=household.id,
            by=alice.id,
        )
    )

    def org(name, causes, ein=None, deductible=True, pledge=None, every=None):
        o = Organisation(
            id=ids.new_id("Orgzn"),
            ownerId=alice.id,
            name=name,
            ein=ein,
            deductible=deductible,
            causes=json.dumps(causes),
            pledge=D(pledge) if pledge else None,
            pledgeEvery=every,
        )
        s.add(o)
        return o

    parish = org("St. Mark's Parish", ["Faith"], "36-2167053", pledge=200, every="month")
    food = org(
        "Greater Chicago Food Depository", ["Hunger"], "36-3136294", pledge=150, every="month"
    )
    msf = org("Doctors Without Borders", ["Relief"], "13-3433452")
    red = org("American Red Cross", ["Relief"], "53-0196605")
    goodwill = org("Goodwill", ["Local"], "36-2167022")
    fire = org("GoFundMe: the Nguyens' fire", ["Local"], deductible=False)
    library = org("Chicago Public Library Foundation", ["Education", "Local"], "36-3693542")
    s.flush()

    def give(day, kind, amount, o=None, **kw):
        s.add(
            Donation(
                id=ids.new_id("Dnatn"),
                ownerId=alice.id,
                date=day,
                kind=kind,
                amount=D(amount),
                organisationId=o.id if o else None,
                **kw,
            )
        )

    for month in range(1, today.month + 1):
        day = dt.date(year, month, 1)
        if day <= today:
            give(day, "cash", "200", parish, acknowledged=True)
            give(day, "cash", "150", food, acknowledged=True)
    for month in range(1, 13):
        give(dt.date(year - 1, month, 1), "cash", "180", parish, acknowledged=True)
    give(dt.date(year, 3, 14), "cash", "1000", msf, acknowledged=True)
    give(dt.date(year, 9, 2), "cash", "300", red)
    give(dt.date(year, 5, 9), "goods", "85", goodwill, description="Two bags of clothes")
    give(dt.date(year, 7, 20), "cash", "300", fire)
    give(dt.date(year - 1, 12, 1), "cash", "2500", msf, acknowledged=True)
    fund = Account(
        id=ids.new_id("Acct"),
        ownerId=alice.id,
        name="Griffin Giving Fund",
        type="daf",
        institution="Fidelity Charitable",
        keptBy='["manual"]',
        countInNetWorth=False,
    )
    s.add(fund)
    s.flush()
    b.txn(fund, dt.date(year, 2, 10), "7480.00", "Contribution", kind="deposit")
    give(dt.date(year, 2, 10), "daf-contribution", "7480", dafAccountId=fund.id, acknowledged=True)
    for day, amount, o, paid in (
        (dt.date(year, 6, 1), "1000", library, True),
        (today - dt.timedelta(days=5), "500", food, False),
    ):
        b.txn(fund, day, f"-{amount}.00", o.name, kind="withdrawal")
        give(day, "daf-grant", amount, o, dafAccountId=fund.id, granted=paid)
    fund.updatedAt = clock.now()
