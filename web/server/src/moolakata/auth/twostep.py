"""Two-step sign-in (requirements S10.1.6): a TOTP code from an authenticator app after the
password, ten recovery codes shown once, and an admin's reset as the last resort.

TOTP is RFC 6238 as every authenticator app reads it: SHA-1, six digits, 30-second steps, a
step either side accepted for clocks that drift, and no step accepted twice. The seed is a
secret (S14.4), sealed on the user's record; a seed being set up is sealed apart until a
code from it is confirmed.
"""

import base64
import datetime as dt
import hashlib
import hmac
import secrets
import struct
import urllib.parse

import segno
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as Db

from .. import activity, clock, settings
from ..errors import Problem, refuse
from ..mail import Email
from ..store.entities.users import OneTimeToken, RecoveryCode, User
from ..store.repos import secrets as secret_repo
from . import sessions
from .tokens import digest, new_token

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
RECOVERY_CODES = 10
SIGN_IN_MINUTES = 5
SEED = "totp"
PENDING_SEED = "totpPending"
# Recovery codes read aloud and typed easily: no 0/O, 1/I/L.
CODE_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"


def _step(at: dt.datetime | None = None) -> int:
    return int((at or clock.now()).timestamp()) // STEP_SECONDS


def code_at(seed: str, step: int) -> str:
    key = base64.b32decode(seed + "=" * (-len(seed) % 8))
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def matching_step(seed: str, code: str, after: int | None) -> int | None:
    """The step a code is good for, near now and later than the last one accepted."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = _step()
    for step in range(now - DRIFT_STEPS, now + DRIFT_STEPS + 1):
        if (after is None or step > after) and hmac.compare_digest(code_at(seed, step), code):
            return step
    return None


def new_seed() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def uri(seed: str, account: str, issuer: str) -> str:
    label = urllib.parse.quote(f"{issuer}:{account}")
    query = urllib.parse.urlencode(
        {"secret": seed, "issuer": issuer, "digits": DIGITS, "period": STEP_SECONDS}
    )
    return f"otpauth://totp/{label}?{query}"


def qr_image(text: str) -> str:
    """The QR code as an SVG data URI, dark on white whatever the theme, for an <img>."""
    return segno.make(text, error="m").svg_data_uri(scale=4, border=4, dark="#000", light="#fff")


def is_on(user: User) -> bool:
    return user.twoStepAt is not None


# ---------- recovery codes ----------


def _normal(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def _new_codes(s: Db, user: User) -> list[str]:
    s.execute(delete(RecoveryCode).where(RecoveryCode.userId == user.id))
    codes = []
    for _ in range(RECOVERY_CODES):
        # 16 characters of a 31-letter alphabet: about 79 bits, enough that a hash of one
        # cannot be searched (S10.1.6.2).
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(16))
        codes.append("-".join(raw[i : i + 4] for i in range(0, 16, 4)))
        s.add(RecoveryCode(codeHash=digest(_normal(raw)), userId=user.id, createdAt=clock.now()))
    s.flush()
    return codes


def codes_left(s: Db, user_id: str) -> int:
    return s.scalar(
        select(func.count()).select_from(RecoveryCode).where(RecoveryCode.userId == user_id)
    )


def _use_recovery_code(s: Db, user: User, code: str) -> bool:
    row = s.scalars(
        select(RecoveryCode).where(RecoveryCode.codeHash == digest(_normal(code)))
    ).first()
    if row is None or row.userId != user.id:
        return False
    s.delete(row)
    return True


# ---------- turning it on and off (Profile) ----------


def begin(s: Db, key: bytes, user: User) -> str:
    """A new seed, sealed apart until a code from it is confirmed."""
    if is_on(user):
        raise refuse(None, "two-step-on", "Two-step sign-in is already on.", 409)
    seed = new_seed()
    secret_repo.put(s, key, "User", user.id, PENDING_SEED, seed, user.id)
    return seed


def confirm(s: Db, svc, key: bytes, user: User, code: str) -> list[str]:
    seed = secret_repo.use(s, key, "User", user.id, PENDING_SEED)
    if seed is None:
        raise refuse(None, "two-step-not-started", "Start setting up two-step sign-in first.", 409)
    step = matching_step(seed, code, None)
    if step is None:
        raise refuse(
            "code",
            "code-wrong",
            "That code isn't right. Check the app shows MoolaKata, and the phone's clock.",
        )
    secret_repo.put(s, key, "User", user.id, SEED, seed, user.id)
    secret_repo.remove(s, "User", user.id, PENDING_SEED)
    user.twoStepAt = clock.now()
    user.totpLastStep = step
    codes = _new_codes(s, user)
    activity.record(
        s,
        "user.two-step-on",
        actor=user.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
        for_admins=True,
    )
    _tell(s, svc, user, "turned on", "Each sign-in now asks for a code from your app.")
    return codes


def new_recovery_codes(s: Db, user: User) -> list[str]:
    if not is_on(user):
        raise refuse(None, "two-step-off", "Two-step sign-in is off.", 409)
    codes = _new_codes(s, user)
    activity.record(
        s,
        "user.recovery-codes",
        actor=user.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
    )
    return codes


def turn_off(s: Db, svc, user: User, by: User) -> None:
    """By the user in Profile, or by an admin as the last resort."""
    if not is_on(user):
        raise refuse(None, "two-step-off", "Two-step sign-in is off.", 409)
    user.twoStepAt = None
    user.totpLastStep = None
    secret_repo.remove(s, "User", user.id, SEED)
    secret_repo.remove(s, "User", user.id, PENDING_SEED)
    s.execute(delete(RecoveryCode).where(RecoveryCode.userId == user.id))
    by_admin = by.id != user.id
    activity.record(
        s,
        "user.two-step-reset" if by_admin else "user.two-step-off",
        actor=by.id,
        subject_kind="user",
        subject_id=user.id,
        owner=user.id,
        for_admins=True,
    )
    if by_admin:
        # Whoever holds the password alone could sign in now: their sessions end too.
        sessions.end_all(s, user.id)
    _tell(
        s,
        svc,
        user,
        "turned off",
        (
            f"{by.displayName}, an admin, turned it off for you. Sign in with your password, "
            "and turn it on again in Profile."
            if by_admin
            else "Signing in now needs only your password."
        ),
    )


def _tell(s: Db, svc, user: User, what: str, more: str) -> None:
    if not user.email:
        return
    svc.mailer.send(
        s,
        Email(
            user.email,
            f"Two-step sign-in was {what}",
            (
                f"Hello {user.displayName},\n\nTwo-step sign-in for {user.username} on "
                f"{settings.get(s, 'serverName')} was just {what}. {more}\n\n"
                "If you didn't do this, tell an admin.\n"
            ),
        ),
    )


# ---------- signing in ----------


def start_sign_in(s: Db, user: User) -> str:
    """The password was right: a short-lived token carries the sign-in to the code."""
    s.execute(
        delete(OneTimeToken).where(
            OneTimeToken.userId == user.id, OneTimeToken.purpose == "two-step"
        )
    )
    token, token_hash = new_token()
    t = clock.now()
    s.add(
        OneTimeToken(
            tokenHash=token_hash,
            purpose="two-step",
            userId=user.id,
            createdAt=t,
            expiresAt=t + dt.timedelta(minutes=SIGN_IN_MINUTES),
        )
    )
    s.flush()
    return token


def pending_user(s: Db, token: str) -> User:
    row = s.scalars(
        select(OneTimeToken).where(OneTimeToken.tokenHash == digest(token or ""))
    ).first()
    if row is None or row.purpose != "two-step" or row.expiresAt <= clock.now():
        if row is not None and row.expiresAt <= clock.now():
            s.delete(row)
        raise Problem(401, "two-step-expired", "That took too long. Sign in again.")
    return s.get(User, row.userId)


def check_code(s: Db, key: bytes, user: User, code: str) -> str | None:
    """Which way the code was good ("code" or "recovery-code"), or None."""
    seed = secret_repo.use(s, key, "User", user.id, SEED)
    if seed is not None:
        step = matching_step(seed, code, user.totpLastStep)
        if step is not None:
            user.totpLastStep = step
            return "code"
    if _use_recovery_code(s, user, code):
        return "recovery-code"
    return None


def finish_sign_in(s: Db, token: str) -> None:
    s.execute(delete(OneTimeToken).where(OneTimeToken.tokenHash == digest(token)))
