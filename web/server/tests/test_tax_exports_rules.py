"""The tax exports' and tax books' rules (requirements S8.2, S8.14–S8.17): Form 8949 as CSV,
TXF for tax software and the PDF summary, called on rows built in memory; and the books' due
dates, filers, accounts, documents and last years, read straight from a store."""

import csv
import datetime as dt
import io
import json
import os
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import make_user
from sqlalchemy import select

from moolakata import ids
from moolakata.config import Config
from moolakata.keys import master
from moolakata.store.entities.accounts import Account, Category, Instrument, Transaction
from moolakata.store.entities.education import Person
from moolakata.store.entities.sharing import SHARE_ENTITIES, AccessClass
from moolakata.store.entities.taxes import (
    Filing,
    TaxBook,
    TaxBookAccount,
    TaxBookDependent,
    TaxBookFiler,
    TaxDocument,
)
from moolakata.store.maintenance import open_store
from moolakata.store.repos.ledger import ensure_categories
from moolakata.taxes import books, exports
from moolakata.taxes.panels import Row, ScheduleD

D = Decimal


def row(box="A", **kw) -> Row:
    """A sale on box A by default: 1,000.50 for 400.25, bought Jan 2 2025, sold Mar 4 2026."""
    r = Row(
        kw.pop("description", "10 MSFT"),
        kw.pop("acquired", dt.date(2025, 1, 2)),
        kw.pop("sold", dt.date(2026, 3, 4)),
        kw.pop("proceeds", D("1000.50")),
        kw.pop("basis", D("400.25")),
        kw.pop("code", ""),
        kw.pop("adjustment", D(0)),
        kw.pop("longTerm", box in "DEFJKL"),
        box,
        kw.pop("account", "Brokerage"),
    )
    for k, v in kw.items():
        setattr(r, k, v)
    return r


# ---------- what the exports say they cover ----------


def test_covers_names_the_books_choice_for_bitcoin_fees():
    assert exports.covers("sale") == f"{exports.COVERS} {exports.FEES['sale']}"
    assert exports.covers("not-taxed") == f"{exports.COVERS} {exports.FEES['not-taxed']}"
    assert exports.FEES["sale"] != exports.FEES["not-taxed"]


# ---------- Form 8949 as CSV ----------


def lines_of(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_the_csv_opens_with_the_year_and_what_it_covers_then_its_columns():
    out = lines_of(exports.csv_8949([], 2026, "not-taxed"))
    assert out == [
        [f"# Form 8949 for 2026, from MoolaKata. {exports.covers('not-taxed')}"],
        [
            "Box",
            "Term",
            "Description",
            "Date acquired",
            "Date sold",
            "Proceeds",
            "Cost basis",
            "Adjustment code",
            "Adjustment",
            "Gain or loss",
            "Account",
        ],
    ]


def test_the_csv_writes_each_row_by_box_then_day_sold():
    rows = [
        row("D", description="late D", sold=dt.date(2026, 5, 1)),
        row("A", description="late A", sold=dt.date(2026, 9, 1)),
        row("D", description="early D", sold=dt.date(2026, 2, 1)),
        row("A", description="early A", sold=dt.date(2026, 1, 1)),
    ]
    out = lines_of(exports.csv_8949(rows, 2026, "sale"))[2:]
    assert [r[2] for r in out] == ["early A", "late A", "early D", "late D"]


def test_the_csv_writes_a_row_with_its_term_days_and_amounts_to_the_cent():
    washed = row(
        "D",
        description="5 NVDA",
        acquired=dt.date(2024, 12, 31),
        sold=dt.date(2026, 1, 1),
        proceeds=D("1234.5"),
        basis=D("2000.004"),
        code="W",
        adjustment=D("300.1"),
        account="Joint",
    )
    plain = row("B", description="1 VTI")
    out = lines_of(exports.csv_8949([washed, plain], 2026, "sale"))[2:]
    assert out == [
        [
            "B",
            "short",
            "1 VTI",
            "2025-01-02",
            "2026-03-04",
            "1000.50",
            "400.25",
            "",
            "",
            "600.25",
            "Brokerage",
        ],
        [
            "D",
            "long",
            "5 NVDA",
            "2024-12-31",
            "2026-01-01",
            "1234.50",
            "2000.00",
            "W",
            "300.10",
            "-465.40",
            "Joint",
        ],
    ]


def test_the_csv_writes_various_for_several_days_bought_and_a_blank_for_no_lot():
    various = row("A", description="several lots", acquired=None)
    no_lot = row("B", description="no lot", acquired=None, lotMissing=True, basis=None)
    out = lines_of(exports.csv_8949([various, no_lot], 2026, "sale"))[2:]
    assert [r[3] for r in out] == ["VARIOUS", ""]
    # No basis: the basis and the gain are blank, never 0.
    assert out[1][6] == "" and out[1][9] == ""


# ---------- TXF ----------


def test_txf_has_its_header_with_the_day_written_and_crlf_lines():
    assert exports.txf([], dt.date(2027, 2, 3)) == "V042\r\nAMoolaKata\r\nD02/03/2027\r\n^\r\n"


def test_txf_writes_a_record_per_sale_by_box_then_day_sold_with_basis_before_proceeds():
    rows = [
        row("D", description="d", sold=dt.date(2026, 2, 1), longTerm=True),
        row("A", description="a2", sold=dt.date(2026, 7, 8), basis=D("10.004")),
        row("A", description="a1", sold=dt.date(2026, 7, 7), acquired=None, proceeds=D(3)),
    ]
    text = exports.txf(rows, dt.date(2027, 1, 2))
    assert text.split("\r\n")[4:] == [
        "TD", "N321", "C1", "L1", "Pa1", "DVARIOUS", "D07/07/2026", "$400.25", "$3.00", "^",
        "TD", "N321", "C1", "L1", "Pa2", "D01/02/2025", "D07/08/2026", "$10.00", "$1000.50", "^",
        "TD", "N323", "C1", "L1", "Pd", "D01/02/2025", "D02/01/2026", "$400.25", "$1000.50", "^",
        "",
    ]  # fmt: skip


def test_txf_uses_each_boxs_own_code():
    for box, code in [("A", 321), ("B", 711), ("C", 712), ("D", 323), ("E", 713), ("F", 714)]:
        text = exports.txf([row(box)], dt.date(2027, 1, 2))
        assert f"\r\nN{code}\r\n" in text, box


def test_txf_writes_a_wash_sales_adjustment_after_the_proceeds_and_only_when_there_is_one():
    washed = row("A", code="W", adjustment=D("12.3"))
    unwashed = row("B", code="W", adjustment=D(0))
    plain = row("C")
    text = exports.txf([washed, unwashed, plain], dt.date(2027, 1, 2))
    records = text.split("\r\n^\r\n")[1:-1]
    assert records[0].endswith("$400.25\r\n$1000.50\r\n$12.30")
    assert records[1].endswith("$400.25\r\n$1000.50")
    assert records[2].endswith("$400.25\r\n$1000.50")


def test_txf_carries_only_boxes_a_to_f_with_no_code_or_a_wash_sale():
    assert exports.in_txf(row("A")) and exports.in_txf(row("F", code="W"))
    assert not exports.in_txf(row("G")) and not exports.in_txf(row("L"))
    assert not exports.in_txf(row("D", code="C")) and not exports.in_txf(row("A", code="L"))
    assert not exports.in_txf(row("A", lotMissing=True))
    assert not exports.in_txf(row("A", basis=None))


def test_txf_counts_a_sale_without_a_lot_as_that_whatever_else_it_lacks():
    """A sale without a lot is counted once, as one without a lot, though its box is a digital
    asset's or it has no basis either."""
    rows = [
        row("H", lotMissing=True),
        row("A", lotMissing=True, basis=None),
        row("C", code="L", lotMissing=True),
        row("D", code="C", basis=None),
        row("B", code="L", basis=None),
        row("K", code="C"),
        row("A"),
        row("E", code="C"),
        row("F", code="L"),
    ]
    assert exports.txf_left_out(rows) == {
        "digital": 1,
        "collectable": 2,
        "personalUse": 2,
        "noLot": 3,
        "noBasis": 0,
    }
    assert exports.txf_left_out([row("E", basis=None), row("E", code="W", basis=None)]) == {
        "digital": 0,
        "collectable": 0,
        "personalUse": 0,
        "noLot": 0,
        "noBasis": 2,
    }


# ---------- Schedule D in the PDF summary ----------


def sched(**kw) -> ScheduleD:
    base = dict(
        byBox={},
        shortTerm=D(0),
        longTerm=D(0),
        collectables=D(0),
        carryoverShort=D(0),
        carryoverLong=D(0),
    )
    return ScheduleD(**(base | kw))


def test_schedule_d_lines_give_each_box_and_the_terms_grouped():
    d = sched(
        byBox={"A": (D("1234.5"), D("1000"), D("0.1"), D("234.6")), "D": (D(2), D(3), D(0), D(-1))},
        shortTerm=D("234.6"),
        longTerm=D("-1"),
    )
    assert exports.schedule_d_lines(d) == [
        "Box A: proceeds 1,234.50, basis 1,000.00, adjustments 0.10, gain or loss 234.60",
        "Box D: proceeds 2.00, basis 3.00, adjustments 0.00, gain or loss -1.00",
        "Short term: 234.60. Long term: -1.00.",
    ]


def test_schedule_d_lines_name_collectables_only_when_there_are_some():
    assert exports.schedule_d_lines(sched(longTerm=D(5000), collectables=D(1500)))[1:] == [
        "Of the long term, collectables (28% rate): 1,500.00."
    ]
    assert len(exports.schedule_d_lines(sched(longTerm=D(5000)))) == 1


@pytest.mark.parametrize(("short", "long_"), [(D("3000"), D(0)), (D(0), D("1200.5"))])
def test_schedule_d_lines_give_a_carryover_when_either_term_has_one(short, long_):
    out = exports.schedule_d_lines(sched(carryoverShort=short, carryoverLong=long_))
    assert out[1:] == [
        "Capital-loss carryover from last year: short "
        f"{exports.grouped(short)}, long {exports.grouped(long_)}."
    ]


# ---------- the PDF ----------


def parse_pdf(data: bytes) -> dict:
    """The PDF's objects by number, checked against its cross-reference table and trailer."""
    assert data.startswith(b"%PDF-1.4\n")
    objects = {
        int(m[1]): (m.start(), m[2])
        for m in re.finditer(rb"(\d+) 0 obj\n(.*?)\nendobj\n", data, re.S)
    }
    xref = data.index(b"xref\n")
    tail = data[xref:]
    n = len(objects)
    head = b"xref\n0 %d\n0000000000 65535 f \n" % (n + 1)
    assert tail.startswith(head)
    entries = tail[len(head) :].split(b"trailer\n")[0]
    assert entries == b"".join(b"%010d 00000 n \n" % objects[k][0] for k in range(1, n + 1))
    assert tail.endswith(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        n + 1, xref))  # fmt: skip
    return {k: body for k, (_, body) in objects.items()}


def pages_of(data: bytes) -> list[list[bytes]]:
    """Each page's text operations, after checking the page tree and the fonts."""
    objs = parse_pdf(data)
    assert objs[1] == b"<< /Type /Catalog /Pages 2 0 R >>"
    assert objs[3] == (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    assert objs[4] == (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    kids = [int(k) for k in re.findall(rb"(\d+) 0 R", re.search(rb"/Kids \[(.*?)\]", objs[2])[1])]
    assert objs[2] == b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = []
    for k in kids:
        content = k - 1
        assert objs[k] == (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>" % content
        )
        m = re.fullmatch(rb"<< /Length (\d+) >>\nstream\n(.*)\nendstream", objs[content], re.S)
        assert int(m[1]) == len(m[2])
        out.append(m[2].split(b"\n"))
    assert sorted(objs) == list(range(1, 4 + 2 * len(kids) + 1))
    return out


def op(font: str, size: float, y: float, text: bytes) -> bytes:
    return b"BT /%s %.1f Tf 54 %.1f Td (%s) Tj ET" % (font.encode(), size, y, text)


def footer(i: int, n: int) -> bytes:
    return b"BT /F1 8 Tf 54 30 Td (Page %d of %d) Tj ET" % (i, n)


def test_the_pdf_sets_the_title_headings_and_lines_down_one_letter_page():
    data = exports.pdf("Tax summary", [("First", ["one", "two"]), ("Second", [])])
    assert pages_of(data) == [
        [
            op("F2", 16, 738, b"Tax summary"),
            op("F2", 12, 713, b"First"),  # 19 below the title, after 6 more
            op("F1", 9.5, 694, b"one"),  # a heading takes 19, a line 13
            op("F1", 9.5, 681, b"two"),
            op("F2", 12, 662, b"Second"),
            footer(1, 1),
        ]
    ]


def test_the_pdf_starts_a_page_below_the_bottom_margin_and_numbers_its_pages():
    """A line may sit on the 54-point margin; the next goes to a new page, at the top."""
    sections = [(f"S{i}", []) for i in range(10)] + [("Last", [f"l{i}" for i in range(33)])]
    pages = pages_of(exports.pdf("T", sections))
    assert len(pages) == 2
    assert pages[0][-2:] == [op("F1", 9.5, 54, b"l30"), footer(1, 2)]
    assert pages[1] == [op("F1", 9.5, 738, b"l31"), op("F1", 9.5, 725, b"l32"), footer(2, 2)]


def texts(data: bytes) -> list[bytes]:
    return [re.search(rb"Td \((.*)\) Tj", o)[1] for o in pages_of(data)[0][2:-1]]


def test_the_pdf_keeps_a_line_of_100_characters_whole():
    line = ("word " * 20)[:100]
    assert texts(exports.pdf("T", [("H", [line])])) == [line.encode()]
    line = "a" * 60 + " " + "b" * 40  # 101 characters: wrapped
    assert texts(exports.pdf("T", [("H", [line])])) == [b"a" * 60, b"    " + b"b" * 40]


def test_the_pdf_wraps_a_long_line_at_its_last_space_before_100_characters():
    first = "a" * 60 + " " + "b" * 38  # 99 characters, the space at 60
    line = first + " " + "c" * 30  # a space at 99 too: the cut is at the last before 100
    assert texts(exports.pdf("T", [("H", [line])])) == [first.encode(), b"    " + b"c" * 30]
    # Each piece is a line of its own, in the lines' font and size.
    assert pages_of(exports.pdf("T", [("H", [line])]))[0][2:4] == [
        op("F1", 9.5, 694, first.encode()),
        op("F1", 9.5, 681, b"    " + b"c" * 30),
    ]
    line = "a" * 95 + " " + "b" * 4 + " " + "c" * 10  # a space at 100 is past the cut
    assert texts(exports.pdf("T", [("H", [line])])) == [
        b"a" * 95,
        b"    " + b"b" * 4 + b" " + b"c" * 10,
    ]


def test_the_pdf_cuts_a_line_at_100_when_its_last_space_is_40_or_nearer_the_start():
    line = "a" * 40 + " " + "b" * 120
    assert texts(exports.pdf("T", [("H", [line])])) == [
        line[:100].encode(),
        b"    " + line[100:].encode(),
    ]
    line = "a" * 41 + " " + "b" * 70
    assert texts(exports.pdf("T", [("H", [line])])) == [b"a" * 41, b"    " + b"b" * 70]


def test_the_pdf_writes_text_in_windows_1252_with_its_brackets_escaped():
    assert exports._escape("Café (net) a\\b ≥ 5€") == b"Caf\xe9 \\(net\\) a\\\\b ? 5\x80"


# ---------- tax books: a filing's due date ----------


def filing(**kw) -> Filing:
    return Filing(id="Filng_1", bookId="TaxBk_1", jurisdiction="federal", form="1040", **kw)


def test_a_filing_is_due_on_its_extended_date_once_it_has_one():
    assert books.due_of(filing()) is None
    assert books.due_of(filing(dueDate=dt.date(2026, 4, 15))) == dt.date(2026, 4, 15)
    late = filing(dueDate=dt.date(2026, 4, 15), extendedDue=dt.date(2026, 10, 15))
    assert books.due_of(late) == dt.date(2026, 10, 15)


def test_a_filing_is_overdue_only_the_day_after_its_due_date_until_it_is_filed():
    due = dt.date(2026, 4, 15)
    day_after = dt.date(2026, 4, 16)
    assert not books.overdue(filing(dueDate=due), due)
    assert books.overdue(filing(dueDate=due), day_after)
    for progress in ("not started", "in progress", "rejected"):
        assert books.overdue(filing(dueDate=due, progress=progress), day_after), progress
    for progress in ("filed", "accepted"):
        assert not books.overdue(filing(dueDate=due, progress=progress), day_after), progress
    assert not books.overdue(filing(), day_after)  # no due date: never overdue


def test_an_extension_that_still_runs_keeps_a_filing_from_being_overdue():
    f = filing(dueDate=dt.date(2026, 4, 15), extendedDue=dt.date(2026, 10, 15))
    assert not books.overdue(f, dt.date(2026, 5, 1))
    assert books.overdue(f, dt.date(2026, 10, 16))


def test_an_amended_return_is_never_overdue():
    f = filing(dueDate=dt.date(2026, 4, 15), amendsId="Filng_0")
    assert not books.overdue(f, dt.date(2027, 1, 1))


# ---------- tax books, read straight from a store ----------

T = dt.datetime(2026, 3, 1, 12, tzinfo=dt.UTC)


class Store:
    """Records put straight in a store, each made a second after the last, so the order they
    are made in is their order by `createdAt`."""

    def __init__(self, s, users: dict[str, str]):
        self.s = s
        self.u = users
        self.n = 0

    def put(self, rec, deleted: bool = False):
        self.n += 1
        rec.createdAt = rec.updatedAt = T + dt.timedelta(seconds=self.n)
        if deleted:
            rec.deletedAt = T
        self.s.add(rec)
        self.s.flush()
        return rec

    def account(self, owner="alice", type="checking", name=None, institution=None, **kw):
        a = Account(id=ids.new_id("Acct"), ownerId=self.u[owner], name=name or type, type=type,
                    institution=institution)  # fmt: skip
        return self.put(a, **kw)

    def book(self, year=2026, filers=None, owner="alice", **kw):
        """`filers`: each filer's name and whether they accepted; the owner alone by default."""
        deleted = kw.pop("deleted", False)
        b = self.put(TaxBook(id=ids.new_id("TaxBk"), ownerId=self.u[owner], year=year, **kw))
        for name, ok in (filers or {owner: True}).items():
            self.put(TaxBookFiler(bookId=b.id, userId=self.u[name], acceptedAt=T if ok else None))
        if deleted:
            b.deletedAt = T
            self.s.flush()
        return b

    def txn(self, account, day, amount, kind="deposit", instrument=None, **kw):
        t = Transaction(id=ids.new_id("Txn"), accountId=account.id, date=day, kind=kind,
                        amount=D(amount), instrumentId=instrument)  # fmt: skip
        return self.put(t, **kw)

    def instrument(self, symbol="VTI"):
        return self.put(Instrument(id=ids.new_id("Instr"), symbol=symbol, instrumentClass="etf"))

    def filing(self, book, jurisdiction="federal", carried=None, amends=None, **kw):
        f = Filing(id=ids.new_id("Filng"), bookId=book.id, jurisdiction=jurisdiction,
                   form="1040", carried=json.dumps(carried or {}), amendsId=amends)  # fmt: skip
        return self.put(f, **kw)

    def document(self, book, form, issuer=None, account=None, direction="received", **kw):
        filing = self.filing(book).id if direction == "filed" else None
        d = TaxDocument(id=ids.new_id("TxDoc"), bookId=book.id, direction=direction, form=form,
                        issuer=issuer, accountId=account.id if account else None,
                        filingId=filing)  # fmt: skip
        return self.put(d, **kw)

    def counts(self, book, account, counted=True, by=None, **kw):
        added = self.u[by] if by else None
        o = TaxBookAccount(bookId=book.id, accountId=account.id, counted=counted, addedById=added)
        return self.put(o, **kw)

    def share(self, account, name):
        read = self.s.scalar(select(AccessClass.id).where(AccessClass.name == "read"))
        cls = SHARE_ENTITIES["account"]
        self.put(cls(id=ids.new_id("AcShr"), targetId=account.id, accessClassId=read,
                     userId=self.u[name]))  # fmt: skip

    def dependent(self, book, name, born, student=False):
        p = self.put(Person(id=ids.new_id("Persn"), name=name, sex="female", birthYear=born))
        d = TaxBookDependent(id=ids.new_id("TxDep"), bookId=book.id, personId=p.id,
                             claimedAs="qualifying child", student=student)  # fmt: skip
        return self.put(d)


@pytest.fixture(scope="module")
def household(tmp_path_factory):
    """A bare store (no server), opened once for the module, with four users (Alice, Bob,
    Carol and Dave) and the categories."""
    tmp = tmp_path_factory.mktemp("books")
    config = Config(name="test", mode="proxy", data_dir=tmp / "data",
                    backup_dir=tmp / "backups", socket_path=tmp / "run" / "sock")  # fmt: skip
    key = os.urandom(16)
    master.create_keyring(config, key)
    store = open_store(config, key)
    db = store.db
    names = ("alice", "bob", "carol", "dave")
    users = {n: make_user(SimpleNamespace(db=db), n).id for n in names}
    with db.tx(unscoped="test") as s:
        ensure_categories(s)
    yield db, users
    db.dispose()


@pytest.fixture
def st(household):
    """Each test's records, in a write read as the server and rolled back after it."""
    db, users = household
    with db.tx(unscoped="test") as s:
        yield Store(s, users)
        s.rollback()


def test_a_books_filers_are_its_live_ones_in_the_order_named(st):
    b = st.book(filers={"bob": False, "alice": True})
    st.put(TaxBookFiler(bookId=b.id, userId=st.u["carol"]), deleted=True)
    assert [f.userId for f in books.filers(st.s, b)] == [st.u["bob"], st.u["alice"]]
    dave = st.put(TaxBookFiler(bookId=b.id, userId=st.u["dave"]))
    dave.createdAt = T - dt.timedelta(days=1)  # named first, though stored last
    st.s.flush()
    got = [f.userId for f in books.filers(st.s, b)]
    assert got == [st.u["dave"], st.u["bob"], st.u["alice"]]
    assert not books.accepted(st.s, b)
    assert books.accepted(st.s, st.book(filers={"bob": True, "alice": True}, year=2027))


def test_the_accounts_counted_are_the_accepted_filers_own_less_those_left_out(st):
    b = st.book(filers={"alice": True, "bob": False})
    kept = st.account(name="A kept")
    left = st.account(name="B left out")
    st.account(name="C deleted", deleted=True)
    st.account("bob", name="D not accepted")
    st.counts(b, left, counted=False)
    st.counts(b, kept, counted=False, deleted=True)  # a left-out undone
    again = st.account(name="E counted again")
    st.counts(b, again, counted=True)  # one of the filers' own, marked counted: still once
    got = books.counted(st.s, b)
    assert [a.name for a in got.accounts] == ["A kept", "E counted again"]
    assert [a.name for a in got.leftOut] == ["B left out"]
    assert got.added == []
    assert {o.accountId: o.counted for o in books.overrides(st.s, b)} == {
        left.id: False,
        again.id: True,
    }
    other = st.book(2027)  # another book's choices are its own
    st.counts(other, kept, counted=False)
    st.counts(other, st.account("carol", name="F added there"), by="alice")
    assert books.counted(st.s, b).accounts == got.accounts


def test_an_added_account_counts_while_its_adder_is_an_accepted_filer_who_sees_it(st):
    b = st.book(filers={"alice": True, "bob": False})
    seen = st.account("carol", name="Seen")
    unseen = st.account("carol", name="Unseen")
    gone = st.account("carol", name="Gone", deleted=True)
    by_bob = st.account("carol", name="By Bob")
    st.share(seen, "alice")
    st.share(gone, "alice")
    st.share(by_bob, "alice")
    st.share(by_bob, "bob")
    for a in (seen, unseen, gone):
        st.counts(b, a, by="alice")
    st.counts(b, by_bob, by="bob")  # bob hasn't accepted the book
    st.counts(b, st.account("carol", name="Undone"), by="alice", deleted=True)
    st.counts(b, seen, by="bob", deleted=True)  # an earlier choice, undone: not who added it
    st.counts(st.book(2027), seen, by="bob")  # another book's: not who added it here
    got = books.counted(st.s, b)
    assert [a.name for a in got.accounts] == ["Seen"] and got.added == [seen.id]


def test_an_added_account_copied_without_its_adder_counts_while_an_accepted_filer_sees_it(st):
    b = st.book(filers={"alice": True, "bob": False})
    seen = st.account("carol", name="Seen by Alice")
    bobs = st.account("carol", name="Seen by Bob")
    st.share(seen, "alice")
    st.share(bobs, "bob")
    st.counts(b, seen)
    st.counts(b, bobs)
    assert books.counted(st.s, b).added == [seen.id]


def test_a_books_filings_and_documents_are_its_live_ones_in_order(st):
    """Filings by jurisdiction, then each kind and the documents as made (`createdAt`, which
    here differs from the order they were stored in)."""
    b = st.book()
    state = st.filing(b, "state")
    second = st.filing(b)
    st.filing(b, deleted=True)
    first = st.filing(b)
    first.createdAt = second.createdAt - dt.timedelta(minutes=1)
    st.filing(st.book(year=2025))
    assert books.filings(st.s, b) == [first, second, state]
    composite = st.document(b, "1099 (composite)")
    st.document(b, "1099-INT", deleted=True)
    w2 = st.document(b, "W-2")
    w2.createdAt = composite.createdAt - dt.timedelta(minutes=1)
    assert books.documents(st.s, b) == [w2, composite]


@pytest.mark.parametrize(
    ("type", "moves", "forms"),
    [
        ("brokerage", [], ["1099 (composite)"]),
        ("ira", [], []),
        ("ira", ["in"], ["5498"]),
        ("roth-ira", ["out"], ["1099-R"]),
        ("ira", ["in", "out"], ["5498", "1099-R"]),
        ("401k", ["in"], []),
        ("401k", ["out"], ["1099-R"]),
        ("roth-ira", ["in"], ["5498"]),
        ("403b", ["out"], ["1099-R"]),
        ("457b", ["out"], ["1099-R"]),
        ("hsa", [], ["5498-SA"]),
        ("hsa", ["out"], ["5498-SA", "1099-SA"]),
        ("529", ["in"], []),
        ("529", ["out"], ["1099-Q"]),
        ("mortgage", [], ["1098"]),
        ("heloc", [], ["1098"]),
        ("student-loan", [], ["1098-E"]),
        ("crypto-exchange", [], ["1099-DA"]),
        ("credit-card", ["in", "out"], []),
    ],
)
def test_each_kind_of_account_expects_its_forms(st, type, moves, forms):
    a = st.account(type=type, name="Acct", institution="Inst")
    for way in moves:
        st.txn(a, dt.date(2026, 6, 1), "100" if way == "in" else "-100")
    got = books.expected(st.s, st.book())
    assert [e.form for e in got] == forms
    assert all((e.issuer, e.accountId) == ("Inst", a.id) for e in got)
    assert all(e.why.startswith("From Acct: ") and e.document is None for e in got)


def test_the_forms_say_why_and_name_the_institution_or_else_the_account(st):
    st.account(type="mortgage", name="Home loan")
    st.account(type="hsa", name="HSA", institution="Fidelity")
    st.account(type="ira", name="IRA")
    st.account(type="529", name="College")
    st.account(type="brokerage", name="Taxable")
    st.account(type="student-loan", name="Loan")
    st.account(type="crypto-exchange", name="Coins")
    st.account(type="401k", name="Plan")
    moving = ("ira", "529", "hsa", "401k")
    for a in st.s.scalars(select(Account).where(Account.type.in_(moving))):
        st.txn(a, dt.date(2026, 6, 1), "-1")
        st.txn(a, dt.date(2026, 6, 1), "1")
    got = books.expected(st.s, st.book())
    assert sorted((e.form, e.issuer, e.why) for e in got) == [
        ("1098", "Home loan", "From Home loan: mortgage interest"),
        ("1098-E", "Loan", "From Loan: student-loan interest"),
        ("1099 (composite)", "Taxable", "From Taxable: a taxable brokerage account"),
        ("1099-DA", "Coins", "From Coins: a crypto exchange"),
        ("1099-Q", "College", "From College: withdrawals"),
        ("1099-R", "IRA", "From IRA: distributions"),
        ("1099-R", "Plan", "From Plan: distributions"),
        ("1099-SA", "Fidelity", "From HSA: distributions"),
        ("5498", "IRA", "From IRA: contributions"),
        ("5498-SA", "Fidelity", "From HSA: an HSA"),
    ]


def test_money_moved_counts_only_cash_in_the_year_and_not_deleted(st):
    a = st.account(type="ira")
    vti = st.instrument()
    st.txn(a, dt.date(2025, 12, 31), "100")  # last year
    st.txn(a, dt.date(2027, 1, 1), "-100")  # next year
    st.txn(a, dt.date(2026, 5, 1), "-100", kind="buy", instrument=vti.id)  # a trade
    st.txn(a, dt.date(2026, 5, 1), "100", deleted=True)
    st.txn(st.account(type="ira"), dt.date(2026, 5, 1), "100")  # another account
    assert not books._paid_in(st.s, a, 2026)
    assert not books._paid_out(st.s, a, 2026)
    st.txn(a, dt.date(2026, 6, 1), "0")  # nothing moved either way
    assert not books._paid_in(st.s, a, 2026)
    assert not books._paid_out(st.s, a, 2026)
    st.txn(a, dt.date(2026, 6, 1), "0.01")  # a cent is money moved
    assert books._paid_in(st.s, a, 2026)
    assert not books._paid_out(st.s, a, 2026)
    st.txn(a, dt.date(2026, 6, 1), "-0.01")
    assert books._paid_out(st.s, a, 2026)


def test_money_moved_takes_in_the_years_first_and_last_days(st):
    a = st.account(type="ira")
    st.txn(a, dt.date(2026, 12, 31), "5")
    st.txn(a, dt.date(2026, 1, 1), "-5")
    assert books._paid_in(st.s, a, 2026) and books._paid_out(st.s, a, 2026)


def test_interest_is_the_years_interest_on_the_account_alone(st):
    a = st.account(type="savings")
    other = st.account(type="savings")
    assert books._interest(st.s, a, 2026) == 0
    st.txn(a, dt.date(2026, 1, 1), "4.50", kind="interest")
    st.txn(a, dt.date(2026, 12, 31), "3", kind="interest")
    st.txn(a, dt.date(2025, 12, 31), "100", kind="interest")
    st.txn(a, dt.date(2027, 1, 1), "100", kind="interest")
    st.txn(a, dt.date(2026, 6, 1), "100", kind="deposit")
    st.txn(a, dt.date(2026, 6, 1), "100", kind="interest", deleted=True)
    st.txn(other, dt.date(2026, 6, 1), "100", kind="interest")
    assert books._interest(st.s, a, 2026) == D("7.50")


@pytest.mark.parametrize("type", ["checking", "savings", "money-market", "cd"])
def test_a_bank_account_expects_a_1099_int_from_10_of_interest(st, type):
    a = st.account(type=type, name="Bank")
    st.txn(a, dt.date(2026, 3, 1), "9.99", kind="interest")
    b = st.book()
    assert books.expected(st.s, b) == []
    st.txn(a, dt.date(2026, 4, 1), "0.01", kind="interest")
    got = books.expected(st.s, b)
    assert [(e.form, e.why) for e in got] == [("1099-INT", "From Bank: $10 or more of interest")]


def test_last_years_received_documents_are_expected_again_unless_already_expected(st):
    brk = st.account(type="brokerage", name="Taxable", institution="Fidelity")
    st.account(type="mortgage", name="Home", institution="Rocket")
    last = st.book(2025)
    st.document(last, "Reply", direction="filed")  # one filed, not received: never expected
    st.document(last, "W-2", issuer="Acme")
    st.document(last, "1099 (composite)", account=brk)  # this year expects it from the account
    st.document(last, "1098", issuer="Rocket")  # and this from the issuer
    st.document(last, "1098", issuer="Other bank")  # another lender's: expected again
    st.document(last, "W-2", issuer="Bolt")  # the same form from two issuers: both
    one, two = st.account(type="savings"), st.account(type="savings")
    st.document(last, "1099-INT", account=one)  # and from two accounts
    st.document(last, "1099-INT", account=two)
    st.document(last, "1099-B", issuer="Gone", deleted=True)
    got = books.expected(st.s, st.book(2026, fromLastYear=True))
    assert [(e.form, e.issuer, e.why) for e in got] == [
        ("1098", "Rocket", "From Home: mortgage interest"),
        ("1099 (composite)", "Fidelity", "From Taxable: a taxable brokerage account"),
        ("W-2", "Acme", "Received in 2025"),
        ("1098", "Other bank", "Received in 2025"),
        ("W-2", "Bolt", "Received in 2025"),
        ("1099-INT", None, "Received in 2025"),
        ("1099-INT", None, "Received in 2025"),
    ]
    assert [e.accountId for e in got if e.form == "1099-INT"] == [one.id, two.id]
    # Not started from last year: only this year's accounts.
    assert [e.form for e in books.expected(st.s, st.book(2026))] == ["1098", "1099 (composite)"]


def test_a_form_last_year_from_another_account_or_issuer_is_expected_again(st):
    brk = st.account(type="brokerage", name="Taxable", institution="Fidelity")
    last = st.book(2025)
    st.document(last, "1099 (composite)", issuer="Fidelity", account=st.account(name="Old"))
    st.document(last, "1099 (composite)", issuer="Schwab", account=brk)
    got = books.expected(st.s, st.book(2026, fromLastYear=True))
    assert [(e.issuer, e.accountId) for e in got] == [("Fidelity", brk.id)]
    st.document(last, "1099 (composite)", issuer="Vanguard")
    got = books.expected(st.s, st.book(2026, fromLastYear=True, owner="bob",
                                       filers={"alice": True}))  # fmt: skip
    assert [(e.issuer, e.why) for e in got] == [
        ("Fidelity", "From Taxable: a taxable brokerage account"),
        ("Vanguard", "Received in 2025"),
    ]


def test_a_student_dependent_expects_a_1098_t_unless_last_years_stands_for_them(st):
    last = st.book(2025)
    st.document(last, "1098-T", issuer="State U")
    b = st.book(2026, fromLastYear=True)
    st.dependent(b, "Ann", 2006, student=True)
    st.dependent(b, "Ben", 2008, student=False)
    assert [(e.form, e.issuer, e.why) for e in books.expected(st.s, b)] == [
        ("1098-T", "State U", "Received in 2025"),
    ]
    st.dependent(b, "Cat", 2007, student=True)
    got = books.expected(st.s, b)
    assert [(e.form, e.issuer, e.accountId, e.why) for e in got] == [
        ("1098-T", "State U", None, "Received in 2025"),
        ("1098-T", None, None, "For Cat: a student"),
    ]


def test_childcare_paid_for_dependents_under_13_expects_the_providers_statement(st):
    care = st.s.scalar(select(Category.id).where(Category.taxTag == "childcare"))
    bank = st.account()
    b = st.book()
    st.dependent(b, "Ann", 2014)  # 12 on Dec 31
    st.dependent(b, "Ben", 2013)  # 13
    st.dependent(b, "Cat", 2020)
    assert books.expected(st.s, b) == []  # nothing paid
    t = st.txn(bank, dt.date(2026, 5, 1), "-200", kind="withdrawal")
    t.categoryId = care
    st.s.flush()
    got = books.expected(st.s, b)
    assert [(e.form, e.issuer, e.accountId, e.why) for e in got] == [
        ("Childcare provider statement", None, None, "For Ann and Cat: childcare paid")
    ]
    older = st.book(2027, owner="bob")
    st.dependent(older, "Ben", 2013)
    assert books.expected(st.s, older) == []


def test_a_document_received_meets_the_one_expected_from_its_account_or_issuer(st):
    brk = st.account(type="brokerage", name="Taxable", institution="Fidelity")
    st.account(type="mortgage", name="Home", institution="Rocket")
    st.account(type="student-loan", name="Loan", institution="Nelnet")
    last = st.book(2025)
    st.document(last, "W-2", issuer="Acme")
    b = st.book(2026, fromLastYear=True)
    by_account = st.document(b, "1099 (composite)", issuer="Someone", account=brk)
    by_issuer = st.document(b, "1098", issuer="ROCKET")
    st.document(b, "1098-E", issuer="Other")  # another issuer: not this one
    st.document(b, "W-2", direction="filed")
    st.document(b, "W-2", issuer="Zed")  # another employer's: not the one expected
    w2 = st.document(b, "W-2", issuer="acme")
    got = {e.form: e.document for e in books.expected(st.s, b)}
    assert got == {"1099 (composite)": by_account, "1098": by_issuer, "1098-E": None, "W-2": w2}


def test_a_document_received_meets_one_expected_and_the_first_it_can(st):
    b = st.book(2026)
    for name in ("Ann", "Ben"):
        st.dependent(b, name, 2006, student=True)
    st.document(b, "1099-INT", issuer="Bank")
    first = st.document(b, "1098-T", issuer="State U")
    got = books.expected(st.s, b)
    assert [(e.why, e.document) for e in got] == [
        ("For Ann: a student", first),
        ("For Ben: a student", None),
    ]
    second = st.document(b, "1098-T")
    assert [e.document for e in books.expected(st.s, b)] == [first, second]


def test_a_document_without_account_or_issuer_meets_none_with_one(st):
    st.account(type="mortgage", name="Home", institution="Rocket")
    b = st.book(2026)
    st.document(b, "1098")
    assert [e.document for e in books.expected(st.s, b)] == [None]
    brk = st.account(type="brokerage", name="Taxable")
    st.document(b, "1099 (composite)", account=st.account(name="Other"))
    got = [e for e in books.expected(st.s, b) if e.accountId == brk.id]
    assert [e.document for e in got] == [None]


def test_a_filer_has_one_accepted_book_a_year(st):
    mine = st.book(2025)
    st.book(2025, owner="bob", filers={"bob": True, "alice": False})
    st.book(2025, owner="carol", filers={"carol": True, "alice": True}, deleted=True)
    st.book(2024)
    st.put(TaxBookFiler(bookId=st.book(2025, owner="bob").id, userId=st.u["alice"],
                        acceptedAt=T), deleted=True)  # fmt: skip
    assert books.accepted_on(st.s, st.u["alice"], 2025).id == mine.id
    assert books.accepted_on(st.s, st.u["alice"], 2025, but=mine.id) is None
    assert books.accepted_on(st.s, st.u["alice"], 2023) is None


def test_last_years_books_wait_for_every_filer_to_accept_this_one(st):
    last = st.book(2025)
    b = st.book(2026, filers={"alice": True, "bob": False})
    assert books.last_years(st.s, b) == []
    st.s.scalars(select(TaxBookFiler).where(TaxBookFiler.bookId == b.id)).all()[1].acceptedAt = T
    st.s.flush()
    got = books.last_years(st.s, b)
    assert [(ly.book.id, ly.filers, ly.joint) for ly in got] == [(last.id, [st.u["alice"]], False)]


def test_last_years_books_are_one_a_filer_in_the_order_made(st):
    bobs = st.book(2025, owner="bob")
    alices = st.book(2025)
    b = st.book(2026, filers={"alice": True, "bob": True, "carol": True})
    got = books.last_years(st.s, b)
    assert [(ly.book.id, ly.filers, ly.joint) for ly in got] == [
        (bobs.id, [st.u["bob"]], False),
        (alices.id, [st.u["alice"]], False),
    ]


def test_a_joint_last_year_is_split_only_when_not_all_its_filers_are_on_this_book(st):
    joint = st.book(2025, filers={"alice": True, "bob": True, "carol": False})
    both = st.book(2026, filers={"alice": True, "bob": True})
    assert [(ly.book.id, ly.filers, ly.joint) for ly in books.last_years(st.s, both)] == [
        (joint.id, [st.u["alice"], st.u["bob"]], False)
    ]
    alone = st.book(2026, owner="bob", filers={"bob": True})
    assert [(ly.book.id, ly.joint) for ly in books.last_years(st.s, alone)] == [(joint.id, True)]
    one = st.book(2025, owner="carol", filers={"carol": True, "bob": False})
    solo = st.book(2026, owner="carol", filers={"carol": True})
    assert [(ly.book.id, ly.joint) for ly in books.last_years(st.s, solo)] == [(one.id, False)]


def test_last_years_carried_figures_are_its_filings_that_carry_any(st):
    last = st.book(2025)
    some = st.filing(last, carried={"basis8606": "50"})
    st.filing(last, "state")  # nothing typed
    every = st.filing(last, "state", carried={"agi": "1", "totalTax": "2"})
    st.filing(last, carried={"agi": "1"}, deleted=True)
    b = st.book(2026)
    got = books.carried_from_last_year(st.s, b)
    assert [(f.id, figures) for f, figures, _ in got] == [
        (some.id, {"basis8606": "50"}),
        (every.id, {"agi": "1", "totalTax": "2"}),
    ]
    assert all(ly.book.id == last.id for _, _, ly in got)
    assert books.carried_from_last_year(st.s, st.book(2026, owner="bob")) == []


def test_last_years_federal_figures_are_the_amended_returns_once_there_is_one(st):
    last = st.book(2025)
    original = st.filing(last, carried={"agi": "1"})
    st.filing(last, "state", carried={"agi": "2"})
    b = st.book(2026)
    assert [figures for figures, _ in books.federal_figures(st.s, b)] == [{"agi": "1"}]
    st.filing(last, carried={"agi": "3"}, amends=original.id)
    st.filing(last, carried={"agi": "4"}, amends=original.id)
    st.filing(last, carried={"agi": "5"})
    assert [figures for figures, _ in books.federal_figures(st.s, b)] == [{"agi": "4"}]
    assert books.federal_figures(st.s, st.book(2026, owner="bob")) == []


def test_the_carryover_sums_last_years_federal_returns(st):
    st.filing(st.book(2025), carried={"capitalLossShort": "100.50", "capitalLossLong": "200"})
    st.filing(st.book(2025, owner="bob"), carried={"capitalLossLong": "30", "agi": "1"})
    b = st.book(2026, filers={"alice": True, "bob": True})
    assert books.carryover(st.s, b) == (D("100.50"), D("230"), False)
    b.carryoverShareShort = b.carryoverShareLong = D(9)  # no joint return to split: no share
    assert books.carryover(st.s, b) == (D("100.50"), D("230"), False)
    assert books.carryover(st.s, st.book(2026, owner="carol")) == (0, 0, False)


def test_a_joint_carryover_is_the_filers_share_once_typed(st):
    st.filing(st.book(2025, filers={"alice": True, "bob": True}),
              carried={"capitalLossShort": "100", "capitalLossLong": "200"})  # fmt: skip
    b = st.book(2026)
    assert books.carryover(st.s, b) == (0, 0, True)
    b.carryoverShareShort = D("40")
    assert books.carryover(st.s, b) == (D("40"), 0, False)
    b.carryoverShareShort, b.carryoverShareLong = None, D("150")
    assert books.carryover(st.s, b) == (0, D("150"), False)


@pytest.mark.parametrize("carried", [{"capitalLossShort": "1"}, {"capitalLossLong": "1"}])
def test_a_joint_carryover_of_either_term_asks_for_the_filers_share(st, carried):
    st.filing(st.book(2025, filers={"alice": True, "bob": True}), carried=carried)
    assert books.carryover(st.s, st.book(2026)) == (0, 0, True)


def test_a_joint_return_without_a_carryover_asks_for_no_share(st):
    st.filing(st.book(2025, filers={"alice": True, "bob": True}),
              carried={"agi": "1", "capitalLossShort": "0.00"})  # fmt: skip
    st.filing(st.book(2025, owner="carol"), carried={"capitalLossShort": "5"})
    b = st.book(2026, filers={"alice": True, "carol": True})
    assert books.carryover(st.s, b) == (D(5), 0, False)


def test_names_are_the_users_display_names(st):
    assert books.names(st.s, [st.u["alice"], st.u["bob"]]) == {
        st.u["alice"]: "Alice",
        st.u["bob"]: "Bob",
    }


def test_a_book_is_got_by_who_holds_it_for_what_they_may_do(st):
    from moolakata.errors import Problem

    b = st.book(filers={"alice": True, "bob": False})
    read = st.s.scalar(select(AccessClass.id).where(AccessClass.name == "read"))
    share = SHARE_ENTITIES["tax-book"]
    st.put(share(id=ids.new_id("TbShr"), targetId=b.id, accessClassId=read, userId=st.u["carol"]))
    got, p = books.get(st.s, st.u["alice"], b.id, "deletable")
    assert got.id == b.id and p.mine
    assert books.get(st.s, st.u["alice"], b.id, "write")[0].id == b.id
    assert books.get(st.s, st.u["carol"], b.id)[0].id == b.id
    for need in ("write", "configurable"):
        with pytest.raises(Problem) as e:
            books.get(st.s, st.u["carol"], b.id, need)
        assert (e.value.status, e.value.code) == (403, "read-only")
        assert e.value.detail == "This tax book is shared with you to read."
    with pytest.raises(Problem) as e:
        books.get(st.s, st.u["bob"], b.id)  # named, not accepted: not shown
    assert (e.value.status, e.value.code, e.value.detail) == (404, "not-found", "Not found")
    with pytest.raises(Problem) as e:
        books.get(st.s, st.u["alice"], "TaxBk_none")
    assert e.value.status == 404


def test_the_books_a_user_holds_are_listed_newest_year_first_then_as_made(st):
    older = st.book(2025)
    second = st.book(2026)
    first = st.book(2026, owner="bob", filers={"bob": True, "alice": True})
    first.createdAt = second.createdAt - dt.timedelta(minutes=1)  # made first, stored later
    st.book(2027, owner="bob", filers={"bob": True, "alice": False})
    got = [b.id for b, _ in books.visible(st.s, st.u["alice"])]
    assert got == [first.id, second.id, older.id]


def test_the_federal_due_date_is_the_next_years_april_15_or_the_next_business_day(st):
    from moolakata.taxes.dates import next_business_day

    assert books.federal_due(st.s, 2026) == dt.date(2027, 4, 15)
    assert books.federal_due(st.s, 2027) == next_business_day(dt.date(2028, 4, 15))
    assert books.federal_due(st.s, 2027) != dt.date(2028, 4, 15)  # a Saturday


def test_the_federal_due_date_is_the_books_own_years_with_an_admins_correction(st):
    """An admin's correction of 2025's due date moves 2025's book only, whatever year it is."""
    from moolakata.store.entities.projections import TaxFigure

    st.put(TaxFigure(id=ids.new_id("TaxFg"), year=2025, key="federalDue", value="[5, 1]"))
    assert books.federal_due(st.s, 2025) == dt.date(2026, 5, 1)  # a Friday
    assert books.federal_due(st.s, 2026) == dt.date(2027, 4, 15)


def test_a_joint_carryover_share_adds_to_a_separate_returns_carryover(st):
    """Joint after a separate return and a joint one: the separate return's carryover and the
    share typed of the joint one, added (made in that order, so the share comes last)."""
    st.filing(
        st.book(2025, owner="carol"), carried={"capitalLossShort": "5", "capitalLossLong": "7"}
    )
    st.filing(st.book(2025, filers={"alice": True, "bob": True}),
              carried={"capitalLossShort": "100", "capitalLossLong": "200"})  # fmt: skip
    b = st.book(2026, filers={"alice": True, "carol": True})
    b.carryoverShareShort, b.carryoverShareLong = D(40), D(150)
    assert books.carryover(st.s, b) == (D(45), D(157), False)


def test_a_share_typed_counts_once_though_both_filers_bring_a_joint_return_to_split(st):
    """Alice filed jointly with Bob, and Carol with Dave; filing together now, the one share
    they type of last year's joint carryovers counts once."""
    st.filing(st.book(2025, filers={"alice": True, "bob": True}),
              carried={"capitalLossShort": "100"})  # fmt: skip
    st.filing(st.book(2025, owner="carol", filers={"carol": True, "dave": True}),
              carried={"capitalLossLong": "60"})  # fmt: skip
    b = st.book(2026, filers={"alice": True, "carol": True})
    assert books.carryover(st.s, b) == (0, 0, True)
    b.carryoverShareShort, b.carryoverShareLong = D(40), D(30)
    assert books.carryover(st.s, b) == (D(40), D(30), False)
