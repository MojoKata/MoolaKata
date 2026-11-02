import datetime as dt
from decimal import Decimal as D

from conftest import make_user, sign_in
from edits import edit, make, remove
from sqlalchemy import text
from test_accounts import add, new_account

from moolakata.ledger import performance as perf

d = dt.date


def test_twr_ignores_contributions_and_irr_weighs_them():
    values = [(d(2026, 1, 1), D(100)), (d(2026, 7, 1), D(220)), (d(2026, 12, 31), D(242))]
    flow = {d(2026, 7, 1): D(100)}  # $100 more went in mid-year
    r = perf.twr(values, flow)
    assert r.quantize(D("0.0001")) == D("0.2100")  # 10% then 10%
    rate = perf.irr(d(2026, 1, 1), D(100), flow, d(2026, 12, 31), D(242))
    # $100 for the year and $100 for half of it grow into $242: about 28.7% a year.
    assert D("0.28") < rate < D("0.29")
    assert perf.irr(d(2026, 1, 1), D(0), {}, d(2026, 12, 31), D(0)) is None


def test_benchmark_gets_the_same_money():
    values = [(d(2026, 1, 1), D(100)), (d(2026, 1, 2), D(205)), (d(2026, 1, 3), D(210))]
    flow = {d(2026, 1, 2): D(100)}
    index = [(d(2026, 1, 1), D(10)), (d(2026, 1, 2), D(11)), (d(2026, 1, 3), D(11))]
    out = perf.benchmark(values, flow, index)
    assert out == [
        (d(2026, 1, 1), D(100)),
        (d(2026, 1, 2), D("220.00")),
        (d(2026, 1, 3), D("220.00")),
    ]
    mixed = perf.mix([(D("0.5"), index), (D("0.5"), [(x, D(1)) for x, _ in index])])
    assert mixed[1][1] == D("1.05")


def test_flows_count_money_in_and_out_not_income():
    class T:
        def __init__(self, kind, amount, inst=None):
            self.kind, self.amount, self.instrumentId = kind, D(amount), inst
            self.date, self.quantity = d(2026, 1, 1), None

    out = perf.flows(
        [
            T("deposit", 100),
            T("dividend", 5, "I"),
            T("buy", -50, "I"),
            T("withdrawal", -20),
            T("interest", 1),
        ]
    )
    assert out == {d(2026, 1, 1): D(80)}


def test_dashboard_counts_owned_and_ticked_accounts(server):
    make_user(server, "alice")
    make_user(server, "bob")
    alice, bob = sign_in(server, "alice"), sign_in(server, "bob")
    a = new_account(alice, openingBalance="1000.00", openingDate="2026-01-01")
    add(alice, a["id"], "-40.00", "2026-09-01")
    card = new_account(
        alice,
        name="Card",
        type="credit-card",
        mask="5555",
        openingBalance="0.00",
        openingDate="2026-01-01",
    )
    add(alice, card["id"], "-60.00", "2026-09-02")
    dash = alice.get("/ui/api/dashboard").json()
    assert dash["netWorth"] == "900.00" and dash["cash"] == "960.00"
    assert [g["group"] for g in dash["groups"]] == ["banking", "liabilities"]
    assert any(x["kind"] == "uncategorised" for x in dash["attention"])
    series = alice.get("/ui/api/dashboard/series", params={"range": "1M"}).json()
    assert series["groups"] == ["banking", "liabilities"]
    assert series["points"][-1]["total"] == "900.00"
    assert bob.get("/ui/api/dashboard").json()["netWorth"] == "0.00"


def test_portfolio_series_returns_and_holdings(server):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(
        c, name="Brokerage", type="brokerage", openingBalance="0.00", openingDate="2026-06-30"
    )
    add(c, a["id"], "1000.00", "2026-07-01", kind="deposit")
    add(c, a["id"], "-1000.00", "2026-07-01", kind="buy", symbol="VTI", quantity="10", price="100")
    p = make(c, "Portf", name="Mine", accountIds=[a["id"]]).json()
    s = c.get(f"/ui/api/portfolios/{p['id']}/series", params={"range": "1Y"}).json()
    assert s["end"] == "1000.00" and s["contributed"] == "1000.00" and s["growth"] == "0.00"
    assert s["benchmark"] == "VT"
    rows = c.get(f"/ui/api/portfolios/{p['id']}/returns").json()["items"]
    assert rows[-1]["name"] == "Mine" and set(rows[-1]["periods"]) == {
        "1M",
        "3M",
        "YTD",
        "1Y",
        "3Y",
        "5Y",
    }
    h = c.get(f"/ui/api/portfolios/{p['id']}/holdings").json()
    assert h["holdings"][0]["symbol"] == "VTI" and h["holdings"][0]["weight"] == "100.0"
    assert c.get("/ui/api/portfolios/all/series").status_code == 200


def test_key_storage_and_backups_for_admins(admin_client, server):
    ks = admin_client.get("/ui/api/settings/keys").json()
    assert ks["fingerprint"].startswith("mk-") and ks["reminderMonths"] == 12
    assert ks["previous"] == [] and ks["scheduled"] is None and ks["lastReencryption"] is None
    with server.db.read(unscoped="test") as s:  # the data, wherever it sits: the file or its log
        pages = s.execute(text("PRAGMA page_count")).scalar_one()
    assert ks["databaseBytes"] == pages * 4096 >= server.config.db_path.stat().st_size
    t = admin_client.post("/ui/api/settings/keys/test").json()
    assert t["ok"] and [x["name"] for x in t["checks"]][:2] == ["Keyring", "Database"]
    b = admin_client.get("/ui/api/settings/backups").json()
    assert b["copies"] == 14 and b["backups"] == []
    from moolakata.store import maintenance

    maintenance.backup(server.config, server.store)
    b = admin_client.get("/ui/api/settings/backups").json()
    assert len(b["backups"]) == 1 and b["backups"][0]["masterKey"] == ks["fingerprint"]


def test_a_portfolio_keeps_a_closed_account_up_to_the_day_it_closed(server):
    # B22: the past keeps it (R3.10); from its closing on it counts nothing, and its leaving
    # is no loss.
    make_user(server, "alice")
    c = sign_in(server, "alice")
    ids = []
    for name, mask in (("Kept", "1111"), ("Closed", "2222")):
        a = new_account(c, name=name, mask=mask, openingBalance="0.00", openingDate="2026-06-30")
        add(c, a["id"], "1000.00", "2026-07-01", kind="deposit")
        ids.append(a)
    p = make(c, "Portf", name="Both", accountIds=[x["id"] for x in ids]).json()
    r = edit(c, "Acct", f"/ui/api/accounts/{ids[1]['id']}", closedOn="2026-08-15")
    assert r.status_code == 200, r.text
    s = c.get(f"/ui/api/portfolios/{p['id']}/series", params={"range": "1Y"}).json()
    by_day = {x["date"]: x["value"] for x in s["points"]}
    assert by_day["2026-08-01"] == "2000.00"
    assert s["end"] == "1000.00" and s["growth"] == "0.00"


def test_a_portfolios_returns_count_a_closed_accounts_gain(server):
    # B22: an account's gain before it closed stays in the portfolio's returns (R3.10).
    make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(c, name="Closed", mask="3333", openingBalance="0.00", openingDate="2026-06-30")
    add(c, a["id"], "1000.00", "2026-07-01", kind="deposit")
    add(c, a["id"], "100.00", "2026-08-01", kind="interest")
    keep = new_account(c, name="Kept", mask="4444", openingBalance="0.00", openingDate="2026-06-30")
    add(c, keep["id"], "1000.00", "2026-07-01", kind="deposit")
    p = make(c, "Portf", name="Both", accountIds=[a["id"], keep["id"]]).json()
    before = c.get(f"/ui/api/portfolios/{p['id']}/returns").json()["items"][-1]["periods"]
    assert edit(c, "Acct", f"/ui/api/accounts/{a['id']}", closedOn="2026-08-15").status_code == 200
    after = c.get(f"/ui/api/portfolios/{p['id']}/returns").json()["items"][-1]["periods"]
    assert before["YTD"] and after["YTD"] == before["YTD"], (before, after)


def test_a_deleted_account_leaves_a_portfolios_past(server):
    """Deleting is a correction (R3.10): the account was never there, past included."""
    make_user(server, "alice")
    c = sign_in(server, "alice")
    ids = []
    for name, mask in (("Kept", "1111"), ("Mistake", "2222")):
        a = new_account(c, name=name, mask=mask, openingBalance="0.00", openingDate="2026-06-30")
        add(c, a["id"], "1000.00", "2026-07-01", kind="deposit")
        ids.append(a)
    p = make(c, "Portf", name="Both", accountIds=[x["id"] for x in ids]).json()
    assert remove(c, "Acct", c.get(f"/ui/api/accounts/{ids[1]['id']}").json()).status_code == 200
    s = c.get(f"/ui/api/portfolios/{p['id']}/series", params={"range": "1Y"}).json()
    by_day = {x["date"]: x["value"] for x in s["points"]}
    assert by_day["2026-08-01"] == "1000.00"
