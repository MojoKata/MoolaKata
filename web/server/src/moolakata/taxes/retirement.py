"""What each movement of money into or out of a retirement account is (requirements S8.6;
CR3-37), worked out once for every reader: a contribution (the owner's or their employer's), a
rollover (between accounts of the same tax treatment, a trustee-to-trustee move too), a
conversion (pre-tax to Roth), or a distribution. A matched transfer tells it by its other
half's account; a source the user set on the transaction says it where none does."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..ledger import types as atypes
from ..store.entities.accounts import Account, Transaction

CASH_KINDS = ("deposit", "withdrawal", "transfer")


def other_account(s: Session, t: Transaction) -> Account | None:
    """The account a matched transfer's other half is in."""
    if not t.transferId:
        return None
    other = s.get(Transaction, t.transferId)
    if other is None or other.deleted:
        return None
    a = s.get(Account, other.accountId)
    return None if a is None or a.deleted else a


def _roth(account_type: str) -> bool:
    return account_type == "roth-ira"


def _pre_tax(account_type: str) -> bool:
    return atypes.TAX.get(account_type) == "deferred"


def classify(s: Session, t: Transaction, account: Account) -> str | None:
    """`employee`, `employer`, `rollover`, `conversion` for money in; `rollover-out`,
    `conversion-out`, `distribution` for money out; None for what isn't cash moved (a trade, a
    dividend, a fee, an amount of nothing)."""
    if t.instrumentId or t.kind not in CASH_KINDS:
        return None
    other = other_account(s, t)
    between = other is not None and atypes.retirement(other.type)
    if t.amount > 0:
        if t.contributionSource in ("employer", "rollover", "conversion"):
            return t.contributionSource
        if between:
            return "conversion" if _pre_tax(other.type) and _roth(account.type) else "rollover"
        return "employee"
    if t.amount < 0:
        if between:
            return (
                "conversion-out" if _pre_tax(account.type) and _roth(other.type) else "rollover-out"
            )
        return "distribution"
    return None
