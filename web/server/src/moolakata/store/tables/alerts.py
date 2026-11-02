"""Alerts (requirements S12.11): what needs someone's attention, one per cause, open while the
cause lasts and resolved by itself when it clears. Alerts are never deleted; resolved ones age
out of the list after 90 days (schema.md §4.4)."""

from sqlalchemy import Column, ForeignKey, Index, Text, UniqueConstraint, text

from ..types import UtcTimestamp
from ._base import Seen, exception

Alert = exception(
    "Alert",
    "never deleted at all: resolved, then out of the list after 90 days (§4.4)",
    Column("kind", Text, nullable=False),
    # What it is about, unique among unresolved alerts: "prices:tiingo", "stale:Acct_…".
    Column("causeKey", Text, nullable=False),
    # Who it is for: one user, or every admin when null.
    Column("userId", Text, ForeignKey("User.id")),
    Column("title", Text, nullable=False),
    Column("about", Text, nullable=False, server_default=text("''")),
    Column("link", Text),
    Column("fix", Text),
    Column("icon", Text, nullable=False, server_default=text("'alert'")),
    # A cause first seen here; the alert opens once it has lasted its delay.
    Column("seenSince", UtcTimestamp, nullable=False),
    Column("openedAt", UtcTimestamp),
    Column("resolvedAt", UtcTimestamp),
    Column("resolution", Text),
    Index("ix_Alert_causeKey", "causeKey", "resolvedAt"),
    Index("ix_Alert_userId", "userId", "openedAt"),
    prefix="Alert",
    seen=Seen.rule(),
    not_figures="raised from figures by the alert sweeps; no figure reads it",
)

# Each person's own state of an alert: seen (for the badge), dismissed, emailed.
AlertState = exception(
    "AlertState",
    "never deleted at all: kept with its alert (§4.4)",
    Column("alertId", Text, ForeignKey("Alert.id"), nullable=False),
    Column("userId", Text, ForeignKey("User.id"), nullable=False),
    Column("seenAt", UtcTimestamp),
    Column("dismissedAt", UtcTimestamp),
    Column("emailedAt", UtcTimestamp),
    UniqueConstraint("alertId", "userId"),
    Index("ix_AlertState_userId", "userId"),
    prefix="AlSt",
    seen=Seen.per_user("userId"),
    not_figures="a user's read and dismissed marks on alerts",
)
