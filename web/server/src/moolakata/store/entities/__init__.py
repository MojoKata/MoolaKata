"""Plain dataclasses, one per table, that import nothing from SQLAlchemy (requirements S14.1.2).
store/mapping.py maps each onto its table."""

import datetime as dt
from dataclasses import dataclass, field

from ... import clock


def _now() -> dt.datetime:
    return clock.now()


class SoftDeleted:
    """The soft-delete fields' behaviour (schema.md §4.1). `deleted` follows `deletedAt`, as the
    database's generated column does; store/mapping.py makes it queryable."""

    deletedAt: dt.datetime | None
    deletedById: str | None

    @property
    def deleted(self) -> bool:
        return self.deletedAt is not None

    def mark_deleted(self, by: str | None, at: dt.datetime | None = None) -> None:
        self.deletedAt = at or _now()
        self.deletedById = by

    def restore(self) -> None:
        self.deletedAt = None
        self.deletedById = None


@dataclass(kw_only=True, eq=False)
class Kept:
    """What every row with an id carries (schema.md §2): its version, which locks a draft
    record (S13.8.6) and counts a server-kept one's saves, and its times."""

    version: int = 1
    createdAt: dt.datetime = field(default_factory=_now)
    updatedAt: dt.datetime = field(default_factory=_now)


@dataclass(kw_only=True, eq=False)
class Record(Kept, SoftDeleted):
    """What every record carries: its version and times (`Kept`), and the soft-delete
    fields (schema.md §4.1)."""

    deletedAt: dt.datetime | None = None
    deletedById: str | None = None
