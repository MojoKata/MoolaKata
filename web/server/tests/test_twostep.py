"""Two-step sign-in (requirements S10.1.6)."""

import datetime as dt

import pytest
from conftest import make_user, new_client, sign_in
from sqlalchemy import select
from test_users import kinds, mails

from moolakata import clock
from moolakata.auth import twostep
from moolakata.store.entities.core import Secret
from moolakata.store.entities.users import RecoveryCode, Session

PW = "a long user passphrase"
T0 = dt.datetime(2026, 10, 13, 12, 0, 0, tzinfo=dt.UTC)


@pytest.fixture
def frozen():
    clock.fix(T0)
    yield
    clock.fix(None)


def later(seconds: int) -> None:
    clock.fix(clock.now() + dt.timedelta(seconds=seconds))


def code(seed: str, offset: int = 0) -> str:
    return twostep.code_at(seed, twostep._step() + offset)


def turn_on(c) -> tuple[str, list[str]]:
    r = c.post("/ui/api/profile/two-step")
    assert r.status_code == 200, r.text
    setup = r.json()
    assert (
        setup["uri"].startswith("otpauth://totp/") and f"secret={setup['secret']}" in setup["uri"]
    )
    assert setup["qrImage"].startswith("data:image/svg+xml")
    r = c.post("/ui/api/profile/two-step/confirm", json={"code": code(setup["secret"])})
    assert r.status_code == 200, r.text
    return setup["secret"], r.json()["codes"]


def test_rfc_6238_test_vector():
    # RFC 6238 appendix B, SHA-1, at T = 59 s: 94287082, of which an app shows six digits.
    seed = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890"
    assert twostep.code_at(seed, 59 // 30) == "287082"


def test_turning_it_on_needs_a_code_from_the_seed(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    r = c.post("/ui/api/profile/two-step")
    seed = r.json()["secret"]
    assert c.get("/ui/api/profile").json()["twoStep"]["on"] is False
    r = c.post("/ui/api/profile/two-step/confirm", json={"code": "000000"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "code"
    r = c.post("/ui/api/profile/two-step/confirm", json={"code": code(seed)})
    codes = r.json()["codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    me = c.get("/ui/api/profile").json()["twoStep"]
    assert me["on"] is True and me["recoveryCodesLeft"] == 10
    # The seed is sealed as a secret, and the one being set up is gone.
    with server.db.read() as s:
        fields = {x.field for x in s.scalars(select(Secret).where(Secret.recordType == "User"))}
        assert fields == {"totp"}
    assert "user.two-step-on" in kinds(server)
    assert mails(server)[-1]["Subject"] == "Two-step sign-in was turned on"


def test_sign_in_asks_for_the_code_and_takes_each_step_once(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    seed, _ = turn_on(c)
    later(30)
    with new_client(server) as b:
        r = b.post("/ui/api/session", json={"login": "alice", "password": PW})
        assert r.status_code == 202 and "mk_session" not in b.cookies
        token = r.json()["twoStepToken"]
        assert b.get("/ui/api/session").status_code == 401
        r = b.post("/ui/api/session/two-step", json={"token": token, "code": "123456"})
        assert r.status_code == 401 and r.json()["errors"][0]["field"] == "code"
        good = code(seed)
        r = b.post(
            "/ui/api/session/two-step", json={"token": token, "code": good[:3] + " " + good[3:]}
        )
        assert r.status_code == 200 and r.json()["user"]["username"] == "alice"
        assert b.get("/ui/api/session").status_code == 200
        # The token was used up with the sign-in.
        r = b.post("/ui/api/session/two-step", json={"token": token, "code": good})
        assert r.status_code == 401 and r.json()["code"] == "two-step-expired"
    with new_client(server) as b2:
        token = b2.post("/ui/api/session", json={"login": "alice", "password": PW}).json()[
            "twoStepToken"
        ]
        r = b2.post("/ui/api/session/two-step", json={"token": token, "code": good})
        assert r.status_code == 401, "the same code twice in one step"
        r = b2.post("/ui/api/session/two-step", json={"token": token, "code": code(seed, 1)})
        assert r.status_code == 200, "the next step, for a clock running a little fast"


def test_the_sign_in_token_lasts_five_minutes(server, frozen):
    make_user(server, "alice")
    seed, _ = turn_on(sign_in(server, "alice"))
    with new_client(server) as b:
        token = b.post("/ui/api/session", json={"login": "alice", "password": PW}).json()[
            "twoStepToken"
        ]
        later(5 * 60 + 1)
        r = b.post("/ui/api/session/two-step", json={"token": token, "code": code(seed)})
        assert r.status_code == 401 and r.json()["code"] == "two-step-expired"


def test_a_recovery_code_works_once(server, frozen):
    make_user(server, "alice")
    _, codes = turn_on(sign_in(server, "alice"))
    for expected in (200, 401):
        with new_client(server) as b:
            token = b.post("/ui/api/session", json={"login": "alice", "password": PW}).json()[
                "twoStepToken"
            ]
            r = b.post("/ui/api/session/two-step", json={"token": token, "code": codes[0].upper()})
            assert r.status_code == expected
    with server.db.read() as s:
        assert len(s.scalars(select(RecoveryCode)).all()) == 9
    assert "signin.recovery-code" in kinds(server)
    # N12: the sign-in with a recovery code is emailed, with how many are left.
    [m] = [m for m in mails(server) if "recovery code" in m["Subject"]]
    assert "9 are left" in m.get_content()


def test_five_wrong_codes_end_the_sign_in_and_ten_lock_the_address(server, frozen, monkeypatch):
    # S10.1.6.3: five wrong codes end a sign-in, so the password is needed again; wrong codes
    # count toward the address's lockout as wrong passwords do (S13.7.5.1).
    from moolakata.ui import session

    monkeypatch.setattr(session.time, "sleep", lambda s: None)
    make_user(server, "alice")
    seed, _ = turn_on(sign_in(server, "alice"))
    later(30)
    two_step = "/ui/api/session/two-step"
    with new_client(server) as b:

        def started() -> str:
            r = b.post("/ui/api/session", json={"login": "alice", "password": PW})
            return r.json()["twoStepToken"]

        first = started()
        codes = [
            b.post(two_step, json={"token": first, "code": "000000"}).json()["code"]
            for _ in range(5)
        ]
        assert codes == ["code-wrong"] * 4 + ["two-step-expired"]
        r = b.post(two_step, json={"token": first, "code": code(seed)})
        assert r.status_code == 401 and r.json()["code"] == "two-step-expired"
        second = started()
        for _ in range(5):
            b.post(two_step, json={"token": second, "code": "000000"})
        r = b.post("/ui/api/session", json={"login": "alice", "password": PW})
        assert r.status_code == 429
    assert "signin.locked" in kinds(server)


def test_new_recovery_codes_replace_the_old(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    _, old = turn_on(c)
    new = c.post("/ui/api/profile/two-step/recovery-codes").json()["codes"]
    assert not set(old) & set(new)
    with new_client(server) as b:
        token = b.post("/ui/api/session", json={"login": "alice", "password": PW}).json()[
            "twoStepToken"
        ]
        r = b.post("/ui/api/session/two-step", json={"token": token, "code": old[0]})
        assert r.status_code == 401


def test_changing_two_step_needs_the_password_within_ten_minutes(server, frozen):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    turn_on(c)
    later(11 * 60)
    for method, path in (
        ("post", "/ui/api/profile/two-step/off"),
        ("post", "/ui/api/profile/two-step/recovery-codes"),
    ):
        r = getattr(c, method)(path)
        assert r.status_code == 403 and r.json()["code"] == "reauth-required", path
    assert c.post("/ui/api/session/reauth", json={"password": PW}).status_code == 204
    assert c.post("/ui/api/profile/two-step/off").status_code == 200
    assert c.get("/ui/api/profile").json()["twoStep"] == {
        "on": False,
        "since": None,
        "recoveryCodesLeft": 0,
    }
    assert mails(server)[-1]["Subject"] == "Two-step sign-in was turned off"
    with new_client(server) as b:
        assert b.post("/ui/api/session", json={"login": "alice", "password": PW}).status_code == 200


def test_an_admins_reset_turns_it_off_and_ends_the_users_sessions(server, admin_client, frozen):
    alice = make_user(server, "alice")
    c = sign_in(server, "alice")
    turn_on(c)
    rows = {u["username"]: u for u in admin_client.get("/ui/api/users").json()["items"]}
    assert rows["alice"]["twoStep"] is True
    r = admin_client.post(f"/ui/api/users/{alice.id}/two-step/reset")
    assert r.status_code == 200 and r.json()["twoStep"] is False
    assert c.get("/ui/api/session").status_code == 401
    with server.db.read() as s:
        assert s.scalars(select(Session).where(Session.userId == alice.id)).first() is None
        assert s.scalars(select(Secret).where(Secret.recordId == alice.id)).first() is None
    assert "user.two-step-reset" in kinds(server)
    assert "an admin, turned it off for you" in mails(server)[-1].get_content()
    # Not an admin: refused.
    c2 = sign_in(server, "alice")
    assert c2.post(f"/ui/api/users/{alice.id}/two-step/reset").status_code == 403


def test_a_two_step_sign_in_from_a_new_address_is_emailed(server, frozen):
    # N12: the second step notes the address as a password-only sign-in does (S10.1.9).
    from moolakata.store.entities.users import User

    make_user(server, "alice")
    seed, _ = turn_on(sign_in(server, "alice"))
    with server.db.tx() as s:
        u = s.query(User).filter_by(username="alice").one()
        u.recentAddresses = '{"192.0.2.1": "2026-10-01T00:00:00+00:00"}'
    later(30)
    with new_client(server) as b:
        token = b.post("/ui/api/session", json={"login": "alice", "password": PW}).json()[
            "twoStepToken"
        ]
        r = b.post("/ui/api/session/two-step", json={"token": token, "code": code(seed)})
        assert r.status_code == 200, r.text
    assert "signin.new-address" in kinds(server)
    assert any("new address" in m["Subject"] for m in mails(server))
