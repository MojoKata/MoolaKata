"""Every refusal of a tax book's records, through the save (requirements S8.14–S8.16): each field a
book, a filing, an estimated payment or a dependent checks, sent wrong, answered with its own code
and nothing saved.
"""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id, remove, saved, share

from moolakata import clock

T0 = dt.datetime(2026, 3, 2, 15, 0, tzinfo=dt.UTC)
UNKNOWN_TXN = "Txn_" + "0" * 26
UNKNOWN_FILING = "Filng_" + "0" * 26

FEDERAL = {"jurisdiction": "federal", "form": "1040", "progress": "in progress"}

FILINGS = [
    ({"jurisdiction": "city"}, "invalid-literal-error"),  # the model refuses it first
    ({"jurisdiction": "state", "place": ""}, "place-missing"),
    ({"form": " "}, "form-missing"),
    ({"progress": "done"}, "progress-invalid"),
    ({"filingStatus": "Happily"}, "status-invalid"),
    ({"sentBy": "fax"}, "sent-invalid"),
    ({"resultKind": "windfall"}, "result-invalid"),
    ({"progress": "filed"}, "filed-on-missing"),
    ({"payments": [{"quarter": 5, "amount": "100"}]}, "quarter-invalid"),
    ({"payments": [{"quarter": 1, "amount": "-1"}]}, "amount-invalid"),
    ({"amendsId": UNKNOWN_FILING}, "filing-unknown"),
    ({"resultTransactionId": UNKNOWN_TXN}, "not-found"),
]
BOOKS = [
    ({"year": 1990}, "year-invalid"),
    ({"filers": "nobody"}, "filers-invalid"),
]


@pytest.fixture
def jane(server):
    clock.fix(T0)
    try:
        make_user(server, "jane")
        yield sign_in(server, "jane")
    finally:
        clock.fix(None)


def _me(c) -> str:
    return c.get("/ui/api/session").json()["user"]["id"]


def _book(c) -> dict:
    r = make(c, "TaxBk", year=2025, filers=[_me(c)])
    assert r.status_code == 200, r.text
    return r.json()


def _refused(r, code: str) -> None:
    assert r.status_code in (403, 404, 409, 422), r.text
    body = r.json()
    codes = [e["code"] for e in body.get("errors", [])] or [body.get("code")]
    assert code in codes, body


@pytest.mark.parametrize(("fields", "code"), FILINGS, ids=[c for _, c in FILINGS])
def test_a_filing_refuses_each_wrong_field(jane, fields, code):
    b = _book(jane)
    _refused(make(jane, "Filng", bookId=b["id"], **{**FEDERAL, **fields}), code)
    assert jane.get(f"/ui/api/tax-books/{b['id']}").json()["filings"] == []


@pytest.mark.parametrize(("fields", "code"), BOOKS, ids=[c for _, c in BOOKS])
def test_a_book_refuses_each_wrong_field(jane, fields, code):
    if fields.get("filers") == "nobody":
        other = new_id("User")
        fields = {"filers": [other]}
    _refused(make(jane, "TaxBk", **{"year": 2025, "filers": [_me(jane)], **fields}), code)


def test_a_book_keeps_its_year_and_a_carryover_share_is_never_negative(jane):
    b = _book(jane)
    got = jane.get(f"/ui/api/tax-books/{b['id']}").json()
    record = {"id": b["id"], "version": got["version"]}
    _refused(change(jane, "TaxBk", record, year=2024), "book-fixed")
    _refused(change(jane, "TaxBk", record, carryoverShareShort="-5.00"), "amount-invalid")


def test_a_filing_stays_in_its_book_and_never_amends_itself(jane):
    b = _book(jane)
    r = make(jane, "Filng", bookId=b["id"], **FEDERAL)
    f = next(x for x in r.parent()["filings"])
    record = {"id": f["id"], "version": f["version"]}
    _refused(change(jane, "Filng", record, amendsId=f["id"]), "amends-itself")
    other = make(jane, "TaxBk", year=2026, filers=[_me(jane)]).json()
    _refused(change(jane, "Filng", record, bookId=other["id"]), "filing-fixed")


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"quarter": 0}, "quarter-invalid"),
        ({"amount": "-1"}, "amount-invalid"),
        ({"transactionId": UNKNOWN_TXN}, "not-found"),
    ],
    ids=["quarter", "amount", "transaction"],
)
def test_an_estimated_payment_refuses_each_wrong_field(jane, fields, code):
    b = _book(jane)
    r = make(jane, "Filng", bookId=b["id"], **FEDERAL)
    f = next(x for x in r.parent()["filings"])
    body = {"filingId": f["id"], "quarter": 1, "amount": "100", **fields}
    _refused(make(jane, "EstPy", **body), code)


def test_a_dependent_is_claimed_as_a_child_or_a_relative(jane):
    b = _book(jane)
    kid = make(jane, "Persn", name="Lisa", sex="female", birthYear=2015).json()["id"]
    _refused(make(jane, "TxDep", bookId=b["id"], personId=kid, claimedAs="cousin", months=12),
             "claimed-as-invalid")  # fmt: skip


# ---------- each refusal at its field, with its code and words ----------


def _said(r, field, code: str, words: str, status: int = 422) -> None:
    """Refused with `status`, at `field` (None: the record's), with its code and words."""
    assert r.status_code == status, r.text
    body = r.json()
    got = body.get("errors") or [{"field": body.get("field"), "code": body["code"],
                                  "message": body["message"]}]  # fmt: skip
    assert (got[0].get("field"), got[0]["code"], got[0]["message"]) == (field, code, words)


def _unknown(prefix: str) -> dict:
    return {"id": new_id(prefix), "version": 1}


@pytest.mark.parametrize(
    "where",
    [{}, {"jurisdiction": "state", "place": "Utah"}, {"jurisdiction": "local", "place": "NYC"}],
    ids=["federal", "state", "local"],
)
def test_an_original_return_needs_its_due_date(jane, where):
    """R3.11, S8.15.3: a blank due date is refused, never read as the tax tables' date; a
    federal filing's field offers that date as its default."""
    b = _book(jane)
    body = {"bookId": b["id"], "form": "1040", "dueDate": None, **where}
    _said(make(jane, "Filng", **body), "dueDate", "due-date-missing", "The due date.")
    assert jane.get(f"/ui/api/tax-books/{b['id']}").json()["federalDue"] == "2026-04-15"


def test_an_amended_return_keeps_no_due_date(jane):
    b = _book(jane)
    r = make(jane, "Filng", bookId=b["id"], form="1040", dueDate="2026-04-15")
    (f,) = r.parent()["filings"]
    r = make(jane, "Filng", bookId=b["id"], form="1040-X", amendsId=f["id"])
    assert r.status_code == 200, r.text
    amended = [x for x in r.parent()["filings"] if x["id"] != f["id"]]
    assert amended[0]["dueDate"] is None


def test_a_book_has_one_filer_or_two(jane):
    filers = [_me(jane), new_id("User"), new_id("User")]
    _said(make(jane, "TaxBk", year=2025, filers=filers), "filers", "filers-invalid",
          "One filer, or two who are married.")  # fmt: skip


def test_only_a_named_filer_accepts_or_declines(server, jane):
    """S8.14.1: a book that doesn't name you, or names you and you accepted, is not found."""
    b = _book(jane)
    assert jane.post(f"/ui/api/tax-books/{new_id('TaxBk')}/accept").status_code == 404
    assert jane.post(f"/ui/api/tax-books/{b['id']}/decline").status_code == 404  # accepted
    # Accepted already, accepting again changes nothing.
    assert jane.post(f"/ui/api/tax-books/{b['id']}/accept").json()["id"] == b["id"]
    make_user(server, "bart")
    bart = sign_in(server, "bart")
    for how in ("accept", "decline"):
        r = bart.post(f"/ui/api/tax-books/{b['id']}/{how}")
        assert (r.status_code, r.json()["code"]) == (404, "not-found")


def test_only_its_filers_add_an_account_and_each_once(server, jane):
    """S8.14.2, S8.14.3: a helper with write changes filings, never what the book counts; an
    account already in the book is changed, not added again; a change keeps its book and
    account, and an unknown one is not found."""
    b = _book(jane)
    acct = make(jane, "Acct", name="Brokerage", type="brokerage").json()
    make_user(server, "dave")
    dave = sign_in(server, "dave")
    assert share(jane, "tax-book", b["id"], users={_me(dave): "write"}).status_code == 200
    share(jane, "account", acct["id"], users={_me(dave): "read"})
    _said(make(dave, "TxBkA", bookId=b["id"], accountId=acct["id"], counted=False), "bookId",
          "filers-only", "Only its filers add or leave out accounts.", 403)  # fmt: skip
    assert (
        make(jane, "TxBkA", bookId=b["id"], accountId=acct["id"], counted=False).status_code == 200
    )
    _said(make(jane, "TxBkA", bookId=b["id"], accountId=acct["id"], counted=True), "accountId",
          "account-in-book", "It is in the book: change it.", 409)  # fmt: skip
    d = jane.get(f"/ui/api/tax-books/{b['id']}").json()
    (left,) = d["leftOut"]
    record = {"id": left["rowId"], "version": left["rowVersion"]}
    other = make(jane, "Acct", name="Checking", type="checking").json()
    _said(change(jane, "TxBkA", record, accountId=other["id"]), "accountId", "account-fixed",
          "It stays with its book and account.")  # fmt: skip
    assert change(jane, "TxBkA", _unknown("TxBkA"), counted=True).status_code == 404
    _said(change(dave, "TxBkA", record, counted=True), None, "filers-only",
          "Only its filers add or leave out accounts.", 403)  # fmt: skip
    assert saved(change(jane, "TxBkA", record, counted=True))
    d = jane.get(f"/ui/api/tax-books/{b['id']}").json()
    assert d["leftOut"] == [] and "Brokerage" in [a["name"] for a in d["accounts"]]


def test_a_dependent_is_one_of_the_households_people_and_stays_in_its_book(jane):
    b = _book(jane)
    _said(make(jane, "TxDep", bookId=b["id"], personId=new_id("Persn"),
               claimedAs="qualifying child", months=12), "personId", "person-unknown",
          "One of the household's people.")  # fmt: skip
    kid = make(jane, "Persn", name="Lisa", sex="female", birthYear=2015).json()["id"]
    r = make(jane, "TxDep", bookId=b["id"], personId=kid, claimedAs="qualifying child",
             months=12)  # fmt: skip
    assert r.status_code == 200, r.text
    (dep,) = jane.get(f"/ui/api/tax-books/{b['id']}").json()["dependents"]
    record = {"id": dep["id"], "version": dep["version"]}
    other = make(jane, "TaxBk", year=2026, filers=[_me(jane)]).json()
    _said(change(jane, "TxDep", record, bookId=other["id"]), "bookId", "dependent-fixed",
          "A dependent stays in their book.")  # fmt: skip
    assert change(jane, "TxDep", _unknown("TxDep"), months=6).status_code == 404


def test_a_filers_8606_basis_is_zero_or_more_and_an_unknown_filing_is_not_found(jane):
    b = _book(jane)
    _said(make(jane, "Filng", bookId=b["id"], **FEDERAL,
               carried={"basis8606": {_me(jane): "-5"}}), "carried.basis8606",
          "amount-invalid", "Zero or more.")  # fmt: skip
    assert change(jane, "Filng", _unknown("Filng"), form="1040").status_code == 404


def test_a_filing_deleted_takes_its_payments_with_it(jane):
    b = _book(jane)
    r = make(jane, "Filng", bookId=b["id"], **FEDERAL,
             payments=[{"quarter": 1, "amount": "100"}])  # fmt: skip
    (f,) = r.parent()["filings"]
    assert remove(jane, "Filng", f).status_code == 200
    assert jane.get(f"/ui/api/tax-books/{b['id']}").json()["filings"] == []


def test_a_payment_stays_with_its_filing(jane):
    b = _book(jane)
    one = make(jane, "Filng", bookId=b["id"], **FEDERAL,
               payments=[{"quarter": 1, "amount": "100"}])  # fmt: skip
    (f,) = one.parent()["filings"]
    (p,) = f["payments"]
    two = make(
        jane,
        "Filng",
        bookId=b["id"],
        jurisdiction="state",
        place="Utah",
        form="TC-40",
        dueDate="2026-04-15",
    )
    other = next(x for x in two.parent()["filings"] if x["id"] != f["id"])
    record = {"id": p["id"], "version": p["version"]}
    _said(change(jane, "EstPy", record, filingId=other["id"]), "filingId", "payment-fixed",
          "A payment stays with its filing.")  # fmt: skip
    assert change(jane, "EstPy", _unknown("EstPy"), amount="5").status_code == 404
    assert saved(change(jane, "EstPy", record, amount="250"))
    (f,) = [x for x in jane.get(f"/ui/api/tax-books/{b['id']}").json()["filings"]
            if x["id"] == f["id"]]  # fmt: skip
    assert f["payments"][0]["amount"] == "250.00"


@pytest.mark.parametrize(
    ("fields", "field", "code", "words"),
    [
        ({"direction": "sent"}, "direction", "direction-invalid", "Received or filed."),
        ({"form": " "}, "form", "form-missing", "Which document."),
        ({"direction": "filed", "filingId": UNKNOWN_FILING}, "filingId", "filing-unknown",
         "One of this book's filings."),
    ],
    ids=["direction", "form", "filing"],
)  # fmt: skip
def test_a_tax_document_refuses_each_wrong_field(jane, fields, field, code, words):
    b = _book(jane)
    body = {"bookId": b["id"], "direction": "received", "form": "W-2", **fields}
    _said(make(jane, "TxDoc", **body), field, code, words)


def test_a_tax_document_stays_in_its_book(jane):
    b = _book(jane)
    r = make(jane, "TxDoc", bookId=b["id"], direction="received", form="W-2")
    assert r.status_code == 200, r.text
    (doc,) = jane.get(f"/ui/api/tax-books/{b['id']}").json()["received"]
    record = {"id": doc["id"], "version": doc["version"]}
    other = make(jane, "TaxBk", year=2026, filers=[_me(jane)]).json()
    _said(change(jane, "TxDoc", record, bookId=other["id"]), "bookId", "document-fixed",
          "A document stays in its book.")  # fmt: skip
    assert change(jane, "TxDoc", _unknown("TxDoc"), form="W-2").status_code == 404
