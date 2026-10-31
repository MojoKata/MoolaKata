"""Projections (requirements S6), assumptions (S6.3), the bitcoin models' comparison (S6.3.1),
the Dashboard's Plans card (S6.8) and Settings › Tax tables (S16.11)."""

import datetime as dt
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import false, select

from .. import access, activity, clock, exactjson, projections
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
        sharedWith=len(access.holders_of(s, Projection, p.id)) - 1 if level == "owner" else 0,
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
    """`need`: *read*, *write*, or a permission's name (which one is active: *configurable*;
    deleting it: *deletable*)."""
    perms = access.perms(s, Projection, pid, user_id)
    p = s.get(Projection, pid) if perms is not None else None
    if p is None:
        raise Problem(404, "not-found", "Not found")
    want = {"read": None, "write": "writable"}.get(need, need)
    if want is not None and not getattr(perms, want):
        raise Problem(403, "owner-only", "Only the projection's owner can do this.")
    return p, perms.level()


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
            mine = {a.id for a, _ in access.accounts(s, user_id)}
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
        return [] if p is not None and people.readable(s, user_id, p.id) else bad
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
    with server(request).db.read(user=c.id) as s:
        return [row(s, c.id, p, lvl) for p, lvl in projections.visible(s, c.id)]


@router.get("/projections/{projection_id}", response_model=ProjectionDetail)
def get_projection(projection_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        p, lvl = _get(s, c.id, projection_id)
        return detail(s, c.id, p, lvl)


@router.post("/projections/{projection_id}/activate", response_model=Activated)
def activate(projection_id: str, request: Request, c: Caller = Depends(caller)):
    """At most one active per subject: the one it replaces goes back to being a scenario.
    Its median path and 10th–90th band as of today become its baseline (S6.7.2)."""
    with server(request).db.tx(user=c.id) as s:
        p, _ = _get(s, c.id, projection_id, "configurable")
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
    with server(request).db.tx(user=c.id) as s:
        p, _ = _get(s, c.id, projection_id, "configurable")
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
    _get(s, c.id, p.id, "deletable")
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
    with server(request).db.read(user=c.id) as s:
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
    with server(request).db.read(user=c.id) as s:
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
    with server(request).db.read(user=c.id) as s:
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
    # Its correction, a record of the save: none while it stands as shipped.
    figureId: str | None = None
    version: int = 0


class TaxTables(Model):
    year: int
    years: list[int]
    rows: list[TaxRow]


def _tables(s, year: int) -> TaxTables:
    vals = taxtables.figures(s, year)
    changed = taxtables.corrected(s, year)
    shipped = taxtables.SHIPPED.get(year, {})
    rows = {
        r.key: r
        for r in s.scalars(
            select(TaxFigure).where(TaxFigure.year == year, TaxFigure.deleted == false())
        )
    }
    return TaxTables(
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
                figureId=rows[f.key].id if f.key in rows else None,
                version=rows[f.key].version if f.key in rows else 0,
            )
            for f in taxtables.of_year(year)
        ],
    )


@router.get("/settings/tax-tables", response_model=TaxTables)
def get_tax_tables(request: Request, c: Caller = Depends(admin), year: int | None = None):
    with server(request).db.read(user=c.id) as s:
        y = year if year in taxtables.SHIPPED else taxtables.years()[-1]
        return _tables(s, y)


class FigureRecord(Model):
    """An admin's correction of one shipped tax-table figure for a year (S16.11), as the tax
    tables' draft saves it; the shipped value again deletes it."""

    year: int
    key: str
    value: Any


def _figure_check(body: FigureRecord):
    if body.year not in taxtables.SHIPPED:
        raise refuse("year", "year-unknown", "That year's tables don't ship with this release.")
    if body.key not in taxtables.SHIPPED[body.year]:
        raise refuse("key", "figure-not-of-year", "That year doesn't ship it.")
    try:
        value = taxtables.check(body.key, body.value)
    except taxtables.Invalid as e:
        raise refuse("value", "figure-invalid", f"Must be {e}.") from None
    if value == taxtables.SHIPPED[body.year].get(body.key):
        raise refuse(
            "value", "figure-shipped", "That is the figure as shipped: nothing to correct."
        )
    return value


def _figure_noted(ctx, row: TaxFigure) -> None:
    """One Activity entry a save, naming the figures it corrected and their year."""
    years = ctx.notes.setdefault("tax-tables", {})
    years.setdefault(row.year, set()).add(row.key)

    def record() -> None:
        for year, keys in years.items():
            activity.record(
                ctx.s,
                "settings.tax-tables",
                actor=ctx.caller.id,
                for_admins=True,
                detail={"fields": sorted(keys), "year": year},
            )

    ctx.verify("tax-tables", record)


def _figure_admin(ctx) -> None:
    if not ctx.caller.admin:
        raise Problem(403, "admins-only", "Only admins can do this.")


def _figure_create(ctx, record_id: str, body: FigureRecord) -> None:
    _figure_admin(ctx)
    value = _figure_check(body)
    if body.key in taxtables.corrected(ctx.s, body.year):
        raise refuse("key", "figure-corrected", "It is corrected: change its correction.", 409)
    row = TaxFigure(
        id=record_id,
        year=body.year,
        key=body.key,
        value=exactjson.dumps(value),
        changedById=ctx.caller.id,
    )
    ctx.s.add(row)
    _figure_noted(ctx, row)


def _figure_editable(ctx, record_id: str) -> TaxFigure:
    _figure_admin(ctx)
    row = ctx.s.get(TaxFigure, record_id)
    if row is None or row.deleted:
        raise Problem(404, "not-found", "Not found")
    return row


def _figure_update(ctx, row: TaxFigure, body: FigureRecord) -> None:
    if (body.year, body.key) != (row.year, row.key):
        raise refuse("key", "figure-fixed", "A correction stays with its figure and year.")
    value = _figure_check(body)
    row.value, row.changedById = exactjson.dumps(value), ctx.caller.id
    _figure_noted(ctx, row)


def _figure_delete(ctx, row: TaxFigure) -> None:
    """The figure as shipped again."""
    _figure_admin(ctx)
    row.mark_deleted(ctx.caller.id)
    _figure_noted(ctx, row)


def _figure_current(ctx, row: TaxFigure) -> dict:
    return {"year": row.year, "key": row.key, "value": json.loads(row.value)}


save.register(
    save.Kind(
        prefix="TaxFg",
        entity=TaxFigure,
        fields=FigureRecord,
        create=_figure_create,
        editable=_figure_editable,
        current=_figure_current,
        update=_figure_update,
        delete=_figure_delete,
        read=lambda ctx, record_id: _tables(ctx.s, ctx.s.get(TaxFigure, record_id).year),
    )
)
