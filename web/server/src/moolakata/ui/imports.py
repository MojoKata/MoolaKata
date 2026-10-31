"""Importing files into an account (requirements S1.3.1–S1.3.3): OFX/QFX, CSV with a column
mapping saved per institution, and statements (a PDF or a photo of one) read on the server and
checked before anything is saved. An import is long work: it answers 202 with a job, and the
live stream announces its end (S13.8.7)."""

import datetime as dt
import hashlib
import json
import re
import secrets
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import Field, StringConstraints
from sqlalchemy import false, select

from .. import access, clock, exactjson, ids, parsing, receipts, settings
from ..errors import Problem, refuse
from ..importers import brokerage, csvfile, ofx, statements
from ..importers.parsed import ParsedFile, ReadError, Row, Security
from ..jobs import Job
from ..ledger import holdingcheck, lots
from ..ledger import types as atypes
from ..store.entities.accounts import (
    Account,
    HoldingCheck,
    Import,
    ImportMapping,
    Instrument,
    Lot,
    StatementLayout,
    Transaction,
)
from ..store.entities.users import User
from ..store.repos import ledger as repo
from .conventions import Deleted, ExactRoute, Gone, Loose, Model, Money, Quantity, Ratio
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["imports"])
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mk-import")
HELD_MINUTES = 30


@dataclass
class Held:
    """An uploaded CSV waiting for its mapping to be checked (never written to disk)."""

    data: bytes
    accountId: str
    userId: str
    fileName: str
    until: dt.datetime
    # A statement: what was read and parsed, for saving and for learning its layout.
    lines: list | None = None
    statement: object | None = None
    method: str | None = None
    # A statement of several accounts (S1.3.3.5): each part's parse, and what the person
    # decided for each, saved together once every part is decided.
    parts: list | None = None
    decisions: dict | None = None


_held: dict[str, Held] = {}
_held_lock = threading.Lock()


class JobOut(Model):
    id: str
    kind: str
    state: str
    progress: Ratio
    result: dict | None
    error: dict | None


class ImportRow(Model):
    id: str
    format: str
    fileName: str
    coveredFrom: dt.date | None
    coveredTo: dt.date | None
    added: int
    matched: int
    changed: int
    userName: str
    createdAt: dt.datetime


class MappingIn(Model):
    mapping: Loose
    save: bool = True


def job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        state=job.state,
        progress=job.progress,
        # Every amount, quantity and price in a result is written as an exact number (R1.9).
        result=exactjson.marked(job.result),
        error=job.error,
    )


def accepted(job: Job) -> JSONResponse:
    """202 with the job (S13.8.7), and where to follow it."""
    return JSONResponse(
        job_out(job).model_dump(mode="json"),
        status_code=202,
        headers={"Location": f"/ui/api/jobs/{job.id}"},
    )


def _hold(data: bytes, account_id: str, user_id: str, name: str, **extra) -> str:
    """Kept in memory while it waits for its mapping or its check. What a user's held uploads
    hold counts against their uploads in flight (S13.7.6): past it, their oldest held one is
    let go, and its dialog asks for the file again (CR3-172)."""
    from ..middleware import IN_FLIGHT

    key = "Upl_" + secrets.token_urlsafe(18)
    now = clock.now()
    with _held_lock:
        for k in [k for k, h in _held.items() if h.until < now]:
            del _held[k]
        mine = sorted((h.until, k) for k, h in _held.items() if h.userId == user_id)
        total = sum(len(_held[k].data) for _, k in mine) + len(data)
        for _, k in mine:
            if total <= IN_FLIGHT:
                break
            total -= len(_held.pop(k).data)
        _held[key] = Held(
            data, account_id, user_id, name, now + dt.timedelta(minutes=HELD_MINUTES), **extra
        )
    return key


def _run(
    srv,
    job: Job,
    account_id: str,
    user_id: str,
    data: bytes,
    name: str,
    mapping: dict | None,
    save_mapping: bool,
) -> None:
    srv.jobs.update(job, state="running", progress=0.1)
    try:
        if ofx.looks_like_ofx(data):
            parsed = parsing.read_ofx(data)
        else:
            if mapping is None:
                with srv.db.read(user=user_id) as s:
                    account = s.get(Account, account_id)
                    saved = s.scalars(
                        select(ImportMapping).where(
                            ImportMapping.ownerId == account.ownerId,
                            ImportMapping.institution == (account.institution or ""),
                            ImportMapping.deleted == false(),
                        )
                    ).first()
                if saved is None:
                    trades = atypes.investing(account.type)
                    proposal = parsing.propose_csv(data, trades)
                    srv.jobs.update(
                        job,
                        state="done",
                        progress=1.0,
                        result={
                            "needsMapping": True,
                            "uploadId": _hold(data, account_id, user_id, name),
                            "trades": trades,
                            **proposal,
                        },
                    )
                    return
                mapping = json.loads(saved.columns)
            parsed = parsing.read_csv(data, mapping)
        with srv.db.tx(user=user_id) as s:
            account, _ = access.account(s, user_id, account_id, "write")
            if mapping is not None and save_mapping and parsed.format == "csv":
                _save_mapping(s, account, mapping)
            applied = repo.apply_import(
                s, account, user_id, parsed, name, hashlib.sha256(data).hexdigest()
            )
        srv.jobs.update(
            job,
            state="done",
            progress=1.0,
            result={
                "importId": applied.importId,
                "added": applied.added,
                "matched": applied.matched,
                "changed": applied.changed,
                "transfers": applied.transfers,
                "categorised": applied.categorised,
                "coveredFrom": applied.coveredFrom.isoformat() if applied.coveredFrom else None,
                "coveredTo": applied.coveredTo.isoformat() if applied.coveredTo else None,
                "warnings": applied.warnings,
                "accountId": account_id,
            },
        )
        srv.events.publish("import", {"accountId": account_id}, users=[user_id])
    except (ReadError, Problem) as e:
        message = str(e) if isinstance(e, ReadError) else e.detail
        srv.jobs.update(job, state="failed", error={"code": "import-failed", "message": message})
    except Exception:
        import logging

        logging.getLogger("moolakata.imports").exception("import %s failed", job.id)
        srv.jobs.update(
            job,
            state="failed",
            error={
                "code": "import-failed",
                "message": "The import failed; an admin can find it in the log.",
            },
        )


def _save_mapping(s, account: Account, mapping: dict) -> None:
    inst = account.institution or ""
    row = s.scalars(
        select(ImportMapping).where(
            ImportMapping.ownerId == account.ownerId,
            ImportMapping.institution == inst,
            ImportMapping.deleted == false(),
        )
    ).first()
    text = exactjson.dumps(mapping, sort_keys=True)
    if row is None:
        s.add(
            ImportMapping(
                id=ids.new_id("Map"), ownerId=account.ownerId, institution=inst, columns=text
            )
        )
    else:
        row.columns = text


@router.post("/accounts/{account_id}/imports", response_model=JobOut, status_code=202)
async def upload(
    account_id: str, request: Request, file: UploadFile = File(...), c: Caller = Depends(caller)
):
    srv = server(request)
    srv.upload_rate.check(c.id, "uploads")
    with srv.db.read(user=c.id) as s:
        access.account(s, c.id, account_id, "write")
        limit = settings.get(s, "importMaxMb") * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise Problem(413, "too-large", f"Files are up to {limit // (1024 * 1024)} MB.")
    if not data:
        raise refuse("file", "file-empty", "The file is empty.")
    # The type is checked from the content, never the name (S13.7.6).
    media = receipts.sniff(data[:16])
    if media is not None:
        with srv.db.read(user=c.id) as s:
            if not settings.get(s, "readStatements"):
                raise Problem(
                    415,
                    "statements-off",
                    "Statements aren't read on this server: import OFX, QFX or CSV files.",
                )
        job = srv.jobs.create("import", c.id)
        _pool.submit(_run_statement, srv, job, account_id, c.id, data, file.filename or "", media)
        return accepted(job)
    if not (ofx.looks_like_ofx(data) or csvfile.looks_like_csv(data)):
        raise Problem(
            415, "unsupported-type", "Import OFX, QFX or CSV files, or a statement (PDF or photo)."
        )
    job = srv.jobs.create("import", c.id)
    _pool.submit(_run, srv, job, account_id, c.id, data, file.filename or "file", None, False)
    return accepted(job)


@router.post("/imports/{upload_id}/mapping", response_model=JobOut, status_code=202)
def apply_mapping(upload_id: str, body: MappingIn, request: Request, c: Caller = Depends(caller)):
    srv = server(request)
    with _held_lock:
        held = _held.get(upload_id)
    if held is None or held.userId != c.id or held.until < clock.now():
        raise Problem(404, "upload-gone", "That upload has expired; choose the file again.")
    problems = csvfile.check_mapping(body.mapping)
    if problems:
        raise refuse(f"mapping.{problems[0][0]}", "mapping-incomplete", problems[0][1])
    try:
        parsing.read_csv(held.data, body.mapping)
    except ReadError as e:
        raise refuse("mapping", "mapping-does-not-read", str(e)) from None
    with _held_lock:
        _held.pop(upload_id, None)
    job = srv.jobs.create("import", c.id)
    _pool.submit(
        _run, srv, job, held.accountId, c.id, held.data, held.fileName, body.mapping, body.save
    )
    return accepted(job)


# ---------- statements (S1.3.3) ----------


def _layout(s, owner_id: str, institution: str) -> StatementLayout | None:
    return s.scalars(
        select(StatementLayout).where(
            StatementLayout.ownerId == owner_id,
            StatementLayout.institution == institution,
            StatementLayout.deleted == false(),
        )
    ).first()


def _institution_key(account: Account, st) -> str:
    return (account.institution or st.institution or "").strip()


def _read(srv, job: Job, data: bytes, media: str) -> tuple[list[str], str] | None:
    """The statement's lines, read in a worker process as receipts are; None when it can't be
    read (the job is then failed)."""
    from ..receipts import ocr
    from ..receipts.reading import STATEMENT_TIME_LIMIT, Worker

    worker = Worker()
    try:
        outcome = worker.read(data, media, STATEMENT_TIME_LIMIT, ocr.STATEMENT_PAGES)
    finally:
        worker.stop()
    if outcome[0] != "ok":
        srv.jobs.update(
            job,
            state="failed",
            error={"code": "statement-unreadable", "message": f"Couldn't read it: {outcome[1]}."},
        )
        return None
    return outcome[1], outcome[2]


def _parse(s, account: Account, lines: list[str], period=None):
    """Parsed with what is known of its institution's layout; and whether that was known."""
    card = account.type == "credit-card"
    first = statements.parse(lines, clock.today(), None, card, account.institution, period)
    saved = _layout(s, account.ownerId, _institution_key(account, first))
    st = statements.parse(
        lines,
        clock.today(),
        json.loads(saved.layout) if saved else None,
        card,
        account.institution or first.institution,
        period,
    )
    return st, saved is not None


def _present(s, account_id: str | None) -> Counter:
    """The account's transactions by date and amount, each as many times as it is there."""
    if account_id is None:
        return Counter()
    return Counter(
        (x.date, x.amount)
        for x in s.scalars(
            select(Transaction).where(
                Transaction.accountId == account_id, Transaction.deleted == false()
            )
        )
    )


def _marked(rows, have: Counter) -> list[bool]:
    """Which of a statement's lines are already in the account, by date and amount, each
    transaction there answering for one line (S1.3.3.3)."""
    left = Counter(have)
    out = []
    for r in rows:
        k = (r.date, r.amount)
        out.append(left[k] > 0)
        left[k] -= 1
    return out


def _figures(st, have: Counter) -> dict:
    return {
        "institution": st.institution,
        "periodStart": st.periodStart.isoformat() if st.periodStart else None,
        "periodEnd": st.periodEnd.isoformat() if st.periodEnd else None,
        "opening": st.opening,
        "closing": st.closing,
        "rows": [
            {
                "date": r.date.isoformat(),
                "description": r.description,
                "amount": r.amount,
                "confidence": r.confidence,
                "present": present,
                "ignored": r.ignored,
            }
            for r, present in zip(st.rows, _marked(st.rows, have), strict=True)
        ],
    }


EMPTY = "No transactions were found in it. Is it a bank or card statement? It can be kept as it is."


def _run_statement(
    srv, job: Job, account_id: str, user_id: str, data: bytes, name: str, media: str
) -> None:
    """Read it, then parse it with what is known of its institution's layout, and hold it for
    the person to check. A statement of several accounts is split where each part begins, and
    each part goes to the account whose last four digits it shows (S1.3.3.5)."""
    srv.jobs.update(job, state="running", progress=0.1)
    got = _read(srv, job, data, media)
    if got is None:
        return
    lines, method = got
    pieces = statements.split(lines)
    with srv.db.read(user=user_id) as s:
        account, _ = access.account(s, user_id, account_id, "write")
        if atypes.investing(account.type) and _run_brokerage(
            srv, job, s, account, user_id, data, name, lines, method
        ):
            return
        if len(pieces) >= 2:
            _hold_parts(srv, job, s, account, user_id, data, name, lines, method, pieces)
            return
        st, learned = _parse(s, account, lines)
        have = _present(s, account_id)
    if not st.rows:
        # Kept as it is instead, if the person likes (S1.3.3.6).
        upload_id = _hold(data, account_id, user_id, name, lines=lines, method=method)
        start, end, _ = statements.period_and_institution(lines)
        srv.jobs.update(
            job,
            state="failed",
            error={
                "code": "statement-empty",
                "message": EMPTY,
                "uploadId": upload_id,
                "fileName": name,
                "periodStart": start.isoformat() if start else None,
                "periodEnd": end.isoformat() if end else None,
            },
        )
        return
    upload_id = _hold(data, account_id, user_id, name, lines=lines, statement=st, method=method)
    srv.jobs.update(
        job,
        state="done",
        progress=1.0,
        result={
            "needsReview": True,
            "uploadId": upload_id,
            "fileName": name,
            "method": method,
            "learned": learned,
            "accountId": account_id,
            **_figures(st, have),
        },
    )


def _hold_parts(srv, job, s, account, user_id, data, name, lines, method, pieces) -> None:
    whole = statements.period_and_institution(lines)
    writable = [
        a for a, p in access.accounts(s, user_id) if p.writable and atypes.reconcilable(a.type)
    ]
    parsed, out = [], []
    for i, piece in enumerate(pieces):
        matches = [a for a in writable if a.mask == piece.last4]
        chosen = matches[0] if len(matches) == 1 else None
        st, _ = _parse(s, chosen or account, piece.lines, whole[:2])
        if st.institution is None:
            st.institution = whole[2]
        parsed.append(st)
        out.append(
            {
                "index": i,
                "last4": piece.last4,
                "header": piece.header,
                "lineCount": len(piece.lines),
                "accountId": chosen.id if chosen else None,
                "candidates": [
                    {"id": a.id, "name": a.name, "mask": a.mask} for a in (matches or writable)
                ],
                **_figures(st, _present(s, chosen.id if chosen else None)),
            }
        )
    upload_id = _hold(
        data,
        account.id,
        user_id,
        name,
        lines=lines,
        statement=parsed[0],
        method=method,
        parts=parsed,
        decisions={},
    )
    srv.jobs.update(
        job,
        state="done",
        progress=1.0,
        result={
            "needsReview": True,
            "uploadId": upload_id,
            "fileName": name,
            "method": method,
            "accountId": account.id,
            "parts": out,
        },
    )


# ---------- brokerage and plan statements (S1.3.3.8) ----------


def _find_instrument(s, symbol: str | None, cusip: str | None, label: str) -> Instrument | None:
    """The instrument a statement's position names, if MoolaKata knows it: never made here. A
    broker's or a plan's statement names listed securities and funds, never coins (S2.1)."""
    q = select(Instrument).where(
        Instrument.deleted == false(), Instrument.instrumentClass != "crypto"
    )
    for cond in (
        Instrument.cusip == cusip if cusip else None,
        Instrument.symbol == symbol.upper() if symbol else None,
        Instrument.name == label if label else None,
    ):
        if cond is not None:
            found = s.scalars(q.where(cond)).first()
            if found is not None:
                return found
    return None


def snapshot_kept(s, account: Account) -> bool:
    """An account kept by snapshots (R3.2): one with no trades of its own (nothing that makes
    or takes away a lot) and no lot typed on its own, however it is kept current; a
    statement's positions are then its holdings on that date."""
    traded = s.scalar(
        select(Transaction.id).where(
            Transaction.accountId == account.id,
            Transaction.deleted == false(),
            Transaction.instrumentId.is_not(None),
            Transaction.kind.in_(lots.TRADES),
        )
    )
    typed = s.scalar(
        select(Lot.id).where(
            Lot.accountId == account.id, Lot.deleted == false(), Lot.transactionId.is_(None)
        )
    )
    return traded is None and typed is None


def _run_brokerage(srv, job, s, account, user_id, data, name, lines, method) -> bool:
    """A brokerage or plan statement: its summary, positions and cash read and held for the
    person to check. A photo of one isn't read: it is offered to be kept. False when it isn't
    one, for the bank reader to try."""
    if method != "text":
        upload_id = _hold(data, account.id, user_id, name, lines=lines, method=method)
        start, end, _ = statements.period_and_institution(lines)
        srv.jobs.update(
            job,
            state="failed",
            error={
                "code": "brokerage-photo",
                "message": "A photo of a brokerage statement isn't read: its tables don't "
                "survive OCR reliably. Upload the PDF to have it read, or keep this one.",
                "uploadId": upload_id,
                "fileName": name,
                "periodStart": start.isoformat() if start else None,
                "periodEnd": end.isoformat() if end else None,
            },
        )
        return True
    saved = _layout(s, account.ownerId, (account.institution or "").strip())
    b = brokerage.parse(lines, clock.today(), json.loads(saved.layout) if saved else None)
    if not b.read:
        return False
    if b.institution is None:
        b.institution = account.institution
    ledger = repo.load(s, account)
    day = b.periodEnd or clock.today()
    have = _present(s, account.id)
    rows = []
    for p in b.positions:
        inst = None if p.cash else _find_instrument(s, p.symbol, p.cusip, p.label)
        rows.append(
            holdingcheck_row(p, inst.id if inst else None),
        )
    trades = []
    for a in b.activity:
        if a.kind != "trade" or not a.symbol or not a.quantity:
            continue
        inst = _find_instrument(s, a.symbol, None, "")
        if inst is not None:
            sold = re.search(r"\b(sold|sell)\b", a.description, re.I) is not None
            what = (
                "reinvestment"
                if "reinvest" in a.description.lower()
                else ("sale" if sold else "purchase")
            )
            trades.append((a.date, inst.id, -a.quantity if sold else a.quantity, what))
    lines_ = holdingcheck.compare(ledger, day, rows, trades)
    totals = brokerage.totals(b)
    upload_id = _hold(data, account.id, user_id, name, lines=lines, statement=b, method=method)
    srv.jobs.update(
        job,
        state="done",
        progress=1.0,
        result={
            "needsReview": True,
            "kind": "brokerage",
            "uploadId": upload_id,
            "fileName": name,
            "method": method,
            "accountId": account.id,
            "institution": b.institution,
            "periodStart": b.periodStart.isoformat() if b.periodStart else None,
            "periodEnd": b.periodEnd.isoformat() if b.periodEnd else None,
            "summary": {k: _text(v) for k, v in b.summary.__dict__.items()},
            "totals": {k: _text(v) for k, v in totals.items()},
            "snapshot": snapshot_kept(s, account),
            "positions": [
                {
                    "label": r.label,
                    "symbol": p.symbol,
                    "instrumentId": r.instrumentId,
                    "quantity": _text(r.quantity),
                    "price": _text(r.price),
                    "marketValue": _text(r.marketValue),
                    "costBasis": _text(r.costBasis),
                    "cash": r.cash,
                    "held": _text(x.held),
                    "heldBasis": _text(x.heldBasis),
                    "difference": _text(x.difference),
                    "hint": x.hint,
                }
                for p, r, x in zip(b.positions, rows, lines_, strict=True)
            ],
            "activity": [
                {
                    "date": a.date.isoformat(),
                    "description": a.description,
                    "amount": a.amount,
                    "kind": a.kind,
                    "notRead": a.notRead,
                    "symbol": a.symbol,
                    "quantity": _text(a.quantity),
                    "price": _text(a.price),
                    "present": present,
                    "ignored": a.ignored,
                }
                for a, present in zip(b.activity, _marked(b.activity, have), strict=True)
            ],
        },
    )
    return True


def _text(v):
    """A figure as it is: a Decimal is written as an exact number (R1.9)."""
    return v


def holdingcheck_row(p, instrument_id: str | None) -> HoldingCheck:
    return HoldingCheck(
        id="",
        accountId="",
        asOf=dt.date.min,
        label=p.label,
        instrumentId=instrument_id,
        quantity=p.quantity,
        price=p.price,
        marketValue=p.value,
        costBasis=p.cost,
        cash=p.cash,
    )


Ignore = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class PositionIn(Model):
    label: str
    instrumentId: str | None = None
    symbol: str | None = None
    quantity: Quantity | None = None
    price: Quantity | None = None
    marketValue: Money | None = None
    costBasis: Money | None = None
    cash: bool = False


class ActivityIn(Model):
    date: dt.date
    description: str
    amount: Money
    kind: str
    include: bool = True
    symbol: str | None = None


class BrokerageIn(Model):
    periodStart: dt.date
    periodEnd: dt.date
    endingValue: Money | None = None
    positions: list[PositionIn] = Field(default_factory=list)
    rows: list[ActivityIn] = Field(default_factory=list)
    # The starts of lines to ignore in this institution's statements from now on, and those
    # to stop ignoring, as the person asked (S1.3.3.4).
    remember: list[Ignore] = Field(default_factory=list, max_length=20)
    forget: list[Ignore] = Field(default_factory=list, max_length=20)


CASH_KINDS = ("deposit", "withdrawal", "dividend", "interest", "fee")


@router.post("/imports/{upload_id}/brokerage", response_model=JobOut)
def save_brokerage(
    upload_id: str, body: BrokerageIn, request: Request, c: Caller = Depends(caller)
):
    """The ending value becomes a value anchor on the last day; the positions a holdings check
    (or, for an account kept by snapshots, its holdings that day); the cash lines kept become
    transactions; and the PDF is kept on the account. Trades are never added here."""
    srv = server(request)
    held = _held_for(upload_id, c)
    b = held.statement
    if not isinstance(b, brokerage.Brokerage):
        raise Problem(404, "upload-gone", "That upload has expired; choose the file again.")
    if body.periodEnd < body.periodStart:
        raise refuse("periodEnd", "period-backwards", "The period ends before it starts.")
    bad = next((r for r in body.rows if r.include and r.kind not in CASH_KINDS), None)
    if bad is not None:
        raise refuse("rows", "row-not-cash", "Trades aren't added here: enter them as trades.")
    cash = next((p for p in body.positions if p.cash and p.marketValue is not None), None)
    with srv.db.tx(user=c.id) as s:
        account, _ = access.account(s, c.id, held.accountId, "write")
        # A line already in the account (its file brought it) is matched, never added again.
        present = _marked(body.rows, _present(s, account.id))
        kept = [r for r, here in zip(body.rows, present, strict=True) if r.include and not here]
        securities = {}
        rows = []
        for r in kept:
            inst = _find_instrument(s, r.symbol, None, "") if r.kind == "dividend" else None
            if inst is not None:
                securities[inst.symbol] = Security(
                    inst.symbol, inst.symbol, inst.name, inst.instrumentClass, inst.cusip
                )
            rows.append(
                Row(
                    date=r.date,
                    kind=r.kind,
                    amount=r.amount,
                    payee=r.description.strip() or None,
                    security=inst.symbol if inst is not None else None,
                )
            )
        parsed = ParsedFile(
            format="statement",
            rows=rows,
            securities=securities,
            balances=[(body.periodEnd, cash.marketValue)] if cash else [],
            coveredFrom=body.periodStart,
            coveredTo=body.periodEnd,
            institution=b.institution,
        )
        applied = repo.apply_import(
            s,
            account,
            c.id,
            parsed,
            held.fileName or "statement",
            hashlib.sha256(held.data).hexdigest(),
        )
        if body.endingValue is not None:
            repo.keep_anchor(
                s,
                account.id,
                body.periodEnd,
                body.endingValue,
                "statement-value",
                applied.importId,
                c.id,
            )
        snapshot = snapshot_kept(s, account)
        for p in body.positions:
            if p.instrumentId is not None and s.get(Instrument, p.instrumentId) is None:
                raise refuse("positions", "instrument-unknown", "One of the instruments here.")
            inst_id = p.instrumentId
            if snapshot and not p.cash and inst_id is None and (p.symbol or p.label):
                inst_id = repo.instrument(
                    s, p.symbol, p.label, "mutual-fund" if p.symbol is None else "equity"
                ).id
            # The same statement again changes nothing; a figure corrected replaces the one kept.
            repo.keep_position(
                s,
                account.id,
                applied.importId,
                body.periodEnd,
                inst_id,
                p.label[:120],
                check=True,
                quantity=p.quantity,
                price=p.price,
                marketValue=p.marketValue,
                costBasis=p.costBasis,
                cash=p.cash,
            )
        r = _keep_file(
            s, srv, c, held, [account.id], b.institution, body.periodStart, body.periodEnd
        )
        key = (account.institution or b.institution or "").strip()
        if key and (body.remember or body.forget):
            row = _layout(s, account.ownerId, key)
            learned = brokerage.learn(
                json.loads(row.layout) if row else None, body.remember, body.forget
            )
            text = exactjson.dumps(learned, sort_keys=True)
            if row is None:
                s.add(
                    StatementLayout(
                        id=ids.new_id("Lyout"),
                        ownerId=account.ownerId,
                        institution=key,
                        layout=text,
                    )
                )
            else:
                row.layout = text
    with _held_lock:
        _held.pop(upload_id, None)
    return _done(
        srv,
        c,
        {
            "importId": applied.importId,
            "added": applied.added,
            "matched": applied.matched,
            "changed": applied.changed,
            "transfers": applied.transfers,
            "categorised": applied.categorised,
            "coveredFrom": body.periodStart.isoformat(),
            "coveredTo": body.periodEnd.isoformat(),
            "warnings": applied.warnings,
            "accountId": held.accountId,
            "receiptId": r.id,
            "snapshot": snapshot,
        },
        [held.accountId],
    )


class StatementRowIn(Model):
    date: dt.date
    description: str
    amount: Money
    include: bool = True
    # The line it was read as: its place in the rows the read gave, so what the person
    # corrected is told from what was read (S1.3.3.4).
    line: int | None = None


class StatementIn(Model):
    periodStart: dt.date
    periodEnd: dt.date
    opening: Money
    closing: Money
    rows: list[StatementRowIn]
    # Save even though the transactions don't add up to the closing balance.
    acceptDifference: bool = False
    # A statement of several accounts: which part, the account it goes to, or left out.
    part: int | None = None
    accountId: str | None = None
    leftOut: bool = False
    # The starts of lines to ignore in this institution's statements from now on, and those
    # to stop ignoring, as the person asked (S1.3.3.4).
    remember: list[Ignore] = Field(default_factory=list, max_length=20)
    forget: list[Ignore] = Field(default_factory=list, max_length=20)


class KeepIn(Model):
    periodStart: dt.date | None = None
    periodEnd: dt.date | None = None


def _held_for(upload_id: str, c: Caller) -> Held:
    with _held_lock:
        held = _held.get(upload_id)
    if held is None or held.userId != c.id or held.until < clock.now():
        raise Problem(404, "upload-gone", "That upload has expired; choose the file again.")
    return held


def _checked(body: StatementIn, present: list[bool]) -> list[StatementRowIn]:
    """The lines to add: those kept that aren't in the account yet. Every line the account will
    hold counts towards the closing balance, those already there too (S1.3.3.3)."""
    counted = [r for r, here in zip(body.rows, present, strict=True) if r.include or here]
    kept = [r for r, here in zip(body.rows, present, strict=True) if r.include and not here]
    difference = body.closing - body.opening - sum((r.amount for r in counted), Decimal(0))
    if difference != 0 and not body.acceptDifference:
        raise refuse(
            "acceptDifference",
            "statement-does-not-add-up",
            f"The transactions are {abs(difference):,.2f} short of the closing balance. "
            "Correct them, or accept the difference.",
        )
    if body.periodEnd < body.periodStart:
        raise refuse("periodEnd", "period-backwards", "The period ends before it starts.")
    return kept


def _apply(s, c: Caller, held: Held, account: Account, st, body: StatementIn, kept):
    parsed = ParsedFile(
        format="statement",
        rows=[
            Row(
                date=r.date,
                kind="deposit" if r.amount > 0 else "withdrawal",
                amount=r.amount,
                payee=r.description.strip() or None,
            )
            for r in kept
        ],
        balances=[
            (body.periodStart - dt.timedelta(days=1), body.opening),
            (body.periodEnd, body.closing),
        ],
        coveredFrom=body.periodStart,
        coveredTo=body.periodEnd,
        institution=st.institution,
    )
    applied = repo.apply_import(
        s,
        account,
        c.id,
        parsed,
        held.fileName or "statement",
        hashlib.sha256(held.data).hexdigest(),
    )
    _learn(s, account, st, body)
    return applied


def _keep_file(s, srv, c: Caller, held: Held, account_ids: list[str], institution, start, end):
    """The file kept once as a receipt, named by its period, on each account it filled."""
    from ..receipts import reading

    stored = receipts.store(s, srv, c.id, held.fileName or "statement.pdf", held.data)
    r = stored.receipt
    if held.lines:
        r.readStatus, r.readMethod, r.readAt = "read", held.method, clock.now()
        r.text = "\n".join(held.lines)
    r.date = end
    r.payee = statements.name(institution, start, end)
    if held.lines:
        reading.index(s, r)
    for a in account_ids:
        receipts.attach_account(s, c.id, r, a)
    return r


def _done(srv, c: Caller, result: dict, accounts: list[str]) -> JobOut:
    job = srv.jobs.create("import", c.id)
    srv.jobs.update(job, state="done", progress=1.0, result=result)
    for a in accounts:
        srv.events.publish("import", {"accountId": a}, users=[c.id])
    return job_out(job)


@router.post("/imports/{upload_id}/statement", response_model=JobOut)
def save_statement(
    upload_id: str, body: StatementIn, request: Request, c: Caller = Depends(caller)
):
    """Nothing is saved until the person has checked it: the rows they keep become
    transactions (what is already there is matched, not added twice), the balances become the
    account's anchors, the file is kept as a receipt on the account, and the layout is learned
    for the next statement from this institution. A statement of several accounts is saved
    once each part is saved or left out."""
    srv = server(request)
    held = _held_for(upload_id, c)
    if held.statement is None:
        raise Problem(404, "upload-gone", "That upload has expired; choose the file again.")
    if held.parts is not None:
        return _save_part(srv, c, upload_id, held, body)
    with srv.db.read(user=c.id) as s:
        present = _marked(body.rows, _present(s, held.accountId))
    kept = _checked(body, present)
    st = held.statement
    with srv.db.tx(user=c.id) as s:
        account, _ = access.account(s, c.id, held.accountId, "write")
        applied = _apply(s, c, held, account, st, body, kept)
        r = _keep_file(
            s, srv, c, held, [account.id], st.institution, body.periodStart, body.periodEnd
        )
    with _held_lock:
        _held.pop(upload_id, None)
    return _done(
        srv,
        c,
        {
            "importId": applied.importId,
            "added": applied.added,
            "matched": applied.matched,
            "changed": applied.changed,
            "transfers": applied.transfers,
            "categorised": applied.categorised,
            "coveredFrom": body.periodStart.isoformat(),
            "coveredTo": body.periodEnd.isoformat(),
            "warnings": applied.warnings,
            "accountId": held.accountId,
            "receiptId": r.id,
        },
        [held.accountId],
    )


def _save_part(srv, c: Caller, upload_id: str, held: Held, body: StatementIn) -> JobOut:
    n = len(held.parts)
    if body.part is None or not 0 <= body.part < n:
        raise refuse("part", "part-unknown", f"One of the statement's {n} parts.")
    if not body.leftOut:
        if not body.accountId:
            raise refuse("accountId", "account-missing", "The account this part goes to.")
        with srv.db.read(user=c.id) as s:
            access.account(s, c.id, body.accountId, "write")
            _checked(body, _marked(body.rows, _present(s, body.accountId)))
    held.decisions[body.part] = body
    left = [i for i in range(n) if i not in held.decisions]
    if left:
        return _done(srv, c, {"part": body.part, "remaining": left}, [])
    saved = [(i, d) for i, d in sorted(held.decisions.items()) if not d.leftOut]
    results, accounts = [], []
    with srv.db.tx(user=c.id) as s:
        for i, d in saved:
            account, _ = access.account(s, c.id, d.accountId, "write")
            kept = _checked(d, _marked(d.rows, _present(s, account.id)))
            applied = _apply(s, c, held, account, held.parts[i], d, kept)
            accounts.append(account.id)
            results.append({"part": i, "accountId": account.id, "added": applied.added})
        r = None
        if saved:
            ends = [d.periodEnd for _, d in saved]
            starts = [d.periodStart for _, d in saved]
            r = _keep_file(
                s,
                srv,
                c,
                held,
                list(dict.fromkeys(accounts)),
                held.parts[saved[0][0]].institution,
                min(starts),
                max(ends),
            )
    with _held_lock:
        _held.pop(upload_id, None)
    return _done(
        srv,
        c,
        {
            "parts": results,
            "leftOut": [i for i, d in sorted(held.decisions.items()) if d.leftOut],
            "receiptId": r.id if r else None,
            "accountId": held.accountId,
        },
        accounts,
    )


# ---------- statements kept without reading (S1.3.3.6) ----------


@router.post("/accounts/{account_id}/statements/keep", response_model=JobOut, status_code=202)
async def keep_upload(
    account_id: str, request: Request, file: UploadFile = File(...), c: Caller = Depends(caller)
):
    """A statement to keep on its account as it is: its period and institution are read where
    they can be, for the person to check."""
    srv = server(request)
    srv.upload_rate.check(c.id, "uploads")
    with srv.db.read(user=c.id) as s:
        access.account(s, c.id, account_id, "write")
        limit = settings.get(s, "importMaxMb") * 1024 * 1024
        reads = settings.get(s, "readStatements")
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise Problem(413, "too-large", f"Files are up to {limit // (1024 * 1024)} MB.")
    if not data:
        raise refuse("file", "file-empty", "The file is empty.")
    media = receipts.sniff(data[:16])
    if media is None:
        raise Problem(415, "unsupported-type", "A statement: a PDF or a photo of one.")
    job = srv.jobs.create("import", c.id)
    _pool.submit(_run_keep, srv, job, account_id, c.id, data, file.filename or "", media, reads)
    return accepted(job)


def _run_keep(srv, job, account_id, user_id, data, name, media, reads: bool) -> None:
    srv.jobs.update(job, state="running", progress=0.1)
    lines: list[str] = []
    method = None
    if reads:
        got = _read(srv, job, data, media)
        if got is None:
            return
        lines, method = got
    start, end, inst = statements.period_and_institution(lines)
    upload_id = _hold(data, account_id, user_id, name, lines=lines or None, method=method)
    srv.jobs.update(
        job,
        state="done",
        progress=1.0,
        result={
            "keep": True,
            "uploadId": upload_id,
            "fileName": name,
            "read": bool(lines),
            "periodStart": start.isoformat() if start else None,
            "periodEnd": end.isoformat() if end else None,
            "institution": inst,
            "accountId": account_id,
        },
    )


@router.post("/imports/{upload_id}/keep", response_model=JobOut)
def keep_statement(upload_id: str, body: KeepIn, request: Request, c: Caller = Depends(caller)):
    """Kept on the account as a receipt named by its period, its period recorded so it counts
    as the statement expected (S1.11.7), its lines never added."""
    srv = server(request)
    held = _held_for(upload_id, c)
    if body.periodStart is None or body.periodEnd is None:
        raise refuse("periodEnd", "period-missing", "The period the statement covers.")
    if body.periodEnd < body.periodStart:
        raise refuse("periodEnd", "period-backwards", "The period ends before it starts.")
    digest = hashlib.sha256(held.data).hexdigest()
    with srv.db.tx(user=c.id) as s:
        account, _ = access.account(s, c.id, held.accountId, "write")
        twice = s.scalars(
            select(Import).where(
                Import.accountId == account.id,
                Import.fileHash == digest,
                Import.deleted == false(),
            )
        ).first()
        if twice is not None:
            raise refuse("file", "statement-kept-already", "This statement is already here.", 409)
        inst = statements.period_and_institution(held.lines or [])[2]
        r = _keep_file(
            s,
            srv,
            c,
            held,
            [account.id],
            account.institution or inst,
            body.periodStart,
            body.periodEnd,
        )
        imp = Import(
            id=ids.new_id("Imprt"),
            accountId=account.id,
            userId=c.id,
            format="kept",
            fileName=held.fileName or "statement.pdf",
            fileHash=digest,
            coveredFrom=body.periodStart,
            coveredTo=body.periodEnd,
        )
        s.add(imp)
    with _held_lock:
        _held.pop(upload_id, None)
    return _done(
        srv,
        c,
        {"kept": True, "importId": imp.id, "receiptId": r.id, "accountId": held.accountId},
        [held.accountId],
    )


def _learn(s, account: Account, st, body: StatementIn) -> None:
    """The layout learned from the lines the person kept, each as it was read (found by its
    `line`, or, for a dialog that sends none, by its date and description), and the lines to
    ignore that they asked for (S1.3.3.4)."""
    by_key = {(x.date, x.description): x for x in st.rows}

    def read_as(r: StatementRowIn):
        if r.line is not None and 0 <= r.line < len(st.rows):
            return st.rows[r.line]
        return by_key.get((r.date, r.description))

    kept = []
    for r in body.rows:
        if not r.include:
            continue
        was = read_as(r)
        description = was.description if was is not None else r.description
        section = getattr(was, "section", None)
        kept.append(statements.StatementRow(r.date, description, r.amount, section=section))
    key = _institution_key(account, st)
    if not key:
        return
    row = _layout(s, account.ownerId, key)
    learned = statements.learn(
        json.loads(row.layout) if row else None, kept, body.remember, body.forget
    )
    text = exactjson.dumps(learned, sort_keys=True)
    if row is None:
        s.add(
            StatementLayout(
                id=ids.new_id("Lyout"), ownerId=account.ownerId, institution=key, layout=text
            )
        )
    elif row.layout != text:
        row.layout = text


@router.delete("/imports/{upload_id}", response_model=Deleted)
def let_go(upload_id: str, c: Caller = Depends(caller)):
    """An upload its dialog no longer needs (closed, or cancelled), let go at once rather than
    when it expires. Held in memory, it has no version; one already gone answers the same."""
    with _held_lock:
        held = _held.get(upload_id)
        if held is not None and held.userId == c.id:
            del _held[upload_id]
    return Deleted(deleted=Gone(id=upload_id))


class IgnoredLine(Model):
    institution: str
    # A bank or card statement's lines, or a brokerage statement's.
    kind: Literal["bank", "brokerage"]
    start: str


@router.get("/statement-layouts/ignored", response_model=list[IgnoredLine])
def ignored_lines(request: Request, c: Caller = Depends(caller)):
    """The starts of statement lines the person asked to ignore (S1.3.3.4), by institution."""
    srv = server(request)
    out = []
    with srv.db.read(user=c.id) as s:
        for row in s.scalars(
            select(StatementLayout)
            .where(StatementLayout.ownerId == c.id, StatementLayout.deleted == false())
            .order_by(StatementLayout.institution)
        ):
            layout = json.loads(row.layout or "{}")
            for start in layout.get("skip", []):
                out.append(IgnoredLine(institution=row.institution, kind="bank", start=start))
            for start in (layout.get("brokerage") or {}).get("skip", []):
                out.append(IgnoredLine(institution=row.institution, kind="brokerage", start=start))
    return out


@router.post("/statement-layouts/ignored/forget", status_code=204)
def forget_ignored_line(body: IgnoredLine, request: Request, c: Caller = Depends(caller)):
    """One of them no longer ignored: its lines are read again from the next statement."""
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
        row = _layout(s, c.id, body.institution)
        if row is not None:
            layout = json.loads(row.layout or "{}")
            if body.kind == "bank":
                layout["skip"] = statements.ignoring(layout.get("skip", []), [], [body.start])
            else:
                layout = brokerage.learn(layout, forget=[body.start])
            row.layout = exactjson.dumps(layout, sort_keys=True)
    return Response(status_code=204)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, request: Request, c: Caller = Depends(caller)):
    job = server(request).jobs.get(job_id, c.id)
    if job is None:
        raise Problem(404, "not-found", "Not found")
    return job_out(job)


@router.get("/accounts/{account_id}/imports", response_model=list[ImportRow])
def list_imports(account_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        a, _ = access.account(s, c.id, account_id)
        names = {u.id: u.displayName for u in s.scalars(select(User))}
        rows = s.scalars(
            select(Import)
            .where(Import.accountId == a.id, Import.deleted == false())
            .order_by(Import.createdAt.desc())
        ).all()
        return [
            ImportRow(
                id=i.id,
                format=i.format,
                fileName=i.fileName,
                coveredFrom=i.coveredFrom,
                coveredTo=i.coveredTo,
                added=i.added,
                matched=i.matched,
                changed=i.changed,
                userName=names.get(i.userId, ""),
                createdAt=i.createdAt,
            )
            for i in rows
        ]
