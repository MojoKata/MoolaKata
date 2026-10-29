import datetime as dt
import email
import re

from conftest import make_user, new_client, sign_in
from edits import change, make, save_settings, saved
from sqlalchemy import select

from moolakata import settings
from moolakata.auth import passwords
from moolakata.auth import users as accounts
from moolakata.store.entities.core import Activity
from moolakata.store.entities.users import Session, User

PW = "a long user passphrase"


def mails(server) -> list[email.message.EmailMessage]:
    folder = server.config.mail_dir
    if not folder.exists():
        return []
    return [
        email.message_from_bytes(
            p.read_bytes(), _class=email.message.EmailMessage, policy=email.policy.default
        )
        for p in sorted(folder.iterdir())
    ]


def last_link(server) -> tuple[str, str]:
    body = mails(server)[-1].get_content()
    url = re.search(r"https://\S+", body).group(0)
    path, _, token = url.partition("#")
    return path, token


def kinds(server) -> list[str]:
    with server.db.read() as s:
        return [a.kind for a in s.scalars(select(Activity).order_by(Activity.at))]


def set_public_url(server):
    with server.db.tx() as s:
        settings.put(s, "publicUrl", "https://money.home.lan", None)


# ---------- an admin from before the welcome (S10.1.2) ----------


def _legacy_admin(server) -> None:
    """The admin a server made before the welcome: the published password, setup to do."""
    from moolakata import ids, people
    from moolakata.store.entities.users import User, UserGroup

    with server.db.tx() as s:
        u = User(
            id=ids.new_id("User"),
            personId=people.make(s, "Admin", "male").id,
            username="legacy",
            displayName="Admin",
            passwordHash=passwords.hash_password(accounts.DEFAULT_PASSWORD),
            needsSetup=True,
        )
        s.add(u)
        s.flush()
        s.add(UserGroup(userId=u.id, groupId=accounts.admins_group(s).id, createdAt=accounts.now()))


def test_an_admin_from_before_the_welcome_only_reaches_setup(client, server):
    _legacy_admin(server)
    r = client.post("/ui/api/session", json={"login": "LEGACY", "password": "moolakata-setup"})
    assert r.status_code == 200
    assert r.json()["user"]["needsSetup"] is True
    first = client.cookies.get("mk_session")
    assert client.get("/ui/api/session").status_code == 200
    r = client.get("/ui/api/profile")
    assert r.status_code == 403 and r.json()["code"] == "setup-required"

    for bad, code in (
        ("short", "password-too-short"),
        ("moolakata-setup", "password-is-default"),
        ("password1234", "password-too-common"),
    ):
        r = client.post("/ui/api/session/setup", json={"password": bad, "email": "a@b.lan"})
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == code, bad
    r = client.post(
        "/ui/api/session/setup", json={"password": "a long admin passphrase", "email": "nope"}
    )
    assert r.json()["errors"][0]["field"] == "email"

    r = client.post(
        "/ui/api/session/setup",
        json={"password": "a long legacy passphrase", "email": "Legacy@Home.lan"},
    )
    assert r.status_code == 200 and r.json()["user"]["needsSetup"] is False
    assert client.cookies.get("mk_session") != first
    assert client.get("/ui/api/profile").status_code == 200
    with new_client(server) as old:
        old.cookies.set("mk_session", first, domain="mk.test", path="/ui")
        assert old.get("/ui/api/session").status_code == 401
    with new_client(server) as c2:
        r = c2.post("/ui/api/session", json={"login": "legacy", "password": "moolakata-setup"})
        assert r.status_code == 401


# ---------- signing in and sessions (S13.7.1) ----------


def test_sign_in_by_username_or_email_with_a_strict_cookie(client, server):
    make_user(server, "alice")
    for login in ("alice", "ALICE", "alice@home.lan", "Alice@Home.LAN"):
        r = client.post("/ui/api/session", json={"login": login, "password": PW})
        assert r.status_code == 200, login
    cookie = r.headers["set-cookie"]
    for part in ("mk_session=", "Path=/ui", "HttpOnly", "Secure", "SameSite=Strict"):
        assert part in cookie
    token = client.cookies.get("mk_session")
    with server.db.read() as s:
        hashes = list(s.scalars(select(Session.tokenHash)))
    assert token not in hashes  # stored as a hash only
    assert len(token) >= 43


def test_wrong_passwords_lock_the_address_and_only_slow_the_username(client, server):
    """S13.7.5.1: ten failures lock the address they came from, whoever they named; the
    username is slowed, never locked, so nobody can lock an admin out from afar."""
    from conftest import ORIGIN
    from fastapi.testclient import TestClient

    make_user(server, "bob")
    for _ in range(9):
        r = client.post("/ui/api/session", json={"login": "bob", "password": "wrong"})
        assert r.status_code == 401
        assert r.json()["code"] == "bad-credentials"
    r = client.post("/ui/api/session", json={"login": "nobody", "password": "wrong"})
    assert r.json()["code"] == "bad-credentials"  # the same answer as a wrong password
    # The tenth failure from this address locks the address: even the right password waits.
    r = client.post("/ui/api/session", json={"login": "bob", "password": PW})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 800
    assert "signin.locked" in kinds(server)
    assert kinds(server).count("signin.failed") == 9  # the tenth is recorded as the lockout
    # From another address, bob still signs in: the username was slowed, not locked.
    elsewhere = TestClient(client.app, base_url=ORIGIN, client=("192.168.1.9", 50000))
    r = elsewhere.post(
        "/ui/api/session", json={"login": "bob", "password": PW}, headers={"Origin": ORIGIN}
    )
    assert r.status_code == 200, r.text


def test_sign_out_ends_every_session_of_the_user(server):
    make_user(server, "carol")
    a, b = sign_in(server, "carol"), sign_in(server, "carol")
    assert a.delete("/ui/api/session").status_code == 204
    assert b.get("/ui/api/session").status_code == 401
    assert a.get("/ui/api/session").status_code == 401


def test_sessions_expire_when_idle_and_absolutely(server):
    make_user(server, "dan")
    c = sign_in(server, "dan")
    with server.db.tx() as s:
        row = s.scalars(select(Session)).one()
        row.lastSeenAt -= dt.timedelta(hours=9)
    r = c.get("/ui/api/session")
    assert r.status_code == 401 and r.json()["code"] == "session-expired"
    c = sign_in(server, "dan")
    with server.db.tx() as s:
        row = s.scalars(select(Session)).one()
        row.expiresAt = accounts.now() - dt.timedelta(seconds=1)
    assert c.get("/ui/api/session").status_code == 401


def test_a_change_of_privilege_gives_a_new_token(server, admin_client):
    bob = make_user(server, "bob")
    c = sign_in(server, "bob")
    before = c.cookies.get("mk_session")
    with server.db.read() as s:
        admins = accounts.admins_group(s)
    groups = admin_client.get("/ui/api/groups").json()["items"]
    g = next(g for g in groups if g["id"] == admins.id)
    saved(change(admin_client, "Group", g, memberIds={"add": [bob.id], "remove": []}))
    r = c.get("/ui/api/session")
    assert r.json()["user"]["admin"] is True
    assert c.cookies.get("mk_session") != before
    with new_client(server) as old:
        old.cookies.set("mk_session", before, domain="mk.test", path="/ui")
        assert old.get("/ui/api/session").status_code == 401


# ---------- invitations (S10.1.3) ----------


def test_invitation_needs_the_public_url_outside_dev_mode(admin_client):
    r = make(
        admin_client, "User", displayName="Eve", username="eve", email="eve@home.lan", sex="female"
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "publicUrl"


def test_invite_join_and_sign_in(admin_client, server):
    set_public_url(server)
    r = make(
        admin_client,
        "User",
        displayName="Eve Shaw",
        username="Eve",
        email="eve@home.lan",
        sex="female",
    )
    assert r.status_code == 200, r.text
    assert r.json()["invited"] is True and r.json()["username"] == "eve"
    msg = mails(server)[-1]
    assert msg["To"] == "eve@home.lan"
    path, token = last_link(server)
    assert path == "https://money.home.lan/ui/welcome"
    with new_client(server) as eve:
        assert (
            eve.post("/ui/api/invitations/lookup", json={"token": token}).json()["username"]
            == "eve"
        )
        r = eve.post(
            "/ui/api/invitations/accept", json={"token": token, "password": "password1234"}
        )
        assert r.json()["errors"][0]["code"] == "password-too-common"
        r = eve.post("/ui/api/invitations/accept", json={"token": token, "password": PW})
        assert r.status_code == 200 and r.json()["user"]["username"] == "eve"
        assert eve.get("/ui/api/profile").status_code == 200
        r = eve.post("/ui/api/invitations/accept", json={"token": token, "password": PW})
        assert r.status_code == 404
    uid = admin_client.get("/ui/api/users").json()["items"]
    eve_row = next(u for u in uid if u["username"] == "eve")
    assert eve_row["invited"] is False
    r = admin_client.post(f"/ui/api/users/{eve_row['id']}/invitation")
    assert r.status_code == 409
    assert "user.invited" in kinds(server) and "user.joined" in kinds(server)


def test_new_users_are_checked_field_by_field(admin_client, server):
    set_public_url(server)
    make_user(server, "taken")
    r = make(
        admin_client,
        "User",
        displayName="",
        username="taken",
        email="taken@home.lan",
        groupIds=["Group_00000000000000000000000000"],
    )
    fields = {e["field"] for e in r.json()["errors"]}
    assert fields == {"displayName", "username", "email", "sex", "groupIds"}


def test_only_admins_manage_users(server):
    make_user(server, "bob")
    c = sign_in(server, "bob")
    assert c.get("/ui/api/users").status_code == 403
    assert c.get("/ui/api/settings").status_code == 403


# ---------- password reset and change (S10.1.5) ----------


def test_password_reset(client, server):
    set_public_url(server)
    make_user(server, "fay")
    other = sign_in(server, "fay")
    assert client.post("/ui/api/password-reset", json={"login": "nobody"}).status_code == 204
    assert mails(server) == []
    assert client.post("/ui/api/password-reset", json={"login": "fay"}).status_code == 204
    path, token = last_link(server)
    assert path.endswith("/ui/reset")
    r = client.post(
        "/ui/api/password-reset/confirm", json={"token": token, "password": "a new long passphrase"}
    )
    assert r.status_code == 204
    assert other.get("/ui/api/session").status_code == 401  # every session ended
    assert (
        client.post(
            "/ui/api/password-reset/confirm",
            json={"token": token, "password": "another passphrase!"},
        ).status_code
        == 404
    )
    assert sign_in(server, "fay", "a new long passphrase")
    assert "changed" in mails(server)[-1]["Subject"]


def test_password_change_keeps_this_browser_signed_in(server):
    make_user(server, "gus")
    here, there = sign_in(server, "gus"), sign_in(server, "gus")
    r = here.post(
        "/ui/api/profile/password",
        json={"currentPassword": "wrong", "newPassword": "a fresh passphrase!"},
    )
    assert r.json()["errors"][0]["field"] == "currentPassword"
    r = here.post(
        "/ui/api/profile/password",
        json={"currentPassword": PW, "newPassword": "a fresh passphrase!"},
    )
    assert r.status_code == 204
    assert here.get("/ui/api/profile").status_code == 200
    assert there.get("/ui/api/profile").status_code == 401


def test_email_change_needs_recent_password_and_a_confirmed_link(server):
    set_public_url(server)
    make_user(server, "hal")
    c = sign_in(server, "hal")
    with server.db.tx() as s:
        row = s.scalars(select(Session)).one()
        row.authAt -= dt.timedelta(minutes=11)
    r = c.post("/ui/api/profile/email", json={"email": "hal@new.lan"})
    assert r.status_code == 403 and r.json()["code"] == "reauth-required"
    assert c.post("/ui/api/session/reauth", json={"password": "wrong"}).status_code == 401
    assert c.post("/ui/api/session/reauth", json={"password": PW}).status_code == 204
    assert c.post("/ui/api/profile/email", json={"email": "hal@new.lan"}).status_code == 204
    assert mails(server)[-1]["To"] == "hal@new.lan"
    assert c.get("/ui/api/profile").json()["email"] == "hal@home.lan"
    assert c.get("/ui/api/profile").json()["pendingEmail"] == "hal@new.lan"
    _, token = last_link(server)
    assert c.post("/ui/api/email-change/confirm", json={"token": token}).status_code == 204
    assert c.get("/ui/api/profile").json()["email"] == "hal@new.lan"


# ---------- the active flag (S10.1.7) ----------


def test_deactivation_ends_sessions_and_reactivation_can_be_asked(admin_client, server):
    ivy = make_user(server, "ivy")
    c = sign_in(server, "ivy")
    row = next(u for u in admin_client.get("/ui/api/users").json()["items"] if u["id"] == ivy.id)
    assert saved(change(admin_client, "User", row, active=False))["active"] is False
    assert c.get("/ui/api/session").status_code == 401
    with new_client(server) as again:
        r = again.post("/ui/api/session", json={"login": "ivy", "password": PW})
        assert r.status_code == 403 and r.json()["code"] == "account-disabled"
        r = again.post("/ui/api/session", json={"login": "ivy", "password": "wrong"})
        assert r.status_code == 401  # a wrong password says nothing about the account
        body = {"login": "ivy", "password": PW}
        assert again.post("/ui/api/reactivation-requests", json=body).status_code == 204
    row = next(u for u in admin_client.get("/ui/api/users").json()["items"] if u["id"] == ivy.id)
    assert row["reactivationAskedAt"] is not None


def test_a_reactivation_request_answers_the_same_whatever_the_account(admin_client, server):
    # S10.1.7: right or wrong, active or not, asked already or not: one answer; a wrong
    # password counts as a sign-in's.
    ivy = make_user(server, "ivy")
    make_user(server, "jo")
    row = next(u for u in admin_client.get("/ui/api/users").json()["items"] if u["id"] == ivy.id)
    saved(change(admin_client, "User", row, active=False))
    asked = "/ui/api/reactivation-requests"
    with new_client(server) as c:
        answers = [
            c.post(asked, json=body).status_code
            for body in (
                {"login": "ivy", "password": PW},
                {"login": "ivy", "password": PW},
                {"login": "jo", "password": PW},
                {"login": "jo", "password": "wrong"},
                {"login": "nobody", "password": "wrong"},
            )
        ]
        assert answers == [204] * 5
    assert kinds(server).count("signin.failed") == 2
    assert kinds(server).count("user.reactivation-asked") == 1


def test_a_wrong_password_asked_again_counts_toward_the_lockout(server, monkeypatch):
    # S13.7.5.1: re-authentication and the current password are guarded as a sign-in is.
    from moolakata.ui import session

    monkeypatch.setattr(session.time, "sleep", lambda s: None)
    make_user(server, "kim")
    c = sign_in(server, "kim")
    for _ in range(5):
        assert c.post("/ui/api/session/reauth", json={"password": "wrong"}).status_code == 401
    for _ in range(5):
        r = c.post(
            "/ui/api/profile/password",
            json={"currentPassword": "wrong", "newPassword": "another long passphrase"},
        )
        assert r.status_code == 422 and r.json()["code"] == "password-wrong"
    assert c.post("/ui/api/session/reauth", json={"password": PW}).status_code == 429


def test_the_last_admin_stays(admin_client, server):
    with server.db.read() as s:
        admin = s.scalars(select(User).where(User.username == "admin")).one()
        admins = accounts.admins_group(s)
    row = next(u for u in admin_client.get("/ui/api/users").json()["items"] if u["id"] == admin.id)
    r = change(admin_client, "User", row, active=False)
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "last-admin"
    g = next(g for g in admin_client.get("/ui/api/groups").json()["items"] if g["id"] == admins.id)
    r = change(admin_client, "Group", g, memberIds={"add": [], "remove": g["memberIds"]})
    assert r.status_code == 409
    for fields in ({"name": "Bosses"}, {"active": False}):
        r = change(admin_client, "Group", g, **fields)
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "group-built-in"


def test_groups(admin_client, server):
    a, b = make_user(server, "amy"), make_user(server, "ben")
    r = make(admin_client, "Group", name="Household", memberIds=[a.id])
    assert r.status_code == 200
    g = r.json()
    r = make(admin_client, "Group", name="household")
    assert r.json()["errors"][0]["code"] == "name-taken"
    out = saved(change(admin_client, "Group", g, name="Family",
                       memberIds={"add": [b.id], "remove": []}))  # fmt: skip
    assert sorted(out["memberIds"]) == sorted([a.id, b.id])
    r = change(admin_client, "Group", g, name="Stale")
    assert r.status_code == 412 and r.json()["current"][0]["current"]["name"] == "Family"
    rows = {u["username"]: u for u in admin_client.get("/ui/api/users").json()["items"]}
    assert rows["ben"]["groupIds"] == [g["id"]]


# ---------- profile ----------


def test_profile_changes_are_checked_and_versioned(server):
    make_user(server, "joy")
    c = sign_in(server, "joy")
    p = c.get("/ui/api/profile").json()
    assert p["timeZone"] == "auto" and p["zone"]
    r = change(c, "User", p, timeZone="America/Denver", theme="light", birthYear=1979)
    assert saved(r)["zone"] == "America/Denver" and saved(r)["version"] == p["version"] + 1
    r = change(c, "User", p, theme="dark")
    assert r.status_code == 412
    v = r.json()["current"][0]["current"]["version"]
    for bad in (
        {"timeZone": "Mars/Base"},
        {"avatar": "javascript:alert(1)"},
        {"theme": "neon"},
        {"birthYear": 1200},
    ):
        r = change(c, "User", {"id": p["id"], "version": v}, **bad)
        assert r.status_code == 422, bad
        assert r.json()["errors"][0]["field"] == next(iter(bad))


def test_a_users_profile_is_theirs_and_their_email_changes_by_request(server, admin_client):
    make_user(server, "kit")
    kit = sign_in(server, "kit")
    row = next(
        u for u in admin_client.get("/ui/api/users").json()["items"] if u["username"] == "kit"
    )
    r = change(admin_client, "User", row, theme="light")
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "own-profile"
    p = kit.get("/ui/api/profile").json()
    assert change(kit, "User", p, email="kit@else.lan").status_code == 403
    assert change(kit, "User", p, active=False).status_code == 403


# ---------- settings ----------


def test_settings_are_checked_together_and_recorded(admin_client, server):
    r = admin_client.get("/ui/api/settings")
    assert r.json()["values"]["passwordMinLength"] == 12
    r = save_settings(admin_client, {"passwordMinLength": 4, "backupTime": "9pm"})
    assert {e["field"] for e in r.json()["errors"]} == {"passwordMinLength", "backupTime"}
    assert admin_client.get("/ui/api/settings").json()["values"]["passwordMinLength"] == 12
    r = save_settings(admin_client, {"passwordMinLength": 14, "householdName": "The Griffins"})
    assert r.status_code == 200
    assert admin_client.get("/ui/api/session").json()["household"]["name"] == "The Griffins"
    assert "settings.changed" in kinds(server)


# ---------- the live stream (S12.6) ----------


def test_the_stream_says_hello_and_ends(server):
    make_user(server, "kim")
    c = sign_in(server, "kim")
    server.stream_seconds = 0.2
    with c.stream("GET", "/ui/api/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: hello" in body and '"version"' in body


def test_a_sign_in_from_a_new_address_is_emailed(client, server):
    """S10.1.9: once a user has signed in from somewhere, a sign-in from an address not seen
    in 30 days sends them a notice; the same address again does not."""
    from conftest import ORIGIN
    from fastapi.testclient import TestClient

    set_public_url(server)
    make_user(server, "gil")
    sign_in(server, "gil")  # the first address seen: nothing to compare with
    sign_in(server, "gil")
    assert [m["Subject"] for m in mails(server)] == []
    far = TestClient(client.app, base_url=ORIGIN, client=("203.0.113.9", 50000))
    r = far.post(
        "/ui/api/session", json={"login": "gil", "password": PW}, headers={"Origin": ORIGIN}
    )
    assert r.status_code == 200, r.text
    subjects = [m["Subject"] for m in mails(server)]
    assert subjects == ["A sign-in to MoolaKata from a new address"]
    assert "signin.new-address" in kinds(server)
    far.post("/ui/api/session", json={"login": "gil", "password": PW}, headers={"Origin": ORIGIN})
    assert len(mails(server)) == 1  # now a known address


def test_making_an_admin_needs_the_password_again(admin_client, server):
    """S13.7.2: changing who is in Admins, whichever route does it."""
    from conftest import stale

    from moolakata.auth import users as accounts

    with server.db.read() as s:
        admins = accounts.admins_group(s).id
    make_user(server, "ivy")
    listed = admin_client.get("/ui/api/users").json()["items"]
    ivy = next(u for u in listed if u["username"] == "ivy")
    stale(server)
    # A change that leaves Admins alone asks nothing.
    ivy = saved(change(admin_client, "User", ivy, displayName="Ivy L."))
    r = change(admin_client, "User", ivy, groupIds={"add": [admins], "remove": []})
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "reauth-required"
    r = make(
        admin_client,
        "User",
        displayName="Jo",
        username="jo",
        email="jo@home.lan",
        sex="female",
        groupIds=[admins],
    )
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "reauth-required"
