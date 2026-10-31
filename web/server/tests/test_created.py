"""Every 201 of the API, walked on a seeded server (requirements S13.8.4, B38): each route that
makes something is called, and the `Location` it answers, if any, reads what was made."""

import pytest
from conftest import sign_in
from edits import option_trade, saved
from sqlalchemy import select
from test_receipts import png

from moolakata import contract
from moolakata.app import Server

# Routes the walk can't call on one server, each with why.
NOT_WALKED = {
    "/ui/api/settings/links/join": "a code from another server's invitation (test_links)",
}

# What no route reads, by its id or in a list, so its 201 names no Location (S13.8.4).
READ_NOWHERE = [
    "/ui/api/settings/links/invitations",
    "/ui/api/settings/connector/pairings",
    "/ui/api/accounts/{account_id}/options/{instrument_id}/settle",
]


@pytest.fixture
def seeded(store, keyed_config):
    from moolakata.dev import seed
    from moolakata.store.repos.ledger import ensure_categories

    srv = Server(config=keyed_config, store=store, ready=True)
    with srv.db.tx(unscoped="test") as s:
        ensure_categories(s)
    seed.seed(srv)
    return srv, seed.PASSWORD


def ids(srv) -> dict[str, str]:
    """The seeded records the walk's calls name."""
    from moolakata.store.entities.accounts import Account, Instrument, Lot, Transaction
    from moolakata.store.entities.assets import Item
    from moolakata.store.entities.education import Person
    from moolakata.store.entities.giving import Organisation
    from moolakata.store.entities.taxes import TaxBook
    from moolakata.store.entities.users import User

    with srv.db.read(unscoped="test") as s:
        users = {u.username: u for u in s.scalars(select(User))}
        alice = users["alice"]
        acct = {a.type: a.id for a in s.scalars(select(Account).where(Account.ownerId == alice.id))}
        held = s.scalars(
            select(Instrument)
            .join(Lot, Lot.instrumentId == Instrument.id)
            .where(Lot.accountId == acct["brokerage"], Instrument.instrumentClass != "option")
        ).first()
        item = s.scalars(select(Item).where(Item.accountId == acct["collectables"])).first()
        kid = s.scalars(
            select(Person).where(Person.id.not_in([u.personId for u in users.values()]))
        ).first()
        book = s.scalars(select(TaxBook).where(TaxBook.ownerId == alice.id)).first()
        from moolakata.store.entities.accounts import Category
        from moolakata.store.entities.budgets import Budget

        budget = s.scalars(select(Budget).where(Budget.ownerId == alice.id)).first()
        cats = {c.builtIn: c.id for c in s.scalars(select(Category))}
        deposit = s.scalars(
            select(Transaction).where(
                Transaction.accountId == acct["checking"],
                Transaction.amount > 5,
                Transaction.transferId.is_(None),
                Transaction.instrumentId.is_(None),
            )
        ).first()
        org = s.scalars(select(Organisation)).first()
        return {
            **{f"acct:{k}": v for k, v in acct.items()},
            "instrument": held.id,
            "item": item.id,
            "kid": kid.id,
            "me": alice.personId,
            "alice": alice.id,
            "book": book.id,
            "org": org.id,
            "year": str(book.year + 1),
            "deposit": deposit.id,
            "budget": budget.id,
            "cat:food": cats["food"],
            "cat:personal": cats["personal"],
        }


def calls(i: dict[str, str]):
    """Each 201 route: who calls it, its path filled in, and its body (a callable is given the
    answers so far, for a call that needs what an earlier one made)."""
    brk = i["acct:brokerage"]
    edu = i["acct:529"]
    return {
        "/ui/api/settings/links/invitations": ("admin", None, None),
        "/ui/api/settings/connector/pairings": ("admin", None, None),
        "/ui/api/budgets/{budget_id}/copy": (
            "alice",
            {"budget_id": i["budget"]},
            {"name": "Household, envelope", "method": "envelope"},
        ),
        "/ui/api/accounts/{account_id}/options/{instrument_id}/settle": (
            "alice",
            lambda made: {"account_id": brk, "instrument_id": made["option"]},
            {"how": "expired", "date": "2026-12-18"},
        ),
        "/ui/api/receipts": ("alice", None, "receipt"),
        "/ui/api/accounts/{account_id}/goal": ("alice", {"account_id": edu}, None),
    }


def test_every_201_answers_a_location_that_reads_what_it_made(seeded):
    srv, pw = seeded
    i = ids(srv)
    todo = calls(i)
    routes = [
        path
        for path, ops in contract.openapi_document()["paths"].items()
        if "201" in ops.get("post", {}).get("responses", {})
    ]
    assert len(routes) > 5
    assert sorted(set(routes) - set(todo) - set(NOT_WALKED)) == [], "walk every 201 route"
    clients = {who: sign_in(srv, who, pw) for who in ("admin", "alice")}
    # An option trade is a transaction of the save's (S3.2): the option made ahead.
    made: dict[str, str] = {}
    trade = saved(option_trade(clients["alice"], i["acct:brokerage"], "2026-10-01", "buy-to-open",
                               "AAPL", "call",
                               300, "2026-12-18", 1, 3))  # fmt: skip
    made["option"] = trade["instrumentId"]
    failed, unnamed = [], []
    for path, (who, params, body) in todo.items():
        params = params(made) if callable(params) else params or {}
        body = body(made) if callable(body) else body
        c = clients[who]
        url = path.format(**params)
        if body == "receipt":
            r = c.post(url, files={"file": ("lunch.png", png(), "image/png")})
        elif body is None:
            r = c.post(url)
        else:
            r = c.post(url, json=body)
        if r.status_code != 201:
            failed.append((path, r.status_code, r.text[:200]))
            continue
        where = r.headers.get("location")
        if where is None:
            unnamed.append(path)
            continue
        got = c.get(where)
        if got.status_code != 200:
            failed.append((path, where, got.status_code))
    assert failed == []
    assert sorted(unnamed) == sorted(READ_NOWHERE)
