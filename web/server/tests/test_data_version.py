"""The data version (docs/schema.md §8) and the budget months kept under it (requirements
S7.3.10)."""

import datetime as dt

import pytest
from sqlalchemy import update
from test_accounts import add
from test_budgets import month, plan, row, setup_budget

from moolakata import budgets, clock
from moolakata.budgets import cache
from moolakata.store import data_version
from moolakata.store.entities.accounts import Transaction
from moolakata.store.entities.budgets import Budget
from moolakata.store.tables import metadata

T0 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def _triggers(s) -> dict[str, str]:
    rows = s.connection().exec_driver_sql(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
    )
    return {name: sql for name, sql in rows}


def test_every_table_moves_the_version_or_says_why(server):
    """A write to any table but those declared otherwise moves the version: three triggers
    each, as the declarations make them, and none on a table declared not an input."""
    wanted = set(data_version.create_all_sql(metadata))
    with server.db.read(unscoped="test") as s:
        have = _triggers(s)
    made = {sql for name, sql in have.items() if name.startswith(data_version.PREFIX)}
    assert made == wanted
    inputs = {t.name for t in data_version.inputs(metadata)}
    for t in metadata.sorted_tables:
        ours = {n for n in have if n.startswith(f"{data_version.PREFIX}{t.name}_")}
        if t.name in inputs:
            assert len(ours) == 3, t.name
        else:
            assert t.info["notFigures"].strip(), t.name
            assert not ours, t.name


def test_a_write_moves_the_version_when_it_commits(server, frozen):
    c, acct, _, _ = setup_budget(server)
    t = add(c, acct["id"], "-50.00", "2026-10-03", payee="Kroger")
    with server.db.read(unscoped="test") as s:
        before = data_version.read(s)
    with server.db.tx(unscoped="test") as w:
        w.execute(update(Transaction).where(Transaction.id == t["id"]).values(amount=-80))
        with server.db.read(unscoped="test") as s:
            assert data_version.read(s) == before  # not committed: no one else sees it
        assert data_version.read(w) == before + 1
    with server.db.read(unscoped="test") as s:
        assert data_version.read(s) == before + 1


def test_a_month_worked_out_during_a_write_is_kept_under_the_older_version(server, frozen):
    """The race the generation had: a read between a write's flush and its commit worked the
    month out without the write and kept it as if after it."""
    c, acct, cat, b = setup_budget(server)
    plan(c, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    t = add(
        c, acct["id"], "-50.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"]
    )
    alice = c.get("/ui/api/session").json()["user"]["id"]
    cache.clear()
    with server.db.tx(unscoped="test") as w:
        w.execute(update(Transaction).where(Transaction.id == t["id"]).values(amount=-80))
        w.flush()
        with server.db.read(user=alice) as s:
            m = budgets.month_view(
                s, s.get(Budget, b["id"]), dt.date(2026, 10, 1), T0.date(), alice
            )
            assert [r.actual for r in m.rows if r.label == "Food"] == [50]
    assert row(month(c, b, "2026-10"), "Food")["actual"] == "80.00"


def test_writes_outside_the_orm_are_seen_and_refresh_works_again(server, frozen):
    c, acct, cat, b = setup_budget(server)
    plan(c, b, "2026-10-01", [{"categoryId": cat["Food"], "amount": "300.00"}])
    t = add(
        c, acct["id"], "-50.00", "2026-10-03", payee="Kroger", categoryId=cat["Food › Groceries"]
    )
    assert row(month(c, b, "2026-10"), "Food")["actual"] == "50.00"
    with server.db.tx(unscoped="test") as s:
        s.execute(update(Transaction).where(Transaction.id == t["id"]).values(amount=-80))
    assert row(month(c, b, "2026-10"), "Food")["actual"] == "80.00"
    r = c.post(f"/ui/api/budgets/{b['id']}/refresh", params={"month": "2026-10"})
    assert r.status_code == 200, r.text
    assert row(r.json(), "Food")["actual"] == "80.00"


def test_only_a_reads_months_are_kept(server, frozen):
    c, _, _, b = setup_budget(server)
    alice = c.get("/ui/api/session").json()["user"]["id"]
    cache.clear()
    with server.db.tx(user=alice) as w:
        budgets.month_view(w, w.get(Budget, b["id"]), dt.date(2026, 10, 1), T0.date(), alice)
    assert len(cache._months) == 0
    with server.db.read(user=alice) as s:
        budgets.month_view(s, s.get(Budget, b["id"]), dt.date(2026, 10, 1), T0.date(), alice)
    assert len(cache._months) == 1


def test_a_kept_month_that_differs_from_its_data_is_caught(server, frozen):
    """CHECK, on in every test, works a kept month out again and fails on a difference."""
    c, _, _, b = setup_budget(server)
    alice = c.get("/ui/api/session").json()["user"]["id"]
    cache.clear()
    month(c, b, "2026-10")
    ((key, kept),) = list(cache._months.items())
    cache._months[key] = type(kept)(**{**kept.__dict__, "spent": kept.spent + 1})
    with server.db.read(user=alice) as s, pytest.raises(cache.Stale):
        budgets.month_view(s, s.get(Budget, b["id"]), dt.date(2026, 10, 1), T0.date(), alice)
