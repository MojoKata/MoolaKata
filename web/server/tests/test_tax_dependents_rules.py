"""The rules under a tax book's dependents, its due dates and its retirement moves, with plain
values where the code allows and records written straight into the store where it reads them:
a dependent's age and what it suggests and ages them out of, their accounts, claims on two
books, unearned income and childcare paid (S8.14.5), the legal holidays and the business day a
due date moves to (S8.15.3), and what each movement of money into or out of a retirement
account is (S8.6)."""

import datetime as dt
from decimal import Decimal

import pytest
from conftest import make_user
from sqlalchemy import select
from sqlalchemy.orm import Session

from moolakata import ids
from moolakata.store import scoping
from moolakata.store.entities.accounts import Account, Category, Split, Transaction
from moolakata.store.entities.education import Person, Relationship
from moolakata.store.entities.taxes import (
    TaxBook,
    TaxBookDependent,
    TaxBookFiler,
    TaxDependentAccount,
)
from moolakata.taxes import dates, dependents, retirement

D = dt.date
ZERO = Decimal(0)

# ---- Legal holidays and business days (S8.15.3) ----

# Each year's federal holidays as observed, with DC's Emancipation Day (April 16), as the
# Office of Personnel Management lists them.
HOLIDAYS = {
    # New Year's Day 2022 is a Saturday: observed on Friday Dec 31, 2021, in both years' sets.
    2021: {
        D(2021, 1, 1), D(2021, 1, 18), D(2021, 2, 15), D(2021, 4, 16), D(2021, 5, 31),
        D(2021, 6, 18), D(2021, 7, 5), D(2021, 9, 6), D(2021, 10, 11), D(2021, 11, 11),
        D(2021, 11, 25), D(2021, 12, 24), D(2021, 12, 31),
    },
    2022: {
        D(2021, 12, 31), D(2022, 1, 17), D(2022, 2, 21), D(2022, 4, 15), D(2022, 5, 30),
        D(2022, 6, 20), D(2022, 7, 4), D(2022, 9, 5), D(2022, 10, 10), D(2022, 11, 11),
        D(2022, 11, 24), D(2022, 12, 26),
    },
    2023: {
        D(2023, 1, 2), D(2023, 1, 16), D(2023, 2, 20), D(2023, 4, 17), D(2023, 5, 29),
        D(2023, 6, 19), D(2023, 7, 4), D(2023, 9, 4), D(2023, 10, 9), D(2023, 11, 10),
        D(2023, 11, 23), D(2023, 12, 25),
    },
    2026: {
        D(2026, 1, 1), D(2026, 1, 19), D(2026, 2, 16), D(2026, 4, 16), D(2026, 5, 25),
        D(2026, 6, 19), D(2026, 7, 3), D(2026, 9, 7), D(2026, 10, 12), D(2026, 11, 11),
        D(2026, 11, 26), D(2026, 12, 25),
    },
}  # fmt: skip


@pytest.mark.parametrize("year", sorted(HOLIDAYS))
def test_the_legal_holidays_are_the_federal_ones_and_emancipation_day_as_observed(year):
    assert dates.legal_holidays(year) == HOLIDAYS[year]


def test_the_nth_weekday_of_a_month_counts_from_its_first_and_its_last():
    # December 2025 starts on a Monday and ends on a Wednesday.
    assert dates._nth(2025, 12, 0, 1) == D(2025, 12, 1)
    assert dates._nth(2025, 12, 2, 1) == D(2025, 12, 3)
    assert dates._nth(2025, 12, 6, 2) == D(2025, 12, 14)
    assert dates._nth(2025, 12, 2, -1) == D(2025, 12, 31)
    assert dates._nth(2025, 12, 3, -1) == D(2025, 12, 25)
    assert dates._nth(2025, 11, 6, -1) == D(2025, 11, 30)


@pytest.mark.parametrize(
    ("due", "moved"),
    [
        (D(2024, 4, 15), D(2024, 4, 15)),  # a Monday, no holiday: the day itself
        (D(2023, 4, 15), D(2023, 4, 18)),  # Saturday, Sunday, Emancipation Day observed Monday
        (D(2022, 4, 15), D(2022, 4, 18)),  # Emancipation Day observed Friday, then a weekend
        (D(2026, 4, 16), D(2026, 4, 17)),  # Emancipation Day on a Thursday
        (D(2027, 4, 17), D(2027, 4, 19)),  # Saturday, then Sunday
        (D(2021, 12, 31), D(2022, 1, 3)),  # the next year's New Year's Day, observed early
        (D(2022, 12, 30), D(2022, 12, 30)),  # a Friday; Jan 1, 2023 is observed on Jan 2
    ],
)
def test_a_due_date_moves_past_weekends_and_legal_holidays(due, moved):
    assert dates.next_business_day(due) == moved


# ---- A dependent's age and the lines it draws (S8.14.5) ----


def test_the_age_on_dec_31_is_the_year_less_the_birth_year():
    emma = Person(id="Persn_x", name="Emma", sex="female", birthYear=2010)
    assert dependents.age_on_dec_31(emma, 2026) == 16
    emma.birthYear = None
    assert dependents.age_on_dec_31(emma, 2026) is None


def test_an_unknown_age_suggests_a_qualifying_child_and_ages_out_of_nothing():
    assert dependents.suggest(True, None, False) == "qualifying child"
    assert dependents.suggest(False, None, True) == "qualifying relative"
    assert dependents.ages_out(None, "qualifying child", False) == []


def test_what_each_age_takes_them_out_of_is_said_in_these_words():
    assert dependents.ages_out(13, "qualifying relative", False) == [
        "turns 13: no longer under 13 for the childcare credit"
    ]
    assert dependents.ages_out(17, "qualifying child", True) == [
        "turns 17: no longer under 17 for the child tax credit"
    ]
    assert dependents.ages_out(19, "qualifying child", False) == [
        "turns 19: a qualifying child after this only as a student"
    ]
    assert dependents.ages_out(24, "qualifying child", True) == [
        "turns 24: past a qualifying child's age"
    ]
    assert dependents.ages_out(19, "qualifying relative", False) == []
    assert dependents.ages_out(24, "qualifying relative", False) == []


@pytest.mark.parametrize(
    ("age", "student", "past"),
    [
        (None, False, False),
        (18, False, False),
        (19, False, True),
        (19, True, False),
        (23, True, False),
        (24, True, True),
        (24, False, True),
    ],
)
def test_past_a_qualifying_childs_age_is_19_or_24_for_a_student(age, student, past):
    assert dependents.past_child_age(age, student) is past


def test_the_year_end_is_dec_31_of_the_books_year():
    assert dependents.year_end(TaxBook(id="TxBk_x", ownerId="User_x", year=2025)) == D(2025, 12, 31)


# ---- What a retirement account's movement is (S8.6) ----


class Store:
    """A session's `get` over records held in memory."""

    def __init__(self, *records):
        self.rows = {(type(r), r.id): r for r in records}

    def get(self, cls, id_):
        return self.rows.get((cls, id_))


def acct(id_: str, type_: str, deleted: bool = False) -> Account:
    a = Account(id=id_, ownerId="User_x", name=id_, type=type_)
    if deleted:
        a.mark_deleted(None)
    return a


def txn(id_: str, account: Account, amount: str, kind: str = "transfer", **kw) -> Transaction:
    return Transaction(
        id=id_, accountId=account.id, date=D(2025, 3, 1), kind=kind, amount=Decimal(amount), **kw
    )


def moved(type_in: str, type_out: str, amount: str = "100", **kw):
    """What the money in (or, with a negative amount, out) of a `type_in` account is, matched
    with its other half in a `type_out` account."""
    here, there = acct("Acct_here", type_in), acct("Acct_there", type_out)
    a = txn("Txn_a", here, amount, transferId="Txn_b", **kw)
    b = txn("Txn_b", there, str(-Decimal(amount)), transferId="Txn_a")
    return retirement.classify(Store(here, there, a, b), a, here)


@pytest.mark.parametrize(
    ("into", "out_of", "what"),
    [
        ("roth-ira", "ira", "conversion"),
        ("roth-ira", "401k", "conversion"),
        ("ira", "401k", "rollover"),
        ("roth-ira", "roth-ira", "rollover"),
        ("roth-ira", "hsa", "rollover"),  # an HSA's money is not pre-tax money
        ("ira", "roth-ira", "rollover"),
        ("ira", "checking", "employee"),  # from outside retirement: a contribution
        ("ira", "brokerage", "employee"),
    ],
)
def test_money_in_is_told_by_its_other_halfs_account(into, out_of, what):
    assert moved(into, out_of) == what


@pytest.mark.parametrize(
    ("out_of", "into", "what"),
    [
        ("ira", "roth-ira", "conversion-out"),
        ("401k", "roth-ira", "conversion-out"),
        ("401k", "ira", "rollover-out"),
        ("roth-ira", "roth-ira", "rollover-out"),
        ("hsa", "roth-ira", "rollover-out"),
        ("roth-ira", "ira", "rollover-out"),
        ("ira", "checking", "distribution"),
    ],
)
def test_money_out_is_told_by_its_other_halfs_account(out_of, into, what):
    assert moved(out_of, into, "-100") == what


@pytest.mark.parametrize("source", ["employer", "rollover", "conversion"])
def test_a_source_set_on_money_in_says_what_it_is(source):
    assert moved("ira", "checking", contributionSource=source) == source
    assert moved("roth-ira", "ira", contributionSource=source) == source


def test_a_source_set_on_money_out_is_not_read():
    assert moved("ira", "checking", "-100", contributionSource="employer") == "distribution"


@pytest.mark.parametrize("source", [None, "employee", "rollover-out"])
def test_money_in_with_no_source_it_takes_is_told_by_its_accounts(source):
    assert moved("ira", "checking", contributionSource=source) == "employee"
    assert moved("roth-ira", "ira", contributionSource=source) == "conversion"


@pytest.mark.parametrize("kind", ["deposit", "withdrawal", "transfer"])
def test_each_kind_of_cash_moved_is_classified(kind):
    here = acct("Acct_here", "ira")
    assert retirement.classify(Store(here), txn("Txn_a", here, "5", kind), here) == "employee"
    assert retirement.classify(Store(here), txn("Txn_a", here, "-5", kind), here) == "distribution"


def test_a_cent_in_or_out_is_money_moved_and_nothing_is_none():
    assert moved("ira", "checking", "0.01") == "employee"
    assert moved("ira", "checking", "-0.01") == "distribution"
    assert moved("roth-ira", "ira", "0.01") == "conversion"
    assert moved("ira", "roth-ira", "-0.01") == "conversion-out"
    assert moved("ira", "roth-ira", "0") is None
    assert moved("roth-ira", "ira", "0", contributionSource="employer") is None


@pytest.mark.parametrize(
    ("kind", "amount", "extra"),
    [
        ("dividend", "5", {}),
        ("interest", "5", {}),
        ("fee", "-5", {}),
        ("deposit", "0", {}),  # nothing moved
        ("deposit", "5", {"instrumentId": "Instr_x"}),  # shares moved in, not cash
    ],
)
def test_what_isnt_cash_moved_is_none(kind, amount, extra):
    here = acct("Acct_here", "ira")
    assert retirement.classify(Store(here), txn("Txn_a", here, amount, kind, **extra), here) is None


def test_an_unmatched_or_vanished_other_half_leaves_no_other_account():
    here, there = acct("Acct_here", "ira"), acct("Acct_there", "401k")
    a = txn("Txn_a", here, "100", transferId="Txn_b")
    b = txn("Txn_b", there, "-100", transferId="Txn_a")
    assert retirement.other_account(Store(here, there, a, b), a) is there
    assert retirement.other_account(Store(here, there, a), a) is None  # half not there
    b.mark_deleted(None)
    assert retirement.other_account(Store(here, there, a, b), a) is None  # half deleted
    b.restore()
    assert retirement.other_account(Store(here, a, b), a) is None  # its account not there
    there.mark_deleted(None)
    assert retirement.other_account(Store(here, there, a, b), a) is None  # account deleted
    assert retirement.classify(Store(here, there, a, b), a, here) == "employee"
    unmatched = txn("Txn_c", here, "100")
    assert retirement.other_account(Store(here, there, a, b), unmatched) is None


# ---- A book's dependents in the store (S8.14.5) ----

T1 = dt.datetime(2026, 1, 5, 9, tzinfo=dt.UTC)
T2 = dt.datetime(2026, 2, 5, 9, tzinfo=dt.UTC)
T3 = dt.datetime(2026, 3, 5, 9, tzinfo=dt.UTC)
T4 = dt.datetime(2026, 4, 5, 9, tzinfo=dt.UTC)


class Home:
    """Alice and Bob, users with their people, and a session over the store that writes the
    records a test needs straight in."""

    def __init__(self, s, alice, bob):
        self.s, self.alice, self.bob = s, alice, bob

    def book(self, year: int, *filers, deleted: bool = False) -> TaxBook:
        filers = filers or (self.alice,)
        b = TaxBook(id=ids.new_id("TaxBk"), ownerId=filers[0].id, year=year)
        if deleted:
            b.mark_deleted(None)
        self.s.add(b)
        for u in filers:
            self.s.add(TaxBookFiler(bookId=b.id, userId=u.id))
        self.s.flush()
        return b

    def person(self, name: str, born=None, died=None, sex="female", deleted=False) -> Person:
        p = Person(id=ids.new_id("Persn"), name=name, sex=sex, birthYear=born, diedOn=died)
        if deleted:
            p.mark_deleted(None)
        self.s.add(p)
        self.s.flush()
        return p

    def me(self, user) -> Person:
        return self.s.get(Person, user.personId)

    def relate(self, a: Person, b: Person, relation: str, since=None, label=None) -> None:
        """`a` is `b`'s parent for a child relation; a stored one otherwise."""
        x, y = (a.id, b.id) if relation == "child" or a.id < b.id else (b.id, a.id)
        self.s.add(
            Relationship(id=ids.new_id("Rltn"), person1Id=x, person2Id=y, relation=relation,
                         fromDate=since, label=label)
        )  # fmt: skip
        self.s.flush()

    def dep(self, book, person, claimed_as="qualifying child", created=T1, deleted=False, **kw):
        d = TaxBookDependent(
            id=ids.new_id("TxDep"), bookId=book.id, personId=person.id, claimedAs=claimed_as,
            createdAt=created, **kw,
        )  # fmt: skip
        if deleted:
            d.mark_deleted(None)
        self.s.add(d)
        self.s.flush()
        return d

    def account(self, name: str, type_: str = "brokerage", owner=None) -> Account:
        a = Account(id=ids.new_id("Acct"), ownerId=(owner or self.alice).id, name=name, type=type_)
        self.s.add(a)
        self.s.flush()
        return a

    def txn(self, account, day, kind, amount, deleted=False, **kw) -> Transaction:
        t = Transaction(
            id=ids.new_id("Txn"), accountId=account.id, date=day, kind=kind,
            amount=Decimal(amount), **kw,
        )  # fmt: skip
        if deleted:
            t.mark_deleted(None)
        self.s.add(t)
        self.s.flush()
        return t

    def category(self, tag: str | None) -> str:
        q = select(Category.id).where(Category.taxTag == tag if tag else Category.taxTag.is_(None))
        return self.s.scalars(q).first()


@pytest.fixture
def home(server):
    alice = make_user(server, "alice", born=1980)
    bob = make_user(server, "bob", sex="male", born=1981)
    with Session(server.db.engine, expire_on_commit=False, autoflush=True) as s:
        scoping.scope_server(s, "test")
        yield Home(s, alice, bob)
        s.rollback()


def test_a_books_dependents_are_its_live_ones_in_the_order_added(home):
    h = home
    book, other = h.book(2025), h.book(2025, h.bob)
    later = h.dep(book, h.person("Later"), created=T2)
    first = h.dep(book, h.person("First"), created=T1)
    h.dep(book, h.person("Removed"), created=T1, deleted=True)
    h.dep(other, h.person("Elsewhere"), created=T1)
    assert [d.id for d in dependents.of_book(h.s, book)] == [first.id, later.id]


def test_a_dependents_accounts_are_its_own_live_rows_set_restored_and_left_out(home):
    h = home
    book = h.book(2025)
    one, two = h.dep(book, h.person("One")), h.dep(book, h.person("Two"))
    a1, a2, a3 = h.account("A1"), h.account("A2"), h.account("A3")

    def rows(d):
        q = select(TaxDependentAccount).where(TaxDependentAccount.dependentId == d.id)
        return {r.accountId: r for r in h.s.scalars(q)}

    def held(d):
        return sorted(dependents.account_ids(h.s, d))

    dependents.set_accounts(h.s, one, [a1.id, a2.id], T1)
    dependents.set_accounts(h.s, two, [a1.id], T1)
    h.s.flush()
    assert held(one) == sorted([a1.id, a2.id]) and held(two) == [a1.id]
    assert rows(one)[a1.id].createdAt == T1

    dependents.set_accounts(h.s, one, [a2.id, a3.id], T2)
    h.s.flush()
    assert held(one) == sorted([a2.id, a3.id])
    assert rows(one)[a1.id].deletedAt == T2 and rows(one)[a3.id].createdAt == T2
    assert held(two) == [a1.id]  # another dependent's rows untouched

    # One already left out keeps the time it was left out.
    dependents.set_accounts(h.s, one, [a3.id], T3)
    h.s.flush()
    assert (rows(one)[a1.id].deletedAt, rows(one)[a2.id].deletedAt) == (T2, T3)
    assert held(one) == [a3.id]

    # Taken back, its own row is restored: no second row for the same account.
    dependents.set_accounts(h.s, one, [a1.id, a3.id], T4)
    h.s.flush()
    assert held(one) == sorted([a1.id, a3.id])
    assert len(rows(one)) == 3 and rows(one)[a1.id].createdAt == T1
    assert rows(one)[a1.id].deletedAt is None and rows(one)[a3.id].deletedAt is None


def test_a_books_filers_are_its_live_filers_people(home):
    h = home
    book = h.book(2025, h.alice, h.bob)
    h.book(2025, h.bob)
    assert sorted(dependents.filer_people(h.s, book)) == sorted([h.alice.personId, h.bob.personId])
    bobs = h.s.scalars(
        select(TaxBookFiler).where(TaxBookFiler.bookId == book.id, TaxBookFiler.userId == h.bob.id)
    ).one()
    bobs.mark_deleted(None)
    h.s.flush()
    assert dependents.filer_people(h.s, book) == [h.alice.personId]


def test_claimed_elsewhere_is_another_live_book_of_the_same_year(home):
    h = home
    kid = h.person("Kid", 2015)
    mine = h.book(2025)
    assert not dependents.claimed_elsewhere(h.s, mine, kid.id)  # no other book
    h.dep(mine, kid)
    assert not dependents.claimed_elsewhere(h.s, mine, kid.id)  # only this book claims them
    h.dep(h.book(2024, h.bob), kid)  # another year
    h.dep(h.book(2025, h.bob, deleted=True), kid)  # a deleted book
    theirs = h.book(2025, h.bob)
    h.dep(theirs, kid, deleted=True)  # a removed claim
    h.dep(theirs, h.person("Someone else", 2015))
    assert not dependents.claimed_elsewhere(h.s, mine, kid.id)
    h.dep(theirs, kid)
    assert dependents.claimed_elsewhere(h.s, mine, kid.id)
    assert dependents.claimed_elsewhere(h.s, theirs, kid.id)
    assert not dependents.claimed_elsewhere(h.s, theirs, h.alice.personId)


def test_a_filer_claimed_on_another_book_is_named_on_their_own(home):
    h = home
    mine, theirs = h.book(2025, h.alice), h.book(2025, h.bob)
    assert dependents.filers_claimed_elsewhere(h.s, theirs) == []
    h.dep(mine, h.s.get(Person, h.bob.personId), "qualifying relative")
    assert [p.id for p in dependents.filers_claimed_elsewhere(h.s, theirs)] == [h.bob.personId]
    assert dependents.filers_claimed_elsewhere(h.s, mine) == []


def test_unearned_income_is_interest_dividends_and_distributions_in_the_year_plus_gains(home):
    h = home
    a, b, other = h.account("UTMA"), h.account("Savings", "savings"), h.account("Not theirs")
    h.txn(a, D(2025, 1, 1), "interest", "1")  # the year's first day
    h.txn(a, D(2025, 12, 31), "interest", "2")  # its last
    h.txn(a, D(2024, 12, 31), "interest", "4000")  # the year before
    h.txn(a, D(2026, 1, 1), "interest", "8000")  # the year after
    h.txn(b, D(2025, 6, 1), "dividend", "10", dividendType="ordinary")
    h.txn(b, D(2025, 6, 1), "dividend", "20")
    h.txn(b, D(2025, 6, 1), "dividend", "40000", dividendType="return-of-capital")
    h.txn(a, D(2025, 6, 1), "reinvest", "-100", dividendType="qualified")
    h.txn(a, D(2025, 6, 1), "reinvest", "-200")  # untyped, income all the same
    h.txn(a, D(2025, 6, 1), "reinvest", "-80000", dividendType="return-of-capital")
    h.txn(a, D(2025, 6, 1), "capital-gain", "400")
    h.txn(a, D(2025, 6, 1), "deposit", "160000")
    h.txn(a, D(2025, 6, 1), "interest", "320000", deleted=True)
    h.txn(other, D(2025, 6, 1), "interest", "640000")
    assert dependents.unearned(h.s, [a, b], 2025, ZERO) == Decimal("733")
    assert dependents.unearned(h.s, [a, b], 2025, Decimal("0.5")) == Decimal("733.5")
    assert dependents.unearned(h.s, [a, b], 2025, Decimal("-1000")) == Decimal("733")
    assert dependents.unearned(h.s, [], 2025, Decimal("7")) == Decimal("7")
    assert dependents.unearned(h.s, [], 2025, Decimal("-7")) == ZERO


def test_childcare_paid_is_a_childcare_expense_in_the_year_in_the_accounts(home):
    h = home
    care, food = h.category("childcare"), h.category(None)
    book = h.book(2025)
    card, other = h.account("Card", "credit-card"), h.account("Other", "checking")

    def paid(*accounts):
        return dependents.childcare_paid(h.s, book, [a.id for a in accounts])

    h.txn(card, D(2025, 3, 1), "withdrawal", "-50", categoryId=food)
    h.txn(card, D(2024, 12, 31), "withdrawal", "-50", categoryId=care)
    h.txn(card, D(2026, 1, 1), "withdrawal", "-50", categoryId=care)
    h.txn(card, D(2025, 3, 1), "withdrawal", "-50", categoryId=care, deleted=True)
    h.txn(other, D(2025, 3, 1), "withdrawal", "-50", categoryId=care)
    assert not paid(card)
    assert paid(card, other)
    assert not paid()  # no accounts counted, whatever is paid


def test_childcare_paid_in_a_split_is_a_live_split_of_a_live_payment_in_the_year(home):
    h = home
    care, food = h.category("childcare"), h.category(None)
    book = h.book(2025)
    card = h.account("Card", "credit-card")

    def split(day, category, deleted=False, txn_deleted=False):
        t = h.txn(card, day, "withdrawal", "-80", deleted=txn_deleted)
        x = Split(id=ids.new_id("Split"), transactionId=t.id, amount=Decimal("-80"),
                  categoryId=category)  # fmt: skip
        if deleted:
            x.mark_deleted(None)
        h.s.add(x)
        h.s.flush()

    split(D(2025, 5, 1), food)
    split(D(2025, 5, 1), care, deleted=True)
    split(D(2025, 5, 1), care, txn_deleted=True)
    split(D(2024, 12, 31), care)
    split(D(2026, 1, 1), care)
    assert not dependents.childcare_paid(h.s, book, [card.id])
    split(D(2025, 12, 31), care)
    assert dependents.childcare_paid(h.s, book, [card.id])
    assert not dependents.childcare_paid(h.s, book, [h.account("Empty").id])


@pytest.mark.parametrize("day", [D(2025, 1, 1), D(2025, 12, 31)])
def test_childcare_paid_on_the_years_first_or_last_day_counts(home, day):
    h = home
    card = h.account("Card", "credit-card")
    h.txn(card, day, "withdrawal", "-50", categoryId=h.category("childcare"))
    assert dependents.childcare_paid(h.s, h.book(2025), [card.id])


def family(h: Home) -> dict[str, Person]:
    """Alice's and Bob's people about a 2025 book: children each has (and is the other's
    friend), a grandchild, Alice's parents (her father died in 2025), a grandmother who died in
    2024, a godmother, a boy Bob adopts in 2026, and someone unrelated."""
    alice, bob = h.me(h.alice), h.me(h.bob)
    p = {
        "bea": h.person("bea", 2009),
        "dan": h.person("dan", 2011, sex="male"),
        "Cal": h.person("Cal", 2024),
        "Mum": h.person("Mum", 1950),
        "Lou": h.person("Lou", 1948, died=D(2025, 2, 1), sex="male"),
        "Gone": h.person("Gone", 1920, died=D(2024, 12, 31)),
        "Fay": h.person("Fay", 1960),
        "Abe": h.person("Abe", 2010, sex="male"),
        "Stan": h.person("Stan", sex="male"),
    }
    h.relate(alice, p["bea"], "child")
    h.relate(bob, p["bea"], "friend")
    h.relate(bob, p["dan"], "child")
    h.relate(alice, p["dan"], "friend")
    h.relate(p["bea"], p["Cal"], "child")
    h.relate(p["Mum"], alice, "child")
    h.relate(p["Lou"], alice, "child")
    h.relate(p["Gone"], p["Mum"], "child")
    h.relate(alice, p["Fay"], "family", label="Godmother")
    h.relate(bob, p["Abe"], "child", since=D(2026, 3, 1))
    return p


def test_candidates_are_the_people_seen_but_the_filers_relatives_and_descendants_first(home):
    # S8.14.5.1: each with their relation to a filer on Dec 31 (a descendant of either filer
    # over a friend of the other) and their age then; anyone who died before the year left out.
    h = home
    family(h)
    book = h.book(2025, h.alice, h.bob)
    got = [
        (c.person.name, c.relation, c.descendant, c.age)
        for c in dependents.candidates(h.s, h.alice.id, book)
        if c.person.name != "Ada Admin"
    ]
    assert got == [
        ("bea", "daughter", True, 16),
        ("Cal", "granddaughter", True, 1),
        ("dan", "son", True, 14),
        ("Fay", "Godmother", False, 65),
        ("Lou", "father", False, 77),
        ("Mum", "mother", False, 75),
        ("Abe", None, False, 15),
        ("Stan", None, False, None),
    ]


def test_a_candidate_related_to_both_filers_keeps_the_first_relation_but_a_descendants(home):
    # Fay is Alice's godmother and Bob's friend; Kit is Alice's granddaughter and Bob's
    # daughter: the first filer's relation is kept, unless only the other's is a descendant.
    h = home
    alice, bob = h.me(h.alice), h.me(h.bob)
    fay, kit, mid = h.person("Fay", 1960), h.person("Kit", 2015), h.person("Mid", 1990)
    h.relate(alice, fay, "family", label="Godmother")
    h.relate(bob, fay, "friend")
    h.relate(alice, mid, "child")
    h.relate(mid, kit, "child")
    h.relate(bob, kit, "child")
    book = h.book(2025, h.alice, h.bob)
    first = dependents.filer_people(h.s, book)[0]
    got = {c.person.name: c.relation for c in dependents.candidates(h.s, h.alice.id, book)}
    assert got["Fay"] == ("Godmother" if first == alice.id else "friend")
    assert got["Kit"] == ("granddaughter" if first == alice.id else "daughter")


def test_a_person_has_one_relation_word_in_the_book_and_when_chosen(home):
    """S8.14.5.5: Zoe is Alice's friend and Bob's daughter. Whichever filer is first, she is
    a daughter both when chosen and in the book's list (CR3-440)."""
    h = home
    alice, bob = h.me(h.alice), h.me(h.bob)
    zoe = h.person("Zoe", 2012)
    h.relate(alice, zoe, "friend")
    h.relate(bob, zoe, "child")
    book = h.book(2025, h.alice, h.bob)
    h.dep(book, zoe, "qualifying child")
    h.s.flush()
    chosen = {c.person.name: c.relation for c in dependents.candidates(h.s, h.alice.id, book)}
    listed = {d.person.name: d.relation for d in dependents.listed(h.s, book)}
    assert chosen["Zoe"] == listed["Zoe"] == "daughter"


def test_a_descendant_is_a_child_or_grandchild_of_a_filer_on_dec_31(home):
    h = home
    p = family(h)
    joint = h.book(2025, h.alice, h.bob)
    is_ = {n for n in p if dependents.is_descendant(h.s, joint, p[n].id)}
    assert is_ == {"bea", "dan", "Cal"}
    assert not dependents.is_descendant(h.s, h.book(2025, h.bob), p["Abe"].id)
    assert dependents.is_descendant(h.s, h.book(2026, h.bob), p["Abe"].id)  # adopted in 2026
    assert not dependents.is_descendant(h.s, h.book(2025, h.bob), p["bea"].id)  # Bob's friend


def test_a_books_dependents_are_listed_with_relation_age_and_the_lines_they_cross(home):
    h = home
    p = family(h)
    book = h.book(2025)
    a1, a2 = h.account("UTMA"), h.account("Savings", "savings")
    rows = [
        ("bea", p["bea"], "qualifying child", False),
        ("k17", h.person("k17", 2008), "qualifying child", False),
        ("k13", h.person("k13", 2012), "qualifying child", False),
        ("k12", h.person("k12", 2013), "qualifying child", False),
        ("s19", h.person("s19", 2006), "qualifying child", True),
        ("n19", h.person("n19", 2006), "qualifying child", False),
        ("r24", h.person("r24", 2001), "qualifying relative", False),
        ("Fay", p["Fay"], "qualifying relative", False),
        ("Abe", p["Abe"], "qualifying relative", False),
        ("nob", h.person("nob"), "qualifying child", False),
    ]
    made = {}
    for i, (key, person, claimed, student) in enumerate(rows):
        made[key] = h.dep(book, person, claimed, created=T1 + dt.timedelta(hours=i),
                          student=student)  # fmt: skip
    dependents.set_accounts(h.s, made["bea"], [a1.id, a2.id], T1)
    h.dep(h.book(2025, h.bob), p["Fay"], "qualifying relative")
    h.s.flush()
    got = dependents.listed(h.s, book)
    assert [d.row.id for d in got] == [made[k].id for k, *_ in rows]
    assert [(d.person.name, d.relation, d.age, d.under17, d.under13) for d in got] == [
        ("bea", "daughter", 16, True, False),
        ("k17", None, 17, False, False),
        ("k13", None, 13, True, False),
        ("k12", None, 12, True, True),
        ("s19", None, 19, False, False),
        ("n19", None, 19, False, False),
        ("r24", None, 24, False, False),
        ("Fay", "Godmother", 65, False, False),
        ("Abe", None, 15, True, False),
        ("nob", None, None, False, False),
    ]
    assert {d.person.name: d.agesOut for d in got if d.agesOut} == {
        "k17": ["turns 17: no longer under 17 for the child tax credit"],
        "k13": ["turns 13: no longer under 13 for the childcare credit"],
        "n19": ["turns 19: a qualifying child after this only as a student"],
    }
    assert [d.person.name for d in got if d.claimedElsewhere] == ["Fay"]
    assert sorted(got[0].accountIds) == sorted([a1.id, a2.id])
    assert [d.accountIds for d in got[1:]] == [[]] * 9
    assert dependents.listed(h.s, h.book(2025)) == []


def test_a_listed_dependents_relation_is_as_of_dec_31(home):
    # Ivy, whom Alice adopts in February 2026, is no relation on Alice's 2025 book, though she
    # is her daughter by the day the book is read.
    from moolakata import clock

    h = home
    ivy = h.person("Ivy", 2016)
    h.relate(h.me(h.alice), ivy, "child", since=D(2026, 2, 1))
    old, new = h.book(2025), h.book(2026)
    h.dep(old, ivy)
    h.dep(new, ivy)
    clock.fix(dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC))
    try:
        assert [d.relation for d in dependents.listed(h.s, old)] == [None]
        assert [d.relation for d in dependents.listed(h.s, new)] == ["daughter"]
    finally:
        clock.fix(None)


def test_next_years_dependents_are_last_years_a_year_older_with_their_accounts(home):
    # S8.14.4: a qualifying child past the age (19, or 24 for a student) is left out and
    # named; anyone who died before the year, or was removed, is left out unnamed; whoever
    # the new book already has is not copied again.
    h = home
    prev, book = h.book(2024), h.book(2025)
    a1, a2 = h.account("UTMA"), h.account("Gone")
    ppl = {
        "kid": h.person("Kid", 2010),
        "stud": h.person("Stud", 2006),  # 19 in 2025, a student
        "n19": h.person("N19", 2006),  # 19 in 2025, not one
        "s24": h.person("S24", 2001),  # 24 in 2025, a student
        "rel": h.person("Rel", 1995),
        "died24": h.person("Died24", 2012, died=D(2024, 12, 31)),
        "died25": h.person("Died25", 2012, died=D(2025, 1, 1)),
        "removed": h.person("Removed", 2012, deleted=True),
        "have": h.person("Have", 2005),  # 20 in 2025, already on the new book
        "unborn": h.person("Unborn"),
    }
    old = {
        "kid": h.dep(prev, ppl["kid"], months=6),
        "stud": h.dep(prev, ppl["stud"], student=True),
        "n19": h.dep(prev, ppl["n19"]),
        "s24": h.dep(prev, ppl["s24"], student=True),
        "rel": h.dep(prev, ppl["rel"], "qualifying relative", months=7),
        "died24": h.dep(prev, ppl["died24"]),
        "died25": h.dep(prev, ppl["died25"]),
        "removed": h.dep(prev, ppl["removed"]),
        "have": h.dep(prev, ppl["have"]),
        "unborn": h.dep(prev, ppl["unborn"]),
    }
    h.dep(prev, h.person("Unclaimed", 2012), deleted=True)
    kept = h.dep(book, ppl["have"], "qualifying relative", months=3)
    dependents.set_accounts(h.s, old["kid"], [a1.id, a2.id], T1)
    dependents.set_accounts(h.s, old["kid"], [a1.id], T2)
    h.s.flush()

    assert dependents.carry_over(h.s, prev, book, T3) == ["N19", "S24"]
    now = {d.personId: d for d in dependents.of_book(h.s, book)}
    names = {pid: h.s.get(Person, pid).name for pid in now}
    assert sorted(names.values()) == ["Died25", "Have", "Kid", "Rel", "Stud", "Unborn"]
    assert now[ppl["have"].id] is kept and kept.months == 3
    got = {
        names[pid]: (d.claimedAs, d.months, d.student, d.bookId == book.id, d.id[:6])
        for pid, d in now.items()
        if pid != ppl["have"].id
    }
    assert got == {
        "Kid": ("qualifying child", 6, False, True, "TxDep_"),
        "Stud": ("qualifying child", 12, True, True, "TxDep_"),
        "Rel": ("qualifying relative", 7, False, True, "TxDep_"),
        "Died25": ("qualifying child", 12, False, True, "TxDep_"),
        "Unborn": ("qualifying child", 12, False, True, "TxDep_"),
    }
    copied = now[ppl["kid"].id]
    assert copied.id != old["kid"].id
    assert dependents.account_ids(h.s, copied) == [a1.id]
    (link,) = h.s.scalars(
        select(TaxDependentAccount).where(TaxDependentAccount.dependentId == copied.id)
    )
    assert link.createdAt == T3

    # From Bob's book of the year before too: a person both claimed is copied once.
    theirs = h.book(2024, h.bob)
    h.dep(theirs, ppl["kid"])
    other = h.dep(theirs, h.person("Other", 2014))
    h.dep(theirs, ppl["n19"])
    assert dependents.carry_over(h.s, theirs, book, T4) == ["N19"]
    after = [d.personId for d in dependents.of_book(h.s, book)]
    assert sorted(after) == sorted([*now, other.personId])


def test_form_8615_is_a_dependent_childs_unearned_income_past_the_years_threshold(
    home, monkeypatch
):
    # S8.14.5.3: interest, dividends and the net gain realized in the year, in the counted
    # taxable accounts in the child's name, past the book's year's threshold (an admin's
    # correction of it too). The ledger's sales and the items sold are given here as values.
    from types import SimpleNamespace

    from moolakata.ledger.lots import Disposal
    from moolakata.store.entities.projections import TaxFigure
    from moolakata.store.repos import ledger as repo
    from moolakata.taxes import panels

    h = home
    h.s.add(TaxFigure(id=ids.new_id("TaxFg"), year=2025, key="form8615Threshold", value="2500"))
    book = h.book(2025)
    utma, sav, ira = (
        h.account("UTMA"),
        h.account("Savings", "savings"),
        h.account("Roth", "roth-ira"),
    )
    apart, exact, rel = h.account("Not counted"), h.account("Exact"), h.account("Relative's")
    for a, interest in ((utma, "1000"), (sav, "1313"), (ira, "9000"), (apart, "9000"),
                        (exact, "2500"), (rel, "9000")):  # fmt: skip
        h.txn(a, D(2025, 5, 1), "interest", interest)
    counted = [utma, sav, ira, exact, rel]

    def sale(sold, proceeds, basis, adjustment="0"):
        return Disposal(
            saleId=None, lotId=None, instrumentId="Instr_x", acquiredOn=D(2020, 1, 1),
            soldOn=sold, quantity=Decimal(1), proceeds=Decimal(proceeds),
            basis=None if basis is None else Decimal(basis), method="fifo",
            adjustment=Decimal(adjustment),
        )  # fmt: skip

    sales = {
        utma.id: [
            sale(D(2025, 1, 1), "300", "100", "7"),  # a gain of 200, 7 of a wash sale added back
            sale(D(2025, 12, 31), "50", "80"),  # a loss of 30
            sale(D(2024, 12, 31), "9000", "0"),  # the year before
            sale(D(2026, 1, 1), "9000", "0"),  # the year after
            sale(D(2025, 6, 1), "9000", None),  # its basis unknown
        ],
        ira.id: [sale(D(2025, 6, 1), "9000", "0")],
    }
    ledger = SimpleNamespace

    def load(s, a):
        assert s is h.s and isinstance(a, Account)
        return ledger(replay=lambda: ledger(disposals=sales.get(a.id, [])))

    monkeypatch.setattr(repo, "load", load)
    asked = []

    def items(s, accts, first, last):
        assert s is h.s
        asked.append((first, last))
        sold = [ledger(gain=Decimal("11")), ledger(gain=None)]
        return sold if utma in accts else []

    monkeypatch.setattr(panels, "_items", items)

    def dep(name, claimed_as, *accounts):
        p = h.person(name, 2012)
        row = TaxBookDependent(id=ids.new_id("TxDep"), bookId=book.id, personId=p.id,
                               claimedAs=claimed_as)  # fmt: skip
        return dependents.Dependent(row, p, None, 13, True, False, [], False,
                                    [a.id for a in accounts])  # fmt: skip

    deps = [
        dep("Relative", "qualifying relative", rel),
        dep("No taxable account", "qualifying child", ira, apart),
        dep("On the line", "qualifying child", exact),
        dep("Past it", "qualifying child", utma, apart, sav, ira),
    ]
    got = dependents.form_8615(h.s, book, deps, counted)
    # 1,000 + 1,313 of interest, 207 - 30 of sales, 11 of an item sold: 2,501.
    assert [(f.name, f.unearned, f.threshold, f.accounts) for f in got] == [
        ("Past it", Decimal("2501"), Decimal("2500"), ["UTMA", "Savings"])
    ]
    assert set(asked) == {(D(2025, 1, 1), D(2025, 12, 31))}
    assert dependents.form_8615(h.s, h.book(2026), deps[3:], counted)[0].threshold == 2700
