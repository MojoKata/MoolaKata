"""Gifts (requirements S7.7, S7.8): each user's gift plans for the household's people, with
their occasions; what each user may see (their own plans and gifts, and plans shared with
them, but never the gifts for themselves); the occasions coming up with what is planned for
them; spending by person, occasion and year; and the gift-tax flag."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import false, select, update
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
    """A gift plan the user can see, with what the user holds of it, and its person: whole
    when the user sees them, else (`person` None) their name alone (R3.14)."""

    plan: GiftPlan
    person: Person | None
    name: str
    perms: access.Perms

    @property
    def personId(self) -> str:
        return self.plan.personId

    def wedding(self, s: Session) -> dt.date | None:
        """The person's wedding day, for one the user sees: nothing else of one they don't."""
        return wedding_of(s, self.personId) if self.person is not None else None


def _whom(s: Session, user_id: str, gp: GiftPlan) -> tuple[Person | None, str]:
    """A plan's person, when the user sees them (PersonAccess, whatever the session reads:
    alerts and badges read as the server), and their name whether or not they do (R3.14)."""
    pid = gp.personId
    p = s.get(Person, pid) if people.readable(s, user_id, pid) else None
    return p, p.name if p is not None else people.names(s, [pid])[pid]


def visible_plans(s: Session, user_id: str) -> list[Plan]:
    """The user's own gift plans and those shared with them, one per person: their own when
    they have one, else the shared one they may change, else any (GiftPlanAccess, which
    leaves out a deleted person's)."""
    best: dict[str, Plan] = {}
    for gp, perms in access.listing(s, GiftPlan, user_id):
        p, name = _whom(s, user_id, gp)
        have = best.get(gp.personId)
        if have is None or _rank(perms) > _rank(have.perms):
            best[gp.personId] = Plan(gp, p, name, perms)
    return sorted(best.values(), key=lambda x: x.name)


def _rank(perms: access.Perms) -> tuple[bool, bool]:
    return perms.mine, perms.writable


def plan_by_id(s: Session, user_id: str, plan_id: str, need: str = "read") -> Plan:
    """`need`: *read*, *write*, or a permission's name (deleting it: *deletable*)."""
    from ..errors import Problem

    perms = access.perms(s, GiftPlan, plan_id, user_id)
    gp = s.get(GiftPlan, plan_id) if perms is not None else None
    if gp is None:
        raise Problem(404, "not-found", "Not found")
    want = {"read": None, "write": "writable"}.get(need, need)
    if want is not None and not getattr(perms, want):
        raise Problem(403, "read-only", "This gift plan is shared with you to read.")
    return Plan(gp, *_whom(s, user_id, gp), perms)


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
    p: Person | None,
    occs: list[Occasion],
    year: int,
    wedding: dt.date | None = None,
    plan: GiftPlan | None = None,
) -> list[Date]:
    """A person's dated occasions in a year: their birthday, their wedding anniversary, and
    the plan's own occasions, each with its budget (the birthday's and the wedding's are the
    plan's, S7.7.1). With no person (one the reader can't see), the plan's own alone."""
    out = []
    if p is not None and p.birthMonth and p.birthDay and not p.diedOn:
        out.append(
            Date(
                "birthday",
                "Birthday",
                _safe(year, p.birthMonth, p.birthDay),
                plan.birthdayBudget if plan else None,
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
                plan.weddingBudget if plan else None,
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


def year_budget(
    plan: GiftPlan, p: Person | None, occs: list[Occasion], year: int, wedding: dt.date | None
) -> Decimal | None:
    """What a plan means to spend on its person in a year (S7.7.1): its yearly budget when it
    has one, else the budgets of that year's occasions together; none when it has neither."""
    if plan.giftBudget is not None:
        return plan.giftBudget
    each = [d.budget for d in dates_in(p, occs, year, wedding, plan) if d.budget is not None]
    return sum(each, ZERO) if each else None


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


@dataclass(frozen=True)
class Named:
    """A person a record names, by name: deleted ones too (S7.8.6), and ones the reader can't
    see (R3.14)."""

    id: str
    name: str
    deleted: bool


@dataclass
class Upcoming:
    person: Named
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
        if me is not None and x.personId == me.personId:
            continue  # your own dates are for others to plan
        wedding = x.wedding(s)
        for year in {today.year, end.year}:
            for d in dates_in(x.person, occs[x.plan.id], year, wedding, x.plan):
                if not today <= d.date <= end:
                    continue
                left = (d.date - today).days
                mine = [
                    g
                    for g, ps in gifts
                    if x.personId in ps
                    and g.occasion == d.key
                    and g.occasionYear == d.date.year
                    and g.status != "received"
                ]
                out.append(
                    Upcoming(
                        Named(x.personId, x.name, False),
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
    byPerson: list[tuple[Named, Decimal, Decimal | None]]  # spent, budget
    byOccasion: list[tuple[str, Decimal]]
    byYear: list[tuple[int, Decimal]]
    flagged: list[tuple[Named, Decimal, Decimal]]  # given in money above the exclusion


def _named(s: Session, person_ids) -> dict[str, Named]:
    """The people a reader's gifts and 529s name, by name, deleted ones too: read as the
    server, since a record the reader sees names whoever it names (R3.14)."""
    from ..store import scoping

    q = select(Person.id, Person.name, Person.deletedAt).where(Person.id.in_(list(person_ids)))
    rows = s.execute(scoping.unscoped(q, "the people a reader's gift spending names"))
    return {r.id: Named(r.id, r.name, r.deletedAt is not None) for r in rows}


def spending(s: Session, user_id: str, year: int) -> Spending:
    me = s.get(User, user_id)
    plans = {x.personId: x for x in visible_plans(s, user_id)}
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
            if r.contributor == "owner":
                money[plan.beneficiaryId] += education.counted_years(s, r).get(year, ZERO)
    limit = Decimal(str(taxtables.figures(s, year)["giftExclusion"]))
    # A row for everyone the year's spending names, so by person adds up with by year: a
    # deleted person, or one whose plan is gone, keeps theirs with no budget (S7.8.6).
    whom = (set(plans) | set(by_person)) - ({me.personId} if me is not None else set())
    named = _named(s, whom | set(money))
    occs = occasions_of(s, [x.plan.id for x in plans.values()])
    budget = {
        pid: year_budget(x.plan, x.person, occs[x.plan.id], year, x.wedding(s))
        for pid, x in plans.items()
    }
    return Spending(
        year=year,
        byPerson=sorted(
            ((named[pid], by_person.get(pid, ZERO), budget.get(pid)) for pid in whom),
            key=lambda x: (x[0].name, x[0].id),
        ),
        byOccasion=sorted(by_occasion.items(), key=lambda x: -x[1]),
        byYear=sorted(by_year.items()),
        flagged=[(named[pid], amt, limit) for pid, amt in money.items() if amt > limit],
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
    # Every plan for them, whoever's: the server's bookkeeping, since the deleter's session
    # sees only the plans it may, and none for a deleted person.
    s.execute(
        update(GiftPlan)
        .where(GiftPlan.personId == p.id, GiftPlan.deletedAt.is_(None))
        .values(deletedAt=now, deletedById=by, version=GiftPlan.version + 1, updatedAt=now)
        .execution_options(synchronize_session=False)
    )
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
