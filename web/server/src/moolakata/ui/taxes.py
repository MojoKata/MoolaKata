"""Tax books (requirements S8.14–S8.17, S12.2.10): the books a user holds or helps with, their
filers and the accounts they count, filings with their estimated payments and the figures they
carry forward, and tax documents received and filed, against the documents expected."""

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import false, select

from .. import access, activity, clock, exactjson, ids, people, receipts
from ..errors import FieldError, Problem, refuse
from ..store.entities.accounts import Account, Transaction
from ..store.entities.taxes import (
    EstimatedPayment,
    Filing,
    TaxBook,
    TaxBookAccount,
    TaxBookDependent,
    TaxBookFiler,
    TaxDocument,
)
from ..store.entities.users import User
from ..store.rows import by_key
from ..taxes import books, closed, dependents
from . import save
from .conventions import ExactRoute, IdOf, Model, Money
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["taxes"])

RECEIVED_FORMS = (
    "W-2",
    "1099 (composite)",
    "1099-B",
    "1099-DIV",
    "1099-INT",
    "1099-R",
    "1099-Q",
    "1099-SA",
    "1099-DA",
    "1099-NEC",
    "1098",
    "1098-E",
    "1098-T",
    "Childcare provider statement",
    "1095",
    "K-1",
    "5498",
    "5498-SA",
    "Property-tax bill",
    "Other",
)
FILED_FORMS = (
    "Return as filed",
    "E-file acknowledgement",
    "Extension",
    "Notice or letter",
    "Reply",
    "Transcript",
    "Preparer's worksheets",
    "Other",
)


class Filer(Model):
    id: str
    name: str
    accepted: bool


class BookRow(Model):
    id: str
    year: int
    filers: list[Filer]
    level: str  # owner, write, read; pending for a filer yet to accept
    label: str
    version: int


def _filers(s, b: TaxBook) -> list[Filer]:
    fs = books.filers(s, b)
    nm = books.names(s, [f.userId for f in fs])
    return [
        Filer(id=f.userId, name=nm.get(f.userId, "?"), accepted=f.acceptedAt is not None)
        for f in fs
    ]


def _row(s, b: TaxBook, lvl: str) -> BookRow:
    fs = _filers(s, b)
    who = " & ".join(f.name.split(" ")[0] for f in fs)
    label = f"{b.year} · {who}" + (" (joint)" if len(fs) > 1 else "")
    return BookRow(id=b.id, year=b.year, filers=fs, level=lvl, label=label, version=b.version)


@router.get("/tax-books", response_model=list[BookRow])
def list_books(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        return [_row(s, b, lvl) for b, lvl in books.visible(s, c.id)]


class NewBookOut(BookRow):
    dependentsLeftOut: list[str]  # last year's, past a qualifying child's age (S8.14.5.4)


class NewBook(Model):
    year: int
    filers: list[str]
    fromLastYear: bool = True
    bitcoinFees: str = "sale"  # or not-taxed, on transfers between the owner's accounts


def _make_book(s, c: Caller, body, book_id: str) -> tuple[TaxBook, list[str]]:
    """A book for a year and its filers: the caller, alone or with their spouse. With
    *from last year*, it copies last year's accounts left out or added, and its dependents a
    year older, leaving out and naming those past a qualifying child's age (S8.14.4)."""
    year = clock.today().year
    if not year - 10 <= body.year <= year + 1:
        raise refuse("year", "year-invalid", "A recent tax year.")
    who = list(dict.fromkeys(body.filers or [c.id]))
    if c.id not in who:
        raise refuse("filers", "filers-invalid", "You are one of the filers.")
    if len(who) > 2:
        raise refuse("filers", "filers-invalid", "One filer, or two who are married.")
    if len(who) == 2 and not people.joint_filers(s, who[0], who[1], body.year):
        raise refuse(
            "filers",
            "not-married",
            "Two filers file together only if married on the last day of the year.",
        )
    if body.bitcoinFees not in ("sale", "not-taxed"):
        raise refuse("bitcoinFees", "choice-invalid", "A sale, or not taxed.")
    b = TaxBook(
        id=book_id,
        ownerId=c.id,
        year=body.year,
        bitcoinFees=body.bitcoinFees,
        fromLastYear=body.fromLastYear,
    )
    s.add(b)
    s.flush()
    now = clock.now()
    for u in who:
        s.add(
            TaxBookFiler(
                bookId=b.id, userId=u, createdAt=now, acceptedAt=now if u == c.id else None
            )
        )
    s.flush()
    left = _from_last_year(s, b, now)
    activity.record(
        s, "tax-book.created", actor=c.id, subject_kind="tax-book", subject_id=b.id, owner=c.id
    )
    s.flush()
    return b, left


@router.post("/tax-books", response_model=NewBookOut, status_code=201)
def create_book(body: NewBook, request: Request, c: Caller = Depends(caller)):
    with server(request).db.tx() as s:
        b, left = _make_book(s, c, body, ids.new_id("TaxBk"))
        return NewBookOut(**_row(s, b, "owner").model_dump(), dependentsLeftOut=left)


def _from_last_year(s, b: TaxBook, now: dt.datetime) -> list[str]:
    """What a new book copies from last year's (S8.14.4): its accounts added or left out, and
    its dependents a year older, once every filer has accepted the new book; until then it
    waits. The names of the dependents it left out."""
    if not b.fromLastYear or not books.accepted(s, b):
        return []
    b.fromLastYear = False
    prev = books.previous(s, b)
    if prev is None:
        return []
    for o in s.scalars(
        select(TaxBookAccount).where(
            TaxBookAccount.bookId == prev.id, TaxBookAccount.deleted == false()
        )
    ):
        s.add(
            TaxBookAccount(
                bookId=b.id,
                accountId=o.accountId,
                counted=o.counted,
                addedById=o.addedById,
                createdAt=now,
            )
        )
    s.flush()
    return dependents.carry_over(s, prev, b, now)


@router.post("/tax-books/{book_id}/accept", response_model=BookRow)
def accept(book_id: str, request: Request, c: Caller = Depends(caller)):
    """A filer named by someone else accepts; then the book counts their accounts."""
    with server(request).db.tx() as s:
        b = s.get(TaxBook, book_id)
        f = (
            next((x for x in books.filers(s, b) if x.userId == c.id), None)
            if b is not None and not b.deleted
            else None
        )
        if f is None:
            raise Problem(404, "not-found", "Not found")
        f.acceptedAt = f.acceptedAt or clock.now()
        s.flush()
        _from_last_year(s, b, clock.now())
        s.flush()
        return _row(s, b, "owner")


# ---- A book in full ----


class AccountRef(Model):
    id: str
    name: str
    type: str
    ownerName: str
    # Its change in this book (TaxBookAccount), a record of the save: added or left out.
    rowId: str | None = None
    rowVersion: int = 0


class Payment(Model):
    id: str | None = None
    quarter: int
    dueDate: dt.date | None = None
    amount: Money
    paidOn: dt.date | None = None
    transactionId: str | None = None


class PaymentView(Model):
    """A payment as shown; its own model, so the contract has one schema each way."""

    id: str | None
    version: int
    quarter: int
    dueDate: dt.date | None
    amount: Money
    paidOn: dt.date | None
    transactionId: str | None


class CarriedView(Model):
    agi: Money | None = None
    totalTax: Money | None = None
    overpaymentApplied: Money | None = None
    capitalLossShort: Money | None = None
    capitalLossLong: Money | None = None
    basis8606: Money | None = None
    charitableCarryover: Money | None = None


class Carried(Model):
    agi: Money | None = None
    totalTax: Money | None = None
    overpaymentApplied: Money | None = None
    capitalLossShort: Money | None = None
    capitalLossLong: Money | None = None
    basis8606: Money | None = None
    charitableCarryover: Money | None = None


class DocumentOut(Model):
    id: str
    direction: str
    form: str
    issuer: str | None
    accountId: str | None
    accountName: str | None
    filingId: str | None
    receiptId: str | None
    fileName: str | None
    notes: str | None
    version: int


class FilingOut(Model):
    id: str
    jurisdiction: str
    place: str | None
    form: str
    label: str
    amendsId: str | None
    filingStatus: str | None
    preparedBy: str | None
    sentBy: str | None
    progress: str
    dueDate: dt.date | None
    extensionFiledOn: dt.date | None
    extendedDue: dt.date | None
    filedOn: dt.date | None
    confirmation: str | None
    resultKind: str | None
    resultAmount: Money | None
    resultTransactionId: str | None
    resultPaid: str | None  # the matched transaction, described
    overdue: bool
    payments: list[PaymentView]
    carried: CarriedView
    documents: list[DocumentOut]
    version: int


class ExpectedOut(Model):
    form: str
    issuer: str | None
    accountId: str | None
    why: str
    document: DocumentOut | None


class LastYear(Model):
    filing: str
    figures: CarriedView


class DependentOut(Model):
    id: str
    personId: str
    name: str
    relation: str | None  # to the filers on Dec 31: daughter
    claimedAs: str
    months: int
    student: bool
    age: int | None  # on Dec 31; none without a birth year
    under17: bool
    under13: bool
    agesOut: list[str]
    claimedElsewhere: bool  # on another book of the year too
    accountIds: list[str]  # counted accounts in their name
    version: int


class Form8615Out(Model):
    name: str
    unearned: Money
    threshold: Money
    accounts: list[str]


class BookDetail(BookRow):
    bitcoinFees: str  # network fees on own transfers: sale or not-taxed (S8.19)
    dependents: list[DependentOut]
    form8615: list[Form8615Out]  # dependent children past the year's threshold
    claimedElsewhere: list[str]  # the book's filers claimed on another book of the year
    accounts: list[AccountRef]
    leftOut: list[AccountRef]
    addable: list[AccountRef]  # accounts the caller can see, not counted
    filings: list[FilingOut]
    expected: list[ExpectedOut]
    received: list[DocumentOut]  # received documents not on the expected list
    lastYear: list[LastYear]
    federalDue: dt.date
    canWrite: bool


def _dependent(d: dependents.Dependent) -> DependentOut:
    return DependentOut(
        id=d.row.id,
        personId=d.person.id,
        name=d.person.name,
        relation=d.relation,
        claimedAs=d.row.claimedAs,
        months=d.row.months,
        student=d.row.student,
        age=d.age,
        under17=d.under17,
        under13=d.under13,
        agesOut=d.agesOut,
        claimedElsewhere=d.claimedElsewhere,
        accountIds=d.accountIds,
        version=d.row.version,
    )


def _acct(s, a: Account, book_id: str | None = None) -> AccountRef:
    row = by_key(s, TaxBookAccount, bookId=book_id, accountId=a.id) if book_id else None
    live = row is not None and not row.deleted
    return AccountRef(
        id=a.id,
        name=a.name,
        type=a.type,
        ownerName=s.get(User, a.ownerId).displayName,
        rowId=row.id if live else None,
        rowVersion=row.version if live else 0,
    )


def _doc(s, d: TaxDocument) -> DocumentOut:
    a = s.get(Account, d.accountId) if d.accountId else None
    from ..store.entities.receipts import Receipt

    r = s.get(Receipt, d.receiptId) if d.receiptId else None
    return DocumentOut(
        id=d.id,
        direction=d.direction,
        form=d.form,
        issuer=d.issuer,
        accountId=d.accountId,
        accountName=a.name if a else None,
        filingId=d.filingId,
        receiptId=d.receiptId,
        fileName=r.fileName if r is not None and not r.deleted else None,
        notes=d.notes,
        version=d.version,
    )


def _label(f: Filing) -> str:
    where = "Federal" if f.jurisdiction == "federal" else (f.place or f.jurisdiction.title())
    return f"{where} · {f.form}" + (" (amended)" if f.amendsId else "")


def _paid(s, t_id: str | None) -> str | None:
    t = s.get(Transaction, t_id) if t_id else None
    if t is None or t.deleted:
        return None
    a = s.get(Account, t.accountId)
    return f"{a.name} · {t.date:%b %-d} · {t.payee or ''} {t.amount:+,.2f}".replace("  ", " ")


def _filing(s, f: Filing, docs: list[TaxDocument], today: dt.date) -> FilingOut:
    pays = s.scalars(
        select(EstimatedPayment)
        .where(EstimatedPayment.filingId == f.id, EstimatedPayment.deleted == false())
        .order_by(EstimatedPayment.quarter)
    )
    return FilingOut(
        id=f.id,
        jurisdiction=f.jurisdiction,
        place=f.place,
        form=f.form,
        label=_label(f),
        amendsId=f.amendsId,
        filingStatus=f.filingStatus,
        preparedBy=f.preparedBy,
        sentBy=f.sentBy,
        progress=f.progress,
        dueDate=f.dueDate,
        extensionFiledOn=f.extensionFiledOn,
        extendedDue=f.extendedDue,
        filedOn=f.filedOn,
        confirmation=f.confirmation,
        resultKind=f.resultKind,
        resultAmount=f.resultAmount,
        resultTransactionId=f.resultTransactionId,
        resultPaid=_paid(s, f.resultTransactionId),
        overdue=books.overdue(f, today),
        payments=[
            PaymentView(
                id=p.id,
                version=p.version,
                quarter=p.quarter,
                dueDate=p.dueDate,
                amount=p.amount,
                paidOn=p.paidOn,
                transactionId=p.transactionId,
            )
            for p in pays
        ],
        carried=CarriedView(
            **{
                k: v
                for k, v in exactjson.loads(f.carried or "{}").items()
                if k in Carried.model_fields
            }
        ),
        documents=[_doc(s, d) for d in docs if d.filingId == f.id],
        version=f.version,
    )


def detail(s, c: Caller, b: TaxBook, lvl: str) -> BookDetail:
    today = clock.today()
    cnt = books.counted(s, b)
    docs = books.documents(s, b)
    exp = books.expected(s, b)
    matched = {e.document.id for e in exp if e.document is not None}
    counted_ids = {a.id for a in cnt.accounts}
    addable = [
        a
        for a, _ in access.visible_accounts(s, c.id)
        if a.id not in counted_ids and a.id not in {x.id for x in cnt.leftOut}
    ]
    base = _row(s, b, lvl)
    deps = dependents.listed(s, b)
    return BookDetail(
        **base.model_dump(),
        bitcoinFees=b.bitcoinFees,
        dependents=[_dependent(d) for d in deps],
        form8615=[
            Form8615Out(**f.__dict__) for f in dependents.form_8615(s, b, deps, cnt.accounts)
        ],
        claimedElsewhere=[p.name for p in dependents.filers_claimed_elsewhere(s, b)],
        accounts=[_acct(s, a, b.id) for a in cnt.accounts],
        leftOut=[_acct(s, a, b.id) for a in cnt.leftOut],
        addable=[_acct(s, a, b.id) for a in addable],
        filings=[_filing(s, f, docs, today) for f in books.filings(s, b)],
        expected=[
            ExpectedOut(
                form=e.form,
                issuer=e.issuer,
                accountId=e.accountId,
                why=e.why,
                document=_doc(s, e.document) if e.document else None,
            )
            for e in exp
        ],
        received=[_doc(s, d) for d in docs if d.direction == "received" and d.id not in matched],
        lastYear=[
            LastYear(
                filing=_label(f),
                figures=CarriedView(
                    **{k: v for k, v in figures.items() if k in Carried.model_fields}
                ),
            )
            for f, figures in books.carried_from_last_year(s, b)
        ],
        federalDue=books.federal_due(s, b.year),
        canWrite=lvl in ("owner", "write"),
    )


@router.get("/tax-books/{book_id}", response_model=BookDetail)
def get_book(book_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        b, lvl = books.get(s, c.id, book_id)
        return detail(s, c, b, lvl)


class BookAccountRecord(Model):
    """An account a tax book counts or leaves out beyond what its filers' own say (S8.14.2):
    one the caller can see added (a custodial account in a child's name), or one of the
    filers' own left out. Deleted, the book counts it as its filers' accounts say."""

    bookId: IdOf("TaxBk")  # type: ignore[valid-type]
    accountId: IdOf("Acct")  # type: ignore[valid-type]
    counted: bool


def _book_account_filer(ctx, book_id: str):
    b, lvl = books.get(ctx.s, ctx.caller.id, book_id, "read")
    if lvl != "owner":  # a helper edits filings, never what the book counts (S8.14.3)
        raise refuse(None, "filers-only", "Only its filers add or leave out accounts.", 403)
    return b


def _book_account_create(ctx, record_id: str, body: BookAccountRecord) -> None:
    s, c = ctx.s, ctx.caller
    b = _book_account_filer(ctx, body.bookId)
    access.account(s, c.id, body.accountId)
    have = by_key(s, TaxBookAccount, bookId=b.id, accountId=body.accountId)
    if have is not None and not have.deleted:
        raise refuse("accountId", "account-in-book", "It is in the book: change it.", 409)
    s.add(
        TaxBookAccount(
            id=record_id,
            bookId=b.id,
            accountId=body.accountId,
            counted=body.counted,
            addedById=c.id,
        )
    )


def _book_account_editable(ctx, record_id: str) -> TaxBookAccount:
    row = ctx.s.get(TaxBookAccount, record_id)
    if row is None or row.deleted:
        raise Problem(404, "not-found", "Not found")
    _book_account_filer(ctx, row.bookId)
    return row


def _book_account_update(ctx, row: TaxBookAccount, body: BookAccountRecord) -> None:
    if (body.bookId, body.accountId) != (row.bookId, row.accountId):
        raise refuse("accountId", "account-fixed", "It stays with its book and account.")
    row.counted, row.addedById = body.counted, ctx.caller.id


def _book_account_read(ctx, record_id: str) -> BookDetail:
    row = ctx.s.get(TaxBookAccount, record_id)
    b, lvl = books.get(ctx.s, ctx.caller.id, row.bookId, "read")
    return detail(ctx.s, ctx.caller, b, lvl)


save.register(
    save.Kind(
        prefix="TxBkA",
        entity=TaxBookAccount,
        fields=BookAccountRecord,
        create=_book_account_create,
        editable=_book_account_editable,
        current=lambda ctx, row: {
            "bookId": row.bookId,
            "accountId": row.accountId,
            "counted": row.counted,
        },
        update=_book_account_update,
        delete=lambda ctx, row: row.mark_deleted(ctx.caller.id),
        read=_book_account_read,
    )
)


# ---- Dependents (S8.14.5) ----


class CandidateOut(Model):
    personId: str
    name: str
    relation: str | None
    age: int | None
    suggest: str  # how they'd be claimed: qualifying child or relative
    suggestIfStudent: str  # the same, were they a full-time student


@router.get("/tax-books/{book_id}/dependent-candidates", response_model=list[CandidateOut])
def dependent_candidates(book_id: str, request: Request, c: Caller = Depends(caller)):
    """The household's people the caller sees, with their relation to the filers on Dec 31
    and how the family tree suggests claiming them (S8.14.5.1)."""
    with server(request).db.read() as s:
        b, _ = books.get(s, c.id, book_id, "write")
        return [
            CandidateOut(
                personId=x.person.id,
                name=x.person.name,
                relation=x.relation,
                age=x.age,
                suggest=dependents.suggest(x.descendant, x.age, False),
                suggestIfStudent=dependents.suggest(x.descendant, x.age, True),
            )
            for x in dependents.candidates(s, c.id, b)
        ]


class DependentIn(Model):
    personId: str
    claimedAs: str = "qualifying child"
    months: int = 12
    student: bool = False
    accountIds: list[str] = Field(default_factory=list)


def _dependent_values(s, c: Caller, b: TaxBook, body: DependentIn, row_id: str | None) -> dict:
    e: list[FieldError] = []
    if body.claimedAs not in dependents.CLAIMS:
        e.append(FieldError("claimedAs", "claimed-as-invalid", "Qualifying child or relative."))
    if not 0 <= body.months <= 12:
        e.append(FieldError("months", "months-invalid", "From 0 to 12."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    try:
        p = people.get(s, c.id, body.personId)
    except Problem:
        raise refuse("personId", "person-unknown", "One of the household's people.") from None
    if p.id in dependents.filer_people(s, b):
        raise refuse("personId", "dependent-filer", "A filer isn't their own dependent.")
    for d in dependents.of_book(s, b):
        if d.personId == p.id and d.id != row_id:
            raise refuse("personId", "dependent-twice", "Already a dependent in this book.")
    counted = {a.id for a in books.counted(s, b).accounts}
    if any(i not in counted for i in body.accountIds):
        raise refuse("accountIds", "account-not-counted", "Accounts this book counts.")
    return {
        "personId": p.id,
        "claimedAs": body.claimedAs,
        "months": body.months,
        "student": body.student,
    }


@router.post("/tax-books/{book_id}/dependents", response_model=BookDetail, status_code=201)
def add_dependent(book_id: str, body: DependentIn, request: Request, c: Caller = Depends(caller)):
    with server(request).db.tx() as s:
        b, lvl = books.get(s, c.id, book_id, "write")
        d = TaxBookDependent(
            id=ids.new_id("TxDep"), bookId=b.id, **_dependent_values(s, c, b, body, None)
        )
        s.add(d)
        s.flush()
        dependents.set_accounts(s, d, list(dict.fromkeys(body.accountIds)), clock.now())
        s.flush()
        return detail(s, c, b, lvl)


def _own_dependent(s, c: Caller, dep_id: str) -> tuple[TaxBookDependent, TaxBook, str]:
    d = s.get(TaxBookDependent, dep_id)
    if d is None or d.deleted:
        raise Problem(404, "not-found", "Not found")
    b, lvl = books.get(s, c.id, d.bookId, "write")
    return d, b, lvl


# ---- Filings (S8.15) ----


class FilingIn(Model):
    jurisdiction: str = "federal"
    place: str | None = None
    form: str = "Form 1040"
    amendsId: str | None = None
    filingStatus: str | None = None
    preparedBy: str | None = None
    sentBy: str | None = None
    progress: str = "not started"
    dueDate: dt.date | None = None
    extensionFiledOn: dt.date | None = None
    extendedDue: dt.date | None = None
    filedOn: dt.date | None = None
    confirmation: str | None = None
    resultKind: str | None = None
    resultAmount: Money | None = None
    resultTransactionId: str | None = None
    payments: list[Payment] = Field(default_factory=list)
    carried: Carried = Field(default_factory=Carried)


STATUSES = (
    "Single",
    "Married filing jointly",
    "Married filing separately",
    "Head of household",
    "Qualifying surviving spouse",
)


def _filing_values(s, c: Caller, b: TaxBook, body: FilingIn) -> dict:
    e: list[FieldError] = []
    if body.jurisdiction not in ("federal", "state", "local"):
        e.append(
            FieldError("jurisdiction", "jurisdiction-invalid", "Federal, a state, a locality.")
        )
    if body.jurisdiction != "federal" and not (body.place or "").strip():
        e.append(FieldError("place", "place-missing", "Which state or locality."))
    if not body.form.strip():
        e.append(FieldError("form", "form-missing", "The form: Form 1040, IT-201…"))
    if body.progress not in ("not started", "in progress", "filed", "accepted", "rejected"):
        e.append(FieldError("progress", "progress-invalid", "Where it is."))
    if body.filingStatus and body.filingStatus not in STATUSES:
        e.append(FieldError("filingStatus", "status-invalid", "One of the filing statuses."))
    if body.sentBy and body.sentBy not in ("e-file", "paper"):
        e.append(FieldError("sentBy", "sent-invalid", "E-file or paper."))
    if body.resultKind and body.resultKind not in ("refund", "owed", "none"):
        e.append(FieldError("resultKind", "result-invalid", "A refund, an amount owed, nothing."))
    if body.progress in ("filed", "accepted") and not body.filedOn:
        e.append(FieldError("filedOn", "filed-on-missing", "The day it was filed."))
    for i, p in enumerate(getattr(body, "payments", [])):
        if not 1 <= p.quarter <= 4:
            e.append(FieldError(f"payments.{i}.quarter", "quarter-invalid", "1 to 4."))
        if p.amount < 0:
            e.append(FieldError(f"payments.{i}.amount", "amount-invalid", "Zero or more."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    if body.amendsId:
        amended = s.get(Filing, body.amendsId)
        if amended is None or amended.deleted or amended.bookId != b.id:
            raise refuse("amendsId", "filing-unknown", "One of this book's filings.")
    for t_id in [
        body.resultTransactionId,
        *[p.transactionId for p in getattr(body, "payments", [])],
    ]:
        if t_id:
            t = s.get(Transaction, t_id)
            if t is None or t.deleted:
                raise refuse("resultTransactionId", "not-found", "No such transaction.")
            access.account(s, c.id, t.accountId)
    due = body.dueDate
    if due is None and body.jurisdiction == "federal" and not body.amendsId:
        due = books.federal_due(s, b.year)
    return {
        "jurisdiction": body.jurisdiction,
        "place": (body.place or "").strip() or None if body.jurisdiction != "federal" else None,
        "form": body.form.strip(),
        "amendsId": body.amendsId or None,
        "filingStatus": body.filingStatus or None,
        "preparedBy": (body.preparedBy or "").strip() or None,
        "sentBy": body.sentBy or None,
        "progress": body.progress,
        "dueDate": due,
        "extensionFiledOn": body.extensionFiledOn,
        "extendedDue": body.extendedDue,
        "filedOn": body.filedOn,
        "confirmation": (body.confirmation or "").strip() or None,
        "resultKind": body.resultKind or None,
        "resultAmount": body.resultAmount,
        "resultTransactionId": body.resultTransactionId or None,
        "carried": exactjson.dumps(
            {k: str(v) for k, v in body.carried.model_dump().items() if v is not None}
        ),
    }


def _set_payments(s, f: Filing, pays: list[Payment], user_id: str) -> None:
    for p in s.scalars(select(EstimatedPayment).where(EstimatedPayment.filingId == f.id)):
        if not p.deleted:
            p.mark_deleted(user_id)
    for p in pays:
        s.add(
            EstimatedPayment(
                id=ids.new_id("EstPy"),
                filingId=f.id,
                quarter=p.quarter,
                dueDate=p.dueDate,
                amount=p.amount,
                paidOn=p.paidOn,
                transactionId=p.transactionId or None,
            )
        )


@router.post("/tax-books/{book_id}/filings", response_model=BookDetail, status_code=201)
def add_filing(book_id: str, body: FilingIn, request: Request, c: Caller = Depends(caller)):
    with server(request).db.tx() as s:
        b, lvl = books.get(s, c.id, book_id, "write")
        f = Filing(id=ids.new_id("Filng"), bookId=b.id, **_filing_values(s, c, b, body))
        s.add(f)
        s.flush()
        _set_payments(s, f, body.payments, c.id)
        _amending(s, c, b, f)
        s.flush()
        return detail(s, c, b, lvl)


def _amending(s, c: Caller, b: TaxBook, f: Filing) -> None:
    """A filing made an amended federal return settles the edits made anyway before it
    (S8.15); one changed afterwards settles nothing more (CR3-35)."""
    if f.jurisdiction == "federal" and f.amendsId:
        closed.settle(s, b, c.id, "amended")


def _own_filing(s, c: Caller, filing_id: str) -> tuple[Filing, TaxBook, str]:
    f = s.get(Filing, filing_id)
    if f is None or f.deleted:
        raise Problem(404, "not-found", "Not found")
    b, lvl = books.get(s, c.id, f.bookId, "write")
    return f, b, lvl


# ---- Tax documents (S8.16) ----


class DocumentIn(Model):
    direction: str = "received"
    form: str
    issuer: str | None = None
    accountId: str | None = None
    filingId: str | None = None
    receiptId: str | None = None
    notes: str | None = None


def _doc_values(s, c: Caller, b: TaxBook, body: DocumentIn, had: str | None = None) -> dict:
    e: list[FieldError] = []
    if body.direction not in ("received", "filed"):
        e.append(FieldError("direction", "direction-invalid", "Received or filed."))
    if not body.form.strip():
        e.append(FieldError("form", "form-missing", "Which document."))
    if body.direction == "filed" and not body.filingId:
        e.append(FieldError("filingId", "filing-missing", "The filing it belongs to."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    if body.filingId:
        f = s.get(Filing, body.filingId)
        if f is None or f.deleted or f.bookId != b.id:
            raise refuse("filingId", "filing-unknown", "One of this book's filings.")
    if body.accountId:
        access.account(s, c.id, body.accountId)
    if body.receiptId and body.receiptId != had:
        receipts.to_attach(s, c.id, body.receiptId)
    return {
        "direction": body.direction,
        "form": body.form.strip(),
        "issuer": (body.issuer or "").strip() or None,
        "accountId": body.accountId or None,
        "filingId": body.filingId if body.direction == "filed" else None,
        "receiptId": body.receiptId or None,
        "notes": body.notes or None,
    }


@router.post("/tax-books/{book_id}/documents", response_model=BookDetail, status_code=201)
def add_document(book_id: str, body: DocumentIn, request: Request, c: Caller = Depends(caller)):
    with server(request).db.tx() as s:
        b, lvl = books.get(s, c.id, book_id, "write")
        s.add(TaxDocument(id=ids.new_id("TxDoc"), bookId=b.id, **_doc_values(s, c, b, body)))
        s.flush()
        return detail(s, c, b, lvl)


def _own_doc(s, c: Caller, doc_id: str) -> tuple[TaxDocument, TaxBook, str]:
    d = s.get(TaxDocument, doc_id)
    if d is None or d.deleted:
        raise Problem(404, "not-found", "Not found")
    b, lvl = books.get(s, c.id, d.bookId, "write")
    return d, b, lvl


class Forms(Model):
    received: list[str]
    filed: list[str]
    statuses: list[str]


@router.get("/tax-forms", response_model=Forms)
def forms(request: Request, c: Caller = Depends(caller)):
    return Forms(received=list(RECEIVED_FORMS), filed=list(FILED_FORMS), statuses=list(STATUSES))


# ---------- filings and their estimated payments in a dialog's draft (S12.15, S13.8.11) ----------


class FilingRecord(Model):
    """A filing as a draft saves it: its estimated payments are records of their own
    (`EstPy`), so each keeps its matched transaction."""

    bookId: IdOf("TaxBk")  # type: ignore[valid-type]
    jurisdiction: Literal["federal", "state", "local"] = "federal"
    place: str | None = None
    form: str = "Form 1040"
    amendsId: IdOf("Filng") | None = None  # type: ignore[valid-type]
    filingStatus: str | None = None
    preparedBy: str | None = None
    sentBy: str | None = None
    progress: str = "not started"
    dueDate: dt.date | None = None
    extensionFiledOn: dt.date | None = None
    extendedDue: dt.date | None = None
    filedOn: dt.date | None = None
    confirmation: str | None = None
    resultKind: str | None = None
    resultAmount: Money | None = None
    resultTransactionId: IdOf("Txn") | None = None  # type: ignore[valid-type]
    carried: Carried = Field(default_factory=Carried)


class PaymentRecord(Model):
    """An estimated tax payment of a filing (S8.15), matched to its transaction."""

    filingId: IdOf("Filng")  # type: ignore[valid-type]
    quarter: int
    dueDate: dt.date | None = None
    amount: Money
    paidOn: dt.date | None = None
    transactionId: IdOf("Txn") | None = None  # type: ignore[valid-type]


FILING_FIELDS = tuple(f for f in FilingRecord.model_fields if f not in ("bookId", "carried"))


def _filing_create(ctx, record_id: str, body: FilingRecord) -> None:
    s, c = ctx.s, ctx.caller
    b, _ = books.get(s, c.id, body.bookId, "write")
    f = Filing(id=record_id, bookId=b.id, **_filing_values(s, c, b, body))
    s.add(f)
    s.flush()
    _amending(s, c, b, f)


def _filing_editable(ctx, record_id: str) -> Filing:
    return _own_filing(ctx.s, ctx.caller, record_id)[0]


def _filing_current(ctx, f: Filing) -> dict:
    carried = {
        k: v for k, v in exactjson.loads(f.carried or "{}").items() if k in Carried.model_fields
    }
    return {"bookId": f.bookId, "carried": carried, **{k: getattr(f, k) for k in FILING_FIELDS}}


def _filing_update(ctx, f: Filing, body: FilingRecord) -> None:
    s, c = ctx.s, ctx.caller
    if body.bookId != f.bookId:
        raise refuse("bookId", "filing-fixed", "A filing stays in its book.")
    if body.amendsId == f.id:
        raise refuse("amendsId", "amends-itself", "A filing can't amend itself.")
    b, _ = books.get(s, c.id, f.bookId, "write")
    was = f.jurisdiction == "federal" and f.amendsId is not None
    for k, v in _filing_values(s, c, b, body).items():
        setattr(f, k, v)
    f.updatedAt = clock.now()
    if not was:
        _amending(s, c, b, f)


def _filing_delete(ctx, f: Filing) -> None:
    """Its estimated payments go with it (schema.md §4)."""
    f.mark_deleted(ctx.caller.id)


def _filing_read(ctx, record_id: str) -> FilingOut:
    s = ctx.s
    f = s.get(Filing, record_id)
    docs = list(s.scalars(select(TaxDocument).where(TaxDocument.bookId == f.bookId)))
    return _filing(s, f, [d for d in docs if not d.deleted], clock.today())


def _payment_values(ctx, body: PaymentRecord) -> dict:
    e: list[FieldError] = []
    if not 1 <= body.quarter <= 4:
        e.append(FieldError("quarter", "quarter-invalid", "1 to 4."))
    if body.amount < 0:
        e.append(FieldError("amount", "amount-invalid", "Zero or more."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    if body.transactionId:
        t = ctx.s.get(Transaction, body.transactionId)
        if t is None or t.deleted:
            raise refuse("transactionId", "not-found", "No such transaction.")
        access.account(ctx.s, ctx.caller.id, t.accountId)
    return body.model_dump(exclude={"filingId"})


def _payment_create(ctx, record_id: str, body: PaymentRecord) -> None:
    _own_filing(ctx.s, ctx.caller, body.filingId)
    ctx.s.add(EstimatedPayment(id=record_id, filingId=body.filingId, **_payment_values(ctx, body)))


def _payment_editable(ctx, record_id: str) -> EstimatedPayment:
    p = ctx.s.get(EstimatedPayment, record_id)
    if p is None or p.deleted:
        raise Problem(404, "not-found", "Not found")
    _own_filing(ctx.s, ctx.caller, p.filingId)
    return p


PAYMENT_FIELDS = ("quarter", "dueDate", "amount", "paidOn", "transactionId")


def _payment_update(ctx, p: EstimatedPayment, body: PaymentRecord) -> None:
    if body.filingId != p.filingId:
        raise refuse("filingId", "payment-fixed", "A payment stays with its filing.")
    for k, v in _payment_values(ctx, body).items():
        setattr(p, k, v)


def _payment_read(ctx, record_id: str) -> PaymentView:
    p = ctx.s.get(EstimatedPayment, record_id)
    return PaymentView(id=p.id, version=p.version, **{k: getattr(p, k) for k in PAYMENT_FIELDS})


save.register(
    save.Kind(
        prefix="Filng",
        entity=Filing,
        fields=FilingRecord,
        create=_filing_create,
        editable=_filing_editable,
        current=_filing_current,
        update=_filing_update,
        delete=_filing_delete,
        read=_filing_read,
    )
)
save.register(
    save.Kind(
        prefix="EstPy",
        entity=EstimatedPayment,
        fields=PaymentRecord,
        create=_payment_create,
        editable=_payment_editable,
        current=lambda ctx, p: {
            "filingId": p.filingId,
            **{k: getattr(p, k) for k in PAYMENT_FIELDS},
        },
        update=_payment_update,
        delete=lambda ctx, p: p.mark_deleted(ctx.caller.id),
        read=_payment_read,
    )
)


# ---------- a book, its dependents and documents in a dialog's draft (S12.15, S13.8.11) ----------


class BookRecord(Model):
    """A tax book as a draft saves it (S8.14): its year and filers are chosen when it is made;
    how it reads bitcoin network fees may change (S8.19)."""

    year: int
    filers: list[IdOf("User")] = Field(  # type: ignore[valid-type]
        default_factory=list, json_schema_extra={"uniqueItems": True}
    )
    fromLastYear: bool = True
    bitcoinFees: Literal["sale", "not-taxed"] = "sale"


class DependentRecord(DependentIn):
    """A dependent of a book (S8.14.5), with the accounts in their name it counts."""

    bookId: IdOf("TaxBk")  # type: ignore[valid-type]
    accountIds: list[str] = Field(default_factory=list, json_schema_extra={"uniqueItems": True})


class DocumentRecord(DocumentIn):
    """A tax document of a book (S8.16), received or filed, with its file."""

    bookId: IdOf("TaxBk")  # type: ignore[valid-type]


def _book_create(ctx, record_id: str, body: BookRecord) -> None:
    _, left = _make_book(ctx.s, ctx.caller, body, record_id)
    ctx.notes[record_id] = left


def _book_editable(ctx, record_id: str) -> TaxBook:
    return books.get(ctx.s, ctx.caller.id, record_id, "write")[0]


def _book_current(ctx, b: TaxBook) -> dict:
    filers = [
        f.userId for f in ctx.s.scalars(select(TaxBookFiler).where(TaxBookFiler.bookId == b.id))
    ]
    return {"year": b.year, "filers": filers, "fromLastYear": b.fromLastYear,
            "bitcoinFees": b.bitcoinFees}  # fmt: skip


def _book_update(ctx, b: TaxBook, body: BookRecord) -> None:
    """How the book reads bitcoin network fees on transfers between the owner's accounts
    (S8.19): a sale, the default, or not taxed, as a preparer may read them."""
    current = _book_current(ctx, b)
    for fixed in ("year", "filers", "fromLastYear"):
        if getattr(body, fixed) != current[fixed]:
            raise refuse(fixed, "book-fixed", "A book keeps its year and filers.")
    b.bitcoinFees = body.bitcoinFees
    b.updatedAt = clock.now()


def _book_delete(ctx, b: TaxBook) -> None:
    books.get(ctx.s, ctx.caller.id, b.id, "owner")
    b.mark_deleted(ctx.caller.id)


def _book_read(ctx, record_id: str) -> NewBookOut:
    b, lvl = books.get(ctx.s, ctx.caller.id, record_id)
    return NewBookOut(**_row(ctx.s, b, lvl).model_dump(),
                      dependentsLeftOut=ctx.notes.get(record_id, []))  # fmt: skip


def _dep_create(ctx, record_id: str, body: DependentRecord) -> None:
    s, c = ctx.s, ctx.caller
    b, _ = books.get(s, c.id, body.bookId, "write")
    d = TaxBookDependent(id=record_id, bookId=b.id, **_dependent_values(s, c, b, body, record_id))
    s.add(d)
    s.flush()
    dependents.set_accounts(s, d, list(body.accountIds), clock.now())


def _dep_editable(ctx, record_id: str) -> TaxBookDependent:
    return _own_dependent(ctx.s, ctx.caller, record_id)[0]


def _dep_current(ctx, d: TaxBookDependent) -> dict:
    return {"bookId": d.bookId, "personId": d.personId, "claimedAs": d.claimedAs,
            "months": d.months, "student": d.student,
            "accountIds": dependents.account_ids(ctx.s, d)}  # fmt: skip


def _dep_update(ctx, d: TaxBookDependent, body: DependentRecord) -> None:
    s, c = ctx.s, ctx.caller
    if body.bookId != d.bookId:
        raise refuse("bookId", "dependent-fixed", "A dependent stays in their book.")
    _, b, _ = _own_dependent(s, c, d.id)
    for k, v in _dependent_values(s, c, b, body, d.id).items():
        setattr(d, k, v)
    d.updatedAt = clock.now()
    dependents.set_accounts(s, d, list(body.accountIds), clock.now())


def _dep_read(ctx, record_id: str) -> DependentOut:
    d = ctx.s.get(TaxBookDependent, record_id)
    b, _ = books.get(ctx.s, ctx.caller.id, d.bookId)
    return next(_dependent(x) for x in dependents.listed(ctx.s, b) if x.row.id == record_id)


def _doc_create(ctx, record_id: str, body: DocumentRecord) -> None:
    s, c = ctx.s, ctx.caller
    b, _ = books.get(s, c.id, body.bookId, "write")
    s.add(TaxDocument(id=record_id, bookId=b.id, **_doc_values(s, c, b, body)))


def _doc_editable(ctx, record_id: str) -> TaxDocument:
    return _own_doc(ctx.s, ctx.caller, record_id)[0]


DOC_FIELDS = ("direction", "form", "issuer", "accountId", "filingId", "receiptId", "notes")


def _doc_update(ctx, d: TaxDocument, body: DocumentRecord) -> None:
    """Its form, issuer, account, notes and file; a file is checked as one to attach only
    when it is newly given, so a co-filer changes a document the other filer filed (CR3-36)."""
    s, c = ctx.s, ctx.caller
    if body.bookId != d.bookId:
        raise refuse("bookId", "document-fixed", "A document stays in its book.")
    _, b, _ = _own_doc(s, c, d.id)
    for k, v in _doc_values(s, c, b, body, d.receiptId).items():
        setattr(d, k, v)
    d.updatedAt = clock.now()


def _doc_read(ctx, record_id: str) -> DocumentOut:
    return _doc(ctx.s, ctx.s.get(TaxDocument, record_id))


save.register(
    save.Kind(
        prefix="TaxBk",
        entity=TaxBook,
        fields=BookRecord,
        create=_book_create,
        editable=_book_editable,
        current=_book_current,
        update=_book_update,
        delete=_book_delete,
        read=_book_read,
    )
)
save.register(
    save.Kind(
        prefix="TxDep",
        entity=TaxBookDependent,
        fields=DependentRecord,
        create=_dep_create,
        editable=_dep_editable,
        current=_dep_current,
        update=_dep_update,
        delete=lambda ctx, d: d.mark_deleted(ctx.caller.id),
        read=_dep_read,
    )
)
save.register(
    save.Kind(
        prefix="TxDoc",
        entity=TaxDocument,
        fields=DocumentRecord,
        create=_doc_create,
        editable=_doc_editable,
        current=lambda ctx, d: {"bookId": d.bookId, **{f: getattr(d, f) for f in DOC_FIELDS}},
        update=_doc_update,
        delete=lambda ctx, d: d.mark_deleted(ctx.caller.id),
        read=_doc_read,
    )
)
