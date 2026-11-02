"""Settings, secrets, the background tasks' last runs, and emails waiting to go out."""

from sqlalchemy import Column, ForeignKey, Index, Integer, LargeBinary, Text, UniqueConstraint

from ..types import UtcTimestamp
from ._base import Seen, exception, record, unique_live

# A setting an admin saved (S16): one live row a key; a key with none stands at its default.
Setting = record(
    "Setting",
    "Setng",
    Column("key", Text, nullable=False),
    Column("value", Text, nullable=False),
    Column("updatedById", Text, ForeignKey("User.id")),
    seen=Seen.admin(),
)
unique_live(Setting, "key")

Secret = exception(
    "Secret",
    "a secret's old ciphertext is removed when it is replaced or removed (§4.4.2)",
    Column("recordType", Text, nullable=False),
    Column("recordId", Text, nullable=False),
    Column("field", Text, nullable=False),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    Column("wrappedKey", LargeBinary, nullable=False),
    Column("setAt", UtcTimestamp, nullable=False),
    Column("setById", Text, ForeignKey("User.id")),
    UniqueConstraint("recordType", "recordId", "field"),
    prefix="Secr",
    seen=Seen.server(),
    not_figures="credentials; no figure reads them",
)

TaskRun = exception(
    "TaskRun",
    "work state: a background task's last run (§4.4.4)",
    Column("name", Text, primary_key=True),
    Column("startedAt", UtcTimestamp, nullable=False),
    Column("finishedAt", UtcTimestamp),
    Column("error", Text),
    seen=Seen.server(),
    not_figures="the background tasks' work state",
)

# The data version (docs/schema.md §8): one row, moved on by a trigger on every write to a table
# figures are worked out from, inside the writing transaction, so a reader's snapshot holds the
# version of exactly the data it reads. A budget's months are kept under it (S7.3.10).
DataVersion = exception(
    "DataVersion",
    "a counter: one row, never deleted (§4.4.4)",
    Column("name", Text, primary_key=True),
    Column("version", Integer, nullable=False),
    seen=Seen.server(),
    not_figures="the counter itself",
)

# An email waiting to go out through SMTP (S16.2), in the database, which is encrypted: removed
# once sent or once its link has expired; one the server refused keeps only its recipient,
# subject and the error.
QueuedEmail = exception(
    "QueuedEmail",
    "a work queue: removed when sent or when its link expires (§4.4.4)",
    Column("recipient", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("message", Text),  # the whole message; none once refused
    Column("queuedAt", UtcTimestamp, nullable=False),
    Column("expiresAt", UtcTimestamp, nullable=False),
    Column("refusedAt", UtcTimestamp),
    Column("error", Text),
    Index("ix_QueuedEmail_queuedAt", "queuedAt"),
    prefix="Email",
    seen=Seen.admin(),
    not_figures="emails waiting to go out",
)
