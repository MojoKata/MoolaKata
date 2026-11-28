"""An import's rows as the ledger keeps them (store/repos/ledger.py, S1.3.2), for what a file
can say that the readers' corpus doesn't: an instrument it names better than before, a position
of a security it doesn't describe, an option's end that can't be settled, an adjusted contract's
root, and lots carried in from an account deleted since."""

import datetime as dt
from decimal import Decimal as D

import pytest

from moolakata import ids
from moolakata.importers.parsed import ParsedFile, Position, Row, Security
from moolakata.options import adjust, contract, contract_of
from moolakata.store.entities.accounts import Account, Instrument, Transaction
from moolakata.store.repos import ledger

DAY = dt.date(2026, 10, 1)
CALL = "AAPL261218C00250000"  # AAPL 18 Dec 26 250 C


@pytest.fixture
def book(unscoped):
    """A session, its user and a brokerage account of theirs."""
    s, uid = unscoped
    a = Account(id=ids.new_id("Acct"), ownerId=uid, name="Brokerage", type="brokerage")
    s.add(a)
    s.flush()
    return s, uid, a


def _import(book, *rows: Row, securities=(), positions=(), name="f.ofx") -> ledger.Applied:
    s, uid, a = book
    parsed = ParsedFile(
        "ofx",
        rows=list(rows),
        securities={x.key: x for x in securities},
        positions=list(positions),
    )
    parsed.cover()
    return ledger.apply_import(s, a, uid, parsed, name, ids.new_id("Imprt"))


def _option(key: str = CALL) -> Security:
    return Security(key, key, None, "option")


def _stock(symbol: str = "AAPL") -> Security:
    return Security(symbol, symbol, None, "equity")


def test_an_instrument_known_by_its_symbol_takes_the_cusip_and_name_a_file_gives(book):
    """S2.1: found by its symbol, an instrument keeps the CUSIP and name it lacked."""
    s, _, _ = book
    vti = Instrument(id=ids.new_id("Instr"), symbol="VTI", instrumentClass="etf")
    s.add(vti)
    s.flush()
    found = ledger.instrument(s, "VTI", "Vanguard Total Stock Market", "etf", "922908769")
    assert found is vti
    assert (vti.cusip, vti.name) == ("922908769", "Vanguard Total Stock Market")
    # What it has already stays.
    ledger.instrument(s, "VTI", "Another name", "etf", None)
    assert vti.name == "Vanguard Total Stock Market"


def test_a_position_of_a_security_the_file_doesnt_describe_is_a_warning(book):
    """S1.3.3.8.2: the position is left out, and the import says why."""
    got = _import(book, positions=[Position("912828XX", DAY, D(10))])
    assert got.warnings == ["a position names a security the file doesn't describe"]


def test_a_balance_the_file_gives_no_day_is_left_out(book):
    """S1.11.2: a balance is an anchor only on the day it is for."""
    s, uid, a = book
    parsed = ParsedFile("ofx", balances=[(None, D(5)), (DAY, D(7))])
    ledger.apply_import(s, a, uid, parsed, "f.ofx", "h")
    from moolakata.store.entities.accounts import Anchor

    anchors = s.query(Anchor).filter_by(accountId=a.id).all()
    assert [(x.date, x.balance) for x in anchors] == [(DAY, D(7))]


def test_an_options_end_the_file_doesnt_describe_is_a_warning_and_its_trade_kept(book):
    """S3.4: an expiry naming no security can't be settled: a warning says to settle it on
    Positions. An assignment's stock trade, when the file has it, is kept as a trade."""
    got = _import(book, Row(DAY, "expire", D(0), fitId="E1", quantity=D(1)))
    assert got.warnings == [
        "An option expired on Oct 1, 2026 wasn't recorded: The file doesn't describe the "
        "option. Settle it on Positions."
    ]
    assert got.added == 0
    buy = Row(DAY, "buy", D(-25000), fitId="B1", security="AAPL", quantity=D(100),
              price=D(250))  # fmt: skip
    got = _import(book, buy, Row(DAY, "assign", D(0), fitId="A1", quantity=D(1), relFitId="B1"),
                  securities=[_stock()], name="g.ofx")  # fmt: skip
    assert got.warnings[0].startswith("An option assigned on Oct 1, 2026 wasn't recorded")
    s, _, a = book
    kept = s.query(Transaction).filter_by(accountId=a.id, fitId="B1").one()
    assert (kept.kind, kept.amount) == ("buy", D(-25000))
    # Two ends naming one stock trade: it goes with the first alone.
    buy2 = Row(DAY, "buy", D(-25000), fitId="B2", security="AAPL", quantity=D(100),
               price=D(250))  # fmt: skip
    ends = [Row(DAY, "exercise", D(0), fitId=f"X{i}", quantity=D(1), relFitId="B2")
            for i in (1, 2)]  # fmt: skip
    got = _import(book, buy2, *ends, securities=[_stock()], name="h.ofx")
    assert len(got.warnings) == 2
    assert s.query(Transaction).filter_by(accountId=a.id, fitId="B2").count() == 1


def test_an_assignment_whose_stock_trade_came_before_is_left_to_settle_by_hand(book):
    """S3.4: settling would make the stock trade a second time, so the import says to delete
    it and settle the option on Positions."""
    buy = Row(DAY, "buy", D(-25000), fitId="B1", security="AAPL", quantity=D(100),
              price=D(250))  # fmt: skip
    opened = Row(DAY - dt.timedelta(days=30), "sell", D(300), fitId="O1", security=CALL,
                 quantity=D(-1), price=D(3))  # fmt: skip
    _import(book, opened, buy, securities=[_stock(), _option()])
    assign = Row(DAY, "assign", D(0), fitId="A1", security=CALL, quantity=D(1), relFitId="B1")
    got = _import(book, buy, assign, securities=[_stock(), _option()], name="g.ofx")
    assert got.warnings == [
        "AAPL 18 Dec 26 250 C on Oct 1, 2026: its stock trade was imported before. Delete that "
        "trade, then settle the option on Positions."
    ]


def test_an_option_the_file_names_without_an_occ_ticker_is_kept_by_its_name(book):
    """S3.2: no OCC ticker anywhere in the file's names: no contract is made of it."""
    s, _, _ = book
    row = Row(DAY, "buy", D(-100), fitId="X1", security="WEIRD", quantity=D(1), price=D(1))
    _import(book, row, securities=[Security("WEIRD", "WEIRD", "Odd", "option")])
    inst = s.query(Instrument).filter_by(symbol="WEIRD").one()
    assert contract_of(s, inst.id) is None


def test_an_adjusted_root_is_linked_to_its_contract_or_named_against_the_one_held(book):
    """S3.10.3: a root ending in a digit is an adjusted contract: linked to the one here
    already, else, while the account holds the contract it adjusts, named in a warning; a
    stock held, or a contract of another expiry, right or root, is not it."""
    s, _, _ = book
    held = [
        Row(DAY, "buy", D(-25000), fitId="S1", security="AAPL", quantity=D(100), price=D(250)),
        Row(DAY, "buy", D(-300), fitId="C1", security=CALL, quantity=D(1), price=D(3)),
        Row(DAY, "buy", D(-300), fitId="P1", security="AAPL261218P00250000", quantity=D(1),
            price=D(3)),
        Row(DAY, "buy", D(-300), fitId="C2", security="AAPL270115C00250000", quantity=D(1),
            price=D(3)),
    ]  # fmt: skip
    _import(book, *held, securities=[_stock(), _option(), _option("AAPL261218P00250000"),
                                    _option("AAPL270115C00250000")])  # fmt: skip
    # Another company's adjusted root matches nothing held.
    assert _import(book, securities=[_option("TSLA1261218C00250000")], name="f2.ofx").warnings == []
    adjusted = "AAPL1261218C00250000"
    got = _import(book, securities=[_option(adjusted)], name="g.ofx")
    assert got.warnings == [
        "AAPL1 18 Dec 26 250 C looks like an adjustment of AAPL 18 Dec 26 250 C: adjust it on "
        "Positions › Strategies, from the OCC's memo, so its lots carry over"
    ]
    # Once the adjusted contract is here, the file's names it.
    inst, _ = contract(s, "AAPL1", "call", D(250), dt.date(2026, 12, 18))
    root, *_ = adjust.parse_occ(adjusted)
    assert root == "AAPL1"
    row = Row(DAY, "sell", D(10), fitId="Z1", security=adjusted, quantity=D(-1), price=D("0.1"))
    got = _import(book, row, securities=[_option(adjusted)], name="h.ofx")
    sold = s.query(Transaction).filter_by(fitId="Z1").one()
    assert sold.instrumentId == inst.id and got.warnings == []


def test_lots_carried_in_from_an_account_deleted_since_are_not_read(book):
    """S1.7: a transfer in is paired with its transfer out of another account; once that
    account is deleted, its lots aren't replayed for it."""
    s, uid, a = book
    other = Account(id=ids.new_id("Acct"), ownerId=uid, name="Old", type="brokerage")
    s.add(other)
    s.flush()
    stock = ledger.instrument(s, "AAPL", None, "equity")
    bought = Transaction(id=ids.new_id("Txn"), accountId=other.id, date=DAY - dt.timedelta(days=9),
                         kind="buy", amount=D(-1000), instrumentId=stock.id, quantity=D(10),
                         price=D(100))  # fmt: skip
    s.add(bought)
    out = Transaction(id=ids.new_id("Txn"), accountId=other.id, date=DAY, kind="transfer-out",
                      amount=D(0), instrumentId=stock.id, quantity=D(-10))  # fmt: skip
    into = Transaction(id=ids.new_id("Txn"), accountId=a.id, date=DAY, kind="transfer-in",
                       amount=D(0), instrumentId=stock.id, quantity=D(10))  # fmt: skip
    s.add_all([out, into])
    s.flush()
    out.transferId, into.transferId = into.id, out.id
    # A pair of two instruments carries nothing.
    other_stock = ledger.instrument(s, "MSFT", None, "equity")
    out2 = Transaction(id=ids.new_id("Txn"), accountId=other.id, date=DAY, kind="transfer-out",
                       amount=D(0), instrumentId=other_stock.id, quantity=D(-1))  # fmt: skip
    into2 = Transaction(id=ids.new_id("Txn"), accountId=a.id, date=DAY, kind="transfer-in",
                        amount=D(0), instrumentId=stock.id, quantity=D(1))  # fmt: skip
    s.add_all([out2, into2])
    s.flush()
    out2.transferId, into2.transferId = into2.id, out2.id
    s.flush()
    assert list(ledger.load(s, a).carried_in) == [into.id]
    other.mark_deleted(None)
    s.flush()
    assert ledger.load(s, a).carried_in == {}
