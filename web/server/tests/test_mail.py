"""SMTP and emails (requirements S10.1.9, S16.2) and sign-up (S10.1.4)."""

import re
import smtplib
from typing import ClassVar

import pytest
from conftest import make_user, new_client
from edits import save_settings
from test_users import kinds, mails, set_public_url

from moolakata import settings
from moolakata.mail import smtp_settings, written

PW = "a long user passphrase"


class FakeSmtp:
    """Stands in for smtplib.SMTP: records what was sent, or fails as told."""

    sent: ClassVar[list] = []
    logins: ClassVar[list] = []
    fail: ClassVar[Exception | None] = None
    starttls_done: ClassVar[bool] = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        FakeSmtp.starttls_done = True

    def login(self, user, password):
        FakeSmtp.logins.append((user, password))
        if password == "wrong":
            raise smtplib.SMTPAuthenticationError(535, b"no")

    def send_message(self, msg, from_addr=None):
        if FakeSmtp.fail:
            raise FakeSmtp.fail
        FakeSmtp.sent.append((from_addr, msg))


@pytest.fixture
def smtp(monkeypatch, server):
    FakeSmtp.sent, FakeSmtp.logins, FakeSmtp.fail, FakeSmtp.starttls_done = [], [], None, False
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)
    # The mail server's name resolves on the LAN, and the guard connects to what it found.
    from moolakata import net

    server.guard = net.Guard(resolver=lambda host, port: ["192.0.2.25"])
    server.guard.allow(["smtp.home.lan"], allowed_by_name=["smtp.home.lan"])
    return FakeSmtp


def set_up_smtp(admin_client, password="app password"):
    r = save_settings(
        admin_client,
        {
            "smtpHost": "smtp.home.lan",
            "smtpUsername": "money@home.lan",
            "smtpFrom": "MoolaKata <money@home.lan>",
            "smtpPassword": password,
        },
    )
    assert r.status_code == 200, r.text
    assert password not in r.text, "never read back"
    r = admin_client.get("/ui/api/settings/email")
    assert r.json()["password"]["setBy"] == "Ada Admin"


def test_settings_check_the_smtp_fields(admin_client):
    for key, bad in (
        ("smtpHost", "not a host!"),
        ("smtpPort", 0),
        ("smtpSecurity", "ssl3"),
        ("smtpFrom", "nobody"),
    ):
        r = save_settings(admin_client, {key: bad})
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == key, key


def test_the_password_is_a_secret_never_read_back(admin_client, server):
    set_up_smtp(admin_client)
    body = admin_client.get("/ui/api/settings/email").text
    assert (
        "app password" not in body
        and "app password" not in admin_client.get("/ui/api/settings").text
    )
    with server.db.read() as s:
        assert smtp_settings(s, server.keys.secrets).password == "app password"


def test_with_smtp_emails_go_through_the_outbox(admin_client, server, smtp):
    set_up_smtp(admin_client)
    set_public_url(server)
    before = len(mails(server))
    r = admin_client.post(
        "/ui/api/users",
        json={"displayName": "Dave", "username": "dave", "email": "dave@x.lan", "sex": "male"},
    )
    assert r.status_code == 201
    assert len(mails(server)) == before, "not written to the mail folder"
    assert len(server.services.mailer.waiting()) == 1
    assert server.services.mailer.send_waiting(_smtp(server), server.guard) == 1
    assert server.services.mailer.waiting() == []
    from_addr, msg = smtp.sent[0]
    assert from_addr == "money@home.lan" and msg["From"] == "MoolaKata <money@home.lan>"
    assert msg["To"] == "dave@x.lan" and smtp.starttls_done
    assert smtp.logins == [("money@home.lan", "app password")]


def _smtp(server):
    with server.db.read() as s:
        return smtp_settings(s, server.keys.secrets)


def test_a_failure_keeps_the_email_and_says_why(admin_client, server, smtp):
    set_up_smtp(admin_client, password="wrong")
    set_public_url(server)
    admin_client.post(
        "/ui/api/users",
        json={"displayName": "Dave", "username": "dave", "email": "dave@x.lan", "sex": "male"},
    )
    with pytest.raises(RuntimeError, match="refused the username or password"):
        server.services.mailer.send_waiting(_smtp(server), server.guard)
    assert len(server.services.mailer.waiting()) == 1
    # A recipient the server will never take is set aside, and the rest go on.
    smtp.fail = smtplib.SMTPRecipientsRefused({"dave@x.lan": (550, b"no such user")})
    save_settings(admin_client, {"smtpPassword": "right"})
    assert server.services.mailer.send_waiting(_smtp(server), server.guard) == 0
    assert admin_client.get("/ui/api/settings/email").json()["setAside"] == 1


def test_emails_wait_in_the_database_until_sent_or_their_link_expires(admin_client, server, smtp):
    # S16.2, S15.1.7: queued in the encrypted database, never in a folder in the clear; one
    # whose link has expired is dropped unsent; a refused one keeps only who, what and why.
    import datetime as dt

    from moolakata import clock
    from moolakata.store.entities.core import QueuedEmail

    set_up_smtp(admin_client)
    set_public_url(server)
    for name in ("dave", "erin"):
        admin_client.post(
            "/ui/api/users",
            json={"displayName": name, "username": name, "email": f"{name}@x.lan", "sex": "male"},
        )
    assert not server.config.outbox_dir.exists(), "nothing in the data directory in the clear"
    assert [w.recipient for w in server.services.mailer.waiting()] == ["dave@x.lan", "erin@x.lan"]
    smtp.fail = smtplib.SMTPRecipientsRefused({"dave@x.lan": (550, b"no such user")})
    assert server.services.mailer.send_waiting(_smtp(server), server.guard) == 0
    with server.db.read() as s:
        refused = s.query(QueuedEmail).filter(QueuedEmail.refusedAt.is_not(None)).all()
        assert [(r.recipient, r.message) for r in refused] == [
            ("dave@x.lan", None),
            ("erin@x.lan", None),
        ]
        assert all(r.error for r in refused)
    assert server.services.mailer.waiting() == []
    smtp.fail = None
    admin_client.post(
        "/ui/api/users",
        json={"displayName": "fay", "username": "fay", "email": "fay@x.lan", "sex": "female"},
    )
    clock.fix(clock.now() + dt.timedelta(days=8))  # past even an invitation's week
    try:
        assert server.services.mailer.waiting() == []
        assert server.services.mailer.expire() == 3
    finally:
        clock.fix(None)
    assert smtp.sent == []


def test_an_earlier_outbox_moves_into_the_queue(server):
    # What an earlier release left in outbox/ in the clear moves into the database.
    from email.message import EmailMessage

    folder = server.config.outbox_dir
    folder.mkdir(parents=True)
    msg = EmailMessage()
    msg["To"], msg["Subject"] = "fay@x.lan", "Choose your password"
    msg.set_content("https://mk.test/ui/reset#token")
    (folder / "20261017-120000-000000-0000000a.eml").write_bytes(bytes(msg))
    assert server.services.mailer.adopt_outbox() == 1
    assert not folder.exists()
    (w,) = server.services.mailer.waiting()
    assert w.recipient == "fay@x.lan" and "ui/reset" in w.message.get_content()


def test_a_written_invitation_stays_a_week_and_the_rest_a_day(server):
    # S16.2: a written email stays as long as its link works.
    import datetime as dt

    from moolakata.mail import Email, expire_written

    with server.db.tx() as s:
        server.services.mailer.send(
            s, Email("gus@x.lan", "invited", "link", keep=dt.timedelta(days=7))
        )
        server.services.mailer.send(s, Email("gus@x.lan", "reset", "link"))
    now = dt.datetime.now(dt.UTC)
    assert expire_written(server.config, now + dt.timedelta(days=2)) == 1
    assert [m.subject for m in written(server.config)] == ["invited"]
    assert expire_written(server.config, now + dt.timedelta(days=8)) == 1


def test_a_reset_email_goes_when_its_link_stops_working(client, server):
    # S16.2, C9: a reset link works an hour, so its written email is kept an hour, not a day.
    import datetime as dt

    from moolakata.mail import expire_written

    set_public_url(server)
    make_user(server, "fay")
    assert client.post("/ui/api/password-reset", json={"login": "fay"}).status_code == 204
    assert [m.subject for m in written(server.config)] == ["Reset your MoolaKata password"]
    now = dt.datetime.now(dt.UTC)
    assert expire_written(server.config, now + dt.timedelta(minutes=50)) == 0
    assert expire_written(server.config, now + dt.timedelta(minutes=70)) == 1


def test_the_egress_guard_refuses_a_host_not_in_settings(admin_client, server, smtp):
    set_up_smtp(admin_client)
    server.guard.allow([])
    r = admin_client.post("/ui/api/settings/email/test")
    assert r.status_code == 502 and "not a host MoolaKata is set up to reach" in r.json()["detail"]


def test_send_a_test_email(admin_client, server, smtp):
    r = admin_client.post("/ui/api/settings/email/test")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "smtpHost"
    set_up_smtp(admin_client)
    r = admin_client.post("/ui/api/settings/email/test")
    assert r.status_code == 200 and r.json()["to"] == "admin@home.lan"
    assert smtp.sent[0][1]["Subject"] == "MoolaKata test email"
    smtp.fail = OSError("Connection refused")
    r = admin_client.post("/ui/api/settings/email/test")
    assert r.status_code == 502 and "could not reach the SMTP server" in r.json()["detail"]


# ---------- sign-up (S10.1.4) ----------


def open_signup(admin_client, server, domains=()):
    set_up_smtp(admin_client)
    set_public_url(server)
    r = save_settings(admin_client, {"signupEnabled": True, "signupDomains": list(domains)})
    assert r.status_code == 200, r.text


def sign_up(server, email="erin@shaw.family", username="erin"):
    with new_client(server) as c:
        return c.post(
            "/ui/api/signup",
            json={
                "displayName": "Erin Shaw",
                "username": username,
                "email": email,
                "password": PW,
                "sex": "female",
            },
        )


def outbox_link(server) -> tuple[str, str]:

    msg = server.services.mailer.waiting()[-1].message
    url = re.search(r"https://\S+", msg.get_body().get_content()).group(0)
    p, _, token = url.partition("#")
    return p, token


def test_sign_up_needs_smtp_and_the_public_url(admin_client, server):
    r = save_settings(admin_client, {"signupEnabled": True})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "signupEnabled"
    with new_client(server) as c:
        assert c.get("/ui/api/signup").json() == {"open": False, "domains": []}
    assert sign_up(server).status_code == 403


def test_sign_up_confirm_and_approve(admin_client, server, smtp):
    open_signup(admin_client, server)
    with new_client(server) as c:
        assert c.get("/ui/api/signup").json()["open"] is True
    assert sign_up(server).status_code == 204
    path, token = outbox_link(server)
    assert path.endswith("/ui/signup/confirm")
    assert admin_client.get("/ui/api/signup-requests").json()["items"] == [], "not until confirmed"
    with new_client(server) as c:
        r = c.post("/ui/api/signup/confirm", json={"token": token})
        assert r.status_code == 200 and r.json()["displayName"] == "Erin Shaw"
        assert c.post("/ui/api/signup/confirm", json={"token": token}).status_code == 404
        # Not a user yet.
        r = c.post("/ui/api/session", json={"login": "erin", "password": PW})
        assert r.status_code == 401
    rows = admin_client.get("/ui/api/signup-requests").json()["items"]
    assert [r["username"] for r in rows] == ["erin"]
    groups = admin_client.get("/ui/api/groups").json()["items"]
    r = admin_client.post(
        f"/ui/api/signup-requests/{rows[0]['id']}/approve", json={"groupIds": [groups[0]["id"]]}
    )
    assert r.status_code == 200 and r.json()["groupIds"] == [groups[0]["id"]]
    assert admin_client.get("/ui/api/signup-requests").json()["items"] == []
    with new_client(server) as c:
        r = c.post("/ui/api/session", json={"login": "erin@shaw.family", "password": PW})
        assert r.status_code == 200
    assert {"signup.requested", "signup.approved"} <= set(kinds(server))
    assert "Your MoolaKata account is ready" in server.services.mailer.waiting()[-1].subject


def test_sign_up_rejected(admin_client, server, smtp):
    open_signup(admin_client, server)
    sign_up(server)
    _, token = outbox_link(server)
    with new_client(server) as c:
        c.post("/ui/api/signup/confirm", json={"token": token})
    rid = admin_client.get("/ui/api/signup-requests").json()["items"][0]["id"]
    assert admin_client.post(f"/ui/api/signup-requests/{rid}/reject").status_code == 204
    assert admin_client.post(f"/ui/api/signup-requests/{rid}/approve", json={}).status_code == 404
    assert "signup.rejected" in kinds(server)


def test_sign_up_never_says_an_email_has_an_account(admin_client, server, smtp):
    open_signup(admin_client, server)
    make_user(server, "bob", email="bob@home.lan")
    waiting = len(server.services.mailer.waiting())
    hashed = []
    from moolakata.auth import passwords

    real = passwords.hash_password
    passwords.hash_password = lambda pw: hashed.append(pw) or real(pw)
    try:
        r = sign_up(server, email="Bob@home.lan", username="bobby")
    finally:
        passwords.hash_password = real
    assert r.status_code == 204
    assert len(server.services.mailer.waiting()) == waiting, "no link for a known address"
    assert len(hashed) == 1, "hashed all the same, so it takes as long (S10.1.4.1)"


def test_sign_up_checks_its_fields_and_domains(admin_client, server, smtp):
    open_signup(admin_client, server, domains=["shaw.family"])
    make_user(server, "bob")
    r = sign_up(server, email="erin@elsewhere.lan")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "email-domain"
    r = sign_up(server, username="bob")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "username"
    with new_client(server) as c:
        r = c.post(
            "/ui/api/signup",
            json={
                "displayName": "Erin",
                "username": "erin",
                "email": "erin@shaw.family",
                "password": "short",
            },
        )
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "password"


def test_signup_settings_are_off_by_default(server):
    with server.db.read() as s:
        assert settings.get(s, "signupEnabled") is False


def test_written_emails_are_listed_for_admins_and_expire(admin_client, server, tmp_path):
    """S16.2: with no SMTP host, each email is written to the mail folder; Settings › Email
    lists them, shows one after the password again, and the mail task removes those older
    than their links' life."""
    import datetime as dt

    from conftest import ORIGIN

    from moolakata import mail, settings

    with server.db.tx() as s:
        settings.put(s, "publicUrl", ORIGIN, None)
    make_user(server, "carol")
    r = admin_client.post(
        "/ui/api/users",
        json={
            "displayName": "Dave",
            "username": "dave",
            "email": "dave@example.com",
            "sex": "male",
        },
    )
    assert r.status_code == 201, r.text
    listed = admin_client.get("/ui/api/settings/email/written").json()["items"]
    assert (
        listed and listed[0]["to"] == "dave@example.com" and "invit" in listed[0]["subject"].lower()
    )
    name = listed[0]["name"]
    r = admin_client.get(f"/ui/api/settings/email/written/{name}")
    assert r.status_code == 200 and "https://" in r.json()["text"]
    # Opening one is recorded for the person it is addressed to (S10.2).
    from moolakata.store.entities.core import Activity
    from moolakata.store.entities.users import User

    with server.db.read() as s:
        dave = s.query(User).filter_by(username="dave").one()
        opened = s.query(Activity).filter_by(kind="email.opened").one()
        assert opened.ownerId == dave.id and opened.forAdmins
    assert admin_client.get("/ui/api/settings/email/written/../x.eml").status_code in (404, 422)
    # An invitation's link works for a week, and its written email stays as long (S16.2).
    week = dt.datetime.now(dt.UTC) + dt.timedelta(days=7, hours=1)
    assert mail.expire_written(server.config, week) == 1
    assert admin_client.get("/ui/api/settings/email/written").json()["items"] == []


def test_a_new_smtp_host_needs_the_password_again_and_clears_the_old_password(
    admin_client, server, smtp
):
    """S16.2, S13.7.2: the stored password belongs to its host, so it never goes to a new one."""
    from conftest import stale

    from moolakata.mail import SMTP_SECRET
    from moolakata.store.repos import secrets as secret_repo

    set_up_smtp(admin_client)
    stale(server)
    r = save_settings(admin_client, {"smtpHost": "smtp.elsewhere.example"})
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "reauth-required"
    # The same host saved again, and other fields, ask nothing.
    r = save_settings(admin_client, {"smtpHost": "smtp.home.lan", "smtpPort": 465})
    assert r.status_code == 200, r.text
    r = save_settings(admin_client, {"publicUrl": "https://elsewhere.example"})
    assert r.status_code == 403
    r = admin_client.post("/ui/api/session/reauth", json={"password": "a long admin passphrase"})
    assert r.status_code == 204
    r = save_settings(admin_client, {"smtpHost": "smtp.elsewhere.example"})
    assert r.status_code == 200, r.text
    with server.db.read() as s:
        assert secret_repo.info(s, *SMTP_SECRET) is None
    assert admin_client.get("/ui/api/settings/email").json()["password"] is None
