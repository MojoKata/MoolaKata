"""Emails (requirements S10.1.9): plain text. Until SMTP is set up (and always in dev mode)
each one is written to the mail folder as an .eml file; dev mode also prints its links.

With SMTP set up (S16.2), an email is queued in the database, which is encrypted, and the mail
task sends it at once, in the background, so a request never waits on the mail server. What
can't be sent stays queued and is tried again every five minutes, until its link expires; one
the server refuses outright keeps only its recipient, subject and the error. Settings › Email
shows the queue and the last error. The SMTP host is one the egress guard allows, by name
(S13.5).

Links are built from Settings › General's public URL, never from the request (S16.1). A
token rides in the link's fragment (#…), which browsers send to no server and no Referer.
"""

import contextlib
import datetime as dt
import email
import email.policy
import itertools
import logging
import os
import re
import secrets
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session

from . import clock, ids, settings
from .config import Config
from .errors import refuse

log = logging.getLogger("moolakata.mail")


# How long an email is kept, written or queued: as long as its link works (S16.2), which each
# email with a link says (a reset's an hour, an invitation's a week, S10.1); a day otherwise.
LINK_LIFE = dt.timedelta(days=1)
EXPIRES = "X-MoolaKata-Expires"


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str
    keep: dt.timedelta = LINK_LIFE  # how long its link works


def base_url(s: Session, config: Config) -> str:
    url = settings.get(s, "publicUrl")
    if url:
        return url
    if config.dev:
        return f"https://localhost:{config.port}"
    raise refuse(
        "publicUrl",
        "public-url-needed",
        "Set the server's public URL in Settings › General first: links in emails "
        "are built from it.",
    )


def link(s: Session, config: Config, path: str, token: str | None = None) -> str:
    url = base_url(s, config) + path
    return f"{url}#{token}" if token else url


SMTP_TIMEOUT = 20
SMTP_SECRET = ("Setting", "smtp", "password")


@dataclass(frozen=True)
class Smtp:
    host: str
    port: int
    security: str  # starttls, tls or none
    username: str | None
    password: str | None
    sender: str


def smtp_settings(s: Session, secrets_key: bytes) -> Smtp | None:
    """SMTP as Settings › Email has it, or None while no host is set."""
    from .store.repos import secrets as secret_repo

    host = settings.get(s, "smtpHost")
    if not host:
        return None
    username = settings.get(s, "smtpUsername")
    sender = settings.get(s, "smtpFrom")
    if not sender:
        household = settings.get(s, "householdName")
        address = username if username and "@" in username else f"moolakata@{host}"
        sender = f"MoolaKata ({household}) <{address}>"
    return Smtp(
        host=host,
        port=settings.get(s, "smtpPort"),
        security=settings.get(s, "smtpSecurity"),
        username=username,
        password=secret_repo.use(s, secrets_key, *SMTP_SECRET),
        sender=sender,
    )


def _vetted(cls, address: str):
    """An SMTP client that connects to the address the guard checked, while TLS still names
    and verifies the host (S13.5)."""

    class Vetted(cls):
        def _get_socket(self, host, port, timeout):
            return super()._get_socket(address, port, timeout)

    return Vetted


def deliver(smtp: Smtp, msg: EmailMessage, guard) -> None:
    """Hand one message to the SMTP server, through the egress guard."""
    address = guard.check(smtp.host, smtp.port)
    context = ssl.create_default_context()
    if smtp.security == "tls":
        conn = _vetted(smtplib.SMTP_SSL, address)(
            smtp.host, smtp.port, timeout=SMTP_TIMEOUT, context=context
        )
    else:
        conn = _vetted(smtplib.SMTP, address)(smtp.host, smtp.port, timeout=SMTP_TIMEOUT)
    with conn:
        conn.ehlo()
        if smtp.security == "starttls":
            conn.starttls(context=context)
            conn.ehlo()
        if smtp.username:
            conn.login(smtp.username, smtp.password or "")
        del msg["From"]
        del msg[EXPIRES]
        msg["From"] = smtp.sender
        conn.send_message(msg, from_addr=parseaddr(smtp.sender)[1])


def describe(e: Exception) -> str:
    """What went wrong, in words an admin can act on, never a password."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "the SMTP server refused the username or password"
    if isinstance(e, smtplib.SMTPNotSupportedError):
        return "the SMTP server does not offer STARTTLS: try TLS or None"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "the SMTP server refused the recipient's address"
    if isinstance(e, smtplib.SMTPSenderRefused):
        return "the SMTP server refused the From address"
    if isinstance(e, ssl.SSLError):
        return f"TLS failed: {e.reason or e}"
    if isinstance(e, TimeoutError | ConnectionError | OSError):
        return f"could not reach the SMTP server: {e}"
    return str(e) or type(e).__name__


_counter = itertools.count(1)
_NAME = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9]{6}-[0-9a-f]{8}\.eml$")


@dataclass
class Written:
    name: str
    to: str
    subject: str
    at: dt.datetime


def written(config: Config) -> list[Written]:
    """The emails in the mail folder, newest first, by their headers."""
    folder = config.mail_dir
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.eml"), reverse=True):
        try:
            msg = email.message_from_bytes(
                path.read_bytes(), _class=EmailMessage, policy=email.policy.default
            )
            at = dt.datetime.strptime(path.name[:22], "%Y%m%d-%H%M%S-%f").replace(tzinfo=dt.UTC)
        except OSError, ValueError:
            continue
        out.append(Written(path.name, str(msg["To"] or ""), str(msg["Subject"] or ""), at))
    return out


def read_written(config: Config, name: str) -> str | None:
    """One written email's text, by the name `written` gave it; nothing for any other name."""
    if not _NAME.match(name):
        return None
    path = config.mail_dir / name
    try:
        msg = email.message_from_bytes(
            path.read_bytes(), _class=EmailMessage, policy=email.policy.default
        )
    except OSError:
        return None
    return f"To: {msg['To']}\nSubject: {msg['Subject']}\n\n{msg.get_content()}"


def _expires(msg: EmailMessage, written_at: dt.datetime) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(str(msg[EXPIRES]))
    except TypeError, ValueError:
        return written_at + LINK_LIFE


def expire_written(config: Config, now: dt.datetime | None = None) -> int:
    """Remove written emails whose links have expired (S16.2); the count removed."""
    now = now or clock.now()
    folder = config.mail_dir
    if not folder.is_dir():
        return 0
    n = 0
    for path in folder.glob("*.eml"):
        try:
            msg = email.message_from_bytes(
                path.read_bytes(), _class=EmailMessage, policy=email.policy.default
            )
            at = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC)
            if now >= _expires(msg, at):
                path.unlink()
                n += 1
        except OSError:
            continue
    return n


@dataclass
class Waiting:
    """An email in the queue, as the mail task and Settings › Email see it."""

    id: str
    recipient: str
    subject: str
    queuedAt: dt.datetime
    message: EmailMessage


class Mailer:
    def __init__(self, config: Config, db: Callable[[], object] = lambda: None) -> None:
        self.config = config
        self.db = db  # the server's database once it is open, for the queue
        # Set once the background tasks exist: starts the mail task for a queued email.
        self.notify: Callable[[], None] = lambda: None

    def send(self, s: Session, email: Email) -> None:
        msg = EmailMessage()
        household = settings.get(s, "householdName")
        msg["From"] = f"MoolaKata ({household}) <moolakata@localhost>"
        msg["To"] = email.to
        msg["Subject"] = email.subject
        msg["Date"] = format_datetime(dt.datetime.now(dt.UTC))
        msg["Message-ID"] = make_msgid(domain="moolakata.local")
        expires = clock.now() + email.keep
        msg[EXPIRES] = expires.isoformat()
        msg.set_content(email.body)
        if not self.config.dev and settings.get(s, "smtpHost"):
            from .store.entities.core import QueuedEmail

            s.add(
                QueuedEmail(
                    id=ids.new_id("Email"),
                    recipient=email.to,
                    subject=email.subject,
                    message=msg.as_string(),
                    queuedAt=clock.now(),
                    expiresAt=expires,
                )
            )
            # Sent once the request's transaction has committed it.
            event.listen(s, "after_commit", lambda _: self.notify(), once=True)
            return
        self._write(msg)

    def _file(self, folder: Path, msg: EmailMessage) -> Path:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Named by the clock, so a frozen one (the generated mockup) names them the same
        # way every time; the suffix tells two written in one microsecond apart.
        stamp = clock.now().strftime("%Y%m%d-%H%M%S-%f")
        suffix = f"{next(_counter):08x}" if clock.frozen() else secrets.token_hex(4)
        path = folder / f"{stamp}-{suffix}.eml"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(bytes(msg))
        return path

    def _write(self, msg: EmailMessage) -> None:
        self._file(self.config.mail_dir, msg)
        if self.config.dev:
            links = [w for w in msg.get_content().split() if w.startswith("https://")]
            log.info("dev mail to %s: %s %s", msg["To"], msg["Subject"], " ".join(links))
        else:
            log.info("an email was written to the mail folder (SMTP is not set up)")

    def waiting(self) -> list[Waiting]:
        """The queue, oldest first: what is still to be sent, its link still working."""
        from sqlalchemy import select

        from .store.entities.core import QueuedEmail

        db = self.db()
        if db is None:
            return []
        with db.read(unscoped="mail: the emails waiting") as s:
            rows = s.scalars(
                select(QueuedEmail)
                .where(QueuedEmail.refusedAt.is_(None), QueuedEmail.expiresAt > clock.now())
                .order_by(QueuedEmail.queuedAt)
            ).all()
            return [
                Waiting(
                    r.id,
                    r.recipient,
                    r.subject,
                    r.queuedAt,
                    email.message_from_string(
                        r.message or "", _class=EmailMessage, policy=email.policy.default
                    ),
                )
                for r in rows
            ]

    def set_aside(self) -> int:
        """Emails the SMTP server refused outright, kept as recipient, subject and error."""
        from sqlalchemy import func, select

        from .store.entities.core import QueuedEmail

        db = self.db()
        if db is None:
            return 0
        with db.read(unscoped="mail: emails set aside") as s:
            return s.scalar(
                select(func.count())
                .select_from(QueuedEmail)
                .where(QueuedEmail.refusedAt.is_not(None))
            )

    def expire(self) -> int:
        """Remove queued emails whose links have expired, and refused ones as old: their
        links work no more, so nothing in them is worth sending (S16.2)."""
        from sqlalchemy import delete

        from .store.entities.core import QueuedEmail

        db = self.db()
        if db is None:
            return 0
        with db.tx(unscoped="mail: expired emails") as s:
            return s.execute(
                delete(QueuedEmail).where(QueuedEmail.expiresAt <= clock.now())
            ).rowcount

    def adopt_outbox(self) -> int:
        """Emails an earlier release left in `outbox/`, in the clear, move into the queue and
        their files go; a refused one keeps only its recipient and subject (S16.2)."""
        from .store.entities.core import QueuedEmail

        folder = self.config.outbox_dir
        db = self.db()
        if db is None or not folder.is_dir():
            return 0
        moved = []
        with db.tx(unscoped="mail: the outbox adopted") as s:
            for path in sorted(folder.iterdir()):
                if path.suffix not in (".eml", ".refused"):
                    continue
                try:
                    msg = email.message_from_bytes(
                        path.read_bytes(), _class=EmailMessage, policy=email.policy.default
                    )
                    at = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC)
                except OSError:
                    continue
                refused = path.suffix == ".refused"
                s.add(
                    QueuedEmail(
                        id=ids.new_id("Email"),
                        recipient=str(msg["To"] or ""),
                        subject=str(msg["Subject"] or ""),
                        message=None if refused else msg.as_string(),
                        queuedAt=at,
                        expiresAt=_expires(msg, at),
                        refusedAt=at if refused else None,
                        error="the SMTP server refused the recipient" if refused else None,
                    )
                )
                moved.append(path)
        for path in moved:
            path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            folder.rmdir()
        return len(moved)

    def send_waiting(self, smtp: Smtp | None, guard, stop=None) -> int:
        """The mail task: send what the queue holds, oldest first. The first failure stops
        the run, which records it, and the rest wait for the next."""
        from .store.entities.core import QueuedEmail

        if smtp is None:
            return 0
        sent = 0
        for w in self.waiting():
            if stop is not None and stop.is_set():
                break
            try:
                deliver(smtp, w.message, guard)
            except smtplib.SMTPRecipientsRefused as e:
                # This address will never take it: set aside, without its message.
                with self.db().tx(unscoped="mail: a recipient refused") as s:
                    row = s.get(QueuedEmail, w.id)
                    row.message, row.refusedAt, row.error = None, clock.now(), describe(e)
                log.warning("the SMTP server refused an email's recipient; it was set aside")
                continue
            except Exception as e:
                raise RuntimeError(describe(e)) from None
            with self.db().tx(unscoped="mail: an email sent") as s:
                row = s.get(QueuedEmail, w.id)
                if row is not None:
                    s.delete(row)
            sent += 1
        if sent:
            log.info("sent %d email%s", sent, "" if sent == 1 else "s")
        return sent
