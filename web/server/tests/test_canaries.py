"""Nothing of a household is readable on the disk (requirements S11.9.1, S11.9.10, S15.7):
one scenario puts distinctive strings (canaries) in the fields that carry a person's data, runs
what writes files (a link and a share with receipts, a pull while the copy is locked, a receipt
upload, an OFX import, a CSV held for its mapping, a backup), then reads every file under the
data and backups folders, and the logs, for each canary. Only what S15.7 leaves plain may hold
one (the mail folder); and every file must be a kind that is known by its header, so a new kind
of file fails here before it ever holds data."""

import logging
import re
from pathlib import Path

from conftest import make_user, sign_in
from edits import attach, make, saved, share
from linkpair import linked
from test_accounts import add, upload
from test_links import admins, links_of, pair  # noqa: F401
from test_receipts import png

from moolakata.links import copy as lcopy
from moolakata.store.entities.users import User

FIX = Path(__file__).parent / "fixtures"
CANARIES = {
    "owner": "Zebulon Quixotic",
    "account": "Quokka Reserve",
    "payee": "Xylophone Emporium",
    "memo": "Marmalade Invoice",
    "ofx payee": "Wombat Hardware",
    "csv payee": "Narwhal Bakery",
    "receipt file": "zanzibar-receipt",
}
AMOUNT = "31415.92"
AMOUNT_FORMS = ("31415.92", "3141592", "31,415.92")


def encodings(text: str) -> list[bytes]:
    """A canary as it could sit in a file: UTF-8, UTF-16, JSON's \\u escapes."""
    escaped = "".join(f"\\u{ord(c):04x}" for c in text)
    return [text.encode(), text.encode("utf-16-le"), escaped.encode()]


SQLITE_PLAIN = b"SQLite format 3\x00"
SEALED = b"MKR1"


def kind(path: Path, data_dir: Path, srv) -> str | None:
    """What a file is, by where it lives and its header; None for a kind nobody named."""
    rel = path.relative_to(data_dir).parts if path.is_relative_to(data_dir) else path.parts
    head = path.read_bytes()[:16]
    if head.startswith(SQLITE_PLAIN):
        return None  # a plain SQLite database: never
    if re.search(r"\.db(-wal|-shm|-journal)?$", path.name):
        return "database"
    if head.startswith(SEALED):
        return "sealed"
    if path == srv.config.keyring_path or (path.name == "keyring" and "backups" in path.parts):
        return "keyring"  # wrapped keys only, and read for canaries all the same
    if path.name == "manifest.json" and path.is_relative_to(srv.config.backup_dir):
        return "backup manifest"  # its files and their hashes, read for canaries too
    if rel and rel[0] in ("mail", "tls"):
        return "plain by S15.7"
    return None


def scan(srv, data_dir: Path, folders: list[Path]):
    unknown, found = [], []
    for folder in folders:
        for p in folder.rglob("*"):
            if not p.is_file():
                continue
            k = kind(p, data_dir, srv)
            if k is None:
                unknown.append(str(p))
                continue
            if k == "plain by S15.7":
                continue
            body = p.read_bytes()
            for name, text in [*CANARIES.items(), *(("amount", a) for a in AMOUNT_FORMS)]:
                if any(e in body for e in encodings(text)):
                    found.append((name, str(p)))
    return unknown, found


def test_no_canary_is_readable_on_the_disk_or_in_the_logs(admins, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    a, b, ca, cb, _ = admins
    make_user(b, "carol")
    make_user(a, "alice")
    with a.db.tx() as s:  # the owner's name, as the share carries it across
        s.query(User).filter(User.username == "alice").update({User.displayName: CANARIES["owner"]})
    alice = sign_in(a, "alice")
    a_id, b_id = linked(ca, cb)
    acct = make(alice, "Acct", name=CANARIES["account"], type="checking").json()
    t = add(alice, acct["id"], amount=f"-{AMOUNT}", payee=CANARIES["payee"], memo=CANARIES["memo"])
    rid = alice.post(
        "/ui/api/receipts",
        files={"file": (CANARIES["receipt file"] + ".png", png(), "application/octet-stream")},
    ).json()["id"]
    saved(attach(alice, rid, t["id"]))
    # An OFX download and a CSV waiting for its mapping, each naming a canary payee.
    ofx = (FIX / "bank.ofx").read_bytes().replace(b"KROGER #123", CANARIES["ofx payee"].encode())
    upload(alice, acct["id"], "bank.ofx", ofx)
    held = upload(
        alice,
        acct["id"],
        "export.csv",
        f"Date,Description,Amount\n2026-09-05,{CANARIES['csv payee']},-12.00\n".encode(),
    )
    assert held["result"]["needsMapping"], "held, waiting for its mapping"
    # Shared with receipts across the link, pulled while Carol's copy is locked.
    carol = next(u for u in links_of(ca)["links"][0]["users"] if u["username"] == "carol")
    cb.post(f"/ui/api/settings/links/{b_id}/copy-key")
    share(alice, "account", acct["id"], users={carol["id"]: "read"}, receipts={a_id: True})
    cb.post(f"/ui/api/settings/links/{b_id}/pull")
    inbox = lcopy.folder(b.config.data_dir, b_id) / "inbox"
    assert any(inbox.iterdir()), "the change waits in the inbox, sealed"
    from moolakata.store.maintenance import backup

    for srv in (a, b):  # the daily backup, as its task makes it
        backup(srv.config, srv.store)
    for srv in (a, b):
        unknown, found = scan(
            srv, srv.config.data_dir, [srv.config.data_dir, srv.config.backup_dir]
        )
        assert unknown == [], f"files of no known kind: {unknown}"
        assert found == [], f"readable on the disk: {found}"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for name, text in [*CANARIES.items(), *(("amount", a) for a in AMOUNT_FORMS)]:
        assert text not in logged, f"the {name} is in the logs"
