"""Dev mode's accounts: a year of transactions across every account type built so far, made
from a fixed seed so every run looks the same (requirements S17.7)."""

import datetime as dt
import random
from decimal import Decimal as D

from sqlalchemy import select

from .. import clock, ids
from ..prices.stub import walk
from ..store.entities.accounts import (
    Account,
    Anchor,
    Category,
    Import,
    Lot,
    Transaction,
)
from ..store.repos import ledger as repo

CENT = D("0.01")


class Book:
    def __init__(self, s, today: dt.date) -> None:
        self.s = s
        self.today = today
        self.rng = random.Random(20261012)  # noqa: S311 - a repeatable seed, not a secret
        self.cats = {c.builtIn: c.id for c in s.scalars(select(Category))}

    def account(self, owner, name, type_, institution, mask, **kw) -> Account:
        a = Account(
            id=ids.new_id("Acct"),
            ownerId=owner.id,
            name=name,
            type=type_,
            institution=institution,
            mask=mask,
            **kw,
        )
        self.s.add(a)
        self.s.flush()
        return a

    def txn(self, a, day, amount, payee=None, kind=None, cat=None, imp=None, **kw) -> Transaction:
        amount = D(amount).quantize(CENT)
        t = Transaction(
            id=ids.new_id("Txn"),
            accountId=a.id,
            date=day,
            kind=kind or ("deposit" if amount > 0 else "withdrawal"),
            amount=amount,
            payee=payee,
            payeeRaw=payee.upper() if payee else None,
            categoryId=self.cats.get(cat) if cat else None,
            importId=imp.id if imp else None,
            **kw,
        )
        self.s.add(t)
        return t

    def trade(self, a, day, kind, inst, qty, price, imp=None) -> Transaction:
        qty, price = D(qty), D(price)
        amount = (-qty * price if kind == "buy" else qty * price).quantize(CENT)
        t = self.txn(
            a,
            day,
            amount,
            payee=f"{kind.title()} {inst.symbol}",
            kind=kind,
            imp=imp,
            instrumentId=inst.id,
            quantity=qty,
            price=price,
        )
        self.s.flush()
        if kind == "buy":
            self.s.add(
                Lot(
                    id=ids.new_id("Lot"),
                    accountId=a.id,
                    instrumentId=inst.id,
                    transactionId=t.id,
                    acquiredOn=day,
                    quantity=qty,
                    costBasis=-amount,
                )
            )
        return t

    def months(self, n: int = 12) -> list[dt.date]:
        first = dt.date(self.today.year, self.today.month, 1)
        out = []
        for i in range(n, -1, -1):
            y, m = first.year, first.month - i
            while m <= 0:
                y, m = y - 1, m + 12
            out.append(dt.date(y, m, 1))
        return out

    def day(self, month: dt.date, d: int) -> dt.date | None:
        try:
            day = month.replace(day=d)
        except ValueError:
            return None
        return day if day <= self.today else None


def seed_accounts(s, people: dict, today: dt.date | None = None) -> None:
    b = Book(s, today or clock.today())
    alice, bob = people["alice"], people["bob"]
    months = b.months()
    start = months[0]
    insts = {
        sym: repo.instrument(s, sym, name, cls)
        for sym, name, cls in (
            ("VTI", "Vanguard Total Stock Market ETF", "etf"),
            ("VXUS", "Vanguard Total International Stock ETF", "etf"),
            ("BND", "Vanguard Total Bond Market ETF", "etf"),
            ("AAPL", "Apple Inc.", "equity"),
            ("FXAIX", "Fidelity 500 Index Fund", "mutual-fund"),
            ("VMFXX", "Vanguard Federal Money Market Fund", "money-market"),
        )
    }

    def price(sym: str, day: dt.date) -> D:
        """The stub price source's walk, so the trades agree with --stubs' closes."""
        return walk(sym, day)

    # ---- Alice's banking, kept from files ----
    checking = b.account(
        alice, "Everyday checking", "checking", "First Example Bank", "4821", keptBy='["file"]'
    )
    savings = b.account(
        alice, "Emergency savings", "savings", "First Example Bank", "7730", keptBy='["file"]'
    )
    card = b.account(
        alice,
        "Travel Visa",
        "credit-card",
        "Example Card Co",
        "1123",
        keptBy='["file"]',
        openingBalance=D("0.00"),
        openingDate=start - dt.timedelta(days=1),
    )
    imp_check = Import(
        id=ids.new_id("Imprt"),
        accountId=checking.id,
        userId=alice.id,
        format="ofx",
        fileName="checking.qfx",
        fileHash="seed",
        coveredFrom=start,
        coveredTo=b.today,
    )
    imp_card = Import(
        id=ids.new_id("Imprt"),
        accountId=card.id,
        userId=alice.id,
        format="csv",
        fileName="card.csv",
        fileHash="seed",
        coveredFrom=start,
        coveredTo=b.today - dt.timedelta(days=40),
    )
    imp_card2 = Import(
        id=ids.new_id("Imprt"),
        accountId=card.id,
        userId=alice.id,
        format="csv",
        fileName="card-recent.csv",
        fileHash="seed2",
        coveredFrom=b.today - dt.timedelta(days=28),
        coveredTo=b.today,
    )
    # Savings statements stopped coming: an alert asks for one (S12.11).
    imp_savings = Import(
        id=ids.new_id("Imprt"),
        accountId=savings.id,
        userId=alice.id,
        format="ofx",
        fileName="savings-august.qfx",
        fileHash="seed3",
        coveredFrom=b.today - dt.timedelta(days=82),
        coveredTo=b.today - dt.timedelta(days=52),
    )
    s.add_all([imp_check, imp_card, imp_card2, imp_savings])
    s.flush()
    s.add(
        Transaction(
            id=ids.new_id("Txn"),
            accountId=checking.id,
            date=start,
            kind="deposit",
            amount=D("4200.00"),
            payee="Opening deposit",
            importId=imp_check.id,
        )
    )
    shops = [
        ("Kroger", "food.groceries", 60, 180),
        ("Whole Foods", "food.groceries", 40, 120),
        ("Chipotle", "food.dining", 12, 40),
        ("Shell", "transport.fuel", 35, 70),
        ("Target", "personal.clothing", 20, 140),
        ("Netflix", "personal.subscriptions", 15.49, 15.49),
    ]
    for month in months:
        if (pay := b.day(month, 1)) is not None:
            b.txn(checking, pay, "2860.00", "Acme Corp payroll", cat="income.salary", imp=imp_check)
        if (pay := b.day(month, 15)) is not None:
            b.txn(checking, pay, "2860.00", "Acme Corp payroll", cat="income.salary", imp=imp_check)
        if (rent := b.day(month, 3)) is not None:
            b.txn(
                checking,
                rent,
                "-2150.00",
                "Maple Street Apartments",
                cat="housing.rent",
                imp=imp_check,
            )
        if (util := b.day(month, 18)) is not None:
            b.txn(
                checking,
                util,
                -D(str(round(b.rng.uniform(90, 210), 2))),
                "City Power & Water",
                cat="housing.utilities",
                imp=imp_check,
            )
        if (save := b.day(month, 16)) is not None:
            out = b.txn(
                checking, save, "-500.00", "Transfer to savings", imp=imp_check, kind="transfer"
            )
            back = b.txn(savings, save, "500.00", "Transfer from checking", kind="transfer")
            s.flush()
            out.transferId, back.transferId = back.id, out.id
        if (interest := b.day(month, 28)) is not None:
            b.txn(
                savings,
                interest,
                D(str(round(b.rng.uniform(8, 14), 2))),
                "Interest paid",
                kind="interest",
                cat="income.interest",
            )
        spent = D(0)
        for _ in range(14):
            day = b.day(month, b.rng.randint(1, 28))
            if day is None:
                continue
            payee, cat, lo, hi = b.rng.choice(shops)
            amount = D(str(round(b.rng.uniform(lo, hi), 2)))
            spent += amount
            b.txn(
                card,
                day,
                -amount,
                payee,
                cat=cat,
                imp=imp_card if day <= imp_card.coveredTo else imp_card2,
            )
        if spent and (due := b.day(month, 25)) is not None:
            out = b.txn(
                checking,
                due,
                -spent,
                "Example Card Co payment",
                kind="transfer",
                cat="transfer.card",
                imp=imp_check,
            )
            paid = b.txn(
                card,
                due + dt.timedelta(days=1) if due < b.today else due,
                spent,
                "Payment - thank you",
                kind="transfer",
                imp=imp_card2,
            )
            s.flush()
            out.transferId, paid.transferId = paid.id, out.id
    s.flush()
    # Balances the bank reported at each month's end: they match, so they stay quiet.
    led = repo.load(s, checking)
    for month in months[1:]:
        end = month - dt.timedelta(days=1)
        s.add(
            Anchor(
                id=ids.new_id("Anchr"),
                accountId=checking.id,
                date=end,
                balance=led.balance(end),
                source="ofx",
                importId=imp_check.id,
            )
        )
    # The card's latest statement charged one coffee where the import has two, so the
    # Reconcile tab shows a mismatch with a duplicate suspect.
    last = b.today - dt.timedelta(days=5)
    for _ in range(2):
        b.txn(
            card,
            last - dt.timedelta(days=2),
            "-4.75",
            "Blue Bottle Coffee",
            cat="food.dining",
            imp=imp_card2,
        )
    s.flush()
    s.add(
        Anchor(
            id=ids.new_id("Anchr"),
            accountId=card.id,
            date=last,
            balance=repo.load(s, card).balance(last) + D("4.75"),
            source="statement",
        )
    )

    # ---- Alice's investing, by hand and from files ----
    brokerage = b.account(
        alice, "Taxable brokerage", "brokerage", "Example Brokerage", "5521", keptBy='["file"]'
    )
    b.txn(brokerage, start, "40000.00", "Transfer in", kind="deposit")
    s.flush()
    for i, month in enumerate(months):
        day = b.day(month, 6)
        if day is None:
            continue
        for sym, dollars in (("VTI", 900), ("VXUS", 400), ("BND", 300)):
            qty = (D(dollars) / price(sym, day)).quantize(D("0.0001"))
            b.trade(brokerage, day, "buy", insts[sym], qty, price(sym, day))
        if i % 3 == 2 and (div := b.day(month, 27)) is not None:
            b.txn(
                brokerage,
                div,
                D(str(round(30 + i * 4.1, 2))),
                "VTI dividend",
                kind="dividend",
                instrumentId=insts["VTI"].id,
                dividendType="qualified",
            )
    b.trade(
        brokerage,
        start + dt.timedelta(days=9),
        "buy",
        insts["AAPL"],
        "20",
        price("AAPL", start + dt.timedelta(days=9)),
    )
    sale = start + dt.timedelta(days=200)
    if sale <= b.today:
        b.trade(brokerage, sale, "sell", insts["AAPL"], "8", price("AAPL", sale))

    roth = b.account(alice, "Roth IRA", "roth-ira", "Example Brokerage", "6610")
    for month in months:
        if (day := b.day(month, 10)) is not None:
            b.txn(
                roth,
                day,
                "583.33",
                "Contribution",
                kind="deposit",
                contributionYear=day.year,
                contributionSource="employee",
            )
            s.flush()
            b.trade(
                roth,
                day,
                "buy",
                insts["VTI"],
                (D("583.33") / price("VTI", day)).quantize(D("0.0001")),
                price("VTI", day),
            )

    k401 = b.account(alice, "Acme 401(k)", "401k", "Example Retirement Services", "0042")
    for month in months:
        for d_ in (1, 15):
            if (day := b.day(month, d_)) is None:
                continue
            b.txn(
                k401,
                day,
                "750.00",
                "Payroll contribution",
                kind="deposit",
                contributionYear=day.year,
                contributionSource="employee",
            )
            b.txn(
                k401,
                day,
                "375.00",
                "Employer match",
                kind="deposit",
                contributionYear=day.year,
                contributionSource="employer",
            )
            s.flush()
            b.trade(
                k401,
                day,
                "buy",
                insts["FXAIX"],
                (D("1125") / price("FXAIX", day)).quantize(D("0.0001")),
                price("FXAIX", day),
            )

    hsa = b.account(
        alice,
        "Health savings",
        "hsa",
        "Example HSA Bank",
        "8800",
        openingBalance=D("3200.00"),
        openingDate=start - dt.timedelta(days=1),
    )
    for month in months:
        if (day := b.day(month, 2)) is not None:
            b.txn(hsa, day, "300.00", "Contribution", kind="deposit", contributionYear=day.year)
        if (day := b.day(month, 20)) is not None and month.month % 3 == 0:
            b.txn(
                hsa,
                day,
                -D(str(round(b.rng.uniform(40, 260), 2))),
                "CVS Pharmacy",
                cat="health.pharmacy",
            )

    # ---- Bob ----
    bob_checking = b.account(
        bob,
        "Bob's checking",
        "checking",
        "Second Example Bank",
        "3390",
        openingBalance=D("2600.00"),
        openingDate=start,
    )
    for month in months:
        if (day := b.day(month, 28)) is not None:
            b.txn(bob_checking, day, "5100.00", "Northwind payroll", cat="income.salary")
        for _ in range(6):
            if (day := b.day(month, b.rng.randint(1, 28))) is not None:
                payee, cat, lo, hi = b.rng.choice(shops)
                b.txn(bob_checking, day, -D(str(round(b.rng.uniform(lo, hi), 2))), payee, cat=cat)
    bob_ira = b.account(bob, "Rollover IRA", "ira", "Example Brokerage", "9012")
    b.txn(bob_ira, start, "85000.00", "Rollover", kind="deposit", contributionSource="rollover")
    s.flush()
    b.trade(
        bob_ira,
        start + dt.timedelta(days=1),
        "buy",
        insts["VTI"],
        "220",
        price("VTI", start + dt.timedelta(days=1)),
    )
    b.trade(
        bob_ira,
        start + dt.timedelta(days=1),
        "buy",
        insts["BND"],
        "380",
        price("BND", start + dt.timedelta(days=1)),
    )
    s.flush()
    for a in (checking, savings, card, brokerage, roth, k401, hsa, bob_checking, bob_ira):
        a.updatedAt = clock.now()


def seed_rules(s, people: dict) -> None:
    """Alice's categorisation rules (S2.7), first match wins."""
    from ..store.entities.accounts import Category, Rule

    cats = {
        c.builtIn: c.id for c in s.scalars(select(Category).where(Category.builtIn.is_not(None)))
    }
    for i, (match, key, extra) in enumerate(
        (
            ("re:^WHOLE ?FOODS", "food.groceries", {"payee": "Whole Foods"}),
            ("kroger", "food.groceries", {}),
            ("shell", "transport.fuel", {"direction": "out", "amountMax": D(100)}),
            ("netflix", "personal.subscriptions", {}),
            ("acme corp payroll", "income.salary", {"direction": "in"}),
        )
    ):
        rule = Rule(
            id=ids.new_id("Rule"),
            ownerId=people["alice"].id,
            position=i,
            payeeMatch=match,
            categoryId=cats[key],
            **extra,
        )
        s.add(rule)
        if match == "netflix":  # it tags what it matches too
            s.flush()
            from .. import tags

            tag = tags.make(s, people["alice"].id, "streaming")
            tags.set_on(s, "rule", rule.id, people["alice"].id, [tag.id], people["alice"].id)
