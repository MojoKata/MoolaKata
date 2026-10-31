"""The Dashboard (requirements S12.2.1): net worth and its change, the net-worth chart, the
accounts by group, and what needs attention."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import false, func, select

from .. import access, budgets, figures, valuation
from ..ledger import expected, reconcile
from ..ledger import types as atypes
from ..prices import refresh as pricing
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
    spent: Money
    plannedSpending: Money
    daysLeft: int


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
            v = budgets.month_view(s, b, budgets.month_of(today), today, c.id)
            card = BudgetCard(
                id=b.id,
                name=b.name,
                month=v.month,
                spent=v.spent,
                plannedSpending=v.plannedSpending,
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
        )


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
        if not atypes.reconcilable(a.type) or not a.active:
            continue
        led = repo.load(s, a)
        checks = reconcile.checks(
            led.opening(), led.transactions, led.anchors, reconcile.coverage(led.imports)
        )
        if checks and not checks[-1].ok:
            out.append(
                Attention(
                    kind="mismatch",
                    count=1,
                    text=f"{a.name}: a reported balance doesn't match",
                    link=f"/ui/accounts/{a.id}/reconcile",
                )
            )
        elif late := expected.overdue(a, led.imports, today):
            out.append(
                Attention(
                    kind="anchor",
                    count=1,
                    text=f"{a.name}: {late.name} is overdue",
                    link=f"/ui/accounts/{a.id}/reconcile",
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

    for b, lvl in taxbooks.visible(s, c.id):
        if lvl not in ("owner", "write"):
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
