"""The connector's page (requirements S18.11): its welcome makes the vault from words typed
back; anyone sees its status, which names no institution, Connection or account; every action
takes the words, wrong ones logged with their address and counted; forms come only from the
page itself; and its certificate names the addresses browsers use. Driven over HTTPS against
its own certificate."""

import http.client
import logging
import re
import socket
import ssl
from urllib.parse import urlencode

import pytest
from cryptography import x509
from moolakata_connector import client, page, words
from moolakata_connector.client import ServerError
from moolakata_connector.core import ConnectionState, Core


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def running(tmp_path):
    data = tmp_path / "data"
    core = Core(data, transport=client.Transport(client.Egress()))
    settings = page.Settings(port=free_port(), names=("127.0.0.1",))
    server = page.serve(core, settings, data)
    yield core, settings, data / "tls" / "cert.pem"
    server.shutdown()
    server.server_close()


def call(running, method, path, form=None, origin="same", headers=None):
    _, settings, cert = running
    c = http.client.HTTPSConnection(
        "127.0.0.1", settings.port, context=ssl.create_default_context(cafile=str(cert)), timeout=10
    )
    h = dict(headers or {})
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
    if origin == "same":
        h["Origin"] = f"https://127.0.0.1:{settings.port}"
    elif origin:
        h["Origin"] = origin
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    out = r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode()
    c.close()
    return out


def offered(text: str) -> tuple[str, list[str]]:
    token = re.search(r'name="token" value="([^"]+)"', text).group(1)
    shown = re.findall(
        r"<b>([a-z]+)</b>", text.split('class="words"', 1)[1].split("</div></div>")[0] + "</div>"
    )
    return token, shown


def make_vault(running) -> str:
    """The welcome, as a person goes through it: the words, three of them typed back."""
    status, _, text = call(running, "POST", "/welcome", {})
    token, shown = offered(text)
    status, _, text = call(running, "POST", "/welcome/check", {"token": token})
    picks = [int(n) for n in re.findall(r'name="word(\d+)"', text)]
    form = {"token": token, **{f"word{n}": shown[n - 1][:4].upper() for n in picks}}
    status, headers, _ = call(running, "POST", "/welcome/vault", form)
    assert status == 303 and headers["location"] == "/"
    return " ".join(shown)


def test_the_welcome_makes_the_vault_from_three_words_typed_back(running):
    core, _, _ = running
    status, headers, text = call(running, "GET", "/")
    assert status == 200 and "Welcome to MoolaKata Connector" in text
    assert "default-src 'none'" in headers["content-security-policy"]
    assert headers["cache-control"] == "no-store" and headers["x-frame-options"] == "DENY"
    assert "<script" not in text
    _, _, a = call(running, "POST", "/welcome", {})
    _, _, b = call(running, "POST", "/welcome", {})
    (ta, wa), (tb, wb) = offered(a), offered(b)
    assert ta != tb and wa != wb and len(wa) == 12 and words.from_words(wa)
    assert not core.vault.exists()  # nothing written while words are only shown
    _, _, check = call(running, "POST", "/welcome/check", {"token": tb})
    picks = [int(n) for n in re.findall(r'name="word(\d+)"', check)]
    assert len(picks) == 3
    wrong = {"token": tb, **{f"word{n}": "zoo" for n in picks}}
    status, _, text = call(running, "POST", "/welcome/vault", wrong)
    assert status == 422 and "aren’t the words shown" in text and not core.vault.exists()
    status, _, text = call(running, "POST", "/welcome/words", {"token": tb})
    assert offered(text) == (tb, wb)  # Back shows the same words
    right = {"token": tb, **{f"word{n}": wb[n - 1] for n in picks}}
    status, headers, _ = call(running, "POST", "/welcome/vault", right)
    assert status == 303 and core.vault.exists() and not core.vault.locked
    assert core.vault.fingerprint() == page.fingerprint(words.from_words(wb))
    # Every other key on offer is dropped, and the welcome is gone.
    status, _, text = call(running, "POST", "/welcome/check", {"token": ta})
    assert status == 410
    status, _, text = call(running, "GET", "/")
    assert "Unlocked since" in text and "Welcome" not in text
    assert call(running, "GET", "/style.css")[1]["content-type"].startswith("text/css")


def test_a_form_from_elsewhere_or_too_big_is_refused(running):
    make_vault(running)
    for origin in ("https://evil.example", None):
        status, _, _ = call(running, "POST", "/lock", {"words": "x"}, origin=origin)
        assert status == 403
    status, _, _ = call(
        running,
        "POST",
        "/lock",
        {"words": "x"},
        origin=None,
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert status == 403  # taken, then refused for its words
    status, _, text = call(
        running, "POST", "/lock", {"words": "x"}, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert status == 403 and "only from this page" in text  # the browser's word comes first
    status, _, _ = call(running, "POST", "/lock", {"words": "x" * 17000})
    assert status == 413
    assert call(running, "GET", "/nothing")[0] == 404


def test_every_action_takes_the_words_and_wrong_ones_are_logged(running, caplog):
    core, _, _ = running
    phrase = make_vault(running)
    caplog.set_level(logging.WARNING, logger="connector.page")
    status, _, text = call(running, "POST", "/lock", {"words": "abandon " * 11 + "about"})
    assert status == 403 and "not this vault" in text and not core.vault.locked
    assert "wrong words on its page from 127.0.0.1" in caplog.text
    # CR3-328: a slip in one of the real words is shown to the person typing, never logged.
    slipped = phrase.split()
    slipped[6] = slipped[6][:3] + "zq"
    status, _, text = call(running, "POST", "/lock", {"words": " ".join(slipped)})
    assert status == 403 and slipped[6] in text
    assert "not a valid phrase" in caplog.text and slipped[6] not in caplog.text
    for rec in caplog.records:  # the address and the kind, nothing typed
        assert re.fullmatch(
            r"wrong words on its page from 127\.0\.0\.1: (not a valid phrase|another vault's)",
            rec.getMessage(),
        ), rec.getMessage()
    status, _, _ = call(running, "POST", "/lock", {"words": phrase})
    assert status == 303 and core.vault.locked
    status, _, text = call(running, "GET", "/")
    assert "is locked" in text and 'action="/unlock"' in text and "Lock…" not in text
    status, _, text = call(running, "POST", "/unlock", {"words": "not the words"})
    assert status == 403 and core.vault.locked
    status, _, _ = call(running, "POST", "/unlock", {"words": phrase})
    assert status == 303 and not core.vault.locked
    # Reset: RESET typed, and the words, then new words as the welcome shows them.
    status, _, text = call(running, "POST", "/reset", {"words": phrase, "confirm": "reset"})
    assert status == 422 and "Type RESET" in text
    before = core.vault.fingerprint()
    status, _, text = call(running, "POST", "/reset", {"words": phrase, "confirm": "RESET"})
    token, shown = offered(text)
    assert core.vault.fingerprint() == before  # nothing replaced until three come back
    _, _, check = call(running, "POST", "/welcome/check", {"token": token})
    picks = [int(n) for n in re.findall(r'name="word(\d+)"', check)]
    call(
        running,
        "POST",
        "/welcome/vault",
        {"token": token, **{f"word{n}": shown[n - 1] for n in picks}},
    )
    assert core.vault.fingerprint() == page.fingerprint(words.from_words(shown)) != before
    # CR3-373: five tries a minute from one address on the page, and no wait for anyone else:
    # the host's unlock, over the socket, opens it at once (S18.3.3).
    phrase = " ".join(shown)
    page_ = running[0]
    assert call(running, "POST", "/lock", {"words": phrase})[0] == 303
    for _ in range(6):
        call(running, "POST", "/unlock", {"words": "abandon " * 11 + "about"})
    status, _, text = call(running, "POST", "/unlock", {"words": phrase})
    assert status == 403 and "Five wrong tries a minute" in text and core.vault.locked
    assert "words tried too often on its page from 127.0.0.1" in caplog.text
    from moolakata_connector import sock

    assert sock.handle(page_, {"command": "unlock", "words": phrase}) == {
        "ok": True,
        "locked": False,
    }


def test_pair_and_unpair_take_the_words(running, monkeypatch):
    core, _, _ = running
    phrase = make_vault(running)
    core.lock()
    monkeypatch.setattr(
        core,
        "pair",
        lambda code: (
            "c2f1 08aa 5e7d 91b3"
            if code == "mkp1.ok"
            else (_ for _ in ()).throw(ServerError("code-used", "That code was used."))
        ),
    )
    status, _, text = call(running, "POST", "/pair", {"code": "mkp1.ok", "words": "wrong"})
    assert status == 403 and core.vault.locked
    status, _, text = call(running, "POST", "/pair", {"code": "mkp1.used", "words": phrase})
    assert status == 422 and "That code was used." in text and not core.vault.locked
    status, _, text = call(running, "POST", "/pair", {"code": "mkp1.ok", "words": phrase})
    assert status == 200 and "c2f1 08aa 5e7d 91b3" in text and "Confirm" in text
    unpaired = []
    monkeypatch.setattr(core, "unpair", lambda: unpaired.append(True))
    assert call(running, "POST", "/unpair", {"words": "wrong"})[0] == 403 and not unpaired
    assert call(running, "POST", "/unpair", {"words": phrase})[0] == 303 and unpaired


def test_the_status_names_no_institution_connection_or_account(running, monkeypatch):
    core, _, _ = running
    make_vault(running)
    core.connections = {
        "Conn_1": ConnectionState("Conn_1", "schwab", "Alice’s Schwab login", {}, [], state="ok"),
        "Conn_2": ConnectionState(
            "Conn_2",
            "ofx-direct",
            "Credit union",
            {},
            [],
            state="failing",
            message="the institution refused the password",
        ),
        "Conn_3": ConnectionState("Conn_3", "ofx-direct", "Joint", {}, [], state="new"),
    }
    real = core.status
    monkeypatch.setattr(
        core,
        "status",
        lambda: {
            **real(),
            "paired": True,
            "server": "https://money.griffin.home",
            "fingerprint": "c2f1 08aa",
            "confirmed": True,
            "lastReport": None,
            "reachable": True,
        },
    )
    _, _, text = call(running, "GET", "/")
    assert "https://money.griffin.home" in text and "confirmed" in text
    assert "1 working, 1 needs attention, 1 starting" in text
    for private in ("Schwab", "Credit union", "Joint", "refused the password", "schwab", "ofx"):
        assert private not in text


def test_the_certificate_names_what_browsers_use_and_follows_them(tmp_path):
    first = page.Settings(names=("money.lan", "192.168.1.20"))
    cert, key = page.certificate(tmp_path, first)
    made = x509.load_pem_x509_certificate(cert.read_bytes())
    named = made.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert sorted(str(getattr(n, "value", n)) for n in named) == [
        "192.168.1.20",
        "localhost",
        "money.lan",
    ]
    assert oct(key.stat().st_mode & 0o777) == "0o600"
    again = cert.read_bytes()
    page.certificate(tmp_path, first)
    assert cert.read_bytes() == again  # the same names keep it
    page.certificate(tmp_path, page.Settings(names=("money.lan",)))
    assert cert.read_bytes() != again  # other names make it again
    # CR3-335: a key left from a remake cut short (written, its certificate not) doesn't match
    # the certificate kept: the next start makes the pair again rather than failing to serve.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    stray = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    key.write_bytes(stray)
    kept = cert.read_bytes()
    page.certificate(tmp_path, page.Settings(names=("money.lan",)))
    assert cert.read_bytes() != kept and key.read_bytes() != stray
    assert not list((tmp_path / "tls").glob("*.tmp"))
    import ssl

    ssl.create_default_context(ssl.Purpose.CLIENT_AUTH).load_cert_chain(cert, key)
    own = page.Settings(cert=tmp_path / "c.pem", key=tmp_path / "k.pem")
    assert page.certificate(tmp_path, own) == (tmp_path / "c.pem", tmp_path / "k.pem")


def test_its_settings_and_address_come_from_the_environment():
    s = page.Settings.from_env(
        {"MOOLAKATA_CONNECTOR_NAMES": " money.lan , fd00::7 ", "MOOLAKATA_CONNECTOR_PORT": "4443"}
    )
    assert s.names == ("money.lan", "fd00::7") and s.port == 4443
    assert s.address == "https://money.lan:4443"
    assert page.Settings(names=("fd00::7",)).address == "https://[fd00::7]:37374"
    assert page.Settings.from_env({}).address is None
    with pytest.raises(ValueError, match="go together"):
        page.Settings.from_env({"MOOLAKATA_CONNECTOR_TLS_CERT": "/c.pem"})


def _block(css: str, start: str) -> dict[str, str]:
    body = css.split(start, 1)[1].split("}", 1)[0]
    return dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", body))


def test_its_stylesheet_keeps_moolakatas_colours_and_type():
    """S18.11.5: the page reads as MoolaKata does, dark and light; a token changed on one side
    only fails here."""
    ours = page.STYLE.read_text()
    theirs = (page.STYLE.parents[2] / "web" / "ui" / "styles" / "tokens.css").read_text()
    dark, light = (
        _block(ours, ":root {"),
        _block(ours.split("prefers-color-scheme: light", 1)[1], ":root {"),
    )
    their_dark = _block(theirs, ":root {")
    their_light = {**their_dark, **_block(theirs, ":root[data-theme='light'] {")}
    assert dark and light
    assert dark == {k: their_dark[k] for k in dark}
    assert light == {k: their_light[k] for k in light}
    used = set(re.findall(r"var\(--([a-z0-9-]+)\)", ours))
    assert used <= set(dark), used - set(dark)
