"""File retention and pruning (requirements S14.10): when each file of a receipt or statement
expires, worked out from when the records it is attached to ended (docs/schema.md §6) and their
retention periods, never stored; what Settings › Storage shows; and file pruning, which removes
expired files after a verified backup and keeps every record.

A record's end and period, by what the file is attached to:

- a transaction: ends on its date, or at the sale of the last share of a lot it made (open
  until then); its period is its category's (a subcategory takes its parent's), the longest of
  its splits', and none for a transfer or an uncategorised one;
- an account (a statement): ends with the statement's period (its date), or without one with
  the account's last transaction once closed; its period is Settings › Storage's *Keep
  statements for*;
- a physical-asset item ends at its sale; a qualified expense or a donation on its date; a gift
  given or received at the later of its occasion's year end and its purchase, else stays open;
  each takes its transaction's period, and has none without one.

A deleted record ended no later than its deletion. A file expires at the latest end plus the
longest period; with Keep on, attached to nothing, or with any record without a period, it is
kept for ever; while any record hasn't ended, it is kept while it is open.
"""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import clock, settings
from ..store.entities.accounts import Account, Category, Lot, Split, Transaction
from ..store.entities.assets import Item
from ..store.entities.education import Gift, QualifiedExpense
from ..store.entities.giving import Donation
from ..store.entities.receipts import Receipt, ReceiptLink
from ..store.repos import ledger as repo
from . import file_path

SOON_DAYS = 90
OPEN_WHAT = {
    "transaction": "the lot",
    "account": "the account",
    "item": "the item",
    "gift": "the gift",
}


def add_years(day: dt.date, years: int) -> dt.date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # Feb 29
        return day.replace(year=day.year + years, day=28)


@dataclass
class Retention:
    state: str  # forever, open, until, expired, pruned
    until: dt.date | None = None
    soon: bool = False  # within 90 days
    openWhat: str | None = None
    category: str | None = None  # the category, or Statements, that sets the period
    years: int | None = None
    link: str | None = None  # the link whose record sets the period

    @property
    def label(self) -> str:
        if self.state == "forever":
            return "Kept for ever"
        if self.state == "open":
            return f"Kept while {self.openWhat or 'what it belongs to'} is open"
        if self.state == "expired":
            return f"Expired {self.until:%b %Y}, prunable"
        if self.state == "until":
            return f"Kept until {self.until:%b %Y}"
        return "File pruned"


class Context:
    """What working out many files' retention reads once: categories, the statements' period,
    and each account's replayed lots."""

    def __init__(self, s: Session, today: dt.date | None = None):
        self.s = s
        self.today = today or clock.today()
        self.cats = {c.id: c for c in s.scalars(select(Category))}
        self.statements = settings.get(s, "keepStatementsYears")
        self._lot_ends: dict[str, dict[str, dt.date | None]] = {}

    def years(self, category_id: str | None) -> tuple[int | None, str | None]:
        """A category's period and the category that sets it; a subcategory without its own
        takes its parent's."""
        c = self.cats.get(category_id) if category_id else None
        seen = 0
        while c is not None and c.keepReceiptsYears is None and c.parentId and seen < 5:
            c, seen = self.cats.get(c.parentId), seen + 1
        if c is None or c.keepReceiptsYears is None:
            return None, None
        return c.keepReceiptsYears, c.name

    def lot_ends(self, account_id: str) -> dict[str, dt.date | None]:
        """Each lot's end in an account: the sale of its last share, None while open."""
        if account_id not in self._lot_ends:
            a = self.s.get(Account, account_id)
            ends: dict[str, dt.date | None] = {}
            if a is not None:
                rp = repo.load(self.s, a).replay()
                open_ids = {x.lotId for x in rp.open if x.lotId}
                for d in rp.disposals:
                    if d.lotId and d.lotId not in open_ids:
                        ends[d.lotId] = max(ends.get(d.lotId) or d.soldOn, d.soldOn)
                for lot_id in open_ids:
                    ends[lot_id] = None
            self._lot_ends[account_id] = ends
        return self._lot_ends[account_id]


def _deleted(row, end: dt.date | None) -> dt.date | None:
    if row.deletedAt is None:
        return end
    gone = row.deletedAt.date()
    return gone if end is None else min(end, gone)


def _transaction(ctx: Context, t: Transaction | None) -> tuple[dt.date | None, int | None, str]:
    """(end, period, category) of a transaction; a missing one ended long ago."""
    if t is None:
        return dt.date.min, None, ""
    end: dt.date | None = t.date
    for lot in ctx.s.scalars(select(Lot).where(Lot.transactionId == t.id)):
        lot_end = ctx.lot_ends(t.accountId).get(lot.id, t.date)
        end = None if lot_end is None or end is None else max(end, lot_end)
    end = _deleted(t, end)
    if t.transferId is not None or t.kind.startswith("transfer"):
        return end, None, ""
    splits = list(
        ctx.s.scalars(select(Split).where(Split.transactionId == t.id, Split.deleted == false()))
    )
    cats = [x.categoryId for x in splits] if splits else [t.categoryId]
    found = [ctx.years(c) for c in cats]
    if any(y is None for y, _ in found):
        return end, None, ""
    years, name = max(found, key=lambda x: x[0])
    return end, years, name or ""


def _link(ctx: Context, link: ReceiptLink, r: Receipt) -> tuple[dt.date | None, int | None, str]:
    s = ctx.s
    if link.kind == "transaction":
        return _transaction(ctx, s.get(Transaction, link.itemId))
    if link.kind == "account":
        # A statement ends with its period, which its date is (S1.3.3); one without a date
        # stays while its account is open.
        a = s.get(Account, link.itemId)
        if a is None:
            return dt.date.min, ctx.statements, "Statements"
        end = r.date
        if end is None and not a.active:
            last = s.scalar(
                select(Transaction.date)
                .where(Transaction.accountId == a.id, Transaction.deleted == false())
                .order_by(Transaction.date.desc())
            )
            end = last or a.updatedAt.date()
        return _deleted(a, end), ctx.statements, "Statements"
    row = {
        "item": Item,
        "expense": QualifiedExpense,
        "gift": Gift,
        "donation": Donation,
    }[link.kind]
    x = s.get(row, link.itemId)
    if x is None:
        return dt.date.min, None, ""
    txn = s.get(Transaction, x.transactionId) if getattr(x, "transactionId", None) else None
    _, years, name = _transaction(ctx, txn) if txn is not None else (None, None, "")
    if link.kind == "item":
        end = x.soldOn
    elif link.kind == "gift":
        if x.status in ("given", "received"):
            day = dt.date(x.occasionYear, 12, 31) if x.occasionYear else x.updatedAt.date()
            end = max(day, txn.date) if txn is not None else day
        else:
            end = None
    else:
        end = x.date
    return _deleted(x, end), years, name


def retention(ctx: Context, r: Receipt) -> Retention:
    if r.filePrunedAt is not None:
        return Retention("pruned")
    if r.keep:
        return Retention("forever")
    links = list(
        ctx.s.scalars(
            select(ReceiptLink).where(ReceiptLink.receiptId == r.id, ReceiptLink.deleted == false())
        )
    )
    if not links:
        return Retention("forever")
    found = [(_link(ctx, x, r), x.kind, x.id) for x in links]
    if any(years is None for (_, years, _), _, _ in found):
        return Retention("forever")
    open_ = [kind for (end, _, _), kind, _ in found if end is None]
    if open_:
        return Retention("open", openWhat=OPEN_WHAT.get(open_[0]))
    end = max(e for (e, _, _), _, _ in found)
    (_, years, name), _, by = max(found, key=lambda f: f[0][1])
    if end == dt.date.min:
        end = r.createdAt.date()
    until = add_years(end, years)
    if until <= ctx.today:
        return Retention("expired", until, category=name, years=years, link=by)
    soon = (until - ctx.today).days <= SOON_DAYS
    return Retention("until", until, soon, category=name, years=years, link=by)


# ---------- Settings › Storage (S14.10.4) ----------


def _size(receipts_dir: Path, file_id: str) -> int:
    p = file_path(receipts_dir, file_id)
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _dir_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


@dataclass
class Group:
    files: int = 0
    bytes: int = 0


@dataclass
class Storage:
    receiptsBytes: int
    expired: Group
    later: Group  # expiring later, or kept while open
    forever: Group
    pruned: int
    byYear: dict[int, dict[str, Group]] = field(default_factory=dict)  # coming years
    expiredBy: dict[str, Group] = field(default_factory=dict)  # by category, to prune
    # Files in the receipts directory that no receipt row names, deleted rows included: left
    # behind when an older database was restored under files written later (S14.6).
    orphans: Group = field(default_factory=Group)


def storage(s: Session, receipts_dir: Path, today: dt.date | None = None) -> Storage:
    ctx = Context(s, today)
    out = Storage(_dir_bytes(receipts_dir), Group(), Group(), Group(), 0)
    years: dict[int, dict[str, Group]] = defaultdict(lambda: defaultdict(Group))
    seen_files: set[str] = set()
    for r in s.scalars(select(Receipt).where(Receipt.deleted == false())):
        rt = retention(ctx, r)
        if rt.state == "pruned":
            out.pruned += 1
            continue
        # A file shared by several receipts counts once, with the first.
        size = 0 if r.fileId in seen_files else _size(receipts_dir, r.fileId)
        seen_files.add(r.fileId)
        g = {"expired": out.expired, "forever": out.forever}.get(rt.state, out.later)
        g.files += 1
        g.bytes += size
        if rt.state == "expired":
            e = out.expiredBy.setdefault(rt.category or "Other", Group())
            e.files += 1
            e.bytes += size
        elif rt.state == "until":
            y = years[rt.until.year][rt.category or "Other"]
            y.files += 1
            y.bytes += size
    out.byYear = {k: dict(v) for k, v in sorted(years.items())}
    for p in orphan_files(s, receipts_dir):
        out.orphans.files += 1
        out.orphans.bytes += p.stat().st_size
    return out


def orphan_files(s: Session, receipts_dir: Path) -> list[Path]:
    """The files no receipt row names, deleted rows included (S9.7)."""
    if not receipts_dir.is_dir():
        return []
    named = {fid for (fid,) in s.execute(select(Receipt.fileId)) if fid}
    return sorted(p for p in receipts_dir.glob("*.mkr") if p.stem not in named)


def remove_orphans(srv, s: Session) -> tuple[int, int]:
    """Remove the orphan files, by the receipts folder's one sweep rule (filestore.py): never
    one an upload is still writing, nor one younger than the grace. The count and bytes freed."""
    receipts_dir = srv.config.receipts_dir

    def named() -> set[str]:
        return {f"{fid}.mkr" for (fid,) in s.execute(select(Receipt.fileId)) if fid}

    gone = srv.files.of(receipts_dir).sweep(named, (".mkr",))
    return len(gone), sum(size for _, size in gone)


def prunable(s: Session, categories: list[str] | None, today: dt.date | None = None):
    """The expired receipts, of the categories named (all when none are)."""
    ctx = Context(s, today)
    out = []
    for r in s.scalars(select(Receipt).where(Receipt.deleted == false())):
        rt = retention(ctx, r)
        if rt.state == "expired" and (categories is None or (rt.category or "Other") in categories):
            out.append(r)
    return out


def prune_files(srv, s: Session, rows: list[Receipt], by: str) -> int:
    """Mark the receipts pruned and remove each file no receipt still needs, but one an upload
    is reusing this moment (filestore.py); the bytes freed."""
    receipts_dir = srv.config.receipts_dir
    store = srv.files.of(receipts_dir)
    now = clock.now()
    for r in rows:
        r.filePrunedAt, r.filePrunedById, r.thumbnail = now, by, None
    s.flush()
    freed = 0
    for file_id in {r.fileId for r in rows}:
        # Needed only by a live receipt: a deleted one doesn't count (S14.10.5).
        still = s.scalar(
            select(Receipt.id).where(
                Receipt.fileId == file_id,
                Receipt.filePrunedAt.is_(None),
                Receipt.deleted == false(),
            )
        )
        if still is not None:
            continue
        freed += store.remove(file_path(receipts_dir, file_id).name)
    return freed
