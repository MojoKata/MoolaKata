"""Sign-up (requirements S10.1.4): when an admin turns it on, a person asks for an account
with their name, email, a username and a password; confirms the email from a link; and waits
until an admin approves or rejects the request. Approval makes the user.

Whether an email address already has an account is never revealed: the answer to a request
is the same either way, and only a new address gets a link.
"""

import datetime as dt

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session as Db

from .. import activity, clock, ids, settings
from ..errors import FieldError, Problem, refuse, refuse_all
from ..mail import Email, link
from ..store.entities.users import SignupRequest, User, UserGroup
from . import passwords
from .tokens import digest, new_token
from .users import (
    EMAIL,
    Services,
    _name_problems,
    _username_problems,
    admins_group,
    by_login,
)

CONFIRM_HOURS = 24


def open_to(s: Db, dev: bool) -> tuple[bool, list[str]]:
    """Whether sign-up is on, and the email domains it is limited to. It needs SMTP and the
    public URL its links are built from; dev mode writes its emails to the folder."""
    ready = dev or bool(settings.get(s, "smtpHost") and settings.get(s, "publicUrl"))
    on = bool(settings.get(s, "signupEnabled") and ready)
    return on, settings.get(s, "signupDomains") if on else []


def _waiting_for(s: Db, column, value: str) -> bool:
    return (
        s.scalar(
            select(func.count())
            .select_from(SignupRequest)
            .where(
                func.lower(column) == value,
                SignupRequest.deleted == false(),
                SignupRequest.status.in_(("waiting",))
                | (
                    (SignupRequest.status == "confirming") & (SignupRequest.confirmBy > clock.now())
                ),
            )
        )
        > 0
    )


def request(
    s: Db,
    svc: Services,
    display_name: str,
    username: str,
    email: str,
    password: str,
    sex: str | None = None,
) -> None:
    from .. import people

    on, domains = open_to(s, svc.config.dev)
    if not on:
        raise Problem(403, "signup-off", "Sign-up is not open on this server.")
    username = (username or "").strip().lower()
    email = (email or "").strip().lower()
    errors = _name_problems(display_name) + _username_problems(s, username)
    if not username_errors(errors) and _waiting_for(s, SignupRequest.username, username):
        errors.append(FieldError("username", "username-taken", "That username is taken."))
    if not EMAIL.fullmatch(email):
        errors.append(FieldError("email", "email-invalid", "Enter an email address."))
    elif domains and email.rsplit("@", 1)[1] not in domains:
        errors.append(
            FieldError(
                "email",
                "email-domain",
                "Sign-up is open to addresses at " + ", ".join(domains) + ".",
            )
        )
    why = passwords.problem(password, settings.get(s, "passwordMinLength"))
    if why:
        errors.append(FieldError("password", *why))
    if sex not in people.SEXES:
        errors.append(FieldError("sex", "sex-invalid", "Female or male."))
    refuse_all(errors)
    # Hashed before the address is looked up, so a known address takes as long (S10.1.4.1).
    password_hash = passwords.hash_password(password)
    if by_login(s, email) is not None or _waiting_for(s, SignupRequest.email, email):
        # The same answer as a new address; nothing is sent.
        return
    token, token_hash = new_token()
    req = SignupRequest(
        id=ids.new_id("Sgnup"),
        displayName=display_name.strip(),
        username=username,
        email=email,
        passwordHash=password_hash,
        sex=sex,
        confirmTokenHash=token_hash,
        confirmBy=clock.now() + dt.timedelta(hours=CONFIRM_HOURS),
    )
    s.add(req)
    s.flush()
    url = link(s, svc.config, "/ui/signup/confirm", token)
    household = settings.get(s, "householdName")
    svc.mailer.send(
        s,
        Email(
            email,
            "Confirm your email for MoolaKata",
            (
                f"Hello {req.displayName},\n\nYou asked for an account on {household}'s "
                f"MoolaKata. Confirm this address here:\n\n{url}\n\nThe link works once, for "
                f"{CONFIRM_HOURS} hours. An admin then approves or rejects the request, and "
                "you'll get an email either way. If you didn't ask, ignore this email.\n"
            ),
            keep=dt.timedelta(hours=CONFIRM_HOURS),
        ),
    )


def username_errors(errors: list[FieldError]) -> bool:
    return any(e.field == "username" for e in errors)


def confirm(s: Db, token: str) -> SignupRequest:
    req = s.scalars(
        select(SignupRequest).where(
            SignupRequest.confirmTokenHash == digest(token or ""),
            SignupRequest.deleted == false(),
        )
    ).first()
    if req is None or req.status != "confirming" or req.confirmBy <= clock.now():
        raise Problem(404, "link-not-valid", "This link has expired or was already used.")
    req.status = "waiting"
    req.confirmedAt = clock.now()
    req.confirmTokenHash = None
    activity.record(
        s,
        "signup.requested",
        actor=None,
        for_admins=True,
        detail={"name": req.displayName},
    )
    return req


def waiting(s: Db) -> list[SignupRequest]:
    return list(
        s.scalars(
            select(SignupRequest)
            .where(SignupRequest.status == "waiting", SignupRequest.deleted == false())
            .order_by(SignupRequest.confirmedAt)
        )
    )


def _waiting_request(s: Db, request_id: str) -> SignupRequest:
    req = s.get(SignupRequest, request_id)
    if req is None or req.deleted or req.status != "waiting":
        raise Problem(404, "not-found", "That request is not waiting for a decision.")
    return req


def approve(s: Db, svc: Services, by: User, request_id: str, group_ids: list[str]) -> User:
    from ..store.entities.users import Group

    req = _waiting_request(s, request_id)
    errors = _username_problems(s, req.username)
    if errors:
        raise refuse(
            None,
            "username-taken",
            f"The username {req.username} was taken since the request was made: reject it, "
            "and ask them to choose another.",
            409,
        )
    if by_login(s, req.email) is not None:
        raise refuse(None, "email-taken", f"{req.email} already has an account.", 409)
    known = {g.id for g in s.scalars(select(Group).where(Group.deleted == false()))}
    if any(g not in known for g in group_ids):
        raise refuse("groupIds", "group-unknown", "Choose existing groups.")
    from .. import people

    t = clock.now()
    u = User(
        id=ids.new_id("User"),
        personId=people.for_new_user(s, req.displayName, req.sex, by.id).id,
        username=req.username,
        displayName=req.displayName,
        email=req.email,
        passwordHash=req.passwordHash,
        passwordChangedAt=t,
    )
    s.add(u)
    s.flush()
    for g in dict.fromkeys(group_ids):
        s.add(UserGroup(userId=u.id, groupId=g, createdAt=t))
    if admins_group(s).id in group_ids:
        u.alertEmails = "each"
    req.status, req.decidedAt, req.decidedById, req.userId = "approved", t, by.id, u.id
    activity.record(
        s,
        "signup.approved",
        actor=by.id,
        subject_kind="user",
        subject_id=u.id,
        owner=u.id,
        for_admins=True,
    )
    url = link(s, svc.config, "/ui/signin")
    svc.mailer.send(
        s,
        Email(
            u.email,
            "Your MoolaKata account is ready",
            (
                f"Hello {u.displayName},\n\n{by.displayName} approved your request. Sign in "
                f"as {u.username} with the password you chose:\n\n{url}\n"
            ),
        ),
    )
    return u


def reject(s: Db, svc: Services, by: User, request_id: str) -> None:
    req = _waiting_request(s, request_id)
    req.status, req.decidedAt, req.decidedById = "rejected", clock.now(), by.id
    activity.record(
        s,
        "signup.rejected",
        actor=by.id,
        for_admins=True,
        detail={"name": req.displayName},
    )
    household = settings.get(s, "householdName")
    svc.mailer.send(
        s,
        Email(
            req.email,
            "Your MoolaKata request",
            (
                f"Hello {req.displayName},\n\nYour request for an account on {household}'s "
                "MoolaKata was not approved.\n"
            ),
        ),
    )
