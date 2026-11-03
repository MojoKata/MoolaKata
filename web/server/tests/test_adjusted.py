"""Adjusted contracts (requirements S3.10): a whole-number split taking open options with it,
an adjustment from the OCC's memo with a new root and deliverable, assignment by deliverable,
and OCC tickers on import. The lot carries over: nothing is sold."""

import datetime as dt
from decimal import Decimal as D

import pytest
from conftest import make_user, sign_in
from edits import make, remove, saved
from test_accounts import new_account
from test_options import opt

from moolakata import clock
from moolakata.options.adjust import parse_occ

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
        return v["shape"], [(x["symbol"], x["quantity"]) for x in v["legs"]], v["capitalAtRiskNow"]

    assert legs() == ("Short put", [("MSFT 20NOV26 480 P", -2)], "94720.00")
    r = make(alice, "Txn", accountId=a, date="2026-10-01", kind="split", symbol="MSFT",
             amount="0", splitRatio="2")  # fmt: skip
    assert r.status_code == 200, r.text
    assert legs() == ("Short put", [("MSFT 20NOV26 240 P", -4)], "94720.00")
    saved(remove(alice, "Txn", r.json()))
    assert legs() == ("Short put", [("MSFT 20NOV26 480 P", -2)], "94720.00")


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
