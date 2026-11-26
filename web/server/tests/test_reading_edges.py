"""The reading queue's and its worker's edges (requirements S9.8.4, S9.8.7): a worker that
never says it is ready, answers out of turn, too much or nothing, or passes its memory; the
queue's threads, and a receipt deleted, pruned, turned off or its file lost as it is read. A
worker here is a pair of pipes with its answers written ahead, never a process."""

import io
import json
import os
import subprocess

import pytest
from conftest import make_user, sign_in
from test_receipts import png, upload

from moolakata import settings
from moolakata.receipts import reading
from moolakata.receipts.reading import MAX_ANSWER, MEMORY_CAP, Reader, Worker
from moolakata.store.entities.receipts import Receipt

READY = {"ready": True, "seccomp": True, "landlock": True, "core": True}


def frame(value) -> bytes:
    data = json.dumps(value).encode()
    return len(data).to_bytes(4, "big") + data


class Piped:
    """A worker process as Worker sees it: real pipes, with what it says written ahead and its
    end closed after, so reading past it is the end of its output."""

    def __init__(self, says: bytes):
        r_in, w_in = os.pipe()
        r_out, w_out = os.pipe()
        os.write(w_out, says)
        os.close(w_out)
        self.drain = r_in  # what the worker would read, left unread
        self.pid = os.getpid()
        self.stdin = os.fdopen(w_in, "wb")
        self.stdout = os.fdopen(r_out, "rb")
        self.exited = None
        self.killed = False

    def poll(self):
        return self.exited

    def kill(self):
        self.killed = True
        self.exited = -9

    def wait(self, timeout=None):
        return self.exited


@pytest.fixture
def started(monkeypatch):
    """`started(says)`: the next worker started is a Piped saying that."""
    made = []

    def start(says: bytes):
        monkeypatch.setattr(
            subprocess, "Popen", lambda *a, **k: made.append(Piped(says)) or made[-1]
        )

    yield start
    for p in made:
        os.close(p.drain)
        for f in (p.stdin, p.stdout):
            f.close() if not f.closed else None


def test_a_worker_that_never_says_it_is_ready_couldnt_start(started):
    started(frame({"ready": False}))
    w = Worker()
    assert w.call("text", b"x", user="User_a") == {"error": "the reader couldn't start"}
    assert w.proc is None and w.user is None


@pytest.mark.parametrize(
    ("then", "said"),
    [
        (frame([1, 2]), "the reader answered out of turn"),
        ((MAX_ANSWER + 1).to_bytes(4, "big"), "the reader stopped while reading it"),
        (b"", "the reader stopped while reading it"),  # its output ends
        (b"\x00\x00\x00\x09{", "the reader stopped while reading it"),  # cut short
    ],
    ids=["not an object", "too long", "nothing", "cut short"],
)
def test_an_answer_out_of_shape_stops_the_worker(started, then, said):
    started(frame(READY) + then)
    w = Worker()
    assert w.call("text", b"x", user="User_a") == {"error": said}
    assert w.proc is None, "stopped, a new one started for the next job"


def test_a_workers_own_refusal_is_told_in_at_most_300_characters(started):
    started(frame(READY) + frame({"error": "x" * 500}))
    w = Worker()
    try:
        assert w.call("text", b"x", user="User_a") == {"error": "x" * 300}
        assert w.proc is not None, "a refusal leaves it running"
        assert w.state == {"seccomp": True, "landlock": True, "core": True}
    finally:
        w.stop()


@pytest.mark.parametrize("sending", [True, False], ids=["sending", "waiting"])
def test_a_worker_past_its_memory_is_stopped(started, monkeypatch, sending):
    """S9.8.4.3: its resident memory is watched while the job is sent and while its answer is
    awaited."""
    # Waiting, nothing is answered: an answer written ahead is read with the hello.
    started(frame(READY) + (frame({"lines": None}) if sending else b""))
    w = Worker()
    w._start()
    monkeypatch.setattr(reading, "resident", lambda pid: MEMORY_CAP + 1)
    if not sending:
        monkeypatch.setattr(Worker, "_send", lambda self, data, deadline: None)
    w.user = "User_a"
    assert w.call("text", b"x", user="User_a") == {
        "error": "it needed more memory than the reader may use"
    }
    assert w.proc is None


def test_a_worker_that_has_ended_is_not_killed_again(started):
    started(frame(READY))
    w = Worker()
    w._start()
    proc = w.proc
    proc.exited = 0
    w.stop()
    assert not proc.killed and proc.stdin.closed and proc.stdout.closed


def test_a_processs_memory_is_read_from_proc_or_is_none(monkeypatch):
    assert reading.resident(os.getpid()) > 0
    assert reading.resident(2**31 - 1) == 0, "no such process"
    monkeypatch.setattr(reading, "open", lambda path: io.StringIO("Name:\tx\n"), raising=False)
    assert reading.resident(os.getpid()) == 0, "a process with no resident set"


# ---------- the queue ----------


@pytest.fixture
def jane(server):
    make_user(server, "jane")
    return sign_in(server, "jane")


def reads(lines):
    """A worker's read that answers these lines, as read from a text layer."""
    return lambda data, media, *a, user, check=False: ("ok", lines, "text", "e", None)


def test_jobs_at_a_time_come_from_the_reader_or_the_setting(server):
    assert Reader(server, workers=2)._jobs_at_a_time() == 2
    assert Reader(server)._jobs_at_a_time() == 1, "Settings › Receipts' default"


def test_starting_queues_what_waits_and_starts_once(server, jane, monkeypatch):
    rid = upload(jane, png((3, 3, 3))).json()["id"]
    reader = Reader(server, workers=1)
    monkeypatch.setattr(Reader, "resize", lambda self: None)
    reader.start()
    assert reader.jobs.get_nowait()[2] == rid
    reader.threads = ["one running"]
    reader.start()
    assert reader.jobs.empty(), "started already: nothing queued again"


def test_a_stopping_reader_starts_no_thread(server):
    reader = Reader(server, workers=2)
    reader.stopping.set()
    reader.resize()
    assert reader.threads == [] and reader.size == 0


def test_a_failed_read_is_logged_and_the_loop_goes_on(server, monkeypatch):
    reader = Reader(server, workers=1)
    said = []
    monkeypatch.setattr(reading.log, "exception", lambda msg, *a: said.append(msg))

    def broken(rid, worker):
        # The stop is taken before any receipt, so it is put once this one is in hand.
        reader.jobs.put((reading._STOP, 99, None))
        raise RuntimeError("broken")

    monkeypatch.setattr(reader, "read_one", broken)
    reader.queue("Rcpt_one")
    reader._loop(Worker())
    assert said == ["reading a receipt failed"]
    assert reader.jobs.empty(), "read to the stop"
    reader.queue("Rcpt_two")
    reader.stopping.set()
    reader._loop(Worker())
    assert not reader.jobs.empty(), "a stopped reader takes nothing more"


def status(server, rid):
    with server.db.read(unscoped="test") as s:
        r = s.get(Receipt, rid)
        return r.readStatus, r.readError


def test_a_receipt_gone_or_read_already_is_passed_over(server, jane):
    w = Worker()
    w.read = reads(["TOTAL 1.00"])
    Reader(server, workers=1).read_one("Rcpt_00000000000000000000000000", w)
    rid = upload(jane, png((4, 4, 4))).json()["id"]
    Reader(server, workers=1).read_one(rid, w)
    assert status(server, rid) == ("read", None)
    w.read = None  # never asked again
    Reader(server, workers=1).read_one(rid, w)
    assert status(server, rid) == ("read", None)


def test_reading_turned_off_before_its_turn_leaves_it_off(server, jane):
    rid = upload(jane, png((5, 5, 5))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        settings.put(s, "readReceipts", False, None)
    Reader(server, workers=1).read_one(rid, None)
    assert status(server, rid) == ("off", None)


def test_a_receipt_whose_file_is_lost_fails_saying_so(server, jane):
    from moolakata.receipts import file_path

    rid = upload(jane, png((6, 6, 6))).json()["id"]
    with server.db.read(unscoped="test") as s:
        file_path(server.config.receipts_dir, s.get(Receipt, rid).fileId).unlink()
    Reader(server, workers=1).read_one(rid, Worker())
    assert status(server, rid) == ("failed", "its file can't be opened (FileNotFoundError)")


def test_a_receipt_the_upload_couldnt_draw_is_drawn_as_it_is_read(server, jane, monkeypatch):
    from moolakata import parsing

    rid = upload(jane, png((7, 7, 7))).json()["id"]
    with server.db.tx(unscoped="test") as s:
        s.get(Receipt, rid).thumbnail = None
    monkeypatch.setattr(parsing, "thumbnail", lambda data, media, user: b"RIFF....WEBP")
    w = Worker()
    w.read = reads(["TOTAL 1.00"])
    Reader(server, workers=1).read_one(rid, w)
    with server.db.read(unscoped="test") as s:
        assert s.get(Receipt, rid).thumbnail == b"RIFF....WEBP"


def test_a_receipt_deleted_or_pruned_mid_read_keeps_what_was_read_unsearched(server, jane):
    """S9.7, S14.10.5: deleted as it is read, its reading is kept on its row, never found by
    search; pruned, its reading is kept and found."""
    from moolakata.receipts import retention

    gone = upload(jane, png((8, 8, 8))).json()["id"]
    pruned = upload(jane, png((9, 9, 9))).json()["id"]

    def deleting(rid):
        def read(data, media, *a, user, check=False):
            files = set()
            with server.db.tx(unscoped="test") as s:
                r = s.get(Receipt, rid)
                if rid == gone:
                    r.mark_deleted(None)
                else:
                    files = retention.mark_pruned(s, [r], r.ownerId)
            retention.remove_pruned(server, files)
            return ("ok", [f"QUINCE {rid[-4:]}", "TOTAL 2.00"], "text", "e", None)

        return read

    for rid in (gone, pruned):
        w = Worker()
        w.read = deleting(rid)
        Reader(server, workers=1).read_one(rid, w)
        assert status(server, rid) == ("read", None)
    with server.db.read(unscoped="test") as s:
        assert reading.search(s, "quince") == {pruned}


def test_a_reading_with_no_merchant_suggests_no_payee(server, jane):
    rid = upload(jane, png((1, 1, 9))).json()["id"]
    w = Worker()
    w.read = reads(["12.50"])
    Reader(server, workers=1).read_one(rid, w)
    got = jane.get(f"/ui/api/receipts/{rid}").json()
    assert (got["payee"], got["amount"], got["filled"]) == (None, "12.50", ["amount"])


def test_a_search_of_quotes_alone_finds_nothing(server):
    with server.db.read(unscoped="test") as s:
        assert reading.search(s, '"" "') == set()
