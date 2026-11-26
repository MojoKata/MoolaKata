"""Reimbursable spending (requirements S2.9): what a budget's accounts await, the deposits that
may pay it back, and pairing them."""

import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import false, select

from .. import access, activity, budgets, clock, reimbursements
from ..errors import Problem, refuse
from ..store import scoping
from ..store.entities.accounts import Account, Reimbursement, Split, Transaction
from ..store.entities.budgets import Budget
from . import save
from .conventions import ExactRoute, Model, Money
from .deps import Caller, caller, server

# How an account not shared with the viewer is named to them (S7.1.1).
NOT_SHARED = "an account not shared"
ZERO = reimbursements.ZERO

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["reimbursements"])


class Offer(Model):
    transactionId: str
    date: dt.date
    payee: str | None
    accountName: str
    free: Money  # what of it isn't paying other spending back yet


class AwaitingRow(Model):
    # No ids, date, payee, category, owed-by or age: an account not shared with the viewer,
    # its rows added into one (S7.1.1).
    spendingId: str | None
    splitId: str | None
    date: dt.date | None
    payee: str | None
    accountName: str
    category: str | None
    owedBy: str | None
    reimbursable: Money
    paidBack: Money
    awaited: Money
    ageDays: int | None
    offers: list[Offer]


class PairIn(Model):
    spendingId: str
    splitId: str | None = None
    paybackId: str
    amount: Money


class PairOut(Model):
    id: str
    spendingId: str
    splitId: str | None
    paybackId: str
    amount: Money
    version: int


def _out(r: Reimbursement) -> PairOut:
    return PairOut(
        id=r.id,
        spendingId=r.spendingId,
        splitId=r.splitId,
        paybackId=r.paybackId,
        amount=r.amount,
        version=r.version,
    )


def _writable(s, user_id: str) -> list[Account]:
    return [a for a, p in access.accounts(s, user_id) if p.writable]


@router.get("/budgets/{budget_id}/reimbursements", response_model=list[AwaitingRow])
def awaiting(budget_id: str, request: Request, c: Caller = Depends(caller)):
    """What the budget's accounts await, oldest first, each with the deposits that may pay it
    back among the caller's own accounts and those they can change. Once access to the budget
    is checked, read as the server reads it: every account `members` gives the caller, the
    owner's own among them; one not shared with the caller is never named, nor its rows' ids,
    dates or payees given, its rows added into one (S7.1.1)."""
    today = clock.today()
    with server(request).db.read(user=c.id) as s:
        b, _ = access.budget(s, c.id, budget_id)
        with scoping.as_server(s, "what a budget's accounts await, for one who reads it",
                               False) as srv:  # fmt: skip
            accts = budgets.account_ids(srv, srv.get(Budget, b.id), c.id, today)
            items = [x for x in reimbursements.marked(srv, accts) if x.awaited > 0]
        names = {a.id: a.name for a, _ in access.accounts(s, c.id, Account.id.in_(accts))}
        tr = budgets.tree(s)
        mine_names = {a.id: a.name for a in _writable(s, c.id)}
        out: list[AwaitingRow] = []
        withheld: dict[str, AwaitingRow] = {}
        for item in items:
            if item.accountId not in names:
                got = withheld.get(item.accountId)
                if got is None:
                    got = withheld[item.accountId] = AwaitingRow(
                        spendingId=None, splitId=None, date=None, payee=None,
                        accountName=NOT_SHARED, category=None, owedBy=None,
                        reimbursable=ZERO, paidBack=ZERO, awaited=ZERO, ageDays=None, offers=[],
                    )  # fmt: skip
                    out.append(got)
                got.reimbursable += item.reimbursable
                got.paidBack += item.paidBack
                got.awaited += item.awaited
                continue
            out.append(
                AwaitingRow(
                    spendingId=item.spendingId,
                    splitId=item.splitId,
                    date=item.date,
                    payee=item.payee,
                    accountName=names[item.accountId],
                    category=tr.label(item.categoryId) if item.categoryId in tr.by_id else None,
                    owedBy=item.owedBy,
                    reimbursable=item.reimbursable,
                    paidBack=item.paidBack,
                    awaited=item.awaited,
                    ageDays=(today - item.date).days,
                    offers=[
                        Offer(
                            transactionId=t.id,
                            date=t.date,
                            payee=t.payee,
                            accountName=mine_names[t.accountId],
                            free=free,
                        )
                        for t, free in reimbursements.offers(s, item, list(mine_names))
                    ],
                )
            )
        return out


def _pair(s, c: Caller, body: PairIn, pair_id: str) -> Reimbursement:
    """A deposit paired with reimbursable spending: that much of it pays the spending back and
    isn't income (S2.9.2)."""
    spent = s.get(Transaction, body.spendingId)
    if spent is None or spent.deleted:
        raise Problem(404, "not-found", "No such transaction.")
    a, _ = access.account(s, c.id, spent.accountId, "write")
    mark = spent.reimbursable
    if body.splitId:
        sp = s.get(Split, body.splitId)
        if sp is None or sp.deleted or sp.transactionId != spent.id:
            raise refuse("splitId", "not-found", "No such part of the transaction.")
        mark = sp.reimbursable
    if mark is None:
        raise refuse("spendingId", "not-reimbursable", "Mark it reimbursable first.")
    paid = sum(
        (
            r.amount
            for r in s.scalars(
                select(Reimbursement).where(
                    Reimbursement.spendingId == spent.id,
                    Reimbursement.deleted == false(),
                )
            )
            if r.splitId == body.splitId
        ),
        reimbursements.ZERO,
    )
    back = s.get(Transaction, body.paybackId)
    if back is None or back.deleted:
        raise refuse("paybackId", "not-found", "No such deposit.")
    access.account(s, c.id, back.accountId, "write")
    if back.amount <= 0 or back.transferId or back.instrumentId:
        raise refuse("paybackId", "not-a-deposit", "Choose money that came in.")
    free = back.amount - reimbursements.paired_out(s, [back.id]).get(back.id, reimbursements.ZERO)
    if body.amount <= 0 or body.amount > mark - paid or body.amount > free:
        raise refuse(
            "amount",
            "amount-invalid",
            "No more than is awaited, nor than is left of the deposit.",
        )
    r = Reimbursement(
        id=pair_id,
        spendingId=spent.id,
        splitId=body.splitId,
        paybackId=back.id,
        amount=body.amount,
        createdById=c.id,
    )
    s.add(r)
    activity.record(
        s,
        "reimbursement.paired",
        actor=c.id,
        subject_kind="account",
        subject_id=a.id,
        owner=a.ownerId,
    )
    return r


def _pair_editable(ctx, record_id: str) -> Reimbursement:
    r = ctx.s.get(Reimbursement, record_id)
    if r is None or r.deleted:
        raise Problem(404, "not-found", "No such pairing.")
    access.account(ctx.s, ctx.caller.id, ctx.s.get(Transaction, r.spendingId).accountId, "write")
    return r


def _pair_update(ctx, r: Reimbursement, body: PairIn) -> None:
    raise refuse(None, "pairing-fixed", "A pairing isn't changed: unpair it, and pair again.")


def _unpair(ctx, r: Reimbursement) -> None:
    a = ctx.s.get(Account, ctx.s.get(Transaction, r.spendingId).accountId)
    r.mark_deleted(ctx.caller.id)
    activity.record(ctx.s, "reimbursement.unpaired", actor=ctx.caller.id,
                    subject_kind="account", subject_id=a.id, owner=a.ownerId)  # fmt: skip


save.register(
    save.Kind(
        prefix="Rmbrs",
        entity=Reimbursement,
        fields=PairIn,
        create=lambda ctx, record_id, body: _pair(ctx.s, ctx.caller, body, record_id),
        editable=_pair_editable,
        current=lambda ctx, r: {f: getattr(r, f) for f in PairIn.model_fields},
        update=_pair_update,
        delete=_unpair,
        read=lambda ctx, record_id: _out(ctx.s.get(Reimbursement, record_id)),
    )
)
