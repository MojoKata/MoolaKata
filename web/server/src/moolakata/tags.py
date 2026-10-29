"""Tags (requirements S2.6): a user's own, each a record (`Tag`) its transactions, receipts and
the tags their rules set refer to by id, so a rename reaches them all. A tag is lower case,
once an owner; who sees one is its owner alone (S10.4: annotations are the user's own)."""

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from . import clock, ids
from .errors import refuse
from .store.entities.accounts import RuleTag, Tag, TransactionTag
from .store.entities.receipts import ReceiptTag

MAX_LENGTH = 40

# What each kind of record holds its tags in: the link's entity and the field naming it.
LINKS = {
    "transaction": (TransactionTag, "transactionId"),
    "receipt": (ReceiptTag, "receiptId"),
    "rule": (RuleTag, "ruleId"),
}


def clean(name: str) -> str:
    """A tag's name as kept: trimmed, lower case, checked."""
    out = (name or "").strip().lower()
    if not out or len(out) > MAX_LENGTH or "," in out:
        raise refuse("name", "tag-invalid", "A tag of up to 40 characters, without a comma.")
    return out


def named(s: Session, owner_id: str, name: str) -> Tag | None:
    """The owner's live tag of this name, if there is one."""
    return s.scalars(
        select(Tag).where(Tag.ownerId == owner_id, Tag.name == name, Tag.deleted == false())
    ).first()


def make(s: Session, owner_id: str, name: str, tag_id: str | None = None) -> Tag:
    """The owner's tag of this name, made when they have none."""
    name = clean(name)
    have = named(s, owner_id, name)
    if have is not None:
        return have
    tag = Tag(id=tag_id or ids.new_id("Tag"), ownerId=owner_id, name=name)
    s.add(tag)
    s.flush()
    return tag


def owned(s: Session, owner_id: str, tag_ids: list[str], field: str = "tagIds") -> list[Tag]:
    """The tags named, each the owner's own and live; refused otherwise."""
    found = {
        t.id: t
        for t in s.scalars(
            select(Tag).where(Tag.id.in_(tag_ids), Tag.ownerId == owner_id, Tag.deleted == false())
        )
    }
    if any(i not in found for i in tag_ids):
        raise refuse(field, "tag-unknown", "Tags of your own.")
    return [found[i] for i in tag_ids]


def of(s: Session, kind: str, owner_id: str, item_ids: list[str]) -> dict[str, list[Tag]]:
    """The owner's tags on each item of a kind, by name."""
    entity, key = LINKS[kind]
    out: dict[str, list[Tag]] = {}
    if not item_ids:
        return out
    rows = s.execute(
        select(getattr(entity, key), Tag)
        .join(Tag, Tag.id == entity.tagId)
        .where(
            getattr(entity, key).in_(item_ids),
            entity.deleted == false(),
            Tag.ownerId == owner_id,
            Tag.deleted == false(),
        )
        .order_by(Tag.name)
    )
    for item_id, tag in rows:
        out.setdefault(item_id, []).append(tag)
    return out


def ids_of(s: Session, kind: str, owner_id: str, item_id: str) -> list[str]:
    return [t.id for t in of(s, kind, owner_id, [item_id]).get(item_id, [])]


def set_on(s: Session, kind: str, item_id: str, owner_id: str, tag_ids: list[str], by: str):
    """The owner's tags on the item made `tag_ids`; another's tags on it stay theirs."""
    entity, key = LINKS[kind]
    wanted = set(tag_ids)
    current = {
        row.tagId: row
        for row, _ in s.execute(
            select(entity, Tag)
            .join(Tag, Tag.id == entity.tagId)
            .where(getattr(entity, key) == item_id, Tag.ownerId == owner_id)
        )
    }
    now = clock.now()
    for tag_id in wanted:
        row = current.get(tag_id)
        if row is None:
            s.add(entity(**{key: item_id, "tagId": tag_id, "createdAt": now}))
        elif row.deleted:
            row.restore()
    for tag_id, row in current.items():
        if tag_id not in wanted and not row.deleted:
            row.mark_deleted(by, now)


def add_on(s: Session, kind: str, item_id: str, tag_id: str) -> bool:
    """One tag put on the item; whether it wasn't there."""
    entity, key = LINKS[kind]
    row = s.scalars(
        select(entity).where(getattr(entity, key) == item_id, entity.tagId == tag_id)
    ).first()
    if row is not None and not row.deleted:
        return False
    if row is not None:
        row.restore()
    else:
        s.add(entity(**{key: item_id, "tagId": tag_id, "createdAt": clock.now()}))
    return True


def dropped_with(s: Session, tag: Tag, by: str) -> None:
    """A tag deleted takes itself off everything that carried it."""
    now = clock.now()
    for entity, _ in LINKS.values():
        for row in s.scalars(
            select(entity).where(entity.tagId == tag.id, entity.deleted == false())
        ):
            row.mark_deleted(by, now)
    tag.mark_deleted(by, now)
