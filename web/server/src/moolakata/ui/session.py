"""Signing in and out, the default admin's setup, invitations, password reset and the live
stream (requirements S10.1, S12.6, S13.7)."""

import asyncio
import datetime as dt
import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import activity, settings, timezones
from ..auth import passwords, sessions, signup, twostep
from ..auth import users as accounts
from ..auth.tokens import digest
from ..errors import Problem, refuse
from ..mail import Email
from ..ratelimit import too_many
from ..store.entities.users import User
from .conventions import ExactRoute, Loose, Model
from .deps import Caller, caller_in_setup, caller_quiet, server, set_cookie
from .stream import stream

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["session"])


class Household(Model):
    name: str
    avatar: Loose


class Me(Model):
    id: str
    username: str
    displayName: str
    email: str | None
    avatar: str | None
    admin: bool
    needsSetup: bool
    timeZone: str
    zone: str
    theme: str
    bitcoinUnit: str  # btc or sats (S1.6.4)


class SessionInfo(Model):
    user: Me
    household: Household
    version: str
    dev: bool
    serverName: str


class SignIn(Model):
    login: str
    password: str


class TwoStepNeeded(Model):
    """The password was right and two-step sign-in is on: the code comes next (S10.1.6)."""

    twoStepToken: str


class TwoStepCode(Model):
    token: str
    code: str


class Setup(Model):
    password: str
    email: str
    displayName: str | None = None
    sex: str | None = None  # the default admin's person (S10.10.1)


class Password(Model):
    password: str


class Login(Model):
    login: str


class TokenPassword(Model):
    token: str
    password: str


class Token(Model):
    token: str


class SignupOpen(Model):
    """Whether the sign-in screen offers Sign up, and to which email domains."""

    open: bool
    domains: list[str]


class SignupForm(Model):
    displayName: str
    username: str
    email: str
    password: str
    sex: str | None = None


class SignupConfirmed(Model):
    displayName: str
    household: str


class InvitationInfo(Model):
    username: str
    displayName: str
    household: str


def info(request: Request, user: User, admin: bool) -> SessionInfo:
    srv = server(request)
    with srv.db.read(user=user.id) as s:
        house = Household(
            name=settings.get(s, "householdName"), avatar=settings.get(s, "householdAvatar")
        )
        name = settings.get(s, "serverName")
    return SessionInfo(
        user=Me(
            id=user.id,
            username=user.username,
            displayName=user.displayName,
            email=user.email,
            avatar=user.avatar,
            admin=admin,
            needsSetup=user.needsSetup,
            timeZone=user.timeZone,
            zone=timezones.zone_for(user.timeZone),
            theme=user.theme,
            bitcoinUnit=user.bitcoinUnit,
        ),
        household=house,
        version=srv.version,
        dev=srv.config.dev,
        serverName=name,
    )


def _address(request: Request) -> str:
    return request.client.host if request.client else "-"


def _counted(request: Request) -> str:
    """The address a sign-in counts against: an IPv6 one by its /64 (S13.7.5.1)."""
    from ..ratelimit import address_key

    return address_key(_address(request))


def _throttle(request: Request) -> None:
    wait = server(request).password_asks.hit(_counted(request))
    if wait:
        raise too_many(wait, "attempts")


@router.get("/session", response_model=SessionInfo)
def get_session(request: Request, c: Caller = Depends(caller_in_setup)):
    return info(request, c.user, c.admin)


@router.post(
    "/session",
    response_model=SessionInfo,
    responses={202: {"model": TwoStepNeeded}, 401: {}, 403: {}, 429: {}},
)
def sign_in(body: SignIn, request: Request):
    srv = server(request)
    guard = srv.sign_in
    login = body.login.strip().lower()
    address = _address(request)
    locked = guard.locked(address)
    if locked:
        raise too_many(locked, "failed sign-ins from this address")
    delay = guard.delay(login, address)
    if delay:
        time.sleep(delay)
    two_step = None
    with srv.db.tx(unscoped="sign-in") as s:
        user = accounts.by_login(s, login)
        ok = passwords.verify(user.passwordHash if user else None, body.password)
        if not ok:
            count_failure(s, guard, login, address, user)
            failed = True
        else:
            failed = False
            if not user.active:
                raise Problem(403, "account-disabled", "This account is disabled.")
            if passwords.needs_rehash(user.passwordHash):
                user.passwordHash = passwords.hash_password(body.password)
            if twostep.is_on(user):
                # No session until the code: failed codes count toward the same lockout.
                two_step = twostep.start_sign_in(s, user)
            else:
                guard.succeeded(login)
                admin, token = _signed_in(s, user, address=address, svc=srv.services)
    if failed:
        # Committed above: failures and lockouts stay in Activity.
        raise Problem(401, "bad-credentials", "The username or password is not right.")
    if two_step:
        return JSONResponse(TwoStepNeeded(twoStepToken=two_step).model_dump(), status_code=202)
    set_cookie(request, token)
    return info(request, user, admin)


@router.post("/session/two-step", response_model=SessionInfo, responses={401: {}, 429: {}})
def sign_in_code(body: TwoStepCode, request: Request):
    """The second step: a code from the app, or one of the recovery codes (S10.1.6). One code
    at a time for each sign-in, slowed before it is checked, and five wrong ones end the
    sign-in, so the password is needed again (S10.1.6.3)."""
    srv = server(request)
    guard = srv.sign_in
    address = _address(request)
    locked = guard.locked(address)
    if locked:
        raise too_many(locked, "failed sign-ins from this address")
    pending = digest(body.token or "")
    if not guard.checking(pending):
        raise too_many(1, "codes at once for this sign-in")
    try:
        with srv.db.tx(unscoped="sign-in: a two-step code") as s:
            login = twostep.pending_user(s, body.token).username
        delay = guard.delay(login, address)
        if delay:
            time.sleep(delay)
        ended = False
        with srv.db.tx(unscoped="sign-in: a two-step code") as s:
            user = twostep.pending_user(s, body.token)
            if not user.active or user.deleted:
                raise Problem(403, "account-disabled", "This account is disabled.")
            how = twostep.check_code(s, srv.keys.secrets, user, body.code)
            if how is None:
                count_failure(s, guard, login, address, user)
                if guard.code_wrong(pending):
                    twostep.finish_sign_in(s, body.token)
                    ended = True
            else:
                guard.succeeded(login)
                guard.code_done(pending)
                twostep.finish_sign_in(s, body.token)
                # The second step's sign-in, a new address emailed as the first step's is.
                admin, token = _signed_in(
                    s,
                    user,
                    "signin" if how == "code" else "signin.recovery-code",
                    address=address,
                    svc=srv.services,
                )
                if how != "code" and user.email:
                    # A recovery code used is emailed (S10.1.9), with how many are left.
                    left = twostep.codes_left(s, user.id)
                    srv.services.mailer.send(
                        s,
                        Email(
                            user.email,
                            "A sign-in to MoolaKata with a recovery code",
                            (
                                f"Hello {user.displayName},\n\nSomeone signed in as "
                                f"{user.username} with one of your two-step recovery codes; "
                                f"{left} {'is' if left == 1 else 'are'} left. If it was you, "
                                "make new codes in Profile once you have your app again. If it "
                                "wasn't, change your password now and tell an admin.\n"
                            ),
                        ),
                    )
    finally:
        guard.checked(pending)
    if ended:
        raise Problem(401, "two-step-expired", "Too many wrong codes. Sign in again.")
    if how is None:
        raise refuse("code", "code-wrong", "That code isn't right.", 401)
    set_cookie(request, token)
    return info(request, user, admin)


def guarded(request: Request, login: str) -> str:
    """A password asked for outside the sign-in itself (re-authentication, the current
    password, a reactivation request) behind the sign-in's guard: refused while its address is
    locked, slowed for a username that keeps failing. The address it counts against
    (S13.7.5.1)."""
    guard = server(request).sign_in
    address = _address(request)
    locked = guard.locked(address)
    if locked:
        raise too_many(locked, "failed sign-ins from this address")
    delay = guard.delay(login, address)
    if delay:
        time.sleep(delay)
    return address


def count_failure(s, guard, login: str, address: str, user: User | None) -> None:
    """A wrong password or code, counted toward the lockout and recorded in Activity."""
    failures = settings.get(s, "lockoutFailures")
    minutes = settings.get(s, "lockoutMinutes")
    now_locked = guard.failed(login, address, failures, minutes)
    activity.record(
        s,
        "signin.locked" if now_locked else "signin.failed",
        actor=None,
        subject_kind="user" if user else None,
        subject_id=user.id if user else None,
        owner=user.id if user else None,
        for_admins=True,
    )


ADDRESS_DAYS = 30


def _signed_in(
    s, user: User, kind: str = "signin", address: str | None = None, svc=None
) -> tuple[bool, str]:
    admin = accounts.is_admin(s, user.id)
    token = sessions.create(s, user.id, admin, user.needsSetup, address=address)
    user.lastSignInAt = sessions.now()
    activity.record(
        s,
        kind,
        actor=user.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
        for_admins=kind != "signin",
    )
    _note_address(s, user, address, svc)
    return admin, token


def _note_address(s, user: User, address: str | None, svc) -> None:
    """A sign-in from an address not seen in 30 days is emailed to the user (S10.1.9), once
    they have signed in from somewhere before; the addresses seen are kept on the user."""
    import ipaddress

    try:
        ipaddress.ip_address(address or "")
    except ValueError:
        return  # no real address to remember
    t = sessions.now()
    try:
        seen = {k: v for k, v in json.loads(user.recentAddresses or "{}").items()}
    except ValueError:
        seen = {}
    seen = {
        k: v
        for k, v in seen.items()
        if t - dt.datetime.fromisoformat(v) < dt.timedelta(days=ADDRESS_DAYS)
    }
    new = bool(seen) and address not in seen
    seen[address] = t.isoformat()
    user.recentAddresses = json.dumps(seen)
    if new:
        activity.record(
            s,
            "signin.new-address",
            actor=user.id,
            subject_kind="user",
            subject_id=user.id,
            owner=user.id,
        )
        if svc is not None and user.email and not user.needsSetup:
            svc.mailer.send(
                s,
                Email(
                    user.email,
                    "A sign-in to MoolaKata from a new address",
                    (
                        f"Hello {user.displayName},\n\nSomeone signed in as {user.username} "
                        f"from {address}, an address not used in the last {ADDRESS_DAYS} "
                        "days. If it was you, there is nothing to do. If it wasn't, change "
                        "your password now and tell an admin.\n"
                    ),
                ),
            )


@router.delete("/session", status_code=204)
def sign_out(request: Request, c: Caller = Depends(caller_in_setup)):
    """Signing out ends every session of the user at once (S13.7.1)."""
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        sessions.end_all(s, c.id)
        activity.record(s, "signout", actor=c.id, subject_kind="user", subject_id=c.id, owner=c.id)
    srv.events.end_user(c.id, "signed-out")
    set_cookie(request, None)
    return Response(status_code=204)


@router.post("/session/setup", response_model=SessionInfo)
def setup(body: Setup, request: Request, c: Caller = Depends(caller_in_setup)):
    if not c.user.needsSetup:
        raise Problem(409, "setup-done", "This account is already set up.")
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        user = s.get(User, c.id)
        accounts.finish_setup(s, user, body.password, body.email, body.displayName, body.sex)
        sessions.end_all(s, user.id)
        admin = accounts.is_admin(s, user.id)
        token = sessions.create(s, user.id, admin, False)
    set_cookie(request, token)
    return info(request, user, admin)


@router.post("/session/reauth", status_code=204)
def reauth(body: Password, request: Request, c: Caller = Depends(caller_in_setup)):
    """The password again, counted toward the sign-in's lockout (S13.7.2, S13.7.5.1)."""
    srv = server(request)
    _throttle(request)
    address = guarded(request, c.user.username)
    with srv.db.tx(user=c.id) as s:
        user = s.get(User, c.id)
        right = passwords.verify(user.passwordHash, body.password)
        if right:
            row = sessions.find(s, request.cookies.get(sessions.COOKIE)).session
            row.authAt = sessions.now()
        else:
            count_failure(s, srv.sign_in, user.username, address, user)
    if not right:
        raise Problem(401, "password-wrong", "That is not your password.")
    return Response(status_code=204)


@router.post("/password-reset", status_code=204)
def password_reset(body: Login, request: Request):
    """The answer is the same whether or not the user exists (S10.1.5)."""
    srv = server(request)
    _throttle(request)
    with srv.db.tx(unscoped="a password reset asked") as s:
        accounts.request_reset(s, srv.services, body.login)
    return Response(status_code=204)


@router.post("/password-reset/confirm", status_code=204)
def password_reset_confirm(body: TokenPassword, request: Request):
    srv = server(request)
    _throttle(request)
    with srv.db.tx(unscoped="a password reset") as s:
        user = accounts.reset_password(s, srv.services, body.token, body.password)
    srv.events.end_user(user.id, "signed-out")
    return Response(status_code=204)


@router.get("/signup", response_model=SignupOpen)
def signup_open(request: Request):
    srv = server(request)
    with srv.db.read(unscoped="whether sign-up is open") as s:
        on, domains = signup.open_to(s, srv.config.dev)
    return SignupOpen(open=on, domains=domains)


@router.post("/signup", status_code=204, responses={403: {}, 422: {}, 429: {}})
def signup_request(body: SignupForm, request: Request):
    """The answer is the same whether or not the email already has an account (S10.1.4)."""
    srv = server(request)
    _throttle(request)
    with srv.db.tx(unscoped="a sign-up asked") as s:
        signup.request(
            s,
            srv.services,
            body.displayName,
            body.username,
            body.email,
            body.password,
            body.sex,
        )
    return Response(status_code=204)


@router.post("/signup/confirm", response_model=SignupConfirmed)
def signup_confirm(body: Token, request: Request):
    srv = server(request)
    _throttle(request)
    with srv.db.tx(unscoped="a sign-up confirmed") as s:
        req = signup.confirm(s, body.token)
        out = SignupConfirmed(
            displayName=req.displayName, household=settings.get(s, "householdName")
        )
        admins = accounts.admin_ids(s)
    srv.events.publish("signup", {}, users=admins)
    return out


@router.post("/invitations/lookup", response_model=InvitationInfo)
def invitation_lookup(body: Token, request: Request):
    srv = server(request)
    _throttle(request)
    with srv.db.read(unscoped="an invitation looked up") as s:
        user = accounts.peek_invitation(s, body.token)
        return InvitationInfo(
            username=user.username,
            displayName=user.displayName,
            household=settings.get(s, "householdName"),
        )


@router.post("/invitations/accept", response_model=SessionInfo)
def invitation_accept(body: TokenPassword, request: Request):
    srv = server(request)
    _throttle(request)
    with srv.db.tx(unscoped="an invitation accepted") as s:
        user = accounts.accept_invitation(s, body.token, body.password)
        admin = accounts.is_admin(s, user.id)
        token = sessions.create(s, user.id, admin, False)
        user.lastSignInAt = sessions.now()
    set_cookie(request, token)
    return info(request, user, admin)


@router.post("/email-change/confirm", status_code=204)
def email_change_confirm(body: Token, request: Request):
    srv = server(request)
    _throttle(request)
    with srv.db.tx(unscoped="an email change confirmed") as s:
        accounts.confirm_email_change(s, body.token, server(request).services)
    return Response(status_code=204)


@router.post("/reactivation-requests", status_code=204)
def reactivation_request(body: SignIn, request: Request):
    """The same answer whatever the account's state, and a wrong password counted as a
    sign-in's (S10.1.7)."""
    srv = server(request)
    _throttle(request)
    login = body.login.strip().lower()
    address = guarded(request, login)
    with srv.db.tx(unscoped="a reactivation asked") as s:
        if not accounts.ask_reactivation(s, login, body.password):
            count_failure(s, srv.sign_in, login, address, accounts.by_login(s, login))
    return Response(status_code=204)


@router.get(
    "/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def events(request: Request, c: Caller = Depends(caller_quiet)):
    """The live stream (S12.6): what changed, never data. It ends after a few minutes and
    the browser reconnects; it never extends the session."""
    srv = server(request)
    token_hash = c.session.tokenHash
    sub = srv.events.subscribe(c.id, token_hash)

    token = request.cookies.get(sessions.COOKIE)

    def check() -> str | None:
        with srv.db.read(user=c.id) as s:
            found = sessions.find(s, token)
            if found is None:
                return "signed-out"
            if found.ended:
                return "expired"
            user = s.get(User, c.id)
            return None if user and user.active else "disabled"

    async def ended() -> str | None:
        # On a worker thread: a database call on the event loop would hold up every request.
        return await asyncio.to_thread(check)

    hello = {"version": srv.version, "badges": srv.badges(c)}
    return StreamingResponse(
        stream(srv.events, sub, hello, ended, seconds=srv.stream_seconds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
