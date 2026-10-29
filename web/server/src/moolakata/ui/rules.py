"""Categorisation and payee rules (requirements S2.7): a user's own ordered list, edited on
Transactions › Rules, applied on import and on demand to the uncategorised."""

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import false, select

from .. import access, activity, tags
from ..errors import FieldError, Problem, refuse
from ..ledger import rules as match
from ..store.entities.accounts import Account, Category, Rule, Transaction
from ..store.repos import rules as repo
from . import save
from .conventions import ExactRoute, IdOf, Model, Money
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["rules"])

DIRECTIONS = ("any", "in", "out")


class RuleFields(Model):
    payeeMatch: str
    amountMin: Money | None = None
    amountMax: Money | None = None
    direction: str = "any"
    accountId: str | None = None
    categoryId: str | None = None
    payee: str | None = None  # the payee shown: Rename to


class RuleOut(Model):
    id: str
    position: int
    payeeMatch: str
    amountMin: Money | None
    amountMax: Money | None
    direction: str
    accountId: str | None
    accountName: str | None
    accountDeleted: bool
    categoryId: str | None
    categoryPath: str | None
    categoryDeleted: bool
    payee: str | None
    tags: list[str]  # by name
    tagIds: list[str]
    version: int


class RuleList(Model):
    items: list[RuleOut]
    uncategorised: int  # in the accounts the user can change, that a rule could set


class Move(Model):
    to: int  # the place it goes, from 0


class Applied(Model):
    changed: int


def _paths(s) -> dict[str, tuple[str, bool]]:
    cats = list(s.scalars(select(Category)))
    by = {c.id: c for c in cats}
    return {
        c.id: (f"{by[c.parentId].name} › {c.name}" if c.parentId in by else c.name, c.deleted)
        for c in cats
    }


def _out(s, r: Rule, paths: dict) -> RuleOut:
    a = s.get(Account, r.accountId) if r.accountId else None
    path, cat_deleted = paths.get(r.categoryId, (None, False)) if r.categoryId else (None, False)
    return RuleOut(
        id=r.id,
        position=r.position,
        payeeMatch=r.payeeMatch,
        amountMin=r.amountMin,
        amountMax=r.amountMax,
        direction=r.direction,
        accountId=r.accountId,
        accountName=a.name if a else None,
        accountDeleted=bool(a and a.deleted),
        categoryId=r.categoryId,
        categoryPath=path,
        categoryDeleted=cat_deleted,
        payee=r.payee,
        tags=[t.name for t in _rule_tags(s, r)],
        tagIds=[t.id for t in _rule_tags(s, r)],
        version=r.version,
    )


def _writable(s, user_id: str) -> list[str]:
    return [a.id for a, lvl in access.visible_accounts(s, user_id) if lvl in ("owner", "write")]


def _uncategorised(s, user_id: str) -> list[Transaction]:
    ids_ = _writable(s, user_id)
    if not ids_:
        return []
    return list(
        s.scalars(
            select(Transaction).where(
                Transaction.accountId.in_(ids_),
                Transaction.deleted == false(),
                Transaction.categoryId.is_(None),
                Transaction.instrumentId.is_(None),
                Transaction.transferId.is_(None),
            )
        )
    )


def _list(s, user_id: str) -> RuleList:
    paths = _paths(s)
    rules = repo.Rules(s, user_id)
    pending = sum(
        1
        for t in _uncategorised(s, user_id)
        if rules.first(t.payeeRaw or t.payee, t.amount, t.accountId)
    )
    return RuleList(
        items=[_out(s, r, paths) for r in repo.of_user(s, user_id)], uncategorised=pending
    )


def _rule_tags(s, r: Rule) -> list:
    return tags.of(s, "rule", r.ownerId, [r.id]).get(r.id, [])


def _check(s, c: Caller, body: RuleFields, tagged: int) -> list[FieldError]:
    e: list[FieldError] = []
    try:
        match.compile_pattern(body.payeeMatch)
    except match.Invalid as x:
        e.append(FieldError("payeeMatch", "pattern-invalid", str(x)))
    if body.direction not in DIRECTIONS:
        e.append(FieldError("direction", "direction-invalid", "Money in, out, or either."))
    for f in ("amountMin", "amountMax"):
        v = getattr(body, f)
        if v is not None and v < 0:
            e.append(FieldError(f, "amount-invalid", "The amount without its sign: 0 or more."))
    if (
        body.amountMin is not None
        and body.amountMax is not None
        and body.amountMax < body.amountMin
    ):
        e.append(FieldError("amountMax", "range-invalid", "At least the amount it starts from."))
    if body.accountId and body.accountId not in _writable(s, c.id):
        e.append(FieldError("accountId", "account-unknown", "One of the accounts you can change."))
    if body.categoryId:
        cat = s.get(Category, body.categoryId)
        if cat is None or cat.deleted:
            e.append(FieldError("categoryId", "category-unknown", "Choose a category."))
    if body.payee is not None and len(body.payee.strip()) > 200:
        e.append(FieldError("payee", "payee-too-long", "At most 200 characters."))
    if tagged > match.MAX_TAGS:
        e.append(FieldError("tagIds", "tags-invalid", "Up to 10 tags."))
    if not body.categoryId and not (body.payee or "").strip() and not tagged:
        e.append(
            FieldError("categoryId", "rule-sets-nothing", "A category, a payee or a tag to set.")
        )
    return e


def _raise(e: list[FieldError]) -> None:
    if e:
        raise Problem(422, e[0].code, e[0].message, e)


def _fill(r: Rule, body: RuleFields) -> None:
    r.payeeMatch = body.payeeMatch.strip()
    r.amountMin, r.amountMax = body.amountMin, body.amountMax
    r.direction = body.direction
    r.accountId = body.accountId or None
    r.categoryId = body.categoryId or None
    r.payee = (body.payee or "").strip() or None


def _record(s, kind: str, c: Caller, count: int | None = None) -> None:
    activity.record(
        s,
        kind,
        actor=c.id,
        subject_kind="user",
        subject_id=c.id,
        owner=c.id,
        detail={"count": count} if count is not None else None,
    )


def _renumber(rules: list[Rule]) -> None:
    for i, r in enumerate(rules):
        if r.position != i:
            r.position = i


@router.get("/rules", response_model=RuleList)
def list_rules(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        return _list(s, c.id)


def _own(s, c: Caller, rule_id: str) -> Rule:
    r = s.get(Rule, rule_id)
    if r is None or r.deleted or r.ownerId != c.id:
        raise Problem(404, "not-found", "No such rule.")
    return r


@router.post("/rules/{rule_id}/move", response_model=RuleList)
def move_rule(rule_id: str, body: Move, request: Request, c: Caller = Depends(caller)):
    """Up or down the list: first match wins, so the order is what a rule means."""
    with server(request).db.tx() as s:
        r = _own(s, c, rule_id)
        rules = [x for x in repo.of_user(s, c.id) if x.id != r.id]
        rules.insert(max(0, min(body.to, len(rules))), r)
        _renumber(rules)
        s.flush()
        _record(s, "rule.moved", c)
        return _list(s, c.id)


class RuleRecord(RuleFields):
    """A rule as a draft saves it (S2.7): a new one goes last in the list; the tags it sets
    are its owner's."""

    tagIds: list[IdOf("Tag")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )


def _rule_create(ctx, record_id: str, body: RuleRecord) -> None:
    s, c = ctx.s, ctx.caller
    _raise(_check(s, c, body, len(body.tagIds)))
    tags.owned(s, c.id, body.tagIds)
    rules = repo.of_user(s, c.id)
    if len(rules) >= 500:
        raise refuse(None, "too-many-rules", "At most 500 rules.")
    r = Rule(id=record_id, ownerId=c.id, position=len(rules), payeeMatch="")
    _fill(r, body)
    s.add(r)
    s.flush()
    tags.set_on(s, "rule", r.id, c.id, body.tagIds, c.id)
    _record(s, "rule.created", c)


def _rule_current(ctx, r: Rule) -> dict:
    return {f: getattr(r, f) for f in RuleFields.model_fields} | {
        "tagIds": [t.id for t in _rule_tags(ctx.s, r)]
    }


def _rule_update(ctx, r: Rule, body: RuleRecord) -> None:
    _raise(_check(ctx.s, ctx.caller, body, len(body.tagIds)))
    tags.owned(ctx.s, ctx.caller.id, body.tagIds)
    _fill(r, body)
    tags.set_on(ctx.s, "rule", r.id, ctx.caller.id, body.tagIds, ctx.caller.id)
    _record(ctx.s, "rule.updated", ctx.caller)


def _rule_delete(ctx, r: Rule) -> None:
    s, c = ctx.s, ctx.caller
    r.mark_deleted(c.id)
    _renumber([x for x in repo.of_user(s, c.id) if x.id != r.id])
    _record(s, "rule.deleted", c)


save.register(
    save.Kind(
        prefix="Rule",
        entity=Rule,
        fields=RuleRecord,
        create=_rule_create,
        editable=lambda ctx, record_id: _own(ctx.s, ctx.caller, record_id),
        current=_rule_current,
        update=_rule_update,
        delete=_rule_delete,
        read=lambda ctx, record_id: _out(ctx.s, ctx.s.get(Rule, record_id), _paths(ctx.s)),
    )
)


@router.post("/rules/apply", response_model=Applied)
def apply_rules(request: Request, c: Caller = Depends(caller)):
    """The rules over the uncategorised transactions in the accounts the user can change; how
    many changed is recorded, never which (S2.7.4)."""
    with server(request).db.tx() as s:
        rules = repo.Rules(s, c.id)
        changed = sum(rules.apply(t) for t in _uncategorised(s, c.id)) if rules else 0
        s.flush()
        if changed:
            _record(s, "rules.applied", c, changed)
        return Applied(changed=changed)
