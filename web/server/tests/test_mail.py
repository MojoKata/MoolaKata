"""SMTP and emails (requirements S10.1.9, S16.2) and sign-up (S10.1.4)."""

import re
import smtplib
from typing import ClassVar

import pytest
from conftest import make_user, new_client
from edits import make, save_settings
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
    server.guard.allow(["smtp.home.lan"], allowed_by_name={"smtp": ["smtp.home.lan"]})
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
    with server.db.read(unscoped="test") as s:
        assert smtp_settings(s, server.keys.secrets).password == "app password"


def test_with_smtp_emails_go_through_the_outbox(admin_client, server, smtp):
    set_up_smtp(admin_client)
    set_public_url(server)
    before = len(mails(server))
    r = make(
        admin_client, "User", displayName="Dave", username="dave", email="dave@x.lan", sex="male"
    )
    assert r.status_code == 200
    assert len(mails(server)) == before, "not written to the mail folder"
    assert len(server.services.mailer.waiting()) == 1
    assert server.services.mailer.send_waiting(_smtp(server), server.guard) == 1
    assert server.services.mailer.waiting() == []
    from_addr, msg = smtp.sent[0]
    assert from_addr == "money@home.lan" and msg["From"] == "MoolaKata <money@home.lan>"
    assert msg["To"] == "dave@x.lan" and smtp.starttls_done
    assert smtp.logins == [("money@home.lan", "app password")]


def _smtp(server):
    with server.db.read(unscoped="test") as s:
        return smtp_settings(s, server.keys.secrets)


def test_a_failure_keeps_the_email_and_says_why(admin_client, server, smtp):
    set_up_smtp(admin_client, password="wrong")
    set_public_url(server)
    make(admin_client, "User", displayName="Dave", username="dave", email="dave@x.lan", sex="male")
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
        make(
            admin_client, "User", displayName=name, username=name, email=f"{name}@x.lan", sex="male"
        )
    assert not server.config.outbox_dir.exists(), "nothing in the data directory in the clear"
    assert [w.recipient for w in server.services.mailer.waiting()] == ["dave@x.lan", "erin@x.lan"]
    smtp.fail = smtplib.SMTPRecipientsRefused({"dave@x.lan": (550, b"no such user")})
    assert server.services.mailer.send_waiting(_smtp(server), server.guard) == 0
    with server.db.read(unscoped="test") as s:
        refused = s.query(QueuedEmail).filter(QueuedEmail.refusedAt.is_not(None)).all()
        assert [(r.recipient, r.message) for r in refused] == [
            ("dave@x.lan", None),
            ("erin@x.lan", None),
        ]
        assert all(r.error for r in refused)
    assert server.services.mailer.waiting() == []
    smtp.fail = None
    make(admin_client, "User", displayName="fay", username="fay", email="fay@x.lan", sex="female")
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

    with server.db.tx(unscoped="test") as s:
        server.services.mailer.send(
            s, Email("gus@x.lan", "invited", "link", keep=dt.timedelta(days=7))
        )
        server.services.mailer.send(s, Email("gus@x.lan", "reset", "link"))
    now = dt.datetime.now(dt.UTC)
    assert expire_written(server.config, now + dt.timedelta(days=2)) == 1
    assert [m.subject for m in written(server.config)] == ["invited"]
    assert expire_written(server.config, now + dt.timedelta(days=8)) == 1


def test_a_reset_email_goes_when_its_link_stops_working(client, server):
    # S16.2: a reset link works an hour, so its written email is kept an hour, not a day.
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
    make_user(server, "john", email="john@home.lan")
    waiting = len(server.services.mailer.waiting())
    hashed = []
    from moolakata.auth import passwords

    real = passwords.hash_password
    passwords.hash_password = lambda pw: hashed.append(pw) or real(pw)
    try:
        r = sign_up(server, email="John@home.lan", username="johnny")
    finally:
        passwords.hash_password = real
    assert r.status_code == 204
    assert len(server.services.mailer.waiting()) == waiting, "no link for a known address"
    assert len(hashed) == 1, "hashed all the same, so it takes as long (S10.1.4.1)"


def test_sign_up_checks_its_fields_and_domains(admin_client, server, smtp):
    open_signup(admin_client, server, domains=["shaw.family"])
    make_user(server, "john")
    r = sign_up(server, email="erin@elsewhere.lan")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "email-domain"
    r = sign_up(server, username="John Doe")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "username-invalid"
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


def test_sign_up_answers_the_same_whether_a_username_is_taken(admin_client, server, smtp):
    """S10.1.4.1: the answer to a request never says whether a username exists."""
    open_signup(admin_client, server)
    make_user(server, "john")
    taken, free = sign_up(server, "not-an-email", "john"), sign_up(server, "not-an-email", "jim")
    assert taken.status_code == free.status_code == 422
    assert taken.json()["errors"] == free.json()["errors"]
    assert [e["field"] for e in taken.json()["errors"]] == ["email"]
    waiting = len(server.services.mailer.waiting())
    assert sign_up(server, "erin@shaw.family", "john").status_code == 204
    assert len(server.services.mailer.waiting()) == waiting + 1, "the link goes out all the same"


def test_confirming_a_taken_username_asks_for_another(admin_client, server, smtp):
    """S10.1.4.1: the username is checked once the email is confirmed; a taken one is asked
    for again before the request reaches the admins."""
    open_signup(admin_client, server)
    make_user(server, "john")
    sign_up(server, "erin@shaw.family", "erin")
    _, first = outbox_link(server)
    sign_up(server, "erin@elsewhere.lan", "john")
    _, token = outbox_link(server)
    with new_client(server) as c:
        assert c.post("/ui/api/signup/confirm", json={"token": first}).status_code == 200
        r = c.post("/ui/api/signup/confirm", json={"token": token})
        assert r.status_code == 422, r.text
        assert [(e["field"], e["code"]) for e in r.json()["errors"]] == [
            ("username", "username-taken")
        ]
        assert [
            x["username"] for x in admin_client.get("/ui/api/signup-requests").json()["items"]
        ] == ["erin"], "not to the admins with a taken username"
        for name, code in (("erin", "username-taken"), ("Erin Shaw", "username-invalid")):
            r = c.post("/ui/api/signup/confirm", json={"token": token, "username": name})
            assert r.status_code == 422 and r.json()["errors"][0]["code"] == code, name
        r = c.post("/ui/api/signup/confirm", json={"token": token, "username": " Erin2 "})
        assert r.status_code == 200 and r.json()["displayName"] == "Erin Shaw"
        assert c.post("/ui/api/signup/confirm", json={"token": token}).status_code == 404
    rows = admin_client.get("/ui/api/signup-requests").json()["items"]
    assert sorted(x["username"] for x in rows) == ["erin", "erin2"]


def test_a_username_taken_after_confirming_is_refused_at_approval(admin_client, server, smtp):
    open_signup(admin_client, server)
    sign_up(server)
    _, token = outbox_link(server)
    with new_client(server) as c:
        assert c.post("/ui/api/signup/confirm", json={"token": token}).status_code == 200
    make_user(server, "erin", email="erin@home.lan")
    rid = admin_client.get("/ui/api/signup-requests").json()["items"][0]["id"]
    r = admin_client.post(f"/ui/api/signup-requests/{rid}/approve", json={})
    assert r.status_code == 409 and r.json()["code"] == "username-taken"


def test_signup_settings_are_off_by_default(server):
    with server.db.read(unscoped="test") as s:
        assert settings.get(s, "signupEnabled") is False


def test_written_emails_are_listed_for_admins_and_expire(admin_client, server, tmp_path):
    """S16.2: with no SMTP host, each email is written to the mail folder; Settings › Email
    lists them, shows one after the password again, and the mail task removes those older
    than their links' life."""
    import datetime as dt

    from conftest import ORIGIN

    from moolakata import mail, settings

    with server.db.tx(unscoped="test") as s:
        settings.put(s, "publicUrl", ORIGIN, None)
    make_user(server, "bart")
    r = make(
        admin_client,
        "User",
        displayName="Dave",
        username="dave",
        email="dave@example.com",
        sex="male",
    )
    assert r.status_code == 200, r.text
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

    with server.db.read(unscoped="test") as s:
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
    with server.db.read(unscoped="test") as s:
        assert secret_repo.info(s, *SMTP_SECRET) is None
    assert admin_client.get("/ui/api/settings/email").json()["password"] is None


# ---------- failures and edges, without a server ----------


@pytest.fixture
def stored(monkeypatch):
    """Settings as a session would read them, from a dict; the SMTP password none."""
    from moolakata.store.repos import secrets as secret_repo

    values: dict = {}
    monkeypatch.setattr(
        settings, "get", lambda s, key: values.get(key, settings.DEFINITIONS[key].default)
    )
    monkeypatch.setattr(secret_repo, "use", lambda *a: None)
    return values


def test_links_come_from_the_public_url_or_in_dev_mode_localhost(stored, config):
    """S16.1: a link is built from the public URL; dev mode has its own; else it is refused at
    the public URL, saying why."""
    import dataclasses

    from moolakata import mail
    from moolakata.errors import Problem

    dev = dataclasses.replace(config, dev=True, port=8443)
    assert mail.link(None, dev, "/ui/reset", "tok") == "https://localhost:8443/ui/reset#tok"
    with pytest.raises(Problem) as e:
        mail.link(None, config, "/ui/reset")
    [error] = e.value.errors
    assert (e.value.status, error.field, error.code) == (422, "publicUrl", "public-url-needed")
    assert error.message == (
        "Set the server's public URL in Settings › General first: links in emails are built "
        "from it."
    )
    stored["publicUrl"] = "https://money.example.lan"
    assert mail.link(None, config, "/ui/x") == "https://money.example.lan/ui/x"


@pytest.mark.parametrize(
    ("username", "sender"),
    [
        ("money@home.lan", "MoolaKata (The Shaws) <money@home.lan>"),
        ("money", "MoolaKata (The Shaws) <moolakata@smtp.home.lan>"),
        (None, "MoolaKata (The Shaws) <moolakata@smtp.home.lan>"),
    ],
)
def test_with_no_from_address_the_sender_is_the_household_at_the_username_or_host(
    stored, username, sender
):
    stored.update(smtpHost="smtp.home.lan", smtpUsername=username, householdName="The Shaws")
    assert smtp_settings(None, b"k").sender == sender


def test_no_smtp_host_is_no_smtp(stored):
    assert smtp_settings(None, b"k") is None


def _ssl_error(reason):
    """An SSLError as the ssl module raises it: with its reason, which may be none."""
    import ssl

    e = ssl.SSLCertVerificationError(1, "[SSL] PEM lib")
    e.reason = reason
    return e


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (
            smtplib.SMTPAuthenticationError(535, b"no"),
            "the SMTP server refused the username or password",
        ),
        (
            smtplib.SMTPNotSupportedError(),
            "the SMTP server does not offer STARTTLS: try TLS or None",
        ),
        (smtplib.SMTPRecipientsRefused({}), "the SMTP server refused the recipient's address"),
        (smtplib.SMTPSenderRefused(553, b"no", "x@y"), "the SMTP server refused the From address"),
        (_ssl_error("CERTIFICATE_VERIFY_FAILED"), "TLS failed: CERTIFICATE_VERIFY_FAILED"),
        (_ssl_error(None), "TLS failed: [SSL] PEM lib"),
        (TimeoutError("timed out"), "could not reach the SMTP server: timed out"),
        (ConnectionRefusedError("refused"), "could not reach the SMTP server: refused"),
        (RuntimeError("odd"), "odd"),
        (RuntimeError(), "RuntimeError"),
    ],
)
def test_a_failure_is_described_in_words_an_admin_can_act_on(error, words):
    from moolakata.mail import describe

    assert describe(error) == words


class _Guard:
    def check(self, host, port, purpose):
        assert purpose == "smtp"
        return "192.0.2.25"


def test_tls_connects_to_the_address_the_guard_checked_and_none_skips_starttls_and_login(
    monkeypatch,
):
    """S13.5, S16.2: TLS from the start through SMTP_SSL, its socket opened to the vetted
    address while TLS names the host; with security none and no username, no STARTTLS and no
    login."""
    from email.message import EmailMessage

    from moolakata import mail

    opened = []

    class Base(FakeSmtp):
        def _get_socket(self, host, port, timeout):
            opened.append((host, port))

        def __init__(self, host, port, timeout=None, context=None):
            super().__init__(host, port, timeout, context)
            self._get_socket(host, port, timeout)

    FakeSmtp.sent, FakeSmtp.logins, FakeSmtp.fail, FakeSmtp.starttls_done = [], [], None, False
    monkeypatch.setattr(smtplib, "SMTP_SSL", Base)
    monkeypatch.setattr(smtplib, "SMTP", Base)
    msg = EmailMessage()
    msg["To"], msg["From"] = "dave@x.lan", "placeholder"
    smtp = mail.Smtp("smtp.home.lan", 465, "tls", None, None, "Money <money@home.lan>")
    mail.deliver(smtp, msg, _Guard())
    assert opened == [("192.0.2.25", 465)]
    assert FakeSmtp.sent[0][0] == "money@home.lan" and msg["From"] == "Money <money@home.lan>"
    assert not FakeSmtp.starttls_done and FakeSmtp.logins == []
    mail.deliver(mail.Smtp("smtp.home.lan", 25, "none", None, None, "m@h.lan"), msg, _Guard())
    assert opened[-1] == ("192.0.2.25", 25) and not FakeSmtp.starttls_done


def test_the_mail_folder_passes_over_what_it_cant_read(config):
    """S16.2: an .eml that isn't one written (a name not the clock's) or can't be read is left
    out of the list, not shown nor removed; a name `written` never gave reads as nothing."""
    import datetime as dt

    from moolakata import mail

    assert mail.written(config) == []
    assert mail.expire_written(config) == 0, "no folder: nothing to expire"
    folder = config.mail_dir
    folder.mkdir(parents=True)
    (folder / "notes.eml").write_text("To: a@b.lan\n\nhello")
    (folder / "20261017-120000-000000-0000000a.eml").mkdir()  # can't be read
    assert mail.written(config) == []
    assert mail.read_written(config, "notes.eml") is None
    assert mail.read_written(config, "../20261017-120000-000000-0000000b.eml") is None
    assert mail.read_written(config, "20261017-120000-000000-0000000a.eml") is None
    assert mail.read_written(config, "20261017-120000-000000-0000000c.eml") is None  # gone
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=2)
    assert mail.expire_written(config, later) == 1, "the readable one, a day old by its file"
    assert (folder / "20261017-120000-000000-0000000a.eml").is_dir()


def test_before_the_database_is_open_the_queue_is_empty(config):
    from moolakata.mail import Mailer

    mailer = Mailer(config)
    assert mailer.waiting() == []
    assert mailer.set_aside() == 0
    assert mailer.expire() == 0
    assert mailer.adopt_outbox() == 0
    assert mailer.send_waiting(None, _Guard()) == 0, "no SMTP host: nothing sent"


def test_an_earlier_outbox_keeps_what_isnt_an_email_or_cant_be_read(server):
    folder = server.config.outbox_dir
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("not an email")
    (folder / "20261017-120000-000000-0000000a.eml").mkdir()
    assert server.services.mailer.adopt_outbox() == 0
    assert sorted(p.name for p in folder.iterdir()) == [
        "20261017-120000-000000-0000000a.eml",
        "notes.txt",
    ]


def test_the_mail_task_stops_when_told_and_minds_an_email_gone_meanwhile(config, monkeypatch):
    """The mail task stops between emails when the server does; an email removed while it was
    being sent (expired meanwhile) is counted sent all the same."""
    import contextlib
    import datetime as dt
    import threading
    from email.message import EmailMessage

    from moolakata import mail

    class Session:
        def get(self, cls, key):
            return None

    class Db:
        @contextlib.contextmanager
        def tx(self, unscoped):
            yield Session()

    mailer = mail.Mailer(config, db=Db)
    waiting = [mail.Waiting("Email_1", "a@b.lan", "s", dt.datetime.now(dt.UTC), EmailMessage())]
    monkeypatch.setattr(mailer, "waiting", lambda: waiting)
    delivered = []
    monkeypatch.setattr(mail, "deliver", lambda smtp, msg, guard: delivered.append(msg))
    smtp = mail.Smtp("smtp.home.lan", 587, "starttls", None, None, "m@h.lan")
    stop = threading.Event()
    stop.set()
    assert mailer.send_waiting(smtp, _Guard(), stop) == 0 and delivered == []
    assert mailer.send_waiting(smtp, _Guard(), threading.Event()) == 1
    assert len(delivered) == 1


def test_security_none_refuses_a_sign_in_at_save(admin_client, server):
    """S16.2: a password never goes to the mail server unencrypted, so None is for a relay that
    needs no sign-in: a username or a stored password with it is refused at the key saved."""
    set_up_smtp(admin_client)
    r = save_settings(admin_client, {"smtpSecurity": "none", "smtpPort": 25})
    assert r.status_code == 422, r.text
    (e,) = r.json()["errors"]
    assert (e["field"], e["code"]) == ("smtpSecurity", "sign-in-needs-tls")
    assert e["message"] == "Sign-in needs STARTTLS or TLS."
    # The username taken away, the stored password still refuses it.
    r = save_settings(admin_client, {"smtpSecurity": "none", "smtpUsername": None})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "smtpSecurity"
    # Both taken away: a relay on the household's own network.
    r = save_settings(
        admin_client, {"smtpSecurity": "none", "smtpUsername": None, "smtpPassword": None}
    )
    assert r.status_code == 200, r.text
    # Then a username, or a password, is refused at its own field.
    r = save_settings(admin_client, {"smtpUsername": "money@home.lan"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "smtpUsername"
    r = save_settings(admin_client, {"smtpPassword": "app password"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "smtpPassword"
    # TLS again takes both.
    r = save_settings(
        admin_client,
        {"smtpSecurity": "tls", "smtpUsername": "money@home.lan", "smtpPassword": "pw"},
    )
    assert r.status_code == 200, r.text


def test_the_mailer_never_signs_in_over_a_plain_link(monkeypatch):
    """S16.2: with security None the mailer signs in to nothing, though settings saved some
    other way carry a username: the email fails before anything goes on the wire."""
    from email.message import EmailMessage

    from moolakata import mail

    opened = []

    class Plain(FakeSmtp):
        def __init__(self, host, port, timeout=None, context=None):
            opened.append((host, port))

    FakeSmtp.sent, FakeSmtp.logins = [], []
    monkeypatch.setattr(smtplib, "SMTP", Plain)
    msg = EmailMessage()
    msg["To"], msg["From"] = "dave@x.lan", "placeholder"
    smtp = mail.Smtp("smtp.home.lan", 25, "none", "money@home.lan", "pw", "m@h.lan")
    with pytest.raises(mail.PlainSignIn) as e:
        mail.deliver(smtp, msg, _Guard())
    words = "sign-in needs STARTTLS or TLS: set Security, or clear the username"
    assert mail.describe(e.value) == words
    assert opened == [] and FakeSmtp.logins == [] and FakeSmtp.sent == []
