"""Projections (requirements S6), assumptions (S6.3), the bitcoin models' comparison (S6.3.1),
the Dashboard's Plans card (S6.8) and Settings › Tax tables (S16.11)."""

import datetime as dt
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import false, select

from .. import access, activity, clock, exactjson, ids, projections
from ..errors import FieldError, Problem, refuse
from ..projections import assumptions, bitcoin, taxtables
from ..store.entities.projections import AssumptionSet, Projection, ShownProjection, TaxFigure
from ..store.entities.users import User
from . import save
from .conventions import (
    ExactRoute,
    Loose,
    Model,
    Money,
    Ratio,
    check_version,
    if_match,
    version_of,
)
from .deps import Caller, admin, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["projections"])
GOALS = ("retirement", "savings", "education")


class ProjectionRow(Model):
    id: str
    name: str
    goal: str
    active: bool
    level: str
    ownerName: str
    builtOn: dict
    builtOnLabel: str
    headline: str
    status: str | None
    shown: bool
    sharedWith: int
    version: int


class ProjectionDetail(ProjectionRow):
    inputs: dict
    result: dict
    tracking: dict | None
    baselineAt: dt.datetime | None


class NewProjection(Model):
    name: str
    goal: str
    builtOn: Loose
    inputs: Loose = Field(default_factory=dict)


class Activated(Model):
    replaced: str | None


class Shown(Model):
    shown: bool


def _shown(s, user_id: str, projection_id: str) -> bool:
    row = s.get(ShownProjection, (user_id, projection_id))
    return row is not None and not row.deleted


def row(s, c_id: str, p: Projection, level: str, result: dict | None = None) -> ProjectionRow:
    result = result or projections.compute(s, p, c_id)
    track = projections.tracking(s, p, c_id) if p.active else None
    owner = s.get(User, p.ownerId)
    return ProjectionRow(
        id=p.id,
        name=p.name,
        goal=p.goal,
        active=p.active,
        level=level,
        ownerName=owner.displayName if owner else "",
        builtOn=json.loads(p.builtOn),
        builtOnLabel=result["builtOnLabel"],
        headline=projections.headline(p, result["answer"]),
        status=track["status"] if track else None,
        shown=level == "owner" or _shown(s, c_id, p.id),
        sharedWith=len(access.holders(s, "projection", p.id, p.ownerId)) - 1
        if level == "owner"
        else 0,
        version=p.version,
    )


def detail(s, c_id: str, p: Projection, level: str) -> ProjectionDetail:
    result = projections.compute(s, p, c_id)
    base = row(s, c_id, p, level, result)
    return ProjectionDetail(
        **base.model_dump(),
        inputs=json.loads(p.inputs),
        result=exactjson.marked(result),
        tracking=exactjson.marked(projections.tracking(s, p, c_id)),
        baselineAt=p.baselineAt,
    )


def _get(s, user_id: str, pid: str, need: str = "read") -> tuple[Projection, str]:
    p = s.get(Projection, pid)
    lvl = (
        access.level_of(s, user_id, "projection", p.ownerId, p.id, p.deleted)
        if p is not None
        else None
    )
    if lvl is None:
        raise Problem(404, "not-found", "Not found")
    if access.RANK[lvl] < access.RANK[need]:
        raise Problem(403, "owner-only", "Only the projection's owner can do this.")
    return p, lvl


def _check(s, user_id: str, name, goal, built, inputs) -> list[FieldError]:
    errors = []
    if name is not None and (not str(name).strip() or len(name) > 80):
        errors.append(FieldError("name", "name-invalid", "Enter a name of up to 80 characters."))
    if goal is not None and goal not in GOALS:
        errors.append(
            FieldError("goal", "goal-invalid", "Retirement, education or a savings target.")
        )
    if built is not None:
        kind = built.get("kind")
        if kind not in ("accounts", "portfolio", "typed"):
            errors.append(FieldError("builtOn", "built-on-invalid", "Choose what it is built on."))
        elif kind == "typed":
            try:
                if float(built.get("amount", -1)) < 0:
                    raise ValueError
            except TypeError, ValueError:
                errors.append(FieldError("builtOn.amount", "amount-invalid", "An amount."))
        elif kind == "portfolio":
            try:
                access.portfolio(s, user_id, built.get("id", ""))
            except Problem:
                errors.append(FieldError("builtOn", "portfolio-unknown", "Choose a portfolio."))
        else:
            mine = {a.id for a, _ in access.visible_accounts(s, user_id)}
            if not built.get("ids") or any(i not in mine for i in built["ids"]):
                errors.append(FieldError("builtOn", "accounts-unknown", "Choose accounts."))
    if inputs is not None:
        errors += _check_inputs(inputs)
        who = inputs.get("beneficiary")
        if goal == "education" or who is not None:
            errors += _check_beneficiary(s, user_id, who)
    return errors


def _check_beneficiary(s, user_id: str, who) -> list[FieldError]:
    """An education goal is for a person the user can see, or a user (S10.10)."""
    from ..store.entities.education import Person
    from ..store.entities.users import User

    bad = [FieldError("inputs.beneficiary", "beneficiary-invalid", "Choose who it is for.")]
    if not isinstance(who, dict):
        return bad
    if who.get("kind") == "person":
        from .. import people

        p = s.get(Person, who.get("id") or "")
        return [] if p is not None and people.level(s, user_id, p) is not None else bad
    if who.get("kind") == "user":
        return [] if s.get(User, who.get("id") or "") is not None else bad
    return bad


def _num(inputs: dict, path: str, lo: float, hi: float, errors: list, message: str) -> None:
    v: Any = inputs
    for part in path.split("."):
        v = v.get(part) if isinstance(v, dict) else None
    if v is None:
        return
    if isinstance(v, bool) or not isinstance(v, int | float) or not lo <= v <= hi:
        errors.append(FieldError(f"inputs.{path}", "input-invalid", message))


def _check_inputs(inputs: dict) -> list[FieldError]:
    e: list[FieldError] = []
    _num(inputs, "contribution.amount", 0, 10_000_000, e, "Zero or more.")
    _num(inputs, "contribution.growth", -20, 50, e, "Between −20% and 50%.")
    _num(inputs, "monthly", 0, 1_000_000, e, "Zero or more.")
    _num(inputs, "target", 0, 1e10, e, "Zero or more.")
    _num(inputs, "horizonAge", 60, 120, e, "Between 60 and 120.")
    _num(inputs, "fees", 0, 5, e, "Between 0% and 5%.")
    _num(inputs, "runs", 100, 5000, e, "Between 100 and 5,000.")
    _num(inputs, "startAge", 3, 40, e, "Between 3 and 40.")
    _num(inputs, "schoolYears", 1, 12, e, "Between 1 and 12.")
    _num(inputs, "cost", 0, 1_000_000, e, "Zero or more.")
    if inputs.get("costBasis") not in (None, "public", "private", "typed"):
        e.append(FieldError("inputs.costBasis", "input-invalid", "Public, private or typed."))
    for i, p in enumerate(inputs.get("people") or []):
        _num({"x": p}, "x.retireAge", 30, 90, e, "Between 30 and 90.")
        if e and e[-1].field == "inputs.x.retireAge":
            e[-1] = FieldError(f"inputs.people.{i}.retireAge", "input-invalid", e[-1].message)
    if inputs.get("date"):
        try:
            when = dt.date.fromisoformat(inputs["date"])
            if when <= clock.today():
                e.append(FieldError("inputs.date", "date-past", "A date in the future."))
            elif when.year > clock.today().year + 100:
                e.append(FieldError("inputs.date", "date-invalid", "A date within 100 years."))
        except ValueError:
            e.append(FieldError("inputs.date", "date-invalid", "A date."))
    # The years a projection runs are bounded: a birth year within the last 120 years, a date
    # or first year of school within the next 100 (S6.4).
    year = clock.today().year
    people = inputs.get("people") or []
    if not isinstance(people, list) or len(people) > 2:
        e.append(FieldError("inputs.people", "input-invalid", "One person, or a couple."))
        people = []
    for i, p in enumerate(people):
        born = p.get("birthYear") if isinstance(p, dict) else None
        if born is not None and (
            isinstance(born, bool) or not isinstance(born, int) or not year - 120 <= born <= year
        ):
            e.append(
                FieldError(
                    f"inputs.people.{i}.birthYear", "input-invalid", "A year in the last 120."
                )
            )
    _num(inputs, "firstYear", year - 1, year + 100, e, "A year within the next 100.")
    income = inputs.get("income") or []
    if not isinstance(income, list) or len(income) > 10:
        e.append(FieldError("inputs.income", "input-invalid", "At most 10 sources of income."))
    else:
        for i, item in enumerate(income):
            _num({"x": item}, "x.fromAge", 0, 120, e, "Between 0 and 120.")
            _num({"x": item}, "x.monthly", 0, 1_000_000, e, "Zero or more.")
            if e and e[-1].field.startswith("inputs.x."):
                e[-1] = FieldError(
                    e[-1].field.replace("inputs.x.", f"inputs.income.{i}."),
                    "input-invalid",
                    e[-1].message,
                )
    w = (inputs.get("withdrawal") or {}).get("method")
    if w is not None and w not in ("fourPercent", "fixed", "percent"):
        e.append(FieldError("inputs.withdrawal.method", "input-invalid", "Choose a rule."))
    return e


def _raise(errors: list[FieldError]) -> None:
    if errors:
        raise Problem(422, errors[0].code, errors[0].message, errors)


@router.get("/projections", response_model=list[ProjectionRow])
def list_projections(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        return [row(s, c.id, p, lvl) for p, lvl in projections.visible(s, c.id)]


@router.post("/projections", response_model=ProjectionDetail, status_code=201)
def create_projection(body: NewProjection, request: Request, c: Caller = Depends(caller)):
    """It starts as a scenario; making it active is a step of its own (S6.7)."""
    with server(request).db.tx() as s:
        _raise(_check(s, c.id, body.name, body.goal, body.builtOn, body.inputs))
        p = Projection(
            id=ids.new_id("Prjct"),
            ownerId=c.id,
            name=body.name.strip(),
            goal=body.goal,
            builtOn=exactjson.dumps(body.builtOn),
            inputs=exactjson.dumps(body.inputs),
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
        out = detail(s, c.id, p, "owner")
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/ui/api/projections/{p.id}"},
    )


@router.get("/projections/{projection_id}", response_model=ProjectionDetail)
def get_projection(projection_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        p, lvl = _get(s, c.id, projection_id)
        return detail(s, c.id, p, lvl)


@router.post("/projections/{projection_id}/activate", response_model=Activated)
def activate(projection_id: str, request: Request, c: Caller = Depends(caller)):
    """At most one active per subject: the one it replaces goes back to being a scenario.
    Its median path and 10th–90th band as of today become its baseline (S6.7.2)."""
    with server(request).db.tx() as s:
        p, _ = _get(s, c.id, projection_id, "owner")
        mine = projections.subject(p)
        replaced = None
        for other, lvl in projections.visible(s, c.id):
            if (
                other.id != p.id
                and other.active
                and lvl == "owner"
                and projections.subject(other) == mine
            ):
                other.active, other.baseline, other.baselineAt = False, None, None
                replaced = other.name
        p.active = True
        p.baseline = exactjson.dumps(projections.make_baseline(projections.compute(s, p, c.id)))
        p.baselineAt = clock.now()
        activity.record(
            s,
            "projection.activated",
            actor=c.id,
            subject_kind="projection",
            subject_id=p.id,
            owner=p.ownerId,
        )
    return Activated(replaced=replaced)


@router.post("/projections/{projection_id}/deactivate", status_code=204)
def deactivate(projection_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.tx() as s:
        p, _ = _get(s, c.id, projection_id, "owner")
        p.active, p.baseline, p.baselineAt = False, None, None
    return Response(status_code=204)


class ProjectionRecord(NewProjection):
    """A projection as a draft saves it (S6.6): its goal chosen when it is made. An active
    one's new inputs become its baseline only when `rebaseline` asks it (S6.7.4); it is an
    instruction, never kept."""

    rebaseline: bool = False


def _projection_create(ctx, record_id: str, body: ProjectionRecord) -> None:
    """It starts as a scenario; making it active is a step of its own (S6.7)."""
    s, c = ctx.s, ctx.caller
    _raise(_check(s, c.id, body.name, body.goal, body.builtOn, body.inputs))
    p = Projection(
        id=record_id,
        ownerId=c.id,
        name=body.name.strip(),
        goal=body.goal,
        builtOn=exactjson.dumps(body.builtOn),
        inputs=exactjson.dumps(body.inputs),
    )
    s.add(p)
    s.flush()
    activity.record(s, "projection.created", actor=c.id, subject_kind="projection",
                    subject_id=p.id, owner=c.id)  # fmt: skip


def _projection_current(ctx, p: Projection) -> dict:
    return {"name": p.name, "goal": p.goal, "builtOn": json.loads(p.builtOn or "null"),
            "inputs": json.loads(p.inputs or "{}"), "rebaseline": False}  # fmt: skip


def _projection_update(ctx, p: Projection, body: ProjectionRecord) -> None:
    s, c = ctx.s, ctx.caller
    if body.goal != p.goal:
        raise refuse("goal", "goal-fixed", "A projection keeps its goal; make another.")
    _raise(_check(s, p.ownerId, body.name, None, body.builtOn, body.inputs))
    current = _projection_current(ctx, p)
    fields = [f for f in ("name", "builtOn", "inputs") if getattr(body, f) != current[f]]
    p.name = body.name.strip()
    p.builtOn = exactjson.dumps(body.builtOn)
    p.inputs = exactjson.dumps(body.inputs)
    if p.active and body.rebaseline:
        s.flush()
        p.baseline = exactjson.dumps(projections.make_baseline(projections.compute(s, p, c.id)))
        p.baselineAt = clock.now()
        fields.append("baseline")
    p.updatedAt = clock.now()
    if fields:
        activity.record(s, "projection.updated", actor=c.id, subject_kind="projection",
                        subject_id=p.id, owner=p.ownerId, detail={"fields": fields})  # fmt: skip


def _projection_delete(ctx, p: Projection) -> None:
    s, c = ctx.s, ctx.caller
    _get(s, c.id, p.id, "owner")
    p.mark_deleted(c.id)
    activity.record(s, "projection.deleted", actor=c.id, subject_kind="projection",
                    subject_id=p.id, owner=c.id)  # fmt: skip


def _projection_read(ctx, record_id: str) -> ProjectionDetail:
    p, lvl = _get(ctx.s, ctx.caller.id, record_id)
    return detail(ctx.s, ctx.caller.id, p, lvl)


save.register(
    save.Kind(
        prefix="Prjct",
        entity=Projection,
        fields=ProjectionRecord,
        create=_projection_create,
        editable=lambda ctx, record_id: _get(ctx.s, ctx.caller.id, record_id, "write")[0],
        current=_projection_current,
        update=_projection_update,
        delete=_projection_delete,
        read=_projection_read,
    )
)


@router.put("/projections/{projection_id}/shown", response_model=Shown)
def show_on_dashboard(
    projection_id: str, body: Shown, request: Request, c: Caller = Depends(caller)
):
    """A shared active projection shows on a receiver's Dashboard only when they ask (S6.8.3)."""
    with server(request).db.tx() as s:
        p, lvl = _get(s, c.id, projection_id)
        if lvl == "owner":
            raise Problem(409, "owner-sees-it", "Your own active projections always show.")
        row_ = s.get(ShownProjection, (c.id, p.id))
        if row_ is None:
            if body.shown:
                s.add(ShownProjection(userId=c.id, projectionId=p.id, createdAt=clock.now()))
        else:
            if body.shown:
                row_.restore()
            else:
                row_.mark_deleted(c.id)
    return body


# ---------- the Dashboard's Plans card (S6.8.1) ----------


class Plan(Model):
    id: str
    name: str
    goal: str
    status: str | None
    headline: str
    actual: list[tuple[str, Money]]  # exact, as the tracking is (S6.9)
    baseline: list[tuple[str, Money]]
    sharedBy: str | None
    builtOn: dict


@router.get("/dashboard/plans", response_model=list[Plan])
def plans(request: Request, c: Caller = Depends(caller)):
    out = []
    with server(request).db.read() as s:
        for p, lvl in projections.visible(s, c.id):
            if not p.active or (lvl != "owner" and not _shown(s, c.id, p.id)):
                continue
            result = projections.compute(s, p, c.id)
            track = projections.tracking(s, p, c.id) or {}
            owner = s.get(User, p.ownerId)
            out.append(
                Plan(
                    id=p.id,
                    name=p.name,
                    goal=p.goal,
                    status=track.get("status"),
                    headline=projections.headline(p, result["answer"]),
                    actual=track.get("points", []),
                    baseline=[(d, mid) for d, _, mid, _ in track.get("band", [])],
                    sharedBy=None if lvl == "owner" else owner.displayName,
                    builtOn=json.loads(p.builtOn),
                )
            )
    return out


# ---------- assumptions (S6.3) ----------


class AssumptionsView(Model):
    figures: dict
    classes: list[tuple[str, str]]
    bitcoinModels: list[tuple[str, str]]
    id: str | None = None  # the user's own figures: none while they keep the shipped ones
    version: int = 0


def assumptions_view(s, user_id: str) -> AssumptionsView:
    row = assumptions.row_of(s, user_id)
    return AssumptionsView(
        figures=assumptions.load(s, user_id),
        classes=[(k, label) for k, label, _, _ in assumptions.CLASSES],
        bitcoinModels=assumptions.BITCOIN_MODELS,
        id=row.id if row else None,
        version=row.version if row else 0,
    )


@router.get("/assumptions", response_model=AssumptionsView)
def get_assumptions(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        return assumptions_view(s, c.id)


class AssumptionsRecord(Model):
    """A user's own assumptions as a draft saves them (S6.3): every figure, checked together;
    made when they first change the shipped ones, deleted to go back to them."""

    figures: Loose


def _assumptions_check(body: AssumptionsRecord) -> None:
    problems = assumptions.check(body.figures)
    if problems:
        errors = [FieldError(f"figures.{f}", "assumption-invalid", m) for f, m in problems]
        raise Problem(422, "assumption-invalid", errors[0].message, errors)


def _assumptions_create(ctx, record_id: str, body: AssumptionsRecord) -> None:
    s, c = ctx.s, ctx.caller
    if assumptions.row_of(s, c.id) is not None:
        raise refuse(None, "assumptions-exist", "Your assumptions are here: change them.", 409)
    _assumptions_check(body)
    figures = json.dumps(body.figures, sort_keys=True)
    s.add(AssumptionSet(id=record_id, ownerId=c.id, figures=figures))
    activity.record(s, "profile.assumptions", actor=c.id, owner=c.id)


def _assumptions_editable(ctx, record_id: str) -> AssumptionSet:
    row = ctx.s.get(AssumptionSet, record_id)
    if row is None or row.deleted or row.ownerId != ctx.caller.id:
        raise Problem(404, "not-found", "Not found")
    return row


def _assumptions_update(ctx, row: AssumptionSet, body: AssumptionsRecord) -> None:
    _assumptions_check(body)
    row.figures = json.dumps(body.figures, sort_keys=True)
    activity.record(ctx.s, "profile.assumptions", actor=ctx.caller.id, owner=ctx.caller.id)


save.register(
    save.Kind(
        prefix="Asmpt",
        entity=AssumptionSet,
        fields=AssumptionsRecord,
        create=_assumptions_create,
        editable=_assumptions_editable,
        current=lambda ctx, row: {"figures": json.loads(row.figures or "{}")},
        update=_assumptions_update,
        # Deleted, the shipped figures stand again.
        delete=lambda ctx, row: row.mark_deleted(ctx.caller.id),
        read=lambda ctx, record_id: assumptions_view(ctx.s, ctx.caller.id),
    )
)


class ModelRow(Model):
    model: str
    path: list[tuple[int, int]]
    at: dict[int, int]
    record: str


class ModelsView(Model):
    price: Ratio | None
    rows: list[ModelRow]
    figuresYear: int


@router.get("/bitcoin-models", response_model=ModelsView)
def bitcoin_models(request: Request, c: Caller = Depends(caller)):
    """Compare models: each one's median path and its figures for 2030, 2035 and 2045."""
    with server(request).db.read() as s:
        price = projections._btc_price(s)
        year = clock.today().year
        rows = bitcoin.compare(taxtables.figures(s, year), price or 100_000.0, clock.today())
    return ModelsView(price=price, rows=[ModelRow(**r) for r in rows], figuresYear=year)


# ---------- Settings › Tax tables (S16.11) ----------


class TaxRow(Model):
    key: str
    label: str
    kind: str
    group: str
    source: str
    value: Any
    shipped: Any
    corrected: bool


class TaxTables(Model):
    year: int
    years: list[int]
    rows: list[TaxRow]
    version: int  # the year's corrections together (S13.8.6)


class TaxChange(Model):
    year: int
    values: Loose


def _tables(s, year: int) -> TaxTables:
    vals = taxtables.figures(s, year)
    changed = taxtables.corrected(s, year)
    shipped = taxtables.SHIPPED.get(year, {})
    return TaxTables(
        version=version_of(s, TaxFigure, TaxFigure.year == year),
        year=year,
        years=taxtables.years(),
        rows=[
            TaxRow(
                key=f.key,
                label=f.label,
                kind=f.kind,
                group=f.group,
                source=f.source,
                value=vals.get(f.key),
                shipped=shipped.get(f.key),
                corrected=f.key in changed,
            )
            for f in taxtables.of_year(year)
        ],
    )


@router.get("/settings/tax-tables", response_model=TaxTables)
def get_tax_tables(request: Request, c: Caller = Depends(admin), year: int | None = None):
    with server(request).db.read() as s:
        y = year if year in taxtables.SHIPPED else taxtables.years()[-1]
        return _tables(s, y)


@router.put("/settings/tax-tables", response_model=TaxTables)
def put_tax_tables(
    body: TaxChange, request: Request, c: Caller = Depends(admin), version: int = Depends(if_match)
):
    """A correction to a shipped figure; the shipped value again removes it."""
    if body.year not in taxtables.SHIPPED:
        raise Problem(404, "year-unknown", "That year's tables don't ship with this release.")
    errors = []
    clean = {}
    for k, v in body.values.items():
        if k in taxtables.BY_KEY and k not in taxtables.SHIPPED[body.year]:
            errors.append(FieldError(k, "figure-not-of-year", "That year doesn't ship it."))
            continue
        try:
            clean[k] = taxtables.check(k, v)
        except taxtables.Invalid as e:
            errors.append(FieldError(k, "figure-invalid", f"Must be {e}."))
    _raise(errors)
    with server(request).db.tx() as s:
        check_version(
            version_of(s, TaxFigure, TaxFigure.year == body.year),
            version,
            lambda: _tables(s, body.year),
        )
        rows = {
            r.key: r
            for r in s.scalars(
                select(TaxFigure).where(TaxFigure.year == body.year, TaxFigure.deleted == false())
            )
        }
        changed = []
        for k, v in clean.items():
            shipped = taxtables.SHIPPED[body.year].get(k)
            r = rows.get(k)
            if v == shipped:
                if r is not None:
                    r.mark_deleted(c.id)
                    changed.append(k)
                continue
            if r is None:
                s.add(
                    TaxFigure(
                        id=ids.new_id("TaxFg"),
                        year=body.year,
                        key=k,
                        value=exactjson.dumps(v),
                        changedById=c.id,
                    )
                )
                changed.append(k)
            elif json.loads(r.value) != v:
                r.value, r.changedById = exactjson.dumps(v), c.id
                changed.append(k)
        if changed:
            activity.record(
                s,
                "settings.tax-tables",
                actor=c.id,
                for_admins=True,
                detail={"fields": sorted(changed), "year": body.year},
            )
        s.flush()
        return _tables(s, body.year)
