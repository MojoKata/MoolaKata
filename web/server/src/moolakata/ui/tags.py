"""A user's tags (requirements S2.6): listed for their forms, and made, renamed or deleted as
records of the save (`Tag`), a rename reaching every transaction, receipt and rule that
carries it."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import false, func, select

from .. import activity, clock, tags
from ..errors import Problem, refuse
from ..store import views
from ..store.entities.accounts import Tag
from ..store.tables.accounts import Rule, RuleTags, Transaction, TransactionTags
from ..store.tables.receipts import Receipt, ReceiptTags
from . import save
from .conventions import ExactRoute, Model
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["tags"])


class TagOut(Model):
    id: str
    name: str
    version: int
    # How many of the records the caller sees carry it: transactions, receipts and rules. A
    # tag box lists the most used first (S12.18.12).
    uses: int = 0


class TagRecord(Model):
    """A tag as a draft saves it: its name, lower case, once its owner's."""

    name: str


def tag_out(t: Tag, uses: int = 0) -> TagOut:
    return TagOut(id=t.id, name=t.name, version=t.version, uses=uses)


# What carries a tag: each record table, its pairs with tags, and the key naming the record.
CARRIERS = (
    (Transaction, TransactionTags, "transactionId"),
    (Receipt, ReceiptTags, "receiptId"),
    (Rule, RuleTags, "ruleId"),
)


def uses(s) -> dict[str, int]:
    """How many live records carry each tag, counting only records the session's user reads:
    each record table is joined, so its access view scopes the count (schema.md §7.6)."""
    counts: dict[str, int] = {}
    for table, pair, key in CARRIERS:
        q = (
            select(pair.c.tagId, func.count())
            .join(table, table.c.id == pair.c[key])
            .where(pair.c.deleted == false())
            .group_by(pair.c.tagId)
        )
        if views.parents(table):
            view = views.view_table(table)
            q = q.join(view, view.c.id == table.c.id).where(view.c.effectiveDeleted == false())
        else:
            q = q.where(table.c.deleted == false())
        for tag_id, n in s.execute(q):
            counts[tag_id] = counts.get(tag_id, 0) + n
    return counts


@router.get("/tags", response_model=list[TagOut])
def list_tags(request: Request, c: Caller = Depends(caller)):
    """The caller's own tags, by name, each with how many records carry it."""
    with server(request).db.read(user=c.id) as s:
        rows = list(
            s.scalars(
                select(Tag).where(Tag.ownerId == c.id, Tag.deleted == false()).order_by(Tag.name)
            )
        )
        n = uses(s)
        return [tag_out(t, n.get(t.id, 0)) for t in rows]


def _create(ctx, record_id: str, body: TagRecord) -> None:
    name = tags.clean(body.name)
    if tags.named(ctx.s, ctx.caller.id, name) is not None:
        raise refuse("name", "tag-taken", f"You have a tag {name}.", 409)
    tags.make(ctx.s, ctx.caller.id, name, record_id)


def _editable(ctx, record_id: str) -> Tag:
    t = ctx.s.get(Tag, record_id)
    if t is None or t.deleted or t.ownerId != ctx.caller.id:
        raise Problem(404, "not-found", "Not found")
    return t


def _update(ctx, t: Tag, body: TagRecord) -> None:
    """Renamed: everything carrying it shows the new name."""
    name = tags.clean(body.name)
    other = tags.named(ctx.s, ctx.caller.id, name)
    if other is not None and other.id != t.id:
        raise refuse("name", "tag-taken", f"You have a tag {name}.", 409)
    if name != t.name:
        t.name, t.updatedAt = name, clock.now()
        activity.record(ctx.s, "tag.renamed", actor=ctx.caller.id, owner=ctx.caller.id)


def _delete(ctx, t: Tag) -> None:
    tags.dropped_with(ctx.s, t, ctx.caller.id)


save.register(
    save.Kind(
        prefix="Tag",
        entity=Tag,
        fields=TagRecord,
        create=_create,
        editable=_editable,
        current=lambda ctx, t: {"name": t.name},
        update=_update,
        delete=_delete,
        read=lambda ctx, record_id: tag_out(ctx.s.get(Tag, record_id)),
    )
)
