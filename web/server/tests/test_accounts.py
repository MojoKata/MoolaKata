from decimal import Decimal
from pathlib import Path

import pytest
from conftest import make_user, sign_in
from edits import asked, change, create, edit, make, new_id, reconcile, remove, saved

from moolakata.dev.waits import eventually

FIX = Path(__file__).parent / "fixtures"


def new_account(c, **kw):
    body = {
        "name": "Checking",
        "type": "checking",
        "institution": "First Example Bank",
        "mask": "4821",
        **kw,
    }
    r = make(c, "Acct", **body)
    assert r.status_code == 200, r.text
    return r.json()


def add(c, account_id, amount, day="2026-09-01", **kw):
    r = make(c, "Txn", **{"accountId": account_id, "date": day, "amount": amount, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def wait_job(c, job):
    # A statement starts its reader's process first: allow it time on a slow host.
    seen = []

    def finished() -> bool:
        seen.append(c.get(f"/ui/api/jobs/{job['id']}").json())
        return seen[-1]["state"] in ("done", "failed")

    eventually(finished, timeout=60, what=f"job {job['id']} finished")
    return seen[-1]


def upload(c, account_id, name, data):
    r = c.post(f"/ui/api/accounts/{account_id}/imports", files={"file": (name, data)})
    assert r.status_code == 202, r.text
    assert r.headers["location"] == f"/ui/api/jobs/{r.json()['id']}"
    return wait_job(c, r.json())


# ---------- accounts ----------


def test_accounts_are_checked_and_their_owners_own(server):
    make_user(server, "jane")
    make_user(server, "john")
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    r = make(jane, "Acct", name="", type="yacht", mask="12", openingBalance="10.00")
    fields = {e["field"] for e in r.json()["errors"]}
    assert fields == {"name", "type", "mask", "openingDate"}
    a = new_account(jane, openingBalance="1000.00", openingDate="2026-08-31")
    assert a["group"] == "banking" and a["access"]["mine"] and a["balance"] == "1000.00"
    assert a["reconcilable"] and not a["investing"]
    assert john.get(f"/ui/api/accounts/{a['id']}").status_code == 404
    assert john.get("/ui/api/accounts").json()["items"] == []
    assert saved(change(jane, "Acct", a, name="Joint checking"))["name"] == "Joint checking"
    r = change(jane, "Acct", a, name="Stale")
    assert r.status_code == 412
    v = r.json()["current"][0]["version"]
    assert remove(jane, "Acct", {"id": a["id"], "version": v}).status_code == 200
    assert jane.get("/ui/api/accounts").json()["items"] == []


# ---------- transactions ----------


@pytest.mark.parametrize(
    ("least", "most", "got", "refused"),
    [
        ("", "", ["-7.00", "-3.00", "50.00"], None),  # blank: any
        ("0", "", ["-7.00", "-3.00", "50.00"], None),
        ("3", "", ["-7.00", "-3.00", "50.00"], None),  # a size, whichever way the money went
        ("3.01", "7", ["-7.00"], None),
        ("", "7", ["-7.00", "-3.00"], None),
        ("7", "7", ["-7.00"], None),  # At most equal to At least
        ("8", "7", None, ("max", "range-invalid", "Below At least.")),  # At most under At least
        ("-1", "", None, ("min", "amount-invalid", "Zero or more.")),
        ("", "-1", None, ("max", "amount-invalid", "Zero or more.")),
        ("NaN", "", None, ("min", "amount-invalid", "Enter an amount such as 25.00.")),
        ("", "Infinity", None, ("max", "amount-invalid", "Enter an amount such as 25.00.")),
        ("abc", "", None, ("min", "amount-invalid", "Enter an amount such as 25.00.")),
    ],
)
def test_a_filters_amount_bounds_are_sizes_any_while_blank(server, least, most, got, refused):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, openingBalance="0.00", openingDate="2026-08-31")
    for amount, kind in (("-3.00", None), ("-7.00", None), ("50.00", "deposit")):
        add(c, a["id"], amount, "2026-09-01", **({"kind": kind} if kind else {}))
    r = c.get("/ui/api/transactions", params={"min": least, "max": most})
    if refused:
        assert r.status_code == 400, r.text
        assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [refused]
        return
    assert r.status_code == 200, r.text
    assert sorted(t["amount"] for t in r.json()["items"]) == got


def test_transactions_filter_page_and_balance(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, openingBalance="100.00", openingDate="2026-08-31")
    for i in range(1, 8):
        add(c, a["id"], f"-{i}.00", f"2026-09-0{i}", payee=f"Shop {i}")
    add(c, a["id"], "50.00", "2026-09-08", payee="Refund", kind="deposit")
    page = c.get("/ui/api/transactions", params={"limit": 3}).json()
    assert [t["payee"] for t in page["items"]] == ["Refund", "Shop 7", "Shop 6"]
    assert (page["total"], page["offset"], page["limit"]) == (8, 0, 3)
    nxt = c.get("/ui/api/transactions", params={"limit": 3, "offset": 3}).json()
    assert [t["payee"] for t in nxt["items"]] == ["Shop 5", "Shop 4", "Shop 3"]
    r = c.get("/ui/api/transactions", params={"min": "3", "max": "5"}).json()
    assert sorted(t["amount"] for t in r["items"]) == ["-5.00", "-4.00", "-3.00"]
    r = c.get("/ui/api/transactions", params={"payee": "refund"}).json()
    assert len(r["items"]) == 1
    r = c.get("/ui/api/transactions", params={"from": "2026-09-07", "sort": "amount"}).json()
    assert [t["amount"] for t in r["items"]] == ["-7.00", "50.00"]
    assert c.get(f"/ui/api/accounts/{a['id']}").json()["balance"] == "122.00"
    # Money is an exact JSON number (S13.8.2): 12.5 is read as written, not through a float, and
    # more than two places is refused.
    r = make(c, "Txn", accountId=a["id"], date="2026-09-01", amount=Decimal("12.5"))
    assert r.status_code == 200 and r.json()["amount"] == "12.50"
    r = make(c, "Txn", accountId=a["id"], date="2026-09-01", amount=Decimal("12.505"))
    assert r.status_code == 422


def test_splits_tags_and_bulk_categorise(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c)
    cats = {x["path"]: x["id"] for x in c.get("/ui/api/categories").json()["items"]}
    groceries, dining = cats["Food › Groceries"], cats["Food › Dining out"]
    r = make(
        c,
        "Txn",
        accountId=a["id"],
        date="2026-09-02",
        amount="-100.00",
        payee="Costco",
        splits=[
            {"categoryId": groceries, "amount": "-70.00"},
            {"categoryId": dining, "amount": "-20.00"},
        ],
    )
    assert r.json()["errors"][0]["code"] == "splits-unbalanced"
    t = add(
        c,
        a["id"],
        "-100.00",
        payee="Costco",
        tags=["Holiday", "costco"],
        splits=[
            {"categoryId": groceries, "amount": "-70.00"},
            {"categoryId": dining, "amount": "-30.00"},
        ],
    )
    assert len(t["splits"]) == 2 and t["tags"] == ["costco", "holiday"]
    u1 = add(c, a["id"], "-5.00", payee="A")
    u2 = add(c, a["id"], "-6.00", payee="B")
    uncategorised = c.get("/ui/api/transactions", params={"category": "none"}).json()["items"]
    assert {x["id"] for x in uncategorised} == {u1["id"], u2["id"]}
    r = c.post(
        "/ui/api/transactions/categorise",
        json={"ids": [u1["id"], u2["id"]], "categoryId": groceries},
    )
    assert r.json()["changed"] == 2
    r = c.get("/ui/api/transactions", params={"category": groceries}).json()["items"]
    assert len(r) == 3  # two direct, one through a split
    # Already so: none changed. Over 1,000 at once, or a category not known: refused.
    again = {"ids": [u1["id"]], "categoryId": groceries}
    assert c.post("/ui/api/transactions/categorise", json=again).json()["changed"] == 0
    many = {"ids": [new_id("Txn") for _ in range(1001)], "categoryId": groceries}
    r = c.post("/ui/api/transactions/categorise", json=many)
    assert (r.status_code, r.json()["code"]) == (422, "too-many")
    r = c.post("/ui/api/transactions/categorise", json={**again, "categoryId": new_id("Cat")})
    assert (r.status_code, r.json()["code"]) == (422, "category-unknown")
    assert (
        c.get("/ui/api/transactions", params={"tag": "holiday"}).json()["items"][0]["id"] == t["id"]
    )


def test_transfers_are_matched_and_can_be_undone(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    checking = new_account(c)
    card = new_account(c, name="Visa", type="credit-card", mask="1111")
    out = add(c, checking["id"], "-500.00", "2026-09-15", payee="Card payment")
    paid = add(c, card["id"], "500.00", "2026-09-16", payee="Payment thank you", kind="deposit")
    assert paid["transferId"] == out["id"] and paid["transferAccountName"] == "Checking"
    path = f"/ui/api/transactions/{paid['id']}"
    assert saved(edit(c, "Txn", path, transferWithId=None))["transferId"] is None
    assert c.get(f"/ui/api/transactions/{out['id']}").json()["transferId"] is None
    # Matched by hand: the same amount the other way, in another account.
    other = add(c, checking["id"], "-499.00", "2026-09-15", payee="Not it")
    r = edit(c, "Txn", path, transferWithId=other["id"])
    assert r.json()["errors"][0]["code"] == "amount-mismatch"
    assert saved(edit(c, "Txn", path, transferWithId=out["id"]))["transferId"] == out["id"]
    assert c.get(f"/ui/api/transactions/{out['id']}").json()["transferId"] == paid["id"]


def test_idempotency_key_returns_the_first_answer(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c)
    fields = {"accountId": a["id"], "date": "2026-09-01", "amount": "-1.00"}
    ops = [{"op": "create", "entity": "Txn", "id": new_id("Txn"), "fields": fields}]
    r1 = c.post("/ui/api/save", json={"ops": ops}, headers={"Idempotency-Key": "k1"})
    r2 = c.post("/ui/api/save", json={"ops": ops}, headers={"Idempotency-Key": "k1"})
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    assert len(c.get("/ui/api/transactions").json()["items"]) == 1


@pytest.mark.parametrize("kind", ["buy", "sell", "reinvest", "transfer-in", "transfer-out",
                                  "reward"])  # fmt: skip
def test_a_trades_fees_are_typed_a_blank_or_less_than_none_refused(server, kind):
    """R3.11: a trade's fees are zero or more, typed; a blank is refused, never read as
    none, made or changed. Money that isn't a trade has no fees to type."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")["id"]
    add(c, a, "1000.00", "2025-01-02", kind="deposit")
    add(c, a, "-100.00", "2025-01-03", kind="buy", symbol="VTI", quantity="2", price="50")
    trade = {"accountId": a, "date": "2025-01-05", "kind": kind, "symbol": "VTI",
             "quantity": "1", "price": "50",
             "amount": "50.00" if kind in ("sell", "transfer-out") else "-50.00"}  # fmt: skip
    if kind == "transfer-in":
        trade["amount"] = "0.00"
    refusal = [("fees", "fees-invalid", "Zero or more.")]
    for fees in (None, "-0.01"):
        r = create(c, "Txn", **trade, fees=fees)
        assert r.status_code == 422, r.text
        assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == refusal
    t = saved(create(c, "Txn", **trade, fees="0"))
    assert t["fees"] == "0.00"
    r = change(c, "Txn", t, fees=None)
    assert [(e["field"], e["code"]) for e in r.json()["errors"]] == [("fees", "fees-invalid")]


def test_trades_make_lots_holdings_and_gains(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage", lotMethod="fifo")
    add(c, a["id"], "10000.00", "2025-01-02", kind="deposit")
    add(c, a["id"], "-1000.00", "2025-01-05", kind="buy", symbol="VTI", quantity="10", price="100")
    add(c, a["id"], "-3000.00", "2025-03-05", kind="buy", symbol="VTI", quantity="10", price="300")
    r = make(c, "Txn", accountId=a["id"], date="2025-04-01", amount="-1.00", kind="buy")
    assert r.json()["errors"][0]["code"] == "trade-incomplete"
    add(c, a["id"], "2500.00", "2026-02-01", kind="sell", symbol="VTI", quantity="10", price="250")
    h = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()
    vti = h["holdings"][0]
    assert vti["symbol"] == "VTI" and vti["quantity"] == "10.0" and vti["costBasis"] == "3000.00"
    assert vti["priceSource"] == "trade" and vti["value"] == "2500.00"
    assert h["cash"] == "8500.00" and h["total"] == "11000.00"
    checking = new_account(c, name="Bank", mask="2222")
    r = make(
        c,
        "Txn",
        accountId=checking["id"],
        date="2026-02-01",
        amount="-1.00",
        kind="buy",
        symbol="VTI",
        quantity="1",
    )
    assert r.json()["errors"][0]["code"] == "kind-not-for-account"


def test_reconciled_periods_ask_before_an_edit(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, openingBalance="0.00", openingDate="2026-08-31")
    t = add(c, a["id"], "-40.00", "2026-09-02")
    t2 = add(c, a["id"], "100.00", "2026-09-03", kind="deposit")
    for x in (t, t2):
        saved(change(c, "Txn", x, cleared=True))
    rec = reconcile(c, a["id"], "2026-09-30", "70.00")
    assert rec["difference"] == "10.00"
    r = change(c, "Recon", rec, finished=True)
    assert r.json()["errors"][0]["code"] == "not-balanced"
    # Its balance corrected, the period balances, and is reconciled in the same save.
    r = change(c, "Recon", rec, statementBalance="60.00", finished=True)
    assert saved(r)["finishedAt"]
    assert remove(c, "Recon", saved(r)).json()["errors"][0]["code"] == "reconciled"
    current = c.get("/ui/api/transactions").json()["items"]
    t = next(x for x in current if x["id"] == t["id"])
    assert t["reconciled"]
    assert asked(change(c, "Txn", t, memo="x")) == ["reconciled-period"]
    saved(change(c, "Txn", t, confirm=True, memo="x"))


# ---------- imports and reconciliation ----------


def test_ofx_import_is_idempotent_and_reconciles(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c)
    data = (FIX / "bank.ofx").read_bytes()
    job = upload(c, a["id"], "statement.qfx", data)
    assert job["state"] == "done" and job["result"]["added"] == 5
    again = upload(c, a["id"], "statement.qfx", data)
    assert again["result"]["added"] == 0 and again["result"]["matched"] == 5
    changed = upload(c, a["id"], "again.ofx", data.replace(b"-142.18", b"-142.81"))
    assert changed["result"]["changed"] == 1
    acct = c.get(f"/ui/api/accounts/{a['id']}").json()
    assert acct["openingStandIn"] is True
    view = c.get(f"/ui/api/accounts/{a['id']}/reconcile").json()
    assert view["periods"][0]["start"] == "2026-09-01"
    assert view["checks"][-1]["ok"] is True  # the stand-in opening fits the reported balance
    imports = c.get(f"/ui/api/accounts/{a['id']}/imports").json()["items"]
    assert len(imports) == 3 and imports[0]["userName"] == "Jane"


def test_reimports_match_by_cents_by_row_and_keep_a_repeated_id(server):
    # A file's sub-cent digits change nothing; a row with a FITID matches one typed by
    # hand; a FITID the file repeats is two rows, flagged as duplicate suspects.
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c)
    add(c, a["id"], "-142.18", "2026-09-03", payee="KROGER #123")
    data = (FIX / "bank.ofx").read_bytes()
    job = upload(c, a["id"], "statement.qfx", data)
    assert job["result"]["added"] == 4 and job["result"]["matched"] == 1, job
    fine = data.replace(b"<TRNAMT>3120.00", b"<TRNAMT>3120.004")
    assert upload(c, a["id"], "fine.qfx", fine)["result"]["changed"] == 0
    # An amount the file changed is read with the one it had before (S1.11.3).
    moved = data.replace(b"<TRNAMT>3120.00", b"<TRNAMT>3100.00")
    assert upload(c, a["id"], "moved.qfx", moved)["result"]["changed"] == 1
    items = c.get("/ui/api/transactions", params={"account": a["id"]}).json()["items"]
    assert sorted((x["amount"], x["amountWas"]) for x in items if x["amountWas"]) == [
        ("3100.00", "3120.00")
    ]
    repeat = data.replace(b"<FITID>20260910-1", b"<FITID>20260903-1")
    b = new_account(c, name="Second", mask="9999")
    first = upload(c, b["id"], "repeat.qfx", repeat)["result"]
    assert first["added"] == 5
    assert upload(c, b["id"], "repeat.qfx", repeat)["result"]["added"] == 0
    from moolakata.ledger import reconcile
    from moolakata.store.entities.accounts import Account
    from moolakata.store.repos import ledger as repo

    with server.db.read(unscoped="test") as s:
        txns = repo.load(s, s.get(Account, b["id"])).transactions
        groups = reconcile.duplicates(txns)
        fits = sorted(t.fitId for t in txns if t.id in groups[0])
    assert len(groups) == 1 and fits == ["20260903-1", "20260903-1#2"]


def test_typed_balance_mismatch_and_adjustment(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, openingBalance="1000.00", openingDate="2026-08-31")
    add(c, a["id"], "-20.00", "2026-09-05", payee="Cafe")
    add(c, a["id"], "-20.00", "2026-09-05", payee="Cafe")
    r = create(c, "Anchr", accountId=a["id"], date="2026-09-10", balance="980.00")
    assert r.status_code == 200, r.text
    view = c.get(f"/ui/api/accounts/{a['id']}/reconcile").json()
    check = view["checks"][-1]
    assert not check["ok"] and check["difference"] == "20.00"
    assert len(check["suspects"]["duplicates"]) == 1
    assert c.get(f"/ui/api/accounts/{a['id']}").json()["mismatch"] is True
    fix = {"accountId": a["id"], "date": "2026-09-10", "amount": "20.00", "kind": "adjustment",
           "payee": "Balance adjustment"}  # fmt: skip
    r = create(c, "Txn", **fix, memo="")
    assert r.json()["errors"][0]["field"] == "memo"
    saved(create(c, "Txn", **fix, memo="Bank fee refunded"))
    assert c.get(f"/ui/api/accounts/{a['id']}/reconcile").json()["checks"][-1]["ok"]


def test_brokerage_ofx_makes_holdings(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage", institution="Example Brokerage")
    job = upload(c, a["id"], "brokerage.ofx", (FIX / "brokerage.ofx").read_bytes())
    assert job["state"] == "done", job["error"]
    h = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()
    vti = h["holdings"][0]
    assert vti["symbol"] == "VTI" and vti["quantity"] == "15.0"
    assert vti["priceSource"] == "statement" and vti["value"] == "4500.00"
    assert h["cash"] == "2317.40"


def test_option_trades_and_an_assignment_from_a_brokers_file(server):
    # OFX option trades are the four option trades, and an assignment is settled with the
    # broker's own stock trade, its premium in the shares' basis; a re-import adds nothing.
    from moolakata.store.entities.accounts import Account, Instrument, Transaction
    from moolakata.store.repos import ledger as repo

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage", institution="Example Brokerage")
    data = (FIX / "options.ofx").read_bytes()
    job = upload(c, a["id"], "options.ofx", data)
    assert job["state"] == "done", job["error"]
    assert not job["result"].get("warnings"), job
    with server.db.read(unscoped="test") as s:
        rows = s.query(Transaction).filter_by(accountId=a["id"]).all()
        kinds = sorted(t.kind for t in rows)
        assert kinds == sorted(
            ["deposit", "sell-to-open", "buy-to-open", "sell-to-close", "assign", "buy"]
        )
        buy = next(t for t in rows if t.kind == "buy")
        assert buy.fitId == "A1" and buy.amount == Decimal("-30000.10") and buy.optionTransactionId
        replay = repo.load(s, s.get(Account, a["id"])).replay()
        aapl = next(x for x in replay.open if x.quantity == 200)
        assert s.get(Instrument, aapl.instrumentId).symbol == "AAPL"
        assert aapl.basis == Decimal("29401.40")  # the strike and its fee, less the put's credit
        assert sum(x.quantity for x in replay.open if x is not aapl) == 0
        call = [d for d in replay.disposals if d.proceeds == Decimal("699.35")]
        assert len(call) == 1 and call[0].basis == Decimal("520.65")
    again = upload(c, a["id"], "options.ofx", data)
    assert again["result"]["added"] == 0


def test_a_sale_keeps_the_lot_method_in_force_when_it_was_made(server):
    # An imported sale records the account's method; changing the method later applies to
    # the sales after it, never rewriting the ones before.
    from moolakata.store.entities.accounts import Transaction

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage", institution="Example Brokerage")
    upload(c, a["id"], "brokerage.ofx", (FIX / "brokerage.ofx").read_bytes())
    with server.db.read(unscoped="test") as s:
        sale = s.query(Transaction).filter_by(accountId=a["id"], kind="sell").one()
        assert sale.lotMethod == "fifo"
    before = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()["holdings"][0]["costBasis"]
    assert before == "3951.00"  # five of the $250 lot sold first, FIFO
    acct = c.get(f"/ui/api/accounts/{a['id']}").json()
    r = change(c, "Acct", acct, lotMethod="lifo")
    assert r.status_code == 200, r.text
    h = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()["holdings"][0]
    assert h["costBasis"] == before  # the sale before the change is as it was
    add(c, a["id"], "1500.00", "2026-10-05", kind="sell", symbol="VTI", quantity="5", price="300")
    h = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()["holdings"][0]
    assert h["costBasis"] == "2600.50"  # the later sale takes five of the newest lot


def test_a_files_positions_are_a_check_on_reconcile(server):
    # Positions the trades don't explain show as a difference; the lots stay as they are.
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage", institution="Example Brokerage")
    data = (FIX / "brokerage.ofx").read_bytes().replace(b"<UNITS>15<", b"<UNITS>20<")
    upload(c, a["id"], "brokerage.ofx", data)
    vti = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()["holdings"][0]
    assert vti["quantity"] == "15.0"
    r = c.get(f"/ui/api/accounts/{a['id']}/reconcile").json()
    assert r["holdingChecksAsOf"] == "2026-09-30"
    line = r["holdingChecks"][0]
    assert line["symbol"] == "VTI" and line["difference"] == 5 and not line["ok"]


def test_a_split_in_a_brokers_file_is_imported(server):
    # The split's options step took a path that didn't exist, failing the whole import.
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage", institution="Example Brokerage")
    split = (
        b"<SPLIT><INVTRAN><FITID>SP1<DTTRADE>20260901</INVTRAN><SECID><UNIQUEID>922908769"
        b"<UNIQUEIDTYPE>CUSIP</SECID><SUBACCTSEC>CASH<OLDUNITS>15<NEWUNITS>30<NUMERATOR>2"
        b"<DENOMINATOR>1</SPLIT>\n</INVTRANLIST>"
    )
    data = (FIX / "brokerage.ofx").read_bytes().replace(b"</INVTRANLIST>", split)
    job = upload(c, a["id"], "brokerage.ofx", data)
    assert job["state"] == "done", job["error"]


def test_csv_import_asks_for_a_mapping_once(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, institution="Credit Union")
    data = (
        b"Date,Description,Amount,Balance\n2026-09-01,Pay,100.00,100.00\n"
        b"2026-09-02,Shop,-10.00,90.00\n"
    )
    job = upload(c, a["id"], "export.csv", data)
    result = job["result"]
    assert result["needsMapping"] and result["mapping"]["amount"] == "Amount"
    mapping = {**result["mapping"], "payee": ""}
    r = c.post(f"/ui/api/imports/{result['uploadId']}/mapping", json={"mapping": mapping})
    assert r.json()["errors"][0]["field"] == "mapping.payee"
    r = c.post(f"/ui/api/imports/{result['uploadId']}/mapping", json={"mapping": result["mapping"]})
    assert r.status_code == 202
    done = wait_job(c, r.json())
    assert done["result"]["added"] == 2
    more = data + b"2026-09-03,Shop,-5.00,85.00\n"
    job = upload(c, a["id"], "export2.csv", more)
    assert job["result"]["added"] == 1  # the saved mapping, and the first two matched
    assert c.get(f"/ui/api/accounts/{a['id']}/reconcile").json()["checks"][-1]["ok"]


def test_held_uploads_count_against_the_users_uploads_in_flight(server, monkeypatch):
    """An upload waiting for its mapping counts; past the limit the user's oldest is
    let go, and a dialog closed lets its own go at once."""
    from moolakata import middleware

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, institution="Credit Union")
    rows = b"".join(b"2026-09-%02d,Coffee at the corner,-4.50\n" % d for d in range(1, 29))
    data = b"Date,Description,Amount\n" + rows
    monkeypatch.setattr(middleware, "IN_FLIGHT", int(len(data) * 1.5))
    job = upload(c, a["id"], "one.csv", data)
    first = job["result"]["uploadId"]
    second = upload(c, a["id"], "two.csv", data)["result"]["uploadId"]
    mapping = {"mapping": {"date": "Date", "dateFormat": "%Y-%m-%d", "amount": "Amount",
                           "payee": "Description"}}  # fmt: skip
    r = c.post(f"/ui/api/imports/{first}/mapping", json=mapping)
    assert r.status_code == 404 and r.json()["code"] == "upload-gone"
    assert c.delete(f"/ui/api/imports/{second}").json()["deleted"]["id"] == second
    r = c.post(f"/ui/api/imports/{second}/mapping", json=mapping)
    assert r.status_code == 404


def test_uploads_are_checked_from_their_content(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c)
    r = c.post(
        f"/ui/api/accounts/{a['id']}/imports",
        files={"file": ("statement.ofx", b"MZ\x90\x00\x03 a program, not a statement")},
    )
    assert r.status_code == 415


def test_an_edited_transfer_in_moves_its_holding(server):
    # Shares moved in from another broker, then corrected: the edit reaches the holding.
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")
    t = add(c, a["id"], "0", "2026-03-02", kind="transfer-in", symbol="VTI", quantity="10")
    saved(change(c, "Txn", t, quantity="12", costBasis="2400.00"))
    h = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()["holdings"][0]
    assert Decimal(h["quantity"]) == 12 and h["costBasis"] == "2400.00"


def test_an_account_closes_on_a_day_and_opens_again(server):
    """S1.2: an account's closed date, empty while open; never a day still to come."""
    import datetime as dt

    from moolakata import clock

    clock.fix(dt.datetime(2026, 10, 20, 15, 0, tzinfo=dt.UTC))
    try:
        make_user(server, "jane")
        c = sign_in(server, "jane")
        a = new_account(c)
        path = f"/ui/api/accounts/{a['id']}"
        r = edit(c, "Acct", path, closedOn="2026-10-21")
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "closed-in-future"
        assert edit(c, "Acct", path, closedOn="2026-10-15").status_code == 200
        assert c.get(path).json()["closedOn"] == "2026-10-15"
        kinds = [x["kind"] for x in c.get("/ui/api/activity").json()["items"]]
        assert "account.closed" in kinds
        assert edit(c, "Acct", path, closedOn=None).status_code == 200
        assert c.get(path).json()["closedOn"] is None
        kinds = [x["kind"] for x in c.get("/ui/api/activity").json()["items"]]
        assert "account.reopened" in kinds
    finally:
        clock.fix(None)


def test_an_ofx_transfer_in_has_its_day_bought_missing(server):
    """Shares moved in by a broker's file say nothing of when they were bought: the lot
    is marked so, its term unknown, until the day is typed."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Schwab", type="brokerage", institution="Charles Schwab")
    data = (FIX / "imports" / "schwab-transfer-in.ofx").read_bytes()
    assert upload(c, a["id"], "transfer.ofx", data)["state"] == "done"
    [vti] = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()["holdings"]
    [lot] = vti["lots"]
    assert lot["acquiredMissing"] and lot["longTerm"] is None and lot["basisMissing"]


def test_a_typed_balance_changes_in_place_and_one_from_a_file_never(server):
    """S1.11: a balance typed by hand is changed where it is, on its own account and never in
    the future, each refusal in its words (R3.7); one a file brought changes only with the
    file; another user's, or one deleted, is not found, and one who only reads its account
    (S10.3) may not change it."""
    import datetime as dt

    from edits import share

    from moolakata import clock
    from moolakata.store.entities.accounts import Anchor

    john = make_user(server, "john").id
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, openingBalance="1000.00", openingDate="2026-08-31")
    other = new_account(c, name="Other")
    add(c, a["id"], "-20.00", "2026-09-05", payee="Cafe")
    an = saved(create(c, "Anchr", accountId=a["id"], date="2026-09-10", balance="990.00"))
    r = change(c, "Anchr", an, accountId=other["id"])
    assert r.status_code == 422, r.text
    assert refusals(r) == [("accountId", "anchor-fixed", "A balance stays with its account.")]
    tomorrow = (clock.today() + dt.timedelta(days=1)).isoformat()
    future = [("date", "date-in-future", "A reported balance can't be in the future.")]
    r = change(c, "Anchr", an, date=tomorrow)
    assert (r.status_code, refusals(r)) == (422, future), r.text
    r = create(c, "Anchr", accountId=a["id"], date=tomorrow, balance="980.00")
    assert (r.status_code, refusals(r)) == (422, future), r.text
    an = saved(change(c, "Anchr", an, balance="980.00", note="  "))
    check = c.get(f"/ui/api/accounts/{a['id']}/reconcile").json()["checks"][-1]
    assert (check["reported"], check["ok"]) == ("980.00", True)
    with server.db.read(unscoped="test") as s:
        kept = s.get(Anchor, an["id"])
        assert (kept.note, kept.source) == (None, "typed")
    # Today's is no balance in the future.
    saved(create(c, "Anchr", accountId=a["id"], date=clock.today().isoformat(), balance="980.00"))
    job = upload(c, other["id"], "statement.qfx", (FIX / "bank.ofx").read_bytes())
    assert job["state"] == "done", job["error"]
    with server.db.read(unscoped="test") as s:
        filed = s.query(Anchor).filter_by(accountId=other["id"]).one()
        filed = {"id": filed.id, "version": filed.version}
    r = change(c, "Anchr", filed, balance="1.00")
    assert refusals(r) == [
        (None, "anchor-imported", "A balance from a file changes with the file.")
    ], r.text
    gone = [(None, "not-found", "Not found")]
    r = change(sign_in(server, "john"), "Anchr", an, balance="1.00")
    assert (r.status_code, refusals(r)) == (404, gone), r.text
    saved(share(c, "account", a["id"], users={john: "read"}))
    r = change(sign_in(server, "john"), "Anchr", an, balance="1.00")
    read_only = [(None, "share-read-only", "You can read this account but not change it.")]
    assert (r.status_code, refusals(r)) == (403, read_only), r.text
    assert remove(c, "Anchr", an).status_code == 200
    r = change(c, "Anchr", an, balance="1.00")
    assert (r.status_code, refusals(r)) == (404, gone), r.text


def test_a_typed_balance_keeps_its_note_trimmed_and_is_logged_for_its_owner(server):
    """S1.11.2: a balance typed keeps its note without the spaces around it, or none, through
    a change that leaves the note as it is; it is the typer's, and logged for the owner."""
    from moolakata.store.entities.accounts import Anchor

    jane = make_user(server, "jane").id
    c = sign_in(server, "jane")
    a = new_account(c, openingBalance="1000.00", openingDate="2026-08-31")
    day = {"accountId": a["id"], "date": "2026-09-10", "balance": "990.00"}
    noted = saved(create(c, "Anchr", **day, note="  From the bank's site  "))
    assert noted["note"] == "From the bank's site"
    bare = saved(create(c, "Anchr", accountId=a["id"], date="2026-09-11", balance="990.00"))
    assert bare["note"] is None
    assert saved(change(c, "Anchr", bare, balance="985.00"))["note"] is None
    assert saved(change(c, "Anchr", noted, note=" Checked "))["note"] == "Checked"
    with server.db.read(unscoped="test") as s:
        made = [s.get(Anchor, x["id"]) for x in (noted, bare)]
        assert [(x.note, x.createdById) for x in made] == [("Checked", jane), (None, jane)]
    typed = ("account.balance-typed", jane, "account", jane, {})
    assert logged(server, a["id"]) == [typed, typed]


INTERVAL = "statement-interval-invalid"
# Each field's refusal, in its own words (R3.7).
REFUSED_WORDS = {
    "lotMethod": "FIFO, LIFO, HIFO, specific identification or average cost.",
    "keptBy": "Imports, manual or bitcoin.",
    "notes": "Notes are up to 20,000 characters.",
    "closedOn": "The day it closed: today or earlier.",
    "statementInterval": "Monthly, quarterly, yearly or none.",
    "statementIntervalDismissed": "An interval.",
    "withdrawalsAMonth": "A savings account's limit: 1 to 99, or empty.",
    "hsaCoverage": "An HSA's coverage: self-only or family.",
    "type": "An account keeps its type.",
    "name": "Enter a name of up to 80 characters.",
    "openingDate": "An opening balance needs its date, and a date its balance.",
}


@pytest.mark.parametrize(
    ("kind", "fields", "field", "code"),
    [
        ("checking", {"lotMethod": "random"}, "lotMethod", "lot-method-invalid"),
        ("checking", {"keptBy": []}, "keptBy", "kept-by-invalid"),
        ("checking", {"keptBy": ["manual", "fax"]}, "keptBy", "kept-by-invalid"),
        ("checking", {"notes": "x" * 20001}, "notes", "notes-too-long"),
        ("checking", {"notes": "x" * 20000}, None, None),
        ("checking", {"closedOn": "tomorrow"}, "closedOn", "closed-in-future"),
        ("checking", {"closedOn": "today"}, None, None),
        ("checking", {"statementInterval": "weekly"}, "statementInterval", INTERVAL),
        (
            "checking",
            {"statementIntervalDismissed": "weekly"},
            "statementIntervalDismissed",
            INTERVAL,
        ),
        ("checking", {"withdrawalsAMonth": 6}, "withdrawalsAMonth", "limit-invalid"),
        ("savings", {"withdrawalsAMonth": 0}, "withdrawalsAMonth", "limit-invalid"),
        ("savings", {"withdrawalsAMonth": 100}, "withdrawalsAMonth", "limit-invalid"),
        ("savings", {"withdrawalsAMonth": 99}, None, None),
        ("money-market", {"withdrawalsAMonth": 1}, None, None),
        ("checking", {"hsaCoverage": "self"}, "hsaCoverage", "coverage-invalid"),
        ("hsa", {"hsaCoverage": "both"}, "hsaCoverage", "coverage-invalid"),
        ("hsa", {"hsaCoverage": "family"}, None, None),
        ("checking", {"type": "savings"}, "type", "type-fixed"),
        ("checking", {"name": "  "}, "name", "name-invalid"),
        ("checking", {"openingBalance": "5.00"}, "openingDate", "opening-incomplete"),
    ],
)
def test_an_accounts_settings_are_refused_on_their_own_field(server, kind, fields, field, code):
    """S1.2, S1.11.7, S8.6, R3.11: a change of an account's settings, each refused on its
    field in its words, and each bound's own side kept."""
    import datetime as dt

    from moolakata import clock

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, type=kind, name=kind.title())
    days = {"today": clock.today(), "tomorrow": clock.today() + dt.timedelta(days=1)}
    fields = {
        k: days[v].isoformat() if v in ("today", "tomorrow") else v for k, v in fields.items()
    }
    r = change(c, "Acct", a, **fields)
    if code is None:
        assert r.status_code == 200, r.text
        return
    assert r.status_code == 422, r.text
    refused = [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]
    assert refused == [(field, code, REFUSED_WORDS[field])]


def logged(server, account_id: str) -> list[tuple]:
    """What Activity holds of an account's changes since it was made (its sharing aside):
    each entry's kind, actor, subject kind, owner and detail."""
    import json

    from moolakata.store.entities.core import Activity

    with server.db.read(unscoped="test") as s:
        rows = (
            s.query(Activity)
            .filter(Activity.subjectId == account_id, Activity.kind.like("account.%"))
            .filter(Activity.kind != "account.created")
            .order_by(Activity.at, Activity.id)
        )
        return [(x.kind, x.actorId, x.subjectKind, x.ownerId, json.loads(x.detail)) for x in rows]


def refusals(r) -> list[tuple]:
    """A save's refusals: each one's field, code and words."""
    return [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]]


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        ("checking", {"notes": "Bills come out of this one."}),
        ("checking", {"keptBy": ["file", "manual"]}),
        ("checking", {"statementInterval": "quarterly"}),
        ("savings", {"withdrawalsAMonth": 6}),
        ("hsa", {"hsaCoverage": "family"}),
    ],
)
def test_an_accounts_change_is_kept_and_logged_for_its_owner_by_the_field_changed(
    server, kind, fields
):
    """S1.2, S8.6, S1.11.7: a change of an account is kept, and logged as an update for its
    owner naming the one field it changed."""
    jane = make_user(server, "jane").id
    c = sign_in(server, "jane")
    a = new_account(c, type=kind, name=kind.title())
    out = saved(change(c, "Acct", a, **fields))
    assert {k: out[k] for k in fields} == fields
    assert logged(server, a["id"]) == [
        ("account.updated", jane, "account", jane, {"fields": list(fields)})
    ]


def test_a_write_share_changes_an_accounts_notes_and_none_of_its_settings(server):
    """S10.3: one who writes an account changes what it holds, its notes among them, logged
    for its owner as theirs; its settings stay the owner's, each refused in the same words."""
    from edits import share

    jane, john = make_user(server, "jane").id, make_user(server, "john").id
    c, j = sign_in(server, "jane"), sign_in(server, "john")
    accounts = {}
    for kind in ("checking", "savings", "hsa"):
        a = new_account(c, type=kind, name=kind.title())
        assert share(c, "account", a["id"], users={john: "write"}).status_code == 200
        accounts[kind] = f"/ui/api/accounts/{a['id']}"
    settings = [
        ("checking", "lotMethod", "lifo"),
        ("checking", "keptBy", ["file", "manual"]),
        ("checking", "closedOn", "2026-01-02"),
        ("checking", "countInNetWorth", False),
        ("checking", "name", "Joint checking"),
        ("checking", "institution", "Second Example Bank"),
        ("checking", "mask", "1234"),
        ("checking", "statementInterval", "quarterly"),
        ("checking", "statementIntervalDismissed", "quarterly"),
        ("checking", "connectionId", new_id("Conn")),
        ("checking", "syncAccount", "Checking ••4417"),
        ("savings", "withdrawalsAMonth", 6),
        ("hsa", "hsaCoverage", "family"),
    ]
    for kind, field, value in settings:
        r = edit(j, "Acct", accounts[kind], **{field: value})
        assert r.status_code == 403, (field, r.text)
        assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [
            (None, "owner-only", "Only the account's owner changes its settings.")
        ], field
    out = saved(edit(j, "Acct", accounts["checking"], notes="John's too."))
    assert out["notes"] == "John's too."
    assert logged(server, out["id"]) == [
        ("account.updated", john, "account", jane, {"fields": ["notes"]})
    ]


def test_a_reconciliation_made_finished_stays_and_an_unfinished_one_may_go(server):
    """S1.11.6: a statement ticked off in the save that makes it is reconciled at once and
    then stays as it was; one not finished stays with its account and may be deleted, and is
    gone after; one who only reads the account (S10.3) changes neither. Each refusal in its
    words (R3.7)."""
    from edits import share

    from moolakata.store.entities.accounts import Reconciliation

    jane, john = make_user(server, "jane").id, make_user(server, "john").id
    c = sign_in(server, "jane")
    a = new_account(c, openingBalance="0.00", openingDate="2026-08-31")
    other = new_account(c, name="Other")
    saved(change(c, "Txn", add(c, a["id"], "100.00", "2026-09-03", kind="deposit"), cleared=True))
    fields = {"accountId": a["id"], "statementDate": "2026-09-30", "statementBalance": "100.00"}
    done = saved(create(c, "Recon", finished=True, **fields))
    assert done["finishedAt"]
    stays = [(None, "reconciled", "A reconciled period stays as it was reconciled.")]
    r = change(c, "Recon", done, statementBalance="90.00")
    assert (r.status_code, refusals(r)) == (422, stays), r.text
    r = remove(c, "Recon", done)
    assert (r.status_code, refusals(r)) == (422, stays), r.text
    open_ = reconcile(c, a["id"], "2026-10-31", "100.00")
    r = change(c, "Recon", open_, accountId=other["id"])
    assert r.status_code == 422, r.text
    assert refusals(r) == [("accountId", "reconciliation-fixed", "It stays with its account.")]
    saved(share(c, "account", a["id"], users={john: "read"}))
    read_only = [(None, "share-read-only", "You can read this account but not change it.")]
    r = change(sign_in(server, "john"), "Recon", open_, statementBalance="1.00")
    assert (r.status_code, refusals(r)) == (403, read_only), r.text
    assert remove(c, "Recon", open_).status_code == 200
    with server.db.read(unscoped="test") as s:
        assert s.get(Reconciliation, open_["id"]).deletedById == jane
    r = change(c, "Recon", open_, statementBalance="1.00")
    assert (r.status_code, refusals(r)) == (404, [(None, "not-found", "Not found")]), r.text


def test_a_statement_counts_and_reconciles_its_accounts_ticked_transactions_to_its_day(server):
    """S1.11.6: a statement's cleared total is the opening balance and the account's own
    transactions ticked (or reconciled before) up to and on its date; finished, it reconciles
    those ticked and not yet reconciled, leaves the earlier statement's its own, and is logged
    for the owner. One that doesn't balance is refused on Finished in its words."""
    from moolakata.store.entities.accounts import Transaction

    jane = make_user(server, "jane").id
    c = sign_in(server, "jane")
    a = new_account(c, openingBalance="10.00", openingDate="2026-08-31")
    b = new_account(c, name="Other", openingBalance="0.00", openingDate="2026-08-31")

    def txn(account, amount, day, ticked=True):
        t = add(c, account["id"], amount, day, **({"kind": "deposit"} if amount[0] != "-" else {}))
        return saved(change(c, "Txn", t, cleared=True)) if ticked else t

    paid = txn(a, "100.00", "2026-09-03")
    on_the_day = txn(a, "-40.00", "2026-09-30")
    unticked = txn(a, "-5.00", "2026-09-10", ticked=False)
    after = txn(a, "-7.00", "2026-10-02")
    elsewhere = txn(b, "1000.00", "2026-09-05")
    first = reconcile(c, a["id"], "2026-09-30", "75.00")
    assert (first["cleared"], first["difference"]) == ("70.00", "5.00")
    r = change(c, "Recon", first, finished=True)
    assert r.status_code == 422, r.text
    assert refusals(r) == [
        ("finished", "not-balanced", "Tick transactions until the difference is zero.")
    ]
    first = saved(change(c, "Recon", first, statementBalance="70.00", finished=True))
    second = reconcile(c, a["id"], "2026-10-31", "63.00")
    assert (second["cleared"], second["difference"]) == ("63.00", "0.00")
    saved(change(c, "Recon", second, finished=True))
    with server.db.read(unscoped="test") as s:
        got = {
            t["id"]: s.get(Transaction, t["id"]).reconciliationId
            for t in (paid, on_the_day, unticked, after, elsewhere)
        }
    assert got == {
        paid["id"]: first["id"],
        on_the_day["id"]: first["id"],
        unticked["id"]: None,
        after["id"]: second["id"],
        elsewhere["id"]: None,
    }
    reconciled = ("account.reconciled", jane, "account", jane, {})
    assert logged(server, a["id"]) == [reconciled, reconciled]


@pytest.mark.parametrize(
    ("acct", "fields", "field", "code"),
    [
        ("checking", {"kind": "gift"}, "kind", "kind-invalid"),
        ("brokerage", {"kind": "merger"}, "kind", "corporate-kind"),
        ("checking", {"kind": "option-adjust"}, "kind", "corporate-kind"),
        ("brokerage", {"kind": "expire"}, "kind", "option-kind"),
        ("brokerage", {"kind": "foreign-tax", "amount": "1.00"}, "amount", "amount-sign"),
        ("brokerage", {"kind": "foreign-tax", "amount": "-1.00"}, None, None),
        ("checking", {"categoryId": "gone"}, "categoryId", "category-unknown"),
        (
            "brokerage",
            {"kind": "buy", "instrumentId": "gone", "quantity": "1", "price": "10", "fees": "0"},
            "instrumentId",
            "instrument-unknown",
        ),
        (
            "brokerage",
            {"kind": "buy", "symbol": "VTI", "quantity": "1", "fees": None},
            "fees",
            "fees-invalid",
        ),
        ("checking", {"fees": "-0.01"}, "fees", "fees-invalid"),
        (
            "checking",
            {"kind": "deposit", "amount": "10.00", "reimbursable": "5.00"},
            "reimbursable",
            "reimbursable-invalid",
        ),
        ("checking", {"reimbursable": "0"}, "reimbursable", "reimbursable-invalid"),
        ("checking", {"reimbursable": "10.01"}, "reimbursable", "reimbursable-invalid"),
        ("checking", {"reimbursable": "10.00"}, None, None),
        ("checking", {"owedBy": "x" * 81}, "owedBy", "owed-by-too-long"),
        ("checking", {"owedBy": "x" * 80}, None, None),
        ("checking", {"payee": "x" * 201}, "payee", "payee-too-long"),
        ("checking", {"payee": "x" * 200}, None, None),
        (
            "ira",
            {"kind": "deposit", "amount": "10.00", "contributionSource": "boss"},
            "contributionSource",
            "choice-invalid",
        ),
        (
            "ira",
            {"kind": "deposit", "amount": "10.00", "contributionYear": 1969},
            "contributionYear",
            "year-invalid",
        ),
        (
            "ira",
            {"kind": "deposit", "amount": "10.00", "contributionYear": 2101},
            "contributionYear",
            "year-invalid",
        ),
        ("ira", {"kind": "deposit", "amount": "10.00", "contributionYear": 2100}, None, None),
    ],
)
def test_a_transactions_fields_are_refused_on_their_own(server, acct, fields, field, code):
    """S2.1, S2.9, S8.6, R3.11: what a transaction is and carries, each refused on its field,
    and each bound's own side kept."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, type=acct, name=acct.title())
    fields = {"accountId": a["id"], "date": "2026-09-01", "amount": "-10.00", **fields}
    if fields.get("categoryId") == "gone":
        fields["categoryId"] = new_id("Cat")
    if fields.get("instrumentId") == "gone":
        fields["instrumentId"] = new_id("Instr")
    r = make(c, "Txn", **fields)
    if code is None:
        assert r.status_code == 200, r.text
        return
    assert r.status_code == 422, r.text
    assert (r.json()["errors"][0]["field"], r.json()["errors"][0]["code"]) == (field, code)


def test_both_real_answers_the_rows_grouped_with_it_and_no_others(server):
    """S1.11.5: *both real* is kept on the rows the reconcile view grouped as possible
    duplicates with the one answered: the same day, amount and payee, or one id a file gave
    twice, never a row that only shares the day and amount."""
    from moolakata.ledger import reconcile
    from moolakata.store.entities.accounts import Account, Transaction
    from moolakata.store.repos import ledger as repo

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c)
    cafe = add(c, a["id"], "-40.00", "2026-09-05", payee="Cafe")
    add(c, a["id"], "-40.00", "2026-09-05", payee="Cafe")
    bakery = add(c, a["id"], "-40.00", "2026-09-05", payee="Bakery")
    add(c, a["id"], "-40.00", "2026-09-05", payee="Bakery")
    b = new_account(c, name="Second", mask="9999")
    data = (FIX / "bank.ofx").read_bytes().replace(b"<FITID>20260910-1", b"<FITID>20260903-1")
    assert upload(c, b["id"], "repeat.qfx", data)["result"]["added"] == 5

    def groups(account_id):
        with server.db.read(unscoped="test") as s:
            txns = repo.load(s, s.get(Account, account_id)).transactions
            return [sorted(t.payee or "" for t in txns if t.id in g)
                    for g in reconcile.duplicates(txns)]  # fmt: skip

    assert groups(a["id"]) == [["Cafe", "Cafe"], ["Bakery", "Bakery"]]
    r = c.post(f"/ui/api/transactions/{cafe['id']}/both-real")
    assert r.status_code == 200, r.text
    assert groups(a["id"]) == [["Bakery", "Bakery"]]
    with server.db.read(unscoped="test") as s:
        second = s.query(Transaction).filter_by(accountId=b["id"], fitId="20260903-1#2").one().id
    assert c.post(f"/ui/api/transactions/{second}/both-real").status_code == 200
    assert groups(b["id"]) == []
    # Another user's row, and one deleted, are not found.
    make_user(server, "john")
    assert (
        sign_in(server, "john").post(f"/ui/api/transactions/{bakery['id']}/both-real").status_code
        == 404
    )
    one = c.get("/ui/api/transactions", params={"payee": "bakery"}).json()["items"][0]
    saved(remove(c, "Txn", one))
    assert c.post(f"/ui/api/transactions/{one['id']}/both-real").status_code == 404


def test_keeping_a_transaction_needs_one_off_the_chain_at_the_version_read(server):
    """S1.6.2.7: *keep* is for a transaction no longer on the chain, at the version read, by
    one who writes its account (S10.3); one on the chain, an old version (answered with the
    transaction as the caller reads it, their tags with it), one only read, and one deleted
    or never made are each refused."""
    from edits import share
    from test_sharing import setup

    u, c = setup(server)
    jane, john = c["jane"], c["john"]
    a = new_account(jane)
    t = add(jane, a["id"], "-5.00", "2026-09-01", tags=["work"])

    def keep(who, txn_id, version):
        return who.post(f"/ui/api/transactions/{txn_id}/keep", headers={"If-Match": f'"{version}"'})

    r = keep(jane, t["id"], t["version"])
    assert (r.status_code, r.json()["code"]) == (422, "on-chain"), r.text
    r = keep(jane, t["id"], t["version"] - 1)
    assert (r.status_code, r.json()["code"]) == (412, "stale-version"), r.text
    assert (r.json()["current"]["id"], r.json()["current"]["tags"]) == (t["id"], ["work"])
    saved(share(jane, "account", a["id"], users={u["john"].id: "read"}))
    r = keep(john, t["id"], t["version"])
    assert (r.status_code, r.json()["code"]) == (403, "share-read-only"), r.text
    gone = add(jane, a["id"], "-6.00", "2026-09-02")
    saved(remove(jane, "Txn", gone))
    for txn_id, version in ((new_id("Txn"), 1), (gone["id"], gone["version"])):
        r = keep(jane, txn_id, version)
        assert (r.status_code, r.json()["code"], r.json()["detail"]) == (
            404,
            "not-found",
            "Not found",
        ), txn_id


def test_a_kind_changed_to_blank_is_refused_on_its_field(server):
    """R3.11: a change that blanks a transaction's kind is refused on the field, never written
    (it reached the database before, refused there as a missing reference)."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    t = add(c, new_account(c)["id"], "-5.00", "2026-09-01")
    r = change(c, "Txn", t, kind="")
    assert r.status_code == 422, r.text
    assert (r.json()["errors"][0]["field"], r.json()["errors"][0]["code"]) == (
        "kind",
        "kind-invalid",
    )


def test_a_trade_changed_carries_its_lot_and_a_known_day_bought_stays(server):
    """S2.2, S2.3: a buy changed moves its lot's quantity, cost and day with it; shares moved
    in whose lots were typed keep each lot's day bought when the move's day changes."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")

    def lots_(symbol):
        held = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()["holdings"]
        lots = next(h for h in held if h["symbol"] == symbol)["lots"]
        return [(x["quantity"], x["basis"], x["acquiredOn"]) for x in lots]

    buy = add(c, a["id"], "-1000.00", "2026-09-01", kind="buy", symbol="VTI", quantity="10",
              price="100", fees="0")  # fmt: skip
    buy = saved(change(c, "Txn", buy, quantity="12", amount="-1260.00", date="2026-09-02"))
    assert lots_("VTI") == [("12.0", "1260.00", "2026-09-02")]
    # Each of the three changed alone carries the lot too, a reinvestment's as a buy's.
    buy = saved(change(c, "Txn", buy, quantity="11"))
    assert lots_("VTI") == [("11.0", "1260.00", "2026-09-02")]
    buy = saved(change(c, "Txn", buy, amount="-1100.00"))
    assert lots_("VTI") == [("11.0", "1100.00", "2026-09-02")]
    saved(change(c, "Txn", buy, date="2026-09-03"))
    assert lots_("VTI") == [("11.0", "1100.00", "2026-09-03")]
    again = add(c, a["id"], "-50.00", "2026-09-04", kind="reinvest", symbol="VXUS", quantity="1",
                price="50", fees="0")  # fmt: skip
    saved(change(c, "Txn", again, quantity="2"))
    assert lots_("VXUS") == [("2.0", "50.00", "2026-09-04")]
    # Shares moved in with no lots typed: their one lot's day follows the day they arrived.
    untyped = add(c, a["id"], "0.00", "2026-09-10", kind="transfer-in", symbol="SCHD",
                  quantity="3")  # fmt: skip
    saved(change(c, "Txn", untyped, date="2026-09-12"))
    assert _lots_made(server, untyped["id"]) == [("2026-09-12", 3, None, True, True)]
    typed = [{"acquiredOn": "2020-01-02", "quantity": "5", "costBasis": "250"}]
    moved = add(c, a["id"], "0.00", "2026-09-10", kind="transfer-in", symbol="KO", quantity="5",
                transferLots=typed)  # fmt: skip
    saved(change(c, "Txn", moved, date="2026-09-11"))
    assert lots_("KO") == [("5.0", "250.00", "2020-01-02")]


def test_an_amount_changed_is_checked_as_it_is_sent(server):
    """S2.1: a change is checked with the amount it sends, not the one it had: foreign tax
    paid made money in is refused on its amount."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")
    t = add(c, a["id"], "-10.00", "2026-09-01", kind="foreign-tax")
    r = change(c, "Txn", t, amount="10.00")
    assert r.status_code == 422, r.text
    assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [
        ("amount", "amount-sign", "Foreign tax paid is money out: a negative amount.")
    ]


def test_a_trade_left_without_fees_keeps_them_until_its_fees_or_kind_change(server):
    """R3.11: a trade a file brought without fees changes without its fees typed; changed in
    kind, it is a trade typed again, and a blank is refused."""
    from moolakata.store.entities.accounts import Transaction

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")
    buy = add(c, a["id"], "-100.00", "2026-09-01", kind="buy", symbol="VTI", quantity="1",
              price="100", fees="0")  # fmt: skip
    with server.db.tx(unscoped="test") as s:
        s.get(Transaction, buy["id"]).fees = None  # as a file without fees leaves it
    path = f"/ui/api/transactions/{buy['id']}"
    assert saved(edit(c, "Txn", path, memo="from the file"))["fees"] is None
    r = edit(c, "Txn", path, kind="reinvest")
    assert r.status_code == 422, r.text
    assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [
        ("fees", "fees-invalid", "Zero or more.")
    ]
    assert saved(edit(c, "Txn", path, kind="reinvest", fees="0"))["kind"] == "reinvest"


def test_a_trade_made_a_sale_takes_the_accounts_method_and_made_a_buy_none(server):
    """S2.3: a buy changed into a sale takes the account's lot method, the one in force for
    it; changed back into a buy, it has none."""
    from moolakata.store.entities.accounts import Transaction

    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage", lotMethod="lifo")["id"]
    add(c, a, "-1000.00", "2026-09-01", kind="buy", symbol="VTI", quantity="10", price="100",
        fees="0")  # fmt: skip
    t = add(c, a, "-500.00", "2026-09-02", kind="buy", symbol="VTI", quantity="5", price="100",
            fees="0")  # fmt: skip

    def method():
        with server.db.read(unscoped="test") as s:
            return s.get(Transaction, t["id"]).lotMethod

    assert method() is None
    t = saved(change(c, "Txn", t, kind="sell", amount="500.00"))
    assert method() == "lifo"
    saved(change(c, "Txn", t, kind="buy", amount="-500.00"))
    assert method() is None


def test_a_transfer_changed_in_its_amount_or_its_day_is_paired_no_more(server):
    """S1.7: a half whose amount or day changes is no longer the other's: both are free."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    chk = new_account(c)["id"]
    card = new_account(c, name="Visa", type="credit-card", mask="1111")["id"]

    def paired(t):
        return c.get(f"/ui/api/transactions/{t['id']}").json()["transferId"]

    for amount, fields in (("500.00", {"amount": "499.00"}), ("600.00", {"date": "2026-09-17"})):
        out = add(c, chk, f"-{amount}", "2026-09-15")
        paid = add(c, card, amount, "2026-09-16", kind="deposit")
        assert paired(paid) == out["id"]
        saved(change(c, "Txn", paid, **fields))
        assert (paired(out), paired(paid)) == (None, None), fields


def _lots_made(server, txn_id):
    """The live lots a transaction made, as stored: day bought, quantity, basis, and whether
    its basis and its day bought are missing."""
    from sqlalchemy import false, select

    from moolakata.store.entities.accounts import Lot

    with server.db.read(unscoped="test") as s:
        rows = s.scalars(select(Lot).where(Lot.transactionId == txn_id, Lot.deleted == false()))
        return sorted((str(x.acquiredOn), x.quantity, x.costBasis, x.basisMissing,
                       x.acquiredMissing) for x in rows)  # fmt: skip


def test_shares_moved_in_arrive_as_the_lots_typed_each_bought_by_that_day(server):
    """S2.2: the lots typed add up to the shares moved in, each of some shares, bought on or
    before the day they moved in; none typed, one lot of that day, its day bought missing, and
    its basis missing unless typed."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")["id"]
    move = {"accountId": a, "date": "2026-09-10", "kind": "transfer-in", "symbol": "KO",
            "quantity": "10", "amount": "0.00"}  # fmt: skip
    unbalanced = ("transferLots", "lots-unbalanced", "The lots add up to the shares moved in.")
    invalid = ("transferLots", "lot-invalid", "Each lot was bought by the day it moved in.")
    for typed, refusal in (
        ([("2020-01-02", "9")], unbalanced),
        ([("2026-09-11", "10")], invalid),  # bought after it moved in
        ([("2020-01-02", "10"), ("2021-01-04", "0")], invalid),
        ([("2020-01-02", "12"), ("2021-01-04", "-2")], invalid),
    ):
        lots = [{"acquiredOn": d, "quantity": q, "costBasis": "100"} for d, q in typed]
        r = create(c, "Txn", **move, transferLots=lots)
        assert r.status_code == 422, r.text
        assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [refusal]
    # Bought the day it moved in, and less than one share: both lots as typed.
    lots = [{"acquiredOn": "2026-09-10", "quantity": "9.5", "costBasis": "950"},
            {"acquiredOn": "2020-01-02", "quantity": "0.5"}]  # fmt: skip
    t = add(c, a, **{**move, "amount": "0.00"}, transferLots=lots)
    assert _lots_made(server, t["id"]) == [
        ("2020-01-02", Decimal("0.5"), None, True, False),
        ("2026-09-10", Decimal("9.5"), Decimal("950"), False, False),
    ]
    t = add(c, a, **move)
    assert _lots_made(server, t["id"]) == [("2026-09-10", Decimal(10), None, True, True)]
    t = add(c, a, **move, costBasis="400.00")
    assert _lots_made(server, t["id"]) == [("2026-09-10", Decimal(10), Decimal(400), False, True)]


def test_coins_received_as_income_open_a_lot_at_their_value_that_day(server):
    """S8.5: a reward's lot has its value as its basis: at the price typed with it, else the
    owner's price for its day; none known, its basis is missing."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    ex = new_account(c, name="Exchange", type="crypto-exchange")["id"]
    # The owner's own trades price ETH, before the day and after it; a price typed later
    # wins from its day on (S4.7).
    for day, price in (("2026-03-01", "2000"), ("2026-05-01", "3000")):
        bought = add(c, ex, f"-{price}.00", day, kind="buy", symbol="ETH", quantity="1",
                     price=price, fees="0")  # fmt: skip
    eth = bought["instrumentId"]
    saved(create(c, "TyPrc", instrumentId=eth, date="2026-06-30", close="2500"))
    reward = {"kind": "reward", "symbol": "ETH", "quantity": "0.003"}
    priced = add(c, ex, "0.00", "2026-04-01", **reward)
    unknown = add(c, ex, "0.00", "2026-04-01", **{**reward, "symbol": "SOL"})
    typed = add(c, ex, "0.00", "2026-07-01", **reward, price="1234.56")
    assert [_lots_made(server, t["id"]) for t in (priced, unknown, typed)] == [
        [("2026-04-01", Decimal("0.003"), Decimal("6.00"), False, False)],
        [("2026-04-01", Decimal("0.003"), None, True, False)],
        [("2026-07-01", Decimal("0.003"), Decimal("3.70"), False, False)],
    ]


def test_a_split_is_of_a_known_transaction_not_a_trade_and_a_known_category(server):
    """S2.6: a part names a transaction the caller writes that isn't a trade, and a category
    there is."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c)
    spent = add(c, a["id"], "-100.00", "2026-09-01")
    brk = new_account(c, name="Brokerage", type="brokerage")
    bought = add(c, brk["id"], "-100.00", "2026-09-01", kind="buy", symbol="VTI", quantity="1",
                 price="100", fees="0")  # fmt: skip
    gone = add(c, a["id"], "-5.00", "2026-09-01")
    saved(remove(c, "Txn", gone))
    for txn in (new_id("Txn"), gone["id"]):  # the save finds no such record
        assert create(c, "Split", transactionId=txn, amount="-40.00").status_code == 404
    trade = ("transactionId", "split-trade", "A trade isn't split across categories.")
    unknown = ("categoryId", "category-unknown", "Choose a category.")
    for txn, fields, refusal in (
        (bought["id"], {}, trade),
        (spent["id"], {"categoryId": new_id("Cat")}, unknown),
    ):
        r = create(c, "Split", transactionId=txn, amount="-40.00", **fields)
        assert r.status_code == 422, r.text
        assert [(e["field"], e["code"], e["message"]) for e in r.json()["errors"]] == [refusal]


def test_a_sold_buy_deleted_leaves_its_sale_without_a_lot(server):
    """S8.4: the shares a sale took gone with their buy, the sale has no lot to match: shown
    as such, never taken from another lot or a basis made up."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    brk = new_account(c, name="Brokerage", type="brokerage")
    bought = add(c, brk["id"], "-100.00", "2026-09-01", kind="buy", symbol="VTI", quantity="1",
                 price="100", fees="0")  # fmt: skip
    add(c, brk["id"], "120.00", "2026-09-02", kind="sell", symbol="VTI", quantity="1",
        price="120", fees="0")  # fmt: skip
    saved(remove(c, "Txn", c.get(f"/ui/api/transactions/{bought['id']}").json()))
    sold = next(r for r in c.get("/ui/api/positions").json()["closed"] if r["symbol"] == "VTI")
    assert sold["realized"] is None, sold


# One account of each group (S1.1) and every kind (S2.1): what the transaction save takes.
GRID_TYPES = ("checking", "credit-card", "mortgage", "brokerage", "ira", "529", "daf",
              "crypto-exchange", "vehicle")  # fmt: skip
HOLDING_KINDS = ("buy", "sell", "reinvest", "return-of-capital", "transfer-in", "transfer-out",
                 "split", "foreign-tax", "reward")  # fmt: skip


def test_every_kind_in_an_account_of_every_group_is_taken_or_refused_by_its_rule(server):
    """S2.1, S2.4, S3.2, S3.10: a kind that moves a holding is an investing account's alone;
    an option trade, an option's end, a corporate action and a contract's adjustment are made
    where they are made, never typed here; every other kind goes in any account."""
    from moolakata.ledger import types as atypes
    from moolakata.store.tables.accounts import TXN_KINDS
    from moolakata.ui import transactions as tx

    make_user(server, "jane")
    c = sign_in(server, "jane")
    accts = {t: new_account(c, type=t, name=t)["id"] for t in GRID_TYPES}
    for kind in TXN_KINDS:
        for type_, aid in accts.items():
            f = {"accountId": aid, "date": "2026-09-01", "amount": "-10.00", "kind": kind,
                 "memo": "why"}  # fmt: skip
            if kind in HOLDING_KINDS or kind in ("dividend", "capital-gain"):
                f |= {"symbol": "VTI", "quantity": "1", "price": "10"}
            if kind == "split":
                f |= {"splitRatio": "2", "amount": "0.00"}
            if kind in ("buy-to-open", "sell-to-open", "buy-to-close", "sell-to-close"):
                want = "right-invalid"  # read as an option trade, which names its contract
            elif kind in tx.CORPORATE_KINDS:
                want = "corporate-kind"
            elif kind in tx.OPTION_KINDS:
                want = "option-kind"
            elif kind in HOLDING_KINDS and not atypes.investing(type_):
                want = "kind-not-for-account"
            else:
                want = None
            r = make(c, "Txn", **f)
            got = None if r.status_code == 200 else r.json()["errors"][0]["code"]
            assert got == want, (kind, type_, r.text)


def test_an_account_is_made_with_what_its_dialog_sent(server):
    """S1.2: a new account keeps its notes, its opening balance's date, whether it counts in
    net worth as sent, and no institution when none was given."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(
        c,
        institution=None,
        notes="Bills come out of this one.",
        openingBalance="10.00",
        openingDate="2026-08-31",
        countInNetWorth=False,
    )
    got = c.get(f"/ui/api/accounts/{a['id']}").json()
    assert {k: got[k] for k in ("institution", "notes", "openingDate", "countInNetWorth")} == {
        "institution": None,
        "notes": "Bills come out of this one.",
        "openingDate": "2026-08-31",
        "countInNetWorth": False,
    }


def test_an_account_is_deleted_by_its_owner_logged_and_never_by_one_who_reads_it(server):
    """S10.3: one who only reads an account is refused its deletion in the words of a read
    share; its owner deletes it, marked as theirs and logged for them."""
    from edits import share

    from moolakata.store.entities.accounts import Account

    jane, john = make_user(server, "jane").id, make_user(server, "john").id
    c = sign_in(server, "jane")
    a = new_account(c)
    saved(share(c, "account", a["id"], users={john: "read"}))
    a = c.get(f"/ui/api/accounts/{a['id']}").json()
    r = remove(sign_in(server, "john"), "Acct", a)
    read_only = [(None, "share-read-only", "You can read this account but not change it.")]
    assert (r.status_code, refusals(r)) == (403, read_only), r.text
    assert remove(c, "Acct", a).status_code == 200
    with server.db.read(unscoped="test") as s:
        assert s.get(Account, a["id"]).deletedById == jane
    assert logged(server, a["id"]) == [("account.deleted", jane, "account", jane, {})]


def test_a_trade_names_its_holding_and_shares_each_missing_refused_on_its_own_field(server):
    """S2.1, R3.11: every kind that moves a holding names it and how much: a holding missing
    is refused on the symbol, shares missing on the quantity."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")["id"]
    words = "A trade needs its instrument and quantity."
    for kind in ("buy", "sell", "reinvest", "transfer-in", "transfer-out", "reward"):
        trade = {"accountId": a, "date": "2026-09-01", "amount": "-10.00", "kind": kind,
                 "price": "10"}  # fmt: skip
        for sent, field in (({"quantity": "1"}, "symbol"), ({"symbol": "VTI"}, "quantity"),
                            ({}, "symbol")):  # fmt: skip
            r = make(c, "Txn", **trade, **sent)
            assert (r.status_code, refusals(r)) == (422, [(field, "trade-incomplete", words)]), (
                kind,
                sent,
            )


def test_a_transaction_is_made_with_what_its_dialog_sent_and_by_whom(server):
    """S2.6: a new transaction keeps its memo and its tick, its payee trimmed as the
    institution's words too, and no payee or debtor when none was sent; it is the maker's."""
    from moolakata.store.entities.accounts import Transaction

    jane = make_user(server, "jane").id
    c = sign_in(server, "jane")
    a = new_account(c)["id"]
    sent = add(c, a, "-20.00", payee="  Acme  ", memo="rent", cleared=True,
               reimbursable="5.00", owedBy=" Bob ")  # fmt: skip
    bare = add(c, a, "-30.00")
    keys = ("payee", "payeeRaw", "memo", "cleared", "owedBy")
    got = [c.get(f"/ui/api/transactions/{t['id']}").json() for t in (sent, bare)]
    assert [{k: t[k] for k in keys} for t in got] == [
        {"payee": "Acme", "payeeRaw": "Acme", "memo": "rent", "cleared": True, "owedBy": "Bob"},
        {"payee": None, "payeeRaw": None, "memo": None, "cleared": False, "owedBy": None},
    ]
    with server.db.read(unscoped="test") as s:
        assert [s.get(Transaction, t["id"]).createdById for t in (sent, bare)] == [jane, jane]


def test_a_retirement_deposit_counts_for_the_year_typed_else_its_days(server):
    """S1.4: a contribution to a retirement account is for the year typed with it, else the
    year of its day; nothing else carries a year it wasn't given."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    ira = new_account(c, name="IRA", type="ira")["id"]
    chk = new_account(c, name="Bank", mask="2222")["id"]
    made = [
        add(c, ira, "100.00", "2026-03-01", kind="deposit", contributionYear=2025),
        add(c, ira, "100.00", "2026-03-01", kind="deposit"),
        add(c, ira, "-100.00", "2026-03-01", kind="withdrawal"),
        add(c, chk, "100.00", "2026-03-01", kind="deposit"),
    ]
    got = [c.get(f"/ui/api/transactions/{t['id']}").json()["contributionYear"] for t in made]
    assert got == [2025, 2026, None, None]


def test_shares_moved_in_read_with_the_basis_typed_and_other_trades_with_none(server):
    """S2.2, S2.6: a transfer-in is read with the basis typed with it; a buy's basis is its
    lot's, never read as the transaction's."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")["id"]
    moved = add(c, a, "0.00", "2026-09-10", kind="transfer-in", symbol="KO", quantity="10",
                costBasis="400.00")  # fmt: skip
    bought = add(c, a, "-100.00", "2026-09-10", kind="buy", symbol="KO", quantity="1",
                 price="100")  # fmt: skip
    got = [c.get(f"/ui/api/transactions/{t['id']}").json()["costBasis"] for t in (moved, bought)]
    assert got == ["400.00", None]


def test_a_reinvested_dividend_opens_a_lot_of_the_shares_it_bought(server):
    """S2.5: a reinvestment is a buy: its shares are a lot bought that day at its amount."""
    make_user(server, "jane")
    c = sign_in(server, "jane")
    a = new_account(c, name="Brokerage", type="brokerage")["id"]
    t = add(c, a, "-50.00", "2026-09-04", kind="reinvest", symbol="VXUS", quantity="1",
            price="50")  # fmt: skip
    assert _lots_made(server, t["id"]) == [("2026-09-04", Decimal(1), Decimal(50), False, False)]
