"""The tax panels' figures at the edges each rule draws (requirements S8.5–S8.12): income by
kind and payer, retirement limits by age and coverage with their notes, movements between
accounts, RMDs and Form 8606's pro rata rule, deductions and estimated payments, giving,
education, students, gifts, loans, and the spouses whose accounts count for wash sales. Rows are
written straight to the database and each panel is called as a function."""

import datetime as dt
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from moolakata import clock, ids, valuation
from moolakata.prices import refresh as pricing
from moolakata.store.entities.accounts import (
    Account,
    Category,
    Instrument,
    Lot,
    Split,
    Transaction,
)
from moolakata.store.entities.prices import Price
from moolakata.store.entities.receipts import Receipt, ReceiptLink
from moolakata.store.entities.taxes import (
    EstimatedPayment,
    Filing,
    TaxBook,
    TaxBookAccount,
    TaxBookFiler,
    TaxDocument,
)
from moolakata.store.entities.users import User
from moolakata.taxes import panels

d = dt.date
YEAR = 2026
ACCEPTED = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def stored_closes(monkeypatch):
    """Stored closes value holdings on a fixed today; both put back after."""
    monkeypatch.setattr(valuation, "_closes", [])
    monkeypatch.setattr(valuation, "_history", [])
    pricing.install()
    clock.fix(dt.datetime(2026, 12, 20, 12, tzinfo=dt.UTC))
    yield
    clock.fix(None)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """One database for the module: each test makes its own users, so books, accounts and
    people never meet; names that must be unique (usernames, symbols) are made so."""
    from moolakata.config import Config
    from moolakata.keys import master
    from moolakata.store.maintenance import open_store
    from moolakata.store.repos.ledger import ensure_categories

    tmp = tmp_path_factory.mktemp("taxpanels")
    config = Config(name="test", mode="proxy", data_dir=tmp / "data",
                    backup_dir=tmp / "backups", socket_path=tmp / "run" / "sock")  # fmt: skip
    key = b"\x07" * 16
    master.create_keyring(config, key)
    store = open_store(config, key)
    with store.db.tx(unscoped="test") as s:
        ensure_categories(s)
    yield store.db
    store.db.dispose()


# ---------- rows written straight to the database ----------


def _user(s, name: str, born: int | None = None) -> str:
    from moolakata import people

    p = people.make(s, name, "female", birth_year=born)
    uid = ids.new_id("User")
    u = User(id=uid, username=uid.lower(), displayName=name, personId=p.id)
    s.add(u)
    s.flush()
    return u.id


def _unique(symbol: str) -> str:
    """A symbol no other test's instrument has: the database is the module's."""
    return f"{symbol}.{ids.new_id('Instr')[-8:]}"


def _book(s, *filers: str, year: int = YEAR, pending=()) -> TaxBook:
    """A book of the filers, in the order named; those pending haven't accepted it."""
    b = TaxBook(id=ids.new_id("TaxBk"), ownerId=filers[0], year=year)
    s.add(b)
    s.flush()
    for i, u in enumerate(filers):
        s.add(TaxBookFiler(bookId=b.id, userId=u, acceptedAt=None if u in pending else ACCEPTED,
                           createdAt=ACCEPTED + dt.timedelta(seconds=i)))  # fmt: skip
    s.flush()
    return b


def _leave_out(s, book: TaxBook, account_id: str) -> None:
    s.add(TaxBookAccount(bookId=book.id, accountId=account_id, counted=False))
    s.flush()


def _acct(s, owner: str, name: str, type_: str, **kw) -> str:
    a = Account(id=ids.new_id("Acct"), ownerId=owner, name=name, type=type_, **kw)
    s.add(a)
    s.flush()
    return a.id


def _txn(s, account: str, day, kind: str, amount, **kw) -> Transaction:
    t = Transaction(
        id=ids.new_id("Txn"), accountId=account, date=day, kind=kind, amount=D(amount), **kw
    )
    s.add(t)
    s.flush()
    return t


def _transfer(s, out_of: str, into: str, day, amount) -> None:
    """A matched transfer: money out of one account and into another, each half naming the
    other."""
    a = _txn(s, out_of, day, "transfer", -D(amount))
    b = _txn(s, into, day, "transfer", D(amount), transferId=a.id)
    a.transferId = b.id
    s.flush()


def _holding(s, account: str, symbol: str, day, qty, price, close) -> None:
    """Shares bought on a day, and their close on that day."""
    i = Instrument(id=ids.new_id("Instr"), symbol=_unique(symbol), instrumentClass="equity")
    s.add(i)
    s.flush()
    _txn(s, account, day, "buy", -D(qty) * D(price), instrumentId=i.id, quantity=D(qty),
         price=D(price))  # fmt: skip
    s.add(Price(instrumentId=i.id, date=day, close=D(close), source="test"))
    s.flush()


def _retirement(db, book):
    with db.tx(unscoped="test") as s:
        return panels.retirement(s, s.get(TaxBook, book.id))


# ---------- the year's span ----------


def test_a_year_runs_from_its_first_day_to_its_last():
    assert panels._span(2024) == (d(2024, 1, 1), d(2024, 12, 31))


# ---------- retirement: limits, notes and what counts against them (S8.6) ----------

CATCH_50 = "with the catch-up at 50 and over"
ROTH = "Roth eligibility depends on MAGI"


@pytest.mark.parametrize(
    "type_, age, limit, note",
    [
        ("ira", None, "7500", ""),
        ("ira", 49, "7500", ""),
        ("ira", 50, "8600", CATCH_50),
        ("roth-ira", 49, "7500", ROTH),
        ("roth-ira", 50, "8600", f"{CATCH_50}; {ROTH}"),
        ("401k", None, "24500", ""),
        ("401k", 49, "24500", ""),
        ("401k", 50, "32500", CATCH_50),
        ("401k", 59, "32500", CATCH_50),
        ("401k", 60, "35750", "with the catch-up at 60–63"),
        ("403b", 63, "35750", "with the catch-up at 60–63"),
        ("457b", 64, "32500", CATCH_50),
    ],
)
def test_a_limit_takes_the_catch_up_its_owners_age_reaches(db, type_, age, limit, note):
    """The IRA catch-up from 50; the deferral catch-up from 50, and its larger one from 60
    through 63 (S8.6). The ages are on December 31 of the book's year."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", None if age is None else YEAR - age)
        _acct(s, u, "Plan", type_)
        b = _book(s, u)
    [c] = _retirement(db, b).contributions
    assert (c.limit, c.note, c.contributed) == (D(limit), note, 0)
    label = panels.atypes.LABELS[type_]
    assert (c.account, c.kind, c.owner, c.ownerId) == ("Plan", label, "Ann", u)


@pytest.mark.parametrize(
    "coverage, age, limit, note",
    [
        ("self", 54, "4400", "self-only coverage"),
        ("self", 55, "5400", "self-only coverage; with the catch-up at 55 and over"),
        ("family", 54, "8750", "family coverage"),
        (None, 54, "8750", "the family limit: set the coverage"),
        (None, None, "8750", "the family limit: set the coverage"),
    ],
)
def test_an_hsas_limit_is_its_coverages_with_1000_more_at_55(db, coverage, age, limit, note):
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", None if age is None else YEAR - age)
        _acct(s, u, "HSA", "hsa", hsaCoverage=coverage)
        b = _book(s, u)
    [c] = _retirement(db, b).contributions
    assert (c.limit, c.note, c.group) == (D(limit), note, "hsa")


def test_the_hsa_catch_up_is_the_years_figure_as_corrected(db):
    """An admin's correction of the HSA catch-up is the one held against (S8.6). A year no
    other test reads: the database is the module's."""
    from moolakata.store.entities.projections import TaxFigure

    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 2024 - 60)
        _acct(s, u, "HSA", "hsa", hsaCoverage="self")
        s.add(TaxFigure(id=ids.new_id("TaxFg"), year=2024, key="hsaCatchUp", value="1250"))
        b = _book(s, u, year=2024)
    [c] = _retirement(db, b).contributions
    assert c.limit == D("5400"), "2024's self-only 4,150 and the corrected 1,250"


def test_what_counts_is_the_contribution_years_and_the_owners_alone_but_in_an_hsa(db):
    """A contribution counts in the year it is for, which may be the next year's first months;
    an employer's money counts against an HSA's limit, never a 401(k)'s employee deferral; the
    note says how much of an HSA's came from the employer (S8.6). A deleted row counts nothing."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        k = _acct(s, u, "A 401k", "401k")
        _txn(s, k, d(2026, 2, 1), "deposit", "1000")
        _txn(s, k, d(2026, 3, 1), "deposit", "250")
        _txn(s, k, d(2027, 3, 1), "deposit", "400", contributionYear=2026)
        _txn(s, k, d(2026, 1, 15), "deposit", "700", contributionYear=2025)
        _txn(s, k, d(2026, 5, 1), "deposit", "8000", deletedAt=ACCEPTED)
        _txn(s, k, d(2026, 4, 1), "deposit", "5000", contributionSource="employer")
        h = _acct(s, u, "B HSA", "hsa", hsaCoverage="self")
        _txn(s, h, d(2026, 2, 1), "deposit", "1000")
        _txn(s, h, d(2026, 5, 1), "deposit", "1234.50", contributionSource="employer")
        _txn(s, h, d(2026, 6, 1), "deposit", "100", contributionSource="employer")
        _txn(s, h, d(2025, 6, 1), "deposit", "999", contributionSource="employer")
        b = _book(s, u)
    c = {x.account: x for x in _retirement(db, b).contributions}
    assert c["A 401k"].contributed == D("1650") and c["A 401k"].note == ""
    assert c["B HSA"].contributed == D("2334.50")
    assert c["B HSA"].note == "self-only coverage; 1,334.50 of it from the employer"


def test_an_account_with_no_contributions_still_shows_its_limit(db):
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        _acct(s, u, "IRA", "ira")
        b = _book(s, u)
    [c] = _retirement(db, b).contributions
    assert (c.contributed, c.limit, c.personTotal) == (0, D("7500"), 0)


def test_the_limits_are_the_books_years_and_its_retirement_accounts_alone(db):
    """A 2025 book holds 2025's IRA limit, whatever today's year; a brokerage account has no
    limit and no row."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 2025 - 40)
        _acct(s, u, "IRA", "ira")
        _txn(s, _acct(s, u, "Brokerage", "brokerage"), d(2025, 3, 1), "deposit", "100")
        b = _book(s, u, year=2025)
    [c] = _retirement(db, b).contributions
    assert (c.account, c.limit) == ("IRA", D("7000"))


def test_a_limit_is_held_against_a_persons_accounts_of_its_group(db):
    """IRAs, traditional and Roth, share one limit; 401(k) and 403(b) deferrals share one; a
    457(b) and an HSA each have their own; and each person has their own (S8.6)."""
    with db.tx(unscoped="test") as s:
        ann, bob = _user(s, "Ann", YEAR - 40), _user(s, "Bob", YEAR - 40)
        for owner, name, type_, amount in (
            (ann, "Ann IRA", "ira", "1000"),
            (ann, "Ann Roth", "roth-ira", "2000"),
            (ann, "Ann 401k", "401k", "300"),
            (ann, "Ann 403b", "403b", "400"),
            (ann, "Ann 457b", "457b", "500"),
            (ann, "Ann HSA", "hsa", "600"),
            (bob, "Bob IRA", "ira", "4000"),
        ):
            _txn(s, _acct(s, owner, name, type_), d(2026, 3, 1), "deposit", amount)
        b = _book(s, ann, bob)
    c = {x.account: (x.personTotal, x.group) for x in _retirement(db, b).contributions}
    assert c == {
        "Ann IRA": (D("3000"), "ira"),
        "Ann Roth": (D("3000"), "ira"),
        "Ann 401k": (D("700"), "deferral"),
        "Ann 403b": (D("700"), "deferral"),
        "Ann 457b": (D("500"), "457b"),
        "Ann HSA": (D("600"), "hsa"),
        "Bob IRA": (D("4000"), "ira"),
    }


def test_distributions_are_the_years_money_out_on_its_first_and_last_days_too(db):
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        a = _acct(s, u, "IRA", "ira")
        _txn(s, a, d(2025, 1, 1), "deposit", "90000")
        _txn(s, a, d(2025, 12, 31), "withdrawal", "-1")
        _txn(s, a, d(2026, 1, 1), "withdrawal", "-100")
        _txn(s, a, d(2026, 12, 31), "withdrawal", "-20")
        _txn(s, a, d(2027, 1, 1), "withdrawal", "-3")
        _acct(s, u, "Roth", "roth-ira")
        b = _book(s, u)
    assert _retirement(db, b).distributions == [("IRA", D("120"))]


# ---------- retirement: rollovers and conversions (S8.6) ----------


def _moves(ms):
    return [(m.kind, m.date, m.fromAccount, m.toAccount, m.amount) for m in ms]


def test_money_in_by_its_source_is_a_movement_from_another_account(db):
    """A rollover or conversion set on money in, with no other half here, comes from another
    account; it is no contribution, and only the year's are listed."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        ira = _acct(s, u, "IRA", "ira")
        roth = _acct(s, u, "Roth", "roth-ira")
        _txn(s, ira, d(2026, 5, 1), "deposit", "1.00", contributionSource="rollover")
        _txn(s, roth, d(2026, 6, 1), "deposit", "2.00", contributionSource="conversion")
        _txn(s, ira, d(2025, 12, 31), "deposit", "3.00", contributionSource="rollover")
        b = _book(s, u)
    r = _retirement(db, b)
    assert _moves(r.rollovers) == [("rollover", d(2026, 5, 1), "another account", "IRA", 1)]
    assert _moves(r.conversions) == [("conversion", d(2026, 6, 1), "another account", "Roth", 2)]
    assert [c.contributed for c in r.contributions] == [0, 0]


def test_money_out_to_an_account_the_book_leaves_out_is_still_a_movement(db):
    """The half going out tells a conversion or a rollover by its other half's account, though
    that account isn't counted (S8.6)."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        ira = _acct(s, u, "IRA", "ira")
        roth = _acct(s, u, "Roth", "roth-ira")
        plan = _acct(s, u, "401k", "401k")
        ira2 = _acct(s, u, "Old IRA", "ira")
        _transfer(s, ira, roth, d(2026, 3, 2), "500")
        _transfer(s, plan, ira2, d(2026, 4, 2), "700")
        b = _book(s, u)
        _leave_out(s, b, roth)
        _leave_out(s, b, ira2)
    r = _retirement(db, b)
    assert _moves(r.conversions) == [("conversion", d(2026, 3, 2), "IRA", "Roth", 500)]
    assert _moves(r.rollovers) == [("rollover", d(2026, 4, 2), "401k", "Old IRA", 700)]
    assert r.distributions == []


def test_a_transfer_both_halves_of_which_are_counted_is_one_movement_listed_by_date(db):
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        a_ira = _acct(s, u, "A IRA", "ira")
        b_ira = _acct(s, u, "B IRA", "ira")
        roth = _acct(s, u, "Roth", "roth-ira")
        k = _acct(s, u, "K", "401k")
        _transfer(s, a_ira, roth, d(2026, 9, 1), "300")
        _transfer(s, b_ira, roth, d(2026, 2, 1), "200")
        _transfer(s, k, a_ira, d(2026, 8, 1), "50")
        _transfer(s, k, b_ira, d(2026, 7, 1), "60")
        b = _book(s, u)
    r = _retirement(db, b)
    assert _moves(r.conversions) == [
        ("conversion", d(2026, 2, 1), "B IRA", "Roth", 200),
        ("conversion", d(2026, 9, 1), "A IRA", "Roth", 300),
    ]
    assert _moves(r.rollovers) == [
        ("rollover", d(2026, 7, 1), "K", "B IRA", 60),
        ("rollover", d(2026, 8, 1), "K", "A IRA", 50),
    ]


# ---------- retirement: RMDs (S8.6) ----------


def test_an_rmd_is_due_from_73_on_last_years_closing_value_holdings_and_all(db):
    """From the RMD age (73), each traditional IRA and plan account owes its value at the end
    of last year over the Uniform Lifetime Table's period for the owner's age; a Roth IRA and
    an HSA owe none, nor an age past the table."""
    with db.tx(unscoped="test") as s:
        old, young, oldest = (
            _user(s, "Old", YEAR - 73),
            _user(s, "Young", YEAR - 72),
            _user(s, "Oldest", YEAR - 101),
        )
        ira = _acct(s, old, "IRA", "ira")
        _txn(s, ira, d(2025, 6, 1), "deposit", "50000")
        _txn(s, ira, d(2025, 12, 31), "deposit", "1000")
        _txn(s, ira, d(2026, 1, 1), "deposit", "5000")
        _holding(s, ira, "VTI", d(2025, 6, 1), "10", "100", "120")
        for owner, name, type_ in (
            (old, "401k", "401k"),
            (old, "403b", "403b"),
            (old, "457b", "457b"),
            (old, "Roth", "roth-ira"),
            (old, "HSA", "hsa"),
            (young, "Young IRA", "ira"),
            (oldest, "Oldest IRA", "ira"),
        ):
            _txn(s, _acct(s, owner, name, type_), d(2025, 1, 1), "deposit", "2650")
        b = _book(s, old, young, oldest)
    rmds = {r.account: r for r in _retirement(db, b).rmds}
    assert set(rmds) == {"IRA", "401k", "403b", "457b"}
    r = rmds["IRA"]
    assert (r.owner, r.age, r.balance, r.factor) == ("Old", 73, D("51200"), 26.5)
    assert r.due == D("1932.08"), "51,200 / 26.5"
    assert rmds["401k"].due == D("100.00")


# ---------- retirement: the 8606 basis and the pro rata rule (S8.6) ----------


def _carried(monkeypatch, *figures):
    """Last year's federal figures as carried, each a return's (`basis8606` by filer)."""
    monkeypatch.setattr(
        panels.books, "federal_figures", lambda s, book: [(f, None) for f in figures]
    )


def _basis(owner, amount) -> dict:
    return {"basis8606": {owner: amount}}


def test_each_filers_8606_basis_is_their_own(db, monkeypatch):
    """S8.17: a joint return carries each filer's basis apart, and separate returns each
    theirs: none is summed into another's, and a filer with none typed has none."""
    with db.tx(unscoped="test") as s:
        ann, bob, cy = (_user(s, n, YEAR - 40) for n in ("Ann", "Bob", "Cy"))
        for u in (ann, bob, cy):
            _acct(s, u, "IRA", "ira")
        b = _book(s, ann, bob, cy)
    _carried(monkeypatch, {"basis8606": {ann: "6500", bob: "100"}}, {"capitalLossShort": "10"})
    got = {x.owner: (x.carried, x.nondeductible, x.undecided) for x in _retirement(db, b).bases}
    assert got == {"Ann": (D("6500"), 0, 0), "Bob": (D("100"), 0, 0), "Cy": (None, 0, 0)}


def test_a_conversion_is_taxed_but_for_its_share_of_the_basis(db, monkeypatch):
    """Form 8606 Part I: the basis over the traditional IRAs' year-end value (holdings too)
    plus what left them in the year, distributions and conversions; a plan account's money is
    not in it, and its conversion has no such share."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        ira = _acct(s, u, "IRA", "ira")
        ira2 = _acct(s, u, "IRA 2", "ira")
        roth = _acct(s, u, "Roth", "roth-ira")
        k = _acct(s, u, "401k", "401k")
        _txn(s, ira, d(2025, 1, 2), "deposit", "100000")
        _txn(s, ira2, d(2025, 1, 2), "deposit", "400")
        _txn(s, k, d(2025, 1, 2), "deposit", "50000")
        _transfer(s, ira, roth, d(2026, 3, 2), "30000")
        _txn(s, ira, d(2026, 4, 1), "withdrawal", "-10000")
        _holding(s, ira, "VTI", d(2026, 2, 1), "10", "100", "150")
        _txn(s, ira, d(2026, 12, 31), "interest", "50")
        _txn(s, ira, d(2027, 1, 5), "interest", "1000")
        _txn(s, k, d(2026, 4, 1), "withdrawal", "-7000")
        _transfer(s, k, roth, d(2026, 5, 2), "5000")
        b = _book(s, u)
    _carried(monkeypatch, _basis(u, "6500"))
    by_from = {m.fromAccount: m.taxable for m in _retirement(db, b).conversions}
    # 30,000 − 6,500 × 30,000 / (60,550 + 400 + 30,000 + 10,000)
    assert by_from == {"IRA": D("28068.35"), "401k": None}


def test_a_conversion_waits_for_last_years_basis_typed(db, monkeypatch):
    """R3.11: with none carried for its owner, the basis isn't read as 0: the taxed part waits
    for it, saying so."""
    _carried(monkeypatch)
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        ira = _acct(s, u, "IRA", "ira")
        roth = _acct(s, u, "Roth", "roth-ira")
        _txn(s, ira, d(2025, 1, 2), "deposit", "1000")
        _transfer(s, ira, roth, d(2026, 3, 2), "1000")
        b = _book(s, u)
    [m] = _retirement(db, b).conversions
    assert (m.taxable, m.waiting) == (None, "type Ann's Form 8606 basis carried from 2025")


def test_a_basis_past_what_the_iras_held_leaves_nothing_of_a_conversion_taxed(db, monkeypatch):
    """Form 8606 line 10: the basis's share is at most the whole (1.000), so a conversion of
    everything the IRAs held is untaxed when the basis is larger, never taxed less than nothing,
    and the rest of the basis carries on."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        ira = _acct(s, u, "IRA", "ira")
        roth = _acct(s, u, "Roth", "roth-ira")
        _txn(s, ira, d(2025, 1, 2), "deposit", "6000")
        _transfer(s, ira, roth, d(2026, 3, 2), "6000")
        b = _book(s, u)
    _carried(monkeypatch, _basis(u, "6500"))
    [m] = _retirement(db, b).conversions
    assert m.taxable == 0


@pytest.mark.parametrize("deposit, taxable", [("100", None), ("101", D("0.00"))])
def test_iras_worth_nothing_in_all_give_the_basis_no_share(db, monkeypatch, deposit, taxable):
    """When the IRAs' year-end value and what left them come to nothing (a fee took what was
    left), there is no share to take; above nothing there is."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        ira = _acct(s, u, "IRA", "ira")
        roth = _acct(s, u, "Roth", "roth-ira")
        _txn(s, ira, d(2025, 1, 2), "deposit", deposit)
        _txn(s, ira, d(2025, 2, 2), "fee", "-100")
        _transfer(s, ira, roth, d(2026, 3, 2), "50")
        b = _book(s, u)
    _carried(monkeypatch, _basis(u, "6500"))
    [m] = _retirement(db, b).conversions
    assert m.taxable == taxable


def test_a_joint_books_conversion_takes_its_owners_iras_and_basis_alone(db, monkeypatch):
    """Form 8606 is a person's own (S8.6): Ann's conversion is taxed by her basis over her
    IRAs, not over Bob's too; Bob's by his. Each IRA is named "IRA": they are told apart by
    account, never by name."""
    with db.tx(unscoped="test") as s:
        ann, bob = _user(s, "Ann", YEAR - 40), _user(s, "Bob", YEAR - 40)
        hers, his = _acct(s, ann, "IRA", "ira"), _acct(s, bob, "IRA", "ira")
        roth_a, roth_b = _acct(s, ann, "Roth", "roth-ira"), _acct(s, bob, "Roth", "roth-ira")
        _txn(s, hers, d(2025, 1, 2), "deposit", "50000")
        _txn(s, his, d(2025, 1, 2), "deposit", "450000")
        _transfer(s, hers, roth_a, d(2026, 3, 2), "50000")
        _transfer(s, his, roth_b, d(2026, 3, 2), "45000")
        b = _book(s, ann, bob)
    _carried(monkeypatch, {"basis8606": {ann: "6500", bob: "9000"}})
    by_to = {m.toAccount + m.fromId: m.taxable for m in _retirement(db, b).conversions}
    # Ann: 50,000 − 6,500 (all of hers converted); Bob: 45,000 − 9,000 × 45,000 / 450,000.
    assert by_to == {"Roth" + hers: D("43500.00"), "Roth" + his: D("44100.00")}


def test_this_years_nondeductible_contributions_add_to_the_basis(db, monkeypatch):
    """Form 8606 line 1 (S8.6): a backdoor Roth, 7,000 put in an IRA and not deducted, then
    converted, is taxed nothing with no basis carried; a split contribution counts its
    nondeductible part, the year's by its contribution year."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        ira = _acct(s, u, "IRA", "ira")
        roth = _acct(s, u, "Roth", "roth-ira")
        _txn(s, ira, d(2026, 1, 10), "deposit", "7000", deductible=False)
        part = _txn(s, ira, d(2027, 3, 1), "deposit", "1000", contributionYear=2026)
        for amount, mark in (("400", True), ("600", False)):
            s.add(Split(id=ids.new_id("Split"), transactionId=part.id, amount=D(amount),
                        deductible=mark))  # fmt: skip
        _txn(s, ira, d(2025, 6, 1), "deposit", "500", deductible=False)  # last year's
        _transfer(s, ira, roth, d(2026, 2, 1), "7000")
        b = _book(s, u)
    _carried(monkeypatch, _basis(u, "0"))
    ret = _retirement(db, b)
    [basis] = ret.bases
    assert (basis.carried, basis.nondeductible, basis.undecided) == (0, D("7600"), 0)
    [m] = ret.conversions
    # 7,600 × 7,000 / (500 at the year's end + 7,000 converted) is past the whole: none taxed.
    assert (m.taxable, m.waiting) == (0, None)


def test_a_conversion_waits_while_a_contribution_is_undecided(db, monkeypatch):
    """R3.11: a contribution not yet marked is never read as deductible: its owner's
    conversion waits, saying for what; another owner's goes on."""
    with db.tx(unscoped="test") as s:
        ann, bob = _user(s, "Ann", YEAR - 40), _user(s, "Bob", YEAR - 40)
        hers, his = _acct(s, ann, "IRA", "ira"), _acct(s, bob, "IRA", "ira")
        roth = _acct(s, ann, "Roth", "roth-ira")
        roth_b = _acct(s, bob, "Roth", "roth-ira")
        _txn(s, hers, d(2026, 1, 10), "deposit", "7000")
        _txn(s, his, d(2025, 1, 10), "deposit", "1000")
        _transfer(s, hers, roth, d(2026, 2, 1), "7000")
        _transfer(s, his, roth_b, d(2026, 2, 1), "1000")
        b = _book(s, ann, bob)
    _carried(monkeypatch, {"basis8606": {ann: "0", bob: "0"}})
    got = {m.fromId: (m.taxable, m.waiting) for m in _retirement(db, b).conversions}
    assert got == {
        hers: (None, "mark whether each of Ann's IRA contributions was deductible"),
        his: (D("1000.00"), None),
    }


def test_a_filers_undecided_contributions_are_counted_and_a_deleted_parts_mark_is_not(
    db, monkeypatch
):
    """S8.6: each contribution, or live part of a split one, still to decide is counted; a part
    taken away leaves no mark behind."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        ira = _acct(s, u, "IRA", "ira")
        _txn(s, ira, d(2026, 1, 10), "deposit", "1000")
        _txn(s, ira, d(2026, 2, 10), "deposit", "2000")
        split = _txn(s, ira, d(2026, 3, 10), "deposit", "3000")
        s.add(Split(id=ids.new_id("Split"), transactionId=split.id, amount=D(3000),
                    deductible=False))  # fmt: skip
        gone = Split(id=ids.new_id("Split"), transactionId=split.id, amount=D(3000))
        s.add(gone)
        s.flush()
        gone.mark_deleted(u)
        b = _book(s, u)
    _carried(monkeypatch, _basis(u, "0"))
    [basis] = _retirement(db, b).bases
    assert (basis.nondeductible, basis.undecided) == (D("3000"), 2)


def test_a_conversion_is_its_iras_whichever_half_is_read_first(db, monkeypatch):
    """The Roth account read first (made first, named first), its half of the transfer is
    read before the IRA's: the conversion still leaves the IRA, and takes its owner's basis."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", YEAR - 40)
        roth = _acct(s, u, "A Roth", "roth-ira")
        ira = _acct(s, u, "Z IRA", "ira")
        _txn(s, ira, d(2025, 1, 2), "deposit", "6000")
        _transfer(s, ira, roth, d(2026, 3, 2), "6000")
        b = _book(s, u)
    _carried(monkeypatch, _basis(u, "6500"))
    [m] = _retirement(db, b).conversions
    assert (m.fromId, m.taxable) == (ira, 0)


# ---------- income (S8.4, S8.5) ----------


def _income(db, book):
    with db.tx(unscoped="test") as s:
        return panels.income(s, s.get(TaxBook, book.id))


def _instrument(s, symbol: str, cls: str = "equity") -> str:
    i = Instrument(id=ids.new_id("Instr"), symbol=_unique(symbol), instrumentClass=cls)
    s.add(i)
    s.flush()
    return i.id


def _reward(s, account: str, iid: str, day, value) -> None:
    """Coins received as income, and the lot they make at their value (its basis), if known."""
    t = _txn(s, account, day, "reward", "0", instrumentId=iid, quantity=D("0.01"))
    s.add(Lot(id=ids.new_id("Lot"), accountId=account, instrumentId=iid, acquiredOn=day,
              quantity=D("0.01"), transactionId=t.id,
              costBasis=None if value is None else D(value)))  # fmt: skip
    s.flush()


def test_interest_is_summed_by_payer_largest_first_over_the_years_days(db):
    """A payer is the account's institution, or its name without one; the year runs from its
    first day through its last; a payer whose interest nets to nothing isn't listed; deleted
    rows and accounts not taxed count nothing."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        ally = _acct(s, u, "A savings", "savings", institution="Ally")
        own = _acct(s, u, "Credit union", "checking")
        none = _acct(s, u, "Netted", "checking", institution="Netted Bank")
        ira = _acct(s, u, "IRA", "ira", institution="Ira Bank")
        _txn(s, ally, d(2026, 1, 1), "interest", "10.25")
        _txn(s, ally, d(2026, 12, 31), "interest", "5.00")
        _txn(s, ally, d(2025, 12, 31), "interest", "1000")
        _txn(s, ally, d(2027, 1, 1), "interest", "1000")
        _txn(s, ally, d(2026, 6, 1), "interest", "1000", deletedAt=ACCEPTED)
        _txn(s, own, d(2026, 6, 1), "interest", "20.00")
        _txn(s, none, d(2026, 6, 1), "interest", "7.00")
        _txn(s, none, d(2026, 7, 1), "interest", "-7.00")
        _txn(s, ira, d(2026, 6, 1), "interest", "99")
        b = _book(s, u)
    assert _income(db, b).interest == [("Credit union", D("20.00")), ("Ally", D("15.25"))]


def test_dividends_by_kind_and_by_payer(db):
    """Ordinary dividends include qualified ones and those untyped; a reinvested dividend is a
    dividend; capital-gain distributions count by payer with dividends; a return of capital is
    its own line and no payer's dividend (S8.5, CR3-392, CR3-402)."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        small = _acct(s, u, "A small", "brokerage", institution="Alpha Co")
        big = _acct(s, u, "B big", "brokerage", institution="Zed Co")
        x = _instrument(s, "SCHD")
        _txn(s, small, d(2026, 3, 1), "dividend", "10", instrumentId=x)
        _txn(s, small, d(2026, 4, 1), "dividend", "20", instrumentId=x, dividendType="qualified")
        _txn(s, small, d(2026, 5, 1), "return-of-capital", "500", instrumentId=x)
        _txn(s, small, d(2026, 5, 2), "return-of-capital", "-25", instrumentId=x)
        _txn(s, big, d(2026, 3, 1), "dividend", "100", instrumentId=x, dividendType="ordinary")
        _txn(s, big, d(2026, 3, 2), "dividend", "200", instrumentId=x, dividendType="qualified")
        _txn(s, big, d(2026, 6, 1), "reinvest", "-40", instrumentId=x, quantity=D(1),
             price=D(40))  # fmt: skip
        _txn(s, big, d(2026, 7, 1), "capital-gain", "30", instrumentId=x)
        _txn(s, big, d(2026, 8, 1), "capital-gain", "3", instrumentId=x)
        b = _book(s, u)
    inc = _income(db, b)
    assert (inc.ordinary, inc.qualified) == (D("370"), D("220"))
    assert (inc.capitalGainDistributions, inc.returnOfCapital) == (D("33"), D("525"))
    assert inc.byPayer == [("Zed Co", D("373")), ("Alpha Co", D("30"))]


def test_foreign_tax_by_payer_and_coins_received_by_account_largest_first(db):
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        small = _acct(s, u, "A small", "brokerage", institution="Alpha Co")
        big = _acct(s, u, "B big", "brokerage", institution="Zed Co")
        x = _instrument(s, "VXUS")
        _txn(s, small, d(2026, 6, 1), "foreign-tax", "-2.00", instrumentId=x)
        _txn(s, big, d(2026, 6, 1), "foreign-tax", "-3.00", instrumentId=x)
        _txn(s, big, d(2026, 9, 1), "foreign-tax", "-4.50", instrumentId=x)
        _txn(s, big, d(2026, 10, 1), "dividend", "40", instrumentId=x)
        one = _acct(s, u, "A Exchange", "crypto-exchange", institution="Ex")
        two = _acct(s, u, "B Exchange", "crypto-exchange", institution="Ex")
        eth = _instrument(s, "ETH", "crypto")
        _reward(s, one, eth, d(2026, 4, 1), "10.00")
        _reward(s, two, eth, d(2026, 4, 1), "20.00")
        _reward(s, two, eth, d(2026, 5, 1), "25.00")
        _reward(s, two, eth, d(2026, 5, 2), None)
        b = _book(s, u)
    inc = _income(db, b)
    assert inc.foreignTax == [("Zed Co", D("7.50")), ("Alpha Co", D("2.00"))]
    assert inc.crypto == [("B Exchange", D("45.00")), ("A Exchange", D("10.00"))]


# ---------- deductions and estimated payments (S8.7) ----------


def _deductions(db, book):
    with db.tx(unscoped="test") as s:
        tags, quarters = panels.deductions(s, s.get(TaxBook, book.id))
    return {t.tag: (t.label, t.total, t.count, t.withReceipts) for t in tags}, tags, quarters


def _category(s, key: str) -> str:
    return s.scalars(select(Category.id).where(Category.builtIn == key)).one()


def _custom_category(s, name: str, tag: str | None) -> str:
    c = Category(id=ids.new_id("Cat"), name=name, kind="expense", taxTag=tag)
    s.add(c)
    s.flush()
    return c.id


def _split(s, txn: Transaction, category: str | None, amount, deleted=False) -> None:
    s.add(Split(id=ids.new_id("Split"), transactionId=txn.id, categoryId=category,
                amount=D(amount), deletedAt=ACCEPTED if deleted else None))  # fmt: skip
    s.flush()


def _receipt(s, owner: str, item: str, kind="transaction", deleted=False) -> None:
    r = Receipt(id=ids.new_id("Rcpt"), ownerId=owner, fileName="r.pdf",
                mediaType="application/pdf", size=1, sha256="0" * 64, fileId="f")  # fmt: skip
    s.add(r)
    s.flush()
    s.add(ReceiptLink(receiptId=r.id, kind=kind, itemId=item,
                      deletedAt=ACCEPTED if deleted else None))  # fmt: skip
    s.flush()


def test_a_tagged_categorys_spending_counts_positive_over_the_years_days(db):
    """Each tax tag's total over the year, its first and last days too, spending counting
    positive and a refund against it; how many rows, and how many with a receipt; a tag with no
    label of its own shows as itself; largest first (S8.7)."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        card = _acct(s, u, "Card", "credit-card")
        doctor = _category(s, "health.doctor")
        gifts = _custom_category(s, "Gifts", "charitable")
        odd = _custom_category(s, "Odd", "odd-tag")
        plain = _custom_category(s, "Plain", None)
        a = _txn(s, card, d(2026, 1, 1), "withdrawal", "-240", categoryId=doctor)
        _txn(s, card, d(2026, 12, 31), "deposit", "40", categoryId=doctor)
        _txn(s, card, d(2025, 12, 31), "withdrawal", "-1000", categoryId=doctor)
        _txn(s, card, d(2027, 1, 1), "withdrawal", "-1000", categoryId=doctor)
        _txn(s, card, d(2026, 6, 1), "withdrawal", "-1000", categoryId=doctor, deletedAt=ACCEPTED)
        g = _txn(s, card, d(2026, 6, 1), "withdrawal", "-300", categoryId=gifts)
        _txn(s, card, d(2026, 6, 2), "withdrawal", "-5", categoryId=odd)
        _txn(s, card, d(2026, 6, 3), "withdrawal", "-77", categoryId=plain)
        _receipt(s, u, a.id)
        _receipt(s, u, g.id, deleted=True)
        _receipt(s, u, g.id, kind="account")
        b = _book(s, u)
    got, tags, _ = _deductions(db, b)
    assert got == {
        "medical": ("Medical and dental", D("200"), 2, 1),
        "charitable": ("Charitable gifts", D("300"), 1, 0),
        "odd-tag": ("odd-tag", D("5"), 1, 0),
    }
    assert [t.tag for t in tags] == ["charitable", "medical", "odd-tag"]


def test_a_split_counts_as_its_transaction_does_but_not_in_a_loan(db):
    """A spending split counts positive under its own category's tag; a deleted split counts
    nothing, nor a split of a loan's payment, which its schedule splits (S8.7, S1.9.3)."""
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        card = _acct(s, u, "Card", "credit-card")
        loan = _acct(s, u, "Loan", "mortgage")
        doctor = _category(s, "health.doctor")
        t = _txn(s, card, d(2026, 4, 2), "withdrawal", "-100")
        _split(s, t, doctor, "-60")
        _split(s, t, None, "-40")
        _split(s, t, doctor, "-9", deleted=True)
        _receipt(s, u, t.id)
        p = _txn(s, loan, d(2026, 4, 3), "transfer", "500")
        _split(s, p, doctor, "-11")
        _txn(s, loan, d(2026, 4, 4), "transfer", "-12", categoryId=doctor)
        b = _book(s, u)
    got, _, _ = _deductions(db, b)
    assert got == {"medical": ("Medical and dental", D("60"), 1, 1)}


def test_a_loans_payments_count_their_tagged_parts_as_recorded_in_the_year(db, monkeypatch):
    """A loan's payments, split by its schedule: the parts filed under a tax-tagged category
    count (interest, property tax from escrow); untagged parts (principal, PMI) and parts of
    nothing don't; a payment only assumed as scheduled, or outside the year, isn't one made
    (S8.7, S1.9.3)."""
    from moolakata.loans import Payment

    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        loan = _acct(s, u, "Mortgage", "mortgage")
        paid = _txn(s, loan, d(2026, 2, 1), "transfer", "640")
        _receipt(s, u, paid.id)
        b = _book(s, u)
    pays = [
        Payment(d(2026, 2, 1), D(640), principal=D(500), interest=D(100), escrowTax=D(30),
                pmi=D(10), transactionId=paid.id),
        Payment(d(2026, 3, 1), D(99), interest=D(99), assumed=True),
        Payment(d(2025, 12, 31), D(1000), interest=D(1000)),
        Payment(d(2027, 1, 1), D(1000), interest=D(1000)),
        Payment(d(2026, 6, 1), D(20), escrowTax=D(20)),
        Payment(d(2026, 12, 31), D(1), interest=D(1)),
        Payment(d(2026, 1, 1), D(2), interest=D(2)),
    ]  # fmt: skip
    monkeypatch.setattr(panels.loans, "history", lambda s, a: (pays, []))
    got, _, _ = _deductions(db, b)
    assert got == {
        "loan-interest": ("Loan interest", D("103"), 3, 1),
        "property-tax": ("Property tax", D("50"), 2, 1),
    }


def test_a_book_without_accounts_has_no_deductions_but_its_estimated_payments(db):
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        b = _book(s, u)
        _payments(s, b)
    got, _, quarters = _deductions(db, b)
    assert got == {}
    assert quarters == QUARTERS


def _payments(s, book) -> None:
    fed = Filing(id=ids.new_id("Filng"), bookId=book.id, jurisdiction="federal", form="1040")
    il = Filing(id=ids.new_id("Filng"), bookId=book.id, jurisdiction="state", form="IL-1040",
                place="IL")  # fmt: skip
    st = Filing(id=ids.new_id("Filng"), bookId=book.id, jurisdiction="state", form="X")
    s.add_all([fed, il, st])
    s.flush()
    for f, q, amount, gone in (
        (fed, 2, "200", False),
        (fed, 1, "100", False),
        (fed, 1, "50", False),
        (fed, 3, "999", True),
        (il, 4, "40", False),
        (st, 1, "10", False),
    ):
        s.add(EstimatedPayment(id=ids.new_id("EstPy"), filingId=f.id, quarter=q,
                               amount=D(amount), deletedAt=ACCEPTED if gone else None))  # fmt: skip
    s.flush()


# By where, then quarter, then amount: a quarter may be paid in parts.
QUARTERS = [
    ("Federal", 1, D("50")),
    ("Federal", 1, D("100")),
    ("Federal", 2, D("200")),
    ("IL", 4, D("40")),
    ("State", 1, D("10")),
]


# ---------- giving, education, students, gifts, loans (S8.9–S8.12, S8.14.5.3) ----------


def test_giving_is_the_accepted_filers_donations_in_the_books_year(db, monkeypatch):
    asked = []
    monkeypatch.setattr(panels.giving, "donations", lambda s, who, y: asked.append((who, y)))
    with db.tx(unscoped="test") as s:
        ann, bob = _user(s, "Ann", 1980), _user(s, "Bob", 1980)
        b = _book(s, bob, ann, pending={bob})
        panels.giving_panel(s, b)
    assert asked == [([ann], YEAR)]


def _plans(monkeypatch, by_account: dict) -> None:
    """Each 529's plan, beneficiary, contributions and withdrawals, by account name."""
    ed = panels.education
    monkeypatch.setattr(ed, "plan_of", lambda s, a: by_account[a.name].get("plan"))
    monkeypatch.setattr(ed, "beneficiary", lambda s, plan: plan and plan.beneficiary)
    monkeypatch.setattr(ed, "contributions", lambda s, a: by_account[a.name].get("rows", []))
    monkeypatch.setattr(ed, "withdrawals", lambda s, a: by_account[a.name].get("years", []))


def _plan(name: str | None, person_id="p", deduction=None):
    from types import SimpleNamespace as NS

    who = None if name is None else NS(id=person_id, name=name)
    return NS(beneficiary=who, stateDeduction=deduction)


def _row(name: str, day, amount, five_year=False):
    from moolakata.education import ContributionRow

    return ContributionRow("t", day, D(amount), "owner", name, None, five_year)


def _year(year: int, taken, expenses="0", not_covered="0"):
    from moolakata.education import WithdrawalYear

    return WithdrawalYear(year, D(taken), D(expenses), D(not_covered))


def test_education_lists_each_529_with_the_years_contributions_and_withdrawals(db, monkeypatch):
    """Contributions summed by contributor, in the book's year only; the year's withdrawals
    with their expenses and what they don't cover; a plan without a beneficiary or a
    deduction shows neither (S8.10)."""
    _plans(monkeypatch, {
        "Kid 529": {
            "plan": _plan("Kid", deduction=D("500")),
            "rows": [
                _row("Grandma", d(2026, 1, 1), "100"),
                _row("Grandma", d(2026, 12, 31), "50"),
                _row("Ann", d(2026, 6, 1), "70"),
                _row("Ann", d(2025, 12, 31), "1000"),
                _row("Zed", d(2027, 1, 1), "1000"),
            ],
            "years": [_year(2025, "9"), _year(2026, "800", "600", "200"), _year(2027, "8")],
        },
        "Spare 529": {"plan": _plan(None), "years": [_year(2025, "9")]},
        "No plan 529": {},
    })  # fmt: skip
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        for name in ("Kid 529", "Spare 529", "No plan 529"):
            _acct(s, u, name, "529")
        _acct(s, u, "Brokerage", "brokerage")
        b = _book(s, u)
        rows = {r.account: r for r in panels.education_panel(s, b)}
    assert set(rows) == {"Kid 529", "Spare 529", "No plan 529"}
    kid = rows["Kid 529"]
    assert (kid.beneficiary, kid.stateDeduction) == ("Kid", D("500"))
    assert kid.contributions == [("Ann", D("70")), ("Grandma", D("150"))]
    assert (kid.distributions, kid.expenses, kid.notCovered) == (D(800), D(600), D(200))
    spare = rows["Spare 529"]
    assert (spare.beneficiary, spare.stateDeduction, spare.contributions) == ("—", None, [])
    assert (spare.distributions, spare.expenses, spare.notCovered) == (0, 0, 0)
    assert (rows["No plan 529"].beneficiary, rows["No plan 529"].stateDeduction) == ("—", None)


def _dependents(monkeypatch, *people) -> None:
    from types import SimpleNamespace as NS

    deps = [NS(row=NS(student=student), person=NS(id=pid, name=name))
            for pid, name, student in people]  # fmt: skip
    monkeypatch.setattr(panels.dependents, "listed", lambda s, book: deps)


def _document(s, book, form: str, direction="received") -> None:
    filing = None
    if direction == "filed":
        filing = Filing(id=ids.new_id("Filng"), bookId=book.id, jurisdiction="federal",
                        form="1040")  # fmt: skip
        s.add(filing)
        s.flush()
    s.add(TaxDocument(id=ids.new_id("TxDoc"), bookId=book.id, direction=direction, form=form,
                      filingId=filing and filing.id))  # fmt: skip
    s.flush()


def test_students_take_the_1098ts_received_in_turn_and_their_529_withdrawals(db, monkeypatch):
    """1098-Ts name the college, not the student: as many students have theirs as arrived, in
    the order listed; each student's withdrawals are the year's from 529s naming them
    (S8.14.5.3)."""
    _dependents(monkeypatch, ("p1", "Kim", True), ("p0", "Tod", False), ("p2", "Lee", True),
                ("p3", "Max", True))  # fmt: skip
    _plans(monkeypatch, {
        "Kim 529": {"plan": _plan("Kim", "p1"), "years": [_year(2025, "5"), _year(2026, "300")]},
        "Kim 529 b": {"plan": _plan("Kim", "p1"), "years": [_year(2026, "25")]},
        "Lee 529": {"plan": _plan("Lee", "p2"), "years": [_year(2027, "7")]},
        "Nobody 529": {"plan": _plan(None), "years": [_year(2026, "9")]},
    })  # fmt: skip
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        for name in ("Kim 529", "Kim 529 b", "Lee 529", "Nobody 529"):
            _acct(s, u, name, "529")
        _acct(s, u, "Brokerage", "brokerage")
        b = _book(s, u)
        _document(s, b, "1098-T")
        _document(s, b, "1098-T")
        _document(s, b, "1098-T", direction="filed")
        _document(s, b, "1099-INT")
        got = panels.students(s, b)
    assert [(x.name, x.received1098T, x.withdrawals529) for x in got] == [
        ("Kim", True, D("325")),
        ("Lee", True, 0),
        ("Max", False, 0),
    ]


def test_a_529_and_its_student_as_stored(db):
    """The plan, its beneficiary, the year's deposits and withdrawals, a five-year election,
    the student claimed and their 1098-T, a loan's payment and the giving, all read from the
    book's own rows: the panels each read them in the session given."""
    from moolakata import people
    from moolakata.store.entities.education import Contribution, EducationPlan
    from moolakata.store.entities.taxes import TaxBookDependent

    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        kid = people.make(s, "Kid", "male", birth_year=2006).id
        a = _acct(s, u, "Kid 529", "529")
        s.add(EducationPlan(id=ids.new_id("EdPln"), accountId=a, beneficiaryId=kid,
                            stateDeduction=D("500")))  # fmt: skip
        t = _txn(s, a, d(2026, 2, 1), "deposit", "10000")
        s.add(Contribution(id=ids.new_id("Cntrb"), transactionId=t.id, fiveYear=True))
        _txn(s, a, d(2026, 8, 1), "withdrawal", "-200")
        _txn(s, _acct(s, u, "Mortgage", "mortgage"), d(2025, 3, 1), "transfer", "1000")
        b = _book(s, u)
        s.add(TaxBookDependent(id=ids.new_id("TxDep"), bookId=b.id, personId=kid,
                               claimedAs="qualifying child", student=True))  # fmt: skip
        _document(s, b, "1098-T")
        [row] = panels.education_panel(s, b)
        [student] = panels.students(s, b)
        flagged, elections = panels.gifts_panel(s, b)
        [loan] = panels.loans_panel(s, b)
        given = panels.giving_panel(s, b)
    assert (row.account, row.beneficiary, row.contributions, row.stateDeduction) == (
        "Kid 529",
        "Kid",
        [("Ann", D("10000"))],
        D("500"),
    )
    assert (row.distributions, row.expenses, row.notCovered) == (D(200), 0, D(200))
    assert (student.name, student.received1098T, student.withdrawals529) == ("Kid", True, 200)
    assert flagged == []
    assert elections == ["Ann's 2026 five-year election to Kid 529: year 1 of 5, 2,000 a year"]
    assert (loan.account, loan.interest, loan.pmi, loan.propertyTax) == ("Mortgage", 0, 0, 0)
    # Money, even with no payment in the year: exact amounts (S13.8.2), never a bare 0.
    assert {type(v) for v in (loan.interest, loan.pmi, loan.propertyTax)} == {D}
    assert given == []


def test_no_students_means_no_rows(db, monkeypatch):
    _dependents(monkeypatch, ("p0", "Tod", False))
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        b = _book(s, u)
        assert panels.students(s, b) == []


def test_gifts_over_the_exclusion_and_the_five_year_elections_still_running(db, monkeypatch):
    """Each person given more than the exclusion by an accepted filer; and each five-year 529
    election of the filers' own 529s in its five years, the book's year counted from the
    contribution's (S8.11)."""
    from types import SimpleNamespace as NS

    monkeypatch.setattr(panels.gifts, "spending", lambda s, uid, y: NS(
        flagged=[(NS(name=f"Kid of {uid[-4:]}"), D("20000"), D("19000"))] if y == YEAR else []
    ))  # fmt: skip
    _plans(monkeypatch, {
        "Ann 529": {"rows": [
            _row("Ann", d(2022, 12, 31), "10003", five_year=True),
            _row("Ann", d(2021, 6, 1), "5000", five_year=True),
            _row("Gran", d(2026, 1, 1), "95000", five_year=True),
            _row("Gran", d(2027, 1, 1), "95000", five_year=True),
            _row("Ann", d(2026, 3, 1), "500"),
        ]},
        "Gone 529": {"rows": [_row("Ann", d(2026, 3, 1), "50000", five_year=True)]},
        "Bob 529": {"rows": [_row("Bob", d(2026, 3, 1), "50000", five_year=True)]},
    })  # fmt: skip
    with db.tx(unscoped="test") as s:
        ann, bob = _user(s, "Ann", 1980), _user(s, "Bob", 1980)
        _acct(s, ann, "Ann 529", "529")
        _acct(s, ann, "Gone 529", "529", deletedAt=ACCEPTED)
        _acct(s, ann, "Brokerage", "brokerage")
        _acct(s, bob, "Bob 529", "529")
        b = _book(s, bob, ann, pending={bob})
        flagged, elections = panels.gifts_panel(s, b)
    assert [(g.giver, g.person, g.given, g.exclusion) for g in flagged] == [
        ("Ann", f"Kid of {ann[-4:]}", D("20000"), D("19000"))
    ]
    assert elections == [
        "Ann's 2022 five-year election to Ann 529: year 5 of 5, 2,001 a year",
        "Gran's 2026 five-year election to Ann 529: year 1 of 5, 19,000 a year",
    ]


def test_a_loans_row_sums_the_years_recorded_payments_and_names_what_secures_it(db, monkeypatch):
    """A mortgage's or HELOC's 1098 and a student loan's 1098-E: the interest, PMI and escrowed
    property tax of the year's payments made, never those only assumed as scheduled; other
    loans have no such form (S8.12)."""
    from types import SimpleNamespace as NS

    from moolakata.loans import Payment
    from moolakata.store.entities.assets import Item

    pays = [
        Payment(d(2026, 1, 1), D(0), interest=D(100), pmi=D(10), escrowTax=D(30)),
        Payment(d(2026, 12, 31), D(0), interest=D(1), pmi=D(2), escrowTax=D(3)),
        Payment(d(2026, 6, 1), D(0), interest=D(500), pmi=D(50), escrowTax=D(70), assumed=True),
        Payment(d(2025, 12, 31), D(0), interest=D(900)),
        Payment(d(2027, 1, 1), D(0), interest=D(900)),
    ]
    monkeypatch.setattr(panels.loans, "history", lambda s, a: (pays, []))
    with db.tx(unscoped="test") as s:
        u = _user(s, "Ann", 1980)
        house = _acct(s, u, "House", "real-estate")
        it = Item(id=ids.new_id("Item"), accountId=house, name="12 Elm St",
                  acquiredOn=d(2020, 1, 1), costBasis=D(1))  # fmt: skip
        s.add(it)
        for name, type_ in (("Mortgage", "mortgage"), ("HELOC", "heloc"),
                            ("School", "student-loan"), ("Car", "auto-loan")):  # fmt: skip
            _acct(s, u, name, type_)
        b = _book(s, u)
        secured = {"Mortgage": it.id, "HELOC": None}
        monkeypatch.setattr(panels.loans, "loan_of", lambda s, a: (
            NS(securedById=secured[a.name]) if a.name in secured else None
        ))  # fmt: skip
        rows = {r.account: r for r in panels.loans_panel(s, b)}
    assert set(rows) == {"Mortgage", "HELOC", "School"}
    m = rows["Mortgage"]
    assert (m.kind, m.interest, m.pmi, m.propertyTax, m.securedBy) == (
        "1098",
        D(101),
        D(12),
        D(33),
        "12 Elm St",
    )
    assert (rows["HELOC"].kind, rows["HELOC"].securedBy) == ("1098", None)
    assert (rows["School"].kind, rows["School"].securedBy) == ("1098-E", None)


# ---------- the spouses whose accounts count for wash sales (S3.8) ----------


def _marry(s, a: str, b: str, start=None, end=None, confirmed=True) -> None:
    from moolakata import people
    from moolakata.store.entities.education import Relationship

    at = ACCEPTED if confirmed else None
    s.add(Relationship(id=ids.new_id("Rltn"), person1Id=people.of_user(s, a).id,
                       person2Id=people.of_user(s, b).id, relation="spouse", fromDate=start,
                       toDate=end, confirmed1At=at, confirmed2At=at))  # fmt: skip
    s.flush()


def test_a_spouse_at_any_time_in_the_year_brings_their_accounts(db):
    """Filing separately, a filer's wash sales reach the accounts of whoever was married to
    them on the year's first day, its last, or from a day in it; a spouse who is a filer too,
    or one married before or after the year only, brings none (S3.8)."""
    with db.tx(unscoped="test") as s:
        ann = _user(s, "Ann", 1980)
        jan = _user(s, "Jan", 1980)  # until March: married on January 1
        dec = _user(s, "Dec", 1980)  # from November: married on December 31
        mid = _user(s, "Mid", 1980)  # March to September: married from a day in the year
        old = _user(s, "Old", 1980)  # ended on the year's first day
        new = _user(s, "New", 1980)  # from the next year
        unconfirmed = _user(s, "Unconfirmed", 1980)
        _marry(s, ann, jan, d(2010, 1, 1), d(2026, 3, 1))
        _marry(s, ann, mid, d(2026, 3, 1), d(2026, 9, 1))
        _marry(s, ann, dec, d(2026, 11, 1))
        _marry(s, ann, old, d(2000, 1, 1), d(2026, 1, 1))
        _marry(s, ann, new, d(2027, 1, 1))
        _marry(s, ann, unconfirmed, d(2026, 2, 1), confirmed=False)
        accounts = {}
        for who, name in ((jan, "Jan"), (dec, "Dec"), (mid, "Mid"), (old, "Old"),
                          (new, "New"), (unconfirmed, "Unconfirmed")):  # fmt: skip
            accounts[name] = _acct(s, who, f"{name} brokerage", "brokerage")
            _acct(s, who, f"{name} closed", "brokerage", deletedAt=ACCEPTED)
        _acct(s, dec, "Dec IRA", "ira")
        b = _book(s, ann)
        got = [a.name for a in panels.spouse_accounts(s, b)]
    order = sorted([(jan, "Jan"), (dec, "Dec"), (mid, "Mid")])
    assert sorted(got) == sorted(["Jan brokerage", "Dec brokerage", "Dec IRA", "Mid brokerage"])
    # Spouse by spouse, in a fixed order.
    assert [n.split()[0] for n in got if n != "Dec IRA"] == [n for _, n in order]


def test_a_spouse_filing_on_the_same_book_brings_nothing_more(db):
    with db.tx(unscoped="test") as s:
        ann, bob = _user(s, "Ann", 1980), _user(s, "Bob", 1980)
        _marry(s, ann, bob, d(2010, 1, 1))
        _acct(s, bob, "Bob brokerage", "brokerage")
        b = _book(s, ann, bob)
        assert panels.spouse_accounts(s, b) == []
