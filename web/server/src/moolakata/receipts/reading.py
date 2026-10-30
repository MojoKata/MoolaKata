"""The reading queue (requirements S9.8.4): receipts are read in the background, never in a
request, by a separate worker process, so a hostile or broken file can't take the server down.

- An upload marks its receipt *waiting* and answers at once; the reader picks it up.
- Jobs run one at a time by default (Settings › Receipts), each in its own worker process
  (worker.py, its own sandbox) with ONNX Runtime held to 2 threads, a lower CPU priority, a
  memory cap and 60 seconds per receipt. A worker that crashes or runs out of time is stopped
  and a new one started; the receipt is marked *couldn't read it*, with the reason, and stays
  usable by hand.
- What is read fills the receipt's empty fields as suggestions, marked as read from it; a value
  a person entered is never overwritten. The full text goes into the database and its search
  index, never into Activity or the log.
"""

import contextlib
import datetime as dt
import json
import logging
import os
import queue
import select
import subprocess
import sys
import threading
import time
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import text

from .. import clock, settings
from ..store.entities.accounts import Account
from ..store.entities.receipts import Receipt
from . import parser

log = logging.getLogger("moolakata.receipts")

TIME_LIMIT = 60
STATEMENT_TIME_LIMIT = 300  # a scanned statement's every page, at about 10 s a page
MEMORY_CAP = 1536 * 1024 * 1024
FIELDS = ("date", "amount", "payee")


def resident(pid: int) -> int:
    """A process's resident memory in bytes, from /proc; 0 where there is none."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


MAX_ANSWER = 64 * 1024 * 1024
MAX_LINES = 20_000
MAX_LINE = 2_000


class Worker:
    """One worker process (worker.py), started when first needed and again after a crash or a
    timeout: no environment, no file descriptor but its pipes, and length-prefixed JSON both
    ways, never pickles (S9.8.4.2). `state` is what its sandbox holds, as it said at start."""

    def __init__(self, data_dir=None) -> None:
        self.proc = None
        self.data_dir = data_dir
        self.state: dict | None = None
        self._buf = b""

    def _start(self) -> None:
        # This Python, the worker's module, and the data directory its sandbox refuses: no
        # input from anyone reaches the command line.
        self.proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-I", "-m", "moolakata.receipts.worker", str(self.data_dir or "")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={},
            close_fds=True,
        )
        self._buf = b""
        hello = self._recv(time.monotonic() + 120)
        if not isinstance(hello, dict) or hello.get("ready") is not True:
            raise OSError("the reader didn't start")
        self.state = {k: bool(hello.get(k)) for k in ("seccomp", "landlock", "core")}

    def _exactly(self, n: int, deadline: float) -> bytes:
        fd = self.proc.stdout.fileno()
        # poll, not select: select refuses a descriptor past 1023, which a busy server's pipes
        # reach, and the reader would never start.
        waiting = select.poll()
        waiting.register(fd, select.POLLIN)
        while len(self._buf) < n:
            if time.monotonic() > deadline:
                raise TimeoutError
            if resident(self.proc.pid) > MEMORY_CAP:
                raise MemoryError
            if waiting.poll(250):
                chunk = os.read(fd, 1 << 16)
                if not chunk:
                    raise EOFError
                self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _recv(self, deadline: float):
        n = int.from_bytes(self._exactly(4, deadline), "big")
        if n > MAX_ANSWER:
            raise ValueError("an answer larger than allowed")
        return json.loads(self._exactly(n, deadline))

    def call(self, op: str, data: bytes = b"", limit: float = TIME_LIMIT, **params) -> dict:
        """One job; its answer as the worker sent it, to be checked by the caller, or `error`
        with the reason."""
        if self.proc is None or self.proc.poll() is not None:
            try:
                self._start()
            except OSError, ValueError, EOFError, TimeoutError, MemoryError:
                self.stop()
                return {"error": "the reader couldn't start"}
        head = json.dumps({"op": op, **params, "length": len(data)}).encode()
        try:
            stdin = self.proc.stdin
            stdin.write(len(head).to_bytes(4, "big") + head + len(data).to_bytes(4, "big"))
            stdin.write(data)
            stdin.flush()
            out = self._recv(time.monotonic() + limit)
        except TimeoutError:
            self.stop()
            return {"error": f"it took longer than {int(limit)} seconds"}
        except MemoryError:
            self.stop()
            return {"error": "it needed more memory than the reader may use"}
        except EOFError, BrokenPipeError, OSError, ValueError:
            self.stop()
            return {"error": "the reader stopped while reading it"}
        if not isinstance(out, dict):
            self.stop()
            return {"error": "the reader answered out of turn"}
        if "error" in out:
            return {"error": str(out["error"])[:300]}
        return out

    def read(
        self, data: bytes, media: str, limit: float = TIME_LIMIT, pages: int | None = None
    ) -> tuple:
        """A receipt or statement read: ("ok", lines, method, engine), or ("error", why). A
        statement asks for more pages than a receipt's three, with a longer limit."""
        extra = {"pages": pages} if pages else {}
        out = self.call("read", data, limit, media=media, **extra)
        if "error" in out:
            return ("error", out["error"])
        lines, method, engine = out.get("lines"), out.get("method"), out.get("engine")
        if (
            not isinstance(lines, list)
            or len(lines) > MAX_LINES
            or not all(isinstance(x, str) and len(x) <= MAX_LINE for x in lines)
            or method not in ("text", "ocr")
            or not isinstance(engine, str)
            or len(engine) > 200
        ):
            self.stop()
            return ("error", "the reader answered out of turn")
        return ("ok", lines, method, engine)

    def stop(self) -> None:
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.kill()
            with contextlib.suppress(Exception):
                self.proc.wait(5)
            for f in (self.proc.stdin, self.proc.stdout):
                with contextlib.suppress(Exception):
                    f.close()
        self.proc = None
        self._buf = b""


class Reader:
    """The queue and its threads, one per job allowed at a time."""

    def __init__(self, server, workers: int | None = None) -> None:
        self.server = server
        self.jobs: queue.Queue[str | None] = queue.Queue()
        self.threads: list[threading.Thread] = []
        self.workers: list[Worker] = []
        self.count = workers
        self.stopping = threading.Event()
        self.last_run: dt.datetime | None = None

    def start(self) -> None:
        if self.threads:
            return
        with self.server.db.read() as s:
            n = self.count or settings.get(s, "receiptReadJobs")
            pending = [
                rid
                for (rid,) in s.execute(
                    text(
                        "SELECT id FROM \"Receipt\" WHERE \"readStatus\" IN ('waiting', 'reading')"
                        ' AND NOT deleted ORDER BY "createdAt"'
                    )
                )
            ]
        for i in range(n):
            w = Worker(self.server.config.data_dir)
            t = threading.Thread(target=self._loop, args=(w,), daemon=True, name=f"mk-read-{i}")
            self.workers.append(w)
            self.threads.append(t)
            t.start()
        for rid in pending:
            self.jobs.put(rid)

    def stop(self) -> None:
        self.stopping.set()
        for _ in self.threads:
            self.jobs.put(None)
        for w in self.workers:
            w.stop()

    def queue(self, receipt_id: str) -> None:
        self.jobs.put(receipt_id)

    def waiting(self) -> int:
        return self.jobs.qsize()

    def _loop(self, worker: Worker) -> None:
        while not self.stopping.is_set():
            rid = self.jobs.get()
            if rid is None:
                return
            try:
                self.read_one(rid, worker)
            except Exception:
                log.exception("reading a receipt failed")

    def read_one(self, rid: str, worker: Worker) -> None:
        from . import whole

        srv = self.server
        with srv.db.tx() as s:
            r = s.get(Receipt, rid)
            if (
                r is None
                or r.deleted
                or r.filePrunedAt is not None
                or r.readStatus not in ("waiting", "reading")
            ):
                return
            if not settings.get(s, "readReceipts"):
                r.readStatus = "off"
                return
            r.readStatus = "reading"
            media = r.mediaType
            owner = r.ownerId
            file = SimpleNamespace(fileId=r.fileId, sha256=r.sha256)
        srv.events.publish("receipt", {"id": rid}, users=[owner])
        try:
            data = whole(srv, file)
            outcome = worker.read(data, media)
        except Exception as e:
            outcome = ("error", f"its file can't be opened ({type(e).__name__})")
        self.last_run = clock.now()
        with srv.db.tx() as s:
            r = s.get(Receipt, rid)
            if r is None:
                return
            if outcome[0] == "ok":
                _, lines, method, engine = outcome
                save_reading(s, r, lines, method, engine)
            else:
                r.readStatus, r.readError, r.readAt = "failed", outcome[1], clock.now()
        srv.events.publish("receipt", {"id": rid}, users=[owner])


def _not_before(s, r: Receipt):
    """A receipt's date can't be before the opening of the accounts its owner keeps."""
    from sqlalchemy import func, select

    return s.scalar(
        select(func.min(Account.openingDate)).where(
            Account.ownerId == r.ownerId, Account.openingDate.is_not(None)
        )
    )


def save_reading(s, r: Receipt, lines: list[str], method: str, engine: str) -> None:
    """Store what was read, and fill the fields nobody typed (S9.8.1)."""
    found = parser.parse(lines, clock.today(), _not_before(s, r))
    r.text = "\n".join(lines)
    r.readMethod, r.readEngine = method, engine
    r.readStatus, r.readError, r.readAt = "read", None, clock.now()
    r.suggested = json.dumps(found.as_dict())
    filled = set(json.loads(r.filled or "[]"))
    values = {
        "date": found.date.value if found.date else None,
        "amount": found.total.value if found.total else None,
        "payee": found.merchant.value if found.merchant else None,
    }
    if values["payee"]:
        # The merchant as the uploader's payee rules show it (S2.7.7, S9.8.2.5.3).
        from ..store.repos.rules import Rules

        values["payee"] = Rules(s, r.ownerId).rename(values["payee"])
    for f in FIELDS:
        empty = getattr(r, f) in (None, "")
        if (empty or f in filled) and values[f] is not None:
            v = values[f]
            setattr(r, f, Decimal(v) if f == "amount" else v)
            filled.add(f)
    r.filled = json.dumps(sorted(filled))
    index(s, r)


def index(s, r: Receipt) -> None:
    s.execute(text('DELETE FROM "ReceiptSearch" WHERE "receiptId" = :id'), {"id": r.id})
    if r.text and not r.deleted:
        s.execute(
            text('INSERT INTO "ReceiptSearch" ("receiptId", text) VALUES (:id, :t)'),
            {"id": r.id, "t": r.text},
        )


def search(s, query: str) -> set[str]:
    """Receipt ids whose text has every word of the query (`blue bottle`, `142.18`)."""
    words = [w.replace('"', "") for w in query.split() if w.strip('"')]
    if not words:
        return set()
    match = " ".join(f'"{w}"' for w in words)
    return {
        rid
        for (rid,) in s.execute(
            text('SELECT "receiptId" FROM "ReceiptSearch" WHERE "ReceiptSearch" MATCH :q'),
            {"q": match},
        )
    }


def read_again(s, r: Receipt) -> None:
    """Queue it again: only empty or suggested fields will be replaced (S9.8.6)."""
    r.readStatus, r.readError = "waiting", None
