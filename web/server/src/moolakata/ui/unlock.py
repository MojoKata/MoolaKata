"""Unlocking the server (requirements S13.6, S15.4.3): it starts locked, with no key anywhere,
until an admin enters the recovery phrase here (the unlock page) or with `moolakata keys
unlock` on the host, which hands it over the host socket (host.py) to the same unlock. The
phrase is the authentication: no user can be checked before the database opens. Wrong phrases
count toward the sign-in lockout, and every attempt is logged."""

import asyncio
import logging

from fastapi import APIRouter, Request

from ..config import RefuseStart
from ..errors import Problem
from ..keys import cli as keys_cli
from ..keys import master, phrase
from .conventions import ExactRoute, Model
from .deps import server

log = logging.getLogger("moolakata.unlock")
router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["unlock"])
LOGIN = "recovery phrase"  # the lockout's name for unlock attempts


class Phrase(Model):
    phrase: str


class Reencrypting(Model):
    stage: str  # backup, database, secrets, receipts, copies
    done: int
    total: int


class LockState(Model):
    locked: bool
    # No keyring yet: the page shows the welcome, which makes the key (S15.4.4).
    uninitialised: bool = False
    # Unlocked with no users yet: the welcome's last step, the first admin (S10.1.2).
    needsAdmin: bool = False
    fingerprint: str | None  # of the key the keyring is wrapped under
    version: str
    # A re-encryption under way before the server serves (S15.7.2), and why the last unlock
    # failed when it did.
    reencrypting: Reencrypting | None = None
    error: str | None = None


def state(srv) -> LockState:
    try:
        fp = keys_cli.fingerprint_of(srv.config)
    except RefuseStart:
        fp = None
    progress = srv.reencrypting.as_dict() if srv.reencrypting is not None else None
    needs_admin = False
    if srv.ready and srv.store is not None:
        from ..auth import users

        with srv.db.read(unscoped="whether the server is locked") as s:
            needs_admin = not users.has_users(s)
    return LockState(
        # Locked until the server serves: the store opens a moment before its tasks start.
        locked=srv.store is None or not srv.ready,
        uninitialised=srv.store is None and not srv.config.keyring_path.exists(),
        needsAdmin=needs_admin,
        fingerprint=fp,
        version=srv.version,
        reencrypting=Reencrypting(**progress) if progress else None,
        error=srv.unlock_error,
    )


@router.get("/unlock", response_model=LockState)
def lock_state(request: Request):
    return state(server(request))


@router.post("/unlock", response_model=LockState)
async def unlock(body: Phrase, request: Request):
    address = request.client.host if request.client else "-"
    return await try_unlock(server(request), body.phrase, address)


async def try_unlock(srv, words: str, address: str) -> LockState:
    """The phrase tried, from the locked screen or `keys unlock` (S15.4.2)."""
    from .. import runtime

    if srv.store is not None:
        raise Problem(409, "unlocked-already", "MoolaKata is already unlocked.")
    guard = srv.sign_in
    wait = guard.locked(address)
    if wait:
        raise Problem(
            429,
            "locked-out",
            "Too many wrong phrases: try again later.",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    delay = guard.delay(LOGIN, address)
    if delay:
        await asyncio.sleep(delay)
    try:
        key = phrase.from_words(words)
    except phrase.PhraseError as e:
        guard.failed(LOGIN, address)
        log.warning("unlock refused from %s: not a phrase", address)
        raise Problem(422, "phrase-invalid", f"Not a recovery phrase: {e}") from None
    try:
        await runtime.unlock(srv, key, wait=False)
    except runtime.Reencrypting:
        raise Problem(409, "re-encrypting", "MoolaKata is re-encrypting: wait for it.") from None
    except master.WrongPhrase:
        guard.failed(LOGIN, address)
        log.warning("unlock refused from %s: wrong phrase (%s)", address, master.fingerprint(key))
        raise Problem(403, "phrase-wrong", "Those words are not this server's key.") from None
    except runtime.AlreadyUnlocked:
        raise Problem(409, "unlocked-already", "MoolaKata is already unlocked.") from None
    except RefuseStart as e:
        log.error("refusing to unlock: %s", e)
        if "pending under" in str(e):  # names the phrase that finishes it (S15.7.2)
            raise Problem(409, "reencrypt-pending", f"{str(e)[:1].upper()}{str(e)[1:]}.") from None
        raise Problem(
            503, "cannot-unlock", "The server cannot open its data: see its log."
        ) from None
    log.info("unlocked from %s", address)
    return state(srv)
