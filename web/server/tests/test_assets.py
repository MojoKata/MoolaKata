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
from moolakata.store.entities.accounts import Account
from moolakata.store.entities.assets import Improvement, Item, ItemValuation
from moolakata.store.entities.prices import Price, PriceSource, TypedPrice

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
    # None recorded yet: Oct 1's payment counts as paid as scheduled (S1.9.3), its $445.99 of
    # principal off the $448,000 borrowed.
    v = saved(r)
    assert [(x["date"], x["status"], x["principal"]) for x in v["rows"][:1]] == [
        ("2026-10-01", "assumed", "445.99")
    ]
    e = v["equity"]
    assert e["value"] == "640000.00" and e["equity"] == "192445.99" and e["ltv"] == "69.90"
    # PMI goes at 78% of the original value: 436,800; on request at 80%: 448,000 (now).
    assert e["pmiRequest"] < e["pmiEnds"]
    items = alice.get(f"/ui/api/accounts/{homes['id']}/items").json()["items"]
    assert items[0]["loans"][0]["name"] == "Mortgage" and items[0]["equity"] == "192445.99"


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


# ---------- the rules, on plain values ----------

d = dt.date


def thing(**kw) -> Item:
    return Item(
        **{"id": ids.new_id("Item"), "accountId": "Acct_x", "name": "Thing",
           "acquiredOn": d(2024, 1, 10), "costBasis": D(1000), **kw}
    )  # fmt: skip


def valued(day, value, item="Item_x", **kw) -> ItemValuation:
    return ItemValuation(id=ids.new_id("Valtn"), itemId=item, date=day, value=D(value), **kw)


def improved(day, amount, item="Item_x") -> Improvement:
    return Improvement(
        id=ids.new_id("Imprv"), itemId=item, date=day, description="Roof", amount=D(amount)
    )


def detail(valuations=(), improvements=()) -> assets.Detail:
    return assets.Detail(list(valuations), list(improvements))


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("24k", D(1)),  # pure gold
        ("1k", D("0.0417")),
        ("0.5k", D("0.0208")),
        ("22 k", D("0.9167")),  # spaces anywhere are left out
        ("99.9 9", D(".9999")),
        ("1", D(1)),  # a whole: pure
        ("1.5", D(".015")),  # over 1, a percentage
        ("99.99", D(".9999")),
        ("100", D(1)),  # 100 is a percentage, past it parts in a thousand
        ("100.5", D(".1005")),
        ("999.9", D(".9999")),
        ("100%", D(1)),
    ],
)
def test_purity_is_a_fraction_however_it_is_written(text, want):
    assert assets.parse_purity(text) == want


@pytest.mark.parametrize("text", ["0k", "25k", "24.5k", "0", "0%", "150%", "1001", "", "fine"])
def test_a_purity_outside_nothing_to_whole_is_refused(text):
    with pytest.raises(ValueError):
        assets.parse_purity(text)


def test_fine_ounces_need_weight_unit_and_purity_and_count_each_unit():
    full = {"unitWeight": D("31.1034768"), "weightUnit": "g", "purity": D(1), "quantity": D(3)}
    assert assets.fine_ounces(thing(**full)) == D(3)
    kilo = thing(**{**full, "unitWeight": D(1), "weightUnit": "kg", "quantity": D(1)})
    assert assets.fine_ounces(kilo) == D(1000) / D("31.1034768")
    for missing in ("unitWeight", "weightUnit", "purity"):
        assert assets.fine_ounces(thing(**{**full, missing: None})) == 0


def test_basis_counts_closing_costs_and_improvements_made_by_the_day():
    home = thing(costBasis=D(500000), closingCosts=D(8000))
    ds = detail(improvements=[improved(d(2025, 5, 20), 40000), improved(d(2026, 1, 1), 1500)])
    assert assets.basis(home, ds, d(2025, 5, 19)) == D(508000)
    assert assets.basis(home, ds, d(2025, 5, 20)) == D(548000)
    assert assets.basis(home, ds) == D(549500)
    assert assets.basis(thing(), detail()) == D(1000)


def test_an_item_is_worth_something_from_the_day_acquired_to_the_day_before_its_sale():
    coin = thing(soldOn=d(2026, 10, 1), proceeds=D(1500))
    assert assets.value_on(coin, detail(), d(2024, 1, 9), None) == 0
    assert assets.value_on(coin, detail(), d(2024, 1, 10), None) == D(1000)
    assert assets.value_on(coin, detail(), d(2026, 9, 30), None) == D(1000)
    assert assets.value_on(coin, detail(), d(2026, 10, 1), None) == 0


def test_a_valuation_counts_from_its_own_day():
    ds = detail([valued(d(2025, 1, 1), 1100), valued(d(2025, 6, 1), 1200)])
    assert assets.value_on(thing(), ds, d(2025, 5, 31), None) == D(1100)
    assert assets.value_on(thing(), ds, d(2025, 6, 1), None) == D(1200)
    assert assets.latest_valuation(ds, d(2024, 12, 31)) is None


def test_without_a_valuation_an_item_is_worth_its_basis_on_the_day():
    ds = detail(improvements=[improved(d(2025, 5, 20), 400)])
    assert assets.value_on(thing(), ds, d(2025, 5, 19), None) == D(1000)
    # A metal with no spot yet, the same.
    bar = thing(valuation="spot", metal="gold", unitWeight=D(1), weightUnit="ozt", purity=D(1))
    assert assets.value_on(bar, ds, d(2025, 5, 19), None) == D(1000)
    assert assets.value_on(bar, ds, d(2025, 5, 20), None) == D(1400)


def test_at_spot_an_item_is_its_fine_ounces_at_spot_plus_its_premium():
    bar = thing(valuation="spot", metal="gold", unitWeight=D(10), weightUnit="ozt", purity=D(1))
    assert assets.value_on(bar, detail(), d(2025, 1, 1), D(30)) == D("300.00")
    bar.sellPremium = D(5)
    assert assets.value_on(bar, detail(), d(2025, 1, 1), D(30)) == D("315.00")
    bar.sellPremium = D(-10)
    assert assets.value_on(bar, detail(), d(2025, 1, 1), D("30.01")) == D("270.09")


def test_depreciation_compounds_yearly_and_only_for_items_valued_so():
    car = thing(
        acquiredOn=d(2020, 1, 1), costBasis=D(10000), valuation="depreciation",
        depreciationRate=D(12),
    )  # fmt: skip
    # Four years (1,461 days) at 12%: 0.88 to the fourth.
    assert assets.value_on(car, detail(), d(2024, 1, 1), None) == D("5996.95")
    car.valuation = "valuations"  # a rate kept from before, not used
    assert assets.value_on(car, detail(), d(2024, 1, 1), None) == D(10000)


def test_a_valuation_over_a_year_old_is_stale_unless_spot_or_sold():
    ds = detail([valued(d(2025, 1, 1), 1100)])
    assert not assets.is_stale(thing(), ds, d(2026, 1, 1))  # 365 days
    assert assets.is_stale(thing(), ds, d(2026, 1, 2))
    assert not assets.is_stale(thing(valuation="spot"), ds, d(2026, 1, 2))
    assert not assets.is_stale(thing(soldOn=d(2026, 1, 1), proceeds=D(1)), ds, d(2026, 1, 2))
    assert not assets.is_stale(thing(), detail(), d(2026, 1, 2))


def test_a_sales_gain_is_its_proceeds_less_fees_and_the_basis_when_sold():
    ds = detail(improvements=[improved(d(2025, 1, 1), 200), improved(d(2026, 10, 2), 50)])
    sold = thing(soldOn=d(2026, 10, 1), proceeds=D(2000), saleFees=D(100))
    assert assets.gain(sold, ds) == D(700)
    assert assets.gain(thing(soldOn=d(2026, 10, 1), proceeds=D(2000)), detail()) == D(1000)
    assert assets.gain(thing(), ds) is None


def test_metals_and_collectables_are_taxed_as_collectables():
    assert assets.is_collectable("precious-metals", thing())
    assert assets.is_collectable("collectables", thing())
    assert assets.is_collectable("other-asset", thing(valuation="spot"))
    assert not assets.is_collectable("vehicle", thing())


# ---------- what is read from the database ----------


@pytest.fixture
def owner(server, frozen):
    return make_user(server, "carol").id


def account(s, owner, type="precious-metals") -> Account:
    a = Account(id=ids.new_id("Acct"), ownerId=owner, name=type.title(), type=type)
    s.add(a)
    s.flush()
    return a


def stored(s, a, **kw) -> Item:
    it = thing(accountId=a.id, **kw)
    s.add(it)
    s.flush()
    return it


def spot(s, owner, metal, *points):
    """The metal's spot instrument, with the owner's typed prices (day, close)."""
    inst = assets.metal_instrument(s, metal)
    for day, close in points:
        s.add(TypedPrice(instrumentId=inst.id, userId=owner, date=day, close=D(close)))
    s.flush()
    return inst


def test_a_metals_spot_instrument_is_named_and_found_by_its_symbol(server, owner):
    with server.db.tx(unscoped="test") as s:
        silver = assets.metal_instrument(s, "silver")
        gold = assets.metal_instrument(s, "gold")
        assert (gold.symbol, gold.name, gold.instrumentClass) == ("XAU", "Gold spot", "metal")
        assert assets.find_metal(s, "gold") is gold and assets.find_metal(s, "silver") is silver
        gold.mark_deleted(None)
        s.flush()
        assert assets.find_metal(s, "gold") is None


def test_an_accounts_items_and_their_history_in_order(server, owner):
    with server.db.tx(unscoped="test") as s:
        a, other = account(s, owner), account(s, owner)
        b = stored(s, a, name="B", acquiredOn=d(2024, 1, 1))
        first = stored(s, a, name="A", acquiredOn=d(2024, 1, 1))
        oldest = stored(s, a, name="C", acquiredOn=d(2023, 1, 1))
        stored(s, a, name="Gone").mark_deleted(None)
        theirs = stored(s, other, name="Theirs")
        s.flush()
        assert assets.items_of(s, a) == [oldest, first, b]
        t0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        later = valued(d(2025, 6, 1), 1300, b.id, createdAt=t0 + dt.timedelta(hours=1))
        earlier = valued(d(2025, 6, 1), 1200, b.id, createdAt=t0)
        oldest_v = valued(d(2025, 1, 1), 1100, b.id)
        gone = valued(d(2025, 2, 1), 1, b.id)
        gone.mark_deleted(None)
        late_m, early_m = improved(d(2025, 9, 1), 20, b.id), improved(d(2025, 3, 1), 10, b.id)
        gone_m = improved(d(2025, 4, 1), 5, b.id)
        gone_m.mark_deleted(None)
        s.add_all([later, earlier, oldest_v, gone, late_m, early_m, gone_m])
        s.add_all([valued(d(2025, 1, 1), 9, theirs.id), improved(d(2025, 1, 1), 9, theirs.id)])
        s.flush()
        ds = assets.details(s, [b])
        assert list(ds) == [b.id]
        assert ds[b.id].valuations == [oldest_v, earlier, later]
        assert ds[b.id].improvements == [early_m, late_m]
        assert assets.details(s, []) == {}


def test_spot_is_the_owners_price_on_the_day_for_items_valued_at_spot(server, owner):
    with server.db.tx(unscoped="test") as s:
        a = account(s, owner)
        oz = {"unitWeight": D(1), "weightUnit": "ozt", "purity": D(1)}
        bar = stored(s, a, valuation="spot", metal="gold", costBasis=D(1800), **oz)
        # A coin valued by appraisal: its metal's spot isn't asked for.
        coin = stored(s, a, metal="silver", **oz)
        spot(s, owner, "gold", (d(2026, 10, 1), 2000), (d(2026, 10, 10), 2100))
        spot(s, owner, "silver", (d(2026, 10, 1), 30))
        got = assets.spots(s, [bar, coin], d(2026, 10, 5))
        assert {m: (p.price, p.asOf) for m, p in got.items()} == {"gold": (D(2000), d(2026, 10, 1))}
        assert assets.worth(s, a, d(2026, 10, 5)) == [(bar, D("2000.00")), (coin, D(1000))]
        assert assets.worth(s, a) == [(bar, D("2100.00")), (coin, D(1000))]  # today
        # One item's worth on a day, and before it was acquired, its worth when it was.
        assert assets.worth_on(s, bar, d(2026, 10, 5)) == D("2000.00")
        s.add(valued(d(2024, 1, 10), 1100, coin.id))
        s.flush()
        assert assets.worth_on(s, coin, d(2026, 10, 5)) == D(1100)
        assert assets.worth_on(s, coin, d(2020, 1, 1)) == D(1100)


def test_an_accounts_items_over_time_carry_spot_forward(server, owner):
    with server.db.tx(unscoped="test") as s:
        a = account(s, owner)
        oz = {"unitWeight": D(1), "weightUnit": "ozt", "purity": D(1)}
        stored(s, a, valuation="spot", metal="gold", costBasis=D(1800), **oz)
        coin = stored(s, a, metal="silver", acquiredOn=d(2026, 9, 1), costBasis=D(40), **oz)
        s.add(valued(d(2026, 9, 1), 50, coin.id))
        stored(s, a, name="Other", acquiredOn=d(2026, 9, 1), costBasis=D(7))
        points = [(d(2026, 10, 3), 2000), (d(2026, 10, 5), 2100), (d(2026, 10, 6), 2200)]
        spot(s, owner, "gold", *points)
        spot(s, owner, "silver", (d(2026, 10, 4), 30))
        got = assets.series(s, a, d(2026, 10, 2), d(2026, 10, 7))
        assert got == [
            (d(2026, 10, 2), D(1857)),  # no spot yet: the bar at its cost
            (d(2026, 10, 3), D(2057)),
            (d(2026, 10, 4), D(2057)),  # carried forward
            (d(2026, 10, 5), D(2157)),
            (d(2026, 10, 6), D(2257)),
            (d(2026, 10, 7), D(2257)),
        ]
        # Every third day, and the last; with `only`, the items it keeps.
        got = assets.series(s, a, d(2026, 10, 2), d(2026, 10, 7), 3, lambda i: i.metal == "gold")
        assert got == [(d(2026, 10, 2), D(1800)), (d(2026, 10, 5), D(2100)),
                       (d(2026, 10, 7), D(2200))]  # fmt: skip
        assert assets.series(s, a, d(2026, 10, 7), d(2026, 10, 7)) == [(d(2026, 10, 7), D(2257))]


def test_metals_held_by_metal_with_spot_cost_and_gain(server, owner):
    with server.db.tx(unscoped="test") as s:
        a = account(s, owner)
        oz = {"weightUnit": "ozt", "purity": D(1), "valuation": "spot"}
        stored(s, a, metal="gold", unitWeight=D(1), costBasis=D(1800), **oz)
        stored(s, a, metal="gold", unitWeight=D(5), soldOn=d(2026, 1, 1), proceeds=D(9), **oz)
        stored(s, a, metal="silver", unitWeight=D(10), costBasis=D(300), **oz)
        # Platinum by appraisal, its weight not given.
        plat = stored(s, a, metal="platinum", costBasis=D(900))
        s.add(valued(d(2026, 6, 1), 950, plat.id))
        spot(s, owner, "gold", (d(2026, 10, 1), 2000), (d(2026, 10, 10), 2100))
        spot(s, owner, "silver")
        spot(s, owner, "platinum", (d(2026, 10, 1), 1000))
        got = [m.__dict__ for m in assets.metals(s, assets.items_of(s, a), d(2026, 10, 5))]
    assert got == [
        {"metal": "gold", "ounces": D(1), "cost": D(1800), "averageCost": D(1800),
         "spot": D(2000), "spotAsOf": d(2026, 10, 1), "value": D(2000), "gain": D(200)},
        {"metal": "silver", "ounces": D(10), "cost": D(300), "averageCost": D(30),
         "spot": None, "spotAsOf": None, "value": D(300), "gain": D(0)},
        {"metal": "platinum", "ounces": D(0), "cost": D(900), "averageCost": None,
         "spot": None, "spotAsOf": None, "value": D(950), "gain": D(50)},
    ]  # fmt: skip
