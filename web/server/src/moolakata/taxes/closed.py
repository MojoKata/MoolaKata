"""Closed tax years (requirements S2.8): a year is closed for an account once a tax book that
counts the account has its federal return filed or accepted, and no amended federal return is
being prepared for it. An edit that would change such a year's realized gains asks first: the
change is worked out, and undone unless confirmed. One made anyway is kept on each tax book that
closed the year (S2.8.3) until an amended federal return, or No amendment needed, settles it
(S8.15)."""

from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import clock, ids
from ..errors import Problem
from ..store.entities.accounts import Account
from ..store.entities.taxes import Filing, TaxBook, TaxBookChange
from ..store.repos import ledger as repo
from . import books

FILED = ("filed", "accepted")
PREPARING = ("not started", "in progress", "rejected")


def closing_books(s: Session, account: Account) -> dict[int, list[TaxBook]]:
    """The tax books that close a year for the account, by year: their federal return is filed
    or accepted, and no amended federal return is being prepared."""
    federal = (Filing.jurisdiction == "federal", Filing.deleted == false())
    filed = select(Filing.bookId).where(*federal, Filing.progress.in_(FILED))
    amending = select(Filing.bookId).where(
        *federal, Filing.amendsId.is_not(None), Filing.progress.in_(PREPARING)
    )
    out: dict[int, list[TaxBook]] = {}
    for book in s.scalars(
        select(TaxBook).where(
            TaxBook.id.in_(filed), TaxBook.id.not_in(amending), TaxBook.deleted == false()
        )
    ):
        if account.id in {a.id for a in books.counted(s, book).accounts}:
            out.setdefault(book.year, []).append(book)
    return out


def closed_years(s: Session, account: Account) -> set[int]:
    return set(closing_books(s, account))


def gains(s: Session, account: Account, years: set[int]) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    for d in repo.load(s, account).replay().disposals:
        if d.soldOn.year in years:
            out[d.soldOn.year] = out.get(d.soldOn.year, Decimal(0)) + (d.gain or Decimal(0))
    return out


class Guard:
    """Made before an edit and checked after it: when the edit moved a closed year's gains
    and isn't confirmed, refused with the years named (409 closed-year), so the request's
    unit of work rolls it back; when confirmed, kept on each tax book that closed the year."""

    def __init__(
        self,
        s: Session,
        account: Account,
        confirm: bool,
        by: str | None = None,
        ask: Callable[[str, str], None] | None = None,
    ):
        """`ask`, for a draft's save (S13.8.11.5), asks the question by its code instead of
        refusing, and returns only once it is confirmed."""
        self.s, self.account, self.confirm, self.by, self.ask = s, account, confirm, by, ask
        self.books = closing_books(s, account)
        self.before = gains(s, account, set(self.books)) if self.books else {}

    def check(self) -> None:
        if not self.books:
            return
        self.s.flush()
        after = gains(self.s, self.account, set(self.books))
        moved = {
            y: after.get(y, Decimal(0)) - self.before.get(y, Decimal(0))
            for y in sorted(self.books)
            if self.before.get(y, Decimal(0)) != after.get(y, Decimal(0))
        }
        named = " and ".join(str(y) for y in moved)
        if moved and self.ask is not None:
            self.ask(
                "closed-year",
                f"It changes the realized gains of {named}, a year whose return is filed. The "
                "return may need amending, and the tax book will list the change.",
            )
        elif moved and not self.confirm:
            raise Problem(
                409,
                "closed-year",
                f"This changes the realized gains of {named}, a year whose return is filed. "
                "Change it anyway? The return may need amending, and the tax book will list "
                "the change.",
                extra={"years": list(moved)},
            )
        for year, change in moved.items():
            for book in self.books[year]:
                self.s.add(
                    TaxBookChange(
                        id=ids.new_id("TxChg"),
                        bookId=book.id,
                        accountId=self.account.id,
                        gains=change,
                        madeById=self.by,
                    )
                )


def unsettled(s: Session, book: TaxBook) -> list[TaxBookChange]:
    """The edits made anyway since the book's federal return was filed, not yet settled."""
    return list(
        s.scalars(
            select(TaxBookChange)
            .where(
                TaxBookChange.bookId == book.id,
                TaxBookChange.settled.is_(None),
                TaxBookChange.deleted == false(),
            )
            .order_by(TaxBookChange.createdAt)
        )
    )


def settle(s: Session, book: TaxBook, by: str, how: str) -> None:
    """Settles the book's changes so far (S8.15): by an amended federal return (`amended`), or
    by No amendment needed (`not-needed`)."""
    now = clock.now()
    for change in unsettled(s, book):
        change.settled, change.settledAt, change.settledById = how, now, by
        change.updatedAt = now
