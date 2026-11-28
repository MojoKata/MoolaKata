import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from moolakata.importers import csvfile, ofx
from moolakata.importers.parsed import ReadError

FIX = Path(__file__).parent / "fixtures"


def test_ofx_bank_statement():
    p = ofx.read((FIX / "bank.ofx").read_bytes())
    assert p.accountKind == "bank" and p.institution == "First Example Bank"
    assert (p.coveredFrom, p.coveredTo) == (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert [r.kind for r in p.rows] == [
        "deposit",
        "withdrawal",
        "withdrawal",
        "transfer",
        "interest",
    ]
    assert p.rows[1].amount == D("-142.18") and p.rows[1].fitId == "20260903-1"
    assert p.balances == [(dt.date(2026, 9, 30), D("5629.09"))]


def test_ofx_dates_are_never_shifted_by_time_zone():
    data = (
        (FIX / "bank.ofx")
        .read_bytes()
        .replace(b"<DTPOSTED>20260903", b"<DTPOSTED>20260903230000[-5:EST]")
    )
    p = ofx.read(data)
    assert p.rows[1].date == dt.date(2026, 9, 3)


def test_ofx_brokerage_trades_positions_and_securities():
    p = ofx.read((FIX / "brokerage.ofx").read_bytes())
    assert p.accountKind == "investment"
    sec = p.securities["922908769"]
    assert sec.symbol == "VTI" and sec.cusip == "922908769"
    kinds = [(r.kind, r.quantity, r.amount) for r in p.rows]
    assert ("buy", D(10), D("-2500.00")) in kinds
    assert ("sell", D(5), D("1500.00")) in kinds
    assert any(r.kind == "dividend" and r.dividendType == "ordinary" for r in p.rows)
    assert p.positions[0].quantity == D(15)
    assert p.balances == [(dt.date(2026, 9, 30), D("2317.40"))]


def test_ofx_option_trades_and_their_ends():
    # OPTBUYTYPE and OPTSELLTYPE give the four option trades, CLOSUREOPT the option's end;
    # a contract is named by its OCC ticker, or by the terms OPTINFO gives.
    p = ofx.read((FIX / "options.ofx").read_bytes())
    assert p.securities["AAPL260918P150"].symbol == "AAPL260918P00150000"
    assert p.securities["MSFT261218C480"].symbol == "MSFT261218C00480000"
    assert p.securities["MSFT261218C480"].multiplier == 100
    got = [(r.kind, r.quantity, r.amount) for r in p.rows if r.security]
    assert got == [
        ("sell-to-open", D(2), D("598.70")),
        ("buy-to-open", D(1), D("-520.65")),
        ("sell-to-close", D(1), D("699.35")),
        ("buy", D(200), D("-30000.10")),
        ("assign", D(2), D(0)),
    ]
    assert p.rows[-1].relFitId == "A1"


def test_csv_option_rows_are_contracts():
    data = (
        b"Date,Action,Symbol,Quantity,Price,Fees & Comm,Amount\n"
        b"08/03/2026,Sell to Open,AAPL 09/18/2026 150.00 P,2,3.00,1.30,598.70\n"
        b"09/18/2026,Assigned,AAPL 09/18/2026 150.00 P,2,,,\n"
        b"09/18/2026,Buy,AAPL,200,150.00,,-30000.00\n"
    )
    p = csvfile.read(data, csvfile.propose(data, trades=True)["mapping"])
    assert [r.kind for r in p.rows] == ["sell-to-open", "assign", "buy"]
    assert p.rows[0].security == "AAPL260918P00150000"
    assert p.securities["AAPL260918P00150000"].instrumentClass == "option"
    plain = data.replace(b"Sell to Open", b"Sell")
    with pytest.raises(ReadError, match="is an option"):
        csvfile.read(plain, csvfile.propose(plain, trades=True)["mapping"])


def test_not_ofx_is_refused():
    with pytest.raises(ReadError):
        ofx.read(b"OFXHEADER:100\n<OFX><nonsense")


CSV = b"""Account: Checking ****4821
Exported 2026-10-01

Posted Date,Description,Debit,Credit,Balance
09/01/2026,ACME PAYROLL,,"3,120.00","4,120.00"
09/03/2026,KROGER #123,142.18,,"3,977.82"
09/05/2026,CAFE,(4.50),,"3,973.32"
"""


def test_a_newest_first_csv_is_read_oldest_first():
    # Each day's last running balance is its latest row's, not its first in the file.
    from moolakata.ledger import balances

    data = (
        b"Date,Description,Amount,Balance\n"
        b"2026-09-02,Lunch,-12.00,968.00\n"
        b"2026-09-02,Coffee,-5.00,980.00\n"
        b"2026-09-01,Groceries,-15.00,985.00\n"
    )
    p = csvfile.read(data, csvfile.propose(data)["mapping"])
    assert [r.payee for r in p.rows] == ["Groceries", "Coffee", "Lunch"]

    class T:
        def __init__(self, i, r):
            self.date, self.runningBalance, self.amount = r.date, r.runningBalance, r.amount
            self.createdAt, self.id = i, str(i)

    pts = balances.points([], [T(i, r) for i, r in enumerate(p.rows)])
    assert [(d.day, b) for d, b, _, _ in pts] == [(1, D("985.00")), (2, D("968.00"))]


def test_csv_proposal_finds_the_header_and_columns():
    p = csvfile.propose(CSV)
    m = p["mapping"]
    assert m["skipRows"] == 2
    assert (m["date"], m["payee"], m["debit"], m["credit"], m["balance"]) == (
        "Posted Date",
        "Description",
        "Debit",
        "Credit",
        "Balance",
    )
    assert m["dateFormat"] == "%m/%d/%Y" and m["amount"] is None
    assert len(p["sample"]) == 3


def test_csv_reads_with_its_mapping():
    p = csvfile.read(CSV, csvfile.propose(CSV)["mapping"])
    assert [r.amount for r in p.rows] == [D("3120.00"), D("-142.18"), D("-4.50")]
    assert p.rows[2].runningBalance == D("3973.32")
    assert (p.coveredFrom, p.coveredTo) == (dt.date(2026, 9, 1), dt.date(2026, 9, 5))


@pytest.mark.parametrize(
    "text, value",
    [
        ("$1,234.56", D("1234.56")),
        ("(12.00)", D("-12")),
        ("12.00-", D("-12")),
        ("1.234,56", D("1234.56")),
        ("−7.25", D("-7.25")),
        ("", None),
    ],
)
def test_amounts_as_banks_write_them(text, value):
    assert csvfile.amount(text) == value


def test_card_exports_with_positive_spending():
    data = b"Date,Description,Amount\n2026-09-02,Coffee,4.50\n2026-09-03,Refund,-10.00\n"
    m = csvfile.propose(data)["mapping"]
    m["negateAmounts"] = True
    p = csvfile.read(data, m)
    assert [r.amount for r in p.rows] == [D("-4.50"), D("10.00")]


def test_trade_history_csv():
    data = (
        b"Date,Action,Symbol,Quantity,Price,Fees,Amount\n"
        b"2026-01-05,Buy,VTI,10,250.00,0,-2500.00\n"
        b"2026-06-30,Dividend,VTI,,,,18.40\n"
    )
    m = csvfile.propose(data, trades=True)["mapping"]
    assert m["symbol"] == "Symbol" and m["action"] == "Action"
    p = csvfile.read(data, m)
    assert [r.kind for r in p.rows] == ["buy", "dividend"]
    assert p.rows[0].quantity == D(10) and "VTI" in p.securities


def test_bad_rows_name_their_row():
    data = b"Date,Description,Amount\n2026-09-02,Coffee,4.50\nyesterday,Tea,3.00\n"
    m = csvfile.propose(data)["mapping"]
    m["dateFormat"] = "%Y-%m-%d"
    with pytest.raises(ReadError, match="Row 3"):
        csvfile.read(data, m)


def test_a_csv_that_cant_be_read_says_why():
    """S1.3.2: a file that isn't text, text in no encoding read here, an empty file, a file with
    nothing below its header, a column the mapping names that isn't there, and an amount that
    isn't one, named by its row."""
    with pytest.raises(ReadError, match="not a text file"):
        csvfile.decode(b"Date\x00,Amount\n")
    with pytest.raises(ReadError, match="can't be read"):
        csvfile.decode(b"Date,Payee\n\x81\x8d\x8f\xff\n")
    assert csvfile.decode("Date,Payee\nCafé\n".encode("cp1252")) == "Date,Payee\nCafé\n"
    with pytest.raises(ReadError, match="is empty"):
        csvfile.propose(b"")
    data = b"Date,Description,Amount\n2026-09-02,Coffee,4.50\n"
    m = csvfile.propose(data)["mapping"]
    with pytest.raises(ReadError, match="no rows below its header"):
        csvfile.read(b"Account 4821\n", {**m, "skipRows": 1})
    assert csvfile.read(b"Date,Description,Amount\n", m).rows == [], "a header alone adds nothing"
    with pytest.raises(ReadError, match="no column called 'Amount'"):
        csvfile.read(b"Date,Description,Total\n2026-09-02,Coffee,4.50\n", m)
    with pytest.raises(ReadError, match=r"Row 2: 'four fifty' is not an amount"):
        csvfile.read(b"Date,Description,Amount\n2026-09-02,Coffee,four fifty\n", m)
    with pytest.raises(ReadError, match="Choose the date column"):
        csvfile.read(data, {**m, "date": None})


def test_a_mapping_names_each_column_it_lacks_at_its_field():
    """S1.3.2, R3.11: no date column, no date format, no amount (nor debit and credit), and no
    description (nor symbol), each refused at its field in its words."""
    assert csvfile.check_mapping({}) == [
        ("date", "Choose the date column."),
        ("dateFormat", "Choose how the dates are written."),
        ("amount", "Choose the amount column, or the debit and credit columns."),
        ("payee", "Choose the description or payee column."),
    ]
    whole = {"date": "D", "dateFormat": "%Y-%m-%d", "debit": "Out", "symbol": "S"}
    assert csvfile.check_mapping(whole) == []


def test_a_csv_row_without_a_date_is_passed_over():
    data = b"Date,Description,Amount\n2026-09-02,Coffee,4.50\n,Subtotal,4.50\n"
    p = csvfile.read(data, csvfile.propose(data)["mapping"])
    assert [r.payee for r in p.rows] == ["Coffee"]


def test_a_csv_proposal_without_a_date_column_starts_at_the_top():
    """No row in the first 15 names a date: the header is taken as the first row, and no
    date column is proposed."""
    data = b"When,Payee,Amount\n2026-09-02,Coffee,4.50\n"
    p = csvfile.propose(data)
    assert p["mapping"]["skipRows"] == 0 and p["mapping"]["date"] is None


def test_a_csv_proposal_with_an_amount_column_drops_debit_and_credit():
    data = b"Date,Description,Amount,Debit,Credit\n2026-09-02,Coffee,-4.50,4.50,\n"
    m = csvfile.propose(data)["mapping"]
    assert (m["amount"], m["debit"], m["credit"]) == ("Amount", None, None)


def test_a_cash_foreign_tax_row_is_money_out():
    data = (
        b"Date,Action,Symbol,Description,Amount\n"
        b"2026-06-30,Foreign Tax Paid,,Withheld,3.10\n"
        b"2026-06-30,Foreign Tax Paid,VXUS,Withheld,2.00\n"
    )
    m = csvfile.propose(data, trades=True)["mapping"]
    p = csvfile.read(data, m)
    assert [(r.kind, r.amount) for r in p.rows] == [
        ("foreign-tax", D("-3.10")),
        ("foreign-tax", D("-2.00")),
    ]


def test_a_reinvested_dividend_is_income_once_and_a_buy_with_none():
    # S2.5: a dividend row carries the income; the buy carries none, so the income panel
    # counts $100 as $100 of 1099-DIV, never $200.
    p = ofx.read((FIX / "reinvest.ofx").read_bytes())
    got = [(r.kind, r.amount, r.dividendType) for r in p.rows]
    assert got == [("dividend", D("100.00"), "ordinary"), ("reinvest", D("-100.00"), None)]
    assert p.rows[1].quantity == D("0.4") and p.rows[1].price == D("250.00")


@pytest.mark.parametrize(
    "symbol, cls",
    [
        ("FXAIX", "mutual-fund"),
        ("SWVXX", "mutual-fund"),
        ("VTI", "equity"),
        ("BRK.B", "equity"),
        ("GOOGL", "equity"),
        ("912828ZT0", "other"),
        ("TARGET 2045 TRUST", "other"),
    ],
)
def test_a_csv_security_is_classed_by_its_symbols_shape(symbol, cls):
    """Five letters ending in X is a fund; any other ticker a listed share, which the
    price sources fetch; anything else isn't known."""
    from moolakata.store.repos.ledger import class_by_symbol

    assert class_by_symbol(symbol) == cls


def test_a_trades_cash_follows_its_action():
    """A buy's cash goes out and a sale's comes in, whatever sign the file writes;
    shares moved in or out move no cash; the account's own currency is cash."""
    data = (
        b"Date,Action,Symbol,Quantity,Amount\n"
        b"2026-09-01,Deposit,USD,1000,1000.00\n"
        b"2026-09-02,Buy,BTC,0.01,600.00\n"
        b"2026-09-03,Sell,BTC,0.005,-310.00\n"
        b"2026-09-04,Receive,ETH,1,2500.00\n"
    )
    m = csvfile.propose(data, trades=True)["mapping"]
    m["payee"] = "Action"
    p = csvfile.read(data, m)
    got = [(r.kind, r.amount, r.security) for r in p.rows]
    assert got == [
        ("deposit", D("1000.00"), None),
        ("buy", D("-600.00"), "BTC"),
        ("sell", D("310.00"), "BTC"),
        ("transfer-in", D(0), "ETH"),
    ]


def test_notes_below_a_csvs_rows_are_left_out():
    """The rows end at the first blank line after them; a blank line between the
    header and the first row doesn't end them."""
    data = (
        b"Date,Description,Amount\n\n2026-09-01,Pay,100.00\n2026-09-02,Shop,-10.00\n\n"
        b'"Downloaded 10/01/2026 9:14 am"\n"Not for distribution."\n'
    )
    assert csvfile.looks_like_csv(data)
    proposal = csvfile.propose(data)
    assert proposal["trailer"] == 2 and len(proposal["sample"]) == 2
    assert [r.payee for r in csvfile.read(data, proposal["mapping"]).rows] == ["Pay", "Shop"]


def test_a_single_days_rows_keep_their_order_when_the_balances_dont_tell():
    """Rows that chain neither way, or have no balances, stay in the file's order."""
    data = (
        b"Date,Description,Amount,Balance\n2026-09-01,One,-1.00,50.00\n2026-09-01,Two,-2.00,70.00\n"
    )
    assert [r.payee for r in csvfile.read(data, csvfile.propose(data)["mapping"]).rows] == [
        "One",
        "Two",
    ]
    bare = b"Date,Description,Amount\n2026-09-01,One,-1.00\n2026-09-01,Two,-2.00\n"
    assert [r.payee for r in csvfile.read(bare, csvfile.propose(bare)["mapping"]).rows] == [
        "One",
        "Two",
    ]


def test_an_ofx_date_not_written_as_a_date_falls_back_to_ofxtools():
    from moolakata.importers.ofx import _raw

    assert _raw("20260930200000[-5:EST]") == dt.date(2026, 9, 30)
    assert _raw("") is None and _raw("2026-09") is None


def test_an_ofx_brokers_other_actions_and_securities():
    """S1.3.1: shares moved in and out, a return of capital, an expense and margin interest as
    fees, a long-term gain, interest and a 2-for-1 split; a journal between sub-accounts is no
    row. A fund named a money market is one, an option without an OCC ticker keeps the file's,
    and a file without its institution's name has none."""
    p = ofx.read((FIX / "actions.ofx").read_bytes())
    assert p.institution is None and p.accountNumber == "X7654321"
    got = [(r.kind, r.amount, r.quantity, r.dividendType) for r in p.rows]
    assert got == [
        ("transfer-in", D(0), D(5), None),
        ("transfer-out", D(0), D(2), None),
        ("return-of-capital", D("12.00"), None, None),
        ("fee", D("-3.00"), None, None),
        ("fee", D("-4.00"), None, None),
        ("capital-gain", D("40.00"), None, "capital-gain"),
        ("interest", D("2.00"), None, None),
        ("split", D(0), None, None),
    ]
    assert p.rows[-1].splitRatio == D(2)
    assert p.securities["31617H102"].instrumentClass == "money-market"
    opt = p.securities["OPT1"]
    assert (opt.symbol, opt.instrumentClass, opt.multiplier) == ("XYZ OPTION", "option", 100)
    assert p.positions == [] and p.balances == []


def test_an_ofx_file_without_its_lists_reads_as_empty():
    """S1.3.1: a bank statement with no transaction list is its balance alone; a broker's with
    no transaction list, or no securities list, or an empty one, has none of them."""
    bank = (FIX / "bank.ofx").read_bytes()
    start, end = bank.index(b"<BANKTRANLIST>"), bank.index(b"</BANKTRANLIST>")
    p = ofx.read(bank[:start] + bank[end + len(b"</BANKTRANLIST>") :])
    assert p.rows == [] and p.balances == [(dt.date(2026, 9, 30), D("5629.09"))]
    assert (p.coveredFrom, p.coveredTo) == (None, None)
    broker = (FIX / "actions.ofx").read_bytes()
    start, end = broker.index(b"<INVTRANLIST>"), broker.index(b"</INVTRANLIST>")
    bare = broker[:start] + broker[end + len(b"</INVTRANLIST>") :]
    seclist = bare[bare.index(b"<SECLISTMSGSRSV1>") : bare.index(b"</OFX>")]
    p = ofx.read(bare.replace(seclist, b""))
    assert (p.rows, p.securities, p.accountKind) == ([], {}, "investment")
    empty = b"<SECLISTMSGSRSV1><SECLIST></SECLIST></SECLISTMSGSRSV1>\n"
    assert ofx.read(bare.replace(seclist, empty)).securities == {}


def test_an_ofx_file_of_no_statement_or_of_several_is_refused():
    """S1.3.1: one account's statement at a time."""
    bank = (FIX / "bank.ofx").read_bytes()
    start, end = bank.index(b"<BANKMSGSRSV1>"), bank.index(b"</OFX>")
    with pytest.raises(ReadError, match="holds no statement"):
        ofx.read(bank[:start] + bank[end:])
    block = bank[start + len(b"<BANKMSGSRSV1>") : bank.index(b"</BANKMSGSRSV1>")]
    twice = bank.replace(block, block + block.replace(b"<TRNUID>1", b"<TRNUID>2"))
    with pytest.raises(ReadError, match="several accounts"):
        ofx.read(twice)
