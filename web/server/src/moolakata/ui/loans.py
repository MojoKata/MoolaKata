"""Loans (requirements S1.9): a loan account's terms, its schedule and summary, payments
recorded or linked from a bank account and split by the schedule, and the servicer's balance
against the computed one."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import false, or_, select

from .. import access, activity, assets, clock, exactjson, ids, loans
from ..errors import FieldError, Problem, refuse
from ..loans import payoff
from ..projections import assumptions
from ..store.entities.accounts import (
    Account,
    Anchor,
    Category,
    Loan,
    PayoffPlan,
    Transaction,
)
from ..store.entities.assets import Item
from . import save
from .conventions import (
    ExactRoute,
    IdOf,
    Model,
    Money,
    Rate,
    Ratio,
    ResetRate,
)
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["loans"])


class Reset(Model):
    date: dt.date
    rate: ResetRate


class Recast(Model):
    date: dt.date
    fee: Money = Decimal(0)


class TermsIn(Model):
    principal: Money
    startDate: dt.date
    termMonths: int
    rate: Rate
    method: str = "amortized"
    payment: Money | None = None
    escrowTax: Money | None = None
    escrowInsurance: Money | None = None
    pmi: Money | None = None
    drawMonths: int | None = None
    resets: list[Reset] = Field(default_factory=list)
    recasts: list[Recast] = Field(default_factory=list)
    originalValue: Money | None = None
    securedById: str | None = None  # the property or vehicle it is secured by
    # How its payments count in budgets (S1.9.7): split by the schedule, or whole.
    budgetCounting: str = "split"
    budgetCategoryId: str | None = None  # whole: the category; none is Loan payments


class ResetView(Model):
    date: dt.date
    rate: ResetRate


class RecastView(Model):
    date: dt.date
    fee: Money


class TermsOut(Model):
    # Its own models for the dated rows, so the contract has one schema for each direction.
    principal: Money
    startDate: dt.date
    termMonths: int
    rate: Rate
    method: str
    payment: Money | None
    escrowTax: Money | None
    escrowInsurance: Money | None
    pmi: Money | None
    drawMonths: int | None
    resets: list[ResetView]
    recasts: list[RecastView]
    originalValue: Money | None
    securedById: str | None
    budgetCounting: str
    budgetCategoryId: str | None
    computedPayment: Money
    id: str
    version: int


class RowOut(Model):
    date: dt.date
    payment: Money
    principal: Money
    interest: Money
    escrow: Money
    pmi: Money
    balance: Money
    past: bool
    overpayment: Money


class ServicerCheck(Model):
    date: dt.date
    servicer: Money
    computed: Money
    difference: Money


class Equity(Model):
    """What the loan is secured by, and the borrower's stake in it (S1.9.5)."""

    itemId: str
    itemName: str
    accountId: str
    value: Money
    owed: Money  # every live loan secured by it
    equity: Money
    ltv: Money  # this loan's balance, in percent of the value
    pmiRequest: dt.date | None  # PMI can be dropped on request: 80% of the original value
    pmiEnds: dt.date | None  # and goes by itself: 78%


class Following(Model):
    planId: str
    name: str
    since: dt.date
    expected: Money  # what the plan has had overpaid since it was chosen
    actual: Money  # what was overpaid
    ahead: Money  # actual less expected: below zero is behind


class LoanView(Model):
    terms: TermsOut | None
    balance: Money
    rate: ResetRate
    payment: Money
    total: Money
    nextDate: dt.date | None
    payoffDate: dt.date | None
    originalPayoff: dt.date | None
    interestPaid: Money
    interestAhead: Money
    principalThisYear: Money
    overpaid: Money
    rows: list[RowOut]
    servicer: ServicerCheck | None
    equity: Equity | None = None
    following: Following | None = None
    canWrite: bool
    version: int = 0  # the loan's terms: 0 until they are set (S13.8.6)


class SplitOut(Model):
    """How the schedule splits a payment (S1.9.3), and the category each part is recorded in;
    the overpayment is principal beyond the schedule's, part of `principal`."""

    principal: Money
    interest: Money
    escrowTax: Money
    escrowInsurance: Money
    pmi: Money
    fees: Money
    overpayment: Money
    categories: dict[str, str]


class Candidate(Model):
    transactionId: str
    accountName: str
    date: dt.date
    amount: Money
    payee: str | None


def _account(s, c: Caller, account_id: str, need: str = "read") -> tuple[Account, str]:
    a, lvl = access.account(s, c.id, account_id, need)
    if not loans.is_loan(a.type):
        raise Problem(409, "not-a-loan", "This account is not a loan.")
    return a, lvl


def _terms_out(row: Loan) -> TermsOut:
    t = loans.terms_of(row)
    return TermsOut(
        principal=row.principal,
        startDate=row.startDate,
        termMonths=row.termMonths,
        rate=row.rate,
        method=row.method,
        payment=row.payment,
        escrowTax=row.escrowTax,
        escrowInsurance=row.escrowInsurance,
        pmi=row.pmi,
        drawMonths=row.drawMonths,
        resets=[ResetView(date=d, rate=r) for d, r in t.resets],
        recasts=[RecastView(date=d, fee=f) for d, f in t.recasts],
        originalValue=row.originalValue,
        securedById=row.securedById,
        budgetCounting=row.budgetCounting,
        budgetCategoryId=row.budgetCategoryId,
        computedPayment=loans.scheduled_payment(t),
        id=row.id,
        version=row.version,
    )


def view(s, a: Account, level: str) -> LoanView:
    row = loans.loan_of(s, a)
    today = clock.today()
    if row is None:
        return LoanView(
            terms=None,
            balance=Decimal(0),
            rate=Decimal(0),
            payment=Decimal(0),
            total=Decimal(0),
            nextDate=None,
            payoffDate=None,
            originalPayoff=None,
            interestPaid=Decimal(0),
            interestAhead=Decimal(0),
            principalThisYear=Decimal(0),
            overpaid=Decimal(0),
            rows=[],
            servicer=None,
            canWrite=level in ("owner", "write"),
        )
    terms = loans.terms_of(row)
    payments, draws = loans.history(s, a)
    sm, rows = loans.summary(terms, payments, draws, today)
    anchor = s.scalars(
        select(Anchor)
        .where(Anchor.accountId == a.id, Anchor.deleted == false(), Anchor.source == "typed")
        .order_by(Anchor.date.desc())
    ).first()
    servicer = None
    if anchor is not None:
        computed = loans.balance_on(terms, payments, draws, anchor.date)
        servicer = ServicerCheck(
            date=anchor.date,
            servicer=-anchor.balance,
            computed=computed,
            difference=-anchor.balance - computed,
        )
    return LoanView(
        version=row.version,
        terms=_terms_out(row),
        balance=sm.balance,
        rate=sm.rate,
        payment=sm.payment,
        total=sm.total,
        nextDate=sm.nextDate,
        payoffDate=sm.payoffDate,
        originalPayoff=sm.originalPayoff,
        interestPaid=sm.interestPaid,
        interestAhead=sm.interestAhead,
        principalThisYear=sm.principalThisYear,
        overpaid=sm.overpaid,
        rows=[RowOut(**r.__dict__) for r in rows],
        servicer=servicer,
        equity=_equity(s, row, terms, sm.balance, rows, today),
        following=_following(s, a, terms, rows, sm.payment, today),
        canWrite=level in ("owner", "write"),
    )


def _equity(s, row: Loan, terms, owed, rows, today) -> Equity | None:
    if not row.securedById:
        return None
    it = s.get(Item, row.securedById)
    if it is None or it.deleted:
        return None
    d = assets.details(s, [it])[it.id]
    sp = assets.spots(s, [it], today).get(it.metal or "")
    worth = assets.value_on(it, d, today, sp.price if sp else None)
    others = s.scalars(
        select(Loan).where(Loan.securedById == it.id, Loan.deleted == false(), Loan.id != row.id)
    ).all()
    owed_all = owed + sum(
        (-loans.value(s, s.get(Account, o.accountId), today) for o in others), Decimal(0)
    )
    original = row.originalValue or assets.basis(it, d)
    request = ends = None
    if terms.pmi and original:
        for r in rows:
            if request is None and r.balance <= original * Decimal("0.80"):
                request = r.date
            if r.balance <= original * Decimal("0.78"):
                ends = r.date
                break
    return Equity(
        itemId=it.id,
        itemName=it.name,
        accountId=it.accountId,
        value=worth,
        owed=owed_all,
        equity=worth - owed_all,
        ltv=(owed / worth * 100).quantize(Decimal("0.1")) if worth else Decimal(0),
        pmiRequest=request,
        pmiEnds=ends,
    )


def _check(body: TermsIn) -> list[FieldError]:
    e = []
    if body.principal < 0:
        e.append(FieldError("principal", "principal-invalid", "Zero or more."))
    if not 1 <= body.termMonths <= 600:
        e.append(FieldError("termMonths", "term-invalid", "Between 1 and 600 months."))
    if not 0 <= body.rate <= 40:
        e.append(FieldError("rate", "rate-invalid", "Between 0% and 40%."))
    if body.method not in ("amortized", "daily"):
        e.append(FieldError("method", "method-invalid", "Monthly or daily."))
    if body.drawMonths is not None and not 0 <= body.drawMonths < body.termMonths:
        e.append(FieldError("drawMonths", "draw-invalid", "Shorter than the term."))
    if body.budgetCounting not in ("split", "whole"):
        e.append(
            FieldError("budgetCounting", "counting-invalid", "Split by the schedule, or whole.")
        )
    for f in ("payment", "escrowTax", "escrowInsurance", "pmi", "originalValue"):
        v = getattr(body, f)
        if v is not None and v < 0:
            e.append(FieldError(f, "amount-invalid", "Zero or more."))
    return e


@router.get("/accounts/{account_id}/loan", response_model=LoanView)
def get_loan(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        a, lvl = _account(s, c, account_id)
        return view(s, a, lvl)


def _terms(s, c: Caller, a: Account, body: TermsIn) -> dict:
    """The terms' columns, checked as the account's own route checks them."""
    errors = _check(body)
    if errors:
        raise Problem(422, errors[0].code, errors[0].message, errors)
    if body.securedById:
        it = s.get(Item, body.securedById)
        if it is None or it.deleted:
            raise refuse("securedById", "not-found", "No such property or vehicle.")
        access.account(s, c.id, it.accountId, "read")
    if body.budgetCategoryId:
        cat = s.get(Category, body.budgetCategoryId)
        if cat is None or cat.deleted or cat.kind == "transfer":
            raise refuse("budgetCategoryId", "category-unknown", "Choose a category.")
    return {
        "principal": body.principal,
        "startDate": body.startDate,
        "termMonths": body.termMonths,
        "rate": body.rate,
        "method": body.method,
        "payment": body.payment,
        "escrowTax": body.escrowTax,
        "escrowInsurance": body.escrowInsurance,
        "pmi": body.pmi,
        "drawMonths": body.drawMonths,
        "resets": exactjson.dumps(
            [{"date": r.date.isoformat(), "rate": str(r.rate)} for r in body.resets]
        ),
        "recasts": exactjson.dumps(
            [{"date": r.date.isoformat(), "fee": str(r.fee)} for r in body.recasts]
        ),
        "originalValue": body.originalValue,
        "securedById": body.securedById,
        "budgetCounting": body.budgetCounting,
        "budgetCategoryId": body.budgetCategoryId if body.budgetCounting == "whole" else None,
    }


def _changed_terms(s, c: Caller, a: Account) -> None:
    activity.record(
        s,
        "account.updated",
        actor=c.id,
        subject_kind="account",
        subject_id=a.id,
        owner=a.ownerId,
        detail={"fields": ["terms"]},
    )


def _categories(s) -> dict[str, str]:
    keys = set(loans.PARTS.values())
    return {c.builtIn: c.id for c in s.scalars(select(Category).where(Category.builtIn.in_(keys)))}


@router.get("/accounts/{account_id}/loan/split", response_model=SplitOut)
def suggest_split(
    account_id: str,
    request: Request,
    date: dt.date,
    amount: Money,
    c: Caller = Depends(caller),
):
    """How the schedule would split a payment of this amount on this day: the parts a payment's
    draft records, a split of its transaction (S1.9.3)."""
    if amount <= 0:
        raise refuse("amount", "amount-invalid", "A payment is more than zero.")
    with server(request).db.read() as s:
        a, _ = _account(s, c, account_id)
        row = loans.loan_of(s, a)
        if row is None:
            raise Problem(409, "no-terms", "Set the loan's terms first.")
        payments, draws = loans.history(s, a)
        p = loans.split_for(loans.terms_of(row), payments, draws, date, amount)
        cats = _categories(s)
        return SplitOut(
            principal=p.principal,
            interest=p.interest,
            escrowTax=p.escrowTax,
            escrowInsurance=p.escrowInsurance,
            pmi=p.pmi,
            fees=p.fees,
            overpayment=p.overpayment,
            categories={part: cats[key] for part, key in loans.PARTS.items() if key in cats},
        )


@router.get("/accounts/{account_id}/loan/candidates", response_model=list[Candidate])
def candidates(account_id: str, request: Request, c: Caller = Depends(caller)):
    """Bank transactions of the last 90 days that look like this loan's payment (within 2% of
    it, not yet a transfer, and not filed under some other category, as rent is), to link
    with one click."""
    with server(request).db.read() as s:
        a, _ = _account(s, c, account_id)
        row = loans.loan_of(s, a)
        if row is None:
            return []
        payments, draws = loans.history(s, a)
        sm, _ = loans.summary(loans.terms_of(row), payments, draws, clock.today())
        want = sm.total
        if not want:
            return []
        banks = [
            x
            for x, lvl in access.visible_accounts(s, c.id)
            if lvl in ("owner", "write") and not loans.is_loan(x.type) and x.id != a.id
        ]
        names = {x.id: x.name for x in banks}
        rows = s.scalars(
            select(Transaction).where(
                Transaction.accountId.in_(list(names)),
                Transaction.deleted == false(),
                Transaction.transferId.is_(None),
                Transaction.amount < 0,
                Transaction.date >= clock.today() - dt.timedelta(days=90),
                or_(
                    Transaction.categoryId.is_(None),
                    Transaction.categoryId == _categories(s).get("transfer.loan"),
                ),
            )
        ).all()
        out = []
        for t in rows:
            if abs(-t.amount - want) <= want * Decimal("0.02"):
                out.append(
                    Candidate(
                        transactionId=t.id,
                        accountName=names[t.accountId],
                        date=t.date,
                        amount=-t.amount,
                        payee=t.payee,
                    )
                )
        return sorted(out, key=lambda x: x.date, reverse=True)


# ---- The payoff planner (S6.10) ----


class Lump(Model):
    date: dt.date
    amount: Money


class PlanIn(Model):
    monthly: Money = Decimal(0)
    monthlyFrom: dt.date | None = None
    monthlyUntil: dt.date | None = None
    yearly: Money = Decimal(0)
    yearlyMonth: int = 12
    lumps: list[Lump] = Field(default_factory=list)
    biweekly: bool = False
    roundTo: Money = Decimal(0)
    recast: bool = False
    recastFee: Money = Decimal(0)
    investClass: str = "usStocks"


class LumpView(Model):
    date: dt.date
    amount: Money


class PlanView(Model):
    """The inputs as saved; its own models, so the contract has one schema for each direction."""

    monthly: Money
    monthlyFrom: dt.date | None
    monthlyUntil: dt.date | None
    yearly: Money
    yearlyMonth: int
    lumps: list[LumpView]
    biweekly: bool
    roundTo: Money
    recast: bool
    recastFee: Money
    investClass: str


class Point(Model):
    date: dt.date
    balance: Money


class OutcomeOut(Model):
    payoffDate: dt.date | None
    months: int
    interest: Money
    paid: Money
    payment: Money
    paymentAfter: Money
    fees: Money
    monthsSaved: int
    interestSaved: Money  # against the schedule, less any recast fees
    balances: list[Point]


class InvestedOut(Model):
    assetClass: str
    rate: Ratio
    contributed: Money
    value: Money
    gain: Money


class PayoffOut(Model):
    schedule: OutcomeOut
    plan: OutcomeOut
    recast: OutcomeOut | None
    invested: InvestedOut
    planRows: list[RowOut]
    recastRows: list[RowOut]
    # An ARM's future rates are the user's assumption, and shown as such (S6.10.6).
    assumedRates: list[ResetView]


class SavedPlanIn(Model):
    name: str
    inputs: PlanIn


class SavedPlan(Model):
    id: str
    name: str
    inputs: PlanView
    following: bool
    followingSince: dt.date | None
    createdAt: dt.datetime
    version: int
    headline: str  # "Paid off Apr 2049 · $41,210 interest saved"


def _plan(body: PlanIn) -> payoff.Plan:
    return payoff.Plan(
        monthly=body.monthly,
        monthlyFrom=body.monthlyFrom,
        monthlyUntil=body.monthlyUntil,
        yearly=body.yearly,
        yearlyMonth=body.yearlyMonth,
        lumps=[(x.date, x.amount) for x in body.lumps],
        biweekly=body.biweekly,
        roundTo=body.roundTo,
        recast=body.recast,
        recastFee=body.recastFee,
        investClass=body.investClass,
    )


def _check_plan(body: PlanIn) -> None:
    e = []
    for f in ("monthly", "yearly", "roundTo", "recastFee"):
        if getattr(body, f) < 0:
            e.append(FieldError(f, "amount-invalid", "Zero or more."))
    if not 1 <= body.yearlyMonth <= 12:
        e.append(FieldError("yearlyMonth", "month-invalid", "A month, 1 to 12."))
    if body.monthlyFrom and body.monthlyUntil and body.monthlyUntil < body.monthlyFrom:
        e.append(FieldError("monthlyUntil", "until-before-from", "After the start."))
    for i, x in enumerate(body.lumps):
        if x.amount <= 0:
            e.append(FieldError(f"lumps.{i}.amount", "amount-invalid", "More than zero."))
    if body.investClass not in assumptions.CLASS_KEYS:
        e.append(FieldError("investClass", "class-invalid", "One of the asset classes."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)


def _months(a: dt.date | None, b: dt.date | None) -> int:
    if a is None or b is None:
        return 0
    return (b.year - a.year) * 12 + b.month - a.month


def _outcome_out(o: payoff.Outcome, base: payoff.Outcome) -> OutcomeOut:
    return OutcomeOut(
        payoffDate=o.payoffDate,
        months=o.months,
        interest=o.interest,
        paid=o.paid,
        payment=o.payment,
        paymentAfter=o.paymentAfter,
        fees=o.fees,
        monthsSaved=_months(o.payoffDate, base.payoffDate),
        interestSaved=base.interest - o.interest - o.fees,
        balances=[Point(date=r.date, balance=r.balance) for r in o.rows if not r.past],
    )


def _compute(s, c: Caller, a: Account, plan: payoff.Plan) -> payoff.Result:
    row = loans.loan_of(s, a)
    if row is None:
        raise Problem(409, "no-terms", "Set the loan's terms first.")
    figures = assumptions.load(s, c.id)
    rate = float(figures["classes"][plan.investClass]["return"])
    payments, draws = loans.history(s, a)
    return payoff.plan_outcomes(loans.terms_of(row), payments, draws, clock.today(), plan, rate)


def _rows(rows) -> list[RowOut]:
    return [RowOut(**r.__dict__) for r in rows if not r.past]


@router.post("/accounts/{account_id}/loan/payoff", response_model=PayoffOut)
def plan_payoff(account_id: str, body: PlanIn, request: Request, c: Caller = Depends(caller)):
    """A plan's overpayments against the schedule: the new payoff date, months and interest
    saved, a recast after its lump sums, and the same money invested instead."""
    _check_plan(body)
    with server(request).db.read() as s:
        a, _ = _account(s, c, account_id)
        plan = _plan(body)
        r = _compute(s, c, a, plan)
        row = loans.loan_of(s, a)
        today = clock.today()
        return PayoffOut(
            schedule=_outcome_out(r.schedule, r.schedule),
            plan=_outcome_out(r.plan, r.schedule),
            recast=_outcome_out(r.recast, r.schedule) if r.recast else None,
            invested=InvestedOut(
                assetClass=plan.investClass,
                rate=r.invested.rate,
                contributed=r.invested.contributed,
                value=r.invested.value,
                gain=r.invested.value - r.invested.contributed,
            ),
            planRows=_rows(r.plan.rows),
            recastRows=_rows(r.recast.rows) if r.recast else [],
            assumedRates=[
                ResetView(date=d, rate=x) for d, x in loans.terms_of(row).resets if d > today
            ],
        )


def _plans(s, a: Account) -> list[PayoffPlan]:
    return list(
        s.scalars(
            select(PayoffPlan)
            .where(PayoffPlan.accountId == a.id, PayoffPlan.deleted == false())
            .order_by(PayoffPlan.createdAt)
        )
    )


def _saved(s, c: Caller, a: Account, p: PayoffPlan) -> SavedPlan:
    plan_in = PlanIn(**exactjson.loads(p.inputs))
    inputs = PlanView(**plan_in.model_dump())
    headline = ""
    if loans.loan_of(s, a) is not None:
        r = _compute(s, c, a, _plan(plan_in))
        best = r.plan
        saved = r.schedule.interest - best.interest - best.fees
        when = f"{best.payoffDate:%b %Y}" if best.payoffDate else "—"
        headline = f"Paid off {when} · ${saved:,.0f} interest saved"
    return SavedPlan(
        id=p.id,
        name=p.name,
        inputs=inputs,
        following=p.following,
        followingSince=p.followingSince,
        createdAt=p.createdAt,
        version=p.version,
        headline=headline,
    )


def _following(s, a: Account, terms, rows, pi, today) -> Following | None:
    p = s.scalars(
        select(PayoffPlan).where(
            PayoffPlan.accountId == a.id,
            PayoffPlan.deleted == false(),
            PayoffPlan.following.is_(True),
        )
    ).first()
    if p is None or p.followingSince is None:
        return None
    inputs = PlanIn(**exactjson.loads(p.inputs))
    expected = payoff.expected_extra(terms, _plan(inputs), p.followingSince, today, pi)
    actual = sum((r.overpayment for r in rows if r.past and r.date > p.followingSince), Decimal(0))
    return Following(
        planId=p.id,
        name=p.name,
        since=p.followingSince,
        expected=expected,
        actual=actual,
        ahead=actual - expected,
    )


@router.get("/accounts/{account_id}/loan/plans", response_model=list[SavedPlan])
def list_plans(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        a, _ = _account(s, c, account_id)
        return [_saved(s, c, a, p) for p in _plans(s, a)]


def _check_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > 80:
        raise refuse("name", "name-invalid", "A name, up to 80 characters.")
    return name


@router.post("/accounts/{account_id}/loan/plans", response_model=SavedPlan, status_code=201)
def save_plan(account_id: str, body: SavedPlanIn, request: Request, c: Caller = Depends(caller)):
    name = _check_name(body.name)
    _check_plan(body.inputs)
    with server(request).db.tx() as s:
        a, _ = _account(s, c, account_id, "write")
        p = PayoffPlan(
            id=ids.new_id("Pyoff"),
            accountId=a.id,
            name=name,
            inputs=exactjson.unmark(body.inputs.model_dump_json()),
            createdById=c.id,
        )
        s.add(p)
        s.flush()
        activity.record(
            s,
            "loan.plan-saved",
            actor=c.id,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
        )
        return _saved(s, c, a, p)


def _get_plan(s, c: Caller, account_id: str, plan_id: str) -> tuple[Account, PayoffPlan]:
    a, _ = _account(s, c, account_id, "write")
    p = s.get(PayoffPlan, plan_id)
    if p is None or p.deleted or p.accountId != a.id:
        raise Problem(404, "not-found", "No such plan.")
    return a, p


class FollowIn(Model):
    following: bool


@router.post("/accounts/{account_id}/loan/plans/{plan_id}/follow", response_model=SavedPlan)
def follow_plan(
    account_id: str, plan_id: str, body: FollowIn, request: Request, c: Caller = Depends(caller)
):
    """Marks the plan being followed, tracked from today, or stops following it; the one
    followed before stops. An action: it changes every plan of the loan."""
    with server(request).db.tx() as s:
        a, p = _get_plan(s, c, account_id, plan_id)
        for other in _plans(s, a):
            if other.following and other.id != p.id:
                other.following, other.followingSince = False, None
        if body.following and not p.following:
            p.following, p.followingSince = True, clock.today()
        elif not body.following:
            p.following, p.followingSince = False, None
        s.flush()
        return _saved(s, c, a, p)


# ---------- a loan's terms and its saved plans in a draft (S12.15, S13.8.11) ----------


class LoanRecord(TermsIn):
    """A loan's terms as a draft saves them: set when the loan is made, corrected later (an
    ARM's resets, a recast)."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]


TERM_FIELDS = tuple(f for f in TermsIn.model_fields if f not in ("resets", "recasts"))


def _loan_account(ctx, account_id: str) -> Account:
    return _account(ctx.s, ctx.caller, account_id, "write")[0]


def _loan_create(ctx, record_id: str, body: LoanRecord) -> None:
    a = _loan_account(ctx, body.accountId)
    if loans.loan_of(ctx.s, a) is not None:
        raise refuse("accountId", "loan-exists", "This loan has its terms; change them.", 409)
    ctx.s.add(Loan(id=record_id, accountId=a.id, **_terms(ctx.s, ctx.caller, a, body)))
    _changed_terms(ctx.s, ctx.caller, a)


def _loan_editable(ctx, record_id: str) -> Loan:
    row = ctx.s.get(Loan, record_id)
    if row is None or row.deleted:
        raise Problem(404, "not-found", "Not found")
    _loan_account(ctx, row.accountId)
    return row


def _loan_current(ctx, row: Loan) -> dict:
    return {
        "accountId": row.accountId,
        "resets": exactjson.loads(row.resets or "[]"),
        "recasts": exactjson.loads(row.recasts or "[]"),
        **{f: getattr(row, f) for f in TERM_FIELDS},
    }


def _loan_update(ctx, row: Loan, body: LoanRecord) -> None:
    if body.accountId != row.accountId:
        raise refuse("accountId", "loan-fixed", "The terms stay with their loan.")
    a = _loan_account(ctx, row.accountId)
    for k, v in _terms(ctx.s, ctx.caller, a, body).items():
        setattr(row, k, v)
    row.updatedAt = clock.now()
    _changed_terms(ctx.s, ctx.caller, a)


def _loan_delete(ctx, row: Loan) -> None:
    raise refuse(None, "loan-delete", "A loan keeps its terms; delete the account instead.")


def _loan_read(ctx, record_id: str) -> LoanView:
    row = ctx.s.get(Loan, record_id)
    a, lvl = _account(ctx.s, ctx.caller, row.accountId)
    return view(ctx.s, a, lvl)


class PayoffRecord(SavedPlanIn):
    """A saved overpayment plan as a draft saves it (S1.9.6)."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]


def _payoff_create(ctx, record_id: str, body: PayoffRecord) -> None:
    name = _check_name(body.name)
    _check_plan(body.inputs)
    a = _loan_account(ctx, body.accountId)
    ctx.s.add(
        PayoffPlan(
            id=record_id,
            accountId=a.id,
            name=name,
            inputs=exactjson.unmark(body.inputs.model_dump_json()),
            createdById=ctx.caller.id,
        )
    )
    activity.record(
        ctx.s,
        "loan.plan-saved",
        actor=ctx.caller.id,
        subject_kind="account",
        subject_id=a.id,
        owner=a.ownerId,
    )


def _payoff_editable(ctx, record_id: str) -> PayoffPlan:
    p = ctx.s.get(PayoffPlan, record_id)
    if p is None or p.deleted:
        raise Problem(404, "not-found", "No such plan.")
    _loan_account(ctx, p.accountId)
    return p


def _payoff_update(ctx, p: PayoffPlan, body: PayoffRecord) -> None:
    if body.accountId != p.accountId:
        raise refuse("accountId", "plan-fixed", "A plan stays with its loan.")
    _check_plan(body.inputs)
    p.name = _check_name(body.name)
    p.inputs = exactjson.unmark(body.inputs.model_dump_json())
    p.updatedAt = clock.now()


def _payoff_read(ctx, record_id: str) -> SavedPlan:
    p = ctx.s.get(PayoffPlan, record_id)
    a, _ = _account(ctx.s, ctx.caller, p.accountId)
    return _saved(ctx.s, ctx.caller, a, p)


save.register(
    save.Kind(
        prefix="Loan",
        entity=Loan,
        fields=LoanRecord,
        create=_loan_create,
        editable=_loan_editable,
        current=_loan_current,
        update=_loan_update,
        delete=_loan_delete,
        read=_loan_read,
    )
)
save.register(
    save.Kind(
        prefix="Pyoff",
        entity=PayoffPlan,
        fields=PayoffRecord,
        create=_payoff_create,
        editable=_payoff_editable,
        current=lambda ctx, p: {
            "accountId": p.accountId,
            "name": p.name,
            "inputs": exactjson.loads(p.inputs),
        },
        update=_payoff_update,
        delete=lambda ctx, p: p.mark_deleted(ctx.caller.id),
        read=_payoff_read,
    )
)
