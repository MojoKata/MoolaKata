"""A new server's welcome (requirements S12.14.1, S15.4.4, S10.1.2): with no keyring it starts
uninitialised and answers only what the welcome needs; every visit shows a new phrase, none
written until three of its words are typed back; then the key is made, the server unlocks,
and the first admin is set up and signed in, once. Verify key (S15.6.5) and the image's
health check, which counts any answer as alive (S13.6), are here too, and so is a database
whose keyring is gone, which refuses the start rather than getting a new key (S15.4.5)."""

import json

import pytest
from conftest import ADMIN_PW, LOOPBACK, ORIGIN, make_user, new_client
from fastapi.testclient import TestClient

from moolakata.app import Server, create_app
from moolakata.keys import master, phrase
from moolakata.store.entities.core import Activity


@pytest.fixture
def new_server(config):
    """A server on a data directory with no keyring, as the image starts on a new host."""
    srv = Server(config=config)
    with TestClient(
        create_app(srv), base_url=ORIGIN, headers={"Origin": ORIGIN}, client=LOOPBACK
    ) as c:
        yield srv, c
    if srv.store is not None:
        srv.tasks.stop()
        srv.reader.stop()
        srv.db.dispose()


def _offer(c) -> dict:
    r = c.post("/ui/api/welcome/phrase")
    assert r.status_code == 200, r.text
    return r.json()


def _typed_back(offer: dict, upper=False) -> dict:
    """The three words asked for, as a person types them: four letters are enough."""
    out = {str(n): offer["words"][n - 1][:4] for n in offer["check"]}
    return {k: v.upper() for k, v in out.items()} if upper else out


def test_a_new_server_is_uninitialised_and_answers_only_the_welcome(new_server):
    _, c = new_server
    r = c.get("/healthz")
    assert r.status_code == 503 and r.json()["status"] == "uninitialised"
    for path in ("/ui/api/session", "/mcp", "/link/v1/hello", "/connector/v1/hello"):
        assert c.get(path).status_code == 503, path
    assert c.get("/ui/").status_code == 200
    state = c.get("/ui/api/unlock").json()
    assert state["uninitialised"] is True and state["locked"] is True
    assert state["fingerprint"] is None and state["needsAdmin"] is False


def test_every_visit_shows_a_new_phrase_and_none_is_written(new_server):
    srv, c = new_server
    a, b = _offer(c), _offer(c)
    assert a["token"] != b["token"] and a["words"] != b["words"]
    assert a["fingerprint"] != b["fingerprint"] and a["fingerprint"].startswith("mk-")
    for offer in (a, b):
        assert len(offer["words"]) == 12 and offer["serverName"] == "test"
        assert len(set(offer["check"])) == 3 and all(1 <= n <= 12 for n in offer["check"])
        assert offer["check"] == sorted(offer["check"])
        assert phrase.from_words(offer["words"])  # a real phrase, its checksum and all
    assert not srv.config.keyring_path.exists()


def test_three_words_back_make_the_key_and_unlock(new_server):
    srv, c = new_server
    other, offer = _offer(c), _offer(c)
    r = c.post("/ui/api/welcome/key", json={"token": "no such token", "words": {}})
    assert r.status_code == 410 and r.json()["code"] == "phrase-gone"
    wrong = {str(n): "zoo" for n in offer["check"]}
    r = c.post("/ui/api/welcome/key", json={"token": offer["token"], "words": wrong})
    assert r.status_code == 422 and r.json()["code"] == "words-wrong"
    assert {e["field"] for e in r.json()["errors"]} == {f"word{n}" for n in offer["check"]}
    assert not srv.config.keyring_path.exists()

    r = c.post(
        "/ui/api/welcome/key",
        json={"token": offer["token"], "words": _typed_back(offer, upper=True)},
    )
    assert r.status_code == 200, r.text
    assert srv.config.keyring_path.exists() and srv.store is not None and srv.ready
    assert (
        master.fingerprint(master.read_keyring(srv.config.keyring_path).master_id)
        == offer["fingerprint"]
    )
    state = c.get("/ui/api/unlock").json()
    assert state["locked"] is False and state["uninitialised"] is False
    assert state["needsAdmin"] is True
    assert c.get("/healthz").status_code == 200
    # The other visitor's phrase went with it, and no new one is offered.
    r = c.post("/ui/api/welcome/key", json={"token": other["token"], "words": _typed_back(other)})
    assert r.status_code == 409 and r.json()["code"] == "initialised"
    assert c.post("/ui/api/welcome/phrase").status_code == 409
    with srv.db.read() as s:
        made = s.query(Activity).filter(Activity.kind == "key.made-welcome").one()
    assert json.loads(made.detail)["fingerprint"] == offer["fingerprint"]


def test_the_first_admin_is_set_up_once_and_signed_in(new_server):
    srv, c = new_server
    offer = _offer(c)
    c.post("/ui/api/welcome/key", json={"token": offer["token"], "words": _typed_back(offer)})
    first = {"displayName": "Pat Tester", "sex": "female", "email": "Pat@Home.lan"}
    for bad, code in (
        ({**first, "password": "short"}, "password-too-short"),
        ({**first, "displayName": " ", "password": ADMIN_PW}, "name-invalid"),
        ({**first, "sex": "other", "password": ADMIN_PW}, "sex-invalid"),
        ({**first, "email": "nope", "password": ADMIN_PW}, "email-invalid"),
    ):
        r = c.post("/ui/api/welcome/admin", json=bad)
        assert r.status_code == 422 and r.json()["code"] == code, bad
    r = c.post("/ui/api/welcome/admin", json={**first, "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    me = r.json()["user"]
    assert me["username"] == "admin" and me["admin"] is True and me["needsSetup"] is False
    assert me["email"] == "pat@home.lan" and me["displayName"] == "Pat Tester"
    assert c.get("/ui/api/session").status_code == 200  # signed in by the cookie it set
    assert c.get("/ui/api/unlock").json()["needsAdmin"] is False
    r = c.post("/ui/api/welcome/admin", json={**first, "password": ADMIN_PW})
    assert r.status_code == 409 and r.json()["code"] == "admin-exists"
    with new_client(srv) as other:
        r = other.post("/ui/api/session", json={"login": "admin", "password": ADMIN_PW})
        assert r.status_code == 200


def test_a_key_made_meanwhile_turns_the_welcome_into_the_locked_screen(new_server):
    """Another browser's welcome made the key first: this one's is refused."""
    import os

    srv, c = new_server
    offer = _offer(c)
    key = os.urandom(16)
    master.create_keyring(srv.config, key)
    state = c.get("/ui/api/unlock").json()
    assert state["uninitialised"] is False and state["locked"] is True
    assert state["fingerprint"] == master.fingerprint(key)
    assert c.get("/healthz").json()["status"] == "locked"
    r = c.post("/ui/api/welcome/key", json={"token": offer["token"], "words": _typed_back(offer)})
    assert r.status_code == 409 and r.json()["code"] == "initialised"
    r = c.post("/ui/api/unlock", json={"phrase": " ".join(phrase.to_words(key))})
    assert r.status_code == 200 and c.get("/ui/api/unlock").json()["needsAdmin"] is True


def test_a_database_without_its_keyring_refuses_the_start_and_a_new_key(config, tmp_path, capsys):
    """A household starting a claimed server over empties its data directory: with the
    keyring alone removed, a new key would not open the database left behind (S15.4.5)."""
    from moolakata import main
    from moolakata.config import RefuseStart

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.db_path.write_bytes(b"a database made under a key nobody wrote down")
    toml = tmp_path / "moolakata.toml"
    toml.write_text(
        f'[server]\nmode = "proxy"\n[paths]\ndata = "{config.data_dir}"\n'
        f'backups = "{config.backup_dir}"\n'
    )
    assert main.main(["--config", str(toml), "serve"]) == 78
    said = capsys.readouterr().err.strip().splitlines()[-1]
    assert said.startswith("refusing to start: ") and "has no keyring beside it" in said
    assert "db restore" in said and str(config.data_dir) in said
    with pytest.raises(RefuseStart, match="has no keyring beside it"):
        master.create_keyring(config, bytes(16))
    assert not config.keyring_path.exists()


def test_verify_key_checks_a_copy_of_the_phrase_and_changes_nothing(
    admin_client, server, master_key
):
    import os

    ring_before = server.config.keyring_path.read_bytes()
    r = admin_client.post("/ui/api/settings/keys/verify", json={"phrase": "not a phrase"})
    assert r.status_code == 422 and r.json()["code"] == "phrase-invalid"
    other = " ".join(phrase.to_words(os.urandom(16)))
    r = admin_client.post("/ui/api/settings/keys/verify", json={"phrase": other})
    assert r.status_code == 403 and r.json()["code"] == "phrase-wrong"
    words = " ".join(w[:4] for w in phrase.to_words(master_key))
    r = admin_client.post("/ui/api/settings/keys/verify", json={"phrase": words})
    assert r.status_code == 200, r.text
    assert r.json()["fingerprint"] == master.fingerprint(master_key)
    assert server.config.keyring_path.read_bytes() == ring_before
    confirmations = admin_client.get("/ui/api/settings/keys").json()["confirmations"]
    assert [(x["how"], x["matched"]) for x in confirmations[:2]] == [("app", True), ("app", False)]

    make_user(server, "bob")
    with new_client(server) as bob:
        bob.post("/ui/api/session", json={"login": "bob", "password": "a long user passphrase"})
        r = bob.post("/ui/api/settings/keys/verify", json={"phrase": words})
        assert r.status_code == 403


def test_the_health_check_counts_any_answer_as_alive(config, monkeypatch, capsys, tmp_path):
    """The image's check passes while the server answers at all, locked or uninitialised
    included (S13.6); nothing answering, or something else answering, fails it."""
    import argparse

    import httpx

    from moolakata import main

    toml = tmp_path / "moolakata.toml"
    toml.write_text(
        f'[server]\nmode = "proxy"\n[paths]\ndata = "{config.data_dir}"\n'
        f'backups = "{config.backup_dir}"\n'
    )
    args = argparse.Namespace(config=str(toml))
    for code, body, alive in (
        (200, {"status": "ok"}, True),
        (503, {"status": "locked"}, True),
        (503, {"status": "uninitialised"}, True),
        (502, None, False),
    ):
        answer = httpx.Response(code, json=body) if body else httpx.Response(code, text="bad")
        monkeypatch.setattr(httpx, "get", lambda *a, answer=answer, **k: answer)
        assert (main.cmd_health(args) == 0) is alive, (code, body)

    def refused(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", refused)
    assert main.cmd_health(args) == 1
