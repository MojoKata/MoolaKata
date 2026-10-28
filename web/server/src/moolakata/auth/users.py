"""Users and groups (requirements S10.1): the first admin, invitations, password reset and
change, email changes, the active flag, and groups with the built-in Admins group.

Every function works inside the caller's unit of work and records what Activity shows.
"""

import datetime as dt
import json
import re
from dataclasses import dataclass

from sqlalchemy import delete, false, func, select
from sqlalchemy.orm import Session as Db

from .. import activity, clock, ids, settings
from ..config import Config
from ..errors import FieldError, Problem, refuse
from ..mail import Email, Mailer, base_url, link
from ..store.entities.users import Group, OneTimeToken, User, UserGroup
from . import passwords, sessions
from .tokens import digest, new_token

DEFAULT_ADMIN = "admin"
# The password a server made before the welcome (S10.1.2) published for its first admin, which
# reached only the setup step; refused as anyone's new password.
DEFAULT_PASSWORD = "moolakata-setup"  # noqa: S105
INVITATION_DAYS = 7
RESET_HOURS = 1
EMAIL_CHANGE_HOURS = 24
REACTIVATION_DAYS = 7
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def now() -> dt.datetime:
    return clock.now()


# ---------- reading ----------


def admins_group(s: Db) -> Group:
    g = s.scalars(select(Group).where(Group.builtIn == "admins", Group.deleted == false())).first()
    if g is None:
        g = Group(id=ids.new_id("Group"), name="Admins", builtIn="admins")
        s.add(g)
        s.flush()
    return g


def group_ids(s: Db, user_id: str) -> list[str]:
    return list(
        s.scalars(
            select(UserGroup.groupId)
            .join(Group, Group.id == UserGroup.groupId)
            .where(
                UserGroup.userId == user_id, UserGroup.deleted == false(), Group.deleted == false()
            )
        )
    )


def is_admin(s: Db, user_id: str) -> bool:
    """Being an admin is membership of the active Admins group, as an active user."""
    return (
        s.scalar(
            select(func.count())
            .select_from(UserGroup)
            .join(Group, Group.id == UserGroup.groupId)
            .join(User, User.id == UserGroup.userId)
            .where(
                UserGroup.userId == user_id,
                UserGroup.deleted == false(),
                Group.builtIn == "admins",
                Group.active,
                Group.deleted == false(),
                User.active,
                User.deleted == false(),
            )
        )
        > 0
    )


def admin_ids(s: Db) -> list[str]:
    g = admins_group(s)
    return list(
        s.scalars(
            select(User.id)
            .join(UserGroup, UserGroup.userId == User.id)
            .where(
                UserGroup.groupId == g.id,
                UserGroup.deleted == false(),
                User.active,
                User.deleted == false(),
                User.linkId.is_(None),
            )
        )
    )


def by_login(s: Db, login: str) -> User | None:
    """A local user by username or email, case-insensitively."""
    login = login.strip().lower()
    if not login:
        return None
    col = User.email if "@" in login else User.username
    return s.scalars(
        select(User).where(func.lower(col) == login, User.deleted == false(), User.linkId.is_(None))
    ).first()


def invited(s: Db, user_id: str) -> bool:
    return (
        s.scalar(
            select(func.count())
            .select_from(OneTimeToken)
            .where(
                OneTimeToken.userId == user_id,
                OneTimeToken.purpose == "invitation",
                OneTimeToken.expiresAt > now(),
            )
        )
        > 0
    )


# ---------- the first admin (S10.1.2) ----------


def has_users(s: Db) -> bool:
    return s.scalar(select(func.count()).select_from(User)) > 0


def make_first_admin(s: Db, display_name: str, sex: str, email: str, password: str) -> User:
    """The welcome's last step: `admin`, with the name, sex, email address and password given,
    made only while the server has no users, and an admin at once (S10.1.2)."""
    from .. import people

    if has_users(s):
        raise Problem(409, "admin-exists", "This server's admin is set up already: sign in.")
    errors = _setup_problems(s, password, email, None, sex)
    name = (display_name or "").strip()
    if not name or len(name) > 80:
        errors.insert(
            0, FieldError("displayName", "name-invalid", "Your name, 80 characters at most.")
        )
    if sex is None:
        errors.append(FieldError("sex", "sex-invalid", "Female or male."))
    if errors:
        raise Problem(422, errors[0].code, errors[0].message, errors)
    at = now()
    u = User(
        id=ids.new_id("User"),
        personId=people.make(s, name, sex).id,
        username=DEFAULT_ADMIN,
        displayName=name,
        email=email.strip().lower(),
        passwordHash=passwords.hash_password(password),
        passwordChangedAt=at,
        needsSetup=False,
        alertEmails="each",
    )
    s.add(u)
    s.flush()
    s.add(UserGroup(userId=u.id, groupId=admins_group(s).id, createdAt=at))
    activity.record(
        s,
        "user.created-first-admin",
        actor=u.id,
        subject_kind="user",
        subject_id=u.id,
        owner=u.id,
        for_admins=True,
    )
    return u


def _setup_problems(
    s: Db, password: str, email: str, user_id: str | None, sex: str | None
) -> list[FieldError]:
    from .. import people

    errors = []
    if sex is not None and sex not in people.SEXES:
        errors.append(FieldError("sex", "sex-invalid", "Female or male."))
    min_len = settings.get(s, "passwordMinLength")
    why = passwords.problem(password, min_len)
    if why:
        errors.append(FieldError("password", *why))
    if password == DEFAULT_PASSWORD:
        errors.append(
            FieldError(
                "password", "password-is-default", "Choose a password other than the published one."
            )
        )
    return errors + _email_problems(s, email, user_id)


def finish_setup(
    s: Db,
    user: User,
    password: str,
    email: str,
    display_name: str | None,
    sex: str | None = None,
) -> None:
    """The setup step of an admin a server made before the welcome, with the published
    password (S10.1.2): a password, an email address, a name and a sex."""
    from .. import people

    errors = _setup_problems(s, password, email, user.id, sex)
    if errors:
        raise Problem(422, errors[0].code, errors[0].message, errors)
    user.passwordHash = passwords.hash_password(password)
    user.passwordChangedAt = now()
    user.email = email.strip().lower()
    me = people.of_user(s, user.id)
    if display_name and display_name.strip():
        user.displayName = display_name.strip()
        people.change(s, me, {"name": user.displayName})
    if sex is not None:
        people.change(s, me, {"sex": sex})
    user.needsSetup = False
    activity.record(
        s,
        "user.setup",
        actor=user.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
        for_admins=True,
    )


# ---------- checks ----------


def _email_problems(s: Db, email: str, user_id: str | None) -> list[FieldError]:
    email = (email or "").strip().lower()
    if not EMAIL.match(email) or len(email) > 254:
        return [FieldError("email", "email-invalid", "Enter an email address.")]
    other = s.scalars(
        select(User).where(
            func.lower(User.email) == email, User.deleted == false(), User.linkId.is_(None)
        )
    ).first()
    if other is not None and other.id != user_id:
        return [FieldError("email", "email-taken", "Another user has this email address.")]
    return []


def _username_problems(s: Db, username: str) -> list[FieldError]:
    if not USERNAME.match(username):
        return [
            FieldError(
                "username",
                "username-invalid",
                "2 to 32 lowercase letters, digits, dots, dashes or underscores, "
                "starting with a letter or digit.",
            )
        ]
    if by_login(s, username) is not None:
        return [FieldError("username", "username-taken", "This username is taken.")]
    return []


def _name_problems(name: str, field: str = "displayName") -> list[FieldError]:
    name = (name or "").strip()
    if not name or len(name) > 80:
        return [FieldError(field, "name-invalid", "Enter a name of up to 80 characters.")]
    return []


def _raise(errors: list[FieldError]) -> None:
    if errors:
        raise Problem(422, errors[0].code, errors[0].message, errors)


# ---------- invitations (S10.1.3) ----------


@dataclass
class Services:
    config: Config
    mailer: Mailer


def _issue(s: Db, user: User, purpose: str, lifetime: dt.timedelta, data: str | None = None) -> str:
    s.execute(
        delete(OneTimeToken).where(OneTimeToken.userId == user.id, OneTimeToken.purpose == purpose)
    )
    token, token_hash = new_token()
    t = now()
    s.add(
        OneTimeToken(
            tokenHash=token_hash,
            purpose=purpose,
            userId=user.id,
            data=data,
            createdAt=t,
            expiresAt=t + lifetime,
        )
    )
    s.flush()
    return token


def _take(s: Db, token: str, purpose: str) -> OneTimeToken:
    """A token is used once: found, checked and removed."""
    row = s.get(OneTimeToken, digest(token or ""))
    if row is None or row.purpose != purpose or row.expiresAt <= now():
        if row is not None and row.expiresAt <= now():
            s.delete(row)
        raise Problem(404, "link-not-valid", "This link has expired or was already used.")
    return row


def peek_invitation(s: Db, token: str) -> User:
    row = s.get(OneTimeToken, digest(token or ""))
    if row is None or row.purpose != "invitation" or row.expiresAt <= now():
        raise Problem(404, "link-not-valid", "This link has expired or was already used.")
    return s.get(User, row.userId)


def invite(
    s: Db,
    svc: Services,
    by: User,
    display_name: str,
    username: str,
    email: str,
    groups: list[str],
    sex: str | None = None,
    user_id: str | None = None,
) -> User:
    from .. import people

    username = (username or "").strip().lower()
    errors = (
        _name_problems(display_name)
        + _username_problems(s, username)
        + _email_problems(s, email, None)
    )
    if sex not in people.SEXES:
        errors.append(FieldError("sex", "sex-invalid", "Female or male."))
    known = {g.id for g in s.scalars(select(Group).where(Group.deleted == false()))}
    if any(g not in known for g in groups):
        errors.append(FieldError("groupIds", "group-unknown", "Choose existing groups."))
    _raise(errors)
    u = User(
        id=user_id or ids.new_id("User"),
        personId=people.for_new_user(s, display_name.strip(), sex, by.id).id,
        username=username,
        displayName=display_name.strip(),
        email=email.strip().lower(),
    )
    s.add(u)
    s.flush()
    for g in dict.fromkeys(groups):
        s.add(UserGroup(userId=u.id, groupId=g, createdAt=now()))
    if admins_group(s).id in groups:
        u.alertEmails = "each"
    _send_invitation(s, svc, by, u)
    activity.record(
        s,
        "user.invited",
        actor=by.id,
        subject_kind="user",
        subject_id=u.id,
        owner=u.id,
        for_admins=True,
    )
    return u


def _send_invitation(s: Db, svc: Services, by: User, u: User) -> None:
    base_url(s, svc.config)  # refuses before a token is made when there is no public URL
    token = _issue(s, u, "invitation", dt.timedelta(days=INVITATION_DAYS))
    url = link(s, svc.config, "/ui/welcome", token)
    household = settings.get(s, "householdName")
    svc.mailer.send(
        s,
        Email(
            u.email or "",
            f"{by.displayName} invited you to MoolaKata",
            (
                f"Hello {u.displayName},\n\n"
                f"{by.displayName} invited you to {household}'s MoolaKata, where the "
                "household keeps its accounts, budgets and plans.\n\n"
                f"Your username is {u.username}. Choose your password here:\n\n{url}\n\n"
                f"The link works once, for {INVITATION_DAYS} days.\n"
            ),
            keep=dt.timedelta(days=INVITATION_DAYS),
        ),
    )


def resend_invitation(s: Db, svc: Services, by: User, user: User) -> None:
    if user.passwordHash is not None:
        raise refuse(None, "already-joined", f"{user.displayName} has already joined.", 409)
    _send_invitation(s, svc, by, user)
    activity.record(
        s,
        "user.invitation-resent",
        actor=by.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
        for_admins=True,
    )


def accept_invitation(s: Db, token: str, password: str) -> User:
    row = _take(s, token, "invitation")
    user = s.get(User, row.userId)
    if user is None or user.deleted or not user.active:
        raise Problem(404, "link-not-valid", "This link has expired or was already used.")
    why = passwords.problem(password, settings.get(s, "passwordMinLength"))
    if why:
        raise refuse("password", *why)
    s.delete(row)
    user.passwordHash = passwords.hash_password(password)
    user.passwordChangedAt = now()
    activity.record(
        s,
        "user.joined",
        actor=user.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
        for_admins=True,
    )
    return user


# ---------- passwords (S10.1.5) ----------


def request_reset(s: Db, svc: Services, login: str) -> None:
    """Always answered the same way: whether the user exists is never revealed."""
    user = by_login(s, login)
    if (
        user is None
        or not user.active
        or user.passwordHash is None
        or not user.email
        or user.needsSetup
    ):
        return
    token = _issue(s, user, "reset", dt.timedelta(hours=RESET_HOURS))
    url = link(s, svc.config, "/ui/reset", token)
    svc.mailer.send(
        s,
        Email(
            user.email,
            "Reset your MoolaKata password",
            (
                f"Hello {user.displayName},\n\n"
                f"Someone asked to reset the password for {user.username}. If it was you, choose a "
                f"new one here:\n\n{url}\n\nThe link works once, for an hour. If it wasn't you, "
                f"ignore this email: your password stays as it is.\n"
            ),
            keep=dt.timedelta(hours=RESET_HOURS),
        ),
    )


def reset_password(s: Db, svc: Services, token: str, password: str) -> User:
    row = _take(s, token, "reset")
    user = s.get(User, row.userId)
    if user is None or user.deleted or not user.active:
        raise Problem(404, "link-not-valid", "This link has expired or was already used.")
    why = passwords.problem(password, settings.get(s, "passwordMinLength"))
    if why:
        raise refuse("password", *why)
    s.delete(row)
    _set_password(s, svc, user, password, "user.password-reset")
    return user


def change_password(s: Db, svc: Services, user: User, current: str, new: str) -> None:
    if not passwords.verify(user.passwordHash, current):
        raise refuse("currentPassword", "password-wrong", "That is not your current password.")
    why = passwords.problem(new, settings.get(s, "passwordMinLength"))
    if why:
        raise refuse("newPassword", *why)
    _set_password(s, svc, user, new, "user.password-changed")


def _set_password(s: Db, svc: Services, user: User, password: str, kind: str) -> None:
    user.passwordHash = passwords.hash_password(password)
    user.passwordChangedAt = now()
    sessions.end_all(s, user.id)
    from .. import tokens

    revoked = tokens.revoke_all(s, user.id)
    activity.record(
        s,
        kind,
        actor=user.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
        for_admins=True,
    )
    if user.email:
        svc.mailer.send(
            s,
            Email(
                user.email,
                "Your MoolaKata password was changed",
                (
                    f"Hello {user.displayName},\n\nThe password for {user.username} was "
                    "just changed, and every session was signed out"
                    + (f" and its {revoked} access tokens revoked" if revoked > 1 else "")
                    + (" and its access token revoked" if revoked == 1 else "")
                    + ". If you didn't do this, ask an admin to reset your account.\n"
                ),
            ),
        )


# ---------- email changes (S10.1.5) ----------


def request_email_change(s: Db, svc: Services, user: User, email: str) -> None:
    """A new address takes effect only when a link sent to it is opened."""
    _raise(_email_problems(s, email, user.id))
    email = email.strip().lower()
    token = _issue(s, user, "email-change", dt.timedelta(hours=EMAIL_CHANGE_HOURS), email)
    url = link(s, svc.config, "/ui/confirm-email", token)
    svc.mailer.send(
        s,
        Email(
            email,
            "Confirm your new email address for MoolaKata",
            (
                f"Hello {user.displayName},\n\nTo use this address for {user.username} on "
                f"MoolaKata, open this link:\n\n{url}\n\nIt works once, for a day. Until then "
                "your old address stays in use.\n"
            ),
            keep=dt.timedelta(hours=EMAIL_CHANGE_HOURS),
        ),
    )


def confirm_email_change(s: Db, token: str, svc: Services | None = None) -> User:
    row = _take(s, token, "email-change")
    user = s.get(User, row.userId)
    if user is None or user.deleted or not user.active:
        raise Problem(404, "link-not-valid", "This link has expired or was already used.")
    _raise(_email_problems(s, row.data or "", user.id))
    s.delete(row)
    old = user.email
    user.email = row.data
    if svc is not None and old and old != user.email:
        # The old address is told (S10.1.9), so a change the person didn't make is noticed.
        svc.mailer.send(
            s,
            Email(
                old,
                "Your MoolaKata email address was changed",
                (
                    f"Hello {user.displayName},\n\nThe email address for {user.username} on "
                    f"MoolaKata is now {user.email}. This address no longer receives its "
                    "emails.\n\nIf you did not make this change, tell an admin at once.\n"
                ),
            ),
        )
    activity.record(
        s,
        "user.email-changed",
        actor=user.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
        for_admins=True,
        detail={"fields": ["email"]},
    )
    return user


# ---------- the active flag (S10.1.7) ----------


def _last_admin_guard(s: Db, user_id: str) -> None:
    if is_admin(s, user_id) and len(admin_ids(s)) <= 1:
        raise refuse(
            "active",
            "last-admin",
            "This is the last active admin. Make someone else an admin first.",
            409,
        )


def set_active(s: Db, svc: Services, by: User, user: User, active: bool) -> list[str]:
    """Switch a user off or on. Off ends their sessions at once; returns the ended ones."""
    if user.active == active:
        return []
    ended: list[str] = []
    if not active:
        _last_admin_guard(s, user.id)
        user.active = False
        ended = sessions.end_all(s, user.id)
        activity.record(
            s,
            "user.deactivated",
            actor=by.id,
            subject_kind="user",
            subject_id=user.id,
            owner=user.id,
            for_admins=True,
        )
    else:
        user.active = True
        user.reactivationAskedAt = None
        activity.record(
            s,
            "user.reactivated",
            actor=by.id,
            subject_kind="user",
            subject_id=user.id,
            owner=user.id,
            for_admins=True,
        )
        if user.email and user.passwordHash:
            svc.mailer.send(
                s,
                Email(
                    user.email,
                    "Your MoolaKata account is active again",
                    (
                        f"Hello {user.displayName},\n\n{by.displayName} made your account active "
                        "again. You can sign in as before.\n"
                    ),
                ),
            )
    return ended


def ask_reactivation(s: Db, login: str, password: str) -> bool:
    """From the *account is disabled* screen, once a week (S10.1.7). Whether the password was
    right; the request is recorded only for a disabled account not asked for in the past week,
    and the asker is told the same either way."""
    user = by_login(s, login)
    if not passwords.verify(user.passwordHash if user else None, password):
        return False
    if user.active or (
        user.reactivationAskedAt
        and now() - user.reactivationAskedAt < dt.timedelta(days=REACTIVATION_DAYS)
    ):
        return True
    user.reactivationAskedAt = now()
    activity.record(
        s,
        "user.reactivation-asked",
        actor=user.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
        for_admins=True,
    )
    return True


def update_user(
    s: Db, by: User, user: User, display_name: str | None, email: str | None
) -> list[str]:
    """An admin's edit. An email is fixed directly only while the invitation is pending;
    afterwards it changes by the user's own confirmed request."""
    fields = []
    if display_name is not None and display_name.strip() != user.displayName:
        _raise(_name_problems(display_name))
        user.displayName = display_name.strip()
        fields.append("displayName")
    if email is not None and email.strip().lower() != (user.email or ""):
        if user.passwordHash is not None:
            raise refuse(
                "email",
                "email-change-by-user",
                "Once a user has joined, they change their own email address.",
                409,
            )
        _raise(_email_problems(s, email, user.id))
        user.email = email.strip().lower()
        fields.append("email")
    if fields:
        activity.record(
            s,
            "user.updated",
            actor=by.id,
            subject_kind="user",
            subject_id=user.id,
            owner=user.id,
            for_admins=True,
            detail={"fields": fields},
        )
    return fields


# ---------- groups (S10.1.8) ----------


def members(s: Db, group_id: str) -> list[str]:
    return list(
        s.scalars(
            select(UserGroup.userId).where(
                UserGroup.groupId == group_id, UserGroup.deleted == false()
            )
        )
    )


def create_group(
    s: Db, by: User, name: str, member_ids: list[str], group_id: str | None = None
) -> Group:
    name = (name or "").strip()
    _raise(_name_problems(name, "name") + _group_name_taken(s, name, None))
    g = Group(id=group_id or ids.new_id("Group"), name=name)
    s.add(g)
    s.flush()
    set_members(s, by, g, member_ids, record=False)
    activity.record(
        s,
        "group.created",
        actor=by.id,
        subject_kind="group",
        subject_id=g.id,
        for_admins=True,
        detail={"members": len(set(member_ids))},
    )
    return g


def _group_name_taken(s: Db, name: str, group_id: str | None) -> list[FieldError]:
    other = s.scalars(
        select(Group).where(func.lower(Group.name) == name.lower(), Group.deleted == false())
    ).first()
    if other is not None and other.id != group_id:
        return [FieldError("name", "name-taken", "Another group has this name.")]
    return []


def update_group(
    s: Db, by: User, g: Group, name: str | None, active: bool | None, member_ids: list[str] | None
) -> None:
    fields = []
    if name is not None and name.strip() != g.name:
        if g.builtIn:
            raise refuse("name", "built-in", "The Admins group keeps its name.", 409)
        _raise(_name_problems(name, "name") + _group_name_taken(s, name.strip(), g.id))
        g.name = name.strip()
        fields.append("name")
    if active is not None and active != g.active:
        if g.builtIn:
            raise refuse("active", "built-in", "The Admins group is always active.", 409)
        g.active = active
        fields.append("active")
    if fields:
        activity.record(
            s,
            "group.updated",
            actor=by.id,
            subject_kind="group",
            subject_id=g.id,
            for_admins=True,
            detail={"fields": fields},
        )
    if member_ids is not None:
        set_members(s, by, g, member_ids)


def set_members(s: Db, by: User, g: Group, member_ids: list[str], record: bool = True) -> None:
    wanted = set(member_ids)
    users = {
        u.id: u
        for u in s.scalars(
            select(User).where(User.id.in_(wanted), User.deleted == false(), User.linkId.is_(None))
        )
    }
    if set(users) != wanted:
        raise refuse("memberIds", "user-unknown", "Choose existing users.")
    current = {m.userId: m for m in s.scalars(select(UserGroup).where(UserGroup.groupId == g.id))}
    added = [u for u in wanted if u not in current or current[u].deleted]
    removed = [u for u, m in current.items() if u not in wanted and not m.deleted]
    if g.builtIn == "admins" and removed:
        remaining = [a for a in admin_ids(s) if a not in removed]
        added_active = [u for u in added if users[u].active]
        if not remaining and not added_active:
            raise refuse(
                "memberIds",
                "last-admin",
                "The Admins group must keep at least one active admin.",
                409,
            )
    for u in added:
        if u in current:
            current[u].restore()
        else:
            s.add(UserGroup(userId=u, groupId=g.id, createdAt=now()))
    for u in removed:
        current[u].mark_deleted(by.id, now())
    s.flush()
    if record and (added or removed):
        activity.record(
            s,
            "group.members",
            actor=by.id,
            subject_kind="group",
            subject_id=g.id,
            for_admins=True,
            detail={"added": len(added), "removed": len(removed)},
        )


def set_user_groups(s: Db, by: User, user: User, group_ids_wanted: list[str]) -> None:
    """Set one user's groups from the user's side (Users and Groups)."""
    groups = {g.id: g for g in s.scalars(select(Group).where(Group.deleted == false()))}
    if any(g not in groups for g in group_ids_wanted):
        raise refuse("groupIds", "group-unknown", "Choose existing groups.")
    have = set(group_ids(s, user.id))
    for gid in set(group_ids_wanted) ^ have:
        g = groups[gid]
        others = [m for m in members(s, gid) if m != user.id]
        set_members(s, by, g, others + ([user.id] if gid in group_ids_wanted else []))


def detail(entry_detail: str) -> dict:
    return json.loads(entry_detail or "{}")
