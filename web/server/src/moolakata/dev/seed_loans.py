"""Dev mode's loans (requirements S17.7): Bob's mortgage, paid each month from his checking
and split by its schedule, with one overpayment and the servicer's last balance typed in,
two payoff plans (one followed), shared with Alice; and Alice's new car loan, its first
payment still to come."""

import datetime as dt
import json
from decimal import Decimal as D

from sqlalchemy import select

from .. import clock, ids, loans, sharing
from ..store.entities.accounts import (
    Account,
    Anchor,
    Category,
    Loan,
    PayoffPlan,
    Split,
    Transaction,
)
from ..store.entities.sharing import CountedAccount


def seed_loans(s, people: dict) -> None:
    bob = people["bob"]
    checking = s.scalars(select(Account).where(Account.name == "Bob's checking")).one()
    today = clock.today()
    start = loans.add_months(dt.date(today.year, today.month, 1), -13)
    home = Account(
        id=ids.new_id("Acct"),
        ownerId=bob.id,
        name="Mortgage",
        type="mortgage",
        institution="Example Home Loans",
        mask="7781",
        keptBy='["manual"]',
    )
    s.add(home)
    s.flush()
    terms = Loan(
        id=ids.new_id("Loan"),
        accountId=home.id,
        principal=D(280000),
        startDate=start,
        termMonths=360,
        rate=D("6.25"),
        method="amortized",
        escrowTax=D("310.00"),
        escrowInsurance=D("120.00"),
        resets="[]",
        recasts="[]",
        originalValue=D(350000),
    )
    s.add(terms)
    s.flush()
    t = loans.terms_of(terms)
    cats = {c.builtIn: c.id for c in s.scalars(select(Category))}
    regular = loans.scheduled_payment(t) + D("430.00")
    paid: list[loans.Payment] = []
    for i in range(1, 14):
        day = loans.add_months(start, i)
        if day > today:
            break
        amount = regular + (D(5000) if i == 7 else 0)
        p = loans.split_for(t, paid, [], day, amount)
        out = Transaction(
            id=ids.new_id("Txn"),
            accountId=checking.id,
            date=day,
            kind="transfer",
            amount=-amount,
            payee="Example Home Loans",
            payeeRaw="EXAMPLE HOME LOANS PMT",
        )
        into = Transaction(
            id=ids.new_id("Txn"),
            accountId=home.id,
            date=day,
            kind="transfer",
            amount=amount,
            payee="Payment",
        )
        s.add_all([out, into])
        s.flush()
        out.transferId, into.transferId = into.id, out.id
        for part, key in loans.PARTS.items():
            if getattr(p, part):
                s.add(
                    Split(
                        id=ids.new_id("Split"),
                        transactionId=into.id,
                        amount=getattr(p, part),
                        categoryId=cats.get(key),
                    )
                )
        p.transactionId = into.id
        paid.append(p)
    # The servicer's statement at the last month's end, as the schedule has it.
    end = dt.date(today.year, today.month, 1) - dt.timedelta(days=1)
    s.add(
        Anchor(
            id=ids.new_id("Anchr"),
            accountId=home.id,
            date=end,
            balance=-loans.balance_on(t, paid, [], end),
            source="typed",
        )
    )
    home.updatedAt = clock.now()
    for name, inputs, since in (
        ("Extra $300 a month", {"monthly": "300"}, loans.add_months(start, 6)),
        (
            "$300 a month and $10,000 next year",
            {
                "monthly": "300",
                "lumps": [{"date": f"{today.year + 1}-01-15", "amount": "10000"}],
                "recast": True,
                "recastFee": "250",
            },
            None,
        ),
    ):
        s.add(
            PayoffPlan(
                id=ids.new_id("Pyoff"),
                accountId=home.id,
                name=name,
                inputs=json.dumps(inputs),
                following=since is not None,
                followingSince=since,
                createdById=bob.id,
            )
        )
    s.add(
        sharing.new_share(
            "account",
            home.id,
            "write",
            user_id=people["alice"].id,
            by=bob.id,
        )
    )
    s.add(CountedAccount(userId=people["alice"].id, accountId=home.id, createdAt=clock.now()))
    car = Account(
        id=ids.new_id("Acct"),
        ownerId=people["alice"].id,
        name="Car loan",
        type="auto-loan",
        institution="Example Auto Finance",
        mask="5512",
        keptBy='["manual"]',
    )
    s.add(car)
    s.flush()
    s.add(
        Loan(
            id=ids.new_id("Loan"),
            accountId=car.id,
            principal=D(24000),
            startDate=today - dt.timedelta(days=20),
            termMonths=60,
            rate=D("6.9"),
            method="daily",
            resets="[]",
            recasts="[]",
        )
    )
