"""The connector's core (requirements S18.1–S18.5): the vault and its words, the keys, signed
calls, sealed credentials, the egress allowlist, the socket's commands, and S18.1.2 (no
import from MoolaKata, each driver's size listed with its colour)."""

import ast
import inspect
import json
import re
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from moolakata_connector import client, keys, sealed, signing, sock, vault, words
from moolakata_connector.drivers import registry

PACKAGE = Path(__file__).resolve().parents[1] / "moolakata_connector"


def test_words_round_trip_and_catch_a_wrong_word():
    key = bytes(range(16))
    w = words.to_words(key)
    assert len(w) == 12 and words.from_words(" ".join(w)) == key
    assert words.from_words([x[:4] for x in w]) == key, "the first four letters are enough"
    with pytest.raises(words.PhraseError, match="not in the word list"):
        words.from_words([*w[:-1], "zzzz"])
    with pytest.raises(words.PhraseError, match="check out"):
        words.from_words([*w[:-1], words.wordlist()[(words.wordlist().index(w[-1]) + 1) % 2048]])


def test_the_vault_opens_only_with_its_words_and_waits_after_five_wrong(tmp_path, monkeypatch):
    v = vault.Vault(tmp_path / "vault.json")
    phrase = " ".join(v.create())
    fp = v.fingerprint()
    v.put("Conn_1", {"username": "alice", "password": "pw"})
    v.lock()
    assert v.locked
    with pytest.raises(vault.VaultError, match="locked"):
        v.get("Conn_1")
    other = " ".join(words.to_words(b"\x01" * 16))
    with pytest.raises(vault.VaultError, match="not this vault's"):
        v.unlock(other)
    with pytest.raises(vault.VaultError, match="12 words"):
        v.unlock("just three words")
    v.unlock(phrase)
    assert v.get("Conn_1") == {"username": "alice", "password": "pw"} and v.ids() == ["Conn_1"]
    v.delete("Conn_1")
    assert v.ids() == []
    assert fp == v.fingerprint() and len(fp) == 16
    # The file holds no credential in clear.
    v.put("Conn_2", {"password": "hunter2-secret"})
    assert "hunter2" not in (tmp_path / "vault.json").read_text()
    # Five wrong in a row: the next waits 15 minutes.
    v.lock()
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    for _ in range(5):
        with pytest.raises(vault.VaultError):
            v.unlock(other)
    with pytest.raises(vault.VaultError, match="wait"):
        v.unlock(phrase)
    now[0] += 15 * 60 + 1
    v.unlock(phrase)
    assert not v.locked
    # Reset: a new vault, new words, the old credentials gone.
    new = " ".join(v.reset())
    assert new != phrase and v.ids() == []


def test_keys_are_made_at_pairing_the_sealing_key_in_the_vault_and_forgotten(tmp_path):
    assert keys.load(tmp_path / "pairing.json") is None
    private, public = keys.new_sealing_key()
    p = keys.make("https://money.lan", "f" * 64, public)
    assert keys.load(tmp_path / "pairing.json") is None, "nothing written until it is taken"
    keys.save(tmp_path / "pairing.json", p)
    assert not (tmp_path / "pairing.json.tmp").exists()
    again = keys.load(tmp_path / "pairing.json")
    assert again.identity_public == p.identity_public and again.address == "https://money.lan"
    assert again.sealing_public == public
    assert keys.short(p.fingerprint).count(" ") == 3
    # The pairing file holds the public half only (S18.4.5): nothing in it opens a box.
    text = (tmp_path / "pairing.json").read_text()
    assert keys.b64(private) not in text and "sealingPublic" in text and '"sealing"' not in text
    v = vault.Vault(tmp_path / "vault.json")
    v.create()
    assert v.sealing_key() is None
    v.keep_sealing_key(private)
    assert v.sealing_key() == private and private.hex() not in (tmp_path / "vault.json").read_text()
    keys.forget(tmp_path / "pairing.json")
    assert keys.load(tmp_path / "pairing.json") is None


def test_credentials_are_bound_to_the_host_they_were_filed_for(tmp_path):
    v = vault.Vault(tmp_path / "vault.json")
    v.create()
    v.put("Conn_1", {"username": "alice", "password": "pw"}, "ofx.cu.example")
    v.put("Conn_2", {"appSecret": "s"})
    assert v.host("Conn_1") == "ofx.cu.example" and v.host("Conn_2") is None
    assert v.get("Conn_1") == {"username": "alice", "password": "pw"} and v.host("Conn_9") is None


def test_signed_calls_and_checked_answers():
    k = Ed25519PrivateKey.generate()
    headers, nonce = signing.sign(k, "POST", "/connector/v1/report", b"{}", "a" * 64)
    assert set(headers) == {"MK-Conn-Key", "MK-Conn-Time", "MK-Conn-Nonce", "MK-Conn-Signature"}
    msg = "\n".join(
        [
            "MK-CONN-1",
            "POST",
            "/connector/v1/report",
            signing.body_hash(b"{}"),
            headers["MK-Conn-Time"],
            nonce,
            "a" * 64,
        ]
    ).encode()
    k.public_key().verify(keys.unb64(headers["MK-Conn-Signature"]), msg)
    server = Ed25519PrivateKey.generate()
    t = str(int(time.time()))
    me, call = "c" * 64, signing.body_hash(b"{}")
    answer = "\n".join(
        ["MK-CONN-1-ANSWER", "200", signing.body_hash(b"ok"), t, nonce, me, call]
    ).encode()
    good = {"MK-Conn-Time": t, "MK-Conn-Signature": keys.b64(server.sign(answer))}
    pub = server.public_key().public_bytes_raw()
    signing.verify_answer(pub, 200, b"ok", nonce, good, me, call)
    with pytest.raises(signing.Refused, match="isn't signed by the server"):
        signing.verify_answer(
            Ed25519PrivateKey.generate().public_key().public_bytes_raw(),
            200,
            b"ok",
            nonce,
            good,
            me,
            call,
        )
    # An answer to another caller, or to another request, is refused (protocol §3.3).
    for who, what in (("d" * 64, call), (me, signing.body_hash(b'{"x":1}'))):
        with pytest.raises(signing.Refused, match="isn't signed by the server"):
            signing.verify_answer(pub, 200, b"ok", nonce, good, who, what)
    with pytest.raises(signing.Refused, match="wasn't signed"):
        signing.verify_answer(pub, 200, b"ok", nonce, {}, me, call)


def test_a_box_sealed_to_the_sealing_key_opens_for_its_connection_only():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    sealing = X25519PrivateKey.generate()
    once = X25519PrivateKey.generate()
    shared = once.exchange(
        X25519PublicKey.from_public_bytes(sealing.public_key().public_bytes_raw())
    )
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"Conn_9", info=sealed.LABEL).derive(
        shared
    )
    nonce = b"\x02" * 12
    box = keys.b64(
        once.public_key().public_bytes_raw()
        + nonce
        + AESGCM(key).encrypt(nonce, b'{"password": "pw"}', None)
    )
    assert sealed.open_box(box, sealing, "Conn_9") == {"password": "pw"}
    with pytest.raises(Exception):  # noqa: B017 - another Connection: another key
        sealed.open_box(box, sealing, "Conn_8")


def test_the_egress_allowlist_refuses_every_other_host():
    e = client.Egress()
    e.allow("money.lan", "api.schwabapi.com")
    e.check("MONEY.lan")
    with pytest.raises(client.EgressRefused):
        e.check("evil.example")
    t = client.Transport(e)
    with pytest.raises(client.EgressRefused):
        t.request("GET", "https://evil.example/x", {}, b"")


def test_every_driver_declares_its_hosts_and_needs():
    for name, d in registry().items():
        assert d.name == name
        assert isinstance(d.hosts, tuple) and isinstance(d.needs, tuple)
        assert d.interval >= 60


def _code_lines(path: Path) -> int:
    """Lines of code: not blank, not a comment, not a docstring."""
    text = path.read_text()
    tree = ast.parse(text)
    doc_lines = set()
    for node in ast.walk(tree):
        kinds = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        first = node.body[0] if isinstance(node, kinds) and node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            doc_lines |= set(range(first.lineno, first.end_lineno + 1))
    return sum(
        1
        for n, line in enumerate(text.splitlines(), 1)
        if line.strip() and not line.strip().startswith("#") and n not in doc_lines
    )


def _colour(lines: int) -> str:
    return "🟢" if lines < 1000 else "🟡" if lines < 2000 else "🔴"


def test_each_drivers_size_is_listed_with_its_colour_and_nothing_imports_moolakata():
    """S18.1.2: each driver's lines of code and colour as the connector protocol's table of
    drivers lists them (§6), whatever the size; no limit on the core; no import from
    MoolaKata."""
    doc = (PACKAGE.parents[1] / "docs" / "connector-protocol.md").read_text()
    table = doc.split("## 6. Drivers", 1)[1].split("\n## ", 1)[0]
    listed = dict(re.findall(r"^\| `([a-z-]+)` \|.*\| (\S+ [\d,]+) \|$", table, re.M))
    drivers = registry()
    for name, driver in drivers.items():
        lines = _code_lines(Path(inspect.getfile(type(driver))))
        size = f"{_colour(lines)} {lines:,}"
        assert listed.get(name) == size, f"connector-protocol.md §6: {name}'s size is {size}"
    assert set(listed) == set(drivers), "the table of drivers lists one that isn't a driver"
    for p in PACKAGE.rglob("*.py"):
        assert not re.search(r"^\s*(from|import)\s+moolakata\b", p.read_text(), re.M), p


def test_the_socket_commands_talk_to_the_running_connector(tmp_path):
    from moolakata_connector.core import ConnectionState, Core

    core = Core(tmp_path, transport=client.Transport(client.Egress()))
    phrase = " ".join(core.vault.create())
    core.vault.lock()
    path = tmp_path / "sock"
    sock.serve(core, path)
    assert sock.ask(path, {"command": "status"})["locked"] is True
    assert "error" in sock.ask(path, {"command": "unlock", "words": "bad words"})
    # Pairing needs the vault open: the sealing key goes into it.
    assert "unlock the vault first" in sock.ask(path, {"command": "pair", "code": "x"})["error"]
    assert sock.ask(path, {"command": "unlock", "words": phrase})["locked"] is False
    # Credentials typed here are filed for a Connection the connector knows, bound to the
    # host its settings name (S18.7.3); an unknown one is refused.
    out = sock.ask(path, {"command": "goes-to", "id": "Conn_1"})
    assert "hasn't heard of that Connection" in out["error"]
    core.connections["Conn_1"] = ConnectionState(
        "Conn_1", "ofx-direct", "CU", {"url": "https://ofx.cu.example/x"}, []
    )
    # The host is shown first, and the credentials filed only for the host confirmed (S18.7.2).
    where = sock.ask(path, {"command": "goes-to", "id": "Conn_1"})
    assert (where["label"], where["host"]) == ("CU", "ofx.cu.example")
    creds = {"command": "connect", "id": "Conn_1", "credentials": {"a": "b"}}
    assert "confirm the host first" in sock.ask(path, creds)["error"]
    assert "nothing filed" in sock.ask(path, {**creds, "host": "ofx.elsewhere.example"})["error"]
    assert core.vault.get("Conn_1") is None
    assert sock.ask(path, {**creds, "host": "ofx.cu.example"})["ok"]
    assert core.vault.get("Conn_1") == {"a": "b"} and core.vault.host("Conn_1") == "ofx.cu.example"
    assert sock.ask(path, {"command": "lock"})["locked"] is True
    # Reset (S18.3.4): the words come from the command line, never back over the socket;
    # the vault is made under them and the connector unpaired.
    from moolakata_connector import words
    from moolakata_connector.vault import fingerprint

    key = bytes(range(16))
    out = sock.ask(path, {"command": "reset", "words": " ".join(words.to_words(key))})
    assert out == {"ok": True, "fingerprint": fingerprint(key)}
    assert json.loads((tmp_path / "vault.json").read_text())["format"]
    assert core.vault.get("Conn_1") is None and core.pairing is None
    assert "error" in sock.ask(path, {"command": "reset", "words": "not twelve words"})
    assert "error" in sock.ask(path, {"command": "nothing"})


def test_a_changed_server_address_sends_nothing_and_asks_for_the_credentials_again(tmp_path):
    """S18.7.3: the host a credential was filed for is the only one it is ever sent to."""
    from moolakata_connector.core import ConnectionState, Core
    from moolakata_connector.drivers.ofx_direct import OfxDirect

    sent = []

    class Watching(client.Transport):
        def request(self, method, url, headers, body, pins=None):
            sent.append(url)
            return client.Answer(200, {}, b"<SONRS><CODE>0</SONRS><ACCTID>1204")

    core = Core(tmp_path, transport=Watching(client.Egress()), drivers={"ofx-direct": OfxDirect()})
    core.vault.create()
    c = core.connections["Conn_1"] = ConnectionState(
        "Conn_1", "ofx-direct", "CU", {"url": "https://ofx.cu.example/ofx", "accountId": "1204"}, []
    )
    core.vault.put("Conn_1", {"username": "alice", "password": "pw"}, "ofx.cu.example")
    core._run(c)
    assert sent == ["https://ofx.cu.example/ofx"] and c.state == "ok"
    # MoolaKata's next answer names another server: the password never goes there.
    c.settings = {**c.settings, "url": "https://evil.example/ofx"}
    core._run(c)
    assert sent == ["https://ofx.cu.example/ofx"]
    assert c.state == "needs-sign-in" and "changed from ofx.cu.example to evil.example" in c.message
    assert core.vault.get("Conn_1") is None, "the old credentials are gone with their binding"


def test_a_driver_run_reaches_its_own_hosts_and_no_other(tmp_path):
    # N17: each run is held to its driver's declared hosts; another driver's, or MoolaKata's,
    # is refused (S18.1.2).
    from urllib.parse import urlsplit

    from moolakata_connector.core import ConnectionState, Core
    from moolakata_connector.drivers import Driver, Result
    from moolakata_connector.drivers.schwab import Schwab

    asked = []

    class Checking(client.Transport):
        def request(self, method, url, headers, body, pins=None):
            host = urlsplit(url).hostname or ""
            self.egress.check(host)
            asked.append(host)
            return client.Answer(200, {}, b"{}")

    class Greedy(Driver):
        name = "greedy"
        label = "Greedy"
        hosts = ("own.example",)

        def run(self, settings, credentials, accounts, transport):
            transport.request("GET", "https://own.example/statement", {}, b"")
            transport.request("GET", settings["then"], {}, b"")
            return Result("ok", "")

    core = Core(
        tmp_path,
        transport=Checking(client.Egress()),
        drivers={"greedy": Greedy(), "schwab": Schwab()},
    )
    core.egress.allow("money.lan")
    core.vault.create()
    for then in ("https://api.schwabapi.com/x", "https://money.lan/connector/v1/files"):
        c = ConnectionState("Conn_1", "greedy", "Own", {"then": then}, [])
        core._run(c)
        assert c.state == "failing" and "refused" in c.message, c.message
    assert asked == ["own.example", "own.example"]
    for d in core.drivers.values():
        own = client.Egress()
        own.allow(*d.hosts_for({}))
        for other in core.drivers.values():
            for host in set(other.hosts) - set(d.hosts):
                with pytest.raises(client.EgressRefused):
                    own.check(host)


def test_moolakata_down_at_start_is_waited_for_with_a_growing_wait(tmp_path):
    # B30: the connector starts, its socket can open and it can be unlocked, while MoolaKata
    # is down; each failed try waits longer, up to the report's five minutes.
    from moolakata_connector import core as core_mod
    from moolakata_connector.core import Core

    class Down(client.Transport):
        def request(self, method, url, headers, body, pins=None):
            raise ConnectionRefusedError("refused")

    data = tmp_path / "data"
    data.mkdir()
    _, public = keys.new_sealing_key()
    keys.save(data / "pairing.json", keys.make("https://money.lan", "f" * 64, public))
    core = Core(data, transport=Down(client.Egress()))  # no hello yet: nothing raised
    assert core.pairing is not None and core.server is None
    with pytest.raises(client.ServerError) as e:
        core.tick()
    assert e.value.code == "server-unreachable"
    waits = []
    for _ in range(7):
        try:
            core.tick()
        except Exception:
            core.retry = min(max(core.retry * 2, core_mod.RETRY_FIRST), core_mod.REPORT_SECONDS)
        waits.append(core.next_wait())
    assert waits == [15, 30, 60, 120, 240, 300, 300]
    assert core.status()["reachable"] is False


def test_a_waiting_sign_in_is_reported_every_15_seconds_for_10_minutes(tmp_path):
    # 11b: so an address pasted back is exchanged at once (S18.5).
    import time

    from moolakata_connector.core import ConnectionState, Core

    core = Core(tmp_path, transport=client.Transport(client.Egress()))
    assert core.next_wait() == 300
    c = core.connections["Conn_1"] = ConnectionState("Conn_1", "schwab", "Schwab", {}, [])
    c.sign_in, c.sign_in_at = "https://api.schwabapi.com/v1/oauth/authorize", time.time()
    assert core.next_wait() == 15
    c.sign_in_at = time.time() - 601
    assert core.next_wait() == 300


def test_init_and_reset_show_the_words_on_the_terminal_only(tmp_path, monkeypatch, capsys):
    # The words go to the terminal, never standard output, so no log keeps them (S18.3.1).
    import re

    from moolakata_connector import main

    shown = []

    def typed_back():
        sheet = next(x for x in reversed(shown) if "vault words" in x)
        return {int(n): w for n, w in re.findall(r"^\s*(\d+)\. (\w+)$", sheet, re.M)}

    class Tty:
        def say(self, text=""):
            shown.append(text)

        def ask(self, prompt):
            if prompt.startswith("word "):
                return typed_back()[int(prompt.split()[1].rstrip(":"))] + "\n"
            return "RESET\n"

    monkeypatch.setattr(main, "DATA", tmp_path)
    assert main.cmd_init(None, tty=Tty()) == 0
    out = capsys.readouterr().out
    phrase = list(typed_back().values())
    assert len(phrase) == 12 and "Made " in out
    assert not any(w in out.split() for w in phrase), "stdout names the vault, never a word"


ON_A_TERMINAL = """
import os, sys
os.close(os.open(os.ttyname(0), os.O_RDWR))  # the pty becomes this session's terminal
from moolakata_connector.main import Terminal
t = Terminal()
t.say("the words")
sys.stdout.write(t.ask("word 3: ").strip() + "\\n")
"""


def test_the_terminal_opens_on_a_real_one():
    """`init` and `reset` reach the words' terminal on a real one: a terminal can't seek, so
    it is opened as getpass opens it, never as a file to read and write."""
    import os
    import pty
    import select
    import subprocess
    import sys

    leader, follower = pty.openpty()
    child = subprocess.Popen(  # noqa: S603 - this interpreter, on the test's own code
        [sys.executable, "-c", ON_A_TERMINAL],
        stdin=follower,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env={**os.environ, "PYTHONPATH": str(PACKAGE.parent)},
    )
    os.close(follower)
    shown = b""
    deadline = time.monotonic() + 30
    while b"word 3: " not in shown:
        ready, _, _ = select.select([leader], [], [], max(0, deadline - time.monotonic()))
        assert ready, f"no prompt on the terminal: {shown!r}"
        try:
            chunk = os.read(leader, 1024)
        except OSError:  # the terminal closed: the command ended before it asked
            chunk = b""
        if not chunk:
            child.wait(timeout=30)
            pytest.fail(f"it ended before it asked: {child.stderr.read().decode()}")
        shown += chunk
    os.write(leader, b"abandon\n")
    out, err = child.communicate(timeout=30)
    os.close(leader)
    assert child.returncode == 0, err.decode()
    assert b"the words" in shown
    assert out == b"abandon\n", "the answer came back from the terminal, and only it"


def test_an_address_the_connector_never_calls_is_refused(monkeypatch):
    # K24: loopback, link-local (cloud metadata) and multicast, as MoolaKata's guard (S13.5).
    import socket as socket_mod

    def resolving(ip):
        return lambda *a, **k: [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 6, "", (ip, 443))]

    for ip in ("169.254.169.254", "127.0.0.1", "224.0.0.1", "0.0.0.0"):  # noqa: S104
        monkeypatch.setattr(socket_mod, "getaddrinfo", resolving(ip))
        with pytest.raises(client.EgressRefused):
            client.vetted("api.example", 443)
    monkeypatch.setattr(socket_mod, "getaddrinfo", resolving("192.168.1.20"))
    assert client.vetted("money.lan", 443) == "192.168.1.20", "a household's own server is fine"


def test_a_signed_not_paired_forgets_the_credentials_and_the_sealing_key(tmp_path):
    # K20: MoolaKata unpaired after a lost host; the connector keeps nothing for it (S18.4.4).
    from moolakata_connector.core import Core

    class Gone:
        def call(self, path, data=None, **kw):
            raise client.ServerError("not-paired", "This server has no pairing with you.")

    data = tmp_path / "data"
    data.mkdir()
    _, public = keys.new_sealing_key()
    keys.save(data / "pairing.json", keys.make("https://money.lan", "f" * 64, public))
    core = Core(data, transport=client.Transport(client.Egress()))
    core.vault.create()
    core.vault.keep_sealing_key(b"\x07" * 32)
    core.vault.put("Conn_1", {"password": "pw"}, "ofx.cu.example")
    core.server = Gone()
    with pytest.raises(client.ServerError):
        core.tick()
    assert core.vault.ids() == [] and core.vault.sealing_key() is None
    assert core.pairing is None and not (data / "pairing.json").exists()


def test_a_box_older_than_the_credential_held_is_refused(tmp_path):
    # K24: the time sealed into each box; an older one handed over again changes nothing.
    import json as json_mod

    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from moolakata_connector.core import ConnectionState, Core

    taken = []

    class Server:
        def call(self, path, data=None, **kw):
            taken.append((path, data))
            return {}

    core = Core(tmp_path, transport=client.Transport(client.Egress()))
    core.vault.create()
    private = X25519PrivateKey.generate()
    core.vault.keep_sealing_key(private.private_bytes_raw())
    core.server = Server()
    c = core.connections["Conn_1"] = ConnectionState("Conn_1", "schwab", "Schwab", {}, [])
    public = private.public_key().public_bytes_raw()

    def box(at, host=None):
        sent = {"credentials": {"appSecret": f"s{at}"}, "host": host, "sealedAt": at}
        return _seal(json_mod.dumps(sent).encode(), public, "Conn_1")

    core._collect(c, box(2000), "t2")
    assert core.vault.get("Conn_1") == {"appSecret": "s2000"} and taken[-1][1] == {"sealedAt": "t2"}
    core._collect(c, box(1000), "t1")
    assert core.vault.get("Conn_1") == {"appSecret": "s2000"} and "older" in c.message
    core._collect(c, box(3000, host="evil.example"), "t3")
    assert core.vault.get("Conn_1") == {"appSecret": "s2000"} and "another server" in c.message
    assert len(taken) == 1, "MoolaKata isn't told a refused box was taken"


def _seal(plain: bytes, public: bytes, connection_id: str) -> str:
    """A sealed box as a browser makes one (docs/connector-protocol.md §4.3)."""
    import os

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    once = X25519PrivateKey.generate()
    shared = once.exchange(X25519PublicKey.from_public_bytes(public))
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=connection_id.encode(),
        info=b"moolakata connector credential",
    ).derive(shared)
    nonce = os.urandom(12)
    out = once.public_key().public_bytes_raw() + nonce + AESGCM(key).encrypt(nonce, plain, None)
    return keys.b64(out)


def test_pair_shows_the_fingerprint_it_works_out_and_refuses_an_answer_naming_another(
    tmp_path, monkeypatch
):
    # CR3-326: the two sides' fingerprints are two workings; the connector never shows the
    # one MoolaKata's answer names (S18.4.2).
    from moolakata_connector import core as core_mod
    from moolakata_connector.core import Core

    server = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    code = "mkp1." + keys.b64(
        json.dumps({"a": "https://money.lan", "f": keys.fingerprint(server), "c": "s"}).encode()
    )
    named = {}

    def answered(self, path, data=None, **kw):
        own = keys.fingerprint(self.pairing.identity_public)
        return {"connectorFingerprint": named["fp"] or own}

    monkeypatch.setattr(core_mod.client, "hello", lambda *a, **k: {"key": keys.b64(server)})
    monkeypatch.setattr(core_mod.client.Server, "call", answered)
    core = Core(tmp_path, transport=client.Transport(client.Egress()))
    core.vault.create()
    named["fp"] = "0" * 64
    with pytest.raises(client.ServerError, match="another connector's key"):
        core.pair(code)
    assert core.pairing is None and not (tmp_path / "pairing.json").exists()
    named["fp"] = None
    shown = core.pair(code)
    assert shown == keys.short(core.pairing.fingerprint)


def test_status_answers_while_a_round_holds_the_loop(tmp_path):
    # CR3-329: a run or a post may take minutes; `status`, the health check and the page
    # answer at once all the same (S18.3.2).
    import threading

    from moolakata_connector.core import ConnectionState, Core

    core = Core(tmp_path, transport=client.Transport(client.Egress()))
    core.vault.create()
    core.connections["Conn_1"] = ConnectionState("Conn_1", "schwab", "Schwab", {}, [], "ok")
    held, done = threading.Event(), threading.Event()

    def a_long_round():
        with core._lock:
            held.set()
            done.wait(10)

    t = threading.Thread(target=a_long_round)
    t.start()
    held.wait(5)
    answered = []
    asker = threading.Thread(target=lambda: answered.append(core.status()))
    asker.start()
    asker.join(2)
    done.set()
    t.join()
    assert answered, "status waited for the round"
    assert answered[0]["connections"]["Conn_1"]["state"] == "ok"


def _tls_server(tmp_path, answer):
    """A local HTTPS server on its own certificate, answering each connection with `answer`
    (a function of the socket); returns its port and the certificate key's pin."""
    import contextlib
    import socket as socket_mod
    import ssl
    import threading

    from cryptography import x509 as x509_mod
    from cryptography.hazmat.primitives.serialization import Encoding
    from moolakata_connector import page

    tmp_path.mkdir(parents=True)
    cert, key = page.certificate(tmp_path, page.Settings(names=("127.0.0.1",)))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    listener = socket_mod.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)

    def serve():
        while True:
            try:
                raw, _ = listener.accept()
            except OSError:
                return
            with ctx.wrap_socket(raw, server_side=True) as s:
                s.recv(65536)
                with contextlib.suppress(OSError):
                    answer(s)

    threading.Thread(target=serve, daemon=True).start()
    der = x509_mod.load_pem_x509_certificate(cert.read_bytes()).public_bytes(Encoding.DER)
    return listener, client.key_fingerprint(der)


def test_a_call_ends_at_its_deadline_however_slowly_the_answer_trickles(tmp_path, monkeypatch):
    # CR3-330: the 60 seconds bound the whole call, not each read (S18.2.2).
    monkeypatch.setattr(client, "LOOPBACK_OK", True)
    monkeypatch.setattr(client, "DEADLINE", 1.5)

    def trickle(s):
        s.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n")
        for _ in range(100):
            s.sendall(b"x")
            time.sleep(0.4)  # each read waits less than the socket's timeout

    def prompt(s):
        s.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

    for answer, ok in ((prompt, True), (trickle, False)):
        listener, pin = _tls_server(tmp_path / answer.__name__, answer)
        port = listener.getsockname()[1]
        e = client.Egress()
        e.allow("127.0.0.1")
        start = time.monotonic()
        try:
            if ok:
                r = client.Transport(e).request(
                    "GET", f"https://127.0.0.1:{port}/", {}, b"", pins=frozenset([pin])
                )
                assert r.body == b"ok"
            else:
                with pytest.raises(TimeoutError, match=r"longer than 1\.5 seconds"):
                    client.Transport(e).request(
                        "GET", f"https://127.0.0.1:{port}/", {}, b"", pins=frozenset([pin])
                    )
                assert time.monotonic() - start < 5
        finally:
            listener.close()
