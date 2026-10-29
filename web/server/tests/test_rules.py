"""Categorisation and payee rules (requirements S2.7)."""

import io
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, remove
from PIL import Image
from test_accounts import FIX, add, new_account, upload
from test_receipts import upload as upload_receipt

from moolakata.ledger import rules as match


def cats(c) -> dict[str, str]:
    return {x["path"]: x["id"] for x in c.get("/ui/api/categories").json()["items"]}


@pytest.fixture
def alice(server):
    make_user(server, "alice")
    return sign_in(server, "alice")


# ---- matching ----


def m(**kw):
    rule = type(
        "R", (), {"amountMin": None, "amountMax": None, "direction": "any", "accountId": None} | kw
    )
    return match.matcher(rule)


def test_text_matches_anywhere_case_aside_and_re_by_its_pattern():
    assert match.matches(m(payeeMatch="whole foods"), "WHOLE FOODS #123", D("-40"), "A")
    assert not match.matches(m(payeeMatch="whole foods"), "WHOLEFOODS", D("-40"), "A")
    assert match.matches(m(payeeMatch="re:^amzn"), "AMZN Mktp US", D("-12"), "A")
    assert not match.matches(m(payeeMatch="re:^amzn"), "PAYPAL *AMZN", D("-12"), "A")


def test_amount_direction_and_account_narrow_a_rule():
    r = m(payeeMatch="sq *", amountMax=D(20), direction="out", accountId="A")
    assert match.matches(r, "SQ *BLUE BOTTLE", D("-5.75"), "A")
    assert not match.matches(r, "SQ *BLUE BOTTLE", D("-25.00"), "A")  # over the range
    assert not match.matches(r, "SQ *BLUE BOTTLE", D("5.75"), "A")  # money in
    assert not match.matches(r, "SQ *BLUE BOTTLE", D("-5.75"), "B")  # another account


@pytest.mark.parametrize("bad", ["", "re:", "re:(unclosed", "re:(a+)+$", "x" * 201])
def test_patterns_that_cant_be_kept_are_refused(bad):
    with pytest.raises(match.Invalid):
        match.compile_pattern(bad)


# ---- through the API ----


def test_rules_are_kept_in_order_and_first_match_wins(alice):
    c = cats(alice)
    r = alice.post(
        "/ui/api/rules", json={"payeeMatch": "re:(a+)+", "categoryId": c["Food › Groceries"]}
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "payeeMatch"
    r = alice.post("/ui/api/rules", json={"payeeMatch": "kroger"})
    assert r.json()["errors"][0]["code"] == "rule-sets-nothing"
    alice.post("/ui/api/rules", json={"payeeMatch": "kroger", "categoryId": c["Food › Groceries"]})
    r = alice.post(
        "/ui/api/rules",
        json={
            "payeeMatch": "re:^KROGER #1",
            "categoryId": c["Food › Dining out"],
            "payee": "Kroger",
        },
    )
    assert r.status_code == 201, r.text
    first, second = r.json()["items"]
    assert (first["position"], second["position"]) == (0, 1)
    r = alice.post(f"/ui/api/rules/{second['id']}/move", json={"to": 0})
    assert [x["id"] for x in r.json()["items"]] == [second["id"], first["id"]]
    a = new_account(alice)
    job = upload(alice, a["id"], "bank.ofx", (FIX / "bank.ofx").read_bytes())
    assert job["result"]["categorised"] == 1, job
    items = alice.get("/ui/api/transactions", params={"account": a["id"]}).json()["items"]
    kroger = next(t for t in items if t["payeeRaw"] == "KROGER #123")
    assert kroger["categoryId"] == c["Food › Dining out"] and kroger["payee"] == "Kroger"
    feed = alice.get("/ui/api/activity").json()["items"]
    assert any("reordered their categorisation rules" in x["text"] for x in feed)


def test_applied_on_demand_to_the_uncategorised_only(alice):
    c = cats(alice)
    a = new_account(alice)
    add(alice, a["id"], "-42.00", "2026-10-01", payee="WHOLE FOODS #77")
    add(
        alice,
        a["id"],
        "-18.00",
        "2026-10-02",
        payee="WHOLE FOODS #77",
        categoryId=c["Food › Dining out"],
    )
    r = alice.post(
        "/ui/api/rules",
        json={"payeeMatch": "whole foods", "categoryId": c["Food › Groceries"], "tags": ["Food"]},
    )
    assert r.json()["uncategorised"] == 1
    assert alice.post("/ui/api/rules/apply").json()["changed"] == 1
    items = alice.get("/ui/api/transactions", params={"account": a["id"]}).json()["items"]
    got = sorted((t["amount"], t["categoryId"], t["tags"]) for t in items)
    assert got == [
        ("-42.00", c["Food › Groceries"], ["food"]),
        ("-18.00", c["Food › Dining out"], []),
    ]
    assert alice.post("/ui/api/rules/apply").json()["changed"] == 0
    feed = alice.get("/ui/api/activity").json()["items"]
    assert any("rules set 1 transaction" in x["text"] for x in feed)


def test_a_rule_is_its_owners_alone_and_can_be_deleted(server, alice):
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    c = cats(alice)
    [r] = alice.post(
        "/ui/api/rules", json={"payeeMatch": "acme", "categoryId": c["Income › Salary"]}
    ).json()["items"]
    assert bob.get("/ui/api/rules").json()["items"] == []
    assert remove(bob, "Rule", r).status_code == 404
    assert remove(alice, "Rule", r).status_code == 200
    assert alice.get("/ui/api/rules").json()["items"] == []


def test_a_rule_changed_keeps_its_place_and_sets_what_it_says(server, alice):
    c = cats(alice)
    for payee in ("acme", "shop"):
        alice.post("/ui/api/rules", json={"payeeMatch": payee, "categoryId": c["Income › Salary"]})
    first, second = alice.get("/ui/api/rules").json()["items"]
    r = change(alice, "Rule", first, payee="Acme Corp", tags={"add": ["Work"], "remove": []})
    assert r.status_code == 200, r.text
    items = alice.get("/ui/api/rules").json()["items"]
    assert [x["id"] for x in items] == [first["id"], second["id"]]
    assert (items[0]["payee"], items[0]["tags"]) == ("Acme Corp", ["work"])
    r = change(alice, "Rule", items[1], categoryId=None)
    assert r.json()["errors"][0]["code"] == "rule-sets-nothing"


def test_a_receipts_merchant_is_renamed_by_the_rules(server, alice):
    from moolakata.receipts.reading import save_reading
    from moolakata.store.entities.receipts import Receipt

    alice.post("/ui/api/rules", json={"payeeMatch": "re:blue ?bottle", "payee": "Blue Bottle"})
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    rid = upload_receipt(alice, buf.getvalue()).json()["id"]
    with server.db.tx() as s:
        save_reading(s, s.get(Receipt, rid), ["BLUEBOTTLE CAFE", "TOTAL 5.75"], "text", "test")
    assert alice.get(f"/ui/api/receipts/{rid}").json()["payee"] == "Blue Bottle"
