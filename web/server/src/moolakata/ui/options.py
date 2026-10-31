"""Option trades (requirements S3.2, S3.3): the four opening and closing trades, recorded with
the contract they are in."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import false, select

from .. import access, activity, options, washes
from ..errors import FieldError, Problem, refuse
from ..ledger import types as atypes
from ..store.entities.accounts import CorporateAction, Instrument, Transaction
from ..store.repos import ledger as repo
from ..taxes import closed
from . import save
from .conventions import ExactRoute, IdOf, Model, Money, Quantity
from .deps import Caller, caller, server
from .transactions import TxnOut, shape

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["options"])


def make_trade(ctx, record_id: str, body) -> Transaction:
    """An option trade (S3.2) as a transaction's draft makes it: its kind the trade, `symbol`
    the underlying, `quantity` the contracts and `price` the premium a share, with the
    contract's right, strike, expiry and multiplier; its amount the cash the trade comes to."""
    s, c = ctx.s, ctx.caller
    e: list[FieldError] = []
    if body.right not in ("call", "put"):
        e.append(FieldError("right", "right-invalid", "A call or a put."))
    underlying = (body.symbol or "").strip().upper()
    if not underlying or len(underlying) > 12:
        e.append(FieldError("symbol", "symbol-invalid", "The underlying's symbol: MSFT."))
    if body.strike is None or body.strike <= 0:
        e.append(FieldError("strike", "strike-invalid", "More than zero."))
    contracts = body.quantity
    if contracts is None or contracts <= 0 or contracts != contracts.to_integral_value():
        e.append(FieldError("quantity", "contracts-invalid", "A whole number of contracts."))
    if body.price is None or body.price < 0:
        e.append(FieldError("price", "premium-invalid", "Zero or more, a share."))
    fees = body.fees or Decimal(0)
    if fees < 0:
        e.append(FieldError("fees", "fees-invalid", "Zero or more."))
    if body.expiry is None:
        e.append(FieldError("expiry", "expiry-required", "The day it expires."))
    elif body.kind.endswith("to-open") and body.expiry < body.date:
        e.append(FieldError("expiry", "expired", "It expired before the trade."))
    multiplier = body.multiplier or 100
    if not 1 <= multiplier <= 10000:
        e.append(FieldError("multiplier", "multiplier-invalid", "Shares a contract: 100."))
    if e:
        raise Problem(422, e[0].code, e[0].message, e)
    a, _ = access.account(s, c.id, body.accountId, "write")
    if not atypes.investing(a.type):
        raise refuse("kind", "kind-not-for-account", "Options belong in an investing account.")
    guard = closed.Guard(s, a, False, c.id, ask=ctx.ask)
    inst, contract = options.contract(
        s, underlying, body.right, body.strike, body.expiry, multiplier
    )
    if body.kind.endswith("to-close"):
        held = repo.load(s, a).replay().quantity(inst.id)
        want_long = body.kind == "sell-to-close"
        if (want_long and held < contracts) or (not want_long and -held < contracts):
            raise refuse(
                "quantity",
                "nothing-to-close",
                f"The account holds {abs(held)} {'long' if held >= 0 else 'short'} "
                "contracts of it.",
            )
    amount = options.cash(body.kind, contracts, body.price, fees, contract.multiplier)
    if body.amount != amount:
        raise refuse("amount", "amount-mismatch", f"The trade comes to {amount:,.2f}.")
    t = Transaction(
        id=record_id,
        accountId=a.id,
        date=body.date,
        kind=body.kind,
        amount=amount,
        payee=(body.payee or "").strip()
        or f"{body.kind.replace('-', ' ').capitalize()} {inst.symbol}",
        memo=body.memo,
        instrumentId=inst.id,
        quantity=contracts,
        price=body.price,
        fees=fees or None,
        createdById=c.id,
    )
    s.add(t)
    s.flush()
    guard.check()
    activity.record(
        s,
        "option.traded",
        actor=c.id,
        subject_kind="account",
        subject_id=a.id,
        owner=a.ownerId,
    )
    return t


class Settle(Model):
    how: str  # expired, assign, exercise
    date: dt.date
    contracts: Quantity | None = None


@router.post(
    "/accounts/{account_id}/options/{instrument_id}/settle",
    response_model=list[TxnOut],
    status_code=201,
)
def settle(
    account_id: str,
    instrument_id: str,
    body: Settle,
    request: Request,
    c: Caller = Depends(caller),
    confirm: bool = False,
):
    """An option's end: it expired, was assigned, or was exercised (S3.4, S3.6)."""
    if body.how not in ("expired", "assign", "exercise"):
        raise refuse("how", "how-invalid", "Expired, assigned or exercised.")
    with server(request).db.tx(user=c.id) as s:
        a, level = access.account(s, c.id, account_id, "write")
        inst = s.get(Instrument, instrument_id)
        if inst is None or inst.deleted:
            raise refuse("instrumentId", "not-found", "No such option.")
        guard = closed.Guard(s, a, confirm, c.id)
        made = options.settle(s, c.id, a, inst, body.how, body.date, body.contracts)
        washes.recompute(s, a.ownerId)
        guard.check()
        activity.record(
            s,
            "option.settled",
            actor=c.id,
            subject_kind="account",
            subject_id=a.id,
            owner=a.ownerId,
        )
        return shape(s, c.id, made, {a.id: level})


# ---- Adjusted contracts (S3.10.2) ----


class OpenContract(Model):
    instrumentId: str
    symbol: str
    right: str
    strike: Quantity
    expiry: dt.date
    root: str | None
    held: list[str]  # the accounts it is open in, with how many: "Short 2 in Options"


class Adjustable(Model):
    underlying: str
    underlyingId: str
    contracts: list[OpenContract]


@router.get("/options/adjustable", response_model=list[Adjustable])
def adjustable(request: Request, c: Caller = Depends(caller)):
    """The caller's open contracts, by underlying, that an adjustment from the OCC's memo can
    change: in the accounts they may change."""
    by: dict[str, dict] = {}
    with server(request).db.read(user=c.id) as s:
        for a, p in access.accounts(s, c.id):
            if not p.writable or not atypes.investing(a.type):
                continue
            for iid, qty in repo.load(s, a).replay().positions().items():
                oc = options.contract_of(s, iid)
                if oc is None:
                    continue
                under = s.get(Instrument, oc.underlyingId)
                group = by.setdefault(
                    under.id, {"underlying": under.symbol, "underlyingId": under.id, "c": {}}
                )
                row = group["c"].setdefault(
                    iid,
                    {
                        "instrumentId": iid,
                        "symbol": s.get(Instrument, iid).symbol,
                        "right": oc.right,
                        "strike": oc.strike,
                        "expiry": oc.expiry,
                        "root": oc.root,
                        "held": [],
                    },
                )
                side = "Short" if qty < 0 else "Long"
                row["held"].append(f"{side} {abs(qty).normalize():f} in {a.name}")
    return [
        Adjustable(
            underlying=g["underlying"],
            underlyingId=g["underlyingId"],
            contracts=[OpenContract(**x) for x in g["c"].values()],
        )
        for g in sorted(by.values(), key=lambda g: g["underlying"])
    ]


class DeliverablePart(Model):
    symbol: str
    shares: Quantity


class ContractAdjustment(Model):
    instrumentId: str
    root: str
    strike: Quantity
    deliverable: list[DeliverablePart]
    cash: Money = Decimal(0)


class Adjustment(Model):
    date: dt.date
    contracts: list[ContractAdjustment]


class Adjusted(Model):
    contracts: int
    accounts: int


@router.post("/options/adjust", response_model=Adjusted)
def adjust_contracts(body: Adjustment, request: Request, c: Caller = Depends(caller)):
    """Each open contract to its new root, strike and deliverable, from the OCC's memo; its
    lots carry over in every account the caller may change, nothing sold (S3.10.2)."""
    from ..options import adjust

    if not body.contracts:
        raise refuse("contracts", "contracts-missing", "At least one contract.")
    moved = 0
    touched: set[str] = set()
    with server(request).db.tx(user=c.id) as s:
        mine = [a for a, p in access.accounts(s, c.id) if p.writable and atypes.investing(a.type)]
        for i, x in enumerate(body.contracts):
            oc = options.contract_of(s, x.instrumentId)
            if oc is None:
                raise refuse(f"contracts.{i}.instrumentId", "not-an-option", "An open contract.")
            root = x.root.strip().upper()
            if not adjust.ADJUSTED_ROOT.match(root) and root != (oc.root or "").upper():
                raise refuse(f"contracts.{i}.root", "root-invalid", "The new root, such as XYZ1.")
            if x.strike <= 0:
                raise refuse(f"contracts.{i}.strike", "strike-invalid", "A strike above 0.")
            parts = adjust.check_deliverable(
                s, [{"symbol": p.symbol, "shares": p.shares} for p in x.deliverable]
            )
            if not parts:
                raise refuse(
                    f"contracts.{i}.deliverable", "deliverable-missing", "What it delivers."
                )
            old = s.get(Instrument, x.instrumentId)
            new, _ = adjust.adjusted_contract(s, oc, root, x.strike, parts, x.cash)
            for a in mine:
                if adjust.carry(s, c.id, a, old, new, Decimal(1), body.date):
                    moved += 1
                    touched.add(a.id)
        for a in mine:
            if a.id in touched:
                activity.record(
                    s,
                    "option.adjusted",
                    actor=c.id,
                    subject_kind="account",
                    subject_id=a.id,
                    owner=a.ownerId,
                )
        s.flush()
        owners = {a.ownerId for a in mine if a.id in touched}
        for o in owners:
            washes.recompute(s, o)
    return Adjusted(contracts=moved, accounts=len(touched))


# ---- Corporate actions (S2.4) ----


class CorporateActionRecord(Model):
    """A corporate action as its dialog's draft saves it (S2.4)."""

    accountId: IdOf("Acct")  # type: ignore[valid-type]
    instrumentId: IdOf("Instr")  # type: ignore[valid-type]
    kind: str  # split, symbol-change, spin-off, merger
    date: dt.date
    ratio: Quantity | None = None  # new shares for each one held
    newSymbol: str | None = None
    basisShare: Quantity | None = None  # a spin-off: the percent of basis that moves
    cashPerShare: Money | None = None  # a merger's cash for each share held
    newPrice: Quantity | None = None  # a new share's price that day, for a merger's cash


class CorporateActionOut(Model):
    id: str
    accountId: str
    instrumentId: str
    symbol: str
    kind: str
    date: dt.date
    ratio: Quantity | None
    newSymbol: str | None
    basisShare: Quantity | None
    cashPerShare: Money | None
    newPrice: Quantity | None
    transactions: list[TxnOut]  # the ones made from it
    version: int


ACTION_FIELDS = (
    "kind", "date", "ratio", "newSymbol", "basisShare", "cashPerShare", "newPrice"
)  # fmt: skip


def _action_create(ctx, record_id: str, body: CorporateActionRecord) -> None:
    """A split, symbol change, spin-off or merger: lots reshaped or moved, never sold and
    bought again; a merger's cash is a gain only as far as the gain goes."""
    from .. import corporate

    s, c = ctx.s, ctx.caller
    if body.kind not in corporate.KINDS:
        raise refuse("kind", "kind-invalid", "A split, symbol change, spin-off or merger.")
    a, _ = access.account(s, c.id, body.accountId, "write")
    if not atypes.investing(a.type):
        raise refuse("kind", "kind-not-for-account", "These belong in an investing account.")
    inst = s.get(Instrument, body.instrumentId)
    if inst is None or inst.deleted or inst.instrumentClass == "option":
        raise refuse("instrumentId", "instrument-unknown", "Choose a holding.")
    guard = closed.Guard(s, a, False, c.id, ask=ctx.ask)
    action = CorporateAction(
        id=record_id,
        accountId=a.id,
        instrumentId=inst.id,
        createdById=c.id,
        **{f: getattr(body, f) for f in ACTION_FIELDS},
    )
    action.newSymbol = (body.newSymbol or "").strip().upper() or None
    s.add(action)
    s.flush()
    made = corporate.record(
        s, c.id, a, inst, body.kind, body.date, body.ratio, action.newSymbol, body.basisShare,
        body.cashPerShare, body.newPrice,
    )  # fmt: skip
    for t in made:
        t.corporateActionId = action.id
    washes.recompute(s, a.ownerId)
    guard.check()
    activity.record(
        s,
        "account.corporate-action",
        actor=c.id,
        subject_kind="account",
        subject_id=a.id,
        owner=a.ownerId,
        detail={"name": corporate.WORDS[body.kind].lower()},
    )


def _action_editable(ctx, record_id: str) -> CorporateAction:
    action = ctx.s.get(CorporateAction, record_id)
    if action is None or action.deleted:
        raise Problem(404, "not-found", "Not found")
    access.account(ctx.s, ctx.caller.id, action.accountId, "write")
    return action


def _action_current(ctx, action: CorporateAction) -> dict:
    return {
        "accountId": action.accountId,
        "instrumentId": action.instrumentId,
        **{f: getattr(action, f) for f in ACTION_FIELDS},
    }


def _action_update(ctx, action: CorporateAction, body: CorporateActionRecord) -> None:
    raise refuse(
        None, "action-fixed", "A corporate action is deleted, and recorded again if it differs."
    )


def _made_from(s, action_id: str) -> list[Transaction]:
    return list(
        s.scalars(
            select(Transaction)
            .where(Transaction.corporateActionId == action_id, Transaction.deleted == false())
            .order_by(Transaction.createdAt, Transaction.id)
        )
    )


def _action_delete(ctx, action: CorporateAction) -> None:
    """Undone: its transactions deleted with it, the lots back as they were."""
    from .transactions import delete_txn

    a, _ = access.account(ctx.s, ctx.caller.id, action.accountId, "write")
    guard = closed.Guard(ctx.s, a, False, ctx.caller.id, ask=ctx.ask)
    for t in _made_from(ctx.s, action.id):
        if not t.deleted:
            delete_txn(ctx.s, ctx.caller, t, a)
    if not action.deleted:
        action.mark_deleted(ctx.caller.id)
    guard.check()


def _action_read(ctx, record_id: str) -> CorporateActionOut:
    s = ctx.s
    action = s.get(CorporateAction, record_id)
    _, level = access.account(s, ctx.caller.id, action.accountId)
    inst = s.get(Instrument, action.instrumentId)
    return CorporateActionOut(
        id=action.id,
        accountId=action.accountId,
        instrumentId=action.instrumentId,
        symbol=inst.symbol,
        transactions=shape(s, ctx.caller.id, _made_from(s, action.id), {action.accountId: level}),
        version=action.version,
        **{f: getattr(action, f) for f in ACTION_FIELDS},
    )


save.register(
    save.Kind(
        prefix="CorpA",
        entity=CorporateAction,
        fields=CorporateActionRecord,
        create=_action_create,
        editable=_action_editable,
        current=_action_current,
        update=_action_update,
        delete=_action_delete,
        read=_action_read,
    )
)
