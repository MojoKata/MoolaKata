"""The connector corpus (requirements S17.5.7, S18.9): what a driver fetches, shaped as its
institution's API or server answers it, turned into the file the driver posts, imported as the
connector's post is, and the account compared with what the entry's `.toml` says, written by
reading the data, never from what the code does now.

- `fixtures/connector/schwab/`: Schwab Trader API data, one account each: its positions and
  balances and its transactions (`.json`), run through the Schwab driver's `statement`.
- `fixtures/connector/ofx/`: an OFX server's answers (`.ofx`), run through OFX Direct Connect
  against a server that answers with them.

Every entry keeps one invariant besides what it says: what the institution reported, its cash
and its positions, is what MoolaKata works out from the transactions, unless the entry names
transactions the driver had to leave out. The real data of a household's own accounts joins the
corpus as it comes (L-items in later work)."""

import datetime as dt
import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import corpus
import pytest
from conftest import make_user, sign_in

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "connector"))

from moolakata_connector import client
from moolakata_connector.drivers import Account as SyncAccount
from moolakata_connector.drivers.ofx_direct import OfxDirect
from moolakata_connector.drivers.schwab import statement

HERE = Path(__file__).parent / "fixtures" / "connector"
SECTIONS = (
    "transactions",
    "holdings",
    "cash",
    "checks",
    "holding_checks",
    "instruments",
    "open",
    "closed",
    "strategies",
)


@dataclass
class Entry(corpus.Entry):
    """A corpus entry whose file is the driver's: `left` names what it couldn't write whole;
    `driver` what the run said (OFX Direct Connect's); `settings` its Connection's."""

    left: list = field(default_factory=list)
    driver: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    source: str = "schwab"
    made: bytes | None = None
    said: list | None = None

    def data(self) -> bytes:
        if self.made is None:
            self.made, self.said = run(self)
        return self.made


def run(e: Entry) -> tuple[bytes, list[str]]:
    """The file the driver posts, and what it says it left out."""
    if e.source == "schwab":
        raw = json.loads(e.path.read_text())
        as_of = dt.datetime.fromisoformat(raw["asOf"])
        return statement(raw["account"]["securitiesAccount"], raw["transactions"], as_of)
    answer = e.path.read_bytes()

    class Server(client.Transport):
        def __init__(self):
            super().__init__(client.Egress())

        def request(self, method, url, headers, body, pins=None):
            return client.Answer(200, {}, answer)

    accounts = [SyncAccount("Acct_1", f"Account ••{e.settings['accountId'][-4:]}", ["ofx"])]
    r = OfxDirect().run(e.settings, {"username": "u", "password": "p"}, accounts, Server())
    e.driver_result = r
    return (r.files[0].data if r.files else b""), []


def entries() -> list[Entry]:
    out = []
    for source, suffix in (("schwab", ".json"), ("ofx", ".ofx")):
        for path in sorted((HERE / source).glob(f"*{suffix}")):
            spec = tomllib.loads(path.with_suffix(".toml").read_text())
            name = path.name if source == "ofx" else path.stem + ".ofx"
            out.append(Entry(name=name, path=path, source=source, **spec))
    return out


ENTRIES = entries()


def marked(e: Entry, part: str):
    claim = e.xfail.get(part) or e.xfail.get("import")
    marks = [pytest.mark.xfail(strict=True, reason=claim)] if claim else []
    return pytest.param(e, part, id=f"{e.source}/{e.name}-{part}", marks=marks)


def state(c, account_id: str) -> dict[str, object]:
    """The account as the import corpus compares it, and what its lots make of it (S3): each
    open position with its side and basis (a short one's credit), each close with what it
    realized and how, and the strategies Positions proposes."""
    out = corpus.state(c, account_id)
    view = c.get("/ui/api/positions").json()
    num = corpus.num
    out["open"] = sorted(
        f"{x['symbol']} {x['side']} {num(x['quantity'])} cost {num(x['cost'], True)}"
        for x in view["open"]
        if x["accountId"] == account_id
    )
    out["closed"] = sorted(
        f"{x['closed']} {x['symbol']} {x['side']} {num(x['quantity'])} {x['how']} "
        f"realized {num(x['realized'], True)}"
        for x in view["closed"]
        if x["accountId"] == account_id
    )
    found = c.get("/ui/api/positions/strategies").json()
    out["strategies"] = sorted(
        f"{'proposed ' + x['kind'] if 'kind' in x else 'grouped'} {x['shape']}: "
        + ", ".join(sorted(leg["symbol"] for leg in x["legs"]))
        for x in found["strategies"] + found["proposals"]
        if x.get("accountId") == account_id
    )
    return out


class Bench:
    """An entry's own server: its file imported once into the first user's account."""

    def __init__(self, e: Entry, path: Path):
        self.e = e
        self.server = corpus.make_server(path)
        self.users = 0
        self.client, self.account = self.fresh()
        data = e.data()
        self.result = corpus.import_file(self.client, self.account, e, data) if data else {}
        self.state = state(self.client, self.account)

    def fresh(self):
        self.users += 1
        name = f"user{self.users}"
        make_user(self.server, name)
        c = sign_in(self.server, name)
        return c, corpus.new_account(c, self.e.account)["id"]


@pytest.fixture(scope="module")
def benches(tmp_path_factory):
    made: dict[str, Bench] = {}

    def bench(e: Entry) -> Bench:
        key = f"{e.source}-{e.name}"
        if key not in made:
            made[key] = Bench(e, tmp_path_factory.mktemp(key.replace(".", "-")))
        return made[key]

    yield bench
    for b in made.values():
        b.server.db.dispose()


@pytest.mark.parametrize(
    "e,section",
    [
        marked(e, s)
        for e in ENTRIES
        if e.expect
        for s in SECTIONS
        if s != "cash" or "cash" in e.expect
    ],
)
def test_the_driver_s_file_makes_what_the_entry_says(benches, e, section):
    empty = {"cash": None, "instruments": {}}.get(section, [])
    assert benches(e).state[section] == e.expect.get(section, empty)


@pytest.mark.parametrize("e,part", [marked(e, "left") for e in ENTRIES if e.source == "schwab"])
def test_what_the_driver_leaves_out_it_names(e, part):
    e.data()
    assert e.said == e.left


@pytest.mark.parametrize(
    "e,part", [marked(e, "reported") for e in ENTRIES if e.expect and not e.left]
)
def test_what_the_institution_reported_is_what_moolakata_works_out(benches, e, part):
    """The cash and positions the institution reported equal what the transactions make: the
    rows' amounts add up to the cash, every position checks out, and nothing is held that the
    institution didn't report (a file's cash anchors the account's, so its check alone would
    pass whatever rows were missing)."""
    from decimal import Decimal

    b = benches(e)
    state = b.state
    rows = b.client.get(
        "/ui/api/transactions", params={"account": b.account, "limit": 1000}
    ).json()["items"]
    (last,) = state["checks"][-1:]
    reported = Decimal(last.split()[1])
    assert sum((Decimal(t["amount"]) for t in rows), Decimal(0)) == reported
    off = [x for x in state["checks"] + state["holding_checks"] if " off " in f"{x} "]
    assert off == []
    held = {h.rsplit(" ", 1)[0] for h in state["holdings"]}
    checked = {c.rsplit(" ", 2)[0] for c in state["holding_checks"][1:]}
    assert held == checked, "a holding the institution didn't report, or the other way"


@pytest.mark.parametrize("e,part", [marked(e, "again") for e in ENTRIES if e.expect])
def test_the_next_days_file_adds_nothing(benches, e, part):
    """The next day's run fetches the same days again: imported again, it adds and changes
    nothing (the import is idempotent)."""
    b = benches(e)
    c, account = b.fresh()
    corpus.import_file(c, account, e, e.data())
    again = corpus.import_file(c, account, e, e.data())
    assert (again.get("added"), again.get("changed", 0)) == (0, 0), again
    assert state(c, account) == b.state


@pytest.mark.parametrize("e,part", [marked(e, "driver") for e in ENTRIES if e.driver])
def test_the_run_says_what_happened(e, part):
    e.data()
    r = e.driver_result
    assert r.state == e.driver["state"]
    assert e.driver.get("message", "") in (r.message or "")
    assert len(r.files) == e.driver.get("files", 1)
