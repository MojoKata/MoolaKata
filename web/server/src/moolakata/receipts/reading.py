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
import itertools
import json
import logging
import os
import queue
import re
import select
import subprocess
import sys
import threading
import time
from decimal import Decimal
from types import SimpleNamespace

import sqlalchemy as sa
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
# Beside the suggested fields: the text layer's total and the scan's, when they disagree.
DISAGREE = "totalCheck"


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
AMOUNT = re.compile(r"-?\d{1,12}\.\d{2}")


def _a_check(found) -> bool:
    """The total against the scan as the worker answers it: two amounts, the scan's or none,
    and whether they agree."""
    return (
        isinstance(found, dict)
        and set(found) == {"text", "scan", "agrees"}
        and isinstance(found["text"], str)
        and AMOUNT.fullmatch(found["text"]) is not None
        and (found["scan"] is None or isinstance(found["scan"], str))
        and (found["scan"] is None or AMOUNT.fullmatch(found["scan"]) is not None)
        and isinstance(found["agrees"], bool)
    )


class Worker:
    """One worker process (worker.py), started when first needed and again after a crash or a
    timeout: no environment, no file descriptor but its pipes, and length-prefixed JSON both
    ways, never pickles (S9.8.4.2). `state` is what its sandbox holds, as it said at start.
    It is started again whenever the next file is another user's than the last, so a file
    that takes it over sees only its own user's files after it (S9.8.4.2)."""

    def __init__(self, data_dir=None) -> None:
        self.proc = None
        self.data_dir = data_dir
        self.state: dict | None = None
        self.user: str | None = None  # whose files it has read
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

    def _send(self, data: bytes, deadline: float) -> None:
        """Bytes into the worker's stdin under the job's deadline and memory watch: a worker
        that stops reading (a hostile file's code, a library wedged between jobs) is stopped
        when it passes, never waited on by its caller and the quick jobs behind it (S9.8.4.2)."""
        fd = self.proc.stdin.fileno()
        os.set_blocking(fd, False)
        # poll, not select, as in _exactly.
        ready = select.poll()
        ready.register(fd, select.POLLOUT)
        view = memoryview(data)
        while view:
            if time.monotonic() > deadline:
                raise TimeoutError
            if resident(self.proc.pid) > MEMORY_CAP:
                raise MemoryError
            if ready.poll(250):
                with contextlib.suppress(BlockingIOError):
                    view = view[os.write(fd, view[: 1 << 16]) :]

    def _recv(self, deadline: float):
        n = int.from_bytes(self._exactly(4, deadline), "big")
        if n > MAX_ANSWER:
            raise ValueError("an answer larger than allowed")
        return json.loads(self._exactly(n, deadline))

    def call(
        self,
        op: str,
        data: bytes = b"",
        limit: float = TIME_LIMIT,
        *,
        user: str | None = None,
        **params,
    ) -> dict:
        """One job; its answer as the worker sent it, to be checked by the caller, or `error`
        with the reason. `user` is whose file it is: another user's than the last is read by a
        fresh worker. Only a job with no file (the sandbox's self-test) goes without."""
        if user is not None and user != self.user:
            self.stop()
            self.user = user
        if self.proc is None or self.proc.poll() is not None:
            try:
                self._start()
            except OSError, ValueError, EOFError, TimeoutError, MemoryError:
                self.stop()
                return {"error": "the reader couldn't start"}
        head = json.dumps({"op": op, **params, "length": len(data)}).encode()
        # The limit counts from the job's start, its sending included.
        deadline = time.monotonic() + limit
        try:
            self._send(len(head).to_bytes(4, "big") + head + len(data).to_bytes(4, "big"), deadline)
            self._send(data, deadline)
            out = self._recv(deadline)
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
        self,
        data: bytes,
        media: str,
        limit: float = TIME_LIMIT,
        pages: int | None = None,
        *,
        user: str,
        check: bool = False,
    ) -> tuple:
        """A receipt or statement read: ("ok", lines, method, engine, check), or ("error",
        why). A statement asks for more pages than a receipt's three, with a longer limit; a
        receipt asks for its total to be checked against the scan (S9.8.2.1.1). `user` is
        whose file it is."""
        extra = {"pages": pages} if pages else {}
        if check:
            extra["check"] = True
        out = self.call("read", data, limit, user=user, media=media, **extra)
        if "error" in out:
            return ("error", out["error"])
        lines, method, engine = out.get("lines"), out.get("method"), out.get("engine")
        found = out.get("check")
        if (
            not isinstance(lines, list)
            or len(lines) > MAX_LINES
            or not all(isinstance(x, str) and len(x) <= MAX_LINE for x in lines)
            or method not in ("text", "ocr", "both")
            or not isinstance(engine, str)
            or len(engine) > 200
            or not (found is None or _a_check(found))
        ):
            self.stop()
            return ("error", "the reader answered out of turn")
        return ("ok", lines, method, engine, found)

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
        self.user = None
        self._buf = b""


# Taken from the reading queue before any receipt: the server stopping, then a thread let go
# when Jobs at a time is lowered. Receipts follow in the order they were queued.
_STOP, _RETIRE, _RECEIPT = 0, 1, 2


class Reader:
    """The queue and its threads, one per job allowed at a time: as many as Settings ›
    Receipts' Jobs at a time says, from the save that changes it (S9.8.7, R3.7)."""

    def __init__(self, server, workers: int | None = None) -> None:
        self.server = server
        self.jobs: queue.PriorityQueue[tuple[int, int, str | None]] = queue.PriorityQueue()
        self._order = itertools.count()
        self._lock = threading.Lock()
        self.threads: list[threading.Thread] = []
        self.workers: list[Worker] = []
        self.count = workers
        self.size = 0  # the threads asked for: those running, less those told to go
        self.stopping = threading.Event()
        self.last_run: dt.datetime | None = None

    def _jobs_at_a_time(self) -> int:
        if self.count:
            return self.count
        with self.server.db.read(unscoped="receipts.reading: jobs at a time") as s:
            return settings.get(s, "receiptReadJobs")

    def start(self) -> None:
        if self.threads:
            return
        with self.server.db.read(unscoped="receipts.reading: start") as s:
            pending = [
                rid
                for (rid,) in s.execute(
                    sa.select(Receipt.id)
                    .where(
                        Receipt.readStatus.in_(("waiting", "reading")),
                        Receipt.deletedAt.is_(None),
                    )
                    .order_by(Receipt.createdAt)
                )
            ]
        self.resize()
        for rid in pending:
            self.queue(rid)

    def resize(self) -> None:
        """As many threads as Jobs at a time says: more started, or as many told to go once
        the receipt in hand is read; the queue is kept (S9.8.7)."""
        if self.stopping.is_set():
            return
        n = self._jobs_at_a_time()
        with self._lock:
            for _ in range(self.size, n):
                w = Worker(self.server.config.data_dir)
                t = threading.Thread(target=self._loop, args=(w,), daemon=True, name="mk-read")
                self.workers.append(w)
                self.threads.append(t)
                t.start()
            for _ in range(n, self.size):
                self.jobs.put((_RETIRE, next(self._order), None))
            self.size = n

    def stop(self) -> None:
        self.stopping.set()
        with self._lock:
            for _ in self.threads:
                self.jobs.put((_STOP, next(self._order), None))
            for w in self.workers:
                w.stop()

    def queue(self, receipt_id: str) -> None:
        self.jobs.put((_RECEIPT, next(self._order), receipt_id))

    def _loop(self, worker: Worker) -> None:
        while not self.stopping.is_set():
            kind, _, rid = self.jobs.get()
            if kind == _STOP:
                return
            if kind == _RETIRE:
                with self._lock:
                    worker.stop()
                    self.threads.remove(threading.current_thread())
                    self.workers.remove(worker)
                return
            try:
                self.read_one(rid, worker)
            except Exception:
                log.exception("reading a receipt failed")

    def read_one(self, rid: str, worker: Worker) -> None:
        from .. import parsing
        from . import whole

        srv = self.server
        with srv.db.tx(unscoped="receipts.reading: read one") as s:
            r = s.get(Receipt, rid)
            if r is None or r.deleted or r.readStatus not in ("waiting", "reading"):
                return
            if r.filePrunedAt is not None:  # never left *Reading…* for good (S14.10.5)
                r.readStatus, r.readError, r.readAt = "failed", "its file was pruned", clock.now()
                return
            if not settings.get(s, "readReceipts"):
                r.readStatus = "off"
                return
            r.readStatus = "reading"
            media = r.mediaType
            owner = r.ownerId
            drawn = r.thumbnail is not None
            file = SimpleNamespace(fileId=r.fileId, sha256=r.sha256)
        srv.events.publish("receipt", {"id": rid}, users=[owner])
        thumb = None
        try:
            data = whole(srv, file)
            # The owner's file: read in a worker no other user's file has been in (S9.8.4.2).
            outcome = worker.read(data, media, user=owner, check=True)
            if not drawn:  # one the upload couldn't draw is tried again
                thumb = parsing.thumbnail(data, media, user=owner)
        except Exception as e:
            outcome = ("error", f"its file can't be opened ({type(e).__name__})")
        self.last_run = clock.now()
        with srv.db.tx(unscoped="receipts.reading: read one") as s:
            r = s.get(Receipt, rid)
            if r is None:
                return
            if thumb is not None and r.thumbnail is None:
                r.thumbnail = thumb
            if outcome[0] == "ok":
                _, lines, method, engine, found = outcome
                save_reading(s, r, lines, method, engine, found)
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


def _payees(s, owner_id: str) -> list[str]:
    """The payees of the transactions in the owner's own accounts, the most used first."""
    from ..store.entities.accounts import Transaction

    used = sa.func.count(Transaction.id)
    return list(
        s.scalars(
            sa.select(Transaction.payee)
            .join(Account, Account.id == Transaction.accountId)
            .where(
                Account.ownerId == owner_id,
                Account.deleted == sa.false(),
                Transaction.deleted == sa.false(),
                Transaction.payee.is_not(None),
                Transaction.payee != "",
            )
            .group_by(Transaction.payee)
            .order_by(used.desc(), Transaction.payee)
        )
    )


def save_reading(
    s, r: Receipt, lines: list[str], method: str, engine: str, check: dict | None = None
) -> None:
    """Store what was read, and fill the fields nobody typed (S9.8.1). A total its text layer
    gives that the scan of its page doesn't is kept with both readings (S9.8.2.1.1)."""
    found = parser.parse(lines, clock.today(), _not_before(s, r))
    r.text = "\n".join(lines)
    r.readMethod, r.readEngine = method, engine
    r.readStatus, r.readError, r.readAt = "read", None, clock.now()
    suggested = found.as_dict()
    if (
        check is not None
        and not check["agrees"]
        and found.total is not None
        and Decimal(check["text"]) == found.total.value
    ):
        suggested[DISAGREE] = {"text": check["text"], "scan": check["scan"]}
    r.suggested = json.dumps(suggested)
    filled = set(json.loads(r.filled or "[]"))
    values = {
        "date": found.date.value if found.date else None,
        "amount": found.total.value if found.total else None,
        "payee": found.merchant.value if found.merchant else None,
    }
    if values["payee"]:
        # The merchant as the uploader's payee rules show it (S2.7.7, S9.8.2.5.3), else as a
        # payee they already have names it.
        from ..store.repos.rules import Rules

        read = values["payee"]
        values["payee"] = Rules(s, r.ownerId).rename(read)
        if values["payee"] == read:
            values["payee"] = parser.known_payee(read, _payees(s, r.ownerId)) or read
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


def turned_on(s) -> list[str]:
    """Read receipts turned on: what came in while it was off is queued, every receipt not
    deleted whose file is kept (S9.8.4.1, S9.8.7). `s` reads as the server; the ids, in the
    order they came, for the reader once the change is saved."""
    ids = []
    for r in s.scalars(
        sa.select(Receipt)
        .where(
            Receipt.readStatus == "off",
            Receipt.deletedAt.is_(None),
            Receipt.filePrunedAt.is_(None),
        )
        .order_by(Receipt.createdAt)
    ):
        read_again(s, r)
        ids.append(r.id)
    return ids


def read_again(s, r: Receipt) -> None:
    """Queue it again: only empty or suggested fields will be replaced (S9.8.6)."""
    r.readStatus, r.readError = "waiting", None


def disagreeing(r: Receipt) -> dict | None:
    """The text layer's total and the scan's, while they disagree and the amount is still the
    one read: until someone picks or types it, no transaction is offered (S9.8.2.1.1)."""
    got = json.loads(r.suggested or "{}").get(DISAGREE)
    if got is None or "amount" not in json.loads(r.filled or "[]"):
        return None
    return got
