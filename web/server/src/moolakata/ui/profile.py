"""Profile (requirements S12.2.16): name, sex, birthday and relationships (the user's person,
S10.10), email, avatar, password, two-step sign-in, time zone, theme and alert emails.
Assumptions and access tokens come with their features."""

import datetime as dt
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import false, select

from .. import access, activity, clock, people, settings, timezones
from ..auth import sessions, twostep
from ..auth import users as accounts
from ..errors import Problem, refuse
from ..people import tree
from ..store.entities.users import OneTimeToken, User
from .conventions import ExactRoute, Model
from .deps import Caller, caller, recent_auth, server, set_cookie
from .session import count_failure, guarded

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["profile"])
AVATAR = re.compile(r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$")
AVATAR_MAX = 256 * 1024


class Relation(Model):
    """Someone the user is related to (S10.10.6): stored, or worked out from those."""

    personId: str
    name: str
    word: str  # husband, daughter, mother-in-law
    stored: bool


class Spouse(Model):
    """Who the user is married to today, when they are a user here (S10.10.4.3)."""

    id: str  # the user
    displayName: str
    birthYear: int | None


class TwoStep(Model):
    on: bool
    since: dt.datetime | None
    recoveryCodesLeft: int


class TwoStepSetup(Model):
    """What an authenticator app needs: the QR code, or the key typed by hand."""

    secret: str
    uri: str
    qrImage: str


class TwoStepConfirm(Model):
    code: str


class RecoveryCodes(Model):
    """Shown once: only their hashes are kept."""

    codes: list[str]


class Profile(Model):
    id: str
    username: str
    displayName: str
    email: str | None
    pendingEmail: str | None
    avatar: str | None
    timeZone: str
    zone: str
    theme: str
    personId: str
    sex: str
    birthMonth: int | None
    birthDay: int | None
    birthYear: int | None
    alertEmails: str
    bitcoinUnit: str  # how bitcoin amounts are shown: btc or sats (S1.6.4)
    shownProjectionIds: list[str]  # shared projections shown on their Dashboard (S6.8.3)
    activeBudgetId: str | None  # the budget they follow (S7.12.1)
    twoStep: TwoStep
    relations: list[Relation]
    spouse: Spouse | None
    version: int


class PasswordChange(Model):
    currentPassword: str
    newPassword: str


class EmailChange(Model):
    email: str


class Zones(Model):
    server: str
    zones: list[str]


def profile(s, u: User) -> Profile:
    pending = s.scalars(
        select(OneTimeToken.data).where(
            OneTimeToken.userId == u.id,
            OneTimeToken.purpose == "email-change",
            OneTimeToken.expiresAt > sessions.now(),
        )
    ).first()
    me = people.of_user(s, u.id)
    g = tree.graph(s)
    relations = [
        Relation(personId=r.personId, name=g.people[r.personId].name, word=r.word, stored=r.stored)
        for r in g.relations(me.id)
        if people.readable(s, u.id, r.personId)
    ]
    return Profile(
        id=u.id,
        username=u.username,
        displayName=u.displayName,
        email=u.email,
        pendingEmail=pending,
        avatar=u.avatar,
        timeZone=u.timeZone,
        zone=timezones.zone_for(u.timeZone),
        theme=u.theme,
        personId=me.id,
        sex=me.sex,
        birthMonth=me.birthMonth,
        birthDay=me.birthDay,
        birthYear=me.birthYear,
        alertEmails=u.alertEmails,
        bitcoinUnit=u.bitcoinUnit,
        shownProjectionIds=shown(s, u.id),
        activeBudgetId=u.activeBudgetId,
        twoStep=TwoStep(
            on=twostep.is_on(u),
            since=u.twoStepAt,
            recoveryCodesLeft=twostep.codes_left(s, u.id),
        ),
        relations=relations,
        spouse=_spouse(s, u.id),
        version=u.version,
    )


def _spouse(s, user_id: str) -> Spouse | None:
    other = people.spouse_user_on(s, user_id, clock.today())
    if other is None:
        return None
    u = s.get(User, other)
    return Spouse(id=u.id, displayName=u.displayName, birthYear=people.birth_year(s, u.id))


@router.get("/profile", response_model=Profile)
def get_profile(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        return profile(s, s.get(User, c.id))


def _show(s, u: User, wanted: list[str]) -> None:
    """A shared active projection shows on a receiver's Dashboard only when they ask; their own
    always show (S6.8.3)."""
    from .. import projections
    from ..store.entities.projections import ShownProjection

    mine = {p.id: held for p, held in projections.visible(s, u.id)}
    for pid in wanted:
        if pid not in mine:
            raise refuse(
                "shownProjectionIds", "projection-unknown", "A projection shared with you."
            )
        if mine[pid].mine:
            raise refuse(
                "shownProjectionIds", "owner-sees-it", "Your own active projections always show."
            )
    rows = {
        r.projectionId: r
        for r in s.scalars(select(ShownProjection).where(ShownProjection.userId == u.id))
    }
    for pid in wanted:
        if pid in rows:
            rows[pid].restore()
        else:
            s.add(ShownProjection(userId=u.id, projectionId=pid, createdAt=clock.now()))
    for pid, r in rows.items():
        if pid not in wanted and not r.deleted:
            r.mark_deleted(u.id)


# A user's own profile, theirs alone to change (S12.2.16); an admin changes the rest.
PROFILE_FIELDS = (
    "shownProjectionIds",
    "displayName",
    "avatar",
    "timeZone",
    "theme",
    "sex",
    "birthMonth",
    "birthDay",
    "birthYear",
    "alertEmails",
    "bitcoinUnit",
    "activeBudgetId",
)


def shown(s, user_id: str) -> list[str]:
    """The shared active projections the user shows on their Dashboard (S6.8.3)."""
    from ..store.entities.projections import ShownProjection

    rows = s.scalars(
        select(ShownProjection.projectionId).where(
            ShownProjection.userId == user_id, ShownProjection.deleted == false()
        )
    )
    return sorted(rows)


def current(s, u: User) -> dict:
    """The profile's fields as a draft holds them."""
    me = people.of_user(s, u.id)
    return {"displayName": u.displayName, "avatar": u.avatar, "timeZone": u.timeZone,
            "theme": u.theme, "sex": me.sex, "birthMonth": me.birthMonth,
            "birthDay": me.birthDay, "birthYear": me.birthYear, "alertEmails": u.alertEmails,
            "bitcoinUnit": u.bitcoinUnit, "shownProjectionIds": shown(s, u.id),
            "activeBudgetId": u.activeBudgetId}  # fmt: skip


def change(s, u: User, body, sent: set[str]) -> None:
    """The fields `sent` set on the user's own profile, each checked."""
    me = people.of_user(s, u.id)
    fields = []
    if "shownProjectionIds" in sent:
        _show(s, u, body.shownProjectionIds)
    if "displayName" in sent:
        name = (body.displayName or "").strip()
        if not name or len(name) > 80:
            raise refuse("displayName", "name-invalid", "Enter a name of up to 80 characters.")
        people.change(s, me, {"name": name})
        fields.append("displayName")
    if "avatar" in sent:
        if body.avatar is not None and (
            not AVATAR.match(body.avatar) or len(body.avatar) > AVATAR_MAX
        ):
            raise refuse("avatar", "avatar-invalid", "Use a PNG, JPEG or WebP image under 192 KB.")
        u.avatar = body.avatar
        fields.append("avatar")
    if "timeZone" in sent:
        tz = body.timeZone or "auto"
        if tz != "auto" and not timezones.valid(tz):
            raise refuse("timeZone", "zone-invalid", "Choose a time zone from the list.")
        u.timeZone = tz
        fields.append("timeZone")
    if "theme" in sent:
        if body.theme not in ("dark", "light", "system"):
            raise refuse("theme", "theme-invalid", "Dark, light or the system's.")
        u.theme = body.theme
        fields.append("theme")
    if "sex" in sent:
        if body.sex not in people.SEXES:
            raise refuse("sex", "sex-invalid", "Female or male.")
        people.change(s, me, {"sex": body.sex})
        fields.append("sex")
    if sent & {"birthMonth", "birthDay", "birthYear"}:
        month, day, year = body.birthMonth, body.birthDay, body.birthYear
        if (month is None) != (day is None):
            raise refuse("birthDay", "birthday-incomplete", "A month and a day.")
        if month is not None and not (1 <= month <= 12 and 1 <= day <= 31):
            raise refuse("birthDay", "day-invalid", "A day of the year.")
        if year is not None and not 1900 <= year <= 2100:
            raise refuse("birthYear", "year-invalid", "Enter a year such as 1979.")
        people.change(s, me, {"birthMonth": month, "birthDay": day, "birthYear": year})
        fields.append("birthday")
    if "alertEmails" in sent:
        if body.alertEmails not in ("each", "daily", "none"):
            raise refuse("alertEmails", "choice-invalid", "Each alert, a daily summary or none.")
        u.alertEmails = body.alertEmails
        fields.append("alertEmails")
    if "bitcoinUnit" in sent:
        if body.bitcoinUnit not in ("btc", "sats"):
            raise refuse("bitcoinUnit", "choice-invalid", "BTC or sats.")
        u.bitcoinUnit = body.bitcoinUnit
        fields.append("bitcoinUnit")
    if "activeBudgetId" in sent:
        # The budget they follow from now on; the one before becomes a scenario, and nothing
        # is rewritten (S7.12.1).
        if body.activeBudgetId is None:
            raise refuse("activeBudgetId", "budget-required", "Choose a budget to follow.")
        b, _ = access.budget(s, u.id, body.activeBudgetId)
        u.activeBudgetId = b.id
        activity.record(s, "budget.activated", actor=u.id, subject_kind="budget",
                        subject_id=b.id, owner=u.id)  # fmt: skip
    if fields:
        # The person's fields are the user's profile too: its version moves with them.
        u.updatedAt = clock.now()
        activity.record(s, "profile.updated", actor=u.id, subject_kind="user", subject_id=u.id,
                        owner=u.id, detail={"fields": fields})  # fmt: skip


@router.post("/profile/password", status_code=204)
def change_password(body: PasswordChange, request: Request, c: Caller = Depends(caller)):
    """Ends every session; this browser gets a fresh one (S13.7.1). A wrong current password
    counts toward the sign-in's lockout (S13.7.5.1)."""
    srv = server(request)
    address = guarded(request, c.user.username)
    try:
        with srv.db.tx(user=c.id) as s:
            u = s.get(User, c.id)
            accounts.change_password(s, srv.services, u, body.currentPassword, body.newPassword)
            token = sessions.create(s, u.id, c.admin, False)
    except Problem as e:
        if e.code == "password-wrong":
            with srv.db.tx(user=c.id) as s:
                count_failure(s, srv.sign_in, c.user.username, address, s.get(User, c.id))
        raise
    srv.events.end_user(c.id, "signed-out")
    set_cookie(request, token)
    return Response(status_code=204)


@router.post("/profile/email", status_code=204)
def change_email(body: EmailChange, request: Request, c: Caller = Depends(caller)):
    recent_auth(c)
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        accounts.request_email_change(s, srv.services, s.get(User, c.id), body.email)
    return Response(status_code=204)


@router.post("/profile/two-step", response_model=TwoStepSetup)
def two_step_begin(request: Request, c: Caller = Depends(caller)):
    """Turning two-step on starts here; it is on once a code from the app is confirmed."""
    recent_auth(c)
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        u = s.get(User, c.id)
        seed = twostep.begin(s, srv.keys.secrets, u)
        link = twostep.uri(seed, u.username, settings.get(s, "serverName") or "MoolaKata")
    return TwoStepSetup(secret=seed, uri=link, qrImage=twostep.qr_image(link))


@router.post("/profile/two-step/confirm", response_model=RecoveryCodes)
def two_step_confirm(body: TwoStepConfirm, request: Request, c: Caller = Depends(caller)):
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        codes = twostep.confirm(s, srv.services, srv.keys.secrets, s.get(User, c.id), body.code)
    return RecoveryCodes(codes=codes)


@router.post("/profile/two-step/recovery-codes", response_model=RecoveryCodes)
def two_step_codes(request: Request, c: Caller = Depends(caller)):
    """New codes replace every old one."""
    recent_auth(c)
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        return RecoveryCodes(codes=twostep.new_recovery_codes(s, s.get(User, c.id)))


@router.post("/profile/two-step/off", response_model=Profile)
def two_step_off(request: Request, c: Caller = Depends(caller)):
    """Two-step sign-in off, with the password again (S13.7.2): an action on the user."""
    recent_auth(c)
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        u = s.get(User, c.id)
        twostep.turn_off(s, srv.services, u, u)
        u.updatedAt = clock.now()
        s.flush()
        return profile(s, u)


@router.get("/timezones", response_model=Zones)
def zones(request: Request, c: Caller = Depends(caller)):
    return Zones(server=timezones.host_zone(), zones=timezones.names())
