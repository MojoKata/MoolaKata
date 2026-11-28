"""A record's stamps (requirements S14, schema.md §2): the store stamps `updatedAt` and moves the
version of every record a save sets a field on, even to the value it had; a handler stamps one
by hand only where the change is in rows of their own (its lines, its accounts, its keys), so
the record's version still moves with it."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import budget_accounts, change, make, saved, wallet
from test_accounts import new_account
from test_budgets import plan, setup_budget
from test_moves import move, moves_on
from test_store import new_user
from test_wallets import ZPUB

from moolakata import clock
from moolakata.store.entities.users import User

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def later(hours: int = 1) -> None:
    clock.fix(clock.now() + dt.timedelta(hours=hours))


def test_a_field_set_to_the_value_it_had_still_stamps_the_record(db, frozen):
    """The store's own stamp (schema.md §2): a save that sets a field, to the same value or
    not, moves the record's version and its `updatedAt`, so a handler needn't."""
    with db.tx(unscoped="test") as s:
        u = new_user(s)
    later()
    with db.tx(unscoped="test") as s:
        x = s.get(User, u.id)
        x.displayName = x.displayName
    with db.read(unscoped="test") as s:
        x = s.get(User, u.id)
        assert (x.version, x.updatedAt, x.createdAt) == (2, clock.now(), T0)


def test_a_budgets_version_moves_with_its_lines_accounts_and_moves(server, frozen):
    """S7.1.7, S7.2, S7.3: a budget's plan lines, its accounts and its moves are rows of their
    own; a change to them is the budget's too, so a draft read before it is stale."""
    c, acct, cat, b = setup_budget(server)

    def version() -> int:
        return c.get(f"/ui/api/budgets/{b['id']}").json()["version"]

    v = version()
    later()
    plan(c, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "600.00"}])
    assert version() == v + 1
    other = new_account(c, name="Savings", type="savings")
    later()
    assert budget_accounts(c, b, [acct["id"], other["id"]]).status_code == 200
    assert version() == v + 2
    moves_on(c, b)
    v = version()
    later()
    moved = move(c, b, month="2026-10-01", fromCategoryId=cat["Food"],
                 toCategoryId=cat["Travel"], amount="5")  # fmt: skip
    assert moved.status_code == 200, moved.text
    assert version() == v + 1


def test_a_portfolios_version_moves_with_its_accounts(admin_client, frozen):
    """S5.1: a portfolio's accounts are rows of their own; a change to them alone is the
    portfolio's too."""
    a, other = new_account(admin_client), new_account(admin_client, name="Savings")
    p = make(admin_client, "Portf", name="Growth", accountIds=[a["id"]], benchmark="60-40").json()
    later()
    q = saved(change(admin_client, "Portf", p, accountIds=[a["id"], other["id"]]))
    assert q["version"] == p["version"] + 1


def test_a_price_sources_version_moves_with_its_key_alone(admin_client, frozen):
    """S4.2.3: a source's key is a secret's row; given alone, the source's version moves."""
    src = make(admin_client, "Src", name="tiingo").json()
    later()
    keyed = saved(change(admin_client, "Src", src, apiKey="abcdef0123456789"))
    assert keyed["version"] == src["version"] + 1


def test_a_profiles_version_moves_with_its_persons_fields(server, frozen):
    """S12.2.16, S10.10.1: the sex and birthday a profile shows are its person's; changed
    alone, the user's version moves too."""
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    me = jane.get("/ui/api/profile").json()
    later()
    saved(change(jane, "User", me, birthYear=1980))
    assert jane.get("/ui/api/profile").json()["version"] == me["version"] + 1


def test_a_wallet_accounts_version_moves_with_its_keys_alone(server, frozen):
    """S1.6.1: a wallet's keys are rows of their own; changed alone, the account's version
    moves."""
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    w = new_account(jane, name="Cold storage", type="crypto-wallet")
    w = saved(wallet(jane, w["id"], ZPUB))  # its first keys name its node wallet, a field
    later()
    again = saved(wallet(jane, w["id"], ZPUB + "\n3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"))
    assert again["version"] == w["version"] + 1


def test_marked_reviewed_again_says_when_it_was_last(server, frozen):
    """S7.14: a month marked reviewed again says the later time, which the store stamps."""
    c, _, _, b = setup_budget(server)
    base = f"/ui/api/budgets/{b['id']}/review"
    assert c.post(base, json={"month": "2026-09-01"}).status_code == 200
    first = c.get(base, params={"month": "2026-09"}).json()["reviewed"]
    later()
    assert c.post(base, json={"month": "2026-09-01"}).status_code == 200
    again = c.get(base, params={"month": "2026-09"}).json()["reviewed"]
    assert dt.datetime.fromisoformat(first["at"]) == T0
    assert dt.datetime.fromisoformat(again["at"]) == T0 + dt.timedelta(hours=1)
