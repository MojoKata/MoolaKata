"""Activity (requirements S10.8): the changes worth showing, each naming who made it and what
it is about. Entries name fields and counts, never amounts (R3.8)."""

import json

from sqlalchemy.orm import Session

from . import ids
from .store.entities.core import Activity


def record(
    s: Session,
    kind: str,
    *,
    actor: str | None,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    owner: str | None = None,
    for_admins: bool = False,
    via: str | None = None,
    detail: dict | None = None,
) -> Activity:
    entry = Activity(
        id=ids.new_id("Actv"),
        kind=kind,
        actorId=actor,
        via=via,
        subjectKind=subject_kind,
        subjectId=subject_id,
        ownerId=owner,
        forAdmins=for_admins,
        detail=json.dumps(detail or {}, sort_keys=True),
    )
    s.add(entry)
    return entry


def about_link(link_id: str) -> dict:
    """What a link's entry is about: that link, named as its server, for admins (S11.8)."""
    return {"subject_kind": "link", "subject_id": link_id, "for_admins": True}
