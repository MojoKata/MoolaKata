"""Tax books (requirements S8.14–S8.17): filers who accept, the accounts counted, filings with
their due dates, results and carried figures, documents against those expected, and next
year's book from this one."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import asked, change, create, make, remove, saved, share
from test_accounts import add, new_account
from test_save import made_at

from moolakata import clock

T0 = dt.datetime(2026, 10, 13, 12, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


@pytest.fixture
def couple(server, frozen):
    make_user(server, "jane")
    make_user(server, "john", sex="male")
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    a_id = jane.get("/ui/api/session").json()["user"]["id"]
    b_id = john.get("/ui/api/session").json()["user"]["id"]
    pa = jane.get("/ui/api/profile").json()["personId"]
    pb = john.get("/ui/api/profile").json()["personId"]
    r = make(jane, "Rltn", person1Id=pa, person2Id=pb, relation="spouse", fromDate="2009-06-14")
    assert r.status_code == 200, r.text
    # John confirms the marriage from his Profile (S10.10.4).
    assert john.post(f"/ui/api/relationships/{r.json()['id']}/confirm").status_code == 200
    return jane, john, a_id, b_id


def book(c, year, filers, **kw):
    r = make(c, "TaxBk", **{"year": year, "filers": filers, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_joint_book_counts_a_filer_once_they_accept(server, couple):
    jane, john, a_id, b_id = couple
    new_account(jane, name="Jane's brokerage", type="brokerage")
    new_account(john, name="John's checking")
    b = book(jane, 2026, [a_id, b_id])
    # Made by Jane, it names John first: by (sex, name), men first (S10.10.7).
    assert b["label"] == "2026 · John & Jane (joint)"
    assert [(f["name"], f["accepted"]) for f in b["filers"]] == [("John", False), ("Jane", True)]
    d = jane.get(f"/ui/api/tax-books/{b['id']}").json()
    assert [a["name"] for a in d["accounts"]] == ["Jane's brokerage"]
    listed = john.get("/ui/api/tax-books").json()
    assert listed["books"] == [] and listed["waiting"][0]["id"] == b["id"]
    assert "access" not in listed["waiting"][0]  # an invitation, read of nothing (decision 5)
    assert john.get(f"/ui/api/tax-books/{b['id']}").status_code == 404
    held = john.post(f"/ui/api/tax-books/{b['id']}/accept").json()["access"]
    assert held == {
        "mine": True,
        "writable": True,
        "deletable": True,
        "shareable": True,
        "configurable": True,
    }
    d = john.get(f"/ui/api/tax-books/{b['id']}").json()
    assert {a["name"] for a in d["accounts"]} == {"Jane's brokerage", "John's checking"}
    make_user(server, "bart")
    c_id = sign_in(server, "bart").get("/ui/api/session").json()["user"]["id"]
    r = make(jane, "TaxBk", year=2026, filers=[a_id, c_id])
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not-married"


def test_accounts_left_out_and_added(couple):
    jane, john, a_id, _ = couple
    mine = new_account(jane, name="Mine", type="brokerage")
    kid = new_account(john, name="Lisa's custodial", type="brokerage")
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    share(john, "account", kid["id"], users={a_id: "read"})
    b = book(jane, 2026, [a_id])
    saved(create(jane, "TxBkA", bookId=b["id"], accountId=mine["id"], counted=False))
    d = saved(create(jane, "TxBkA", bookId=b["id"], accountId=kid["id"], counted=True))
    assert [a["name"] for a in d["accounts"]] == ["Lisa's custodial"]
    assert [a["name"] for a in d["leftOut"]] == ["Mine"]
    assert john_id


def test_filings_due_dates_overdue_and_results(couple):
    jane, _, a_id, _ = couple
    bank = new_account(jane, name="Checking")
    refund = add(jane, bank["id"], "1240.00", "2026-03-18", payee="IRS TREAS 310")
    last = book(jane, 2025, [a_id])
    r = make(jane, "Filng", bookId=last["id"], form="Form 1040")
    f = r.parent()["filings"][0]
    assert f["dueDate"] == "2026-04-15" and f["overdue"]
    dash = jane.get("/ui/api/dashboard").json()["attention"]
    assert any(a["text"] == "Federal return for 2025 is past its due date" for a in dash)
    bad = change(jane, "Filng", f, progress="filed")
    assert bad.json()["errors"][0]["field"] == "filedOn"
    fields = {
        "progress": "accepted",
        "filedOn": "2026-03-02",
        "filingStatus": "Single",
        "sentBy": "e-file",
        "resultKind": "refund",
        "resultAmount": "1240",
        "resultTransactionId": refund["id"],
        "carried": {"agi": "214380", "totalTax": "31920", "capitalLossLong": "2100"},
    }
    pay = {"filingId": f["id"], "quarter": 1, "dueDate": "2025-04-15", "amount": "1500"}
    r = jane.post("/ui/api/save", json={"ops": [
        {"op": "update", "entity": "Filng", "id": f["id"], "version": f["version"],
         "fields": fields},
        {"op": "create", "entity": "EstPy", "id": made_at("EstPy", clock.now()), "fields": pay},
    ]})  # fmt: skip
    assert r.status_code == 200, r.text
    f = jane.get(f"/ui/api/tax-books/{last['id']}").json()["filings"][0]
    assert not f["overdue"] and f["resultPaid"].startswith("Checking · Mar 18")
    assert f["payments"][0]["amount"] == "1500.00"
    state = make(jane, "Filng", bookId=last["id"], jurisdiction="state", form="TC-40")
    assert state.json()["errors"][0]["field"] == "place"
    # This year's book carries last year's figures.
    now = book(jane, 2026, [a_id])
    d = jane.get(f"/ui/api/tax-books/{now['id']}").json()
    assert d["lastYear"][0]["filing"] == "Federal · Form 1040"
    assert d["lastYear"][0]["figures"]["agi"] == "214380.00"
    assert d["federalDue"] == "2027-04-15"


def test_documents_expected_received_and_carried_to_next_year(couple):
    jane, _, a_id, _ = couple
    brk = new_account(jane, name="Brokerage", type="brokerage", institution="Fidelity")
    new_account(jane, name="Mortgage", type="mortgage", institution="Rocket")
    last = book(jane, 2025, [a_id])
    d = jane.get(f"/ui/api/tax-books/{last['id']}").json()
    assert {e["form"] for e in d["expected"]} == {"1099 (composite)", "1098"}
    up = jane.post(
        "/ui/api/receipts", files={"file": ("w2.pdf", b"%PDF-1.4 w2", "application/pdf")}
    )
    make(
        jane,
        "TxDoc",
        bookId=last["id"],
        form="1099 (composite)",
        issuer="Fidelity",
        accountId=brk["id"],
        receiptId=up.json()["id"],
    )
    d = make(jane, "TxDoc", bookId=last["id"], form="W-2", issuer="Acme Corp").parent()
    composite = next(e for e in d["expected"] if e["form"] == "1099 (composite)")
    assert composite["document"]["fileName"] == "w2.pdf"
    assert [x["form"] for x in d["received"]] == ["W-2"]
    bad = make(jane, "TxDoc", bookId=last["id"], direction="filed", form="Reply")
    assert bad.json()["errors"][0]["field"] == "filingId"
    # Next year expects last year's W-2 again.
    now = book(jane, 2026, [a_id])
    d = jane.get(f"/ui/api/tax-books/{now['id']}").json()
    w2 = [e for e in d["expected"] if e["form"] == "W-2"]
    assert [(e["issuer"], e["why"], e["document"]) for e in w2] == [
        ("Acme Corp", "Received in 2025", None)
    ]


def test_a_preparer_helps_but_cannot_delete(server, couple):
    jane, _, a_id, _ = couple
    make_user(server, "dave")
    dave = sign_in(server, "dave")
    d_id = dave.get("/ui/api/session").json()["user"]["id"]
    b = book(jane, 2026, [a_id])
    r = share(jane, "tax-book", b["id"], users={d_id: "write"})
    assert r.status_code == 200, r.text
    assert make(dave, "Filng", bookId=b["id"]).status_code == 200
    assert remove(dave, "TaxBk", b).status_code == 403


# ---- Dependents (S8.14.5) ----


def person(c, name, sex="female", **kw):
    r = make(c, "Persn", **{"name": name, "sex": sex, **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def child_of(c, parent, kid):
    r = make(c, "Rltn", person1Id=parent, person2Id=kid, relation="child")
    assert r.status_code == 200, r.text


def dependent(c, book_id, person_id, **kw):
    return make(c, "TxDep", **{"bookId": book_id, "personId": person_id, **kw})


def test_a_couple_is_named_by_sex_then_name_whoever_made_the_book(server, frozen):
    # S10.10.7: by (sex, name), men first; with the sex the same, the name decides.
    for a, b, sex in (("zoe", "ann", "female"), ("max", "ben", "male")):
        make_user(server, a, sex=sex)
        make_user(server, b, sex=sex)
        first, second = sign_in(server, a), sign_in(server, b)
        pa = first.get("/ui/api/profile").json()["personId"]
        pb = second.get("/ui/api/profile").json()["personId"]
        r = make(first, "Rltn", person1Id=pa, person2Id=pb, relation="spouse")
        assert r.status_code == 200, r.text
        assert second.post(f"/ui/api/relationships/{r.json()['id']}/confirm").status_code == 200
        b_id = second.get("/ui/api/session").json()["user"]["id"]
        made = book(first, 2026, [first.get("/ui/api/session").json()["user"]["id"], b_id])
        assert made["label"] == f"2026 · {b.title()} & {a.title()} (joint)", made["label"]


def test_dependents_are_suggested_from_the_family_tree_and_aged_on_dec_31(server, couple):
    jane, _, a_id, _ = couple
    pa = jane.get("/ui/api/profile").json()["personId"]
    bart = person(jane, "Bart Doe", "male", birthYear=2012, birthMonth=11, birthDay=30)
    lisa = person(jane, "Lisa Doe", birthYear=2018)
    sam = person(jane, "Sam Doe", "male", birthYear=2006)
    gran = person(jane, "Candace Doe", birthYear=1950)
    for kid in (bart, lisa, sam):
        child_of(jane, pa, kid)
    b = book(jane, 2026, [a_id])
    items = jane.get(f"/ui/api/tax-books/{b['id']}/dependent-candidates").json()["items"]
    cands = {x["name"]: x for x in items}
    # The children first, oldest first (S10.10.7).
    assert [x["name"] for x in items[:3]] == ["Sam Doe", "Bart Doe", "Lisa Doe"]
    assert "Jane" not in cands  # a filer isn't their own dependent
    assert cands["Bart Doe"]["relation"] == "son"
    assert cands["Bart Doe"]["age"] == 14
    assert cands["Bart Doe"]["suggest"] == "qualifying child"
    # Sam is 20: a qualifying child only as a student.
    assert (cands["Sam Doe"]["suggest"], cands["Sam Doe"]["suggestIfStudent"]) == (
        "qualifying relative",
        "qualifying child",
    )
    assert cands["Candace Doe"]["suggest"] == "qualifying relative"

    # Added youngest first, they are listed oldest first.
    r = dependent(jane, b["id"], lisa)
    assert r.status_code == 200, r.text
    r = dependent(jane, b["id"], bart, student=True)
    d = {x["name"]: x for x in r.parent()["dependents"]}
    assert d["Bart Doe"]["age"] == 14 and d["Bart Doe"]["under17"]
    assert not d["Bart Doe"]["under13"]
    assert d["Lisa Doe"]["under13"] and d["Lisa Doe"]["agesOut"] == []
    assert dependent(jane, b["id"], gran, claimedAs="qualifying relative").status_code == 200
    assert dependent(jane, b["id"], bart).json()["errors"][0]["code"] == "dependent-twice"
    assert dependent(jane, b["id"], pa).json()["errors"][0]["code"] == "dependent-filer"
    assert dependent(jane, b["id"], lisa, months=13).json()["errors"][0]["code"] == "months-invalid"

    # Their documents: a student's 1098-T is expected.
    detail = jane.get(f"/ui/api/tax-books/{b['id']}").json()
    assert any(e["form"] == "1098-T" and "Bart" in e["why"] for e in detail["expected"])
    p = jane.get(f"/ui/api/tax-books/{b['id']}/panels").json()
    # The children oldest first, then anyone else by name (S10.10.7).
    assert [x["name"] for x in p["dependents"]] == ["Bart Doe", "Lisa Doe", "Candace Doe"]
    assert p["students"] == [{"name": "Bart Doe", "received1098T": False, "withdrawals529": 0}]

    # Changing and removing one.
    dep = next(x for x in detail["dependents"] if x["name"] == "Lisa Doe")
    dep = saved(change(jane, "TxDep", dep, months=6))
    assert dep["months"] == 6
    assert remove(jane, "TxDep", dep).status_code == 200
    after = jane.get(f"/ui/api/tax-books/{b['id']}").json()["dependents"]
    assert "Lisa Doe" not in {x["name"] for x in after}


def test_a_person_claimed_on_two_books_is_flagged_on_both(server, couple):
    jane, john, a_id, b_id = couple
    kid = person(jane, "Bart Doe", "male", birthYear=2012)
    mine = book(jane, 2026, [a_id])
    theirs = book(john, 2026, [b_id])
    assert dependent(jane, mine["id"], kid).status_code == 200
    r = dependent(john, theirs["id"], kid)
    assert r.parent()["dependents"][0]["claimedElsewhere"]
    d = jane.get(f"/ui/api/tax-books/{mine['id']}").json()
    assert d["dependents"][0]["claimedElsewhere"]
    issues = jane.get(f"/ui/api/tax-books/{mine['id']}/panels").json()["issues"]
    assert "Bart Doe is claimed on another 2026 tax book too" in [i["text"] for i in issues]
    # A dependent's own book notes that they are claimed on another.
    pb = john.get("/ui/api/profile").json()["personId"]
    assert dependent(jane, mine["id"], pb, claimedAs="qualifying relative").status_code == 200
    d = john.get(f"/ui/api/tax-books/{theirs['id']}").json()
    assert d["claimedElsewhere"] == ["John"]


def test_a_dependent_childs_unearned_income_past_the_threshold_is_flagged(server, couple):
    jane, _, a_id, _ = couple
    kid = person(jane, "Bart Doe", "male", birthYear=2012)
    utma = new_account(jane, name="Bart's UTMA", type="brokerage")
    add(jane, utma["id"], "1900.00", day="2026-03-02", kind="dividend")
    add(jane, utma["id"], "1010.00", day="2026-06-02", kind="interest")
    b = book(jane, 2026, [a_id])
    r = dependent(jane, b["id"], kid, accountIds=["Acct_00000000000000000000000000"])
    assert r.json()["errors"][0]["code"] == "account-not-counted"
    r = dependent(jane, b["id"], kid, accountIds=[utma["id"]])
    assert r.status_code == 200, r.text
    f = r.parent()["form8615"]
    assert f == [
        {"name": "Bart Doe", "unearned": 2910, "threshold": 2700, "accounts": ["Bart's UTMA"]}
    ]
    issues = jane.get(f"/ui/api/tax-books/{b['id']}/panels").json()["issues"]
    assert any(i["kind"] == "form-8615" for i in issues)


def test_next_years_book_copies_dependents_a_year_older(server, couple):
    jane, _, a_id, _ = couple
    bart = person(jane, "Bart Doe", "male", birthYear=2012)
    sam = person(jane, "Sam Doe", "male", birthYear=2007)  # 19 in 2026
    ruth = person(jane, "Ruth Doe", birthYear=2003)
    old = book(jane, 2025, [a_id])
    assert dependent(jane, old["id"], bart).status_code == 200
    assert dependent(jane, old["id"], sam).status_code == 200
    assert dependent(jane, old["id"], ruth, claimedAs="qualifying relative").status_code == 200
    new = book(jane, 2026, [a_id])
    assert new["dependentsLeftOut"] == ["Sam Doe"]
    d = jane.get(f"/ui/api/tax-books/{new['id']}").json()
    ages = {x["name"]: x["age"] for x in d["dependents"]}
    assert ages == {"Bart Doe": 14, "Ruth Doe": 23}


def test_last_years_book_waits_for_every_filer_and_an_added_account_for_its_adder(server, couple):
    """S8.14.1, S8.14.2, S8.14.4 (P1): a book naming John shows nothing of his year before, and
    copies nothing from it, until he accepts; an account he added counts while he sees it."""
    jane, john, a_id, b_id = couple
    kid = new_account(jane, name="Lisa's custodial", type="brokerage")
    share(jane, "account", kid["id"], users={b_id: "read"})
    last = book(john, 2025, [b_id])
    r = create(john, "TxBkA", bookId=last["id"], accountId=kid["id"], counted=True)
    assert [a["name"] for a in saved(r)["accounts"]] == ["Lisa's custodial"]
    # Jane names John; until he accepts, the book has nothing of his 2025.
    joint = book(jane, 2026, [a_id, b_id], fromLastYear=True)
    from moolakata.store.entities.taxes import TaxBook, TaxBookAccount

    with server.db.read(unscoped="test") as s:
        assert s.query(TaxBookAccount).filter_by(bookId=joint["id"]).count() == 0
        assert s.get(TaxBook, joint["id"]).copyPending
    assert john.post(f"/ui/api/tax-books/{joint['id']}/accept").status_code == 200
    with server.db.read(unscoped="test") as s:
        copied = s.query(TaxBookAccount).filter_by(bookId=joint["id"]).one()
        assert copied.accountId == kid["id"] and copied.addedById == b_id
        assert not s.get(TaxBook, joint["id"]).copyPending
    # John's added account counts in his own 2025 book only while he can see it.
    share(jane, "account", kid["id"], users={b_id: "none"})
    d = john.get(f"/ui/api/tax-books/{last['id']}").json()
    assert "Lisa's custodial" not in [a["name"] for a in d["accounts"]]


def test_a_helper_edits_but_never_changes_what_the_book_counts(server, couple):
    """S8.14.3 (P7): write lets a helper edit filings, not add accounts; any filer shares it."""
    jane, john, a_id, b_id = couple
    make_user(server, "gail")
    gail = sign_in(server, "gail")
    g_id = gail.get("/ui/api/session").json()["user"]["id"]
    acct = new_account(gail, name="Gail's", type="brokerage")
    b = book(jane, 2026, [a_id, b_id])
    john.post(f"/ui/api/tax-books/{b['id']}/accept")
    # John, a filer who didn't make it, changes its sharing.
    r = share(john, "tax-book", b["id"], users={g_id: "write"})
    assert r.status_code == 200, r.text
    r = create(gail, "TxBkA", bookId=b["id"], accountId=acct["id"], counted=True)
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "filers-only"
    r = make(gail, "Filng", bookId=b["id"], form="Form 1040")
    assert r.status_code == 200, r.text


def test_a_due_date_skips_weekends_and_legal_holidays():
    # B22: Emancipation Day (April 16, as observed) moves the return's due date, as in 2017,
    # 2018, 2022 and 2023.
    import datetime as dt

    from moolakata.taxes.dates import next_business_day

    got = [next_business_day(dt.date(y, 4, 15)) for y in (2017, 2018, 2022, 2023, 2026)]
    assert got == [
        dt.date(2017, 4, 18),
        dt.date(2018, 4, 17),
        dt.date(2022, 4, 18),
        dt.date(2023, 4, 18),
        dt.date(2026, 4, 15),
    ]


def test_an_edit_that_moves_a_filed_years_gains_asks_first(server, couple):
    # N5: once 2025's federal return is filed, an edit that changes 2025's realized gains is
    # refused, naming the year, until confirmed.
    from test_accounts import add, new_account

    jane = couple[0]
    brk = new_account(jane, name="Brokerage", type="brokerage")
    add(jane, brk["id"], "10000.00", "2024-01-02", kind="deposit")
    add(
        jane,
        brk["id"],
        "-1000.00",
        "2024-01-05",
        kind="buy",
        symbol="VTI",
        quantity="10",
        price="100",
    )
    sale = add(
        jane,
        brk["id"],
        "1500.00",
        "2025-03-03",
        kind="sell",
        symbol="VTI",
        quantity="10",
        price="150",
    )
    me = jane.get("/ui/api/session").json()["user"]["id"]
    book = make(jane, "TaxBk", year=2025, filers=[me]).json()
    r = make(
        jane,
        "Filng",
        bookId=book["id"],
        jurisdiction="federal",
        form="1040",
        progress="filed",
        filedOn="2026-04-10",
    )
    assert r.status_code == 200, r.text
    r = change(jane, "Txn", sale, amount="1600.00")
    assert asked(r) == ["closed-year"]
    assert "gains of 2025" in r.json()["asks"][0]["message"]
    sale = saved(change(jane, "Txn", sale, confirm=True, amount="1600.00"))
    # A memo isn't a gain: no question asked.
    saved(change(jane, "Txn", sale, memo="sold to rebalance"))


def test_an_edit_made_anyway_stays_on_the_book_until_amended_or_waved(server, couple):
    # S2.8.3, S8.15: an edit made anyway is listed on the book and in Needs attention; an
    # amended federal return settles it and opens the year while it's prepared; filing it
    # closes the year again; No amendment needed settles what follows.
    from test_accounts import add, new_account

    jane = couple[0]
    brk = new_account(jane, name="Brokerage", type="brokerage")
    add(jane, brk["id"], "10000.00", "2024-01-02", kind="deposit")
    add(jane, brk["id"], "-1000.00", "2024-01-05", kind="buy", symbol="VTI", quantity="10",
        price="100")  # fmt: skip
    sale = add(jane, brk["id"], "1500.00", "2025-03-03", kind="sell", symbol="VTI",
               quantity="10", price="150")  # fmt: skip
    me = jane.get("/ui/api/session").json()["user"]["id"]
    b = make(jane, "TaxBk", year=2025, filers=[me]).json()
    federal = {"jurisdiction": "federal", "form": "1040", "progress": "filed"}
    r = make(jane, "Filng", **{"bookId": b["id"], **federal, "filedOn": "2026-04-10"})
    original = next(f for f in r.parent()["filings"] if f["form"] == "1040")

    def issues():
        p = jane.get(f"/ui/api/tax-books/{b['id']}/panels").json()
        return [i["text"] for i in p["issues"] if i["kind"] == "changed-after-filing"]

    def attention():
        d = jane.get("/ui/api/dashboard").json()
        return [a["text"] for a in d["attention"] if a["kind"] == "changed-after-filing"]

    def edit(amount, confirm):
        nonlocal sale
        r = change(jane, "Txn", sale, confirm=confirm, amount=amount)
        if r.status_code == 200:
            sale = saved(r)
        return r

    assert issues() == [] and attention() == []
    assert edit("1600.00", confirm=True).status_code == 200
    assert edit("1650.00", confirm=True).status_code == 200
    assert issues() == [
        "Realized gains changed by +$150.00 after the federal return was filed: Brokerage, 2 edits"
    ]
    assert attention() == ["2025's realized gains changed after the federal return was filed"]
    # An amended return, being prepared: the changes are settled and the year is open.
    r = make(
        jane,
        "Filng",
        **{
            "bookId": b["id"],
            **federal,
            "form": "1040-X",
            "progress": "in progress",
            "amendsId": original["id"],
        },
    )
    assert r.status_code == 200, r.text
    amended = next(f for f in r.parent()["filings"] if f["form"] == "1040-X")
    assert issues() == [] and attention() == []
    assert edit("1700.00", confirm=False).status_code == 200
    assert issues() == []
    # Filed: the year is closed again, and an edit made anyway is listed afresh.
    saved(change(jane, "Filng", amended, progress="filed", filedOn="2026-06-20"))
    r = edit("1690.00", confirm=False)
    assert asked(r) == ["closed-year"]
    assert edit("1690.00", confirm=True).status_code == 200
    assert issues() == [
        "Realized gains changed by -$10.00 after the federal return was filed: Brokerage, 1 edit"
    ]
    # The amended return accepted later settles nothing it never had in (CR3-35).
    filings = jane.get(f"/ui/api/tax-books/{b['id']}").json()["filings"]
    amended = next(f for f in filings if f["form"] == "1040-X")
    saved(change(jane, "Filng", amended, progress="accepted", confirmation="X-2026-0611"))
    assert len(issues()) == 1, "the edit made after the 1040-X was filed is still listed"
    # No amendment needed settles it, for those who may write.
    r = couple[1].post(f"/ui/api/tax-books/{b['id']}/no-amendment")
    assert r.status_code in (403, 404), r.text
    r = jane.post(f"/ui/api/tax-books/{b['id']}/no-amendment")
    assert r.status_code == 200, r.text
    assert [i for i in r.json()["issues"] if i["kind"] == "changed-after-filing"] == []
    assert issues() == [] and attention() == []


def test_a_tax_documents_file_opens_for_the_books_filers(server, couple):
    # N13: a co-filer opens the file through the book; it isn't in the uploader's Inbox, and
    # can't be deleted while the document keeps it.
    jane, john, a_id, b_id = couple
    b = book(jane, 2026, [a_id, b_id])
    john.post(f"/ui/api/tax-books/{b['id']}/accept")
    up = jane.post(
        "/ui/api/receipts", files={"file": ("w2.pdf", b"%PDF-1.4 w2", "application/pdf")}
    ).json()
    r = make(jane, "TxDoc", bookId=b["id"], form="W-2", issuer="Acme Corp", receiptId=up["id"])
    assert r.status_code == 200, r.text
    assert john.get(f"/ui/api/receipts/{up['id']}/file").status_code == 200
    got = jane.get(f"/ui/api/receipts/{up['id']}").json()
    assert [(x["kind"], x["label"]) for x in got["links"]] == [
        ("tax-document", "W-2 in the 2026 tax book")
    ]
    assert jane.get("/ui/api/receipts", params={"show": "inbox"}).json()["items"] == []
    assert remove(jane, "Rcpt", got).status_code == 409


def test_a_document_changed_removed_and_given_its_file_by_a_co_filer(couple):
    """CR3-36: a document's form, notes and file change, and it goes, through the save; a
    co-filer changes one the other filer attached a file to, the file left as it was."""
    jane, john, a_id, b_id = couple
    b = book(jane, 2026, [a_id, b_id])
    assert john.post(f"/ui/api/tax-books/{b['id']}/accept").status_code == 200
    up = jane.post(
        "/ui/api/receipts", files={"file": ("w2.pdf", b"%PDF-1.4 w2", "application/pdf")}
    ).json()
    d = make(
        jane, "TxDoc", bookId=b["id"], form="1099-INT", issuer="Acme Corp", receiptId=up["id"]
    ).parent()
    (doc,) = d["received"]
    doc = saved(change(jane, "TxDoc", doc, form="W-2"))
    assert doc["form"] == "W-2" and doc["receiptId"] == up["id"]
    doc = saved(change(john, "TxDoc", doc, notes="corrected copy expected"))
    assert doc["notes"] == "corrected copy expected"
    kept = make(jane, "TxDoc", bookId=b["id"], form="1098", issuer="Rocket").parent()
    later = next(x for x in kept["received"] if x["form"] == "1098")
    pdf = jane.post(
        "/ui/api/receipts", files={"file": ("1098.pdf", b"%PDF-1.4 1098", "application/pdf")}
    ).json()
    assert saved(change(jane, "TxDoc", later, receiptId=pdf["id"]))["fileName"] == "1098.pdf"
    assert remove(jane, "TxDoc", doc).status_code == 200
    left = jane.get(f"/ui/api/tax-books/{b['id']}").json()["received"]
    assert [x["form"] for x in left] == ["1098"]


def test_a_childs_reinvested_dividends_and_gains_count_toward_form_8615(server, couple):
    # CR3-392's sibling: a child's reinvested dividend is unearned income, typed or not, and so
    # is a gain sold in their account; a dependent's accounts change as the book's draft says.
    jane, _, a_id, _ = couple
    kid = person(jane, "Bart Doe", "male", birthYear=2012)
    utma = new_account(jane, name="Bart's UTMA", type="brokerage")
    other = new_account(jane, name="Bart's savings", type="savings")
    add(jane, utma["id"], "-1500.00", day="2026-03-31", kind="reinvest", symbol="SCHD",
        quantity="10", price="150")  # fmt: skip
    add(jane, utma["id"], "-1000.00", day="2025-01-06", kind="buy", symbol="IBM",
        quantity="10", price="100")  # fmt: skip
    add(jane, utma["id"], "1400.00", day="2026-05-04", kind="sell", symbol="IBM",
        quantity="10", price="140")  # fmt: skip
    b = book(jane, 2026, [a_id])
    r = dependent(jane, b["id"], kid, accountIds=[utma["id"], other["id"]])
    assert r.status_code == 200, r.text
    assert r.parent()["form8615"] == [], "1,500 reinvested and a 400 gain: under 2,700"
    add(jane, utma["id"], "-900.00", day="2026-06-30", kind="reinvest", symbol="SCHD",
        quantity="6", price="150")  # fmt: skip
    (f,) = jane.get(f"/ui/api/tax-books/{b['id']}").json()["form8615"]
    assert f["unearned"] == 2800 and sorted(f["accounts"]) == ["Bart's UTMA", "Bart's savings"]
    # The savings account taken off, then given back: kept as one row.
    d = jane.get(f"/ui/api/tax-books/{b['id']}").json()["dependents"][0]
    rec = {"id": d["id"], "version": d["version"]}
    d = saved(change(jane, "TxDep", rec, accountIds=[utma["id"]]))
    d = saved(change(jane, "TxDep", d, accountIds=[utma["id"], other["id"]]))
    got = jane.get(f"/ui/api/tax-books/{b['id']}").json()["dependents"][0]
    assert sorted(got["accountIds"]) == sorted([utma["id"], other["id"]])


def test_childcare_paid_in_a_split_expects_the_providers_statement(server, couple):
    # S8.14.5.3: childcare paid for a dependent under 13 expects the provider's statement,
    # paid as a part of a transaction too.
    jane, _, a_id, _ = couple
    kid = person(jane, "Bart Doe", "male", birthYear=2018)
    checking = new_account(jane, name="Checking")
    cats = {x["path"]: x["id"] for x in jane.get("/ui/api/categories").json()["items"]}
    care = next(v for k, v in cats.items() if k.endswith("Childcare"))
    food = cats["Food › Groceries"]
    add(jane, checking["id"], "-300.00", day="2026-04-01", payee="Little Learners",
        splits=[{"categoryId": care, "amount": "-200.00"},
                {"categoryId": food, "amount": "-100.00"}])  # fmt: skip
    b = book(jane, 2026, [a_id])
    assert dependent(jane, b["id"], kid).status_code == 200
    exp = jane.get(f"/ui/api/tax-books/{b['id']}").json()["expected"]
    assert any(e["form"] == "Childcare provider statement" for e in exp), exp


def test_a_tax_documents_file_goes_with_the_book_to_its_helpers(server, couple):
    """CR3-9, CR3-74: a preparer the book is shared with at write opens the W-2 a filer
    attached, as a read share does; a stranger still can't."""
    from edits import share

    jane, _john, a_id, _b_id = couple
    make_user(server, "dave")
    make_user(server, "erin")
    make_user(server, "mallory")
    dave, erin, mallory = (sign_in(server, u) for u in ("dave", "erin", "mallory"))
    uid = {n: c.get("/ui/api/session").json()["user"]["id"]
           for n, c in (("dave", dave), ("erin", erin))}  # fmt: skip
    b = book(jane, 2026, [a_id])
    up = jane.post(
        "/ui/api/receipts", files={"file": ("w2.pdf", b"%PDF-1.4 w2", "application/pdf")}
    ).json()
    r = make(jane, "TxDoc", bookId=b["id"], form="W-2", issuer="Acme Corp", receiptId=up["id"])
    assert r.status_code == 200, r.text
    assert share(jane, "tax-book", b["id"], users={uid["dave"]: "write"}).status_code == 200
    assert share(jane, "tax-book", b["id"], users={uid["erin"]: "read"}).status_code == 200
    assert dave.get(f"/ui/api/receipts/{up['id']}/file").status_code == 200
    assert erin.get(f"/ui/api/receipts/{up['id']}/file").status_code == 200
    assert mallory.get(f"/ui/api/receipts/{up['id']}/file").status_code == 404
