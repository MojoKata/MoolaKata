"""The folders of files that rows name (requirements S9.7, S11.9.6.6): the server's receipts,
and each linked copy's. A file is written before the row that names it is committed, and a
copy's receipts may wait days for theirs, so whatever sweeps a folder for files no row names
goes by one rule, here:

1. a file an operation is still writing is registered with its folder's store
   (`writing`), until the operation's rows are committed or it fails;
2. an operation that names files in bulk (a pull, a copy's unlock) marks the store busy
   (`busy`), and the sweep leaves a busy store alone;
3. the sweep removes only a file unregistered, named by no row, and older than a generous
   grace, holding the store for the whole pass, so neither starts while it runs."""

import contextlib
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

GRACE_SECONDS = 30 * 60  # older than any operation still writing its file takes


class FileStore:
    def __init__(self, folder: Path):
        self.folder = folder
        self._lock = threading.Lock()
        self._writing: Counter[str] = Counter()
        self._busy = 0

    @contextlib.contextmanager
    def writing(self, *names: str):
        """Files being written, kept from the sweep until the block ends; `add` registers more
        as they are made."""
        held: list[str] = []

        def add(name: str) -> None:
            with self._lock:
                self._writing[name] += 1
            held.append(name)

        for n in names:
            add(n)
        try:
            yield add
        finally:
            with self._lock:
                for n in held:
                    self._writing[n] -= 1
                    if self._writing[n] <= 0:
                        del self._writing[n]

    def hold_until_done(self, session, name: str) -> None:
        """A file named by a row in `session`'s transaction: kept from the sweep until that
        transaction is committed or rolled back."""
        from sqlalchemy import event

        block = self.writing(name)
        block.__enter__()
        done = [False]

        def release(*_):
            if not done[0]:
                done[0] = True
                block.__exit__(None, None, None)

        event.listen(session, "after_commit", release, once=True)
        event.listen(session, "after_rollback", release, once=True)

    @contextlib.contextmanager
    def busy(self):
        """An operation naming files in bulk: the sweep leaves this store alone meanwhile."""
        with self._lock:
            self._busy += 1
        try:
            yield
        finally:
            with self._lock:
                self._busy -= 1

    def remove(self, name: str) -> int:
        """Remove one file no row needs any more, unless an operation is writing, or reusing,
        it this moment; the bytes freed."""
        with self._lock:
            if name in self._writing:
                return 0
            p = self.folder / name
            try:
                size = p.stat().st_size
                p.unlink()
            except FileNotFoundError:
                return 0
            return size

    def is_busy(self) -> bool:
        with self._lock:
            return self._busy > 0

    def sweep(
        self,
        named: Callable[[], set[str]],
        suffixes: tuple[str, ...],
        grace: float = GRACE_SECONDS,
    ) -> list[tuple[str, int]]:
        """Remove the files of these suffixes that `named()` (the rows' file names, read once
        the store is held) doesn't name, nobody is writing and are older than `grace`; nothing
        while the store is busy. Returns each removed file's name and size."""
        if not self.folder.is_dir():
            return []
        with self._lock:
            if self._busy:
                return []
            writing = set(self._writing)
            names = named()
            old = time.time() - grace
            gone = []
            for f in self.folder.iterdir():
                if f.suffix not in suffixes or f.name in names or f.name in writing:
                    continue
                try:
                    st = f.stat()
                except FileNotFoundError:
                    continue
                if st.st_mtime > old:
                    continue
                f.unlink(missing_ok=True)
                gone.append((f.name, st.st_size))
            return gone


class FileStores:
    """One store per folder, made the first time it is asked for."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stores: dict[Path, FileStore] = {}

    def of(self, folder: Path) -> FileStore:
        key = Path(folder).resolve()
        with self._lock:
            if key not in self._stores:
                self._stores[key] = FileStore(key)
            return self._stores[key]
