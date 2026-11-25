"""Reading receipts (requirements S9.8): the field parser on its own, then RapidOCR in its
worker process on drawn receipts."""

import datetime as dt
import io
import json
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, remove, save_settings
from PIL import Image
from test_receipts import png, upload

from moolakata.dev.seed_receipts import draw
from moolakata.receipts import ocr, parser
from moolakata.receipts.reading import Reader, Worker

TODAY = dt.date(2026, 10, 13)


def fields(lines):
    return parser.parse(lines, TODAY)


@pytest.mark.parametrize(
    ("lines", "total"),
    [
        (["SUBTOTAL 18.40", "TAX 1.52", "TOTAL 19.92", "CASH 20.00", "CHANGE 0.08"], "19.92"),
        (["Order total", "$1,234.50"], "1234.50"),
        (["GRAND TOTAL $63.21", "VISA 63.21"], "63.21"),
        (["AMOUNT DUE 153.58", "TOTAL SAVINGS 4.00"], "153.58"),
        (["LATTE 5.75", "MUFFIN 3.25"], "5.75"),  # no label: the largest
        (["TOTAL 14 2.18"], "142.18"),  # an amount the recognizer split
    ],
)
def test_total(lines, total):
    assert fields(lines).total.value == Decimal(total)


@pytest.mark.parametrize(
    ("line", "day"),
    [
        ("10/09/2026", dt.date(2026, 10, 9)),
        ("2026-10-09", dt.date(2026, 10, 9)),
        ("09 OCT 26", dt.date(2026, 10, 9)),
        ("Oct 9, 2026", dt.date(2026, 10, 9)),
        ("OCT 9,2026", dt.date(2026, 10, 9)),
        ("DATE: 10-09-26 14:02", dt.date(2026, 10, 9)),
        ("09/25/202614:32", dt.date(2026, 9, 25)),  # the time run into the date
    ],
)
def test_date_formats(line, day):
    assert fields([line]).date.value == day


def test_dates_in_the_future_or_before_the_account_are_passed_over():
    found = parser.parse(["12/31/2026", "10/01/2026"], TODAY)
    assert found.date.value == dt.date(2026, 10, 1)
    found = parser.parse(["01/05/2019", "10/01/2026"], TODAY, not_before=dt.date(2020, 1, 1))
    assert found.date.value == dt.date(2026, 10, 1)


def test_merchant_card_and_tax():
    f = fields(
        [
            "BLUE BOTTLE COFFEE #12",
            "300 Webster St",
            "(510) 555-0142",
            "LATTE 5.75",
            "SALES TAX 0.52",
            "TOTAL 6.27",
            "VISA XXXX1123",
        ]
    )
    assert f.merchant.value == "Blue Bottle Coffee"
    assert f.card.value == "1123" and f.tax.value == Decimal("0.52")
    assert fields(["Paid with card ending in 4821"]).card.value == "4821"


@pytest.mark.parametrize(
    ("read", "payees", "known"),
    [
        # The same words, whatever the case, store number or state.
        ("Blue Bottle Coffee", ["Blue Apron", "BLUE BOTTLE COFFEE SF"], "BLUE BOTTLE COFFEE SF"),
        ("Kroger", ["KROGER #123"], "KROGER #123"),
        ("trader joe's", ["Trader Joe's"], "Trader Joe's"),
        # All of the shorter name's words, when it has two or more.
        ("Whole Foods Market", ["WHOLE FOODS"], "WHOLE FOODS"),
        ("The Home Depot", ["Home Depot"], "Home Depot"),
        # One word in a longer name, or a word in common, is a near miss.
        ("Kroger", ["Kroger Fuel"], None),
        ("Blue Bottle Coffee", ["Blue Apron"], None),
        ("Shell", ["Shell Oil", "Shellfish Shack"], None),
        ("#042", ["Store 042"], None),
        # The closest wins; among equals, the first given (the most used).
        ("Whole Foods", ["Whole Foods Market Austin", "WHOLE FOODS MARKET"], "WHOLE FOODS MARKET"),
        ("Whole Foods Market", ["WHOLE FOODS", "Whole Foods"], "WHOLE FOODS"),
    ],
)
def test_a_merchant_is_matched_to_a_payee_its_owner_has(read, payees, known):
    """S9.8.2.5.3: the payee the merchant names, else none."""
    assert parser.known_payee(read, payees) == known


def test_a_receipts_merchant_takes_the_payee_its_owner_already_has(server):
    """S9.8.2.5.3: after the rules, the owner's own payee the merchant names replaces it, from
    their accounts only, and a payee typed by hand stays."""
    from edits import make
    from test_accounts import add, new_account

    from moolakata.receipts.reading import save_reading
    from moolakata.store.entities.receipts import Receipt

    make_user(server, "jane")
    make_user(server, "john")
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    add(jane, new_account(jane)["id"], "-5.75", "2026-10-02", payee="BLUE BOTTLE COFFEE SF")
    add(john, new_account(john)["id"], "-5.75", "2026-10-02", payee="Blue Bottle Coffee Oakland")
    make(jane, "Rule", payeeMatch="kroger", payee="Kroger Groceries")
    lines = ["BLUE BOTTLE COFFEE #042", "TOTAL 5.75"]
    theirs = upload(john, png((1, 2, 3))).json()["id"]
    mine = upload(jane, png((4, 5, 6))).json()["id"]
    renamed = upload(jane, png((7, 8, 9))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        save_reading(s, s.get(Receipt, mine), lines, "text", "test")
        save_reading(s, s.get(Receipt, theirs), lines, "text", "test")
        save_reading(s, s.get(Receipt, renamed), ["KROGER #12", "TOTAL 9.10"], "text", "test")
    assert jane.get(f"/ui/api/receipts/{mine}").json()["payee"] == "BLUE BOTTLE COFFEE SF"
    assert john.get(f"/ui/api/receipts/{theirs}").json()["payee"] == "Blue Bottle Coffee Oakland"
    assert jane.get(f"/ui/api/receipts/{renamed}").json()["payee"] == "Kroger Groceries"
    r = change(jane, "Rcpt", jane.get(f"/ui/api/receipts/{mine}").json(), payee="Blue Bottle")
    assert r.status_code == 200, r.text
    with server.db.tx(unscoped="test") as s:
        save_reading(s, s.get(Receipt, mine), lines, "text", "test")
    assert jane.get(f"/ui/api/receipts/{mine}").json()["payee"] == "Blue Bottle", "typed stays"


def test_the_shipped_models_are_the_pinned_ones():
    assert set(ocr.check_models()) == {"det", "cls", "rec"}


def test_the_engine_switches_onnxruntime_telemetry_off(monkeypatch):
    """The wheel carries a client that uploads to Microsoft; the reader turns it off before its
    first session, since nothing leaves the server but the calls of R3.1."""
    import onnxruntime

    calls = []
    monkeypatch.setattr(onnxruntime, "disable_telemetry_events", lambda: calls.append(True))
    monkeypatch.setattr(ocr, "_engine", None)
    assert ocr.engine() is not None
    assert calls == [True]


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def test_ocr_in_the_worker_reads_a_tilted_receipt():
    img = draw(
        [
            "KROGER #0421",
            "1200 MAIN ST",
            "09/25/2026  14:32",
            "SUBTOTAL           134.62",
            "TAX                0.00",
            "TOTAL              134.62",
            "VISA ****1123",
        ]
    ).rotate(3, expand=True, fillcolor="white")
    w = Worker()
    try:
        status, lines, method, engine, _ = w.read(_png(img), "image/png", user="User_a")
    finally:
        w.stop()
    assert status == "ok" and method == "ocr" and "PP-OCRv6" in engine
    f = parser.parse(lines, TODAY)
    assert f.total.value == Decimal("134.62")
    assert f.date.value == dt.date(2026, 9, 25)
    assert f.merchant.value.startswith("Kroger")
    assert f.card.value == "1123"


def text_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a text layer, as an emailed invoice has."""
    content = "BT /F1 12 Tf 40 360 Td 14 TL " + " ".join(f"({x}) '" for x in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 4 0 R"
        " >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode()


def test_a_pdf_with_a_text_layer_is_read_without_ocr():
    r = ocr.read(
        text_pdf(["City Power & Water", "Invoice 2026-117", "AMOUNT DUE 153.58"]), "application/pdf"
    )
    assert r.method == "text" and "AMOUNT DUE 153.58" in r.lines
    assert parser.parse(r.lines, TODAY).total.value == Decimal("153.58")


def pdf(*pages: dict) -> bytes:
    """A PDF of these pages, each a dict: `text`, lines in its text layer (`hidden`: drawn
    invisible, as a scanner's own OCR layer is); `scan`, lines drawn as an image, as a scanned
    page is."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None]
    font = len(objs) + 1
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for p in pages:
        content, xobjects = "", ""
        if p.get("scan"):
            img = draw(p["scan"]).convert("L")
            w, h = img.size
            raw = img.tobytes()
            objs.append(
                f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace"
                f" /DeviceGray /BitsPerComponent 8 /Length {len(raw)} >>\nstream\n"
                + raw.decode("latin-1")
                + "\nendstream"
            )
            xobjects = f"/XObject << /Im1 {len(objs)} 0 R >>"
            height = 300 * h / w
            content += f"q 300 0 0 {height:.2f} 0 {400 - height:.2f} cm /Im1 Do Q "
        if p.get("text"):
            mode = "3 Tr " if p.get("hidden") else ""
            content += f"BT {mode}/F1 12 Tf 40 360 Td 14 TL "
            content += " ".join(f"({x}) '" for x in p["text"]) + " ET"
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
        contents = len(objs)
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1"
            f" {font} 0 R >> {xobjects} >> /Contents {contents} 0 R >>"
        )
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = "%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


LETTER = {"text": ["Dear Jane,", "Please find your receipt for the repair attached."]}
INVOICE = {"text": ["City Power & Water", "Invoice 2026-117", "AMOUNT DUE 153.58"]}
SCAN = {"scan": ["CORNER STORE", "OCT 9, 2026", "TOTAL 12.34"]}


@pytest.fixture
def ocr_calls(monkeypatch):
    """The pages read by OCR, counted."""
    calls = []
    real = ocr._ocr
    monkeypatch.setattr(ocr, "_ocr", lambda images: calls.append(1) or real(images))
    return calls


@pytest.mark.parametrize(
    ("pages", "method", "read", "ocred"),
    [
        ([LETTER, INVOICE], "text", ["Dear Jane,", "AMOUNT DUE 153.58"], 0),
        ([SCAN, {"scan": ["PAGE TWO"]}], "ocr", ["TOTAL 12.34", "PAGE TWO"], 2),
        ([LETTER, SCAN], "both", ["Dear Jane,", "TOTAL 12.34"], 1),
        ([SCAN, LETTER], "both", ["TOTAL 12.34", "Dear Jane,"], 1),
    ],
    ids=["all text", "all scanned", "a letter, then a scan", "a scan, then a letter"],
)
def test_a_pdf_is_read_page_by_page(pages, method, read, ocred, ocr_calls):
    """S9.8.2.1: a page with a text layer is read from it, any other by OCR, in page order;
    the method says which, or both."""
    r = ocr.read(pdf(*pages), "application/pdf")
    assert r.method == method
    assert [x for x in r.lines if x in read] == read, r.lines
    assert len(ocr_calls) == ocred
    if method == "both":
        assert r.engine.startswith("pypdfium2 text layer, rapidocr")
        assert parser.parse(r.lines, TODAY).total.value == Decimal("12.34")


def test_the_page_cap_counts_only_the_pages_read_by_ocr(ocr_calls):
    """S9.8.2.2: the cap is on scanned pages; a text page past it is still read."""
    r = ocr.read(pdf(SCAN, LETTER, {"scan": ["PAGE THREE"]}, INVOICE), "application/pdf", 1)
    assert r.method == "both" and len(ocr_calls) == 1
    assert "TOTAL 12.34" in r.lines and "PAGE THREE" not in r.lines
    assert "AMOUNT DUE 153.58" in r.lines, "the text page after the cap"


def test_the_total_is_checked_against_the_scan_of_its_page(ocr_calls):
    """S9.8.2.1.1: the page whose text layer gives the total is read by OCR too, alone."""
    agrees = pdf(LETTER, {**INVOICE, "scan": INVOICE["text"], "hidden": True})
    r = ocr.read(agrees, "application/pdf", check=True)
    assert r.method == "text" and len(ocr_calls) == 1, "that one page, not the letter"
    assert r.check == {"text": "153.58", "scan": "153.58", "agrees": True}
    # A scanner's text layer that misread the total: the scan says otherwise.
    misread = {"text": ["CORNER STORE", "TOTAL 72.34"], "hidden": True, "scan": SCAN["scan"]}
    r = ocr.read(pdf(misread), "application/pdf", check=True)
    assert r.check == {"text": "72.34", "scan": "12.34", "agrees": False}
    # Not asked (a statement), or a total read by OCR already: nothing read twice.
    ocr_calls.clear()
    assert ocr.read(pdf(misread), "application/pdf").check is None
    assert ocr.read(pdf(LETTER, SCAN), "application/pdf", check=True).check is None
    assert len(ocr_calls) == 1, "the scanned page, once"


class _Process:
    """A worker process as Worker sees it, without starting one: each has its own pid."""

    started = 0

    def __init__(self):
        _Process.started += 1
        self.pid = _Process.started
        self.stdin = self.stdout = io.BytesIO()

    def poll(self):
        return None

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def no_process(monkeypatch):
    """Workers that start no process and answer every job with no lines."""
    monkeypatch.setattr(Worker, "_start", lambda self: setattr(self, "proc", _Process()))
    from moolakata import parsing

    monkeypatch.setattr(Worker, "_send", lambda self, data, deadline: None)
    monkeypatch.setattr(
        Worker, "_recv", lambda self, deadline: {"lines": [], "method": "text", "engine": "x"}
    )
    parsing.stop()
    yield
    parsing.stop()  # no later test finds the quick worker without its process


def test_another_users_file_gets_a_fresh_worker_and_the_same_users_run_shares_one(no_process):
    # S9.8.4.2: a file that takes the worker over sees no other user's file after it.
    w = Worker()
    pids = []
    for user in ("User_a", "User_a", "User_b", "User_a"):
        assert w.read(b"%PDF", "application/pdf", user=user)[0] == "ok"
        pids.append(w.proc.pid)
    assert pids[0] == pids[1], "one user's run of files shares it"
    assert len({pids[1], pids[2], pids[3]}) == 3, "another user's file: a fresh worker"
    # A job with no file (the sandbox's self-test) keeps the worker it finds.
    w.call("selftest")
    assert w.proc.pid == pids[3]


def test_the_quick_worker_is_fresh_for_another_users_file(no_process):
    # S9.8.4.2: thumbnails, photos and imports likewise, one user's files at a time.
    from moolakata import parsing

    pids = []
    for user in ("User_a", "User_a", "User_b"):
        parsing.text_layer(b"%PDF", user=user)
        pids.append(parsing._worker.proc.pid)
    assert pids[0] == pids[1] != pids[2]


def test_the_reading_queue_reads_each_receipt_as_its_owners_file(server, monkeypatch, no_process):
    # S9.8.4.2: the queue names the owner, so another owner's receipt gets a fresh worker.
    make_user(server, "jane")
    make_user(server, "john")
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    ids = [
        upload(who, text_pdf(["AMOUNT DUE 1.00"]), name="r.pdf").json()["id"]
        for who in (jane, john)
    ]
    owners = {}
    with server.db.read(unscoped="test") as s:
        from moolakata.store.entities.receipts import Receipt

        for rid in ids:
            owners[rid] = s.get(Receipt, rid).ownerId
    seen = []
    w = Worker()
    monkeypatch.setattr(
        w, "read", lambda data, media, *a, user, **k: seen.append(user) or ("error", "x")
    )
    for rid in ids:
        Reader(server, workers=1).read_one(rid, w)
    assert seen == [owners[rid] for rid in ids]


def test_a_broken_file_fails_with_a_reason_and_the_worker_lives_on():
    w = Worker()
    try:
        assert w.read(b"\x89PNG\r\n\x1a\nbroken", "image/png", user="User_a")[0] == "error"
        status = w.read(b"%PDF-1.4 nothing", "application/pdf", user="User_a")
        assert status == ("error", "the PDF can't be opened")
    finally:
        w.stop()


def test_the_worker_starts_when_the_server_holds_over_a_thousand_files():
    """Its pipes then have numbers past 1023, which `select` refuses (the full test run reaches
    that, and a busy server can)."""
    import os
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if hard != resource.RLIM_INFINITY and hard < 1200:
        pytest.skip("this account may not hold 1200 files")
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, 1200), hard))
    held = []
    try:
        while not held or held[-1] < 1100:
            held.append(os.open(os.devnull, os.O_RDONLY))
        w = Worker()
        try:
            assert (
                w.read(text_pdf(["AMOUNT DUE 153.58"]), "application/pdf", user="User_a")[0] == "ok"
            )
        finally:
            w.stop()
    finally:
        for fd in held:
            os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def test_a_worker_past_its_time_is_stopped():
    w = Worker()
    try:
        w.read(_png(draw(["warm up"])), "image/png", user="User_a")
        out = w.read(
            _png(draw(["X" * 30] * 60, width=1600)), "image/png", limit=0.01, user="User_a"
        )
        assert out == ("error", "it took longer than 0 seconds")
        assert w.proc is None
        assert w.read(_png(draw(["TOTAL 1.00"])), "image/png", user="User_a")[0] == "ok", (
            "a new one starts"
        )
    finally:
        w.stop()


def test_a_worker_that_stops_reading_its_job_is_stopped_at_the_jobs_deadline(monkeypatch):
    """S9.8.4.2: the time limit counts from the job's start, its sending included, so a worker
    that stops reading (a hostile file's code, a library wedged) is stopped, not waited on."""
    import os
    import threading

    pipes = []

    class Deaf:
        """A started worker that never reads its stdin and never answers."""

        def __init__(self):
            r_in, w_in = os.pipe()
            r_out, w_out = os.pipe()
            pipes.extend((r_in, w_out))
            self.pid = os.getpid()
            self.stdin = os.fdopen(w_in, "wb")
            self.stdout = os.fdopen(r_out, "rb")

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(Worker, "_start", lambda self: setattr(self, "proc", Deaf()))
    w = Worker()
    out = []
    job = threading.Thread(
        target=lambda: out.append(w.call("thumbnail", b"x" * (4 << 20), 0.2, user="User_a")),
        daemon=True,
    )
    try:
        job.start()
        job.join(30)
        assert not job.is_alive(), "the caller waits on the worker for good"
        assert out == [{"error": "it took longer than 0 seconds"}]
        assert w.proc is None, "the worker is stopped"
    finally:
        for fd in pipes:  # a caller still stuck in its write is let go
            os.close(fd)
        job.join(30)


def test_reading_fills_empty_fields_never_typed_ones(server):
    make_user(server, "jane")
    c = sign_in(server, "jane")
    img = draw(["BLUE BOTTLE COFFEE", "OCT 9, 2026", "LATTE 5.75", "TOTAL 5.75"])
    rid = upload(c, _png(img)).json()["id"]
    v = c.get(f"/ui/api/receipts/{rid}").json()
    assert v["readStatus"] == "waiting"
    r = change(c, "Rcpt", v, payee="My café")
    reader = Reader(server, workers=1)
    w = Worker()
    try:
        reader.read_one(rid, w)
    finally:
        w.stop()
    got = c.get(f"/ui/api/receipts/{rid}").json()
    assert got["readStatus"] == "read" and "TOTAL 5.75" in got["text"]
    assert got["amount"] == "5.75" and got["date"] == "2026-10-09"
    assert got["payee"] == "My café", "a typed value is never overwritten"
    assert set(got["filled"]) == {"amount", "date"}
    assert got["suggested"]["total"]["confidence"] >= 90
    # The text is searchable.
    assert [x["id"] for x in c.get("/ui/api/receipts", params={"q": "latte"}).json()["items"]] == [
        rid
    ]
    # Read again: still only empty or suggested fields.
    assert c.post(f"/ui/api/receipts/{rid}/read").json()["readStatus"] == "waiting"
    assert json.loads(json.dumps(got["filled"])) == ["amount", "date"]
    assert r.status_code == 200


def test_reading_off_leaves_receipts_unread(server, admin_client):
    assert save_settings(admin_client, {"readReceipts": False}).status_code == 200
    make_user(server, "jane")
    c = sign_in(server, "jane")
    rid = upload(c, _png(draw(["TOTAL 1.00"]))).json()["id"]
    assert c.get(f"/ui/api/receipts/{rid}").json()["readStatus"] == "off"
    q = admin_client.get("/ui/api/settings/receipts").json()
    assert q["waiting"] == 0


def test_text_and_scan_disagreeing_flag_the_total_until_someone_confirms_it(server):
    """S9.8.2.1.1: the scan's reading kept beside the amount and no transaction offered, until
    its amount is picked or typed and saved; then it is the person's, as a typed one is. The
    receipt's own columns say so (`scanTotal`, `totalChecked`), nothing inside `suggested`."""
    from test_accounts import add, new_account
    from test_budget_refusals import refused

    from moolakata.store.entities.receipts import Receipt

    make_user(server, "jane")
    c = sign_in(server, "jane")
    acct = new_account(c)
    add(c, acct["id"], "-72.34", "2026-10-09", payee="Corner Store")
    lines = ["CORNER STORE", "OCT 9, 2026", "TOTAL 72.34"]
    rid = upload(c, text_pdf(lines), name="r.pdf").json()["id"]
    answer = ("ok", lines, "text", "pypdfium2 text layer", None)
    w = Worker()
    once = ("totalChecked", "total-check-fixed", "Only a total waiting to be checked is confirmed.")

    def read_with(check):
        w.read = lambda data, media, *a, user, check=False: (*answer[:4], found if check else None)
        found = check
        assert c.post(f"/ui/api/receipts/{rid}/read").status_code == 200
        Reader(server, workers=1).read_one(rid, w)
        with server.db.read(unscoped="test") as s:
            assert "totalCheck" not in json.loads(s.get(Receipt, rid).suggested)
        return c.get(f"/ui/api/receipts/{rid}").json()

    got = read_with(None)
    assert (got["scanTotal"], got["totalChecked"]) == (None, None), "nothing checked"
    got = read_with({"text": "72.34", "scan": "72.34", "agrees": True})
    assert (got["scanTotal"], got["totalChecked"]) == (None, None), "they agree"
    assert [m["amount"] for m in got["matches"]] == ["-72.34"]
    # A total the server's own reading doesn't give checks nothing.
    got = read_with({"text": "99.99", "scan": "12.34", "agrees": False})
    assert (got["scanTotal"], got["totalChecked"]) == (None, None)
    got = read_with({"text": "72.34", "scan": "12.34", "agrees": False})
    assert (got["scanTotal"], got["totalChecked"]) == ("12.34", False)
    assert got["matches"] == [], "nothing offered meanwhile"
    assert got["suggested"]["total"]["value"] == "72.34" and got["amount"] == "72.34"
    # A save of anything else leaves it waiting.
    assert change(c, "Rcpt", got, notes="from the shoebox").status_code == 200
    got = c.get(f"/ui/api/receipts/{rid}").json()
    assert got["totalChecked"] is False and "amount" in got["filled"]
    refused(change(c, "Rcpt", got, totalChecked=None), *once)
    # Picking the text's reading confirms it, once.
    assert change(c, "Rcpt", got, totalChecked=True).status_code == 200
    got = c.get(f"/ui/api/receipts/{rid}").json()
    assert (got["scanTotal"], got["totalChecked"], got["amount"]) == ("12.34", True, "72.34")
    assert "amount" not in got["filled"], "the person's now"
    assert [m["amount"] for m in got["matches"]] == ["-72.34"]
    for wrong in (None, False):
        refused(change(c, "Rcpt", got, totalChecked=wrong), *once)
    # Read again, it disagrees again over the person's amount: theirs, nothing to confirm.
    got = read_with({"text": "72.34", "scan": "12.34", "agrees": False})
    assert (got["scanTotal"], got["totalChecked"]) == ("12.34", True)
    assert [m["amount"] for m in got["matches"]] == ["-72.34"]
    # A scan with no total at all disagrees too.
    assert change(c, "Rcpt", got, amount=None).status_code == 200
    got = read_with({"text": "72.34", "scan": None, "agrees": False})
    assert (got["scanTotal"], got["totalChecked"]) == (None, False)
    # Clearing the amount confirms nothing; a total confirmed blank is refused.
    blank = ("amount", "total-check-blank", "Pick or type the total to confirm it.")
    refused(change(c, "Rcpt", got, amount=None, totalChecked=True), *blank)
    assert change(c, "Rcpt", got, amount=None).status_code == 200
    got = c.get(f"/ui/api/receipts/{rid}").json()
    assert (got["amount"], got["totalChecked"]) == (None, False)
    # Typing the amount confirms it as well.
    assert change(c, "Rcpt", got, amount="12.34").status_code == 200
    got = c.get(f"/ui/api/receipts/{rid}").json()
    assert (got["totalChecked"], got["amount"]) == (True, "12.34")
    # Agreeing, there is nothing to confirm.
    assert change(c, "Rcpt", got, amount=None).status_code == 200
    got = read_with({"text": "72.34", "scan": "72.34", "agrees": True})
    assert (got["scanTotal"], got["totalChecked"]) == (None, None)
    refused(change(c, "Rcpt", got, totalChecked=True), *once)
    refused(change(c, "Rcpt", got, totalChecked=False), *once)


def test_a_receipt_whose_file_was_pruned_is_never_left_reading(server, admin_client):
    """S9.8.6, S14.10.5: Read again is refused on a pruned receipt, before reading being off is;
    and one queued already (at a start, or before the prune) fails, saying why."""
    from moolakata import clock
    from moolakata.store.entities.receipts import Receipt

    make_user(server, "jane")
    c = sign_in(server, "jane")
    rid = upload(c, _png(draw(["TOTAL 1.00"]))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        s.get(Receipt, rid).filePrunedAt = dt.datetime(2026, 10, 1, 12, tzinfo=dt.UTC)
    r = c.post(f"/ui/api/receipts/{rid}/read")
    assert (r.status_code, r.json()["code"]) == (409, "file-pruned")
    assert r.json()["detail"] == "Its file was pruned on Oct 1, 2026."
    assert save_settings(admin_client, {"readReceipts": False}).status_code == 200
    assert c.post(f"/ui/api/receipts/{rid}/read").json()["code"] == "file-pruned"
    assert save_settings(admin_client, {"readReceipts": True}).status_code == 200
    assert c.get(f"/ui/api/receipts/{rid}").json()["readStatus"] == "waiting"
    clock.fix(dt.datetime(2026, 10, 2, 9, tzinfo=dt.UTC))
    try:
        Reader(server, workers=1).read_one(rid, None)
    finally:
        clock.fix(None)
    got = c.get(f"/ui/api/receipts/{rid}").json()
    assert (got["readStatus"], got["readError"]) == ("failed", "its file was pruned")


class _Queue:
    """The running reader as a save reaches it: what it was asked, in order."""

    def __init__(self):
        self.asked = []

    def resize(self):
        self.asked.append("resize")

    def queue(self, rid):
        self.asked.append(rid)


def test_turning_reading_on_reads_what_came_in_while_it_was_off(server, admin_client):
    """S9.8.4.1, S9.8.7: every receipt uploaded while reading was off is queued once it is on
    again, in the order they came; one deleted or whose file was pruned stays as it is."""
    from moolakata import clock
    from moolakata.store.entities.receipts import Receipt

    assert save_settings(admin_client, {"readReceipts": False}).status_code == 200
    make_user(server, "jane")
    make_user(server, "john")
    jane, john = sign_in(server, "jane"), sign_in(server, "john")
    first = upload(jane, _png(draw(["TOTAL 1.00"]))).json()["id"]
    second = upload(john, _png(draw(["TOTAL 2.00"]))).json()["id"]
    pruned = upload(jane, _png(draw(["TOTAL 3.00"]))).json()["id"]
    deleted = upload(jane, _png(draw(["TOTAL 4.00"]))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        s.get(Receipt, pruned).filePrunedAt = clock.now()
        s.get(Receipt, deleted).mark_deleted(None)
    server.reader = _Queue()
    try:
        assert save_settings(admin_client, {"readReceipts": True}).status_code == 200
        assert server.reader.asked == ["resize", first, second]
    finally:
        server.reader = None
    with server.db.read(unscoped="test") as s:
        got = {rid: s.get(Receipt, rid).readStatus for rid in (first, second, pruned, deleted)}
    assert got == {first: "waiting", second: "waiting", pruned: "off", deleted: "off"}
    # Turned on by going back to its default, likewise.
    assert save_settings(admin_client, {"readReceipts": False}).status_code == 200
    third = upload(jane, _png(draw(["TOTAL 5.00"]))).json()["id"]
    ref = admin_client.get("/ui/api/settings").json()["records"]["readReceipts"]
    server.reader = _Queue()
    try:
        assert remove(admin_client, "Setng", ref).status_code == 200
        assert server.reader.asked == ["resize", third]
    finally:
        server.reader = None


def test_jobs_at_a_time_applies_from_the_save(server, admin_client, no_process):
    """S9.8.7, R3.7: a new number of jobs starts more threads, or lets the extra ones go once
    the receipt in hand is read; the queue is kept."""
    from moolakata.dev.waits import eventually

    reader = Reader(server)
    server.reader = reader
    try:
        reader.start()
        assert len(reader.threads) == 1
        assert save_settings(admin_client, {"receiptReadJobs": 3}).status_code == 200
        assert len(reader.threads) == 3 and len(reader.workers) == 3
        assert save_settings(admin_client, {"receiptReadJobs": 2}).status_code == 200
        eventually(lambda: len(reader.threads) == 2, what="one thread let go")
        assert len(reader.workers) == 2 and reader.size == 2
        assert all(t.is_alive() for t in reader.threads)
    finally:
        reader.stop()
        server.reader = None
    for t in list(reader.threads):
        t.join(30)
    assert not any(t.is_alive() for t in reader.threads), "every thread stops with the reader"


def _variants(img: Image.Image):
    """The same receipt as a phone might take it: straight, tilted, faded, soft, small."""
    from PIL import ImageEnhance, ImageFilter

    yield img
    yield img.rotate(-4, expand=True, fillcolor="white")
    yield ImageEnhance.Contrast(img).enhance(0.45)
    yield img.filter(ImageFilter.GaussianBlur(0.8))
    yield img.resize((img.width * 2 // 3, img.height * 2 // 3))
    yield img.rotate(180)


FIXTURES = [
    (
        [
            "TRADER JOE'S #551",
            "1525 ELM AVE",
            "10/02/2026 18:21",
            "BANANAS            1.16",
            "COFFEE BEANS       8.99",
            "SUBTOTAL          10.15",
            "TAX                0.00",
            "TOTAL             10.15",
            "CHANGE             9.85",
        ],
        ("10.15", dt.date(2026, 10, 2), "Trader Joe'S"),
    ),
    (
        [
            "SHELL",
            "2026-09-30",
            "PUMP 4  UNLEADED",
            "GALLONS 11.214",
            "TOTAL $42.37",
            "DEBIT ****4821",
        ],
        ("42.37", dt.date(2026, 9, 30), "Shell"),
    ),
]


def test_fixture_receipts_stay_above_the_accuracy_floor():
    """Date, total and merchant across the variants: a change must not drop below 80%."""
    w = Worker()
    right = asked = 0
    try:
        for lines, (total, day, merchant) in FIXTURES:
            for img in _variants(draw(lines)):
                out = w.read(_png(img), "image/png", user="User_a")
                f = parser.parse(out[1] if out[0] == "ok" else [], TODAY)
                asked += 3
                right += bool(f.total and f.total.value == Decimal(total))
                right += bool(f.date and f.date.value == day)
                right += bool(
                    f.merchant and f.merchant.value.lower().startswith(merchant.lower()[:5])
                )
    finally:
        w.stop()
    assert right / asked >= 0.8, f"{right} of {asked}"


def test_the_worker_gives_up_the_network_and_its_environment(tmp_path):
    """S9.8.4.2: no socket of any kind and no signal but to itself (seccomp), no environment,
    and the data directory closed where the kernel has Landlock; it says which it holds."""
    from moolakata import sandbox

    (tmp_path / "secret").write_text("x")
    w = Worker(tmp_path)
    try:
        out = w.call("selftest", b"", path=str(tmp_path))
        assert out["network"] is False, "a network socket is refused"
        # Nor a local one, nor a signal to the server: the server's own socket and process
        # are out of its reach (S9.8.4.2).
        assert out["local"] is False and out["signal"] is False
        # Its own thread count, and the locale Python itself sets: nothing of the server's.
        assert set(out["environment"]) <= {"OMP_NUM_THREADS", "LC_CTYPE"}
        assert w.state["seccomp"] and w.state["core"]
        landlock = sandbox.landlock_abi() >= 1
        assert w.state["landlock"] is landlock
        assert out["path"] is (not landlock), "the data directory is closed with Landlock"
    finally:
        w.stop()


def test_an_answer_out_of_shape_is_refused(monkeypatch):
    """The server checks every field of what the worker answers, never trusting its shape."""
    from moolakata import parsing
    from moolakata.importers import parsed

    w = Worker()
    monkeypatch.setattr(
        w, "call", lambda *a, **k: {"lines": ["ok", 7], "method": "ocr", "engine": "x"}
    )
    assert w.read(b"", "image/png", user="User_a") == ("error", "the reader answered out of turn")
    good = {"text": "72.34", "scan": None, "agrees": False}
    for check in (
        "yes",
        {**good, "text": "NaN"},
        {**good, "scan": "1e9"},
        {**good, "agrees": "no"},
        {**good, "more": 1},
    ):
        answer = {"lines": ["ok"], "method": "both", "engine": "x", "check": check}
        monkeypatch.setattr(w, "call", lambda *a, answer=answer, **k: answer)
        assert w.read(b"", "application/pdf", user="User_a", check=True)[0] == "error", check
    monkeypatch.setattr(w, "call", lambda *a, **k: {**answer, "check": good})
    assert w.read(b"", "application/pdf", user="User_a", check=True)[4] == good
    monkeypatch.setattr(parsing, "_call", lambda op, data, **k: {"webp": "not base64!"})
    assert parsing.thumbnail(b"", "image/png", user="User_a") is None
    monkeypatch.setattr(parsing, "_call", lambda op, data, **k: {"jpeg": "aGVsbG8="})
    with pytest.raises(parsed.ReadError):
        parsing.as_jpeg(b"", user="User_a")
    for bad in (
        None,
        {"format": "ofx", "rows": [{"date": "2026-13-01", "kind": "deposit", "amount": "1"}]},
        {"format": "ofx", "rows": [{"date": "2026-01-01", "kind": "deposit", "amount": "NaN"}]},
        {"format": "exe", "rows": []},
    ):
        monkeypatch.setattr(parsing, "_call", lambda op, data, b=bad, **k: {"parsed": b})
        with pytest.raises(parsed.ReadError):
            parsing.read_ofx(b"", user="User_a")


def test_a_csv_proposal_carries_only_a_mappings_keys(monkeypatch):
    """S9.8.4.2.1: the worker's proposed mapping is checked key by key, so a taken-over worker
    can't put a key of its own into what the browser sends back and the server saves."""
    from moolakata import parsing
    from moolakata.importers import csvfile, parsed

    good = csvfile.propose(b"Date,Amount,Description\n2026-01-02,-4.50,Coffee\n", trades=True)
    answer = {"proposal": good}
    monkeypatch.setattr(parsing, "_call", lambda op, data, **k: answer)
    assert parsing.propose_csv(b"", trades=True, user="User_a")["mapping"] == good["mapping"]
    answer["proposal"] = {**good, "mapping": {**good["mapping"], "script": "x"}}
    with pytest.raises(parsed.ReadError):
        parsing.propose_csv(b"", user="User_a")


def test_the_server_can_be_made_non_dumpable():
    """S9.8.4.3: no other process of its account reads the server's memory."""
    import subprocess
    import sys

    code = (
        "import ctypes; from moolakata import sandbox; sandbox.not_dumpable();"
        "libc = ctypes.CDLL(None); print(libc.prctl(3, 0, 0, 0, 0))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "0"


def test_a_pdf_page_is_drawn_within_the_pixel_cap():
    # S9.8.4.3: a page of any size is never drawn bigger than an image may be.
    from moolakata.receipts import ocr

    class Page:
        def get_size(self):
            return (14400.0, 14400.0)  # the largest page PDF allows, in points

        def render(self, scale):
            self.scale = scale
            return self

        def to_pil(self):
            return self

    page = ocr._rendered(Page())
    assert (14400 * page.scale) ** 2 <= ocr.MAX_PIXELS * 1.0001


def test_an_upload_is_held_in_memory(bare_client):
    # S13.7.6: never spooled to a temporary file; uploads stop at 100 MB.
    from starlette.formparsers import MultiPartParser

    assert MultiPartParser.spool_max_size >= 100 * 1024 * 1024


def test_a_hostile_worker_reaches_no_socket_and_no_other_process(tmp_path):
    """S17.5: code run under the worker's filter, as a file that took the worker would run it,
    tries to reach a local listener of its own account, to signal its parent and every
    process, and to make a socket of each family; each is refused, and the process itself goes
    on working."""
    import socket
    import subprocess
    import sys

    from moolakata import sandbox

    if not sandbox.ARCHES.get(__import__("platform").machine()):
        pytest.skip("no seccomp filter for this machine")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = tmp_path / "sock"
    listener.bind(str(path))
    listener.listen()
    code = f"""
import os, socket, threading
from moolakata import sandbox
assert sandbox.no_network()
def refused(fn):
    try:
        fn()
    except OSError:
        return True
    return False
assert refused(lambda: socket.socket(socket.AF_UNIX).connect({str(path)!r})), "local listener"
assert refused(lambda: socket.socket(socket.AF_INET)), "inet"
assert refused(lambda: socket.socket(socket.AF_INET6)), "inet6"
assert refused(lambda: socket.socket(socket.AF_NETLINK, socket.SOCK_RAW)), "netlink"
assert refused(lambda: socket.socketpair()), "a socket pair"
assert refused(lambda: os.kill(os.getppid(), 0)), "the parent"
assert refused(lambda: os.kill(-1, 0)), "every process"
assert refused(lambda: os.kill(0, 0)), "its process group"
os.kill(os.getpid(), 0)
t = threading.Thread(target=lambda: None)
t.start()
t.join()
print("held")
"""
    try:
        r = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
        )
    finally:
        listener.close()
    assert r.returncode == 0 and r.stdout.strip() == "held", r.stderr


def _judged(program: bytes, arch: int, nr: int, arg0: int = 0) -> int:
    """What a classic BPF seccomp `program` returns for one call: its loads, equality and
    at-or-above jumps, and returns, the only instructions the filter uses."""
    import struct

    data = struct.pack("<iIQQ", nr, arch, 0, arg0)
    code = [struct.unpack("HBBI", program[i : i + 8]) for i in range(0, len(program), 8)]
    pc, acc = 0, 0
    while True:
        op, jt, jf, k = code[pc]
        if op == 0x20:  # load a word of the call's data
            acc = struct.unpack_from("<I", data, k)[0]
        elif op in (0x15, 0x35):  # jump if equal, jump if at or above
            hit = acc == k if op == 0x15 else acc >= k
            pc += jt if hit else jf
        elif op == 0x06:
            return k
        else:
            raise AssertionError(f"instruction {op:#x}")
        pc += 1


def test_the_filter_judges_only_native_calls_and_refuses_x32_ones():
    """S9.8.4.2: a call of the x32 ABI comes with x86_64's architecture and its number's bit 30
    set; it is refused, so `socket` through that entry is refused as the native one is."""
    import errno

    from moolakata import sandbox

    deny = sandbox.SECCOMP_RET_ERRNO | errno.EPERM
    allow = sandbox.SECCOMP_RET_ALLOW
    x86 = sandbox.ARCHES["x86_64"]
    program = sandbox._filter(x86, 77)
    arch = x86["arch"]
    assert _judged(program, arch, 41) == deny, "socket"
    assert _judged(program, arch, 0x40000000 | 41) == deny, "socket through x32"
    assert _judged(program, arch, 0x40000000) == deny, "x32's first call"
    assert _judged(program, arch, 0x3FFFFFFF) == allow, "a native number below x32's"
    assert _judged(program, arch, 0) == allow, "read"
    assert _judged(program, arch, 62, 77) == allow, "a signal to itself"
    assert _judged(program, arch, 62, 78) == deny, "a signal to another"
    assert _judged(program, 0x40000003, 41) == deny, "another architecture"
    # aarch64 has no such entry: its numbers are judged as they are.
    arm = sandbox.ARCHES["aarch64"]
    program = sandbox._filter(arm, 77)
    assert _judged(program, arm["arch"], 198) == deny, "socket"
    assert _judged(program, arm["arch"], 129, 77) == allow, "a signal to itself"
    assert _judged(program, arm["arch"], 0x40000000) == allow


def test_the_quick_worker_answering_an_error_or_nothing_is_told_as_the_reader_tells_it(
    monkeypatch,
):
    """S9.8.4.2: the worker's error is the reader's words; a thumbnail it can't draw, or one
    not an image, is none; a photo it can't show, or a text layer out of shape, is refused."""
    import base64

    from moolakata import parsing
    from moolakata.importers import parsed

    def answering(answer):
        monkeypatch.setattr(parsing, "_call", lambda op, data, **k: answer)

    answering({"error": "the file is damaged"})
    assert parsing.sandbox() is None
    assert parsing.thumbnail(b"", "image/png", user="User_a") is None
    for read in (
        lambda: parsing.as_jpeg(b"", user="User_a"),
        lambda: parsing.text_layer(b"", user="User_a"),
        lambda: parsing.propose_csv(b"", user="User_a"),
        lambda: parsing.read_csv(b"", {}, user="User_a"),
    ):
        with pytest.raises(parsed.ReadError, match="the file is damaged"):
            read()
    for webp in (7, "A" * (3 * 1024 * 1024)):  # not text, or past the largest a thumbnail is
        answering({"webp": webp})
        assert parsing.thumbnail(b"", "image/png", user="User_a") is None
    jpeg = b"\xff\xd8\xff\xe0 a photo"
    answering({"jpeg": base64.b64encode(jpeg).decode()})
    assert parsing.as_jpeg(b"", user="User_a") == jpeg
    answering({})
    assert parsing.thumbnail(b"", "image/png", user="User_a") is None, "none drawn"
    with pytest.raises(parsed.ReadError, match="the photo can't be shown"):
        parsing.as_jpeg(b"", user="User_a")
    assert parsing.text_layer(b"", user="User_a") is None, "no text layer worth reading"
    for lines in ("one line", ["x" * 2001], [None]):
        answering({"lines": lines})
        with pytest.raises(parsed.ReadError, match="the reader answered out of turn"):
            parsing.text_layer(b"", user="User_a")


def test_a_new_data_directory_stops_the_quick_worker_kept_out_of_the_old(
    no_process, monkeypatch, tmp_path
):
    """S9.8.4.2: the worker's sandbox keeps it out of the data directory it was started with:
    a new one, and the next file gets a worker kept out of that."""
    from moolakata import parsing

    monkeypatch.setattr(parsing, "_data_dir", parsing._data_dir)
    parsing.text_layer(b"%PDF", user="User_a")
    first = parsing._worker
    parsing.use_data_dir(tmp_path)
    assert parsing._worker is None
    parsing.text_layer(b"%PDF", user="User_a")
    assert parsing._worker is not first and parsing._worker.data_dir == tmp_path
