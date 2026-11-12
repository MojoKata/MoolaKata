"""Categories (requirements S7.2): the household's one tree, which every user reads. Made, renamed,
changed and deleted through the save (S13.8.11) by the rules of S7.2.3; merged by an admin
through their own route (S7.2.4), in one transaction. Each change goes to Activity, for every
user (S10.8), and the live stream tells every page (S12.6)."""

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import false, select

from .. import activity
from .. import categories as cats
from ..errors import Problem, refuse
from ..store import scoping
from ..store.entities.accounts import Category
from ..store.entities.budgets import Budget, BudgetLine
from ..store.entities.users import User
from . import save
from .conventions import ExactRoute, Model, if_match
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["categories"])

SUBJECT = "category"


class Allowed(Model):
    """What the reader may do with a category now (S7.2.3)."""

    rename: bool
    change: bool  # its parent, kind and tax tag
    delete: bool
    merge: bool


class CategoryOut(Model):
    id: str
    name: str
    kind: str
    parentId: str | None
    taxTag: str | None
    path: str
    keepReceiptsYears: int | None  # its own; none: its parent's, or for ever (S14.10.1.1)
    shipped: bool
    serverNamed: bool  # a shipped one the server counts in by its own rules: it stays
    createdById: str | None
    createdByName: str | None  # the maker's name, as the owner's on a budget's row
    inUse: bool  # something names it: a transaction, split, rule, plan line, move, loan, child
    allowed: Allowed
    version: int


class NewCategory(Model):
    name: str
    kind: str
    parentId: str | None = None
    taxTag: str | None = None


class CategoryRecord(NewCategory):
    """A category as a draft saves it (S2.5): its name, kind, parent and tax tag, and how long
    receipts in it are kept, an admin's, since it decides what file pruning may remove
    (S14.10.1.1)."""

    keepReceiptsYears: int | None = None


def _used(s, ids) -> set[str]:
    # Nothing it reads changes the user's records, so they are left as read (no expiring).
    why = "categories: whether anything names them"  # pragma: no mutate
    with scoping.as_server(s, why, expire=False) as srv:  # pragma: no mutate
        return cats.used(srv, ids)


def _allowed(c: Caller, cat: Category, in_use: bool) -> Allowed:
    maker = cat.createdById == c.id and not cat.builtIn
    fixed = cats.server_named(cat)
    return Allowed(
        rename=True,
        change=c.admin or (maker and not in_use),
        delete=not fixed and not in_use and (c.admin or maker),
        merge=c.admin and not fixed,
    )


def _names(s) -> dict[str, str]:
    return {u.id: u.displayName for u in s.scalars(select(User))}


def _out(
    c: Caller, cat: Category, paths: dict[str, str], in_use: bool, names: dict[str, str]
) -> CategoryOut:
    return CategoryOut(
        id=cat.id,
        name=cat.name,
        kind=cat.kind,
        parentId=cat.parentId,
        taxTag=cat.taxTag,
        path=paths[cat.id],
        keepReceiptsYears=cat.keepReceiptsYears,
        shipped=cat.builtIn is not None,
        serverNamed=cats.server_named(cat),
        createdById=cat.createdById,
        createdByName=names.get(cat.createdById),
        inUse=in_use,
        allowed=_allowed(c, cat, in_use),
        version=cat.version,
    )


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        every = cats.live(s)
        paths = cats.paths(every)
        used = _used(s, [x.id for x in every])
        names = _names(s)
        return sorted(
            (_out(c, x, paths, x.id in used, names) for x in every), key=lambda x: x.path.lower()
        )


def _read(ctx, cat_id: str) -> CategoryOut:
    cat = ctx.s.get(Category, cat_id)
    paths = cats.paths(cats.live(ctx.s))
    return _out(ctx.caller, cat, paths, cat.id in _used(ctx.s, [cat.id]), _names(ctx.s))


# ---------- the save's kind ----------


def _name(s, raw: str, parent_id: str | None, but: str | None = None) -> str:
    name = raw.strip()
    if not name or len(name) > cats.NAME_MAX or "›" in name:
        raise refuse("name", "name-invalid", "Enter a name of up to 60 characters, without ›.")
    if cats.name_taken(s, name, parent_id, but):
        where = "at the top level" if parent_id is None else "beside it"
        raise refuse("name", "name-taken", f"There is a category with this name {where} already.")
    return name


def _parent(s, parent_id: str | None, cat: Category | None = None) -> None:
    if parent_id is None:
        return
    parent = s.get(Category, parent_id)
    if parent is None or parent.deleted or parent.parentId or (cat and parent.id == cat.id):
        raise refuse(
            "parentId", "parent-invalid", "Categories have two levels: choose a top-level one."
        )
    if cat is not None and cats.children(s, cat.id):
        raise refuse(
            "parentId",
            "parent-invalid",
            "It has categories of its own, and categories have two levels: it stays at the top.",
        )


def _kind_and_tag(kind: str, tag: str | None) -> None:
    if kind not in cats.KINDS:
        raise refuse("kind", "kind-invalid", "Expense, income, savings or transfer.")
    if tag is not None and tag not in cats.TAX_TAGS:
        raise refuse("taxTag", "tax-tag-invalid", "Choose one of the tax tags, or none.")


def _record(ctx, kind: str, cat: Category, **detail) -> None:
    activity.record(
        ctx.s,
        f"category.{kind}",
        actor=ctx.caller.id,
        subject_kind=SUBJECT,
        subject_id=cat.id,
        detail=detail,
    )
    srv = server(ctx.request)
    # Once per save, however many categories it changes: the key only says which work it is.
    tell = lambda: srv.events.publish("category")  # noqa: E731
    ctx.after("category", tell)  # pragma: no mutate


def _category_create(ctx, record_id: str, body: CategoryRecord) -> None:
    s = ctx.s
    _kind_and_tag(body.kind, body.taxTag)
    _parent(s, body.parentId)
    name = _name(s, body.name, body.parentId)
    if body.keepReceiptsYears is not None:
        _retention(ctx, body.keepReceiptsYears)
    cat = Category(
        id=record_id,
        name=name,
        kind=body.kind,
        parentId=body.parentId,
        taxTag=body.taxTag,
        createdById=ctx.caller.id,
        keepReceiptsYears=body.keepReceiptsYears,
    )
    s.add(cat)
    s.flush()
    _record(ctx, "added", cat, name=cats.paths(cats.live(s))[cat.id])


def _category_editable(ctx, record_id: str) -> Category:
    cat = ctx.s.get(Category, record_id)
    if cat is None or cat.deleted:
        raise Problem(404, "not-found", "Not found")
    return cat


def _category_current(ctx, cat: Category) -> dict:
    return {f: getattr(cat, f) for f in CategoryRecord.model_fields}


def _retention(ctx, years: int | None) -> None:
    if not ctx.caller.admin:
        raise refuse("keepReceiptsYears", "admins-only", "Only admins can do this.", 403)
    if years is not None and not 1 <= years <= 100:
        raise refuse("keepReceiptsYears", "years-invalid", "A whole number of years from 1.")


def _why_not(ctx, cat: Category) -> str:
    if cat.builtIn:
        return "Only admins change a shipped category's parent, kind or tax tag."
    if cat.createdById != ctx.caller.id:
        return "Only admins change another user's category's parent, kind or tax tag."
    return "It's in use now: only admins change its parent, kind or tax tag."


def _years(n: int | None) -> str:
    return "its parent's, or for ever" if n is None else f"{n} year{'' if n == 1 else 's'}"


def _category_update(ctx, cat: Category, body: CategoryRecord) -> None:
    s = ctx.s
    before = {f: getattr(cat, f) for f in CategoryRecord.model_fields}
    changed = [f for f in CategoryRecord.model_fields if getattr(body, f) != before[f]]
    if not changed:
        return
    paths = cats.paths(cats.live(s))
    was = paths[cat.id]
    structure = [f for f in ("parentId", "kind", "taxTag") if f in changed]
    if structure:
        if "kind" in structure and cats.server_named(cat):
            raise refuse(
                "kind",
                "category-kept",
                "MoolaKata counts in this category by its own rules: its kind stays.",
            )
        maker = cat.createdById == ctx.caller.id and not cat.builtIn
        if not ctx.caller.admin and not (maker and cat.id not in _used(s, [cat.id])):
            raise refuse(structure[0], "admins-only", _why_not(ctx, cat), 403)
        _kind_and_tag(body.kind, body.taxTag)
        if "parentId" in structure:
            _parent(s, body.parentId, cat)
    if "keepReceiptsYears" in changed:
        _retention(ctx, body.keepReceiptsYears)
    if "name" in changed or "parentId" in changed:
        name = _name(s, body.name, body.parentId, cat.id)
    else:
        name = cat.name
    cat.name, cat.parentId, cat.kind = name, body.parentId, body.kind
    cat.taxTag, cat.keepReceiptsYears = body.taxTag, body.keepReceiptsYears
    s.flush()
    now = cats.paths(cats.live(s))[cat.id]
    if name != before["name"]:
        _record(ctx, "renamed", cat, **{"from": was, "to": now})
    if "parentId" in changed:
        top = "the top level"
        _record(
            ctx,
            "moved",
            cat,
            name=cat.name,
            **{
                "from": paths[before["parentId"]] if before["parentId"] else top,
                "to": paths[body.parentId] if body.parentId else top,
            },
        )
    if "kind" in changed:
        _record(ctx, "kind", cat, name=now, **{"from": before["kind"], "to": body.kind})
    if "taxTag" in changed:
        _record(
            ctx,
            "tax-tag",
            cat,
            name=now,
            **{"from": before["taxTag"] or "none", "to": body.taxTag or "none"},
        )
    if "keepReceiptsYears" in changed:
        _record(
            ctx,
            "retention",
            cat,
            name=now,
            **{"from": _years(before["keepReceiptsYears"]), "to": _years(body.keepReceiptsYears)},
        )


def _category_delete(ctx, cat: Category) -> None:
    s = ctx.s
    if cats.server_named(cat):
        raise refuse(
            None, "category-kept", "MoolaKata counts in this category by its own rules: it stays."
        )
    if cat.id in _used(s, [cat.id]):
        raise refuse(
            None, "category-in-use", "It's in use: an admin can merge it into another category."
        )
    maker = cat.createdById == ctx.caller.id and not cat.builtIn
    if not ctx.caller.admin and not maker:
        why = "a shipped category" if cat.builtIn else "another user's category"
        raise refuse(None, "admins-only", f"Only admins delete {why}.", 403)
    name = cats.paths(cats.live(s))[cat.id]
    cat.mark_deleted(ctx.caller.id)
    _record(ctx, "deleted", cat, name=name)


save.register(
    save.Kind(
        prefix="Cat",
        entity=Category,
        fields=CategoryRecord,
        create=_category_create,
        editable=_category_editable,
        current=_category_current,
        update=_category_update,
        delete=_category_delete,
        read=_read,
    )
)


# ---------- a merge (S7.2.4) ----------


class MergeIn(Model):
    into: str
    # Each of the category's own categories: itself (it moves under `into`, as it is) or one
    # of `into`'s categories (it merges into that one).
    children: dict[str, str] = Field(default_factory=dict)


class MergePreview(Model):
    """The budgets the reader sees whose plans the merge changes."""

    budgets: list[str]


class MergeOut(Model):
    into: CategoryOut


def _merge_plan(s, c: Caller, cat_id: str, body: MergeIn) -> cats.Plan:
    if not c.admin:
        raise refuse(None, "admins-only", "Only admins merge categories.", 403)
    source = s.get(Category, cat_id)
    if source is None or source.deleted:
        raise Problem(404, "not-found", "Not found")
    target = s.get(Category, body.into)
    if target is None or target.deleted:
        raise refuse("into", "category-unknown", "Choose a category.")
    try:
        return cats.plan(s, source, target, body.children)
    except cats.Refused as e:
        raise refuse(e.field, e.code, e.message) from None


def _visible_budgets(s, budget_ids: set[str]) -> list[str]:
    """The names of those the reader sees: the user's session reads no other (schema.md §7.6),
    and says nothing of the rest (S13.8.10)."""
    rows = s.scalars(select(Budget).where(Budget.id.in_(budget_ids)))
    return sorted((b.name for b in rows), key=str.lower)


@router.post("/categories/{cat_id}/merge-preview", response_model=MergePreview)
def merge_preview(cat_id: str, body: MergeIn, request: Request, c: Caller = Depends(caller)):
    """What a merge would change that the reader can see, checked as the merge would be."""
    with server(request).db.read(user=c.id) as s:
        p = _merge_plan(s, c, cat_id, body)
        gone = [x.id for x, _ in p.pairs]
        with scoping.as_server(s, "categories: the budgets a merge changes", expire=False) as srv:
            touched = set(
                srv.scalars(
                    select(BudgetLine.budgetId)
                    .where(BudgetLine.categoryId.in_(gone), BudgetLine.deleted == false())
                    .distinct()
                )
            )
        return MergePreview(budgets=_visible_budgets(s, touched))


@router.post("/categories/{cat_id}/merge", response_model=MergeOut)
def merge(
    cat_id: str,
    body: MergeIn,
    request: Request,
    c: Caller = Depends(caller),
    version: int = Depends(if_match),
):
    """An admin's merge (S7.2.4): one transaction, every use moved, in the request."""
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        p = _merge_plan(s, c, cat_id, body)
        if p.source.version != version:
            raise Problem(412, "stale", "It changed since you read it: reload and try again.")
        paths = cats.paths(cats.live(s))
        detail = {
            "name": paths[p.source.id],
            "to": paths[p.target.id],
            "children": [{"name": x.name, "into": paths[into.id]} for x, into in p.pairs[1:]]
            + [{"name": x.name, "into": None} for x in p.moved],
        }
        source_id, target_id = p.source.id, p.target.id
        with scoping.as_server(s, "categories: an admin's merge moves every use") as as_srv:
            again = cats.plan(
                as_srv,
                as_srv.get(Category, source_id),
                as_srv.get(Category, target_id),
                body.children,
            )
            cats.apply(as_srv, again, c.id)
        activity.record(
            s,
            "category.merged",
            actor=c.id,
            subject_kind=SUBJECT,
            subject_id=target_id,
            detail=detail,
        )
        s.flush()
        target = s.get(Category, target_id)
        paths = cats.paths(cats.live(s))
        out = _out(c, target, paths, target_id in _used(s, [target_id]), _names(s))
    srv.events.publish("category", {})
    return MergeOut(into=out)
