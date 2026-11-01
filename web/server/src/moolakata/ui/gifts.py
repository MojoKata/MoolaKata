"""Gifts (requirements S7.7, S7.8): gift plans and their occasions, gifts from idea to given
and those received, the occasions coming up, spending by person, occasion and year, each
person's history, and the gift-tax flag. Gift plans and gifts are their owner's alone unless a
plan is shared; a gift for the viewer is never shown to them."""

import datetime as dt
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import false, select

from .. import access, activity, clock, gifts, people, receipts
from ..errors import FieldError, Problem, refuse
from ..gifts import holidays
from ..people import tree
from ..store import scoping
from ..store.entities.accounts import Account, Category, Transaction
from ..store.entities.education import Gift, GiftPerson, GiftPlan, Occasion, Person
from ..store.entities.users import User
from . import save
from .conventions import Access, ExactRoute, IdOf, Model, Money
from .deps import Caller, caller, server
from .receipts import ReceiptRow
from .receipts import row as receipt_row

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["gifts"])


# ---- Gift plans and their occasions (S7.7) ----


class OccasionIn(Model):
    kind: str  # anniversary, holiday, custom
    name: str | None = None
    holiday: str | None = None
    month: int | None = None
    day: int | None = None
    year: int | None = None
    budget: Money | None = None


class OccasionOut(OccasionIn):
    id: str
    label: str
    next: dt.date | None
    version: int


class PersonIn(Model):
    """A gift plan, and the person it is for: an existing one (`personId`) or a new one."""

    personId: str | None = None
    name: str = ""
    sex: str | None = None
    birthMonth: int | None = None
    birthDay: int | None = None
    birthYear: int | None = None
    diedOn: dt.date | None = None
    private: bool | None = None  # left as it is when not given
    differentPerson: bool = False  # the same name as someone here, told apart by birth year
    giftBudget: Money | None = None
    leadDays: int = 14
    notes: str | None = None
    occasions: list[OccasionIn] | None = None  # a new plan's


class NextDate(Model):
    key: str
    label: str
    date: dt.date
    days: int
    turns: int | None


class RemoteUser(Model):
    id: str
    name: str
    server: str


class PersonOut(Model):
    """A gift plan the caller sees, with its person."""

    id: str  # the person's
    planId: str
    name: str
    sex: str
    relation: str | None  # to the caller: daughter, mother-in-law (S10.10.5)
    userId: str | None  # when they are a user
    userName: str | None
    birthMonth: int | None
    birthDay: int | None
    birthYear: int | None
    diedOn: dt.date | None
    wedding: dt.date | None  # the start of their marriage, for its anniversary (S7.7.1)
    private: bool
    canChangePerson: bool
    canMakePrivate: bool  # whoever added them (S10.10.2)
    isUser: bool
    # Remote users who may be this person, to join to them (S10.10.1).
    sameAs: list[RemoteUser]
    giftBudget: Money | None
    leadDays: int
    notes: str | None
    occasions: list[OccasionOut]
    next: NextDate | None
    spent: Money  # this year
    lastGift: str | None
    access: Access
    ownerName: str
    version: int  # the plan's
    personVersion: int


class HolidayOut(Model):
    key: str
    label: str
    date: dt.date | None  # this year's


def _next(
    p: Person, occs: list[Occasion], today: dt.date, wedding: dt.date | None
) -> NextDate | None:
    ahead = [
        d
        for y in (today.year, today.year + 1)
        for d in gifts.dates_in(p, occs, y, wedding)
        if d.date >= today
    ]
    if not ahead:
        return None
    d = min(ahead, key=lambda x: x.date)
    return NextDate(
        key=d.key, label=d.label, date=d.date, days=(d.date - today).days, turns=d.turns
    )


def _occasion_out(o: Occasion, today: dt.date) -> OccasionOut:
    nxt = None
    for y in (today.year, today.year + 1):
        if o.kind == "holiday":
            d = holidays.date_of(o.holiday, y)
        else:
            d = gifts._safe(y, o.month, o.day)
        if d is not None and d >= today:
            nxt = d
            break
    label = holidays.label(o.holiday) if o.kind == "holiday" else (o.name or "Anniversary")
    return OccasionOut(
        id=o.id,
        kind=o.kind,
        name=o.name,
        holiday=o.holiday,
        month=o.month,
        day=o.day,
        year=o.year,
        budget=o.budget,
        label=label,
        next=nxt,
        version=o.version,
    )


def _remote(s, u: User) -> RemoteUser:
    from ..store.entities.links import Link

    link = s.get(Link, u.linkId)
    return RemoteUser(
        id=u.id, name=u.displayName, server=(link.peerName or link.address or "") if link else ""
    )


def people_view(s, c: Caller) -> list[PersonOut]:
    today = clock.today()
    plans = gifts.visible_plans(s, c.id)
    occs = gifts.occasions_of(s, [x.plan.id for x in plans])
    seen = gifts.readable(s, c.id)
    me = s.get(User, c.id)
    words = tree.relation_to(s, me.personId) if me else {}
    users = people.users_by_person(s)
    spent: dict[str, Decimal] = {}
    last: dict[str, tuple[int, str]] = {}
    for g, ps in seen:
        if g.status not in gifts.SPENT:
            continue
        y = gifts.gift_day(g, s) or 0
        for pid in ps:
            if y == today.year and g.cost:
                spent[pid] = spent.get(pid, Decimal(0)) + g.cost / max(len(ps), 1)
            if g.status == "given" and y >= last.get(pid, (0, ""))[0]:
                last[pid] = (y, f"{g.description}, {y}")
    out = []
    for x in plans:
        p, gp = x.person, x.plan
        owner = s.get(User, gp.ownerId)
        u = users.get(p.id)
        rel = words.get(p.id)
        wedding = gifts.wedding_of(s, p.id)
        out.append(
            PersonOut(
                id=p.id,
                planId=gp.id,
                name=p.name,
                sex=p.sex,
                relation=rel.word if rel else None,
                userId=u.id if u else None,
                userName=u.displayName if u else None,
                birthMonth=p.birthMonth,
                birthDay=p.birthDay,
                birthYear=p.birthYear,
                diedOn=p.diedOn,
                wedding=wedding,
                private=p.private,
                canChangePerson=people.changeable(s, c.id, p.id),
                canMakePrivate=p.ownerId == c.id,
                isUser=p.id in users,
                sameAs=[_remote(s, r) for r in people.may_join(s, c.id, p)],
                giftBudget=gp.giftBudget,
                leadDays=gp.leadDays,
                notes=gp.notes,
                occasions=[_occasion_out(o, today) for o in occs[gp.id]],
                next=_next(p, occs[gp.id], today, wedding),
                spent=spent.get(p.id, Decimal(0)),
                lastGift=None if me and p.id == me.personId else last.get(p.id, (0, None))[1],
                access=Access.of(x.perms),
                ownerName=owner.displayName,
                version=gp.version,
                personVersion=p.version,
            )
        )
    return out


def check_person_fields(body) -> dict:
    """A person's own fields (S10.10.1): name, sex and birthday."""
    e: list[FieldError] = []
    name = (body.name or "").strip()
    if not name or len(name) > 80:
        e.append(FieldError("name", "name-invalid", "A name, up to 80 characters."))
    if body.sex not in people.SEXES:
        e.append(FieldError("sex", "sex-invalid", "Female or male."))
    if body.birthMonth is not None and not 1 <= body.birthMonth <= 12:
        e.append(FieldError("birthMonth", "month-invalid", "A month, 1 to 12."))
    if body.birthDay is not None and not 1 <= body.birthDay <= 31:
        e.append(FieldError("birthDay", "day-invalid", "A day, 1 to 31."))
    if (body.birthMonth is None) != (body.birthDay is None):
        e.append(FieldError("birthDay", "birthday-incomplete", "A month and a day."))
    year = clock.today().year
    if body.birthYear is not None and not year - 120 <= body.birthYear <= year:
        e.append(FieldError("birthYear", "year-invalid", "A year of birth."))
    died = getattr(body, "diedOn", None)
    if died is not None and (
        died > clock.today() or (body.birthYear is not None and died.year < body.birthYear)
    ):
        e.append(FieldError("diedOn", "died-on-invalid", "A day since their birth, not ahead."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    return {
        "name": name,
        "sex": body.sex,
        "birthMonth": body.birthMonth,
        "birthDay": body.birthDay,
        "birthYear": body.birthYear,
        "diedOn": getattr(body, "diedOn", None),
    }


def refuse_clash(s, c: Caller, name: str, birth_year: int | None, exclude=None) -> None:
    """One person, once (S10.10.3): a name already here shows that person instead."""
    other = people.clash(s, name, birth_year, exclude)
    if other is None:
        return
    seen = access.perms(s, Person, other.id, c.id) is not None
    raise Problem(
        409,
        "person-exists",
        f"{other.name} is already here."
        + ("" if seen else " Ask to share them, or give both birth years to tell them apart."),
        [FieldError("name", "person-exists", f"{other.name} is already here.")],
        extra={
            "person": {
                "id": other.id,
                "name": other.name,
                "visible": seen,
                "private": other.private,
                "createdBy": other.creator,
            }
        },
    )


def _check_plan(body: PersonIn) -> dict:
    e: list[FieldError] = []
    if body.giftBudget is not None and body.giftBudget < 0:
        e.append(FieldError("giftBudget", "amount-invalid", "Zero or more."))
    if not 0 <= body.leadDays <= 120:
        e.append(FieldError("leadDays", "lead-invalid", "0 to 120 days."))
    for i, o in enumerate(body.occasions or []):
        at = f"occasions.{i}"
        if o.kind == "holiday":
            if o.holiday not in holidays.HOLIDAYS:
                e.append(FieldError(f"{at}.holiday", "holiday-invalid", "One of the holidays."))
        elif o.kind in ("anniversary", "custom"):
            if not (o.month and o.day and 1 <= o.month <= 12 and 1 <= o.day <= 31):
                e.append(FieldError(f"{at}.month", "date-invalid", "A month and a day."))
            if o.kind == "custom" and not (o.name or "").strip():
                e.append(FieldError(f"{at}.name", "name-missing", "What the occasion is."))
        else:
            e.append(FieldError(f"{at}.kind", "kind-invalid", "An anniversary, holiday or date."))
        if o.budget is not None and o.budget < 0:
            e.append(FieldError(f"{at}.budget", "amount-invalid", "Zero or more."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    return {"giftBudget": body.giftBudget, "leadDays": body.leadDays, "notes": body.notes or None}


def _one(s, c: Caller, person_id: str) -> PersonOut:
    return next(p for p in people_view(s, c) if p.id == person_id)


@router.get("/people", response_model=list[PersonOut])
def list_people(request: Request, c: Caller = Depends(caller)):
    """The caller's gift plans and those shared with them, with their people."""
    with server(request).db.read(user=c.id) as s:
        return people_view(s, c)


@router.get("/holidays", response_model=list[HolidayOut])
def list_holidays(request: Request, c: Caller = Depends(caller)):
    year = clock.today().year
    return [
        HolidayOut(key=k, label=holidays.label(k), date=holidays.date_of(k, year))
        for k in holidays.HOLIDAYS
    ]


@router.get("/people/{person_id}", response_model=PersonOut)
def get_plan(person_id: str, request: Request, c: Caller = Depends(caller)):
    """One gift plan the caller sees, with its person: what the plan's dialog starts from."""
    with server(request).db.read(user=c.id) as s:
        gifts.plan_for(s, c.id, person_id)
        return _one(s, c, person_id)


# ---- Gifts (S7.8) ----


class PersonRef(Model):
    id: str
    name: str
    deleted: bool = False  # kept by name (S7.8.6)


class Paid(Model):
    transactionId: str | None  # None when its account isn't shared with the viewer
    date: dt.date
    amount: Money
    payee: str | None
    accountName: str


class GiftIn(Model):
    people: list[str]
    occasion: str | None = None  # birthday, holiday:<key>, occasion:<id>; none for an idea
    occasionYear: int | None = None
    description: str
    status: str = "idea"
    cost: Money | None = None
    transactionId: str | None = None
    store: str | None = None
    link: str | None = None
    notes: str | None = None
    cash: bool = False
    thankYou: bool = False


class GiftOut(Model):
    id: str
    people: list[PersonRef]
    occasion: str | None
    occasionLabel: str
    occasionYear: int | None
    description: str
    status: str
    cost: Money | None
    paid: Paid | None
    store: str | None
    link: str | None
    notes: str | None
    cash: bool
    thankYou: bool
    documents: list[ReceiptRow]
    access: Access
    version: int


NOT_SHARED = "an account not shared"


def _paid(s, t_id: str | None, viewer: str) -> Paid | None:
    """What a gift was paid with; an account the viewer can't see is named as such, and its
    transaction is left out (S11.5.2): its date and amount read as the server, as the gift
    shows them."""
    t = (
        s.execute(
            scoping.unscoped(
                select(Transaction.date, Transaction.amount, Transaction.accountId).where(
                    Transaction.id == t_id, Transaction.deletedAt.is_(None)
                ),
                "what paid for a gift",
            )
        ).first()
        if t_id
        else None
    )
    if t is None:
        return None
    a = s.get(Account, t.accountId)
    full = s.get(Transaction, t_id) if a is not None else None
    if a is None or full is None:
        return Paid(
            transactionId=None, date=t.date, amount=t.amount, payee=None, accountName=NOT_SHARED
        )
    return Paid(
        transactionId=t_id, date=t.date, amount=t.amount, payee=full.payee, accountName=a.name
    )


def _gift_out(s, c: Caller, g: Gift, ps: list[str]) -> GiftOut:
    perms = access.perms(s, Gift, g.id, c.id)
    # The people a gift is for, by name, deleted ones too (S7.8.6): read as the server.
    named = {
        r.id: r
        for r in s.execute(
            scoping.unscoped(
                select(Person.id, Person.name, Person.deletedAt).where(Person.id.in_(ps)),
                "the people a gift is for",
            )
        )
    }
    return GiftOut(
        id=g.id,
        people=[
            PersonRef(id=p.id, name=p.name, deleted=p.deletedAt is not None)
            for p in (named.get(pid) for pid in ps)
            if p
        ],
        occasion=g.occasion,
        occasionLabel=gifts.label_for_occasion(s, g, ps),
        occasionYear=g.occasionYear,
        description=g.description,
        status=g.status,
        cost=g.cost,
        paid=_paid(s, g.transactionId, c.id),
        store=g.store,
        link=g.link,
        notes=g.notes,
        cash=g.cash,
        thankYou=g.thankYou,
        documents=[
            receipt_row(s, r, receipts.perms_for(s, c.id, r) or access.READ, c.id)
            for r in receipts.of_item(s, g.id, "gift")
        ],
        access=Access.of(perms or access.READ),
        version=g.version,
    )


def gifts_view(s, c: Caller, status: str | None = None, person: str | None = None):
    out = []
    for g, ps in gifts.readable(s, c.id):
        if status and g.status != status:
            continue
        if person and person not in ps:
            continue
        out.append(_gift_out(s, c, g, ps))
    order = {k: i for i, k in enumerate(gifts.STATUSES)}
    return sorted(out, key=lambda x: (order[x.status], -(x.occasionYear or 9999), x.description))


def _owner_for(s, c: Caller, person_ids: list[str]) -> str:
    """Whose plan a new gift goes in: the caller's, or for people the caller plans only
    through someone's shared plan, at write, that plan's owner (S7.8.5)."""
    owners = None
    for pid in person_ids:
        people.get(s, c.id, pid)
        mine = s.scalars(
            select(GiftPlan).where(
                GiftPlan.ownerId == c.id, GiftPlan.personId == pid, GiftPlan.deleted == false()
            )
        ).first()
        if mine is not None:
            return c.id
        here = {
            x.plan.ownerId
            for x in gifts.visible_plans(s, c.id)
            if x.person.id == pid and x.perms.writable and not x.perms.mine
        }
        owners = here if owners is None else owners & here
    return next(iter(sorted(owners))) if owners else c.id


def _check_gift(s, c: Caller, body: GiftIn, current: str | None = None) -> dict:
    e: list[FieldError] = []
    desc = body.description.strip()
    if not desc:
        e.append(FieldError("description", "description-missing", "What it is."))
    if body.status not in gifts.STATUSES:
        e.append(FieldError("status", "status-invalid", "Idea, planned, bought, given, received."))
    if not body.people:
        e.append(FieldError("people", "people-missing", "Who it is for."))
    if body.cost is not None and body.cost < 0:
        e.append(FieldError("cost", "amount-invalid", "Zero or more."))
    if body.occasion and not body.occasionYear:
        e.append(FieldError("occasionYear", "year-missing", "The year of the occasion."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    for pid in body.people:
        people.get(s, c.id, pid)
    if body.transactionId and body.transactionId != current:
        # Linking a purchase may recategorise it under Gifts: write on its account (P7).
        t = s.get(Transaction, body.transactionId)
        if t is None or t.deleted:
            raise refuse("transactionId", "not-found", "No such transaction.")
        access.account(s, c.id, t.accountId, "write")
    return {
        "occasion": body.occasion or None,
        "occasionYear": body.occasionYear if body.occasion else None,
        "description": desc,
        "status": body.status,
        "cost": body.cost,
        "transactionId": body.transactionId or None,
        "store": (body.store or "").strip() or None,
        "link": (body.link or "").strip() or None,
        "notes": body.notes or None,
        "cash": body.cash,
        "thankYou": body.thankYou and body.status == "received",
    }


def _set_people(s, g: Gift, ids_: list[str], user_id: str) -> None:
    now = clock.now()
    have = {
        gp.personId: gp for gp in s.scalars(select(GiftPerson).where(GiftPerson.giftId == g.id))
    }
    for pid, gp in have.items():
        if pid not in ids_ and not gp.deleted:
            gp.mark_deleted(user_id, now)
    for pid in ids_:
        gp = have.get(pid)
        if gp is None:
            s.add(GiftPerson(giftId=g.id, personId=pid, createdAt=now))
        elif gp.deleted:
            gp.restore()


def _categorise(s, t_id: str | None) -> None:
    """A gift's purchase goes under Gifts in budgets (S7.8.4), unless already categorised."""
    t = s.get(Transaction, t_id) if t_id else None
    if t is None or t.categoryId:
        return
    cat = s.scalars(select(Category).where(Category.builtIn == "gifts")).first()
    if cat is not None:
        t.categoryId = cat.id


def _linked(s, c: Caller, before: str | None, after: str | None) -> None:
    """A purchase newly linked to a gift: put under Gifts when uncategorised, and recorded."""
    if not after or after == before:
        return
    _categorise(s, after)
    t = s.get(Transaction, after)
    a = s.get(Account, t.accountId)
    activity.record(
        s,
        "gift.purchase-linked",
        actor=c.id,
        subject_kind="account",
        subject_id=a.id,
        owner=a.ownerId,
    )


def _gift_for(s, c: Caller, gift_id: str) -> GiftOut:
    return next(x for x in gifts_view(s, c) if x.id == gift_id)


@router.get("/gifts", response_model=list[GiftOut])
def list_gifts(
    request: Request,
    status: str | None = None,
    person: str | None = None,
    c: Caller = Depends(caller),
):
    with server(request).db.read(user=c.id) as s:
        return gifts_view(s, c, status, person)


def _editable(s, c: Caller, gift_id: str) -> Gift:
    g = s.get(Gift, gift_id)
    if g is None or g.deleted:
        raise Problem(404, "not-found", "Not found")
    found = [x for x in gifts_view(s, c) if x.id == gift_id]
    if not found:
        raise Problem(404, "not-found", "Not found")
    if not found[0].access.writable:
        raise Problem(403, "read-only", "This gift is shared with you to read.")
    return g


class Purchase(Model):
    transactionId: str
    date: dt.date
    amount: Money
    payee: str | None
    accountName: str
    category: str | None


@router.get("/gifts/purchases", response_model=list[Purchase])
def purchases(request: Request, c: Caller = Depends(caller)):
    """Recent spending, to link a gift's cost to its transaction: the last 90 days, in the
    accounts the caller writes to, since linking may recategorise it."""
    with server(request).db.read(user=c.id) as s:
        accts = {a.id: a for a, p in access.accounts(s, c.id) if p.writable}
        if not accts:
            return []
        cats = {x.id: x.name for x in s.scalars(select(Category))}
        rows = s.scalars(
            select(Transaction)
            .where(
                Transaction.accountId.in_(list(accts)),
                Transaction.deleted == false(),
                Transaction.amount < 0,
                Transaction.transferId.is_(None),
                Transaction.instrumentId.is_(None),
                Transaction.date >= clock.today() - dt.timedelta(days=90),
            )
            .order_by(Transaction.date.desc())
            .limit(200)
        )
        return [
            Purchase(
                transactionId=t.id,
                date=t.date,
                amount=t.amount,
                payee=t.payee,
                accountName=accts[t.accountId].name,
                category=cats.get(t.categoryId),
            )
            for t in rows
        ]


# ---- Upcoming, spending and history ----


class UpcomingOut(Model):
    person: PersonRef
    key: str
    label: str
    date: dt.date
    days: int
    turns: int | None
    inLead: bool
    budget: Money | None
    planned: Money
    missing: str
    gifts: list[GiftOut]


@router.get("/gifts/upcoming", response_model=list[UpcomingOut])
def list_upcoming(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        out = []
        for u in gifts.upcoming(s, c.id, clock.today()):
            ps = gifts.people_of_gifts(s, [g.id for g in u.gifts])
            out.append(
                UpcomingOut(
                    person=PersonRef(id=u.person.id, name=u.person.name),
                    key=u.date.key,
                    label=u.date.label,
                    date=u.date.date,
                    days=u.days,
                    turns=u.date.turns,
                    inLead=u.inLead,
                    budget=u.date.budget,
                    planned=u.planned,
                    missing=gifts.what_is_missing(u),
                    gifts=[_gift_out(s, c, g, ps[g.id]) for g in u.gifts],
                )
            )
        return out


class PersonSpend(Model):
    person: PersonRef
    spent: Money
    budget: Money | None


class Amount(Model):
    label: str
    amount: Money


class Flag(Model):
    person: PersonRef
    given: Money
    exclusion: Money


class SpendingOut(Model):
    year: int
    byPerson: list[PersonSpend]
    byOccasion: list[Amount]
    byYear: list[Amount]
    flagged: list[Flag]


@router.get("/gifts/spending", response_model=SpendingOut)
def get_spending(request: Request, year: int | None = None, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        sp = gifts.spending(s, c.id, year or clock.today().year)
        return SpendingOut(
            year=sp.year,
            byPerson=[
                PersonSpend(person=PersonRef(id=p.id, name=p.name), spent=a, budget=b)
                for p, a, b in sp.byPerson
            ],
            byOccasion=[Amount(label=k, amount=v) for k, v in sp.byOccasion],
            byYear=[Amount(label=str(k), amount=v) for k, v in sp.byYear],
            flagged=[
                Flag(person=PersonRef(id=p.id, name=p.name), given=a, exclusion=x)
                for p, a, x in sp.flagged
            ],
        )


# ---------- gift plans and their occasions in a dialog's draft (S12.15, S13.8.11) ----------


class PlanRecord(Model):
    """A gift plan as a draft saves it: its occasions are records of their own (`Occsn`), so
    each keeps its id, and the gifts planned for it stay with it (CR3-43)."""

    personId: IdOf("Persn")  # type: ignore[valid-type]
    giftBudget: Money | None = None
    leadDays: int = 14
    notes: str | None = None


class OccasionRecord(Model):
    """An occasion of a gift plan (S7.7.1): a holiday by its key, or an anniversary or other
    occasion on a month and day, with the year it began when known."""

    giftPlanId: IdOf("GfPln")  # type: ignore[valid-type]
    kind: Literal["anniversary", "holiday", "custom"]
    name: str | None = None
    holiday: str | None = None
    month: int | None = None
    day: int | None = None
    year: int | None = None
    budget: Money | None = None


def _plan_values(body: PlanRecord) -> dict:
    e: list[FieldError] = []
    if body.giftBudget is not None and body.giftBudget < 0:
        e.append(FieldError("giftBudget", "amount-invalid", "Zero or more."))
    if not 0 <= body.leadDays <= 120:
        e.append(FieldError("leadDays", "lead-invalid", "0 to 120 days."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    return {"giftBudget": body.giftBudget, "leadDays": body.leadDays, "notes": body.notes or None}


def _plan_create(ctx, record_id: str, body: PlanRecord) -> None:
    """A gift plan for someone the caller sees: a person already here, or one made in the
    same save; one plan each (S7.7)."""
    s, c = ctx.s, ctx.caller
    values = _plan_values(body)
    p = people.get(s, c.id, body.personId)
    have = s.scalars(
        select(GiftPlan).where(
            GiftPlan.ownerId == c.id, GiftPlan.personId == p.id, GiftPlan.deleted == false()
        )
    ).first()
    if have is not None:
        raise refuse("personId", "plan-exists", f"You have a gift plan for {p.name}.", 409)
    s.add(GiftPlan(id=record_id, ownerId=c.id, personId=p.id, **values))


def _plan_editable(ctx, record_id: str) -> GiftPlan:
    return gifts.plan_by_id(ctx.s, ctx.caller.id, record_id, "write").plan


def _plan_current(ctx, gp: GiftPlan) -> dict:
    return {"personId": gp.personId, "giftBudget": gp.giftBudget, "leadDays": gp.leadDays,
            "notes": gp.notes}  # fmt: skip


def _plan_update(ctx, gp: GiftPlan, body: PlanRecord) -> None:
    if body.personId != gp.personId:
        raise refuse("personId", "plan-fixed", "A gift plan stays with its person.")
    for k, v in _plan_values(body).items():
        setattr(gp, k, v)


def _plan_delete(ctx, gp: GiftPlan) -> None:
    """The caller's own plan; the person stays (S10.10), its occasions go with it."""
    gifts.plan_by_id(ctx.s, ctx.caller.id, gp.id, "deletable")
    gp.mark_deleted(ctx.caller.id)


def _occasion_values(body: OccasionRecord) -> dict:
    e: list[FieldError] = []
    holiday = body.kind == "holiday"
    if holiday:
        if body.holiday not in holidays.HOLIDAYS:
            e.append(FieldError("holiday", "holiday-invalid", "One of the holidays."))
    else:
        if not (body.month and body.day and 1 <= body.month <= 12 and 1 <= body.day <= 31):
            e.append(FieldError("month", "date-invalid", "A month and a day."))
        if body.kind == "custom" and not (body.name or "").strip():
            e.append(FieldError("name", "name-missing", "What the occasion is."))
    if body.budget is not None and body.budget < 0:
        e.append(FieldError("budget", "amount-invalid", "Zero or more."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    return {
        "kind": body.kind,
        "name": None if holiday else ((body.name or "").strip() or None),
        "holiday": body.holiday if holiday else None,
        "month": None if holiday else body.month,
        "day": None if holiday else body.day,
        "year": None if holiday else body.year,
        "budget": body.budget,
    }


def _occasion_create(ctx, record_id: str, body: OccasionRecord) -> None:
    gifts.plan_by_id(ctx.s, ctx.caller.id, body.giftPlanId)
    ctx.s.add(Occasion(id=record_id, giftPlanId=body.giftPlanId, **_occasion_values(body)))


def _occasion_editable(ctx, record_id: str) -> Occasion:
    o = ctx.s.get(Occasion, record_id)
    if o is None or o.deleted:
        raise Problem(404, "not-found", "Not found")
    gifts.plan_by_id(ctx.s, ctx.caller.id, o.giftPlanId, "write")
    return o


OCCASION_FIELDS = ("kind", "name", "holiday", "month", "day", "year", "budget")


def _occasion_current(ctx, o: Occasion) -> dict:
    return {"giftPlanId": o.giftPlanId, **{f: getattr(o, f) for f in OCCASION_FIELDS}}


def _occasion_update(ctx, o: Occasion, body: OccasionRecord) -> None:
    """In place: the gifts planned for it keep it (S7.8.1, CR3-43)."""
    if body.giftPlanId != o.giftPlanId:
        raise refuse("giftPlanId", "occasion-fixed", "An occasion stays with its plan.")
    for k, v in _occasion_values(body).items():
        setattr(o, k, v)


def _occasion_delete(ctx, o: Occasion) -> None:
    """Gifts planned for an anniversary or other occasion taken away become ideas again, once
    that is confirmed; a holiday's keep it by name."""
    key = f"occasion:{o.id}"
    planned = list(ctx.s.scalars(select(Gift).where(Gift.occasion == key, Gift.deleted == false())))
    if planned:
        label = o.name or "this occasion"
        n = len(planned)
        ctx.ask(
            "occasion-gifts",
            f"{n} gift{'s are' if n > 1 else ' is'} planned for {label}: "
            f"{'they become ideas' if n > 1 else 'it becomes an idea'}, with no occasion.",
        )
        for g in planned:
            g.occasion, g.occasionYear = None, None
    o.mark_deleted(ctx.caller.id)


def _occasion_read(ctx, record_id: str) -> OccasionOut:
    return _occasion_out(ctx.s.get(Occasion, record_id), clock.today())


save.register(
    save.Kind(
        prefix="GfPln",
        entity=GiftPlan,
        fields=PlanRecord,
        create=_plan_create,
        editable=_plan_editable,
        current=_plan_current,
        update=_plan_update,
        delete=_plan_delete,
        read=lambda ctx, record_id: _one(
            ctx.s, ctx.caller, ctx.s.get(GiftPlan, record_id).personId
        ),
    )
)
save.register(
    save.Kind(
        prefix="Occsn",
        entity=Occasion,
        fields=OccasionRecord,
        create=_occasion_create,
        editable=_occasion_editable,
        current=_occasion_current,
        update=_occasion_update,
        delete=_occasion_delete,
        read=_occasion_read,
    )
)


# ---------- gifts in a dialog's draft (S12.15, S13.8.11) ----------


class GiftRecord(GiftIn):
    """A gift as a draft saves it (S7.8), with its people as a set and the receipts kept with
    it (`receiptIds`)."""

    people: list[IdOf("Persn")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )
    receiptIds: list[IdOf("Rcpt")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )


GIFT_FIELDS = ("occasion", "occasionYear", "description", "status", "cost", "transactionId",
               "store", "link", "notes", "cash", "thankYou")  # fmt: skip


def _gift_create(ctx, record_id: str, body: GiftRecord) -> None:
    s, c = ctx.s, ctx.caller
    values = _check_gift(s, c, body)
    g = Gift(id=record_id, ownerId=_owner_for(s, c, body.people), **values)
    s.add(g)
    s.flush()
    _set_people(s, g, body.people, c.id)
    receipts.keep_set(s, c.id, "gift", g.id, [], body.receiptIds)
    _linked(s, c, None, g.transactionId)
    activity.record(s, "gift.saved", actor=c.id, owner=c.id)


def _gift_current(ctx, g: Gift) -> dict:
    s = ctx.s
    return {
        "people": gifts.people_of_gifts(s, [g.id])[g.id],
        "receiptIds": [r.id for r in receipts.of_item(s, g.id, "gift")],
        **{f: getattr(g, f) for f in GIFT_FIELDS},
    }


def _gift_update(ctx, g: Gift, body: GiftRecord) -> None:
    s, c = ctx.s, ctx.caller
    before = g.transactionId
    current = _gift_current(ctx, g)
    for k, v in _check_gift(s, c, body, before).items():
        setattr(g, k, v)
    g.updatedAt = clock.now()
    _set_people(s, g, body.people, c.id)
    receipts.keep_set(s, c.id, "gift", g.id, current["receiptIds"], body.receiptIds)
    _linked(s, c, before, g.transactionId)


save.register(
    save.Kind(
        prefix="Gift",
        entity=Gift,
        fields=GiftRecord,
        create=_gift_create,
        editable=lambda ctx, record_id: _editable(ctx.s, ctx.caller, record_id),
        current=_gift_current,
        update=_gift_update,
        delete=lambda ctx, g: g.mark_deleted(ctx.caller.id),
        read=lambda ctx, record_id: _gift_for(ctx.s, ctx.caller, record_id),
    )
)
