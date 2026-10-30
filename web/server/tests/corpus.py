"""The import corpus (requirements S17.5.7): files shaped as institutions export them, each with
its expected results beside it, imported through the API as the browser's import dialog does,
and the account read back as plain text lines a test compares.

An entry is a file in `fixtures/imports/` and a `.toml` of the same name. A statement is kept as
its text (`.statement.txt`) and drawn into a one-page PDF with a text layer; a real PDF dropped
in is sent as it is. The `.toml` says what the file is like, the account it goes into, and what
MoolaKata should make of it, written by reading the file, never from what the code does now.
"""

import re
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).parent / "fixtures" / "imports"
SUFFIXES = (".ofx", ".qfx", ".csv", ".statement.txt", ".pdf")


@dataclass
class Entry:
    name: str  # the file's name, the entry's id in test names
    path: Path
    about: str
    account: dict
    mapping: str | dict = "proposed"
    result: dict = field(default_factory=dict)
    expect: dict = field(default_factory=dict)
    xfail: dict = field(default_factory=dict)  # a section or an invariant: the claim it waits on

    @property
    def kind(self) -> str:
        if self.name.endswith((".ofx", ".qfx")):
            return "ofx"
        if self.name.endswith(".csv"):
            return "csv"
        return "statement"

    def data(self) -> bytes:
        if self.name.endswith(".statement.txt"):
            from test_reading import text_pdf

            return text_pdf(self.path.read_text().splitlines())
        return self.path.read_bytes()

    def upload_name(self) -> str:
        return self.name.removesuffix(".statement.txt") + (
            ".pdf" if self.name.endswith(".txt") else ""
        )


def entries() -> list[Entry]:
    out = []
    for path in sorted(HERE.iterdir()):
        if not path.name.endswith(SUFFIXES):
            continue
        stem = path.name
        for suffix in SUFFIXES:
            stem = stem.removesuffix(suffix)
        spec = tomllib.loads((HERE / f"{stem}.toml").read_text())
        out.append(Entry(name=path.name, path=path, **spec))
    return out


def entry(name: str) -> Entry:
    return next(e for e in entries() if e.name == name)


# ---------- importing, as the import dialog does ----------


def new_account(c, spec: dict) -> dict:
    from test_accounts import new_account as make

    body = {"name": spec.get("name", spec["type"].title()), "mask": spec.get("mask", "0001")}
    return make(c, **body, **{k: v for k, v in spec.items() if k not in ("name", "mask")})


def import_file(c, account_id: str, e: Entry, data: bytes | None = None, ticks=None) -> dict:
    """The file imported into the account, every question answered as the dialog's defaults
    answer it: a CSV's proposed mapping (with the entry's changes, made as the person would
    in the mapping step), a statement's lines ticked as the review ticks them. `ticks` changes a
    statement's ticks: a function of a review row giving True or False. Returns the result."""
    from test_accounts import upload, wait_job

    data = e.data() if data is None else data
    job = upload(c, account_id, e.upload_name(), data)
    assert job["state"] == "done", job
    res = job["result"]
    if res.get("needsMapping"):
        mapping = dict(res["mapping"])
        if isinstance(e.mapping, dict):
            mapping.update(e.mapping)
        r = c.post(f"/ui/api/imports/{res['uploadId']}/mapping", json={"mapping": mapping})
        assert r.status_code == 202, r.text
        job = wait_job(c, r.json())
        assert job["state"] == "done", job
        return job["result"]
    if res.get("kind") == "brokerage":
        return _brokerage(c, res, ticks)
    if res.get("needsReview"):
        return _statement(c, res, ticks)
    return res


def _brokerage(c, review: dict, ticks) -> dict:
    body = {
        "periodStart": review["periodStart"],
        "periodEnd": review["periodEnd"],
        "endingValue": review["summary"]["ending"],
        "positions": [
            {
                k: p.get(k)
                for k in (
                    "label",
                    "symbol",
                    "instrumentId",
                    "quantity",
                    "price",
                    "cash",
                    "marketValue",
                    "costBasis",
                )
            }
            for p in review["positions"]
        ],
        "rows": [
            {
                "date": x["date"],
                "description": x["description"],
                "amount": x["amount"],
                "kind": x["kind"],
                "symbol": x["symbol"],
                "include": ticks(x)
                if ticks
                else not x["present"] and not x["notRead"] and not review.get("byFile"),
            }
            for x in review["activity"]
        ],
    }
    r = c.post(f"/ui/api/imports/{review['uploadId']}/brokerage", json=body)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _statement(c, review: dict, ticks) -> dict:
    body = {
        "periodStart": review["periodStart"],
        "periodEnd": review["periodEnd"],
        "opening": review["opening"],
        "closing": review["closing"],
        "rows": [
            {
                "date": x["date"],
                "description": x["description"],
                "amount": x["amount"],
                "line": i,
                "include": ticks(x) if ticks else not x["present"],
            }
            for i, x in enumerate(review["rows"])
        ],
    }
    r = c.post(f"/ui/api/imports/{review['uploadId']}/statement", json=body)
    assert r.status_code == 200, r.text
    return r.json()["result"]


# ---------- the account, read back ----------


def num(v, money: bool = False) -> str:
    """A number as the corpus writes it: plain digits, money to the cent or past it."""
    if v is None:
        return "-"
    d = Decimal(str(v))
    if money and d == d.quantize(Decimal("0.01")):
        return format(d.quantize(Decimal("0.01")), "f")
    return format(d.normalize(), "f")


def state(c, account_id: str) -> dict[str, object]:
    """The account as the corpus compares it, by section."""
    txns = c.get(
        "/ui/api/transactions", params={"account": account_id, "limit": 1000, "sort": "date"}
    ).json()["items"]
    lines = []
    for t in txns:
        text = f"{t['date']} {t['kind']} {num(t['amount'], True)}"
        # A trade is told by its instrument and quantity, a bank row by the payee as written.
        if t["symbol"]:
            text += f" {t['symbol']}"
            if t["quantity"]:
                text += f" {num(t['quantity'])}"
        elif t["payeeRaw"] or t["payee"]:
            text += f" | {t['payeeRaw'] or t['payee']}"
        lines.append(text)
    h = c.get(f"/ui/api/accounts/{account_id}/holdings").json()
    rec = c.get(f"/ui/api/accounts/{account_id}/reconcile").json()
    imports = c.get(f"/ui/api/accounts/{account_id}/imports").json()["items"]
    starts = [x["coveredFrom"] for x in imports if x["coveredFrom"]]
    ends = [x["coveredTo"] for x in imports if x["coveredTo"]]
    # By the instrument the account holds: a coin and a listed share may share a symbol.
    ids = {t["symbol"]: t["instrumentId"] for t in txns if t["symbol"]} | {
        x["symbol"]: x["instrumentId"] for x in h["holdings"]
    }
    symbols = set(ids)
    classes = {}
    for sym, iid in ids.items():
        found = c.get("/ui/api/instruments", params={"q": sym[:40]}).json()["items"]
        classes[sym] = next((i["instrumentClass"] for i in found if i["id"] == iid), "?")
    return {
        "covered": [min(starts), max(ends)] if starts else [],
        "transactions": sorted(lines),
        "holdings": sorted(
            f"{x['symbol']} {num(x['quantity'])}" for x in h["holdings"] if Decimal(x["quantity"])
        ),
        "cash": num(h["cash"], True),
        "checks": [
            f"{k['date']} {num(k['reported'], True)} "
            + ("ok" if k["ok"] else f"off {num(k['difference'], True)}")
            for k in rec["checks"]
            if k["source"] != "opening"
        ],
        "holding_checks": ([f"as of {rec['holdingChecksAsOf']}"] if rec["holdingChecks"] else [])
        + sorted(
            f"{x['symbol'] or x['label']} {num(x['statement'])} "
            + ("ok" if x["ok"] else f"off {num(x['difference'])}")
            for x in rec["holdingChecks"]
        ),
        "instruments": {s: classes.get(s, "?") for s in sorted(symbols)},
        "unpriced": sorted(s for s in symbols if not fetched(classes.get(s, "?"))),
    }


def fetched(cls: str) -> bool:
    """Whether a price source that fetches serves the class (S4.3): the stub dev mode runs on
    serves every class, so a class no real source fetches would look priced there."""
    from moolakata.prices.base import SOURCES

    return any(cls in src.classes and src.fetches and not src.dev_only for src in SOURCES.values())


def holding_rows(server, account_id: str) -> int:
    """The holdings snapshots kept for the account (S1.3.2), live ones."""
    from sqlalchemy import false, func, select

    from moolakata.store.entities.accounts import Holding

    with server.db.read() as s:
        return s.scalar(
            select(func.count())
            .select_from(Holding)
            .where(Holding.accountId == account_id, Holding.deleted == false())
        )


# ---------- variants of a file, for the invariants ----------

OFX_ROWS = re.compile(
    rb"<(STMTTRN|INVBANKTRAN|BUYSTOCK|SELLSTOCK|BUYMF|SELLMF|BUYOTHER|SELLOTHER|BUYDEBT|"
    rb"SELLDEBT|INCOME|REINVEST|INVEXPENSE|RETOFCAP|SPLIT|TRANSFER|BUYOPT|SELLOPT|CLOSUREOPT)>"
    rb".*?</\1>",
    re.S,
)
OFX_DATE = re.compile(rb"<(DT[A-Z]+)>(\d{8})[0-9.]*(\[[^\]]*\])?")


def _row_date(chunk: bytes) -> bytes:
    m = re.search(rb"<DT(?:POSTED|TRADE)>(\d{8})", chunk)
    return m.group(1) if m else b""


def _rewrite_rows(data: bytes, rows: list[re.Match], chunks: list[bytes]) -> bytes:
    """The file with its rows' places filled by `chunks`, the rest dropped."""
    out, at = b"", 0
    for i, m in enumerate(rows):
        out += data[at : m.start()] + (chunks[i] if i < len(chunks) else b"")
        at = m.end()
    return out + data[at:]


def csv_split(data: bytes) -> tuple[list[bytes], list[bytes], list[bytes]]:
    """A CSV's lines down to its header, its rows, and the notes some exports add after them."""
    lines = data.splitlines(keepends=True)
    at = header_line(data)
    rest = lines[at + 1 :]
    last = max((i for i, x in enumerate(rest) if CSV_ROW.match(x)), default=-1)
    return lines[: at + 1], [x for x in rest[: last + 1] if x.strip()], rest[last + 1 :]


CSV_ROW = re.compile(rb'\s*"?\d')


def reversed_rows(e: Entry) -> bytes | None:
    """The same rows in the opposite order."""
    data = e.data()
    if e.kind == "ofx":
        rows = list(OFX_ROWS.finditer(data))
        return _rewrite_rows(data, rows, [m.group(0) for m in reversed(rows)])
    if e.kind == "csv":
        head, rows, tail = csv_split(data)
        return b"".join(head + rows[::-1] + tail)
    return None


def without_earliest(e: Entry) -> bytes | None:
    """The file less its earliest third of rows by date: a later download that overlaps it,
    with the same end, balance and positions."""
    data = e.data()
    if e.kind == "ofx":
        rows = list(OFX_ROWS.finditer(data))
        if len(rows) < 3:
            return None
        cut = sorted(_row_date(m.group(0)) for m in rows)[len(rows) // 3]
        keep = [m.group(0) for m in rows if _row_date(m.group(0)) >= cut]
        return _rewrite_rows(data, rows, keep)
    if e.kind == "csv":
        head, rows, tail = csv_split(data)
        if len(rows) < 3:
            return None
        newest_first = csv_date(rows[0]) > csv_date(rows[-1])
        n = len(rows) // 3
        keep = rows[:-n] if newest_first else rows[n:]
        return b"".join(head + keep + tail)
    return None


def header_line(data: bytes) -> int:
    """The line the CSV reader takes for the header (banks put account details above it)."""
    import csv

    from moolakata.importers import csvfile

    _, rows = csvfile._table(csvfile.decode(data))
    want = [x.strip() for x in rows[csvfile.header_row(rows)]]
    for i, line in enumerate(csvfile.decode(data).splitlines()):
        if [x.strip() for x in next(csv.reader([line]), [])] == want:
            return i
    return 0


def csv_date(line: bytes) -> tuple:
    """A CSV row's first date, as (year, month, day), to tell which way the file runs."""
    m = re.search(rb"(\d{1,4})[/-](\d{1,2})[/-](\d{2,4})", line)
    if not m:
        return ()
    a, b, y = (int(x) for x in m.groups())
    return (a, b, y) if a > 31 else (y, a, b)


def evening_times(e: Entry) -> bytes | None:
    """Every date-time of an OFX file written as 8 PM US Eastern on its day, as many banks
    write them: no calendar day may move (S14.9.3)."""
    if e.kind != "ofx":
        return None
    return OFX_DATE.sub(lambda m: b"<%s>%s200000.000[-5:EST]" % (m.group(1), m.group(2)), e.data())


# ---------- a server of its own ----------


def make_server(path: Path):
    """A server with the first admin, in `path`, for one corpus entry: instruments are kept once
    per server (S2.1), so entries never share one."""
    import os

    from conftest import ADMIN_PW

    from moolakata.app import Server
    from moolakata.auth import users as accounts
    from moolakata.config import Config
    from moolakata.keys import cli as keys_cli
    from moolakata.store.maintenance import open_store
    from moolakata.store.repos.ledger import ensure_categories

    config = Config(
        name="test",
        mode="proxy",
        data_dir=path / "data",
        backup_dir=path / "backups",
        socket_path=path / "run" / "sock",
    )
    key = os.urandom(16)
    keys_cli.init(config, say=lambda _: None, confirm=False, master_key=key)
    srv = Server(config=config, store=open_store(config, key), ready=True)
    with srv.db.tx() as s:
        accounts.make_first_admin(s, "Ada Admin", "male", "admin@home.lan", ADMIN_PW)
        ensure_categories(s)
    return srv
