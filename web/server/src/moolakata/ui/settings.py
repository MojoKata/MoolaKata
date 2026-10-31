"""Settings, for admins (requirements S16). Each section of the screen reads and writes its
own keys; secrets and the sources come with their sections' routes."""

import datetime as dt
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import false, select, text

from .. import activity, clock, settings, timezones
from ..errors import FieldError, Problem, refuse
from ..store.entities.core import Setting
from . import save
from .conventions import Deleted, ExactRoute, Model
from .deps import Caller, admin, server
from .imports import JobOut, accepted
from .welcome import Offered

log = logging.getLogger("moolakata.settings")
router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["settings"])


class SettingRef(Model):
    """A saved setting's record: its id and version (S13.8.6)."""

    id: str
    version: int


class SettingsView(Model):
    values: dict[str, Any]
    sections: dict[str, list[str]]
    serverZone: str
    # The saved ones' records, by key, the passwords' among them; a key with none stands at
    # its default, and a section's draft makes its record when it changes.
    records: dict[str, SettingRef]


def view(s) -> SettingsView:
    values = {k: settings.get(s, k) for k in settings.DEFINITIONS}
    sections: dict[str, list[str]] = {}
    for k, d in settings.DEFINITIONS.items():
        sections.setdefault(d.section, []).append(k)
    rows = s.scalars(select(Setting).where(Setting.deleted == false()))
    return SettingsView(
        values=values,
        sections=sections,
        serverZone=timezones.host_zone(),
        records={r.key: SettingRef(id=r.id, version=r.version) for r in rows},
    )


# Settings whose change redirects a secret or a link (S13.7.2); Network's are all of them too.
REAUTH = {"smtpHost", "publicUrl"}


def _secrets():
    from ..bitcoin.sync import PASSWORD
    from ..mail import SMTP_SECRET

    return {"smtpPassword": SMTP_SECRET, "bitcoinPassword": PASSWORD}


# The passwords a section saves with its keys: written, never read back (S14.4), each bound to
# the host its section names, which clears it when it changes (S16.2, S16.7).
SECRETS = {"smtpPassword": "smtpHost", "bitcoinPassword": "bitcoinNodeHost"}


@router.get("/settings", response_model=SettingsView)
def get_settings(request: Request, c: Caller = Depends(admin)):
    with server(request).db.read() as s:
        return view(s)


class SettingRecord(Model):
    """A setting as a section's draft saves it (S16): its key, and a value its definition
    checks; a password's value is written and never read back, null removing it."""

    key: str
    value: Any = None


class SettingOut(SettingRecord):
    id: str
    version: int


def _setting_admin(ctx) -> Caller:
    if not ctx.caller.admin:
        raise Problem(403, "admins-only", "Only admins can do this.")
    return ctx.caller


def _setting_create(ctx, record_id: str, body: SettingRecord) -> None:
    _setting_admin(ctx)
    if body.key not in settings.DEFINITIONS and body.key not in SECRETS:
        raise refuse("key", "setting-unknown", "Not a setting.")
    if settings.row_of(ctx.s, body.key) is not None:
        raise refuse("key", "setting-saved", "It is saved: change it.", 409)
    row = Setting(id=record_id, key=body.key, value="null", updatedById=ctx.caller.id)
    _setting_apply(ctx, row, body, new=True)
    ctx.s.add(row)


def _setting_editable(ctx, record_id: str) -> Setting:
    _setting_admin(ctx)
    row = ctx.s.get(Setting, record_id)
    if row is None or row.deleted:
        raise Problem(404, "not-found", "Not found")
    return row


def _setting_current(ctx, row: Setting) -> dict:
    return {"key": row.key, "value": None if row.key in SECRETS else json.loads(row.value)}


def _setting_update(ctx, row: Setting, body: SettingRecord) -> None:
    if body.key != row.key:
        raise refuse("key", "setting-fixed", "A setting keeps its key.")
    _setting_apply(ctx, row, body, new=False)


def _setting_apply(ctx, row: Setting, body: SettingRecord, new: bool) -> None:
    """The value checked and kept; what spans keys is checked once all are (`_settings_after`)."""
    s, c = ctx.s, ctx.caller
    srv = server(ctx.request)
    notes = ctx.notes.setdefault("settings", {"changed": [], "secrets": set(), "ids": {}})
    notes["ids"][body.key] = row.id
    if body.key in SECRETS:
        v = body.value
        if v is not None and (not isinstance(v, str) or not v or len(v) > 500):
            raise refuse("value", "password-invalid", "A password, or none.")
        from .deps import recent_auth

        recent_auth(c)  # a secret: the password again (S13.7.2)
        from ..store.repos import secrets as secret_repo

        where = _secrets()[body.key]
        if v:
            secret_repo.put(s, srv.keys.secrets, *where, v, c.id)
        else:
            secret_repo.remove(s, *where)
        row.updatedById = c.id
        row.updatedAt = clock.now()
        notes["secrets"].add(body.key)
        notes["changed"].append(body.key)
    else:
        value = settings.coerce(body.key, body.value)
        if body.key == "bitcoinSource" and value == "stub" and not srv.config.stubs:
            raise refuse("value", "source-unknown", "Only with dev mode's stubs (--stubs).")
        if body.key == "backupCopies":
            _fewer_copies(srv, settings.get(s, body.key), value)
        if value != settings.get(s, body.key) or new:
            if body.key in REAUTH or body.key.startswith("network"):
                # Who reaches the app, a link or the connector, and where a secret or a link
                # is sent: the password again (S13.7.2).
                from .deps import recent_auth

                recent_auth(c)
            row.value, row.updatedById = json.dumps(value, sort_keys=True), c.id
            notes["changed"].append(body.key)
    ctx.verify("settings", lambda: _settings_after(ctx))


def _settings_after(ctx) -> None:
    """Once every setting of the save is in: sign-up's needs, the passwords a new host clears,
    one Activity entry, and the hosts the server may reach (S13.5)."""
    s, c = ctx.s, ctx.caller
    srv = server(ctx.request)
    notes = ctx.notes["settings"]
    s.flush()
    # Sign-up sends links by email: it needs SMTP and the public URL (S10.1.4).
    missing = [k for k in ("smtpHost", "publicUrl") if not settings.get(s, k)]
    if settings.get(s, "signupEnabled") and missing and not srv.config.dev:
        # At the key this save changed: sign-up turned on, or what it needs taken away.
        key = next(k for k in ("signupEnabled", *missing) if k in notes["ids"])
        message = "Sign-up sends links by email: set up SMTP and the public URL first."
        error = FieldError(key, "signup-needs-email", message, notes["ids"][key])
        raise Problem(422, "signup-needs-email", message, [error])
    from ..store.repos import secrets as secret_repo

    cleared = []
    for secret, host in SECRETS.items():
        where = _secrets()[secret]
        moved = host in notes["changed"] and secret not in notes["secrets"]
        if moved and secret_repo.info(s, *where) is not None:
            secret_repo.remove(s, *where)
            cleared.append(secret)
    changed = notes["changed"]
    if changed:
        activity.record(s, "settings.changed", actor=c.id, for_admins=True,
                        detail={"fields": sorted(set(changed + cleared))})  # fmt: skip
    if any(k == "smtpHost" or k.startswith("bitcoin") for k in changed):
        from .prices import apply_egress

        ctx.after("egress", lambda: apply_egress(srv))


def _setting_delete(ctx, row: Setting) -> None:
    """Back to its default."""
    _setting_admin(ctx)
    row.mark_deleted(ctx.caller.id)


def _setting_read(ctx, record_id: str) -> SettingOut:
    row = ctx.s.get(Setting, record_id)
    return SettingOut(id=row.id, version=row.version, **_setting_current(ctx, row))


save.register(
    save.Kind(
        prefix="Setng",
        entity=Setting,
        fields=SettingRecord,
        create=_setting_create,
        editable=_setting_editable,
        current=_setting_current,
        update=_setting_update,
        delete=_setting_delete,
        read=_setting_read,
    )
)


# ---------- Email (S16.2) ----------


class SecretSet(Model):
    """A stored secret as the UI shows it: set, when and by whom."""

    setAt: dt.datetime
    setBy: str | None


class EmailView(Model):
    password: SecretSet | None
    waiting: int
    setAside: int
    lastRun: dt.datetime | None
    lastError: str | None


class TestEmail(Model):
    to: str


def _email_view(srv, s) -> EmailView:
    from ..mail import SMTP_SECRET
    from ..store.entities.core import TaskRun
    from ..store.entities.users import User
    from ..store.repos import secrets as secret_repo

    info = secret_repo.info(s, *SMTP_SECRET)
    by = s.get(User, info.setById) if info and info.setById else None
    run = s.get(TaskRun, "mail")
    return EmailView(
        password=SecretSet(setAt=info.setAt, setBy=by.displayName if by else None)
        if info
        else None,
        waiting=len(srv.services.mailer.waiting()),
        setAside=srv.services.mailer.set_aside(),
        lastRun=run.finishedAt if run else None,
        lastError=run.error if run else None,
    )


@router.get("/settings/email", response_model=EmailView)
def email_status(request: Request, c: Caller = Depends(admin)):
    srv = server(request)
    with srv.db.read() as s:
        return _email_view(srv, s)


class WrittenEmail(Model):
    name: str
    to: str
    subject: str
    writtenAt: dt.datetime


class WrittenEmailText(Model):
    name: str
    text: str


@router.get("/settings/email/written", response_model=list[WrittenEmail])
def written_emails(request: Request, c: Caller = Depends(admin)):
    """The emails written to the mail folder while SMTP was not set up (S16.2), newest
    first: who they are for and what they say, for an admin to pass a link on."""
    from ..mail import written

    return [
        WrittenEmail(name=w.name, to=w.to, subject=w.subject, writtenAt=w.at)
        for w in written(server(request).config)
    ]


@router.get("/settings/email/written/{name}", response_model=WrittenEmailText)
def written_email(name: str, request: Request, c: Caller = Depends(admin)):
    """One written email, links and all: the password again (S13.7.2), since a link in it is
    a token that signs someone in or resets a password."""
    from ..mail import read_written
    from .deps import recent_auth

    recent_auth(c)
    srv = server(request)
    text = read_written(srv.config, name)
    if text is None:
        raise Problem(404, "not-found", "No such email.")
    # Recorded for the person it is addressed to, as its owner (S10.2, S16.2).
    from ..auth.users import by_login

    head = dict(
        line.split(": ", 1) for line in text.split("\n\n", 1)[0].splitlines() if ": " in line
    )
    with srv.db.tx() as s:
        to = by_login(s, head.get("To", "").strip())
        activity.record(
            s,
            "email.opened",
            actor=c.id,
            owner=to.id if to else None,
            for_admins=True,
            detail={"subject": head.get("Subject", ""), "to": head.get("To", "")},
        )
    return WrittenEmailText(name=name, text=text)


# ---------- Bitcoin (S16.7, S1.6.2) ----------


class BitcoinView(Model):
    password: SecretSet | None  # Bitcoin Core's RPC password
    wallets: int
    lastRun: dt.datetime | None
    lastError: str | None
    certificate: str | None  # the Electrum server's, trusted (S1.6.2.4): its SHA-256
    certificateOffered: str | None  # another one it presented since, waiting to be confirmed


class BitcoinTest(Model):
    answer: str


def _bitcoin_view(s) -> BitcoinView:
    from sqlalchemy import false, func, select

    from ..bitcoin.sync import PASSWORD
    from ..store.entities.accounts import Account
    from ..store.entities.core import TaskRun
    from ..store.entities.users import User
    from ..store.repos import secrets as secret_repo

    info = secret_repo.info(s, *PASSWORD)
    by = s.get(User, info.setById) if info and info.setById else None
    run = s.get(TaskRun, "bitcoin")
    return BitcoinView(
        password=SecretSet(setAt=info.setAt, setBy=by.displayName if by else None)
        if info
        else None,
        wallets=s.scalar(
            select(func.count())
            .select_from(Account)
            .where(Account.type == "crypto-wallet", Account.deleted == false())
        ),
        lastRun=run.finishedAt if run else None,
        lastError=run.error if run else None,
        certificate=settings.get(s, "bitcoinNodeCert"),
        certificateOffered=settings.get(s, "bitcoinNodeCertOffered"),
    )


@router.get("/settings/bitcoin", response_model=BitcoinView)
def bitcoin_status(request: Request, c: Caller = Depends(admin)):
    with server(request).db.read() as s:
        return _bitcoin_view(s)


class TrustCertificate(Model):
    sha256: str


@router.post("/settings/bitcoin/certificate", response_model=BitcoinView)
def bitcoin_certificate(body: TrustCertificate, request: Request, c: Caller = Depends(admin)):
    """An admin confirms the Electrum server's certificate, as Test showed it: it is then the
    one trusted, and any other refused (S1.6.2.4)."""
    import re

    sha = body.sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        from ..errors import refuse

        raise refuse("sha256", "fingerprint-invalid", "The SHA-256 fingerprint Test showed.")
    with server(request).db.tx() as s:
        settings.put(s, "bitcoinNodeCert", sha, c.id)
        settings.put(s, "bitcoinNodeCertOffered", None, c.id)
        activity.record(
            s,
            "settings.changed",
            actor=c.id,
            for_admins=True,
            detail={"fields": ["bitcoinNodeCert"]},
        )
        s.flush()
        return _bitcoin_view(s)


@router.post("/settings/bitcoin/test", response_model=BitcoinTest)
def bitcoin_test(request: Request, c: Caller = Depends(admin)):
    """Ask the saved explorer or node for the chain's height, and say what failed."""
    from ..bitcoin import sync
    from ..bitcoin.sources import SourceError

    srv = server(request)
    with srv.db.read() as s:
        cfg = sync.config(s, srv.keys.secrets)
        src = sync.source(srv, s)
    hosts, named = cfg.hosts()
    if hosts and not srv.config.stubs:
        # The host is allowed for this test even before a wallet needs it.
        current_hosts, current_named = srv.guard.snapshot()
        srv.guard.allow(current_hosts | set(hosts), current_named | set(named))
    from .prices import apply_egress

    try:
        return BitcoinTest(answer=src.test())
    except SourceError as e:
        raise Problem(502, "source-failed", str(e)) from None
    finally:
        apply_egress(srv)


@router.post("/settings/email/test", response_model=TestEmail)
def email_test(request: Request, c: Caller = Depends(admin)):
    """Send a test email to the admin now, through the saved settings, and say what failed."""
    from ..mail import Email, deliver, describe, smtp_settings

    srv = server(request)
    if not c.user.email:
        raise Problem(409, "no-email", "Your profile has no email address to send to.")
    with srv.db.read() as s:
        smtp = smtp_settings(s, srv.keys.secrets)
        name = settings.get(s, "serverName")
    if smtp is None:
        raise Problem(
            422,
            "smtp-not-set",
            "Save the SMTP host first.",
            [FieldError("smtpHost", "smtp-not-set", "Save the SMTP host first.")],
        )
    from email.message import EmailMessage
    from email.utils import format_datetime, make_msgid

    note = Email(
        c.user.email,
        "MoolaKata test email",
        f"This is a test email from {name}. Email from MoolaKata reaches you.\n",
    )
    msg = EmailMessage()
    msg["From"] = smtp.sender
    msg["To"] = note.to
    msg["Subject"] = note.subject
    msg["Date"] = format_datetime(clock.now())
    msg["Message-ID"] = make_msgid(domain="moolakata.local")
    msg.set_content(note.body)
    try:
        deliver(smtp, msg, srv.guard)
    except Exception as e:
        raise Problem(502, "smtp-failed", f"The test email was not sent: {describe(e)}.") from None
    return TestEmail(to=c.user.email)


# ---------- Receipts (S16.10, S9.8.7) ----------


class ReadingQueue(Model):
    waiting: int
    reading: int
    failed: int
    read: int
    lastRun: dt.datetime | None
    # Whether the reader's worker is kept out of the data directory on this host: False on a
    # kernel without Landlock (S9.8.4.2, S16.10); None until it is known.
    fileSandbox: bool | None = None


def _queue(s, srv) -> ReadingQueue:
    counts = dict(
        s.execute(
            text(
                'SELECT "readStatus", count(*) FROM "Receipt" WHERE NOT deleted '
                'GROUP BY "readStatus"'
            )
        ).all()
    )
    last = s.execute(text('SELECT max("readAt") FROM "Receipt"')).scalar()
    return ReadingQueue(
        waiting=counts.get("waiting", 0),
        reading=counts.get("reading", 0),
        failed=counts.get("failed", 0),
        read=counts.get("read", 0),
        lastRun=dt.datetime.fromisoformat(last).replace(tzinfo=dt.UTC)
        if isinstance(last, str)
        else last,
    )


@router.get("/settings/receipts", response_model=ReadingQueue)
def receipts_queue(request: Request, c: Caller = Depends(admin)):
    from .. import parsing

    srv = server(request)
    sandboxed = parsing.file_sandbox(start=True)
    with srv.db.read() as s:
        out = _queue(s, srv)
    out.fileSandbox = sandboxed
    return out


@router.post("/settings/receipts/reread", response_model=ReadingQueue)
def reread_all(request: Request, c: Caller = Depends(admin)):
    """After a model update: every receipt read again; only empty or suggested fields are
    replaced (S9.8.6)."""
    from ..store.entities.receipts import Receipt

    srv = server(request)
    with srv.db.tx() as s:
        if not settings.get(s, "readReceipts"):
            raise Problem(409, "reading-off", "Turn on Read receipts first.")
        ids = []
        for r in s.query(Receipt).filter(
            Receipt.deleted.is_(False), Receipt.filePrunedAt.is_(None)
        ):
            r.readStatus, r.readError = "waiting", None
            ids.append(r.id)
        activity.record(s, "receipts.reread", actor=c.id, for_admins=True)
        s.flush()
        out = _queue(s, srv)
    if srv.reader is not None:
        for rid in ids:
            srv.reader.queue(rid)
    return out


# ---------- Key storage (S16.13, S15) ----------


class PreviousKeyOut(Model):
    fingerprint: str
    removableAfter: dt.date | None  # when the backup directory's own copies no longer need it


class Confirmation(Model):
    at: dt.datetime
    fingerprint: str
    matched: bool
    how: str = "verify"  # verify (`keys verify` on the host), app (Verify key) or unlock (S15.6.5)


class RestoreReport(Model):
    at: dt.datetime | None
    source: str | None
    receiptsSetAside: list[str]
    receiptsUnopened: list[str]
    secretsUnopened: list[str]


class ReencryptScheduled(Model):
    at: dt.datetime
    why: str  # settings, rotation, host
    copies: dict[str, str]
    started: bool  # under way


class ReencryptReport(Model):
    finishedAt: dt.datetime
    why: str | None
    receiptsSetAside: list[str]
    secretsSetAside: list[str]
    copies: dict[str, str]
    # A rotation whose keyring stayed under this old key: it re-encrypted, but didn't rotate.
    rotationUnfinished: str | None = None


class KeyStorage(Model):
    fingerprint: str
    created: dt.datetime
    ageDays: int
    reminderMonths: int
    reminderDue: bool
    dataKeyCreated: dt.datetime
    previous: list[PreviousKeyOut]
    confirmations: list[Confirmation]
    databaseBytes: int
    secrets: int
    receipts: int
    # A re-encryption scheduled for the next restart (S15.7.2): when, why, and its copies'
    # choices; and what the last one set aside.
    scheduled: ReencryptScheduled | None = None
    lastReencryption: ReencryptReport | None = None
    # What the first unlock after a restore couldn't open (S15.6.8).
    lastRestore: RestoreReport | None = None


class CheckOut(Model):
    name: str
    ok: bool
    detail: str


class KeyTest(Model):
    ok: bool
    checks: list[CheckOut]


def _database_bytes(s) -> int:
    """The database's size as SQLite counts it, reading through the write-ahead log, where a
    new server's data sits until a checkpoint: the file alone can say 0.0 MB. On a keyed
    connection SQLCipher answers `page_size` itself, as text, hence the casts."""
    pages = int(s.execute(text("PRAGMA page_count")).scalar_one())
    return pages * int(s.execute(text("PRAGMA page_size")).scalar_one())


@router.get("/settings/keys", response_model=KeyStorage)
def key_storage(request: Request, c: Caller = Depends(admin)):
    """Key storage (S16.13): the master key's state, its previous keys, and the last
    re-encryption; the copies come from their own route."""
    from sqlalchemy import func

    from ..keys import master
    from ..store.entities.core import Activity, Secret

    srv = server(request)
    ring = srv.store.keys.ring
    now = clock.now()
    with srv.db.read() as s:
        keep_days = settings.get(s, "backupCopies")
        months = settings.get(s, "keyReminderMonths")
        database_bytes = _database_bytes(s)
        confirmations = [
            Confirmation(
                at=a.at,
                fingerprint=json.loads(a.detail).get("fingerprint", ""),
                matched=a.kind in ("key.verified", "key.checked", "key.unlocked"),
                how="unlock"
                if a.kind == "key.unlocked"
                else "app"
                if a.kind.startswith("key.check")
                else "verify",
            )
            for a in s.scalars(
                select(Activity)
                # An unlock counts as a confirmation, as Verify key and `keys verify` do (S15.6.5).
                .where(
                    Activity.kind.in_(
                        (
                            "key.verified",
                            "key.checked",
                            "key.unlocked",
                            "key.verify-failed",
                            "key.check-failed",
                        )
                    )
                )
                .order_by(Activity.at.desc())
                .limit(10)
            )
        ]
        secrets = s.scalar(select(func.count()).select_from(Secret))
    age = (now - ring.master_created).days
    receipts_dir = srv.config.receipts_dir
    return KeyStorage(
        fingerprint=master.fingerprint(srv.store.keys.master_id),
        created=ring.master_created,
        ageDays=age,
        reminderMonths=months,
        reminderDue=bool(months) and age > months * 30.4,
        dataKeyCreated=ring.data_key_created,
        previous=[
            PreviousKeyOut(
                fingerprint=master.fingerprint(p.master_id),
                removableAfter=(p.rotated + dt.timedelta(days=keep_days)).date(),
            )
            for p in ring.previous
        ],
        confirmations=confirmations,
        databaseBytes=database_bytes,
        secrets=secrets,
        receipts=sum(1 for _ in receipts_dir.rglob("*") if _.is_file())
        if receipts_dir.is_dir()
        else 0,
        scheduled=_scheduled(srv.config),
        lastReencryption=_last(srv.config),
        lastRestore=_restored(srv.config),
    )


def _restored(config) -> RestoreReport | None:
    from ..store import maintenance

    r = maintenance.restore_report(config)
    if not r:
        return None
    at = r.get("at")
    return RestoreReport(
        at=dt.datetime.fromisoformat(at) if at else None,
        source=r.get("source"),
        receiptsSetAside=r.get("receiptsSetAside") or [],
        receiptsUnopened=r.get("receiptsUnopened") or [],
        secretsUnopened=r.get("secretsUnopened") or [],
    )


def _scheduled(config) -> ReencryptScheduled | None:
    from ..store import reencrypt

    j = reencrypt.journal(config)
    if j is None:
        return None
    return ReencryptScheduled(
        at=dt.datetime.fromisoformat(j["scheduledAt"]),
        why=str(j.get("why") or "settings"),
        copies=j.get("copies") or {},
        started=bool(j.get("steps")),
    )


def _last(config) -> ReencryptReport | None:
    from ..store import reencrypt

    r = reencrypt.report(config)
    if not r:
        return None
    return ReencryptReport(
        finishedAt=dt.datetime.fromisoformat(r["finishedAt"]),
        why=r.get("why"),
        receiptsSetAside=r.get("receiptsSetAside") or [],
        secretsSetAside=r.get("secretsSetAside") or [],
        copies=r.get("copies") or {},
        rotationUnfinished=r.get("rotationUnfinished"),
    )


class Verified(Model):
    fingerprint: str
    at: dt.datetime


@router.post("/settings/keys/verify", response_model=Verified)
async def verify_key(body: PhraseIn, request: Request, c: Caller = Depends(admin)):
    """Verify key (S15.6.5): the 12 words of a copy of the phrase, checked against the keyring
    without changing anything, and recorded as a confirmation. A wrong phrase counts toward
    the lockout, as at the unlock (S15.4.2)."""
    import asyncio

    from ..keys import master, phrase
    from .unlock import LOGIN

    srv = server(request)
    address = request.client.host if request.client else "-"
    guard = srv.sign_in
    wait = guard.locked(address)
    if wait:
        raise Problem(
            429,
            "locked-out",
            "Too many wrong phrases: try again later.",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    delay = guard.delay(LOGIN, address)
    if delay:
        await asyncio.sleep(delay)
    try:
        key = phrase.from_words(body.phrase)
    except phrase.PhraseError as e:
        guard.failed(LOGIN, address)
        raise Problem(422, "phrase-invalid", f"Not a recovery phrase: {e}") from None
    ring = master.read_keyring(srv.config.keyring_path)
    try:
        master.unwrap(key, ring)
    except ValueError:  # a valid phrase, but not the key that wrapped this keyring
        guard.failed(LOGIN, address)
        with srv.db.tx() as s:
            activity.record(
                s,
                "key.check-failed",
                actor=c.id,
                for_admins=True,
                detail={"fingerprint": master.fingerprint(key)},
            )
        raise Problem(403, "phrase-wrong", "Those words are not this server's key.") from None
    fingerprint = master.fingerprint(key)
    with srv.db.tx() as s:
        entry = activity.record(
            s, "key.checked", actor=c.id, for_admins=True, detail={"fingerprint": fingerprint}
        )
        at = entry.at
    srv.tasks.run_now("alerts")
    return Verified(fingerprint=fingerprint, at=at)


@router.post("/settings/keys/test", response_model=KeyTest)
def key_test(request: Request, c: Caller = Depends(admin)):
    """Test: the keyring on disk is the one the phrase unlocked, and the database and a
    secret open with the data key it holds."""
    from ..config import RefuseStart
    from ..keys import master
    from ..keys import secrets as sealing
    from ..store.db import WrongKey, connect
    from ..store.entities.core import Secret

    srv = server(request)
    cfg = srv.config
    checks = []
    try:
        ring = master.read_keyring(cfg.keyring_path)
        if ring.master_id != srv.store.keys.master_id:
            raise ValueError(
                f"the keyring on disk is wrapped under {master.fingerprint(ring.master_id)}, "
                f"the server was unlocked with {master.fingerprint(srv.store.keys.master_id)}"
            )
        checks.append(
            CheckOut(
                name="Keyring",
                ok=True,
                detail=f"present, wrapped under {master.fingerprint(ring.master_id)}",
            )
        )
        conn = connect(cfg.db_path, srv.store.keys.keys.sqlcipher_key)
        conn.close()
        checks.append(CheckOut(name="Database", ok=True, detail="opens with the data key"))
    except (RefuseStart, ValueError, WrongKey) as e:
        checks.append(CheckOut(name="Key storage", ok=False, detail=str(e)))
    with srv.db.read() as s:
        row = s.scalars(select(Secret)).first()
        if row is not None:
            try:
                sealing.open_sealed(
                    srv.keys.secrets,
                    sealing.Sealed(row.ciphertext, row.nonce, row.wrappedKey),
                    row.recordType,
                    row.recordId,
                    row.field,
                )
                checks.append(CheckOut(name="Secrets", ok=True, detail="a secret opens"))
            except sealing.SecretError:
                checks.append(CheckOut(name="Secrets", ok=False, detail="a secret does not open"))
    with srv.db.tx() as s:
        activity.record(s, "keys.tested", actor=c.id, for_admins=True)
    return KeyTest(ok=all(x.ok for x in checks), checks=checks)


class ReencryptIn(Model):
    copies: dict[str, str] = Field(default_factory=dict)  # name: reencrypt, delete or leave


class Restarting(Model):
    """A re-encryption or a rotation scheduled, and the server restarting for it (S15.7.2):
    the browser waits for the locked screen, where the phrase starts it."""

    restarting: bool
    why: str  # settings, rotation
    fingerprint: str  # the phrase that unlocks after the restart
    copies: dict[str, str] = Field(default_factory=dict)  # what each copy will meet


def _copies_choices(srv, chosen: dict[str, str]) -> dict[str, str]:
    """Each copy's choice, re-encrypt by default (S15.7.2); a choice for no copy refused."""
    from ..store import copies, reencrypt

    if any(v not in reencrypt.CHOICES for v in chosen.values()):
        raise refuse("copies", "choice-invalid", "Each copy: reencrypt, delete or leave.")
    return {c.name: chosen.get(c.name, "reencrypt") for c in copies.copies(srv.config)}


@router.post("/settings/keys/reencrypt", response_model=Restarting)
def key_reencrypt(body: ReencryptIn, request: Request, c: Caller = Depends(admin)):
    """Re-encrypt now (S15.7.2): scheduled with each copy's choice, and the server restarts at
    once; the unlock that follows runs it before the server serves, with the phrase given
    there. It never runs while the server serves, and once scheduled it is not withdrawn
    (CR3-61). The password again (S13.7.2)."""
    from .. import runtime
    from ..config import RefuseStart
    from ..keys import master
    from ..store import reencrypt
    from .deps import recent_auth

    recent_auth(c)
    srv = server(request)
    choices = _copies_choices(srv, dict(body.copies))
    with srv.maintenance_lock:
        try:
            reencrypt.schedule(srv.config, choices, c.id, "settings")
        except RefuseStart as e:
            raise Problem(409, "reencrypt-pending", str(e)) from None
    with srv.db.tx() as s:
        activity.record(
            s, "keys.reencrypt-scheduled", actor=c.id, for_admins=True, detail={"copies": choices}
        )
    runtime.restart(srv)
    return Restarting(
        restarting=True,
        why="settings",
        fingerprint=master.fingerprint(srv.store.keys.master_id),
        copies=choices,
    )


@router.post("/settings/keys/rotate/phrase", response_model=Offered)
def rotation_phrase(request: Request, c: Caller = Depends(admin)):
    """A rotation's new phrase (S15.7.1), made and held in memory only, as the welcome's are
    (an hour each, 20 at most), until three of its words are typed back with the rotation."""
    from ..keys import master, phrase

    srv = server(request)
    token, made = srv.rotations.offer()
    return Offered(
        token=token,
        words=phrase.to_words(made.key),
        fingerprint=master.fingerprint(made.key),
        serverName=srv.config.name,
        made=dt.date.today(),
        check=[i + 1 for i in made.picks],
    )


class RotateIn(Model):
    token: str  # the new phrase on offer
    words: dict[str, str] = Field(default_factory=dict)  # word number: the word typed back
    phrase: str | None = None  # the current phrase
    code: str | None = None  # or a break-glass code from the host, for a lost phrase (S15.5.2)
    copies: dict[str, str] = Field(default_factory=dict)  # name: reencrypt, delete or leave


@router.post("/settings/keys/rotate", response_model=Restarting)
def rotate(body: RotateIn, request: Request, c: Caller = Depends(admin)):
    """Rotate (S15.7.1): a new master key and phrase, and with them a new data key. The
    password again and the current phrase, or a break-glass code from the host, so an
    admin's session alone can't change the phrase the household holds; a wrong one counts
    toward the sign-in's lockout. Three of the new phrase's words typed back; then the
    keyring is wrapped under it and the server restarts, and the unlock with the new phrase
    re-encrypts (S15.7.2)."""
    from .. import runtime
    from ..config import RefuseStart
    from ..keys import master, phrase
    from ..store import maintenance
    from ..store.entities.users import User
    from .deps import recent_auth
    from .session import count_failure, guarded
    from .welcome import words_wrong

    recent_auth(c)
    srv = server(request)
    made = srv.rotations.get(body.token)
    if made is None:
        raise Problem(410, "phrase-gone", "That phrase isn't on offer now: show a new one.")
    words_wrong(made, body.words)
    choices = _copies_choices(srv, dict(body.copies))
    address = guarded(request, c.user.username)
    if body.code:
        how, right = "break-glass", srv.break_glass.use(body.code)
    else:
        try:
            given = phrase.from_words(body.phrase or "")
            right = master.key_id(given) == srv.store.keys.master_id
        except phrase.PhraseError:
            right = False
        how = "phrase"
    if not right:
        with srv.db.tx() as s:
            count_failure(s, srv.sign_in, c.user.username, address, s.get(User, c.id))
        if how == "break-glass":
            raise refuse(
                "code", "code-wrong", "That code isn't the one issued, or it expired.", 403
            )
        raise refuse("phrase", "phrase-wrong", "That isn't this server's recovery phrase.", 403)
    old_fp = master.fingerprint(srv.store.keys.master_id)
    with srv.maintenance_lock:
        try:
            srv.store, outcomes = maintenance.rotate_running(
                srv.config, srv.store, made.key, choices, c.id
            )
        except RefuseStart as e:
            raise Problem(409, "reencrypt-pending", str(e)) from None
    srv.rotations.clear()
    new_fp = master.fingerprint(made.key)
    with srv.db.tx() as s:
        activity.record(
            s,
            "key.rotated",
            actor=c.id,
            for_admins=True,
            detail={"from": old_fp, "to": new_fp, "how": how, "copies": outcomes},
        )
    log.info("the master key was rotated in Settings: %s -> %s (%s)", old_fp, new_fp, how)
    if srv.config.dev:
        from ..dev import devmode

        devmode.remember_phrase(srv.config, made.key)
    runtime.restart(srv)
    return Restarting(restarting=True, why="rotation", fingerprint=new_fp, copies=outcomes)


# ---------- The copies on this host (S15.7, S16.13) ----------


class CopyOut(Model):
    name: str
    kind: str  # backup, pre-upgrade, before-restore
    what: str
    made: dt.datetime
    bytes: int
    masterKey: str | None  # the fingerprint its keyring is wrapped under
    opens: str  # current, phrase, previous, unknown (store/copies.py)


class CopiesOut(Model):
    copies: list[CopyOut]
    note: str


COPIES_NOTE = (
    "The host's own snapshots and backups are copies too, outside this list: they open with "
    "the phrase of their day for as long as the host keeps them."
)


def copies_out(srv) -> CopiesOut:
    from ..keys import master
    from ..store import copies

    return CopiesOut(
        copies=[
            CopyOut(
                name=c.name,
                kind=c.kind,
                what=c.what,
                made=c.made,
                bytes=c.bytes,
                masterKey=master.fingerprint(c.ring.master_id) if c.ring else None,
                opens=copies.opens_with(c, srv.store.keys),
            )
            for c in copies.copies(srv.config)
        ],
        note=COPIES_NOTE,
    )


@router.get("/settings/keys/copies", response_model=CopiesOut)
def key_copies(request: Request, c: Caller = Depends(admin)):
    """Every copy on this host, with how it opens; snapshots and the host's backups are not
    here (S15.7)."""
    return copies_out(server(request))


class PhraseIn(Model):
    phrase: str


@router.delete("/settings/keys/copies/{name}", response_model=Deleted)
def remove_copy(name: str, body: PhraseIn, request: Request, c: Caller = Depends(admin)):
    """Remove one copy (S15.8 step 4): the password again and the recovery phrase, so an
    admin's session alone deletes no backup (S13.7.2, S16.13). A wrong phrase counts toward
    the sign-in's lockout."""
    from ..keys import master, phrase
    from ..store import copies
    from ..store.entities.users import User
    from .deps import recent_auth
    from .session import count_failure, guarded

    recent_auth(c)
    srv = server(request)
    address = guarded(request, c.user.username)
    try:
        right = master.key_id(phrase.from_words(body.phrase)) == srv.store.keys.master_id
    except phrase.PhraseError:
        right = False
    if not right:
        with srv.db.tx() as s:
            count_failure(s, srv.sign_in, c.user.username, address, s.get(User, c.id))
        raise refuse("phrase", "phrase-wrong", "That isn't this server's recovery phrase.", 403)
    found = copies.find(srv.config, name)
    if found is None:
        raise Problem(404, "not-found", "No such copy.")
    copies.remove(found)
    with srv.db.tx() as s:
        activity.record(s, "keys.copy-removed", actor=c.id, for_admins=True, detail={"name": name})
    return Deleted(deleted={"id": name, "deletedAt": clock.now(), "version": 0}, parent=None)


@router.delete("/settings/keys/previous/{fingerprint}", response_model=Deleted)
def forget_previous_key(fingerprint: str, request: Request, c: Caller = Depends(admin)):
    """Drop a previous master key from the keyring's list once nothing needs it (S15.7.1)."""
    from ..keys import master
    from ..store import copies
    from .deps import recent_auth

    recent_auth(c)
    srv = server(request)
    # The keyring is written under the maintenance lock, never beside a rotation (K5).
    with srv.maintenance_lock:
        if not copies.forget_previous(srv.config, fingerprint):
            raise Problem(404, "not-found", "No such previous key.")
    k = srv.store.keys
    srv.store.keys = master.Unlocked(
        k.master_id, master.read_keyring(srv.config.keyring_path), k.keys, k.data_key
    )
    with srv.db.tx() as s:
        activity.record(
            s, "keys.previous-forgotten", actor=c.id, for_admins=True, detail={"key": fingerprint}
        )
    return Deleted(deleted={"id": fingerprint, "deletedAt": clock.now(), "version": 0}, parent=None)


# ---------- Backups (S16.12, S14.6) ----------


class BackupOut(Model):
    name: str
    made: dt.datetime
    bytes: int
    files: int
    masterKey: str


class Backups(Model):
    directory: str
    time: str
    copies: int
    backups: list[BackupOut]
    lastRun: dt.datetime | None
    lastError: str | None
    nextRun: dt.datetime | None
    running: bool


@router.get("/settings/backups", response_model=Backups)
def backups(request: Request, c: Caller = Depends(admin)):
    from ..store import maintenance

    srv = server(request)
    out = []
    for path in reversed(maintenance.backups(srv.config)):
        try:
            meta = json.loads((path / "manifest.json").read_text())
        except OSError, ValueError:
            continue
        out.append(
            BackupOut(
                name=path.name,
                made=dt.datetime.fromisoformat(meta["made"]),
                bytes=sum(f["bytes"] for f in meta["files"].values()),
                files=len(meta["files"]),
                masterKey=meta.get("masterKey", ""),
            )
        )
    status = srv.tasks.status().get("backups", {})
    with srv.db.read() as s:
        return Backups(
            directory=str(srv.config.backup_dir),
            time=settings.get(s, "backupTime"),
            copies=settings.get(s, "backupCopies"),
            backups=out,
            lastRun=status.get("lastRun"),
            lastError=status.get("lastError"),
            nextRun=status.get("nextRun"),
            running=status.get("running", False),
        )


def _fewer_copies(srv, was: int, value: int) -> None:
    """Fewer days of backups than are kept now deletes some at the next backup: that takes
    the recovery phrase, as Remove does, so an admin's session alone deletes no backup
    (CR3-63)."""
    from ..store import maintenance

    if value < was and value < maintenance.backup_days(srv.config):
        raise refuse(
            "value",
            "phrase-needed",
            "Fewer days than the backups kept deletes some: that takes the recovery phrase.",
            403,
        )


class CopiesIn(Model):
    copies: int
    phrase: str | None = None  # needed when it is fewer days than the backups kept


@router.post("/settings/backups/copies", response_model=Backups)
def backup_copies(body: CopiesIn, request: Request, c: Caller = Depends(admin)):
    """*Copies kept* (S16.12): the days of backups kept. Fewer than the backups there are
    deletes some at the next backup, so that takes the password again and the recovery
    phrase, as Remove does (S16.13); a wrong phrase counts toward the sign-in's lockout."""
    from ..keys import master, phrase
    from ..store import maintenance
    from ..store.entities.users import User
    from .deps import recent_auth
    from .session import count_failure, guarded

    srv = server(request)
    try:
        value = settings.coerce("backupCopies", body.copies)
    except Problem:
        raise refuse("copies", "value-invalid", "Between 3 and 365.") from None
    with srv.db.read() as s:
        was = settings.get(s, "backupCopies")
    if value < was and value < maintenance.backup_days(srv.config):
        recent_auth(c)
        if not body.phrase:
            raise refuse("phrase", "phrase-needed", "Fewer days than the backups kept: the phrase.")
        address = guarded(request, c.user.username)
        try:
            right = master.key_id(phrase.from_words(body.phrase)) == srv.store.keys.master_id
        except phrase.PhraseError:
            right = False
        if not right:
            with srv.db.tx() as s:
                count_failure(s, srv.sign_in, c.user.username, address, s.get(User, c.id))
            raise refuse("phrase", "phrase-wrong", "That isn't this server's recovery phrase.", 403)
    with srv.db.tx() as s:
        settings.put(s, "backupCopies", value, c.id)
        activity.record(
            s,
            "settings.changed",
            actor=c.id,
            for_admins=True,
            detail={"fields": ["backupCopies"], "from": was, "to": value},
        )
    return backups(request, c)


@router.post("/settings/backups/run", response_model=JobOut, status_code=202)
def backup_now(request: Request, c: Caller = Depends(admin)):
    """Back up now: the daily task, at once, followed as a job (S13.8.7)."""
    srv = server(request)
    job = srv.jobs.create("backup", c.id)
    if not srv.tasks.run_now("backups", srv.jobs.follow(job)):
        raise Problem(503, "not-available", "Backups can't run right now.")
    with srv.db.tx() as s:
        activity.record(s, "backups.started", actor=c.id, for_admins=True)
    return accepted(job)


# ---- Storage and file pruning (S16.17, S14.10) ----


class Size(Model):
    files: int
    bytes: int


class CategorySize(Size):
    category: str


class YearSizes(Model):
    year: int
    categories: list[CategorySize]


class StorageOut(Model):
    databaseBytes: int
    receiptsBytes: int
    expired: Size
    later: Size  # expiring later, or kept while what they belong to is open
    forever: Size
    pruned: int  # files pruned before
    byYear: list[YearSizes]  # what expires each coming year, by category
    expiredBy: list[CategorySize]  # what can be pruned now, by category
    keepStatementsYears: int | None
    orphans: Size  # files no record names (S14.6)


def _size(g) -> Size:
    return Size(files=g.files, bytes=g.bytes)


@router.get("/settings/storage", response_model=StorageOut)
def storage(request: Request, c: Caller = Depends(admin)):
    """Sizes and counts only, never what the files hold (S14.10.4)."""
    from ..receipts import retention

    srv = server(request)
    with srv.db.read() as s:
        st = retention.storage(s, srv.config.receipts_dir)
        return StorageOut(
            databaseBytes=_database_bytes(s),
            receiptsBytes=st.receiptsBytes,
            expired=_size(st.expired),
            later=_size(st.later),
            forever=_size(st.forever),
            pruned=st.pruned,
            byYear=[
                YearSizes(
                    year=y,
                    categories=[
                        CategorySize(category=k, files=g.files, bytes=g.bytes)
                        for k, g in sorted(cats.items())
                    ],
                )
                for y, cats in st.byYear.items()
            ],
            expiredBy=[
                CategorySize(category=k, files=g.files, bytes=g.bytes)
                for k, g in sorted(st.expiredBy.items())
            ],
            keepStatementsYears=settings.get(s, "keepStatementsYears"),
            orphans=_size(st.orphans),
        )


class PruneIn(Model):
    categories: list[str]  # those ticked in the preview
    count: int  # typed by the admin, to confirm


class PruneOut(Model):
    files: int
    bytes: int


@router.post("/settings/storage/prune", response_model=PruneOut)
def prune_files(body: PruneIn, request: Request, c: Caller = Depends(admin)):
    """Remove the expired files of the categories ticked, keeping every record; recorded in
    Activity with its counts (S14.10.5). No backup first: a backup holds no files, the host's
    own backups do."""
    from ..receipts import retention
    from .deps import recent_auth

    recent_auth(c)
    srv = server(request)
    with srv.db.read() as s:
        rows = retention.prunable(s, body.categories)
    if not rows:
        raise refuse("categories", "nothing-to-prune", "No expired files in what is ticked.")
    if body.count != len(rows):
        raise refuse("count", "count-mismatch", f"Type {len(rows):,} to prune them.")
    with srv.db.tx() as s:
        rows = retention.prunable(s, body.categories)
        freed = retention.prune_files(srv, s, rows, c.id)
        activity.record(
            s,
            "files.pruned",
            actor=c.id,
            for_admins=True,
            detail={"files": len(rows), "bytes": freed, "categories": body.categories},
        )
    return PruneOut(files=len(rows), bytes=freed)


@router.post("/settings/storage/orphans/remove", response_model=PruneOut)
def remove_orphans(request: Request, c: Caller = Depends(admin)):
    """Remove the files no record names, left behind by a restore of an older database under
    files written later (S14.6, S16.17). The password again (S13.7.2)."""
    from ..receipts import retention
    from .deps import recent_auth

    recent_auth(c)
    srv = server(request)
    with srv.db.tx() as s:
        n, freed = retention.remove_orphans(srv, s)
        activity.record(
            s,
            "files.orphans-removed",
            actor=c.id,
            for_admins=True,
            detail={"files": n, "bytes": freed},
        )
    return PruneOut(files=n, bytes=freed)
