"""The import routes' edges (requirements S1.3, S1.3.3, S1.9.3): each refusal at its field or
status with its code and words, uploads held and let go, a reader that fails, a statement with
no lines, a brokerage photo, and a row left out that is gone or changed meanwhile."""

import datetime as dt
from pathlib import Path

import pytest
from conftest import make_user, sign_in
from test_accounts import new_account, upload, wait_job
from test_brokerage import SCHWAB
from test_reading import text_pdf
from test_statements import COMBINED, UMB, _body, _import

from moolakata import clock, settings
from moolakata.ui import imports

FIX = Path(__file__).parent / "fixtures"
CSV = b"Date,Description,Amount\n2026-09-01,Pay,100.00\n2026-09-02,Shop,-10.00\n"


@pytest.fixture
def jane(server):
    make_user(server, "jane")
    return sign_in(server, "jane")


def _refused(r) -> tuple:
    body = r.json()
    if body.get("errors"):
        e = body["errors"][0]
        return r.status_code, e["field"], e["code"], e["message"]
    return r.status_code, None, body["code"], body["detail"]


def _held(c, account_id: str, data: bytes = CSV, name: str = "export.csv") -> str:
    """A CSV held for its mapping: its upload's id."""
    result = upload(c, account_id, name, data)["result"]
    assert result["needsMapping"], result
    return result["uploadId"]


# ---------- what an upload is refused for ----------


def test_an_upload_too_large_empty_or_not_a_statement_is_refused(server, jane):
    """S13.7.6, S16.8: past Settings › Imports' size, at its status; empty, at the file; to keep,
    anything but a PDF or a photo, by its content."""
    a = new_account(jane)
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "importMaxMb", 1, None)
    big = b"x" * (1024 * 1024 + 1)
    for path in (
        f"/ui/api/accounts/{a['id']}/imports",
        f"/ui/api/accounts/{a['id']}/statements/keep",
    ):
        r = jane.post(path, files={"file": ("big.csv", big)})
        assert _refused(r) == (413, None, "too-large", "Files are up to 1 MB.")
        r = jane.post(path, files={"file": ("empty.csv", b"")})
        assert _refused(r) == (422, "file", "file-empty", "The file is empty.")
    r = jane.post(f"/ui/api/accounts/{a['id']}/statements/keep", files={"file": ("a.csv", CSV)})
    assert _refused(r) == (415, None, "unsupported-type", "A statement: a PDF or a photo of one.")


def test_a_job_that_isnt_yours_or_isnt_there_is_not_found(server, jane):
    make_user(server, "john")
    john = sign_in(server, "john")
    a = new_account(jane)
    r = jane.post(f"/ui/api/accounts/{a['id']}/imports", files={"file": ("e.csv", CSV)})
    job = r.json()
    assert john.get(f"/ui/api/jobs/{job['id']}").status_code == 404
    assert jane.get("/ui/api/jobs/Job_nothing").status_code == 404
    wait_job(jane, job)


# ---------- uploads held for the person to check ----------


def test_an_upload_held_is_let_go_once_it_expires(server, jane):
    """S1.3.2: an upload waits 30 minutes for its mapping; one past that is gone, and the next
    upload sweeps it."""
    a = new_account(jane, institution="Credit Union")
    first = _held(jane, a["id"])
    clock.fix(clock.now() + dt.timedelta(minutes=imports.HELD_MINUTES + 1))
    try:
        _held(jane, a["id"], name="export2.csv")
        assert first not in imports._held, "swept by the next upload"
        r = jane.post(f"/ui/api/imports/{first}/mapping", json={"mapping": {}})
        assert _refused(r)[2] == "upload-gone"
    finally:
        clock.fix(None)


def test_the_oldest_upload_gives_way_past_what_may_be_held_at_once(server, jane):
    """S13.7.5: uploads held for one person stay within what may be in flight; the oldest is let
    go first."""
    from moolakata.middleware import IN_FLIGHT

    class Large(bytes):
        """As large as may be in flight, without the memory."""

        def __len__(self) -> int:
            return IN_FLIGHT

    a = new_account(jane, institution="Credit Union")
    first = _held(jane, a["id"])
    imports._held[first].data = Large()
    second = _held(jane, a["id"], name="export2.csv")
    assert first not in imports._held and second in imports._held


def test_another_persons_upload_is_gone_to_you(server, jane):
    """S1.3.3: what someone else uploaded is never reached by its id."""
    make_user(server, "john")
    john = sign_in(server, "john")
    a = new_account(jane, institution="UMB Bank", keptBy=["file"])
    found = _import(jane, a["id"], text_pdf(UMB.splitlines()), keep=True)["result"]
    for path, body in (
        (f"/ui/api/imports/{found['uploadId']}/keep", {"periodStart": "2026-09-01"}),
        (f"/ui/api/imports/{found['uploadId']}/statement", _bodyless()),
    ):
        assert _refused(john.post(path, json=body))[2] == "upload-gone"


def _bodyless() -> dict:
    return {"periodStart": "2026-09-01", "periodEnd": "2026-09-30", "opening": "0.00",
            "closing": "0.00", "rows": []}  # fmt: skip


# ---------- a CSV's mapping ----------


def test_a_mapping_that_doesnt_read_the_file_is_refused_at_the_mapping(server, jane):
    a = new_account(jane, institution="Credit Union")
    held = _held(jane, a["id"])
    mapping = upload(jane, a["id"], "again.csv", CSV)["result"]["mapping"]
    r = jane.post(
        f"/ui/api/imports/{held}/mapping", json={"mapping": {**mapping, "dateFormat": "%d/%m/%Y"}}
    )
    status, field, code, message = _refused(r)
    assert (status, field, code) == (422, "mapping", "mapping-does-not-read")
    assert message == "Row 2: the date is not written as %d/%m/%Y."


def test_a_mapping_saved_again_replaces_the_owners_and_one_that_no_longer_reads_fails(server, jane):
    """S1.3.2: the mapping saved for an institution is replaced by the next one saved; a file the
    saved mapping can't read fails its import in the reader's words."""
    from moolakata.store.entities.accounts import ImportMapping

    a = new_account(jane, institution="Credit Union")
    held = [upload(jane, a["id"], name, CSV)["result"] for name in ("one.csv", "two.csv")]
    for h, memo in zip(held, ("Description", None), strict=True):
        mapping = {**h["mapping"], "memo": memo}
        r = jane.post(f"/ui/api/imports/{h['uploadId']}/mapping", json={"mapping": mapping})
        assert wait_job(jane, r.json())["state"] == "done"
        with server.db.read(unscoped="test") as s:
            [row] = s.query(ImportMapping).all()
            assert ('"memo": "Description"' in row.columns) == (memo is not None)
    job = upload(jane, a["id"], "other.csv", b"When,Payee,Total\n2026-09-03,Cafe,-4.50\n")
    assert job["state"] == "failed"
    assert job["error"] == {
        "code": "import-failed",
        "message": "The file has no column called 'Date'.",
    }


# ---------- statements ----------


def test_a_statement_the_reader_cant_open_or_that_holds_no_lines(server, jane):
    """S1.3.3: a file that looks like a PDF but isn't fails in the reader's words, whether
    imported or kept; one with no transactions is offered to be kept, with its period."""
    a = new_account(jane, institution="UMB Bank")
    broken = b"%PDF-1.4\n" + b"\x00" * 64
    for keep in (False, True):
        job = _import(jane, a["id"], broken, keep=keep)
        assert job["state"] == "failed" and job["error"]["code"] == "statement-unreadable", job
        assert job["error"]["message"].startswith("Couldn't read it: ")
    lines = ["UMB Bank, n.a.", "Statement Period: 09/01/26 - 09/30/26", "Nothing happened."]
    job = _import(jane, a["id"], text_pdf(lines))
    err = job["error"]
    assert (job["state"], err["code"], err["message"]) == ("failed", "statement-empty",
                                                         imports.EMPTY)  # fmt: skip
    assert (err["periodStart"], err["periodEnd"]) == ("2026-09-01", "2026-09-30")
    assert err["uploadId"] in imports._held, "kept as it is, if the person likes"


def test_a_statements_save_and_keep_refuse_a_period_backwards_or_missing(server, jane):
    a = new_account(jane, institution="UMB Bank", keptBy=["file"])
    review = _import(jane, a["id"], text_pdf(UMB.splitlines()))["result"]
    url = f"/ui/api/imports/{review['uploadId']}/statement"
    body = _body(review, periodStart="2026-10-01", periodEnd="2026-09-30")
    assert _refused(jane.post(url, json=body)) == (
        422,
        "periodEnd",
        "period-backwards",
        "The period ends before it starts.",
    )
    keep = f"/ui/api/imports/{review['uploadId']}/keep"
    assert _refused(jane.post(keep, json={"periodStart": "2026-09-01"})) == (
        422,
        "periodEnd",
        "period-missing",
        "The period the statement covers.",
    )
    r = jane.post(keep, json={"periodStart": "2026-10-01", "periodEnd": "2026-09-30"})
    assert _refused(r)[1:3] == ("periodEnd", "period-backwards")
    # A CSV held for its mapping is no statement to save.
    held = _held(jane, new_account(jane, name="Card", institution="Credit Union")["id"])
    r = jane.post(f"/ui/api/imports/{held}/statement", json=_body(review))
    assert _refused(r)[0:3] == (404, None, "upload-gone")


def test_a_part_that_isnt_one_of_the_statements_is_refused(server, jane):
    checking = new_account(jane, name="Free Checking", mask="4821", institution=None)
    lines = [x for x in COMBINED.splitlines() if not x.startswith("UMB Bank")]
    review = _import(jane, checking["id"], text_pdf(lines))["result"]
    assert [p["institution"] for p in review["parts"]] == [None, None], "named by none"
    url = f"/ui/api/imports/{review['uploadId']}/statement"
    for part in (None, 2, -1):
        r = jane.post(url, json=_body(review["parts"][0], part=part, accountId=checking["id"]))
        assert _refused(r) == (422, "part", "part-unknown", "One of the statement's 2 parts.")


def test_a_statement_of_no_institution_teaches_no_layout_and_a_second_teaches_its_own(server, jane):
    """S1.3.3.4: what is learned is kept per institution: a statement naming none, on an account
    naming none, teaches nothing; the next statement from an institution changes what the first
    taught."""
    from moolakata.store.entities.accounts import StatementLayout

    nameless = new_account(jane, name="Nameless", institution=None)
    lines = [x for x in UMB.splitlines() if not x.startswith("UMB Bank")]
    review = _import(jane, nameless["id"], text_pdf(lines))["result"]
    assert review["institution"] is None
    r = jane.post(f"/ui/api/imports/{review['uploadId']}/statement", json=_body(review))
    assert r.status_code == 200, r.text

    def layouts() -> list[str]:
        with server.db.read(unscoped="test") as s:
            return [x.layout for x in s.query(StatementLayout).all()]

    assert layouts() == []
    a = new_account(jane, institution="UMB Bank")
    for remember in ([], ["Daily balance"]):
        review = _import(jane, a["id"], text_pdf(UMB.splitlines()))["result"]
        body = _body(review, remember=remember)
        assert (
            jane.post(f"/ui/api/imports/{review['uploadId']}/statement", json=body).status_code
            == 200
        )
    [layout] = layouts()
    assert "daily balance" in layout


# ---------- brokerage statements ----------


def test_a_brokerage_photo_is_offered_to_be_kept_and_a_bank_statement_read_as_one(
    server, jane, monkeypatch
):
    """S1.3.3.8: a photo of a brokerage statement isn't read; a statement in an investing account
    that isn't a broker's is read as a bank's."""
    a = new_account(jane, name="Individual Brokerage", type="brokerage", institution="Schwab")
    real = imports._read

    def as_photo(srv, job, data, media):
        got = real(srv, job, data, media)
        return got[0], "ocr"

    monkeypatch.setattr(imports, "_read", as_photo)
    job = _import(jane, a["id"], text_pdf(SCHWAB.splitlines()))
    err = job["error"]
    assert (job["state"], err["code"]) == ("failed", "brokerage-photo")
    assert (err["periodStart"], err["periodEnd"]) == ("2026-09-01", "2026-09-30")
    monkeypatch.setattr(imports, "_read", real)
    review = _import(jane, a["id"], text_pdf(UMB.splitlines()))["result"]
    assert review.get("kind") != "brokerage" and len(review["rows"]) == 6


def test_a_brokerage_save_refuses_what_isnt_its_statement(server, jane):
    """S1.3.3.8: a bank statement's upload isn't a brokerage statement's; a period backwards and
    an instrument MoolaKata doesn't know are refused at their fields."""
    a = new_account(jane, name="Individual Brokerage", type="brokerage", institution="Schwab")
    review = _import(jane, a["id"], text_pdf(SCHWAB.splitlines()))["result"]
    url = f"/ui/api/imports/{review['uploadId']}/brokerage"
    body = {"periodStart": "2026-09-01", "periodEnd": "2026-09-30"}
    r = jane.post(url, json={**body, "periodStart": "2026-10-01"})
    assert _refused(r) == (
        422,
        "periodEnd",
        "period-backwards",
        "The period ends before it starts.",
    )
    stranger = {"label": "X", "instrumentId": "Instr_01m8gc3c7ceds8ftpyrfccktqg", "cash": False}
    r = jane.post(url, json={**body, "positions": [stranger]})
    assert _refused(r) == (422, "positions", "instrument-unknown", "One of the instruments here.")
    bank = new_account(jane, institution="UMB Bank")
    other = _import(jane, bank["id"], text_pdf(UMB.splitlines()))["result"]
    r = jane.post(f"/ui/api/imports/{other['uploadId']}/brokerage", json=body)
    assert _refused(r)[0:3] == (404, None, "upload-gone")


def test_a_brokerage_statement_remembered_twice_keeps_both(server, jane):
    from moolakata.store.entities.accounts import StatementLayout

    a = new_account(jane, name="Individual Brokerage", type="brokerage", institution="Schwab")
    for remember in (["MoneyLink Transfer"], ["Bank Interest"]):
        review = _import(jane, a["id"], text_pdf(SCHWAB.splitlines()))["result"]
        body = {"periodStart": review["periodStart"], "periodEnd": review["periodEnd"],
                "remember": remember}  # fmt: skip
        r = jane.post(f"/ui/api/imports/{review['uploadId']}/brokerage", json=body)
        assert r.status_code == 200, r.text
    with server.db.read(unscoped="test") as s:
        [row] = s.query(StatementLayout).all()
    assert "moneylink transfer" in row.layout and "bank interest" in row.layout


# ---------- a loan's rows left out ----------


def test_a_row_left_out_gone_or_changed_meanwhile(server):
    """S1.9.3, S13.8.6: leaving out a row already gone is not found; one changed since it was
    read answers its current form to try again."""
    from test_loans_routes import BEFORE, _kept, _leave_out, _mortgage_and_checking, loan_ofx

    c, _, loan = _mortgage_and_checking(server)
    imp = upload(c, loan["id"], "home.ofx", loan_ofx(*BEFORE))["result"]["importId"]
    payment, _ = _kept(c, imp)
    r = _leave_out(c, [{**payment, "version": payment["version"] + 1}])
    [stale] = r.json()["current"]
    assert r.status_code == 412 and (stale["entity"], stale["id"]) == ("ImpLO", payment["id"])
    assert stale["current"]["reason"] == payment["reason"] and stale["current"]["fits"] is False
    assert _leave_out(c, [payment]).status_code == 200
    r = _leave_out(c, [payment])
    assert r.status_code == 404


# ---------- what is left of the routes ----------


def test_an_import_that_fails_unexpectedly_says_so_and_logs_it(server, jane, monkeypatch, caplog):
    """S13.7.9: a fault in an import fails its job with words for an admin to look up, and the
    log keeps what happened; the person sees no internals."""
    from moolakata.store.repos import ledger

    def broken(*_a, **_k):
        raise RuntimeError("a bug")

    monkeypatch.setattr(ledger, "apply_import", broken)
    a = new_account(jane)
    job = upload(jane, a["id"], "bank.ofx", (FIX / "bank.ofx").read_bytes())
    assert job["state"] == "failed" and job["error"] == {
        "code": "import-failed",
        "message": "The import failed; an admin can find it in the log.",
    }
    assert any("failed" in r.getMessage() and r.exc_info for r in caplog.records)


def test_a_statement_of_several_accounts_saved_with_parts_left_out(server, jane):
    """S1.3.3.5: a part left out adds nothing; with every part left out nothing is kept."""
    from moolakata.store.entities.receipts import Receipt

    checking = new_account(jane, name="Free Checking", institution="UMB Bank", mask="4821")
    for leave in ((1,), (0, 1)):
        review = _import(jane, checking["id"], text_pdf(COMBINED.splitlines()))["result"]
        url = f"/ui/api/imports/{review['uploadId']}/statement"
        for i, part in enumerate(review["parts"]):
            extra = {"leftOut": True} if i in leave else {"accountId": checking["id"]}
            r = jane.post(url, json=_body(part, part=i, **extra))
            assert r.status_code == 200, r.text
        done = r.json()["result"]
        assert done["leftOut"] == list(leave)
        assert [p["part"] for p in done["parts"]] == [i for i in (0, 1) if i not in leave]
        if len(leave) == 2:
            assert done["receiptId"] is None, "nothing saved, nothing kept"
    with server.db.read(unscoped="test") as s:
        assert s.query(Receipt).count() == 1, "kept once, by the save that kept a part"


def test_a_statement_kept_with_reading_off_is_kept_unread(server, jane, admin_client):
    """S1.3.3.6: with statement reading off, a statement is still kept, by its name alone."""
    from edits import save_settings

    assert save_settings(admin_client, {"readStatements": False}).status_code == 200
    a = new_account(jane, institution="UMB Bank", keptBy=["file"])
    found = _import(jane, a["id"], text_pdf(UMB.splitlines()), keep=True)["result"]
    assert (found["periodStart"], found["periodEnd"]) == (None, None)
    r = jane.post(
        f"/ui/api/imports/{found['uploadId']}/keep",
        json={"periodStart": "2026-09-01", "periodEnd": "2026-09-30"},
    )
    assert r.status_code == 200, r.text


def test_an_upload_let_go_twice_or_by_another_answers_the_same(server, jane):
    """S13.8.1: letting go of an upload already gone, or of someone else's, answers as letting
    go of one's own, and leaves the other's held."""
    make_user(server, "john")
    john = sign_in(server, "john")
    held = _held(jane, new_account(jane, institution="Credit Union")["id"])
    r = john.delete(f"/ui/api/imports/{held}")
    assert r.status_code == 200 and r.json()["deleted"]["id"] == held
    assert held in imports._held
    for _ in range(2):
        r = jane.delete(f"/ui/api/imports/{held}")
        assert r.status_code == 200 and r.json()["deleted"]["id"] == held
    assert held not in imports._held


def test_forgetting_an_ignored_line_of_an_institution_with_none_changes_nothing(server, jane):
    body = {"institution": "Nowhere Bank", "kind": "bank", "start": "daily balance"}
    r = jane.post("/ui/api/statement-layouts/ignored/forget", json=body)
    assert r.status_code == 204
    assert jane.get("/ui/api/statement-layouts/ignored").json()["items"] == []
