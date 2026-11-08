"""Physical assets (requirements S1.10): items valued at spot, from valuations or depreciated;
improvements; selling; documents; metal spot from its proxy; and a loan's equity (S1.9.5)."""

import datetime as dt
import json
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, drop, edit, make, new_id, remove, saved, sell, share, terms
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


@pytest.mark.parametrize(
    "text", ["0k", "25k", "24.5k", "0", "0%", "150%", "1001", "", "fine", None]
)
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


# ---------- the item routes' rules, through the save and the reads ----------

TODAY, TOMORROW = "2026-10-13", "2026-10-14"
SPOT = {"valuation": "spot", "metal": "gold", "unitWeight": "1", "weightUnit": "ozt",
        "purity": ".9999"}  # fmt: skip


def refusals(r) -> list[tuple[str | None, str, str]]:
    """A save's refusals, in order: each one's field, code and message."""
    assert r.status_code == 422, r.text
    return [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


def test_an_items_form_is_refused_at_every_field_at_once(alice):
    metals = new_account(alice, name="Metals", type="precious-metals")
    r = make(alice, "Item", accountId=metals["id"], name="  ", acquiredHow="found",
             acquiredOn=TOMORROW, costBasis="-0.01", quantity="0", insuredValue="-0.01",
             closingCosts="-0.01", valuation="spot", metal="tin", unitWeight="0",
             weightUnit="lb", purity="fine", sellPremium="100.01")  # fmt: skip
    assert refusals(r) == [
        ("name", "name-invalid", "A name, up to 120 characters."),
        ("acquiredHow", "how-invalid", "Bought, a gift or inherited."),
        ("acquiredOn", "date-ahead", "Not after today."),
        ("costBasis", "amount-invalid", "Zero or more."),
        ("quantity", "quantity-invalid", "More than zero."),
        ("insuredValue", "amount-invalid", "Zero or more."),
        ("closingCosts", "amount-invalid", "Zero or more."),
        ("metal", "metal-invalid", "Gold, silver, platinum or palladium."),
        ("unitWeight", "weight-invalid", "The weight of one unit."),
        ("weightUnit", "unit-invalid", "Troy ounces, grams or kilograms."),
        ("purity", "purity-invalid", "Such as .9999, .925 or 22k."),
        ("sellPremium", "premium-invalid", "Between −50% and 100%."),
    ]


NAME = ("name", "name-invalid", "A name, up to 120 characters.")
VALUATION = ("valuation", "valuation-invalid", "Spot, valuations or depreciation.")
PREMIUM = ("sellPremium", "premium-invalid", "Between −50% and 100%.")
RATE = ("depreciationRate", "rate-invalid", "A yearly percentage.")
DEPRECIATED = {"valuation": "depreciation"}
METAL = ("metal", "metal-invalid", "Gold, silver, platinum or palladium.")
WEIGHT = ("unitWeight", "weight-invalid", "The weight of one unit.")
UNIT = ("weightUnit", "unit-invalid", "Troy ounces, grams or kilograms.")
PURITY = ("purity", "purity-invalid", "Such as .9999, .925 or 22k.")


@pytest.mark.parametrize(
    ("kw", "refused"),
    [
        ({"name": "x" * 120}, None),
        ({"name": "x" * 121}, NAME),
        ({"name": f" {'x' * 120} "}, None),  # counted once trimmed
        ({"acquiredOn": TODAY}, None),
        ({"acquiredHow": "gift"}, None),
        ({"acquiredHow": "inherited"}, None),
        ({"costBasis": "0", "insuredValue": "0", "closingCosts": "0"}, None),
        ({"quantity": "0.0001"}, None),
        ({"valuation": "worth"}, VALUATION),
        ({**SPOT, "sellPremium": "-50"}, None),
        ({**SPOT, "sellPremium": "100"}, None),
        ({**SPOT, "sellPremium": "-50.01"}, PREMIUM),
        ({**SPOT, "metal": "palladium", "weightUnit": "kg", "purity": "22k"}, None),
        ({**SPOT, "metal": None}, METAL),
        ({**SPOT, "unitWeight": None}, WEIGHT),
        ({**SPOT, "weightUnit": None}, UNIT),
        ({**SPOT, "purity": None}, PURITY),
        ({**DEPRECIATED, "depreciationRate": "0.01"}, None),
        ({**DEPRECIATED, "depreciationRate": "99.99"}, None),
        ({**DEPRECIATED, "depreciationRate": "0"}, RATE),
        ({**DEPRECIATED, "depreciationRate": "100"}, RATE),
        (DEPRECIATED, RATE),
        # What spot and depreciation ask is asked of nothing else.
        ({"metal": "tin", "unitWeight": "0", "sellPremium": "500",
          "depreciationRate": "100"}, None),
    ],
)  # fmt: skip
def test_an_item_on_a_bound_is_kept_and_past_it_refused(alice, kw, refused):
    metals = new_account(alice, name="Metals", type="precious-metals")
    body = {"name": "Thing", "acquiredOn": "2024-01-10", "costBasis": "1000", **kw}
    r = make(alice, "Item", accountId=metals["id"], **body)
    if refused is None:
        assert r.status_code == 200, r.text
    else:
        assert refusals(r) == [refused]


def test_an_item_keeps_its_words_trimmed_and_only_what_its_valuation_and_account_use(alice):
    coll = new_account(alice, name="Coll", type="collectables")
    every = {"name": "  Watch  ", "category": " Watch ", "description": "  ", "location": " Safe ",
             "serial": "", "condition": " Mint ", "policy": " P-1 ", "notes": "  as typed ",
             "acquiredHow": "gift", "quantity": "2", "insuredValue": "50", "metal": "gold",
             "unitWeight": "1", "weightUnit": "ozt", "purity": ".999", "sellPremium": "5",
             "depreciationRate": "10", "address": " 1 Main St ", "closingCosts": "100",
             "primaryResidence": True, "personalUse": True}  # fmt: skip
    keys = ("name", "category", "description", "location", "serial", "condition", "policy",
            "notes", "acquiredHow", "quantity", "insuredValue", "metal", "unitWeight",
            "weightUnit", "purity", "sellPremium", "depreciationRate", "address", "closingCosts",
            "primaryResidence", "personalUse", "valuation")  # fmt: skip

    def kept(account, **kw):
        return {k: item(alice, account["id"], **{**every, **kw})[k] for k in keys}

    plain = {"name": "Watch", "category": "Watch", "description": None, "location": "Safe",
             "serial": None, "condition": "Mint", "policy": "P-1", "notes": "  as typed ",
             "acquiredHow": "gift", "quantity": "2.0", "insuredValue": "50.00", "metal": None,
             "unitWeight": None, "weightUnit": None, "purity": None, "sellPremium": "0.00",
             "depreciationRate": None, "address": None, "closingCosts": None,
             "primaryResidence": False, "personalUse": True, "valuation": "valuations"}  # fmt: skip
    assert kept(coll) == plain
    assert kept(coll, notes="", category=None, personalUse=False) == {
        **plain,
        "notes": None,
        "category": None,
        "personalUse": False,
    }
    assert kept(coll, valuation="depreciation") == {
        **plain,
        "valuation": "depreciation",
        "depreciationRate": "10.00",
    }
    assert kept(coll, valuation="spot") == {
        **plain, "valuation": "spot", "metal": "gold", "unitWeight": "1.0", "weightUnit": "ozt",
        "purity": "0.999", "sellPremium": "5.00",
    }  # fmt: skip
    homes = new_account(alice, name="Home", type="real-estate")
    assert kept(homes) == {
        **plain,
        "address": "1 Main St",
        "closingCosts": "100.00",
        "primaryResidence": True,
    }
    assert kept(homes, primaryResidence=False)["primaryResidence"] is False


def refused(r, status: int = 422) -> list[tuple[str | None, str, str]]:
    """A save's refusals with their status: each one's field, code and message."""
    assert r.status_code == status, r.text
    return [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


def test_items_are_only_in_physical_asset_accounts_and_stay_in_their_own(alice):
    checking = new_account(alice)
    r = alice.get(f"/ui/api/accounts/{checking['id']}/items")
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
        409, "not-physical", "This account doesn't hold items."
    )  # fmt: skip
    r = make(alice, "Item", accountId=checking["id"], name="X", acquiredOn=TODAY, costBasis="1")
    assert refused(r, 409) == [(None, "not-physical", "This account doesn't hold items.")]
    coll = new_account(alice, name="Coll", type="collectables")
    other = new_account(alice, name="Other", type="collectables")
    coin = item(alice, coll["id"], name="Coin")
    r = edit(alice, "Item", f"/ui/api/items/{coin['id']}", accountId=other["id"])
    assert refused(r) == [("accountId", "item-fixed", "An item stays in its account.")]


def test_an_item_its_valuations_and_improvements_not_there_or_deleted_are_not_found(alice):
    coll = new_account(alice, name="Coll", type="collectables")
    coin = item(alice, coll["id"], name="Coin")
    path = f"/ui/api/items/{coin['id']}"
    v = make(alice, "Valtn", itemId=coin["id"], date=TODAY, value="5").json()
    m = make(alice, "Imprv", itemId=coin["id"], date=TODAY, description="Case", amount="5").json()
    for kind, what, x in (("Valtn", "valuation", v), ("Imprv", "improvement", m)):
        missing = {"id": new_id(kind), "version": 1}
        not_found = [(None, "not-found", f"No such {what}.")]
        assert refused(change(alice, kind, missing), 404) == not_found
        assert remove(alice, kind, x).status_code == 200
        assert refused(change(alice, kind, x), 404) == not_found
    assert saved(edit(alice, "Item", path, name="Coin"))["valuations"] == []
    assert drop(alice, "Item", path).status_code == 200
    for got in (alice.get(path), alice.get(f"/ui/api/items/{new_id('Item')}")):
        assert (got.status_code, got.json()["code"], got.json()["detail"]) == (
            404, "not-found", "No such item."
        )  # fmt: skip


def test_a_reader_of_the_account_reads_its_items_and_changes_none(server, alice):
    coll = new_account(alice, name="Coll", type="collectables")
    coin = item(alice, coll["id"], name="Coin")
    v = make(alice, "Valtn", itemId=coin["id"], date=TODAY, value="5").json()
    m = make(alice, "Imprv", itemId=coin["id"], date=TODAY, description="Case", amount="5").json()
    bob_id = make_user(server, "bob").id
    bob = sign_in(server, "bob")
    assert share(alice, "account", coll["id"], users={bob_id: "read"}).status_code == 200
    path = f"/ui/api/items/{coin['id']}"
    nothing = dict.fromkeys(("mine", "writable", "deletable", "shareable", "configurable"), False)
    assert bob.get(path).json()["access"] == nothing
    owner = {**nothing, "mine": True, "writable": True, "deletable": True, "configurable": True}
    assert alice.get(path).json()["access"] == owner
    no = [(None, "share-read-only", "You can read this account but not change it.")]
    assert refused(edit(bob, "Item", path, name="Mine"), 403) == no
    assert refused(drop(bob, "Item", path), 403) == no
    assert refused(change(bob, "Valtn", v, value="6"), 403) == no
    assert refused(change(bob, "Imprv", m, amount="6"), 403) == no
    assert alice.get(path).json()["name"] == "Coin"


def test_an_items_changes_are_told_in_its_accounts_activity(alice):
    coll = new_account(alice, name="Coll", type="collectables")
    coin = item(alice, coll["id"], name="Coin")
    path = f"/ui/api/items/{coin['id']}"
    steps = [
        lambda: edit(alice, "Item", path, name="Old coin"),
        lambda: sell(alice, coin["id"], TODAY, "10"),
        lambda: edit(alice, "Item", path, saleFees="1"),  # sold already: a change
        lambda: drop(alice, "Item", path),
    ]
    for n, step in enumerate(steps, 1):
        clock.fix(T0 + dt.timedelta(minutes=n))
        assert step().status_code == 200
    feed = alice.get("/ui/api/activity").json()["items"]
    told = [(x["kind"], x["subjectKind"], x["subjectId"], x["actorName"]) for x in feed]
    assert [x for x in told if x[0].startswith("item.")] == [
        (kind, "account", coll["id"], "Alice")
        for kind in ("item.deleted", "item.changed", "item.sold", "item.changed", "item.added")
    ]


def test_a_sale_has_amounts_of_zero_or_more_on_a_day_from_acquired_to_today(server, alice):
    coll = new_account(alice, name="Coll", type="collectables")
    coin = item(alice, coll["id"], name="Coin", acquiredOn="2024-01-10")
    path = f"/ui/api/items/{coin['id']}"
    amount = ("amount-invalid", "Zero or more.")
    assert refused(sell(alice, coin["id"], TODAY, "-0.01", "-0.01")) == [("proceeds", *amount)]
    assert refused(sell(alice, coin["id"], TODAY, "0", "-0.01")) == [("saleFees", *amount)]
    assert refused(sell(alice, coin["id"], "2024-01-09", "1")) == [
        ("soldOn", "sold-before-bought", "On or after the day it was acquired.")
    ]
    assert refused(sell(alice, coin["id"], TOMORROW, "1")) == [
        ("soldOn", "date-ahead", "Not after today.")
    ]
    assert saved(sell(alice, coin["id"], TODAY, "0", "0"))["sale"]["soldOn"] == TODAY
    # Without its amounts, a sale is for nothing, with no fees.
    out = saved(edit(alice, "Item", path, soldOn="2024-01-10", proceeds=None, saleFees=None))
    assert out["sale"] == {"soldOn": "2024-01-10", "proceeds": "0.00", "fees": "0.00",
                           "gain": "-1000.00", "collectable": True, "deductible": True}  # fmt: skip
    # Taken away, its amounts go with it and the item is held again.
    out = saved(edit(alice, "Item", path, soldOn=None, proceeds="5", saleFees="5"))
    assert out["sale"] is None and out["value"] == "1000.00"
    with server.db.read(unscoped="test") as s:
        it = s.get(Item, coin["id"])
        assert (it.soldOn, it.proceeds, it.saleFees) == (None, None, None)


def test_a_sale_shows_its_fees_and_only_a_loss_on_personal_use_property_isnt_deductible(alice):
    cars = new_account(alice, name="Cars", type="vehicle")
    even = item(alice, cars["id"], name="Even", costBasis="1000", personalUse=True)
    sale = saved(sell(alice, even["id"], TODAY, "1050", "50"))["sale"]
    assert (sale["fees"], sale["gain"], sale["deductible"]) == ("50.00", "0.00", True)
    business = item(alice, cars["id"], name="Van", costBasis="1000")
    sale = saved(sell(alice, business["id"], TODAY, "900"))["sale"]
    assert (sale["gain"], sale["deductible"], sale["collectable"]) == ("-100.00", True, False)


def test_a_valuation_is_zero_or_more_from_a_known_source_on_a_day_not_ahead(alice):
    coll = new_account(alice, name="Coll", type="collectables")
    watch = item(alice, coll["id"], name="Watch")
    other = item(alice, coll["id"], name="Other")

    def valuation(**kw):
        return make(alice, "Valtn", **{"itemId": watch["id"], "date": TODAY, "value": "100", **kw})

    amount = [("value", "amount-invalid", "Zero or more.")]
    source = [("source", "source-invalid", "Appraisal, sale, guide or estimate.")]
    ahead = [("date", "date-ahead", "Not after today.")]
    assert refused(valuation(value="-0.01")) == amount
    assert refused(valuation(source="hunch")) == source
    assert refused(valuation(date=TOMORROW)) == ahead
    for name in ("appraisal", "sale", "guide"):
        assert valuation(source=name).json()["source"] == name
    assert valuation(note=" By the insurer ").json()["note"] == "By the insurer"
    v = valuation(value="0", note="  ").json()
    assert (v["date"], v["value"], v["source"], v["note"]) == (TODAY, "0.00", "estimate", None)
    # Changed, by the same rules, and it stays with its item.
    assert refused(change(alice, "Valtn", v, itemId=other["id"])) == [
        ("itemId", "valuation-fixed", "A valuation stays with its item.")
    ]
    assert refused(change(alice, "Valtn", v, value="-0.01")) == amount
    assert refused(change(alice, "Valtn", v, source="hunch")) == source
    assert refused(change(alice, "Valtn", v, date=TOMORROW)) == ahead
    out = saved(change(alice, "Valtn", v, date="2025-01-02", value="7", source="sale",
                       note=" Sold one "))  # fmt: skip
    assert (out["date"], out["value"], out["source"], out["note"]) == (
        "2025-01-02", "7.00", "sale", "Sold one"
    )  # fmt: skip
    assert saved(change(alice, "Valtn", out, date=TODAY, note="As noted"))["note"] == "As noted"


def test_an_improvement_says_what_was_done_for_more_than_nothing_on_a_day_not_ahead(alice):
    homes = new_account(alice, name="Home", type="real-estate")
    home = item(alice, homes["id"], name="Home")
    other = item(alice, homes["id"], name="Other")

    def improvement(**kw):
        body = {"itemId": home["id"], "date": "2025-05-20", "description": "Roof", "amount": "1"}
        return make(alice, "Imprv", **{**body, **kw})

    missing = [("description", "description-missing", "What was done.")]
    nothing = [("amount", "amount-invalid", "More than zero.")]
    assert refused(improvement(description="  ")) == missing
    assert refused(improvement(amount="0")) == nothing
    ahead = [("date", "date-ahead", "Not after today.")]
    assert refused(improvement(date=TOMORROW)) == ahead
    m = improvement(description=" Roof ", amount="0.01").json()
    assert (m["date"], m["description"], m["amount"]) == ("2025-05-20", "Roof", "0.01")
    assert refused(change(alice, "Imprv", m, itemId=other["id"])) == [
        ("itemId", "improvement-fixed", "An improvement stays with its item.")
    ]
    assert refused(change(alice, "Imprv", m, description=" ")) == missing
    assert refused(change(alice, "Imprv", m, amount="0")) == nothing
    assert refused(change(alice, "Imprv", m, date=TOMORROW)) == ahead
    assert saved(change(alice, "Imprv", m, date=TODAY))["date"] == TODAY
    m = alice.get(f"/ui/api/items/{home['id']}").json()["improvements"][0]
    out = saved(change(alice, "Imprv", m, date="2025-06-01", description=" New roof ",
                       amount="1"))  # fmt: skip
    assert (out["date"], out["description"], out["amount"]) == ("2025-06-01", "New roof", "1.00")


def test_an_items_history_is_its_value_at_each_months_end_and_today(alice):
    coll = new_account(alice, name="Coll", type="collectables")
    # Acquired in November: its months run over the year's end.
    watch = item(alice, coll["id"], name="Watch", acquiredOn="2025-11-20")
    make(alice, "Valtn", itemId=watch["id"], date="2025-12-15", value="1100")
    make(alice, "Valtn", itemId=watch["id"], date="2026-02-01", value="1200")
    got = alice.get(f"/ui/api/items/{watch['id']}").json()["history"]
    assert got == [
        ["2025-11-30", "1000.00"], ["2025-12-31", "1100.00"], ["2026-01-31", "1100.00"],
        ["2026-02-28", "1200.00"], ["2026-03-31", "1200.00"], ["2026-04-30", "1200.00"],
        ["2026-05-31", "1200.00"], ["2026-06-30", "1200.00"], ["2026-07-31", "1200.00"],
        ["2026-08-31", "1200.00"], ["2026-09-30", "1200.00"], [TODAY, "1200.00"],
    ]  # fmt: skip
    # Sold, it ends on the day of the sale, worth nothing from then.
    saved(sell(alice, watch["id"], "2026-02-10", "1300"))
    got = alice.get(f"/ui/api/items/{watch['id']}").json()["history"]
    assert got[-2:] == [["2026-01-31", "1100.00"], ["2026-02-10", "0.00"]]


def test_an_items_history_at_spot_takes_each_months_last_price_of_its_owner(server, alice):
    metals = new_account(alice, name="Metals", type="precious-metals")
    bar = item(alice, metals["id"], name="Bar", acquiredOn="2026-07-15", costBasis="1800",
               **{**SPOT, "purity": "1"})  # fmt: skip
    with server.db.tx(unscoped="test") as s:
        owner = s.get(Account, metals["id"]).ownerId
        points = [(d(2026, 7, 1), 2000), (d(2026, 8, 10), 2100), (d(2026, 8, 20), 2200),
                  (d(2026, 10, 1), 2300)]  # fmt: skip
        spot(s, owner, "gold", *points)
    got = alice.get(f"/ui/api/items/{bar['id']}").json()
    assert got["history"] == [
        ["2026-07-31", "2000.00"], ["2026-08-31", "2200.00"], ["2026-09-30", "2200.00"],
        [TODAY, "2300.00"],
    ]  # fmt: skip
    assert (got["spot"], got["spotAsOf"], got["value"]) == ("2300.00", "2026-10-01", "2300.00")


def test_an_items_valuations_and_improvements_are_listed_newest_first(alice):
    homes = new_account(alice, name="Home", type="real-estate")
    home = item(alice, homes["id"], name="Home", acquiredOn="2020-01-10", costBasis="300000")
    for day, value in (("2024-01-01", "350000"), ("2025-01-01", "400000")):
        make(alice, "Valtn", itemId=home["id"], date=day, value=value, source="appraisal")
    for day, amount in (("2021-05-01", "100"), ("2022-05-01", "200")):
        make(alice, "Imprv", itemId=home["id"], date=day, description="Paint", amount=amount)
    got = alice.get(f"/ui/api/items/{home['id']}").json()
    assert [(v["date"], v["value"], v["source"]) for v in got["valuations"]] == [
        ("2025-01-01", "400000.00", "appraisal"), ("2024-01-01", "350000.00", "appraisal")
    ]  # fmt: skip
    assert [(m["date"], m["amount"]) for m in got["improvements"]] == [
        ("2022-05-01", "200.00"), ("2021-05-01", "100.00")
    ]  # fmt: skip
    latest = got["latest"]
    assert (latest["date"], latest["value"], latest["source"]) == (
        "2025-01-01", "400000.00", "appraisal"
    )  # fmt: skip
    assert (got["basis"], got["value"], got["gain"], got["years"], got["stale"]) == (
        "300300.00", "400000.00", "99700.00", "6.8", True
    )  # fmt: skip


def test_an_accounts_items_add_up_only_what_is_still_held(alice):
    metals = new_account(alice, name="Metals", type="precious-metals")
    # 3 coins of a gram of .9999 gold: 0.0964 fine ounces, to four places.
    item(alice, metals["id"], name="Coins", costBasis="300", quantity="3",
                 **{**SPOT, "unitWeight": "1", "weightUnit": "g"})  # fmt: skip
    medal = item(alice, metals["id"], name="Medal", acquiredOn="2025-04-13", costBasis="100")
    make(alice, "Valtn", itemId=medal["id"], date="2026-01-01", value="150")
    sold = item(alice, metals["id"], name="Sold", acquiredOn="2022-10-13", costBasis="500")
    saved(sell(alice, sold["id"], "2024-04-13", "500"))
    v = alice.get(f"/ui/api/accounts/{metals['id']}/items").json()
    rows = {r["name"]: r for r in v["items"]}
    assert (rows["Coins"]["fineOunces"], rows["Medal"]["fineOunces"]) == ("0.0964", None)
    assert [(r["name"], r["basis"], r["value"], r["gain"], r["years"]) for r in v["items"]] == [
        ("Sold", "500.00", "0.00", "0.00", "1.5"),  # held to its sale
        ("Coins", "300.00", "300.00", "0.00", "2.8"),
        ("Medal", "100.00", "150.00", "50.00", "1.5"),
    ]  # fmt: skip
    assert (rows["Medal"]["latest"]["value"], rows["Coins"]["latest"]) == ("150.00", None)
    assert (v["value"], v["basis"], v["gain"]) == ("450.00", "400.00", "50.00")
    assert [(m["metal"], m["ounces"], m["cost"]) for m in v["metals"]] == [
        ("gold", "0.0964", "300.00")
    ]


def test_a_loan_is_secured_by_an_unsold_item_of_property_a_vehicle_or_another_asset(alice):
    assert alice.get("/ui/api/items").json()["items"] == []
    kept = {}
    for name, type_ in (("Home", "real-estate"), ("Cars", "vehicle"), ("Boats", "other-asset"),
                        ("Coll", "collectables"), ("Metals", "precious-metals")):  # fmt: skip
        kept[name] = new_account(alice, name=name, type=type_)["id"]
    assert alice.get("/ui/api/items").json()["items"] == []
    for account, name in (("Home", "B house"), ("Cars", "A car"), ("Boats", "C boat"),
                          ("Coll", "Coin"), ("Metals", "Bar")):  # fmt: skip
        item(alice, kept[account], name=name)
    sold = item(alice, kept["Cars"], name="D old car")
    saved(sell(alice, sold["id"], TODAY, "1"))
    gone = item(alice, kept["Cars"], name="E gone car")
    assert drop(alice, "Item", f"/ui/api/items/{gone['id']}").status_code == 200
    got = alice.get("/ui/api/items").json()["items"]
    assert [(x["name"], x["accountName"], x["accountId"]) for x in got] == [
        ("A car", "Cars", kept["Cars"]), ("B house", "Home", kept["Home"]),
        ("C boat", "Boats", kept["Boats"]),
    ]  # fmt: skip
    assert got[0]["id"] != sold["id"]


def test_an_items_documents_come_with_it_and_a_change_to_them_changes_its_version(alice):
    coll = new_account(alice, name="Coll", type="collectables")
    ids_ = []
    for name in ("receipt.pdf", "appraisal.pdf"):
        up = alice.post(
            "/ui/api/receipts",
            files={"file": (name, b"%PDF-1.4 " + name.encode(), "application/pdf")},
        )
        ids_.append(up.json()["id"])
    first, second = ids_
    watch = item(alice, coll["id"], name="Watch", receiptIds=[first])
    assert [x["id"] for x in watch["documents"]] == [first]
    clock.fix(T0 + dt.timedelta(minutes=1))
    path = f"/ui/api/items/{watch['id']}"
    out = saved(edit(alice, "Item", path, receiptIds={"add": [second], "remove": [first]}))
    assert [x["id"] for x in out["documents"]] == [second]
    assert out["version"] == watch["version"] + 1


def test_an_items_loans_are_the_live_ones_it_secures_with_what_is_owed_today(alice):
    homes = new_account(alice, name="Home", type="real-estate")
    home = item(alice, homes["id"], name="Home", costBasis="500000")
    # A car loan secures nothing; a bridge loan on the home starts next month: nothing owed yet.
    car = new_account(alice, name="Car loan", type="auto-loan")["id"]
    saved(terms(alice, car, principal="20000", startDate="2026-01-01", termMonths=60, rate="5"))
    bridge = new_account(alice, name="Bridge", type="mortgage")["id"]
    saved(terms(alice, bridge, principal="100000", startDate="2026-11-01", termMonths=12,
                rate="7", securedById=home["id"]))  # fmt: skip
    path = f"/ui/api/accounts/{homes['id']}/items"
    row = alice.get(path).json()["items"][0]
    assert row["loans"] == [{"accountId": bridge, "name": "Bridge", "owed": "0.00"}]
    assert row["equity"] == "500000.00"
    # Its loan's account deleted, it secures nothing.
    assert drop(alice, "Acct", f"/ui/api/accounts/{bridge}", confirm=True).status_code == 200
    row = alice.get(path).json()["items"][0]
    assert (row["loans"], row["equity"]) == ([], None)


def test_an_item_and_its_parts_record_who_made_and_who_deleted_them(server, alice):
    coll = new_account(alice, name="Coll", type="collectables")
    coin = item(alice, coll["id"], name="Coin")
    v = make(alice, "Valtn", itemId=coin["id"], date=TODAY, value="5").json()
    m = make(alice, "Imprv", itemId=coin["id"], date=TODAY, description="Case", amount="5").json()
    assert remove(alice, "Valtn", v).status_code == 200
    assert remove(alice, "Imprv", m).status_code == 200
    assert drop(alice, "Item", f"/ui/api/items/{coin['id']}").status_code == 200
    with server.db.read(unscoped="test") as s:
        owner = s.get(Account, coll["id"]).ownerId
        for entity, x in ((Item, coin), (ItemValuation, v), (Improvement, m)):
            row = s.get(entity, x["id"])
            assert (row.createdById, row.deletedById) == (owner, owner), entity


def test_an_item_changed_keeps_what_the_change_leaves_alone(alice):
    metals = new_account(alice, name="Metals", type="precious-metals")
    bar = item(alice, metals["id"], name="Bar", **SPOT)
    out = saved(edit(alice, "Item", f"/ui/api/items/{bar['id']}", name="Gold bar"))
    assert (out["name"], out["metal"], out["purity"]) == ("Gold bar", "gold", "0.9999")
    homes = new_account(alice, name="Home", type="real-estate")
    home = item(alice, homes["id"], name="Home", address="1 Elm St", closingCosts="900",
                primaryResidence=True)  # fmt: skip
    out = saved(edit(alice, "Item", f"/ui/api/items/{home['id']}", name="Our home"))
    assert (out["address"], out["closingCosts"], out["primaryResidence"]) == (
        "1 Elm St", "900.00", True
    )  # fmt: skip


def test_an_item_changed_to_spot_has_its_metals_price_asked_for(server, alice):
    coll = new_account(alice, name="Coll", type="collectables")
    coin = item(alice, coll["id"], name="Coin")
    with server.db.read(unscoped="test") as s:
        assert assets.find_metal(s, "platinum") is None
    path = f"/ui/api/items/{coin['id']}"
    out = saved(edit(alice, "Item", path, **{**SPOT, "metal": "platinum"}))
    assert (out["valuation"], out["metal"]) == ("spot", "platinum")
    with server.db.read(unscoped="test") as s:
        assert assets.find_metal(s, "platinum").symbol == "XPT"


def test_an_item_changed_by_someone_it_is_shared_with_is_told_to_its_owner(server, alice):
    coll = new_account(alice, name="Coll", type="collectables")
    coin = item(alice, coll["id"], name="Coin")
    bob_id = make_user(server, "bob").id
    bob = sign_in(server, "bob")
    assert share(alice, "account", coll["id"], users={bob_id: "write"}).status_code == 200
    clock.fix(T0 + dt.timedelta(minutes=1))
    assert edit(bob, "Item", f"/ui/api/items/{coin['id']}", name="Old coin").status_code == 200
    feed = alice.get("/ui/api/activity").json()["items"]
    assert (feed[0]["kind"], feed[0]["actorName"]) == ("item.changed", "Bob")


def test_an_items_row_takes_its_basis_on_the_day_its_value_is_taken(alice):
    """An improvement dated after the day shown (made today, the clock read a day back) is in
    neither the basis nor the value: the gain stays what it was (CR3-433)."""
    homes = new_account(alice, name="Home", type="real-estate")
    home = item(alice, homes["id"], name="Home", acquiredOn="2025-01-02", costBasis="1000")
    r = make(alice, "Imprv", itemId=home["id"], date=TODAY, description="Roof", amount="300")
    assert r.status_code == 200, r.text
    clock.fix(T0 - dt.timedelta(days=1))
    row = alice.get(f"/ui/api/accounts/{homes['id']}/items").json()["items"][0]
    assert (row["basis"], row["value"], row["gain"]) == ("1000.00", "1000.00", "0.00")


def test_pmi_without_an_original_value_reads_the_homes_basis_when_the_loan_was_made(alice):
    """An improvement made after the loan doesn't raise the value it started from (CR3-434)."""
    homes = new_account(alice, name="Home", type="real-estate")
    home = item(alice, homes["id"], name="Home", acquiredOn="2025-01-02", costBasis="500000")
    loan = new_account(alice, name="Mortgage", type="mortgage")

    def ends():
        r = terms(alice, loan["id"], principal="450000", startDate="2025-02-01", termMonths=360,
                  rate="6", pmi="150", securedById=home["id"])  # fmt: skip
        e = saved(r)["equity"]
        return e["pmiRequest"], e["pmiEnds"]

    before = ends()
    r = make(alice, "Imprv", itemId=home["id"], date="2026-01-05", description="Addition",
             amount="200000")  # fmt: skip
    assert r.status_code == 200, r.text
    assert ends() == before


def test_a_mortgage_without_an_original_value_stops_pmi_when_its_screen_says(alice):
    """S1.9.5, CR3-439: the schedule's PMI ends at 78% of the original value, the home's basis
    when the loan was made unless one is typed, the day the screen names; a value typed
    stands."""
    homes = new_account(alice, name="Home", type="real-estate")
    home = item(alice, homes["id"], name="Home", acquiredOn="2025-01-02", costBasis="500000")
    loan = new_account(alice, name="Mortgage", type="mortgage")

    def schedule(**more):
        v = saved(terms(alice, loan["id"], principal="450000", startDate="2025-02-01",
                        termMonths=360, rate="6", pmi="150", securedById=home["id"],
                        **more))  # fmt: skip
        first_free = next(r["date"] for r in v["rows"] if r["pmi"] == "0.00")
        return v["equity"]["pmiEnds"], first_free

    ends, first_free = schedule()
    assert ends is not None and first_free == ends
    typed_ends, typed_free = schedule(originalValue="600000")
    assert typed_free == typed_ends and typed_free < first_free
