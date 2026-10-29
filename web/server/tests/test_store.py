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
from moolakata.store.tables._base import record
from moolakata.store.tables.receipts import is_search_table


def new_user(s, name="alice"):
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
    with store.db.tx() as s:
        new_user(s)
    raw = keyed_config.db_path.read_bytes()
    assert b"SQLite format 3" not in raw[:100]
    assert b"alice" not in raw
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(keyed_config.db_path).execute("SELECT * FROM User").fetchall()


def test_read_refuses_writes_and_tx_commits(db):
    with db.tx() as s:
        new_user(s)
    with db.read() as s:
        assert s.scalars(select(User)).one().username == "alice"
        with pytest.raises(Exception, match=r"readonly|query_only|attempt to write"):
            s.execute(text("UPDATE User SET displayName = 'x'"))


def test_versions_change_with_every_save(db):
    with db.tx() as s:
        u = new_user(s)
    assert u.version == 1
    with db.tx() as s:
        u = s.get(User, u.id)
        u.displayName = "Alice G."
    assert u.version == 2


def test_partial_unique_index_ignores_deleted(db):
    with db.tx() as s:
        a = new_user(s)
        a.mark_deleted(None)
    with db.tx() as s:
        new_user(s)  # the name can be used again
    with pytest.raises(Exception, match="UNIQUE"), db.tx() as s:
        new_user(s)


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
        parent = record("Thing", "Thng")
        child = record(
            "Part",
            "Part",
            Column("thingId", Text, ForeignKey("Thing.id", ondelete="CASCADE"), nullable=False),
        )
    finally:
        _base.metadata = saved
    engine = make_engine(tmp_path / "v.db", None)
    md.create_all(engine)
    with engine.begin() as conn:
        views.sync(conn, md)
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
    with db.tx() as s:
        a = new_user(s, "a")
        new_user(s, "b")
        a.mark_deleted(None)
    from moolakata.store.tables.users import User as UserTable

    with db.read() as s:
        names = [u.username for u in s.scalars(live(User, UserTable))]
    assert names == ["b"]


def test_a_newer_database_refuses_the_start(store, keyed_config, master_key):
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
    with store.db.tx() as s:
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

    with db.tx() as s:
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
    with store.db.tx() as s:
        new_user(s)
    keyed_config.receipts_dir.mkdir(parents=True)
    (keyed_config.receipts_dir / "abc.mkr").write_bytes(b"sealed bytes")
    t0 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    made = [maintenance.backup(keyed_config, store, t0 + dt.timedelta(days=i)) for i in range(3)]
    key = master_key
    for b in made:
        maintenance.check_backup(b, key)
        # The database and its keyring only: the host backs up the files (S14.6).
        assert sorted(p.name for p in b.iterdir()) == ["keyring", "manifest.json", "moolakata.db"]
    assert maintenance.prune(keyed_config, 2) == made[:1]
    assert maintenance.backups(keyed_config) == made[1:]

    # The restore of S15.6.8: the key from its phrase, the data directory from a backup.
    from moolakata.config import Config

    restored = Config(**{**keyed_config.__dict__, "data_dir": tmp_path / "restored"})
    restored.data_dir.mkdir()
    shutil.copy(made[-1] / "moolakata.db", restored.db_path)
    shutil.copy(made[-1] / "keyring", restored.keyring_path)
    again = maintenance.open_store(restored, master_key)
    with again.db.read() as s:
        assert s.scalars(select(User)).one().username == "alice"
    again.db.dispose()

    (made[-1] / "keyring").write_text((made[-1] / "keyring").read_text().replace("a", "b", 1))
    with pytest.raises(Exception):  # noqa: B017 - any failure: the copy changed
        maintenance.check_backup(made[-1], key)


def test_reencrypt_changes_the_data_key_and_keeps_everything(store, keyed_config, master_key):
    with store.db.tx() as s:
        new_user(s)
        secret_repo.put(s, store.keys.keys.secrets, "Smtp", "Smtp_x", "password", "hunter2", None)
    old_db_key = store.keys.keys.database
    with pytest.raises(master.WrongPhrase):
        maintenance.reencrypt(keyed_config, store, os.urandom(16))
    store2 = maintenance.reencrypt(keyed_config, store, master_key)
    assert store2.keys.keys.database != old_db_key
    with store2.db.read() as s:
        assert (
            secret_repo.use(s, store2.keys.keys.secrets, "Smtp", "Smtp_x", "password") == "hunter2"
        )
    store2.db.dispose()
    store3 = maintenance.open_store(keyed_config, master_key)
    with store3.db.read() as s:
        assert s.scalars(select(User)).one().username == "alice"
    store3.db.dispose()


def test_an_interrupted_reencrypt_is_finished_at_start(
    store, keyed_config, monkeypatch, master_key
):
    """S15.7.2: a crash part-way leaves a journal; the next unlock carries it on, redoing
    nothing, and the data opens under the new key."""
    from moolakata.store import reencrypt as journaled

    with store.db.tx() as s:
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
    with again.db.read() as s:
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
    with store.db.tx() as s:
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
    with store.db.tx() as s:
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
    with db.tx() as s:
        new_user(s)
    failures = []

    def read():
        try:
            for _ in range(20):
                with db.read() as s:
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
        with store.db.read() as s:
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
            f"VALUES ('{pa}', 'Alice', 'female', 1, {stamp}, {stamp}, 0)",
            'INSERT INTO "Person" (id, name, sex, version, "createdAt", "updatedAt", deleted) '
            f"VALUES ('{pb}', 'Bob', 'male', 1, {stamp}, {stamp}, 0)",
            'INSERT INTO "User" (id, "personId", username, "displayName", version, '
            f"\"createdAt\", \"updatedAt\", deleted) VALUES ('{uid}', '{pa}', 'alice', "
            f"'Alice', 1, {stamp}, {stamp}, 0)",
            'INSERT INTO "User" (id, "personId", username, "displayName", version, '
            f'"createdAt", "updatedAt", deleted, "deletedAt", "deletedById") VALUES '
            f"('{gone}', '{pb}', 'bob', 'Bob', 1, {stamp}, {stamp}, 1, {stamp}, '{uid}')",
            'INSERT INTO "Account" (id, "ownerId", name, type, version, "createdAt", '
            f"\"updatedAt\", deleted) VALUES ('{aid}', '{uid}', 'Checking', 'checking', 1, "
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
            f"VALUES ('householdName', '\"The Griffins\"', '{uid}', 3, {stamp}, 0)",
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
        assert [tuple(u) for u in users] == [("alice", 0), ("bob", 1)]
        txn = conn.exec_driver_sql(f'SELECT "importId" FROM "Transaction" WHERE id = \'{tid}\'')
        assert txn.scalar_one() == iid
        setting = conn.exec_driver_sql('SELECT id, value, version FROM "Setting"').one()
        assert setting[0].startswith("Setng_") and setting[1:] == ('"The Griffins"', 3)
        migrated = dict(
            conn.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type = 'table'").all()
        )
    engine.dispose()

    fresh = make_engine(tmp_path / "fresh.db", None)
    metadata.create_all(fresh)
    with fresh.connect() as conn:
        made = dict(
            conn.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type = 'table'").all()
        )
    fresh.dispose()
    differ = [n for n in metadata.tables if _clauses(migrated[n]) != _clauses(made[n])]
    assert differ == []


def test_restore_puts_a_backup_back_and_keeps_what_it_replaced(store, keyed_config, master_key):
    """`moolakata db restore` (S15.6.8): the backup checked, what it replaces moved aside, and
    the restored database opens at the server's next start."""
    from moolakata.keys import files

    def receipt(name: str, data: bytes) -> None:
        public = store.keys.keys.receipts.public_key()
        files.write(keyed_config.receipts_dir / f"{name}.mkr", [data], public, name)

    with store.db.tx() as s:
        new_user(s, "alice")
    keyed_config.receipts_dir.mkdir(parents=True)
    receipt("abc", b"sealed bytes")
    made = maintenance.backup(keyed_config, store)
    assert maintenance.verify_backup(keyed_config, master_key) == made
    with pytest.raises(RefuseStart, match="does not open with that phrase"):
        maintenance.verify_backup(keyed_config, os.urandom(16))
    with store.db.tx() as s:
        new_user(s, "bob")
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
    with again.db.read() as s:
        assert [u.username for u in s.scalars(select(User))] == ["alice"]
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
    """S15.7: every copy carries its keyring; a rotation re-wraps it, a re-encryption rewrites
    it, Settings removes it; each says how it opens."""
    from moolakata.store import copies

    with store.db.tx() as s:
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

    # Rotation through the running server (S15.7.1): the keyring under the new phrase at
    # once, one copy deleted now, and a re-encryption scheduled that will rewrite one copy and
    # leave the other.
    from moolakata.store import reencrypt as journaled

    new_key = os.urandom(16)
    store2, outcomes = maintenance.rotate_running(
        keyed_config,
        store,
        new_key,
        {b.name: "reencrypt", aside.name: "delete", "moolakata-before-0009-t.db": "leave"},
    )
    assert outcomes == {
        b.name: "re-encrypted at the next unlock",
        aside.name: "deleted",
        "moolakata-before-0009-t.db": "left",
    }
    assert journaled.journal(keyed_config)["why"] == "rotation"
    assert maintenance.verify_backup(keyed_config, master_key) == b, "still under its day's key"
    assert [master.fingerprint(p.master_id) for p in store2.keys.ring.previous] == [
        master.fingerprint(master_key)
    ]

    # The next unlock, with the new phrase: everything under a new data key, the backup
    # rewritten under it and the new phrase, the pre-upgrade copy left under the old one.
    store2.db.dispose()
    store3 = maintenance.open_store(keyed_config, new_key)
    assert store3.keys.ring.data_key_id != store.keys.ring.data_key_id
    found = {c.name: c for c in copies.copies(keyed_config)}
    first = journaled.report(keyed_config)["backup"]
    assert copies.opens_with(found[b.name], store3.keys) == "current"
    assert copies.opens_with(found["moolakata-before-0009-t.db"], store3.keys) == "previous"
    assert copies.opens_with(found[first], store3.keys) == "phrase", "the old data key"
    assert maintenance.verify_backup(keyed_config, new_key, b) == b
    assert journaled.report(keyed_config)["copies"] == {
        b.name: "re-encrypted",
        "moolakata-before-0009-t.db": "left",
        # The backup the re-encryption made first, under the replaced data key.
        journaled.report(keyed_config)["backup"]: "left",
    }
    store3.db.dispose()

    # Settings: forget the previous key, remove a copy.
    assert copies.forget_previous(keyed_config, master.fingerprint(master_key))
    assert master.read_keyring(keyed_config.keyring_path).previous == ()
    assert not copies.forget_previous(keyed_config, "mk-none")
    copies.remove(found["moolakata-before-0009-t.db"])
    assert [c.kind for c in copies.copies(keyed_config)] == ["backup", "backup"]
    assert not (older / "moolakata-before-0009-t.keyring").exists()


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
    with store.db.tx() as s:
        link = Link(id=ids.new_id("Link"), state="active", role="inviter", copyPublicKey="k")
        link.copyFolder = "f"
        s.add(link)
    made = maintenance.backup(keyed_config, store)
    old_receipts = store.keys.keys.receipts
    store = maintenance.reencrypt(keyed_config, store, master_key)
    assert not journaled.opens(keyed_config.receipts_dir / "r1.mkr", old_receipts, "r1")
    store.db.dispose()
    maintenance.restore(keyed_config, made, master_key)
    assert journaled.opens(keyed_config.receipts_dir / "r1.mkr", old_receipts, "r1")
    again = maintenance.open_store(keyed_config, master_key)
    srv = Server(config=keyed_config, store=again, ready=True)
    mark = maintenance.after_restore(keyed_config)
    check_restored(srv, mark)
    with again.db.read() as s:
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

    journaled.cancel(keyed_config)
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
    with store.db.tx() as s:
        new_user(s, "alice")
    older = keyed_config.data_dir / "pre-upgrade"
    older.mkdir()
    key = store.keys.keys.sqlcipher_key
    copy.export(store.db.engine, older / "moolakata-before-0009-t.db", key)
    shutil.copy2(keyed_config.keyring_path, older / "moolakata-before-0009-t.keyring")
    with store.db.tx() as s:
        new_user(s, "bob")
    store.db.dispose()
    maintenance.restore(keyed_config, older / "moolakata-before-0009-t.db", master_key)
    again = maintenance.open_store(keyed_config, master_key)
    with again.db.read() as s:
        assert [u.username for u in s.scalars(select(User))] == ["alice"]
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
    journaled.cancel(keyed_config)
    st = maintenance.open_store(keyed_config, master_key, read_only=True)
    with pytest.raises(Exception), st.db.engine.begin() as conn:  # noqa: B017 - refused
        conn.exec_driver_sql("PRAGMA query_only = 1")
        conn.exec_driver_sql('DELETE FROM "User"')
    st.db.dispose()


def test_0017_writes_money_in_cents_and_leaves_the_premium_to_the_replay(tmp_path):
    """B23 and B12: decimal text becomes integer cents; a stock trade settled before keeps the
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


def test_a_failed_write_names_no_value_it_was_given(store):
    # S13.7.9: the engines hide statement parameters, so a failed write logs no value.
    from sqlalchemy.exc import IntegrityError

    secret = "4111-1111-1111-1111"
    row = {"k": "aTestKey", "v": json.dumps(secret), "t": "2026-10-17T00:00:00.000000Z"}
    insert = text('INSERT INTO "Setting" (key, value, "updatedAt") VALUES (:k, :v, :t)')
    with pytest.raises(IntegrityError) as e, store.db.tx() as s:
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
    # K25: verify-backup and restore go by the manifest's own time, so a backup renamed to a
    # newer one's name passes for nothing.
    made = maintenance.backup(keyed_config, store)
    assert maintenance.made_of(made).replace(microsecond=0).strftime("%Y%m%d-%H%M%S") in made.name
    renamed = made.with_name("moolakata-20991231-235959")
    made.rename(renamed)
    with pytest.raises(RefuseStart, match="not when its name says"):
        maintenance.verify_backup(keyed_config, master_key, renamed)
