"""Every refusal of a tax book's records, through the save (requirements S8.14–S8.16; the filed
tax years walk, decision 3.7): each field a book, a filing, an estimated payment or a
dependent checks, sent wrong, answered with its own code and nothing saved.
"""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, make, new_id

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
def alice(server):
    clock.fix(T0)
    try:
        make_user(server, "alice")
        yield sign_in(server, "alice")
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
def test_a_filing_refuses_each_wrong_field(alice, fields, code):
    b = _book(alice)
    _refused(make(alice, "Filng", bookId=b["id"], **{**FEDERAL, **fields}), code)
    assert alice.get(f"/ui/api/tax-books/{b['id']}").json()["filings"] == []


@pytest.mark.parametrize(("fields", "code"), BOOKS, ids=[c for _, c in BOOKS])
def test_a_book_refuses_each_wrong_field(alice, fields, code):
    if fields.get("filers") == "nobody":
        other = new_id("User")
        fields = {"filers": [other]}
    _refused(make(alice, "TaxBk", **{"year": 2025, "filers": [_me(alice)], **fields}), code)


def test_a_book_keeps_its_year_and_a_carryover_share_is_never_negative(alice):
    b = _book(alice)
    got = alice.get(f"/ui/api/tax-books/{b['id']}").json()
    record = {"id": b["id"], "version": got["version"]}
    _refused(change(alice, "TaxBk", record, year=2024), "book-fixed")
    _refused(change(alice, "TaxBk", record, carryoverShareShort="-5.00"), "amount-invalid")


def test_a_filing_stays_in_its_book_and_never_amends_itself(alice):
    b = _book(alice)
    r = make(alice, "Filng", bookId=b["id"], **FEDERAL)
    f = next(x for x in r.parent()["filings"])
    record = {"id": f["id"], "version": f["version"]}
    _refused(change(alice, "Filng", record, amendsId=f["id"]), "amends-itself")
    other = make(alice, "TaxBk", year=2026, filers=[_me(alice)]).json()
    _refused(change(alice, "Filng", record, bookId=other["id"]), "filing-fixed")


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"quarter": 0}, "quarter-invalid"),
        ({"amount": "-1"}, "amount-invalid"),
        ({"transactionId": UNKNOWN_TXN}, "not-found"),
    ],
    ids=["quarter", "amount", "transaction"],
)
def test_an_estimated_payment_refuses_each_wrong_field(alice, fields, code):
    b = _book(alice)
    r = make(alice, "Filng", bookId=b["id"], **FEDERAL)
    f = next(x for x in r.parent()["filings"])
    body = {"filingId": f["id"], "quarter": 1, "amount": "100", **fields}
    _refused(make(alice, "EstPy", **body), code)


def test_a_dependent_is_claimed_as_a_child_or_a_relative(alice):
    b = _book(alice)
    kid = make(alice, "Persn", name="Emma", sex="female", birthYear=2015).json()["id"]
    _refused(make(alice, "TxDep", bookId=b["id"], personId=kid, claimedAs="cousin", months=12),
             "claimed-as-invalid")  # fmt: skip
