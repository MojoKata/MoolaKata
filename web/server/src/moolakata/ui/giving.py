"""Charitable giving (requirements S7.9, S12.2.9): the year's plan, target and progress,
donations of every type (shares from a lot, into or from a donor-advised fund), organisations
with their pledges, and the acknowledgements the tax rules need."""

import datetime as dt
import json
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select

from .. import access, activity, clock, exactjson, giving, ids, receipts
from ..errors import FieldError, Problem, refuse
from ..ledger.lots import long_term as held_long
from ..store.entities.accounts import Account, Category, Instrument, Lot, LotPick, Transaction
from ..store.entities.giving import Donation, GivingPlan, Organisation
from ..store.repos import ledger as repo
from . import save
from .conventions import (
    ExactRoute,
    IdOf,
    Model,
    Money,
    Quantity,
    Ratio,
)
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["giving"])


# ---- The plan (S7.9.1, S7.9.2) ----


class PlanIn(Model):
    year: int
    targetKind: str = "percent"
    percent: Money | None = Decimal(10)
    amount: Money | None = None
    incomeBasis: str = "take-home"
    income: Money | None = None
    dafCounted: str = "funded"


class PlanOut(Model):
    id: str
    year: int
    targetKind: str
    percent: Money | None
    amount: Money | None
    incomeBasis: str
    income: Money | None
    dafCounted: str
    level: str
    ownerName: str
    version: int


class Share(Model):
    label: str
    amount: Money


class YearPct(Model):
    year: int
    percent: Ratio | None


class FundOut(Model):
    accountId: str
    name: str
    institution: str | None
    balance: Money
    contributed: Money
    granted: Money


class GivingView(Model):
    year: int
    plan: PlanOut | None
    income: Money
    target: Money
    given: Money  # counted toward the target
    pace: Money  # the even pace to the target, as of today
    pledged: Money  # pledges still due this year
    projected: Money  # given and pledged
    byMonth: list[Money]
    byOrganisation: list[Share]
    byCause: list[Share]
    byKind: list[Share]
    history: list[YearPct]
    funds: list[FundOut]
    missingAcks: int
    notes: list[str]


def _plan_out(s, p: GivingPlan, lvl: str) -> PlanOut:
    from ..store.entities.users import User

    return PlanOut(
        id=p.id,
        year=p.year,
        targetKind=p.targetKind,
        percent=p.percent,
        amount=p.amount,
        incomeBasis=p.incomeBasis,
        income=p.income,
        dafCounted=p.dafCounted,
        level=lvl,
        ownerName=s.get(User, p.ownerId).displayName,
        version=p.version,
    )


def _shares(d: dict[str, Decimal]) -> list[Share]:
    return [Share(label=k, amount=v) for k, v in sorted(d.items(), key=lambda x: -x[1]) if v]


@router.get("/giving", response_model=GivingView)
def get_giving(request: Request, year: int | None = None, c: Caller = Depends(caller)):
    today = clock.today()
    year = year or today.year
    with server(request).db.read(user=c.id) as s:
        plan, lvl = giving.plan_for(s, c.id, year)
        who = giving.givers(s, plan, c.id)
        gifts = giving.donations(s, who, year)
        counted = [g for g in gifts if giving.counts(plan, g)]
        given = sum((g.amount for g in counted), Decimal(0))
        earned = giving.income(s, plan, who, year)
        goal = giving.target(plan, earned)
        orgs = giving.organisations(s, who)
        by_org: dict[str, Decimal] = {}
        by_cause: dict[str, Decimal] = {}
        by_kind: dict[str, Decimal] = {}
        given_to: dict[str, Decimal] = {}
        for g in counted:
            by_org[g.name] = by_org.get(g.name, Decimal(0)) + g.amount
            by_kind[giving.KINDS[g.kind]] = by_kind.get(giving.KINDS[g.kind], Decimal(0)) + g.amount
            causes = (
                ["In the donor-advised fund"]
                if g.kind == "daf-contribution"
                else giving.causes_of(g.organisation) or ["No cause"]
            )
            for cause in causes:
                by_cause[cause] = by_cause.get(cause, Decimal(0)) + g.amount / len(causes)
            if g.organisation is not None:
                given_to[g.organisation.id] = given_to.get(g.organisation.id, Decimal(0)) + g.amount
        pledged = (
            giving.pledged_ahead(list(orgs.values()), today, given_to)
            if year == today.year
            else Decimal(0)
        )
        history = []
        for y in range(year - 4, year + 1):
            gs = [g for g in giving.donations(s, who, y) if giving.counts(plan, g)]
            inc = giving.income(s, plan if y == year else None, who, y)
            total = sum((g.amount for g in gs), Decimal(0))
            history.append(
                YearPct(year=y, percent=round(float(total / inc * 100), 1) if inc else None)
            )
        return GivingView(
            year=year,
            plan=_plan_out(s, plan, lvl) if plan else None,
            income=earned,
            target=goal,
            given=given,
            pace=giving.pace(goal, today, year),
            pledged=pledged,
            projected=given + pledged,
            byMonth=giving.by_month(plan, gifts, year),
            byOrganisation=_shares(by_org),
            byCause=_shares({k: v.quantize(Decimal("0.01")) for k, v in by_cause.items()}),
            byKind=_shares(by_kind),
            history=[h for h in history if h.percent is not None or h.year == year],
            funds=[
                FundOut(
                    accountId=f.account.id,
                    name=f.account.name,
                    institution=f.account.institution,
                    balance=f.balance,
                    contributed=f.contributed,
                    granted=f.granted,
                )
                for f in giving.funds(s, who, year, gifts)
            ],
            missingAcks=sum(1 for g in gifts if g.needsAck and not g.acknowledged),
            notes=giving.tax_notes(gifts),
        )


def _plan_checked(body: PlanIn) -> dict:
    e = []
    if body.targetKind not in ("percent", "amount"):
        e.append(FieldError("targetKind", "target-invalid", "A percentage or an amount."))
    if body.targetKind == "percent" and not (body.percent and 0 < body.percent <= 100):
        e.append(FieldError("percent", "percent-invalid", "Between 0% and 100%."))
    if body.targetKind == "amount" and not (body.amount and body.amount > 0):
        e.append(FieldError("amount", "amount-invalid", "More than zero."))
    if body.incomeBasis not in ("take-home", "gross", "agi"):
        e.append(FieldError("incomeBasis", "basis-invalid", "Take-home, gross or AGI."))
    if body.incomeBasis != "take-home" and not (body.income and body.income > 0):
        e.append(FieldError("income", "income-missing", "The income, typed."))
    if body.dafCounted not in ("funded", "granted"):
        e.append(FieldError("dafCounted", "daf-invalid", "When funded, or when it grants."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    return PlanIn.model_validate(body.model_dump(include=set(PlanIn.model_fields))).model_dump()


# ---- Organisations (S7.9.5) ----


class OrganisationIn(Model):
    name: str
    ein: str | None = None
    deductible: bool = True
    causes: list[str] = Field(default_factory=list)
    pledge: Money | None = None
    pledgeEvery: str | None = None
    notes: str | None = None


class OrganisationOut(OrganisationIn):
    id: str
    given: Money  # this year
    canWrite: bool
    version: int


def _orgs_view(s, c: Caller) -> list[OrganisationOut]:
    year = clock.today().year
    plan, _ = giving.plan_for(s, c.id, year)
    who = giving.givers(s, plan, c.id)
    given: dict[str, Decimal] = {}
    for g in giving.donations(s, who, year):
        if g.organisation is not None and g.kind != "daf-contribution":
            given[g.organisation.id] = given.get(g.organisation.id, Decimal(0)) + g.amount
    return [
        OrganisationOut(
            id=o.id,
            name=o.name,
            ein=o.ein,
            deductible=o.deductible,
            causes=json.loads(o.causes),
            pledge=o.pledge,
            pledgeEvery=o.pledgeEvery,
            notes=o.notes,
            given=given.get(o.id, Decimal(0)),
            canWrite=o.ownerId == c.id,
            version=o.version,
        )
        for o in sorted(giving.organisations(s, who).values(), key=lambda o: o.name.lower())
    ]


def _org_values(body: OrganisationIn) -> dict:
    e = []
    if not body.name.strip():
        e.append(FieldError("name", "name-missing", "The organisation's name."))
    if body.ein and not (
        len(body.ein.replace("-", "")) == 9 and body.ein.replace("-", "").isdigit()
    ):
        e.append(FieldError("ein", "ein-invalid", "Nine digits, such as 36-2167053."))
    if body.pledge is not None and body.pledge < 0:
        e.append(FieldError("pledge", "amount-invalid", "Zero or more."))
    if body.pledge and body.pledgeEvery not in ("month", "year"):
        e.append(FieldError("pledgeEvery", "every-invalid", "A month or a year."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    return {
        "name": body.name.strip(),
        "ein": (body.ein or "").strip() or None,
        "deductible": body.deductible,
        "causes": exactjson.dumps(sorted({x.strip() for x in body.causes if x.strip()})),
        "pledge": body.pledge or None,
        "pledgeEvery": body.pledgeEvery if body.pledge else None,
        "notes": body.notes or None,
    }


@router.get("/giving/organisations", response_model=list[OrganisationOut])
def list_organisations(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        return _orgs_view(s, c)


def _own_org(s, c: Caller, org_id: str) -> Organisation:
    o = s.get(Organisation, org_id)
    if o is None or o.deleted or o.ownerId != c.id:
        raise Problem(404, "not-found", "Not found")
    return o


# ---- Donations (S7.9.3, S8.9) ----


class DonationIn(Model):
    date: dt.date
    kind: str
    organisationId: str | None = None
    amount: Money | None = None  # for shares, the market value; worked out when left out
    description: str | None = None  # goods given
    transactionId: str | None = None  # a transaction categorised Giving it records
    fromAccountId: str | None = None  # where the money or shares came from
    dafAccountId: str | None = None
    lotId: str | None = None  # shares: the lot they come from
    quantity: Quantity | None = None
    acknowledged: bool = False
    granted: bool | None = None
    notes: str | None = None


class DonationOut(Model):
    id: str | None
    date: dt.date
    kind: str
    kindLabel: str
    name: str
    organisationId: str | None
    amount: Money
    deductible: bool
    counted: bool
    needsAck: bool
    acknowledged: bool
    transactionId: str | None
    description: str | None
    symbol: str | None
    quantity: Quantity | None
    basis: Money | None
    longTerm: bool | None
    granted: bool | None
    notes: str | None
    canWrite: bool
    version: int | None  # None for a gift that is only a categorised transaction


def _donation_out(s, c: Caller, plan, g: giving.Gift) -> DonationOut:
    d = g.record
    inst = s.get(Instrument, d.instrumentId) if d is not None and d.instrumentId else None
    return DonationOut(
        id=g.id,
        date=g.date,
        kind=g.kind,
        kindLabel=giving.KINDS[g.kind],
        name=g.name,
        organisationId=g.organisation.id if g.organisation else None,
        amount=g.amount,
        deductible=g.deductible,
        counted=giving.counts(plan, g),
        needsAck=g.needsAck,
        acknowledged=g.acknowledged,
        transactionId=g.transactionId,
        description=d.description if d else None,
        symbol=inst.symbol if inst else None,
        quantity=d.quantity if d else None,
        basis=d.basis if d else None,
        longTerm=d.longTerm if d else None,
        granted=d.granted if d else None,
        notes=d.notes if d else None,
        canWrite=(d.ownerId == c.id) if d else True,
        version=d.version if d else None,
    )


def donations_view(s, c: Caller, year: int) -> list[DonationOut]:
    plan, _ = giving.plan_for(s, c.id, year)
    who = giving.givers(s, plan, c.id)
    return [_donation_out(s, c, plan, g) for g in giving.donations(s, who, year)]


@router.get("/giving/donations", response_model=list[DonationOut])
def list_donations(request: Request, year: int | None = None, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        return donations_view(s, c, year or clock.today().year)


def _giving_category(s) -> str | None:
    cat = s.scalars(select(Category).where(Category.builtIn == "giving")).first()
    return cat.id if cat else None


def _txn(s, c: Caller, account_id: str, day, kind, amount, payee, **kw) -> Transaction:
    t = Transaction(
        id=ids.new_id("Txn"),
        accountId=account_id,
        date=day,
        kind=kind,
        amount=amount,
        payee=payee,
        createdById=c.id,
        **kw,
    )
    s.add(t)
    s.flush()
    return t


def _shares_given(s, c: Caller, body: DonationIn, to: str) -> dict:
    """Shares from a lot: they leave the account without realizing a gain (S7.9.3); held over
    a year, the deduction is their market value, else their basis."""
    a, _ = access.account(s, c.id, body.fromAccountId or "", "write")
    lot = s.get(Lot, body.lotId or "")
    if lot is None or lot.accountId != a.id or lot.deleted:
        raise refuse("lotId", "lot-unknown", "Choose a lot in that account.")
    open_lot = next((x for x in repo.load(s, a).replay().open if x.lotId == lot.id), None)
    qty = body.quantity or Decimal(0)
    if open_lot is None or not 0 < qty <= open_lot.quantity:
        raise refuse("quantity", "quantity-invalid", "Up to what the lot still holds.")
    basis = (
        (open_lot.basis * qty / open_lot.quantity).quantize(Decimal("0.01"))
        if open_lot.basis is not None
        else None
    )
    # S3.1's one anniversary rule, from the day a wash sale's replacement is held from (S3.8.3).
    long_term = held_long(open_lot.heldFrom or lot.acquiredOn, body.date)
    value = body.amount
    if value is None:
        from .. import valuation

        owner = s.get(Account, lot.accountId).ownerId  # their own typed prices (S4.10)
        price = valuation.prices(s, [lot.instrumentId], body.date, owner).get(lot.instrumentId)
        if price is None:
            raise refuse("amount", "value-missing", "The shares' market value on the day.")
        value = (price.price * qty).quantize(Decimal("0.01"))
    out = _txn(
        s,
        c,
        a.id,
        body.date,
        "transfer-out",
        Decimal(0),
        to,
        instrumentId=lot.instrumentId,
        quantity=-qty,
        lotMethod="specific",
    )
    s.add(LotPick(saleId=out.id, lotId=lot.id, quantity=qty, createdAt=clock.now()))
    if body.kind == "daf-contribution" and body.dafAccountId:
        into = _txn(
            s,
            c,
            body.dafAccountId,
            body.date,
            "transfer-in",
            Decimal(0),
            a.name,
            instrumentId=lot.instrumentId,
            quantity=qty,
        )
        s.add(
            Lot(
                id=ids.new_id("Lot"),
                accountId=body.dafAccountId,
                instrumentId=lot.instrumentId,
                transactionId=into.id,
                acquiredOn=lot.acquiredOn,
                quantity=qty,
                costBasis=basis,
                basisMissing=basis is None,
            )
        )
        out.transferId, into.transferId = into.id, out.id
    return {
        "instrumentId": lot.instrumentId,
        "quantity": qty,
        "basis": basis,
        "longTerm": long_term,
        # The deduction: the market value held over a year, else the basis.
        "amount": value if long_term or basis is None else min(value, basis),
        "fromAccountId": a.id,
        "transactionId": out.id,
    }


def _record(s, c: Caller, body: DonationIn, donation_id: str | None = None) -> Donation:
    e = []
    if body.kind not in giving.KINDS:
        e.append(FieldError("kind", "kind-invalid", "One of the kinds of donation."))
    needs_org = body.kind not in ("daf-contribution",)
    if needs_org and not body.organisationId:
        e.append(FieldError("organisationId", "organisation-missing", "Who it was given to."))
    if body.kind in ("daf-contribution", "daf-grant") and not body.dafAccountId:
        e.append(FieldError("dafAccountId", "fund-missing", "The donor-advised fund."))
    if (
        body.kind != "securities"
        and not body.lotId
        and not body.transactionId
        and (body.amount is None or body.amount <= 0)
    ):
        e.append(FieldError("amount", "amount-invalid", "More than zero."))
    if body.kind == "goods" and not (body.description or "").strip():
        e.append(FieldError("description", "description-missing", "What was given."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    org = None
    plan, lvl = giving.plan_for(s, c.id, body.date.year)
    # Recorded in the plan the caller writes to: its owner's giving (S7.9.1).
    owner = plan.ownerId if plan is not None and lvl == "write" else c.id
    if body.organisationId:
        org = s.get(Organisation, body.organisationId)
        if org is None or org.deleted or org.ownerId not in giving.givers(s, plan, c.id):
            raise refuse("organisationId", "organisation-unknown", "Choose an organisation.")
    fund = None
    if body.dafAccountId:
        fund, _ = access.account(s, c.id, body.dafAccountId, "write")
        if fund.type != "daf":
            raise refuse("dafAccountId", "not-a-fund", "Choose a donor-advised fund.")
    values = {
        "date": body.date,
        "kind": body.kind,
        "organisationId": org.id if org else None,
        "description": (body.description or "").strip() or None,
        "dafAccountId": fund.id if fund else None,
        "acknowledged": body.acknowledged,
        "granted": body.granted if body.kind == "daf-grant" else None,
        "notes": body.notes or None,
        "amount": body.amount or Decimal(0),
    }
    to = org.name if org else (fund.name if fund else "Donation")
    if body.lotId:
        values.update(_shares_given(s, c, body, to))
    elif body.transactionId:
        t = s.get(Transaction, body.transactionId)
        if t is None or t.deleted:
            raise refuse("transactionId", "not-found", "No such transaction.")
        access.account(s, c.id, t.accountId, "write")
        values["transactionId"] = t.id
        values["amount"] = body.amount or -t.amount
        if not t.categoryId and body.kind == "cash":
            t.categoryId = _giving_category(s)
    elif body.fromAccountId:
        a, _ = access.account(s, c.id, body.fromAccountId, "write")
        cat = _giving_category(s) if body.kind in ("cash", "qcd") else None
        out = _txn(s, c, a.id, body.date, "withdrawal", -values["amount"], to, categoryId=cat)
        values["transactionId"] = out.id
        values["fromAccountId"] = a.id
        if body.kind == "daf-contribution" and fund is not None:
            into = _txn(s, c, fund.id, body.date, "transfer", values["amount"], a.name)
            out.kind = "transfer"
            out.categoryId = None
            out.transferId, into.transferId = into.id, out.id
    elif body.kind == "daf-grant" and fund is not None:
        out = _txn(s, c, fund.id, body.date, "withdrawal", -values["amount"], to)
        values["transactionId"] = out.id
    d = Donation(id=donation_id or ids.new_id("Dnatn"), ownerId=owner, **values)
    s.add(d)
    s.flush()
    return d


def _out(s, c: Caller, d: Donation) -> DonationOut:
    return next(x for x in donations_view(s, c, d.date.year) if x.id == d.id)


def _own(s, c: Caller, donation_id: str) -> Donation:
    d = s.get(Donation, donation_id)
    if d is None or d.deleted or d.ownerId != c.id:
        raise Problem(404, "not-found", "Not found")
    return d


def _org_of(s, c: Caller, org_id: str, year: int) -> Organisation:
    o = s.get(Organisation, org_id)
    plan, _ = giving.plan_for(s, c.id, year)
    if o is None or o.deleted or o.ownerId not in giving.givers(s, plan, c.id):
        raise refuse("organisationId", "organisation-unknown", "Choose an organisation.")
    return o


# ---------- the plan, organisations and donations in a dialog's draft (S12.15, S13.8.11) ----------


class GivingPlanRecord(PlanIn):
    """A year's giving plan as a draft saves it (S7.9.1)."""


def _gplan_create(ctx, record_id: str, body: GivingPlanRecord) -> None:
    values = _plan_checked(body)
    p, _ = giving.plan_for(ctx.s, ctx.caller.id, body.year)
    if p is not None:
        raise refuse("year", "plan-exists", "This year has its plan; change it.", 409)
    ctx.s.add(GivingPlan(id=record_id, ownerId=ctx.caller.id, **values))


def _gplan_editable(ctx, record_id: str) -> GivingPlan:
    p = ctx.s.get(GivingPlan, record_id)
    if p is None or p.deleted:
        raise Problem(404, "not-found", "Not found")
    _, lvl = giving.plan_for(ctx.s, ctx.caller.id, p.year)
    if lvl not in ("owner", "write"):
        raise Problem(403, "read-only", "This plan is shared with you to read.")
    return p


def _gplan_update(ctx, p: GivingPlan, body: GivingPlanRecord) -> None:
    if body.year != p.year:
        raise refuse("year", "plan-fixed", "A plan keeps its year.")
    for k, v in _plan_checked(body).items():
        setattr(p, k, v)
    p.updatedAt = clock.now()


def _gplan_read(ctx, record_id: str) -> PlanOut:
    p = ctx.s.get(GivingPlan, record_id)
    _, lvl = giving.plan_for(ctx.s, ctx.caller.id, p.year)
    return _plan_out(ctx.s, p, lvl or "owner")


class OrganisationRecord(OrganisationIn):
    """An organisation as a draft saves it (S7.9.5)."""


def _org_create(ctx, record_id: str, body: OrganisationRecord) -> None:
    ctx.s.add(Organisation(id=record_id, ownerId=ctx.caller.id, **_org_values(body)))


def _org_update(ctx, o: Organisation, body: OrganisationRecord) -> None:
    for k, v in _org_values(body).items():
        setattr(o, k, v)
    o.updatedAt = clock.now()


class DonationRecord(DonationIn):
    """A donation as a draft saves it (S7.9.2): recorded whole; afterwards only what changes
    after the fact does, the acknowledgement arriving (its file among `receiptIds`), a grant
    paid, the organisation, notes."""

    receiptIds: list[IdOf("Rcpt")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )


AFTER = ("acknowledged", "granted", "notes", "organisationId", "receiptIds")


def _donation_create(ctx, record_id: str, body: DonationRecord) -> None:
    s, c = ctx.s, ctx.caller
    d = _record(s, c, body, record_id)
    if body.receiptIds:
        receipts.keep_set(s, c.id, "donation", d.id, [], body.receiptIds)
    activity.record(s, "donation.recorded", actor=c.id, owner=c.id)


def _donation_current(ctx, d: Donation) -> dict:
    out = {f: getattr(d, f, None) for f in DonationIn.model_fields}
    out["amount"] = d.amount
    out["receiptIds"] = [r.id for r in receipts.of_item(ctx.s, d.id, "donation")]
    return out


def _donation_update(ctx, d: Donation, body: DonationRecord) -> None:
    s, c = ctx.s, ctx.caller
    current = _donation_current(ctx, d)
    fixed = [
        f for f in DonationRecord.model_fields if f not in AFTER and getattr(body, f) != current[f]
    ]
    if fixed:
        raise refuse(
            fixed[0], "donation-fixed", "Recorded, a donation changes only after the fact."
        )
    d.acknowledged = body.acknowledged
    if d.kind == "daf-grant" and body.granted is not None:
        d.granted = body.granted
    d.notes = body.notes or None
    if body.organisationId != current["organisationId"] and d.kind != "daf-contribution":
        d.organisationId = _org_of(s, c, body.organisationId, d.date.year).id
    if body.receiptIds != current["receiptIds"]:
        receipts.keep_set(s, c.id, "donation", d.id, current["receiptIds"], body.receiptIds)
        if set(body.receiptIds) - set(current["receiptIds"]):
            d.acknowledged = True  # the acknowledgement's file: it has arrived
    d.updatedAt = clock.now()


save.register(
    save.Kind(
        prefix="GvPln",
        entity=GivingPlan,
        fields=GivingPlanRecord,
        create=_gplan_create,
        editable=_gplan_editable,
        current=lambda ctx, p: {f: getattr(p, f) for f in PlanIn.model_fields},
        update=_gplan_update,
        delete=lambda ctx, p: p.mark_deleted(ctx.caller.id),
        read=_gplan_read,
    )
)
save.register(
    save.Kind(
        prefix="Orgzn",
        entity=Organisation,
        fields=OrganisationRecord,
        create=_org_create,
        editable=lambda ctx, record_id: _own_org(ctx.s, ctx.caller, record_id),
        current=lambda ctx, o: {
            **{f: getattr(o, f) for f in OrganisationIn.model_fields if f != "causes"},
            "causes": json.loads(o.causes or "[]"),
        },
        update=_org_update,
        delete=lambda ctx, o: o.mark_deleted(ctx.caller.id),
        read=lambda ctx, record_id: next(
            x for x in _orgs_view(ctx.s, ctx.caller) if x.id == record_id
        ),
    )
)
save.register(
    save.Kind(
        prefix="Dnatn",
        entity=Donation,
        fields=DonationRecord,
        create=_donation_create,
        editable=lambda ctx, record_id: _own(ctx.s, ctx.caller, record_id),
        current=_donation_current,
        update=_donation_update,
        delete=lambda ctx, d: d.mark_deleted(ctx.caller.id),
        read=lambda ctx, record_id: _out(ctx.s, ctx.caller, ctx.s.get(Donation, record_id)),
    )
)
