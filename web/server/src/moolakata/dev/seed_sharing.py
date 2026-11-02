"""Dev mode's shares and portfolios (requirements S17.7), so every sharing mark shows."""

from sqlalchemy import func, select

from .. import activity, clock, ids, sharing
from ..store.entities.accounts import Account, Import, Transaction
from ..store.entities.sharing import CountedAccount, Portfolio, PortfolioAccount
from ..store.entities.users import Group


def seed_sharing(s, people: dict) -> None:
    alice, bob = people["alice"], people["bob"]
    acct = {a.name: a for a in s.scalars(select(Account))}
    household = s.scalars(select(Group).where(Group.name == "Household")).one()
    now = clock.now()

    def grant(kind, item, allow, user=None, group=None, by=alice):
        s.add(
            sharing.new_share(
                kind,
                item.id,
                allow,
                user_id=user.id if user else None,
                group_id=group.id if group else None,
                by=by.id,
            )
        )

    grant("account", acct["Everyday checking"], "read", group=household)
    grant("account", acct["Emergency savings"], "write", user=bob)
    grant("account", acct["Rollover IRA"], "read", user=alice, by=bob)
    s.add(CountedAccount(userId=alice.id, accountId=acct["Rollover IRA"].id, createdAt=now))

    def portfolio(owner, name, names, benchmark="VT"):
        p = Portfolio(id=ids.new_id("Portf"), ownerId=owner.id, name=name, benchmark=benchmark)
        s.add(p)
        s.flush()
        for n in names:
            s.add(PortfolioAccount(portfolioId=p.id, accountId=acct[n].id, createdAt=now))
        return p

    retirement = portfolio(
        alice, "Retirement", ["Roth IRA", "Acme 401(k)", "Health savings"], "60-40"
    )
    portfolio(alice, "Family investing", ["Taxable brokerage", "Roth IRA", "Rollover IRA"], "SPY")
    grant("portfolio", retirement, "read", user=bob)
    s.flush()
    _history(s)


def _history(s) -> None:
    """Activity for what the seed made, so the Activity screen has something to show."""
    for a in s.scalars(select(Account).order_by(Account.createdAt)):
        activity.record(
            s,
            "account.created",
            actor=a.ownerId,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
        )
    for i in s.scalars(select(Import).order_by(Import.createdAt)):
        a = s.get(Account, i.accountId)
        added = s.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.importId == i.id)
        )
        activity.record(
            s,
            "account.imported",
            actor=i.userId,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
            detail={"added": added, "matched": 0, "changed": 0, "format": i.format},
        )
    for p in s.scalars(select(Portfolio)):
        activity.record(
            s,
            "portfolio.created",
            actor=p.ownerId,
            subject_kind="portfolio",
            subject_id=p.id,
            owner=p.ownerId,
        )
    for sh in sorted(sharing.every_share(s), key=lambda x: x.id.split("_", 1)[1]):
        owner = sharing.item(s, sh.kind, sh.targetId).ownerId
        activity.record(
            s,
            "share.given",
            actor=sh.createdById,
            subject_kind=sh.kind,
            subject_id=sh.targetId,
            owner=owner,
            detail={
                "granteeKind": "user" if sh.userId else "group",
                "granteeId": sh.userId or sh.groupId,
                "allow": sharing.allow_of(sh),
            },
        )
