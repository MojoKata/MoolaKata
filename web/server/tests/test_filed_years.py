"""A filed year's gains move only when asked and recorded (requirements S2.8, S8.15): every way
of writing that can move realized gains, against every state a tax book's federal return can
be in, through the API (the filed tax years walk, decision 1, and its tests, decision 1.7).

Each case makes a small household (Alice and Bob, married since 2009, a 2025 book they file
jointly) whose 2025 sales gain $250 in all, puts the book's federal return in a state, and
writes one way. The invariant:

- a year **closed** (a return filed or accepted, an amended one filed, or the changes waived
  with *No amendment needed*): a write a person makes is refused, the year's gains as they
  were, until confirmed (`closed-year`); confirmed, or made by no one who can be asked (a file
  imported in the background), the book lists by how much the gains moved since filing,
  exactly the move;
- a year **open** (no return filed, or an amended one being prepared): nothing is asked and
  nothing is listed.

Left out, with where they are covered: *both real* and a matched transfer carrying basis (to
come with the commit-time check's own tests), a Connection's posted file (the same import
path as a file uploaded, `test_connections`).
"""

import datetime as dt
import re
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, create, make, remove, saved
from test_accounts import upload

from moolakata import clock

T0 = dt.datetime(2026, 6, 15, 15, 0, tzinfo=dt.UTC)

STATES = ("none", "filed", "accepted", "amending", "amended", "waived")
CLOSED = {"filed", "accepted", "amended", "waived"}


def _ok(r):
    assert r.status_code == 200, r.text
    return r


class World:
    """Alice and Bob, married; Alice's Brokerage, Second and IRA, Bob's brokerage; a 2025 book
    they file jointly."""

    def __init__(self, server):
        clock.fix(T0)
        make_user(server, "alice")
        make_user(server, "bob")
        self.server = server
        self.a, self.b = sign_in(server, "alice"), sign_in(server, "bob")
        uid = {n: c.get("/ui/api/session").json()["user"]["id"] for n, c in (("a", self.a),
               ("b", self.b))}  # fmt: skip
        pa = self.a.get("/ui/api/profile").json()["personId"]
        pb = self.b.get("/ui/api/profile").json()["personId"]
        r = _ok(make(self.a, "Rltn", person1Id=pa, person2Id=pb, relation="spouse",
                     fromDate="2009-06-14"))  # fmt: skip
        _ok(self.b.post(f"/ui/api/relationships/{r.json()['id']}/confirm"))
        self.acct = {}
        accounts = (("a", "Brokerage", "brokerage"), ("a", "Second", "brokerage"),
                    ("a", "IRA", "ira"), ("b", "Bob's brokerage", "brokerage"))  # fmt: skip
        for who, name, kind in accounts:
            c = self.a if who == "a" else self.b
            self.acct[name] = _ok(make(c, "Acct", name=name, type=kind, institution="Example",
                                       mask=str(1000 + len(self.acct)))).json()  # fmt: skip
        self.sale = {}
        # A $200 loss in December, $250 and $200 gains: $250 for 2025.
        self.trade("Brokerage", "2024-01-08", "buy", "AAPL", 10, "100")
        self.sale["AAPL"] = self.trade("Brokerage", "2025-12-15", "sell", "AAPL", 10, "80")
        self.trade("Brokerage", "2024-02-05", "buy", "MSFT", 10, "100")
        self.trade("Brokerage", "2024-08-05", "buy", "MSFT", 10, "120")
        self.sale["MSFT"] = self.trade("Brokerage", "2025-06-02", "sell", "MSFT", 5, "150")
        self.trade("Second", "2024-03-04", "buy", "IBM", 10, "50")
        self.sale["IBM"] = self.trade("Second", "2025-09-02", "sell", "IBM", 10, "70")
        self.book = _ok(make(self.a, "TaxBk", year=2025, filers=[uid["a"], uid["b"]])).json()
        _ok(self.b.post(f"/ui/api/tax-books/{self.book['id']}/accept"))

    def trade(self, account, day, kind, symbol, qty, price, c=None):
        cents = qty * int(Decimal(price) * 100)
        amount = f"{'-' if kind == 'buy' else ''}{cents // 100}.{cents % 100:02d}"
        c = c or (self.b if account == "Bob's brokerage" else self.a)
        r = make(c, "Txn", accountId=self.acct[account]["id"], date=day, kind=kind,
                 symbol=symbol, quantity=str(qty), price=price, amount=amount)  # fmt: skip
        return _ok(r).json()

    def filing(self, **fields):
        r = make(self.a, "Filng", bookId=self.book["id"], jurisdiction="federal", **fields)
        return r.parent()["filings"]

    def state(self, state: str) -> None:
        """The book's federal return put in a state."""
        if state == "none":
            return
        progress = "accepted" if state == "accepted" else "filed"
        filed = self.filing(form="1040", progress=progress, filedOn="2026-04-10")
        original = next(f for f in filed if f["form"] == "1040")
        if state in ("amending", "amended"):
            progress = "in progress" if state == "amending" else "filed"
            extra = {"filedOn": "2026-05-20"} if state == "amended" else {}
            self.filing(form="1040-X", progress=progress, amendsId=original["id"], **extra)
        if state == "waived":
            # A change made anyway and waived: the year stays closed, the next change listed
            # afresh.
            sale = self.a.get(f"/ui/api/transactions/{self.sale['IBM']['id']}").json()
            self.sale["IBM"] = saved(change(self.a, "Txn", sale, confirm=True, amount="710.00"))
            _ok(self.a.post(f"/ui/api/tax-books/{self.book['id']}/no-amendment"))

    def gains(self) -> Decimal:
        p = _ok(self.a.get(f"/ui/api/tax-books/{self.book['id']}/panels")).json()
        return sum((Decimal(str(r["gain"])) for r in p["rows"]), Decimal(0))

    def listed(self) -> Decimal | None:
        """By how much the book says the gains moved since filing, if it says so."""
        p = _ok(self.a.get(f"/ui/api/tax-books/{self.book['id']}/panels")).json()
        found = [i["text"] for i in p["issues"] if i["kind"] == "changed-after-filing"]
        if not found:
            return None
        m = re.search(r"changed by ([+−-])\$([\d,]+\.\d\d)", found[0])
        assert m, found
        amount = Decimal(m.group(2).replace(",", ""))
        return -amount if m.group(1) in "−-" else amount


def _asked(r) -> bool:
    """Refused for a closed year: the save's question, or a plain route's 409."""
    if r.status_code != 409:
        return False
    body = r.json()
    if body.get("code") == "confirm-needed":
        return any(a["code"] == "closed-year" for a in body["asks"])
    return body.get("code") == "closed-year"


# ---------- the ways of writing: each makes its change, confirmed or not ----------


def _edit(w: World, confirm: bool):
    sale = w.a.get(f"/ui/api/transactions/{w.sale['MSFT']['id']}").json()
    return change(w.a, "Txn", sale, confirm=confirm, amount="800.00")


def _delete(w: World, confirm: bool):
    sale = w.a.get(f"/ui/api/transactions/{w.sale['IBM']['id']}").json()
    return remove(w.a, "Txn", sale, confirm=confirm)


def _add(w: World, confirm: bool):
    return make(w.a, "Txn", confirm=confirm, accountId=w.acct["Brokerage"]["id"],
                date="2025-07-01", kind="sell", symbol="MSFT", quantity="5", price="160",
                amount="800.00")  # fmt: skip


def _ira_wash(w: World, confirm: bool):
    # CR3-27: a buy in the IRA within 30 days washes December's loss.
    return make(w.a, "Txn", confirm=confirm, accountId=w.acct["IRA"]["id"], date="2026-01-05",
                kind="buy", symbol="AAPL", quantity="10", price="82", amount="-820.00")  # fmt: skip


def _spouse_wash(w: World, confirm: bool):
    return make(w.b, "Txn", confirm=confirm, accountId=w.acct["Bob's brokerage"]["id"],
                date="2026-01-06", kind="buy", symbol="AAPL", quantity="10", price="82",
                amount="-820.00")  # fmt: skip


def _pick(w: World, confirm: bool):
    # Picking the $120 lot for the June sale: its basis $600, not $500.
    q = f"?date=2025-06-02&saleId={w.sale['MSFT']['id']}"
    lots = _ok(w.a.get(f"/ui/api/accounts/{w.acct['Brokerage']['id']}/lots{q}")).json()["items"]
    lot = next(x for x in lots if x["symbol"] == "MSFT" and x["acquiredOn"] == "2024-08-05")
    return create(w.a, "LotPk", confirm=confirm, saleId=w.sale["MSFT"]["id"],
                  lotId=lot["lotId"], quantity="5")  # fmt: skip


def _split(w: World, confirm: bool):
    held = {p["symbol"]: p["instrumentId"] for p in w.a.get("/ui/api/positions").json()["open"]}
    return create(w.a, "CorpA", confirm=confirm, accountId=w.acct["Brokerage"]["id"],
                  instrumentId=held["MSFT"], kind="split", date="2025-03-03",
                  ratio="2")  # fmt: skip


def _delete_account(w: World, confirm: bool):
    a = w.a.get(f"/ui/api/accounts/{w.acct['Second']['id']}").json()
    return remove(w.a, "Acct", a, confirm=confirm)


def _leave_out(w: World, confirm: bool):
    return create(w.a, "TxBkA", confirm=confirm, bookId=w.book["id"],
                  accountId=w.acct["Second"]["id"], counted=False)  # fmt: skip


OFX = (
    "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:USASCII\nCHARSET:1252\n"
    "COMPRESSION:NONE\nOLDFILEUID:NONE\nNEWFILEUID:NONE\n\n<OFX>\n<SIGNONMSGSRSV1><SONRS><STATUS>"
    "<CODE>0<SEVERITY>INFO</STATUS><DTSERVER>20260601120000<LANGUAGE>ENG<FI><ORG>Example<FID>1"
    "</FI></SONRS></SIGNONMSGSRSV1>\n<INVSTMTMSGSRSV1><INVSTMTTRNRS><TRNUID>1<STATUS><CODE>0"
    "<SEVERITY>INFO</STATUS>\n<INVSTMTRS><DTASOF>20251231<CURDEF>USD<INVACCTFROM><BROKERID>"
    "example.com<ACCTID>X1</INVACCTFROM>\n<INVTRANLIST><DTSTART>20240101<DTEND>20251231\n"
    "<BUYSTOCK><INVBUY><INVTRAN><FITID>B9<DTTRADE>20240105</INVTRAN><SECID><UNIQUEID>922908769"
    "<UNIQUEIDTYPE>CUSIP</SECID><UNITS>10<UNITPRICE>200.00<COMMISSION>0<TOTAL>-2000.00"
    "<SUBACCTSEC>CASH<SUBACCTFUND>CASH</INVBUY><BUYTYPE>BUY</BUYSTOCK>\n"
    "<SELLSTOCK><INVSELL><INVTRAN><FITID>S9<DTTRADE>20251103</INVTRAN><SECID><UNIQUEID>922908769"
    "<UNIQUEIDTYPE>CUSIP</SECID><UNITS>-10<UNITPRICE>230.00<COMMISSION>0<TOTAL>2300.00"
    "<SUBACCTSEC>CASH<SUBACCTFUND>CASH</INVSELL><SELLTYPE>SELL</SELLSTOCK>\n"
    "</INVTRANLIST>\n</INVSTMTRS></INVSTMTTRNRS></INVSTMTMSGSRSV1>\n<SECLISTMSGSRSV1><SECLIST>\n"
    "<STOCKINFO><SECINFO><SECID><UNIQUEID>922908769<UNIQUEIDTYPE>CUSIP</SECID><SECNAME>Vanguard"
    " Total Stock Market ETF<TICKER>VTI</SECINFO></STOCKINFO>\n</SECLIST></SECLISTMSGSRSV1>\n"
    "</OFX>\n"
)


def _import(w: World, confirm: bool):
    # A file read in the background: a 2025 sale missed, $300 more gain. No one is there to
    # ask: kept, and listed on the book.
    job = upload(w.a, w.acct["Second"]["id"], "missed.ofx", OFX.encode())
    assert job["state"] == "done", job

    class Done:
        status_code = 200
        text = ""

    return Done()


WAYS = {"edit": _edit, "delete": _delete, "add": _add, "ira-wash": _ira_wash,
        "spouse-wash": _spouse_wash, "pick": _pick, "split": _split,
        "delete-account": _delete_account, "leave-out": _leave_out, "import": _import}  # fmt: skip
UNASKED = {"import"}  # written by no one who can be asked

# The ways that move a closed year unasked today (CR3-27, CR3-33), each until decision 1's
# commit-time check: strict, so one that starts passing fails here until taken off.
OPEN_CLAIMS = {"ira-wash", "spouse-wash", "pick", "delete-account", "leave-out", "import"}


def _cases():
    for way in WAYS:
        for state in STATES:
            marks = []
            if way in OPEN_CLAIMS and state in CLOSED:
                marks = [pytest.mark.xfail(strict=True, reason="CR3-27, CR3-33: decision 1")]
            yield pytest.param(way, state, marks=marks, id=f"{way}-{state}")


@pytest.fixture
def world(server):
    try:
        yield World(server)
    finally:
        clock.fix(None)


@pytest.mark.parametrize(("way", "state"), list(_cases()))
def test_a_filed_years_gains_move_only_asked_and_recorded(world, way, state):
    w = world
    w.state(state)
    before, listed_before = w.gains(), w.listed()
    closed = state in CLOSED
    if closed and way not in UNASKED:
        r = WAYS[way](w, False)
        assert _asked(r), (r.status_code, r.text)
        assert w.gains() == before, "refused: the year as it was"
        assert w.listed() == listed_before
        r = WAYS[way](w, True)
    else:
        r = WAYS[way](w, False)
    assert r.status_code == 200, r.text
    after = w.gains()
    assert after != before, "each way moves 2025's gains"
    if closed:
        assert w.listed() == after - before, "the book lists exactly the move since filing"
    else:
        assert w.listed() is None, "an open year lists nothing"
