"""Sign-in, sessions and users at their edges (S10.1, S13.7): the password checked outside the
write lock and a bounded number at once, attempts in flight counted toward the lockout."""

import email
import email.policy
import re
import threading
from contextlib import ExitStack

import pytest
from conftest import LOOPBACK, ORIGIN, make_user, sign_in
from fastapi.testclient import TestClient

from moolakata.auth import passwords
from moolakata.errors import Problem
from moolakata.ratelimit import SignInGuard

PW = "a long user passphrase"


# ---------- the password is checked outside the write lock (S13.7.3) ----------


def _writes_meanwhile(server, monkeypatch) -> list[bool]:
    """passwords.verify, wrapped: while it runs another thread writes, and whether that write
    got through at once is kept."""
    real = passwords.verify
    got: list[bool] = []

    def verify(stored, password):
        def write():
            with server.db.tx(unscoped="test: a write beside a sign-in"):
                pass

        t = threading.Thread(target=write)
        t.start()
        t.join(timeout=2)
        got.append(not t.is_alive())
        out = real(stored, password)
        t.join()
        return out

    monkeypatch.setattr(passwords, "verify", verify)
    return got


def test_a_sign_in_checks_the_password_with_the_writer_free(client, server, monkeypatch):
    make_user(server, "ada")
    got = _writes_meanwhile(server, monkeypatch)
    assert client.post("/ui/api/session", json={"login": "ada", "password": PW}).status_code == 200
    r = client.post("/ui/api/session", json={"login": "ada", "password": "wrong"})
    assert r.status_code == 401
    assert got == [True, True]


def test_a_reauthentication_checks_the_password_with_the_writer_free(server, monkeypatch):
    make_user(server, "bea")
    c = sign_in(server, "bea")
    got = _writes_meanwhile(server, monkeypatch)
    assert c.post("/ui/api/session/reauth", json={"password": PW}).status_code == 204
    assert c.post("/ui/api/session/reauth", json={"password": "wrong"}).status_code == 401
    assert got == [True, True]


def test_a_stale_hash_is_redone_on_a_right_sign_in(client, server, monkeypatch):
    from moolakata.store.entities.users import User

    u = make_user(server, "cat")
    monkeypatch.setattr(passwords, "needs_rehash", lambda stored: True)
    assert client.post("/ui/api/session", json={"login": "cat", "password": PW}).status_code == 200
    with server.db.read(unscoped="test") as s:
        again = s.get(User, u.id).passwordHash
    assert again != u.passwordHash and passwords.verify(again, PW)


def test_a_password_changed_while_it_was_checked_is_not_signed_in_with(client, server, monkeypatch):
    """The check was of the hash read before; one changed meanwhile decides nothing."""
    from moolakata.store.entities.users import User

    u = make_user(server, "dot")
    real = passwords.verify

    def verify(stored, password):
        with server.db.tx(unscoped="test") as s:
            s.get(User, u.id).passwordHash = passwords.hash_password("another long passphrase")
        return real(stored, password)

    monkeypatch.setattr(passwords, "verify", verify)
    r = client.post("/ui/api/session", json={"login": "dot", "password": PW})
    assert r.status_code == 401 and r.json()["code"] == "bad-credentials"


# ---------- a bounded number of hashes at once (S13.7.3, S13.7.5.1) ----------


def test_no_more_than_two_passwords_are_hashed_at_once(monkeypatch):
    monkeypatch.setattr(passwords, "WAIT", 0.01)
    stored = passwords.hash_password(PW)
    with ExitStack() as held:
        held.enter_context(passwords.slot())
        assert passwords.verify(stored, PW)  # one left
        held.enter_context(passwords.slot())
        for work in (lambda: passwords.verify(stored, PW), lambda: passwords.hash_password(PW)):
            with pytest.raises(Problem) as e:
                work()
            assert e.value.status == 429 and e.value.headers["Retry-After"] == "1"
    assert passwords.verify(stored, PW)  # free again


def test_a_sign_in_past_the_bound_is_answered_too_many(client, server, monkeypatch):
    monkeypatch.setattr(passwords, "WAIT", 0.01)
    make_user(server, "eve")
    with passwords.slot(), passwords.slot():
        r = client.post("/ui/api/session", json={"login": "eve", "password": PW})
    assert r.status_code == 429 and r.headers["retry-after"] == "1"
    assert client.post("/ui/api/session", json={"login": "eve", "password": PW}).status_code == 200


# ---------- attempts in flight count toward the lockout (S13.7.5.1) ----------


def test_attempts_in_flight_count_with_the_failures_toward_the_threshold():
    guard = SignInGuard(clock=lambda: 1000.0)
    for _ in range(8):
        guard.failed("x", "10.0.0.1", threshold=10)
    with guard.attempt("10.0.0.1", 10), guard.attempt("10.0.0.1", 10):
        with pytest.raises(Problem) as e, guard.attempt("10.0.0.1", 10):
            pass
        assert e.value.status == 429 and "at once" in e.value.detail
        with guard.attempt("10.0.0.2", 10):  # another address is its own
            pass
    with guard.attempt("10.0.0.1", 10):  # ended, so free again
        pass
    assert guard.held()["trying"] == 0  # none kept once ended


def test_a_locked_address_is_refused_its_attempt():
    guard = SignInGuard(clock=lambda: 1000.0)
    for _ in range(3):
        guard.failed("x", "10.0.0.1", threshold=3, lock_minutes=15)
    with pytest.raises(Problem) as e, guard.attempt("10.0.0.1", 3):
        pass
    assert e.value.status == 429 and int(e.value.headers["Retry-After"]) == 900


def test_an_eleventh_sign_in_at_once_is_refused_before_its_hash(client, server, monkeypatch):
    make_user(server, "fay")
    checked = []
    monkeypatch.setattr(passwords, "verify", lambda *a: checked.append(a) or False)
    with ExitStack() as held:
        for _ in range(10):
            held.enter_context(server.sign_in.attempt(LOOPBACK[0], 10))
        r = client.post("/ui/api/session", json={"login": "fay", "password": PW})
    assert r.status_code == 429 and checked == []


# ---------- re-authentication after a change of privilege (S13.7.1, S13.7.2) ----------


def test_a_reauthentication_as_the_first_request_after_being_made_admin(server):
    """The request's token is rotated for the change; the password marks the new one."""
    import datetime as dt

    from sqlalchemy import select

    from moolakata.auth import users as accounts
    from moolakata.store.entities.users import Session, UserGroup

    u = make_user(server, "gus")
    c = sign_in(server, "gus")
    before = c.cookies.get("mk_session")
    long_ago = accounts.now() - dt.timedelta(hours=1)
    with server.db.tx(unscoped="test") as s:
        s.scalars(select(Session).where(Session.userId == u.id)).one().authAt = long_ago
        s.add(UserGroup(userId=u.id, groupId=accounts.admins_group(s).id, createdAt=accounts.now()))
    r = c.post("/ui/api/session/reauth", json={"password": PW})
    assert r.status_code == 204, r.text
    assert c.cookies.get("mk_session") != before
    with server.db.read(unscoped="test") as s:
        row = s.scalars(select(Session).where(Session.userId == u.id)).one()
    assert row.admin and row.authAt > long_ago


# ---------- a sign-in from a new address (S10.1.9) ----------


def _mails(server) -> list[email.message.EmailMessage]:
    folder = server.config.mail_dir
    if not folder.exists():
        return []
    return [
        email.message_from_bytes(p.read_bytes(), policy=email.policy.default)
        for p in sorted(folder.iterdir())
    ]


def _subjects(server) -> list[str]:
    return [m["Subject"] for m in _mails(server)]


def _from(client, address: str) -> TestClient:
    return TestClient(
        client.app, base_url=ORIGIN, headers={"Origin": ORIGIN}, client=(address, 50000)
    )


NOTICE = "A sign-in to MoolaKata from a new address"


def test_a_new_address_after_a_quiet_month_is_emailed(client, server):
    """Once signed in from somewhere, ever: the addresses seen lapse after 30 days, the
    notice doesn't."""
    import datetime as dt
    import json

    from moolakata.auth import users as accounts
    from moolakata.store.entities.users import User

    u = make_user(server, "gil")
    sign_in(server, "gil")
    month = accounts.now() - dt.timedelta(days=31)
    with server.db.tx(unscoped="test") as s:
        row = s.get(User, u.id)
        seen = json.loads(row.recentAddresses)
        row.recentAddresses = json.dumps(dict.fromkeys(seen, month.isoformat()))
        row.lastSignInAt = month
    r = _from(client, "203.0.113.9").post("/ui/api/session", json={"login": "gil", "password": PW})
    assert r.status_code == 200, r.text
    assert _subjects(server) == [NOTICE]


def test_the_first_sign_in_after_accepting_an_invitation(admin_client, server):
    """The address an invitation was accepted from is known; another is new."""
    from edits import make

    from moolakata import settings

    with server.db.tx(unscoped="test") as s:
        settings.put(s, "publicUrl", "https://money.home.lan", None)
    r = make(
        admin_client, "User", displayName="Hal", username="hal", email="hal@home.lan", sex="male"
    )
    assert r.status_code == 200, r.text
    token = re.search(r"#(\S+)", _mails(server)[-1].get_content()).group(1)
    here = _from(admin_client, "198.51.100.7")
    r = here.post("/ui/api/invitations/accept", json={"token": token, "password": PW})
    assert r.status_code == 200, r.text
    sent = len(_mails(server))
    r = here.post("/ui/api/session", json={"login": "hal", "password": PW})
    assert r.status_code == 200 and len(_mails(server)) == sent  # the same address
    far = _from(admin_client, "203.0.113.9")
    r = far.post("/ui/api/session", json={"login": "hal", "password": PW})
    assert r.status_code == 200 and _subjects(server)[sent:] == [NOTICE]


# ---------- an admin's rename in Users (S10.10.1, S10.10.3) ----------


def _listed(admin_client, user_id: str) -> dict:
    return next(u for u in admin_client.get("/ui/api/users").json()["items"] if u["id"] == user_id)


def test_an_admins_rename_is_the_users_person_renamed(admin_client, server):
    from edits import change, saved

    eve = make_user(server, "eve")
    saved(change(admin_client, "User", _listed(admin_client, eve.id), displayName=" Eve Wong "))
    person = admin_client.get(f"/ui/api/persons/{eve.personId}").json()
    assert person["name"] == "Eve Wong"
    assert _listed(admin_client, eve.id)["displayName"] == "Eve Wong"


def test_an_admins_rename_to_someone_already_here_is_refused(admin_client, server):
    from edits import change

    from moolakata import people

    eve = make_user(server, "eve")
    with server.db.tx(unscoped="test") as s:
        people.make(s, "Zoe Park", "female")
    r = change(admin_client, "User", _listed(admin_client, eve.id), displayName="zoe park")
    assert r.status_code == 409, r.text
    (e,) = r.json()["errors"]
    assert (e["field"], e["code"]) == ("displayName", "person-exists")
    assert admin_client.get(f"/ui/api/persons/{eve.personId}").json()["name"] == "Eve"
    # Her own name in another case is still hers.
    r = change(admin_client, "User", _listed(admin_client, eve.id), displayName="EVE")
    assert r.status_code == 200, r.text


def test_a_rename_in_profile_to_someone_already_here_is_refused(server):
    from edits import change, saved

    from moolakata import people

    make_user(server, "ivy")
    with server.db.tx(unscoped="test") as s:
        people.make(s, "Zoe Park", "female")
    c = sign_in(server, "ivy")
    p = c.get("/ui/api/profile").json()
    r = change(c, "User", p, displayName="Zoe Park")
    assert r.status_code == 409, r.text
    assert r.json()["errors"][0]["field"] == "displayName"
    assert saved(change(c, "User", p, displayName="Ivy Lee"))["displayName"] == "Ivy Lee"


# ---------- a name is one line (S10.1.1, S10.10.1) ----------

BROKEN = ("Ada\nAdmin", "Ada\rAdmin", "Ada\tAdmin", "Ada\x00", "Ada\x1bAdmin", "Ada\x7f")


@pytest.mark.parametrize("name", BROKEN)
def test_a_name_with_a_control_character_is_refused_everywhere(admin_client, server, name):
    from edits import change, make

    jo = make_user(server, "jo")
    c = sign_in(server, "jo")
    for r, field in (
        (change(c, "User", c.get("/ui/api/profile").json(), displayName=name), "displayName"),
        (change(admin_client, "User", _listed(admin_client, jo.id), displayName=name), None),
        (
            make(
                admin_client, "User", displayName=name, username="kay", email="k@h.lan", sex="male"
            ),
            "displayName",
        ),
        (make(admin_client, "Group", name=name, memberIds=[]), "name"),
        (make(c, "Persn", name=name, sex="female"), "name"),
    ):
        assert r.status_code == 422, r.text
        assert r.json()["errors"][0]["field"] == (field or "displayName")


def test_an_invitation_from_a_name_stored_with_a_line_break_still_goes(admin_client, server):
    """The subject takes the name on one line, whatever was stored before the rule."""
    from edits import make

    from moolakata import settings
    from moolakata.auth import users as accounts
    from moolakata.store.entities.users import User

    with server.db.tx(unscoped="test") as s:
        settings.put(s, "publicUrl", "https://money.home.lan", None)
        admin = s.get(User, accounts.admin_ids(s)[0])
        admin.displayName = "Ada\nAdmin"
    r = make(admin_client, "User", displayName="Kay", username="kay", email="k@h.lan", sex="male")
    assert r.status_code == 200, r.text
    assert _subjects(server)[-1] == "Ada Admin invited you to MoolaKata"


def test_a_peers_names_are_kept_on_one_line():
    """A linked server's names can't be refused at a field: their control characters become
    spaces (S10.3.3.1, link protocol §4.2)."""
    from moolakata.links import manage

    h, users = manage._checked(
        {
            "household": {"serverName": "doe\nparents", "name": "The\r\nDoes\x00"},
            "users": [{"id": "u", "username": "ann\tb", "displayName": "Ann\x1b[2J\nBee"}],
        }
    )
    assert (h["serverName"], h["name"]) == ("doe parents", "The Does")
    assert (users[0]["username"], users[0]["displayName"]) == ("ann b", "Ann [2J Bee")
    _, users = manage._checked({"users": [{"id": "v", "displayName": "\n\t"}]})
    assert users[0]["displayName"] is None  # nothing left of it
