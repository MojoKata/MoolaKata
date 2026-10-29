"""Linked servers (requirements S11.1, S11.7): each link with another MoolaKata server."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)

from ..types import Day, UtcTimestamp
from ._base import exception, pairs, record, unique_live

# A link with another server (S11.1). On the inviting side it starts as an invitation (its
# code kept as a hash), becomes a request when the other side answers, and is active once an
# admin approves it; on the joining side it waits for that approval. Paused stops the
# exchanges both ways; ended stays listed, and deletes the copies on both sides.
Link = record(
    "Link",
    "Link",
    Column("state", Text, nullable=False),
    Column("role", Text, nullable=False),  # inviter or joiner
    Column("peerName", Text),  # the peer's server name (S16.1)
    Column("householdName", Text),
    Column("householdAvatar", Text),  # JSON, as the peer sets it
    Column("address", Text),  # the peer's link address
    Column("peerKey", Text),  # its Ed25519 public key, base64url
    Column("codeHash", Text),  # an invitation's code
    Column("codeExpiresAt", UtcTimestamp),
    Column("createdById", Text, ForeignKey("User.id")),
    Column("approvedById", Text, ForeignKey("User.id")),
    Column("approvedAt", UtcTimestamp),
    Column("lastOkAt", UtcTimestamp),  # the last exchange that worked, either way
    Column("lastError", Text),
    Column("failingSince", UtcTimestamp),
    Column("peerVersion", Text),
    Column("peerProtocol", Integer),
    Column("endedAt", UtcTimestamp),
    # Paused for a duration: it resumes on its own then (S11.7.2).
    Column("pausedUntil", UtcTimestamp),
    # A large change arriving in parts, oldest first (S11.7.1): the newest record's date so far,
    # and what has arrived of what the source said it would send.
    Column("syncThrough", Day),
    Column("syncBytes", Integer),
    Column("syncTotal", Integer),
    # The linked copy's access key (S11.9.2): its public key only, and who made it when. The
    # copy key itself is never stored.
    Column("copyFolder", Text),  # the copy's folder under links/, a random name (schema.md §2.5)
    Column("copyPublicKey", Text),
    Column("copyKeyAt", UtcTimestamp),
    Column("copyKeyById", Text, ForeignKey("User.id")),
    # Pulls (S11.4, S11.9.5): when the last one arrived, the newest change waiting in the inbox,
    # and whether the next pull asks for everything again (a reset copy, an inbox overflowed).
    Column("pulledAt", UtcTimestamp),
    Column("inboxAsOf", UtcTimestamp),
    Column("needsFull", Boolean, nullable=False, server_default=text("0")),
    # The last change this side sent the peer, and the last one it took from the peer.
    Column("sentSeq", Integer, nullable=False, server_default=text("0")),
    Column("gotSeq", Integer, nullable=False, server_default=text("0")),
    # The peer's copy key for this link (S11.9.2.2), which this side seals its changes and
    # receipts to; none until the peer's copy has an access key.
    Column("peerCopyKey", Text),
    # The peer's TLS certificate, when it is its own (S11.1.3): its key's fingerprint, pinned
    # from the link code or the join; the next one, announced; and one it presented without
    # announcing, waiting for an admin to accept it. None pinned: a public certificate.
    Column("peerCert", Text),
    Column("peerCertNext", Text),
    Column("peerCertOffered", Text),
    # The peer answered that it has no link with this one (S11.6): broken until an admin ends
    # it or links again.
    Column("brokenAt", UtcTimestamp),
    CheckConstraint(
        "state IN ('invited', 'requested', 'pending', 'active', 'paused', 'ended')", name="state"
    ),
    CheckConstraint("role IN ('inviter', 'joiner')", name="role"),
)
unique_live(Link, "peerKey")

# What a link brings in, as the main database knows it while the copy is locked (S11.9.1): each
# shared item's id there, kind, owner's display name, when it was shared and the people here it
# names, never its name or figures. Replaced at each pull: a cache (schema.md §4.4.5).
LinkedItem = exception(
    "LinkedItem",
    "cache: replaced from each pull of the link (§4.4.5)",
    Column("linkId", Text, ForeignKey("Link.id", ondelete="CASCADE"), nullable=False),
    Column("remoteId", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("ownerName", Text, nullable=False),
    Column("sharedAt", UtcTimestamp, nullable=False),
    Column("viewers", Text, nullable=False, server_default=text("'[]'")),  # local user ids
    Column("includeReceipts", Boolean, nullable=False, server_default=text("0")),
    Column("createdAt", UtcTimestamp, nullable=False),
    prefix="LItem",
)
Index("ux_LinkedItem_link_remote", LinkedItem.c.linkId, LinkedItem.c.remoteId, unique=True)

# What this server last sent a peer of each shared item (S11.4): a hash for each document, so
# only changes travel. Worked out again in full when the peer asks for everything: a cache
# (schema.md §4.4.5).
LinkSent = exception(
    "LinkSent",
    "cache: what was last sent a peer, worked out again when it asks for everything (§4.4.5)",
    Column("linkId", Text, ForeignKey("Link.id", ondelete="CASCADE"), nullable=False),
    Column("itemId", Text, nullable=False),
    Column("path", Text, nullable=False),  # the item's own row is "", its documents their path
    Column("viewer", Text, nullable=False),  # the peer's user id
    Column("hash", Text, nullable=False),
    UniqueConstraint("linkId", "itemId", "path", "viewer"),
    prefix="LkSnt",
)

# A receipt a change named that hasn't reached the copy yet (S11.4): asked for again at each
# exchange until it is fetched, then its file name kept until the copy has it. Removed once it
# has: part of the linked copy (schema.md §4.4.3).
LinkFile = exception(
    "LinkFile",
    "linked copies: a receipt not yet in the copy, until it is (§4.4.3)",
    Column("linkId", Text, ForeignKey("Link.id", ondelete="CASCADE"), nullable=False),
    Column("fileId", Text, nullable=False),  # its id at the source
    Column("fileName", Text),  # random, under the copy's receipts/, once fetched
    Column("tries", Integer, nullable=False, server_default=text("0")),
    Column("missedAt", UtcTimestamp, nullable=False),
    Column("error", Text),  # why the last try failed, in this server's words
    UniqueConstraint("linkId", "fileId"),
    prefix="LkFil",
)

# The colour each user chose for a linked household's window (S12.10.3.2), from a fixed palette.
LinkColours = pairs(
    "LinkColours",
    Column("userId", Text, ForeignKey("User.id", ondelete="CASCADE"), nullable=False),
    Column("linkId", Text, ForeignKey("Link.id", ondelete="CASCADE"), nullable=False),
    Column("colour", Text, nullable=False),
    CheckConstraint(
        "colour IN ('teal', 'violet', 'amber', 'rose', 'green', 'blue')", name="colour"
    ),
    PrimaryKeyConstraint("userId", "linkId"),
)
