"""A driver's file posted for one account (requirements S18.8): the same import as an upload by
the owner, run as the connector waits. OFX, QFX and CSV go through the import; a statement
(a PDF, a photo) is kept on the account without reading (S1.3.3.6), named by its period where
the text layer gives one."""

import hashlib
import json
import math
from email.parser import BytesParser
from email.policy import HTTP

from fastapi import Request

from .. import activity, clock, parsing, receipts, settings
from ..errors import Problem
from ..importers import csvfile, ofx, statements
from ..importers.parsed import ReadError
from ..store.entities.accounts import Account, Import
from ..store.entities.connector import Connection
from ..store.repos import ledger as repo
from .manage import VIA


class Refused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Limit(Refused):
    def __init__(self, wait: float):
        super().__init__("limit", "The owner's upload limit for this hour is reached.")
        self.retry_after = str(max(1, math.ceil(wait)))


def parts(request: Request, body: bytes) -> tuple[bytes, dict]:
    """The `file` and `meta` parts of the multipart body, read whole (it was signed whole)."""
    ctype = request.headers.get("content-type", "")
    if not ctype.startswith("multipart/"):
        raise ValueError("A file post is multipart, with a file part and a meta part.")
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body
    )
    data, meta = None, None
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name == "file":
            data = part.get_payload(decode=True)
        elif name == "meta":
            try:
                meta = json.loads(part.get_payload(decode=True) or b"{}")
            except ValueError:
                raise ValueError("The meta part isn't JSON.") from None
    if not data or not isinstance(meta, dict):
        raise ValueError("A file post carries a file part and a meta part.")
    return data, meta


def post(srv, c: Connection, a: Account, data: bytes, meta: dict) -> dict:
    """Imported as the owner's own upload would be (S1.3), counted against their upload limit
    (S13.7.5.3); a repeated post adds nothing (idempotent by content)."""
    wait = srv.upload_rate.hit(c.ownerId)
    if wait:
        raise Limit(wait)
    with srv.db.read(unscoped="connector.files: post") as s:
        limit = settings.get(s, "importMaxMb") * 1024 * 1024
    if len(data) > limit:
        # Settings › Imports' size, the one statements are held to (S16.8, protocol §7).
        raise Refused("too-large", f"Files are up to {limit // (1024 * 1024)} MB.")
    name = str(meta.get("fileName") or "file")[:200]
    want = meta.get("sha256")
    if isinstance(want, str) and want != hashlib.sha256(data).hexdigest():
        raise Refused("file-refused", "The file's hash isn't the one its meta names.")
    media = receipts.sniff(data[:16])
    if media is not None:
        return _keep(srv, c, a, data, name, media)
    try:
        parsed = _read(srv, a, data)
    except ReadError as e:
        # A file the reader can't make out is refused, signed, with its words (S18.8).
        raise Refused("file-refused", str(e)) from None
    try:
        with srv.db.tx(unscoped="connector.files: post") as s:
            account = s.get(Account, a.id)
            applied = repo.apply_import(
                s, account, c.ownerId, parsed, name, hashlib.sha256(data).hexdigest()
            )
            _record(s, c, a, "import", {"added": applied.added, "matched": applied.matched})
    except (ReadError, Problem) as e:
        raise Refused("file-refused", str(e) if isinstance(e, ReadError) else e.detail) from None
    srv.events.publish("import", {"accountId": a.id}, users=[c.ownerId])
    return {
        "imported": {
            "added": applied.added,
            "matched": applied.matched,
            "changed": applied.changed,
        },
        "kept": False,
    }


def _read(srv, a: Account, data: bytes):
    """An OFX, QFX or CSV file read as the import reads an upload; anything else refused."""
    if ofx.looks_like_ofx(data):
        return parsing.read_ofx(data)
    if csvfile.looks_like_csv(data):
        with srv.db.read(unscoped="connector.files: read") as s:
            from sqlalchemy import false, select

            from ..store.entities.accounts import ImportMapping

            saved = s.scalars(
                select(ImportMapping).where(
                    ImportMapping.ownerId == a.ownerId,
                    ImportMapping.institution == (a.institution or ""),
                    ImportMapping.deleted == false(),
                )
            ).first()
        if saved is None:
            raise Refused(
                "mapping-missing",
                "The account has no saved CSV mapping: import one file by hand first.",
            )
        return parsing.read_csv(data, json.loads(saved.columns))
    raise Refused("file-refused", "Not a file MoolaKata imports (OFX, QFX, CSV, a statement).")


def _keep(srv, c: Connection, a: Account, data: bytes, name: str, media: str) -> dict:
    """A statement kept on the account as it is (S1.3.3.6): once per file, named by its period
    when a PDF's text layer gives one, and recorded as an import that adds nothing."""
    digest = hashlib.sha256(data).hexdigest()
    start = end = institution = None
    if media == "application/pdf":
        try:
            lines = parsing.text_layer(data)  # in the reader's worker (S9.8.4.2)
        except parsing.ReadError:  # a PDF that won't open is kept by its name alone
            lines = None
        if lines:
            start, end, institution = statements.period_and_institution(lines)
    with srv.db.tx(unscoped="connector.files: keep") as s:
        from sqlalchemy import false, select

        twice = s.scalars(
            select(Import).where(
                Import.accountId == a.id, Import.fileHash == digest, Import.deleted == false()
            )
        ).first()
        if twice is not None:
            return {"imported": None, "kept": True, "repeated": True}
        stored = receipts.store(s, srv, c.ownerId, name, data)
        r = stored.receipt
        r.date = end
        r.payee = statements.name(institution or a.institution, start, end)
        receipts.attach_account(s, c.ownerId, r, a.id)
        from .. import ids

        s.add(
            Import(
                id=ids.new_id("Imprt"),
                accountId=a.id,
                userId=c.ownerId,
                format="kept",
                fileName=name,
                fileHash=digest,
                coveredFrom=start,
                coveredTo=end,
            )
        )
        _record(s, c, a, "kept", {})
    srv.events.publish("import", {"accountId": a.id}, users=[c.ownerId])
    return {"imported": None, "kept": True, "repeated": False}


def _record(s, c: Connection, a: Account, what: str, detail: dict) -> None:
    """Activity: *by MoolaKata Connector, Alice's Schwab login* (S18.8)."""
    activity.record(
        s,
        f"import.{what}",
        actor=None,
        subject_kind="account",
        subject_id=a.id,
        owner=c.ownerId,
        via=f"{VIA}, {c.label}",
        detail={**detail, "connection": c.label, "at": clock.now().isoformat()},
    )
