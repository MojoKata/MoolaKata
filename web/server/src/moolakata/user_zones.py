"""A user's time zones over time (requirements S14.9.2): each in effect from 00:00 of its date,
in that time zone, until the next one starts; before every entry, the earliest. `User.timeZone`
is the one in effect now; a user who never changed it has no entry, and it is theirs at every
moment. *Auto* is kept as it was chosen, and is the server's time zone when used.

A bitcoin transaction is a moment, and its ledger date that moment's day in the time zone in
effect for its owner then (S1.6.2.6.1): a move, from today, never dates the past again; a
correction, from an earlier date, dates again what it covers, in the same save (`change`)."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import false, select, update
from sqlalchemy.orm import Session

from . import activity, clock, ids, timezones
from .store.entities.accounts import Account, Transaction
from .store.entities.users import User, UserTimeZone

# The date the time zone a user had before their first change is kept from, and the earliest
# a change may be from (R3.11): as far back as a birthday's year goes (S12.2.16).
ALL_ALONG = dt.date(1900, 1, 1)


def zone(name: str) -> ZoneInfo:
    """A time zone as kept: *Auto* is the server's."""
    return ZoneInfo(timezones.zone_for(name))


def entries(s: Session, user_id: str) -> list[UserTimeZone]:
    """The user's live entries, oldest first."""
    return list(
        s.scalars(
            select(UserTimeZone)
            .where(UserTimeZone.userId == user_id, UserTimeZone.deleted == false())
            .order_by(UserTimeZone.since)
        )
    )


def start(name: str, since: dt.date) -> dt.datetime:
    """When an entry starts: 00:00 of its date, in its own time zone."""
    return dt.datetime.combine(since, dt.time(), zone(name))


def at(history: list[UserTimeZone], current: str, moment: dt.datetime) -> ZoneInfo:
    """The time zone in effect at a moment: the latest entry started by then, else the earliest;
    with no entry, the user's own."""
    picked = None
    for e in history:
        if start(e.timeZone, e.since) <= moment:
            picked = e
    if picked is None and history:
        picked = history[0]
    return zone(picked.timeZone if picked else current)


class Bitcoin:
    """The time zones of one owner, for dating the moments of their wallets' transactions."""

    def __init__(self, s: Session, owner_id: str):
        self.history = entries(s, owner_id)
        self.current = s.get(User, owner_id).timeZone

    def day(self, moment: dt.datetime) -> dt.date:
        return moment.astimezone(at(self.history, self.current, moment)).date()


def change(s: Session, u: User, record_id: str, name: str, since: dt.date) -> int:
    """`name` in effect for the user from `since` on, later entries it covers replaced: today's
    date for a move, an earlier one for a correction. Their bitcoin transactions from its start
    on are dated again in it, with their fee's sale and cash; one whose date isn't its moment's
    day in the time zone in effect before was typed by hand, and stays. Returns those dated
    again. The write's closed-year check (S2.8.2) asks about a closed year's gains it moves."""
    before = entries(s, u.id)
    was = u.timeZone
    now = clock.now()
    if not before and since > ALL_ALONG:
        # The time zone they had all along, so a move or a correction keeps what came before.
        s.add(UserTimeZone(id=ids.new_id("UsrTz"), userId=u.id, timeZone=was, since=ALL_ALONG))
    for e in before:
        if e.since >= since:
            e.mark_deleted(u.id, now)
    s.add(UserTimeZone(id=record_id, userId=u.id, timeZone=name, since=since))
    # The one in effect now, kept on the user as their own: no other draft of theirs is made
    # stale by it, as no draft holds it.
    from .store.tables.users import User as UserTable

    s.execute(update(UserTable).where(UserTable.c.id == u.id).values(timeZone=name))
    s.expire(u, ["timeZone"])
    activity.record(s, "profile.updated", actor=u.id, subject_kind="user", subject_id=u.id,
                    owner=u.id, detail={"fields": ["timeZone"]})  # fmt: skip
    s.flush()
    return _redate(s, u.id, before, was, name, start(name, since))


def _redate(
    s: Session, user_id: str, before: list[UserTimeZone], was: str, name: str, begins: dt.datetime
) -> int:
    rows = s.scalars(
        select(Transaction)
        .join(Account, Account.id == Transaction.accountId)
        .where(
            Account.ownerId == user_id,
            Account.type == "crypto-wallet",
            Transaction.fitId.like("btc:%"),
            Transaction.confirmedAt >= begins,
            Transaction.deleted == false(),
        )
    ).all()
    new = zone(name)
    accounts: set[str] = set()
    done = 0
    for r in rows:
        moment = r.confirmedAt
        if r.date != moment.astimezone(at(before, was, moment)).date():
            continue  # typed by hand
        day = moment.astimezone(new).date()
        if day == r.date:
            continue
        r.date = day
        txid = r.fitId.removeprefix("btc:")
        for f in s.scalars(
            select(Transaction).where(
                Transaction.accountId == r.accountId,
                Transaction.fitId.in_((f"btcfee:{txid}", f"btcfeecash:{txid}")),
                Transaction.deleted == false(),
            )
        ):
            # The fee's sale is at its new day's price: valued again below, as one waiting.
            f.date, f.amount = day, Decimal(0)
            if f.kind == "sell":
                f.price = None
        accounts.add(r.accountId)
        done += 1
    s.flush()
    from .bitcoin import sync

    for account_id in sorted(accounts):
        sync.revalue_fees(s, account_id)
    return done
