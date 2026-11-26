"""Portfolios as records (requirements S5.1): their accounts changed, kept and taken back,
the owner's choice alone; a portfolio deleted; and Holdings with what has no price or no
cost basis (S5.2.3)."""

from conftest import make_user, sign_in
from edits import change, make, remove, saved
from edits import share as shared
from test_accounts import add, new_account


def made(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def kinds(c) -> list[str]:
    return [x["kind"] for x in c.get("/ui/api/activity").json()["items"]]


def test_a_portfolios_accounts_are_taken_out_and_put_back_by_its_owner_alone(server):
    make_user(server, "jane")
    john = make_user(server, "john")
    jane, johns = sign_in(server, "jane"), sign_in(server, "john")
    one = new_account(jane, name="One", openingBalance="100.00", openingDate="2026-01-01")
    two = new_account(jane, name="Two", mask="1111", openingBalance="50.00",
                      openingDate="2026-01-01")  # fmt: skip
    p = made(make(jane, "Portf", name="Both", accountIds=[one["id"], two["id"]]))

    # Two taken out, then put back: its membership is kept and restored, not made again.
    p = saved(change(jane, "Portf", p, accountIds=[one["id"]]))
    assert p["accountIds"] == [one["id"]] and p["value"] == "100.00"
    p = saved(change(jane, "Portf", p, accountIds=[one["id"], two["id"]]))
    assert sorted(p["accountIds"]) == sorted([one["id"], two["id"]]) and p["value"] == "150.00"
    assert kinds(jane).count("portfolio.updated") == 2

    # Saved as it is: nothing changes, and nothing is recorded.
    version = p["version"]
    p = saved(change(jane, "Portf", p, name="Both", benchmark="VT"))
    assert p["version"] == version and kinds(jane).count("portfolio.updated") == 2

    # John, sharing it at write, renames it, but the accounts are the owner's choice.
    for a in (one, two):
        shared(jane, "account", a["id"], users={john.id: "read"})
    shared(jane, "portfolio", p["id"], users={john.id: "write"})
    his = johns.get(f"/ui/api/portfolios/{p['id']}").json()
    r = change(johns, "Portf", his, accountIds=[one["id"]])
    assert r.status_code == 403, r.text
    assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [
        ("accountIds", "owner-only", "Only the owner chooses the accounts.")
    ]
    his = saved(change(johns, "Portf", his, name="Ours"))
    assert his["name"] == "Ours"


def test_a_portfolio_deleted_is_gone_and_recorded(server):
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    p = made(make(jane, "Portf", name="Old", accountIds=[]))
    assert remove(jane, "Portf", p).status_code == 200
    assert jane.get(f"/ui/api/portfolios/{p['id']}").status_code == 404
    assert "portfolio.deleted" in kinds(jane)


def test_holdings_name_a_holding_without_a_price_or_a_basis_with_neither(server):
    """Shares moved in with no lots typed and nothing to price them: Holdings lists them with
    no value, cost basis, gain or weight, never a value of 0."""
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    a = new_account(jane, name="Brokerage", type="brokerage")
    add(jane, a["id"], "0.00", "2026-09-10", kind="transfer-in", symbol="XNOPRICEZ",
        quantity="3")  # fmt: skip
    p = made(make(jane, "Portf", name="Moved", accountIds=[a["id"]]))
    (h,) = jane.get(f"/ui/api/portfolios/{p['id']}/holdings").json()["holdings"]
    assert h["symbol"] == "XNOPRICEZ" and h["quantity"] == 3
    assert h["value"] is h["costBasis"] is h["gain"] is h["weight"] is None
