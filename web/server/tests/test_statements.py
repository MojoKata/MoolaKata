"""Statement import (requirements S1.3.3): the parser on the layouts most statements share."""

import datetime as dt
from decimal import Decimal

from moolakata.importers import statements

TODAY = dt.date(2026, 10, 13)

UMB = """UMB Bank, n.a.
Free Checking
Statement Period: 09/01/26 - 09/30/26
Account Summary
Beginning Balance on 09/01/26 $5,710.50
Deposits and Other Credits 4,820.00
Withdrawals and Other Debits 4,410.00
Ending Balance on 09/30/26 $6,120.50
Deposits and Other Credits
09/15 ACME CORP PAYROLL 2,410.00
09/30 ACME CORP PAYROLL 2,410.00
Withdrawals and Other Debits
09/03 POS KROGER #412 142.18
09/10 ONLINE TRANSFER TO SAVINGS 1,000.00
09/22 DUKE ENERGY 188.40
Checks Paid
09/12 1043 3,079.42
Daily Balance
09/03 5,568.32
09/10 4,568.32
"""

SCHWAB = """Charles Schwab Bank
Schwab Bank Investor Checking
Statement Period: September 1-30, 2026
Beginning Balance $1,000.00
Ending Balance $1,207.82
Transaction Detail
Date Description Withdrawals Deposits Balance
09/03 Visa Purchase BLUE BOTTLE 42.18 957.82
09/15 Funds Transfer from Brokerage 500.00 1,457.82
09/20 ATM Fee Rebate 3.00 1,460.82
09/28 Bill Pay CITY POWER 253.00 1,207.82
"""

CARD = """Example Card Co
Opening/Closing Date 08/29/26 - 09/28/26
Previous Balance $1,203.11
Payments and Credits -$1,203.11
Purchases +$842.50
New Balance $842.50
Transactions
08/31 KROGER #412 142.18
09/05 PAYMENT THANK YOU -1,203.11
09/12 DELTA AIR 700.32
"""


COMBINED = """UMB Bank, n.a.
Statement Period: 09/01/26 - 09/30/26
Free Checking Account Number XXXXXX4821
Beginning Balance $1,000.00
Ending Balance $1,500.00
Deposits and Other Credits
09/15 ACME CORP PAYROLL 2,000.00
Withdrawals and Other Debits
09/20 ONLINE TRANSFER TO SAVINGS 1,500.00
UMB Bank, n.a.  Page 2 of 3
Account Number XXXXXX4821 (continued)
Daily Balance
09/15 3,000.00
Savings Account Number XXXXXX9030
Beginning Balance $10,000.00
Ending Balance $11,502.10
Deposits and Other Credits
09/20 ONLINE TRANSFER FROM CHECKING 1,500.00
09/30 INTEREST PAID 2.10
"""


def parse(text, **kw):
    return statements.parse(text.splitlines(), TODAY, **kw)


def test_a_umb_checking_statement_by_its_sections():
    st = parse(UMB)
    assert (st.periodStart, st.periodEnd) == (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert (st.opening, st.closing) == (Decimal("5710.50"), Decimal("6120.50"))
    assert [(r.date.day, r.amount) for r in st.rows] == [
        (15, Decimal("2410.00")),
        (30, Decimal("2410.00")),
        (3, Decimal("-142.18")),
        (10, Decimal("-1000.00")),
        (22, Decimal("-188.40")),
        (12, Decimal("-3079.42")),
    ]
    assert st.difference == 0, "the daily balances are not transactions"
    assert st.institution.startswith("UMB Bank")


def test_a_schwab_statement_by_its_running_balance():
    st = parse(SCHWAB)
    assert (st.periodStart, st.periodEnd) == (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert [r.amount for r in st.rows] == [
        Decimal("-42.18"),
        Decimal("500.00"),
        Decimal("3.00"),
        Decimal("-253.00"),
    ]
    assert all(r.confidence >= 97 for r in st.rows) and st.difference == 0


def test_a_card_statement_is_turned_to_the_accounts_side():
    st = parse(CARD, card=True)
    assert (st.opening, st.closing) == (Decimal("-1203.11"), Decimal("-842.50"))
    assert [r.amount for r in st.rows] == [
        Decimal("-142.18"),
        Decimal("1203.11"),
        Decimal("-700.32"),
    ]
    assert st.rows[0].date == dt.date(2026, 8, 31) and st.difference == 0


def test_a_cards_cr_and_dr_are_the_accounts_side_already():
    # B20: a payment marked CR is money in, turned once, never twice.
    st = parse(
        CARD.replace("PAYMENT THANK YOU -1,203.11", "PAYMENT THANK YOU 1,203.11 CR"), card=True
    )
    assert [r.amount for r in st.rows] == [
        Decimal("-142.18"),
        Decimal("1203.11"),
        Decimal("-700.32"),
    ]
    assert st.difference == 0


def test_a_statement_that_does_not_add_up_says_by_how_much():
    st = parse(UMB.replace("09/22 DUKE ENERGY 188.40\n", ""))
    assert st.difference == Decimal("-188.40")


def test_the_layout_learned_is_applied_next_time():
    text = """Prairie Credit Union
Statement Period 10/01/26 - 10/31/26
Beginning Balance 100.00
Ending Balance 70.00
Money Movement
10/02 COFFEE 10.00
10/05 RENT 20.00
Fee Detail
10/05 SERVICE CHARGE WAIVED 5.00
"""
    first = parse(text)
    assert first.difference != 0
    # The person makes the first section money out and takes the waived fee out.
    kept = [
        statements.StatementRow(r.date, r.description, -abs(r.amount), section=r.section)
        for r in first.rows
        if not r.description.startswith("SERVICE")
    ]
    layout = statements.learn(None, kept, remember=["Service charge waived"])
    again = parse(text, layout=layout)
    # The fee asked to be ignored is shown, marked, and left out of the sum.
    assert [(r.amount, r.ignored) for r in again.rows] == [
        (Decimal("-10.00"), None),
        (Decimal("-20.00"), None),
        (Decimal("-5.00"), "service charge waived"),
    ]
    assert again.difference == 0
    assert statements.learn(layout, kept, forget=["service charge waived"])["skip"] == []


def test_a_line_left_out_teaches_no_skip():
    """CR3-16: a line is ignored next time only when the person asks (Remember…), never because
    they left it out, or because it was already in the account."""
    row = statements.StatementRow
    day = dt.date(2026, 9, 3)
    kept = [row(day, "DEBIT CARD PURCHASE KROGER 123", Decimal("-40.00"))]
    assert statements.learn(None, kept)["skip"] == []
    asked = statements.learn(None, kept, remember=["  Service  Charge waived "])
    assert asked["skip"] == ["service charge waived"]
    assert statements.learn(asked, kept, remember=["service charge waived"])["skip"] == [
        "service charge waived"
    ]


# ---------- through the server ----------


def _import(c, account_id, data, name="statement.pdf", keep=False):
    from test_accounts import wait_job

    r = c.post(
        f"/ui/api/accounts/{account_id}/" + ("statements/keep" if keep else "imports"),
        files={"file": (name, data, "application/pdf")},
    )
    assert r.status_code == 202, r.text
    return wait_job(c, r.json())


def test_a_statement_is_checked_then_saved_once(server):
    from conftest import make_user, sign_in
    from test_accounts import new_account
    from test_reading import text_pdf

    make_user(server, "alice")
    c = sign_in(server, "alice")
    acct = new_account(c, institution="UMB Bank")
    pdf = text_pdf(UMB.splitlines())
    job = _import(c, acct["id"], pdf)
    assert job["state"] == "done", job
    review = job["result"]
    assert review["needsReview"] and review["method"] == "text"
    assert len(review["rows"]) == 6 and review["opening"] == "5710.50"
    rows = [
        {"date": x["date"], "description": x["description"], "amount": x["amount"]}
        for x in review["rows"]
    ]
    body = {
        "periodStart": review["periodStart"],
        "periodEnd": review["periodEnd"],
        "opening": review["opening"],
        "closing": review["closing"],
        "rows": rows[:-1],
    }
    r = c.post(f"/ui/api/imports/{review['uploadId']}/statement", json=body)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "acceptDifference"
    body["rows"] = rows
    r = c.post(f"/ui/api/imports/{review['uploadId']}/statement", json=body)
    assert r.status_code == 200, r.text
    done = r.json()["result"]
    assert done["added"] == 6
    # The statement is kept as a receipt on the account, its text searchable.
    rc = c.get(f"/ui/api/receipts/{done['receiptId']}").json()
    assert rc["links"][0]["accountId"] == acct["id"] and "PAYROLL" in rc["text"]
    # The balances are the account's anchors: the Reconcile tab checks them.
    rec = c.get(f"/ui/api/accounts/{acct['id']}/reconcile").json()
    assert [k["source"] for k in rec["checks"]].count("statement") == 2
    # The same statement again adds nothing.
    again = _import(c, acct["id"], pdf)["result"]
    assert all(x["present"] for x in again["rows"])
    r = c.post(
        f"/ui/api/imports/{again['uploadId']}/statement",
        json={**body, "rows": rows},
    )
    assert r.json()["result"]["added"] == 0


CARDS = """UMB Bank, n.a.
Free Checking
Statement Period: {start} - {end}
Beginning Balance on {start} $1,000.00
Ending Balance on {end} $895.00
Withdrawals and Other Debits
{m}/03 DEBIT CARD PURCHASE {first} 60.00
{m}/04 DEBIT CARD PURCHASE KROGER 123 40.00
{m}/05 SERVICE CHARGE WAIVED 5.00
"""


def test_correcting_a_line_then_importing_the_next_statement_keeps_its_lines(server):
    """CR3-1, CR3-16 (S1.3.3.3, S1.3.3.4), end to end: the person renames one line, leaves
    the waived fee out and asks to ignore lines like it; the next statement from the bank keeps
    every card purchase and shows the fee, ignored, left out."""
    from conftest import make_user, sign_in
    from test_accounts import new_account
    from test_reading import text_pdf

    make_user(server, "alice")
    c = sign_in(server, "alice")
    acct = new_account(c, institution="UMB Bank")
    sep = CARDS.format(start="09/01/26", end="09/30/26", m="09", first="AMAZN MKTP")
    review = _import(c, acct["id"], text_pdf(sep.splitlines()))["result"]
    assert [x["description"] for x in review["rows"]] == [
        "DEBIT CARD PURCHASE AMAZN MKTP",
        "DEBIT CARD PURCHASE KROGER 123",
        "SERVICE CHARGE WAIVED",
    ]
    rows = [
        {"date": x["date"], "description": x["description"], "amount": x["amount"], "line": i}
        for i, x in enumerate(review["rows"])
    ]
    rows[0]["description"] = "Amazon"
    rows[2]["include"] = False
    body = {
        **_body(review),
        "rows": rows,
        "acceptDifference": True,
        "remember": ["service charge waived"],
    }
    r = c.post(f"/ui/api/imports/{review['uploadId']}/statement", json=body)
    assert r.status_code == 200, r.text
    oct_ = CARDS.format(start="10/01/26", end="10/31/26", m="10", first="TARGET 0042")
    nxt = _import(c, acct["id"], text_pdf(oct_.splitlines()))["result"]
    assert [(x["description"], x["ignored"]) for x in nxt["rows"]] == [
        ("DEBIT CARD PURCHASE TARGET 0042", None),
        ("DEBIT CARD PURCHASE KROGER 123", None),
        ("SERVICE CHARGE WAIVED", "service charge waived"),
    ]
    # Profile lists it, and it can be taken back.
    listed = c.get("/ui/api/statement-layouts/ignored").json()["items"]
    assert listed == [{"institution": "UMB Bank", "kind": "bank", "start": "service charge waived"}]
    assert c.post("/ui/api/statement-layouts/ignored/forget", json=listed[0]).status_code == 204
    assert c.get("/ui/api/statement-layouts/ignored").json()["items"] == []


def test_statement_reading_can_be_off(server, admin_client):
    from conftest import make_user, sign_in
    from edits import save_settings
    from test_accounts import new_account
    from test_reading import text_pdf

    assert save_settings(admin_client, {"readStatements": False}).status_code == 200
    make_user(server, "alice")
    c = sign_in(server, "alice")
    acct = new_account(c)
    r = c.post(
        f"/ui/api/accounts/{acct['id']}/imports",
        files={"file": ("s.pdf", text_pdf(UMB.splitlines()), "application/pdf")},
    )
    assert r.status_code == 415 and r.json()["code"] == "statements-off"


def test_a_statement_of_two_accounts_splits_where_each_begins():
    lines = COMBINED.splitlines()
    parts = statements.split(lines)
    assert [p.last4 for p in parts] == ["4821", "9030"]
    assert "Page 2 of 3" in "\n".join(parts[0].lines), "a repeated header stays in its part"
    whole = statements._period(lines)
    checking = statements.parse(parts[0].lines, TODAY, period=whole)
    savings = statements.parse(parts[1].lines, TODAY, period=whole)
    assert (checking.opening, checking.closing, checking.difference) == (
        Decimal("1000.00"),
        Decimal("1500.00"),
        0,
    )
    assert savings.periodEnd == dt.date(2026, 9, 30), "the period from the top of the whole"
    assert [r.amount for r in savings.rows] == [Decimal("1500.00"), Decimal("2.10")]
    assert savings.difference == 0
    assert statements.split(UMB.splitlines()) == [], "one account, no header: no parts"


def test_a_kept_statement_is_named_by_its_period():
    start, end, inst = statements.period_and_institution(UMB.splitlines())
    assert statements.name(inst, start, end) == "UMB Bank, n.a. statement, Sep 1 – Sep 30, 2026"
    assert statements.name(None, None, None) == "Statement"


def _body(p: dict, **kw) -> dict:
    return {
        "periodStart": p["periodStart"],
        "periodEnd": p["periodEnd"],
        "opening": p["opening"],
        "closing": p["closing"],
        "rows": [
            {"date": x["date"], "description": x["description"], "amount": x["amount"]}
            for x in p["rows"]
        ],
        **kw,
    }


def test_a_combined_statement_is_saved_once_each_part_is_saved_or_left_out(server):
    from conftest import make_user, sign_in
    from test_accounts import new_account
    from test_reading import text_pdf

    make_user(server, "alice")
    c = sign_in(server, "alice")
    checking = new_account(c, name="Free Checking", institution="UMB Bank", mask="4821")
    savings = new_account(c, name="Savings", type="savings", institution="UMB Bank", mask="1111")
    review = _import(c, checking["id"], text_pdf(COMBINED.splitlines()))["result"]
    parts = review["parts"]
    assert [p["last4"] for p in parts] == ["4821", "9030"]
    assert parts[0]["accountId"] == checking["id"]
    assert parts[1]["accountId"] is None, "no account ends in 9030: the person chooses"
    assert savings["id"] in {x["id"] for x in parts[1]["candidates"]}
    url = f"/ui/api/imports/{review['uploadId']}/statement"
    r = c.post(url, json=_body(parts[0], part=0, accountId=checking["id"]))
    assert r.json()["result"] == {"part": 0, "remaining": [1]}
    assert c.get(f"/ui/api/accounts/{checking['id']}/imports").json()["items"] == [], (
        "nothing is saved until every part is decided"
    )
    r = c.post(url, json=_body(parts[1], part=1))
    assert r.json()["errors"][0]["field"] == "accountId"
    r = c.post(url, json=_body(parts[1], part=1, accountId=savings["id"]))
    assert r.status_code == 200, r.text
    done = r.json()["result"]
    assert [(p["part"], p["added"]) for p in done["parts"]] == [(0, 2), (1, 2)]
    rc = c.get(f"/ui/api/receipts/{done['receiptId']}").json()
    assert {x["accountId"] for x in rc["links"]} == {checking["id"], savings["id"]}, (
        "the PDF is kept once, on each account it filled"
    )
    assert rc["payee"] == "UMB Bank statement, Sep 1 – Sep 30, 2026"


def test_a_statement_kept_without_reading_counts_as_arrived(server):
    from conftest import make_user, sign_in
    from test_accounts import new_account
    from test_reading import text_pdf

    make_user(server, "alice")
    c = sign_in(server, "alice")
    acct = new_account(c, institution="UMB Bank", keptBy=["file"])
    pdf = text_pdf(UMB.splitlines())
    job = _import(c, acct["id"], pdf, keep=True)
    found = job["result"]
    assert (found["periodStart"], found["periodEnd"]) == ("2026-09-01", "2026-09-30")
    url = f"/ui/api/imports/{found['uploadId']}/keep"
    r = c.post(url, json={"periodStart": "2026-09-01", "periodEnd": "2026-09-30"})
    assert r.status_code == 200, r.text
    kept = r.json()["result"]
    rows = c.get(f"/ui/api/accounts/{acct['id']}/imports").json()["items"]
    assert [(x["format"], x["coveredTo"], x["added"]) for x in rows] == [("kept", "2026-09-30", 0)]
    assert c.get(f"/ui/api/transactions?account={acct['id']}").json()["items"] == []
    rc = c.get(f"/ui/api/receipts/{kept['receiptId']}").json()
    assert rc["payee"] == "UMB Bank statement, Sep 1 – Sep 30, 2026"
    # Kept twice is refused.
    again = _import(c, acct["id"], pdf, keep=True)["result"]
    r = c.post(
        f"/ui/api/imports/{again['uploadId']}/keep",
        json={"periodStart": "2026-09-01", "periodEnd": "2026-09-30"},
    )
    assert r.json()["code"] == "statement-kept-already"
