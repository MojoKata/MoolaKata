"""Activity (requirements S10.8): what happened, who did it and what it is about. Entries are
kept as written, never deleted, and never name an amount (R3.8)."""

from sqlalchemy import Boolean, Column, ForeignKey, Index, Text, text

from ..types import UtcTimestamp
from ._base import Seen, exception

Activity = exception(
    "Activity",
    "never deleted at all: kept as it was written (§4.4)",
    Column("at", UtcTimestamp, nullable=False),
    Column("actorId", Text, ForeignKey("User.id")),
    Column("via", Text),
    Column("kind", Text, nullable=False),
    Column("subjectKind", Text),
    Column("subjectId", Text),
    Column("ownerId", Text, ForeignKey("User.id")),
    Column("forAdmins", Boolean, nullable=False, server_default=text("0")),
    Column("detail", Text, nullable=False, server_default=text("'{}'")),
    Index("ix_Activity_at", "at"),
    Index("ix_Activity_subject", "subjectId", "at"),
    prefix="Actv",
    seen=Seen.rule(),
)
