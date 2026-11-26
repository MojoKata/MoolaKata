"""The Dashboard (requirements S12.2.1): the recurring transactions coming up, and what needs
attention beyond what test_figures covers: giving behind its pace, stale valuations, and
sources that need attention."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import giving_plan, make, saved
from test_accounts import add, new_account

from moolakata import clock, ids
from moolakata.store.entities.accounts import Account, Holding, Instrument
from moolakata.store.entities.connector import Connection, Connector
from moolakata.store.entities.prices import PriceSource

T0 = dt.datetime(2026, 9, 20, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def jane(server, frozen):
    make_user(server, "jane")
    return sign_in(server, "jane")


def dash(c) -> dict:
    r = c.get("/ui/api/dashboard")
    assert r.status_code == 200, r.text
    return r.json()


def made(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def attention(c, kind: str) -> list[dict]:
    return [a for a in dash(c)["attention"] if a["kind"] == kind]


# ---- Upcoming (S7.5, S12.2.1) ----


def test_upcoming_lists_each_series_next_date_in_the_coming_month_soonest_first(jane):
    bank = new_account(jane, openingBalance="5000.00", openingDate="2026-01-01")
    card = new_account(
        jane, name="Card", type="credit-card", mask="5555", openingBalance="0.00",
        openingDate="2026-01-01",
    )  # fmt: skip
    for m in (6, 7, 8, 9):
        add(jane, bank["id"], "-2410.77", f"2026-{m:02d}-01", payee="Rocket Mortgage")
        add(jane, card["id"], "-15.49", f"2026-{m:02d}-05", payee="Netflix")
        add(jane, bank["id"], "-80.00", f"2026-{m - 4:02d}-10", payee="Gym")  # ended in May
    for day in ("2026-08-14", "2026-08-28", "2026-09-11"):
        add(jane, bank["id"], "4820.00", day, kind="deposit", payee="Acme Corp Payroll")
    got = dash(jane)["upcoming"]
    assert [(u["payee"], u["date"], u["every"], u["amount"]) for u in got] == [
        ("Acme Corp Payroll", "2026-09-25", "2 weeks", "4820.00"),
        ("Rocket Mortgage", "2026-10-01", "month", "-2410.77"),
        ("Netflix", "2026-10-05", "month", "-15.49"),
    ]


def test_upcoming_leaves_out_investing_accounts_and_keeps_five(jane):
    from moolakata.ui import dashboard

    bank = new_account(jane, openingBalance="5000.00", openingDate="2026-01-01")
    broker = new_account(jane, name="Broker", type="brokerage")
    for m in (6, 7, 8, 9):
        add(jane, broker["id"], "-5.00", f"2026-{m:02d}-02", payee="Fee")
        for k in range(dashboard.UPCOMING_ROWS + 1):
            add(
                jane, bank["id"], "-1.00", f"2026-{m:02d}-{k + 2:02d}", payee=f"Sub {'ABCDEFGH'[k]}"
            )
    got = dash(jane)["upcoming"]
    assert [u["payee"] for u in got] == [
        f"Sub {'ABCDEFGH'[k]}" for k in range(dashboard.UPCOMING_ROWS)
    ]


def test_a_cash_accounts_transfer_out_is_upcoming_and_the_cards_side_is_not(server, jane):
    """S7.6.1: a card payment from checking is money out of checking; the card's side of it,
    a transfer in, is not counted again."""
    from moolakata.store.entities.accounts import Transaction

    bank = new_account(jane, openingBalance="5000.00", openingDate="2026-01-01")
    card = new_account(jane, name="Card", type="credit-card", mask="5555")
    with server.db.tx(unscoped="test") as s:
        for m in (6, 7, 8, 9):
            pair = [
                Transaction(id=ids.new_id("Txn"), accountId=aid, date=dt.date(2026, m, 12),
                            kind="transfer", amount=amount, payee="Card payment")
                for aid, amount in ((bank["id"], -300), (card["id"], 300))
            ]  # fmt: skip
            s.add_all(pair)
            s.flush()
            pair[0].transferId, pair[1].transferId = pair[1].id, pair[0].id
    got = dash(jane)["upcoming"]
    assert [(u["payee"], u["amount"]) for u in got] == [("Card payment", "-300.00")]


# ---- Giving against its target (S7.9.6) ----


def _plan(c, **fields):
    return saved(giving_plan(c, 2026, **{"targetKind": "amount", "amount": "1200", **fields}))


def test_giving_behind_its_even_pace_needs_attention(jane):
    _plan(jane)
    (a,) = attention(jane, "giving-behind")
    # Sep 20 is day 263 of 365: the pace is $865, and nothing given is 0% of the target.
    assert a["text"] == "Giving is $865 behind pace · 0% of the target"
    assert a["link"] == "/ui/giving"


def test_giving_on_pace_or_without_a_plan_needs_nothing(server, jane):
    assert attention(jane, "giving-behind") == []
    _plan(jane, amount="100")
    org = made(make(jane, "Orgzn", name="Food Bank"))
    made(make(jane, "Dnatn", organisationId=org["id"], date="2026-09-01", kind="cash",
                amount="80"))  # fmt: skip
    assert attention(jane, "giving-behind") == []


# ---- Stale valuations (S4.3, S1.10.2) ----


def test_a_holding_valued_from_a_stale_statement_needs_its_owner(server, jane):
    acct = new_account(jane, name="Kept", type="brokerage")
    with server.db.tx(unscoped="test") as s:
        s.get(Account, acct["id"]).statementInterval = "none"
        fund = Instrument(id=ids.new_id("Instr"), symbol="XKEPTZ", instrumentClass="mutual-fund")
        s.add(fund)
        s.flush()
        s.add(Holding(id=ids.new_id("Hold"), accountId=acct["id"], instrumentId=fund.id,
                      asOf=dt.date(2025, 7, 1), quantity=10, marketValue=1000))  # fmt: skip
    (a,) = attention(jane, "statement-value-old")
    assert a["text"] == "Kept: a holding is still valued from an old statement"
    assert a["link"] == f"/ui/accounts/{acct['id']}/holdings"


def test_items_valued_over_a_year_ago_need_their_owner(jane):
    coll = new_account(jane, name="Collectables", type="collectables")
    for name, day in (("Watch", "2025-06-01"), ("Pen", "2025-09-01"), ("Coin", "2026-01-01")):
        it = made(make(jane, "Item", accountId=coll["id"], name=name, acquiredOn="2024-01-10",
                        costBasis="1000"))  # fmt: skip
        made(make(jane, "Valtn", itemId=it["id"], date=day, value="1200", source="appraisal"))
    (a,) = attention(jane, "valuation-old")
    assert a["text"] == "Collectables: 2 valuations over a year old" and a["count"] == 2
    assert a["link"] == f"/ui/accounts/{coll['id']}/items"


# ---- Sources that need attention (S18.5.3, S16.16) ----


def _connection(server, owner_id: str, state: str, label: str) -> str:
    with server.db.tx(unscoped="test") as s:
        row = Connector(id=ids.new_id("Cnctr"), state="paired")
        s.add(row)
        s.flush()
        conn = Connection(id=ids.new_id("Conn"), ownerId=owner_id, connectorId=row.id,
                          driver="ofx-direct", label=label, state=state)  # fmt: skip
        s.add(conn)
        return conn.id


def test_a_connection_failing_needs_its_owner_and_the_owner_of_an_account_it_keeps(server, jane):
    john = make_user(server, "john")
    mine = new_account(jane, name="Joint")
    conn = _connection(server, john.id, "needs-sign-in", "John's bank login")
    johns = sign_in(server, "john")
    (a,) = attention(johns, "connection-failing")
    assert a["text"] == "John's bank login needs a sign-in" and a["link"] == "/ui/profile"
    assert attention(jane, "connection-failing") == []
    with server.db.tx(unscoped="test") as s:
        s.get(Account, mine["id"]).connectionId = conn
        s.get(Connection, conn).state = "failing"
    assert [a["text"] for a in attention(jane, "connection-failing")] == [
        "John's bank login is failing"
    ]
    with server.db.tx(unscoped="test") as s:
        s.get(Connection, conn).state = "ok"
    assert attention(jane, "connection-failing") == []


def test_a_price_source_failing_past_the_threshold_needs_the_admins(server, admin_client, frozen):
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    with server.db.tx(unscoped="test") as s:
        ok = clock.now() - dt.timedelta(hours=47)
        s.add(PriceSource(id=ids.new_id("Src"), name="tiingo", enabled=True, lastOkAt=ok,
                          lastError="HTTP 401"))  # fmt: skip
    assert attention(admin_client, "source-failing") == []
    clock.fix(T0 + dt.timedelta(hours=2))
    (a,) = attention(admin_client, "source-failing")
    assert a["text"] == "Tiingo is failing" and a["link"] == "/ui/settings/prices"
    assert attention(jane, "source-failing") == []
