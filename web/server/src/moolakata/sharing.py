"""Sharing an account or a portfolio with users and groups (requirements S10.3–S10.6, S5.1).

The Share dialog lists every active user and group with None, Read or Write; nothing changes
until Save, which replaces the item's grants as a whole. Removing a share ends the receiver's
access on their next request and deletes their own annotations on the item (their tags).
"""

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from . import access, clock
from .errors import Problem
from .store.entities.accounts import Account, Transaction, TransactionTag
from .store.entities.sharing import Portfolio, PortfolioAccount, Share
from .store.entities.users import User

LEVELS = ("none", "read", "write")


def item(s: Session, kind: str, item_id: str):
    from .store.entities.budgets import Budget
    from .store.entities.education import GiftPlan, Person
    from .store.entities.giving import GivingPlan
    from .store.entities.projections import Projection
    from .store.entities.taxes import TaxBook

    cls = {
        "account": Account,
        "portfolio": Portfolio,
        "budget": Budget,
        "projection": Projection,
        "person": Person,
        "gift-plan": GiftPlan,
        "giving-plan": GivingPlan,
        "tax-book": TaxBook,
    }.get(kind)
    if cls is None:
        raise Problem(404, "not-found", "Not found")
    obj = s.get(cls, item_id)
    if obj is None or obj.deleted:
        raise Problem(404, "not-found", "Not found")
    return obj


def name_of(s: Session, kind: str, obj) -> str:
    """What the Share dialog calls an item; a gift plan by its person."""
    if kind == "gift-plan":
        from .store.entities.education import Person

        return f"Gift plan for {s.get(Person, obj.personId).name}"
    return obj.name


def grants(s: Session, kind: str, item_id: str) -> list[Share]:
    return list(
        s.scalars(
            select(Share).where(
                Share.kind == kind, Share.itemId == item_id, Share.deleted == false()
            )
        )
    )


def portfolio_accounts(s: Session, portfolio_id: str) -> list[Account]:
    return list(
        s.scalars(
            select(Account)
            .join(PortfolioAccount, PortfolioAccount.accountId == Account.id)
            .where(
                PortfolioAccount.portfolioId == portfolio_id,
                PortfolioAccount.deleted == false(),
                Account.deleted == false(),
            )
            .order_by(Account.name)
        )
    )


def hidden_accounts(s: Session, p: Portfolio, user_ids: list[str]) -> dict[str, list[str]]:
    """For each person, the portfolio's accounts they can't see (S5.1.2)."""
    accounts = portfolio_accounts(s, p.id)
    out = {}
    for uid in user_ids:
        r = access.reach(s, uid)
        missing = [a.id for a in accounts if not access.account_level(s, uid, a, r)]
        if missing:
            out[uid] = missing
    return out


def drop_annotations(s: Session, user_id: str, account_id: str) -> None:
    """A removed receiver's own tags on the account's transactions are deleted (S10.4)."""
    now = clock.now()
    for tag in s.scalars(
        select(TransactionTag)
        .join(Transaction, Transaction.id == TransactionTag.transactionId)
        .where(
            Transaction.accountId == account_id,
            TransactionTag.userId == user_id,
            TransactionTag.deleted == false(),
        )
    ):
        tag.mark_deleted(user_id, now)


def link_live(s: Session, link_id: str) -> bool:
    from .store.entities.links import Link

    link = s.get(Link, link_id)
    return link is not None and not link.deleted and link.state in ("active", "paused")


def remove_link_shares(s: Session, link_id: str, by: str | None = None) -> int:
    """When a link ends, the shares naming its users go (S10.3.3)."""
    ids_ = [u.id for u in s.scalars(select(User).where(User.linkId == link_id))]
    if not ids_:
        return 0
    n = 0
    for row in s.scalars(select(Share).where(Share.userId.in_(ids_), Share.deleted == false())):
        row.mark_deleted(by)
        n += 1
    return n
