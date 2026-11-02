"""Dev mode's physical assets (requirements S17.7): Alice's metals and collectables (one
valued over a year ago, one sold), her car securing her car loan, and Bob's home with its
improvements securing his mortgage, shared with Alice."""

import datetime as dt
from decimal import Decimal as D

from sqlalchemy import select

from .. import assets, clock, ids, sharing
from ..store.entities.accounts import Account, Loan
from ..store.entities.assets import Improvement, Item, ItemValuation


def seed_assets(s, people: dict) -> None:
    alice, bob = people["alice"], people["bob"]
    today = clock.today()

    def account(owner, name, type_, institution=None):
        a = Account(
            id=ids.new_id("Acct"),
            ownerId=owner.id,
            name=name,
            type=type_,
            institution=institution,
            keptBy='["manual"]',
        )
        s.add(a)
        s.flush()
        return a

    def item(a, owner, name, days_ago, cost, **kw):
        it = Item(
            id=ids.new_id("Item"),
            accountId=a.id,
            name=name,
            acquiredOn=today - dt.timedelta(days=days_ago),
            costBasis=D(cost),
            createdById=owner.id,
            **kw,
        )
        s.add(it)
        s.flush()
        return it

    def valued(it, days_ago, value, source):
        s.add(
            ItemValuation(
                id=ids.new_id("Valtn"),
                itemId=it.id,
                date=today - dt.timedelta(days=days_ago),
                value=D(value),
                source=source,
            )
        )

    metals = account(alice, "Precious metals", "precious-metals", "Home safe")
    for metal in ("gold", "silver"):
        assets.metal_instrument(s, metal)
    spot = {"valuation": "spot", "weightUnit": "ozt"}
    item(
        metals,
        alice,
        "American Gold Eagle, 1 oz",
        700,
        "10650",
        category="Coin",
        metal="gold",
        unitWeight=D(1),
        purity=D("0.9167"),
        quantity=D(5),
        location="Bank box, First Example Bank",
        **spot,
    )
    item(
        metals,
        alice,
        "Gold bar, 1 oz (PAMP)",
        420,
        "2310",
        category="Bar",
        metal="gold",
        unitWeight=D(1),
        purity=D("0.9999"),
        serial="C 482113",
        **spot,
    )
    item(
        metals,
        alice,
        "Silver bar, 100 oz",
        900,
        "2450",
        category="Bar",
        metal="silver",
        unitWeight=D(100),
        purity=D("0.999"),
        location="Home safe",
        **spot,
    )
    coll = account(alice, "Collectables", "collectables")
    watch = item(
        coll,
        alice,
        "Rolex Submariner 124060",
        1100,
        "9100",
        category="Watch",
        serial="7Y2K4410",
        condition="Excellent, box and papers",
        insuredValue=D(14000),
        notes="Serviced at the dealer in 2025.",
        personalUse=True,
    )
    valued(watch, 480, "12500", "appraisal")
    cards = item(
        coll, alice, "1986 Fleer Jordan rookie, PSA 8", 1500, "3200", category="Trading cards"
    )
    valued(cards, 40, "4100", "sale")
    coin = item(coll, alice, "1909-S VDB cent, MS-63", 2000, "1450", category="Coin (numismatic)")
    coin.soldOn, coin.proceeds, coin.saleFees = today - dt.timedelta(days=60), D(1980), D(95)

    cars = account(alice, "Vehicles", "vehicle")
    car = item(
        cars,
        alice,
        "2026 Subaru Outback",
        20,
        "31800",
        valuation="depreciation",
        depreciationRate=D(12),
        serial="4S4BTGND7R3",
        personalUse=True,
    )
    home_acct = account(bob, "Home", "real-estate")
    mortgage = s.scalars(select(Account).where(Account.name == "Mortgage")).first()
    start = today - dt.timedelta(days=400)
    if mortgage is not None:
        start = s.scalars(select(Loan).where(Loan.accountId == mortgage.id)).one().startDate
    home = item(
        home_acct,
        bob,
        "1428 Elm St",
        (today - start).days,
        "350000",
        address="1428 Elm St",
        closingCosts=D(7400),
        primaryResidence=True,
        personalUse=True,
    )
    s.add(
        Improvement(
            id=ids.new_id("Imprv"),
            itemId=home.id,
            date=today - dt.timedelta(days=150),
            description="Roof replacement",
            amount=D(14200),
        )
    )
    valued(home, 30, "372000", "estimate")
    for loan_name, secured in (("Mortgage", home), ("Car loan", car)):
        acct = s.scalars(select(Account).where(Account.name == loan_name)).first()
        if acct is not None:
            s.scalars(select(Loan).where(Loan.accountId == acct.id)).one().securedById = secured.id
    s.add(
        sharing.new_share(
            "account",
            home_acct.id,
            "read",
            user_id=alice.id,
            by=bob.id,
        )
    )
