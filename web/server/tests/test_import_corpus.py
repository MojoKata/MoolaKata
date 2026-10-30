"""The import corpus (requirements S17.5.7): every file in `fixtures/imports/` imported as the
browser's import dialog imports it, and the account compared with what the file's `.toml` says;
the invariants every import keeps, run over every file; the sequences that carry one import into
the next; and the browser offering what the server takes.

A part that waits on a review claim is an expected failure named by the claim (`[xfail]` in a
file's `.toml`, `KNOWN` here): strict, so the fix that makes it pass must take the mark away."""

import re
from dataclasses import dataclass
from pathlib import Path

import corpus
import pytest
from conftest import make_user, sign_in
from edits import remove

ENTRIES = corpus.entries()
SECTIONS = (
    "covered",
    "transactions",
    "holdings",
    "cash",
    "checks",
    "holding_checks",
    "instruments",
    "unpriced",
)
# Invariants every file waits on, by the claim that breaks them.
KNOWN = {"deleted": "CR3-13", "zones": "CR3-170"}
UI = Path(__file__).parents[2] / "ui"


def marked(e: corpus.Entry, part: str, known: dict | None = None):
    # `import` marks every part of a file that can't be imported at all.
    claim = e.xfail.get(part) or e.xfail.get("import") or (known or {}).get(part)
    marks = [pytest.mark.xfail(strict=True, reason=claim)] if claim else []
    return pytest.param(e, part, id=f"{e.name}-{part}", marks=marks)


# ---------- one server per file, its first import kept ----------


class Bench:
    """A corpus file's own server: the file imported once into the first user's account, and
    a fresh user for each variant, so no mapping, transfer or layout learned carries over."""

    def __init__(self, e: corpus.Entry, path: Path):
        self.e = e
        self.server = corpus.make_server(path)
        self.users = 0
        self.client, self.account = self.fresh()
        self.result = corpus.import_file(self.client, self.account, e)
        self.state = corpus.state(self.client, self.account)

    def fresh(self):
        self.users += 1
        name = f"user{self.users}"
        make_user(self.server, name)
        c = sign_in(self.server, name)
        return c, corpus.new_account(c, self.e.account)["id"]


@pytest.fixture(scope="module")
def benches(tmp_path_factory):
    made: dict[str, Bench] = {}

    def bench(e: corpus.Entry) -> Bench:
        if e.name not in made:
            made[e.name] = Bench(e, tmp_path_factory.mktemp(e.name.replace(".", "-")))
        return made[e.name]

    yield bench
    for b in made.values():
        b.server.db.dispose()


# ---------- what each file should make ----------


def _expected(e: corpus.Entry, section: str):
    empty = {"covered": [], "cash": None, "instruments": {}}.get(section, [])
    return e.expect.get(section, empty)


@pytest.mark.parametrize(
    "e,section",
    [marked(e, s) for e in ENTRIES for s in SECTIONS if s != "cash" or "cash" in e.expect],
)
def test_the_file_makes_what_it_says(benches, e, section):
    assert benches(e).state[section] == _expected(e, section)


@pytest.mark.parametrize("e,section", [marked(e, "result") for e in ENTRIES if e.result])
def test_the_import_says_what_it_did(benches, e, section):
    got = benches(e).result
    assert {k: got.get(k) for k in e.result} == e.result


# ---------- what every import keeps ----------


def _applies(e: corpus.Entry, invariant: str) -> bool:
    if invariant == "again":
        return True
    if invariant in ("reversed", "overlap", "deleted"):
        return e.kind in ("ofx", "csv")
    return e.kind == "ofx"  # zones


INVARIANTS = ("again", "reversed", "overlap", "deleted", "zones")


@pytest.mark.parametrize(
    "e,invariant",
    [marked(e, i, KNOWN) for e in ENTRIES for i in INVARIANTS if _applies(e, i)],
)
def test_every_import_keeps(benches, e, invariant):
    b = benches(e)
    c, account = b.fresh()
    if invariant == "again":
        # A file imported again adds and changes nothing.
        corpus.import_file(c, account, e)
        again = corpus.import_file(c, account, e)
        assert (again.get("added"), again.get("changed", 0)) == (0, 0), again
        assert corpus.state(c, account) == b.state
    elif invariant == "reversed":
        # The order of a file's rows changes nothing: the dates and balances tell it.
        corpus.import_file(c, account, e, corpus.reversed_rows(e))
        assert corpus.state(c, account) == b.state
    elif invariant == "overlap":
        # A later download that overlaps the file, imported before or after it, adds nothing.
        later = corpus.without_earliest(e)
        if later is None:
            pytest.skip("too few rows to overlap")
        corpus.import_file(c, account, e, later)
        corpus.import_file(c, account, e)
        assert corpus.state(c, account) == b.state
        c2, account2 = b.fresh()
        corpus.import_file(c2, account2, e)
        corpus.import_file(c2, account2, e, later)
        assert corpus.state(c2, account2) == b.state
    elif invariant == "deleted":
        # A row the owner deleted stays deleted when a file that carries it comes again.
        corpus.import_file(c, account, e)
        rows = c.get("/ui/api/transactions", params={"account": account, "sort": "date"})
        assert remove(c, "Txn", rows.json()["items"][0], confirm=True).status_code == 200
        after = corpus.state(c, account)
        corpus.import_file(c, account, e)
        assert corpus.state(c, account) == after
    elif invariant == "zones":
        # Times of day and zones move no calendar day (S14.9.3).
        corpus.import_file(c, account, e, corpus.evening_times(e))
        assert corpus.state(c, account) == b.state


# ---------- sequences: what one import leaves for the next ----------


@dataclass
class Seq:
    name: str
    claim: str | None
    steps: list[tuple]


STEPS = corpus.HERE / "steps"
BROKERAGE = {"type": "brokerage", "institution": "Charles Schwab"}
SOL_SHARES = {b"922908769": b"83415U306", b"<TICKER>VTI": b"<TICKER>SOL"}
SPOTIFY = b"10/01/2026,10/02/2026,SPOTIFY USA,Entertainment,Sale,-11.99,\r\n"
COIN_TRADES = {"action": "Transaction Type", "symbol": "Asset", "quantity": "Quantity Transacted"}

SEQUENCES = [
    Seq(
        "a CSV's mapping is asked once: the next export adds only its new rows",
        None,
        [
            ("account", "card", {"type": "credit-card", "institution": "Chase"}),
            ("import", "card", "chase-card.csv"),
            ("import", "card", "chase-card.csv", {b"Memo\r\n": b"Memo\r\n" + SPOTIFY}),
            ("result", "added", 1),
            ("count", "card", "transactions", 7),
        ],
    ),
    Seq(
        "a statement read beside the account's files teaches no skip (S1.3.3.4)",
        "CR3-16",
        [
            ("account", "brk", {**BROKERAGE, "keptBy": ["file"]}),
            ("import", "brk", "schwab-brokerage.ofx"),
            ("import", "brk", "steps/schwab-brokerage-sep.statement.txt"),
            (
                "account",
                "ira",
                {"type": "ira", "institution": "Charles Schwab", "keptBy": ["statement"]},
            ),
            ("import", "ira", "steps/schwab-ira-sep.statement.txt"),
            ("count", "ira", "transactions", 2),
        ],
    ),
    Seq(
        "positions are holdings snapshots only for an account kept by snapshots (S1.3.2)",
        "CR3-345",
        [
            ("account", "brk", BROKERAGE),
            ("import", "brk", "schwab-brokerage.ofx"),
            ("holding_rows", "brk", 0),
        ],
    ),
    Seq(
        "a coin and a listed share with the same ticker stay two instruments (S2.1)",
        "CR3-174",
        [
            ("account", "ex", {"type": "crypto-exchange", "institution": "Coinbase"}),
            ("import", "ex", "coinbase-history.csv", COIN_TRADES),
            ("account", "brk", BROKERAGE),
            ("import", "brk", "schwab-brokerage.ofx", SOL_SHARES),
            ("expect", "ex", "instruments", {"BTC": "crypto", "SOL": "crypto"}),
            ("expect", "brk", "instruments", {"SCHD": "equity", "SOL": "equity"}),
        ],
    ),
]


def _step_file(name: str, changes: dict | None = None) -> tuple[corpus.Entry, bytes]:
    """A step's file, with its bytes changed (`{old: new}`) or its mapping changed."""
    path = corpus.HERE / name
    if path.parent == corpus.HERE:
        e = corpus.entry(name)
    else:
        e = corpus.Entry(name=path.name, path=path, about="", account={})
    data = e.data()
    if changes and all(isinstance(k, bytes) for k in changes):
        for old, new in changes.items():
            data = data.replace(old, new)
    elif changes:
        e = corpus.Entry(**{**e.__dict__, "mapping": changes})
    return e, data


@pytest.mark.parametrize(
    "seq",
    [
        pytest.param(
            s,
            id=re.sub(r"\W+", "-", s.name)[:60].strip("-"),
            marks=[pytest.mark.xfail(strict=True, reason=s.claim)] if s.claim else [],
        )
        for s in SEQUENCES
    ],
)
def test_sequences(server, seq):
    make_user(server, "alice")
    c = sign_in(server, "alice")
    accounts: dict[str, str] = {}
    last: dict = {}
    for step in seq.steps:
        what, *args = step
        if what == "account":
            accounts[args[0]] = corpus.new_account(c, {"name": args[0], **args[1]})["id"]
        elif what == "import":
            e, data = _step_file(*args[1:])
            last = corpus.import_file(c, accounts[args[0]], e, data)
        elif what == "result":
            assert last.get(args[0]) == args[1], last
        elif what == "count":
            assert len(corpus.state(c, accounts[args[0]])[args[1]]) == args[2]
        elif what == "expect":
            assert corpus.state(c, accounts[args[0]])[args[1]] == args[2]
        elif what == "holding_rows":
            assert corpus.holding_rows(server, accounts[args[0]]) == args[1]


# ---------- the browser offers what the server takes ----------


def _js_keys(path: Path, name: str) -> set[str]:
    """The first strings of a `[['key', 'label', ...], ...]` list the browser defines."""
    text = path.read_text()
    body = re.search(rf"const {name} = .*?\(\[(.*?)\]\);", text, re.S).group(1)
    return set(re.findall(r"\[\s*'([^']+)'", body))


@pytest.mark.xfail(strict=True, reason="CR3-18")
def test_the_browser_offers_every_way_an_account_is_kept():
    from moolakata.ui import accounts

    # A wallet's account is kept by its wallet (S1.6), made with it, never chosen.
    offered = _js_keys(UI / "screens" / "new-account.js", "KEPT_BY") | {"bitcoin"}
    assert offered == set(accounts.KEPT_BY)


@pytest.mark.xfail(strict=True, reason="CR3-19")
def test_the_mapping_step_offers_every_column_the_reader_takes():
    from moolakata.importers import csvfile

    assert _js_keys(UI / "screens" / "import.js", "COLUMNS") == set(csvfile.FIELDS)
