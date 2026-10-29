"""Finding a record by the keys it is unique on (docs/schema.md §4.3): the live one, or else
the latest deleted one, for a change that brings it back."""

from sqlalchemy import select
from sqlalchemy.orm import Session


def by_key(s: Session, entity, **keys):
    """The record whose fields are `keys`: live first, then the latest deleted one."""
    q = select(entity).where(*(getattr(entity, k) == v for k, v in keys.items()))
    return s.scalars(q.order_by(entity.deletedAt.is_not(None), entity.deletedAt.desc())).first()
