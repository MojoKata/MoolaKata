"""Access tokens (requirements S10.9.1): made in the profile, shown once, kept as a hash,
listed, revoked, and dead once expired or their user is inactive."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import remove
from test_accounts import new_account

from moolakata import clock, tokens


@pytest.fixture
def alice(server):
    make_user(server, "alice")
    return sign_in(server, "alice")


def test_a_token_is_shown_once_and_kept_as_a_hash(server, alice):
    r = alice.post("/ui/api/profile/tokens", json={"name": "Claude on my laptop"})
    assert r.status_code == 201, r.text
    made = r.json()
    secret = made["secret"]
    assert secret.startswith("mkt_") and "." in secret
    assert made["token"]["scope"] == "all"
    left = dt.datetime.fromisoformat(made["token"]["expiresAt"]) - clock.now()
    assert dt.timedelta(days=89) < left <= dt.timedelta(days=90), "90 days by default"
    listed = alice.get("/ui/api/profile/tokens").json()["items"]
    assert [t["name"] for t in listed] == ["Claude on my laptop"]
    assert secret.split(".")[1] not in str(listed)
    with server.db.read() as s:
        found = tokens.find(s, secret)
        assert found is not None and found[1].username == "alice"
        assert found[0].secretHash != secret.split(".")[1]
        assert tokens.find(s, secret[:-1] + ("A" if secret[-1] != "A" else "B")) is None
        assert tokens.find(s, "mkt_nonsense") is None


def test_a_token_can_be_limited_to_chosen_items(server, alice):
    a = new_account(alice, name="Brokerage", type="brokerage")
    r = alice.post(
        "/ui/api/profile/tokens",
        json={
            "name": "Retirement check-ins",
            "scope": "chosen",
            "items": [{"kind": "account", "id": a["id"]}],
            "days": 30,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["token"]["items"] == [{"kind": "account", "id": a["id"], "name": "Brokerage"}]
    for body, field in (
        ({"name": "x", "scope": "chosen", "items": []}, "items"),
        ({"name": "x", "days": 7}, "days"),
        ({"name": "  "}, "name"),
        (
            {"name": "x", "scope": "chosen", "items": [{"kind": "account", "id": "Acct_nope"}]},
            "items",
        ),
    ):
        r = alice.post("/ui/api/profile/tokens", json=body)
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == field, body


def test_a_token_dies_when_revoked_expired_or_its_user_is_inactive(server, alice):
    def make():
        return alice.post("/ui/api/profile/tokens", json={"name": "t", "days": 30}).json()

    one = make()
    assert remove(alice, "Token", one["token"]).status_code == 200
    assert alice.get("/ui/api/profile/tokens").json()["items"] == []
    two = make()
    with server.db.read() as s:
        assert tokens.find(s, one["secret"]) is None
        assert tokens.find(s, two["secret"]) is not None
    from moolakata.store.entities.users import AccessToken

    with server.db.tx() as s:
        s.get(AccessToken, two["token"]["id"]).expiresAt = clock.now() - dt.timedelta(seconds=1)
    with server.db.read() as s:
        assert tokens.find(s, two["secret"]) is None
    assert alice.get("/ui/api/profile/tokens").json()["items"][0]["expired"] is True
    three = make()
    from moolakata.store.entities.users import User

    with server.db.tx() as s:
        s.get(User, tokens.find(s, three["secret"])[1].id).active = False
    with server.db.read() as s:
        assert tokens.find(s, three["secret"]) is None


def test_someone_elses_token_cant_be_revoked(server, alice):
    t = alice.post("/ui/api/profile/tokens", json={"name": "mine"}).json()["token"]
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    assert remove(bob, "Token", t).status_code == 404
    assert bob.get("/ui/api/profile/tokens").json()["items"] == []


def test_making_a_token_needs_the_password_again_and_is_emailed(server, alice):
    """S13.7.2 and S10.1.9: someone with a minute at an unlocked browser can't make one."""
    from sqlalchemy import select
    from test_users import PW, mails

    from moolakata.store.entities.users import Session

    with server.db.tx() as s:
        s.scalars(select(Session)).one().authAt -= dt.timedelta(minutes=11)
    r = alice.post("/ui/api/profile/tokens", json={"name": "Stale"})
    assert r.status_code == 403 and r.json()["code"] == "reauth-required"
    assert alice.post("/ui/api/session/reauth", json={"password": PW}).status_code == 204
    assert alice.post("/ui/api/profile/tokens", json={"name": "Fresh"}).status_code == 201
    told = mails(server)[-1]
    assert told["To"] == "alice@home.lan" and told["Subject"] == "An access token was made"
    assert '"Fresh"' in told.get_content()


def test_a_password_change_or_reset_stops_every_token(server, alice):
    """S10.9.4: a token outlives neither."""
    from test_users import PW, mails

    secret = alice.post("/ui/api/profile/tokens", json={"name": "Laptop"}).json()["secret"]
    r = alice.post(
        "/ui/api/profile/password",
        json={"currentPassword": PW, "newPassword": "another long passphrase"},
    )
    assert r.status_code in (200, 204), r.text
    with server.db.read() as s:
        assert tokens.find(s, secret) is None
    assert alice.get("/ui/api/profile/tokens").json()["items"] == []
    assert "access token revoked" in mails(server)[-1].get_content()
