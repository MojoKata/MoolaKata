"""Gifts (requirements S7.7, S7.8): each user's gift plans for the household's people, with
their occasions; what each user may see (their own plans and gifts, and plans shared with
them, but never the gifts for themselves); the occasions coming up with what is planned for
them; spending by person, occasion and year; and the gift-tax flag."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import access, people
from ..projections import taxtables
from ..store.entities.education import Gift, GiftPerson, GiftPlan, Occasion, Person
from ..store.entities.users import User
from . import holidays

ZERO = Decimal(0)
UPCOMING_DAYS = 60
STATUSES = ("idea", "planned", "bought", "given", "received")
SPENT = ("bought", "given")
NOT_YET = ("idea", "planned")


@dataclass
class Plan:
    """A gift plan the user can see, with its person and what the user holds of it."""

    plan: GiftPlan
    person: Person
    perms: access.Perms


def visible_plans(s: Session, user_id: str) -> list[Plan]:
    """The user's own gift plans and those shared with them, one per person: their own when
    they have one, else the shared one they may change, else any (GiftPlanAccess)."""
    best: dict[str, Plan] = {}
    for gp, perms in access.listing(s, GiftPlan, user_id):
        p = s.get(Person, gp.personId)
        if p is None or p.deleted:
            continue
        have = best.get(p.id)
        if have is None or _rank(perms) > _rank(have.perms):
            best[p.id] = Plan(gp, p, perms)
    return sorted(best.values(), key=lambda x: x.person.name)


def _rank(perms: access.Perms) -> tuple[bool, bool]:
    return perms.mine, perms.writable


def plan_for(s: Session, user_id: str, person_id: str, need: str = "read") -> Plan:
    from ..errors import Problem

    found = next((x for x in visible_plans(s, user_id) if x.person.id == person_id), None)
    if found is None:
        raise Problem(404, "not-found", "Not found")
    if need != "read" and not found.perms.writable:
        raise Problem(403, "read-only", "This gift plan is shared with you to read.")
    return found


def plan_by_id(s: Session, user_id: str, plan_id: str, need: str = "read") -> Plan:
    """`need`: *read*, *write*, or a permission's name (deleting it: *deletable*)."""
    from ..errors import Problem

    perms = access.perms(s, GiftPlan, plan_id, user_id)
    gp = s.get(GiftPlan, plan_id) if perms is not None else None
    p = s.get(Person, gp.personId) if gp else None
    if gp is None or p is None or p.deleted:
        raise Problem(404, "not-found", "Not found")
    want = {"read": None, "write": "writable"}.get(need, need)
    if want is not None and not getattr(perms, want):
        raise Problem(403, "read-only", "This gift plan is shared with you to read.")
    return Plan(gp, p, perms)


def occasions_of(s: Session, plan_ids: list[str]) -> dict[str, list[Occasion]]:
    out: dict[str, list[Occasion]] = {i: [] for i in plan_ids}
    if not plan_ids:
        return out
    for o in s.scalars(
        select(Occasion)
        .where(Occasion.giftPlanId.in_(plan_ids), Occasion.deleted == false())
        .order_by(Occasion.createdAt)
    ):
        out[o.giftPlanId].append(o)
    return out


def people_of_gifts(s: Session, gift_ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {i: [] for i in gift_ids}
    if not gift_ids:
        return out
    for gp in s.scalars(
        select(GiftPerson).where(GiftPerson.giftId.in_(gift_ids), GiftPerson.deleted == false())
    ):
        out[gp.giftId].append(gp.personId)
    return out


def readable(s: Session, user_id: str) -> list[tuple[Gift, list[str]]]:
    """The gifts the user reads, with their people (GiftAccess: their own, and those in the
    plans shared with them, never one for the user themselves until it is received)."""
    rows = [g for g, _ in access.listing(s, Gift, user_id)]
    whom = people_of_gifts(s, [g.id for g in rows])
    return [(g, whom[g.id]) for g in rows]


@dataclass
class Date:
    key: str  # birthday, wedding, holiday:<key> or occasion:<id>
    label: str
    date: dt.date
    budget: Decimal | None
    kind: str  # birthday, anniversary, holiday, custom
    turns: int | None = None  # a birthday's age, an anniversary's count


def _safe(year: int, month: int, day: int) -> dt.date:
    try:
        return dt.date(year, month, day)
    except ValueError:  # 29 February
        return dt.date(year, month, 28)


def wedding_of(s: Session, person_id: str) -> dt.date | None:
    """The start of the person's marriage, while it holds (S7.7.1)."""
    for r in people.live_relationships(s, [person_id]):
        if r.relation == "spouse" and r.fromDate and people.holds_on(s, r, people.today()):
            return r.fromDate
    return None


def dates_in(
    p: Person, occs: list[Occasion], year: int, wedding: dt.date | None = None
) -> list[Date]:
    """A person's dated occasions in a year: their birthday, their wedding anniversary, and
    the plan's own occasions."""
    out = []
    if p.birthMonth and p.birthDay and not p.diedOn:
        out.append(
            Date(
                "birthday",
                "Birthday",
                _safe(year, p.birthMonth, p.birthDay),
                None,
                "birthday",
                year - p.birthYear if p.birthYear else None,
            )
        )
    if wedding is not None and year > wedding.year:
        out.append(
            Date(
                "wedding",
                "Wedding anniversary",
                _safe(year, wedding.month, wedding.day),
                None,
                "anniversary",
                year - wedding.year,
            )
        )
    for o in occs:
        if o.kind == "holiday":
            day = holidays.date_of(o.holiday, year)
            if day is not None:
                key = f"holiday:{o.holiday}"
                out.append(Date(key, holidays.label(o.holiday), day, o.budget, "holiday"))
        else:
            label = o.name or ("Anniversary" if o.kind == "anniversary" else "Occasion")
            out.append(
                Date(
                    f"occasion:{o.id}",
                    label,
                    _safe(year, o.month, o.day),
                    o.budget,
                    o.kind,
                    year - o.year if o.year else None,
                )
            )
    return out


def label_of(key: str | None, occs: list[Occasion]) -> str:
    if not key:
        return "An idea"
    if key == "birthday":
        return "Birthday"
    if key == "wedding":
        return "Wedding anniversary"
    kind, _, ident = key.partition(":")
    if kind == "holiday" and ident in holidays.HOLIDAYS:
        return holidays.label(ident)
    o = next((x for x in occs if x.id == ident), None)
    return (o.name or "Anniversary") if o else "An occasion"


@dataclass
class Upcoming:
    person: Person
    date: Date
    days: int
    inLead: bool
    gifts: list[Gift] = field(default_factory=list)
    planned: Decimal = ZERO  # what the gifts for it cost so far


def upcoming(s: Session, user_id: str, today: dt.date, days: int = UPCOMING_DAYS) -> list[Upcoming]:
    """The dates in the user's gift plans in the next 60 days, each with the gifts for it
    (S7.7.3)."""
    me = s.get(User, user_id)
    plans = visible_plans(s, user_id)
    occs = occasions_of(s, [x.plan.id for x in plans])
    gifts = readable(s, user_id)
    end = today + dt.timedelta(days=days)
    out = []
    for x in plans:
        p = x.person
        if me is not None and p.id == me.personId:
            continue  # your own dates are for others to plan
        wedding = wedding_of(s, p.id)
        for year in {today.year, end.year}:
            for d in dates_in(p, occs[x.plan.id], year, wedding):
                if not today <= d.date <= end:
                    continue
                left = (d.date - today).days
                mine = [
                    g
                    for g, ps in gifts
                    if p.id in ps
                    and g.occasion == d.key
                    and g.occasionYear == d.date.year
                    and g.status != "received"
                ]
                out.append(
                    Upcoming(
                        p,
                        d,
                        left,
                        left <= x.plan.leadDays,
                        mine,
                        sum((g.cost or ZERO for g in mine if g.status != "idea"), ZERO),
                    )
                )
    return sorted(out, key=lambda u: (u.date.date, u.person.name))


def what_is_missing(u: Upcoming) -> str:
    """'no gift yet', '1 idea, nothing bought', or what is planned."""
    if not u.gifts:
        return "no gift yet"
    ideas = sum(1 for g in u.gifts if g.status == "idea")
    done = [g for g in u.gifts if g.status in ("bought", "given")]
    if done:
        return f"{len(done)} bought"
    if ideas == len(u.gifts):
        return f"{ideas} idea{'' if ideas == 1 else 's'}, nothing bought"
    return f"{len(u.gifts) - ideas} planned, nothing bought"


def gift_day(g: Gift, s: Session) -> int | None:
    """The year a gift's spending counts in: its occasion's, else its purchase's."""
    if g.occasionYear:
        return g.occasionYear
    if g.transactionId:
        from ..store.entities.accounts import Transaction

        t = s.get(Transaction, g.transactionId)
        return t.date.year if t else None
    return None


@dataclass
class Spending:
    year: int
    byPerson: list[tuple[Person, Decimal, Decimal | None]]  # spent, budget
    byOccasion: list[tuple[str, Decimal]]
    byYear: list[tuple[int, Decimal]]
    flagged: list[tuple[Person, Decimal, Decimal]]  # given in money above the exclusion


def spending(s: Session, user_id: str, year: int) -> Spending:
    me = s.get(User, user_id)
    plans = {x.person.id: x for x in visible_plans(s, user_id)}
    by_person: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_occasion: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_year: dict[int, Decimal] = defaultdict(lambda: ZERO)
    money: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for g, ps in readable(s, user_id):
        if g.status not in SPENT or not g.cost:
            continue
        y = gift_day(g, s)
        if y is None:
            continue
        by_year[y] += g.cost
        if y != year:
            continue
        share = g.cost / max(len(ps), 1)
        for pid in ps:
            by_person[pid] += share
            if g.cash and g.ownerId == user_id:
                money[pid] += share
        kind = (g.occasion or "other").partition(":")[0]
        name = {
            "birthday": "Birthdays",
            "wedding": "Anniversaries and other dates",
            "holiday": label_of(g.occasion, []),
            "occasion": "Anniversaries and other dates",
        }.get(kind, "Other")
        by_occasion[name] += g.cost
    # 529 contributions to the person are gifts to them too (S1.8.2, S7.8.7).
    from .. import education
    from ..store.entities.accounts import Account
    from ..store.entities.education import EducationPlan

    # Every 529 of the user's counts, whether or not its beneficiary has a gift plan; a
    # five-year election is a fifth of it in each of its five years.
    for plan in s.scalars(
        select(EducationPlan)
        .join(Account, Account.id == EducationPlan.accountId)
        .where(
            Account.ownerId == user_id,
            Account.deleted == false(),
            EducationPlan.deleted == false(),
        )
    ):
        if me is not None and plan.beneficiaryId == me.personId:
            continue
        a = s.get(Account, plan.accountId)
        for r in education.contributions(s, a):
            if r.contributor != "owner":
                continue
            if r.fiveYear and r.date.year <= year <= r.date.year + 4:
                money[plan.beneficiaryId] += (r.amount / 5).quantize(Decimal("0.01"))
            elif not r.fiveYear and r.date.year == year:
                money[plan.beneficiaryId] += r.amount
    limit = Decimal(str(taxtables.figures(s, year)["giftExclusion"]))
    return Spending(
        year=year,
        byPerson=[
            (x.person, by_person.get(pid, ZERO), x.plan.giftBudget)
            for pid, x in plans.items()
            if me is None or pid != me.personId
        ],
        byOccasion=sorted(by_occasion.items(), key=lambda x: -x[1]),
        byYear=sorted(by_year.items()),
        flagged=[(s.get(Person, pid), amt, limit) for pid, amt in money.items() if amt > limit],
    )


def label_for_occasion(s: Session, g: Gift, ps: list[str]) -> str:
    owner_plans = [
        gp.id
        for gp in s.scalars(
            select(GiftPlan).where(
                GiftPlan.ownerId == g.ownerId,
                GiftPlan.personId.in_(ps),
                GiftPlan.deleted == false(),
            )
        )
    ]
    occs = occasions_of(s, owner_plans)
    return label_of(g.occasion, [o for v in occs.values() for o in v])


def delete_person(s: Session, p: Person, by: str) -> None:
    """Deleting a person (S7.8.6): their gift plans go with them, ideas and planned gifts for
    them alone are deleted, and every other gift keeps them by name."""
    from .. import clock

    now = clock.now()
    p.mark_deleted(by, now)
    for gp in s.scalars(
        select(GiftPlan).where(GiftPlan.personId == p.id, GiftPlan.deleted == false())
    ):
        gp.mark_deleted(by, now)
    links = list(
        s.scalars(
            select(GiftPerson).where(GiftPerson.personId == p.id, GiftPerson.deleted == false())
        )
    )
    whom = people_of_gifts(s, [x.giftId for x in links])
    for x in links:
        g = s.get(Gift, x.giftId)
        if g is None or g.deleted or g.status not in NOT_YET:
            continue
        if whom[g.id] == [p.id]:
            g.mark_deleted(by, now)
        else:
            x.mark_deleted(by, now)
