"""Users, groups, sessions and one-time tokens (requirements S10.1, S13.7.1)."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    text,
)

from ..types import UtcTimestamp
from ._base import exception, pairs, record, unique_live

User = record(
    "User",
    "User",
    Column("username", Text, nullable=False),
    Column("displayName", Text, nullable=False),
    Column("email", Text),
    Column("active", Boolean, nullable=False, server_default=text("1")),
    # A password is set from an invitation or the default admin's setup; until then, none.
    Column("passwordHash", Text),
    Column("passwordChangedAt", UtcTimestamp),
    # The default admin's first sign-in leads only to the setup step (S10.1.2).
    Column("needsSetup", Boolean, nullable=False, server_default=text("0")),
    Column("avatar", Text),
    Column("timeZone", Text, nullable=False, server_default=text("'auto'")),
    Column("theme", Text, nullable=False, server_default=text("'dark'")),
    # Their person (S10.10.1): name, sex, birthday and relationships.
    Column(
        "personId",
        Text,
        ForeignKey("Person.id", use_alter=True, name="fk_User_personId_Person"),
        nullable=False,
    ),
    Column("alertEmails", Text, nullable=False, server_default=text("'daily'")),
    # How bitcoin amounts are shown to them: BTC or sats (S1.6.4).
    Column("bitcoinUnit", Text, nullable=False, server_default=text("'btc'")),
    Column("lastSignInAt", UtcTimestamp),
    Column("reactivationAskedAt", UtcTimestamp),
    # Two-step sign-in (S10.1.6): on since this time. Its TOTP seed is a secret (S14.4); the
    # last step a code was accepted for, so a code is never accepted twice.
    Column("twoStepAt", UtcTimestamp),
    Column("totpLastStep", Integer),
    # The addresses this user signed in from in the last 30 days, JSON {address: when}, so a
    # sign-in from a new one is noticed by email (S10.1.9).
    Column("recentAddresses", Text, nullable=False, server_default=text("'{}'")),
    # When the last daily summary of alerts was sent (S12.11.5).
    Column("alertSummaryAt", UtcTimestamp),
    # A user of a linked server (S10.3.3.1): its link, and its id there. It never signs in here,
    # so it has no password or two-step sign-in.
    Column("linkId", Text, ForeignKey("Link.id", use_alter=True, name="fk_User_linkId_Link")),
    Column("remoteId", Text),
    # The budget they follow; the others they can see are scenarios (S7.12).
    Column(
        "activeBudgetId",
        Text,
        ForeignKey(
            "Budget.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_User_activeBudgetId_Budget",
        ),
    ),
    CheckConstraint("theme IN ('dark', 'light', 'system')", name="theme"),
    CheckConstraint("\"alertEmails\" IN ('each', 'daily', 'none')", name="alert_emails"),
    CheckConstraint("\"bitcoinUnit\" IN ('btc', 'sats')", name="bitcoin_unit"),
    CheckConstraint(
        '"linkId" IS NULL OR ("passwordHash" IS NULL AND "twoStepAt" IS NULL '
        'AND "remoteId" IS NOT NULL)',
        name="remote",
    ),
)
# Usernames and emails are unique among this server's own users; a linked server's users are
# told apart by their link (S10.3.3.1).
Index(
    "ux_User_username",
    User.c.username,
    unique=True,
    sqlite_where=text('NOT deleted AND "linkId" IS NULL'),
)
Index(
    "ux_User_email",
    User.c.email,
    unique=True,
    sqlite_where=text('NOT deleted AND "linkId" IS NULL'),
)
unique_live(User, "personId")
Index(
    "ux_User_linkId_remoteId",
    User.c.linkId,
    User.c.remoteId,
    unique=True,
    sqlite_where=text("NOT deleted"),
)

Group = record(
    "Group",
    "Group",
    Column("name", Text, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("1")),
    # The built-in Admins group: membership is what makes an admin (S10.1.8).
    Column("builtIn", Text),
    CheckConstraint('"builtIn" IS NULL OR "builtIn" = \'admins\'', name="built_in"),
)
unique_live(Group, "name")

UserGroups = pairs(
    "UserGroups",
    Column("userId", Text, ForeignKey("User.id", ondelete="CASCADE"), nullable=False),
    Column("groupId", Text, ForeignKey("Group.id", ondelete="CASCADE"), nullable=False),
    PrimaryKeyConstraint("userId", "groupId"),
)

Session = exception(
    "Session",
    "sessions are removed when they end or expire (§4.4.1)",
    Column("tokenHash", Text, primary_key=True),
    Column("userId", Text, ForeignKey("User.id"), nullable=False),
    Column("createdAt", UtcTimestamp, nullable=False),
    Column("lastSeenAt", UtcTimestamp, nullable=False),
    Column("expiresAt", UtcTimestamp, nullable=False),
    # When the password was last given in this session, for re-authentication (S13.7.2).
    Column("authAt", UtcTimestamp, nullable=False),
    Column("address", Text),  # the client's address at sign-in (S10.1.9)
    Column("admin", Boolean, nullable=False, server_default=text("0")),
    Column("needsSetup", Boolean, nullable=False, server_default=text("0")),
    Index("ix_Session_userId", "userId"),
)

OneTimeToken = exception(
    "OneTimeToken",
    "one-time tokens are removed when used or expired (§4.4.1)",
    Column("tokenHash", Text, primary_key=True),
    Column("purpose", Text, nullable=False),
    Column("userId", Text, ForeignKey("User.id"), nullable=False),
    Column("data", Text),
    Column("createdAt", UtcTimestamp, nullable=False),
    Column("expiresAt", UtcTimestamp, nullable=False),
    CheckConstraint(
        "purpose IN ('invitation', 'reset', 'email-change', 'two-step')", name="purpose"
    ),
    Index("ix_OneTimeToken_userId", "userId"),
)

# Ten per user, each usable once in place of a two-step code (S10.1.6).
RecoveryCode = exception(
    "RecoveryCode",
    "two-step recovery codes are removed when used or replaced (§4.4.1)",
    Column("codeHash", Text, primary_key=True),
    Column("userId", Text, ForeignKey("User.id"), nullable=False),
    Column("createdAt", UtcTimestamp, nullable=False),
    Index("ix_RecoveryCode_userId", "userId"),
)

# A person's request for an account (S10.1.4): confirmed by an emailed link, then approved or
# rejected by an admin. Approval makes the User; the request stays as the record of it.
SignupRequest = record(
    "SignupRequest",
    "Sgnup",
    Column("displayName", Text, nullable=False),
    Column("username", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("passwordHash", Text, nullable=False),
    Column("sex", Text, nullable=False),  # for their person (S10.10.1)
    Column("status", Text, nullable=False, server_default=text("'confirming'")),
    # The emailed link's token, as its hash, until it is opened.
    Column("confirmTokenHash", Text),
    Column("confirmBy", UtcTimestamp, nullable=False),
    Column("confirmedAt", UtcTimestamp),
    Column("decidedAt", UtcTimestamp),
    Column("decidedById", Text, ForeignKey("User.id")),
    Column("userId", Text, ForeignKey("User.id")),
    CheckConstraint("status IN ('confirming', 'waiting', 'approved', 'rejected')", name="status"),
    CheckConstraint("sex IN ('male', 'female')", name="sex"),
    Index("ix_SignupRequest_confirmTokenHash", "confirmTokenHash"),
)

# A user's read-only token for the MCP endpoint (S10.9.1): shown once, kept as a hash of its
# secret part. Revoking it deletes it (soft, so Activity still names it).
AccessToken = record(
    "AccessToken",
    "Token",
    Column("userId", Text, ForeignKey("User.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("scope", Text, nullable=False),  # all, or chosen
    Column("items", Text, nullable=False, server_default=text("'[]'")),  # chosen: kind and id
    Column("secretHash", Text, nullable=False),
    Column("expiresAt", UtcTimestamp, nullable=False),
    Column("lastUsedAt", UtcTimestamp),
    CheckConstraint("scope IN ('all', 'chosen')", name="scope"),
    Index("ix_AccessToken_userId", "userId"),
)
