"""Loading an account's ledger, the shipped categories, instruments, and applying an import
(requirements S1.3, S1.7, S2)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from ... import activity, ids, money
from ...importers.parsed import ParsedFile
from ...ledger import balances, lots, transfers
from ...ledger import types as atypes
from ...ledger.categories import DEFAULTS
from .. import scoping
from ..db import live
from ..entities.accounts import (
    Account,
    Anchor,
    Category,
    Holding,
    HoldingCheck,
    Import,
    Instrument,
    Lot,
    LotPick,
    Transaction,
    WashSale,
)
from ..tables import accounts as t


@dataclass
class Ledger:
    """Everything an account's figures are worked out from."""

    account: Account
    transactions: list[Transaction]
    lots: list[Lot]
    picks: list[LotPick]
    snapshots: list[Holding]
    anchors: list[Anchor]
    imports: list[Import]
    washes: list = field(default_factory=list)  # wash sales touching its trades (S3.8)

    def opening(self) -> balances.Opening:
        return balances.opening(self.account, self.transactions, self.anchors)

    def balance(self, day: dt.date | None = None) -> Decimal:
        day = day or dt.date.max
        return balances.balance_on(day, self.opening(), self.transactions)

    def replay(self) -> lots.Replay:
        return lots.replay(
            self.account.lotMethod,
            self.transactions,
            self.lots,
            self.picks,
            self.snapshots,
            self.washes,
            basis_added=lots.adds_basis(self.account.type),
        )


def load(s: Session, account: Account, raw: bool = False) -> Ledger:
    """The account's ledger; raw leaves out the wash sales, for working them out."""
    aid = account.id
    txns = s.scalars(
        select(Transaction)
        .where(Transaction.accountId == aid, Transaction.deleted == false())
        .order_by(Transaction.date, Transaction.createdAt)
    ).all()
    lot_rows = s.scalars(live(Lot, t.Lot).where(Lot.accountId == aid)).all()
    lot_ids = [x.id for x in lot_rows]
    picks = (
        s.scalars(
            select(LotPick).where(LotPick.lotId.in_(lot_ids), LotPick.deleted == false())
        ).all()
        if lot_ids
        else []
    )
    snaps = s.scalars(
        select(Holding).where(Holding.accountId == aid, Holding.deleted == false())
    ).all()
    anchors = s.scalars(
        select(Anchor)
        .where(Anchor.accountId == aid, Anchor.deleted == false())
        .order_by(Anchor.date)
    ).all()
    imports = s.scalars(
        select(Import)
        .where(Import.accountId == aid, Import.deleted == false())
        .order_by(Import.createdAt)
    ).all()
    ids_ = [x.id for x in txns]
    washes = (
        s.scalars(
            select(WashSale).where((WashSale.saleId.in_(ids_)) | (WashSale.replacementId.in_(ids_)))
        ).all()
        if ids_ and not raw
        else []
    )
    return Ledger(
        account,
        list(txns),
        list(lot_rows),
        list(picks),
        list(snaps),
        list(anchors),
        list(imports),
        list(washes),
    )


# ---------- categories ----------


def ensure_categories(s: Session) -> int:
    """Add any shipped category this database lacks, found by its key."""
    have = {c.builtIn: c for c in s.scalars(select(Category).where(Category.builtIn.is_not(None)))}
    added = 0
    for key, name, kind, tag, children in DEFAULTS:
        parent = have.get(key)
        if parent is None:
            parent = Category(id=ids.new_id("Cat"), name=name, kind=kind, taxTag=tag, builtIn=key)
            s.add(parent)
            added += 1
        for ckey, cname, ctag, *ckind in children:
            if ckey not in have:
                s.add(
                    Category(
                        id=ids.new_id("Cat"),
                        name=cname,
                        kind=ckind[0] if ckind else kind,
                        taxTag=ctag,
                        builtIn=ckey,
                        parentId=parent.id,
                    )
                )
                added += 1
    s.flush()
    return added


# ---------- instruments ----------

# A US fund's symbol is five letters ending in X (FXAIX, VTSAX, SWVXX); any other ticker is a
# listed share, an ETF among them, which the price sources fetch the same way (CR3-14).
FUND_SYMBOL = re.compile(r"[A-Z]{4}X")
TICKER = re.compile(r"[A-Z][A-Z0-9]{0,4}(?:[.-][A-Z])?")


def class_by_symbol(symbol: str | None) -> str:
    """What a security named only by its symbol most likely is: a fund, a listed share, or
    not known."""
    s = (symbol or "").strip().upper()
    if FUND_SYMBOL.fullmatch(s):
        return "mutual-fund"
    return "equity" if TICKER.fullmatch(s) else "other"


def instrument(
    s: Session, symbol: str | None, name: str | None, cls: str, cusip: str | None = None
) -> Instrument:
    """The instrument with this CUSIP or symbol, made if MoolaKata doesn't know it yet. A
    symbol is looked for among the coins for a coin and among the rest otherwise: a coin and a
    listed share may share a ticker (S2.1)."""
    found = None
    if cusip:
        found = s.scalars(
            select(Instrument).where(Instrument.cusip == cusip, Instrument.deleted == false())
        ).first()
    # One known only by its CUSIP or name is kept under it as its symbol, and found by it.
    wanted = symbol or cusip or name
    if found is None and wanted:
        coin = Instrument.instrumentClass == "crypto"
        found = s.scalars(
            select(Instrument).where(
                Instrument.symbol == wanted.upper(),
                Instrument.deleted == false(),
                coin if cls == "crypto" else ~coin,
            )
        ).first()
    if found is not None:
        if cusip and not found.cusip:
            found.cusip = cusip
        if name and not found.name:
            found.name = name
        return found
    inst = Instrument(
        id=ids.new_id("Instr"),
        symbol=(symbol or cusip or name or "?").upper(),
        name=name,
        instrumentClass=cls,
        cusip=cusip,
    )
    s.add(inst)
    s.flush()
    return inst


# ---------- what a file or statement reports on a day ----------


def keep_anchor(
    s: Session,
    account_id: str,
    day: dt.date,
    balance: Decimal,
    source: str,
    import_id: str | None,
    created_by: str | None = None,
) -> None:
    """A balance a file or statement reports, kept once for its account, day and source: the
    same file again adds nothing, and a balance that differs replaces the one kept."""
    found = s.scalars(
        select(Anchor).where(
            Anchor.accountId == account_id,
            Anchor.date == day,
            Anchor.source == source,
            Anchor.deleted == false(),
        )
    ).first()
    if found is None:
        s.add(
            Anchor(
                id=ids.new_id("Anchr"),
                accountId=account_id,
                date=day,
                balance=balance,
                source=source,
                importId=import_id,
                createdById=created_by,
            )
        )
    elif found.balance != balance:
        found.balance = balance


def keep_position(
    s: Session,
    account_id: str,
    import_id: str | None,
    day: dt.date,
    instrument_id: str | None,
    label: str,
    *,
    check: bool,
    **figures,
) -> None:
    """A position a file or statement reports, kept once for its account, day and instrument
    (or its label, for one MoolaKata doesn't know): as a holdings check when `check`, and, for a
    known instrument, as the day's holding, which is the holdings of an account kept by
    snapshots and the statement price of an instrument no source prices (S1.3.2). The same file
    again adds nothing; figures that differ replace the ones kept."""
    if check:
        found = s.scalars(
            select(HoldingCheck).where(
                HoldingCheck.accountId == account_id,
                HoldingCheck.asOf == day,
                HoldingCheck.instrumentId == instrument_id
                if instrument_id
                else (HoldingCheck.instrumentId.is_(None) & (HoldingCheck.label == label)),
                HoldingCheck.deleted == false(),
            )
        ).first()
        if found is None:
            s.add(
                HoldingCheck(
                    id=ids.new_id("HdChk"),
                    accountId=account_id,
                    importId=import_id,
                    asOf=day,
                    instrumentId=instrument_id,
                    label=label,
                    **figures,
                )
            )
        else:
            for k, v in figures.items():
                setattr(found, k, v)
    quantity, value = figures.get("quantity"), figures.get("marketValue")
    if instrument_id is None or figures.get("cash") or not quantity:
        return
    held = s.scalars(
        select(Holding).where(
            Holding.accountId == account_id,
            Holding.instrumentId == instrument_id,
            Holding.asOf == day,
            Holding.deleted == false(),
        )
    ).first()
    if held is None:
        s.add(
            Holding(
                id=ids.new_id("Hold"),
                accountId=account_id,
                instrumentId=instrument_id,
                asOf=day,
                quantity=quantity,
                marketValue=value,
                importId=import_id,
            )
        )
    else:
        held.quantity, held.marketValue = quantity, value


# ---------- transfers (S1.7) ----------


def match_transfer(s: Session, txn: Transaction, owner_id: str) -> Transaction | None:
    """Link a transaction to its other half in another of the owner's accounts."""
    if txn.transferId or txn.amount == 0 or txn.instrumentId:
        return None
    lo, hi = transfers.window(txn)
    others = s.scalars(
        select(Transaction)
        .join(Account, Account.id == Transaction.accountId)
        .where(
            Account.ownerId == owner_id,
            Account.deleted == false(),
            Transaction.deleted == false(),
            Transaction.accountId != txn.accountId,
            Transaction.transferId.is_(None),
            Transaction.instrumentId.is_(None),
            Transaction.amount == -txn.amount,
            Transaction.date >= lo,
            Transaction.date <= hi,
        )
    ).all()
    other = transfers.best(txn, list(others))
    if other is not None:
        txn.transferId, other.transferId = other.id, txn.id
    return other


def unlink_transfer(s: Session, txn: Transaction) -> None:
    if txn.transferId:
        other = s.get(Transaction, txn.transferId)
        if other is not None and other.transferId == txn.id:
            other.transferId = None
        txn.transferId = None


# ---------- imports (S1.3.2) ----------


@dataclass
class Applied:
    importId: str
    added: int = 0
    matched: int = 0
    changed: int = 0
    transfers: int = 0
    categorised: int = 0  # set by the importer's rules (S2.7)
    coveredFrom: dt.date | None = None
    coveredTo: dt.date | None = None
    warnings: list[str] = field(default_factory=list)


def _option(s: Session, account: Account, sec, result) -> Instrument | None:
    """An option the file names by its OCC ticker, made a contract (S3.2). A root ending in a
    digit is an adjusted contract (S3.10.3): linked to the adjusted contract already here, or,
    when the account still holds the contract it adjusts, named in a warning to adjust it."""
    from ...options import adjust, contract, contract_of, symbol

    for text in (sec.symbol, sec.name, sec.key):
        occ = adjust.parse_occ(text or "")
        if occ is not None:
            break
    else:
        return None
    root, expiry, right, strike = occ
    if not adjust.ADJUSTED_ROOT.match(root):
        inst, _ = contract(s, root, right, strike, expiry, sec.multiplier or 100)
        return inst
    name = symbol(root, expiry, right, strike)
    here = s.scalars(
        select(Instrument).where(Instrument.symbol == name, Instrument.deleted == false())
    ).first()
    if here is not None and contract_of(s, here.id) is not None:
        return here
    base = root.rstrip("0123456789")
    held = load(s, account).replay().positions()
    for iid in held:
        c = contract_of(s, iid)
        if c is None or c.right != right or c.expiry != expiry or (c.root or "") == root:
            continue
        under = s.get(Instrument, c.underlyingId)
        if under is not None and under.symbol == base:
            result.warnings.append(
                f"{name} looks like an adjustment of {s.get(Instrument, iid).symbol}: adjust it "
                "on Positions › Strategies, from the OCC's memo, so its lots carry over"
            )
            break
    return None


def apply_import(
    s: Session, account: Account, user_id: str, parsed: ParsedFile, file_name: str, file_hash: str
) -> Applied:
    """Add what is new: rows are matched by the file's transaction id (an OFX FITID), or by
    date, amount and payee. A re-imported file adds nothing; an amount that changed between
    imports is updated and kept for the reconciliation's suspects (S1.11.3). The server's work
    on an account the importer may change, checked before: it matches the rows the owner
    deleted too, which no one's view holds (S1.3.2)."""
    with scoping.as_server(s, "an import into an account its importer may change") as srv:
        return _apply_import(
            srv, srv.get(Account, account.id), user_id, parsed, file_name, file_hash
        )


def _apply_import(
    s: Session, account: Account, user_id: str, parsed: ParsedFile, file_name: str, file_hash: str
) -> Applied:
    imp = Import(
        id=ids.new_id("Imprt"),
        accountId=account.id,
        userId=user_id,
        format=parsed.format,
        fileName=file_name[:200],
        fileHash=file_hash,
        coveredFrom=parsed.coveredFrom,
        coveredTo=parsed.coveredTo,
    )
    s.add(imp)
    s.flush()
    result = Applied(imp.id, coveredFrom=parsed.coveredFrom, coveredTo=parsed.coveredTo)
    instruments: dict[str, Instrument] = {}
    crypto = atypes.GROUPS.get(account.type) == "crypto"
    for key, sec in parsed.securities.items():
        found = _option(s, account, sec, result) if sec.instrumentClass == "option" else None
        # What an exchange's or a wallet's file trades is crypto, whatever the file calls it;
        # a CSV names a security by its symbol alone, so its shape says what it is.
        cls = "crypto" if crypto and sec.instrumentClass == "other" else sec.instrumentClass
        if cls == "other" and parsed.format == "csv":
            cls = class_by_symbol(sec.symbol)
        instruments[key] = found or instrument(s, sec.symbol, sec.name, cls, sec.cusip)

    # Deleted rows first, so a live row with the same identity is the one found.
    existing = s.scalars(
        select(Transaction)
        .where(Transaction.accountId == account.id)
        .order_by(Transaction.deleted.desc())
    ).all()
    # What is here already, by the file's id, and by date, amount and payee for the rows
    # without one; rows the owner deleted too, so a file never brings one back (S1.3.2). A
    # FITID a file repeats is another row, kept as its second (`id#2`), and both are duplicate
    # suspects (S1.11.5).
    by_fit = {x.fitId: x for x in existing if x.fitId}
    before = {x.fitId for x in existing if x.fitId and not x.deleted}
    seen: dict[str, int] = {}
    loose: dict[tuple, list[Transaction]] = {}
    for x in reversed(existing):
        if not x.fitId:
            loose.setdefault(_loose_key(x.date, x.amount, x.payeeRaw), []).append(x)

    # An option's end in the file is settled after the trades that opened it, and the stock
    # trade the broker reports with an assignment or exercise is the one settling makes.
    legs = _stock_legs(s, parsed.rows, instruments)
    held_back = {id(r) for r in legs.values()}
    ends: list = []
    added: list[Transaction] = []
    for row in parsed.rows:
        inst = instruments.get(row.security) if row.security else None
        if row.fitId:
            seen[row.fitId] = seen.get(row.fitId, 0) + 1
            if seen[row.fitId] > 1:
                row.fitId = f"{row.fitId}#{seen[row.fitId]}"
        found = by_fit.get(row.fitId) if row.fitId else None
        if found is None:
            # A row typed by hand or brought by a file without ids is the same row.
            bucket = loose.get(_loose_key(row.date, row.amount, row.payee))
            found = bucket.pop(0) if bucket else None
            if found is not None and row.fitId:
                found.fitId = row.fitId
        if found is not None and found.deleted:
            # Deleted by its owner: matched, and left deleted as it was.
            result.matched += 1
            continue
        if found is not None:
            # Compared in cents, as stored: a file's sub-cent digits change nothing.
            if money.to_cents(found.amount) != money.to_cents(row.amount):
                found.amountWas, found.amount = found.amount, row.amount
                result.changed += 1
            else:
                result.matched += 1
            if row.runningBalance is not None:
                found.runningBalance = row.runningBalance
            continue
        if row.kind in OPTION_ENDS:
            ends.append(row)
            continue
        if id(row) in held_back:
            continue
        added.append(_add_row(s, account, user_id, imp, row, inst))
    s.flush()
    for row in ends:
        leg = legs.get(id(row))
        if leg is not None and leg.fitId in before:
            # Its stock trade came in with an earlier file, so settling would make it twice.
            result.warnings.append(
                f"{instruments[row.security].symbol} on {row.date:%b %-d, %Y}: its stock trade "
                "was imported before. Delete that trade, then settle the option on Positions."
            )
            continue
        added += _settle(s, account, user_id, imp, row, instruments, leg, result)
    result.added = len(added)
    s.flush()
    # A whole-number split imported takes the account's open options with it (S3.10.1).
    splits = [t for t in added if t.kind == "split" and t.instrumentId and t.splitRatio]
    if splits:
        from ...options import adjust

        for t in splits:
            adjust.with_split(s, user_id, account, t)
        s.flush()

    # A balance the file reports: an OFX file's, or a statement's opening and closing.
    source = "statement" if parsed.format == "statement" else "ofx"
    for day, balance in parsed.balances:
        if day:
            keep_anchor(s, account.id, day, balance, source, imp.id)
    # The file's positions: the holdings of an account kept by snapshots, and otherwise a
    # holdings check on Reconcile, the lots changing only through transactions (S1.3.3.8.2).
    s.flush()
    checked = parsed.positions and not lots.kept_by_snapshots(
        s.scalars(
            select(Transaction).where(
                Transaction.accountId == account.id, Transaction.deleted == false()
            )
        ).all(),
        s.scalars(select(Lot).where(Lot.accountId == account.id, Lot.deleted == false())).all(),
    )
    for pos in parsed.positions:
        inst = instruments.get(pos.security)
        if inst is None:
            result.warnings.append("a position names a security the file doesn't describe")
            continue
        keep_position(
            s,
            account.id,
            imp.id,
            pos.asOf,
            inst.id,
            (inst.symbol or inst.name or "")[:200],
            check=bool(checked),
            quantity=pos.quantity,
            marketValue=pos.marketValue,
        )
    for txn in added:
        if match_transfer(s, txn, account.ownerId):
            result.transfers += 1
    # The importer's rules, on the new bank rows that aren't transfers (S2.7.3).
    from .rules import Rules

    rules = Rules(s, user_id)
    if rules:
        result.categorised = sum(rules.apply(txn) for txn in added)
    imp.added, imp.matched, imp.changed = result.added, result.matched, result.changed
    activity.record(
        s,
        "account.imported",
        actor=user_id,
        subject_kind="account",
        subject_id=account.id,
        owner=account.ownerId,
        detail={
            "added": result.added,
            "matched": result.matched,
            "changed": result.changed,
            "format": parsed.format,
        },
    )
    if any(r.instrumentId for r in txns_made(s, imp.id)):
        from ... import washes

        s.flush()
        washes.recompute(s, account.ownerId)
    return result


OPTION_ENDS = ("expire", "assign", "exercise")


def _add_row(s: Session, account: Account, user_id: str, imp: Import, row, inst) -> Transaction:
    txn = Transaction(
        id=ids.new_id("Txn"),
        accountId=account.id,
        date=row.date,
        kind=row.kind,
        amount=row.amount,
        payee=_payee(row.payee),
        payeeRaw=row.payee,
        memo=row.memo,
        instrumentId=inst.id if inst else None,
        quantity=row.quantity,
        price=row.price,
        fees=row.fees,
        dividendType=row.dividendType,
        splitRatio=row.splitRatio,
        importId=imp.id,
        fitId=row.fitId,
        runningBalance=row.runningBalance,
        createdById=user_id,
        lotMethod=account.lotMethod if row.kind in lots.DISPOSALS else None,
        contributionYear=row.date.year if row.kind == "deposit" and _retirement(account) else None,
    )
    s.add(txn)
    s.flush()
    if inst and row.kind in ("buy", "reinvest", "transfer-in") and row.quantity:
        s.add(
            Lot(
                id=ids.new_id("Lot"),
                accountId=account.id,
                instrumentId=inst.id,
                transactionId=txn.id,
                acquiredOn=row.date,
                quantity=row.quantity,
                costBasis=-row.amount if row.kind != "transfer-in" else None,
                basisMissing=row.kind == "transfer-in",
            )
        )
    return txn


def _stock_legs(s: Session, rows: list, instruments: dict) -> dict[int, object]:
    """For each assignment or exercise in a file, the stock trade the broker reports with it:
    the one its RELFITID names, or else a buy or sell of the underlying that day, of the
    contracts' shares, on the side the option's end makes."""
    from ...options import contract_of

    trades = [r for r in rows if r.kind in ("buy", "sell") and r.security]
    by_fit = {r.fitId: r for r in trades if r.fitId}
    out: dict[int, object] = {}
    taken: set[int] = set()
    for row in rows:
        if row.kind not in ("assign", "exercise"):
            continue
        leg = by_fit.get(row.relFitId) if row.relFitId else None
        inst = instruments.get(row.security) if row.security else None
        c = contract_of(s, inst.id) if inst is not None else None
        if leg is None and c is not None and row.quantity:
            buys = (row.kind == "exercise") == (c.right == "call")
            leg = next(
                (
                    r
                    for r in trades
                    if id(r) not in taken
                    and r.date == row.date
                    and r.kind == ("buy" if buys else "sell")
                    and instruments[r.security].id == c.underlyingId
                    and r.quantity == row.quantity * c.multiplier
                ),
                None,
            )
        if leg is not None and id(leg) not in taken:
            out[id(row)] = leg
            taken.add(id(leg))
    return out


def _settle(s, account, user_id, imp, row, instruments, leg, result) -> list[Transaction]:
    """An option's end from a file, settled as Positions settles one (S3.4): the premium goes
    into the stock's basis or proceeds, and the broker's own stock trade, when the file has
    it, gives its cash and its id. One that can't be settled is named in a warning."""
    from ...errors import Problem
    from ...options import settle

    inst = instruments.get(row.security) if row.security else None
    word = {"expire": "expired", "assign": "assigned", "exercise": "exercised"}[row.kind]
    try:
        if inst is None:
            raise Problem(422, "not-an-option", "The file doesn't describe the option.")
        made = settle(
            s,
            user_id,
            account,
            inst,
            "expired" if row.kind == "expire" else row.kind,
            row.date,
            row.quantity,
        )
    except Problem as e:
        name = inst.symbol if inst is not None else "An option"
        result.warnings.append(
            f"{name} {word} on {row.date:%b %-d, %Y} wasn't recorded: {e.detail} Settle it on "
            "Positions."
        )
        if leg is None:
            return []
        return [_add_row(s, account, user_id, imp, leg, instruments.get(leg.security))]
    end = made[0]
    end.fitId, end.importId, end.memo = row.fitId, imp.id, row.memo
    stock = next((t for t in made[1:] if t.kind in ("buy", "sell")), None)
    if leg is not None and stock is not None:
        # The broker's cash, fees included, in place of the strike's: a buy's fees go into
        # the lot's basis; a sale's come off its proceeds through its amount.
        diff = leg.amount - stock.amount
        stock.amount, stock.fees, stock.fitId = leg.amount, leg.fees, leg.fitId
        stock.importId = imp.id
        if stock.kind == "buy" and diff:
            lot = s.scalars(select(Lot).where(Lot.transactionId == stock.id)).first()
            if lot is not None and lot.costBasis is not None:
                lot.costBasis -= diff
    s.flush()
    return made


def txns_made(s: Session, import_id: str) -> list[Transaction]:
    return list(
        s.scalars(
            select(Transaction).where(
                Transaction.importId == import_id, Transaction.deleted == false()
            )
        )
    )


def _loose_key(day: dt.date, amount: Decimal, payee: str | None) -> tuple:
    return (day, money.to_cents(amount), (payee or "").strip().lower())


def _payee(raw: str | None) -> str | None:
    return " ".join(raw.split()) if raw else None


def _retirement(account: Account) -> bool:
    from ...ledger.types import retirement

    return retirement(account.type)


def latest_activity(s: Session, account_ids: list[str]) -> dict[str, dt.datetime]:
    """When each account was last updated: its newest import or transaction."""
    if not account_ids:
        return {}
    rows = s.execute(
        select(Transaction.accountId, func.max(Transaction.updatedAt))
        .where(Transaction.accountId.in_(account_ids), Transaction.deleted == false())
        .group_by(Transaction.accountId)
    ).all()
    return dict(rows)


def search_instruments(s: Session, query: str, limit: int = 20) -> list[Instrument]:
    q = f"%{query.strip().upper()}%"
    return list(
        s.scalars(
            select(Instrument)
            .where(
                Instrument.deleted == false(),
                or_(Instrument.symbol.like(q), func.upper(Instrument.name).like(q)),
            )
            .order_by(Instrument.symbol)
            .limit(limit)
        )
    )
