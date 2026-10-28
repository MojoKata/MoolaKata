"""Options (requirements S3.2, S3.3): the four trades, short options as negative lots, and
their gains at close or expiry."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import remove
from test_accounts import add, new_account

from moolakata import clock

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


def opt(
    c,
    acct,
    action,
    day,
    premium,
    contracts="1",
    right="put",
    strike="480",
    expiry="2026-11-20",
    fees="0.65",
    **kw,
):
    r = c.post(
        f"/ui/api/accounts/{acct}/options",
        json={
            "date": day,
            "action": action,
            "underlying": "msft",
            "right": right,
            "strike": strike,
            "expiry": expiry,
            "contracts": contracts,
            "premium": premium,
            "fees": fees,
            **kw,
        },
    )
    return r


def test_a_short_put_is_a_negative_lot_and_realizes_at_close(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    r = opt(alice, brk["id"], "sell-to-open", "2026-09-02", "6.40", contracts="2")
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["amount"] == "1279.35", "2 × 100 × 6.40 less 0.65"
    v = alice.get("/ui/api/positions").json()
    row = v["open"][0]
    assert row["symbol"] == "MSFT 20NOV26 480 P" and row["side"] == "short"
    assert row["quantity"] == "-2.0" and row["cost"] == "-1279.35"
    r = opt(alice, brk["id"], "buy-to-close", "2026-10-01", "2.10", contracts="2")
    assert r.status_code == 201 and r.json()["amount"] == "-420.65"
    v = alice.get("/ui/api/positions").json()
    assert v["open"] == []
    closed = v["closed"][0]
    assert closed["realized"] == "858.70" and closed["how"] == "bought back"


def test_a_long_call_closes_or_expires(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    opt(
        alice,
        brk["id"],
        "buy-to-open",
        "2026-08-01",
        "3.00",
        right="call",
        strike="500",
        contracts="3",
        fees="0",
    )
    opt(
        alice,
        brk["id"],
        "sell-to-close",
        "2026-09-01",
        "5.00",
        right="call",
        strike="500",
        contracts="1",
        fees="0",
    )
    v = alice.get("/ui/api/positions").json()
    assert v["open"][0]["quantity"] == "2.0"
    assert v["closed"][0]["realized"] == "200.00"
    too_many = opt(
        alice,
        brk["id"],
        "sell-to-close",
        "2026-09-02",
        "5.00",
        right="call",
        strike="500",
        contracts="5",
    )
    assert too_many.status_code == 422
    assert too_many.json()["errors"][0]["code"] == "nothing-to-close"


def test_option_kinds_go_through_their_own_endpoint(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    r = alice.post(
        "/ui/api/transactions",
        json={
            "accountId": brk["id"],
            "date": "2026-09-01",
            "amount": "100",
            "kind": "sell-to-open",
            "symbol": "MSFT",
            "quantity": "1",
        },
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "option-kind"
    bad = opt(
        alice, brk["id"], "sell-to-open", "2026-09-02", "1", contracts="1.5", right="straddle"
    )
    assert {e["field"] for e in bad.json()["errors"]} == {"contracts", "right"}


def _held(c, acct, symbol):
    return next(
        (r for r in c.get("/ui/api/positions").json()["open"] if r["symbol"] == symbol), None
    )


def test_a_short_put_assigned_folds_the_credit_into_the_stock_basis(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    opt(alice, brk["id"], "sell-to-open", "2026-09-02", "6.40", contracts="1", fees="0")
    put = _held(alice, brk["id"], "MSFT 20NOV26 480 P")
    r = alice.post(
        f"/ui/api/accounts/{brk['id']}/options/{put['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-11-20"},
    )
    assert r.status_code == 201, r.text
    end, stock = r.json()
    assert end["kind"] == "assign" and stock["amount"] == "-48000.00"
    msft = _held(alice, brk["id"], "MSFT")
    assert msft["quantity"] == "100.0" and msft["cost"] == "47360.00", "48,000 less the 640 credit"
    assert _held(alice, brk["id"], "MSFT 20NOV26 480 P") is None
    assert (
        alice.post(
            f"/ui/api/accounts/{brk['id']}/options/{put['instrumentId']}/settle",
            json={"how": "assign", "date": "2026-11-20"},
        ).status_code
        == 422
    )


def test_an_assignment_follows_its_opening_trade_and_goes_with_its_stock_trade(server, alice):
    # B12: the premium is folded in at replay, so a change to the opening trade (a re-import
    # with a corrected amount) follows through; deleting the assignment deletes its stock trade.
    from moolakata.store.entities.accounts import Transaction

    brk = new_account(alice, name="Brokerage", type="brokerage")
    sold = opt(alice, brk["id"], "sell-to-open", "2026-09-02", "6.40", fees="0").json()
    put = _held(alice, brk["id"], "MSFT 20NOV26 480 P")
    end, stock = alice.post(
        f"/ui/api/accounts/{brk['id']}/options/{put['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-11-20"},
    ).json()
    with server.db.tx() as s:
        s.get(Transaction, sold["id"]).amount = D("700.00")
    assert _held(alice, brk["id"], "MSFT")["cost"] == "47300.00"
    r = remove(alice, "Txn", end)
    assert r.status_code == 200, r.text
    assert _held(alice, brk["id"], "MSFT") is None
    assert _held(alice, brk["id"], "MSFT 20NOV26 480 P") is not None
    items = alice.get("/ui/api/transactions", params={"accountId": brk["id"]}).json()["items"]
    assert stock["id"] not in {t["id"] for t in items}
    assert end["id"] not in {t["id"] for t in items}


def test_a_short_call_assigned_adds_its_credit_to_the_proceeds(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    add(
        alice,
        brk["id"],
        "-40000.00",
        "2025-01-02",
        kind="buy",
        symbol="MSFT",
        quantity="100",
        price="400",
    )
    opt(
        alice, brk["id"], "sell-to-open", "2026-09-02", "5.00", right="call", strike="450", fees="0"
    )
    call = _held(alice, brk["id"], "MSFT 20NOV26 450 C")
    alice.post(
        f"/ui/api/accounts/{brk['id']}/options/{call['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-11-20"},
    )
    closed = next(
        r for r in alice.get("/ui/api/positions").json()["closed"] if r["symbol"] == "MSFT"
    )
    assert closed["proceeds"] == "45500.00" and closed["realized"] == "5500.00"
    assert closed["term"] == "long"


def test_a_long_call_exercised_adds_its_premium_to_the_basis(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    opt(alice, brk["id"], "buy-to-open", "2026-09-02", "3.00", right="call", strike="450", fees="0")
    call = _held(alice, brk["id"], "MSFT 20NOV26 450 C")
    alice.post(
        f"/ui/api/accounts/{brk['id']}/options/{call['instrumentId']}/settle",
        json={"how": "exercise", "date": "2026-11-20"},
    )
    assert _held(alice, brk["id"], "MSFT")["cost"] == "45300.00"


def test_out_of_the_money_expires_the_day_after(server, alice):
    from moolakata import options
    from moolakata.prices import refresh as pricing
    from moolakata.store.entities.accounts import Instrument

    pricing.install()
    from moolakata.store.entities.prices import Price

    brk = new_account(alice, name="Brokerage", type="brokerage")
    opt(alice, brk["id"], "sell-to-open", "2026-09-02", "6.40", expiry="2026-10-09", fees="0")
    opt(
        alice,
        brk["id"],
        "sell-to-open",
        "2026-09-02",
        "2.00",
        strike="530",
        expiry="2026-10-09",
        fees="0",
    )
    with server.db.tx() as s:
        msft = s.query(Instrument).filter_by(symbol="MSFT").one()
        s.add(
            Price(
                instrumentId=msft.id,
                date=dt.date(2026, 10, 9),
                close=500,
                source="manual",
                fetchedAt=clock.now(),
                updatedAt=clock.now(),
            )
        )
    with server.db.tx() as s:
        assert options.expire_due(s, dt.date(2026, 10, 13)) == 1, "the 480 put; the 530 is ITM"
    v = alice.get("/ui/api/positions").json()
    assert [r["symbol"] for r in v["open"]] == ["MSFT 09OCT26 530 P"]
    expired = next(r for r in v["closed"] if r["how"] == "expired")
    assert expired["realized"] == "640.00"
    from moolakata import alerts

    assert [a.kind for a in alerts.evaluate(server)] == ["option-expired"]


def test_each_option_trade_has_its_premium_pl_and_return(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    add(alice, brk["id"], amount="100000.00", kind="deposit")
    # A short put: 2 sold at 5.00, 1 bought back at 2.00, the other expires.
    opt(alice, brk["id"], "sell-to-open", "2026-09-01", "5.00", contracts="2")
    opt(alice, brk["id"], "buy-to-close", "2026-09-15", "2.00")
    assert (
        opt(alice, brk["id"], "sell-to-open", "2026-09-02", "3.00", right="call").status_code == 201
    )
    r = alice.post(
        f"/ui/api/accounts/{brk['id']}/options/"
        + next(
            p["instrumentId"]
            for p in alice.get("/ui/api/positions").json()["open"]
            if p["symbol"].endswith("480 P")
        )
        + "/settle",
        json={"how": "expired", "date": "2026-10-01"},
    )
    assert r.status_code == 201, r.text
    rows = alice.get("/ui/api/positions/option-trades").json()["items"]
    put = next(x for x in rows if x["symbol"].endswith("480 P"))
    assert put["side"] == "short" and put["contracts"] == "2.0"
    assert (put["opened"], put["closed"], put["how"]) == ("2026-09-01", "2026-10-01", "expired")
    assert put["premiumIn"] == "999.35" and put["premiumOut"] == "200.65"
    assert put["pl"] == "798.70"
    assert put["capitalAtRisk"] == "96000.00", "480 a share on 200 shares, cash secured"
    assert put["returnPct"] == 0.83
    call = next(x for x in rows if x["symbol"].endswith("480 C"))
    assert call["closed"] is None and rows[0] is call, "open trades first"


def test_assigned_a_call_with_no_shares_opens_a_short_stock_lot(alice):
    # N7: a short sale at the strike, not a sale without a lot; buying the shares closes it.
    brk = new_account(alice, name="Brokerage", type="brokerage")
    add(alice, brk["id"], "10000.00", "2026-09-01", kind="deposit")
    opt(alice, brk["id"], "sell-to-open", "2026-09-02", "6.40", right="call", fees="0")
    call = _held(alice, brk["id"], "MSFT 20NOV26 480 C")
    r = alice.post(
        f"/ui/api/accounts/{brk['id']}/options/{call['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-11-20"},
    )
    assert r.status_code == 201, r.text
    msft = _held(alice, brk["id"], "MSFT")
    assert msft["quantity"] == "-100.0" and msft["cost"] == "-48640.00"
    r = alice.post(
        "/ui/api/transactions",
        json={
            "accountId": brk["id"],
            "date": "2026-11-23",
            "amount": "-47000.00",
            "kind": "buy",
            "symbol": "MSFT",
            "quantity": "100",
            "price": "470",
        },
    )
    assert r.status_code == 201, r.text
    assert _held(alice, brk["id"], "MSFT") is None
    gains = alice.get("/ui/api/positions/gains", params={"by": "term"}).json()
    assert "1640.00" in str(gains), gains


def test_only_the_expiry_days_close_decides_an_expiry(server, alice):
    # S3.6, A26: a close from before the expiry day decides nothing; the user is asked.
    from moolakata import options
    from moolakata.prices import refresh as pricing
    from moolakata.store.entities.accounts import Instrument
    from moolakata.store.entities.prices import Price

    pricing.install()
    brk = new_account(alice, name="Brokerage", type="brokerage")
    opt(alice, brk["id"], "sell-to-open", "2026-09-02", "6.40", expiry="2026-10-09", fees="0")
    with server.db.tx() as s:
        msft = s.query(Instrument).filter_by(symbol="MSFT").one()
        s.add(
            Price(
                instrumentId=msft.id,
                date=dt.date(2026, 10, 8),
                close=500,
                source="manual",
                fetchedAt=clock.now(),
                updatedAt=clock.now(),
            )
        )
    with server.db.tx() as s:
        assert options.expire_due(s, dt.date(2026, 10, 13)) == 0


def test_a_split_strike_is_rounded_to_the_thousandth():
    # S3.10.1: as the OCC prints it.
    from decimal import Decimal

    from moolakata.options.adjust import adjusted_strike

    assert adjusted_strike(Decimal("100"), Decimal("3")) == Decimal("33.333")
    assert adjusted_strike(Decimal("50"), Decimal("1.5")) == Decimal("33.333")
    assert adjusted_strike(Decimal("200"), Decimal("2")) == Decimal("100")
