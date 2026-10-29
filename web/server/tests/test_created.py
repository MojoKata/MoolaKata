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
    "/ui/api/strategies",
    "/ui/api/accounts/{account_id}/options/{instrument_id}/settle",
    "/ui/api/accounts/{account_id}/corporate-actions",
    "/ui/api/accounts/{account_id}/expenses",
    "/ui/api/reimbursements",
]


@pytest.fixture
def seeded(store, keyed_config):
    from moolakata.dev import seed
    from moolakata.store.repos.ledger import ensure_categories

    srv = Server(config=keyed_config, store=store, ready=True)
    with srv.db.tx() as s:
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

    with srv.db.read() as s:
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
    chk, brk, coll = i["acct:checking"], i["acct:brokerage"], i["acct:collectables"]
    loan, edu = i["acct:auto-loan"], i["acct:529"]
    day = "2026-10-01"
    return {
        "/ui/api/users": (
            "admin",
            None,
            {
                "displayName": "Carol",
                "username": "carol",
                "email": "carol@home.lan",
                "sex": "female",
            },
        ),
        "/ui/api/groups": ("admin", None, {"name": "Cousins"}),
        "/ui/api/profile/tokens": ("alice", None, {"name": "A script"}),
        "/ui/api/settings/links/invitations": ("admin", None, None),
        "/ui/api/settings/connector/pairings": ("admin", None, None),
        "/ui/api/profile/connections": (
            "alice",
            None,
            {"driver": "schwab", "label": "Schwab", "settings": {"appKey": "an-app-key"}},
        ),
        "/ui/api/accounts": ("alice", None, {"name": "Extra", "type": "checking"}),
        "/ui/api/transactions": (
            "alice",
            None,
            {"accountId": chk, "date": day, "amount": -5, "reimbursable": 5},
        ),
        "/ui/api/budgets/{budget_id}/copy": (
            "alice",
            {"budget_id": i["budget"]},
            {"name": "Household, envelope", "method": "envelope"},
        ),
        "/ui/api/budgets/{budget_id}/moves": (
            "alice",
            {"budget_id": i["budget"]},
            {
                "month": "2026-10-01",
                "fromCategoryId": i["cat:personal"],
                "toCategoryId": i["cat:food"],
                "amount": 25,
            },
        ),
        "/ui/api/reimbursements": (
            "alice",
            None,
            lambda made: {"spendingId": made["txn"], "paybackId": i["deposit"], "amount": 5},
        ),
        "/ui/api/categories": ("alice", None, {"name": "Hobbies", "kind": "expense"}),
        "/ui/api/rules": ("alice", None, {"payeeMatch": "COFFEE", "payee": "Coffee shop"}),
        "/ui/api/price-sources": ("admin", None, {"name": "tiingo"}),
        "/ui/api/portfolios": ("alice", None, {"name": "Mine", "accountIds": [brk]}),
        "/ui/api/strategies": (
            "alice",
            None,
            lambda made: {"accountId": brk, "legs": [{"instrumentId": made["option"]}]},
        ),
        "/ui/api/accounts/{account_id}/options/{instrument_id}/settle": (
            "alice",
            lambda made: {"account_id": brk, "instrument_id": made["option"]},
            {"how": "expired", "date": "2026-12-18"},
        ),
        "/ui/api/accounts/{account_id}/corporate-actions": (
            "alice",
            {"account_id": brk},
            {"kind": "split", "date": day, "instrumentId": i["instrument"], "ratio": 2},
        ),
        "/ui/api/budgets": ("alice", None, {"name": "Home", "accountIds": [chk]}),
        "/ui/api/receipts": ("alice", None, "receipt"),
        "/ui/api/projections": (
            "alice",
            None,
            {"name": "Later", "goal": "retirement", "builtOn": {"kind": "typed", "amount": 1000}},
        ),
        "/ui/api/accounts/{account_id}/loan/plans": (
            "alice",
            {"account_id": loan},
            {"name": "Faster", "inputs": {"monthly": 100}},
        ),
        "/ui/api/accounts/{account_id}/items": (
            "alice",
            {"account_id": coll},
            {"name": "Stamp", "acquiredOn": "2020-01-01", "costBasis": 50},
        ),
        "/ui/api/items/{item_id}/valuations": (
            "alice",
            {"item_id": i["item"]},
            {"date": day, "value": 500},
        ),
        "/ui/api/items/{item_id}/improvements": (
            "alice",
            {"item_id": i["item"]},
            {"date": day, "description": "Reframed", "amount": 40},
        ),
        "/ui/api/accounts/{account_id}/contributions": (
            "alice",
            {"account_id": edu},
            {"date": day, "amount": 100},
        ),
        "/ui/api/accounts/{account_id}/expenses": (
            "alice",
            {"account_id": edu},
            {"date": day, "kind": "tuition", "amount": 100},
        ),
        "/ui/api/accounts/{account_id}/goal": ("alice", {"account_id": edu}, None),
        "/ui/api/persons": ("alice", None, {"name": "Aunt May", "sex": "female"}),
        "/ui/api/relationships": (
            "alice",
            None,
            {"person1Id": i["me"], "person2Id": i["kid"], "relation": "family"},
        ),
        "/ui/api/people": ("alice", None, {"name": "Uncle Ben", "sex": "male"}),
        "/ui/api/gifts": ("alice", None, {"people": [i["kid"]], "description": "A kite"}),
        "/ui/api/giving/organisations": (
            "alice",
            None,
            {"name": "Food Bank", "deductible": True},
        ),
        "/ui/api/giving/donations": (
            "alice",
            None,
            {"date": day, "kind": "cash", "amount": 25, "organisationId": i["org"]},
        ),
        "/ui/api/tax-books": ("alice", None, {"year": int(i["year"]), "filers": [i["alice"]]}),
        "/ui/api/tax-books/{book_id}/dependents": (
            "alice",
            {"book_id": i["book"]},
            lambda made: {"personId": made["person"]},
        ),
        "/ui/api/tax-books/{book_id}/filings": ("alice", {"book_id": i["book"]}, {}),
        "/ui/api/tax-books/{book_id}/documents": (
            "alice",
            {"book_id": i["book"]},
            {"form": "1099-B"},
        ),
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
    assert len(routes) > 30
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
        if path == "/ui/api/persons":
            made["person"] = r.json()["id"]
        if path == "/ui/api/transactions":
            made["txn"] = r.json()["id"]
        where = r.headers.get("location")
        if where is None:
            unnamed.append(path)
            continue
        got = c.get(where)
        if got.status_code != 200:
            failed.append((path, where, got.status_code))
    assert failed == []
    assert sorted(unnamed) == sorted(READ_NOWHERE)
