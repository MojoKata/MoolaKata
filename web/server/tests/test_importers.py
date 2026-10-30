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
    # B5: OPTBUYTYPE and OPTSELLTYPE give the four option trades, CLOSUREOPT the option's end;
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
    # B18: each day's last running balance is its latest row's, not its first in the file.
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


def test_a_reinvested_dividend_is_income_once_and_a_buy_with_none():
    # B3, S2.5: a dividend row carries the income; the buy carries none, so the income panel
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
    """CR3-14: five letters ending in X is a fund; any other ticker a listed share, which the
    price sources fetch; anything else isn't known."""
    from moolakata.store.repos.ledger import class_by_symbol

    assert class_by_symbol(symbol) == cls
