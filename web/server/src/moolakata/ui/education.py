"""529 plans (requirements S1.8): the plan and its beneficiary (a person, S10.10),
contributions and who made them against the annual gift exclusion, withdrawals against
qualified expenses with their receipts, the Roth IRA rollover, and the Goal tab's education
projection (S6.2.2)."""

import datetime as dt
import json
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import false, select

from .. import access, activity, clock, education, exactjson, ids, people, projections, receipts
from ..access import Perms
from ..errors import Problem, refuse
from ..store.entities.accounts import Account, Transaction
from ..store.entities.education import Contribution, EducationPlan, Person, QualifiedExpense
from ..store.entities.projections import Projection
from ..store.entities.users import User
from . import save
from .conventions import Access, ExactRoute, IdOf, Model, Money
from .deps import Caller, caller, server
from .projections import ProjectionDetail
from .projections import detail as projection_detail
from .receipts import ReceiptRow
from .receipts import row as receipt_row

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["education"])


# ---- The plan ----


class BeneficiaryRef(Model):
    kind: str  # person, or user for a user's own person
    id: str


class BeneficiaryOut(BeneficiaryRef):
    name: str
    birthYear: int | None
    deleted: bool = False


class PlanIn(Model):
    planState: str | None = None
    planName: str | None = None
    beneficiary: BeneficiaryRef | None = None
    openedOn: dt.date | None = None
    stateDeduction: Money | None = None


class RolloverOut(Model):
    possibleFrom: dt.date | None
    limit: Money
    used: Money
    eligible: Money
    available: Money


class PlanOut(Model):
    planState: str | None
    planName: str | None
    beneficiary: BeneficiaryOut | None
    openedOn: dt.date | None
    stateDeduction: Money | None
    contributedThisYear: Money
    rollover: RolloverOut
    access: Access
    id: str | None = None  # the plan's, once it is set
    beneficiaryId: str | None = None  # their person
    version: int = 0  # the plan's: 0 until it is set (S13.8.6)


def _account(s, c: Caller, account_id: str, need: str = "read") -> tuple[Account, Perms]:
    a, held = access.account(s, c.id, account_id, need)
    if a.type != "529":
        raise Problem(409, "not-a-529", "This account isn't a 529 plan.")
    return a, held


def _beneficiary_out(b: education.Beneficiary | None) -> BeneficiaryOut | None:
    if b is None:
        return None
    return BeneficiaryOut(
        kind=b.kind, id=b.id, name=b.name, birthYear=b.birthYear, deleted=b.deleted
    )


def plan_view(s, a: Account, held: Perms) -> PlanOut:
    """The 529's plan; `held` is the reader's on the account, the plan its child."""
    today = clock.today()
    plan = education.plan_of(s, a)
    rows = education.contributions(s, a)
    r = education.rollover(s, a, plan, rows, today)
    return PlanOut(
        planState=plan.planState if plan else None,
        planName=plan.planName if plan else None,
        beneficiary=_beneficiary_out(education.beneficiary(s, plan)),
        openedOn=plan.openedOn if plan else None,
        stateDeduction=plan.stateDeduction if plan else None,
        contributedThisYear=sum((x.amount for x in rows if x.date.year == today.year), Decimal(0)),
        rollover=RolloverOut(**r.__dict__),
        access=Access.of(held.child()),
        id=plan.id if plan else None,
        beneficiaryId=plan.beneficiaryId if plan else None,
        version=plan.version if plan else 0,
    )


def _person_of(s, c: Caller, kind: str, ident: str) -> Person | None:
    """A person the caller can see; a user stands for their own person (S10.10.1)."""
    if kind == "user":
        u = s.get(User, ident)
        ident = u.personId if u is not None else ""
    if kind not in ("person", "user"):
        return None
    p = s.get(Person, ident)
    return p if p is not None and people.readable(s, c.id, p.id) else None


def _check_beneficiary(s, c: Caller, b: BeneficiaryRef | None, owner_id: str) -> dict:
    if b is None:
        return {"beneficiaryId": None}
    p = _person_of(s, c, b.kind, b.id)
    if p is None:
        raise refuse("beneficiary", "beneficiary-invalid", "One of the household's people.")
    return {"beneficiaryId": p.id}


@router.get("/accounts/{account_id}/plan529", response_model=PlanOut)
def get_plan(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        a, held = _account(s, c, account_id)
        return plan_view(s, a, held)


class EducationPlanRecord(Model):
    """A 529's plan as a draft saves it (S1.8.1): made with the account or on its Settings."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]
    planState: str | None = None
    planName: str | None = None
    beneficiaryId: IdOf("Persn") | None = None  # type: ignore[valid-type]
    openedOn: dt.date | None = None
    stateDeduction: Money | None = None


def _plan_values(ctx, body: EducationPlanRecord) -> dict:
    if body.stateDeduction is not None and body.stateDeduction < 0:
        raise refuse("stateDeduction", "amount-invalid", "Zero or more.")
    if body.openedOn is not None and body.openedOn > clock.today():
        raise refuse("openedOn", "date-ahead", "Not after today.")
    if body.beneficiaryId and _person_of(ctx.s, ctx.caller, "person", body.beneficiaryId) is None:
        raise refuse("beneficiaryId", "beneficiary-invalid", "One of the household's people.")
    return {
        "planState": (body.planState or "").strip() or None,
        "planName": (body.planName or "").strip() or None,
        "openedOn": body.openedOn,
        "stateDeduction": body.stateDeduction,
        "beneficiaryId": body.beneficiaryId,
    }


def _plan_changed(ctx, a: Account) -> None:
    activity.record(
        ctx.s,
        "account.updated",
        actor=ctx.caller.id,
        subject_kind="account",
        subject_id=a.id,
        owner=a.ownerId,
        detail={"fields": ["plan"]},
    )


def _plan_create(ctx, record_id: str, body: EducationPlanRecord) -> None:
    a, _ = _account(ctx.s, ctx.caller, body.accountId, "write")
    if education.plan_of(ctx.s, a) is not None:
        raise refuse("accountId", "plan-exists", "This 529 has its plan; change it.", 409)
    ctx.s.add(EducationPlan(id=record_id, accountId=a.id, **_plan_values(ctx, body)))
    _plan_changed(ctx, a)


def _plan_editable(ctx, record_id: str) -> EducationPlan:
    plan = ctx.s.get(EducationPlan, record_id)
    if plan is None or plan.deleted:
        raise Problem(404, "not-found", "Not found")
    _account(ctx.s, ctx.caller, plan.accountId, "write")
    return plan


PLAN_FIELDS = ("planState", "planName", "beneficiaryId", "openedOn", "stateDeduction")


def _plan_update(ctx, plan: EducationPlan, body: EducationPlanRecord) -> None:
    if body.accountId != plan.accountId:
        raise refuse("accountId", "plan-fixed", "A plan stays with its account.")
    a, _ = _account(ctx.s, ctx.caller, plan.accountId, "write")
    for k, v in _plan_values(ctx, body).items():
        setattr(plan, k, v)
    plan.updatedAt = clock.now()
    _plan_changed(ctx, a)


def _plan_delete(ctx, plan: EducationPlan) -> None:
    raise refuse(None, "plan-delete", "A 529 keeps its plan; delete the account instead.")


def _plan_read(ctx, record_id: str) -> PlanOut:
    plan = ctx.s.get(EducationPlan, record_id)
    a, held = _account(ctx.s, ctx.caller, plan.accountId)
    return plan_view(ctx.s, a, held)


save.register(
    save.Kind(
        prefix="EdPln",
        entity=EducationPlan,
        fields=EducationPlanRecord,
        create=_plan_create,
        editable=_plan_editable,
        current=lambda ctx, plan: {
            "accountId": plan.accountId,
            **{f: getattr(plan, f) for f in PLAN_FIELDS},
        },
        update=_plan_update,
        delete=_plan_delete,
        read=_plan_read,
    )
)


# ---- Contributions (S1.8.2) ----


class ContributionOut(Model):
    id: str | None = None  # its tag's: none until it is tagged
    transactionId: str
    date: dt.date
    amount: Money
    contributor: str
    name: str
    relationship: str | None
    fiveYear: bool
    version: int = 0  # its tag's: 0 until it is tagged (S13.8.6)


class GiftYearOut(Model):
    contributor: str
    name: str
    year: int
    counted: Money
    exclusion: Money
    over: bool
    fromElection: int | None


class ContributionsView(Model):
    rows: list[ContributionOut]
    years: list[GiftYearOut]


def _contributor(s, c: Caller, key: str, owner_id: str) -> str | None:
    if key == "owner":
        return None
    kind, _, ident = key.partition(":")
    p = _person_of(s, c, kind, ident)
    if p is None:
        raise refuse("contributor", "contributor-invalid", "The owner or a person.")
    return p.id


def _tag_of(s, txn_id: str) -> Contribution | None:
    return s.scalars(
        select(Contribution).where(
            Contribution.transactionId == txn_id, Contribution.deleted == false()
        )
    ).first()


def contributions_view(s, a: Account) -> ContributionsView:
    rows = education.contributions(s, a)
    tags = {
        t.transactionId: t
        for t in s.scalars(
            select(Contribution).where(
                Contribution.transactionId.in_([r.transactionId for r in rows]),
                Contribution.deleted == false(),
            )
        )
    }
    return ContributionsView(
        rows=[
            ContributionOut(
                **r.__dict__,
                id=tags[r.transactionId].id if r.transactionId in tags else None,
                version=tags[r.transactionId].version if r.transactionId in tags else 0,
            )
            for r in reversed(rows)
        ],
        years=[GiftYearOut(**g.__dict__) for g in education.gift_years(s, rows)],
    )


@router.get("/accounts/{account_id}/contributions", response_model=ContributionsView)
def list_contributions(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        a, _ = _account(s, c, account_id)
        return contributions_view(s, a)


def _new_deposit(s, c: Caller, a: Account, body) -> Transaction:
    """A deposit into the 529, with who made it; from a bank account, both halves."""
    if body.amount is None or body.amount <= 0:
        raise refuse("amount", "amount-invalid", "More than zero.")
    if body.date is None:
        raise refuse("date", "date-missing", "The day it was paid in.")
    other = None
    if body.fromAccountId:
        access.account(s, c.id, body.fromAccountId, "write")
        other = Transaction(
            id=ids.new_id("Txn"),
            accountId=body.fromAccountId,
            date=body.date,
            kind="transfer",
            amount=-body.amount,
            payee=a.name,
            createdById=c.id,
        )
        s.add(other)
    txn = Transaction(
        id=ids.new_id("Txn"),
        accountId=a.id,
        date=body.date,
        kind="transfer" if other else "deposit",
        amount=body.amount,
        payee="Contribution",
        createdById=c.id,
    )
    s.add(txn)
    s.flush()
    if other is not None:
        txn.transferId, other.transferId = other.id, txn.id
    activity.record(s, "529.contribution", actor=c.id, subject_kind="account",
                    subject_id=a.id, owner=a.ownerId)  # fmt: skip
    return txn


class ContributionRecord(Model):
    """A contribution's tag as a draft saves it (S1.8.2): who made a deposit into the 529 and
    whether it is a five-year election. Made for a deposit already there (an imported one), or
    with the deposit it records, from a bank account with both halves."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]
    transactionId: IdOf("Txn") | None = None  # type: ignore[valid-type]
    date: dt.date | None = None  # a new deposit's
    amount: Money | None = None
    fromAccountId: IdOf("Acct") | None = None  # type: ignore[valid-type]
    contributor: str = "owner"  # owner, person:<id>, or user:<id> for their person
    fiveYear: bool = False


def _contribution_create(ctx, record_id: str, body: ContributionRecord) -> None:
    s, c = ctx.s, ctx.caller
    a, _ = _account(s, c, body.accountId, "write")
    from_person = _contributor(s, c, body.contributor, a.ownerId)
    if body.transactionId is None:
        txn = _new_deposit(s, c, a, body)
    else:
        txn = s.get(Transaction, body.transactionId)
        if txn is None or txn.deleted or txn.accountId != a.id or txn.amount <= 0:
            raise refuse("transactionId", "not-found", "No such contribution.")
        if _tag_of(s, txn.id) is not None:
            raise refuse("transactionId", "tagged", "It is tagged: change its tag.", 409)
    s.add(Contribution(id=record_id, transactionId=txn.id, fromPersonId=from_person,
                       fiveYear=body.fiveYear))  # fmt: skip


def _contribution_editable(ctx, record_id: str) -> Contribution:
    t = ctx.s.get(Contribution, record_id)
    if t is None or t.deleted:
        raise Problem(404, "not-found", "No such contribution.")
    _account(ctx.s, ctx.caller, ctx.s.get(Transaction, t.transactionId).accountId, "write")
    return t


def _contribution_current(ctx, t: Contribution) -> dict:
    txn = ctx.s.get(Transaction, t.transactionId)
    return {"accountId": txn.accountId, "transactionId": txn.id, "date": None, "amount": None,
            "fromAccountId": None, "fiveYear": t.fiveYear,
            "contributor": f"person:{t.fromPersonId}" if t.fromPersonId else "owner"}  # fmt: skip


def _contribution_update(ctx, t: Contribution, body: ContributionRecord) -> None:
    """Who it came from and the election; the deposit itself is changed as a transaction."""
    current = _contribution_current(ctx, t)
    fixed = [f for f in ("accountId", "transactionId", "date", "amount", "fromAccountId")
             if getattr(body, f) != current[f]]  # fmt: skip
    if fixed:
        raise refuse(fixed[0], "contribution-fixed", "Change the deposit on the Transactions tab.")
    a = ctx.s.get(Account, body.accountId)
    t.fromPersonId = _contributor(ctx.s, ctx.caller, body.contributor, a.ownerId)
    t.fiveYear = body.fiveYear
    t.updatedAt = clock.now()


def _contribution_read(ctx, record_id: str) -> ContributionOut:
    t = ctx.s.get(Contribution, record_id)
    a, _ = _account(ctx.s, ctx.caller, ctx.s.get(Transaction, t.transactionId).accountId)
    return next(x for x in contributions_view(ctx.s, a).rows if x.id == record_id)


save.register(
    save.Kind(
        prefix="Cntrb",
        entity=Contribution,
        fields=ContributionRecord,
        create=_contribution_create,
        editable=_contribution_editable,
        current=_contribution_current,
        update=_contribution_update,
        # Untagged, the deposit stays: it counts as the owner's.
        delete=lambda ctx, t: t.mark_deleted(ctx.caller.id),
        read=_contribution_read,
    )
)


# ---- Withdrawals and qualified expenses (S1.8.3) ----


class ExpenseIn(Model):
    date: dt.date
    year: int | None = None  # the tax year it counts in: the date's, unless said
    kind: str
    description: str | None = None
    amount: Money


class ExpenseOut(Model):
    id: str
    date: dt.date
    year: int
    kind: str
    kindLabel: str
    description: str | None
    amount: Money
    documents: list[ReceiptRow]
    version: int


class WithdrawalYearOut(Model):
    year: int
    distributions: Money
    expenses: Money
    notCovered: Money


class WithdrawalsView(Model):
    years: list[WithdrawalYearOut]
    expenses: list[ExpenseOut]
    kinds: list[tuple[str, str]]


def withdrawals_view(s, c: Caller, a: Account) -> WithdrawalsView:
    return WithdrawalsView(
        years=[WithdrawalYearOut(**w.__dict__) for w in education.withdrawals(s, a)],
        expenses=[
            ExpenseOut(
                id=e.id,
                date=e.date,
                year=e.year,
                kind=e.kind,
                kindLabel=education.KINDS[e.kind],
                description=e.description,
                amount=e.amount,
                documents=[
                    receipt_row(s, r, receipts.perms_for(s, c.id, r) or access.READ, c.id)
                    for r in receipts.of_item(s, e.id, "expense")
                ],
                version=e.version,
            )
            for e in education.expenses(s, a)
        ],
        kinds=list(education.KINDS.items()),
    )


@router.get("/accounts/{account_id}/withdrawals", response_model=WithdrawalsView)
def list_withdrawals(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        a, _ = _account(s, c, account_id)
        return withdrawals_view(s, c, a)


def _expense_values(body) -> dict:
    if body.kind not in education.KINDS:
        raise refuse("kind", "kind-invalid", "One of the qualified expenses.")
    if body.amount <= 0:
        raise refuse("amount", "amount-invalid", "More than zero.")
    return {
        "date": body.date,
        "year": body.year or body.date.year,
        "kind": body.kind,
        "description": (body.description or "").strip() or None,
        "amount": body.amount,
    }


def _expense(s, c: Caller, expense_id: str) -> tuple[QualifiedExpense, Account, str]:
    e = s.get(QualifiedExpense, expense_id)
    if e is None or e.deleted:
        raise Problem(404, "not-found", "No such expense.")
    a, held = _account(s, c, e.accountId, "write")
    return e, a, held


class ExpenseRecord(ExpenseIn):
    """A qualified expense as a draft saves it (S1.8.3), in its 529's account."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]


def _expense_create(ctx, record_id: str, body: ExpenseRecord) -> None:
    values = _expense_values(body)
    a, _ = _account(ctx.s, ctx.caller, body.accountId, "write")
    ctx.s.add(QualifiedExpense(id=record_id, accountId=a.id, **values))


def _expense_update(ctx, e: QualifiedExpense, body: ExpenseRecord) -> None:
    if body.accountId != e.accountId:
        raise refuse("accountId", "expense-fixed", "An expense stays with its 529.")
    for k, v in _expense_values(body).items():
        setattr(e, k, v)
    e.updatedAt = clock.now()


def _expense_read(ctx, record_id: str) -> ExpenseOut:
    e = ctx.s.get(QualifiedExpense, record_id)
    a, _ = _account(ctx.s, ctx.caller, e.accountId)
    return next(x for x in withdrawals_view(ctx.s, ctx.caller, a).expenses if x.id == e.id)


save.register(
    save.Kind(
        prefix="QExpn",
        entity=QualifiedExpense,
        fields=ExpenseRecord,
        create=_expense_create,
        editable=lambda ctx, record_id: _expense(ctx.s, ctx.caller, record_id)[0],
        current=lambda ctx, e: {"accountId": e.accountId, **_expense_values(e)},
        update=_expense_update,
        delete=lambda ctx, e: e.mark_deleted(ctx.caller.id),
        read=_expense_read,
    )
)


# ---- The Goal tab (S1.8.5) ----


class GoalView(Model):
    beneficiary: BeneficiaryOut | None
    projection: ProjectionDetail | None
    others: int  # more education projections for the same beneficiary


def _goals(s, c: Caller, b: education.Beneficiary) -> list[Projection]:
    out = []
    for p, _ in projections.visible(s, c.id):
        if p.goal != "education":
            continue
        who = json.loads(p.inputs or "{}").get("beneficiary") or {}
        if who.get("kind") == "user":
            u = s.get(User, who.get("id") or "")
            who = {"kind": "person", "id": u.personId if u else None}
        if who.get("kind") == b.kind and who.get("id") == b.id:
            out.append(p)
    return sorted(out, key=lambda p: (not p.active, p.createdAt))


@router.get("/accounts/{account_id}/goal", response_model=GoalView)
def get_goal(account_id: str, request: Request, c: Caller = Depends(caller)):
    """The beneficiary's education projection: the active one, else the first made."""
    with server(request).db.read(user=c.id) as s:
        a, _ = _account(s, c, account_id)
        b = education.beneficiary(s, education.plan_of(s, a))
        if b is None:
            return GoalView(beneficiary=None, projection=None, others=0)
        found = _goals(s, c, b)
        if not found:
            return GoalView(beneficiary=_beneficiary_out(b), projection=None, others=0)
        p = found[0]
        perms = access.perms(s, Projection, p.id, c.id) or access.READ
        return GoalView(
            beneficiary=_beneficiary_out(b),
            projection=projection_detail(s, c.id, p, perms),
            others=len(found) - 1,
        )


@router.post("/accounts/{account_id}/goal", response_model=GoalView, status_code=201)
def start_goal(account_id: str, request: Request, c: Caller = Depends(caller)):
    """An education projection for the beneficiary, built on their 529s the caller can see,
    starting from the shipped public-college average and this year's contributions."""
    with server(request).db.tx(user=c.id) as s:
        a, _ = _account(s, c, account_id, "write")
        b = education.beneficiary(s, education.plan_of(s, a))
        if b is None:
            raise Problem(409, "no-beneficiary", "Choose the beneficiary in Settings first.")
        mine = [x.id for x, _ in access.accounts(s, c.id)]
        built = education.accounts_for(s, b.id, mine) or [a.id]
        rows = education.contributions(s, a)
        year = clock.today().year
        recent = sum((r.amount for r in rows if r.date.year >= year - 1), Decimal(0))
        p = Projection(
            id=ids.new_id("Prjct"),
            ownerId=c.id,
            name=f"{b.name.split(' ')[0]}'s college",
            goal="education",
            builtOn=exactjson.dumps({"kind": "accounts", "ids": built}),
            inputs=exactjson.dumps(
                {
                    "beneficiary": {"kind": b.kind, "id": b.id},
                    "startAge": 18,
                    "schoolYears": 4,
                    "costBasis": "public",
                    "monthly": round(float(recent) / 24, 2),
                }
            ),
        )
        s.add(p)
        s.flush()
        activity.record(
            s,
            "projection.created",
            actor=c.id,
            subject_kind="projection",
            subject_id=p.id,
            owner=c.id,
        )
        return GoalView(
            beneficiary=_beneficiary_out(b),
            projection=projection_detail(s, c.id, p, access.OWNER),
            others=0,
        )
