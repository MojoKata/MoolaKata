"""Adjusted contracts (requirements S3.10): a whole-number split taking open options with it,
an adjustment from the OCC's memo with a new root and deliverable, assignment by deliverable,
and OCC tickers on import. The lot carries over: nothing is sold."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import create, make, option_trade, remove, saved
from sqlalchemy import false, select
from test_accounts import new_account
from test_options import opt

from moolakata import clock, ids
from moolakata.errors import FieldError, Problem
from moolakata.options import adjust, contract_of
from moolakata.options.adjust import parse_occ
from moolakata.store.entities.accounts import (
    Account,
    Instrument,
    OptionContract,
    Transaction,
)
from moolakata.store.entities.users import User

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def alice(server):
    clock.fix(T0)
    make_user(server, "alice")
    yield sign_in(server, "alice")
    clock.fix(None)


def held(c):
    return {
        r["symbol"]: (r["quantity"], r["cost"], r["lots"][0]["acquiredOn"])
        for r in c.get("/ui/api/positions").json()["open"]
    }


def test_a_whole_split_takes_the_open_options_with_it_and_undoes_with_it(alice):
    a = new_account(alice, type="brokerage")["id"]
    assert (
        opt(alice, a, "sell-to-open", "2026-09-01", "6.40", contracts="2", fees="0").status_code
        == 200
    )
    r = make(
        alice,
        "Txn",
        accountId=a,
        date="2026-10-01",
        kind="split",
        symbol="MSFT",
        amount="0",
        splitRatio="2",
    )
    assert r.status_code == 200, r.text
    after = held(alice)
    assert after == {"MSFT 20NOV26 240 P": (-4, -1280, "2026-09-01")}, "basis and days carry"
    gains = alice.get("/ui/api/positions").json()["closed"]
    assert gains == [], "nothing was sold"
    split = r.json()
    saved(remove(alice, "Txn", split))
    assert held(alice) == {"MSFT 20NOV26 480 P": (-2, -1280, "2026-09-01")}


def test_an_adjustment_from_the_memo_changes_root_and_deliverable(alice):
    a = new_account(alice, type="brokerage")["id"]
    opt(alice, a, "sell-to-open", "2026-09-01", "3.00", contracts="2", fees="0")
    [g] = alice.get("/ui/api/options/adjustable").json()["items"]
    [cn] = g["contracts"]
    assert (g["underlying"], cn["held"]) == ("MSFT", ["Short 2 in Checking"])
    r = alice.post(
        "/ui/api/options/adjust",
        json={
            "date": "2026-10-05",
            "contracts": [
                {
                    "instrumentId": cn["instrumentId"],
                    "root": "MSFT1",
                    "strike": "480",
                    "deliverable": [{"symbol": "MSFT", "shares": "150"}],
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"contracts": 1, "accounts": 1}
    pos = held(alice)
    assert pos == {"MSFT1 20NOV26 480 P": (-2, -600, "2026-09-01")}
    # Assigned: it buys its deliverable, 150 shares a contract, at the strike on 100.
    row = next(r for r in alice.get("/ui/api/positions").json()["open"])
    r = alice.post(
        f"/ui/api/accounts/{a}/options/{row['instrumentId']}/settle",
        json={"how": "assign", "date": "2026-11-20", "contracts": "2"},
    )
    assert r.status_code in (200, 201), r.text
    after = held(alice)
    qty, cost, _ = after["MSFT"]
    assert qty == 300 and D(str(cost)) == D("96000") - D("600")


def test_occ_tickers_are_read_with_their_root():
    assert parse_occ("O:XYZ1270115C00060000") == ("XYZ1", dt.date(2027, 1, 15), "call", D("60"))
    assert parse_occ("MSFT  261120P00480000") == ("MSFT", dt.date(2026, 11, 20), "put", D("480"))
    assert parse_occ("Microsoft Corp") is None


def _short_adjusted_call(c, held: str, deliverable: list[dict]):
    from edits import create

    a = new_account(c, type="brokerage")["id"]
    r = create(c, "Txn", accountId=a, date="2026-08-01", kind="buy", symbol="MSFT",
               quantity=held, price="400", amount=f"-{int(held) * 400}.00")  # fmt: skip
    assert r.status_code == 200, r.text
    assert (
        opt(c, a, "sell-to-open", "2026-09-01", "3.00", right="call", fees="0").status_code == 200
    )
    [g] = c.get("/ui/api/options/adjustable").json()["items"]
    [cn] = g["contracts"]
    r = c.post("/ui/api/options/adjust", json={"date": "2026-10-05", "contracts": [
        {"instrumentId": cn["instrumentId"], "root": "MSFT1", "strike": "480",
         "deliverable": deliverable}]})  # fmt: skip
    assert r.status_code == 200, r.text
    acct = c.get(f"/ui/api/accounts/{a}").json()
    risk = None if acct["capitalAtRiskUnlimited"] else acct["capitalAtRisk"]
    proposals = [p["kind"] for p in c.get("/ui/api/positions/strategies").json()["proposals"]]
    return risk, proposals


@pytest.mark.parametrize(
    ("held", "deliverable", "risk", "proposed"),
    [
        # 150 shares a contract (a 3:2 split): 100 held leave 50 uncovered.
        ("100", [{"symbol": "MSFT", "shares": "150"}], None, []),
        # 150 held cover it: the shares' $60,000 less the $300 credit.
        ("150", [{"symbol": "MSFT", "shares": "150"}], "59700.00", ["covered-call"]),
        # Another company's shares in it: no holding of the underlying alone covers it.
        ("150", [{"symbol": "MSFT", "shares": "150"}, {"symbol": "SPUN", "shares": "20"}],
         None, []),
    ],
)  # fmt: skip
def test_an_adjusted_short_call_is_covered_by_what_it_delivers(alice, held, deliverable, risk,
                                                               proposed):  # fmt: skip
    """CR3-400, S3.10.2: the multiplier stays 100, so coverage counts the shares the contract
    delivers, all of them, and only of its underlying."""
    assert _short_adjusted_call(alice, held, deliverable) == (risk, proposed)


def test_a_strategys_leg_follows_its_contract_when_adjusted(alice):
    """CR3-401, S3.10: a whole split adjusts a grouped short put; the strategy holds the new
    contract, its contracts doubled, and deleting the split brings the leg back."""
    from edits import create

    a = new_account(alice, type="brokerage")["id"]
    assert (
        opt(alice, a, "sell-to-open", "2026-09-01", "6.40", contracts="2", fees="0").status_code
        == 200
    )
    [row] = alice.get("/ui/api/positions").json()["open"]
    st = saved(create(alice, "Strat", accountId=a, legs=[{"instrumentId": row["instrumentId"]}]))

    def legs():
        [v] = [x for x in alice.get("/ui/api/positions/strategies").json()["strategies"]
               if x["id"] == st["id"]]  # fmt: skip
        return (v["shape"], [(x["symbol"], x["quantity"]) for x in v["legs"]],
                v["capitalAtRiskNow"], v["capitalAtRiskAtOpen"])  # fmt: skip

    # At open, the leg is the contract it opened as.
    assert legs() == ("Short put", [("MSFT 20NOV26 480 P", -2)], "94720.00", "94720.00")
    r = make(alice, "Txn", accountId=a, date="2026-10-01", kind="split", symbol="MSFT",
             amount="0", splitRatio="2")  # fmt: skip
    assert r.status_code == 200, r.text
    assert legs() == ("Short put", [("MSFT 20NOV26 240 P", -4)], "94720.00", "94720.00")
    saved(remove(alice, "Txn", r.json()))
    assert legs() == ("Short put", [("MSFT 20NOV26 480 P", -2)], "94720.00", "94720.00")


def _adjusted_put(c, contracts="2", deliverable=None, cash="0"):
    a = new_account(c, type="brokerage")["id"]
    assert opt(c, a, "sell-to-open", "2026-09-01", "3.00", contracts=contracts,
               fees="0").status_code == 200  # fmt: skip
    [g] = c.get("/ui/api/options/adjustable").json()["items"]
    [cn] = g["contracts"]
    r = c.post("/ui/api/options/adjust", json={"date": "2026-10-05", "contracts": [
        {"instrumentId": cn["instrumentId"], "root": "MSFT1", "strike": "480", "cash": cash,
         "deliverable": deliverable or [{"symbol": "MSFT", "shares": "100"}]}]})  # fmt: skip
    return a, r


def _settle(c, a, how, contracts=None):
    row = next(
        r for r in c.get("/ui/api/positions").json()["open"] if r["symbol"].startswith("MSFT1")
    )
    body = {"how": how, "date": "2026-11-20"} | ({"contracts": contracts} if contracts else {})
    return c.post(f"/ui/api/accounts/{a}/options/{row['instrumentId']}/settle", json=body)


def test_a_deliverables_cash_comes_with_an_assignment(server, alice):
    """S3.10.4: a short put on 100 shares and $50 a contract, two contracts assigned: the
    strike is paid for the shares, the $100 comes in as its own deposit, and comes off the
    shares' basis with the credit."""
    from moolakata.store.entities.accounts import Transaction

    a, r = _adjusted_put(alice, cash="50")
    assert r.status_code == 200, r.text
    r = _settle(alice, a, "assign", "2")
    assert r.status_code in (200, 201), r.text
    with server.db.read(unscoped="test") as s:
        cash = [(t.kind, t.amount, t.payee) for t in s.query(Transaction).filter_by(
            accountId=a, kind="deposit", deleted=False)]  # fmt: skip
    assert cash == [("deposit", D("100.00"), "Deliverable cash (assigned MSFT1 20NOV26 480 P)")]
    assert held(alice) == {"MSFT": (200, 95300, "2026-11-20")}


@pytest.mark.parametrize(
    ("side", "how", "contracts", "code"),
    [
        ("sell-to-open", "exercise", "2", "short-exercise"),
        ("buy-to-open", "assign", "2", "long-assign"),
        # From 1 to those held, whole: nothing else means all (CR3-403).
        ("sell-to-open", "assign", "3", "contracts-invalid"),
        ("sell-to-open", "assign", "0", "contracts-invalid"),
        ("sell-to-open", "assign", "-1", "contracts-invalid"),
        ("sell-to-open", "assign", "1.5", "contracts-invalid"),
        ("sell-to-open", "assign", None, "invalid-missing"),
    ],
)
def test_a_settlement_that_cant_be_is_refused(alice, side, how, contracts, code):
    a = new_account(alice, type="brokerage")["id"]
    assert opt(alice, a, side, "2026-09-01", "3.00", contracts="2", fees="0").status_code == 200
    row = next(r for r in alice.get("/ui/api/positions").json()["open"])
    body = {"how": how, "date": "2026-11-20"} | ({"contracts": contracts} if contracts else {})
    r = alice.post(f"/ui/api/accounts/{a}/options/{row['instrumentId']}/settle", json=body)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == code, r.text


def test_shares_are_not_an_option_to_settle(alice):
    from edits import create

    a = new_account(alice, type="brokerage")["id"]
    create(alice, "Txn", accountId=a, date="2026-08-01", kind="buy", symbol="MSFT",
           quantity="100", price="400", amount="-40000.00")  # fmt: skip
    [row] = alice.get("/ui/api/positions").json()["open"]
    r = alice.post(f"/ui/api/accounts/{a}/options/{row['instrumentId']}/settle",
                   json={"how": "assign", "date": "2026-11-20", "contracts": "1"})  # fmt: skip
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not-an-option", r.text


def test_deleting_either_half_of_an_adjustment_undoes_it(server, alice):
    """S3.10: the pair goes together, whichever half is deleted, and the lot is back on the
    contract it was."""
    from edits import drop

    from moolakata.store.entities.accounts import Transaction

    for half in ("out", "into"):
        a, r = _adjusted_put(alice)
        assert r.status_code == 200, r.text
        with server.db.read(unscoped="test") as s:
            rows = {("into" if t.splitRatio else "out"): t.id for t in s.query(Transaction)
                    .filter_by(accountId=a, kind="option-adjust", deleted=False)}  # fmt: skip
        saved(drop(alice, "Txn", f"/ui/api/transactions/{rows[half]}"))
        with server.db.read(unscoped="test") as s:
            left = s.query(Transaction).filter_by(accountId=a, kind="option-adjust",
                                                  deleted=False).count()  # fmt: skip
        assert left == 0, half
        mine = [r for r in alice.get("/ui/api/positions").json()["open"]
                if r["accountId"] == a]  # fmt: skip
        assert [(r["symbol"], r["quantity"]) for r in mine] == [("MSFT 20NOV26 480 P", -2)]


def test_a_split_not_a_whole_number_waits_for_the_memo(alice):
    """S3.10.1: a 3:2 split adjusts no option itself; the contract waits for its memo."""
    a = new_account(alice, type="brokerage")["id"]
    assert (
        opt(alice, a, "sell-to-open", "2026-09-01", "6.40", contracts="2", fees="0").status_code
        == 200
    )
    r = make(alice, "Txn", accountId=a, date="2026-10-01", kind="split", symbol="MSFT",
             amount="0", splitRatio="1.5")  # fmt: skip
    assert r.status_code == 200, r.text
    assert held(alice) == {"MSFT 20NOV26 480 P": (-2, -1280, "2026-09-01")}


def test_an_adjustment_needs_a_deliverable_and_a_date_that_reads():
    assert parse_occ("XYZ1  271315C00060000") is None  # no 13th month
    assert parse_occ("XYZ1  270115C00060000") == ("XYZ1", dt.date(2027, 1, 15), "call",
                                                  D("60"))  # fmt: skip


def test_a_deliverable_of_no_shares_is_refused(alice):
    _, r = _adjusted_put(alice, deliverable=[{"symbol": "MSFT", "shares": "0"}])
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["code"] == "deliverable-invalid"


def test_a_splits_strike_rounds_half_up_to_the_thousandth():
    """S3.10.1: as the OCC prints it, a half thousandth goes up, not to the even digit."""
    assert adjust.adjusted_strike(D("4.125"), D("2")) == D("2.063")
    assert adjust.adjusted_strike(D("480"), D("3")) == D("160")


def _uid(server, name="alice"):
    with server.db.read(unscoped="test") as s:
        return s.scalars(select(User.id).where(User.username == name)).one()


def _split(s, a, uid, ratio, day=dt.date(2026, 10, 16)):
    """A split of MSFT recorded in the account, its options not yet adjusted."""
    msft = s.scalars(
        select(Instrument).where(Instrument.symbol == "MSFT", Instrument.deleted == false())
    ).one()
    t = Transaction(id=ids.new_id("Txn"), accountId=a, date=day, kind="split", amount=D(0),
                    instrumentId=msft.id, splitRatio=ratio, createdById=uid)  # fmt: skip
    s.add(t)
    s.flush()
    return t


def _pairs(s, a):
    """Each adjustment's pair in the account: (out, into)."""
    rows = s.scalars(
        select(Transaction).where(Transaction.accountId == a, Transaction.kind == "option-adjust")
    ).all()
    return [(t, s.get(Transaction, t.transferId)) for t in rows if t.splitRatio is None]


def _book(c):
    """100 MSFT shares; on MSFT a short put of two contracts, a long mini call (10 shares a
    contract), a short put expiring on the split's day and one expired before it; an AAPL put."""
    a = new_account(c, type="brokerage")["id"]
    saved(create(c, "Txn", accountId=a, date="2026-08-01", kind="buy", symbol="MSFT",
                 quantity="100", price="400", amount="-40000.00"))  # fmt: skip
    saved(opt(c, a, "sell-to-open", "2026-09-01", "6.40", contracts="2", fees="0"))
    saved(opt(c, a, "buy-to-open", "2026-09-01", "2.00", right="call", strike="450", fees="0",
              multiplier="10"))  # fmt: skip
    saved(opt(c, a, "sell-to-open", "2026-09-01", "1.00", strike="500", expiry="2026-10-16",
              fees="0"))  # fmt: skip
    saved(opt(c, a, "sell-to-open", "2026-09-01", "1.00", strike="300", expiry="2026-10-09",
              fees="0"))  # fmt: skip
    saved(option_trade(c, a, "2026-09-01", "sell-to-open", "aapl", "put", "200", "2026-11-20",
                       "1", "1.00"))  # fmt: skip
    return a


def test_a_whole_split_adjusts_each_contract_on_the_stock_open_on_its_day(server, alice):
    """S3.10.1: each MSFT contract open on the split's day, the one expiring that day too, is
    carried to its contract at half the strike, its right, root, deliverable and multiplier as
    they were: a pair of rows by the one who recorded the split, naming it, moving no cash.
    The shares, the AAPL put and the contract expired before stay."""
    a = _book(alice)
    uid = _uid(server)
    with server.db.tx(unscoped="test") as s:
        split = _split(s, a, uid, D("2"))
        assert adjust.with_split(s, uid, s.get(Account, a), split) == 3
        name = {}
        moved = set()
        for out, into in _pairs(s, a):
            for t in (out, into):
                assert (t.amount, t.createdById, t.optionTransactionId) == (0, uid, split.id)
            assert into.transferId == out.id
            old, new = (s.get(Instrument, t.instrumentId).symbol for t in (out, into))
            name[new] = into.instrumentId
            moved.add((old, out.quantity, out.payee, new, into.quantity, into.splitRatio,
                       into.payee))  # fmt: skip
        cs = {n: contract_of(s, i) for n, i in name.items()}
        terms = {
            n: (c.right, c.strike, c.expiry, c.multiplier, c.root, c.deliverable)
            for n, c in cs.items()
        }
        s.rollback()
    assert moved == {
        ("MSFT 20NOV26 480 P", 2, "Adjusted: MSFT 20NOV26 480 P became MSFT 20NOV26 240 P",
         "MSFT 20NOV26 240 P", 4, 2, "Adjusted from MSFT 20NOV26 480 P"),
        ("MSFT 20NOV26 450 C", 1, "Adjusted: MSFT 20NOV26 450 C became MSFT 20NOV26 225 C",
         "MSFT 20NOV26 225 C", 2, 2, "Adjusted from MSFT 20NOV26 450 C"),
        ("MSFT 16OCT26 500 P", 1, "Adjusted: MSFT 16OCT26 500 P became MSFT 16OCT26 250 P",
         "MSFT 16OCT26 250 P", 2, 2, "Adjusted from MSFT 16OCT26 500 P"),
    }  # fmt: skip
    nov, oct16 = dt.date(2026, 11, 20), dt.date(2026, 10, 16)
    assert terms == {
        "MSFT 20NOV26 240 P": ("put", 240, nov, 100, None, None),
        "MSFT 20NOV26 225 C": ("call", 225, nov, 10, None, None),
        "MSFT 16OCT26 250 P": ("put", 250, oct16, 100, None, None),
    }


@pytest.mark.parametrize("ratio", [None, D("1"), D("1.5"), D("2.5"), D("0.5")])
def test_a_split_below_two_or_not_whole_adjusts_no_option(server, alice, ratio):
    """S3.10.1: only a whole split of 2 or more adjusts by itself; any other waits for the
    OCC's memo."""
    a = new_account(alice, type="brokerage")["id"]
    saved(opt(alice, a, "sell-to-open", "2026-09-01", "6.40", contracts="2", fees="0"))
    uid = _uid(server)
    with server.db.tx(unscoped="test") as s:
        split = _split(s, a, uid, ratio)
        assert adjust.with_split(s, uid, s.get(Account, a), split) == 0
        assert _pairs(s, a) == []
        s.rollback()


@pytest.mark.parametrize(
    ("deliverable", "cash", "after"),
    [
        # Only MSFT shares, which split too: twice the contracts, each delivering the same.
        ([{"symbol": "MSFT", "shares": "150"}], "0", ("MSFT1 20NOV26 240 P", -4)),
        # Another company's shares, or cash, don't split: twice the contracts would deliver
        # twice as many of them, so the contract waits for the OCC's memo.
        ([{"symbol": "MSFT", "shares": "100"}, {"symbol": "SPUN", "shares": "20"}], "0",
         ("MSFT1 20NOV26 480 P", -2)),
        ([{"symbol": "MSFT", "shares": "100"}], "50", ("MSFT1 20NOV26 480 P", -2)),
    ],
)  # fmt: skip
def test_a_whole_split_adjusts_an_adjusted_contract_only_when_it_delivers_just_the_stock(
    server, alice, deliverable, cash, after
):
    """S3.10.1: a 2:1 split of MSFT with a contract adjusted from the memo before it, and a
    plain put opened after, which the split adjusts whatever the other does. The adjusted
    contract keeps its new root and deliverable through the split."""
    a, r = _adjusted_put(alice, deliverable=deliverable, cash=cash)
    assert r.status_code == 200, r.text
    saved(opt(alice, a, "sell-to-open", "2026-10-06", "1.00", strike="500", fees="0"))
    r = make(alice, "Txn", accountId=a, date="2026-10-07", kind="split", symbol="MSFT",
             amount="0", splitRatio="2")  # fmt: skip
    assert r.status_code == 200, r.text
    sym = after[0]
    assert held(alice) == {
        sym: (after[1], -600, "2026-09-01"),
        "MSFT 20NOV26 250 P": (-2, -100, "2026-10-06"),
    }
    with server.db.read(unscoped="test") as s:
        terms = {
            i.symbol: (c.root, c.deliverable)
            for i, c in s.execute(
                select(Instrument, OptionContract).join(
                    OptionContract, OptionContract.instrumentId == Instrument.id
                )
            )
        }
    assert terms[sym] == terms["MSFT1 20NOV26 480 P"]
    assert terms[sym][0] == "MSFT1"


def test_a_deliverables_refusal_names_its_contract_and_its_part(alice):
    """R3.7: a part refused in the second contract's deliverable is shown at that part."""
    a = new_account(alice, type="brokerage")["id"]
    for strike in ("480", "500"):
        saved(opt(alice, a, "sell-to-open", "2026-09-01", "3.00", strike=strike, fees="0"))
    [g] = alice.get("/ui/api/options/adjustable").json()["items"]
    good = [{"symbol": "MSFT", "shares": "100"}]
    bad = [{"symbol": "MSFT", "shares": "100"}, {"symbol": "MSFT", "shares": "0"}]
    contracts = [
        {"instrumentId": cn["instrumentId"], "root": "MSFT1", "strike": str(cn["strike"]),
         "deliverable": d} for cn, d in zip(g["contracts"], (good, bad), strict=True)
    ]  # fmt: skip
    r = alice.post("/ui/api/options/adjust", json={"date": "2026-10-05", "contracts": contracts})
    assert r.status_code == 422, r.text
    errors = [(e["field"], e["code"]) for e in r.json()["errors"]]
    assert errors == [("contracts.1.deliverable.1", "deliverable-invalid")]


@pytest.mark.parametrize(
    "part",
    [
        {"shares": "5"},
        {"symbol": "  ", "shares": "5"},
        {"symbol": "MSFT"},
        {"symbol": "MSFT", "shares": "0"},
        {"symbol": "MSFT", "shares": "-1"},
    ],
)
def test_a_deliverable_part_needs_a_symbol_and_shares_above_zero(server, part):
    with server.db.tx(unscoped="test") as s, pytest.raises(Problem) as e:
        adjust.check_deliverable(s, [{"symbol": "MSFT", "shares": "100"}, part], "c.0.deliverable")
    assert e.value.errors == [
        FieldError("c.0.deliverable.1", "deliverable-invalid", "A symbol and its shares.")
    ]


def test_a_deliverable_part_of_any_shares_above_zero_is_kept_under_its_symbol(server):
    with server.db.tx(unscoped="test") as s:
        parts = adjust.check_deliverable(
            s, [{"symbol": " msft ", "shares": "1"}, {"symbol": "SPUN", "shares": D("0.5")}], "d"
        )
        named = [(s.get(Instrument, i).symbol, q) for i, q in parts]
        s.rollback()
    assert named == [("MSFT", D("1")), ("SPUN", D("0.5"))]


T1 = dt.datetime(2026, 10, 1, 9, tzinfo=dt.UTC)


def test_deleting_a_split_undoes_only_the_adjustments_it_made(server, alice):
    """S3.10: its pairs are deleted by whoever deleted it. A pair from the memo, a half
    deleted before (it keeps its time), and a row of another kind that names the split stay
    as they were."""
    a, r = _adjusted_put(alice, deliverable=[{"symbol": "MSFT", "shares": "150"}])
    assert r.status_code == 200, r.text
    saved(opt(alice, a, "sell-to-open", "2026-09-01", "1.00", strike="500", fees="0"))
    uid = _uid(server)
    with server.db.tx(unscoped="test") as s:
        [memo] = _pairs(s, a)
        split = _split(s, a, uid, D("2"))
        assert adjust.with_split(s, uid, s.get(Account, a), split) == 2
        mine = [p for p in _pairs(s, a) if p != memo]
        before = mine[0][1]
        before.mark_deleted(uid, T1)
        other = Transaction(id=ids.new_id("Txn"), accountId=a, date=split.date, kind="deposit",
                            amount=D(1), optionTransactionId=split.id)  # fmt: skip
        s.add(other)
        s.flush()
        adjust.undo(s, uid, split)
        undone = {(t.deletedAt, t.deletedById) for p in mine for t in p if t is not before}
        kept = (before.deletedAt, other.deletedAt, [t.deletedAt for t in memo])
        s.rollback()
    assert undone == {(T0, uid)}
    assert kept == (T1, None, [None, None])


def test_deleting_one_half_of_a_pair_deletes_the_other_once(server, alice):
    """S3.10: the other half, deleted already, keeps its time; a transfer's halves, which
    aren't an adjustment, are left to the transfer."""
    a, r = _adjusted_put(alice)
    assert r.status_code == 200, r.text
    uid = _uid(server)
    with server.db.tx(unscoped="test") as s:
        [(out, into)] = _pairs(s, a)
        into.mark_deleted(uid, T1)
        adjust.undo(s, uid, out)
        sent = Transaction(id=ids.new_id("Txn"), accountId=a, date=T0.date(), kind="withdrawal",
                           amount=D(-5))  # fmt: skip
        s.add(sent)
        s.flush()
        came = Transaction(id=ids.new_id("Txn"), accountId=a, date=T0.date(), kind="deposit",
                           amount=D(5), transferId=sent.id)  # fmt: skip
        s.add(came)
        s.flush()
        sent.transferId = came.id
        adjust.undo(s, uid, sent)
        kept = (into.deletedAt, came.deletedAt)
        s.rollback()
    assert kept == (T1, None)


def _split_msft(c, a, day="2026-10-01"):
    r = make(c, "Txn", accountId=a, date=day, kind="split", symbol="MSFT", amount="0",
             splitRatio="2")  # fmt: skip
    assert r.status_code == 200, r.text


def test_an_option_trade_runs_through_its_contracts_adjustment(alice):
    """S3.9.1, S3.10.4, CR3-438: an adjustment sells nothing, so the trade goes on under the
    adjusted contract with its opening day and premium, its contracts times the ratio, noting
    the change; a short one requires the larger of its capital before and after."""
    a = new_account(alice, type="brokerage")["id"]
    saved(opt(alice, a, "buy-to-open", "2026-09-01", "3.00", right="call", fees="0"))
    saved(opt(alice, a, "sell-to-open", "2026-09-01", "6.40", contracts="2", fees="0"))
    _split_msft(alice, a)
    saved(opt(alice, a, "sell-to-close", "2026-10-10", "2.00", contracts="2", right="call",
              strike="240", fees="0"))  # fmt: skip
    saved(opt(alice, a, "buy-to-close", "2026-10-12", "1.00", contracts="4", strike="240",
              fees="0"))  # fmt: skip
    rows = alice.get("/ui/api/positions/option-trades").json()["items"]
    keys = ("symbol", "side", "contracts", "opened", "closed", "how", "premiumIn", "premiumOut",
            "pl", "capitalRequired", "adjustedFrom", "adjustedOn")  # fmt: skip
    assert [tuple(r[k] for k in keys) for r in rows] == [
        ("MSFT 20NOV26 240 P", "short", "4.0", "2026-09-01", "2026-10-12", "bought back",
         "1280.00", "400.00", "880.00", "96000.00", "MSFT 20NOV26 480 P", "2026-10-01"),
        ("MSFT 20NOV26 240 C", "long", "2.0", "2026-09-01", "2026-10-10", "sold", "400.00",
         "300.00", "100.00", "300.00", "MSFT 20NOV26 480 C", "2026-10-01"),
    ]  # fmt: skip


def test_an_option_trade_open_through_its_adjustment_is_worth_its_adjusted_contract(alice):
    a = new_account(alice, type="brokerage")["id"]
    saved(opt(alice, a, "buy-to-open", "2026-09-01", "3.00", right="call", fees="0"))
    _split_msft(alice, a)
    (row,) = alice.get("/ui/api/positions/option-trades").json()["items"]
    assert (row["symbol"], row["contracts"], row["closed"], row["premiumOut"]) == (
        "MSFT 20NOV26 240 C", "2.0", None, "300.00")  # fmt: skip
    assert (row["adjustedFrom"], row["adjustedOn"]) == ("MSFT 20NOV26 480 C", "2026-10-01")
