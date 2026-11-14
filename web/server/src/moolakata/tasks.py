"""Background tasks (requirements S13.4): price refresh, backups, pruning and the others. They
run in a thread pool, never block a request, keep within each provider's rate limits, and
record their last run and error, which Settings shows."""

import asyncio
import datetime as dt
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from . import clock

log = logging.getLogger("moolakata.tasks")

TICK_SECONDS = 15


class Stopping(Exception):
    """Raised inside a task when the server is stopping."""


@dataclass
class Every:
    """Every so many seconds, the first run soon after start."""

    seconds: float
    first_after: float = 30

    def next_due(self, last: dt.datetime | None, started: dt.datetime) -> dt.datetime:
        if last is None:
            return started + dt.timedelta(seconds=self.first_after)
        return last + dt.timedelta(seconds=self.seconds)


@dataclass
class Daily:
    """Once a day at a time of day in a zone, both read when needed so a Settings change
    applies to the next run. A day missed while the server was down runs once at start."""

    at: Callable[[], tuple[dt.time, str]]

    def next_due(self, last: dt.datetime | None, started: dt.datetime) -> dt.datetime:
        when, zone = self.at()
        tz = ZoneInfo(zone)
        ref = (last or started - dt.timedelta(days=1)).astimezone(tz)
        due = dt.datetime.combine(ref.date(), when, tz)
        if due <= ref:
            due = dt.datetime.combine(ref.date() + dt.timedelta(days=1), when, tz)
        return due.astimezone(dt.UTC)


@dataclass
class TaskRun:
    started: dt.datetime
    finished: dt.datetime | None = None
    error: str | None = None


@dataclass
class Task:
    name: str
    run: Callable[[TaskContext], None]
    schedule: Every | Daily | None
    last: TaskRun | None = None
    running: bool = False
    requested: bool = False
    waiting: list = field(default_factory=list)  # called when the next run ends


@dataclass
class TaskContext:
    name: str
    stop: threading.Event
    limits: ProviderLimits

    def check(self) -> None:
        if self.stop.is_set():
            raise Stopping

    def wait_for(self, provider: str) -> None:
        """Block until the provider's limits allow one more call."""
        self.limits.acquire(provider, self.stop)


@dataclass
class Window:
    calls: int
    seconds: float
    seen: deque = field(default_factory=deque)


class ProviderLimits:
    """Per-provider call limits (Tiingo's 50 an hour, 1,000 a day; Massive's 5 a minute)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._windows: dict[str, list[Window]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def set(self, provider: str, limits: Sequence[tuple[int, float]]) -> None:
        with self._lock:
            self._windows[provider] = [Window(n, s) for n, s in limits]

    def delay(self, provider: str) -> float:
        """Seconds until a call is allowed; 0 records the call."""
        with self._lock:
            now = self._clock()
            windows = self._windows.get(provider, [])
            wait = 0.0
            for w in windows:
                while w.seen and now - w.seen[0] >= w.seconds:
                    w.seen.popleft()
                if len(w.seen) >= w.calls:
                    wait = max(wait, w.seconds - (now - w.seen[0]))
            if wait == 0:
                for w in windows:
                    w.seen.append(now)
            return wait

    def acquire(self, provider: str, stop: threading.Event) -> None:
        while True:
            wait = self.delay(provider)
            if wait <= 0:
                return
            if stop.wait(min(wait, 60)):
                raise Stopping


RecordFn = Callable[[str, TaskRun], None]


class Tasks:
    def __init__(
        self,
        record: RecordFn | None = None,
        workers: int = 4,
        now: Callable[[], dt.datetime] = clock.now,
    ) -> None:
        self._tasks: dict[str, Task] = {}
        self._record = record
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mk-task")
        self._stop = threading.Event()
        self._now = now
        self._started = now()
        self._lock = threading.Lock()
        self._runner: asyncio.Task | None = None
        self.limits = ProviderLimits()

    def register(
        self,
        name: str,
        run: Callable[[TaskContext], None],
        schedule: Every | Daily | None,
        last: TaskRun | None = None,
    ) -> None:
        self._tasks[name] = Task(name, run, schedule, last=last)

    def status(self) -> dict[str, dict]:
        out = {}
        for t in self._tasks.values():
            nxt = (
                t.schedule.next_due(t.last.started if t.last else None, self._started)
                if t.schedule
                else None
            )
            out[t.name] = {
                "running": t.running,
                "lastRun": t.last.started if t.last else None,
                "lastFinished": t.last.finished if t.last else None,
                "lastError": t.last.error if t.last else None,
                "nextRun": nxt,
            }
        return out

    def run_now(self, name: str, ended: Callable[[TaskRun], None] | None = None) -> bool:
        """Ask for a run (Refresh prices, Backup Now): at once once the tasks have started,
        else at the first tick. A task already running runs again when it finishes. `ended`
        is called with the run this asks for, when it ends (its job, S13.8.7)."""
        task = self._tasks.get(name)
        if task is None:
            return False
        with self._lock:
            if ended is not None:
                task.waiting.append(ended)
            if self._runner is not None and not task.running and not self._stop.is_set():
                self._launch(task)
            else:
                task.requested = True
        return True

    def _launch(self, task: Task) -> None:
        task.running = True
        task.requested = False
        waiting, task.waiting = task.waiting, []
        run = TaskRun(started=self._now())
        ctx = TaskContext(task.name, self._stop, self.limits)

        def body() -> None:
            try:
                task.run(ctx)
            except Stopping:
                run.error = "stopped when the server stopped"
            except Exception as e:
                # The error's type only: its text may name an account or an amount (S13.7.9).
                run.error = (
                    f"{type(e).__name__}: {e}" if isinstance(e, TaskError) else type(e).__name__
                )
                log.exception("task %s failed", task.name)
            finally:
                run.finished = self._now()
                task.last = run
                task.running = False
                if self._record:
                    try:
                        self._record(task.name, run)
                    except Exception:
                        log.exception("recording task %s failed", task.name)
                for ended in waiting:
                    try:
                        ended(run)
                    except Exception:
                        log.exception("ending a job of task %s failed", task.name)

        self._pool.submit(body)

    def tick(self) -> None:
        now = self._now()
        with self._lock:
            for task in self._tasks.values():
                if task.running:
                    continue
                due = task.requested
                if not due and task.schedule is not None:
                    last = task.last.started if task.last else None
                    due = task.schedule.next_due(last, self._started) <= now
                if due:
                    self._launch(task)

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("task tick failed")
            await asyncio.sleep(TICK_SECONDS)

    def start(self) -> None:
        self._runner = asyncio.get_running_loop().create_task(self.run())

    def stop(self) -> None:
        self._stop.set()
        if self._runner:
            self._runner.cancel()
        self._pool.shutdown(wait=False, cancel_futures=True)


class TaskError(Exception):
    """A failure whose message is safe to show in Settings (no names, amounts or secrets)."""
