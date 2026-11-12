"""Transactions (requirements S2.6, S12.2.3): every visible account's transactions together,
filtered and paged; manual entry and edits; bulk categorise; splits, tags and transfers."""

import datetime as dt
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import and_, false, func, or_, select, type_coerce
from sqlalchemy.orm import Session

from .. import access, activity, clock, ids, reimbursements, tags, washes
from ..access import Perms
from ..errors import FieldError, Problem, refuse
from ..ledger import lots
from ..ledger import types as atypes
from ..store.entities.accounts import (
    Account,
    Category,
    CorporateAction,
    Instrument,
    Lot,
    LotPick,
    Reconciliation,
    Split,
    Tag,
    Transaction,
    TransactionTag,
)
from ..store.repos import ledger as repo
from ..store.tables.accounts import TXN_KINDS
from ..store.types import Cents
from ..taxes import closed
from . import save
from .conventions import (
    Access,
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
    "reward",  # coins received as income, at the day's price (S8.5)
)
# Made only with what they need: an option trade with its contract (S3.2, a create that names
# it), an option's end by settling it, and a corporate action's pairs from the action (S2.4).
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
    deductible: bool | None = None  # a traditional IRA contribution's part (S8.6)


class SplitOut(SplitIn):
    id: str
    version: int


class PickOut(Model):
    """How much of a lot a sale takes, picked (S2.3)."""

    id: str
    lotId: str
    quantity: Quantity
    version: int


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
    # A traditional IRA contribution's (S8.6): a nullable boolean, null until decided.
    deductible: bool | None = None
    paidBack: Money  # what paired deposits have paid back of it and its splits
    costBasis: Money | None = None  # a transfer-in's, as typed with it (S2.6)
    transferLots: list[TransferLot] | None = None  # a transfer-in's, lot by lot (S2.2)
    leftOutOf: list[str] | None = None  # the budgets it is left out of: on one read alone
    splits: list[SplitOut]
    picks: list[PickOut] = Field(default_factory=list)  # a sale's lots, picked (S2.3)
    tags: list[str]  # the reader's own, by name
    tagIds: list[str]
    receipts: int
    access: Access
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


class Categorise(Model):
    ids: list[str]
    categoryId: str | None


class InstrumentOut(Model):
    id: str
    symbol: str
    name: str | None
    instrumentClass: str


class Done(Model):
    changed: int


# ---------- reading ----------


# Where money into a retirement account came from (S8.6), when it isn't told by its transfer.
SOURCES = ("employee", "employer", "rollover", "conversion")


def _tags(s: Session, user_id: str, txn_ids: list[str]) -> dict[str, list]:
    """A user's own tags on transactions (S10.4: annotations are the user's own)."""
    return tags.of(s, "transaction", user_id, txn_ids)


def shape(
    s: Session, user_id: str, rows: list[Transaction], held: dict[str, Perms]
) -> list[TxnOut]:
    """Transactions as the API answers them; `held` is what the reader holds of each one's
    account, from which each transaction's own access follows (a child's, schema.md §7)."""
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
    picked: dict[str, list[LotPick]] = {}
    sales = [t.id for t in rows if t.kind == "sell"]
    if sales:
        for p in s.scalars(
            select(LotPick)
            .where(LotPick.saleId.in_(sales), LotPick.deleted == false())
            .order_by(LotPick.id)
        ):
            picked.setdefault(p.saleId, []).append(p)
    tagged = _tags(s, user_id, ids_)
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
        # The other half is named only to someone who reads its account (decision 1c.4 of
        # the access-views walk): neither its id nor its account's name, else.
        if other is not None and access.perms(s, Account, other.id, user_id) is None:
            other = None
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
                transferId=t.transferId if other is not None else None,
                transferAccountName=other.name if other is not None else None,
                imported=t.importId is not None,
                cleared=t.cleared,
                reconciled=t.reconciliationId in finished,
                amountWas=t.amountWas,
                offChainAt=t.offChainAt,
                reimbursable=t.reimbursable,
                owedBy=t.owedBy,
                deductible=t.deductible,
                paidBack=paid.get(t.id, Decimal(0)),
                costBasis=bases.get(t.id),
                splits=[_split_read(x) for x in splits.get(t.id, [])],
                picks=[_pick_read(x) for x in picked.get(t.id, [])],
                tags=[x.name for x in tagged.get(t.id, [])],
                tagIds=[x.id for x in tagged.get(t.id, [])],
                receipts=len(attached.get(t.id, [])),
                access=Access.of(held[t.accountId].child()),
                version=t.version,
            )
        )
    return out


def _size_bounds(least: str | None, most: str | None) -> tuple[Decimal | None, Decimal | None]:
    """A filter's At least and At most (S12.2.3.1): each a size, zero or more, any while
    blank; At most under At least is refused, never read as no rows."""
    out: list[Decimal | None] = []
    for name, value in (("min", least), ("max", most)):
        text = (value or "").strip()
        if not text:
            out.append(None)
            continue
        try:
            d = Decimal(text)
        except InvalidOperation:
            d = None
        if d is None or not d.is_finite():
            raise refuse(name, "amount-invalid", "Enter an amount such as 25.00.", 400)
        if d < 0:
            raise refuse(name, "amount-invalid", "Zero or more.", 400)
        out.append(d)
    lo, hi = out
    if lo is not None and hi is not None and hi < lo:
        raise refuse("max", "range-invalid", "Below At least.", 400)
    return lo, hi


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
    with server(request).db.read(user=c.id) as s:
        visible = {a.id: p for a, p in access.accounts(s, c.id)}
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
        least, most = _size_bounds(min_amount, max_amount)
        size = type_coerce(func.abs(Transaction.amount), Cents())
        if least is not None:
            q = q.where(size >= least)
        if most is not None:
            q = q.where(size <= most)
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
                    select(TransactionTag.transactionId)
                    .join(Tag, Tag.id == TransactionTag.tagId)
                    .where(
                        Tag.ownerId == c.id,
                        Tag.name == tag.strip().lower(),
                        Tag.deleted == false(),
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
    with server(request).db.read(user=c.id) as s:
        visible = [a.id for a, _ in access.accounts(s, c.id)]
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


def _check(
    s: Session, body, kind: str, investing: bool, fees_sent: bool = True
) -> list[FieldError]:
    """What's wrong with a transaction made or changed; `fees_sent` when its fees or kind are
    typed (a change that leaves them keeps a trade imported without fees as it is)."""
    errors = []
    if kind not in TXN_KINDS:
        errors.append(FieldError("kind", "kind-invalid", "Choose a kind of transaction."))
    elif kind == "adjustment" and not (getattr(body, "memo", None) or "").strip():
        # A difference accepted as an adjustment says why (S1.11.4).
        errors.append(FieldError("memo", "note-required", "Say why the balance is adjusted."))
    elif kind in OPTION_KINDS[:3]:
        errors.append(
            FieldError("kind", "corporate-kind", "Record it as a corporate action on Positions.")
        )
    elif kind in OPTION_KINDS:
        errors.append(
            FieldError("kind", "option-kind", "Record an option trade from the account's Holdings.")
        )
    if (kind in INSTRUMENT_KINDS or kind == "foreign-tax") and not investing:
        errors.append(
            FieldError("kind", "kind-not-for-account", "Trades belong in an investing account.")
        )
    if kind == "foreign-tax" and getattr(body, "amount", None) is not None and body.amount > 0:
        errors.append(
            FieldError("amount", "amount-sign", "Foreign tax paid is money out: a negative amount.")
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
    # A trade's fees are typed with it, 0 for none: a blank is refused (R3.11, CR3-437).
    fees = getattr(body, "fees", None)
    if (fees_sent and kind in lots.FEE_KINDS and fees is None) or (fees is not None and fees < 0):
        errors.append(FieldError("fees", "fees-invalid", "Zero or more."))
    errors += _check_reimbursable(body, "", body.amount)
    for i, sp in enumerate(getattr(body, "splits", None) or []):
        errors += _check_reimbursable(sp, f"splits.{i}.", sp.amount)
    if getattr(body, "payee", None) and len(body.payee) > 200:
        errors.append(FieldError("payee", "payee-too-long", "At most 200 characters."))
    if body.contributionSource and body.contributionSource not in SOURCES:
        errors.append(
            FieldError(
                "contributionSource",
                "choice-invalid",
                "Employee, employer, rollover or conversion.",
            )
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
                deductible=sp.deductible,
            )
        )
    if splits:
        t.categoryId = None


def _set_tags(s: Session, t: Transaction, user_id: str, names: list[str]) -> None:
    """Tags given by name (a new transaction's): each the user's own, made when new."""
    tag_ids = [tags.make(s, user_id, n).id for n in dict.fromkeys(names) if n.strip()]
    tags.set_on(s, "transaction", t.id, user_id, tag_ids, user_id)


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
        # A coin typed in a crypto account is crypto, with the 8949 boxes of its own (S8.1); a
        # fund is known by its symbol's shape, as in a file (S2.1).
        return repo.instrument(s, symbol, None, repo.class_named(symbol, account.type)).id
    return None


def _transfer_lots(s: Session, t: Transaction, a: Account, inst_id: str, body) -> None:
    """The lots shares moved in arrive as (S2.2, CR3-73): those typed, each with the day it was
    bought and its basis, adding up to the shares; none typed, one lot of the day they arrived,
    marked as not knowing when they were bought (its term unknown until it is)."""
    lots_in = getattr(body, "transferLots", None)
    if lots_in:
        if sum((x.quantity for x in lots_in), Decimal(0)) != abs(body.quantity):
            raise refuse(
                "transferLots", "lots-unbalanced", "The lots add up to the shares moved in."
            )
        if any(x.acquiredOn > body.date or x.quantity <= 0 for x in lots_in):
            raise refuse(
                "transferLots", "lot-invalid", "Each lot was bought by the day it moved in."
            )
        rows = [(x.acquiredOn, x.quantity, x.costBasis, False) for x in lots_in]
    else:
        rows = [(body.date, abs(body.quantity), getattr(body, "costBasis", None), True)]
    for acquired, qty, basis, missing in rows:
        s.add(
            Lot(
                id=ids.new_id("Lot"),
                accountId=a.id,
                instrumentId=inst_id,
                transactionId=t.id,
                acquiredOn=acquired,
                quantity=qty,
                costBasis=basis,
                basisMissing=basis is None,
                acquiredMissing=missing,
            )
        )


def _reward_basis(s: Session, body, inst_id: str, owner: str) -> Decimal | None:
    """Coins received as income: their value that day is their basis and the income (S8.5),
    at the price typed with them, else the owner's price for the day; none known, missing."""
    from .. import valuation

    price = body.price
    if price is None:
        found = valuation.prices(s, [inst_id], body.date, owner=owner).get(inst_id)
        price = found.price if found is not None else None
    return (abs(body.quantity) * price).quantize(Decimal("0.01")) if price else None


def _make(s: Session, c: Caller, body, txn_id: str, confirm: bool):
    """A transaction made, with its lot, splits and tags; the closed-year question (S2.8) is
    the write's own check, before it commits (`taxes.closed`)."""
    a, held = access.account(s, c.id, body.accountId, "write")
    investing = atypes.investing(a.type)
    _raise(_check(s, body, body.kind, investing))
    if confirm:
        closed.confirm(s)
    inst_id = _instrument(s, body, a)
    if body.kind in ("buy", "sell", "reinvest", "transfer-in", "transfer-out", "reward") and (
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
        deductible=getattr(body, "deductible", None),
        cleared=bool(getattr(body, "cleared", False)),
        createdById=c.id,
    )
    s.add(t)
    s.flush()
    if inst_id and body.kind == "transfer-in":
        _transfer_lots(s, t, a, inst_id, body)
    elif inst_id and body.kind in ("buy", "reinvest", "reward"):
        basis = -body.amount
        if body.kind == "reward":
            basis = _reward_basis(s, body, inst_id, a.ownerId)
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
    if inst_id and body.kind in ("transfer-in", "transfer-out"):
        # Shares or coins moved between the owner's accounts, offered as a pair (CR3-73).
        from ..bitcoin import transfers as pairs

        s.flush()
        pairs.propose(s, a.ownerId)
    _set_splits(s, t, getattr(body, "splits", None) or [], c.id)
    if getattr(body, "tagIds", None):
        tags.owned(s, c.id, body.tagIds)
        tags.set_on(s, "transaction", t.id, c.id, body.tagIds, c.id)
    elif getattr(body, "tags", None):
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
    return t, a, held


def _editable(
    s: Session, c: Caller, txn_id: str, version: int, confirm: bool
) -> tuple[Transaction, Account, str]:
    t = s.get(Transaction, txn_id)
    if t is None or t.deleted:
        raise Problem(404, "not-found", "Not found")
    a, held = access.account(s, c.id, t.accountId, "write")
    if t.version != version:
        raise stale(shape(s, c.id, [t], {a.id: held})[0])
    if t.reconciliationId and not confirm:
        r = s.get(Reconciliation, t.reconciliationId)
        if r is not None and r.finishedAt is not None:
            raise Problem(
                409,
                "reconciled-period",
                "This transaction is in a reconciled period. Change it anyway?",
            )
    return t, a, held


@router.get("/transactions/{txn_id}", response_model=TxnOut)
def get_transaction(txn_id: str, request: Request, c: Caller = Depends(caller)):
    """One transaction the caller can see: where a new one's Location leads (S13.8.4)."""
    with server(request).db.read(user=c.id) as s:
        t = s.get(Transaction, txn_id)
        if t is None or t.deleted:
            raise Problem(404, "not-found", "Not found")
        return _read_one(s, c, t)


def _read_one(s: Session, c: Caller, t: Transaction) -> TxnOut:
    """A transaction as one read gives it, with the budgets it is left out of: what a dialog's
    draft starts from (S12.15.1)."""
    a, held = access.account(s, c.id, t.accountId)
    out = shape(s, c.id, [t], {a.id: held})[0]
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
    "deductible",
)


def _change(s: Session, c: Caller, t: Transaction, a: Account, body, sent: set[str]) -> list[str]:
    """The fields `sent` set on a transaction, its lot following its trade; what changed."""
    kind = body.kind if "kind" in sent and body.kind else t.kind
    checked = body.model_copy(update={"amount": body.amount if "amount" in sent else t.amount})
    _raise(_check(s, checked, kind, atypes.investing(a.type), bool({"fees", "kind"} & sent)))
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
    if t.kind == "transfer-in" and "transferLots" in sent:
        # Its lots typed again, each with the day it was bought (S2.2, CR3-73).
        for lot in s.scalars(select(Lot).where(Lot.transactionId == t.id, Lot.deleted == false())):
            lot.mark_deleted(c.id)
        s.flush()
        inst_id = t.instrumentId
        _transfer_lots(s, t, s.get(Account, t.accountId), inst_id,
                       SimpleNamespace(transferLots=body.transferLots, quantity=t.quantity,
                                       date=t.date, costBasis=None))  # fmt: skip
        changed.append("transferLots")
    elif t.kind == "transfer-in" and {"quantity", "date"} & set(changed):
        # A lot whose day bought is known keeps it; one still missing it follows the day the
        # shares arrived (CR3-73).
        for lot in s.scalars(select(Lot).where(Lot.transactionId == t.id)):
            if lot.acquiredMissing:
                lot.quantity, lot.acquiredOn = abs(t.quantity), t.date
    if t.kind in ("buy", "reinvest") and {"quantity", "amount", "date"} & set(changed):
        # The lot follows its trade.
        for lot in s.scalars(select(Lot).where(Lot.transactionId == t.id)):
            lot.quantity, lot.acquiredOn = t.quantity, t.date
            lot.costBasis = -t.amount
    if getattr(body, "splits", None) is not None and "splits" in sent:
        _set_splits(s, t, body.splits, c.id)
        changed.append("splits")
    if getattr(body, "tagIds", None) is not None and "tagIds" in sent:
        tags.owned(s, c.id, body.tagIds)
        tags.set_on(s, "transaction", t.id, c.id, body.tagIds, c.id)
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


def delete_txn(s: Session, c: Caller, t: Transaction, a: Account) -> None:
    """A transaction deleted, with what goes with it: an assignment's stock trades, a split's
    or a corporate action's adjustments undone, the action it was made from."""
    if t.kind in ("split", "option-adjust"):
        from ..options import adjust

        adjust.undo(s, c.id, t)
    if t.kind in ("symbol-change", "spin-off", "merger"):
        from .. import corporate

        corporate.undo(s, c.id, t)
    if t.corporateActionId:
        # The action it was made from goes with it (S2.4).
        action = s.get(CorporateAction, t.corporateActionId)
        if action is not None and not action.deleted:
            action.mark_deleted(c.id)
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
    srv = server(request)
    with srv.db.tx(user=c.id) as s:
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
    if per_account:
        srv.events.publish("saved", users=[c.id])  # as a save does (S12.6)
    return Done(changed=sum(per_account.values()))


@router.post("/transactions/{txn_id}/both-real", response_model=TxnOut)
def both_real(txn_id: str, request: Request, c: Caller = Depends(caller)):
    """Two identical rows on one day, or two a file gave one id: the answer *both real* is
    kept (S1.11.5)."""
    with server(request).db.tx(user=c.id) as s:
        t = s.get(Transaction, txn_id)
        if t is None or t.deleted:
            raise Problem(404, "not-found", "Not found")
        a, held = access.account(s, c.id, t.accountId, "write")
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
        return shape(s, c.id, [t], {a.id: held})[0]


# ---------- instruments ----------


@router.get("/instruments", response_model=list[InstrumentOut])
def search_instruments(
    request: Request, c: Caller = Depends(caller), q: str = Query(..., min_length=1, max_length=40)
):
    with server(request).db.read(user=c.id) as s:
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
    with server(request).db.tx(user=c.id) as s:
        t, a, held = _editable(s, c, txn_id, version, True)
        if t.offChainAt is None:
            raise refuse(None, "on-chain", "It is still on the chain.")
        t.offChainAt, t.offChainMissedAt, t.offChainKeptAt = None, None, clock.now()
        s.flush()
        return shape(s, c.id, [t], {a.id: held})[0]


# ---------- transactions and their splits in a dialog's draft (S12.15, S13.8.11) ----------


def _set_of():
    """A set held by the record, sent as what to add and take away (S13.8.11.1)."""
    return Field(default_factory=list, json_schema_extra={"uniqueItems": True})


class TransferLot(Model):
    """One lot shares moved in arrive as (S2.2, CR3-73): when it was bought, and its basis."""

    acquiredOn: dt.date
    quantity: Quantity
    costBasis: Money | None = None


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
    # Shares moved in, lot by lot, each with the day it was bought (S2.2); none given, one lot
    # whose day bought is missing until it is (CR3-73).
    transferLots: list[TransferLot] | None = None
    reimbursable: Money | None = None
    owedBy: str | None = None
    # A contribution to a traditional IRA (S8.6): deductible or not, null until decided; with
    # splits, each part's instead.
    deductible: bool | None = None
    cleared: bool = False
    tagIds: list[IdOf("Tag")] = _set_of()  # type: ignore[valid-type]  # the saver's own (S2.6)
    leftOutOf: list[IdOf("Bdgt")] = _set_of()  # type: ignore[valid-type]
    splitRatio: Quantity | None = None  # a split's new shares for each one held (S2.4)
    # An option trade's contract (S3.2), `symbol` its underlying: made with the trade.
    right: str | None = None  # call or put
    strike: Quantity | None = None
    expiry: dt.date | None = None
    multiplier: int | None = None  # shares a contract: 100 unless typed
    # The other half of a transfer (S1.7): one of the same save, or a free one already
    # recorded, such as a loan payment's bank transaction (S1.9.3); changed, a match made by
    # hand, or none to undo one.
    transferWithId: IdOf("Txn") | None = None  # type: ignore[valid-type]


class SplitRecord(Model):
    """A part of a transaction's amount with its own category (S2.6), as a draft saves it."""

    transactionId: IdOf("Txn")  # type: ignore[valid-type]
    categoryId: IdOf("Cat") | None = None  # type: ignore[valid-type]
    amount: Money
    memo: str | None = None
    reimbursable: Money | None = None  # to be paid back (S2.9)
    owedBy: str | None = None
    deductible: bool | None = None  # a traditional IRA contribution's part (S8.6)


class LotPickRecord(Model):
    """How much of a lot a sale takes, picked (S2.3, specific identification), as a draft
    saves it: a record of its own, kept with the sale."""

    saleId: IdOf("Txn")  # type: ignore[valid-type]
    lotId: IdOf("Lot")  # type: ignore[valid-type]
    quantity: Quantity


def _left_out_of(s: Session, c: Caller, t: Transaction) -> list[str]:
    """The budgets the caller sees that leave the transaction out."""
    from ..store.entities.budgets import Budget, BudgetLeaveOut

    seen = {b.id for b, _ in access.listing(s, Budget, c.id)}
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
        if t.accountId not in budgets.account_ids(s, b, c.id, t.date):
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
    of its own (S2.6); a deductible mark is on a traditional IRA contribution, on its parts
    when it has them (S8.6)."""

    def check() -> None:
        if t.deleted:
            return
        parts = list(
            ctx.s.scalars(
                select(Split).where(Split.transactionId == t.id, Split.deleted == false())
            )
        )
        _deductible_fits(ctx.s, t, parts)
        if not parts:
            return
        if sum((x.amount for x in parts), Decimal(0)) != t.amount:
            raise refuse(
                "splits", "splits-unbalanced", "The parts must add up to the transaction's amount."
            )
        t.categoryId = None

    ctx.verify(f"splits:{t.id}", check)


def _deductible_fits(s: Session, t: Transaction, parts: list[Split]) -> None:
    """Only the owner's own contribution to a traditional IRA is deductible or not (S8.6), and
    a split one is marked part by part."""
    from ..taxes import retirement as moves

    marked = [t.deductible, *(x.deductible for x in parts)]
    if all(m is None for m in marked):
        return
    a = s.get(Account, t.accountId)
    if a.type != "ira" or moves.classify(s, t, a) != "employee":
        raise refuse(
            "deductible",
            "deductible-not-a-contribution",
            "Only a contribution to a traditional IRA is deductible or not.",
        )
    if parts and t.deductible is not None:
        raise refuse("deductible", "deductible-on-parts", "Split, each part is marked instead.")


def _txn_create(ctx, record_id: str, body: TxnRecord) -> None:
    from .. import options

    if body.kind in options.ACTIONS:
        from .options import make_trade

        t = make_trade(ctx, record_id, body)
    else:
        t, _, _ = _make(ctx.s, ctx.caller, body, record_id, False)
    ctx.notes.setdefault("transactions-made", set()).add(t.id)
    if body.leftOutOf:
        _set_left_out(ctx.s, ctx.caller, t, [], body.leftOutOf)
    if body.transferWithId:
        _transfer_with(ctx, t, body.transferWithId)
    _parts_add_up(ctx, t)


def _transfer_with(ctx, t: Transaction, other_id: str) -> None:
    """Once every op is in: the transaction paired with the other half it names, in place of
    any match made by itself (S1.7). The other is one of this save's, or free: a transfer
    already matched elsewhere stays as it is."""

    def pair() -> None:
        made = ctx.notes.get("transactions-made", set())
        other = ctx.s.get(Transaction, other_id)
        if other is None or other.deleted or other.id == t.id:
            raise refuse("transferWithId", "transaction-unknown", "No such transaction.")
        access.account(ctx.s, ctx.caller.id, other.accountId, "write")
        if other.transferId not in (None, t.id) and other.id not in made:
            raise refuse("transferWithId", "transfer-taken", "That transaction isn't free.")
        if other.accountId == t.accountId or other.instrumentId or t.instrumentId:
            raise refuse("transferWithId", "not-a-transfer", "A transfer is between two accounts.")
        if other.amount != -t.amount:
            raise refuse("amount", "amount-mismatch", "The two halves' amounts differ.")
        repo.unlink_transfer(ctx.s, t)
        repo.unlink_transfer(ctx.s, other)
        t.transferId, other.transferId = other.id, t.id

    ctx.verify(f"transfer:{t.id}", pair)


def _txn_editable(ctx, record_id: str) -> Transaction:
    """Read for a change: one who only sees the account may still leave it out of a budget
    they write; anything else needs the account's write (checked by the update)."""
    t = ctx.s.get(Transaction, record_id)
    if t is None or t.deleted:
        raise Problem(404, "not-found", "Not found")
    access.account(ctx.s, ctx.caller.id, t.accountId)
    return t


def _lots_of(s: Session, t: Transaction) -> list[TransferLot] | None:
    """A transfer-in's lots as typed; none while its day bought is missing."""
    rows = list(s.scalars(select(Lot).where(Lot.transactionId == t.id, Lot.deleted == false())))
    if not rows or any(x.acquiredMissing for x in rows):
        return None
    return [TransferLot(acquiredOn=x.acquiredOn, quantity=x.quantity, costBasis=x.costBasis)
            for x in sorted(rows, key=lambda x: x.acquiredOn)]  # fmt: skip


def _txn_current(ctx, t: Transaction) -> dict:
    lot = ctx.s.scalars(select(Lot).where(Lot.transactionId == t.id)).first()
    inst = ctx.s.get(Instrument, t.instrumentId) if t.instrumentId else None
    return {
        "accountId": t.accountId,
        "symbol": inst.symbol if inst else None,
        "instrumentId": t.instrumentId,
        "costBasis": lot.costBasis if lot is not None and t.kind == "transfer-in" else None,
        "transferLots": _lots_of(ctx.s, t) if t.kind == "transfer-in" else None,
        "tagIds": tags.ids_of(ctx.s, "transaction", ctx.caller.id, t.id),
        "leftOutOf": _left_out_of(ctx.s, ctx.caller, t),
        "transferWithId": t.transferId,
        "splitRatio": t.splitRatio,
        **{f: getattr(t, f) for f in CHANGED},
    }


def _txn_update(ctx, t: Transaction, body: TxnRecord) -> None:
    current = _txn_current(ctx, t)
    sent = {f for f in TxnRecord.model_fields if getattr(body, f) != current.get(f)}
    fixed_fields = ("accountId", "symbol", "instrumentId", "splitRatio", "right", "strike",
                    "expiry", "multiplier")  # fmt: skip
    for fixed in fixed_fields:
        if fixed in sent:
            raise refuse(fixed, "transaction-fixed", "A transaction keeps its account and holding.")
    if "transferWithId" in sent:
        access.account(ctx.s, ctx.caller.id, t.accountId, "write")
        if body.transferWithId:
            _transfer_with(ctx, t, body.transferWithId)
        else:
            repo.unlink_transfer(ctx.s, t)
    if sent - {"leftOutOf", "transferWithId"}:
        a, _ = access.account(ctx.s, ctx.caller.id, t.accountId, "write")
        _reconciled(ctx, t)
        changed = _change(ctx.s, ctx.caller, t, a, body, sent)
        _changed(ctx.s, ctx.caller, a, changed)
        ctx.s.flush()
        if t.instrumentId:
            washes.recompute(ctx.s, a.ownerId)
    if "leftOutOf" in sent:
        _set_left_out(ctx.s, ctx.caller, t, current["leftOutOf"], body.leftOutOf)
    _parts_add_up(ctx, t)


def _txn_delete(ctx, t: Transaction) -> None:
    a, _ = access.account(ctx.s, ctx.caller.id, t.accountId, "write")
    _reconciled(ctx, t)
    delete_txn(ctx.s, ctx.caller, t, a)


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
        "deductible": body.deductible,
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


SPLIT_FIELDS = ("categoryId", "amount", "memo", "reimbursable", "owedBy", "deductible")


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


# ---- a sale's lots, picked (S2.3) ----


def _pick_sale(ctx, sale_id: str) -> tuple[Transaction, Account]:
    """The pick's sale, written by the caller."""
    t = ctx.s.get(Transaction, sale_id)
    if t is None or t.deleted:
        raise refuse("saleId", "transaction-unknown", "No such transaction.")
    a, _ = access.account(ctx.s, ctx.caller.id, t.accountId, "write")
    if t.kind != "sell" or not t.instrumentId:
        raise refuse("saleId", "pick-not-a-sale", "Lots are picked for a sale.")
    return t, a


def _pick_checked(ctx, body: LotPickRecord) -> tuple[Transaction, Account]:
    t, a = _pick_sale(ctx, body.saleId)
    lot = ctx.s.get(Lot, body.lotId)
    if (
        lot is None
        or lot.deleted
        or lot.accountId != t.accountId
        or lot.instrumentId != t.instrumentId
    ):
        raise refuse("lotId", "lot-unknown", "Choose a lot of this holding.")
    if body.quantity <= 0:
        raise refuse("quantity", "quantity-invalid", "More than none.")
    _picks_fit(ctx, t, a)
    return t, a


def _picks_fit(ctx, t: Transaction, a: Account) -> None:
    """Once every op is in: the lots picked come to no more than the sale, each to no more
    than the lot held that day; then the household's wash sales are worked out again."""

    def check() -> None:
        if t.deleted:
            return
        picks = list(
            ctx.s.scalars(select(LotPick).where(LotPick.saleId == t.id, LotPick.deleted == false()))
        )
        if sum((p.quantity for p in picks), Decimal(0)) > abs(t.quantity or 0):
            raise refuse("quantity", "picks-over", "The lots picked come to more than the sale.")
        held = {c.lotId: c.quantity for c in lot_choices(ctx.s, a, t.date, t.id)}
        for p in picks:
            if p.quantity > held.get(p.lotId, Decimal(0)):
                raise refuse("quantity", "pick-over", "More than the lot held that day.")
        washes.recompute(ctx.s, a.ownerId)

    ctx.verify(f"picks:{t.id}", check)


def _pick_create(ctx, record_id: str, body: LotPickRecord) -> None:
    _pick_checked(ctx, body)
    ctx.s.add(
        LotPick(
            id=record_id,
            saleId=body.saleId,
            lotId=body.lotId,
            quantity=body.quantity,
            createdAt=clock.now(),
        )
    )


def _pick_editable(ctx, record_id: str) -> LotPick:
    p = ctx.s.get(LotPick, record_id)
    if p is None or p.deleted:
        raise Problem(404, "not-found", "Not found")
    _pick_sale(ctx, p.saleId)
    return p


def _pick_current(ctx, p: LotPick) -> dict:
    return {"saleId": p.saleId, "lotId": p.lotId, "quantity": p.quantity}


def _pick_update(ctx, p: LotPick, body: LotPickRecord) -> None:
    if body.saleId != p.saleId or body.lotId != p.lotId:
        raise refuse("lotId", "pick-fixed", "A pick keeps its sale and lot.")
    _pick_checked(ctx, body)
    p.quantity = body.quantity


def _pick_read(p: LotPick) -> PickOut:
    return PickOut(id=p.id, lotId=p.lotId, quantity=p.quantity, version=p.version)


def _pick_delete(ctx, p: LotPick) -> None:
    t, a = _pick_sale(ctx, p.saleId)
    p.mark_deleted(ctx.caller.id)
    _picks_fit(ctx, t, a)


class LotChoice(Model):
    """An open lot a sale may pick from, as held on the sale's day (S2.3)."""

    lotId: str
    instrumentId: str
    symbol: str
    acquiredOn: dt.date
    quantity: Quantity
    basis: Money | None
    longTerm: bool  # if sold that day


def lot_choices(
    s: Session, a: Account, day: dt.date, sale_id: str | None = None
) -> list[LotChoice]:
    """The account's open lots at a sale on `day`, before it: what it held from trades up to
    the day, the sale itself left out; a lot a wash sale split shown whole, as a pick takes
    every part of it."""
    led = repo.load(s, a)
    led.transactions = [t for t in led.transactions if t.date <= day and t.id != sale_id]
    kept = {t.id for t in led.transactions}
    led.lots = [x for x in led.lots if x.transactionId is None or x.transactionId in kept]
    led.picks = [p for p in led.picks if p.saleId in kept]
    # Wash sales whose loss sale is past by then, this sale's own left out.
    led.washes = [
        w
        for w in led.washes
        if w.saleId != sale_id
        and (w.saleId in kept or (w.saleId in led.sale_at and led.sale_at[w.saleId][0] <= day))
    ]
    whole: dict[str, list] = {}
    for lot in led.replay().open:
        if lot.lotId and lot.quantity > 0:
            whole.setdefault(lot.lotId, []).append(lot)
    symbols = {
        i.id: i.symbol
        for i in s.scalars(
            select(Instrument).where(Instrument.id.in_({p[0].instrumentId for p in whole.values()}))
        )
    }
    out = []
    for lot_id, parts in whole.items():
        first = parts[0]
        basis = None if any(p.basis is None for p in parts) else sum(p.basis for p in parts)
        out.append(
            LotChoice(
                lotId=lot_id,
                instrumentId=first.instrumentId,
                symbol=symbols.get(first.instrumentId, "?"),
                acquiredOn=first.acquiredOn,
                quantity=sum(p.quantity for p in parts),
                basis=basis,
                longTerm=all(lots.long_term(p.heldFrom or p.acquiredOn, day) for p in parts),
            )
        )
    return sorted(out, key=lambda c: (c.symbol, c.acquiredOn, c.lotId))


@router.get("/accounts/{account_id}/lots", response_model=list[LotChoice])
def get_lots(
    account_id: str,
    request: Request,
    date: dt.date,
    saleId: str | None = None,
    c: Caller = Depends(caller),
):
    """The lots a sale on `date` may pick from (S2.3): `saleId` leaves an edited sale out."""
    with server(request).db.read(user=c.id) as s:
        a, _ = access.account(s, c.id, account_id)
        return lot_choices(s, a, date, saleId)


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
save.register(
    save.Kind(
        prefix="LotPk",
        entity=LotPick,
        fields=LotPickRecord,
        create=_pick_create,
        editable=_pick_editable,
        current=_pick_current,
        update=_pick_update,
        delete=_pick_delete,
        read=lambda ctx, record_id: _pick_read(ctx.s.get(LotPick, record_id)),
    )
)
