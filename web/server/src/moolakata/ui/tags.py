"""A user's tags (requirements S2.6): listed for their forms, and made, renamed or deleted as
records of the save (`Tag`), a rename reaching every transaction, receipt and rule that
carries it."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import false, select

from .. import activity, clock, tags
from ..errors import Problem, refuse
from ..store.entities.accounts import Tag
from . import save
from .conventions import ExactRoute, Model
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["tags"])


class TagOut(Model):
    id: str
    name: str
    version: int


class TagRecord(Model):
    """A tag as a draft saves it: its name, lower case, once its owner's."""

    name: str


def tag_out(t: Tag) -> TagOut:
    return TagOut(id=t.id, name=t.name, version=t.version)


@router.get("/tags", response_model=list[TagOut])
def list_tags(request: Request, c: Caller = Depends(caller)):
    """The caller's own tags, by name."""
    with server(request).db.read(user=c.id) as s:
        rows = s.scalars(
            select(Tag).where(Tag.ownerId == c.id, Tag.deleted == false()).order_by(Tag.name)
        )
        return [tag_out(t) for t in rows]


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
