"""Closed tax years (requirements S2.8): a year is closed for an account once a tax book that
counts the account has its federal return filed or accepted, and no amended federal return is
being prepared for it. A write that moves such a year's realized gains asks first; one made
anyway is kept on each tax book that closed the year (S2.8.3) until an amended federal return,
or No amendment needed, settles it (S8.15).

One check, run by every write before it commits (`check`, registered with
`store.commit_checks`; the filed tax years walk, decision 1): every write notes the households
it touches (`_track`); for each closed book of theirs, the book's gains by account as committed
and as written are compared. A move is asked of the person who wrote it: the save's question,
or a route's 409 `closed-year`, confirmed by the request's header
(`commit_checks.HEADER`). Work no one is there to answer (the server's own, or a file read in
the background, `unasked`) keeps the write and records it. No route makes a guard of its own,
so a new way of writing is checked as it is."""

import json
from decimal import Decimal

from sqlalchemy import event, false, inspect, select, update
from sqlalchemy.orm import Session

from .. import clock, ids
from ..errors import Problem
from ..store import commit_checks, scoping
from ..store.entities.accounts import Account
from ..store.entities.taxes import Filing, TaxBook, TaxBookChange
from . import books

FILED = ("filed", "accepted")
PREPARING = ("not started", "in progress", "rejected")
ZERO = Decimal(0)

TRACK = "closed-years: touched"  # noted on the write's connection: what it touched
DELETED = "closed-years: an account deleted"  # noted too: the question says to close instead
MODE = "closed-years: mode"  # session info: "confirmed", or "record" for work no one answers
CODE = "closed-year"


def closing_books(s: Session) -> list[TaxBook]:
    """The tax books that close their year: the federal return filed or accepted, and no
    amended federal return being prepared."""
    federal = (Filing.jurisdiction == "federal", Filing.deleted == false())
    filed = select(Filing.bookId).where(*federal, Filing.progress.in_(FILED))
    amending = select(Filing.bookId).where(
        *federal, Filing.amendsId.is_not(None), Filing.progress.in_(PREPARING)
    )
    return list(
        s.scalars(
            select(TaxBook).where(
                TaxBook.id.in_(filed), TaxBook.id.not_in(amending), TaxBook.deleted == false()
            )
        )
    )


def book_gains(s: Session, book: TaxBook) -> dict[str, Decimal]:
    """The book's realized gains by account: its Form 8949 rows' (S8.1), as the server reads
    them."""
    from . import panels

    rows, _ = panels.form_8949(s, book, panels.spouse_accounts(s, book))
    out: dict[str, Decimal] = {}
    for r in rows:
        if r.accountId:
            out[r.accountId] = out.get(r.accountId, ZERO) + (r.gain or ZERO)
    return out


def _named(moves: dict[int, Decimal]) -> str:
    def amount(v: Decimal) -> str:
        return f"{'−' if v < 0 else '+'}${abs(v):,.2f}"

    return " and ".join(f"{y} by {amount(v)}" for y, v in sorted(moves.items()))


def _keep_them(account_deleted: bool) -> str:
    return (
        " To keep them, close the account instead: a closed account keeps its history."
        if account_deleted
        else ""
    )


def question(moves: dict[int, Decimal], account_deleted: bool = False) -> str:
    """The save's question (S2.8.2), naming each year's move."""
    return (
        f"It changes the realized gains of {_named(moves)}, a year whose return is filed. The "
        "return may need amending, and the tax book will list the change."
        + _keep_them(account_deleted)
    )


def refusal(moves: dict[int, Decimal], account_deleted: bool = False) -> str:
    """A route's refusal, until the request says it is confirmed (S2.8.2)."""
    return (
        f"This changes the realized gains of {_named(moves)}, a year whose return is filed. "
        "Change it anyway? The return may need amending, and the tax book will list the change."
        + _keep_them(account_deleted)
    )


def closing_filing(s: Session, book: TaxBook) -> Filing | None:
    """The federal return that closes the book's year: an amended one filed, else the
    original (S8.15)."""
    filed = list(
        s.scalars(
            select(Filing).where(
                Filing.bookId == book.id,
                Filing.jurisdiction == "federal",
                Filing.deleted == false(),
                Filing.progress.in_(FILED),
            )
        )
    )
    amended = [f for f in filed if f.amendsId]
    pick = amended or filed
    return max(pick, key=lambda f: (f.filedOn or f.createdAt.date(), f.createdAt), default=None)


def as_filed(s: Session, book: TaxBook) -> tuple[dict[str, Decimal], set[str]] | None:
    """The book's gains by account when its return closed the year, and the changes already
    in them (S8.15)."""
    f = closing_filing(s, book)
    if f is None or not f.filedGains:
        return None
    kept = json.loads(f.filedGains)
    return {a: Decimal(v) for a, v in kept["gains"].items()}, set(kept["changes"])


def unexplained(s: Session, book: TaxBook, live: dict[str, Decimal]) -> dict[str, Decimal]:
    """By account, how far the book's gains differ from those filed with every change since
    added: a difference no write made here explains (a corrected rule, a restored backup),
    listed beside the changes (S8.15)."""
    # While an amended return is being prepared the year is open: nothing is measured.
    if book.id not in {b.id for b in closing_books(s)}:
        return {}
    filed = as_filed(s, book)
    if filed is None:
        return {}
    gains, known = filed
    expected = dict(gains)
    for c in _changes(s, book):
        if c.id not in known:
            expected[c.accountId] = expected.get(c.accountId, ZERO) + c.gains
    out = {}
    for a in set(expected) | set(live):
        d = live.get(a, ZERO) - expected.get(a, ZERO)
        if d:
            out[a] = d
    return out


def _changes(s: Session, book: TaxBook) -> list[TaxBookChange]:
    return list(
        s.scalars(
            select(TaxBookChange).where(
                TaxBookChange.bookId == book.id, TaxBookChange.deleted == false()
            )
        )
    )


def _keep_as_filed(s: Session, book: TaxBook, gains: dict[str, Decimal]) -> None:
    """The book's gains kept on the return that closed its year: written as the server's own,
    leaving the filing's version as the person last saved it."""
    from ..store.tables.taxes import Filing as FilingTable

    f = closing_filing(s, book)
    if f is None:
        return
    kept = {
        "gains": {a: str(v) for a, v in sorted(gains.items())},
        "changes": sorted(c.id for c in _changes(s, book)),
    }
    s.execute(
        update(FilingTable)
        .where(FilingTable.c.id == f.id)
        .values(filedGains=json.dumps(kept, sort_keys=True))
    )


LABEL = "closed-years: label"  # session info: the refusal's button, for the browser


def label(s: Session, text: str) -> None:
    """What the browser's question offers to do anyway (*Import anyway* at a statement's
    review); *Change it anyway* else."""
    s.info[LABEL] = text


def unasked(s: Session) -> None:
    """The write is work no one is there to answer (a file read in the background): a move of
    a closed year is kept and recorded, never refused."""
    s.info[MODE] = "record"


def confirm(s: Session) -> None:
    """The person confirmed the closed-year question: a move is made and recorded."""
    s.info[MODE] = "confirmed"


# ---- what a write touched ----

# What a gains figure is worked out from, and how each names who it belongs to.
_ACCOUNT = ("Transaction", "Lot", "CorporateAction", "Item", "Holding")
_INPUTS = (*_ACCOUNT, "Account", "LotPick", "WashSale", "Relationship", "TaxBook",
           "TaxBookAccount", "TaxBookFiler", "AccountShare", "Filing")  # fmt: skip


# A change to a record already kept moves gains only through these fields; anything else (a
# memo, a category, a bank transaction's payee) is never a closed-year question, and costs no
# check (S2.8.2: "a memo, a category asks nothing").
_FIELDS = {
    "Transaction": {"amount", "quantity", "price", "fees", "date", "kind", "instrumentId",
                    "deletedAt", "lotMethod", "transferId", "splitRatio", "optionTransactionId",
                    "proceedsAdjustment", "accountId"},
    "Account": {"deletedAt", "closedOn", "ownerId", "type", "lotMethod"},
    "Lot": {"quantity", "costBasis", "basisMissing", "acquiredOn", "deletedAt"},
    "Item": {"soldOn", "proceeds", "saleFees", "acquiredOn", "deletedAt", "personalUse"},
    "Filing": {"progress", "jurisdiction", "amendsId", "deletedAt"},
}  # fmt: skip


def _moves_gains(s: Session, obj, name: str) -> bool:
    """Whether a record's change can move gains: new or deleted, or changed in a field gains
    are worked out from; a bank transaction never."""
    if name == "Transaction" and not obj.instrumentId:
        was = inspect(obj).attrs.instrumentId.history.deleted
        if not any(was):
            return False
    if name == "Account" and obj in s.new:
        return False  # nothing in it yet
    if obj in s.new or obj in s.deleted or name not in _FIELDS:
        return True
    state = inspect(obj)
    return any(state.attrs[f].history.has_changes() for f in _FIELDS[name] if f in state.attrs)


@event.listens_for(Session, "before_flush")
def _track(s: Session, _ctx, _instances) -> None:
    touched = None
    for obj in (*s.new, *s.dirty, *s.deleted):
        name = type(obj).__name__
        if name not in _INPUTS or not _moves_gains(s, obj, name):
            continue
        touched = touched or commit_checks.notes(s).setdefault(TRACK, set())
        if name in _ACCOUNT:
            touched.add(("account", obj.accountId))
        elif name == "Account":
            touched.add(("owner", obj.ownerId))
            if inspect(obj).attrs.deletedAt.history.has_changes() and obj.deletedAt:
                commit_checks.notes(s)[DELETED] = True
        elif name == "LotPick":
            touched.add(("sale", obj.saleId))
        elif name == "WashSale":
            touched.add(("owner", obj.ownerId))
        elif name == "Relationship":
            touched |= {("person", obj.person1Id), ("person", obj.person2Id)}
        elif name == "TaxBook":
            touched.add(("book", obj.id))
        elif name in ("TaxBookAccount", "TaxBookFiler", "Filing"):
            touched.add(("book", obj.bookId))
            if name == "TaxBookAccount":
                touched.add(("account", obj.accountId))
        elif name == "AccountShare":
            touched.add(("account", obj.targetId))


def _households(s: Session, touched: set) -> tuple[set[str], set[str]]:
    """The users whose figures the write may move, with their spouses (whose trades wash
    theirs, S3.8), and the books it touched itself."""
    from .. import people, washes
    from ..store.entities.accounts import Transaction

    owners: set[str] = set()
    book_ids: set[str] = set()
    for kind, key in touched:
        if kind == "owner":
            owners.add(key)
        elif kind == "account":
            a = s.get(Account, key)
            if a is not None:
                owners.add(a.ownerId)
        elif kind == "sale":
            t = s.get(Transaction, key)
            a = s.get(Account, t.accountId) if t is not None else None
            if a is not None:
                owners.add(a.ownerId)
        elif kind == "person":
            u = people.user_of(s, key)
            if u is not None:
                owners.add(u.id)
        elif kind == "book":
            book_ids.add(key)
    household: set[str] = set()
    for o in owners:
        household |= set(washes.household(s, o))
    return household, book_ids


def _affected(s: Session, household: set[str], book_ids: set[str]) -> list[TaxBook]:
    out = []
    for b in closing_books(s):
        if b.id in book_ids:
            out.append(b)
            continue
        filers = {f.userId for f in books.filers(s, b)}
        if filers & household:
            out.append(b)
            continue
        counted = books.counted(s, b).accounts
        if any(a.ownerId in household for a in counted):
            out.append(b)
    return out


def check(s: Session) -> None:
    """Before a write commits: the closed books of the households it touched, their gains as
    committed and as written. A move is asked (`Problem` 409 `closed-year`, which the save turns
    into its question), or, confirmed or unasked, recorded on each book it moved."""
    notes = commit_checks.notes(s)
    touched = notes.pop(TRACK, None)
    if not touched:
        return
    with scoping.as_server(s, "closed years: the books a write may move", expire=False) as srv:
        household, book_ids = _households(srv, touched)
        affected = _affected(srv, household, book_ids)
        if not affected:
            return
        after = {b.id: book_gains(srv, b) for b in affected}
    from ..store.db import Database

    before: dict[str, dict[str, Decimal]] = {}
    with Database(s.get_bind()).read(unscoped="closed years: the books as committed") as r:
        was_closed = {x.id for x in closing_books(r)}
        for b in affected:
            was = r.get(TaxBook, b.id)
            if was is not None and was.id in was_closed:
                before[b.id] = book_gains(r, was)
    # A book this write closed (a return marked filed or accepted, an amended one filed) keeps
    # its gains as they are now: what later changes are measured from.
    with scoping.as_server(s, "closed years: the gains as filed", expire=False) as srv:
        for b in affected:
            if b.id not in before:
                _keep_as_filed(srv, b, after[b.id])
    moved = {
        (b, account): after[b.id].get(account, ZERO) - before[b.id].get(account, ZERO)
        for b in affected
        if b.id in before
        for account in set(after[b.id]) | set(before[b.id])
    }
    moved = {k: v for k, v in moved.items() if v}
    if not moved:
        return
    years = sorted({b.year for b, _ in moved})
    confirmed = CODE in commit_checks.confirmed.get() or s.info.get(MODE) == "confirmed"
    record = s.info.get(MODE) == "record" or scoping.user_of(s) is None
    if not (confirmed or record):
        by_year: dict[int, Decimal] = {}
        for (b, _), v in moved.items():
            by_year[b.year] = by_year.get(b.year, ZERO) + v
        gone = bool(notes.get(DELETED))
        extra = {
            "years": years,
            "moves": {str(y): str(v) for y, v in by_year.items()},
            "accountDeleted": gone,
            "confirm": s.info.get(LABEL, "Change it anyway"),
        }
        raise Problem(409, "closed-year", refusal(by_year, gone), extra=extra)
    by = scoping.user_of(s)
    # The book's own record of it, whoever wrote: the server's work, not the writer's own row.
    with scoping.as_server(s, "closed years: a move recorded on its book", expire=False) as srv:
        for (book, account), change in sorted(moved.items(), key=lambda x: (x[0][0].id, x[0][1])):
            srv.add(
                TaxBookChange(
                    id=ids.new_id("TxChg"),
                    bookId=book.id,
                    accountId=account,
                    gains=change,
                    madeById=by,
                )
            )
        srv.flush()


commit_checks.register(check)


def unsettled(s: Session, book: TaxBook) -> list[TaxBookChange]:
    """The edits made anyway since the book's federal return was filed, not yet settled."""
    return list(
        s.scalars(
            select(TaxBookChange)
            .where(
                TaxBookChange.bookId == book.id,
                TaxBookChange.settled.is_(None),
                TaxBookChange.deleted == false(),
            )
            .order_by(TaxBookChange.createdAt)
        )
    )


def settle(s: Session, book: TaxBook, by: str, how: str) -> None:
    """Settles the book's changes so far (S8.15): by an amended federal return (`amended`), or
    by No amendment needed (`not-needed`)."""
    now = clock.now()
    for change in unsettled(s, book):
        change.settled, change.settledAt, change.settledById = how, now, by
        change.updatedAt = now
