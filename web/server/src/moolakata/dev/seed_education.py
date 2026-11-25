"""Dev mode's 529 (requirements S17.7): for Jane's daughter Lisa, with her grandmother Candace
among its contributors: Lisa's 529 with Jane's monthly contributions, Candace's five-year
election and one from John, invested in a fund, and Lisa's education projection, active."""

import datetime as dt
import json
from decimal import Decimal as D

from sqlalchemy import select

from .. import clock, exactjson, ids, projections
from ..prices.stub import walk
from ..store.entities.accounts import Account
from ..store.entities.education import Contribution, EducationPlan, Person
from ..store.entities.projections import Projection
from ..store.repos import ledger as repo
from .seed_accounts import Book


def seed_education(s, people: dict) -> None:
    jane, john = people["jane"], people["john"]
    today = clock.today()
    b = Book(s, today)
    lisa = s.scalars(select(Person).where(Person.name == "Lisa Doe")).one()
    candace = s.scalars(select(Person).where(Person.name == "Candace Doe")).one()
    acct = Account(
        id=ids.new_id("Acct"),
        ownerId=jane.id,
        name="Lisa's 529",
        type="529",
        institution="my529",
        mask="2018",
        keptBy='["manual"]',
    )
    s.add(acct)
    s.flush()
    s.add(
        EducationPlan(
            id=ids.new_id("EdPln"),
            accountId=acct.id,
            planState="Utah",
            planName="my529",
            beneficiaryId=lisa.id,
            openedOn=dt.date(2018, 11, 2),
            stateDeduction=D(2410),
        )
    )

    def give(day, amount, person_id=None, five=False):
        t = b.txn(acct, day, amount, "Contribution", kind="deposit")
        s.flush()
        if person_id or five:
            s.add(
                Contribution(
                    id=ids.new_id("Cntrb"),
                    transactionId=t.id,
                    fromPersonId=person_id,
                    fiveYear=five,
                )
            )
        return t

    give(dt.date(2018, 11, 2), "12000")
    give(dt.date(2024, 3, 1), "30000", candace.id, five=True)
    give(dt.date(today.year - 1, 12, 20), "2500", john.personId)
    for month in b.months(11):
        if (day := b.day(month, 5)) is not None:
            give(day, "250")
    s.flush()
    fund = repo.instrument(s, "VTI", "Vanguard Total Stock Market ETF", "etf")
    for day, amount in ((dt.date(2018, 11, 5), 11500), (dt.date(2024, 3, 5), 29000)):
        price = walk("VTI", day if day >= dt.date(2020, 1, 1) else dt.date(2020, 1, 2))
        qty = (D(amount) / price).quantize(D("0.0001"))
        b.trade(acct, day, "buy", fund, qty, price)
    s.flush()
    p = Projection(
        id=ids.new_id("Prjct"),
        ownerId=jane.id,
        name="Lisa's college",
        goal="education",
        builtOn=json.dumps({"kind": "accounts", "ids": [acct.id]}),
        inputs=json.dumps(
            {
                "beneficiary": {"kind": "person", "id": lisa.id},
                "startAge": 18,
                "schoolYears": 4,
                "costBasis": "public",
                "monthly": 250,
                "fees": 0.1,
            }
        ),
    )
    s.add(p)
    s.flush()
    p.active = True
    p.baseline = exactjson.dumps(projections.make_baseline(projections.compute(s, p, jane.id)))
    p.baselineAt = clock.now()
    acct.updatedAt = clock.now()
