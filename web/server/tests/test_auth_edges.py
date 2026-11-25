"""Users, sessions, Profile, tokens and two-step at their rarer edges (S10.1, S10.2, S10.9,
S13.7): each refusal at its field (or status), with its code and words, and the paths few
requests take."""

import datetime as dt

from conftest import make_user, new_client, sign_in
from edits import change, make, saved
from sqlalchemy import select
from test_users import kinds, mails, set_public_url

from moolakata.auth import users as accounts
from moolakata.store.entities.users import User, UserGroup

PW = "a long user passphrase"
NEW_PW = "another long passphrase"


def refused(r, status: int, field, code: str, message: str) -> None:
    """The answer refuses at `field` (None: the whole request), with that code and words."""
    assert r.status_code == status, r.text
    (e,) = r.json()["errors"]
    assert (e["field"], e["code"], e["message"]) == (field, code, message)


def save_refused(r, status: int, field, code: str, message: str) -> None:
    """A save refused, nothing of it kept: the refusal at `field` of its record."""
    assert r.status_code == status and r.json()["code"] == "save-refused", r.text
    (e,) = r.json()["errors"]
    assert (e["field"], e["code"], e["message"]) == (field, code, message)


def problem(r, status: int, code: str, detail: str) -> None:
    assert r.status_code == status, r.text
    assert (r.json()["code"], r.json()["detail"]) == (code, detail)


def _token(server, user_id: str, purpose: str, data: str | None = None, hours: float = 1):
    with server.db.tx(unscoped="test") as s:
        return accounts._issue(
            s, s.get(User, user_id), purpose, dt.timedelta(hours=hours), data=data
        )


def _set(server, user_id: str, **fields) -> None:
    with server.db.tx(unscoped="test") as s:
        u = s.get(User, user_id)
        for k, v in fields.items():
            setattr(u, k, v)


def _row(admin_client, user_id: str) -> dict:
    return next(u for u in admin_client.get("/ui/api/users").json()["items"] if u["id"] == user_id)


def _group_row(admin_client, group_id: str) -> dict:
    return next(
        g for g in admin_client.get("/ui/api/groups").json()["items"] if g["id"] == group_id
    )


LINK_GONE = "This link has expired or was already used."


# ---------- one-time links (S10.1.3, S10.1.5) ----------


def test_a_link_for_someone_made_inactive_meanwhile_is_gone(client, server):
    """An invitation, a reset or an email change for a user switched off since it was sent
    works no more, and is answered as a used link is, whatever it carries."""
    u = make_user(server, "ina")
    invited = _token(server, u.id, "invitation")
    reset = _token(server, u.id, "reset")
    moved = _token(server, u.id, "email-change", data="ina@new.lan")
    _set(server, u.id, active=False)
    r = client.post("/ui/api/invitations/accept", json={"token": invited, "password": NEW_PW})
    problem(r, 404, "link-not-valid", LINK_GONE)
    r = client.post("/ui/api/password-reset/confirm", json={"token": reset, "password": NEW_PW})
    problem(r, 404, "link-not-valid", LINK_GONE)
    r = client.post("/ui/api/email-change/confirm", json={"token": moved})
    problem(r, 404, "link-not-valid", LINK_GONE)


def test_an_expired_link_is_refused(client, server):
    """Answered as a used link is; the hourly prune removes it (S13.7.1)."""
    u = make_user(server, "exa")
    token = _token(server, u.id, "reset", hours=-1)
    r = client.post("/ui/api/password-reset/confirm", json={"token": token, "password": NEW_PW})
    problem(r, 404, "link-not-valid", LINK_GONE)
    assert sign_in(server, "exa")  # the password stands


def test_a_reset_checks_the_new_password_and_mails_only_an_address(client, server):
    u = make_user(server, "rae")
    token = _token(server, u.id, "reset")
    r = client.post("/ui/api/password-reset/confirm", json={"token": token, "password": "short"})
    refused(r, 422, "password", "password-too-short", "Use at least 12 characters.")
    _set(server, u.id, email=None)
    sent = len(mails(server))
    r = client.post("/ui/api/password-reset/confirm", json={"token": token, "password": NEW_PW})
    assert r.status_code == 204, "the link is still good after a refusal"
    assert len(mails(server)) == sent, "no address, no mail"
    assert kinds(server)[-1] == "user.password-reset"


def test_a_change_of_password_refuses_a_poor_new_one_at_its_field(server):
    make_user(server, "pat")
    c = sign_in(server, "pat")
    body = {"currentPassword": PW, "newPassword": "password1234"}
    refused(
        c.post("/ui/api/profile/password", json=body),
        422,
        "newPassword",
        "password-too-common",
        "This password is on the list of the most common ones. Choose another.",
    )
    assert sign_in(server, "pat")  # the password stands


def test_a_new_password_past_1024_characters_is_refused(server):
    """S13.7.3: at most 1,024 characters, at the field that took it."""
    make_user(server, "lon")
    c = sign_in(server, "lon")
    body = {"currentPassword": PW, "newPassword": "x" * 1025}
    refused(
        c.post("/ui/api/profile/password", json=body),
        422,
        "newPassword",
        "password-too-long",
        "Use at most 1,024 characters.",
    )
    body["newPassword"] = "x" * 1024
    assert c.post("/ui/api/profile/password", json=body).status_code == 204


# ---------- the setup step and the first admin (S10.1.2) ----------


def test_an_admins_setup_takes_their_name_and_sex_to_their_person(client, server):
    from moolakata import people

    u = make_user(server, "legacy", password=accounts.DEFAULT_PASSWORD, sex="male")
    _set(server, u.id, needsSetup=True)
    r = client.post("/ui/api/session", json={"login": "legacy", "password": "moolakata-setup"})
    assert r.status_code == 200
    body = {"password": NEW_PW, "email": "l@home.lan", "sex": "female"}
    r = client.post("/ui/api/session/setup", json={**body, "displayName": "Lee\tAnn"})
    refused(r, 422, "displayName", "name-invalid", people.ONE_LINE)
    r = client.post("/ui/api/session/setup", json={**body, "displayName": " Lee Ann "})
    assert r.status_code == 200, r.text
    with server.db.read(unscoped="test") as s:
        me = people.of_user(s, u.id)
        assert (s.get(User, u.id).displayName, me.name, me.sex) == ("Lee Ann",) * 2 + ("female",)
    problem(
        client.post("/ui/api/session/setup", json=body),
        409,
        "setup-done",
        "This account is already set up.",
    )


def test_the_first_admins_name_is_one_line(store, keyed_config):
    from moolakata import people
    from moolakata.app import Server

    srv = Server(config=keyed_config, store=store, ready=True)
    first = {"sex": "female", "email": "pat@home.lan", "password": NEW_PW}
    with new_client(srv) as c:
        r = c.post("/ui/api/welcome/admin", json={**first, "displayName": "Pat\nTester"})
    refused(r, 422, "displayName", "name-invalid", people.ONE_LINE)


# ---------- signing in (S10.1, S13.7.5) ----------


def test_a_blank_login_matches_nobody(client, server):
    with server.db.read(unscoped="test") as s:
        assert accounts.by_login(s, "   ") is None
    r = client.post("/ui/api/session", json={"login": "  ", "password": PW})
    problem(r, 401, "bad-credentials", "The username or password is not right.")


# ---------- users and groups, an admin's (S10.1, S10.2) ----------


def test_a_username_is_its_shape_and_stays(admin_client, server):
    set_public_url(server)
    r = make(admin_client, "User", displayName="Uma", username="-uma", email="u@home.lan",
             sex="female")  # fmt: skip
    refused(
        r,
        422,
        "username",
        "username-invalid",
        "2 to 32 lowercase letters, digits, dots, dashes or underscores, starting with a letter "
        "or digit.",
    )
    u = make_user(server, "uma")
    refused(
        change(admin_client, "User", _row(admin_client, u.id), username="uma2"),
        422,
        "username",
        "username-fixed",
        "A user keeps their username.",
    )


def test_a_joined_users_email_is_theirs_to_change(admin_client, server):
    u = make_user(server, "val")
    save_refused(
        change(admin_client, "User", _row(admin_client, u.id), email="val@else.lan"),
        409,
        "email",
        "email-change-by-user",
        "Once a user has joined, they change their own email address.",
    )


def test_an_admin_sets_a_users_groups_from_their_row(admin_client, server):
    set_public_url(server)
    u = make_user(server, "xia")
    family = make(admin_client, "Group", name="Family", memberIds=[]).json()
    lodgers = make(admin_client, "Group", name="Lodgers", memberIds=[u.id]).json()
    row = saved(change(admin_client, "User", _row(admin_client, u.id),
                       groupIds={"add": [family["id"]], "remove": [lodgers["id"]]}))  # fmt: skip
    assert row["groupIds"] == [family["id"]]
    assert _group_row(admin_client, lodgers["id"])["memberIds"] == []
    # Back in the group they left: their membership taken up again.
    row = saved(change(admin_client, "User", row, groupIds={"add": [lodgers["id"]], "remove": []}))
    assert sorted(row["groupIds"]) == sorted([family["id"], lodgers["id"]])
    with server.db.read(unscoped="test") as s:
        kept = s.scalars(
            select(UserGroup).where(UserGroup.userId == u.id, UserGroup.groupId == lodgers["id"])
        ).all()
    assert len(kept) == 1 and not kept[0].deleted


def test_an_invited_admin_gets_each_alert_by_email(admin_client, server):
    """S12.11.5: an admin starts on an email for each alert."""
    set_public_url(server)
    with server.db.read(unscoped="test") as s:
        admins = accounts.admins_group(s).id
    r = make(admin_client, "User", displayName="Yan", username="yan", email="yan@home.lan",
             sex="male", groupIds=[admins, admins])  # fmt: skip
    assert r.status_code == 200, r.text
    with server.db.read(unscoped="test") as s:
        u = s.scalars(select(User).where(User.username == "yan")).one()
        assert u.alertEmails == "each" and accounts.group_ids(s, u.id) == [admins]


def test_an_admin_leaves_the_admins_while_another_stays(admin_client, server):
    with server.db.read(unscoped="test") as s:
        admins = accounts.admins_group(s).id
        me = s.scalars(select(User.id).where(User.username == "admin")).one()
    other = make_user(server, "abe", admin=True)
    g = _group_row(admin_client, admins)
    out = saved(change(admin_client, "Group", g, memberIds={"add": [], "remove": [other.id]}))
    assert out["memberIds"] == [me]


def test_a_users_groups_are_groups_here(admin_client, server):
    u = make_user(server, "cal")
    r = change(admin_client, "User", _row(admin_client, u.id),
               groupIds={"add": ["Group_00000000000000000000000000"], "remove": []})  # fmt: skip
    save_refused(r, 422, "groupIds", "group-unknown", "Choose existing groups.")


def test_a_group_of_someone_unknown_is_refused(admin_client):
    r = make(admin_client, "Group", name="Ghosts", memberIds=["User_00000000000000000000000000"])
    refused(r, 422, "memberIds", "user-unknown", "Choose existing users.")


def test_reactivation_tells_the_user_by_email(admin_client, server):
    """S10.1.7: made active again, a user who has joined is told."""
    u = make_user(server, "zed")
    row = saved(change(admin_client, "User", _row(admin_client, u.id), active=False))
    _set(server, u.id, reactivationAskedAt=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    row = saved(change(admin_client, "User", _row(admin_client, u.id), active=True))
    assert row["active"] is True and row["reactivationAskedAt"] is None
    msg = mails(server)[-1]
    assert (msg["To"], msg["Subject"]) == ("zed@home.lan", "Your MoolaKata account is active again")
    assert "Ada Admin made your account active again" in msg.get_content()
    assert kinds(server)[-1] == "user.reactivated"
    # One invited who never joined has nothing to sign in with: no mail.
    ivy = make_user(server, "ivy")
    _set(server, ivy.id, passwordHash=None)
    saved(change(admin_client, "User", _row(admin_client, ivy.id), active=False))
    sent = len(mails(server))
    saved(change(admin_client, "User", _row(admin_client, ivy.id), active=True))
    assert len(mails(server)) == sent and kinds(server)[-1] == "user.reactivated"
