"""Bitcoin moved between the owner's accounts (requirements S1.7.1): a transfer out and a
transfer in of the same amount (the network fee is a sale of its own, S8.19), within 3 days,
are proposed as a pair. Confirmed, the coins arrive with the lots they left with: the basis
and the day each was acquired carry over, so nothing is missing a basis and nothing is taxed."""

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import clock, ids
from ..store.entities.accounts import Account, Instrument, Lot, Transaction, TransferMatch
from ..store.repos import ledger as repo

DAYS = 3


def _taken(s: Session, owner_id: str) -> set[str]:
    """Transactions in a pair proposed or confirmed, or one turned down with this partner."""
    out = set()
    for m in s.scalars(
        select(TransferMatch).where(
            TransferMatch.ownerId == owner_id,
            TransferMatch.deleted == false(),
            TransferMatch.state != "rejected",
        )
    ):
        out |= {m.outId, m.inId}
    return out


def _chain(t: Transaction) -> str | None:
    """The transaction on the chain a wallet's row records, or None for a line with none."""
    return t.fitId.removeprefix("btc:") if t.fitId and t.fitId.startswith("btc:") else None


def _alike(o: Transaction, i: Transaction) -> bool:
    """Two wallets' sides are one transaction on the chain: the same id, whatever their dates,
    and two ids never; a side with none (an exchange's or a brokerage's line) pairs within
    days (S1.7.1)."""
    a, b = _chain(o), _chain(i)
    if a and b:
        return a == b
    return abs((i.date - o.date).days) <= DAYS


def propose(s: Session, owner_id: str) -> int:
    """Shares, funds or coins that left one of the owner's accounts and arrived in another,
    the same quantity within days, proposed as a pair (S1.7.1): confirmed, they carry
    the lots they left with."""
    accounts = {
        a.id: a
        for a in s.scalars(
            select(Account).where(Account.ownerId == owner_id, Account.deleted == false())
        )
    }
    rows = list(
        s.scalars(
            select(Transaction).where(
                Transaction.accountId.in_(list(accounts)),
                Transaction.instrumentId.is_not(None),
                Transaction.kind.in_(("transfer-in", "transfer-out")),
                Transaction.transferId.is_(None),
                Transaction.deleted == false(),
            )
        )
    )
    taken = _taken(s, owner_id)
    rejected = {
        (m.outId, m.inId)
        for m in s.scalars(
            select(TransferMatch).where(
                TransferMatch.ownerId == owner_id, TransferMatch.state == "rejected"
            )
        )
    }
    made = 0
    outs = [t for t in rows if t.kind == "transfer-out" and t.id not in taken]
    ins = [t for t in rows if t.kind == "transfer-in" and t.id not in taken]
    for o in sorted(outs, key=lambda t: t.date):
        for i in sorted(ins, key=lambda t: (_chain(t) != _chain(o), abs((t.date - o.date).days))):
            if (
                i.id in taken
                or i.accountId == o.accountId
                or i.instrumentId != o.instrumentId
                or abs(i.quantity or 0) != abs(o.quantity or 0)
                or not _alike(o, i)
                or (o.id, i.id) in rejected
            ):
                continue
            s.add(TransferMatch(id=ids.new_id("XfrMt"), ownerId=owner_id, outId=o.id, inId=i.id))
            taken |= {o.id, i.id}
            made += 1
            break
    s.flush()
    return made


def pending(s: Session, owner_id: str) -> list[TransferMatch]:
    return list(
        s.scalars(
            select(TransferMatch).where(
                TransferMatch.ownerId == owner_id,
                TransferMatch.state == "proposed",
                TransferMatch.deleted == false(),
            )
        )
    )


def confirm(s: Session, user_id: str, m: TransferMatch) -> int:
    """The pair linked, and the coins opened in the receiving account with the lots they left
    with: acquired on the same days, with the same basis. Returns the lots opened."""
    out = s.get(Transaction, m.outId)
    into = s.get(Transaction, m.inId)
    src = s.get(Account, out.accountId)
    moved = repo.load(s, src).replay().moved.get(out.id, [])
    for lot in s.scalars(select(Lot).where(Lot.transactionId == into.id, Lot.deleted == false())):
        lot.mark_deleted(user_id)
    n = 0
    for lot in moved:
        s.add(
            Lot(
                id=ids.new_id("Lot"),
                accountId=into.accountId,
                instrumentId=into.instrumentId,
                transactionId=into.id,
                acquiredOn=lot.acquiredOn,
                quantity=lot.quantity,
                costBasis=lot.basis,
                basisMissing=lot.basis is None,
            )
        )
        n += 1
    out.transferId, into.transferId = into.id, out.id
    m.state = "confirmed"
    m.updatedAt = clock.now()
    s.flush()
    return n


def reject(s: Session, m: TransferMatch) -> None:
    m.state = "rejected"
    m.updatedAt = clock.now()


def describe(s: Session, m: TransferMatch) -> dict:
    out = s.get(Transaction, m.outId)
    into = s.get(Transaction, m.inId)
    return {
        "id": m.id,
        "fromAccount": s.get(Account, out.accountId).name,
        "toAccount": s.get(Account, into.accountId).name,
        "fromDate": out.date,
        "toDate": into.date,
        "sats": int(abs(out.quantity) * 100_000_000),
        "symbol": s.get(Instrument, out.instrumentId).symbol,
        "quantity": abs(out.quantity),
        "version": m.version,
    }
