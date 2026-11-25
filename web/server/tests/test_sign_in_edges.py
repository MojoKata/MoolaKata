"""Sign-in, sessions and users at their edges (S10.1, S13.7): the password checked outside the
write lock and a bounded number at once, attempts in flight counted toward the lockout."""

import threading
from contextlib import ExitStack

import pytest
from conftest import LOOPBACK, make_user, sign_in

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
