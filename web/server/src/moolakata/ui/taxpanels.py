"""The tax panels and exports (requirements S8.1–S8.13, S8.2) for one tax book."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Response

from .. import clock
from ..store import scoping
from ..taxes import books, closed, dependents, exports, panels
from .conventions import ExactRoute, Model, Money, Quantity, Ratio
from .deps import Caller, caller, server

router = APIRouter(prefix="/ui/api", route_class=ExactRoute, tags=["taxes"])


class RowOut(Model):
    description: str
    acquired: dt.date | None
    sold: dt.date
    proceeds: Money
    basis: Money | None
    code: str
    adjustment: Money
    gain: Money | None
    longTerm: bool
    box: str
    account: str
    collectable: bool


class WashOut(Model):
    sold: dt.date
    symbol: str
    account: str
    loss: Money
    disallowed: Money
    replacedOn: dt.date
    replacementAccount: str
    replacementQty: Quantity
    adjustedBasis: Money | None
    review: bool


class BoxTotal(Model):
    box: str
    proceeds: Money
    basis: Money
    adjustment: Money
    gain: Money


class ScheduleDOut(Model):
    boxes: list[BoxTotal]
    shortTerm: Money
    longTerm: Money
    collectables: Money
    carryoverShort: Money
    carryoverLong: Money
    net: Money


class Amount(Model):
    label: str
    amount: Money


class IncomeOut(Model):
    interest: list[Amount]
    interestTotal: Money
    ordinary: Money
    qualified: Money
    capitalGainDistributions: Money
    returnOfCapital: Money
    dividendsByPayer: list[Amount]


class ContributionOut(Model):
    account: str
    kind: str
    owner: str
    contributed: Money
    limit: Money | None
    # What the person put in all their accounts under the same limit (S8.6), and which those
    # are; `over` holds that total against the limit.
    personTotal: Money
    across: str | None
    over: bool
    note: str


class RmdOut(Model):
    account: str
    owner: str
    age: int
    balance: Money
    factor: Ratio
    due: Money


class RetirementOut(Model):
    contributions: list[ContributionOut]
    distributions: list[Amount]
    rmds: list[RmdOut]
    basis8606: Money | None


class TagOut(Model):
    tag: str
    label: str
    total: Money
    count: int
    withReceipts: int


class Quarter(Model):
    jurisdiction: str
    quarter: int
    amount: Money


class DonationRow(Model):
    date: dt.date
    name: str
    kindLabel: str
    amount: Money
    deductible: bool
    needsAck: bool
    acknowledged: bool


class GivingOut(Model):
    deductible: list[DonationRow]
    apart: list[DonationRow]  # QCDs, grants, gifts to non-deductible organisations
    deductibleTotal: Money
    missingAcks: int
    notes: list[str]


class EducationOut(Model):
    account: str
    beneficiary: str
    contributions: list[Amount]
    stateDeduction: Money | None
    distributions: Money
    expenses: Money
    notCovered: Money


class DependentAge(Model):
    name: str
    relation: str | None
    age: int | None  # on Dec 31
    under17: bool
    under13: bool
    agesOut: list[str]


class StudentOut(Model):
    name: str
    received1098T: bool
    withdrawals529: Money


class GiftTaxOut(Model):
    giver: str
    person: str
    given: Money
    exclusion: Money


class LoanOut(Model):
    account: str
    form: str
    interest: Money
    pmi: Money
    propertyTax: Money
    securedBy: str | None


class ResidenceOut(Model):
    name: str
    sold: dt.date
    gain: Money
    yearsOwned: Ratio


class IssueOut(Model):
    kind: str
    text: str
    link: str | None


class TxfLeftOut(Model):
    """The sales the TXF file leaves out, by why, to be entered from the CSV (S8.2)."""

    digital: int  # in a digital asset's box, G to L
    collectable: int  # code C
    personalUse: int  # code L, a loss on personal-use property


class Panels(Model):
    year: int
    rows: list[RowOut]
    washes: list[WashOut]
    scheduleD: ScheduleDOut
    income: IncomeOut
    retirement: RetirementOut
    deductions: list[TagOut]
    dependents: list[DependentAge]  # in Deductions and credits (S8.14.5.3)
    estimated: list[Quarter]
    lastYearTax: Money | None  # beside the estimated payments
    giving: GivingOut
    education: list[EducationOut]
    students: list[StudentOut]  # dependent students (S8.14.5.3)
    giftTax: list[GiftTaxOut]
    elections: list[str]
    loans: list[LoanOut]
    residences: list[ResidenceOut]
    issues: list[IssueOut]
    leftOut: list[str]
    txfLeftOut: TxfLeftOut
    covers: str


def _rows(s, b):
    return panels.form_8949(s, b, panels.spouse_accounts(s, b))


def _rows_of(s, b):
    """Form 8949's rows of a book the caller reads, worked out as the server (S8.14.2)."""
    with scoping.as_server(s, "a tax book's 8949, for one who reads it") as srv:
        return _rows(srv, srv.get(type(b), b.id))


def build(s, b) -> Panels:
    """A book's panels, worked out as the server over its filers' accounts (S8.14.2): the
    caller's access to the book is checked first."""
    with scoping.as_server(s, "a tax book's panels, for one who reads it") as srv:
        return _build(srv, srv.get(type(b), b.id))


def _build(s, b) -> Panels:
    rows, washes = _rows(s, b)
    d = panels.schedule_d(s, b, rows)
    inc = panels.income(s, b)
    ret = panels.retirement(s, b)
    tags, quarters = panels.deductions(s, b)
    gifts_ = panels.giving_panel(s, b)
    flagged, elections = panels.gifts_panel(s, b)
    last_tax = None
    for f, figures in books.carried_from_last_year(s, b):
        if f.jurisdiction == "federal" and figures.get("totalTax"):
            last_tax = Decimal(str(figures["totalTax"]))

    def donation(g) -> DonationRow:
        return DonationRow(
            date=g.date,
            name=g.name,
            kindLabel=panels.giving.KINDS[g.kind],
            amount=g.amount,
            deductible=g.deductible,
            needsAck=g.needsAck,
            acknowledged=g.acknowledged,
        )

    return Panels(
        year=b.year,
        rows=[RowOut(**{k: getattr(r, k) for k in RowOut.model_fields}) for r in rows],
        washes=[WashOut(**w.__dict__) for w in washes],
        scheduleD=ScheduleDOut(
            boxes=[
                BoxTotal(box=k, proceeds=v[0], basis=v[1], adjustment=v[2], gain=v[3])
                for k, v in d.byBox.items()
            ],
            shortTerm=d.shortTerm,
            longTerm=d.longTerm,
            collectables=d.collectables,
            carryoverShort=d.carryoverShort,
            carryoverLong=d.carryoverLong,
            net=d.net,
        ),
        income=IncomeOut(
            interest=[Amount(label=k, amount=v) for k, v in inc.interest],
            interestTotal=sum((v for _, v in inc.interest), Decimal(0)),
            ordinary=inc.ordinary,
            qualified=inc.qualified,
            capitalGainDistributions=inc.capitalGainDistributions,
            returnOfCapital=inc.returnOfCapital,
            dividendsByPayer=[Amount(label=k, amount=v) for k, v in inc.byPayer],
        ),
        retirement=RetirementOut(
            contributions=[
                ContributionOut(
                    account=c.account,
                    kind=c.kind,
                    owner=c.owner,
                    contributed=c.contributed,
                    limit=c.limit,
                    personTotal=c.personTotal,
                    across=panels.GROUP_LABELS.get(c.group)
                    if c.personTotal != c.contributed
                    else None,
                    over=c.limit is not None and c.personTotal > c.limit,
                    note=c.note,
                )
                for c in ret.contributions
            ],
            distributions=[Amount(label=k, amount=v) for k, v in ret.distributions],
            rmds=[RmdOut(**r.__dict__) for r in ret.rmds],
            basis8606=ret.basis8606,
        ),
        deductions=[TagOut(**t.__dict__) for t in tags],
        dependents=[
            DependentAge(
                name=d.person.name,
                relation=d.relation,
                age=d.age,
                under17=d.under17,
                under13=d.under13,
                agesOut=d.agesOut,
            )
            for d in dependents.listed(s, b)
        ],
        estimated=[Quarter(jurisdiction=j, quarter=q, amount=a) for j, q, a in quarters],
        lastYearTax=last_tax,
        giving=GivingOut(
            deductible=[donation(g) for g in gifts_ if g.deductible],
            apart=[donation(g) for g in gifts_ if not g.deductible],
            deductibleTotal=sum((g.amount for g in gifts_ if g.deductible), Decimal(0)),
            missingAcks=sum(1 for g in gifts_ if g.needsAck and not g.acknowledged),
            notes=panels.giving.tax_notes(gifts_),
        ),
        education=[
            EducationOut(
                account=e.account,
                beneficiary=e.beneficiary,
                contributions=[Amount(label=k, amount=v) for k, v in e.contributions],
                stateDeduction=e.stateDeduction,
                distributions=e.distributions,
                expenses=e.expenses,
                notCovered=e.notCovered,
            )
            for e in panels.education_panel(s, b)
        ],
        students=[StudentOut(**x.__dict__) for x in panels.students(s, b)],
        giftTax=[GiftTaxOut(**g.__dict__) for g in flagged],
        elections=elections,
        loans=[
            LoanOut(
                account=x.account,
                form=x.kind,
                interest=x.interest,
                pmi=x.pmi,
                propertyTax=x.propertyTax,
                securedBy=x.securedBy,
            )
            for x in panels.loans_panel(s, b)
        ],
        residences=[ResidenceOut(**r.__dict__) for r in panels.residences(s, b)],
        issues=[IssueOut(**i.__dict__) for i in panels.issues(s, b, rows)],
        leftOut=[a.name for a in books.counted(s, b).leftOut],
        txfLeftOut=TxfLeftOut(**exports.txf_left_out(rows)),
        covers=exports.covers(b.bitcoinFees),
    )


@router.get("/tax-books/{book_id}/panels", response_model=Panels)
def get_panels(book_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        b, _ = books.get(s, c.id, book_id)
        return build(s, b)


@router.post("/tax-books/{book_id}/no-amendment", response_model=Panels)
def no_amendment(book_id: str, request: Request, c: Caller = Depends(caller)):
    """No amendment needed (S8.15): settles the edits made since the federal return was filed,
    with who said so and when."""
    with server(request).db.tx(user=c.id) as s:
        b, _ = books.get(s, c.id, book_id, "write")
        closed.settle(s, b, c.id, "not-needed")
        s.flush()
        return build(s, b)


def _download(body: bytes | str, name: str, kind: str) -> Response:
    data = body.encode() if isinstance(body, str) else body
    return Response(
        data,
        media_type=kind,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/tax-books/{book_id}/exports/8949.csv", response_class=Response)
def export_csv(book_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        b, _ = books.get(s, c.id, book_id)
        rows, _ = _rows_of(s, b)
        return _download(
            exports.csv_8949(rows, b.year, b.bitcoinFees), f"form-8949-{b.year}.csv", "text/csv"
        )


@router.get("/tax-books/{book_id}/exports/moolakata.txf", response_class=Response)
def export_txf(book_id: str, request: Request, c: Caller = Depends(caller)):
    with server(request).db.read(user=c.id) as s:
        b, _ = books.get(s, c.id, book_id)
        rows, _ = _rows_of(s, b)
        return _download(
            exports.txf(rows, clock.today()), f"moolakata-{b.year}.txf", "application/x-txf"
        )


@router.get("/tax-books/{book_id}/exports/summary.pdf", response_class=Response)
def export_pdf(book_id: str, request: Request, c: Caller = Depends(caller)):
    """A summary for a preparer: what each panel holds, with its sources."""
    with server(request).db.read(user=c.id) as s:
        b, _ = books.get(s, c.id, book_id)
        p = build(s, b)
        filers = " & ".join(f.name for f in _filers(s, b))
        d = panels.schedule_d(s, b, _rows(s, b)[0])
        sections = [
            (
                "About this summary",
                [
                    f"Tax year {b.year} for {filers}, prepared by MoolaKata on "
                    f"{clock.today():%B %-d, %Y}.",
                    "MoolaKata gathers figures and their sources. It does not compute the tax, "
                    "choose a filing status, or file.",
                    exports.COVERS,
                    *(f"Left out of this book: {x}" for x in p.leftOut),
                ],
            ),
            ("Capital gains (Form 8949, Schedule D)", exports.schedule_d_lines(d)),
            (
                "Wash sales",
                [
                    f"{w.symbol} sold {w.sold:%b %-d} in {w.account}: {w.disallowed:,.2f} of a "
                    f"{w.loss:,.2f} loss disallowed; replaced {w.replacedOn:%b %-d} in "
                    f"{w.replacementAccount}"
                    for w in p.washes
                ]
                or ["None found."],
            ),
            (
                "Income",
                [
                    *(f"Interest from {x.label}: {x.amount:,.2f}" for x in p.income.interest),
                    f"Ordinary dividends {p.income.ordinary:,.2f} (qualified "
                    f"{p.income.qualified:,.2f}); capital-gain distributions "
                    f"{p.income.capitalGainDistributions:,.2f}",
                ],
            ),
            (
                "Retirement",
                [
                    *(
                        f"{x.account} ({x.kind}, {x.owner}): contributed {x.contributed:,.2f}"
                        + (f" of {x.limit:,.2f}" if x.limit else "")
                        for x in p.retirement.contributions
                    ),
                    *(
                        f"Distributions from {x.label}: {x.amount:,.2f}"
                        for x in p.retirement.distributions
                    ),
                    *(f"RMD due from {x.account}: {x.due:,.2f}" for x in p.retirement.rmds),
                ]
                or ["Nothing this year."],
            ),
            (
                "Deductions and credits",
                [
                    f"{t.label}: {t.total:,.2f} ({t.count} transactions, {t.withReceipts} with "
                    "receipts)"
                    for t in p.deductions
                ]
                + [
                    f"Estimated payment, {q.jurisdiction} Q{q.quarter}: {q.amount:,.2f}"
                    for q in p.estimated
                ]
                or ["None."],
            ),
            (
                "Charitable giving",
                [
                    f"Deductible: {p.giving.deductibleTotal:,.2f}; "
                    f"{p.giving.missingAcks} acknowledgements missing.",
                    *p.giving.notes,
                ],
            ),
            (
                "Loans",
                [
                    f"{x.account} ({x.form}): interest {x.interest:,.2f}, PMI {x.pmi:,.2f}, "
                    f"property tax through escrow {x.propertyTax:,.2f}"
                    for x in p.loans
                ]
                or ["None."],
            ),
            (
                "Education and gifts",
                [
                    *(
                        f"{e.account} for {e.beneficiary}: distributions {e.distributions:,.2f}, "
                        f"qualified expenses {e.expenses:,.2f}, not covered {e.notCovered:,.2f}"
                        for e in p.education
                    ),
                    *(
                        f"Form 709: {g.giver} gave {g.person} {g.given:,.2f}, above the "
                        f"{g.exclusion:,.2f} exclusion"
                        for g in p.giftTax
                    ),
                    *p.elections,
                ]
                or ["None."],
            ),
            ("To look at", [i.text for i in p.issues] or ["Nothing."]),
        ]
        body = exports.pdf(f"Tax summary {b.year}: {filers}", sections)
        return _download(body, f"tax-summary-{b.year}.pdf", "application/pdf")


def _filers(s, b):
    from .taxes import _filers as filers_of

    return filers_of(s, b)
