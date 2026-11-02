"""Alerts (requirements S12.11): what needs someone's attention. Activity records what
happened; an alert asks for an action.

Each kind of cause has a check that says which causes hold now. The alerts task runs the
checks: a new cause opens an alert (after its delay, when it has one), a cause that holds
keeps its alert open, and one that has cleared resolves its alert by itself. One alert per
cause, never one per attempt. Opening an alert tells its people on the live stream, and by
email those who chose each alert; the daily summary task emails the rest.

An admin's alert about someone else's account names its owner and source, never the
account's name or figures (S10.2).
"""

import datetime as dt
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session, aliased

from . import clock, ids, settings, timezones
from .store.entities.alerts import Alert, AlertState
from .store.entities.users import User

log = logging.getLogger("moolakata.alerts")

KEEP_RESOLVED_DAYS = 90
MISMATCH_DAYS = 7
PHRASE_CHECK_DAYS = 365


@dataclass
class Cause:
    key: str
    kind: str
    title: str
    about: str = ""
    user_id: str | None = None  # None: for every admin
    link: str | None = None
    fix: str | None = None
    icon: str = "alert"
    since: dt.datetime | None = None  # when it began, if known; else when first seen
    delay: dt.timedelta = dt.timedelta(0)


Check = Callable[[Session, object], Iterable[Cause]]
CHECKS: list[Check] = []


def check(fn: Check) -> Check:
    CHECKS.append(fn)
    return fn


def _ago(delta: dt.timedelta) -> str:
    hours = int(delta.total_seconds() // 3600)
    if hours < 48:
        return f"{hours} hours"
    return f"{hours // 24} days"


# ---------- the causes this release has ----------


@check
def price_sources(s: Session, server) -> Iterable[Cause]:
    """A price source failing for longer than Settings › Alerts allows (admins)."""
    from .prices.refresh import SOURCES, enabled

    limit = dt.timedelta(hours=settings.get(s, "alertSourceHours"))
    now = clock.now()
    for src in enabled(s, server.config.dev):
        if not src.lastError:
            continue
        since = src.lastOkAt or src.createdAt
        label = SOURCES[src.name].label if src.name in SOURCES else src.name
        yield Cause(
            key=f"prices:{src.name}",
            kind="source-failing",
            title=f"{label} failing for {_ago(now - since)}",
            about=f"price source · {src.lastError}",
            link="/ui/settings/prices",
            fix="Prices settings",
            icon="sync",
            since=since,
            delay=limit,
        )


@check
def bitcoin_certificate(s: Session, server) -> Iterable[Cause]:
    """The Electrum server presented a certificate other than the one trusted (S1.6.2.4):
    admins confirm it, or find out why it changed."""
    offered = settings.get(s, "bitcoinNodeCertOffered")
    if offered and offered != settings.get(s, "bitcoinNodeCert"):
        yield Cause(
            key="bitcoin-certificate",
            kind="node-certificate",
            title="The bitcoin node's certificate changed",
            about="it is refused until an admin confirms the new one",
            user_id=None,
            link="/ui/settings/bitcoin",
            fix="Bitcoin settings",
            icon="lock",
        )


@check
def bitcoin_off_chain(s: Session, server) -> Iterable[Cause]:
    """A recorded bitcoin transaction the explorer or node no longer has (S1.6.2.7): its
    account's owner keeps or deletes it."""
    from .store.entities.accounts import Account, Transaction

    rows = s.execute(
        select(Account.id, Account.name, Account.ownerId)
        .join(Transaction, Transaction.accountId == Account.id)
        .where(Transaction.offChainAt.is_not(None), Transaction.deleted == false())
        .distinct()
    ).all()
    for account_id, name, owner in rows:
        yield Cause(
            key=f"off-chain:{account_id}",
            kind="off-chain",
            title=f"{name}: a bitcoin transaction is no longer on the chain",
            about="keep it, or delete it",
            user_id=owner,
            link=f"/ui/accounts/{account_id}/transactions",
            fix="See it",
            icon="alert",
        )


@check
def bitcoin_source(s: Session, server) -> Iterable[Cause]:
    """The bitcoin explorer or node failing for longer than Settings › Alerts allows: admins,
    and each wallet's owner (S1.6.2, S16.16)."""
    from sqlalchemy import func

    from .store.entities.accounts import Account, WalletAddress
    from .store.entities.core import TaskRun

    run = s.get(TaskRun, "bitcoin")
    if run is None or not run.error:
        return
    last_ok = s.scalar(select(func.max(WalletAddress.checkedAt)))
    since = last_ok or run.startedAt
    now = clock.now()
    owners = set(
        s.scalars(
            select(Account.ownerId).where(
                Account.type == "crypto-wallet", Account.deleted == false()
            )
        )
    )
    for who in [None, *sorted(owners)]:
        yield Cause(
            key="bitcoin" + (f":{who}" if who else ""),
            kind="source-failing",
            title=f"Bitcoin wallets not checked for {_ago(now - since)}",
            about=f"explorer or node · {run.error}",
            user_id=who,
            link="/ui/settings/bitcoin" if who is None else "/ui/accounts",
            fix="Bitcoin settings" if who is None else "Your accounts",
            icon="sync",
            since=since,
            delay=dt.timedelta(hours=settings.get(s, "alertSourceHours")),
        )


@check
def linked_servers(s: Session, server) -> Iterable[Cause]:
    """A linked server failing for longer than the source threshold, and a link whose shares
    wait for this side's access key (S12.11.1): admins."""
    from .store.entities.links import Link, LinkedItem

    limit = dt.timedelta(hours=settings.get(s, "alertSourceHours"))
    now = clock.now()
    for link in s.scalars(
        select(Link).where(Link.deleted == false(), Link.state.in_(("active", "pending")))
    ):
        name = link.peerName or "A linked server"
        # Both at once, not after the failing threshold: an admin decides each (S11.6, §4.5).
        if link.brokenAt:
            yield Cause(
                key=f"link-broken:{link.id}",
                kind="link-broken",
                title=f"{name} has no link with this server",
                about="restored from an older backup, perhaps · end the link, or link again",
                link="/ui/settings/links",
                fix="Linked servers",
                icon="link",
                since=link.brokenAt,
            )
            continue
        if link.peerCertOffered:
            yield Cause(
                key=f"link-cert:{link.id}",
                kind="link-certificate",
                title=f"{name}'s certificate changed",
                about="compare its new fingerprint with its admin, then accept it",
                link="/ui/settings/links",
                fix="Linked servers",
                icon="link",
            )
            continue
        if link.failingSince and link.lastError:
            yield Cause(
                key=f"link:{link.id}",
                kind="source-failing",
                title=f"{name} not reached for {_ago(now - link.failingSince)}",
                about=f"linked server · {link.lastError}",
                link="/ui/settings/links",
                fix="Linked servers",
                icon="link",
                since=link.failingSince,
                delay=limit,
            )
        if (
            not link.copyPublicKey
            and s.scalars(select(LinkedItem.id).where(LinkedItem.linkId == link.id)).first()
        ):
            yield Cause(
                key=f"link-key:{link.id}",
                kind="link-key-waiting",
                title=f"{name} shares something with people here",
                about="its copy waits for an access key",
                link="/ui/settings/links",
                fix="Create the access key",
                icon="link",
            )


@check
def connector(s: Session, server) -> Iterable[Cause]:
    """The MoolaKata Connector locked, or not heard from for 15 minutes (S18.5): admins. A
    Connection that needs a sign-in or is failing: admins, and the owner of each account it
    keeps current (S18.5.3)."""
    from .connector import manage
    from .store.entities.accounts import Account
    from .store.entities.connector import Connection

    row = manage.paired(s)
    if row is None:
        return
    silent = manage.silent_for(row)
    if silent is not None:
        yield Cause(
            key="connector:silent",
            kind="connector-silent",
            title="The MoolaKata Connector hasn't been heard from",
            about=f"Connector · last report {row.lastReportAt:%b %-d, %H:%M} UTC · "
            "it is stopped, down, or can't reach MoolaKata",
            link="/ui/settings/connector",
            fix="Connector settings",
            icon="sync",
            since=row.lastReportAt,
        )
    # Open until an admin accepts the new address or unpairs, whatever the connector reports
    # from next: the genuine one reporting again doesn't clear a thief's (S18.5.4).
    if row.newAddress and row.knownAddress:
        yield Cause(
            key="connector:moved",
            kind="connector-moved",
            title="The MoolaKata Connector reports from a new address",
            about=f"Connector · was {row.knownAddress}, now {row.newAddress} · accept it if "
            "the connector moved; unpair if its host was lost",
            link="/ui/settings/connector",
            fix="Connector settings",
            icon="alert",
            since=row.lastReportAt,
        )
    if silent is None and row.locked:
        yield Cause(
            key="connector:locked",
            kind="connector-locked",
            title="The MoolaKata Connector is locked",
            about="Connector · unlock it on its page, or on its host, with its 12 words",
            link="/ui/settings/connector",
            fix="Connector settings",
            icon="lock",
            since=row.lastReportAt,
        )
    for c in s.scalars(
        select(Connection).where(
            Connection.connectorId == row.id,
            Connection.deleted == false(),
            Connection.state.in_(("needs-sign-in", "failing")),
        )
    ):
        needs = c.state == "needs-sign-in"
        title = f"{c.label} {'needs a sign-in' if needs else 'is failing'}"
        about = f"Connection · {c.message or c.driver}"
        # Admins, and the owner of each account it keeps current (S18.5.3).
        owners = {c.ownerId} | set(
            s.scalars(
                select(Account.ownerId).where(
                    Account.connectionId == c.id, Account.deleted == false()
                )
            )
        )
        for owner in sorted(owners):
            yield Cause(
                key=f"connection:{c.id}:{c.state}:{owner}",
                kind="connection-failing",
                title=title,
                about=about,
                user_id=owner,
                link="/ui/profile",
                fix="Sign in again" if needs and owner == c.ownerId else "Your connections",
                icon="lock" if needs else "sync",
                since=c.lastRunAt,
            )
        yield Cause(
            key=f"connection:{c.id}:{c.state}",
            kind="connection-failing",
            title=title,
            about=about,
            link="/ui/settings/connector",
            fix="Connector settings",
            icon="lock" if needs else "sync",
            since=c.lastRunAt,
        )


@check
def backups(s: Session, server) -> Iterable[Cause]:
    from .store.entities.core import TaskRun

    run = s.get(TaskRun, "backups")
    if run is not None and run.error:
        yield Cause(
            key="backups",
            kind="backup-failed",
            title="Backup failed",
            about=run.error,
            link="/ui/settings/backups",
            fix="Backups",
            icon="alert",
            since=run.finishedAt or run.startedAt,
        )


@check
def reader_sandbox(s: Session, server) -> Iterable[Cause]:
    """Reading runs without its file sandbox: the host's kernel, or its container, doesn't
    offer Landlock (S9.8.4.2). For admins, while it lasts."""
    from . import parsing

    if parsing.file_sandbox() is False:
        yield Cause(
            key="reader-sandbox",
            kind="reader-sandbox",
            title="Reading runs without its file sandbox",
            about="this host doesn't offer Landlock (Linux 5.13 or later, and a container "
            "that allows it), so a file that exploits a reader could reach the data directory",
            link="/ui/settings/receipts",
            fix="Receipts settings",
            icon="lock",
        )


@check
def email(s: Session, server) -> Iterable[Cause]:
    """Email that can't be sent for longer than the source threshold (admins)."""
    from .store.entities.core import TaskRun

    run = s.get(TaskRun, "mail")
    waiting = server.services.mailer.waiting()
    if run is None or not run.error or not waiting:
        return
    oldest = waiting[0].queuedAt
    yield Cause(
        key="mail",
        kind="source-failing",
        title=f"Email can't be sent: {len(waiting)} waiting",
        about=f"SMTP · {run.error}",
        link="/ui/settings/email",
        fix="Email settings",
        icon="sync",
        since=oldest,
        delay=dt.timedelta(hours=settings.get(s, "alertSourceHours")),
    )


@check
def key_rotation(s: Session, server) -> Iterable[Cause]:
    """The master key's rotation (S15.8.4), due once the key is older than Settings › Key
    storage's reminder period; none when the period is off."""
    months = settings.get(s, "keyReminderMonths")
    if not months:
        return
    made = server.store.keys.ring.master_created
    due = made + dt.timedelta(days=round(months * 30.44))
    if clock.now() >= due:
        yield Cause(
            key="keys:rotation",
            kind="key-rotation",
            title="Time to rotate the master key",
            about=f"it is over {months} months old: Rotate, in Settings › Key storage",
            link="/ui/settings/keys",
            fix="Key storage",
            icon="lock",
            since=due,
        )


BREAK_GLASS_DAYS = 2


@check
def break_glass(s: Session, server) -> Iterable[Cause]:
    """A break-glass code asked for on the host (S15.5.2): every admin is told, for two days,
    so one nobody asked for is noticed."""
    from .store.entities.core import Activity

    at = s.scalars(
        select(Activity.at).where(Activity.kind == "keys.break-glass").order_by(Activity.at.desc())
    ).first()
    if at is not None and clock.now() < at + dt.timedelta(days=BREAK_GLASS_DAYS):
        yield Cause(
            key="keys:break-glass",
            kind="break-glass",
            title="A break-glass code was asked for on the host",
            about="it stands in for the recovery phrase at Rotate; if nobody here asked, someone "
            "has the server's host",
            link="/ui/activity",
            fix="Activity",
            icon="lock",
            since=at,
        )


@check
def recovery_phrase(s: Session, server) -> Iterable[Cause]:
    """The yearly check of the master key's recovery phrase (S15.6.5)."""
    from .store.entities.core import Activity

    last = s.scalars(
        # Verify key, `keys verify` on the host, or any unlock: each opened the keyring
        # (S15.6.5).
        select(Activity.at)
        .where(Activity.kind.in_(("key.verified", "key.checked", "key.unlocked")))
        .order_by(Activity.at.desc())
    ).first()
    since = last or server.store.keys.ring.master_created
    due = since + dt.timedelta(days=PHRASE_CHECK_DAYS)
    if clock.now() >= due:
        yield Cause(
            key="keys:phrase",
            kind="phrase-check",
            title="Check the recovery phrase: it's been a year",
            about="type a copy of the phrase into Verify key, in Settings › Key storage",
            link="/ui/settings/keys?verify",
            fix="Verify key",
            icon="lock",
            since=due,
        )


@check
def accounts(s: Session, server) -> Iterable[Cause]:
    """For each account's owner: a statement overdue at its account's interval (S1.11.7), and a
    balance the institution reported that has disagreed for 7 days (S1.11)."""
    from .ledger import expected, reconcile
    from .ledger import types as atypes
    from .store.entities.accounts import Account, Import
    from .store.repos import ledger as repo

    today = clock.today()
    rows = s.scalars(
        select(Account).where(Account.deleted == false(), Account.closedOn.is_(None))
    ).all()
    for a in rows:
        # A loan is checked on its Overview, against its servicer's balance (S1.11, S1.9.4).
        where = f"/ui/accounts/{a.id}" + ("/reconcile" if atypes.reconcilable(a.type) else "")
        imports = s.scalars(
            select(Import).where(Import.accountId == a.id, Import.deleted == false())
        ).all()
        if not imports:
            continue
        late = expected.overdue(a, imports, today)
        if late is not None:
            yield Cause(
                # One alert per missing statement: it clears when one covering it arrives.
                key=f"statement:{a.id}:{late.periodEnd.isoformat()}",
                kind="statement-overdue",
                title=f"{a.name}: {late.name} is overdue",
                about=f"{expected.interval(a)} statements · the last ended "
                f"{late.periodStart - dt.timedelta(days=1):%b %-d} · "
                f"overdue from {late.due:%b %-d}",
                user_id=a.ownerId,
                link=where,
                fix="Import a statement",
                icon="receipt",
                since=dt.datetime.combine(late.due, dt.time(), dt.UTC),
            )
        ledger = repo.load(s, a)
        checks = reconcile.checks(
            ledger.opening(), ledger.transactions, ledger.anchors, reconcile.coverage(imports)
        )
        if checks and not checks[-1].ok:
            yield Cause(
                key=f"mismatch:{a.id}",
                kind="reconcile-mismatch",
                title=f"{a.name}: the balance disagrees with the institution's",
                about=f"since {checks[-1].date:%b %-d, %Y}",
                user_id=a.ownerId,
                link=f"/ui/accounts/{a.id}/reconcile",
                fix="Reconcile",
                icon="alert",
                delay=dt.timedelta(days=MISMATCH_DAYS),
            )


@check
def statement_values(s: Session, server) -> Iterable[Cause]:
    """For each account's owner: a holding valued from a statement more than 90 days old
    (S4.3), until a newer statement, a price or a sale replaces it."""
    from . import valuation
    from .ledger import types as atypes
    from .prices.refresh import STATEMENT_STALE_DAYS
    from .store.entities.accounts import Account
    from .store.repos import ledger as repo

    today = clock.today()
    for a in s.scalars(
        select(Account).where(Account.deleted == false(), Account.closedOn.is_(None))
    ):
        if not atypes.investing(a.type):
            continue
        held = repo.load(s, a).replay().positions()
        if not held:
            continue
        old = [
            p.asOf
            for p in valuation.prices(s, list(held), today, a.ownerId).values()
            if p.source == "statement" and (today - p.asOf).days > STATEMENT_STALE_DAYS
        ]
        if old:
            oldest = min(old)
            yield Cause(
                key=f"statement-value:{a.id}",
                kind="statement-value-old",
                title=f"{a.name}: a holding is valued from a statement over 90 days old",
                about=f"the statement of {oldest:%b %-d, %Y} · import a newer one, or type a price",
                user_id=a.ownerId,
                link=f"/ui/accounts/{a.id}/holdings",
                fix="See the holdings",
                icon="receipt",
                since=dt.datetime.combine(
                    oldest + dt.timedelta(days=STATEMENT_STALE_DAYS + 1), dt.time(), dt.UTC
                ),
            )


@check
def cash_short(s: Session, server) -> Iterable[Cause]:
    """For each user's active budget, each checking account with recurring payments out whose
    balance, less those expected before its next money in, would fall below zero (S7.6.1)."""
    from . import budgets
    from .budgets import recurring
    from .store.entities.accounts import Account, Transaction
    from .store.entities.budgets import Budget
    from .store.repos import ledger

    today = clock.today()
    for u in s.scalars(
        select(User).where(User.activeBudgetId.is_not(None), User.deleted == false())
    ):
        b_id = budgets.active_id(s, u.id)
        b = s.get(Budget, b_id) if b_id else None
        if b is None:
            continue
        for aid in budgets.account_ids(s, b, u.id):
            a = s.get(Account, aid)
            if a is None or a.type != "checking":
                continue
            txns = s.scalars(
                select(Transaction).where(
                    Transaction.accountId == a.id,
                    Transaction.deleted == false(),
                    Transaction.date >= today - dt.timedelta(days=460),
                )
            ).all()
            # Transfers count here: a regular top-up is money in, a card payment money out.
            series = recurring.detect([_Plain(t) for t in txns], today)
            ins = sorted(x.next for x in series if x.usual > 0 and x.next > today)
            horizon = ins[0] if ins else today + dt.timedelta(days=31)
            outs = sorted(
                (x.next, -x.usual) for x in series if x.usual < 0 and today < x.next < horizon
            )
            if not outs:
                continue
            balance = ledger.load(s, a).balance(today)
            for day, amount in outs:
                balance -= amount
                if balance < 0:
                    before = f"before money comes in on {horizon:%b %-d}" if ins else "this month"
                    yield Cause(
                        key=f"cash:{b.id}:{a.id}",
                        kind="cash-short",
                        title=f"{a.name} dips below $0 on the {_ordinal(day.day)}",
                        about=f"{before} · the recurring payments from it",
                        user_id=u.id,
                        link=f"/ui/budgets/{b.id}/recurring",
                        fix="See the recurring payments",
                        icon="bank",
                    )
                    break


class _Plain:
    """A transaction as the recurring finder sees it, a transfer included."""

    def __init__(self, t):
        self.payee, self.amount, self.accountId, self.date = t.payee, t.amount, t.accountId, t.date
        self.transferId = None
        self.instrumentId = t.instrumentId
        self.categoryId = t.categoryId


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


@check
def projections_behind(s: Session, server) -> Iterable[Cause]:
    """An active projection whose actual balance fell below its baseline's band, as of the end
    of the last month: checked monthly (S6.7.5)."""
    from . import projections
    from .store.entities.projections import Projection

    month_end = clock.today().replace(day=1) - dt.timedelta(days=1)
    for p in s.scalars(select(Projection).where(Projection.active, Projection.deleted == false())):
        if p.baselineAt is None or p.baselineAt.date() >= month_end:
            continue
        track = projections.tracking(s, p, p.ownerId, upto=month_end)
        if track and track["status"] == "behind":
            yield Cause(
                key=f"behind:{p.id}",
                kind="projection-behind",
                title=f"{p.name} is behind its plan",
                about=f"below the band of the baseline set {p.baselineAt:%b %-d, %Y}",
                user_id=p.ownerId,
                link="/ui/projections",
                fix="See the plan",
                icon="trend",
            )


@check
def options_expired(s: Session, server) -> Iterable[Cause]:
    """An option past its expiry still open: in the money, or with no close to tell, it waits
    for its owner to say what happened (S3.6)."""
    from . import options
    from .ledger import types as atypes
    from .store.entities.accounts import Account, Instrument
    from .store.repos import ledger as repo

    today = clock.today()
    for a in s.scalars(select(Account).where(Account.deleted == false())):
        if not atypes.investing(a.type):
            continue
        for iid in repo.load(s, a).replay().positions():
            c = options.contract_of(s, iid)
            if c is None or c.expiry >= today:
                continue
            inst = s.get(Instrument, iid)
            yield Cause(
                key=f"option-expired:{a.id}:{iid}",
                kind="option-expired",
                title=f"{inst.symbol} expired: what happened?",
                about=f"in {a.name}; expired, assigned or exercised",
                user_id=a.ownerId,
                link="/ui/positions/open",
                fix="Record it",
                icon="candles",
            )


EXPIRING_DAYS = 7


@check
def options_expiring(s: Session, server) -> Iterable[Cause]:
    """An option held that expires within a week (S12.11.1.3): to its account's owner, to
    close, roll or let go; it resolves once it is closed or past its expiry."""
    from . import options
    from .ledger import types as atypes
    from .store.entities.accounts import Account, Instrument
    from .store.repos import ledger as repo

    today = clock.today()
    for a in s.scalars(select(Account).where(Account.deleted == false())):
        if not atypes.investing(a.type):
            continue
        for iid, qty in repo.load(s, a).replay().positions().items():
            c = options.contract_of(s, iid)
            if c is None or not today <= c.expiry <= today + dt.timedelta(days=EXPIRING_DAYS):
                continue
            inst = s.get(Instrument, iid)
            days = (c.expiry - today).days
            when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
            yield Cause(
                key=f"option-expiring:{a.id}:{iid}",
                kind="option-expiring",
                title=f"{inst.symbol} expires {when}",
                about=f"{abs(qty).normalize():f} {'short' if qty < 0 else 'long'} in {a.name}",
                user_id=a.ownerId,
                link="/ui/positions/open",
                fix="See it",
                icon="candles",
            )


@check
def pledges_due(s: Session, server) -> Iterable[Cause]:
    """A pledge not yet met (S7.9.5): a monthly one from the 25th of the month, a yearly one
    from December 1, while less than it has been given to the organisation in that month or
    year. It resolves when the donation is recorded."""
    from decimal import Decimal

    from .store.entities.giving import Donation, Organisation

    today = clock.today()
    for o in s.scalars(
        select(Organisation).where(Organisation.deleted == false(), Organisation.pledge > 0)
    ):
        if o.pledgeEvery == "month" and today.day >= 25:
            first, period = today.replace(day=1), f"{today:%B}"
        elif o.pledgeEvery == "year" and today.month == 12:
            first, period = today.replace(month=1, day=1), str(today.year)
        else:
            continue
        given = sum(
            (
                d.amount
                for d in s.scalars(
                    select(Donation).where(
                        Donation.organisationId == o.id,
                        Donation.ownerId == o.ownerId,
                        Donation.deleted == false(),
                        Donation.date >= first,
                        Donation.date <= today,
                    )
                )
            ),
            Decimal(0),
        )
        if given >= o.pledge:
            continue
        yield Cause(
            key=f"pledge:{o.id}:{first.isoformat()}",
            kind="pledge-due",
            title=f"Your pledge to {o.name} is due",
            about=f"for {period}",
            user_id=o.ownerId,
            link="/ui/giving/organisations",
            fix="Record a donation",
            icon="heart",
        )


@check
def occasions(s: Session, server) -> Iterable[Cause]:
    """An occasion inside its reminder time with nothing bought for it yet (S7.7.3)."""
    from . import gifts

    today = clock.today()
    for u in s.scalars(
        select(User).where(User.active, User.deleted == false(), User.linkId.is_(None))
    ):
        for up in gifts.upcoming(s, u.id, today):
            if not up.inLead or any(g.status in gifts.SPENT for g in up.gifts):
                continue
            yield Cause(
                key=f"occasion:{u.id}:{up.person.id}:{up.date.key}:{up.date.date.isoformat()}",
                kind="occasion",
                title=occasion_title(up),
                about=gifts.what_is_missing(up),
                user_id=u.id,
                link="/ui/gifts",
                fix="Plan a gift",
                icon="gift",
            )


@check
def share_asked(s: Session, server) -> Iterable[Cause]:
    """Someone asked for a private person to be shared (S10.10.3): to whoever added them and
    to the admins, until the person is shared with the asker or no longer private."""
    from . import people
    from .store.entities.core import Activity
    from .store.entities.education import Person

    since = clock.now() - dt.timedelta(days=KEEP_RESOLVED_DAYS)
    for a in s.scalars(
        select(Activity).where(Activity.kind == "person.share-asked", Activity.at >= since)
    ):
        p = s.get(Person, a.subjectId)
        asker = s.get(User, a.actorId) if a.actorId else None
        if p is None or p.deleted or not p.private or asker is None or not asker.active:
            continue
        if people.readable(s, asker.id, p.id):
            continue
        for to in {p.ownerId, None}:
            yield Cause(
                key=f"share-asked:{p.id}:{asker.id}:{to or 'admins'}",
                kind="share-asked",
                title=f"{asker.displayName} asks to see {p.name}",
                about="Share the person, or make them seen by the household",
                user_id=to,
                link="/ui/gifts/people",
                fix="Share",
                icon="share",
                since=a.at,
            )


def occasion_title(up) -> str:
    """'Emma's birthday in 9 days'; a holiday or a named date keeps its capitals."""
    when = "today" if up.days == 0 else "tomorrow" if up.days == 1 else f"in {up.days} days"
    plain = up.date.kind in ("birthday", "anniversary") and up.date.label in (
        "Birthday",
        "Anniversary",
    )
    label = up.date.label.lower() if plain else up.date.label
    return f"{up.person.name}'s {label} {when}"


# ---------- running the checks ----------


def recipients(s: Session, alert: Alert) -> list[User]:
    from .auth.users import admin_ids

    if alert.userId:
        wanted = [alert.userId]
    else:
        # An admin who owns what failed is told once, as its owner (S12.11.2).
        admins = admin_ids(s)
        owners = set(
            s.scalars(
                select(Alert.userId).where(
                    Alert.userId.in_(admins),
                    Alert.causeKey.in_([f"{alert.causeKey}:{a}" for a in admins]),
                    Alert.openedAt.is_not(None),
                    Alert.resolvedAt.is_(None),
                )
            )
        )
        wanted = [a for a in admins if a not in owners]
    return [
        u
        for u in (s.get(User, i) for i in wanted)
        if u is not None and u.active and not u.deleted and u.linkId is None
    ]


def evaluate(server) -> list[Alert]:
    """Run every check in a read transaction, then open, update and resolve alerts, writing
    only what changed (S12.11.2). A check that fails leaves its alerts as they are. Returns the
    alerts that opened."""
    now = clock.now()
    holding: dict[str, Cause] = {}
    failed: set[str] = set()
    with server.db.read(unscoped="alerts: evaluate") as s:
        for fn in CHECKS:
            try:
                for cause in fn(s, server):
                    holding[cause.key] = cause
            except Exception:
                # A check that fails says nothing: its alerts stay as they are.
                log.exception("the alert check %s failed", fn.__name__)
                failed |= _KINDS[fn.__name__]
        current = [
            (a.id, a.causeKey, a.kind, (a.title, a.about, a.link, a.fix), a.openedAt, a.seenSince)
            for a in _unresolved(s)
        ]
    resolve: list[str] = []
    change: dict[str, tuple[Cause, bool]] = {}
    for alert_id, key, kind, shown, opened_at, seen in current:
        cause = holding.pop(key, None)
        if cause is None:
            if kind not in failed:
                resolve.append(alert_id)
            continue
        opens = opened_at is None and seen + cause.delay <= now
        if opens or shown != (cause.title, cause.about, cause.link, cause.fix):
            change[alert_id] = (cause, opens)
    if not (resolve or change or holding):
        return []
    opened: list[Alert] = []
    with server.db.tx(unscoped="alerts: evaluate") as s:
        for alert_id in resolve:
            a = s.get(Alert, alert_id)
            if a is not None and a.resolvedAt is None:
                a.resolvedAt, a.resolution = now, "the cause cleared"
        for alert_id, (cause, opens) in change.items():
            a = s.get(Alert, alert_id)
            if a is None or a.resolvedAt is not None:
                continue
            a.title, a.about, a.link, a.fix = cause.title, cause.about, cause.link, cause.fix
            if opens and a.openedAt is None:
                a.openedAt = now
                opened.append(a)
        for cause in holding.values():
            since = min(cause.since or now, now)
            a = Alert(
                id=ids.new_id("Alert"),
                kind=cause.kind,
                causeKey=cause.key,
                userId=cause.user_id,
                title=cause.title,
                about=cause.about,
                link=cause.link,
                fix=cause.fix,
                icon=cause.icon,
                seenSince=since,
                openedAt=now if since + cause.delay <= now else None,
            )
            s.add(a)
            if a.openedAt:
                opened.append(a)
        s.flush()
        for a in opened:
            _announce(s, server, a)
        notify = {a.id: [u.id for u in recipients(s, a)] for a in opened}
    for users in notify.values():
        # Its count only, never its title: the screen reads the alert through the API (S12.6).
        server.events.publish("alert", {"count": 1}, users=users)
    return opened


# The kinds each check raises: when it fails, these stay as they are.
_KINDS = {
    "price_sources": {"source-failing"},
    "email": {"source-failing"},
    "bitcoin_source": {"source-failing"},
    "linked_servers": {"source-failing", "link-broken", "link-certificate", "link-key-waiting"},
    "backups": {"backup-failed"},
    "reader_sandbox": {"reader-sandbox"},
    "recovery_phrase": {"phrase-check"},
    "key_rotation": {"key-rotation"},
    "break_glass": {"break-glass"},
    "accounts": {"statement-overdue", "reconcile-mismatch"},
    "statement_values": {"statement-value-old"},
    "projections_behind": {"projection-behind"},
    "cash_short": {"cash-short"},
    "bitcoin_certificate": {"node-certificate"},
    "bitcoin_off_chain": {"off-chain"},
    "connector": {"connector-silent", "connector-locked", "connector-moved", "connection-failing"},
    "options_expired": {"option-expired"},
    "options_expiring": {"option-expiring"},
    "pledges_due": {"pledge-due"},
    "occasions": {"occasion"},
    "share_asked": {"share-asked"},
}


def _unresolved(s: Session) -> list[Alert]:
    return list(s.scalars(select(Alert).where(Alert.resolvedAt.is_(None))))


def _sends(s: Session, server) -> bool:
    """Without SMTP the choice is kept, but nothing is sent (dev mode writes to its folder)."""
    return server.config.dev or bool(settings.get(s, "smtpHost"))


def _announce(s: Session, server, a: Alert) -> None:
    """Email it to those who chose each alert: once, when it opens."""
    if not _sends(s, server):
        return
    from .mail import Email

    for u in recipients(s, a):
        if u.alertEmails != "each" or not u.email:
            continue
        server.services.mailer.send(
            s,
            Email(
                u.email,
                f"MoolaKata alert: {a.title}",
                (
                    f"Hello {u.displayName},\n\n{a.title}\n{a.about}\n\n"
                    f"{_where(s, server, a)}"
                    "Alerts resolve by themselves when their cause clears. Choose how they "
                    "reach you in Profile.\n"
                ),
            ),
        )
        state = _state(s, a.id, u.id)
        state.emailedAt = clock.now()


def _where(s: Session, server, a: Alert) -> str:
    from .mail import base_url

    try:
        return f"{a.fix or 'See it'}: {base_url(s, server.config)}{a.link or '/ui/alerts'}\n\n"
    except Exception:
        return ""


def _state(s: Session, alert_id: str, user_id: str) -> AlertState:
    st = s.scalars(
        select(AlertState).where(AlertState.alertId == alert_id, AlertState.userId == user_id)
    ).first()
    if st is None:
        st = AlertState(alertId=alert_id, userId=user_id)
        s.add(st)
    return st


# ---------- what a user sees ----------


def visible(s: Session, user_id: str, admin: bool):
    """The alerts for one user: their own, and the admins' when they are one, but for those
    they have as the owner of what failed (S12.11.2)."""
    who = Alert.userId == user_id
    if admin:
        who = or_(who, and_(Alert.userId.is_(None), ~_owned(user_id)))
    cutoff = clock.now() - dt.timedelta(days=KEEP_RESOLVED_DAYS)
    return (
        select(Alert, AlertState)
        .outerjoin(AlertState, and_(AlertState.alertId == Alert.id, AlertState.userId == user_id))
        .where(
            who,
            Alert.openedAt.is_not(None),
            or_(Alert.resolvedAt.is_(None), Alert.resolvedAt >= cutoff),
        )
        .order_by(Alert.openedAt.desc())
    )


def _owned(user_id: str):
    """An admins' alert the user also has as the owner of what failed: a Connection that keeps
    their accounts current, their wallets' explorer or node. The owner's alert has the admins'
    key and the owner's id, and opens and resolves with it."""
    own = aliased(Alert)
    return (
        select(own.id)
        .where(
            own.userId == user_id,
            own.causeKey == Alert.causeKey + f":{user_id}",
            own.openedAt.is_not(None),
            own.resolvedAt.is_(Alert.resolvedAt),
        )
        .exists()
    )


def unseen(s: Session, user_id: str, admin: bool) -> int:
    return sum(
        1
        for a, st in s.execute(visible(s, user_id, admin))
        if a.resolvedAt is None and (st is None or (st.seenAt is None and st.dismissedAt is None))
    )


def mark_seen(s: Session, user_id: str, admin: bool) -> None:
    now = clock.now()
    for a, st in s.execute(visible(s, user_id, admin)).all():
        if a.resolvedAt is None and (st is None or st.seenAt is None):
            _state(s, a.id, user_id).seenAt = now


def dismiss(s: Session, user_id: str, admin: bool, alert_id: str) -> bool:
    for a, st in s.execute(visible(s, user_id, admin)).all():
        if a.id == alert_id and a.resolvedAt is None and (st is None or st.dismissedAt is None):
            st = _state(s, a.id, user_id)
            st.dismissedAt = st.seenAt = clock.now()
            return True
    return False


# ---------- the daily summary (S12.11.5) ----------


def daily_summaries(server) -> int:
    """For each user on the daily summary, once their day has passed the summary's time:
    the alerts opened since the last one, or nothing on a day without any."""
    from .auth.users import is_admin
    from .mail import Email

    sent = 0
    now = clock.now()
    with server.db.tx(unscoped="alerts: daily summaries") as s:
        if not _sends(s, server):
            return 0
        at = settings.time_of(s, "alertSummaryTime")
        users = s.scalars(
            select(User).where(
                User.deleted == false(),
                User.active,
                User.linkId.is_(None),
                User.alertEmails == "daily",
                User.email.is_not(None),
            )
        ).all()
        for u in users:
            zone = ZoneInfo(timezones.zone_for(u.timeZone))
            local = now.astimezone(zone)
            if local.time() < at:
                continue
            if u.alertSummaryAt and u.alertSummaryAt.astimezone(zone).date() >= local.date():
                continue
            since = u.alertSummaryAt or now - dt.timedelta(days=1)
            fresh = [
                a
                for a, st in s.execute(visible(s, u.id, is_admin(s, u.id))).all()
                if a.openedAt > since and (st is None or st.dismissedAt is None)
            ]
            u.alertSummaryAt = now
            if not fresh:
                continue
            lines = "\n".join(f"- {a.title} ({a.about})" for a in fresh)
            server.services.mailer.send(
                s,
                Email(
                    u.email,
                    f"MoolaKata: {len(fresh)} new alert{'' if len(fresh) == 1 else 's'}",
                    (
                        f"Hello {u.displayName},\n\nOpened since your last summary:\n\n{lines}\n\n"
                        "See them on the Alerts screen. Choose how alerts reach you in Profile.\n"
                    ),
                ),
            )
            sent += 1
    return sent
