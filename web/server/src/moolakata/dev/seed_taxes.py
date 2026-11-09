"""Dev mode's tax books (requirements S17.7): Alice and Bob's joint book for last year, its
federal and state returns accepted with their documents and the figures they carry forward,
and this year's book started from it; and a loss sale this year bought back in the Roth IRA
within 30 days, a wash sale for the Capital gains panel. Their daughters are the books'
dependents."""

import datetime as dt
import json

from sqlalchemy import select

from .. import clock, ids
from ..store.entities.accounts import Account
from ..store.entities.education import Person
from ..store.entities.taxes import (
    Filing,
    TaxBook,
    TaxBookDependent,
    TaxBookFiler,
    TaxDocument,
)
from ..store.repos import ledger as repo
from .seed_accounts import Book


def seed_taxes(s, people: dict) -> None:
    alice, bob = people["alice"], people["bob"]
    year = clock.today().year
    now = clock.now()
    accts = {a.name: a for a in s.scalars(select(Account))}

    def book(y):
        b = TaxBook(id=ids.new_id("TaxBk"), ownerId=alice.id, year=y)
        s.add(b)
        s.flush()
        for u in (alice, bob):
            s.add(TaxBookFiler(bookId=b.id, userId=u.id, createdAt=now, acceptedAt=now))
        return b

    last, this = book(year - 1), book(year)
    # Their daughters as dependents in both books (S8.14.5), Carol a student.
    for b in (last, this):
        for name, student in (("Carol Griffin", True), ("Emma Griffin", False)):
            kid = s.scalars(select(Person).where(Person.name == name)).one()
            s.add(
                TaxBookDependent(
                    id=ids.new_id("TxDep"),
                    bookId=b.id,
                    personId=kid.id,
                    claimedAs="qualifying child",
                    student=student,
                )
            )
    federal = Filing(
        id=ids.new_id("Filng"),
        bookId=last.id,
        jurisdiction="federal",
        form="Form 1040",
        filingStatus="Married filing jointly",
        preparedBy="Alice, with tax software",
        sentBy="e-file",
        progress="accepted",
        dueDate=dt.date(year, 4, 15),
        filedOn=dt.date(year, 3, 2),
        confirmation="Submission ID 00412-7731",
        resultKind="refund",
        resultAmount=1240,
        carried=json.dumps(
            {
                "agi": "214380",
                "totalTax": "31920",
                "overpaymentApplied": "0",
                "capitalLossLong": "2100",
                # Bob's: his rollover IRA's nondeductible contributions (S8.17).
                "basis8606": {bob.id: "6500"},
            }
        ),
    )
    state = Filing(
        id=ids.new_id("Filng"),
        bookId=last.id,
        jurisdiction="state",
        place="Illinois",
        form="IL-1040",
        filingStatus="Married filing jointly",
        sentBy="e-file",
        progress="accepted",
        dueDate=dt.date(year, 4, 15),
        filedOn=dt.date(year, 3, 2),
        resultKind="owed",
        resultAmount=310,
    )
    s.add_all([federal, state])
    s.flush()

    def doc(b, form, issuer, account=None, direction="received", filing=None, notes=None):
        s.add(
            TaxDocument(
                id=ids.new_id("TxDoc"),
                bookId=b.id,
                direction=direction,
                form=form,
                issuer=issuer,
                accountId=accts[account].id if account and account in accts else None,
                filingId=filing.id if filing else None,
                notes=notes,
            )
        )

    doc(last, "W-2", "Acme Corp")
    doc(last, "W-2", "Northwind")
    doc(last, "1099 (composite)", "Example Brokerage", "Taxable brokerage")
    doc(last, "1098", "Example Home Loans", "Mortgage")
    doc(last, "Return as filed", "IRS", direction="filed", filing=federal)
    doc(
        last,
        "E-file acknowledgement",
        "IRS",
        direction="filed",
        filing=federal,
        notes="Accepted the next day.",
    )
    doc(this, "W-2", "Acme Corp")
    s.add(
        Filing(
            id=ids.new_id("Filng"),
            bookId=this.id,
            jurisdiction="federal",
            form="Form 1040",
            filingStatus="Married filing jointly",
            dueDate=dt.date(year + 1, 4, 15),
        )
    )
    # A loss sale bought back in the Roth IRA within 30 days.
    if "Taxable brokerage" in accts and "Roth IRA" in accts:
        b = Book(s, clock.today())
        apple = repo.instrument(s, "AAPL", "Apple Inc.", "equity")
        today = clock.today()
        brk, roth = accts["Taxable brokerage"], accts["Roth IRA"]
        b.txn(brk, today - dt.timedelta(days=101), "4000.00", "Deposit", kind="deposit")
        b.trade(brk, today - dt.timedelta(days=100), "buy", apple, "15", "240")
        b.trade(brk, today - dt.timedelta(days=40), "sell", apple, "15", "205")
        b.txn(
            roth,
            today - dt.timedelta(days=26),
            "2000.00",
            "Contribution",
            kind="deposit",
            contributionYear=today.year,
        )
        b.trade(roth, today - dt.timedelta(days=25), "buy", apple, "8", "210")
