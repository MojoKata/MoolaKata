"""The item routes' rules a mutation run found unpinned (S1.10): what one item's page says of
its loans and its history, the account's totals with nothing held, what is kept as typed, who
an item's activity is told to, and the field a refused receipt names."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, drop, edit, make, saved, share, tag, terms
from sqlalchemy import select
from test_accounts import new_account
from test_assets import T0, item

from moolakata import assets, clock
from moolakata.store.entities.accounts import Account
from moolakata.store.entities.core import Activity
from moolakata.store.entities.prices import TypedPrice


@pytest.fixture
def alice(server):
    clock.fix(T0)
    make_user(server, "alice")
    yield sign_in(server, "alice")
    clock.fix(None)


def test_an_items_page_owes_its_loans_today_and_leaves_out_one_whose_account_is_gone(alice):
    """Its loans as the list shows them (S1.9.5): owed today, not at the schedule's end, and a
    loan whose account was deleted is left out without ending the list."""
    homes = new_account(alice, name="Home", type="real-estate")
    home = item(alice, homes["id"], name="Home", costBasis="500000")
    gone = new_account(alice, name="Old loan", type="mortgage")["id"]
    saved(terms(alice, gone, principal="50000", startDate="2026-01-01", termMonths=60,
                rate="5", securedById=home["id"]))  # fmt: skip
    clock.fix(T0 + dt.timedelta(minutes=1))
    # Read after the one deleted, by the order they were made: the first is skipped, not the end.
    bridge = new_account(alice, name="Bridge", type="mortgage")["id"]
    saved(terms(alice, bridge, principal="100000", startDate="2026-11-01", termMonths=12,
                rate="7", securedById=home["id"]))  # fmt: skip
    assert drop(alice, "Acct", f"/ui/api/accounts/{gone}", confirm=True).status_code == 200
    page = alice.get(f"/ui/api/items/{home['id']}").json()
    # The bridge loan starts next month: nothing is owed on it today.
    assert page["loans"] == [{"accountId": bridge, "name": "Bridge", "owed": "0.00"}]
    assert page["equity"] == "500000.00"


def test_an_item_bought_and_sold_on_a_months_first_day_has_that_day_in_its_history(alice):
    coll = new_account(alice, name="Coll", type="collectables")
    coin = item(alice, coll["id"], name="Coin", acquiredOn="2026-10-01", costBasis="100",
                soldOn="2026-10-01", proceeds="120", saleFees="0")  # fmt: skip
    page = alice.get(f"/ui/api/items/{coin['id']}").json()
    # Sold that day, it is worth nothing in the account from it (S1.10.5).
    assert [(day, str(v)) for day, v in page["history"]] == [("2026-10-01", "0.00")]


def test_an_item_sold_as_it_is_added_is_sold(alice):
    """A sale typed in the form that adds the item is kept with it (S1.10.5)."""
    coll = new_account(alice, name="Coll", type="collectables")
    coin = item(alice, coll["id"], name="Coin", costBasis="100", soldOn="2026-10-02",
                proceeds="150", saleFees="5")  # fmt: skip
    assert coin["sale"]["soldOn"] == "2026-10-02"
    assert (coin["sale"]["proceeds"], coin["sale"]["fees"]) == ("150.00", "5.00")


def test_an_account_holding_nothing_totals_zero(alice):
    coll = new_account(alice, name="Coll", type="collectables")
    item(alice, coll["id"], name="Coin", costBasis="100", soldOn="2026-10-02", proceeds="150",
         saleFees="0")  # fmt: skip
    got = alice.get(f"/ui/api/accounts/{coll['id']}/items").json()
    assert (got["value"], got["basis"], got["gain"]) == ("0.00", "0.00", "0.00")


def test_an_items_description_and_serial_are_kept_trimmed(alice):
    coll = new_account(alice, name="Coll", type="collectables")
    watch = item(alice, coll["id"], name="Watch", description="  Steel, 1968  ",
                 serial=" A-1234 ")  # fmt: skip
    page = alice.get(f"/ui/api/items/{watch['id']}").json()
    assert (page["description"], page["serial"]) == ("Steel, 1968", "A-1234")


def test_an_items_activity_is_its_accounts_owners(server, alice):
    """Told to whoever owns the account, as its other activity is (S12.11)."""
    coll = new_account(alice, name="Coll", type="collectables")
    item(alice, coll["id"], name="Coin")
    with server.db.tx(unscoped="test") as s:
        owner = s.get(Account, coll["id"]).ownerId
        rows = s.scalars(select(Activity).where(Activity.kind == "item.added")).all()
        assert [(r.ownerId, r.subjectId) for r in rows] == [(owner, coll["id"])]


def test_a_receipt_shared_to_read_is_refused_at_the_items_receipts(server, alice):
    """A read share shows a receipt and attaches it nowhere (S9.6): the refusal names the
    item's field."""
    coll = new_account(alice, name="Coll", type="collectables")
    up = alice.post("/ui/api/receipts",
                    files={"file": ("a.pdf", b"%PDF-1.4 a", "application/pdf")})  # fmt: skip
    rid = up.json()["id"]
    item(alice, coll["id"], name="Watch", receiptIds=[rid])
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    bob_id = {
        u["displayName"]: u["id"]
        for u in alice.get(f"/ui/api/shares/account/{coll['id']}").json()["users"]
    }["Bob"]
    assert share(alice, "account", coll["id"], users={bob_id: "read"}, groups={}).status_code == 200
    his = new_account(bob, name="His", type="collectables")["id"]
    r = make(bob, "Item", accountId=his, name="Clock", acquiredOn="2024-01-10",
             costBasis="10", receiptIds=[rid])  # fmt: skip
    assert r.status_code == 403, r.text
    (e,) = r.json()["errors"]
    assert (e["field"], e["code"]) == ("receiptIds", "receipt-read-only")


def test_a_stale_items_current_has_no_purity_when_not_at_spot(alice):
    """The record a stale edit is answered with (412) is the item as it is: an item not valued
    at spot has no purity, not the word None."""
    coll = new_account(alice, name="Coll", type="collectables")
    watch = item(alice, coll["id"], name="Watch")
    saved(edit(alice, "Item", f"/ui/api/items/{watch['id']}", name="Old watch"))
    r = change(alice, "Item", watch, name="New watch")
    assert r.status_code == 412, r.text
    (stale,) = r.json()["current"]
    assert stale["current"]["purity"] is None and stale["current"]["name"] == "Old watch"


def test_a_spot_price_on_a_months_last_day_values_that_month(server, alice):
    """An item at spot is worth, at each month's end, the spot on or before that day
    (S1.10.5): a price typed on the 31st counts for August."""
    metals = new_account(alice, name="Metals", type="precious-metals")
    bar = item(alice, metals["id"], name="Silver bar", valuation="spot", metal="silver",
               unitWeight="100", weightUnit="ozt", purity=".999", costBasis="2800",
               acquiredOn="2026-08-15")  # fmt: skip
    with server.db.tx(unscoped="test") as s:
        owner = s.get(Account, metals["id"]).ownerId
        inst = assets.metal_instrument(s, "silver")
        for day, close in ((dt.date(2026, 8, 20), "20"), (dt.date(2026, 8, 31), "30")):
            s.add(TypedPrice(instrumentId=inst.id, userId=owner, date=day, close=D(close)))
    page = alice.get(f"/ui/api/items/{bar['id']}").json()
    (day, v), *_ = page["history"]
    assert (day, str(v)) == ("2026-08-31", "2997.00")


def test_an_items_receipt_is_listed_as_its_owner_holds_it_with_their_tags(alice):
    """An item's documents (S9.6) are its receipts as the reader holds them: its owner may
    change and delete one, and sees their own tags on it."""
    coll = new_account(alice, name="Coll", type="collectables")
    pdf = {"file": ("a.pdf", b"%PDF-1.4 a", "application/pdf")}
    rid = alice.post("/ui/api/receipts", files=pdf).json()["id"]
    tid = tag(alice, "Insurance")
    saved(edit(alice, "Rcpt", f"/ui/api/receipts/{rid}", tagIds=[tid]))
    watch = item(alice, coll["id"], name="Watch", receiptIds=[rid])
    (doc,) = alice.get(f"/ui/api/items/{watch['id']}").json()["documents"]
    assert (doc["id"], doc["tags"], doc["tagIds"]) == (rid, ["insurance"], [tid])
    assert doc["access"]["writable"] and doc["access"]["deletable"]
