"""The tax panels (requirements S8.1–S8.13): for one tax book's accounts and year, Form 8949
rows with wash sales and Schedule D totals, income, retirement, deductions and credits, giving,
education, gifts, loans, physical assets, and the missing or doubtful data to look at. Figures
and their sources only: MoolaKata never computes the tax."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import assets, education, gifts, giving, loans, people
from ..ledger import lots
from ..ledger import types as atypes
from ..money import grouped
from ..projections import taxtables
from ..store.entities.accounts import (
    Account,
    Category,
    Instrument,
    Lot,
    OptionContract,
    Split,
    Transaction,
)
from ..store.entities.assets import Item
from ..store.entities.receipts import ReceiptLink
from ..store.entities.taxes import EstimatedPayment, TaxBook
from ..store.entities.users import User
from ..store.repos import ledger as repo
from . import books, closed, dependents

ZERO = Decimal(0)
CENT = Decimal("0.01")
WASH_DAYS = 30
# The Uniform Lifetime Table's distribution periods (Treas. Reg. 1.401(a)(9)-9), ages 72–100.
UNIFORM = {
    72: 27.4, 73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9, 78: 22.0, 79: 21.1, 80: 20.2,
    81: 19.4, 82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2, 87: 14.4, 88: 13.7, 89: 12.9,
    90: 12.2, 91: 11.5, 92: 10.8, 93: 10.1, 94: 9.5, 95: 8.9, 96: 8.4, 97: 7.8, 98: 7.3,
    99: 6.8, 100: 6.4,
}  # fmt: skip


def _span(year: int) -> tuple[dt.date, dt.date]:
    return dt.date(year, 1, 1), dt.date(year, 12, 31)


# ---------- Form 8949 and Schedule D (S8.1, S8.3, S8.13) ----------


@dataclass
class Row:
    """One Form 8949 line."""

    description: str
    acquired: dt.date | None
    sold: dt.date
    proceeds: Decimal
    basis: Decimal | None
    code: str  # adjustment codes: W wash sale, L nondeductible loss, C collectible
    adjustment: Decimal
    longTerm: bool
    box: str  # A–C short term, D–F long term (S8.1)
    account: str
    collectable: bool = False
    saleId: str | None = None
    instrumentId: str | None = None
    quantity: Decimal | None = None
    accountId: str | None = None
    acquiredMissing: bool = False  # shares moved in whose day bought isn't known (S2.2)
    # What was sold: a holding (shares, a fund, a coin), a return of capital past its basis,
    # an option, or a physical item; the panels group by it, never by the words.
    kind: str = "holding"
    lotMissing: bool = False  # sold without a lot to match: its day bought is missing (S8.1)

    @property
    def gain(self) -> Decimal | None:
        if self.basis is None:
            return None
        return (self.proceeds - self.basis + self.adjustment).quantize(CENT)


@dataclass
class Wash:
    """A loss disallowed because the same instrument was bought within 30 days (S3.8)."""

    sold: dt.date
    symbol: str
    account: str
    loss: Decimal
    disallowed: Decimal
    replacedOn: dt.date
    replacementAccount: str
    replacementQty: Decimal
    adjustedBasis: Decimal | None  # the replacement lot's basis with the loss added
    review: bool = False  # options on the same underlying: for the preparer to decide


# Digital assets' basis reporting on Form 1099-DA: brokers report the gross proceeds of sales
# from 2025, and the basis of what was acquired from 2026 and held with them (i8949, 2025).
DIGITAL_BOXES_FROM = 2025
DIGITAL_BASIS_FROM = dt.date(2026, 1, 1)


def box_of(long_term: bool, inst_class: str, account_type: str, acquired, year: int) -> str:
    """A sale's 8949 box (S8.1). From 2025 a digital asset has boxes of its own, never C or F:
    G/J with its basis on a 1099-DA, H/K without, I/L with no 1099-DA (a self-custody
    wallet's). Before, it goes in A to F as a security would."""
    crypto = inst_class == "crypto"
    if crypto and year >= DIGITAL_BOXES_FROM:
        if account_type == "crypto-wallet":
            return "L" if long_term else "I"
        if acquired is not None and acquired >= DIGITAL_BASIS_FROM:
            return "J" if long_term else "G"
        return "K" if long_term else "H"
    return _box(long_term, not crypto, _covered(inst_class, acquired) if acquired else False)


def _box(long_term: bool, reported: bool, covered: bool) -> str:
    """The 8949 box the broker's reporting decides: basis reported (A/D), not reported
    (B/E), or no 1099-B at all (C/F)."""
    if not reported:
        return "F" if long_term else "C"
    if not covered:
        return "E" if long_term else "B"
    return "D" if long_term else "A"


def _taxable(accounts: list[Account]) -> list[Account]:
    return [a for a in accounts if atypes.TAX.get(a.type) == "taxable"]


def _covered(cls: str, acquired: dt.date) -> bool:
    """Whether the broker reports the basis: equities from 2011, funds from 2012, other
    securities from 2014."""
    if cls == "equity":
        return acquired >= dt.date(2011, 1, 1)
    if cls in ("etf", "mutual-fund"):
        return acquired >= dt.date(2012, 1, 1)
    return acquired >= dt.date(2014, 1, 1)


def form_8949(s: Session, book: TaxBook, spouse_accounts: list[Account] | None = None):
    """Every sale in the book's taxable accounts in the year, and each sold item, as 8949 rows.
    A wash sale's disallowed loss (worked out across the filers' accounts, IRAs included, and a
    spouse's, S3.8) is the row's W adjustment; options on the same underlying bought or sold
    within 30 days are flagged for review, not decided."""
    first, last = _span(book.year)
    counted = books.counted(s, book).accounts
    rows: list[Row] = []
    insts: dict[str, Instrument] = {}
    losses: dict[str, Decimal] = {}
    for a in _taxable(counted):
        if a.type not in ("brokerage", "crypto-exchange", "crypto-wallet"):
            continue
        led = repo.load(s, a)
        for d in led.replay().disposals:
            if not first <= d.soldOn <= last:
                continue
            # The session keeps what it has read: a second get of an instrument reads nothing.
            inst = s.get(Instrument, d.instrumentId)
            insts[inst.id] = inst
            proceeds, basis = d.proceeds, d.basis
            if d.written and d.basis is not None:
                # A written option: the premium received is the proceeds and what closing it
                # cost the basis, both as paid (IRS Pub. 550, options).
                proceeds, basis = -d.basis, -d.proceeds
            row = Row(
                description=f"{inst.symbol} return of capital over basis"
                if d.method == "return-of-capital"
                else f"{_qty(d.quantity)} {inst.symbol}",
                # VARIOUS when not known: a stand-in's, or shares moved in without it (S2.2)
                # Missing when sold without a lot to match (CR3-415).
                acquired=None if d.standIn or d.acquiredMissing or d.lotMissing else d.acquiredOn,
                sold=d.soldOn,
                proceeds=proceeds,
                basis=basis,
                code="W" if d.adjustment else "",
                adjustment=d.adjustment,
                longTerm=d.longTerm,
                box=box_of(d.longTerm, inst.instrumentClass, a.type, d.acquiredOn, book.year),
                account=a.name,
                accountId=a.id,
                saleId=d.saleId,
                instrumentId=inst.id,
                quantity=d.quantity,
                acquiredMissing=d.acquiredMissing,
                lotMissing=d.lotMissing,
                kind="return-of-capital"
                if d.method == "return-of-capital"
                else "option"
                if inst.instrumentClass == "option"
                else "holding",
            )
            if d.basis is not None and d.saleId and d.proceeds < d.basis:
                losses[d.saleId] = losses.get(d.saleId, ZERO) + d.basis - d.proceeds
            rows.append(row)
    if book.bitcoinFees == "not-taxed":
        rows = [r for r in rows if not _own_transfer_fee(s, r.saleId)]
    washes_ = _stored_washes(s, book, losses, {a.id for a in counted})
    washes_ += _option_reviews(s, rows, counted + (spouse_accounts or []), insts)
    rows += _items(s, counted, first, last)
    return rows, washes_


def _own_transfer_fee(s: Session, sale_id: str | None) -> bool:
    """A network fee's sale (S8.19) on a transfer between the owner's own accounts."""
    t = s.get(Transaction, sale_id) if sale_id else None
    if t is None or not (t.fitId or "").startswith("btcfee:") or not t.optionTransactionId:
        return False
    out = s.get(Transaction, t.optionTransactionId)
    return out is not None and out.transferId is not None


def _stored_washes(
    s: Session, book: TaxBook, losses: dict[str, Decimal], counted: set[str]
) -> list[Wash]:
    """The book's wash sales: of the sales in the accounts it counts (CR3-393), an added
    account's too, whoever owns it (S8.14.2), read together (one query for each kind of
    record, however many there are: the walk's decision 3.6)."""
    from .. import washes

    first, last = _span(book.year)
    found = washes.for_accounts(s, counted, first, last)
    if not found:
        return []
    wanted = {w.saleId for w in found} | {w.replacementId for w in found}
    txns = {t.id: t for t in s.scalars(select(Transaction).where(Transaction.id.in_(wanted)))}
    lots_by = {
        x.transactionId: x
        for x in s.scalars(
            select(Lot).where(Lot.transactionId.in_({w.replacementId for w in found}))
        )
    }
    accts = {
        a.id: a
        for a in s.scalars(
            select(Account).where(Account.id.in_({t.accountId for t in txns.values()}))
        )
    }
    insts = {
        i.id: i
        for i in s.scalars(
            select(Instrument).where(Instrument.id.in_({t.instrumentId for t in txns.values()}))
        )
    }
    out = []
    for w in found:
        sale, repl = txns[w.saleId], txns[w.replacementId]
        lot = lots_by.get(repl.id)
        into = accts[repl.accountId]
        basis = None
        if lot is not None and lot.costBasis is not None and lot.quantity:
            basis = (lot.costBasis * w.quantity / lot.quantity).quantize(CENT)
            # In an IRA the loss is lost for good, never added (S3.8.3).
            if lots.adds_basis(into.type):
                basis += w.disallowed
        out.append(
            Wash(
                sale.date,
                insts[sale.instrumentId].symbol,
                accts[sale.accountId].name,
                losses.get(sale.id, w.disallowed),
                w.disallowed,
                repl.date,
                into.name,
                w.quantity,
                basis,
            )
        )
    return out


def _option_reviews(s: Session, rows: list[Row], accounts: list[Account], insts) -> list[Wash]:
    """A loss sale of a stock with an option on it bought within 30 days, or an option's loss
    with its stock bought: flagged for the preparer (S3.8, S8.3)."""
    from .. import options as opts

    ids_ = {a.id: a for a in accounts}
    out = []

    def first(near, *where) -> Transaction | None:
        return s.scalars(select(Transaction).where(*near, *where)).first()

    # The rows are the sales of the accounts given, each of an instrument in `insts`.
    for r in rows:
        if r.gain is None or r.gain >= 0:
            continue
        inst = insts[r.instrumentId]
        near = (
            Transaction.accountId.in_(list(ids_)),
            Transaction.deleted == false(),
            Transaction.date >= r.sold - dt.timedelta(days=WASH_DAYS),
            Transaction.date <= r.sold + dt.timedelta(days=WASH_DAYS),
        )
        if inst.instrumentClass == "option":
            # Its stock bought; an option with no contract (a file's, unread) has none.
            c = opts.contract_of(s, inst.id)
            targets = [c.underlyingId] if c else []
            hit = first(
                near,
                Transaction.instrumentId.in_(targets),
                Transaction.kind.in_(("buy", "reinvest")),
            )
        else:
            on_it = [
                oc.instrumentId
                for oc in s.scalars(
                    select(OptionContract).where(OptionContract.underlyingId == inst.id)
                )
            ]
            # An option on it bought, or the stock bought back through an option: a put
            # assigned, a call exercised.
            ends = select(Transaction.id).where(Transaction.kind.in_(("assign", "exercise")))
            hit = first(
                near, Transaction.instrumentId.in_(on_it), Transaction.kind == "buy-to-open"
            ) or first(
                near,
                Transaction.instrumentId == inst.id,
                Transaction.kind == "buy",
                Transaction.optionTransactionId.in_(ends),
            )
        if hit is not None:
            out.append(
                Wash(
                    r.sold,
                    inst.symbol,
                    r.account,
                    -r.gain,
                    ZERO,
                    hit.date,
                    ids_[hit.accountId].name,
                    abs(hit.quantity or ZERO),
                    None,
                    review=True,
                )
            )
    return out


def _qty(q: Decimal) -> str:
    return f"{q.normalize():f}"


def _items(s: Session, accounts: list[Account], first: dt.date, last: dt.date) -> list[Row]:
    """Physical assets sold (S8.13): collectables marked; a personal-use loss not deductible
    (code L)."""
    out = []
    phys = {a.id: a for a in accounts if assets.is_physical(a.type)}
    if not phys:
        return out
    for it in s.scalars(
        select(Item).where(
            Item.accountId.in_(list(phys)),
            Item.deleted == false(),
            Item.soldOn >= first,
            Item.soldOn <= last,
        )
    ):
        a = phys[it.accountId]
        d = assets.details(s, [it])[it.id]
        basis = assets.basis(it, d, it.soldOn)
        proceeds = it.proceeds - (it.saleFees or ZERO)
        long_term = lots.long_term(it.acquiredOn, it.soldOn)
        collectable = assets.is_collectable(a.type, it)
        gain = proceeds - basis
        code, adj = ("C" if collectable else ""), ZERO
        if gain < 0 and it.personalUse:
            code, adj = "L", -gain
        out.append(
            Row(
                description=it.name,
                acquired=it.acquiredOn,
                sold=it.soldOn,
                proceeds=proceeds,
                basis=basis,
                code=code,
                adjustment=adj,
                longTerm=long_term,
                box="F" if long_term else "C",
                account=a.name,
                accountId=a.id,
                collectable=collectable,
                kind="item",
            )
        )
    return out


@dataclass
class ScheduleD:
    byBox: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]]  # proceeds, basis, adj, gain
    shortTerm: Decimal
    longTerm: Decimal
    collectables: Decimal  # long-term collectables gain, taxed at its own rate
    carryoverShort: Decimal
    carryoverLong: Decimal

    @property
    def net(self) -> Decimal:
        return self.shortTerm + self.longTerm - self.carryoverShort - self.carryoverLong


def schedule_d(s: Session, book: TaxBook, rows: list[Row]) -> ScheduleD:
    by: dict[str, list[Decimal]] = {}
    for r in rows:
        t = by.setdefault(r.box, [ZERO, ZERO, ZERO, ZERO])
        t[0] += r.proceeds
        t[1] += r.basis or ZERO
        t[2] += r.adjustment
        t[3] += r.gain or ZERO
    short, long_, _ = books.carryover(s, book)
    return ScheduleD(
        byBox={k: tuple(v) for k, v in sorted(by.items())},
        shortTerm=sum((r.gain or ZERO for r in rows if not r.longTerm), ZERO),
        longTerm=sum((r.gain or ZERO for r in rows if r.longTerm), ZERO),
        collectables=sum((r.gain or ZERO for r in rows if r.longTerm and r.collectable), ZERO),
        carryoverShort=short,
        carryoverLong=long_,
    )


# ---------- Income (S8.5) ----------


@dataclass
class Income:
    interest: list[tuple[str, Decimal]]  # by payer
    ordinary: Decimal
    qualified: Decimal
    capitalGainDistributions: Decimal
    returnOfCapital: Decimal
    byPayer: list[tuple[str, Decimal]]  # dividends by payer
    # Foreign tax paid by payer (1099-DIV box 7), and crypto received as income, at its value
    # when received, by account (S8.5, CR3-38).
    foreignTax: list[tuple[str, Decimal]]
    crypto: list[tuple[str, Decimal]]


def income(s: Session, book: TaxBook) -> Income:
    first, last = _span(book.year)
    interest: dict[str, Decimal] = defaultdict(lambda: ZERO)
    divs: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_payer: dict[str, Decimal] = defaultdict(lambda: ZERO)
    foreign: dict[str, Decimal] = defaultdict(lambda: ZERO)
    crypto: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for a in _taxable(books.counted(s, book).accounts):
        payer = a.institution or a.name
        rewards = {
            lot.transactionId: lot.costBasis
            for lot in repo.load(s, a).lots
            if lot.costBasis is not None
        }
        for t in s.scalars(
            select(Transaction).where(
                Transaction.accountId == a.id,
                Transaction.deleted == false(),
                Transaction.kind.in_(
                    (
                        "interest",
                        "dividend",
                        "reinvest",
                        "capital-gain",
                        "return-of-capital",
                        "foreign-tax",
                        "reward",
                    )
                ),
                Transaction.date >= first,
                Transaction.date <= last,
            )
        ):
            if t.kind == "foreign-tax":
                foreign[payer] -= t.amount
            elif t.kind == "reward":
                # Ordinary income at its value when received, the basis of its lot (S8.5).
                crypto[a.name] += rewards.get(t.id, ZERO)
            elif t.kind == "interest":
                interest[payer] += t.amount
            elif t.kind == "capital-gain":
                divs["capital-gain"] += t.amount
                by_payer[payer] += t.amount
            elif t.kind == "return-of-capital":
                # 1099-DIV box 3: off the basis, not a dividend on Schedule B (CR3-402).
                divs["return-of-capital"] += abs(t.amount)
            elif t.kind in ("dividend", "reinvest"):
                # A reinvested dividend is a dividend too, ordinary unless typed (CR3-392).
                amount = t.amount if t.kind == "dividend" else -t.amount
                divs[t.dividendType or "ordinary"] += amount
                by_payer[payer] += amount
    return Income(
        interest=sorted(((k, v) for k, v in interest.items() if v), key=lambda x: -x[1]),
        # Qualified dividends are part of ordinary dividends (1099-DIV box 1a includes 1b).
        ordinary=divs["ordinary"] + divs["qualified"],
        qualified=divs["qualified"],
        capitalGainDistributions=divs["capital-gain"],
        returnOfCapital=divs["return-of-capital"],
        byPayer=sorted(((k, v) for k, v in by_payer.items() if v), key=lambda x: -x[1]),
        foreignTax=sorted(((k, v) for k, v in foreign.items() if v), key=lambda x: -x[1]),
        crypto=sorted(((k, v) for k, v in crypto.items() if v), key=lambda x: -x[1]),
    )


# ---------- Retirement (S8.6) ----------


@dataclass
class Contribution:
    account: str
    kind: str
    owner: str
    contributed: Decimal
    limit: Decimal | None
    note: str
    # A limit is a person's, across their accounts of its kind (S8.6): what they put in all of
    # them, which the limit is held against.
    personTotal: Decimal = ZERO
    group: str = ""
    ownerId: str = ""


@dataclass
class Rmd:
    account: str
    owner: str
    age: int
    balance: Decimal  # at the end of last year
    factor: float
    due: Decimal


@dataclass
class Movement:
    """Money moved between retirement accounts (S8.6): a rollover, or a conversion to Roth
    with the part of it that is taxed by Form 8606's pro rata rule, when the basis is known."""

    kind: str  # "rollover" or "conversion"
    date: dt.date
    fromAccount: str
    toAccount: str
    amount: Decimal
    taxable: Decimal | None = None
    fromId: str | None = None  # the account it left, when the book counts it
    waiting: str | None = None  # what the taxed part waits for, said to the user


@dataclass
class Basis8606:
    """A filer's Form 8606 basis (S8.6): carried from last year (line 2), none until typed, and
    this year's nondeductible contributions (line 1), which wait while any is undecided."""

    ownerId: str
    owner: str
    carried: Decimal | None
    nondeductible: Decimal
    undecided: int  # contributions still to mark deductible or not


@dataclass
class Retirement:
    contributions: list[Contribution]
    distributions: list[tuple[str, Decimal]]
    rmds: list[Rmd]
    bases: list[Basis8606]
    conversions: list[Movement]
    rollovers: list[Movement]


# Which accounts share one limit: a person's IRAs, traditional and Roth; their 401(k) and
# 403(b) deferrals; a 457(b) has a limit of its own; and an HSA.
LIMIT_GROUPS = {
    "ira": "ira",
    "roth-ira": "ira",
    "401k": "deferral",
    "403b": "deferral",
    "457b": "457b",
    "hsa": "hsa",
}
GROUP_LABELS = {"ira": "IRAs", "deferral": "401(k) and 403(b) deferrals", "457b": "457(b)s"}


def retirement(s: Session, book: TaxBook) -> Retirement:
    from . import retirement as moves

    y = book.year
    first, last = _span(y)
    figures = taxtables.figures(s, y)
    accounts = [a for a in books.counted(s, book).accounts if atypes.retirement(a.type)]
    contributions, distributions, rmds = [], [], []
    moved: dict[frozenset, Movement] = {}
    taken_from: dict[str, Decimal] = {}  # distributions by account id
    # Form 8606 line 1, each owner's: the nondeductible parts of their own contributions to a
    # traditional IRA for the year, and how many are still to decide (S8.6).
    nondeductible: dict[str, Decimal] = defaultdict(lambda: ZERO)
    undecided: dict[str, int] = defaultdict(int)
    for a in accounts:
        owner = s.get(User, a.ownerId)
        born = people.birth_year(s, a.ownerId)
        age = y - born if born else None
        # Each movement classified once (CR3-37): what counts against a limit is a
        # contribution, never a rollover or a conversion.
        put = employer = taken = ZERO
        for t in s.scalars(
            select(Transaction).where(
                Transaction.accountId == a.id,
                Transaction.deleted == false(),
                Transaction.instrumentId.is_(None),
                Transaction.kind.in_(moves.CASH_KINDS),
            )
        ):
            what = moves.classify(s, t, a)
            year = t.contributionYear or t.date.year
            if what == "employee" and year == y:
                put += t.amount
                if a.type == "ira":
                    for amount, mark in _marks(s, t):
                        if mark is None:
                            undecided[a.ownerId] += 1
                        elif not mark:
                            nondeductible[a.ownerId] += amount
            elif what == "employer" and year == y:
                employer += t.amount
            elif not first <= t.date <= last:
                continue
            elif what == "distribution":
                taken -= t.amount
            elif what in ("rollover", "conversion", "rollover-out", "conversion-out"):
                # Money out is a rollover or a conversion only by its other half's account;
                # money in may be one by the source set on it, from an account not here.
                other = moves.other_account(s, t)
                there = other.name if other else "another account"
                ends = (a.name, there) if what.endswith("-out") else (there, a.name)
                source = a if what.endswith("-out") else other
                key = frozenset({t.id, t.transferId or t.id})
                moved.setdefault(
                    key,
                    Movement(
                        what.removesuffix("-out"),
                        t.date,
                        *ends,
                        abs(t.amount),
                        fromId=source.id if source is not None else None,
                    ),
                )
        counted = put + employer if a.type == "hsa" else put
        limit, note = None, ""
        if a.type in ("ira", "roth-ira"):
            limit = Decimal(str(figures["iraLimit"]))
            if age and age >= 50:
                limit += Decimal(str(figures["iraCatchUp"]))
                note = "with the catch-up at 50 and over"
            if a.type == "roth-ira":
                note = (note + "; " if note else "") + "Roth eligibility depends on MAGI"
        elif a.type in ("401k", "403b", "457b"):
            limit = Decimal(str(figures["k401Deferral"]))
            if age and 60 <= age <= 63:
                limit += Decimal(str(figures["k401CatchUp6063"]))
                note = "with the catch-up at 60–63"
            elif age and age >= 50:
                limit += Decimal(str(figures["k401CatchUp"]))
                note = "with the catch-up at 50 and over"
        elif a.type == "hsa":
            # Employee and employer money both count against an HSA's limit, which its
            # coverage sets, with $1,000 more at 55 (S8.6).
            if a.hsaCoverage == "self":
                limit, note = Decimal(str(figures["hsaSelf"])), "self-only coverage"
            else:
                limit = Decimal(str(figures["hsaFamily"]))
                note = "family coverage" if a.hsaCoverage else "the family limit: set the coverage"
            if age and age >= 55:
                limit += Decimal(str(figures["hsaCatchUp"]))
                note += "; with the catch-up at 55 and over"
            if employer:
                note += f"; {grouped(employer)} of it from the employer"
        if counted or limit:
            contributions.append(
                Contribution(
                    a.name,
                    atypes.LABELS[a.type],
                    owner.displayName,
                    counted,
                    limit,
                    note,
                    group=LIMIT_GROUPS[a.type],
                    ownerId=owner.id,
                )
            )
        if taken:
            distributions.append((a.name, taken))
            taken_from[a.id] = taken
        rmd_age = Decimal(str(figures["rmdAge"]))  # 70½ until 2019
        if age and age >= rmd_age and a.type in ("ira", "401k", "403b", "457b") and age in UNIFORM:
            from .. import valuation

            led = repo.load(s, a)
            bal = valuation.account_value(s, led, True, dt.date(y - 1, 12, 31))
            factor = UNIFORM[age]
            rmds.append(
                Rmd(
                    a.name,
                    owner.displayName,
                    age,
                    bal,
                    factor,
                    (bal / Decimal(str(factor))).quantize(CENT),
                )
            )
    totals: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for c in contributions:
        totals[(c.ownerId, c.group)] += c.contributed
    for c in contributions:
        c.personTotal = totals[(c.ownerId, c.group)]
    # The 8606 basis is a person's own (S8.6, S8.17): each filer's as their return carried it,
    # a joint return's each filer's apart.
    carried: dict[str, Decimal] = {}
    for figs, _ in books.federal_figures(s, book):
        for owner_id, v in (figs.get("basis8606") or {}).items():
            carried[owner_id] = Decimal(str(v))
    iras = [a for a in accounts if a.type == "ira"]
    owners = list(dict.fromkeys(a.ownerId for a in iras))
    names = books.names(s, owners)
    bases = [Basis8606(o, names[o], carried.get(o), nondeductible[o], undecided[o]) for o in owners]
    conversions = sorted(
        (m for m in moved.values() if m.kind == "conversion"), key=lambda m: m.date
    )
    rollovers = sorted((m for m in moved.values() if m.kind == "rollover"), key=lambda m: m.date)
    for b in bases:
        _pro_rata(s, b, [a for a in iras if a.ownerId == b.ownerId], conversions, taken_from, y)
    return Retirement(contributions, distributions, rmds, bases, conversions, rollovers)


def _marks(s: Session, t: Transaction) -> list[tuple[Decimal, bool | None]]:
    """A contribution's amounts with whether each is deductible: its parts' when split."""
    parts = list(
        s.scalars(select(Split).where(Split.transactionId == t.id, Split.deleted == false()))
    )
    return [(x.amount, x.deductible) for x in parts] or [(t.amount, t.deductible)]


def _pro_rata(s, basis: Basis8606, iras, conversions, taken_from, year) -> None:
    """Form 8606 Part I, one filer's: a conversion from their traditional IRAs is taxed but
    for its share of their basis (last year's and this year's nondeductible contributions),
    over their IRAs' year-end value plus what left them in the year (distributions and
    conversions). It waits while a contribution is undecided or last year's basis untyped."""
    ids_ = {a.id for a in iras}
    from_iras = [m for m in conversions if m.fromId in ids_]
    if not from_iras:
        return
    if basis.undecided:
        for m in from_iras:
            m.waiting = f"mark whether each of {basis.owner}'s IRA contributions was deductible"
        return
    if basis.carried is None:
        for m in from_iras:
            m.waiting = f"type {basis.owner}'s Form 8606 basis carried from {year - 1}"
        return
    from .. import valuation

    whole_basis = basis.carried + basis.nondeductible
    # Money, each sum: there is an IRA, and a conversion from one.
    year_end = sum(
        valuation.account_value(s, repo.load(s, a), True, dt.date(year, 12, 31)) for a in iras
    )
    out = sum(m.amount for m in from_iras)
    taken = sum(taken_from.get(i, ZERO) for i in ids_)
    whole = year_end + out + taken
    if whole <= 0:
        return  # nothing in the IRAs at all (a fee took more than was there): no share
    for m in from_iras:
        # The basis's share is at most the whole of it (line 10's 1.000): a conversion is
        # never taxed less than nothing, and the basis left over carries on.
        untaxed = min(whole_basis * m.amount / whole, m.amount)
        m.taxable = (m.amount - untaxed).quantize(CENT)


# ---------- Deductions and credits (S8.7) ----------


@dataclass
class TagTotal:
    tag: str
    label: str
    total: Decimal
    count: int
    withReceipts: int


TAG_LABELS = {
    "medical": "Medical and dental",
    "childcare": "Childcare",
    "education": "Education",
    "charitable": "Charitable gifts",
    "business": "Business expenses",
    "loan-interest": "Loan interest",
    "property-tax": "Property tax",
    "retirement": "Retirement contributions",
}


def deductions(s: Session, book: TaxBook) -> tuple[list[TagTotal], list[tuple[str, int, Decimal]]]:
    """Totals of tax-tagged categories with how many have receipts; and estimated tax
    payments by quarter."""
    first, last = _span(book.year)
    ids = [a.id for a in books.counted(s, book).accounts]
    cats = {c.id: c for c in s.scalars(select(Category).where(Category.taxTag.is_not(None)))}
    out: dict[str, TagTotal] = {}
    if ids:
        txns = s.scalars(
            select(Transaction).where(
                Transaction.accountId.in_(ids),
                Transaction.deleted == false(),
                Transaction.date >= first,
                Transaction.date <= last,
            )
        ).all()
        by_id = {t.id: t for t in txns}
        loan_accounts = [a for a in books.counted(s, book).accounts if loans.is_loan(a.type)]
        in_loans = {a.id for a in loan_accounts}
        amounts: list[tuple[str | None, str, Decimal]] = []
        for t in txns:
            if t.categoryId in cats and t.accountId not in in_loans:
                amounts.append((t.id, cats[t.categoryId].taxTag, -t.amount))
        for sp in s.scalars(
            select(Split).where(
                Split.transactionId.in_(list(by_id)),
                Split.deleted == false(),
                Split.categoryId.in_(list(cats)),
            )
        ):
            # A split counts as its transaction does (S8.7): a spending split is negative, as
            # spending is, and counts positive.
            if by_id[sp.transactionId].accountId not in in_loans:
                amounts.append((sp.transactionId, cats[sp.categoryId].taxTag, -sp.amount))
        # A loan's payments, each split by the schedule however it arrived (S1.9.3): the
        # parts filed under a tax-tagged category (the interest) count.
        tagged = {c.builtIn: c.taxTag for c in cats.values() if c.builtIn}
        for a in loan_accounts:
            for pay in loans.history(s, a)[0]:
                # A payment assumed as scheduled (S1.9.3) isn't one recorded: no deduction.
                if pay.assumed or not first <= pay.date <= last:
                    continue
                for part, key in loans.PARTS.items():
                    amount = getattr(pay, part)
                    if amount and key in tagged:
                        amounts.append((pay.transactionId, tagged[key], amount))
        with_receipts = set(
            s.scalars(
                select(ReceiptLink.itemId).where(
                    ReceiptLink.kind == "transaction",
                    ReceiptLink.deleted == false(),
                    ReceiptLink.itemId.in_(list(by_id)),
                )
            )
        )
        for t_id, tag, amount in amounts:
            row = out.setdefault(tag, TagTotal(tag, TAG_LABELS.get(tag, tag), ZERO, 0, 0))
            row.total += amount
            row.count += 1
            row.withReceipts += t_id in with_receipts
    quarters = []
    for f in books.filings(s, book):
        for p in s.scalars(
            select(EstimatedPayment).where(
                EstimatedPayment.filingId == f.id, EstimatedPayment.deleted == false()
            )
        ):
            where = "Federal" if f.jurisdiction == "federal" else (f.place or "State")
            quarters.append((where, p.quarter, p.amount))
    return sorted(out.values(), key=lambda x: -x.total), sorted(quarters)


# ---------- Giving, education, gifts, loans (S8.9–S8.12) ----------


def giving_panel(s: Session, book: TaxBook) -> list[giving.Gift]:
    who = [f.userId for f in books.filers(s, book) if f.acceptedAt is not None]
    return giving.donations(s, who, book.year)


@dataclass
class EducationRow:
    account: str
    beneficiary: str
    contributions: list[tuple[str, Decimal]]  # by contributor
    stateDeduction: Decimal | None
    distributions: Decimal
    expenses: Decimal
    notCovered: Decimal


def education_panel(s: Session, book: TaxBook) -> list[EducationRow]:
    out = []
    for a in books.counted(s, book).accounts:
        if a.type != "529":
            continue
        plan = education.plan_of(s, a)
        b = education.beneficiary(s, plan)
        by: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for r in education.contributions(s, a):
            if r.date.year == book.year:
                by[r.name] += r.amount
        w = next((x for x in education.withdrawals(s, a) if x.year == book.year), None)
        out.append(
            EducationRow(
                a.name,
                b.name if b else "—",
                sorted(by.items()),
                plan.stateDeduction if plan else None,
                w.distributions if w else ZERO,
                w.expenses if w else ZERO,
                w.notCovered if w else ZERO,
            )
        )
    return out


@dataclass
class Student:
    """A dependent student (S8.14.5.3): their 1098-T, and the withdrawals from 529s for them."""

    name: str
    received1098T: bool
    withdrawals529: Decimal


def students(s: Session, book: TaxBook) -> list[Student]:
    deps = [d for d in dependents.listed(s, book) if d.row.student]
    if not deps:
        return []
    # 1098-Ts name the college, not the student: as many students have theirs as arrived.
    got = sum(
        1 for d in books.documents(s, book) if d.direction == "received" and d.form == "1098-T"
    )
    taken: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for a in books.counted(s, book).accounts:
        if a.type != "529":
            continue
        b = education.beneficiary(s, education.plan_of(s, a))
        w = next((x for x in education.withdrawals(s, a) if x.year == book.year), None)
        if b is not None and w is not None:
            taken[b.id] += w.distributions
    return [Student(d.person.name, i < got, taken[d.person.id]) for i, d in enumerate(deps)]


@dataclass
class GiftTax:
    giver: str
    person: str
    given: Decimal
    exclusion: Decimal


def gifts_panel(s: Session, book: TaxBook) -> tuple[list[GiftTax], list[str]]:
    """Each person who received more than the exclusion from a filer, and the five-year 529
    elections still running (S8.11)."""
    flagged, elections = [], []
    for f in books.filers(s, book):
        if f.acceptedAt is None:
            continue
        u = s.get(User, f.userId)
        sp = gifts.spending(s, u.id, book.year)
        for p, amount, limit in sp.flagged:
            flagged.append(GiftTax(u.displayName, p.name, amount, limit))
        for a in s.scalars(
            select(Account).where(
                Account.ownerId == u.id, Account.type == "529", Account.deleted == false()
            )
        ):
            for r in education.contributions(s, a):
                if r.fiveYear and r.date.year <= book.year <= r.date.year + 4:
                    year_n = book.year - r.date.year + 1
                    elections.append(
                        f"{r.name}'s {r.date.year} five-year election to {a.name}: "
                        f"year {year_n} of 5, {r.amount / 5:,.0f} a year"
                    )
    return flagged, elections


@dataclass
class LoanRow:
    account: str
    kind: str
    interest: Decimal
    pmi: Decimal
    propertyTax: Decimal
    securedBy: str | None


def loans_panel(s: Session, book: TaxBook) -> list[LoanRow]:
    out = []
    for a in books.counted(s, book).accounts:
        if a.type not in ("mortgage", "heloc", "student-loan"):
            continue
        payments, _ = loans.history(s, a)
        mine = [p for p in payments if p.date.year == book.year and not p.assumed]
        row = loans.loan_of(s, a)
        secured = None
        if row is not None and row.securedById:
            # The item a loan names is kept while it does (a deleted one too, by its name).
            secured = s.get(Item, row.securedById).name
        out.append(
            LoanRow(
                a.name,
                "1098-E" if a.type == "student-loan" else "1098",
                sum((p.interest for p in mine), ZERO),
                sum((p.pmi for p in mine), ZERO),
                sum((p.escrowTax for p in mine), ZERO),
                secured,
            )
        )
    return out


@dataclass
class Residence:
    name: str
    sold: dt.date
    gain: Decimal
    yearsOwned: float


def residences(s: Session, book: TaxBook) -> list[Residence]:
    """A sold primary residence: its gain and the years owned (S8.13); the exclusion is the
    preparer's to apply."""
    first, last = _span(book.year)
    out = []
    for a in books.counted(s, book).accounts:
        if a.type != "real-estate":
            continue
        for it in s.scalars(
            select(Item).where(
                Item.accountId == a.id,
                Item.deleted == false(),
                Item.primaryResidence,
                Item.soldOn >= first,
                Item.soldOn <= last,
            )
        ):
            g = assets.gain(it, assets.details(s, [it])[it.id]) or ZERO
            out.append(
                Residence(
                    it.name, it.soldOn, g, round((it.soldOn - it.acquiredOn).days / 365.25, 1)
                )
            )
    return out


# ---------- Missing or doubtful data (S8.4) ----------


@dataclass
class Issue:
    kind: str
    text: str
    link: str | None = None


def issues(s: Session, book: TaxBook, rows: list[Row]) -> list[Issue]:
    out = []
    if changed := changed_after_filing(s, book):
        out.append(Issue("changed-after-filing", changed))
    if differs := differs_from_filed(s, book, rows):
        out.append(Issue("differs-from-filed", differs))
    if books.carryover(s, book)[2]:
        out.append(
            Issue(
                "carryover-share",
                f"Type your share of {book.year - 1}'s joint return's capital-loss carryover: "
                "splitting it is yours to decide, and none counts until it is typed.",
            )
        )
    counted = books.counted(s, book)
    for a in counted.leftOut:
        out.append(Issue("left-out", f"{a.name} is left out of this tax book."))
    for a in _taxable(counted.accounts):
        if not atypes.investing(a.type):
            continue
        led = repo.load(s, a)
        rp = led.replay()
        for p in rp.problems:
            inst = s.get(Instrument, p.instrumentId)
            if p.kind == "sale-without-lot" and p.date.year == book.year:
                out.append(
                    Issue(
                        p.kind,
                        f"{a.name}: {inst.symbol} sold on {p.date:%b %-d} without a lot to match",
                        f"/ui/accounts/{a.id}/holdings",
                    )
                )
        for lot in rp.open:
            if lot.acquiredMissing:
                inst = s.get(Instrument, lot.instrumentId)
                out.append(
                    Issue(
                        "acquired-missing",
                        f"{a.name}: {inst.symbol} moved in on {lot.acquiredOn:%b %-d, %Y}: when "
                        "it was bought, and its basis, for its term and gain",
                        f"/ui/accounts/{a.id}/holdings",
                    )
                )
            elif lot.basis is None:
                inst = s.get(Instrument, lot.instrumentId)
                out.append(
                    Issue(
                        "basis-missing",
                        f"{a.name}: a lot of {inst.symbol} has no cost basis",
                        f"/ui/accounts/{a.id}/holdings",
                    )
                )
    for r in rows:
        if r.acquiredMissing:
            out.append(
                Issue(
                    "sale-acquired-missing",
                    f"{r.account}: the sale of {r.description} on {r.sold:%b %-d} is of shares "
                    "moved in: when they were bought, for its term",
                    f"/ui/accounts/{r.accountId}/holdings",
                )
            )
        if r.basis is None:
            out.append(
                Issue(
                    "sale-basis",
                    f"{r.account}: the sale of {r.description} on {r.sold:%b %-d} has no basis"
                    + (" or day bought" if r.lotMissing else ""),
                )
            )
    # Dependents (S8.14.5): claimed on two books, a filer claimed on another, Form 8615.
    deps = dependents.listed(s, book)
    for d in deps:
        if d.claimedElsewhere:
            out.append(
                Issue(
                    "claimed-twice",
                    f"{d.person.name} is claimed on another {book.year} tax book too",
                )
            )
    for p in dependents.filers_claimed_elsewhere(s, book):
        out.append(
            Issue(
                "claimed-elsewhere",
                f"{p.name} is claimed as a dependent on another {book.year} tax book",
            )
        )
    for f in dependents.form_8615(s, book, deps, counted.accounts):
        out.append(
            Issue(
                "form-8615",
                f"{f.name}'s unearned income of ${grouped(f.unearned)} is above the "
                f"${f.threshold:,.0f} threshold: Form 8615 may apply",
            )
        )
    # Transfers between users' accounts carry a gift's basis over (S8.4).
    ids = {a.id: a for a in counted.accounts}
    first, last = _span(book.year)
    for t in s.scalars(
        select(Transaction).where(
            Transaction.accountId.in_(list(ids)),
            Transaction.deleted == false(),
            Transaction.kind == "transfer-in",
            Transaction.date >= first,
            Transaction.date <= last,
            Transaction.transferId.is_not(None),
        )
    ):
        other = s.get(Transaction, t.transferId)
        oa = s.get(Account, other.accountId) if other else None
        if oa is not None and oa.ownerId != ids[t.accountId].ownerId:
            out.append(
                Issue(
                    "gift-basis",
                    f"{ids[t.accountId].name}: shares from {oa.name} on {t.date:%b %-d} keep "
                    "the giver's basis",
                )
            )
    return out


def changed_after_filing(s: Session, book: TaxBook) -> str | None:
    """The edits made anyway since the federal return was filed, not yet settled (S8.15): how
    far they moved the realized gains, and in which accounts."""
    edits: dict[str, int] = defaultdict(int)
    total = Decimal(0)
    for change in closed.unsettled(s, book):
        edits[change.accountId] += 1
        total += change.gains
    if not edits:
        return None
    where = "; ".join(
        f"{s.get(Account, a).name}, {n} edit{'' if n == 1 else 's'}" for a, n in edits.items()
    )
    sign = "-" if total < 0 else "+"
    return (
        f"Realized gains changed by {sign}${grouped(abs(total))} after the federal return was "
        f"filed: {where}"
    )


def differs_from_filed(s: Session, book: TaxBook, rows: list[Row]) -> str | None:
    """A difference from the gains as filed that no change made here explains (S8.15): a rule
    corrected since, or a backup restored, say. Listed so the return can be checked."""
    live: dict[str, Decimal] = defaultdict(Decimal)
    for r in rows:
        if r.accountId:
            live[r.accountId] += r.gain or Decimal(0)
    off = closed.unexplained(s, book, dict(live))
    if not off:
        return None
    total = sum(off.values(), Decimal(0))
    names = ", ".join(sorted(s.get(Account, a).name for a in off))
    sign = "-" if total < 0 else "+"
    return (
        f"Realized gains differ by {sign}${grouped(abs(total))} from those when the federal return "
        f"was filed, by no change made here: {names}"
    )


def spouse_accounts(s: Session, book: TaxBook) -> list[Account]:
    """For wash sales: the filers' spouses' accounts, when filing separately (S3.8): whoever
    was married to a filer at any time in the year."""
    who = {f.userId for f in books.filers(s, book)}
    first, last = _span(book.year)
    out = []
    spouses = set()
    for uid in who:
        # A spouse who files on this book too is in it already; one found once, once.
        for other in people.spouse_users_ever(s, uid) - who - spouses:
            if any(
                people.spouse_user_on(s, uid, day) == other
                for day in (first, last, *_marriage_days(s, uid, other, first, last))
            ):
                spouses.add(other)
    for other in sorted(spouses):
        out += list(
            s.scalars(select(Account).where(Account.ownerId == other, Account.deleted == false()))
        )
    return out


def _marriage_days(s: Session, user_a: str, user_b: str, first, last) -> list:
    """The days in a year a marriage between two users began, to test it held that year."""
    a, b = people.of_user(s, user_a), people.of_user(s, user_b)
    days = []
    for r in people.live_relationships(s, [a.id]):
        if (
            r.relation == "spouse"
            and people.other(r, a.id) == b.id
            and r.fromDate
            and first <= r.fromDate <= last
        ):
            days.append(r.fromDate)
    return days
