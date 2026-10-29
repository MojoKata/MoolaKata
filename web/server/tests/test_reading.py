"""Reading receipts (requirements S9.8): the field parser on its own, then RapidOCR in its
worker process on drawn receipts."""

import datetime as dt
import io
import json
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change
from PIL import Image
from test_receipts import upload

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
        status, lines, method, engine = w.read(_png(img), "image/png")
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


def test_a_broken_file_fails_with_a_reason_and_the_worker_lives_on():
    w = Worker()
    try:
        assert w.read(b"\x89PNG\r\n\x1a\nbroken", "image/png")[0] == "error"
        status = w.read(b"%PDF-1.4 nothing", "application/pdf")
        assert status == ("error", "the PDF can't be opened")
    finally:
        w.stop()


def test_a_worker_past_its_time_is_stopped():
    w = Worker()
    try:
        w.read(_png(draw(["warm up"])), "image/png")
        out = w.read(_png(draw(["X" * 30] * 60, width=1600)), "image/png", limit=0.01)
        assert out == ("error", "it took longer than 0 seconds")
        assert w.proc is None
        assert w.read(_png(draw(["TOTAL 1.00"])), "image/png")[0] == "ok", "a new one starts"
    finally:
        w.stop()


def test_reading_fills_empty_fields_never_typed_ones(server):
    make_user(server, "alice")
    c = sign_in(server, "alice")
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
    assert admin_client.patch("/ui/api/settings", json={"readReceipts": False}).status_code == 200
    make_user(server, "alice")
    c = sign_in(server, "alice")
    rid = upload(c, _png(draw(["TOTAL 1.00"]))).json()["id"]
    assert c.get(f"/ui/api/receipts/{rid}").json()["readStatus"] == "off"
    q = admin_client.get("/ui/api/settings/receipts").json()
    assert q["waiting"] == 0


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
                out = w.read(_png(img), "image/png")
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
    assert w.read(b"", "image/png") == ("error", "the reader answered out of turn")
    monkeypatch.setattr(parsing, "_call", lambda op, data, **k: {"webp": "not base64!"})
    assert parsing.thumbnail(b"", "image/png") is None
    monkeypatch.setattr(parsing, "_call", lambda op, data, **k: {"jpeg": "aGVsbG8="})
    with pytest.raises(parsed.ReadError):
        parsing.as_jpeg(b"")
    for bad in (
        None,
        {"format": "ofx", "rows": [{"date": "2026-13-01", "kind": "deposit", "amount": "1"}]},
        {"format": "ofx", "rows": [{"date": "2026-01-01", "kind": "deposit", "amount": "NaN"}]},
        {"format": "exe", "rows": []},
    ):
        monkeypatch.setattr(parsing, "_call", lambda op, data, b=bad, **k: {"parsed": b})
        with pytest.raises(parsed.ReadError):
            parsing.read_ofx(b"")


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
