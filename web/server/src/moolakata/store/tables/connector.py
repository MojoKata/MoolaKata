"""The MoolaKata Connector (requirements S18): the one connector paired with this server, and
each user's Connections, the sign-ins it keeps for them. MoolaKata holds the connector's public
keys and these records, never a credential (S18.2.3)."""

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, Text, text

from ..types import UtcTimestamp
from ._base import Seen, record, unique_live

# The paired connector (S18.4). One is paired at a time: pairing another replaces it, as
# Unpair does, and the replaced one ends (endedAt). While a pairing code is out, the row holds
# the code's secret as a hash until the connector introduces itself with it.
Connector = record(
    "Connector",
    "Cnctr",
    Column("state", Text, nullable=False),  # pairing, paired, ended
    Column("codeHash", Text),  # the one-time pairing code's secret (S18.4.1)
    Column("codeExpiresAt", UtcTimestamp),
    # Its two Ed25519 public keys, base64url (S18.4.2): the action key signs its calls, and the
    # status key, kept outside its vault, only a report that it is locked and `unpaired`.
    Column("actionKey", Text),
    Column("sealingKey", Text),  # its X25519 public key, base64url (S18.7.1)
    Column("pairedAt", UtcTimestamp),
    Column("pairedById", Text, ForeignKey("User.id")),
    # An admin compared the fingerprints and confirmed the pairing (S18.4.3): until then no
    # sealed credential is handed over and no file is taken.
    Column("confirmedAt", UtcTimestamp),
    Column("confirmedById", Text, ForeignKey("User.id")),
    Column("endedAt", UtcTimestamp),  # unpaired, or replaced by another pairing
    Column("endedById", Text, ForeignKey("User.id")),
    # Its reports (S18.5): the last one, whether it said it was locked, and what it runs.
    Column("lastReportAt", UtcTimestamp),
    Column("locked", Boolean, nullable=False, server_default=text("1")),
    Column("connectorVersion", Text),  # the connector's own version, from its reports
    # Where its reports come from: a change alerts admins, since a stolen volume reports as
    # the connector from wherever it went (S18.2.4.4); Accept makes the new one known.
    Column("lastAddress", Text),
    Column("knownAddress", Text),
    Column("protocol", Integer),
    # An address it reported from that no admin has accepted: kept, and alerted, until one
    # accepts it or unpairs, whatever the connector reports from next (S18.5.4).
    Column("newAddress", Text),
    # Its action key's signature over its sealing key (S18.4.5), which a browser checks
    # before sealing, so the key sealed to is the paired connector's own.
    Column("sealingSignature", Text),
    # Its page's address, from its reports (S18.11.1), which Settings › Connector links to.
    Column("pageAddress", Text),
    Column("statusKey", Text),
    CheckConstraint("state IN ('pairing', 'paired', 'ended')", name="state"),
    seen=Seen.rule(),
)
unique_live(Connector, "actionKey")
unique_live(Connector, "statusKey")

# A Connection (S18.6): one sign-in at one institution, kept by the connector and owned by
# the user whose sign-in it is. Its state and last run come from the connector's reports; the
# institution accounts the driver found are kept as JSON (name and last four digits). A
# credential sealed for the connector (S18.7.1) waits here only as ciphertext MoolaKata can't
# open, until the connector collects it.
Connection = record(
    "Connection",
    "Conn",
    Column("ownerId", Text, ForeignKey("User.id", ondelete="CASCADE"), nullable=False),
    Column("connectorId", Text, ForeignKey("Connector.id"), nullable=False),
    Column("driver", Text, nullable=False),  # folder, ofx-direct, schwab
    Column("label", Text, nullable=False),  # "Alice's Schwab login"
    Column("state", Text, nullable=False),  # new, ok, needs-sign-in, failing, removed
    Column("message", Text),  # the connector's words for the state
    Column("lastRunAt", UtcTimestamp),
    Column("lastRunAdded", Integer),  # what the last run posted, as the connector counts it
    Column("institutionAccounts", Text, nullable=False, server_default=text("'[]'")),
    Column("settings", Text, nullable=False, server_default=text("'{}'")),  # the driver's own
    Column("sealedCredential", Text),  # waiting for the connector, base64url; deleted once taken
    Column("sealedAt", UtcTimestamp),
    Column("signInAddress", Text),  # an OAuth sign-in the connector reported (S18.7.1)
    Column("removedAt", UtcTimestamp),  # Remove (S18.6.4): the connector deletes its credentials
    CheckConstraint("state IN ('new', 'ok', 'needs-sign-in', 'failing', 'removed')", name="state"),
    CheckConstraint("driver IN ('folder', 'ofx-direct', 'schwab')", name="driver"),
    seen=Seen.rule(),
)
unique_live(Connection, "ownerId", "label")
