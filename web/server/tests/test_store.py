import datetime as dt
import json
import os
import re
import shutil
import sqlite3

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, ForeignKey, MetaData, Table, Text, select, text

from moolakata import ids, settings
from moolakata.config import RefuseStart
from moolakata.keys import master
from moolakata.keys import secrets as sealing
from moolakata.store import copy, maintenance, migrate, schema_check, views
from moolakata.store.db import Database, live, make_engine
from moolakata.store.entities.core import Secret
from moolakata.store.entities.users import User
from moolakata.store.repos import secrets as secret_repo
from moolakata.store.tables import metadata
from moolakata.store.tables._base import Seen, record
from moolakata.store.tables.receipts import is_search_table


def new_user(s, name="jane"):
    from moolakata import people

    u = User(
        id=ids.new_id("User"),
        personId=people.make(s, name.title(), "female").id,
        username=name,
        displayName=name.title(),
    )
    s.add(u)
    s.flush()
    return u


def test_database_is_encrypted_at_rest(store, keyed_config):
    # A plaintext long enough that the file's random bytes can't hold it by chance, as a
    # name of four letters would now and then.
    marker = "plaintextthatmustnotshowonthedisk"
    with store.db.tx(unscoped="test") as s:
        new_user(s, marker)
    raw = keyed_config.db_path.read_bytes()
    assert b"SQLite format 3" not in raw[:100]
    assert marker.encode() not in raw
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(keyed_config.db_path).execute("SELECT * FROM User").fetchall()


def test_read_refuses_writes_and_tx_commits(db):
    with db.tx(unscoped="test") as s:
        new_user(s)
    with db.read(unscoped="test") as s:
        assert s.scalars(select(User)).one().username == "jane"
        with pytest.raises(Exception, match=r"readonly|query_only|attempt to write"):
            s.execute(text("UPDATE User SET displayName = 'x'"))


def test_versions_change_with_every_save(db):
    with db.tx(unscoped="test") as s:
        u = new_user(s)
    assert u.version == 1
    with db.tx(unscoped="test") as s:
        u = s.get(User, u.id)
        u.displayName = "Jane G."
    assert u.version == 2


def test_every_table_with_an_id_has_its_version_and_times_locked_or_counted():
    """schema.md §2: each table with an `id` has `version`, `createdAt` and `updatedAt`. The
    version is the lock on a locked table and a counter on a counted one, never both, and §2
    names the counted tables as they are mapped."""
    from sqlalchemy import inspect as sa_inspect

    from moolakata.store import mapping

    mapping.map_all()
    by_table = {
        m.local_table.name: m for m in mapping.mapper_registry.mappers if "id" in m.local_table.c
    }
    with_id = {n for n, t in metadata.tables.items() if "id" in t.c}
    assert set(by_table) == with_id
    missing = {
        n: sorted({"version", "createdAt", "updatedAt"} - set(metadata.tables[n].c.keys()))
        for n in with_id
    }
    assert {n: m for n, m in missing.items() if m} == {}
    both_or_neither = [
        n
        for n, m in by_table.items()
        if (m.version_id_col is None) == (m.class_ not in mapping.COUNTED)
    ]
    assert both_or_neither == []
    counted = {sa_inspect(e).local_table.name for e in mapping.COUNTED}
    assert schema_check.counted_tables() == counted


def test_a_server_kept_record_counts_its_saves_and_a_stale_copy_never_fails(db):
    """schema.md §2: a counted record's version counts its saves in the database, so a
    write from a copy read before another one is saved, never refused for its version, and
    neither save goes uncounted."""
    from moolakata.store.entities.links import LinkSent

    with db.tx(unscoped="test") as s:
        sent = LinkSent(linkId=_a_link(s), itemId="Acct_x", path="/a", viewer="v", hash="h1")
        s.add(sent)
    assert sent.version == 1
    made = sent.createdAt
    with db.tx(unscoped="test") as s:
        s.get(LinkSent, sent.id).hash = "h2"
    with db.tx(unscoped="test") as s:
        s.add(sent)  # the copy read at version 1
        sent.hash = "h3"
    assert sent.version == 3
    with db.read(unscoped="test") as s:
        now = s.get(LinkSent, sent.id)
        assert (now.hash, now.version, now.createdAt) == ("h3", 3, made)
        assert now.updatedAt > made


def _a_lot(s):
    from moolakata.store.entities.accounts import Lot, Transaction

    acct, inst = _an_account_and_instrument(s)
    txn = Transaction(
        id=ids.new_id("Txn"), accountId=acct, date=dt.date(2026, 3, 2), kind="buy", amount=-100
    )
    s.add(txn)
    s.flush()
    lot = Lot(
        id=ids.new_id("Lot"),
        accountId=acct,
        instrumentId=inst,
        transactionId=txn.id,
        acquiredOn=dt.date(2026, 3, 2),
        quantity=10,
        costBasis=100,
    )
    return lot, "costBasis", (90, 80)


def _a_holding(s):
    from moolakata.store.entities.accounts import Holding

    acct, inst = _an_account_and_instrument(s)
    held = Holding(
        id=ids.new_id("Hold"), accountId=acct, instrumentId=inst, asOf=dt.date(2026, 3, 2),
        quantity=10,
    )  # fmt: skip
    return held, "quantity", (11, 12)


def _a_price(s):
    from moolakata.store.entities.prices import Price

    _, inst = _an_account_and_instrument(s)
    price = Price(instrumentId=inst, date=dt.date(2026, 3, 2), close=10, source="stooq")
    return price, "close", (11, 12)


def _an_account_and_instrument(s) -> tuple[str, str]:
    from moolakata.store.entities.accounts import Account, Instrument

    owner = new_user(s)
    acct = Account(id=ids.new_id("Acct"), ownerId=owner.id, name="Brokerage", type="brokerage")
    inst = Instrument(id=ids.new_id("Instr"), symbol="VTI", instrumentClass="etf")
    s.add_all([acct, inst])
    s.flush()
    return acct.id, inst.id


def _a_transaction(s):
    from moolakata.store.entities.accounts import Transaction

    acct, _ = _an_account_and_instrument(s)
    txn = Transaction(
        id=ids.new_id("Txn"), accountId=acct, date=dt.date(2026, 3, 2), kind="buy", amount=-100
    )
    return txn, "memo", ("expired", "synced")


def _an_import(s):
    from moolakata.store.entities.accounts import Account, Import

    acct, _ = _an_account_and_instrument(s)
    owner = s.get(Account, acct).ownerId
    imp = Import(
        id=ids.new_id("Imprt"), accountId=acct, userId=owner, format="ofx", fileName="a.ofx",
        fileHash="h",
    )  # fmt: skip
    return imp, "added", (3, 4)


def _an_anchor(s):
    from moolakata.store.entities.accounts import Anchor

    acct, _ = _an_account_and_instrument(s)
    anchor = Anchor(
        id=ids.new_id("Anchr"), accountId=acct, date=dt.date(2026, 3, 2), balance=100,
        source="ofx",
    )  # fmt: skip
    return anchor, "balance", (110, 120)


def _a_holding_check(s):
    from moolakata.store.entities.accounts import HoldingCheck

    acct, inst = _an_account_and_instrument(s)
    check = HoldingCheck(
        id=ids.new_id("HdChk"), accountId=acct, instrumentId=inst, asOf=dt.date(2026, 3, 2),
        label="VTI", quantity=10,
    )  # fmt: skip
    return check, "quantity", (11, 12)


def _a_transfer_match(s):
    from moolakata.store.entities.accounts import Account, Transaction, TransferMatch

    acct, _ = _an_account_and_instrument(s)
    owner = s.get(Account, acct).ownerId
    out, in_ = (
        Transaction(id=ids.new_id("Txn"), accountId=acct, date=dt.date(2026, 3, 2), kind=k,
                    amount=a)
        for k, a in (("transfer-out", -1), ("transfer-in", 1))
    )  # fmt: skip
    s.add_all([out, in_])
    s.flush()
    match = TransferMatch(id=ids.new_id("XfrMt"), ownerId=owner, outId=out.id, inId=in_.id)
    return match, "state", ("rejected", "confirmed")


def _a_price_source(s):
    from moolakata.store.entities.prices import PriceSource

    src = PriceSource(id=ids.new_id("Src"), name="counted-test", enabled=True)
    return src, "lastError", ("refused", "timed out")


def _a_link_row(s):
    from moolakata.store.entities.links import Link

    return s.get(Link, _a_link(s)), "lastError", ("unreachable", "refused")


def _a_connector(s):
    from moolakata.store.entities.connector import Connector

    return Connector(id=ids.new_id("Cnctr"), state="paired"), "connectorVersion", ("1.1", "1.2")


def _a_connection(s):
    from moolakata.store.entities.connector import Connection

    connector, _, _ = _a_connector(s)
    s.add(connector)
    s.flush()
    row = Connection(
        id=ids.new_id("Conn"), ownerId=new_user(s).id, connectorId=connector.id,
        driver="folder", label="Bank", state="ok",
    )  # fmt: skip
    return row, "state", ("failing", "needs-sign-in")


def _a_setting(s):
    from moolakata.store.entities.core import Setting

    row = Setting(id=ids.new_id("Setng"), key="bitcoinNodeCertOffered", value='"a"')
    return row, "value", ('"b"', "null")


BACKGROUND = {
    "Lot": _a_lot,
    "Holding": _a_holding,
    "Price": _a_price,
    # The connector's files (S18.8), the bitcoin sync (S1.6.2) and the hourly option expiry
    # (S3.6).
    "Transaction": _a_transaction,
    # The connector's files.
    "Import": _an_import,
    "Anchor": _an_anchor,
    "HoldingCheck": _a_holding_check,
    # The bitcoin sync's proposals (S1.6.2).
    "TransferMatch": _a_transfer_match,
    # The price refresh (S16.7).
    "PriceSource": _a_price_source,
    # The hourly exchange (S11.4).
    "Link": _a_link_row,
    # The connector's reports (S18.5).
    "Connector": _a_connector,
    "Connection": _a_connection,
    # The bitcoin sync's certificate offer (S1.6.2).
    "Setting": _a_setting,
}


@pytest.mark.parametrize("make", BACKGROUND.values(), ids=BACKGROUND.keys())
def test_a_table_written_in_the_background_counts_a_save_from_an_old_copy(db, make):
    """schema.md §2: a table the server writes in the background, outside a person's save, is
    counted. A write from a copy read before another save is never refused for its version,
    and both saves are counted."""
    from moolakata.store import mapping

    with db.tx(unscoped="test") as s:
        row, field_, (then, last) = make(s)
        s.add(row)
    with db.tx(unscoped="test") as s:
        setattr(s.get(type(row), row.id), field_, then)  # the background write
    with db.tx(unscoped="test") as s:
        s.add(row)  # the copy read at version 1
        setattr(row, field_, last)
    with db.read(unscoped="test") as s:
        now = s.get(type(row), row.id)
        assert (getattr(now, field_), now.version) == (last, 3)
    assert type(row) in mapping.COUNTED


def _persons(s, owner: str, prefix: str):
    """A record of a counted table that a person saves with a version, owned by `owner`, and
    the field a background write changes on it."""
    from moolakata.store.entities.accounts import Account, Anchor, Transaction
    from moolakata.store.entities.connector import Connection, Connector
    from moolakata.store.entities.core import Setting
    from moolakata.store.entities.prices import PriceSource

    if prefix == "Src":
        return PriceSource(id=ids.new_id("Src"), name="tiingo", enabled=True), "lastError"
    if prefix == "Setng":
        return Setting(id=ids.new_id("Setng"), key="householdName", value='"Home"'), "value"
    if prefix == "Conn":
        connector = Connector(id=ids.new_id("Cnctr"), state="paired")
        s.add(connector)
        s.flush()
        row = Connection(
            id=ids.new_id("Conn"), ownerId=owner, connectorId=connector.id, driver="folder",
            label="Bank", state="ok",
        )  # fmt: skip
        return row, "message"
    acct = Account(id=ids.new_id("Acct"), ownerId=owner, name="Checking", type="checking")
    s.add(acct)
    s.flush()
    if prefix == "Anchr":
        row = Anchor(
            id=ids.new_id("Anchr"), accountId=acct.id, date=dt.date(2026, 3, 2), balance=100,
            source="typed",
        )  # fmt: skip
        return row, "note"
    row = Transaction(
        id=ids.new_id("Txn"), accountId=acct.id, date=dt.date(2026, 3, 2), kind="withdrawal",
        amount=-100,
    )  # fmt: skip
    return row, "memo"


@pytest.mark.parametrize("prefix", ["Txn", "Anchr", "Src", "Conn", "Setng"])
def test_a_persons_stale_save_of_a_counted_table_is_still_refused(server, admin_client, prefix):
    """schema.md §2: a counted table's version locks nothing in the store, but a person's save
    names the version its draft read (S13.8.6), and one older than a background write is
    refused at the save, with the record as it is now. The other counted tables of #665
    (imports, holding checks, links, the connector) have no save of a person's that names a
    version; a transfer match's answer does (the next test)."""
    from sqlalchemy import select

    with server.db.tx(unscoped="test") as s:
        owner = s.scalars(select(User.id).where(User.username == "admin")).one()
        row, field_ = _persons(s, owner, prefix)
        s.add(row)
    with server.db.tx(unscoped="test") as s:
        setattr(s.get(type(row), row.id), field_, '"Away"')  # the background write
    op = {"op": "update", "entity": prefix, "id": row.id, "version": 1, "fields": {}}
    r = admin_client.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 412, r.text
    assert r.json()["code"] == "stale-version"
    (current,) = r.json()["current"]
    assert (current["id"], current["version"]) == (row.id, 2)


def test_a_stale_answer_to_a_transfer_match_is_still_refused(server, admin_client):
    """schema.md §2: a transfer match is counted, so the bitcoin sync's writes never fail on
    it, but a person's answer names the version it read (S13.8.6) and a stale one is refused."""
    from sqlalchemy import select

    from moolakata.store.entities.accounts import Account, Transaction

    with server.db.tx(unscoped="test") as s:
        match, _, _ = _a_transfer_match(s)
        admin = s.scalars(select(User.id).where(User.username == "admin")).one()
        s.get(Account, s.get(Transaction, match.outId).accountId).ownerId = admin
        match.ownerId = admin
        s.add(match)
    with server.db.tx(unscoped="test") as s:
        s.get(type(match), match.id).state = "proposed"  # the sync proposes it again
    r = admin_client.post(
        f"/ui/api/transfers/bitcoin/{match.id}", json={"confirm": False},
        headers={"If-Match": '"1"'},
    )  # fmt: skip
    assert r.status_code == 412, r.text
    assert (r.json()["code"], r.json()["version"]) == ("stale-version", 2)


def test_a_signup_request_written_only_by_a_persons_action_is_locked(db):
    """schema.md §2: no background task writes a sign-up request, only the sign-up, its
    confirmation and an admin's decision, each a person's own action: a write from a copy read
    before another save is refused for its version."""
    from sqlalchemy.orm.exc import StaleDataError

    from moolakata.store import mapping
    from moolakata.store.entities.users import SignupRequest

    req = SignupRequest(
        id=ids.new_id("Sgnup"), displayName="Bart", username="bart", email="bart@example.org",
        passwordHash="h", sex="male", confirmTokenHash="t",
        confirmBy=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
    )  # fmt: skip
    with db.tx(unscoped="test") as s:
        s.add(req)
    assert SignupRequest not in mapping.COUNTED
    with db.tx(unscoped="test") as s:
        s.get(SignupRequest, req.id).status = "waiting"
    with pytest.raises(StaleDataError), db.tx(unscoped="test") as s:
        s.add(req)  # the copy read at version 1
        req.status = "rejected"


def _a_link(s) -> str:
    from moolakata.store.entities.links import Link

    link = Link(id=ids.new_id("Link"), state="active", role="inviter")
    s.add(link)
    s.flush()
    return link.id


def test_partial_unique_index_ignores_deleted(db):
    with db.tx(unscoped="test") as s:
        a = new_user(s)
        a.mark_deleted(None)
    with db.tx(unscoped="test") as s:
        new_user(s)  # the name can be used again
    with pytest.raises(Exception, match="UNIQUE"), db.tx(unscoped="test") as s:
        new_user(s)


# An index on an expression can't be reflected; the upgrade test compares its DDL instead.
@pytest.mark.filterwarnings("ignore:.*expression-based index")
def test_tables_and_revisions_agree(db):
    with db.engine.connect() as conn:
        mc = MigrationContext.configure(
            conn,
            opts={
                "version_table": "SchemaRevision",
                "compare_type": True,
                "include_name": lambda name, type_, parent: (
                    type_ != "table" or not is_search_table(name)
                ),
            },
        )
        diff = compare_metadata(mc, metadata)
    assert diff == []
    assert migrate.current(db.engine) == migrate.head()


def test_schema_follows_the_conventions(db):
    assert schema_check.check_metadata(metadata) == []
    with db.engine.connect() as conn:
        assert schema_check.check_database(conn, metadata) == []


def test_schema_names_each_share_as_a_grant_of_one_item_to_a_user_or_group():
    """R2.9: a share grants one item, of the eight kinds of S10.3, to a user or a group; a
    linked server's named users are `User` records (S10.3.3.1), never the server itself. Each
    share table's row in schema.md says so, one per kind."""
    from pathlib import Path

    from moolakata.links.serve import KINDS
    from moolakata.store.tables.shares import SHARES

    assert sorted(SHARES) == sorted(KINDS)
    doc = (Path(__file__).resolve().parents[3] / "docs" / "schema.md").read_text()
    for kind, table in SHARES.items():
        row = re.search(rf"^\| \w+ +\| {table.name} +\| (.*?) +\|$", doc, re.M)
        assert row, f"{table.name} has its row"
        said = re.fullmatch(
            r"A grant of an? (.+) to a user or a group, at an access class\.", row[1]
        )
        assert said and said[1].endswith(kind.replace("-", " ")), row[1]


def test_schema_checks_catch_breaks():
    md = MetaData()
    Table(
        "Things",
        md,
        Column("id", Text, primary_key=True),
        Column("Bad_Name", Text),
        info={"softDelete": True},
    )
    problems = schema_check.check_metadata(md, "## 3. Prefixes\n\n| Prefix | Table |\n")
    assert any("singular" in p for p in problems)
    assert any("camelCase" in p for p in problems)
    assert any("WITHOUT ROWID" in p for p in problems)
    assert any("no row in schema.md" in p for p in problems)
    assert any("soft-delete" in p or "lacks" in p for p in problems)
    assert any("(schema.md §2)" in p for p in problems)
    assert any("say how it is seen" in p for p in problems)


def test_effective_views_follow_what_records_belong_to(tmp_path):
    from moolakata.store.tables import _base

    saved = _base.metadata
    md = MetaData(naming_convention=_base.NAMING)
    _base.metadata = md
    try:
        Table(
            "User",
            md,
            Column("id", Text, primary_key=True),
            info={"softDelete": False, "exception": "§4.4"},
        )
        parent = record("Thing", "Thng", seen=Seen.server())
        child = record(
            "Part",
            "Part",
            Column("thingId", Text, ForeignKey("Thing.id", ondelete="CASCADE"), nullable=False),
            seen=Seen.server(),
        )
    finally:
        _base.metadata = saved
    engine = make_engine(tmp_path / "v.db", None)
    md.create_all(engine)
    with engine.begin() as conn:
        views.sync(conn, md, access=False)
        now = "2026-10-12T10:00:00.000000Z"
        later = "2026-10-12T11:00:00.000000Z"
        tid, pid = ids.new_id("Thng"), ids.new_id("Part")
        conn.execute(
            parent.insert().values(
                id=tid, createdAt=dt.datetime.now(dt.UTC), updatedAt=dt.datetime.now(dt.UTC)
            )
        )
        conn.execute(
            child.insert().values(
                id=pid,
                thingId=tid,
                createdAt=dt.datetime.now(dt.UTC),
                updatedAt=dt.datetime.now(dt.UTC),
            )
        )
        row = conn.exec_driver_sql('SELECT "effectiveDeleted" FROM "PartEffective"').one()
        assert row[0] == 0
        conn.exec_driver_sql(f"""UPDATE "Thing" SET "deletedAt" = '{later}'""")
        conn.exec_driver_sql(f"""UPDATE "Part" SET "deletedAt" = '{now}'""")
        row = conn.exec_driver_sql(
            'SELECT "effectiveDeleted", "effectiveDeletedAt" FROM "PartEffective"'
        ).one()
        assert row == (1, now)  # the earliest along the chain
        conn.exec_driver_sql("""UPDATE "Part" SET "deletedAt" = NULL""")
        row = conn.exec_driver_sql(
            'SELECT "effectiveDeleted", "effectiveDeletedAt" FROM "PartEffective"'
        ).one()
        assert row == (1, later)


def test_live_leaves_out_deleted_records(db):
    with db.tx(unscoped="test") as s:
        a = new_user(s, "a")
        new_user(s, "b")
        a.mark_deleted(None)
    from moolakata.store.tables.users import User as UserTable

    with db.read(unscoped="test") as s:
        names = [u.username for u in s.scalars(live(User, UserTable))]
    assert names == ["b"]


def test_a_newer_database_refuses_the_unlock(store, keyed_config, master_key):
    """S13.6: the store is opened at the unlock, once the phrase opens the database, and a
    database from a newer release is refused there."""
    with store.db.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE \"SchemaRevision\" SET version_num = '9999'")
    store.db.dispose()
    with pytest.raises(RefuseStart, match="newer MoolaKata"):
        maintenance.open_store(keyed_config, master_key)


def test_a_wrong_data_key_refuses_the_start(store, keyed_config, master_key):
    store.db.dispose()
    ring = master.read_keyring(keyed_config.keyring_path)
    fresh = master.wrap(master_key, master.new_data_key(), ring.master_created, master.now())
    master.write_keyring(keyed_config.keyring_path, fresh)
    with pytest.raises(RefuseStart, match="does not open with the data key"):
        maintenance.open_store(keyed_config, master_key)


def test_a_wrong_phrase_does_not_unlock(store, keyed_config):
    store.db.dispose()
    with pytest.raises(master.WrongPhrase, match="wrapped by"):
        maintenance.open_store(keyed_config, os.urandom(16))


def test_secrets_are_bound_to_their_record_and_field(store):
    key = store.keys.keys.secrets
    with store.db.tx(unscoped="test") as s:
        secret_repo.put(s, key, "PriceSource", "Src_a", "apiKey", "tiingo-123", None)
        assert secret_repo.use(s, key, "PriceSource", "Src_a", "apiKey") == "tiingo-123"
        assert secret_repo.info(s, "PriceSource", "Src_a", "apiKey") is not None
        row = s.scalars(select(Secret)).one()
        assert b"tiingo-123" not in row.ciphertext
        sealed = sealing.Sealed(row.ciphertext, row.nonce, row.wrappedKey)
        with pytest.raises(sealing.SecretError):
            sealing.open_sealed(key, sealed, "PriceSource", "Src_b", "apiKey")
        with pytest.raises(sealing.SecretError):
            sealing.open_sealed(key, sealed, "PriceSource", "Src_a", "otherField")
        secret_repo.put(s, key, "PriceSource", "Src_a", "apiKey", "tiingo-456", None)
        assert len(s.scalars(select(Secret)).all()) == 1  # the old ciphertext is gone
        secret_repo.remove(s, "PriceSource", "Src_a", "apiKey")
        assert secret_repo.use(s, key, "PriceSource", "Src_a", "apiKey") is None


def test_settings_have_defaults_and_are_checked(db):
    from moolakata.errors import Problem

    with db.tx(unscoped="test") as s:
        assert settings.get(s, "passwordMinLength") == 12
        settings.put(s, "passwordMinLength", 16, None)
        assert settings.get(s, "passwordMinLength") == 16
        with pytest.raises(Problem) as e:
            settings.put(s, "passwordMinLength", 6, None)
        assert e.value.errors[0].field == "passwordMinLength"
        with pytest.raises(Problem):
            settings.put(s, "backupTime", "25:00", None)
        assert settings.section(s, "backups") == {"backupTime": "02:30", "backupCopies": 14}


def test_backup_is_verified_restorable_and_pruned(store, keyed_config, tmp_path, master_key):
    with store.db.tx(unscoped="test") as s:
        new_user(s)
    keyed_config.receipts_dir.mkdir(parents=True)
    (keyed_config.receipts_dir / "abc.mkr").write_bytes(b"sealed bytes")
    t0 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    made = [maintenance.backup(keyed_config, store, t0 + dt.timedelta(days=i)) for i in range(5)]
    key = master_key
    for b in made:
        maintenance.check_backup(b, key)
        # The database and its keyring only: the host backs up the files (S14.6).
        assert sorted(p.name for p in b.iterdir()) == ["keyring", "manifest.json", "moolakata.db"]
    # Kept by day, never fewer than three: a second backup the same day, Backup Now,
    # pushes out no earlier day's.
    again = maintenance.backup(keyed_config, store, t0 + dt.timedelta(days=4, hours=6))
    assert maintenance.prune(keyed_config, 1) == made[:2]
    assert maintenance.backups(keyed_config) == [*made[2:], again]
    assert maintenance.backup_days(keyed_config) == 3
    made = made[2:]

    # The restore of S15.6.8: the key from its phrase, the data directory from a backup.
    from moolakata.config import Config

    restored = Config(**{**keyed_config.__dict__, "data_dir": tmp_path / "restored"})
    restored.data_dir.mkdir()
    shutil.copy(made[-1] / "moolakata.db", restored.db_path)
    shutil.copy(made[-1] / "keyring", restored.keyring_path)
    again = maintenance.open_store(restored, master_key)
    with again.db.read(unscoped="test") as s:
        assert s.scalars(select(User)).one().username == "jane"
    again.db.dispose()

    (made[-1] / "keyring").write_text((made[-1] / "keyring").read_text().replace("a", "b", 1))
    with pytest.raises(Exception):  # noqa: B017 - any failure: the copy changed
        maintenance.check_backup(made[-1], key)


def test_reencrypt_changes_the_data_key_and_keeps_everything(store, keyed_config, master_key):
    with store.db.tx(unscoped="test") as s:
        new_user(s)
        secret_repo.put(s, store.keys.keys.secrets, "Smtp", "Smtp_x", "password", "hunter2", None)
    old_db_key = store.keys.keys.database
    with pytest.raises(master.WrongPhrase):
        maintenance.reencrypt(keyed_config, store, os.urandom(16))
    store2 = maintenance.reencrypt(keyed_config, store, master_key)
    assert store2.keys.keys.database != old_db_key
    with store2.db.read(unscoped="test") as s:
        assert (
            secret_repo.use(s, store2.keys.keys.secrets, "Smtp", "Smtp_x", "password") == "hunter2"
        )
    store2.db.dispose()
    store3 = maintenance.open_store(keyed_config, master_key)
    with store3.db.read(unscoped="test") as s:
        assert s.scalars(select(User)).one().username == "jane"
    store3.db.dispose()


def test_an_interrupted_reencrypt_is_finished_at_start(
    store, keyed_config, monkeypatch, master_key
):
    """S15.7.2: a crash part-way leaves a journal; the next unlock carries it on, redoing
    nothing, and the data opens under the new key."""
    from moolakata.store import reencrypt as journaled

    with store.db.tx(unscoped="test") as s:
        secret_repo.put(s, store.keys.keys.secrets, "Smtp", "Smtp_x", "password", "hunter2", None)
    old_db_key = store.keys.keys.database

    def crash(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(journaled, "rewrap_files", crash)
    with pytest.raises(KeyboardInterrupt):
        maintenance.reencrypt(keyed_config, store, master_key)
    monkeypatch.undo()
    assert maintenance.next_keyring(keyed_config).exists()
    steps = journaled.journal(keyed_config)["steps"]
    assert steps["rekeyed"] is True and "secrets" in steps and "receipts" not in steps
    again = maintenance.open_store(keyed_config, master_key)
    assert not maintenance.next_keyring(keyed_config).exists()
    assert journaled.journal(keyed_config) is None
    assert again.keys.keys.database != old_db_key
    with again.db.read(unscoped="test") as s:
        assert (
            secret_repo.use(s, again.keys.keys.secrets, "Smtp", "Smtp_x", "password") == "hunter2"
        )
    done = journaled.report(keyed_config)
    assert done["backup"] and done["receiptsSetAside"] == []
    again.db.dispose()


def test_a_file_or_secret_under_neither_key_is_set_aside_not_fatal(store, keyed_config, master_key):
    """S15.7.2: one bad file never stops a re-encryption for ever."""
    from moolakata.keys import files
    from moolakata.store import reencrypt as journaled

    keyed_config.receipts_dir.mkdir(parents=True)
    public = store.keys.keys.receipts.public_key()
    files.write(keyed_config.receipts_dir / "good.mkr", [b"ok"], public, "good")
    (keyed_config.receipts_dir / "broken.mkr").write_bytes(b"not sealed at all")
    with store.db.tx(unscoped="test") as s:
        secret_repo.put(s, store.keys.keys.secrets, "Smtp", "Smtp_x", "password", "hunter2", None)
        from moolakata.store.entities.core import Secret

        row = s.query(Secret).one()
        row.nonce = bytes(len(row.nonce))  # a secret that opens under no key
    again = maintenance.reencrypt(keyed_config, store, master_key)
    done = journaled.report(keyed_config)
    assert done["receiptsSetAside"] == ["broken.mkr"]
    assert done["secretsSetAside"] == ["Smtp/Smtp_x/password"]
    assert (keyed_config.data_dir / "receipts-set-aside" / "broken.mkr").exists()
    assert journaled.opens(keyed_config.receipts_dir / "good.mkr", again.keys.keys.receipts, "good")
    again.db.dispose()


@pytest.mark.parametrize(
    "step", ["backup", "next", "rekeyed", "secrets", "receipts", "keyring", "copies"]
)
def test_a_reencryption_stopped_after_any_step_and_before_its_record_resumes(
    store, keyed_config, monkeypatch, master_key, step
):
    """Each step is taken, then recorded; a stop between the two (a crash, a power cut) is carried
    on at the next unlock with the data under the one new data key the journal names, never a
    third."""
    from moolakata.keys import files
    from moolakata.store import reencrypt as journaled

    keyed_config.receipts_dir.mkdir(parents=True)
    files.write(
        keyed_config.receipts_dir / "r1.mkr",
        [b"a receipt"],
        store.keys.keys.receipts.public_key(),
        "r1",
    )
    with store.db.tx(unscoped="test") as s:
        new_user(s)
        secret_repo.put(s, store.keys.keys.secrets, "Smtp", "Smtp_x", "password", "hunter2", None)
    maintenance.backup(keyed_config, store, dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    real = journaled._step

    def stop_before_recording(config, j, name, value):
        if name == step:
            raise KeyboardInterrupt
        real(config, j, name, value)

    monkeypatch.setattr(journaled, "_step", stop_before_recording)
    with pytest.raises(KeyboardInterrupt):
        maintenance.reencrypt(keyed_config, store, master_key)
    monkeypatch.undo()
    named = journaled.journal(keyed_config)["steps"].get("next")
    again = maintenance.open_store(keyed_config, master_key)
    ring = master.read_keyring(keyed_config.keyring_path)
    if named:
        assert ring.data_key_id == named  # the journal's new key, never a third
    assert ring.data_key_id != store.keys.ring.data_key_id
    with again.db.read(unscoped="test") as s:
        assert s.scalars(select(User)).one().username == "jane"
        assert (
            secret_repo.use(s, again.keys.keys.secrets, "Smtp", "Smtp_x", "password") == "hunter2"
        )
    assert journaled.opens(keyed_config.receipts_dir / "r1.mkr", again.keys.keys.receipts, "r1")
    assert journaled.journal(keyed_config) is None
    # The old keyring stays until the store has opened under the new one (`tidy`).
    journaled.tidy(keyed_config)
    assert not (keyed_config.data_dir / journaled.OLD).exists()
    done = journaled.report(keyed_config)
    assert set(done["copies"].values()) <= {"re-encrypted", "already under the new data key"}
    again.db.dispose()


def test_a_receipt_damaged_past_its_first_part_is_set_aside_with_no_half_file(
    store, keyed_config, master_key
):
    """Its first chunk opens under the old key, a later one doesn't: the file is set aside as
    damaged and the run goes on, leaving no `.tmp`."""
    from moolakata.keys import files
    from moolakata.store import reencrypt as journaled

    keyed_config.receipts_dir.mkdir(parents=True)
    path = keyed_config.receipts_dir / "big.mkr"
    files.write(path, [os.urandom(200_000)], store.keys.keys.receipts.public_key(), "big")
    data = bytearray(path.read_bytes())
    data[files.HEADER + files.CHUNK + files.TAG + 10] ^= 1  # a byte in the second chunk
    path.write_bytes(bytes(data))
    assert journaled.opens(path, store.keys.keys.receipts, "big")
    again = maintenance.reencrypt(keyed_config, store, master_key)
    assert journaled.report(keyed_config)["receiptsSetAside"] == ["big.mkr"]
    assert (keyed_config.data_dir / journaled.SET_ASIDE / "big.mkr").exists()
    assert not list(keyed_config.receipts_dir.glob("*.tmp"))
    again.db.dispose()


def test_copies_the_choices_dont_name_are_reencrypted_the_first_backup_last(
    store, keyed_config, monkeypatch, master_key
):
    """A backup made after the choices (a daily one, the run's own first) holds the data key being
    replaced: it takes the default, re-encrypt, and the run's own goes last."""
    from moolakata.store import copies
    from moolakata.store import reencrypt as journaled

    named = maintenance.backup(keyed_config, store, dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    journaled.schedule(keyed_config, {named.name: "leave"}, None, "settings")
    later = maintenance.backup(keyed_config, store, dt.datetime(2026, 1, 2, tzinfo=dt.UTC))
    order = []
    real = journaled._copy
    monkeypatch.setattr(journaled, "_copy", lambda c, *a: order.append(c.name) or real(c, *a))
    store.db.dispose()
    again = maintenance.open_store(keyed_config, master_key)
    done = journaled.report(keyed_config)
    first = done["backup"]
    assert done["copies"][named.name] == "left"
    assert done["copies"][later.name] == done["copies"][first] == "re-encrypted"
    assert order[-1] == first
    new_id = again.keys.ring.data_key_id
    assert all(
        c.ring.data_key_id == new_id
        for c in copies.copies(keyed_config)
        if c.name in (later.name, first)
    )
    again.db.dispose()


def test_a_backup_cut_off_part_way_is_removed_and_a_set_aside_keyring_listed(
    store, keyed_config, master_key
):
    """A `.part` folder never stays, and a keyring set aside is a copy to remove."""
    from moolakata.store import copies

    keyed_config.backup_dir.mkdir(parents=True)
    stale = keyed_config.backup_dir / "moolakata-20250101-000000.part"
    stale.mkdir()
    (stale / "moolakata.db").write_bytes(b"half a database")
    maintenance.backup(keyed_config, store)
    assert not stale.exists()
    aside = keyed_config.data_dir / "keyring.next.set-aside-20260101-000000"
    aside.write_text(store.keys.ring.to_json())
    found = copies.find(keyed_config, aside.name)
    assert found is not None and found.kind == "keyring"
    copies.remove(found)
    assert not aside.exists()


def test_a_keyring_next_nothing_explains_is_set_aside_never_deleted(
    store, keyed_config, master_key
):
    store.db.dispose()
    maintenance.next_keyring(keyed_config).write_text("{}")
    again = maintenance.open_store(keyed_config, master_key)
    assert not maintenance.next_keyring(keyed_config).exists()
    assert list(keyed_config.data_dir.glob("keyring.next.set-aside-*"))
    again.db.dispose()


def test_migration_copies_the_database_first(store, keyed_config, monkeypatch, master_key):
    with store.db.tx(unscoped="test") as s:
        new_user(s)
    store.db.dispose()
    engine = make_engine(keyed_config.db_path, store.keys.keys.sqlcipher_key)
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE \"SchemaRevision\" SET version_num = '0001'")
    engine.dispose()
    monkeypatch.setattr(migrate, "head", lambda: "0002")
    monkeypatch.setattr(migrate, "known", lambda: {"0001", "0002"})
    calls = []
    monkeypatch.setattr(migrate.command, "upgrade", lambda cfg, rev: calls.append(rev))
    older = keyed_config.data_dir / "pre-upgrade"
    older.mkdir()
    for i in range(3):  # three copies from earlier upgrades, oldest first
        (older / f"moolakata-before-000{i}-x.db").write_bytes(b"old")
        os.utime(older / f"moolakata-before-000{i}-x.db", (1_000_000 + i, 1_000_000 + i))
    maintenance.open_store(keyed_config, master_key).db.dispose()
    copies = sorted(p.name for p in older.glob("*.db"))
    assert calls == ["head"]
    # The new copy and the two newest before it: the oldest is removed.
    assert len(copies) == migrate.PRE_UPGRADE_KEPT and "moolakata-before-0000-x.db" not in copies
    new = [p for p in older.glob("*.db") if "0002" in p.name and "-x" not in p.name]
    assert len(new) == 1 and os.stat(new[0]).st_mode & 0o777 == 0o600
    # It carries its keyring, so it still opens after a re-encryption (S15.7).
    ring = new[0].with_suffix(".keyring")
    assert master.read_keyring(ring).master_id == master.key_id(master_key)


def test_database_class_requires_a_unit_of_work(db):
    assert isinstance(db, Database)


def test_the_pool_keeps_connections_apart_across_threads(db):
    """Many requests at once each get their own connection, never a closed one."""
    import threading

    from sqlalchemy.pool import QueuePool

    assert isinstance(db.engine.pool, QueuePool)
    with db.tx(unscoped="test") as s:
        new_user(s)
    failures = []

    def read():
        try:
            for _ in range(20):
                with db.read(unscoped="test") as s:
                    s.scalars(select(User)).all()
        except Exception as e:
            failures.append(e)

    threads = [threading.Thread(target=read) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert failures == []


def test_a_backup_after_reads_still_writes_its_copy(store, keyed_config):
    """A pooled connection returns writable after a read (the backup's export needs it)."""
    for _ in range(5):
        with store.db.read(unscoped="test") as s:
            s.scalars(select(User)).all()
    maintenance.backup(keyed_config, store)


def _clauses(sql: str) -> list[str]:
    """A CREATE statement's columns and constraints, in whatever order they were written, and
    a default with or without the parentheses Alembic writes around it."""
    sql = re.sub(r"DEFAULT \(('[^']*'|[\w.-]+)\)", r"DEFAULT \1", sql)
    return sorted(line.strip().rstrip(",").strip() for line in sql.splitlines() if line.strip())


def test_revisions_carry_a_database_from_0001_to_head(tmp_path):
    """Every revision after 0001, run as the server runs them: rows written at 0001 are kept,
    a deleted one stays deleted, rows referring to a rebuilt table keep their references with
    foreign keys back on, and each table ends as the declarations make it. The rows are written
    in 0001's terms, so they change only when 0001 does."""
    from alembic import command

    engine = make_engine(tmp_path / "old.db", None)
    stamp = "'2026-10-01 00:00:00'"
    uid, gone = ids.new_id("User"), ids.new_id("User")
    pa, pb = ids.new_id("Persn"), ids.new_id("Persn")
    aid, iid, tid = ids.new_id("Acct"), ids.new_id("Imprt"), ids.new_id("Txn")
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0001")
        conn.commit()
        for statement in (
            'INSERT INTO "Person" (id, name, sex, version, "createdAt", "updatedAt", deleted) '
            f"VALUES ('{pa}', 'Jane', 'female', 1, {stamp}, {stamp}, 0)",
            'INSERT INTO "Person" (id, name, sex, version, "createdAt", "updatedAt", deleted) '
            f"VALUES ('{pb}', 'John', 'male', 1, {stamp}, {stamp}, 0)",
            'INSERT INTO "User" (id, "personId", username, "displayName", version, '
            f"\"createdAt\", \"updatedAt\", deleted) VALUES ('{uid}', '{pa}', 'jane', "
            f"'Jane', 1, {stamp}, {stamp}, 0)",
            'INSERT INTO "User" (id, "personId", username, "displayName", version, '
            f'"createdAt", "updatedAt", deleted, "deletedAt", "deletedById") VALUES '
            f"('{gone}', '{pb}', 'john', 'John', 1, {stamp}, {stamp}, 1, {stamp}, '{uid}')",
            # Closed: 0046 takes the day of its last transaction as its closed date.
            'INSERT INTO "Account" (id, "ownerId", name, type, active, version, "createdAt", '
            f"\"updatedAt\", deleted) VALUES ('{aid}', '{uid}', 'Checking', 'checking', 0, 1, "
            f"{stamp}, {stamp}, 0)",
            'INSERT INTO "Import" (id, "accountId", "userId", format, "fileName", "fileHash", '
            f"version, \"createdAt\", \"updatedAt\", deleted) VALUES ('{iid}', '{aid}', '{uid}', "
            f"'ofx', 'a.ofx', 'h', 1, {stamp}, {stamp}, 0)",
            'INSERT INTO "Transaction" (id, "accountId", date, kind, amount, "importId", '
            f"version, \"createdAt\", \"updatedAt\", deleted) VALUES ('{tid}', '{aid}', "
            f"'2026-10-01', 'deposit', '10.00', '{iid}', 1, {stamp}, {stamp}, 0)",
            'INSERT INTO "OneTimeToken" ("tokenHash", purpose, "userId", "createdAt", '
            f"\"expiresAt\") VALUES ('h1', 'invitation', '{uid}', {stamp}, '2030-01-01 00:00:00')",
            'INSERT INTO "Setting" ("key", value, "updatedById", version, "updatedAt", deleted) '
            f"VALUES ('householdName', '\"The Does\"', '{uid}', 3, {stamp}, 0)",
            'INSERT INTO "TransactionTags" ("transactionId", "userId", tag, "createdAt", deleted) '
            f"VALUES ('{tid}', '{uid}', 'coffee', {stamp}, 0)",
        ):
            conn.exec_driver_sql(statement)
        conn.commit()
        before = {
            name: conn.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar_one()
            for (name,) in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'ReceiptSearch%'"
            )
        }

    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert conn.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
        for name, count in before.items():
            if name in metadata.tables:
                assert conn.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar() == count
        users = conn.exec_driver_sql(
            'SELECT username, "effectiveDeleted" FROM "UserEffective" ORDER BY 1'
        ).all()
        assert [tuple(u) for u in users] == [("jane", 0), ("john", 1)]
        closed = conn.exec_driver_sql(f'SELECT "closedOn" FROM "Account" WHERE id = \'{aid}\'')
        assert closed.scalar_one() == "2026-10-01"
        txn = conn.exec_driver_sql(f'SELECT "importId" FROM "Transaction" WHERE id = \'{tid}\'')
        assert txn.scalar_one() == iid
        tagged = conn.exec_driver_sql(
            'SELECT t."ownerId", t.name FROM "TransactionTags" x JOIN "Tag" t ON t.id = x."tagId"'
        ).one()
        assert tuple(tagged) == (uid, "coffee")
        setting = conn.exec_driver_sql('SELECT id, value, version FROM "Setting"').one()
        assert setting[0].startswith("Setng_") and setting[1:] == ('"The Does"', 3)
        migrated = dict(
            conn.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type = 'table'").all()
        )
        migrated_ix = dict(conn.exec_driver_sql(INDEXES).all())
    engine.dispose()

    fresh = make_engine(tmp_path / "fresh.db", None)
    metadata.create_all(fresh)
    with fresh.connect() as conn:
        made = dict(
            conn.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type = 'table'").all()
        )
        made_ix = dict(conn.exec_driver_sql(INDEXES).all())
    fresh.dispose()
    differ = [n for n in metadata.tables if _clauses(migrated[n]) != _clauses(made[n])]
    assert differ == []
    # An index on an expression, which the comparison of tables and revisions can't reflect.
    flat = lambda sql: " ".join(sql.split())  # noqa: E731
    assert {n: flat(x) for n, x in migrated_ix.items()} == {n: flat(x) for n, x in made_ix.items()}


INDEXES = "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"


def test_restore_puts_a_backup_back_and_keeps_what_it_replaced(store, keyed_config, master_key):
    """`moolakata db restore` (S15.6.8): the backup checked, what it replaces moved aside, and
    the restored database opens at the server's next start."""
    from moolakata.keys import files

    def receipt(name: str, data: bytes) -> None:
        public = store.keys.keys.receipts.public_key()
        files.write(keyed_config.receipts_dir / f"{name}.mkr", [data], public, name)

    with store.db.tx(unscoped="test") as s:
        new_user(s, "jane")
    keyed_config.receipts_dir.mkdir(parents=True)
    receipt("abc", b"sealed bytes")
    made = maintenance.backup(keyed_config, store)
    assert maintenance.verify_backup(keyed_config, master_key) == made
    with pytest.raises(RefuseStart, match="does not open with that phrase"):
        maintenance.verify_backup(keyed_config, os.urandom(16))
    with store.db.tx(unscoped="test") as s:
        new_user(s, "john")
    receipt("later", b"after the backup")
    store.db.dispose()

    held = maintenance.lock_data_dir(keyed_config, "test")
    with pytest.raises(RefuseStart, match="stop the server before restoring"):
        maintenance.restore(keyed_config, made, master_key)
    held.close()

    aside = maintenance.restore(keyed_config, made, master_key)
    # The receipts stay where they are; the database and keyring are set aside (S14.6).
    assert sorted(p.name for p in aside.iterdir()) == ["keyring", "moolakata.db"]
    assert (keyed_config.data_dir / "restored.json").exists(), "the next unlock checks it"
    assert sorted(p.name for p in keyed_config.receipts_dir.iterdir()) == ["abc.mkr", "later.mkr"]
    again = maintenance.open_store(keyed_config, master_key)
    with again.db.read(unscoped="test") as s:
        assert [u.username for u in s.scalars(select(User))] == ["jane"]
        # A file no record names is counted, for Settings › Storage to offer removing.
        from moolakata.receipts import retention

        assert retention.orphan_files(s, keyed_config.receipts_dir) == [
            keyed_config.receipts_dir / "abc.mkr",
            keyed_config.receipts_dir / "later.mkr",
        ]
    again.db.dispose()


def test_restore_refuses_a_changed_backup_or_one_from_a_newer_release(
    store, keyed_config, master_key
):
    made = maintenance.backup(keyed_config, store)
    store.db.dispose()
    manifest = made / "manifest.json"
    # A manifest rewritten by hand is refused as not the backup's own (S14.6)...
    head = f'"revision": "{migrate.head()}"'
    manifest.write_text(manifest.read_text().replace(head, '"revision": "9999"'))
    with pytest.raises(RuntimeError, match="not the one its backup wrote"):
        maintenance.verify_backup(keyed_config, master_key, made)
    # ...and one a newer release wrote, signed by it, is refused for its revision.
    m = json.loads(manifest.read_text())
    maintenance.write_manifest(manifest, m, store.keys.data_key)
    with pytest.raises(RefuseStart, match="from a newer MoolaKata"):
        maintenance.restore(keyed_config, made, master_key)
    assert keyed_config.db_path.exists()  # nothing was moved
    with open(made / "moolakata.db", "ab") as f:
        f.write(b"x")
    with pytest.raises(RuntimeError, match="has changed since the backup"):
        maintenance.verify_backup(keyed_config, master_key, made)


def test_the_copies_on_the_host_are_listed_rewrapped_reencrypted_and_removed(
    store, keyed_config, master_key
):
    """S15.7: every copy carries its keyring; a rotation's re-encryption rewrites it, Settings
    removes it; each says how it opens."""
    from moolakata.store import copies

    with store.db.tx(unscoped="test") as s:
        new_user(s)
    b = maintenance.backup(keyed_config, store)
    older = keyed_config.data_dir / "pre-upgrade"
    older.mkdir()
    key = store.keys.keys.sqlcipher_key
    copy.export(store.db.engine, older / "moolakata-before-0009-t.db", key)
    shutil.copy2(keyed_config.keyring_path, older / "moolakata-before-0009-t.keyring")
    aside = keyed_config.data_dir / "before-restore-20261001-000000"
    aside.mkdir()
    copy.export(store.db.engine, aside / "moolakata.db", key)
    shutil.copy2(keyed_config.keyring_path, aside / "keyring")
    found = copies.copies(keyed_config)
    assert [(c.kind, c.name) for c in found] == [
        ("backup", b.name),
        ("pre-upgrade", "moolakata-before-0009-t.db"),
        ("before-restore", aside.name),
    ]
    assert all(copies.opens_with(c, store.keys) == "current" for c in found)

    # Rotation in the running server (S15.7.1): the keyring under the new phrase at once, and
    # a re-encryption journaled that will rewrite one copy, delete one and leave the other.
    from moolakata.store import reencrypt as journaled

    new_key = os.urandom(16)
    store2, outcomes = maintenance.rotate_running(
        keyed_config,
        store,
        new_key,
        {b.name: "reencrypt", aside.name: "delete", "moolakata-before-0009-t.db": "leave"},
    )
    assert outcomes == {
        b.name: "re-encrypted at the restart",
        aside.name: "deleted at the restart",
        "moolakata-before-0009-t.db": "left",
    }
    j = journaled.journal(keyed_config)
    assert j["why"] == "rotation" and j["to"] == master.key_id(new_key)
    assert maintenance.verify_backup(keyed_config, master_key) == b, "still under its day's key"
    assert [master.fingerprint(p.master_id) for p in store2.keys.ring.previous] == [
        master.fingerprint(master_key)
    ]

    # The next unlock, with the new phrase: everything under a new data key, the backup
    # rewritten under it and the new phrase, the copy chosen deleted, the pre-upgrade copy
    # left under the old one, and the run's own first backup rewritten last.
    store2.db.dispose()
    store3 = maintenance.open_store(keyed_config, new_key)
    assert store3.keys.ring.data_key_id != store.keys.ring.data_key_id
    found = {c.name: c for c in copies.copies(keyed_config)}
    first = journaled.report(keyed_config)["backup"]
    assert copies.opens_with(found[b.name], store3.keys) == "current"
    assert copies.opens_with(found["moolakata-before-0009-t.db"], store3.keys) == "previous"
    assert copies.opens_with(found[first], store3.keys) == "current"
    assert aside.name not in found
    assert maintenance.verify_backup(keyed_config, new_key, b) == b
    assert journaled.report(keyed_config)["copies"] == {
        b.name: "re-encrypted",
        aside.name: "deleted",
        "moolakata-before-0009-t.db": "left",
        first: "re-encrypted",
    }
    store3.db.dispose()

    # Settings: forget the previous key, remove a copy.
    assert copies.forget_previous(keyed_config, master.fingerprint(master_key))
    assert master.read_keyring(keyed_config.keyring_path).previous == ()
    assert not copies.forget_previous(keyed_config, "mk-none")
    copies.remove(found["moolakata-before-0009-t.db"])
    assert [c.kind for c in copies.copies(keyed_config)] == ["backup", "backup"]
    assert not (older / "moolakata-before-0009-t.keyring").exists()


def test_a_rotation_offers_a_copy_no_rewrap_without_reencrypting(store, keyed_config, master_key):
    """S15.7.1: a rotation always re-encrypts, so a copy's choice is to be re-encrypted,
    deleted or left; a re-wrap under the new phrase alone is refused before anything changes."""
    from moolakata.store import reencrypt as journaled

    b = maintenance.backup(keyed_config, store)
    before = keyed_config.keyring_path.read_bytes()
    with pytest.raises(ValueError, match="each copy: reencrypt, delete or leave"):
        maintenance.rotate_running(keyed_config, store, os.urandom(16), {b.name: "rewrap"})
    assert keyed_config.keyring_path.read_bytes() == before
    assert not journaled.pending(keyed_config)


def test_a_pending_reencryption_under_another_phrase_is_refused_by_name(
    store, keyed_config, master_key, monkeypatch
):
    """S15.7.2: a re-encryption interrupted, then a rotation offline: the next unlock says
    which phrase finishes it instead of crashing."""

    from moolakata.store import reencrypt as journaled

    def crash(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(journaled, "_rewrap_secrets", crash)
    with pytest.raises(KeyboardInterrupt):
        maintenance.reencrypt(keyed_config, store, master_key)
    monkeypatch.undo()
    other = os.urandom(16)
    ring = master.read_keyring(keyed_config.keyring_path)
    master.write_keyring(
        keyed_config.keyring_path,
        master.rotated(ring, master.unwrap(master_key, ring), other, master.now()),
    )
    with pytest.raises(RefuseStart, match="pending under mk-"):
        maintenance.open_store(keyed_config, other)


def test_a_restore_after_a_reencryption_rewraps_the_receipts_and_resets_the_links(
    store, keyed_config, master_key
):
    """S15.6.8: the receipts stay where they are, under the data key a re-encryption made
    since the backup; the restore re-wraps them to the backup's, and the first unlock after it
    starts each link's copy again and reports what doesn't open."""
    from moolakata import ids
    from moolakata.app import Server
    from moolakata.keys import files
    from moolakata.runtime import check_restored
    from moolakata.store import reencrypt as journaled
    from moolakata.store.entities.links import Link

    keyed_config.receipts_dir.mkdir(parents=True)
    public = store.keys.keys.receipts.public_key()
    files.write(keyed_config.receipts_dir / "r1.mkr", [b"one"], public, "r1")
    with store.db.tx(unscoped="test") as s:
        link = Link(id=ids.new_id("Link"), state="active", role="inviter", copyPublicKey="k")
        link.copyFolder = "f"
        s.add(link)
    made = maintenance.backup(keyed_config, store)
    old_receipts = store.keys.keys.receipts
    store = maintenance.reencrypt(keyed_config, store, master_key, {made.name: "leave"})
    assert not journaled.opens(keyed_config.receipts_dir / "r1.mkr", old_receipts, "r1")
    store.db.dispose()
    maintenance.restore(keyed_config, made, master_key)
    assert journaled.opens(keyed_config.receipts_dir / "r1.mkr", old_receipts, "r1")
    again = maintenance.open_store(keyed_config, master_key)
    srv = Server(config=keyed_config, store=again, ready=True)
    mark = maintenance.after_restore(keyed_config)
    check_restored(srv, mark)
    with again.db.read(unscoped="test") as s:
        link = s.query(Link).one()
        assert link.copyPublicKey is None and link.copyFolder is None and link.needsFull
    report = maintenance.restore_report(keyed_config)
    assert report["receiptsUnopened"] == [] and report["secretsUnopened"] == []
    again.db.dispose()


def test_a_restore_under_an_earlier_phrase_asks_first(store, keyed_config, master_key):
    """S15.6.8: a backup made before a rotation restores under that phrase: the restore names
    it and goes on only when asked to."""
    made = maintenance.backup(keyed_config, store)
    new_key = os.urandom(16)
    store2, _ = maintenance.rotate_running(keyed_config, store, new_key)
    store2.db.dispose()
    from moolakata.store import reencrypt as journaled

    (keyed_config.data_dir / journaled.JOURNAL).unlink()  # as if never scheduled
    asked = []
    with pytest.raises(RefuseStart, match="current phrase stays"):
        maintenance.restore(
            keyed_config, made, master_key, confirm=lambda q: asked.append(q) or False
        )
    assert "no longer does" in asked[0] and master.fingerprint(master_key) in asked[0]
    maintenance.restore(keyed_config, made, master_key, confirm=lambda q: True)
    assert master.read_keyring(keyed_config.keyring_path).master_id == master.key_id(master_key)


def test_a_pre_upgrade_copy_restores_like_a_backup(store, keyed_config, master_key):
    """S16.13: `db restore` takes a pre-upgrade copy's .db with its .keyring beside it."""
    with store.db.tx(unscoped="test") as s:
        new_user(s, "jane")
    older = keyed_config.data_dir / "pre-upgrade"
    older.mkdir()
    key = store.keys.keys.sqlcipher_key
    copy.export(store.db.engine, older / "moolakata-before-0009-t.db", key)
    shutil.copy2(keyed_config.keyring_path, older / "moolakata-before-0009-t.keyring")
    with store.db.tx(unscoped="test") as s:
        new_user(s, "john")
    store.db.dispose()
    maintenance.restore(keyed_config, older / "moolakata-before-0009-t.db", master_key)
    again = maintenance.open_store(keyed_config, master_key)
    with again.db.read(unscoped="test") as s:
        assert [u.username for u in s.scalars(select(User))] == ["jane"]
    again.db.dispose()


def test_an_offline_backup_needs_the_server_stopped_and_changes_nothing(
    store, keyed_config, master_key
):
    """S15.4.7: on the host, with the server stopped: the lock taken, read only, nothing
    pending run and nothing migrated."""
    from moolakata.store import reencrypt as journaled

    store.db.dispose()
    journaled.schedule(keyed_config, {}, None, "settings")
    with pytest.raises(RefuseStart, match="re-encryption is pending"):
        maintenance.open_store(keyed_config, master_key, read_only=True)
    (keyed_config.data_dir / journaled.JOURNAL).unlink()  # as if never scheduled
    st = maintenance.open_store(keyed_config, master_key, read_only=True)
    with pytest.raises(Exception), st.db.engine.begin() as conn:  # noqa: B017 - refused
        conn.exec_driver_sql("PRAGMA query_only = 1")
        conn.exec_driver_sql('DELETE FROM "User"')
    st.db.dispose()


def test_0017_writes_money_in_cents_and_leaves_the_premium_to_the_replay(tmp_path):
    """Decimal text becomes integer cents; a stock trade settled before keeps the
    strike's cash, its premium worked out at replay; a sale made before records its method."""
    from alembic import command

    def insert(conn, table: str, **values) -> None:
        values |= {"createdAt": "2026-10-01 00:00:00", "updatedAt": "2026-10-01 00:00:00"}
        names = ", ".join(f'"{k}"' for k in values)
        marks = ", ".join("?" for _ in values)
        conn.exec_driver_sql(
            f'INSERT INTO "{table}" ({names}) VALUES ({marks})', tuple(values.values())
        )

    engine = make_engine(tmp_path / "old.db", None)
    uid, pid, aid = ids.new_id("User"), ids.new_id("Persn"), ids.new_id("Acct")
    inst, lot, loan = ids.new_id("Instr"), ids.new_id("Lot"), ids.new_id("Loan")
    end, buy, end2, sell = (ids.new_id("Txn") for _ in range(4))
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0016")
        conn.commit()
        insert(conn, "Person", id=pid, name="A", sex="female")
        insert(conn, "User", id=uid, personId=pid, username="a", displayName="A")
        insert(conn, "Account", id=aid, ownerId=uid, name="B", type="brokerage", lotMethod="lifo")
        insert(conn, "Instrument", id=inst, symbol="MSFT", instrumentClass="equity")
        day = "2026-09-18"
        insert(conn, "Transaction", id=end, accountId=aid, date=day, kind="assign", amount=0)
        insert(
            conn,
            "Transaction",
            id=buy,
            accountId=aid,
            date=day,
            kind="buy",
            amount=-4800000,
            instrumentId=inst,
            quantity="100",
            optionTransactionId=end,
        )
        # Settled before: the put's $640 credit taken off the lot's basis.
        insert(
            conn,
            "Lot",
            id=lot,
            accountId=aid,
            instrumentId=inst,
            transactionId=buy,
            acquiredOn=day,
            quantity="100",
            costBasis=4736000,
        )
        insert(conn, "Transaction", id=end2, accountId=aid, date=day, kind="assign", amount=0)
        insert(
            conn,
            "Transaction",
            id=sell,
            accountId=aid,
            date=day,
            kind="sell",
            amount=4800000,
            instrumentId=inst,
            quantity="100",
            optionTransactionId=end2,
            proceedsAdjustment="640.00",
        )
        insert(
            conn,
            "Loan",
            id=loan,
            accountId=aid,
            principal="300000.50",
            startDate="2026-01-01",
            termMonths=360,
            rate="6.875",
        )
        conn.commit()

    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        q = conn.exec_driver_sql
        assert tuple(q(f"SELECT principal, rate FROM \"Loan\" WHERE id = '{loan}'").one()) == (
            30000050,
            "6.875",
        )
        assert q(f'SELECT "costBasis" FROM "Lot" WHERE id = \'{lot}\'').scalar_one() == 4800000
        row = q(
            f'SELECT "proceedsAdjustment", "lotMethod" FROM "Transaction" WHERE id = \'{sell}\''
        )
        assert tuple(row.one()) == (None, "lifo")
        assert q("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()


def test_0056_leaves_no_close_to_the_manual_source_and_refuses_one(tmp_path):
    """A close is a fetching source's: a `manual` one left from before goes, a fetched one
    stays, and a `manual` one is refused from then on: the shape the price code's branches
    for it (removed) would have handled."""
    from alembic import command

    engine = make_engine(tmp_path / "old.db", None)
    inst = ids.new_id("Instr")
    fetched, manual = ids.new_id("Price"), ids.new_id("Price")
    stamp = "2026-10-01 00:00:00"
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0055")
        conn.commit()
        q = conn.exec_driver_sql
        q('INSERT INTO "Instrument" (id, symbol, "instrumentClass", "createdAt", "updatedAt") '
          "VALUES (?, 'MSFT', 'equity', ?, ?)", (inst, stamp, stamp))  # fmt: skip
        for pid, source in ((fetched, "tiingo"), (manual, "manual")):
            q('INSERT INTO "Price" (id, "instrumentId", date, close, source, "fetchedAt", '
              '"createdAt", "updatedAt") VALUES (?, ?, ?, \'400\', ?, ?, ?, ?)',
              (pid, inst, "2026-09-0" + ("1" if source == "tiingo" else "2"), source, stamp,
               stamp, stamp))  # fmt: skip
        conn.commit()

    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        q = conn.exec_driver_sql
        assert [r[0] for r in q('SELECT id FROM "Price"')] == [fetched]
        assert "enteredById" not in [r[1] for r in q('PRAGMA table_xinfo("Price")')]
        with pytest.raises(Exception, match="ck_Price_source"):
            q('INSERT INTO "Price" (id, "instrumentId", date, close, source, "fetchedAt", '
              '"createdAt", "updatedAt") VALUES (?, ?, \'2026-09-03\', \'1\', \'manual\', ?, ?, ?)',
              (ids.new_id("Price"), inst, stamp, stamp, stamp))  # fmt: skip
        assert q("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()


def test_0057_clears_a_label_on_any_relation_but_family_and_refuses_one(tmp_path):
    """Only a family relationship carries a label (S10.10.4): one left on another relation is
    cleared, a family one stays, and a label on another relation is refused from then on: the
    shape the dependents' relation words (which read only the word) would have shown."""
    from alembic import command

    engine = make_engine(tmp_path / "old.db", None)
    stamp = "2026-10-01 00:00:00"
    a, b = sorted(ids.new_id("Persn") for _ in range(2))
    friend, family = ids.new_id("Rltn"), ids.new_id("Rltn")
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0056")
        conn.commit()
        q = conn.exec_driver_sql
        for pid, name in ((a, "Ann"), (b, "Bea")):
            q('INSERT INTO "Person" (id, name, sex, "createdAt", "updatedAt") '
              "VALUES (?, ?, 'female', ?, ?)", (pid, name, stamp, stamp))  # fmt: skip
        for rid, relation in ((friend, "friend"), (family, "family")):
            q('INSERT INTO "Relationship" (id, "person1Id", "person2Id", relation, label, '
              '"createdAt", "updatedAt") VALUES (?, ?, ?, ?, \'godmother\', ?, ?)',
              (rid, a, b, relation, stamp, stamp))  # fmt: skip
        conn.commit()

    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        q = conn.exec_driver_sql
        assert dict(q('SELECT relation, label FROM "Relationship"').fetchall()) == {
            "friend": None,
            "family": "godmother",
        }
        with pytest.raises(Exception, match="ck_Relationship_label"):
            q("UPDATE \"Relationship\" SET label = 'aunt' WHERE id = ?", (friend,))
        assert q("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()


def test_0065_counts_a_pledge_from_the_period_it_was_last_changed_in(tmp_path):
    """S7.9.5: a pledge made before counts from the month (or year) of its last change; an
    organisation without one has no period, and a pledge without one is refused from then on."""
    from alembic import command

    engine = make_engine(tmp_path / "old.db", None)
    stamp = "2026-10-01 00:00:00"
    uid, pid = ids.new_id("User"), ids.new_id("Persn")
    monthly, yearly, none = (ids.new_id("Orgzn") for _ in range(3))
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0064")
        conn.commit()
        q = conn.exec_driver_sql
        q('INSERT INTO "Person" (id, name, sex, "createdAt", "updatedAt") '
          "VALUES (?, 'Jane', 'female', ?, ?)", (pid, stamp, stamp))  # fmt: skip
        q('INSERT INTO "User" (id, "personId", username, "displayName", "createdAt", '
          "\"updatedAt\") VALUES (?, ?, 'jane', 'Jane', ?, ?)",
          (uid, pid, stamp, stamp))  # fmt: skip
        for oid, pledge, every, changed in (
            (monthly, 5000, "month", "2026-09-14T08:00:00.000000Z"),
            (yearly, 30000, "year", "2025-06-02T08:00:00.000000Z"),
            (none, None, None, stamp),
        ):
            q('INSERT INTO "Organisation" (id, "ownerId", name, pledge, "pledgeEvery", '
              '"createdAt", "updatedAt") VALUES (?, ?, ?, ?, ?, ?, ?)',
              (oid, uid, oid, pledge, every, stamp, changed))  # fmt: skip
        conn.commit()

    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        q = conn.exec_driver_sql
        assert dict(q('SELECT id, "pledgeFrom" FROM "Organisation"').fetchall()) == {
            monthly: "2026-09-01",
            yearly: "2025-01-01",
            none: None,
        }
        with pytest.raises(Exception, match="ck_Organisation_pledge_from"):
            q('UPDATE "Organisation" SET "pledgeFrom" = NULL WHERE id = ?', (monthly,))
    engine.dispose()


def test_0066_gives_each_row_its_version_and_times_from_its_own(tmp_path):
    """schema.md §2: a row of a table that had no version or times gets version 1, made when
    its own time says and changed at the latest it keeps; one that keeps none, the
    migration's time."""
    from alembic import command

    engine = make_engine(tmp_path / "old.db", None)
    made, seen, last = (
        "2026-09-01T08:00:00.000000Z",
        "2026-09-14T08:00:00.000000Z",
        "2026-10-02T08:00:00.000000Z",
    )
    uid, pid = ids.new_id("User"), ids.new_id("Persn")
    act, alert, state, sess = (ids.new_id(p) for p in ("Actv", "Alert", "AlSt", "Sessn"))
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0065")
        conn.commit()
        q = conn.exec_driver_sql
        q('INSERT INTO "Person" (id, name, sex, "createdAt", "updatedAt") '
          "VALUES (?, 'Jane', 'female', ?, ?)", (pid, made, made))  # fmt: skip
        q('INSERT INTO "User" (id, "personId", username, "displayName", "createdAt", '
          "\"updatedAt\") VALUES (?, ?, 'jane', 'Jane', ?, ?)", (uid, pid, made, made))  # fmt: skip
        q("INSERT INTO \"Activity\" (id, at, kind) VALUES (?, ?, 'x')", (act, seen))
        q('INSERT INTO "Alert" (id, kind, "causeKey", title, "seenSince", "openedAt") '
          "VALUES (?, 'k', 'c', 't', ?, ?)", (alert, made, last))  # fmt: skip
        q(
            'INSERT INTO "AlertState" (id, "alertId", "userId") VALUES (?, ?, ?)',
            (state, alert, uid),
        )
        q('INSERT INTO "Session" (id, "tokenHash", "userId", "createdAt", "lastSeenAt", '
          '"expiresAt", "authAt") VALUES (?, \'h\', ?, ?, ?, ?, ?)',
          (sess, uid, made, last, "2027-01-01T00:00:00.000000Z", seen))  # fmt: skip
        conn.commit()

    before = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        row = lambda t, i: tuple(  # noqa: E731
            conn.exec_driver_sql(
                f'SELECT version, "createdAt", "updatedAt" FROM "{t}" WHERE id = ?', (i,)
            ).one()
        )
        assert row("Activity", act) == (1, seen, seen)
        assert row("Alert", alert) == (1, made, last)
        assert row("Session", sess) == (1, made, last)
        version, created, updated = row("AlertState", state)
        assert version == 1 and created == updated and created >= before
    engine.dispose()


def test_0070_gives_a_receipt_the_scans_total_and_whether_it_was_checked(tmp_path):
    """S9.8.2.1.1: `Receipt.scanTotal` and `totalChecked` start empty on every receipt read
    before (nothing checked), and a scan's total is never kept without whether it was checked."""
    from alembic import command

    engine = make_engine(tmp_path / "old.db", None)
    made = "2026-09-01T08:00:00.000000Z"
    uid, pid, rid = ids.new_id("User"), ids.new_id("Persn"), ids.new_id("Rcpt")
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0069")
        conn.commit()
        q = conn.exec_driver_sql
        q('INSERT INTO "Person" (id, name, sex, "createdAt", "updatedAt") '
          "VALUES (?, 'Jane', 'female', ?, ?)", (pid, made, made))  # fmt: skip
        q('INSERT INTO "User" (id, "personId", username, "displayName", "createdAt", '
          "\"updatedAt\") VALUES (?, ?, 'jane', 'Jane', ?, ?)", (uid, pid, made, made))  # fmt: skip
        q('INSERT INTO "Receipt" (id, "ownerId", "fileName", "mediaType", size, sha256, '
          '"fileId", amount, "createdAt", "updatedAt") VALUES (?, ?, \'r.pdf\', '
          "'application/pdf', 3, 'h', 'f', 7234, ?, ?)", (rid, uid, made, made))  # fmt: skip
        conn.commit()

    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        q = conn.exec_driver_sql
        got = q('SELECT amount, "scanTotal", "totalChecked" FROM "Receipt"').one()
        assert tuple(got) == (7234, None, None)
        with pytest.raises(Exception, match="ck_Receipt_scan_total"):
            q('UPDATE "Receipt" SET "scanTotal" = 1234 WHERE id = ?', (rid,))
        q('UPDATE "Receipt" SET "scanTotal" = 1234, "totalChecked" = 0 WHERE id = ?', (rid,))
    engine.dispose()


def test_0071_names_each_keyed_wallets_bitcoin_node_wallet_at_random(tmp_path):
    """S1.6.2.3: a wallet account whose keys were saved is given its Bitcoin node wallet's
    name, `moolakata-` and a random one, never its id; any other account none; no two share
    one. A transaction's moment and a user's time zones start empty."""
    import re

    from alembic import command

    engine = make_engine(tmp_path / "old.db", None)
    made = "2026-09-01T08:00:00.000000Z"
    uid, pid = ids.new_id("User"), ids.new_id("Persn")
    keyed, other, bare, bank = (ids.new_id("Acct") for _ in range(4))
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0070")
        conn.commit()
        q = conn.exec_driver_sql
        q('INSERT INTO "Person" (id, name, sex, "createdAt", "updatedAt") '
          "VALUES (?, 'Jane', 'female', ?, ?)", (pid, made, made))  # fmt: skip
        q('INSERT INTO "User" (id, "personId", username, "displayName", "createdAt", '
          "\"updatedAt\") VALUES (?, ?, 'jane', 'Jane', ?, ?)", (uid, pid, made, made))  # fmt: skip
        for a, kind in ((keyed, "crypto-wallet"), (other, "crypto-wallet"),
                        (bare, "crypto-wallet"), (bank, "checking")):  # fmt: skip
            q('INSERT INTO "Account" (id, "ownerId", name, type, "createdAt", "updatedAt") '
              "VALUES (?, ?, 'A', ?, ?, ?)", (a, uid, kind, made, made))  # fmt: skip
        for a in (keyed, other, bank):
            q('INSERT INTO "WalletKey" (id, "accountId", kind, value, script, "createdAt", '
              "\"updatedAt\") VALUES (?, ?, 'address', ?, 'p2wpkh', ?, ?)",
              (ids.new_id("WKey"), a, f"bc1q{a[-8:]}", made, made))  # fmt: skip
        txn = ids.new_id("Txn")
        q('INSERT INTO "Transaction" (id, "accountId", date, kind, amount, "fitId", '
          "\"createdAt\", \"updatedAt\") VALUES (?, ?, '2026-08-31', 'transfer-in', 0, ?, ?, ?)",
          (txn, keyed, "btc:" + "a" * 64, made, made))  # fmt: skip
        conn.commit()

    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        got = dict(conn.exec_driver_sql('SELECT id, "bitcoinNodeWallet" FROM "Account"').all())
        named = [got[keyed], got[other]]
        assert all(re.fullmatch(r"moolakata-[0-9a-f]{16}", n) for n in named)
        assert named[0] != named[1] and (got[bare], got[bank]) == (None, None)
        # No two accounts share one; any number have none.
        with pytest.raises(Exception, match="UNIQUE"):
            conn.exec_driver_sql(
                'UPDATE "Account" SET "bitcoinNodeWallet" = ? WHERE id = ?', (named[0], other)
            )
        # S1.6.2.6.1: a transaction recorded before has no moment until its next read; S14.9.2:
        # no user has a time zone history until they change their time zone.
        q = conn.exec_driver_sql
        assert q('SELECT date, "confirmedAt" FROM "Transaction"').one() == ("2026-08-31", None)
        assert q('SELECT count(*) FROM "UserTimeZone"').scalar_one() == 0
        tz = (ids.new_id("UsrTz"), uid, made, made)
        sql = ('INSERT INTO "UserTimeZone" (id, "userId", "timeZone", since, "createdAt", '
               "\"updatedAt\") VALUES (?, ?, 'America/Denver', '2026-09-01', ?, ?)")  # fmt: skip
        q(sql, tz)
        with pytest.raises(Exception, match="UNIQUE"):
            q(sql, (ids.new_id("UsrTz"), *tz[1:]))
    engine.dispose()


def test_0072_gives_every_instrument_no_price_miss(tmp_path):
    """S4.2.2: `Instrument.priceMissedAt` starts empty on every instrument, its rows and its
    unique symbol kept; the next refresh records each one no source knows."""
    from alembic import command

    engine = make_engine(tmp_path / "old.db", None)
    made = "2026-09-01T08:00:00.000000Z"
    vti = ids.new_id("Instr")
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0071")
        conn.commit()
        conn.exec_driver_sql(
            'INSERT INTO "Instrument" (id, symbol, "instrumentClass", cusip, "createdAt", '
            "\"updatedAt\") VALUES (?, 'VTI', 'etf', '922908769', ?, ?)",
            (vti, made, made),
        )
        conn.commit()

    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        q = conn.exec_driver_sql
        got = q('SELECT id, symbol, cusip, "priceMissedAt" FROM "Instrument"').one()
        assert tuple(got) == (vti, "VTI", "922908769", None)
        with pytest.raises(Exception, match="UNIQUE"):
            q('INSERT INTO "Instrument" (id, symbol, "instrumentClass", "createdAt", '
              "\"updatedAt\") VALUES (?, 'VTI', 'equity', ?, ?)",
              (ids.new_id("Instr"), made, made))  # fmt: skip
    engine.dispose()


def test_0073_gives_every_tax_book_no_magi(tmp_path):
    """S8.6: `TaxBook.magi` starts empty on every book, its rows and its other figures kept;
    a Roth IRA contribution is read against it once typed."""
    from alembic import command

    engine = make_engine(tmp_path / "old.db", None)
    made = "2026-09-01T08:00:00.000000Z"
    book = ids.new_id("TaxBk")
    with engine.connect() as conn:
        command.upgrade(migrate.alembic_config(conn), "0072")
        conn.commit()
        person, user = ids.new_id("Persn"), ids.new_id("User")
        conn.exec_driver_sql(
            'INSERT INTO "Person" (id, name, sex, "createdAt", "updatedAt") '
            "VALUES (?, 'Jane', 'female', ?, ?)",
            (person, made, made),
        )
        conn.exec_driver_sql(
            'INSERT INTO "User" (id, "personId", username, "displayName", "createdAt", '
            "\"updatedAt\") VALUES (?, ?, 'jane', 'Jane', ?, ?)",
            (user, person, made, made),
        )
        conn.exec_driver_sql(
            'INSERT INTO "TaxBook" (id, "ownerId", year, "carryoverShareLong", "createdAt", '
            '"updatedAt") VALUES (?, ?, 2026, 210000, ?, ?)',
            (book, user, made, made),
        )
        conn.commit()

    assert migrate.upgrade(engine, tmp_path / "old.db", None, None)

    with engine.connect() as conn:
        got = conn.exec_driver_sql(
            'SELECT id, year, "carryoverShareLong", magi FROM "TaxBook"'
        ).one()
        assert tuple(got) == (book, 2026, 210000, None)
    engine.dispose()


def test_a_failed_write_names_no_value_it_was_given(store):
    # S13.7.9: the engines hide statement parameters, so a failed write logs no value.
    from sqlalchemy.exc import IntegrityError

    secret = "4111-1111-1111-1111"
    row = {"k": "aTestKey", "v": json.dumps(secret), "t": "2026-10-17T00:00:00.000000Z"}
    insert = text('INSERT INTO "Setting" (key, value, "updatedAt") VALUES (:k, :v, :t)')
    with pytest.raises(IntegrityError) as e, store.db.tx(unscoped="test") as s:
        s.execute(insert, row)
        s.execute(insert, row)
    assert secret not in str(e.value)


def test_two_backups_in_one_second_take_two_names(store, keyed_config, master_key):
    """A fast host can make two backups within one second: the later one takes the next free
    second, and its manifest says so, so each still passes its name check (S14.6)."""
    at = dt.datetime(2026, 10, 18, 4, 3, 38, 250000, tzinfo=dt.UTC)
    first = maintenance.backup(keyed_config, store, now=at)
    second = maintenance.backup(keyed_config, store, now=at.replace(microsecond=750000))
    assert first.name == "moolakata-20261018-040338"
    assert second.name == "moolakata-20261018-040339"
    for b in (first, second):
        maintenance.verify_backup(keyed_config, master_key, b)
    assert maintenance.made_of(second) == at.replace(second=39, microsecond=750000)


def test_a_backup_renamed_to_another_time_is_refused(store, keyed_config, master_key):
    # Verify-backup and restore go by the manifest's own time, so a backup renamed to a
    # newer one's name passes for nothing.
    made = maintenance.backup(keyed_config, store)
    assert maintenance.made_of(made).replace(microsecond=0).strftime("%Y%m%d-%H%M%S") in made.name
    renamed = made.with_name("moolakata-20991231-235959")
    made.rename(renamed)
    with pytest.raises(RefuseStart, match="not when its name says"):
        maintenance.verify_backup(keyed_config, master_key, renamed)
