"""Adjusted contracts (requirements S3.10): when the underlying splits, merges, spins off a
company or pays a large special dividend, the OCC adjusts its open options, and the lot carries
over to the adjusted contract: no sale, no wash sale.

An adjustment is a pair of `option-adjust` transactions linked by their transferId: one on the
old contract, whose lots leave, and one on the new, which takes them with the contracts times
the ratio (its splitRatio). A pair made with a stock's split names the split as its
optionTransactionId, so deleting the split undoes them."""

import datetime as dt
import json
import re
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import ids
from ..errors import refuse
from ..store.entities.accounts import Instrument, OptionContract, Transaction
from ..store.repos import ledger as repo
from . import contract_of, symbol

ADJUSTED_ROOT = re.compile(r"^[A-Z.]+\d+$")


def adjusted_strike(strike: Decimal, ratio: Decimal) -> Decimal:
    """A split's new strike: the old one divided by the ratio, rounded to the thousandth, as
    the OCC prints it (S3.10.1)."""
    return (strike / ratio).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP).normalize()


def adjusted_contract(
    s: Session,
    old: OptionContract,
    root: str | None,
    strike: Decimal,
    deliverable: list[tuple[str, Decimal]] | None = None,
    cash: Decimal | None = None,
) -> tuple[Instrument, OptionContract]:
    """The contract an adjustment makes: a new root (or the same), a strike, and what it
    delivers (or the same); found again if it is already here. Only the memo gives cash: a
    whole split adjusts no contract with cash (`splits_whole`)."""
    under = s.get(Instrument, old.underlyingId)
    name = symbol(root or old.root or under.symbol, old.expiry, old.right, strike)
    inst = repo.instrument(s, name, None, "option")
    c = contract_of(s, inst.id)
    if c is None:
        c = OptionContract(
            id=ids.new_id("OptCt"),
            instrumentId=inst.id,
            underlyingId=old.underlyingId,
            right=old.right,
            strike=strike,
            expiry=old.expiry,
            multiplier=old.multiplier,
            root=root or old.root,
            deliverable=json.dumps([{"instrumentId": i, "shares": str(q)} for i, q in deliverable])
            if deliverable
            else old.deliverable,
            deliverableCash=cash,
        )
        s.add(c)
        s.flush()
    return inst, c


def carry(
    s: Session,
    user_id: str,
    account,
    old: Instrument,
    new: Instrument,
    ratio: Decimal,
    day: dt.date,
    split: Transaction | None = None,
) -> list[Transaction]:
    """The pair that carries the old contract's lots in an account to the new one."""
    held = repo.load(s, account).replay().quantity(old.id)
    if not held:
        return []
    out = Transaction(
        id=ids.new_id("Txn"),
        accountId=account.id,
        date=day,
        kind="option-adjust",
        amount=Decimal(0),
        payee=f"Adjusted: {old.symbol} became {new.symbol}",
        instrumentId=old.id,
        quantity=abs(held),
        optionTransactionId=split.id if split else None,
        createdById=user_id,
    )
    s.add(out)
    s.flush()
    into = Transaction(
        id=ids.new_id("Txn"),
        accountId=account.id,
        date=day,
        kind="option-adjust",
        amount=Decimal(0),
        payee=f"Adjusted from {old.symbol}",
        instrumentId=new.id,
        quantity=abs(held) * ratio,
        splitRatio=ratio,
        transferId=out.id,
        optionTransactionId=split.id if split else None,
        createdById=user_id,
    )
    s.add(into)
    s.flush()
    out.transferId = into.id
    return [out, into]


def open_contracts(s: Session, account, underlying_id: str, day: dt.date) -> list[OptionContract]:
    """The account's contracts on the stock still open on the day (one expiring that day is)."""
    out = []
    # Positions holds only what isn't zero.
    for iid in repo.load(s, account).replay().positions():
        c = contract_of(s, iid)
        if c is not None and c.underlyingId == underlying_id and c.expiry >= day:
            out.append(c)
    return out


def splits_whole(c: OptionContract) -> bool:
    """Whether a whole-number split adjusts the contract by itself: it delivers only shares of
    its underlying, which split with it, and no cash. Another company's shares and cash don't
    split, so more contracts each delivering the same would deliver more of them in all: such
    a contract waits for the OCC's memo (S3.10.1)."""
    parts = json.loads(c.deliverable) if c.deliverable else []
    return not c.deliverableCash and all(x["instrumentId"] == c.underlyingId for x in parts)


def with_split(s: Session, user_id: str, account, split: Transaction) -> int:
    """A whole-number split (2:1, 4:1) applied to the account's open options on the stock:
    contracts times the ratio, strike divided by it, the basis spread over the new contracts
    (S3.10.1). Any other ratio, and a contract delivering more than its underlying's shares,
    waits for the adjustment from the OCC's memo."""
    ratio = split.splitRatio
    if not ratio or ratio < 2 or ratio != ratio.to_integral_value():
        return 0
    done = 0
    for c in open_contracts(s, account, split.instrumentId, split.date):
        if not splits_whole(c):
            continue
        old = s.get(Instrument, c.instrumentId)
        # Its root and deliverable stay: only the strike changes.
        new, _ = adjusted_contract(s, c, None, adjusted_strike(c.strike, ratio))
        if carry(s, user_id, account, old, new, ratio, split.date, split):
            done += 1
    return done


def undo(s: Session, by: str, txn: Transaction) -> None:
    """Deleting a split undoes the adjustments made with it; deleting either half of a pair
    deletes the other."""
    rows = list(
        s.scalars(
            select(Transaction).where(
                Transaction.optionTransactionId == txn.id,
                Transaction.kind == "option-adjust",
                Transaction.deleted == false(),
            )
        )
    )
    if txn.kind == "option-adjust" and txn.transferId:
        other = s.get(Transaction, txn.transferId)
        if other is not None and not other.deleted:
            rows.append(other)
    for r in rows:
        r.mark_deleted(by)


def parse_occ(text: str) -> tuple[str, dt.date, str, Decimal] | None:
    """An OCC ticker (`XYZ1  270115C00060000`, `O:XYZ1270115C00060000`): its root, expiry,
    right and strike; None for anything else."""
    t = text.strip().upper().removeprefix("O:").replace(" ", "")
    m = re.fullmatch(r"([A-Z.]{1,6}\d?)(\d{6})([CP])(\d{8})", t)
    if not m:
        return None
    try:
        expiry = dt.datetime.strptime(m.group(2), "%y%m%d").date()
    except ValueError:
        return None
    return (
        m.group(1),
        expiry,
        "call" if m.group(3) == "C" else "put",
        Decimal(m.group(4)) / 1000,
    )


def check_deliverable(s: Session, rows: list[dict], at: str) -> list[tuple[str, Decimal]]:
    """A deliverable's parts as instruments and shares. A part without a symbol or with no
    shares is refused at its own row under `at`, the contract's deliverable field."""
    out = []
    for i, x in enumerate(rows):
        # The instrument is found and made by its symbol in capitals.
        sym = (x.get("symbol") or "").strip()
        shares = x.get("shares")
        if not sym or shares is None or Decimal(str(shares)) <= 0:
            raise refuse(f"{at}.{i}", "deliverable-invalid", "A symbol and its shares.")
        inst = repo.instrument(s, sym, None, "equity")
        out.append((inst.id, Decimal(str(shares))))
    return out
