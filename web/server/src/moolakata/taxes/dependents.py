"""Tax-book dependents (requirements S8.14.5): the people a book's filers claim for the year.
MoolaKata doesn't decide who qualifies (S8.18): it suggests how each is claimed from the family
tree, shows their ages on Dec 31, flags a person claimed on two books for one year, expects
their documents, and flags a dependent child's unearned income past the Form 8615 threshold."""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import ids, people
from ..people import tree
from ..projections import taxtables
from ..store.entities.accounts import Account, Transaction
from ..store.entities.education import Person
from ..store.entities.taxes import (
    TaxBook,
    TaxBookDependent,
    TaxBookFiler,
    TaxDependentAccount,
)

CLAIMS = ("qualifying child", "qualifying relative")
CHILD_AGE = 19  # a qualifying child is under 19, or under 24 and a full-time student
STUDENT_AGE = 24
CREDIT_AGE = 17  # the child tax credit's
CARE_AGE = 13  # the childcare credit's
ZERO = Decimal(0)
# Relations from the tree that make someone a qualifying child: a child or a grandchild of a
# filer, however further down (S8.14.5.1).
DESCENDANTS = ("child", "grandchild")


def year_end(book: TaxBook) -> dt.date:
    return dt.date(book.year, 12, 31)


def age_on_dec_31(p: Person, year: int) -> int | None:
    """On Dec 31 every birthday of the year has passed, so the year alone gives the age."""
    return None if p.birthYear is None else year - p.birthYear


def suggest(descendant: bool, age: int | None, student: bool) -> str:
    """A child or grandchild under 19, or under 24 and a student, is suggested as a
    qualifying child; anyone else as a qualifying relative. An unknown age is no reason
    against."""
    if not descendant:
        return "qualifying relative"
    if age is None or age < CHILD_AGE or (student and age < STUDENT_AGE):
        return "qualifying child"
    return "qualifying relative"


def of_book(s: Session, book: TaxBook) -> list[TaxBookDependent]:
    return list(
        s.scalars(
            select(TaxBookDependent)
            .where(TaxBookDependent.bookId == book.id, TaxBookDependent.deleted == false())
            .order_by(TaxBookDependent.createdAt)
        )
    )


def account_ids(s: Session, d: TaxBookDependent) -> list[str]:
    return list(
        s.scalars(
            select(TaxDependentAccount.accountId).where(
                TaxDependentAccount.dependentId == d.id, TaxDependentAccount.deleted == false()
            )
        )
    )


def set_accounts(s: Session, d: TaxBookDependent, ids: list[str], now: dt.datetime) -> None:
    rows = {
        r.accountId: r
        for r in s.scalars(
            select(TaxDependentAccount).where(TaxDependentAccount.dependentId == d.id)
        )
    }
    for acct, r in rows.items():
        if acct not in ids and not r.deleted:
            r.mark_deleted(None, now)
    for acct in ids:
        r = rows.get(acct)
        if r is None:
            s.add(TaxDependentAccount(dependentId=d.id, accountId=acct, createdAt=now))
        elif r.deleted:
            r.restore()


def filer_people(s: Session, book: TaxBook) -> list[str]:
    who = s.scalars(
        select(TaxBookFiler.userId).where(
            TaxBookFiler.bookId == book.id, TaxBookFiler.deleted == false()
        )
    )
    out = []
    for uid in who:
        p = people.of_user(s, uid)
        if p is not None:
            out.append(p.id)
    return out


@dataclass
class Candidate:
    person: Person
    # To the filers: daughter, mother-in-law; a family relation's word is its label.
    relation: str | None
    descendant: bool
    age: int | None


def candidates(s: Session, user_id: str, book: TaxBook) -> list[Candidate]:
    """The household's people the caller can see, but the filers, each with their relation to
    a filer on Dec 31 and their age then; relatives first."""
    filers = filer_people(s, book)
    g = tree.graph(s, year_end(book))
    rel: dict[str, tree.Relation] = {}
    for f in filers:
        for r in g.relations(f):
            if r.personId not in rel or (
                r.key in DESCENDANTS and rel[r.personId].key not in DESCENDANTS
            ):
                rel[r.personId] = r
    out = []
    for p, _ in people.visible(s, user_id):
        if p.id in filers or (p.diedOn is not None and p.diedOn.year < book.year):
            continue
        r = rel.get(p.id)
        out.append(
            Candidate(
                p,
                r.word if r is not None else None,
                r is not None and r.key in DESCENDANTS,
                age_on_dec_31(p, book.year),
            )
        )
    out.sort(key=lambda c: (c.relation is None, not c.descendant, c.person.name.lower()))
    return out


def is_descendant(s: Session, book: TaxBook, person_id: str) -> bool:
    g = tree.graph(s, year_end(book))
    return any(
        r.personId == person_id and r.key in DESCENDANTS
        for f in filer_people(s, book)
        for r in g.relations(f)
    )


def _same_year_books(s: Session, book: TaxBook) -> list[TaxBook]:
    return list(
        s.scalars(
            select(TaxBook).where(
                TaxBook.year == book.year, TaxBook.deleted == false(), TaxBook.id != book.id
            )
        )
    )


def claimed_elsewhere(s: Session, book: TaxBook, person_id: str) -> bool:
    """Whether another live book of the same year claims the person. Which book isn't said:
    the caller may not see it (S8.14.5.2)."""
    others = [b.id for b in _same_year_books(s, book)]
    if not others:
        return False
    return (
        s.scalar(
            select(TaxBookDependent.id).where(
                TaxBookDependent.bookId.in_(others),
                TaxBookDependent.personId == person_id,
                TaxBookDependent.deleted == false(),
            )
        )
        is not None
    )


@dataclass
class Dependent:
    row: TaxBookDependent
    person: Person
    relation: str | None
    age: int | None
    under17: bool
    under13: bool
    agesOut: list[str]  # what they age out of this year
    claimedElsewhere: bool
    accountIds: list[str] = field(default_factory=list)


def ages_out(age: int | None, claimed_as: str, student: bool) -> list[str]:
    """What turning this year's age takes them out of."""
    if age is None:
        return []
    out = []
    if age == CREDIT_AGE:
        out.append("turns 17: no longer under 17 for the child tax credit")
    if age == CARE_AGE:
        out.append("turns 13: no longer under 13 for the childcare credit")
    if claimed_as == "qualifying child":
        if age == CHILD_AGE and not student:
            out.append("turns 19: a qualifying child after this only as a student")
        if age == STUDENT_AGE:
            out.append("turns 24: past a qualifying child's age")
    return out


def listed(s: Session, book: TaxBook) -> list[Dependent]:
    rows = of_book(s, book)
    if not rows:
        return []
    g = tree.graph(s, year_end(book))
    rel: dict[str, str] = {}
    for f in filer_people(s, book):
        for r in g.relations(f):
            rel.setdefault(r.personId, r.word)
    out = []
    for d in rows:
        p = s.get(Person, d.personId)
        age = age_on_dec_31(p, book.year)
        out.append(
            Dependent(
                row=d,
                person=p,
                relation=rel.get(p.id),
                age=age,
                under17=age is not None and age < CREDIT_AGE,
                under13=age is not None and age < CARE_AGE,
                agesOut=ages_out(age, d.claimedAs, d.student),
                claimedElsewhere=claimed_elsewhere(s, book, p.id),
                accountIds=account_ids(s, d),
            )
        )
    return out


def filers_claimed_elsewhere(s: Session, book: TaxBook) -> list[Person]:
    """The book's own filers claimed as a dependent on another book of the year: their own
    book notes it (S8.14.5.2)."""
    out = []
    for pid in filer_people(s, book):
        if claimed_elsewhere(s, book, pid):
            out.append(s.get(Person, pid))
    return out


def unearned(s: Session, accounts: list[Account], year: int, gains: Decimal) -> Decimal:
    """Interest, dividends and capital-gain distributions in the accounts over the year, plus
    the net gain realized in them (when positive): what Form 8615 calls unearned income."""
    first, last = dt.date(year, 1, 1), dt.date(year, 12, 31)
    total = ZERO
    ids = [a.id for a in accounts]
    if ids:
        for t in s.scalars(
            select(Transaction).where(
                Transaction.accountId.in_(ids),
                Transaction.deleted == false(),
                Transaction.kind.in_(("interest", "dividend", "reinvest", "capital-gain")),
                Transaction.date >= first,
                Transaction.date <= last,
            )
        ):
            if t.kind == "reinvest":
                # Reinvested, a dividend is income all the same, untyped ones too (CR3-392).
                if t.dividendType != "return-of-capital":
                    total -= t.amount
            elif not (t.kind == "dividend" and t.dividendType == "return-of-capital"):
                total += t.amount
    return total + max(gains, ZERO)


@dataclass
class Form8615:
    name: str
    unearned: Decimal
    threshold: Decimal
    accounts: list[str]


def form_8615(s: Session, book: TaxBook, deps: list[Dependent], counted) -> list[Form8615]:
    """Each dependent child whose unearned income in the counted accounts in their name passes
    the year's threshold (S8.14.5.3)."""
    from ..store.repos import ledger as repo
    from .panels import _items, _taxable

    threshold = Decimal(str(taxtables.figures(s, book.year)["form8615Threshold"]))
    by_id = {a.id: a for a in _taxable(counted)}
    first, last = dt.date(book.year, 1, 1), year_end(book)
    out = []
    for d in deps:
        if d.row.claimedAs != "qualifying child":
            continue
        accts = [by_id[i] for i in d.accountIds if i in by_id]
        if not accts:
            continue
        gains = ZERO
        for a in accts:
            for x in repo.load(s, a).replay().disposals:
                if first <= x.soldOn <= last and x.basis is not None:
                    gains += x.proceeds - x.basis + x.adjustment
        for r in _items(s, accts, first, last):
            if r.gain is not None:
                gains += r.gain
        amount = unearned(s, accts, book.year, gains)
        if amount > threshold:
            out.append(Form8615(d.person.name, amount, threshold, [a.name for a in accts]))
    return out


def childcare_paid(s: Session, book: TaxBook, account_ids: list[str]) -> bool:
    """Whether the counted accounts paid anything categorised as childcare in the year."""
    from ..store.entities.accounts import Category, Split

    cats = select(Category.id).where(Category.taxTag == "childcare")
    first, last = dt.date(book.year, 1, 1), year_end(book)
    in_year = (
        Transaction.accountId.in_(account_ids),
        Transaction.deleted == false(),
        Transaction.date >= first,
        Transaction.date <= last,
    )
    if s.scalar(select(Transaction.id).where(*in_year, Transaction.categoryId.in_(cats))):
        return True
    # Or a part of a payment in the year.
    parts = select(Split.id).where(
        Split.transactionId == Transaction.id,
        *in_year,
        Split.deleted == false(),
        Split.categoryId.in_(cats),
    )
    return s.scalar(parts) is not None


def past_child_age(age: int | None, student: bool) -> bool:
    return age is not None and (age >= STUDENT_AGE or (age >= CHILD_AGE and not student))


def carry_over(s: Session, prev: TaxBook, book: TaxBook, now: dt.datetime) -> list[str]:
    """Last year's dependents, a year older, with their accounts in their name: anyone past a
    qualifying child's age who isn't claimed as a relative is left out, and named."""
    left = []
    # From each of last year's books in turn (two after filing separately): a person both
    # claimed is copied once (S8.14.4). A book claims a person once, so what this book has
    # before the copy is all there is to look up.
    have = {d.personId for d in of_book(s, book)}
    for d in of_book(s, prev):
        p = s.get(Person, d.personId)
        if p is None or p.deleted or (p.diedOn is not None and p.diedOn.year < book.year):
            continue
        if d.personId in have:
            continue
        if d.claimedAs == "qualifying child" and past_child_age(
            age_on_dec_31(p, book.year), d.student
        ):
            left.append(p.name)
            continue
        new = TaxBookDependent(
            id=ids.new_id("TxDep"),
            bookId=book.id,
            personId=d.personId,
            claimedAs=d.claimedAs,
            months=d.months,
            student=d.student,
        )
        s.add(new)
        s.flush()
        set_accounts(s, new, account_ids(s, d), now)
    return left
