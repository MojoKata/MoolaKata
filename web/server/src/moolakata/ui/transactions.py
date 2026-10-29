"""Transactions (requirements S2.6, S12.2.3): every visible account's transactions together,
filtered and paged; manual entry and edits; bulk categorise; splits, tags and transfers."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import and_, false, func, or_, select, type_coerce
from sqlalchemy.orm import Session

from .. import access, activity, clock, ids, reimbursements, washes
from ..errors import FieldError, Problem, refuse
from ..ledger import lots
from ..ledger import types as atypes
from ..store.entities.accounts import (
    Account,
    Category,
    Instrument,
    Lot,
    LotPick,
    Reconciliation,
    Split,
    Transaction,
    TransactionTag,
)
from ..store.repos import ledger as repo
from ..store.tables.accounts import TXN_KINDS
from ..store.types import Cents
from ..taxes import closed
from . import save
from .conventions import (
    ExactRoute,
    IdOf,
    Model,
    Money,
    Page,
    Paging,
    Quantity,
    if_match,
    stale,
)
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["transactions"])
INSTRUMENT_KINDS = (
    "buy",
    "sell",
    "reinvest",
    "transfer-in",
    "transfer-out",
    "split",
    "return-of-capital",
)
# Recorded through the option-trade endpoint (S3.2), which knows the contract, and the
# corporate-action one (S2.4), which makes their pairs.
OPTION_KINDS = (
    "symbol-change",
    "spin-off",
    "merger",
    "buy-to-open",
    "sell-to-open",
    "buy-to-close",
    "sell-to-close",
    "expire",
    "assign",
    "exercise",
)


class SplitIn(Model):
    categoryId: str | None = None
    amount: Money
    memo: str | None = None
    reimbursable: Money | None = None  # to be paid back (S2.9)
    owedBy: str | None = None


class SplitOut(SplitIn):
    id: str
    version: int


class PickIn(Model):
    lotId: str
    quantity: Quantity


class TxnOut(Model):
    id: str
    accountId: str
    accountName: str
    date: dt.date
    kind: str
    amount: Money
    payee: str | None
    payeeRaw: str | None
    memo: str | None
    categoryId: str | None
    instrumentId: str | None
    symbol: str | None
    quantity: Quantity | None
    price: Quantity | None
    fees: Money | None
    dividendType: str | None
    contributionYear: int | None
    contributionSource: str | None
    transferId: str | None
    transferAccountName: str | None
    imported: bool
    cleared: bool
    reconciled: bool
    amountWas: Money | None
    offChainAt: dt.datetime | None  # bitcoin no longer on the chain, to keep or delete (S1.6.2.7)
    reimbursable: Money | None  # to be paid back, and by whom (S2.9)
    owedBy: str | None
    paidBack: Money  # what paired deposits have paid back of it and its splits
    costBasis: Money | None = None  # a transfer-in's, as typed with it (S2.6)
    leftOutOf: list[str] | None = None  # the budgets it is left out of: on one read alone
    splits: list[SplitOut]
    tags: list[str]
    receipts: int
    level: str
    version: int


class TxnIn(Model):
    accountId: str
    date: dt.date
    kind: str = "withdrawal"
    amount: Money
    payee: str | None = None
    memo: str | None = None
    categoryId: str | None = None
    instrumentId: str | None = None
    symbol: str | None = None
    quantity: Quantity | None = None
    price: Quantity | None = None
    fees: Money | None = None
    dividendType: str | None = None
    splitRatio: Quantity | None = None
    contributionYear: int | None = None
    contributionSource: str | None = None
    costBasis: Money | None = None
    reimbursable: Money | None = None
    owedBy: str | None = None
    splits: list[SplitIn] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    picks: list[PickIn] = Field(default_factory=list)


class Categorise(Model):
    ids: list[str]
    categoryId: str | None


class TransferLink(Model):
    otherId: str | None


class CategoryOut(Model):
    id: str
    name: str
    kind: str
    parentId: str | None
    taxTag: str | None
    path: str
    keepReceiptsYears: int | None  # its own; none: its parent's, or for ever (S14.10.1.1)
    version: int


class NewCategory(Model):
    name: str
    kind: str
    parentId: str | None = None
    taxTag: str | None = None


class InstrumentOut(Model):
    id: str
    symbol: str
    name: str | None
    instrumentClass: str


class Done(Model):
    changed: int


# ---------- reading ----------


def _tags(s: Session, user_id: str, txn_ids: list[str]) -> dict[str, list[str]]:
    """A user's own tags on transactions (S10.4: annotations are the user's own)."""
    out: dict[str, list[str]] = {}
    if not txn_ids:
        return out
    for tag in s.scalars(
        select(TransactionTag)
        .where(
            TransactionTag.transactionId.in_(txn_ids),
            TransactionTag.userId == user_id,
            TransactionTag.deleted == false(),
        )
        .order_by(TransactionTag.tag)
    ):
        out.setdefault(tag.transactionId, []).append(tag.tag)
    return out


def shape(
    s: Session, user_id: str, rows: list[Transaction], levels: dict[str, str]
) -> list[TxnOut]:
    ids_ = [t.id for t in rows]
    accounts = {
        a.id: a
        for a in s.scalars(
            select(Account).where(
                Account.id.in_(
                    {t.accountId for t in rows}
                    | {
                        t2.accountId
                        for t2 in s.scalars(
                            select(Transaction).where(
                                Transaction.id.in_([t.transferId for t in rows if t.transferId])
                            )
                        )
                    }
                )
            )
        )
    }
    other_acct = {
        t.id: t.accountId
        for t in s.scalars(
            select(Transaction).where(
                Transaction.id.in_([t.transferId for t in rows if t.transferId])
            )
        )
    }
    insts = {
        i.id: i
        for i in s.scalars(
            select(Instrument).where(
                Instrument.id.in_({t.instrumentId for t in rows if t.instrumentId})
            )
        )
    }
    splits: dict[str, list[Split]] = {}
    if ids_:
        for sp in s.scalars(
            select(Split)
            .where(Split.transactionId.in_(ids_), Split.deleted == false())
            .order_by(Split.id)
        ):
            splits.setdefault(sp.transactionId, []).append(sp)
    tags = _tags(s, user_id, ids_)
    paid = reimbursements.paid_back(s, ids_)
    moved_in = [t.id for t in rows if t.kind == "transfer-in"]
    bases = {
        lot.transactionId: lot.costBasis
        for lot in s.scalars(select(Lot).where(Lot.transactionId.in_(moved_in)))
    }
    from .. import receipts as receipt_store

    attached = receipt_store.receipts_of(s, ids_)
    finished = {
        r.id
        for r in s.scalars(select(Reconciliation).where(Reconciliation.finishedAt.is_not(None)))
    }
    out = []
    for t in rows:
        other = accounts.get(other_acct.get(t.transferId, ""))
        out.append(
            TxnOut(
                id=t.id,
                accountId=t.accountId,
                accountName=accounts[t.accountId].name,
                date=t.date,
                kind=t.kind,
                amount=t.amount,
                payee=t.payee,
                payeeRaw=t.payeeRaw,
                memo=t.memo,
                categoryId=t.categoryId,
                instrumentId=t.instrumentId,
                symbol=insts[t.instrumentId].symbol if t.instrumentId else None,
                quantity=t.quantity,
                price=t.price,
                fees=t.fees,
                dividendType=t.dividendType,
                contributionYear=t.contributionYear,
                contributionSource=t.contributionSource,
                transferId=t.transferId,
                transferAccountName=other.name
                if other and access.account_level(s, user_id, other)
                else None,
                imported=t.importId is not None,
                cleared=t.cleared,
                reconciled=t.reconciliationId in finished,
                amountWas=t.amountWas,
                offChainAt=t.offChainAt,
                reimbursable=t.reimbursable,
                owedBy=t.owedBy,
                paidBack=paid.get(t.id, Decimal(0)),
                costBasis=bases.get(t.id),
                splits=[_split_read(x) for x in splits.get(t.id, [])],
                tags=tags.get(t.id, []),
                receipts=len(attached.get(t.id, [])),
                level=levels[t.accountId],
                version=t.version,
            )
        )
    return out


@router.get("/transactions", response_model=Page[TxnOut])
def list_transactions(
    request: Request,
    c: Caller = Depends(caller),
    paging: Paging = Depends(),
    account: list[str] = Query(default_factory=list),
    category: str | None = Query(None, description="a category id, or 'none'"),
    start: dt.date | None = Query(None, alias="from"),
    end: dt.date | None = Query(None, alias="to"),
    min_amount: str | None = Query(None, alias="min"),
    max_amount: str | None = Query(None, alias="max"),
    payee: str | None = None,
    tag: str | None = None,
    sort: str = Query("-date", pattern="^-?(date|amount|payee)$"),
):
    with server(request).db.read() as s:
        visible = {a.id: lvl for a, lvl in access.visible_accounts(s, c.id)}
        wanted = [a for a in account if a in visible] if account else list(visible)
        if account and not wanted:
            return paging.wrap([], 0)
        q = select(Transaction).where(
            Transaction.accountId.in_(wanted), Transaction.deleted == false()
        )
        if category == "none":
            q = q.where(
                Transaction.categoryId.is_(None),
                Transaction.transferId.is_(None),
                Transaction.instrumentId.is_(None),
                ~Transaction.id.in_(select(Split.transactionId).where(Split.deleted == false())),
            )
        elif category:
            q = q.where(
                or_(
                    Transaction.categoryId == category,
                    Transaction.id.in_(
                        select(Split.transactionId).where(
                            Split.categoryId == category, Split.deleted == false()
                        )
                    ),
                )
            )
        if start:
            q = q.where(Transaction.date >= start)
        if end:
            q = q.where(Transaction.date <= end)
        for value, op in ((min_amount, "ge"), (max_amount, "le")):
            if value:
                try:
                    dollars = Decimal(value)
                except Exception:
                    raise refuse(
                        "min" if op == "ge" else "max",
                        "amount-invalid",
                        "Enter an amount such as 25.00.",
                        400,
                    ) from None
                size = type_coerce(func.abs(Transaction.amount), Cents())
                q = q.where(size >= dollars if op == "ge" else size <= dollars)
        if payee:
            like = f"%{payee.strip().lower()}%"
            q = q.where(
                or_(
                    func.lower(Transaction.payee).like(like),
                    func.lower(Transaction.memo).like(like),
                )
            )
        if tag:
            q = q.where(
                Transaction.id.in_(
                    select(TransactionTag.transactionId).where(
                        TransactionTag.userId == c.id,
                        TransactionTag.tag == tag,
                        TransactionTag.deleted == false(),
                    )
                )
            )
        field = sort.lstrip("-")
        desc = sort.startswith("-")
        col = {"date": Transaction.date, "amount": Transaction.amount, "payee": Transaction.payee}[
            field
        ]
        order = [col.desc(), Transaction.id.desc()] if desc else [col.asc(), Transaction.id]
        rows, total = paging.query(s, q.order_by(*order))
        return paging.wrap(shape(s, c.id, rows, visible), total)


class Newer(Model):
    count: int


@router.get("/transactions/newer", response_model=Newer)
def newer_transactions(
    request: Request, c: Caller = Depends(caller), since: dt.datetime = Query(...)
):
    """How many transactions arrived after the page loaded: the +N new pill (S12.1.3)."""
    with server(request).db.read() as s:
        visible = [a.id for a, _ in access.visible_accounts(s, c.id)]
        n = s.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.accountId.in_(visible),
                Transaction.deleted == false(),
                Transaction.createdAt > since,
            )
        )
        return Newer(count=n or 0)


# ---------- writing ----------


def _check(s: Session, body, kind: str, investing: bool) -> list[FieldError]:
    errors = []
    if kind not in TXN_KINDS:
        errors.append(FieldError("kind", "kind-invalid", "Choose a kind of transaction."))
    elif kind in OPTION_KINDS[:3]:
        errors.append(
            FieldError("kind", "corporate-kind", "Record it as a corporate action on Positions.")
        )
    elif kind in OPTION_KINDS:
        errors.append(
            FieldError("kind", "option-kind", "Record an option trade from the account's Holdings.")
        )
    if kind in INSTRUMENT_KINDS and not investing:
        errors.append(
            FieldError("kind", "kind-not-for-account", "Trades belong in an investing account.")
        )
    if getattr(body, "categoryId", None):
        cat = s.get(Category, body.categoryId)
        if cat is None or cat.deleted:
            errors.append(FieldError("categoryId", "category-unknown", "Choose a category."))
    for i, sp in enumerate(getattr(body, "splits", None) or []):
        if sp.categoryId:
            cat = s.get(Category, sp.categoryId)
            if cat is None or cat.deleted:
                errors.append(
                    FieldError(f"splits.{i}.categoryId", "category-unknown", "Choose a category.")
                )
    if getattr(body, "splits", None) and body.amount is not None:
        total = sum((sp.amount for sp in body.splits), Decimal(0))
        if total != body.amount:
            errors.append(
                FieldError(
                    "splits",
                    "splits-unbalanced",
                    "The parts must add up to the transaction's amount.",
                )
            )
    errors += _check_reimbursable(body, "", body.amount)
    for i, sp in enumerate(getattr(body, "splits", None) or []):
        errors += _check_reimbursable(sp, f"splits.{i}.", sp.amount)
    if getattr(body, "payee", None) and len(body.payee) > 200:
        errors.append(FieldError("payee", "payee-too-long", "At most 200 characters."))
    if body.contributionSource and body.contributionSource not in (
        "employee",
        "employer",
        "rollover",
    ):
        errors.append(
            FieldError("contributionSource", "choice-invalid", "Employee, employer or rollover.")
        )
    if body.contributionYear is not None and not 1970 <= body.contributionYear <= 2100:
        errors.append(FieldError("contributionYear", "year-invalid", "Enter a year."))
    return errors


def _check_reimbursable(body, at: str, amount: Decimal | None) -> list[FieldError]:
    """Spending marked to be paid back: no more than was spent (S2.9)."""
    errors = []
    r = getattr(body, "reimbursable", None)
    if r is not None and (r <= 0 or amount is None or amount >= 0 or r > -amount):
        errors.append(
            FieldError(
                f"{at}reimbursable",
                "reimbursable-invalid",
                "Spending only, and no more than was spent.",
            )
        )
    owed = getattr(body, "owedBy", None)
    if owed is not None and len(owed) > 80:
        errors.append(FieldError(f"{at}owedBy", "owed-by-too-long", "At most 80 characters."))
    return errors


def _raise(errors: list[FieldError]) -> None:
    if errors:
        raise Problem(422, errors[0].code, errors[0].message, errors)


def _set_splits(s: Session, t: Transaction, splits: list[SplitIn], by: str) -> None:
    for old in s.scalars(
        select(Split).where(Split.transactionId == t.id, Split.deleted == false())
    ):
        old.mark_deleted(by)
    for sp in splits:
        s.add(
            Split(
                id=ids.new_id("Split"),
                transactionId=t.id,
                categoryId=sp.categoryId,
                amount=sp.amount,
                memo=sp.memo,
                reimbursable=sp.reimbursable,
                owedBy=(sp.owedBy or "").strip() or None,
            )
        )
    if splits:
        t.categoryId = None


def _set_tags(s: Session, t: Transaction, user_id: str, tags: list[str]) -> None:
    wanted = {x.strip().lower() for x in tags if x.strip()}
    if any(len(x) > 40 for x in wanted):
        raise refuse("tags", "tag-too-long", "Tags are at most 40 characters.")
    current = {
        x.tag: x
        for x in s.scalars(
            select(TransactionTag).where(
                TransactionTag.transactionId == t.id, TransactionTag.userId == user_id
            )
        )
    }
    now = clock.now()
    for tag in wanted:
        if tag in current:
            if current[tag].deleted:
                current[tag].restore()
        else:
            s.add(TransactionTag(transactionId=t.id, userId=user_id, tag=tag, createdAt=now))
    for tag, row in current.items():
        if tag not in wanted and not row.deleted:
            row.mark_deleted(user_id, now)


def _instrument(s: Session, body: TxnIn, account: Account) -> str | None:
    if body.instrumentId:
        inst = s.get(Instrument, body.instrumentId)
        if inst is None or inst.deleted:
            raise refuse("instrumentId", "instrument-unknown", "Choose an instrument.")
        return inst.id
    if body.symbol:
        symbol = body.symbol.strip().upper()
        if not symbol or len(symbol) > 32:
            raise refuse("symbol", "symbol-invalid", "Enter a symbol such as VTI.")
        # A coin typed in a crypto account is crypto, with the 8949 boxes of its own (S8.1).
        crypto = atypes.GROUPS.get(account.type) == "crypto"
        return repo.instrument(s, symbol, None, "crypto" if crypto else "equity").id
    return None


def _make(s: Session, c: Caller, body, txn_id: str, confirm: bool, ask=None):
    """A transaction made, with its lot, picks, splits and tags; the closed-year question
    (S2.8) refused unless confirmed, or asked through `ask` for a draft's save."""
    a, level = access.account(s, c.id, body.accountId, "write")
    investing = atypes.investing(a.type)
    _raise(_check(s, body, body.kind, investing))
    guard = closed.Guard(s, a, confirm, c.id, ask=ask) if investing else None
    inst_id = _instrument(s, body, a)
    if body.kind in ("buy", "sell", "reinvest", "transfer-in", "transfer-out") and (
        not inst_id or not body.quantity
    ):
        raise refuse(
            "symbol" if not inst_id else "quantity",
            "trade-incomplete",
            "A trade needs its instrument and quantity.",
        )
    t = Transaction(
        id=txn_id,
        accountId=a.id,
        date=body.date,
        kind=body.kind,
        amount=body.amount,
        payee=(body.payee or "").strip() or None,
        payeeRaw=(body.payee or "").strip() or None,
        memo=body.memo,
        categoryId=body.categoryId,
        instrumentId=inst_id,
        quantity=body.quantity,
        price=body.price,
        fees=body.fees,
        dividendType=body.dividendType,
        splitRatio=getattr(body, "splitRatio", None),
        lotMethod=a.lotMethod if body.kind in lots.DISPOSALS else None,
        contributionYear=body.contributionYear
        if body.contributionYear
        else (body.date.year if body.kind == "deposit" and atypes.retirement(a.type) else None),
        contributionSource=body.contributionSource,
        reimbursable=body.reimbursable,
        owedBy=(body.owedBy or "").strip() or None,
        cleared=bool(getattr(body, "cleared", False)),
        createdById=c.id,
    )
    s.add(t)
    s.flush()
    if inst_id and body.kind in ("buy", "reinvest", "transfer-in"):
        basis = body.costBasis if body.kind == "transfer-in" else -body.amount
        s.add(
            Lot(
                id=ids.new_id("Lot"),
                accountId=a.id,
                instrumentId=inst_id,
                transactionId=t.id,
                acquiredOn=body.date,
                quantity=body.quantity,
                costBasis=basis,
                basisMissing=basis is None,
            )
        )
    picks = getattr(body, "picks", None) or []
    if body.kind == "sell" and picks:
        t.lotMethod = "specific"
        for p in picks:
            lot = s.get(Lot, p.lotId)
            if lot is None or lot.accountId != a.id or lot.instrumentId != inst_id:
                raise refuse("picks", "lot-unknown", "Choose lots of this holding.")
            s.add(
                LotPick(
                    saleId=t.id,
                    lotId=lot.id,
                    quantity=p.quantity,
                    createdAt=clock.now(),
                )
            )
    _set_splits(s, t, getattr(body, "splits", None) or [], c.id)
    _set_tags(s, t, c.id, body.tags)
    repo.match_transfer(s, t, a.ownerId)
    s.flush()
    if t.kind == "split" and inst_id:
        # Its open options follow a whole-number split (S3.10.1).
        from ..options import adjust

        adjust.with_split(s, c.id, a, t)
        s.flush()
    if inst_id:
        washes.recompute(s, a.ownerId)
    if guard is not None:
        guard.check()
    return t, a, level


@router.post("/transactions", response_model=TxnOut, status_code=201)
def create_transaction(
    body: TxnIn, request: Request, c: Caller = Depends(caller), confirm: bool = False
):
    srv = server(request)
    key = request.headers.get("idempotency-key")
    again = srv.idempotency.lookup(c.id, key)
    if again:
        status, payload, headers = again
        return JSONResponse(payload, status_code=status, headers=headers)
    with srv.db.tx() as s:
        t, a, level = _make(s, c, body, ids.new_id("Txn"), confirm)
        out = shape(s, c.id, [t], {a.id: level})[0]
    payload = out.model_dump(mode="json")
    headers = {"Location": f"/ui/api/transactions/{t.id}"}
    srv.idempotency.remember(c.id, key, 201, payload, headers)
    return JSONResponse(payload, status_code=201, headers=headers)


def _editable(
    s: Session, c: Caller, txn_id: str, version: int, confirm: bool
) -> tuple[Transaction, Account, str]:
    t = s.get(Transaction, txn_id)
    if t is None or t.deleted:
        raise Problem(404, "not-found", "Not found")
    a, level = access.account(s, c.id, t.accountId, "write")
    if t.version != version:
        raise stale(shape(s, c.id, [t], {a.id: level})[0])
    if t.reconciliationId and not confirm:
        r = s.get(Reconciliation, t.reconciliationId)
        if r is not None and r.finishedAt is not None:
            raise Problem(
                409,
                "reconciled-period",
                "This transaction is in a reconciled period. Change it anyway?",
            )
    return t, a, level


@router.get("/transactions/{txn_id}", response_model=TxnOut)
def get_transaction(txn_id: str, request: Request, c: Caller = Depends(caller)):
    """One transaction the caller can see: where a new one's Location leads (S13.8.4)."""
    with server(request).db.read() as s:
        t = s.get(Transaction, txn_id)
        if t is None or t.deleted:
            raise Problem(404, "not-found", "Not found")
        return _read_one(s, c, t)


def _read_one(s: Session, c: Caller, t: Transaction) -> TxnOut:
    """A transaction as one read gives it, with the budgets it is left out of: what a dialog's
    draft starts from (S12.15.1)."""
    a, level = access.account(s, c.id, t.accountId)
    out = shape(s, c.id, [t], {a.id: level})[0]
    out.leftOutOf = _left_out_of(s, c, t)
    return out


# The fields a change sets on the transaction itself.
CHANGED = (
    "date",
    "kind",
    "amount",
    "payee",
    "memo",
    "categoryId",
    "quantity",
    "price",
    "fees",
    "dividendType",
    "contributionYear",
    "contributionSource",
    "cleared",
    "reimbursable",
    "owedBy",
)


def _change(s: Session, c: Caller, t: Transaction, a: Account, body, sent: set[str]) -> list[str]:
    """The fields `sent` set on a transaction, its lot following its trade; what changed."""
    kind = body.kind if "kind" in sent and body.kind else t.kind
    checked = body.model_copy(update={"amount": body.amount if "amount" in sent else t.amount})
    _raise(_check(s, checked, kind, atypes.investing(a.type)))
    changed = []
    for f in CHANGED:
        if f in sent:
            value = getattr(body, f)
            if f in ("date", "kind", "amount", "cleared") and value is None:
                continue
            if getattr(t, f) != value:
                setattr(t, f, value)
                changed.append(f)
    if "kind" in changed:
        # Made a sale: the account's method now is the one in force for it (S2.3).
        t.lotMethod = (t.lotMethod or a.lotMethod) if t.kind in lots.DISPOSALS else None
    if "amount" in changed or "date" in changed:
        repo.unlink_transfer(s, t)
        t.amountWas = None
    if "costBasis" in sent:
        for lot in s.scalars(select(Lot).where(Lot.transactionId == t.id)):
            if lot.costBasis != body.costBasis:
                lot.costBasis = body.costBasis
                lot.basisMissing = body.costBasis is None
                changed.append("costBasis")
    if t.kind in ("buy", "reinvest", "transfer-in") and {"quantity", "amount", "date"} & set(
        changed
    ):
        # The lot follows its trade; a transfer-in's basis is the one typed with it.
        for lot in s.scalars(select(Lot).where(Lot.transactionId == t.id)):
            lot.quantity, lot.acquiredOn = t.quantity, t.date
            if t.kind != "transfer-in":
                lot.costBasis = -t.amount
    if getattr(body, "splits", None) is not None and "splits" in sent:
        _set_splits(s, t, body.splits, c.id)
        changed.append("splits")
    if body.tags is not None and "tags" in sent:
        _set_tags(s, t, c.id, body.tags)
    return changed


def _changed(s: Session, c: Caller, a: Account, fields: list[str]) -> None:
    if fields and fields != ["cleared"]:
        activity.record(
            s,
            "transaction.updated",
            actor=c.id,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
            detail={"fields": fields, "count": 1},
        )


def _remove(s: Session, c: Caller, t: Transaction, a: Account) -> None:
    """A transaction deleted, with what goes with it: an assignment's stock trades, a split's
    or a corporate action's adjustments undone."""
    if t.kind in ("split", "option-adjust"):
        from ..options import adjust

        adjust.undo(s, c.id, t)
    if t.kind in ("symbol-change", "spin-off", "merger"):
        from .. import corporate

        corporate.undo(s, c.id, t)
    end = s.get(Transaction, t.optionTransactionId) if t.optionTransactionId else None
    if end is not None and end.kind in ("assign", "exercise") and not end.deleted:
        raise refuse(
            None,
            "made-by-an-assignment",
            f"This trade came with the {'assignment' if end.kind == 'assign' else 'exercise'}"
            f" of {end.payee or 'an option'}: delete that, and this goes with it.",
        )
    if t.kind in ("assign", "exercise"):
        # Its stock trades and the deliverable's cash go with it (S3.4); the dialog asks.
        for leg in s.scalars(
            select(Transaction).where(
                Transaction.optionTransactionId == t.id, Transaction.deleted == false()
            )
        ):
            repo.unlink_transfer(s, leg)
            leg.mark_deleted(c.id)
    repo.unlink_transfer(s, t)
    t.mark_deleted(c.id)
    if t.instrumentId:
        s.flush()
        washes.recompute(s, a.ownerId)
    activity.record(
        s,
        "transaction.deleted",
        actor=c.id,
        subject_kind="account",
        subject_id=a.id,
        owner=a.ownerId,
        detail={"count": 1},
    )


@router.post("/transactions/categorise", response_model=Done)
def categorise(body: Categorise, request: Request, c: Caller = Depends(caller)):
    """Bulk categorise (S12.2.3): Activity says how many, never which amounts."""
    if len(body.ids) > 1000:
        raise refuse("ids", "too-many", "At most 1,000 at a time.")
    with server(request).db.tx() as s:
        if body.categoryId:
            cat = s.get(Category, body.categoryId)
            if cat is None or cat.deleted:
                raise refuse("categoryId", "category-unknown", "Choose a category.")
        per_account: dict[str, int] = {}
        for t in s.scalars(
            select(Transaction).where(Transaction.id.in_(body.ids), Transaction.deleted == false())
        ):
            a, _ = access.account(s, c.id, t.accountId, "write")
            if t.categoryId != body.categoryId:
                t.categoryId = body.categoryId
                per_account[a.id] = per_account.get(a.id, 0) + 1
        for aid, n in per_account.items():
            a = s.get(Account, aid)
            activity.record(
                s,
                "transaction.categorised",
                actor=c.id,
                subject_kind="account",
                subject_id=aid,
                owner=a.ownerId,
                detail={"fields": ["category"], "count": n},
            )
        return Done(changed=sum(per_account.values()))


@router.post("/transactions/{txn_id}/transfer", response_model=TxnOut)
def link_transfer(txn_id: str, body: TransferLink, request: Request, c: Caller = Depends(caller)):
    """Match a transfer by hand, or undo a match (S1.7)."""
    with server(request).db.tx() as s:
        t = s.get(Transaction, txn_id)
        if t is None or t.deleted:
            raise Problem(404, "not-found", "Not found")
        a, level = access.account(s, c.id, t.accountId, "write")
        repo.unlink_transfer(s, t)
        if body.otherId:
            o = s.get(Transaction, body.otherId)
            if o is None or o.deleted:
                raise refuse("otherId", "not-found", "Choose a transaction.")
            access.account(s, c.id, o.accountId, "write")
            if o.accountId == t.accountId or o.amount != -t.amount:
                raise refuse(
                    "otherId",
                    "not-a-transfer",
                    "The other half is the same amount the other way, in another account.",
                )
            repo.unlink_transfer(s, o)
            t.transferId, o.transferId = o.id, t.id
        s.flush()
        return shape(s, c.id, [t], {a.id: level})[0]


@router.post("/transactions/{txn_id}/both-real", response_model=TxnOut)
def both_real(txn_id: str, request: Request, c: Caller = Depends(caller)):
    """Two identical rows on one day, or two a file gave one id: the answer *both real* is
    kept (S1.11.5)."""
    with server(request).db.tx() as s:
        t = s.get(Transaction, txn_id)
        if t is None or t.deleted:
            raise Problem(404, "not-found", "Not found")
        a, level = access.account(s, c.id, t.accountId, "write")
        base = (t.fitId or "").rpartition("#")[0] or t.fitId
        same = and_(Transaction.date == t.date, Transaction.amount == t.amount)
        if base:
            same = or_(same, Transaction.fitId == base, Transaction.fitId.like(f"{base}#%"))
        for twin in s.scalars(
            select(Transaction).where(
                Transaction.accountId == t.accountId, same, Transaction.deleted == false()
            )
        ):
            twin.duplicateAnswer = "both-real"
        s.flush()
        return shape(s, c.id, [t], {a.id: level})[0]


# ---------- categories and instruments ----------


def _paths(cats: list[Category]) -> dict[str, str]:
    by = {x.id: x for x in cats}
    return {x.id: f"{by[x.parentId].name} › {x.name}" if x.parentId in by else x.name for x in cats}


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(request: Request, c: Caller = Depends(caller)):
    with server(request).db.read() as s:
        cats = s.scalars(select(Category).where(Category.deleted == false())).all()
        paths = _paths(list(cats))
        return sorted(
            (
                CategoryOut(
                    id=x.id,
                    name=x.name,
                    kind=x.kind,
                    parentId=x.parentId,
                    taxTag=x.taxTag,
                    path=paths[x.id],
                    keepReceiptsYears=x.keepReceiptsYears,
                    version=x.version,
                )
                for x in cats
            ),
            key=lambda x: x.path.lower(),
        )


def _category_out(s, cat: Category) -> CategoryOut:
    paths = _paths(list(s.scalars(select(Category).where(Category.deleted == false()))))
    return CategoryOut(
        id=cat.id,
        name=cat.name,
        kind=cat.kind,
        parentId=cat.parentId,
        taxTag=cat.taxTag,
        path=paths[cat.id],
        keepReceiptsYears=cat.keepReceiptsYears,
        version=cat.version,
    )


def _make_category(s, c: Caller, body: NewCategory, cat_id: str) -> Category:
    name = body.name.strip()
    if not name or len(name) > 60 or "›" in name:
        raise refuse("name", "name-invalid", "Enter a name of up to 60 characters.")
    if body.kind not in ("expense", "income", "savings", "transfer"):
        raise refuse("kind", "kind-invalid", "Expense, income, savings or transfer.")
    if body.parentId:
        parent = s.get(Category, body.parentId)
        if parent is None or parent.deleted or parent.parentId:
            raise refuse(
                "parentId",
                "parent-invalid",
                "Categories have two levels: choose a top-level one.",
            )
    same = s.scalars(
        select(Category).where(
            Category.deleted == false(),
            func.lower(Category.name) == name.lower(),
            Category.parentId.is_(body.parentId)
            if body.parentId is None
            else Category.parentId == body.parentId,
        )
    ).first()
    if same:
        raise refuse("name", "name-taken", "There is already a category with this name.")
    cat = Category(
        id=cat_id,
        name=name,
        kind=body.kind,
        parentId=body.parentId,
        taxTag=body.taxTag,
        createdById=c.id,
    )
    s.add(cat)
    s.flush()
    return cat


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(body: NewCategory, request: Request, c: Caller = Depends(caller)):
    with server(request).db.tx() as s:
        out = _category_out(s, _make_category(s, c, body, ids.new_id("Cat")))
    return JSONResponse(out.model_dump(mode="json"), status_code=201)


class CategoryRecord(NewCategory):
    """A category as a draft saves it (S2.5): made with its name, kind and parent; afterwards
    only how long receipts in it are kept, an admin's, since it decides what file pruning may
    remove (S14.10.1.1)."""

    keepReceiptsYears: int | None = None


def _category_create(ctx, record_id: str, body: CategoryRecord) -> None:
    cat = _make_category(ctx.s, ctx.caller, body, record_id)
    if body.keepReceiptsYears is not None:
        _category_update(ctx, cat, body)


def _category_editable(ctx, record_id: str) -> Category:
    cat = ctx.s.get(Category, record_id)
    if cat is None or cat.deleted:
        raise Problem(404, "not-found", "Not found")
    return cat


def _category_current(ctx, cat: Category) -> dict:
    return {f: getattr(cat, f) for f in CategoryRecord.model_fields}


def _category_update(ctx, cat: Category, body: CategoryRecord) -> None:
    fixed = [f for f in NewCategory.model_fields if getattr(body, f) != getattr(cat, f)]
    if fixed:
        raise refuse(fixed[0], "category-fixed", "Only how long its receipts are kept changes.")
    years = body.keepReceiptsYears
    if years == cat.keepReceiptsYears:
        return
    if not ctx.caller.admin:
        raise refuse("keepReceiptsYears", "admins-only", "Only admins can do this.", 403)
    if years is not None and not 1 <= years <= 100:
        raise refuse("keepReceiptsYears", "years-invalid", "A whole number of years from 1.")
    cat.keepReceiptsYears = years
    cat.updatedAt = clock.now()


def _category_delete(ctx, cat: Category) -> None:
    raise refuse(None, "category-kept", "A category stays: transactions and plans name it.")


save.register(
    save.Kind(
        prefix="Cat",
        entity=Category,
        fields=CategoryRecord,
        create=_category_create,
        editable=_category_editable,
        current=_category_current,
        update=_category_update,
        delete=_category_delete,
        read=lambda ctx, record_id: _category_out(ctx.s, ctx.s.get(Category, record_id)),
    )
)


@router.get("/instruments", response_model=list[InstrumentOut])
def search_instruments(
    request: Request, c: Caller = Depends(caller), q: str = Query(..., min_length=1, max_length=40)
):
    with server(request).db.read() as s:
        return [
            InstrumentOut(id=i.id, symbol=i.symbol, name=i.name, instrumentClass=i.instrumentClass)
            for i in repo.search_instruments(s, q)
        ]


@router.post("/transactions/{txn_id}/keep", response_model=TxnOut)
def keep_off_chain(
    txn_id: str, request: Request, c: Caller = Depends(caller), version: int = Depends(if_match)
):
    """Keep a bitcoin transaction the explorer or node no longer has: its mark is cleared
    (S1.6.2.7). Deleting it is the usual delete."""
    with server(request).db.tx() as s:
        t, a, level = _editable(s, c, txn_id, version, True)
        if t.offChainAt is None:
            raise refuse(None, "on-chain", "It is still on the chain.")
        t.offChainAt, t.offChainMissedAt, t.offChainKeptAt = None, None, clock.now()
        s.flush()
        return shape(s, c.id, [t], {a.id: level})[0]


# ---------- transactions and their splits in a dialog's draft (S12.15, S13.8.11) ----------


def _set_of():
    """A set held by the record, sent as what to add and take away (S13.8.11.1)."""
    return Field(default_factory=list, json_schema_extra={"uniqueItems": True})


class TxnRecord(Model):
    """A transaction as a draft saves it: its splits are records of their own (`Split`), so
    each keeps its id, and with it what pays it back (S2.9). `symbol` names a new trade's
    instrument; `leftOutOf` lists the budgets it is left out of (S7.3.5)."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]
    date: dt.date
    kind: str = "withdrawal"
    amount: Money
    payee: str | None = None
    memo: str | None = None
    categoryId: IdOf("Cat") | None = None  # type: ignore[valid-type]
    symbol: str | None = None
    instrumentId: IdOf("Instr") | None = None  # type: ignore[valid-type]
    quantity: Quantity | None = None
    price: Quantity | None = None
    fees: Money | None = None
    dividendType: str | None = None
    contributionYear: int | None = None
    contributionSource: str | None = None
    costBasis: Money | None = None
    reimbursable: Money | None = None
    owedBy: str | None = None
    cleared: bool = False
    tags: list[str] = _set_of()
    leftOutOf: list[IdOf("Bdgt")] = _set_of()  # type: ignore[valid-type]


class SplitRecord(Model):
    """A part of a transaction's amount with its own category (S2.6), as a draft saves it."""

    transactionId: IdOf("Txn")  # type: ignore[valid-type]
    categoryId: IdOf("Cat") | None = None  # type: ignore[valid-type]
    amount: Money
    memo: str | None = None
    reimbursable: Money | None = None  # to be paid back (S2.9)
    owedBy: str | None = None


def _left_out_of(s: Session, c: Caller, t: Transaction) -> list[str]:
    """The budgets the caller sees that leave the transaction out."""
    from ..store.entities.budgets import BudgetLeaveOut

    seen = {b.id for b, _ in access.visible_budgets(s, c.id)}
    return sorted(
        x.budgetId
        for x in s.scalars(
            select(BudgetLeaveOut).where(
                BudgetLeaveOut.transactionId == t.id, BudgetLeaveOut.deleted == false()
            )
        )
        if x.budgetId in seen
    )


def _set_left_out(s: Session, c: Caller, t: Transaction, was: list[str], now: list[str]):
    """Leave the transaction out of budgets, or count it again: each a budget the caller
    writes that counts its account (S7.3.5)."""
    from .. import budgets
    from ..store.entities.budgets import BudgetLeaveOut

    errors = []
    for budget_id in sorted(set(was) ^ set(now)):
        out = budget_id in now
        try:
            b, _ = access.budget(s, c.id, budget_id, "write")
        except Problem:
            errors.append(FieldError("leftOutOf", "budget-unknown", "Not a budget you can change."))
            continue
        if t.accountId not in budgets.account_ids(s, b, c.id):
            errors.append(FieldError("leftOutOf", "not-in-budget", f"{b.name} doesn't count it."))
            continue
        row = s.get(BudgetLeaveOut, (b.id, t.id))
        if out and row is None:
            s.add(BudgetLeaveOut(budgetId=b.id, transactionId=t.id, createdAt=clock.now()))
        elif out and row.deleted:
            row.restore()
        elif not out and row is not None and not row.deleted:
            row.mark_deleted(c.id)
        activity.record(
            s,
            "budget.left-out" if out else "budget.counted-again",
            actor=c.id,
            subject_kind="budget",
            subject_id=b.id,
            owner=b.ownerId,
        )
    _raise(errors)


def _reconciled(ctx, t: Transaction) -> None:
    """A transaction in a reconciled period changes only once that is confirmed (S2.7)."""
    r = ctx.s.get(Reconciliation, t.reconciliationId) if t.reconciliationId else None
    if r is not None and r.finishedAt is not None:
        a = ctx.s.get(Account, t.accountId)
        when = f"{r.statementDate:%b} {r.statementDate.day}, {r.statementDate.year}"
        ctx.ask(
            "reconciled-period",
            f"It is in a reconciled period of {a.name} (statement of {when}).",
        )


def _parts_add_up(ctx, t: Transaction) -> None:
    """Once every op is in: a split transaction's parts add up to it, and it has no category
    of its own (S2.6)."""

    def check() -> None:
        if t.deleted:
            return
        parts = list(
            ctx.s.scalars(
                select(Split).where(Split.transactionId == t.id, Split.deleted == false())
            )
        )
        if not parts:
            return
        if sum((x.amount for x in parts), Decimal(0)) != t.amount:
            raise refuse(
                "splits", "splits-unbalanced", "The parts must add up to the transaction's amount."
            )
        t.categoryId = None

    ctx.verify(f"splits:{t.id}", check)


def _txn_create(ctx, record_id: str, body: TxnRecord) -> None:
    t, _, _ = _make(ctx.s, ctx.caller, body, record_id, False, ask=ctx.ask)
    if body.leftOutOf:
        _set_left_out(ctx.s, ctx.caller, t, [], body.leftOutOf)
    _parts_add_up(ctx, t)


def _txn_editable(ctx, record_id: str) -> Transaction:
    """Read for a change: one who only sees the account may still leave it out of a budget
    they write; anything else needs the account's write (checked by the update)."""
    t = ctx.s.get(Transaction, record_id)
    if t is None or t.deleted:
        raise Problem(404, "not-found", "Not found")
    access.account(ctx.s, ctx.caller.id, t.accountId)
    return t


def _txn_current(ctx, t: Transaction) -> dict:
    lot = ctx.s.scalars(select(Lot).where(Lot.transactionId == t.id)).first()
    inst = ctx.s.get(Instrument, t.instrumentId) if t.instrumentId else None
    return {
        "accountId": t.accountId,
        "symbol": inst.symbol if inst else None,
        "instrumentId": t.instrumentId,
        "costBasis": lot.costBasis if lot is not None and t.kind == "transfer-in" else None,
        "tags": _tags(ctx.s, ctx.caller.id, [t.id]).get(t.id, []),
        "leftOutOf": _left_out_of(ctx.s, ctx.caller, t),
        **{f: getattr(t, f) for f in CHANGED},
    }


def _txn_update(ctx, t: Transaction, body: TxnRecord) -> None:
    current = _txn_current(ctx, t)
    sent = {f for f in TxnRecord.model_fields if getattr(body, f) != current.get(f)}
    for fixed in ("accountId", "symbol", "instrumentId"):
        if fixed in sent:
            raise refuse(fixed, "transaction-fixed", "A transaction keeps its account and holding.")
    if sent - {"leftOutOf"}:
        a, _ = access.account(ctx.s, ctx.caller.id, t.accountId, "write")
        _reconciled(ctx, t)
        guard = closed.Guard(ctx.s, a, False, ctx.caller.id, ask=ctx.ask)
        changed = _change(ctx.s, ctx.caller, t, a, body, sent)
        _changed(ctx.s, ctx.caller, a, changed)
        ctx.s.flush()
        if t.instrumentId:
            washes.recompute(ctx.s, a.ownerId)
        guard.check()
    if "leftOutOf" in sent:
        _set_left_out(ctx.s, ctx.caller, t, current["leftOutOf"], body.leftOutOf)
    _parts_add_up(ctx, t)


def _txn_delete(ctx, t: Transaction) -> None:
    a, _ = access.account(ctx.s, ctx.caller.id, t.accountId, "write")
    _reconciled(ctx, t)
    guard = closed.Guard(ctx.s, a, False, ctx.caller.id, ask=ctx.ask)
    _remove(ctx.s, ctx.caller, t, a)
    guard.check()


def _split_txn(ctx, txn_id: str) -> tuple[Transaction, Account]:
    """The split's transaction, written by the caller and not a trade."""
    t = ctx.s.get(Transaction, txn_id)
    if t is None or t.deleted:
        raise refuse("transactionId", "transaction-unknown", "No such transaction.")
    a, _ = access.account(ctx.s, ctx.caller.id, t.accountId, "write")
    if t.instrumentId:
        raise refuse("transactionId", "split-trade", "A trade isn't split across categories.")
    return t, a


def _split_checked(ctx, body: SplitRecord) -> tuple[Transaction, Account]:
    t, a = _split_txn(ctx, body.transactionId)
    errors = _check_reimbursable(body, "", body.amount)
    if body.categoryId:
        cat = ctx.s.get(Category, body.categoryId)
        if cat is None or cat.deleted:
            errors.append(FieldError("categoryId", "category-unknown", "Choose a category."))
    _raise(errors)
    return t, a


def _split_values(body: SplitRecord) -> dict:
    return {
        "categoryId": body.categoryId,
        "amount": body.amount,
        "memo": body.memo,
        "reimbursable": body.reimbursable,
        "owedBy": (body.owedBy or "").strip() or None,
    }


def _split_create(ctx, record_id: str, body: SplitRecord) -> None:
    t, _ = _split_checked(ctx, body)
    _reconciled(ctx, t)
    ctx.s.add(Split(id=record_id, transactionId=t.id, **_split_values(body)))
    _parts_add_up(ctx, t)


def _split_editable(ctx, record_id: str) -> Split:
    sp = ctx.s.get(Split, record_id)
    if sp is None or sp.deleted:
        raise Problem(404, "not-found", "Not found")
    _split_txn(ctx, sp.transactionId)
    return sp


SPLIT_FIELDS = ("categoryId", "amount", "memo", "reimbursable", "owedBy")


def _split_current(ctx, sp: Split) -> dict:
    return {"transactionId": sp.transactionId, **{f: getattr(sp, f) for f in SPLIT_FIELDS}}


def _split_update(ctx, sp: Split, body: SplitRecord) -> None:
    """In place, so what pays the part back stays paired with it (S2.9, CR3-29)."""
    if body.transactionId != sp.transactionId:
        raise refuse("transactionId", "split-fixed", "A part stays with its transaction.")
    t, _ = _split_checked(ctx, body)
    _reconciled(ctx, t)
    for f, v in _split_values(body).items():
        setattr(sp, f, v)
    _parts_add_up(ctx, t)


def _split_read(sp: Split) -> SplitOut:
    return SplitOut(id=sp.id, version=sp.version, **{f: getattr(sp, f) for f in SPLIT_FIELDS})


def _split_delete(ctx, sp: Split) -> None:
    """Its pairings go with it (schema.md §4)."""
    t, _ = _split_txn(ctx, sp.transactionId)
    sp.mark_deleted(ctx.caller.id)
    _parts_add_up(ctx, t)


save.register(
    save.Kind(
        prefix="Txn",
        entity=Transaction,
        fields=TxnRecord,
        create=_txn_create,
        editable=_txn_editable,
        current=_txn_current,
        update=_txn_update,
        delete=_txn_delete,
        read=lambda ctx, record_id: _read_one(ctx.s, ctx.caller, ctx.s.get(Transaction, record_id)),
    )
)
save.register(
    save.Kind(
        prefix="Split",
        entity=Split,
        fields=SplitRecord,
        create=_split_create,
        editable=_split_editable,
        current=_split_current,
        update=_split_update,
        delete=_split_delete,
        read=lambda ctx, record_id: _split_read(ctx.s.get(Split, record_id)),
    )
)
