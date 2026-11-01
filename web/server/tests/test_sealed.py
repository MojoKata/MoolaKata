"""Sealed files and the inbox (requirements S11.9.5, S11.9.6): streamed, chunked AES-256-GCM to
the copy's key, refusing any change to a file; changes applied in order once unlocked, each
signature checked."""

import io
import json
import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select
from test_copies import setup  # noqa: F401

from moolakata import clock
from moolakata.links import changes, copydb, sealed
from moolakata.links import copy as lcopy
from moolakata.links.keys import b64
from moolakata.store.entities.links import Link


def keypair():
    priv = lcopy.private_key(os.urandom(16))
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv, pub


def roundtrip(priv, pub, data: bytes, name="r1", link="Link_x", open_name=None, open_link=None):
    blob = b"".join(sealed.seal(pub, sealed.RECEIPT, link, name, [data]))
    out = b"".join(
        sealed.open_sealed(
            priv, sealed.RECEIPT, open_link or link, open_name or name, io.BytesIO(blob)
        )
    )
    return blob, out


@pytest.mark.parametrize("size", [0, 10, sealed.CHUNK, sealed.CHUNK * 3 + 17])
def test_a_file_seals_and_opens_whatever_its_size(size):
    priv, pub = keypair()
    data = os.urandom(size)
    blob, out = roundtrip(priv, pub, data)
    assert out == data and blob[:4] == b"MKR1"
    chunks = size // sealed.CHUNK + 1
    assert len(blob) == sealed.HEADER + size + chunks * sealed.TAG


def test_a_changed_cut_reordered_or_renamed_file_fails():
    priv, pub = keypair()
    data = os.urandom(sealed.CHUNK * 2 + 5)
    blob, _ = roundtrip(priv, pub, data)

    def opens(b, name="r1", link="Link_x", key=priv):
        try:
            b"".join(sealed.open_sealed(key, sealed.RECEIPT, link, name, io.BytesIO(b)))
            return True
        except sealed.SealError:
            return False

    assert opens(blob)
    flipped = bytearray(blob)
    flipped[sealed.HEADER + 100] ^= 1
    assert not opens(bytes(flipped))
    one = sealed.CHUNK + sealed.TAG
    assert not opens(blob[: sealed.HEADER + one]), "cut after a whole chunk"
    assert not opens(blob[: sealed.HEADER + 2 * one]), "the last chunk dropped"
    first, second = blob[sealed.HEADER : sealed.HEADER + one], blob[sealed.HEADER + one :][:one]
    swapped = blob[: sealed.HEADER] + second + first + blob[sealed.HEADER + 2 * one :]
    assert not opens(swapped)
    assert not opens(blob, name="r2"), "copied onto another receipt"
    assert not opens(blob, link="Link_y")
    assert not opens(blob, key=keypair()[0]), "not this copy's"
    assert not opens(b"MKR0" + blob[4:])


def signed_change(key, seq, server, link_id, **body):
    """A change as a peer sends it: its registry in the open, the rest sealed to this copy's
    key for the peer-to-here direction, and signed by the peer (link-protocol.md §4.4)."""
    from moolakata.links.keys import direction, fingerprint, public_of, unb64

    part = {"seq": seq, "asOf": clock.now().isoformat(), **body}
    with server.db.tx(unscoped="test") as s:  # this server's link key is made on first use
        link = s.get(Link, link_id)
        way = direction(
            fingerprint(unb64(link.peerKey)), fingerprint(public_of(s, server.keys.secrets))
        )
        copy_key = unb64(link.copyPublicKey)
    return changes.sign(key, changes.seal_part(part, copy_key, way))


def test_changes_wait_in_the_inbox_and_apply_in_order_once_unlocked(server, setup):  # noqa: F811
    link_id, admin, alice, _ = setup
    peer = Ed25519PrivateKey.generate()
    with server.db.tx(unscoped="test") as s:
        s.get(Link, link_id).peerKey = b64(
            peer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        )
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    alice_id = alice.get("/ui/api/session").json()["user"]["id"]
    item = {"id": "Acct_1", "kind": "account", "name": "Mom's IRA", "ownerName": "Margaret"}
    changes.enqueue(
        server,
        link_id,
        signed_change(
            peer,
            1,
            server,
            link_id,
            full=True,
            items=[{**item, "viewers": [alice_id], "version": 1}],
        ),
    )
    changes.enqueue(
        server,
        link_id,
        signed_change(
            peer,
            2,
            server,
            link_id,
            items=[{**item, "name": "Mom's Roth IRA", "viewers": [alice_id], "version": 2}],
            docs=[
                {
                    "itemId": "Acct_1",
                    "path": "/accounts/Acct_1",
                    "viewer": alice_id,
                    "body": {"balance": "412880.00"},
                }
            ],
        ),
    )
    inbox = changes.waiting(server.config.data_dir, link_id)
    assert [p.name for p in inbox] == ["0000000001.mks", "0000000002.mks"]
    assert all(b"Roth" not in p.read_bytes() for p in inbox), "sealed: no names on disk"
    with server.db.read(unscoped="test") as s:
        assert s.get(Link, link_id).inboxAsOf is not None
    r = alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    assert r.status_code == 200
    assert changes.waiting(server.config.data_dir, link_id) == []
    o = server.copies.get(link_id)
    with o.engine.connect() as conn:
        rows = conn.execute(select(copydb.Item.c.name, copydb.Item.c.version)).all()
        assert rows == [("Mom's Roth IRA", 2)]
        doc = conn.execute(select(copydb.Doc.c.body)).scalar_one()
        assert json.loads(doc)["balance"] == "412880.00"
    # While it stays unlocked, a new change applies as it arrives.
    changes.enqueue(server, link_id, signed_change(peer, 3, server, link_id, removed=["Acct_1"]))
    with o.engine.connect() as conn:
        assert conn.execute(select(copydb.Item.c.id)).all() == []


def test_a_change_not_signed_by_the_peer_stops_the_apply(server, setup):  # noqa: F811
    link_id, admin, alice, _ = setup
    peer, stranger = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    with server.db.tx(unscoped="test") as s:
        s.get(Link, link_id).peerKey = b64(
            peer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        )
    words = admin.post(f"/ui/api/settings/links/{link_id}/copy-key").json()["words"]
    changes.enqueue(server, link_id, signed_change(peer, 1, server, link_id, items=[]))
    forged = signed_change(stranger, 2, server, link_id, items=[{"id": "x", "kind": "account"}])
    changes.enqueue(server, link_id, forged)
    alice.post(f"/ui/api/linked/{link_id}/unlock", json={"words": " ".join(words)})
    # Nothing applied: set aside, recorded, and everything asked for again (S11.9.5.3).
    assert changes.waiting(server.config.data_dir, link_id) == []
    aside = lcopy.folder(server.config.data_dir, link_id) / "set-aside"
    assert len(list(aside.glob("*.mks"))) == 2
    with server.db.read(unscoped="test") as s:
        link = s.get(Link, link_id)
        assert "signature" in link.lastError and link.needsFull
    with server.copies.get(link_id).engine.connect() as conn:
        assert conn.execute(select(copydb.Item.c.id)).all() == []


def test_an_overflowing_inbox_is_discarded_for_a_full_snapshot(server, setup, monkeypatch):  # noqa: F811
    link_id, admin, _, _ = setup
    peer = Ed25519PrivateKey.generate()
    admin.post(f"/ui/api/settings/links/{link_id}/copy-key")
    monkeypatch.setattr(changes, "MAX_CHANGES", 3)
    with server.db.tx(unscoped="test") as s:
        s.get(Link, link_id).peerKey = b64(
            peer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        )
    for n in range(1, 4):
        assert changes.enqueue(server, link_id, signed_change(peer, n, server, link_id))
    assert not changes.enqueue(server, link_id, signed_change(peer, 4, server, link_id))
    assert changes.waiting(server.config.data_dir, link_id) == []
    with server.db.read(unscoped="test") as s:
        assert s.get(Link, link_id).needsFull
