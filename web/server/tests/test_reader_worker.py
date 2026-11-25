"""The reader's worker (requirements S9.8.4): its frames, its jobs and its loop, run in the
test's own process on small real files. The sandboxed process itself, which no coverage
follows, is tested in test_reading."""

import base64
import io
import json
import struct
import sys
import zlib
from pathlib import Path

import pytest
from PIL import Image
from test_reading import text_pdf
from test_receipts import png

from moolakata.receipts import ocr, worker

FIXTURES = Path(__file__).parent / "fixtures" / "imports"


def frame(data: bytes) -> bytes:
    return len(data).to_bytes(4, "big") + data


def answers(raw: bytes) -> list[dict]:
    f, out = io.BytesIO(raw), []
    while (got := worker.read_frame(f, worker.MAX_HEAD)) is not None:
        out.append(json.loads(got))
    return out


def scanned_pdf() -> bytes:
    """A one-page PDF with no text layer: a scan."""
    out = io.BytesIO()
    Image.new("RGB", (60, 80), (255, 255, 255)).save(out, "PDF")
    return out.getvalue()


def huge_png(w: int, h: int) -> bytes:
    """A PNG's head claiming w × h pixels, with no pixels behind it."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    head = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + head + chunk(b"IEND", b"")


def test_a_frame_is_its_length_then_its_bytes():
    out = io.BytesIO()
    worker.write_frame(out, b"hello")
    assert out.getvalue() == b"\x00\x00\x00\x05hello"
    assert worker.read_frame(io.BytesIO(out.getvalue()), 5) == b"hello"
    assert worker.read_frame(io.BytesIO(b""), 5) is None, "the end"
    assert worker.read_frame(io.BytesIO(b"\x00\x00"), 5) is None, "a head cut short ends it"
    with pytest.raises(ValueError, match="a frame larger than allowed"):
        worker.read_frame(io.BytesIO(out.getvalue()), 4)
    with pytest.raises(ValueError, match="a frame cut short"):
        worker.read_frame(io.BytesIO(b"\x00\x00\x00\x05hel"), 5)


def test_a_pdf_with_a_text_layer_is_read_and_its_lines_answered():
    lines = ["CORNER STORE", "OCT 9, 2026", "TOTAL 72.34"]
    got = worker.handle({"op": "read", "media": "application/pdf"}, text_pdf(lines))
    assert got == {
        "lines": lines,
        "method": "text",
        "engine": "pypdfium2 text layer",
        "check": None,
    }


@pytest.mark.parametrize(
    ("pages", "used"),
    [(None, 3), (0, 3), (1, 1), (30, 30), (31, 3), ("2", 3), (True, 3), (2.0, 3)],
)
def test_a_read_asks_for_whole_pages_within_a_statements_else_a_receipts(monkeypatch, pages, used):
    """S9.8.2.2: a statement's job asks for up to 30 pages; any other count is a receipt's 3."""
    seen = []

    def read(data, media, pages, check):
        seen.append((media, pages, check))
        return ocr.Read(["x"], "ocr", "e")

    monkeypatch.setattr(ocr, "read", read)
    job = {"op": "read", "pages": pages, "check": True}
    assert worker.handle(job, b"")["lines"] == ["x"]
    worker.handle({"op": "read", "media": "image/png", "check": "yes"}, b"")
    assert seen == [("", used, True), ("image/png", 3, False)]


def test_the_text_job_gives_a_pdfs_text_layer_or_none():
    assert worker.handle({"op": "text"}, text_pdf(["ACME BANK STATEMENT 2026"])) == {
        "lines": ["ACME BANK STATEMENT 2026"]
    }
    assert worker.handle({"op": "text"}, scanned_pdf()) == {"lines": None}
    assert worker.handle({"op": "text"}, b"%PDF-1.4 broken") == {"error": "the PDF can't be opened"}


def test_a_thumbnail_and_a_photo_for_the_browser_are_answered_in_base64():
    webp = base64.b64decode(worker.handle({"op": "thumbnail", "media": "image/png"}, png())["webp"])
    assert webp[:4] == b"RIFF" and webp[8:12] == b"WEBP"
    pdf = worker.handle({"op": "thumbnail", "media": "application/pdf"}, scanned_pdf())
    assert base64.b64decode(pdf["webp"])[8:12] == b"WEBP"
    assert worker.handle({"op": "thumbnail"}, b"not a picture") == {"webp": None}
    jpeg = base64.b64decode(worker.handle({"op": "jpeg"}, png())["jpeg"])
    assert jpeg[:3] == b"\xff\xd8\xff"


def test_an_image_past_the_pixel_cap_is_refused_in_words_safe_to_show():
    """S9.8.4.3: its head is read, never its pixels."""
    with pytest.warns(Image.DecompressionBombWarning):
        got = worker.handle({"op": "jpeg"}, huge_png(10_000, 5_000))
    assert got == {"error": "The image is larger than 40 million pixels."}


@pytest.mark.filterwarnings("ignore:Encountered private extension tag")
def test_an_import_is_parsed_in_the_worker_and_answered_as_json():
    qfx = (FIXTURES / "umb-checking.qfx").read_bytes()
    parsed = worker.handle({"op": "ofx"}, qfx)["parsed"]
    assert (parsed["format"], parsed["institution"], len(parsed["rows"])) == ("ofx", "UMB", 8)
    got = worker.handle({"op": "ofx"}, b"not an ofx")
    assert got == {"error": "This is not an OFX or QFX file MoolaKata can read (OFXHeaderError)."}
    data = (FIXTURES / "chase-card.csv").read_bytes()
    proposal = worker.handle({"op": "csv-propose"}, data)["proposal"]
    assert proposal["headers"][0] == "Transaction Date"
    assert worker.handle({"op": "csv-propose", "trades": True}, data)["proposal"]["headers"]
    parsed = worker.handle({"op": "csv", "mapping": proposal["mapping"]}, data)["parsed"]
    assert (parsed["format"], len(parsed["rows"])) == ("csv", 6)
    assert worker.handle({"op": "csv"}, data) == {"error": "Choose the date column."}


@pytest.mark.parametrize(
    ("raised", "said"),
    [
        (MemoryError, "it needed more memory than the reader may use"),
        (KeyError("x"), "the reader failed (KeyError)"),
    ],
)
def test_a_job_that_breaks_answers_why_never_a_trace(monkeypatch, raised, said):
    def read(*a):
        raise raised

    monkeypatch.setattr(ocr, "read", read)
    assert worker.handle({"op": "read"}, b"") == {"error": said}


def test_an_unknown_job_is_answered_so():
    assert worker.handle({"op": "format-disk"}, b"") == {"error": "no such job: 'format-disk'"}
    assert worker.handle({}, b"") == {"error": "no such job: None"}


def test_the_self_test_reports_what_its_process_may_do(tmp_path):
    """S9.8.4.2: unsandboxed, as here, everything is allowed; the sandbox's own refusals are
    test_reading's."""
    got = worker.handle({"op": "selftest", "path": str(tmp_path)}, b"")
    assert (got["network"], got["local"], got["signal"], got["path"]) == (True, True, True, True)
    assert got["environment"] == sorted(got["environment"])
    assert worker.handle({"op": "selftest", "path": str(tmp_path / "none")}, b"")["path"] is False
    assert worker.handle({"op": "selftest"}, b"")["path"] is False


def test_the_self_test_reports_each_refusal(monkeypatch):
    """What a sandbox refuses raises OSError, and is reported as not allowed."""
    import os
    import socket

    def refused(*a):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(socket, "socket", refused)
    monkeypatch.setattr(socket, "socketpair", refused)
    monkeypatch.setattr(os, "kill", refused)
    got = worker.handle({"op": "selftest"}, b"")
    assert (got["network"], got["local"], got["signal"]) == (False, False, False)


def test_the_libraries_are_loaded_before_the_lock_down():
    worker._preload()
    assert "pypdfium2" in sys.modules and "ofxtools.Parser" in sys.modules


def test_the_lock_down_reads_only_the_systems_and_pythons_files(monkeypatch, tmp_path):
    """S9.8.4.2: the sandbox's three parts, the data directory refused; what each holds is
    what the process says when ready."""
    from moolakata import sandbox

    calls = {}
    monkeypatch.setattr(sandbox, "not_dumpable", lambda: True)
    monkeypatch.setattr(sandbox, "no_network", lambda: False)

    def read_only(roots, writable, refuse):
        calls.update(roots=roots, writable=writable, refuse=refuse)
        return True

    monkeypatch.setattr(sandbox, "read_only", read_only)
    assert worker._lock_down(tmp_path) == {"seccomp": False, "landlock": True, "core": True}
    assert Path("/usr") in calls["roots"] and Path(sys.prefix) in calls["roots"]
    assert calls["roots"] == sorted(calls["roots"])
    assert (calls["writable"], calls["refuse"]) == ([Path("/dev")], tmp_path)


class Pipe(io.BytesIO):
    """A pipe's end that keeps what was written once closed."""

    def close(self):
        self.kept = self.getvalue()
        super().close()


def run_main(monkeypatch, sent: bytes, argv: list[str], nice=None):
    """The worker's loop over `sent` as its stdin: its exit code, what it answered, and the
    data directory it locked down."""
    import os

    inp, out = Pipe(sent), Pipe()
    locked = []
    monkeypatch.setenv("OMP_NUM_THREADS", "8")
    monkeypatch.setattr(worker, "_preload", lambda: None)
    monkeypatch.setattr(worker, "_lock_down", lambda d: locked.append(d) or {"seccomp": True})
    monkeypatch.setattr(os, "fdopen", lambda fd, mode: {0: inp, 1: out}[fd])
    monkeypatch.setattr(os, "nice", nice or (lambda n: n))
    code = worker.main(argv)
    assert os.environ["OMP_NUM_THREADS"] == "2"
    return code, answers(out.kept), locked


def test_the_loop_answers_ready_then_each_job_until_its_input_ends(monkeypatch, tmp_path):
    job = json.dumps({"op": "text", "length": 0}).encode()
    code, got, locked = run_main(
        monkeypatch, frame(job) + frame(b"") + frame(job) + frame(b""), ["worker", str(tmp_path)]
    )
    assert code == 0 and locked == [tmp_path]
    none = {"error": "the PDF can't be opened"}
    assert got == [{"ready": True, "seccomp": True}, none, none]


def test_the_loop_stops_at_a_frame_out_of_shape(monkeypatch):
    def refused(n):
        raise OSError("not allowed")

    job = json.dumps({"op": "text"}).encode()
    code, got, locked = run_main(monkeypatch, frame(job) + b"\x00\x00\x00\x09abc", ["worker"])
    assert code == 1 and locked == [None] and got == [{"ready": True, "seccomp": True}]
    code, _, locked = run_main(monkeypatch, frame(b"{"), ["worker", ""], nice=refused)
    assert code == 1 and locked == [None], "a frame that is no JSON, and nice refused"
