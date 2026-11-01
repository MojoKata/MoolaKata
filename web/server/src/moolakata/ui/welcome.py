"""A new server's welcome (requirements S12.14.1, S15.4.4, S10.1.2): with no keyring, the page
shows a new phrase on every visit, makes the key from the one whose words are typed back,
unlocks, and then sets up the first admin, signed in at once. Nothing of a phrase that isn't
confirmed is written, and nobody signs in before the admin exists."""

import datetime as dt
import logging

from fastapi import APIRouter, Request
from pydantic import Field

from .. import activity
from ..auth import sessions
from ..auth import users as accounts
from ..errors import FieldError, Problem
from ..keys import master, phrase
from ..keys.welcome import Offer
from .conventions import ExactRoute, Model
from .deps import server, set_cookie
from .session import SessionInfo, _throttle, info
from .unlock import LockState, state

log = logging.getLogger("moolakata.welcome")
router = APIRouter(prefix="/ui/api/welcome", route_class=ExactRoute, tags=["welcome"])


class Offered(Model):
    token: str  # the browser keeps it to confirm these words, and only these
    words: list[str]
    fingerprint: str
    serverName: str
    made: dt.date
    check: list[int]  # the three word numbers (1 to 12) to type back


class Confirm(Model):
    token: str
    words: dict[str, str] = Field(default_factory=dict)  # word number: the word typed


class FirstAdmin(Model):
    displayName: str
    sex: str
    email: str
    password: str


def matches(word: str, typed: str) -> bool:
    """A word typed in full, or by its first four letters (which identify it)."""
    return typed == word or (len(typed) >= 4 and word.startswith(typed))


def words_wrong(made: Offer, typed: dict[str, str]) -> None:
    """Refused unless the three words asked for are typed back (S15.6.1): the welcome's and a
    rotation's."""
    words = phrase.to_words(made.key)
    wrong = [
        i for i in made.picks if not matches(words[i], typed.get(str(i + 1), "").strip().lower())
    ]
    if wrong:
        errors = [
            FieldError(f"word{i + 1}", "word-wrong", "Not the word shown: check your sheet.")
            for i in wrong
        ]
        raise Problem(422, "words-wrong", "Those aren't the words shown: check your sheet.", errors)


def _uninitialised(srv) -> None:
    if srv.store is not None or srv.config.keyring_path.exists():
        raise Problem(409, "initialised", "This server has its key: unlock it with its phrase.")


@router.post("/phrase", response_model=Offered)
def offer(request: Request):
    """A new master key's phrase, held in memory only, until its words are typed back."""
    srv = server(request)
    _uninitialised(srv)
    token, made = srv.phrases.offer()
    return Offered(
        token=token,
        words=phrase.to_words(made.key),
        fingerprint=master.fingerprint(made.key),
        serverName=srv.config.name,
        made=dt.date.today(),
        check=[i + 1 for i in made.picks],
    )


@router.post("/key", response_model=LockState)
async def make_key(body: Confirm, request: Request):
    """Three of the words typed back make the key: the keyring is written and the server
    unlocks with it (S15.4.4)."""
    from .. import runtime

    srv = server(request)
    _uninitialised(srv)
    made = srv.phrases.get(body.token)
    if made is None:
        raise Problem(410, "phrase-gone", "Those words aren't on offer now: show a new phrase.")
    words_wrong(made, body.words)
    srv.phrases.clear()
    _uninitialised(srv)  # another browser's welcome may have made one meanwhile
    master.create_keyring(srv.config, made.key)
    address = request.client.host if request.client else "-"
    log.info("the welcome made the key %s, from %s", master.fingerprint(made.key), address)
    await runtime.unlock(srv, made.key, wait=False)
    if srv.store is not None:
        with srv.db.tx(unscoped="the welcome: the key made") as s:
            activity.record(
                s,
                "key.made-welcome",
                actor=None,
                for_admins=True,
                detail={"fingerprint": master.fingerprint(made.key)},
            )
    return state(srv)


@router.post("/admin", response_model=SessionInfo)
def first_admin(body: FirstAdmin, request: Request):
    """The welcome's last step: the first admin, signed in at once (S10.1.2)."""
    srv = server(request)
    _throttle(request)
    with srv.db.tx(unscoped="the welcome: the first admin") as s:
        user = accounts.make_first_admin(s, body.displayName, body.sex, body.email, body.password)
        token = sessions.create(s, user.id, True, False)
    set_cookie(request, token)
    return info(request, user, True)
