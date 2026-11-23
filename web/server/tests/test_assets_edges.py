"""Physical assets' edges (requirements S1.10): each rule of an item's worth, its form and a
home's residence periods pinned on the case that tells it apart, on plain values where the code
allows and through the save where the rule spans records."""

import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest
from conftest import make_user, sign_in
from edits import make, sell
from sqlalchemy import select
from test_accounts import new_account

from moolakata import assets, clock, ids
from moolakata.errors import Problem
from moolakata.store.entities.accounts import Account, Loan
from moolakata.store.entities.assets import Item, ResidencePeriod
from moolakata.store.entities.education import Person
from moolakata.store.entities.users import User
from moolakata.ui import items as UI

d = dt.date
T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def book(server, frozen):
    """A session on the test household, unscoped as the server's own work reads it, and the
    first admin's id to own what a test adds; nothing it adds is kept."""
    with server.db.tx(unscoped="test") as s:
        yield s, s.scalars(select(User.id)).first()
        s.rollback()


@pytest.fixture
def jane(server, frozen):
    make_user(server, "jane")
    return sign_in(server, "jane")


def _account(s, uid, type="real-estate", name="Homes", id=None) -> Account:
    a = Account(id=id or ids.new_id("Acct"), ownerId=uid, name=name, type=type)
    s.add(a)
    s.flush()
    return a


def _home(s, a, **kw) -> Item:
    kw = {"name": "Elm St", "acquiredOn": d(2015, 3, 1), "costBasis": D(1), **kw}
    it = Item(id=ids.new_id("Item"), accountId=a.id, **kw)
    s.add(it)
    s.flush()
    return it


def _person(s, uid, name="Ann Doe") -> Person:
    p = Person(id=ids.new_id("Persn"), name=name, sex="female", ownerId=uid)
    s.add(p)
    s.flush()
    return p


def _lived(s, home, who, start, end=None, id=None) -> ResidencePeriod:
    p = ResidencePeriod(
        id=id or ids.new_id("RsPrd"), itemId=home.id, personId=who.id, fromDate=start, toDate=end
    )
    s.add(p)
    s.flush()
    return p


def _raised(fn) -> tuple[int, str, str, list[tuple[str | None, str, str]]]:
    """The problem `fn` raises: its status, code and words, and each refusal's."""
    with pytest.raises(Problem) as got:
        fn()
    p = got.value
    return p.status, p.code, p.detail, [(e.field, e.code, e.message) for e in p.errors]


def _me(c) -> str:
    """The caller's own person (S10.10.1)."""
    return next(p["id"] for p in c.get("/ui/api/persons").json()["items"] if p["relation"] == "you")


def _made(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def _item(c, account_id, **kw) -> dict:
    return _made(make(c, "Item", **{"accountId": account_id, "costBasis": "1", **kw}))


def _period(c, home_id, person_id, **kw) -> dict:
    return _made(make(c, "RsPrd", **{"itemId": home_id, "personId": person_id, **kw}))


def _updates(c, *changes) -> list[dict]:
    """An update op for each (item, fields), at the version the item has now."""
    ops = []
    for it, fields in changes:
        now = c.get(f"/ui/api/items/{it['id']}").json()
        ops.append({"op": "update", "entity": "Item", "id": it["id"], "version": now["version"],
                    "fields": fields})  # fmt: skip
    return ops


# assets.periods_of, five_years_before, years_lived_in, series; ui.items._secured, _period_out,
# _values, _item_update, _outside, _periods_owned, _period_owned


def test_a_homes_periods_come_in_order_of_their_start_and_then_their_id(book):
    """S1.10.4: a home's residence periods are listed by their start; two starting on one day
    by their id, so the order never changes between reads."""
    s, uid = book
    home = _home(s, _account(s, uid))
    ann, bob = _person(s, uid), _person(s, uid, "Bob Doe")
    first, second, third = sorted(ids.new_id("RsPrd") for _ in range(3))
    _lived(s, home, ann, d(2017, 1, 1), id=second)
    _lived(s, home, bob, d(2017, 1, 1), id=first)
    _lived(s, home, ann, d(2016, 1, 1), d(2016, 12, 31), id=third)
    assert [p.id for p in assets.periods_of(s, home.id)] == [third, first, second]


def test_five_years_before_a_day_is_the_same_day_five_years_earlier():
    assert assets.five_years_before(d(2024, 3, 1)) == d(2019, 3, 1)
    assert assets.five_years_before(d(2023, 2, 28)) == d(2018, 2, 28)


def test_the_years_lived_in_count_from_none_in_years_of_365_25_days():
    """S8.13: a person's time lived in is their days, from none, over 365.25, to a tenth: 18
    days are 0.0 years and 19 are 0.1; 420 days are 1.1 years and 421 are 1.2."""
    home = NS(acquiredOn=d(2010, 1, 1))
    sold = d(2024, 6, 30)

    def lived(days):
        return assets.years_lived_in(
            home, sold, [NS(fromDate=d(2022, 1, 1), toDate=d(2022, 1, 1) + dt.timedelta(days=days))]
        )

    assert [lived(n) for n in (18, 19, 420, 421)] == [0.0, 0.1, 1.1, 1.2]


def test_an_account_with_no_items_is_worth_a_decimal_nothing_each_day(book):
    """R1.9: amounts are `Decimal` end to end, an account with no items' value too."""
    s, uid = book
    a = _account(s, uid, type="collectables", name="Coll")
    got = assets.series(s, a, d(2026, 10, 12), d(2026, 10, 13))
    assert got == [(d(2026, 10, 12), D(0)), (d(2026, 10, 13), D(0))]
    assert all(type(v) is D for _, v in got)


def test_an_items_loans_are_listed_in_the_order_they_were_made(book):
    """S1.9.5, S1.10.4: the loans an item secures, each live loan's account with what is owed,
    in the order the loans were made (their ids), whatever their accounts' ids."""
    s, uid = book
    home = _home(s, _account(s, uid))
    low, high = sorted(ids.new_id("Acct") for _ in range(2))
    older, newer = sorted(ids.new_id("Loan") for _ in range(2))
    for account_id, name, loan_id in ((low, "Second", newer), (high, "First", older)):
        a = _account(s, uid, type="mortgage", name=name, id=account_id)
        s.add(Loan(id=loan_id, accountId=a.id, principal=D(1000), startDate=d(2026, 11, 1),
                   termMonths=12, rate=D(5), securedById=home.id))  # fmt: skip
    s.flush()
    got = UI._secured(s, [home.id], d(2026, 10, 13))[home.id]
    assert [(x.accountId, x.name) for x in got] == [(high, "First"), (low, "Second")]


def test_a_period_names_its_person_whoever_reads_it():
    """S1.10.4, R3.14: a residence period carries its person's name, from the names read."""
    p = ResidencePeriod(id="RsPrd_x", itemId="Item_x", personId="Persn_ann",
                        fromDate=d(2016, 1, 1), version=3)  # fmt: skip
    out = UI._period_out(p, {"Persn_bob": "Bob Doe", "Persn_ann": "Ann Doe"})
    assert (out.personId, out.personName, out.version) == ("Persn_ann", "Ann Doe", 3)


def test_a_givers_holding_is_refused_off_a_gift_and_after_the_day_given_in_its_words(frozen):
    """S1.10.1, R3.7: held since is only for a gift, and on or before the date acquired; each
    is refused at its field in its words."""

    def refused(**kw):
        body = UI.ItemIn(name="Cup", acquiredOn=d(2024, 1, 10), costBasis=D(1), **kw)
        return _raised(lambda: UI._values(body, "collectables"))

    assert refused(heldFrom=d(2001, 5, 1)) == (
        422, "held-from-not-gift", "Only for a gift.",
        [("heldFrom", "held-from-not-gift", "Only for a gift.")],
    )  # fmt: skip
    assert refused(heldFrom=d(2024, 1, 11), acquiredHow="gift") == (
        422, "held-from-after", "On or before the day acquired.",
        [("heldFrom", "held-from-after", "On or before the day acquired.")],
    )  # fmt: skip


def test_each_home_whose_dates_change_in_one_save_is_checked_against_its_own_periods(jane):
    """S1.10.4: two homes' dates changed in one save, each is checked against its own
    residence periods: the second's refused though the first's fit."""
    me = _me(jane)
    homes = new_account(jane, name="Homes", type="real-estate")
    elm = _item(jane, homes["id"], name="Elm St", acquiredOn="2015-03-01")
    oak = _item(jane, homes["id"], name="Oak St", acquiredOn="2015-03-01")
    _period(jane, elm["id"], me, fromDate="2015-03-01", toDate="2015-12-31")
    _period(jane, oak["id"], me, fromDate="2016-01-01")
    ops = _updates(jane, (elm, {"acquiredOn": "2015-02-01"}), (oak, {"acquiredOn": "2016-02-01"}))
    r = jane.post("/ui/api/save", json={"ops": ops})
    assert r.status_code == 422, r.text
    why = "The residence period from Jan 1, 2016 starts before this."
    assert [(e["field"], e["code"], e["message"], e["id"]) for e in r.json()["errors"]] == [
        ("acquiredOn", "periods-outside", why, oak["id"])
    ]


def test_a_sale_moved_is_checked_for_each_person_who_lived_in_the_home(jane):
    """S1.10.4: a home's sale day moved later runs every open period on to it; each person's
    is checked against their other homes, the second person's too though the first's fit."""
    ann = _made(make(jane, "Persn", name="Ann Doe", sex="female"))["id"]
    me = _me(jane)
    first, second = sorted([me, ann])
    homes = new_account(jane, name="Homes", type="real-estate")
    pine = _item(jane, homes["id"], name="Pine St", acquiredOn="2014-01-01")
    elm = _item(jane, homes["id"], name="Elm St", acquiredOn="2015-01-01")
    assert sell(jane, pine["id"], "2015-05-31", "1").status_code == 200
    for who in (first, second):
        _period(jane, pine["id"], who, fromDate="2014-02-01")  # open: up to the sale
    _period(jane, elm["id"], second, fromDate="2015-06-01")
    r = jane.post("/ui/api/save", json={"ops": _updates(jane, (pine, {"soldOn": "2015-06-15"}))})
    assert r.status_code == 422, r.text
    name = "Jane" if second == me else "Ann Doe"
    why = f"{name}'s main home then was Elm St (from Jun 1, 2015)."
    assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [
        ("soldOn", "periods-overlap", why)
    ]


def test_a_period_falls_outside_its_home_where_it_passes_either_end_and_never_on_them():
    """S1.10.4: a period falls outside a home's days owned when it starts before the date
    acquired, starts after the sale or ends after it, each at its date and all at once; one
    on either day is within them, and a home not sold has no end."""
    sold = NS(acquiredOn=d(2015, 3, 1), soldOn=d(2020, 6, 30))
    held = NS(acquiredOn=d(2015, 3, 1), soldOn=None)

    def outside(home, start, end=None):
        return UI._outside(home, NS(fromDate=start, toDate=end))

    assert outside(sold, d(2015, 3, 1), d(2020, 6, 30)) == []
    assert outside(sold, d(2020, 6, 30)) == []
    assert outside(sold, d(2015, 2, 28)) == [("fromDate", "starts before")]
    assert outside(sold, d(2020, 7, 1)) == [("fromDate", "starts after")]
    assert outside(sold, d(2016, 1, 1), d(2020, 7, 1)) == [("toDate", "ends after")]
    assert outside(sold, d(2015, 2, 28), d(2020, 7, 1)) == [
        ("fromDate", "starts before"),
        ("toDate", "ends after"),
    ]
    assert outside(sold, d(2020, 7, 1), d(2020, 7, 2)) == [
        ("fromDate", "starts after"),
        ("toDate", "ends after"),
    ]
    assert outside(held, d(2030, 1, 1), d(2031, 1, 1)) == []
    assert outside(held, d(2015, 2, 28), d(2031, 1, 1)) == [("fromDate", "starts before")]


def test_a_homes_new_dates_are_refused_once_each_naming_the_first_period_outside(book):
    """S1.10.4, R3.7: a home's dates that leave periods outside are refused at each date once,
    naming the first period outside it, both dates at once: the date acquired for a period
    starting before it, the sale day for one starting or ending after it."""
    s, uid = book
    home = _home(s, _account(s, uid), acquiredOn=d(2015, 6, 1), soldOn=d(2020, 6, 30),
                 proceeds=D(1))  # fmt: skip
    ann = _person(s, uid)
    _lived(s, home, ann, d(2015, 3, 1), d(2016, 1, 1))  # starts before
    _lived(s, home, ann, d(2015, 4, 1), d(2020, 12, 31))  # starts before and ends after
    _lived(s, home, ann, d(2020, 7, 1))  # starts after
    ctx = NS(s=s, notes={})
    why = "The residence period from {} {} this."
    assert _raised(lambda: UI._periods_owned(ctx, home)) == (
        422, "periods-outside", why.format("Mar 1, 2015", "starts before"),
        [("acquiredOn", "periods-outside", why.format("Mar 1, 2015", "starts before")),
         ("soldOn", "periods-outside", why.format("Apr 1, 2015", "ends after"))],
    )  # fmt: skip


def test_a_period_starting_after_the_sale_is_refused_at_the_sale_day(book):
    """S1.10.4: a period starting after a home's new sale day is refused at it; one ending
    on it is within the days owned."""
    s, uid = book
    home = _home(s, _account(s, uid), acquiredOn=d(2015, 1, 1), soldOn=d(2020, 6, 30),
                 proceeds=D(1))  # fmt: skip
    ann = _person(s, uid)
    _lived(s, home, ann, d(2015, 1, 1), d(2020, 6, 30))
    _lived(s, home, ann, d(2020, 7, 1))
    why = "The residence period from Jul 1, 2020 starts after this."
    assert _raised(lambda: UI._periods_owned(NS(s=s, notes={}), home)) == (
        422, "periods-outside", why, [("soldOn", "periods-outside", why)]
    )  # fmt: skip


def test_a_homes_new_dates_skip_only_the_periods_the_same_save_makes_or_changes(book):
    """S1.10.4: a period the save makes or changes is checked on its own, so the home's dates
    aren't refused for it; every other period still is, one after it included."""
    s, uid = book
    home = _home(s, _account(s, uid), acquiredOn=d(2015, 6, 1))
    ann = _person(s, uid)
    touched = _lived(s, home, ann, d(2015, 3, 1), d(2020, 12, 31))
    _lived(s, home, ann, d(2015, 4, 1), d(2016, 1, 1))
    ctx = NS(s=s, notes={})
    UI._touched(ctx).add(touched.id)
    why = "The residence period from Apr 1, 2015 starts before this."
    assert _raised(lambda: UI._periods_owned(ctx, home))[3] == [
        ("acquiredOn", "periods-outside", why)
    ]
    UI._touched(ctx).update(p.id for p in assets.periods_of(s, home.id))
    UI._periods_owned(ctx, home)  # every one touched: nothing refused


def test_a_period_is_refused_where_it_falls_outside_its_home_in_its_words(book):
    """S1.10.4, R3.7: a period made or changed is refused at each end outside the home's days
    owned: before the date acquired, or after the sale, both at once; within them, kept."""
    s, uid = book
    home = _home(s, _account(s, uid), acquiredOn=d(2015, 3, 1), soldOn=d(2020, 6, 30),
                 proceeds=D(1))  # fmt: skip
    ann = _person(s, uid)
    ctx = NS(s=s, notes={})

    def refused(start, end=None):
        p = _lived(s, home, ann, start, end)
        return _raised(lambda: UI._period_owned(ctx, p.id))

    before = ("fromDate", "before-acquired", "On or after the day acquired.")
    starts_after = ("fromDate", "after-sold", "Not after the sale.")
    ends_after = ("toDate", "after-sold", "Not after the sale.")
    assert refused(d(2015, 2, 28), d(2015, 12, 31)) == (422, *before[1:], [before])
    assert refused(d(2020, 7, 1)) == (422, *starts_after[1:], [starts_after])
    assert refused(d(2016, 1, 1), d(2020, 7, 1)) == (422, *ends_after[1:], [ends_after])
    assert refused(d(2015, 2, 28), d(2020, 7, 1))[3] == [before, ends_after]
    UI._period_owned(ctx, _lived(s, home, ann, d(2015, 3, 1), d(2020, 6, 30)).id)


def test_a_period_on_a_home_deleted_in_the_same_save_is_not_checked(book):
    """S1.10.4: a home deleted has no days owned to fall outside of: its period, changed in the
    same save, is let through."""
    s, uid = book
    home = _home(s, _account(s, uid))
    p = _lived(s, home, _person(s, uid), d(2015, 2, 1))
    home.mark_deleted(None)
    s.flush()
    UI._period_owned(NS(s=s, notes={}), p.id)
    assert s.get(ResidencePeriod, p.id).fromDate == d(2015, 2, 1)
