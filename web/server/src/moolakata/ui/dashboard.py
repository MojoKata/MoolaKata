"""The Dashboard (requirements S12.2.1): net worth and its change, the net-worth chart, the
accounts by group, the recurring transactions coming up, and what needs attention."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import false, func, select

from .. import access, budgets, figures, valuation
from ..ledger import expected, reconcile
from ..ledger import types as atypes
from ..prices import refresh as pricing
from ..store import scoping
from ..store.entities.accounts import Lot, Split, Transaction
from ..store.entities.budgets import Budget
from ..store.repos import ledger as repo
from .conventions import ExactRoute, Model, Money
from .deps import Caller, caller, server
from .sharing import counted_for

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["dashboard"])


class Change(Model):
    day: Money | None
    month: Money | None
    year: Money | None


class GroupTotal(Model):
    group: str
    total: Money
    accounts: list[str]
    inNetWorth: bool


class Attention(Model):
    kind: str
    count: int
    text: str
    link: str


class BudgetCard(Model):
    """The active budget's month (S7.12, S12.2.1)."""

    id: str
    name: str
    month: dt.date
    spent: Money  # against the monthly lines and outside the plan (S7.3.12)
    available: Money
    left: Money
    unbacked: Money  # an envelope budget's card spending not backed, named beside (S7.13.2)
    daysLeft: int


class Upcoming(Model):
    """A recurring transaction's next date (S7.5), on the Dashboard's Upcoming card."""

    payee: str
    date: dt.date
    every: str
    amount: Money


class Dashboard(Model):
    netWorth: Money
    change: Change
    investments: Money
    investmentsDay: Money | None
    cash: Money
    cashAccounts: int
    lastUpdated: dt.datetime | None
    groups: list[GroupTotal]
    attention: list[Attention]
    upcoming: list[Upcoming]
    budget: BudgetCard | None


class GroupPoint(Model):
    date: dt.date
    total: Money
    groups: dict[str, Money]


class NetWorthSeries(Model):
    points: list[GroupPoint]
    groups: list[str]


@router.get("/dashboard", response_model=Dashboard)
def dashboard(request: Request, c: Caller = Depends(caller)):
    srv = server(request)
    today = figures.today()
    days = {
        "now": today,
        "day": today - dt.timedelta(days=1),
        "month": today - dt.timedelta(days=30),
        "year": today - dt.timedelta(days=365),
    }
    with srv.db.read(user=c.id) as s:
        mine = figures.net_worth_accounts(s, c.id, counted_for(s, c.id))
        # Each account's ledger is loaded once and valued on the four days the screen needs.
        values: dict[str, dict[str, Decimal]] = {}
        for a in mine:
            ledger = repo.load(s, a)
            investing = atypes.investing(a.type)
            values[a.id] = {
                k: valuation.account_value(s, ledger, investing, d) for k, d in days.items()
            }

        def total(accounts: list, key: str = "now") -> Decimal:
            return sum((values[a.id][key] for a in accounts), Decimal(0))

        now = total(mine)
        investing = [a for a in mine if atypes.investing(a.type)]
        banking = [a for a in mine if atypes.GROUPS[a.type] == "banking"]
        groups: dict[str, list] = {}
        for a in mine:
            groups.setdefault(atypes.GROUPS[a.type], []).append(a)
        visible = access.accounts(s, c.id)
        writable = [a.id for a, p in visible if p.writable]
        attention = _attention(s, c, [a for a, _ in visible], writable, today, srv.config.dev)
        updated = repo.latest_activity(s, [a.id for a in banking])
        card = None
        active = budgets.active_id(s, c.id)
        if active:
            b = s.get(Budget, active)
            # The budget's figures count the owner's accounts not shared with the caller too
            # (S7.1.1), and name none.
            with scoping.as_server(s, "the budget's figures, for one who follows it", False) as w:
                v = budgets.month_view(w, w.get(Budget, b.id), budgets.month_of(today), today, c.id)
            card = BudgetCard(
                id=b.id,
                name=b.name,
                month=v.month,
                spent=v.available - v.left,
                available=v.available,
                left=v.left,
                unbacked=v.unbacked,
                daysLeft=v.daysLeft,
            )
        return Dashboard(
            budget=card,
            netWorth=now,
            change=Change(
                **{k: now - total(mine, k) if mine else None for k in ("day", "month", "year")}
            ),
            investments=total(investing),
            investmentsDay=total(investing) - total(investing, "day") if investing else None,
            cash=total(banking),
            cashAccounts=len(banking),
            lastUpdated=max(updated.values()) if updated else None,
            groups=[
                GroupTotal(
                    group=g,
                    total=total(groups[g]),
                    accounts=[a.name for a in groups[g]],
                    inNetWorth=True,
                )
                for g in atypes.GROUP_ORDER
                if g in groups
            ],
            attention=attention,
            upcoming=_upcoming(s, mine, today),
        )


UPCOMING_DAYS = 30  # how far ahead the Upcoming card looks
UPCOMING_ROWS = 5


def _upcoming(s, mine: list, today: dt.date) -> list[Upcoming]:
    """The recurring transactions of the user's cash and card accounts next expected in the
    coming month, soonest first, each series once (S7.5, S12.2.1); one flagged missed has
    stopped, and is left out. A cash account's transfers
    count, as cash before payday counts them (S7.6.1): a card payment or a mortgage paid from
    checking is money out; a card's own payments in are its checking account's transfers."""
    from ..budgets import recurring

    until = today + dt.timedelta(days=UPCOMING_DAYS)
    out = []
    for a in mine:
        cash = atypes.GROUPS[a.type] == "banking"
        if not cash and a.type != "credit-card":
            continue
        txns = s.scalars(
            select(Transaction).where(
                Transaction.accountId == a.id,
                Transaction.deleted == false(),
                Transaction.date >= today - dt.timedelta(days=460),
            )
        ).all()
        seen = [recurring.WithTransfers(t) for t in txns] if cash else txns
        for x in recurring.detect(seen, today):
            due = [] if x.missed else x.due(today, until)
            if due:
                out.append(Upcoming(payee=x.payee, date=due[0], every=x.every, amount=x.usual))
    out.sort(key=lambda u: (u.date, u.payee))
    return out[:UPCOMING_ROWS]


def _attention(
    s, c: Caller, visible: list, writable: list[str], today: dt.date, dev: bool
) -> list[Attention]:
    out = []
    if writable:
        uncategorised = s.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.accountId.in_(writable),
                Transaction.deleted == false(),
                Transaction.categoryId.is_(None),
                Transaction.transferId.is_(None),
                Transaction.instrumentId.is_(None),
                Transaction.kind.in_(("deposit", "withdrawal")),
                ~Transaction.id.in_(select(Split.transactionId).where(Split.deleted == false())),
            )
        )
        if uncategorised:
            out.append(
                Attention(
                    kind="uncategorised",
                    count=uncategorised,
                    text=f"{uncategorised} transaction"
                    f"{'' if uncategorised == 1 else 's'} to categorise",
                    link="/ui/transactions?category=none",
                )
            )
        missing = s.scalar(
            select(func.count())
            .select_from(Lot)
            .where(Lot.accountId.in_(writable), Lot.deleted == false(), Lot.basisMissing)
        )
        if missing:
            out.append(
                Attention(
                    kind="basis-missing",
                    count=missing,
                    text=f"{missing} lot{'' if missing == 1 else 's'} without a cost basis",
                    link="/ui/accounts",
                )
            )
    for a in visible:
        # The accounts the alerts check, each linked to where it is reconciled (S1.11).
        if not reconcile.checked(a.type) or a.closedOn is not None:
            continue
        led = repo.load(s, a)
        if reconcile.mismatch(s, a, led) is not None:
            out.append(
                Attention(
                    kind="mismatch",
                    count=1,
                    text=f"{a.name}: a reported balance doesn't match",
                    link=reconcile.page(a),
                )
            )
        elif late := expected.overdue(a, led.imports, today):
            out.append(
                Attention(
                    kind="anchor",
                    count=1,
                    text=f"{a.name}: {late.name} is overdue",
                    link=reconcile.page(a),
                )
            )
    # Occasions inside their reminder time with nothing bought yet (S7.7.3).
    from .. import alerts as alerting
    from .. import gifts

    for up in gifts.upcoming(s, c.id, today):
        if up.inLead and not any(g.status in gifts.SPENT for g in up.gifts):
            out.append(
                Attention(
                    kind="occasion",
                    count=1,
                    text=f"{alerting.occasion_title(up)}, {gifts.what_is_missing(up)}",
                    link="/ui/gifts",
                )
            )
    # A filing past its due date, not filed, with no extension still running (S8.15).
    from ..taxes import books as taxbooks
    from ..taxes import closed

    for b, held in taxbooks.visible(s, c.id):
        if not held.writable:
            continue
        for f in taxbooks.filings(s, b):
            if taxbooks.overdue(f, today):
                where = "Federal" if f.jurisdiction == "federal" else (f.place or "A")
                out.append(
                    Attention(
                        kind="filing-overdue",
                        count=1,
                        text=f"{where} return for {b.year} is past its due date",
                        link="/ui/taxes/filings",
                    )
                )
        # Edits made anyway since the federal return was filed, not yet settled (S8.15).
        if closed.unsettled(s, b):
            out.append(
                Attention(
                    kind="changed-after-filing",
                    count=1,
                    text=f"{b.year}'s realized gains changed after the federal return was filed",
                    link="/ui/taxes/issues",
                )
            )
    out += _valuations(s, c, visible, today)
    out += _sources(s, c, dev)
    out += _giving(s, c, today)
    status = pricing.status(s, dev, c.id)
    if status["stale"]:
        out.append(
            Attention(
                kind="stale-prices",
                count=1,
                text="Some prices are stale",
                link="/ui/settings/prices" if c.admin else "/ui/accounts",
            )
        )
    return out


def _valuations(s, c: Caller, visible: list, today: dt.date) -> list[Attention]:
    """The caller's own accounts with a stale valuation: a holding still valued from a
    statement once that value is stale (S4.3), unless the account's next statement is overdue,
    which its own line says; and items valued over a year ago (S1.10.2)."""
    from .. import assets

    out = []
    for a in visible:
        if a.ownerId != c.id or a.closedOn is not None:
            continue
        if atypes.investing(a.type):
            led = repo.load(s, a)
            if (
                expected.overdue(a, led.imports, today) is None
                and valuation.old_statement(s, led, today) is not None
            ):
                out.append(
                    Attention(
                        kind="statement-value-old",
                        count=1,
                        text=f"{a.name}: a holding is still valued from an old statement",
                        link=f"/ui/accounts/{a.id}/holdings",
                    )
                )
        elif assets.is_physical(a.type):
            items = assets.items_of(s, a)
            ds = assets.details(s, items)
            old = sum(1 for it in items if assets.is_stale(it, ds[it.id], today))
            if old:
                out.append(
                    Attention(
                        kind="valuation-old",
                        count=old,
                        text=f"{a.name}: {old} valuation{'' if old == 1 else 's'} over a year old",
                        link=f"/ui/accounts/{a.id}/items",
                    )
                )
    return out


def _sources(s, c: Caller, dev: bool) -> list[Attention]:
    """Sources that need attention (S12.2.1): a Connection of the caller's, or one keeping an
    account of theirs current, that needs a sign-in or is failing (S18.5.3); and, for an
    admin, a price source failing for longer than the alert threshold (S16.16)."""
    from .. import clock, settings
    from ..prices.refresh import SOURCES, enabled
    from ..store.entities.accounts import Account
    from ..store.entities.connector import Connection

    out = []
    keeping = select(Account.connectionId).where(
        Account.ownerId == c.id, Account.deleted == false()
    )
    # Another's Connection keeping the caller's account current is read as the server: its
    # label and state are what the alert raised to them says too (S18.5.3).
    with scoping.as_server(s, "the Connections keeping a user's accounts current", False) as w:
        for row in w.scalars(
            select(Connection)
            .where(
                Connection.deleted == false(),
                Connection.state.in_(("needs-sign-in", "failing")),
                (Connection.ownerId == c.id) | Connection.id.in_(keeping),
            )
            .order_by(Connection.label)
        ):
            needs = row.state == "needs-sign-in"
            out.append(
                Attention(
                    kind="connection-failing",
                    count=1,
                    text=f"{row.label} {'needs a sign-in' if needs else 'is failing'}",
                    link="/ui/profile",
                )
            )
    if c.admin:
        limit = dt.timedelta(hours=settings.get(s, "alertSourceHours"))
        now = clock.now()
        for src in enabled(s, dev):
            if src.lastError and now - (src.lastOkAt or src.createdAt) > limit:
                out.append(
                    Attention(
                        kind="source-failing",
                        count=1,
                        text=f"{SOURCES[src.name].label} is failing",
                        link="/ui/settings/prices",
                    )
                )
    return out


def _giving(s, c: Caller, today: dt.date) -> list[Attention]:
    """The caller's giving this year behind the even pace to its target (S7.9.6), as the
    Giving screen's header counts it."""
    from .. import giving

    plan, _ = giving.plan_for(s, c.id, today.year)
    if plan is None:
        return []
    who = giving.givers(s, plan, c.id)
    given = sum(
        (g.amount for g in giving.donations(s, who, today.year) if giving.counts(plan, g)),
        Decimal(0),
    )
    goal = giving.target(plan, giving.income(s, plan, who, today.year))
    behind = giving.pace(goal, today, today.year) - given
    if goal <= 0 or behind <= 0:
        return []
    return [
        Attention(
            kind="giving-behind",
            count=1,
            text=f"Giving is ${behind:,.0f} behind pace · {given / goal * 100:.0f}% of the target",
            link="/ui/giving",
        )
    ]


@router.get("/dashboard/series", response_model=NetWorthSeries)
def net_worth_series(
    request: Request,
    c: Caller = Depends(caller),
    range: str = Query("1Y", pattern="^(1M|3M|YTD|1Y|5Y|All)$"),
):
    """Net worth over time, with its composition by account group (S5.3)."""
    today = figures.today()
    with server(request).db.read(user=c.id) as s:
        mine = figures.net_worth_accounts(s, c.id, counted_for(s, c.id))
        first = figures.first_day(range, today, figures.earliest(s, mine))
        comb = figures.combine(s, mine, first, today, figures.step_for(first, today))
        groups = sorted({atypes.GROUPS[a.type] for a in mine}, key=atypes.GROUP_ORDER.index)
        by_group: dict[str, dict[dt.date, Decimal]] = {g: {} for g in groups}
        for a in mine:
            g = atypes.GROUPS[a.type]
            for d, v in comb.byAccount[a.id]:
                by_group[g][d] = by_group[g].get(d, Decimal(0)) + v
        return NetWorthSeries(
            groups=groups,
            points=[
                GroupPoint(
                    date=d, total=v, groups={g: by_group[g].get(d, Decimal(0)) for g in groups}
                )
                for d, v in comb.values
            ],
        )
