"""People and their relationships (requirements S10.10): every user is a person, people are the
household's unless private, one person is added once, and dated relationships say who is
married to whom on a given day, for wash sales (S3.8) and joint tax books (S8.14.1)."""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from .. import access, clock, ids
from ..errors import FieldError, Problem
from ..store import scoping
from ..store.entities.education import Person, Relationship
from ..store.entities.users import User

SEXES = ("male", "female")
RELATIONS = ("spouse", "couple", "child", "friend", "colleague", "family")


def make(
    s: Session,
    name: str,
    sex: str,
    owner_id: str | None = None,
    birth_year: int | None = None,
) -> Person:
    """A new person; a user's own is made with the user, before it (User.personId)."""
    if sex not in SEXES:
        raise Problem(
            422,
            "sex-invalid",
            "Female or male.",
            [FieldError("sex", "sex-invalid", "Female or male.")],
        )
    p = Person(
        id=ids.new_id("Persn"), name=name.strip(), sex=sex, ownerId=owner_id, birthYear=birth_year
    )
    s.add(p)
    s.flush()
    return p


def for_new_user(s: Session, name: str, sex: str, by: str | None = None) -> Person:
    """The person a new user is: one already here under that name who isn't a user yet (a
    child on someone's gift list who now signs in), else a new one (S10.10.1, S10.10.3)."""
    taken = set(s.scalars(select(User.personId).where(User.deleted == false())))
    free = [p for p in same_name(s, name) if p.id not in taken]
    if len(free) == 1:
        p = s.get(Person, free[0].id)
        p.sex, p.private = sex, False
        return p
    return make(s, name, sex, by)


def _bare(s: Session, person_id: str) -> bool:
    """A person nothing here names yet: no gift plan, gift or relationship."""
    from ..store.entities.education import GiftPerson, GiftPlan

    return not any(
        s.scalars(q.limit(1)).first()
        for q in (
            select(GiftPlan.id).where(GiftPlan.personId == person_id, GiftPlan.deleted == false()),
            select(GiftPerson.giftId).where(
                GiftPerson.personId == person_id, GiftPerson.deleted == false()
            ),
            select(Relationship.id).where(
                or_(Relationship.person1Id == person_id, Relationship.person2Id == person_id),
                Relationship.deleted == false(),
            ),
        )
    )


def may_join(s: Session, user_id: str, p: Person) -> list[User]:
    """The remote users who may be this person (S10.10.1): of the same name, with a person of
    their own that nothing names yet; offered to someone who may change this one, a person
    who isn't a user."""
    if p.deleted or user_of(s, p.id) is not None or level(s, user_id, p) != "owner":
        return []
    out = []
    for u in s.scalars(
        select(User).where(
            User.linkId.is_not(None),
            User.deleted == false(),
            func.lower(User.displayName) == p.name.lower(),
        )
    ):
        own = s.get(Person, u.personId)
        if own is not None and own.id != p.id and own.ownerId is None and _bare(s, own.id):
            out.append(u)
    return out


def join(s: Session, user_id: str, p: Person, remote: User) -> None:
    """A remote user joined to a person here, by someone who may change that person; the
    person stays as private as it was, and the remote user's own person goes."""
    if remote not in may_join(s, user_id, p):
        raise Problem(409, "cannot-join", "That user can't be joined to this person.")
    # The remote user's record and its own person are the link's, not the joiner's to
    # change: the server joins them, for one who may change the person.
    with scoping.as_server(s, "a linked server's user joined to a person") as srv:
        r = srv.get(User, remote.id)
        own = srv.get(Person, r.personId)
        r.personId = p.id
        srv.flush()
        own.mark_deleted(user_id)


def of_user(s: Session, user_id: str) -> Person | None:
    u = s.get(User, user_id)
    return s.get(Person, u.personId) if u is not None else None


def user_of(s: Session, person_id: str) -> User | None:
    return s.scalars(
        select(User).where(User.personId == person_id, User.deleted == false())
    ).first()


def users_by_person(s: Session) -> dict[str, User]:
    return {u.personId: u for u in s.scalars(select(User).where(User.deleted == false()))}


def birth_year(s: Session, user_id: str) -> int | None:
    p = of_user(s, user_id)
    return p.birthYear if p else None


# ---- Who sees and changes a person (S10.10.2) ----


def is_admin(s: Session, user_id: str) -> bool:
    from ..auth.users import admin_ids

    return user_id in admin_ids(s)


def level(s: Session, user_id: str, p: Person, r: access.Reach | None = None) -> str | None:
    """'owner' for those who may change it, 'read' for the rest who see it, else None."""
    if p.deleted:
        return None
    u = s.get(User, user_id)
    if u is None:
        return None
    # A linked server's user sees a person only through a share, of them or of a gift plan
    # for them, read only (S10.3.3).
    if u.linkId is None:
        if p.id == u.personId or is_admin(s, user_id):
            return "owner"
        # Once they are a user here, a person is changed by that user (and admins) alone;
        # until then, and for a linked server's user, who never signs in here, by whoever
        # added them (S10.10.2).
        mine = user_of(s, p.id)
        if mine is not None and mine.id == user_id:
            return "owner"
        if (mine is None or mine.linkId is not None) and p.ownerId == user_id:
            return "owner"
        if not p.private:
            return "read"
    r = r or access.reach(s, user_id)
    if r.levels.get(("person", p.id)):
        return "read"
    # Holding a gift plan for them shows them too.
    from ..store.entities.education import GiftPlan

    plans = s.scalars(
        select(GiftPlan.id).where(GiftPlan.personId == p.id, GiftPlan.deleted == false())
    ).all()
    if any(r.levels.get(("gift-plan", i)) for i in plans):
        return "read"
    return None


def visible(s: Session, user_id: str) -> list[tuple[Person, str]]:
    """The people the user reads (PersonAccess), by name: *owner* for those they may change,
    *read* for the rest."""
    return [
        (p, "owner" if perms.writable else "read")
        for p, perms in access.listing(s, Person, user_id, order_by=Person.name)
    ]


def readable(s: Session, user_id: str, person_id: str) -> bool:
    return access.perms(s, Person, person_id, user_id) is not None


def changeable(s: Session, user_id: str, person_id: str) -> bool:
    p = access.perms(s, Person, person_id, user_id)
    return p is not None and p.writable


def get(s: Session, user_id: str, person_id: str, need: str = "read") -> Person:
    perms = access.perms(s, Person, person_id, user_id)
    p = s.get(Person, person_id) if perms is not None else None
    if p is None:
        raise Problem(404, "not-found", "Not found")
    if need != "read" and not perms.writable:
        raise Problem(
            403,
            "person-read-only",
            "Only the person, whoever added them, or an admin changes them.",
        )
    return p


def change(s: Session, p: Person, values: dict) -> None:
    """A person's own fields; a user's display name is their person's name (S10.10.1)."""
    for k, v in values.items():
        setattr(p, k, v)
    p.updatedAt = clock.now()
    if "name" not in values:
        return
    with s.no_autoflush:  # one save of the user, with whatever else changed on it
        u = user_of(s, p.id)
    if u is not None:
        u.displayName = p.name


# ---- One person, once (S10.10.3) ----


@dataclass(frozen=True)
class Named:
    """A person as the one-person-once check sees them, read as the server: the check names
    one the user may not read (S10.10.3)."""

    id: str
    name: str
    birthYear: int | None
    private: bool
    ownerId: str | None
    creator: str | None  # who added them, by name


def same_name(s: Session, name: str, exclude: str | None = None) -> list[Named]:
    q = (
        select(Person.id, Person.name, Person.birthYear, Person.private, Person.ownerId)
        .add_columns(select(User.displayName).where(User.id == Person.ownerId).scalar_subquery())
        .where(Person.deletedAt.is_(None), func.lower(Person.name) == name.strip().lower())
    )
    if exclude:
        q = q.where(Person.id != exclude)
    return [Named(*r) for r in s.execute(scoping.unscoped(q, "one person, once"))]


def told_apart(a: int | None, b: int | None) -> bool:
    """A different person with the same name: both have birth years, and they differ."""
    return a is not None and b is not None and a != b


def clash(s: Session, name: str, birth_year: int | None, exclude: str | None = None):
    """The person already here under this name that a new one can't be told apart from."""
    for p in same_name(s, name, exclude):
        if not told_apart(p.birthYear, birth_year):
            return p
    return None


# ---- Relationships (S10.10.4) ----


def live_relationships(s: Session, person_ids: list[str] | None = None) -> list[Relationship]:
    q = select(Relationship).where(Relationship.deleted == false())
    if person_ids is not None:
        q = q.where(
            or_(Relationship.person1Id.in_(person_ids), Relationship.person2Id.in_(person_ids))
        )
    return list(s.scalars(q))


def ended_on(s: Session, r: Relationship, deaths: dict[str, dt.date] | None = None):
    """When a relationship ends: its own end date, or for a marriage the first death."""
    ends = [r.toDate] if r.toDate else []
    if r.relation in ("spouse", "couple"):
        if deaths is None:
            deaths = {
                p.id: p.diedOn
                for p in (s.get(Person, r.person1Id), s.get(Person, r.person2Id))
                if p is not None and p.diedOn
            }
        ends += [deaths[i] for i in (r.person1Id, r.person2Id) if i in deaths]
    return min(ends) if ends else None


def holds_on(s: Session, r: Relationship, day: dt.date, deaths=None) -> bool:
    """Whether a relationship holds on a day: from its start, up to (not on) its end."""
    if r.fromDate and day < r.fromDate:
        return False
    end = ended_on(s, r, deaths)
    return end is None or day < end


def other(r: Relationship, person_id: str) -> str:
    return r.person2Id if r.person1Id == person_id else r.person1Id


def confirmed(r: Relationship) -> bool:
    """A marriage both people have confirmed (S10.10.4); other relations need no confirming."""
    return r.relation != "spouse" or (r.confirmed1At is not None and r.confirmed2At is not None)


def may_confirm(s: Session, user_id: str, person_id: str) -> bool:
    """A spouse confirms their own side, from their own Profile; an admin confirms for a person
    who isn't a user."""
    me = of_user(s, user_id)
    if me is not None and me.id == person_id:
        return True
    u = user_of(s, person_id)
    return (u is None or u.linkId is not None) and is_admin(s, user_id)


def confirm(s: Session, user_id: str, r: Relationship, fresh: bool = False) -> bool:
    """The sides of a marriage this user may confirm, confirmed now; `fresh` (the marriage is new
    or changed) clears the others first. Whether either side changed."""
    if r.relation != "spouse":
        r.confirmed1At = r.confirmed2At = None
        return False
    if fresh:
        r.confirmed1At = r.confirmed2At = None
    now = clock.now()
    changed = False
    if r.confirmed1At is None and may_confirm(s, user_id, r.person1Id):
        r.confirmed1At, changed = now, True
    if r.confirmed2At is None and may_confirm(s, user_id, r.person2Id):
        r.confirmed2At, changed = now, True
    return changed


def spouse_on(s: Session, person_id: str, day: dt.date, confirmed_only: bool = False) -> str | None:
    for r in live_relationships(s, [person_id]):
        if r.relation == "spouse" and holds_on(s, r, day) and (confirmed(r) or not confirmed_only):
            return other(r, person_id)
    return None


def spouse_user_on(s: Session, user_id: str, day: dt.date) -> str | None:
    """The local user married to this one on a day, by a marriage both confirmed: for wash
    sales and tax books, which an unconfirmed marriage never reaches (S10.10.4)."""
    me = of_user(s, user_id)
    if me is None:
        return None
    sp = spouse_on(s, me.id, day, confirmed_only=True)
    u = user_of(s, sp) if sp else None
    return u.id if u is not None and u.linkId is None else None


def spouse_users_ever(s: Session, user_id: str) -> set[str]:
    """Every local user ever married to this one, by a marriage both confirmed."""
    me = of_user(s, user_id)
    if me is None:
        return set()
    out = set()
    for r in live_relationships(s, [me.id]):
        if r.relation == "spouse" and confirmed(r):
            u = user_of(s, other(r, me.id))
            if u is not None and u.linkId is None:
                out.add(u.id)
    return out


def joint_filers(s: Session, user_a: str, user_b: str, year: int) -> bool:
    """Spouses on the last day of the year, or married until one of them died in it, by a
    marriage both confirmed (S8.14.1)."""
    a, b = of_user(s, user_a), of_user(s, user_b)
    if a is None or b is None:
        return False
    for r in live_relationships(s, [a.id]):
        if r.relation != "spouse" or other(r, a.id) != b.id or not confirmed(r):
            continue
        if holds_on(s, r, dt.date(year, 12, 31)):
            return True
        death = min((d for d in (a.diedOn, b.diedOn) if d), default=None)
        if (
            death
            and death.year == year
            and (r.toDate is None or r.toDate >= death)
            and (r.fromDate is None or r.fromDate <= death)
        ):
            return True
    return False


def _ancestors(rels: list[Relationship], person_id: str) -> set[str]:
    parents: dict[str, set[str]] = {}
    for r in rels:
        if r.relation == "child":
            parents.setdefault(r.person2Id, set()).add(r.person1Id)
    seen: set[str] = set()
    todo = [person_id]
    while todo:
        for p in parents.get(todo.pop(), ()):
            if p not in seen:
                seen.add(p)
                todo.append(p)
    return seen


def check(s: Session, r: Relationship) -> None:
    """At most one spouse at a time, and no one their own ancestor (S10.10.4.1)."""
    errors: list[FieldError] = []
    if r.relation not in RELATIONS:
        errors.append(FieldError("relation", "relation-invalid", "One of the relations."))
    if r.person1Id == r.person2Id:
        errors.append(FieldError("person2Id", "same-person", "Two different people."))
    if r.fromDate and r.toDate and r.toDate < r.fromDate:
        errors.append(FieldError("toDate", "dates-invalid", "It ends after it begins."))
    if errors:
        raise Problem(422, errors[0].code, errors[0].message, errors)
    others = [x for x in live_relationships(s) if x.id != r.id]
    if r.relation == "child" and r.person2Id in _ancestors(others, r.person1Id):
        raise Problem(
            422,
            "ancestor-loop",
            "No one is their own ancestor.",
            [FieldError("person2Id", "ancestor-loop", "No one is their own ancestor.")],
        )
    if r.relation == "spouse":
        far = dt.date.max
        start, end = r.fromDate or dt.date.min, ended_on(s, r) or far
        for x in others:
            if x.relation != "spouse" or not (
                {x.person1Id, x.person2Id} & {r.person1Id, r.person2Id}
            ):
                continue
            xs, xe = x.fromDate or dt.date.min, ended_on(s, x) or far
            if start < xe and xs < end:
                raise Problem(
                    422,
                    "one-spouse",
                    "At most one spouse at a time.",
                    [FieldError("fromDate", "one-spouse", "At most one spouse at a time.")],
                )


def ordered(relation: str, a: str, b: str) -> tuple[str, str]:
    """A child runs parent to child; the rest are kept with the smaller id first."""
    return (a, b) if relation == "child" or a < b else (b, a)


def may_relate(s: Session, user_id: str, a: str, b: str) -> bool:
    """A user adds relationships they are in; an admin adds any."""
    me = of_user(s, user_id)
    return (me is not None and me.id in (a, b)) or is_admin(s, user_id)


def today() -> dt.date:
    return clock.today()
