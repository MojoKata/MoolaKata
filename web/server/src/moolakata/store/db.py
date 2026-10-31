"""The database connection (requirements S14.1.4): SQLCipher through SQLAlchemy, WAL, foreign
keys on, a 10-second busy timeout. A unit of work is `Database.tx()` (BEGIN IMMEDIATE) or
`Database.read()` (PRAGMA query_only, which refuses any write)."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlcipher3
from sqlalchemy import Engine, and_, create_engine, event, false, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from . import scoping, views

BUSY_MS = 10_000


class WrongKey(Exception):
    """The database does not open with this key."""


def connect(path: Path, key: str | None) -> sqlcipher3.Connection:
    """One raw connection, keyed before anything else is read. A key of None opens a plain
    SQLite file (dev tools only, never the server's database)."""
    conn = sqlcipher3.connect(
        str(path), timeout=BUSY_MS / 1000, check_same_thread=False, isolation_level=None
    )
    if key is not None:
        conn.execute(f'PRAGMA key = "{key}"')
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlcipher3.DatabaseError:
        conn.close()
        raise WrongKey(f"{path.name} does not open with this key") from None
    conn.execute(f"PRAGMA busy_timeout = {BUSY_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


class HeldKey:
    """A database key a release overwrites: each new connection reads it, and once it is
    overwritten none can open (S11.9.4)."""

    def __init__(self, raw: bytes) -> None:
        self._raw = bytearray(raw)
        self.released = False

    def text(self) -> str:
        if self.released:
            raise WrongKey("the copy was locked: its key is gone")
        return f"x'{self._raw.hex()}'"

    def release(self) -> None:
        for i in range(len(self._raw)):
            self._raw[i] = 0
        self.released = True


def make_engine(path: Path, key: str | HeldKey | None) -> Engine:
    # The URL names no file (the creator opens it with its key), which SQLAlchemy would take for
    # an in-memory database and give a SingletonThreadPool; that pool closes connections other
    # threads still use. A QueuePool keeps one connection per checkout.
    engine = create_engine(
        "sqlite://",
        creator=lambda: connect(path, key.text() if isinstance(key, HeldKey) else key),
        module=sqlcipher3,
        poolclass=QueuePool,
        # More connections than the server has worker threads (40), so a thread never waits
        # for one; SQLite in WAL mode serves many readers at once.
        pool_size=16,
        max_overflow=32,
        pool_timeout=30,
        # A failed statement's error names no value it was given, so the log holds none
        # (S13.7.9).
        hide_parameters=True,
    )

    @event.listens_for(engine, "checkin")
    def checkin(dbapi_connection, record):
        # A connection goes back to the pool writable: a read leaves PRAGMA query_only on,
        # and a raw connection taken later (a backup's export) runs no BEGIN to reset it.
        dbapi_connection.execute("PRAGMA query_only = OFF")

    @event.listens_for(engine, "begin")
    def begin(conn):
        mode = conn.get_execution_options().get("mk_mode", "write")
        if mode == "read":
            conn.exec_driver_sql("PRAGMA query_only = ON")
            conn.exec_driver_sql("BEGIN")
        else:
            conn.exec_driver_sql("PRAGMA query_only = OFF")
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _scope(s: Session, user: str | None, unscoped: str | None) -> None:
        """A user's request reads only what their access views give them; the server's own
        work names why it reads everything (schema.md §7.6)."""
        if user is not None:
            scoping.scope_user(s, user)
        elif unscoped is not None:
            scoping.scope_server(s, unscoped)

    @contextmanager
    def tx(self, user: str | None = None, unscoped: str | None = None) -> Iterator[Session]:
        """A write: BEGIN IMMEDIATE, committed on leaving, rolled back on an exception."""
        with Session(self.engine, expire_on_commit=False, autoflush=True) as s:
            self._scope(s, user, unscoped)
            s.connection(execution_options={"mk_mode": "write"})
            try:
                yield s
                s.commit()
            except BaseException:
                s.rollback()
                raise

    @contextmanager
    def read(self, user: str | None = None, unscoped: str | None = None) -> Iterator[Session]:
        """A read under PRAGMA query_only: any write in it fails."""
        with Session(self.engine, expire_on_commit=False, autoflush=False) as s:
            self._scope(s, user, unscoped)
            s.connection(execution_options={"mk_mode": "read"})
            # Leaving the block closes the session: the pool rolls the connection back, and
            # what was read stays loaded (a rollback here would expire it).
            yield s

    def dispose(self) -> None:
        self.engine.dispose()


def live(entity, table, *, include_deleted: bool = False):
    """SELECT entity, leaving out what is effectively deleted (schema.md §4.2): through its
    Effective view where it is deleted with something, else by its own `deleted`."""
    stmt = select(entity)
    if include_deleted:
        return stmt
    if not views.parents(table):
        return stmt.where(table.c.deleted == false())
    view = views.view_table(table)
    on = and_(*(table.c[c.name] == view.c[c.name] for c in table.primary_key.columns))
    return stmt.join(view, on).where(view.c.effectiveDeleted == false())
