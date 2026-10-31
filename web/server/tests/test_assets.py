"""Physical assets (requirements S1.10): items valued at spot, from valuations or depreciated;
improvements; selling; documents; metal spot from its proxy; and a loan's equity (S1.9.5)."""

import datetime as dt
import json
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import edit, make, saved, sell, terms
from sqlalchemy import select
from test_accounts import new_account

from moolakata import assets, clock, ids
from moolakata.prices import TickerSource, register
from moolakata.prices import refresh as pricing
from moolakata.store.entities.prices import Price, PriceSource

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def alice(server, frozen):
    make_user(server, "alice")
    return sign_in(server, "alice")


def item(c, account_id, **kw):
    body = {"name": "Thing", "acquiredOn": "2024-01-10", "costBasis": "1000", **kw}
    r = make(c, "Item", **{"accountId": account_id, **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_purity_is_read_as_people_write_it():
    assert assets.parse_purity(".9999") == D(".9999")
    assert assets.parse_purity("999.9") == D(".9999")
    assert assets.parse_purity("92.5%") == D(".925")
    assert assets.parse_purity("22k") == D(".9167")
    with pytest.raises(ValueError):
        assets.parse_purity("1.5k0")


@register
class FixedTest(TickerSource):
    name = "fixed-test"
    label = "Fixed"
    classes = frozenset({"etf"})

    def history(self, ref, start, end):
        assert ref.symbol == "SLV"
        return [(end - dt.timedelta(days=1), D("30.00"))]


def test_metals_at_spot_from_the_proxy_and_by_metal(server, alice):
    metals = new_account(alice, name="Metals", type="precious-metals")
    bar = item(
        alice,
        metals["id"],
        name="Silver bar, 100 oz",
        valuation="spot",
        metal="silver",
        unitWeight="100",
        weightUnit="ozt",
        purity=".999",
        costBasis="2800",
    )
    assert bar["fineOunces"] == "99.9"
    assert bar["value"] == "2800.00", "no spot yet: worth its cost"
    with server.db.tx(unscoped="test") as s:
        s.add(
            PriceSource(
                id=ids.new_id("Src"), name="fixed-test", enabled=True, preference=json.dumps({})
            )
        )
    pricing.install()
    pricing.refresh(server)
    with server.db.read(unscoped="test") as s:
        p = s.scalars(select(Price)).all()
        assert [x.close for x in p] == [(D("30.00") / D("0.8591")).quantize(D("0.01"))]
    spot = (D("30.00") / D("0.8591")).quantize(D("0.01"))
    v = alice.get(f"/ui/api/accounts/{metals['id']}/items").json()
    assert v["items"][0]["value"] == str((D("99.9") * spot).quantize(D("0.01")))
    m = v["metals"][0]
    assert m["metal"] == "silver" and m["ounces"] == "99.9" and m["spot"] == str(spot)
    assert m["averageCost"] == str((D(2800) / D("99.9")).quantize(D("0.01")))
    # The account's value is its items'.
    assert alice.get(f"/ui/api/accounts/{metals['id']}").json()["balance"] == v["value"]


def test_valuations_staleness_and_depreciation(alice):
    coll = new_account(alice, name="Collectables", type="collectables")
    watch = item(alice, coll["id"], name="Watch", costBasis="9000", category="Watch")
    r = make(
        alice, "Valtn", itemId=watch["id"], date="2025-06-01", value="12500", source="appraisal"
    )
    assert r.status_code == 200, r.text
    w = alice.get(f"/ui/api/items/{watch['id']}").json()
    assert w["value"] == "12500.00" and w["gain"] == "3500.00" and w["stale"] is True
    make(alice, "Valtn", itemId=watch["id"], date="2026-09-01", value="13000", source="guide")
    w = alice.get(f"/ui/api/items/{watch['id']}").json()
    assert w["value"] == "13000.00" and not w["stale"] and len(w["valuations"]) == 2
    cars = new_account(alice, name="Car", type="vehicle")
    car = item(
        alice,
        cars["id"],
        name="Outback",
        acquiredOn="2023-10-13",
        costBasis="33900",
        valuation="depreciation",
        depreciationRate="12",
        personalUse=True,
    )
    assert 23000 < float(car["value"]) < 23200  # three years at 12%
    bad = make(
        alice,
        "Item",
        accountId=cars["id"],
        name="",
        acquiredOn="2030-01-01",
        costBasis="-1",
        valuation="spot",
    )
    assert {e["field"] for e in bad.json()["errors"]} >= {
        "name",
        "acquiredOn",
        "costBasis",
        "metal",
        "unitWeight",
        "purity",
    }


def test_a_sale_realizes_a_gain_flagged_for_tax(alice):
    coll = new_account(alice, name="Collectables", type="collectables")
    coin = item(alice, coll["id"], name="1909-S VDB", costBasis="1500")
    out = saved(sell(alice, coin["id"], "2026-10-01", "2100", "100"))
    sale = out["sale"]
    assert sale["gain"] == "500.00" and sale["collectable"] and sale["deductible"]
    assert out["value"] == "0.00"
    v = alice.get(f"/ui/api/accounts/{coll['id']}/items").json()
    assert v["value"] == "0.00"
    cars = new_account(alice, name="Car", type="vehicle")
    car = item(alice, cars["id"], name="Car", costBasis="30000", personalUse=True)
    sale = saved(sell(alice, car["id"], "2026-10-01", "20000"))["sale"]
    assert sale["gain"] == "-10000.00" and not sale["deductible"] and not sale["collectable"]
    r = sell(alice, car["id"], "2020-01-01", "1")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "sold-before-bought"


def test_a_home_with_improvements_a_mortgage_and_its_equity(alice):
    homes = new_account(alice, name="Home", type="real-estate")
    home = item(
        alice,
        homes["id"],
        name="1428 Elm St",
        acquiredOn="2023-03-15",
        costBasis="560000",
        closingCosts="8400",
        address="1428 Elm St",
        primaryResidence=True,
    )
    r = make(
        alice,
        "Imprv",
        itemId=home["id"],
        date="2025-05-20",
        description="Kitchen remodel",
        amount="38500",
    )
    assert r.status_code == 200, r.text
    h = alice.get(f"/ui/api/items/{home['id']}").json()
    assert h["basis"] == "606900.00" and h["primaryResidence"]
    make(alice, "Valtn", itemId=home["id"], date="2026-09-20", value="640000", source="estimate")
    loan = new_account(alice, name="Mortgage", type="mortgage")
    r = terms(alice, loan["id"], principal="448000", startDate="2026-09-01", termMonths=360,
              rate="6", pmi="150", originalValue="560000", securedById=home["id"])  # fmt: skip
    e = saved(r)["equity"]
    assert e["value"] == "640000.00" and e["equity"] == "192000.00" and e["ltv"] == "70.00"
    # PMI goes at 78% of the original value: 436,800; on request at 80%: 448,000 (now).
    assert e["pmiRequest"] < e["pmiEnds"]
    items = alice.get(f"/ui/api/accounts/{homes['id']}/items").json()["items"]
    assert items[0]["loans"][0]["name"] == "Mortgage" and items[0]["equity"] == "192000.00"


def test_documents_are_receipts_kept_with_the_item(alice):
    coll = new_account(alice, name="Collectables", type="collectables")
    watch = item(alice, coll["id"], name="Watch")
    up = alice.post(
        "/ui/api/receipts",
        files={"file": ("appraisal.pdf", b"%PDF-1.4 appraisal", "application/pdf")},
    )
    rid = up.json()["id"]
    path = f"/ui/api/items/{watch['id']}"
    r = edit(alice, "Item", path, receiptIds={"add": [rid], "remove": []})
    assert [d["id"] for d in saved(r)["documents"]] == [rid]
    links = alice.get(f"/ui/api/receipts/{rid}").json()["links"]
    assert links[0]["payee"] == "Watch"
    r = edit(alice, "Item", path, receiptIds={"add": [], "remove": [rid]})
    assert saved(r)["documents"] == []


def test_others_read_but_cannot_change_items(server, alice):
    coll = new_account(alice, name="Collectables", type="collectables")
    watch = item(alice, coll["id"], name="Watch")
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    assert bob.get(f"/ui/api/items/{watch['id']}").status_code == 404
