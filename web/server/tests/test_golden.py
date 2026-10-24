"""Golden files (requirements S17.5): a fixture portfolio whose Form 8949 rows and TXF file are
known, checked byte for byte. A change to either export shows here as a diff to read; after
reading it, `MK_GOLDEN_WRITE=1 pytest tests/test_golden.py` writes the files again."""

import datetime as dt
import os
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import make_user, sign_in
from test_accounts import add, new_account

from moolakata import clock

GOLDEN = Path(__file__).parent / "golden"
T0 = dt.datetime(2026, 12, 20, 12, tzinfo=dt.UTC)


@pytest.fixture
def alice(server):
    clock.fix(T0)
    make_user(server, "alice", born=1970)
    yield sign_in(server, "alice")
    clock.fix(None)


def trade(c, acct, day, kind, qty, price, symbol):
    amount = Decimal(qty) * Decimal(price)
    add(
        c,
        acct,
        f"{-amount if kind == 'buy' else amount:.2f}",
        day,
        kind=kind,
        symbol=symbol,
        quantity=qty,
        price=price,
    )


def portfolio(c) -> str:
    brk = new_account(c, name="Taxable", type="brokerage", mask="1001")
    trade(c, brk["id"], "2024-01-05", "buy", "10", "100", "VTI")
    trade(c, brk["id"], "2026-02-01", "sell", "4", "150", "VTI")  # long-term, box D
    trade(c, brk["id"], "2026-03-02", "buy", "10", "400", "MSFT")
    trade(c, brk["id"], "2026-04-01", "sell", "10", "350", "MSFT")  # a loss, washed
    trade(c, brk["id"], "2026-04-15", "buy", "10", "360", "MSFT")  # its replacement
    r = c.post(
        f"/ui/api/accounts/{brk['id']}/options",
        json={
            "date": "2026-05-01",
            "action": "sell-to-open",
            "underlying": "AAPL",
            "right": "put",
            "strike": "200",
            "expiry": "2026-06-19",
            "contracts": "1",
            "premium": "3.10",
            "fees": "0.65",
        },
    )
    assert r.status_code == 201, r.text
    r = c.post(
        f"/ui/api/accounts/{brk['id']}/options",
        json={
            "date": "2026-05-20",
            "action": "buy-to-close",
            "underlying": "AAPL",
            "right": "put",
            "strike": "200",
            "expiry": "2026-06-19",
            "contracts": "1",
            "premium": "1.05",
            "fees": "0.65",
        },
    )
    assert r.status_code == 201, r.text
    ex = new_account(c, name="Exchange", type="crypto-exchange", mask="2002")
    trade(c, ex["id"], "2025-03-01", "buy", "0.05", "80000", "BTC")
    trade(c, ex["id"], "2026-06-01", "sell", "0.05", "100000", "BTC")  # long, no basis: K
    trade(c, ex["id"], "2026-07-01", "buy", "0.02", "90000", "BTC")
    trade(c, ex["id"], "2026-08-03", "sell", "0.02", "95000", "BTC")  # acquired 2026: G
    w = new_account(c, name="Cold storage", type="crypto-wallet", mask="3003")
    trade(c, w["id"], "2026-02-02", "buy", "0.01", "85000", "BTC")
    trade(c, w["id"], "2026-05-04", "sell", "0.01", "98000", "BTC")  # self-custody: I
    me = c.get("/ui/api/session").json()["user"]["id"]
    r = c.post("/ui/api/tax-books", json={"year": 2026, "filers": [me]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize(
    ("export", "golden"),
    [("8949.csv", "form-8949-2026.csv"), ("moolakata.txf", "moolakata-2026.txf")],
)
def test_the_exports_match_their_golden_files(alice, export, golden):
    book = portfolio(alice)
    r = alice.get(f"/ui/api/tax-books/{book}/exports/{export}")
    assert r.status_code == 200, r.text
    path = GOLDEN / golden
    if os.environ.get("MK_GOLDEN_WRITE") == "1":
        path.write_bytes(r.content)
    assert r.content == path.read_bytes()


def option(c, acct, day, action, premium, **kw):
    r = c.post(
        f"/ui/api/accounts/{acct}/options",
        json={
            "date": day,
            "action": action,
            "underlying": kw.get("underlying", "MSFT"),
            "right": kw.get("right", "call"),
            "strike": kw.get("strike", "500"),
            "expiry": kw.get("expiry", "2027-01-15"),
            "contracts": "1",
            "premium": premium,
            "fees": "0.65",
        },
    )
    assert r.status_code == 201, r.text


def review_cases(c) -> str:
    """The figures the second review found wrong (section 4), each a case whose rows are
    worked out by hand in the comments."""
    # B1: average cost re-bases every lot at each sale: 300 paid, 300 of basis sold.
    avg = new_account(c, name="Average", type="brokerage", mask="4004", lotMethod="average")
    trade(c, avg["id"], "2026-01-05", "buy", "10", "10", "VXUS")
    trade(c, avg["id"], "2026-01-06", "buy", "10", "20", "VXUS")  # the average is 15
    trade(c, avg["id"], "2026-02-02", "sell", "5", "15", "VXUS")  # 75 against 75
    trade(c, avg["id"], "2026-03-02", "sell", "15", "15", "VXUS")  # 225 against 225
    # B2: a loss washed into a replacement that is itself sold at a loss and replaced again:
    # each loss deferred, the second including the first.
    chain = new_account(c, name="Chained", type="brokerage", mask="5005")
    trade(c, chain["id"], "2026-01-05", "buy", "10", "100", "NVDA")
    trade(c, chain["id"], "2026-02-02", "sell", "10", "80", "NVDA")  # 200 lost, washed
    trade(c, chain["id"], "2026-02-10", "buy", "10", "85", "NVDA")  # basis 850 + 200
    trade(c, chain["id"], "2026-03-02", "sell", "10", "70", "NVDA")  # 350 lost, washed
    trade(c, chain["id"], "2026-03-09", "buy", "10", "72", "NVDA")  # basis 720 + 350, held
    # B11: a written option is short term however long it was open (S3.3).
    written = new_account(c, name="Written", type="brokerage", mask="6006")
    trade(c, written["id"], "2025-01-02", "buy", "100", "1", "CASHX")  # cash for margin
    option(c, written["id"], "2025-01-10", "sell-to-open", "20.00")  # 2000 - 0.65
    option(c, written["id"], "2026-03-10", "buy-to-close", "12.00")  # 1200 + 0.65
    me = c.get("/ui/api/session").json()["user"]["id"]
    r = c.post("/ui/api/tax-books", json={"year": 2026, "filers": [me]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_the_review_cases_match_their_golden_file(alice):
    # S17.5: a golden case for each figure the second review found wrong.
    book = review_cases(alice)
    r = alice.get(f"/ui/api/tax-books/{book}/exports/8949.csv")
    assert r.status_code == 200, r.text
    path = GOLDEN / "form-8949-review-2026.csv"
    if os.environ.get("MK_GOLDEN_WRITE") == "1":
        path.write_bytes(r.content)
    assert r.content == path.read_bytes()
    # B2: the second replacement, still held, carries both losses' second: 720 + 350.
    held = alice.get("/ui/api/positions").json()["open"]
    nvda = next(x for x in held if x["symbol"] == "NVDA")
    assert nvda["cost"] == "1070.00"


def budget_household(c):
    """A household's budgets over three months, touching every figure of S7: rollover, a
    reserve held in savings, moves, money leaving the budget, a loan's split payment, a refund,
    reimbursable spending, and an envelope scenario with a card."""
    cat = {x["path"]: x["id"] for x in c.get("/ui/api/categories").json()["items"]}
    chk = new_account(c, name="Checking", mask="2001")
    sav = new_account(c, name="Savings", type="savings", mask="2002")
    card = new_account(c, name="Visa", type="credit-card", mask="2003")
    brk = new_account(c, name="Brokerage", type="brokerage", mask="2004")
    ids = [chk["id"], sav["id"], card["id"]]
    b = c.post(
        "/ui/api/budgets",
        json={"name": "Household", "accountIds": ids, "reserves": True, "moves": True},
    ).json()
    food, fun, repair = cat["Food"], cat["Entertainment"], cat["Transportation › Car maintenance"]
    lines = [
        {"categoryId": cat["Income › Salary"], "amount": "4000.00"},
        {"categoryId": food, "amount": "500.00", "rollover": True},
        {"categoryId": fun, "amount": "150.00"},
        {"categoryId": repair, "amount": "100.00", "target": "250.00", "heldInId": sav["id"]},
        {"categoryId": cat["Loan payments"], "amount": "1100.00"},
        {"categoryId": cat["Savings › Investing"], "amount": "300.00"},
    ]
    v = c.get(f"/ui/api/budgets/{b['id']}").json()["version"]
    c.put(
        f"/ui/api/budgets/{b['id']}/plan",
        json={"month": "2026-09-01", "lines": lines},
        headers={"If-Match": str(v)},
    )
    loan = new_account(c, name="Car loan", type="auto-loan", mask="2005")
    c.put(
        f"/ui/api/accounts/{loan['id']}/loan",
        json={"principal": "20000", "startDate": "2026-08-01", "termMonths": 60, "rate": "6"},
    )
    for m in ("09", "10", "11"):
        add(
            c,
            chk["id"],
            "4000.00",
            f"2026-{m}-01",
            payee="Payroll",
            categoryId=cat["Income › Salary"],
        )
        add(
            c,
            chk["id"],
            "-460.00",
            f"2026-{m}-04",
            payee="Kroger",
            categoryId=cat["Food › Groceries"],
        )
        c.post(
            f"/ui/api/accounts/{loan['id']}/loan/payments",
            json={"date": f"2026-{m}-15", "amount": "1000.00", "fromAccountId": chk["id"]},
        )
        add(
            c,
            chk["id"],
            "-300.00",
            f"2026-{m}-20",
            payee="To Fidelity",
            categoryId=cat["Savings › Investing"],
        )
        add(c, brk["id"], "300.00", f"2026-{m}-20", payee="From checking", kind="deposit")
    add(c, chk["id"], "-200.00", "2026-09-28", payee="To savings")
    add(c, sav["id"], "200.00", "2026-09-28", payee="From checking", kind="deposit")
    add(c, card["id"], "-260.00", "2026-10-09", payee="Midas", categoryId=repair)
    add(c, card["id"], "-190.00", "2026-10-12", payee="Concert", categoryId=fun)
    add(
        c,
        chk["id"],
        "35.00",
        "2026-10-14",
        payee="Kroger refund",
        categoryId=cat["Food › Groceries"],
    )
    hotel = add(
        c,
        card["id"],
        "-310.00",
        "2026-11-03",
        payee="Hilton",
        categoryId=cat["Travel"],
        reimbursable="310.00",
        owedBy="Acme Corp",
    )
    back = add(c, chk["id"], "310.00", "2026-11-18", payee="Acme expense report")
    c.post(
        "/ui/api/reimbursements",
        json={"spendingId": hotel["id"], "paybackId": back["id"], "amount": "310.00"},
    )
    c.post(
        f"/ui/api/budgets/{b['id']}/moves",
        json={"month": "2026-10-01", "fromCategoryId": food, "toCategoryId": fun, "amount": "40"},
    )
    for day, amount in (("2026-10-25", "-450.00"), ("2026-11-25", "-150.00")):
        add(c, chk["id"], amount, day, payee="Visa payment")
        add(c, card["id"], amount[1:], day, payee="Thank you", kind="deposit")
    env = c.post(
        f"/ui/api/budgets/{b['id']}/copy", json={"name": "Envelopes", "method": "envelope"}
    ).json()
    return b, env


def budget_figures(c, b) -> list[str]:
    out = []
    for month in ("2026-09", "2026-10", "2026-11", "2026-12"):
        v = c.get(f"/ui/api/budgets/{b['id']}/month", params={"month": month}).json()
        head = f"{b['name']} {month}"
        out.append(
            f"{head} spent {v['spent']} saved {v['saved']} income {v['income']}"
            f" toBudget {v['toBudget']} moved {len(v['moved'])}"
        )
        for r in v["rows"]:
            out.append(
                f"{head} {r['label']}: planned {r['planned']} carried {r['carried']}"
                f" moved {r['moved']} actual {r['actual']} remaining {r['remaining']}"
                f" {r['state']}" + (f" balance {r['balance']}" if r["balance"] is not None else "")
            )
        for x in v["cards"]:
            out.append(
                f"{head} card {x['name']}: set aside {x['setAside']} owed {x['owed']}"
                f" not backed {x['notBacked']}"
            )
        w = c.get(f"/ui/api/budgets/{b['id']}/where", params={"month": month}).json()
        for h in w["heldIn"]:
            out.append(
                f"{head} held in {h['accountName']}: total {h['total']} moved in {h['movedIn']}"
                f" to move {h['toMove']}"
            )
    return out


def test_the_budgets_match_their_golden_file(alice):
    b, env = budget_household(alice)
    got = "\n".join(budget_figures(alice, b) + budget_figures(alice, env)) + "\n"
    path = GOLDEN / "budgets-2026.txt"
    if os.environ.get("MK_GOLDEN_WRITE") == "1":
        path.write_text(got)
    assert got == path.read_text()
