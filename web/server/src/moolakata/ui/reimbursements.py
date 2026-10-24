"""Reimbursable spending (requirements S2.9): what a budget's accounts await, the deposits that
may pay it back, and pairing them."""

import datetime as dt

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import false, select

from .. import access, activity, budgets, clock, ids, reimbursements
from ..errors import Problem, refuse
from ..store.entities.accounts import Account, Reimbursement, Split, Transaction
from .conventions import Deleted, ExactRoute, Model, Money, check, gone, if_match
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["reimbursements"])


class Offer(Model):
    transactionId: str
    date: dt.date
    payee: str | None
    accountName: str
    free: Money  # what of it isn't paying other spending back yet


class AwaitingRow(Model):
    spendingId: str
    splitId: str | None
    date: dt.date
    payee: str | None
    accountName: str
    category: str | None
    owedBy: str | None
    reimbursable: Money
    paidBack: Money
    awaited: Money
    ageDays: int
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
    return [a for a, lvl in access.visible_accounts(s, user_id) if lvl in ("owner", "write")]


@router.get("/budgets/{budget_id}/reimbursements", response_model=list[AwaitingRow])
def awaiting(budget_id: str, request: Request, c: Caller = Depends(caller)):
    """What the budget's accounts await, oldest first, each with the deposits that may pay it
    back among the caller's own accounts and those they can change."""
    today = clock.today()
    with server(request).db.read() as s:
        b, _ = access.budget(s, c.id, budget_id)
        accts = budgets.account_ids(s, b, c.id)
        names = {a.id: a.name for a in s.scalars(select(Account).where(Account.id.in_(accts)))}
        tr = budgets.tree(s)
        mine = _writable(s, c.id)
        mine_names = {a.id: a.name for a in mine}
        out = []
        for item in reimbursements.marked(s, accts):
            if item.awaited <= 0:
                continue
            out.append(
                AwaitingRow(
                    spendingId=item.spendingId,
                    splitId=item.splitId,
                    date=item.date,
                    payee=item.payee,
                    accountName=names.get(item.accountId, "an account not shared"),
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


@router.post("/reimbursements", response_model=PairOut, status_code=201)
def pair(body: PairIn, request: Request, c: Caller = Depends(caller)):
    """A deposit paired with reimbursable spending: that much of it pays the spending back and
    isn't income (S2.9.2)."""
    with server(request).db.tx() as s:
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
        free = back.amount - reimbursements.paired_out(s, [back.id]).get(
            back.id, reimbursements.ZERO
        )
        if body.amount <= 0 or body.amount > mark - paid or body.amount > free:
            raise refuse(
                "amount",
                "amount-invalid",
                "No more than is awaited, nor than is left of the deposit.",
            )
        r = Reimbursement(
            id=ids.new_id("Rmbrs"),
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
        s.flush()
        out = _out(r)
    # Read only within the transactions it pairs: no route of its own (S13.8.4).
    return JSONResponse(out.model_dump(mode="json"), status_code=201)


@router.delete("/reimbursements/{pair_id}", response_model=Deleted[None])
def unpair(
    pair_id: str, request: Request, c: Caller = Depends(caller), version: int = Depends(if_match)
):
    with server(request).db.tx() as s:
        r = s.get(Reimbursement, pair_id)
        if r is None or r.deleted:
            raise Problem(404, "not-found", "No such pairing.")
        spent = s.get(Transaction, r.spendingId)
        a, _ = access.account(s, c.id, spent.accountId, "write")
        check(r, version, lambda: _out(r))
        r.mark_deleted(c.id)
        activity.record(
            s,
            "reimbursement.unpaired",
            actor=c.id,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
        )
        s.flush()
        return Deleted[None](deleted=gone(r))
