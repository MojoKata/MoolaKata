import time
from decimal import Decimal
from pathlib import Path

from conftest import make_user, sign_in
from edits import asked, change, create, edit, make, new_id, reconcile, remove, saved

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
    for _ in range(600):
        j = c.get(f"/ui/api/jobs/{job['id']}").json()
        if j["state"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def upload(c, account_id, name, data):
    r = c.post(f"/ui/api/accounts/{account_id}/imports", files={"file": (name, data)})
    assert r.status_code == 202, r.text
    assert r.headers["location"] == f"/ui/api/jobs/{r.json()['id']}"
    return wait_job(c, r.json())


# ---------- accounts ----------


def test_accounts_are_checked_and_their_owners_own(server):
    make_user(server, "alice")
    make_user(server, "bob")
    alice, bob = sign_in(server, "alice"), sign_in(server, "bob")
    r = make(alice, "Acct", name="", type="yacht", mask="12", openingBalance="10.00")
    fields = {e["field"] for e in r.json()["errors"]}
    assert fields == {"name", "type", "mask", "openingDate"}
    a = new_account(alice, openingBalance="1000.00", openingDate="2026-08-31")
    assert a["group"] == "banking" and a["access"]["mine"] and a["balance"] == "1000.00"
    assert a["reconcilable"] and not a["investing"]
    assert bob.get(f"/ui/api/accounts/{a['id']}").status_code == 404
    assert bob.get("/ui/api/accounts").json()["items"] == []
    assert saved(change(alice, "Acct", a, name="Joint checking"))["name"] == "Joint checking"
    r = change(alice, "Acct", a, name="Stale")
    assert r.status_code == 412
    v = r.json()["current"][0]["version"]
    assert remove(alice, "Acct", {"id": a["id"], "version": v}).status_code == 200
    assert alice.get("/ui/api/accounts").json()["items"] == []


# ---------- transactions ----------


def test_transactions_filter_page_and_balance(server):
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    assert (
        c.get("/ui/api/transactions", params={"tag": "holiday"}).json()["items"][0]["id"] == t["id"]
    )


def test_transfers_are_matched_and_can_be_undone(server):
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(c)
    fields = {"accountId": a["id"], "date": "2026-09-01", "amount": "-1.00"}
    ops = [{"op": "create", "entity": "Txn", "id": new_id("Txn"), "fields": fields}]
    r1 = c.post("/ui/api/save", json={"ops": ops}, headers={"Idempotency-Key": "k1"})
    r2 = c.post("/ui/api/save", json={"ops": ops}, headers={"Idempotency-Key": "k1"})
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    assert len(c.get("/ui/api/transactions").json()["items"]) == 1


def test_trades_make_lots_holdings_and_gains(server):
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    assert len(imports) == 3 and imports[0]["userName"] == "Alice"


def test_reimports_match_by_cents_by_row_and_keep_a_repeated_id(server):
    # B19: a file's sub-cent digits change nothing; a row with a FITID matches one typed by
    # hand; a FITID the file repeats is two rows, flagged as duplicate suspects.
    make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(c)
    add(c, a["id"], "-142.18", "2026-09-03", payee="KROGER #123")
    data = (FIX / "bank.ofx").read_bytes()
    job = upload(c, a["id"], "statement.qfx", data)
    assert job["result"]["added"] == 4 and job["result"]["matched"] == 1, job
    fine = data.replace(b"<TRNAMT>3120.00", b"<TRNAMT>3120.004")
    assert upload(c, a["id"], "fine.qfx", fine)["result"]["changed"] == 0
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(c, name="Brokerage", type="brokerage", institution="Example Brokerage")
    job = upload(c, a["id"], "brokerage.ofx", (FIX / "brokerage.ofx").read_bytes())
    assert job["state"] == "done", job["error"]
    h = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()
    vti = h["holdings"][0]
    assert vti["symbol"] == "VTI" and vti["quantity"] == "15.0"
    assert vti["priceSource"] == "statement" and vti["value"] == "4500.00"
    assert h["cash"] == "2317.40"


def test_option_trades_and_an_assignment_from_a_brokers_file(server):
    # B5: OFX option trades are the four option trades, and an assignment is settled with the
    # broker's own stock trade, its premium in the shares' basis; a re-import adds nothing.
    from moolakata.store.entities.accounts import Account, Instrument, Transaction
    from moolakata.store.repos import ledger as repo

    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    # B7: an imported sale records the account's method; changing the method later applies to
    # the sales after it, never rewriting the ones before.
    from moolakata.store.entities.accounts import Transaction

    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    # B9: positions the trades don't explain show as a difference; the lots stay as they are.
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    """CR3-172: an upload waiting for its mapping counts; past the limit the user's oldest is
    let go, and a dialog closed lets its own go at once."""
    from moolakata import middleware

    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(c)
    r = c.post(
        f"/ui/api/accounts/{a['id']}/imports",
        files={"file": ("statement.ofx", b"MZ\x90\x00\x03 a program, not a statement")},
    )
    assert r.status_code == 415


def test_an_edited_transfer_in_moves_its_holding(server):
    # Shares moved in from another broker, then corrected (B37).
    make_user(server, "alice")
    c = sign_in(server, "alice")
    a = new_account(c, name="Brokerage", type="brokerage")
    t = add(c, a["id"], "0", "2026-03-02", kind="transfer-in", symbol="VTI", quantity="10")
    saved(change(c, "Txn", t, quantity="12", costBasis="2400.00"))
    h = c.get(f"/ui/api/accounts/{a['id']}/holdings").json()["holdings"][0]
    assert Decimal(h["quantity"]) == 12 and h["costBasis"] == "2400.00"
