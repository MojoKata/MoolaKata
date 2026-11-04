"""Options (requirements S3.2, S3.3): the four trades, short options as negative lots, and
their gains at close or expiry."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import change, create, make, option_trade, remove, saved
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
    return option_trade(c, acct, day, action, "msft", right, strike, expiry, contracts, premium,
                        fees, **kw)  # fmt: skip


def test_a_short_put_is_a_negative_lot_and_realizes_at_close(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    t = saved(opt(alice, brk["id"], "sell-to-open", "2026-09-02", "6.40", contracts="2"))
    assert t["amount"] == "1279.35", "2 × 100 × 6.40 less 0.65"
    v = alice.get("/ui/api/positions").json()
    row = v["open"][0]
    assert row["symbol"] == "MSFT 20NOV26 480 P" and row["side"] == "short"
    assert row["quantity"] == "-2.0" and row["cost"] == "-1279.35"
    r = opt(alice, brk["id"], "buy-to-close", "2026-10-01", "2.10", contracts="2")
    assert saved(r)["amount"] == "-420.65"
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


def test_an_option_trade_is_made_with_its_contract_and_an_end_by_settling(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")
    r = create(alice, "Txn", accountId=brk["id"], date="2026-09-01", amount="100",
               kind="expire", symbol="MSFT", quantity="1")  # fmt: skip
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "option-kind"
    bad = opt(
        alice, brk["id"], "sell-to-open", "2026-09-02", "1", contracts="1.5", right="straddle"
    )
    assert {e["field"] for e in bad.json()["errors"]} == {"quantity", "right"}
    r = create(alice, "Txn", accountId=brk["id"], date="2026-09-02", amount="100",
               kind="sell-to-open", symbol="MSFT", right="put", strike="480",
               expiry="2026-11-20", quantity="1", price="6.40")  # fmt: skip
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "amount-mismatch"


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
        json={"how": "assign", "date": "2026-11-20", "contracts": "1"},
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
            json={"how": "assign", "date": "2026-11-20", "contracts": "1"},
        ).status_code
        == 422
    )


def test_an_assignment_follows_its_opening_trade_and_goes_with_its_stock_trade(server, alice):
    # B12: the premium is folded in at replay, so a change to the opening trade (a re-import
    # with a corrected amount) follows through; deleting the assignment deletes its stock trade.
    from moolakata.store.entities.accounts import Transaction

    brk = new_account(alice, name="Brokerage", type="brokerage")
    sold = saved(opt(alice, brk["id"], "sell-to-open", "2026-09-02", "6.40", fees="0"))
    put = _held(alice, brk["id"], "MSFT 20NOV26 480 P")
    end, stock = alice.post(
        f"/ui/api/accounts/{brk['id']}/options/{put['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-11-20", "contracts": "1"},
    ).json()
    with server.db.tx(unscoped="test") as s:
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
        json={"how": "assign", "date": "2026-11-20", "contracts": "1"},
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
        json={"how": "exercise", "date": "2026-11-20", "contracts": "1"},
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
    with server.db.tx(unscoped="test") as s:
        msft = s.query(Instrument).filter_by(symbol="MSFT").one()
        s.add(
            Price(
                instrumentId=msft.id,
                date=dt.date(2026, 10, 9),
                close=500,
                source="test",  # a price source's close
                fetchedAt=clock.now(),
                updatedAt=clock.now(),
            )
        )
    with server.db.tx(unscoped="test") as s:
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
        opt(alice, brk["id"], "sell-to-open", "2026-09-02", "3.00", right="call").status_code == 200
    )
    r = alice.post(
        f"/ui/api/accounts/{brk['id']}/options/"
        + next(
            p["instrumentId"]
            for p in alice.get("/ui/api/positions").json()["open"]
            if p["symbol"].endswith("480 P")
        )
        + "/settle",
        json={"how": "expired", "date": "2026-10-01", "contracts": "1"},
    )
    assert r.status_code == 201, r.text
    rows = alice.get("/ui/api/positions/option-trades").json()["items"]
    put = next(x for x in rows if x["symbol"].endswith("480 P"))
    assert put["side"] == "short" and put["contracts"] == "2.0"
    assert (put["opened"], put["closed"], put["how"]) == ("2026-09-01", "2026-10-01", "expired")
    assert put["premiumIn"] == "999.35" and put["premiumOut"] == "200.65"
    assert put["pl"] == "798.70"
    assert put["capitalRequired"] == "96000.00", "480 a share on 200 shares, cash secured"
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
        json={"how": "assign", "date": "2026-11-20", "contracts": "1"},
    )
    assert r.status_code == 201, r.text
    msft = _held(alice, brk["id"], "MSFT")
    assert msft["quantity"] == "-100.0" and msft["cost"] == "-48640.00"
    r = make(
        alice,
        "Txn",
        accountId=brk["id"],
        date="2026-11-23",
        amount="-47000.00",
        kind="buy",
        symbol="MSFT",
        quantity="100",
        price="470",
    )
    assert r.status_code == 200, r.text
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
    with server.db.tx(unscoped="test") as s:
        msft = s.query(Instrument).filter_by(symbol="MSFT").one()
        s.add(
            Price(
                instrumentId=msft.id,
                date=dt.date(2026, 10, 8),
                close=500,
                source="test",  # a price source's close
                fetchedAt=clock.now(),
                updatedAt=clock.now(),
            )
        )
    with server.db.tx(unscoped="test") as s:
        assert options.expire_due(s, dt.date(2026, 10, 13)) == 0


def test_a_split_strike_is_rounded_to_the_thousandth():
    # S3.10.1: as the OCC prints it.
    from decimal import Decimal

    from moolakata.options.adjust import adjusted_strike

    assert adjusted_strike(Decimal("100"), Decimal("3")) == Decimal("33.333")
    assert adjusted_strike(Decimal("50"), Decimal("1.5")) == Decimal("33.333")
    assert adjusted_strike(Decimal("200"), Decimal("2")) == Decimal("100")


# ---------- each rule, with data that tells a wrong answer apart ----------


def test_a_symbol_is_upper_case_with_its_right_as_c_or_p():
    from moolakata import options

    day = dt.date(2026, 11, 20)
    assert options.symbol("msft", day, "call", D("482.50")) == "MSFT 20NOV26 482.5 C"
    assert options.symbol("msft", day, "put", D("480")) == "MSFT 20NOV26 480 P"


def test_an_occ_ticker_has_the_strike_in_thousandths_over_eight_digits():
    from types import SimpleNamespace as NS

    from moolakata import options

    day = dt.date(2026, 11, 20)
    put = NS(right="put", strike=D("480"), expiry=day)
    assert options.occ("MSFT", put) == "O:MSFT261120P00480000"
    call = NS(right="call", strike=D("33.333"), expiry=day)
    assert options.occ("MSFT1", call) == "O:MSFT1261120C00033333"


def test_in_the_money_is_past_the_strike_never_on_it():
    from types import SimpleNamespace as NS

    from moolakata import options

    prices = [D("479.99"), D("480"), D("480.01")]
    call, put = NS(right="call", strike=D("480")), NS(right="put", strike=D("480"))
    assert [options.in_the_money(call, p) for p in prices] == [False, False, True]
    assert [options.in_the_money(put, p) for p in prices] == [True, False, False]


def test_a_contract_is_made_once_with_its_terms_and_named_for_people(server):
    from moolakata import options

    day = dt.date(2026, 11, 20)
    with server.db.tx(unscoped="test") as s:
        call, cc = options.contract(s, "msft", "call", D("482.50"), day)
        assert call.symbol == "MSFT 20NOV26 482.5 C"
        assert call.name == "MSFT call 482.5, expiring Nov 20, 2026"
        assert (cc.right, cc.strike, cc.expiry, cc.multiplier) == ("call", D("482.50"), day, 100)
        put, pc = options.contract(s, "msft", "put", D("480"), day, multiplier=10)
        assert put.name == "MSFT put 480, expiring Nov 20, 2026" and pc.multiplier == 10
        put.name = "The hedge"  # a name given is kept
        again, same = options.contract(s, "MSFT", "put", D("480"), day)
        assert (again.id, same.id, again.name) == (put.id, pc.id, "The hedge")
        put_id = put.id
        pc.mark_deleted(None)
    with server.db.tx(unscoped="test") as s:
        assert options.contract_of(s, put_id) is None, "a deleted contract is no contract"


def _plain(**kw):
    from types import SimpleNamespace as NS

    return NS(**({"deliverable": None, "deliverableCash": None, "underlyingId": "U",
                  "multiplier": 100} | kw))  # fmt: skip


def _parts(cash=None):
    """An adjusted contract: 100 shares of A, 50 of B, and its cash."""
    import json

    rows = [{"instrumentId": "A", "shares": "100"}, {"instrumentId": "B", "shares": 50}]
    return _plain(deliverable=json.dumps(rows), deliverableCash=cash)


def _book(monkeypatch, name, prices, *, owned, session=None):
    """valuation's `name` answered from `prices`, {(owner or None, instrument, day): Price},
    for the session given alone: the session to call with."""
    from moolakata import valuation

    session = session or object()

    def lookup(s, ids, day=None, **kw):
        assert s is session, "read in the caller's session"
        assert ("owner" in kw) == owned
        who = kw.get("owner")
        return {i: prices[who, i, day] for i in ids if (who, i, day) in prices}

    monkeypatch.setattr(valuation, name, lookup)
    return session


def test_the_market_close_is_the_underlyings_or_the_deliverables_worth_a_share(monkeypatch):
    # S3.6, S3.10.5: 100 A at 10 and 50 B at 3, and 25 in cash, over 100 shares: 11.75 a
    # share, as of the older of the two closes; a part without a close leaves it unknown.
    from moolakata import options
    from moolakata.valuation import Price

    day, before = dt.date(2026, 11, 20), dt.date(2026, 11, 19)
    closes = {
        (None, "U", day): Price(D("480.5"), before, "close"),
        (None, "A", day): Price(D("10"), day, "close"),
        (None, "B", day): Price(D("3"), before, "close"),
    }
    s = _book(monkeypatch, "closes", closes, owned=False)
    assert options.market_close(s, _plain(), day) == (D("480.5"), before)
    assert options.market_close(s, _plain(underlyingId="X"), day) is None
    assert options.market_close(s, _plain(), before) is None, "the day asked, no other"
    assert options.market_close(s, _parts(D("25")), day) == (D("11.75"), before)
    assert options.market_close(s, _parts(), day) == (D("11.5"), before), "no cash is none"
    del closes[None, "B", day]
    assert options.market_close(s, _parts(D("25")), day) is None


def test_a_contracts_worth_a_share_reads_its_owners_prices_that_day(monkeypatch):
    # S3.10.5, as the market close above, from the prices the owner sees on the day asked.
    from moolakata import options
    from moolakata.valuation import Price

    day, before = dt.date(2026, 11, 20), dt.date(2026, 11, 19)
    prices = {
        ("Usr_1", "U", day): Price(D("480.5"), before, "statement"),
        ("Usr_1", "A", day): Price(D("10"), day, "close"),
        ("Usr_1", "B", day): Price(D("3"), before, "trade"),
    }
    s = _book(monkeypatch, "prices", prices, owned=True)
    assert options.per_share(s, _plain(), day, "Usr_1") == (D("480.5"), before)
    assert options.per_share(s, _plain(), day, "Usr_2") is None
    assert options.per_share(s, _plain(), None, "Usr_1") is None
    assert options.per_share(s, _parts(D("25")), day, "Usr_1") == (D("11.75"), before)
    assert options.per_share(s, _parts(), day, "Usr_1") == (D("11.5"), before)
    assert options.per_share(s, _parts(), day, "Usr_2") is None
    assert options.per_share(s, _parts(), None, "Usr_1") is None


def test_a_deliverables_parts_are_weighed_by_value_or_by_shares_without_prices(monkeypatch):
    # S3.10.4: 100 A at 10 and 50 B at 30 weigh 1,000 to 1,500; with a price missing, 100
    # shares to 50. A contract never adjusted delivers its multiplier of the underlying.
    from types import SimpleNamespace as NS

    from moolakata import options
    from moolakata.store.entities.accounts import Instrument
    from moolakata.valuation import Price

    day = dt.date(2026, 11, 20)
    prices = {
        ("Usr_1", "A", day): Price(D("10"), day, "close"),
        ("Usr_1", "B", day): Price(D("30"), day, "close"),
    }
    s = NS(get=lambda kind, iid: NS(id=iid) if kind is Instrument else None)
    _book(monkeypatch, "prices", prices, owned=True, session=s)

    def weights(c, owner, when=day):
        return [(i.id, q, w) for i, q, w in options.deliverable(s, c, when, owner)]

    assert weights(_plain(multiplier=10), "Usr_1") == [("U", D(10), D(1))]
    assert weights(_parts(), "Usr_1") == [("A", D(100), D("0.4")), ("B", D(50), D("0.6"))]
    by_shares = [("A", D(100), D(100) / 150), ("B", D(50), D(50) / 150)]
    assert weights(_parts(), "Usr_2") == by_shares
    assert weights(_parts(), "Usr_1", None) == by_shares
    # Parts all worth nothing that day weigh nothing: the last part takes the strike.
    prices["Usr_1", "A", day] = prices["Usr_1", "B", day] = Price(D(0), day, "close")
    assert weights(_parts(), "Usr_1") == [("A", D(100), D(0)), ("B", D(50), D(0))]


def test_a_read_asks_for_each_contract_once(server):
    # A read over many accounts asks for an option's contract, or that a stock has none, once.
    from sqlalchemy import event

    from moolakata import options

    with server.db.tx(unscoped="test") as s:
        inst, c = options.contract(s, "msft", "put", D("480"), dt.date(2026, 11, 20))
        asked_for = [inst.id, c.underlyingId]
    with server.db.read(unscoped="test") as s:
        asked = []
        event.listen(s, "do_orm_execute", asked.append)
        first = [options.contract_of(s, i) for i in asked_for]
        again = [options.contract_of(s, i) for i in asked_for]
        assert len(asked) == 2 and first[1] is None
        assert [x and x.id for x in again] == [first[0].id, None]


def _ended(server, acct_id, symbol, how, contracts=None, terms=None):
    """options.settle as the route calls it, on Nov 20, 2026, after `terms` changes the
    contract: the account's owner, and each record made as its fields, with the basis of the
    lot it opened."""
    from types import SimpleNamespace as NS

    from moolakata import options
    from moolakata.store.entities.accounts import Account, Instrument, Lot

    keys = ("id", "kind", "amount", "payee", "instrumentId", "quantity", "price", "lotMethod",
            "proceedsAdjustment", "optionTransactionId", "createdById")  # fmt: skip
    with server.db.tx(unscoped="test") as s:
        a = s.get(Account, acct_id)
        inst = s.query(Instrument).filter_by(symbol=symbol, deleted=False).one()
        if terms:
            terms(s, options.contract_of(s, inst.id))
        made = options.settle(s, a.ownerId, a, inst, how, dt.date(2026, 11, 20), contracts)
        s.flush()
        basis = {x.transactionId: x.costBasis for x in s.query(Lot).filter_by(accountId=a.id)}
        return a.ownerId, [
            NS(**{k: getattr(t, k) for k in keys}, basis=basis.get(t.id)) for t in made
        ]


def _adjusted(cash, *symbols):
    """Terms that adjust a contract to 10 shares of each of `symbols` and `cash` a contract."""

    def terms(s, c):
        import json

        from moolakata.store.repos import ledger as repo

        ids_ = [repo.instrument(s, x, None, "equity").id for x in symbols]
        c.deliverable = json.dumps([{"instrumentId": i, "shares": "10"} for i in ids_])
        c.deliverableCash = D(cash)

    return terms


@pytest.mark.parametrize(
    ("held", "how", "contracts", "error"),
    [
        ("shares", "assign", "1", ("instrumentId", "not-an-option", "That isn't an option.")),
        ("closed", "expired", None,
         ("instrumentId", "nothing-open", "Nothing of it is open in this account.")),
        ("short", "assign", "3", ("contracts", "contracts-invalid", "Up to 2 contracts.")),
        ("short", "assign", "0", ("contracts", "contracts-invalid", "Up to 2 contracts.")),
        ("short", "exercise", "1",
         ("how", "short-exercise", "A short option is assigned, not exercised.")),
        ("long", "assign", "1",
         ("how", "long-assign", "A long option is exercised, not assigned.")),
    ],
)  # fmt: skip
def test_a_settlement_refused_names_its_field_and_says_why(server, alice, held, how, contracts,
                                                          error):  # fmt: skip
    from moolakata.errors import Problem

    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    symbol = "MSFT 20NOV26 480 P"
    if held == "shares":
        add(alice, brk, "-40000.00", "2026-08-03", kind="buy", symbol="MSFT", quantity="100",
            price="400")  # fmt: skip
        symbol = "MSFT"
    elif held == "long":  # one contract: a long position of 1 is long
        opt(alice, brk, "buy-to-open", "2026-09-02", "6.40", fees="0")
    else:
        opt(alice, brk, "sell-to-open", "2026-09-02", "6.40", contracts="2", fees="0")
        if held == "closed":
            opt(alice, brk, "buy-to-close", "2026-09-03", "6.40", contracts="2", fees="0")
    with pytest.raises(Problem) as e:
        _ended(server, brk, symbol, how, contracts and D(contracts))
    assert [(f.field, f.code, f.message) for f in e.value.errors] == [error]


def test_an_expiry_ends_every_contract_held_and_makes_nothing_else(server, alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    opt(alice, brk, "sell-to-open", "2026-09-02", "6.40", contracts="2", fees="0")
    owner, made = _ended(server, brk, "MSFT 20NOV26 480 P", "expired")
    assert [(t.kind, t.amount, t.quantity, t.payee, t.createdById) for t in made] == [
        ("expire", D(0), D(2), "Expired MSFT 20NOV26 480 P", owner)
    ]


def test_an_assignment_or_exercise_trades_the_shares_at_the_strike_and_says_which(server, alice):
    # S3.4: a short put assigned buys at the strike, opening a lot; a long put exercised sells
    # at it, by the account's lot method. Each names what it was, and is the user's.
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    opt(alice, brk, "sell-to-open", "2026-09-02", "6.40", strike="482.5", fees="0")
    opt(alice, brk, "buy-to-open", "2026-09-02", "3.00", strike="470", fees="0")
    owner, (end, buy) = _ended(server, brk, "MSFT 20NOV26 482.5 P", "assign")
    assert (end.kind, end.payee) == ("assign", "Assigned MSFT 20NOV26 482.5 P")
    assert (buy.kind, buy.amount, buy.quantity, buy.price) == ("buy", D("-48250"), 100, D("482.5"))
    assert (buy.payee, buy.lotMethod, buy.basis) == ("Buy MSFT at 482.5 (assigned)", None, D(48250))
    assert (buy.optionTransactionId, buy.proceedsAdjustment) == (end.id, None)
    assert (end.createdById, buy.createdById) == (owner, owner)
    owner, (end, sell) = _ended(server, brk, "MSFT 20NOV26 470 P", "exercise")
    assert (end.kind, end.payee) == ("exercise", "Exercised MSFT 20NOV26 470 P")
    assert (sell.kind, sell.amount, sell.quantity, sell.price) == ("sell", D(47000), 100, D(470))
    assert (sell.payee, sell.lotMethod, sell.basis) == (
        "Sell MSFT at 470 (exercised)",
        "fifo",
        None,
    )
    assert (sell.optionTransactionId, sell.proceedsAdjustment) == (end.id, None)
    assert (end.createdById, sell.createdById) == (owner, owner)


def test_an_adjusted_assignment_spreads_strike_and_cash_the_last_part_taking_the_rounding(
    server, alice
):
    # S3.10.4: 2 of 3 short puts at 100, adjusted to 10 shares each of three companies and
    # 0.50 a contract, without prices (a third each): the 20,000 paid is 6,666.67, 6,666.67
    # and 6,666.66, and the 1.00 of cash, which comes in as its own deposit, comes off the
    # bases as 0.33, 0.33 and 0.34, all of it.
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    opt(alice, brk, "sell-to-open", "2026-09-02", "1.00", contracts="3", strike="100", fees="0")
    terms = _adjusted("0.50", "AAA", "BBB", "CCC")
    owner, made = _ended(server, brk, "MSFT 20NOV26 100 P", "assign", D(2), terms)
    end, *buys, cash = made
    assert end.quantity == 2
    assert [(t.kind, t.amount, t.quantity, t.price, t.basis) for t in buys] == [
        ("buy", D("-6666.67"), 20, D("333.3335"), D("6666.34")),
        ("buy", D("-6666.67"), 20, D("333.3335"), D("6666.34")),
        ("buy", D("-6666.66"), 20, D("333.333"), D("6666.32")),
    ]
    assert [t.payee for t in buys] == [f"Buy {x} at 100 (assigned)" for x in ("AAA", "BBB", "CCC")]
    assert {(t.lotMethod, t.proceedsAdjustment, t.optionTransactionId) for t in buys} == {
        (None, None, end.id)
    }
    assert (cash.kind, cash.amount, cash.payee, cash.optionTransactionId) == (
        "deposit",
        D("1.00"),
        "Deliverable cash (assigned MSFT 20NOV26 100 P)",
        end.id,
    )
    assert {t.createdById for t in made} == {owner}


def test_an_adjusted_exercise_sells_each_part_its_cash_going_with_the_proceeds(server, alice):
    # S3.10.4: 2 long puts at 100 on the same three parts: each sold for a third of 20,000,
    # the 1.00 of cash delivered out of the account and off the proceeds, all of it.
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    opt(alice, brk, "buy-to-open", "2026-09-02", "1.00", contracts="2", strike="100", fees="0")
    terms = _adjusted("0.50", "AAA", "BBB", "CCC")
    owner, made = _ended(server, brk, "MSFT 20NOV26 100 P", "exercise", None, terms)
    end, *sells, cash = made
    assert [(t.kind, t.amount, t.proceedsAdjustment, t.lotMethod, t.basis) for t in sells] == [
        ("sell", D("6666.67"), D("-0.33"), "fifo", None),
        ("sell", D("6666.67"), D("-0.33"), "fifo", None),
        ("sell", D("6666.66"), D("-0.34"), "fifo", None),
    ]
    assert [t.payee for t in sells] == [
        f"Sell {x} at 100 (exercised)" for x in ("AAA", "BBB", "CCC")
    ]
    assert (cash.kind, cash.amount, cash.payee, cash.optionTransactionId, cash.createdById) == (
        "withdrawal",
        D("-1.00"),
        "Deliverable cash (exercised MSFT 20NOV26 100 P)",
        end.id,
        owner,
    )


def test_an_adjusted_assignment_weighs_its_parts_by_the_owners_prices_that_day(
    server, alice, monkeypatch
):
    # S3.10.4: 10 AAA at 30 and 10 BBB at 10 take three quarters and a quarter of the 10,000
    # paid; prices another day, or another owner's, would weigh them by shares, half each.
    from moolakata.store.entities.accounts import Account
    from moolakata.valuation import Price

    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    opt(alice, brk, "sell-to-open", "2026-09-02", "1.00", strike="100", fees="0")
    with server.db.read(unscoped="test") as s:
        owner = s.get(Account, brk).ownerId
    adjust = _adjusted("0", "AAA", "BBB")

    def terms(s, c):
        from moolakata.store.repos import ledger as repo

        adjust(s, c)
        day = dt.date(2026, 11, 20)
        aaa, bbb = (repo.instrument(s, x, None, "equity").id for x in ("AAA", "BBB"))
        prices = {
            (owner, aaa, day): Price(D(30), day, "close"),
            (owner, bbb, day): Price(D(10), day, "close"),
        }
        _book(monkeypatch, "prices", prices, owned=True, session=s)

    _, (_, aaa, bbb) = _ended(server, brk, "MSFT 20NOV26 100 P", "assign", None, terms)
    assert [(t.amount, t.price) for t in (aaa, bbb)] == [(D(-7500), D(750)), (D(-2500), D(250))]


def test_expiring_what_is_due_passes_over_the_rest_and_counts_each(server, alice):
    # S3.6: on Oct 13, of what expired Oct 9 the 480 and 470 puts were out of the money at
    # that day's close of 500 and expire; the AAPL put without a close and the 530 put in the
    # money wait for the user, as does the 460 put expiring that day; the shares and the
    # checking account (not for investing) are passed over, not stopped at, and a deleted
    # account's 480 put is left as it is.
    from moolakata import options
    from moolakata.prices import refresh as pricing
    from moolakata.store.entities.accounts import Account, Instrument, Transaction
    from moolakata.store.entities.prices import Price

    pricing.install()
    new_account(alice, name="Checking")
    gone = new_account(alice, name="Closed", type="brokerage")["id"]
    opt(alice, gone, "sell-to-open", "2026-09-03", "1.00", expiry="2026-10-09", fees="0")
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    add(alice, brk, "-40000.00", "2026-08-03", kind="buy", symbol="MSFT", quantity="100",
        price="400")  # fmt: skip
    option_trade(alice, brk, "2026-09-01", "sell-to-open", "aapl", "put", "200", "2026-10-09",
                 "1", "1.00")  # fmt: skip
    for day, strike, expiry in [
        ("2026-09-02", "530", "2026-10-09"),
        ("2026-09-03", "480", "2026-10-09"),
        ("2026-09-04", "470", "2026-10-09"),
        ("2026-09-05", "460", "2026-10-13"),
    ]:
        opt(alice, brk, "sell-to-open", day, "1.00", strike=strike, expiry=expiry, fees="0")
    with server.db.tx(unscoped="test") as s:
        s.get(Account, gone).mark_deleted(None)
        msft = s.query(Instrument).filter_by(symbol="MSFT").one()
        for day in (dt.date(2026, 10, 9), dt.date(2026, 10, 13)):
            s.add(Price(instrumentId=msft.id, date=day, close=500, source="test",
                        fetchedAt=clock.now(), updatedAt=clock.now()))  # fmt: skip
    with server.db.tx(unscoped="test") as s:
        assert options.expire_due(s, dt.date(2026, 10, 13)) == 2
    with server.db.read(unscoped="test") as s:
        owner = s.get(Account, brk).ownerId
        ended = {(t.accountId, t.payee, t.date, t.createdById) for t in s.query(Transaction)
                 .filter_by(kind="expire", deleted=False)}  # fmt: skip
    assert ended == {
        (brk, f"Expired MSFT 09OCT26 {k} P", dt.date(2026, 10, 9), owner) for k in ("480", "470")
    }


# ---- An option trade as its draft records it (S3.2) ----


def _trade(c, acct, **changed):
    """A sell-to-open of one MSFT 480 put for $6.40 with $0.65 fees, with `changed` in place of
    its fields, as the dialog's draft sends it."""
    fields = {"accountId": acct, "date": "2026-09-02", "kind": "sell-to-open", "symbol": "msft",
              "right": "put", "strike": "480", "expiry": "2026-11-20", "quantity": "1",
              "price": "6.40", "fees": "0.65", "amount": "639.35", **changed}  # fmt: skip
    return create(c, "Txn", **fields)


def _refused(r):
    assert r.status_code == 422, r.text
    return [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


@pytest.mark.parametrize(
    ("changed", "error"),
    [
        ({"right": "Call"}, ("right", "right-invalid", "A call or a put.")),
        ({"right": None}, ("right", "right-invalid", "A call or a put.")),
        ({"symbol": None}, ("symbol", "symbol-invalid", "The underlying's symbol: MSFT.")),
        ({"symbol": "   "}, ("symbol", "symbol-invalid", "The underlying's symbol: MSFT.")),
        ({"symbol": "ABCDEFGHIJKLM"},
         ("symbol", "symbol-invalid", "The underlying's symbol: MSFT.")),
        ({"strike": "0"}, ("strike", "strike-invalid", "More than zero.")),
        ({"strike": None}, ("strike", "strike-invalid", "More than zero.")),
        ({"quantity": "0"}, ("quantity", "contracts-invalid", "A whole number of contracts.")),
        ({"quantity": "-1"}, ("quantity", "contracts-invalid", "A whole number of contracts.")),
        ({"quantity": None}, ("quantity", "contracts-invalid", "A whole number of contracts.")),
        ({"quantity": "1.5"}, ("quantity", "contracts-invalid", "A whole number of contracts.")),
        ({"price": "-0.01"}, ("price", "premium-invalid", "Zero or more, a share.")),
        ({"price": None}, ("price", "premium-invalid", "Zero or more, a share.")),
        ({"fees": "-0.01"}, ("fees", "fees-invalid", "Zero or more.")),
        ({"expiry": None}, ("expiry", "expiry-required", "The day it expires.")),
        ({"expiry": "2026-09-01"}, ("expiry", "expired", "It expired before the trade.")),
        ({"multiplier": 0}, ("multiplier", "multiplier-invalid", "Shares a contract: 100.")),
        ({"multiplier": 10001}, ("multiplier", "multiplier-invalid", "Shares a contract: 100.")),
    ],
)  # fmt: skip
def test_an_option_trade_refused_names_its_field_and_says_why(alice, changed, error):
    """R3.11: a blank, a zero or a value out of range is refused, never read as the default."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    assert _refused(_trade(alice, brk, **changed)) == [error]


def test_an_option_trade_says_each_field_wrong_in_the_forms_order(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    r = _trade(alice, brk, right="x", symbol="", strike="0", quantity="0", price="-1",
               fees="-1", expiry=None, multiplier=0)  # fmt: skip
    assert [e[:2] for e in _refused(r)] == [
        ("right", "right-invalid"), ("symbol", "symbol-invalid"), ("strike", "strike-invalid"),
        ("quantity", "contracts-invalid"), ("price", "premium-invalid"),
        ("fees", "fees-invalid"), ("expiry", "expiry-required"),
        ("multiplier", "multiplier-invalid")]  # fmt: skip


@pytest.mark.parametrize(
    ("changed", "symbol"),
    [
        ({"symbol": " abcdefghijkl "}, "ABCDEFGHIJKL 20NOV26 480 P"),
        ({"strike": "0.5", "amount": "639.35"}, "MSFT 20NOV26 0.5 P"),
        ({"price": "0", "amount": "-0.65"}, "MSFT 20NOV26 480 P"),
        ({"expiry": "2026-09-02"}, "MSFT 02SEP26 480 P"),
        ({"multiplier": 1, "amount": "5.75"}, "MSFT 20NOV26 480 P"),
        ({"multiplier": 10000, "amount": "63999.35"}, "MSFT 20NOV26 480 P"),
    ],
)
def test_an_option_trade_takes_each_field_on_its_bound(alice, changed, symbol):
    """An underlying of 12 letters, a strike above zero, a premium of zero, an expiry the day of
    the opening trade, and a multiplier from 1 to 10,000 are all taken."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    t = saved(_trade(alice, brk, **changed))
    assert (t["symbol"], t["amount"]) == (symbol, changed.get("amount", "639.35"))


def test_options_belong_in_an_investing_account(alice):
    chk = new_account(alice, name="Checking")["id"]
    assert _refused(_trade(alice, chk)) == [
        ("kind", "kind-not-for-account", "Options belong in an investing account.")
    ]


@pytest.mark.parametrize(
    ("opened", "kind", "contracts", "holds"),
    [
        (None, "sell-to-close", "1", "0 long"),
        ("buy-to-open", "sell-to-close", "3", "2 long"),
        ("buy-to-open", "buy-to-close", "1", "2 long"),
        ("sell-to-open", "buy-to-close", "3", "2 short"),
        ("sell-to-open", "sell-to-close", "1", "2 short"),
    ],
)
def test_a_close_is_of_contracts_held_on_its_side(alice, opened, kind, contracts, holds):
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    if opened:
        assert opt(alice, brk, opened, "2026-09-01", "6.40", contracts="2").status_code == 200
    r = opt(alice, brk, kind, "2026-09-02", "1.00", contracts=contracts)
    assert _refused(r) == [
        ("quantity", "nothing-to-close", f"The account holds {holds} contracts of it.")
    ]


@pytest.mark.parametrize(("opened", "kind"), [("buy-to-open", "sell-to-close"),
                                              ("sell-to-open", "buy-to-close")])  # fmt: skip
def test_every_contract_held_closes_even_after_its_expiry(alice, opened, kind):
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    assert opt(alice, brk, opened, "2026-09-01", "6.40", contracts="2").status_code == 200
    t = saved(opt(alice, brk, kind, "2026-11-23", "0.10", contracts="2"))
    assert (t["kind"], t["quantity"]) == (kind, "2.0")
    assert alice.get("/ui/api/positions").json()["open"] == []


def test_an_option_trade_comes_to_its_cash_or_is_refused_saying_what(alice):
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    r = _trade(alice, brk, quantity="20", amount="12799.00")
    assert _refused(r) == [("amount", "amount-mismatch", "The trade comes to 12,799.35.")]


def test_an_option_trade_is_saved_with_its_contract_payee_and_who_made_it(server, alice):
    """Its payee the trade and contract unless typed, its fees none when there are none, the
    trade in the account's activity."""
    from moolakata.store.entities.accounts import Transaction

    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    t = saved(_trade(alice, brk, fees=None, amount="640.00", memo="Wheel"))
    assert (t["payee"], t["memo"], t["fees"], t["quantity"], t["price"]) == (
        "Sell to open MSFT 20NOV26 480 P", "Wheel", None, "1.0", "6.4")  # fmt: skip
    typed = saved(_trade(alice, brk, payee="  Schwab  ", fees="0", amount="640.00"))
    assert (typed["payee"], typed["fees"]) == ("Schwab", None)
    blank = saved(_trade(alice, brk, payee="  ", kind="buy-to-open", amount="-640.65"))
    assert blank["payee"] == "Buy to open MSFT 20NOV26 480 P"
    with server.db.read(unscoped="test") as s:
        made = s.get(Transaction, t["id"])
        assert made.createdById == alice.get("/ui/api/session").json()["user"]["id"]
    texts = [e["text"] for e in alice.get("/ui/api/activity").json()["items"]]
    assert sum("recorded an option trade in Brokerage" in x for x in texts) == 3


# ---- Corporate actions as their dialog's draft records them (S2.4) ----


def _holding(c, symbol="FB", qty="10", account_type="brokerage"):
    """An account holding `qty` shares of `symbol` bought at $100: the account and the
    shares' instrument."""
    a = new_account(c, name="Brokerage", type=account_type)["id"]
    t = add(c, a, f"-{int(qty) * 100}.00", "2025-01-02", kind="buy", symbol=symbol,
            quantity=qty, price="100")  # fmt: skip
    return a, t["instrumentId"]


@pytest.mark.parametrize(
    ("changed", "error"),
    [
        ({"kind": "dividend"},
         ("kind", "kind-invalid", "A split, symbol change, spin-off or merger.")),
        ({"instrumentId": "Instr_01m4tj4gg0f02s596bvjcn26rw"},
         ("instrumentId", "instrument-unknown", "Choose a holding.")),
    ],
)  # fmt: skip
def test_a_corporate_action_refused_names_its_field_and_says_why(alice, changed, error):
    a, fb = _holding(alice)
    fields = {"accountId": a, "instrumentId": fb, "kind": "symbol-change", "date": "2026-06-09",
              "newSymbol": "META", **changed}  # fmt: skip
    assert _refused(create(alice, "CorpA", **fields)) == [error]


def test_a_corporate_action_is_of_shares_in_an_investing_account(alice):
    """An option is adjusted from the OCC's memo, never by a corporate action of its own."""
    brk = new_account(alice, name="Brokerage", type="brokerage")["id"]
    assert opt(alice, brk, "sell-to-open", "2026-09-02", "6.40").status_code == 200
    [put] = alice.get("/ui/api/positions").json()["open"]
    r = create(alice, "CorpA", accountId=brk, instrumentId=put["instrumentId"],
               kind="split", date="2026-10-01", ratio="2")  # fmt: skip
    assert _refused(r) == [("instrumentId", "instrument-unknown", "Choose a holding.")]
    chk = new_account(alice, name="Checking")["id"]
    r = create(alice, "CorpA", accountId=chk, instrumentId=put["instrumentId"],
               kind="split", date="2026-10-01", ratio="2")  # fmt: skip
    assert _refused(r) == [
        ("kind", "kind-not-for-account", "These belong in an investing account.")
    ]


def test_a_corporate_action_is_saved_as_typed_with_the_transactions_made_from_it(alice):
    a, fb = _holding(alice)
    act = saved(create(alice, "CorpA", accountId=a, instrumentId=fb, kind="symbol-change",
                       date="2026-06-09", newSymbol=" meta "))  # fmt: skip
    assert (act["accountId"], act["instrumentId"], act["symbol"], act["kind"], act["date"],
            act["newSymbol"], act["ratio"], act["basisShare"], act["cashPerShare"],
            act["newPrice"]) == (a, fb, "FB", "symbol-change", "2026-06-09", "META", None, None,
                                 None, None)  # fmt: skip
    assert [(t["kind"], t["symbol"], t["quantity"]) for t in act["transactions"]] == [
        ("symbol-change", "FB", "10.0"), ("symbol-change", "META", "10.0")]  # fmt: skip
    split = saved(create(alice, "CorpA", accountId=a, instrumentId=act["transactions"][1][
        "instrumentId"], kind="split", date="2026-07-01", ratio="2", newSymbol="  "))  # fmt: skip
    assert (split["ratio"], split["newSymbol"]) == ("2.0", None)
    assert [t["kind"] for t in split["transactions"]] == ["split"]
    texts = [e["text"] for e in alice.get("/ui/api/activity").json()["items"]]
    assert any("recorded a symbol change in Brokerage" in x for x in texts)
    assert any("recorded a split in Brokerage" in x for x in texts)


def test_a_corporate_action_is_deleted_and_recorded_again_never_changed(alice):
    a, fb = _holding(alice)
    act = saved(create(alice, "CorpA", accountId=a, instrumentId=fb, kind="split",
                       date="2026-06-09", ratio="2"))  # fmt: skip
    r = change(alice, "CorpA", act, accountId=a, instrumentId=fb, kind="split",
               date="2026-06-10", ratio="2")  # fmt: skip
    assert _refused(r) == [
        (None, "action-fixed", "A corporate action is deleted, and recorded again if it differs.")
    ]
    assert remove(alice, "CorpA", {"id": "CorpA_01m4tj4gg0f02s596bvjcn26rw", "version": 1}
                  ).status_code == 404  # fmt: skip


def test_only_who_may_change_the_account_records_or_deletes_its_corporate_actions(server):
    from edits import share
    from test_sharing import setup

    u, c = setup(server)
    a, fb = _holding(c["alice"])
    assert share(c["alice"], "account", a, users={u["bob"].id: "read"}).status_code == 200
    fields = {"accountId": a, "instrumentId": fb, "kind": "split", "date": "2026-06-09",
              "ratio": "2"}  # fmt: skip
    assert create(c["bob"], "CorpA", **fields).status_code == 403
    act = saved(create(c["alice"], "CorpA", **fields))
    assert remove(c["bob"], "CorpA", act).status_code == 403
    assert remove(c["alice"], "CorpA", act).status_code == 200


# ---- An option's end and an adjustment from the memo, through their routes (S3.4, S3.10.2) --


def _put(c, name="Brokerage", mask="4821"):
    """An account with two MSFT 480 puts sold: the account and the put's instrument."""
    a = new_account(c, name=name, type="brokerage", mask=mask)["id"]
    assert opt(c, a, "sell-to-open", "2026-09-02", "6.40", contracts="2").status_code == 200
    [put] = [x for x in c.get("/ui/api/positions").json()["open"] if x["accountId"] == a]
    return a, put["instrumentId"]


def test_an_end_is_expired_assigned_or_exercised_of_an_option_there(alice):
    a, put = _put(alice)
    r = alice.post(f"/ui/api/accounts/{a}/options/{put}/settle",
                   json={"how": "sold", "date": "2026-11-20", "contracts": "1"})  # fmt: skip
    assert _refused(r) == [("how", "how-invalid", "Expired, assigned or exercised.")]
    r = alice.post(f"/ui/api/accounts/{a}/options/Instr_01m4tj4gg0f02s596bvjcn26rw/settle",
                   json={"how": "expired", "date": "2026-11-20", "contracts": "1"})  # fmt: skip
    assert _refused(r) == [("instrumentId", "not-found", "No such option.")]
    r = alice.post(f"/ui/api/accounts/{a}/options/{put}/settle",
                   json={"how": "expired", "date": "2026-11-20", "contracts": "1"})  # fmt: skip
    assert r.status_code == 201, r.text
    assert [(t["kind"], t["quantity"], t["accountId"]) for t in r.json()] == [
        ("expire", "1.0", a)]  # fmt: skip
    texts = [e["text"] for e in alice.get("/ui/api/activity").json()["items"]]
    assert any("recorded an option's expiry, assignment or exercise in Brokerage" in x
               for x in texts)  # fmt: skip


def _adjust(c, *contracts, day="2026-10-05"):
    return c.post("/ui/api/options/adjust", json={"date": day, "contracts": list(contracts)})


def _to(put, root="MSFT1", strike="480", deliverable=({"symbol": "MSFT", "shares": "150"},)):
    return {"instrumentId": put, "root": root, "strike": strike,
            "deliverable": list(deliverable)}  # fmt: skip


def test_an_adjustment_refused_names_its_contracts_field_and_says_why(alice):
    a, put = _put(alice)
    shares = add(alice, a, "-4000.00", "2026-09-01", kind="buy", symbol="MSFT", quantity="10",
                 price="400")["instrumentId"]  # fmt: skip
    assert _refused(_adjust(alice)) == [
        ("contracts", "contracts-missing", "At least one contract.")]  # fmt: skip
    assert _refused(_adjust(alice, _to(put), _to(shares))) == [
        ("contracts.1.instrumentId", "not-an-option", "An open contract.")]  # fmt: skip
    assert _refused(_adjust(alice, _to(put, root="MSFT"))) == [
        ("contracts.0.root", "root-invalid", "The new root, such as XYZ1.")]  # fmt: skip
    assert _refused(_adjust(alice, _to(put, strike="0"))) == [
        ("contracts.0.strike", "strike-invalid", "A strike above 0.")]  # fmt: skip
    assert _refused(_adjust(alice, _to(put, deliverable=()))) == [
        ("contracts.0.deliverable", "deliverable-missing", "What it delivers.")]  # fmt: skip


def test_an_adjustment_moves_each_contract_in_every_account_the_caller_may_change(server):
    """S3.10.2: the same contract held in two accounts moves in both, and is counted once; an
    account shared to read is left as it is; a root typed again in lower case is the root."""
    from edits import share
    from test_sharing import setup

    u, c = setup(server)
    alice, bob = c["alice"], c["bob"]
    a, put = _put(alice)
    b, _ = _put(alice, name="Second", mask="5150")
    theirs, _ = _put(bob, name="Bob's", mask="5151")
    assert share(bob, "account", theirs, users={u["alice"].id: "read"}).status_code == 200
    r = _adjust(alice, _to(put, root=" msft1 "))
    assert r.status_code == 200, r.text
    assert r.json() == {"contracts": 2, "accounts": 2}
    syms = {(x["accountId"], x["symbol"]) for x in alice.get("/ui/api/positions").json()["open"]}
    assert syms == {(a, "MSFT1 20NOV26 480 P"), (b, "MSFT1 20NOV26 480 P"),
                    (theirs, "MSFT 20NOV26 480 P")}  # fmt: skip
    [g] = alice.get("/ui/api/options/adjustable").json()["items"]
    [cn] = g["contracts"]
    assert (cn["root"], cn["held"]) == ("MSFT1", ["Short 2 in Brokerage", "Short 2 in Second"])
    r = _adjust(alice, _to(cn["instrumentId"], root="msft1", strike="490"))
    assert r.status_code == 200, r.text  # the root it has, typed again
    texts = [e["text"] for e in alice.get("/ui/api/activity").json()["items"]]
    assert sum("adjusted options in" in x for x in texts) == 4
    me = _me(alice)
    assert _logged(server, "option.adjusted") in {(me, "account", x, me, "{}") for x in (a, b)}


def _logged(server, kind):
    """The last activity of a kind, as stored: its actor, subject, owner and detail."""
    from sqlalchemy import select

    from moolakata.store.entities.core import Activity

    with server.db.read(unscoped="test") as s:
        rows = s.scalars(select(Activity).where(Activity.kind == kind)).all()
        x = sorted(rows, key=lambda r: r.id)[-1]
        return x.actorId, x.subjectKind, x.subjectId, x.ownerId, x.detail


def _me(c):
    return c.get("/ui/api/session").json()["user"]["id"]


def test_a_corporate_action_and_what_it_made_are_the_callers_and_logged(server, alice):
    """Who recorded an action and its transactions; the account's activity names it; read
    back, the pair's new leg names its other half's account to the caller."""
    from moolakata.store.entities.accounts import CorporateAction, Transaction

    a, fb = _holding(alice)
    act = saved(create(alice, "CorpA", accountId=a, instrumentId=fb, kind="symbol-change",
                       date="2026-06-09", newSymbol="META"))  # fmt: skip
    me = _me(alice)
    with server.db.read(unscoped="test") as s:
        assert s.get(CorporateAction, act["id"]).createdById == me
        assert {s.get(Transaction, t["id"]).createdById for t in act["transactions"]} == {me}
    assert _logged(server, "account.corporate-action") == (
        me, "account", a, me, '{"name": "symbol change"}')  # fmt: skip
    old, new = act["transactions"]
    assert (new["transferId"], new["transferAccountName"]) == (old["id"], "Brokerage")
    t = saved(_trade(alice, a))
    assert _logged(server, "option.traded") == (me, "account", a, me, "{}")
    r = alice.post(f"/ui/api/accounts/{a}/options/{t['instrumentId']}/settle",
                   json={"how": "expired", "date": "2026-11-20", "contracts": "1"})  # fmt: skip
    assert r.status_code == 201, r.text
    assert _logged(server, "option.settled") == (me, "account", a, me, "{}")


def test_a_corporate_action_deleted_is_marked_by_who_deleted_it(server, alice):
    from moolakata.store.entities.accounts import CorporateAction, Transaction

    a, fb = _holding(alice)
    act = saved(create(alice, "CorpA", accountId=a, instrumentId=fb, kind="symbol-change",
                       date="2026-06-09", newSymbol="META"))  # fmt: skip
    assert remove(alice, "CorpA", act).status_code == 200
    with server.db.read(unscoped="test") as s:
        gone = s.get(CorporateAction, act["id"])
        assert (gone.deleted, gone.deletedById) == (True, _me(alice))
        assert all(s.get(Transaction, t["id"]).deleted for t in act["transactions"])
    r = remove(alice, "CorpA", act)
    assert (r.status_code, _refused_as(r)) == (404, [(None, "not-found", "Not found")])


def _refused_as(r):
    return [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


def test_a_corporate_action_is_deleted_only_by_who_may_change_the_account(server):
    from edits import share
    from test_sharing import setup

    u, c = setup(server)
    a, fb = _holding(c["alice"])
    act = saved(create(c["alice"], "CorpA", accountId=a, instrumentId=fb, kind="split",
                       date="2026-06-09", ratio="2"))  # fmt: skip
    assert share(c["alice"], "account", a, users={u["bob"].id: "read"}).status_code == 200
    r = remove(c["bob"], "CorpA", act)
    assert (r.status_code, [e["code"] for e in r.json()["errors"]]) == (403, ["share-read-only"])


def test_an_all_cash_merger_at_a_loss_is_a_wash_sale_with_shares_bought_elsewhere(alice):
    """S3.8: the merger's cash is a sale, at a loss; the same shares bought in the household's
    other account within 30 days replace them, so the loss is disallowed."""
    a, twtr = _holding(alice, symbol="TWTR")
    b = new_account(alice, name="Other", type="brokerage", mask="5150")["id"]
    add(alice, b, "-250.00", "2026-10-01", kind="buy", symbol="TWTR", quantity="5", price="50")
    saved(create(alice, "CorpA", accountId=a, instrumentId=twtr, kind="merger",
                 date="2026-10-12", cashPerShare="54.20"))  # fmt: skip
    [row] = [r for r in alice.get("/ui/api/positions").json()["closed"] if r["accountId"] == a]
    assert (row["how"], row["realized"], row["washDisallowed"]) == ("merger", "-229.00",
                                                                     "229.00")  # fmt: skip
