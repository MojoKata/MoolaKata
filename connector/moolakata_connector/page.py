"""Its page (requirements S18.11): one small HTTPS page the connector serves itself, on a port
of its own, where its vault is made, its words given after a restart and its pairing done.
Plain forms the connector renders, no JavaScript. Anyone on the network sees its status;
every action takes the words, and wrong ones count toward the vault's wait (S18.3.3) and are
logged with the address they came from. MoolaKata only links here and never sees the words."""

import datetime as dt
import html
import ipaddress
import logging
import os
import secrets
import ssl
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from . import VERSION, words
from .client import ServerError
from .vault import VaultError, fingerprint

log = logging.getLogger("connector.page")

PORT = 37374
OFFER_SECONDS = 3600  # a welcome's words stay on offer an hour
OFFERS_KEPT = 20
BODY_LIMIT = 16 * 1024
CERT_DAYS = 825
STYLE = Path(__file__).with_name("page.css")
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; "
        "base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",  # no-referrer would make a browser's Origin "null"
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
}
WORKING = {"ok"}
ATTENTION = {"needs-sign-in", "failing"}


@dataclass(frozen=True)
class Settings:
    """Where the page listens and what its certificate names (S18.11.1), from the
    environment: MOOLAKATA_CONNECTOR_PORT, _NAMES, _TLS_CERT and _TLS_KEY."""

    port: int = PORT
    names: tuple[str, ...] = ()
    cert: Path | None = None
    key: Path | None = None

    @staticmethod
    def from_env(env=os.environ) -> Settings:
        names = tuple(n.strip() for n in env.get("MOOLAKATA_CONNECTOR_NAMES", "").split(","))
        cert, key = env.get("MOOLAKATA_CONNECTOR_TLS_CERT"), env.get("MOOLAKATA_CONNECTOR_TLS_KEY")
        if bool(cert) != bool(key):
            raise ValueError("MOOLAKATA_CONNECTOR_TLS_CERT and _TLS_KEY go together")
        return Settings(
            port=int(env.get("MOOLAKATA_CONNECTOR_PORT") or PORT),
            names=tuple(n for n in names if n),
            cert=Path(cert) if cert else None,
            key=Path(key) if key else None,
        )

    @property
    def address(self) -> str | None:
        """The page's address, for every report, so MoolaKata can link to it."""
        if not self.names:
            return None
        host = self.names[0]
        return f"https://{f'[{host}]' if ':' in host else host}:{self.port}"


# ---------- its certificate ----------


def certificate(data: Path, settings: Settings) -> tuple[Path, Path]:
    """The certificate the page serves: the one named to it, or its own, made at the first
    start and made again when the names change or it nears its end (S18.11.1)."""
    if settings.cert and settings.key:
        return settings.cert, settings.key
    folder = data / "tls"
    cert, key = folder / "cert.pem", folder / "key.pem"
    wanted = sorted({"localhost", *settings.names})
    if cert.exists() and key.exists():
        have = x509.load_pem_x509_certificate(cert.read_bytes())
        named = have.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if sorted(
            str(getattr(n, "value", n)) for n in named
        ) == wanted and have.not_valid_after_utc - dt.datetime.now(dt.UTC) > dt.timedelta(days=30):
            return cert, key
    folder.mkdir(mode=0o700, exist_ok=True)
    private = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MoolaKata Connector")])
    made = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=CERT_DAYS))
        .add_extension(x509.SubjectAlternativeName([_san(n) for n in wanted]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private, hashes.SHA256())
    )
    fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(
            private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    cert.write_bytes(made.public_bytes(serialization.Encoding.PEM))
    log.info("made the page's certificate for %s", ", ".join(wanted))
    return cert, key


def _san(name: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(name))
    except ValueError:
        return x509.DNSName(name)


# ---------- the words on offer ----------


@dataclass
class Offer:
    """A new key shown on the page, kept in memory only until three of its words come back
    (S18.11.2); `reset` when it replaces a vault (S18.3.4)."""

    key: bytes
    made: float
    picks: tuple[int, ...]
    reset: bool = False

    @property
    def words(self) -> list[str]:
        return words.to_words(self.key)


class Page:
    """What the page knows besides the core: the keys on offer."""

    def __init__(self, core, settings: Settings) -> None:
        self.core = core
        self.settings = settings
        self.offers: dict[str, Offer] = {}
        self._lock = threading.Lock()

    def offer(self, reset: bool = False) -> tuple[str, Offer]:
        with self._lock:
            now = time.time()
            for token in [t for t, o in self.offers.items() if now - o.made > OFFER_SECONDS]:
                del self.offers[token]
            while len(self.offers) >= OFFERS_KEPT:
                del self.offers[min(self.offers, key=lambda t: self.offers[t].made)]
            picks = tuple(sorted(secrets.SystemRandom().sample(range(12), 3)))
            token = secrets.token_urlsafe(18)
            self.offers[token] = Offer(secrets.token_bytes(16), now, picks, reset)
            return token, self.offers[token]

    def on_offer(self, token: str) -> Offer | None:
        with self._lock:
            o = self.offers.get(token)
            return o if o and time.time() - o.made <= OFFER_SECONDS else None

    def taken(self) -> None:
        with self._lock:
            self.offers.clear()


# ---------- rendering ----------


def e(text) -> str:
    return html.escape(str(text), quote=True)


def layout(page: Page, title: str, sub: str, body: str, host: str) -> str:
    shown = page.settings.names[0] if page.settings.names else host
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · MoolaKata Connector</title><link rel="stylesheet" href="/style.css">
</head><body><main class="auth"><div class="card">
<div class="acct-row"><div class="logo">C</div><div><b class="brand">MoolaKata Connector</b>
<div class="small dim">{e(shown)} · {e(VERSION)}</div></div></div>
<h2>{e(title)}</h2>{f'<p class="small dim">{sub}</p>' if sub else ""}{body}
</div></main></body></html>
"""


def words_field(label: str = "The vault’s words") -> str:
    return (
        f'<label class="field"><span>{e(label)}</span><input class="in" type="password" '
        'name="words" placeholder="twelve words, in order" autocomplete="off" '
        'autocapitalize="none" spellcheck="false" required><small>From the household’s '
        "password manager. Four letters of each are enough. Five wrong tries in a row make "
        "the next wait 15 minutes.</small></label>"
    )


def notice(message: str | None) -> str:
    return f'<div class="notice bad" role="alert">{e(message)}</div>' if message else ""


def _ago(t: float | None) -> str:
    if not t:
        return "never"
    s = time.time() - t
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    return f"{int(s // 86400)} days ago"


def _when(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%b %-d, %H:%M")


def status_rows(st: dict) -> str:
    """What anyone may see (S18.11.3): never an institution, a Connection's name, an account
    or a credential."""
    locked = st["locked"]
    vault = (
        '<span class="pill warn">locked</span>'
        if locked
        else '<span class="pill ok">unlocked</span>'
    )
    fp = st.get("vault") or ""
    fp = " ".join(fp[i : i + 4] for i in range(0, len(fp), 4))
    rows = [
        f'<div class="list-item"><span class="grow">Vault</span>{vault}'
        f'<span class="small dim mono">· {e(fp)}</span></div>'
    ]
    if st["paired"]:
        confirmed = {True: "· confirmed", False: "· not confirmed yet", None: ""}[
            st.get("confirmed")
        ]
        rows.append(
            f'<div class="list-item"><span class="grow">Paired with</span><span class="mono '
            f'small">{e(st["server"])}</span><span class="small dim">{confirmed}</span></div>'
        )
        rows.append(
            f'<div class="list-item"><span class="grow">This connector</span><span class="mono '
            f'small">{e(st["fingerprint"] or "")}</span></div>'
        )
        answered = (
            "· MoolaKata answered"
            if st["reachable"] and not st.get("lastError")
            else "· MoolaKata isn’t answering"
        )
        rows.append(
            '<div class="list-item"><span class="grow">Last report</span>'
            f'{e(_ago(st["lastReport"]))}<span class="small dim">{answered}</span></div>'
        )
        states = [c.get("state") for c in st["connections"].values()]
        if not states:
            count = "none yet"
        elif locked:
            count = f"{len(states)}, waiting for the unlock"
        else:
            working = sum(s in WORKING for s in states)
            attention = sum(s in ATTENTION for s in states)
            parts = [f"{working} working"]
            if attention:
                parts.append(f"{attention} need{'s' if attention == 1 else ''} attention")
            if rest := len(states) - working - attention:
                parts.append(f"{rest} starting")
            count = ", ".join(parts)
        rows.append(f'<div class="list-item"><span class="grow">Connections</span>{e(count)}</div>')
    else:
        rows.append(
            '<div class="list-item"><span class="grow">MoolaKata</span>not paired yet</div>'
            '<p class="small dim">Pair it with the code Settings › Connector shows in '
            "MoolaKata.</p>"
        )
    return "".join(rows)


def actions(locked: bool) -> str:
    lock = "" if locked else '<a class="btn" href="/lock">Lock…</a>'
    return (
        f'<div class="toolbar">{lock}<a class="btn" href="/pair">Pair…</a>'
        '<a class="btn" href="/unpair">Unpair…</a><span class="spacer"></span>'
        '<a class="btn danger" href="/reset">Reset…</a></div><p class="small dim">Each asks for '
        "the vault’s words. Sign-ins at institutions are never typed here: their owners seal "
        "them in MoolaKata.</p>"
    )


# ---------- the server ----------


class Handler(BaseHTTPRequestHandler):
    server_version = "MoolaKata-Connector"
    sys_version = ""
    timeout = 20
    page: Page  # set on the class made for each server

    # ----- plumbing -----

    def setup(self) -> None:
        self.request.settimeout(self.timeout)
        self.request.do_handshake()  # here, in this request's thread, within its timeout
        super().setup()

    def log_message(self, format, *args) -> None:
        log.debug("%s %s", self.address_string(), format % args)

    def _send(self, status: int, body: bytes, kind: str, extra: dict | None = None) -> None:
        self.send_response(status)
        for k, v in {**HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def html(self, title: str, sub: str, body: str, status: int = 200) -> None:
        text = layout(self.page, title, sub, body, self._host())
        self._send(status, text.encode(), "text/html; charset=utf-8")

    def go(self, where: str = "/") -> None:
        self._send(303, b"", "text/plain", {"Location": where})

    def _host(self) -> str:
        return urlsplit("//" + (self.headers.get("Host") or "")).hostname or "this connector"

    def _form(self) -> dict[str, str] | None:
        """A form posted from this page, at most 16 KB (S18.11.5); None (answered) otherwise."""
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None:  # what a browser says of where the form came from, first
            same = site == "same-origin"
        else:
            origin = self.headers.get("Origin") or ""
            same = bool(origin) and urlsplit(origin).netloc == (self.headers.get("Host") or "")
        if not same:
            self._send(403, b"Forms are taken only from this page.", "text/plain; charset=utf-8")
            return None
        try:
            length = int(self.headers.get("Content-Length") or "-1")
        except ValueError:
            length = -1
        if length < 0 or length > BODY_LIMIT:
            self._send(413, b"A form here is at most 16 KB.", "text/plain; charset=utf-8")
            return None
        body = self.rfile.read(length).decode("utf-8", "replace")
        return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}

    def _words(self, form: dict, unlock: bool = False) -> str | None:
        """The words checked against the vault (or used to unlock it); a wrong one is logged
        with its address and counts toward the wait (S18.3.3). None when refused."""
        phrase = form.get("words", "")
        vault = self.page.core.vault
        try:
            if unlock and vault.locked:
                self.page.core.unlock(phrase)
            else:
                vault.check(phrase)
        except VaultError as err:
            log.warning("wrong words on its page from %s: %s", self.client_address[0], err.kind)
            self.refused = str(err)[:1].upper() + str(err)[1:] + "."
            return None
        return phrase

    # ----- GET -----

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/style.css":
            self._send(200, STYLE.read_bytes(), "text/css; charset=utf-8")
        elif path == "/":
            self.home()
        elif path in ("/lock", "/pair", "/unpair", "/reset"):
            if self.page.core.vault.exists():
                getattr(self, "form_" + path[1:])()
            else:
                self.go()
        else:
            self._send(404, b"Not here.", "text/plain; charset=utf-8")

    def home(self, message: str | None = None, status: int = 200) -> None:
        core = self.page.core
        if not core.vault.exists():
            self.html(
                "Welcome to MoolaKata Connector",
                "This connector is new. Its vault will keep your household’s sign-ins at "
                "institutions.",
                notice(message) + '<p class="small">The vault opens only with <b>12 words</b>, '
                "which you keep in the household’s password manager. Nothing keeps them for "
                "you: the connector asks for them after every restart, and without them its "
                'sign-ins are entered again.</p><p class="small dim">MoolaKata never sees them: '
                "this page is the connector’s own.</p>"
                '<form method="post" action="/welcome"><button class="btn primary wide">Show my '
                "words</button></form>",
                status,
            )
            return
        st = core.status()
        if st["locked"]:
            self.html(
                "MoolaKata Connector is locked",
                "It started and fetches nothing until someone gives it the vault’s words.",
                status_rows(st)
                + notice(message)
                + '<form method="post" action="/unlock">'
                + words_field()
                + '<button class="btn primary wide">Unlock</button></form>'
                + actions(True),
                status,
            )
            return
        since = f"Unlocked since {_when(st['unlockedAt'])}. " if st.get("unlockedAt") else ""
        self.html(
            "MoolaKata Connector",
            since + "It fetches on its schedule and reports every 5 minutes.",
            notice(message) + status_rows(st) + actions(False),
            status,
        )

    def form_lock(self, message: str | None = None, status: int = 200) -> None:
        self.html(
            "Lock",
            "Close the vault now. The connector fetches nothing until it is unlocked again.",
            notice(message)
            + '<form method="post" action="/lock">'
            + words_field()
            + '<div class="row"><a class="btn" href="/">Cancel</a><span class="spacer"></span>'
            '<button class="btn primary">Lock</button></div></form>',
            status,
        )

    def form_pair(self, message: str | None = None, status: int = 200) -> None:
        self.html(
            "Pair with MoolaKata",
            "Settings › Connector › Pair in MoolaKata shows the code, good for 24 hours.",
            notice(message) + '<form method="post" action="/pair"><label class="field">'
            '<span>Pairing code</span><input class="in" name="code" placeholder="mkp1.…" '
            'autocomplete="off" spellcheck="false" required><small>Pairing again replaces the '
            "server this connector is paired with.</small></label>"
            + words_field()
            + '<div class="row"><a class="btn" href="/">Cancel</a><span class="spacer"></span>'
            '<button class="btn primary">Pair</button></div></form>',
            status,
        )

    def form_unpair(self, message: str | None = None, status: int = 200) -> None:
        server = self.page.core.status()["server"]
        self.html(
            "Unpair",
            f"Forget {e(server)}, and the sign-ins kept for it." if server else "Not paired.",
            notice(message) + '<p class="small">The connector stops reporting and deletes every '
            "credential it holds for that server, and its keys. Pairing again makes new ones, "
            'and every sign-in is entered again.</p><form method="post" action="/unpair">'
            + words_field()
            + '<div class="row"><a class="btn" href="/">Cancel</a><span '
            'class="spacer"></span><button class="btn danger">Unpair</button></div></form>',
            status,
        )

    def form_reset(self, message: str | None = None, status: int = 200) -> None:
        self.html(
            "Reset the vault",
            "New words, when the old ones may have been seen.",
            notice(message) + '<div class="notice bad">This deletes the vault: every sign-in '
            "in it, and the pairing with MoolaKata. Pair again afterwards, and each sign-in is "
            'entered again.</div><form method="post" action="/reset">'
            + words_field("The vault’s words, now")
            + '<label class="field"><span>Type RESET'
            '</span><input class="in" name="confirm" autocomplete="off" required></label>'
            '<div class="row"><a class="btn" href="/">Cancel</a><span class="spacer"></span>'
            '<button class="btn danger">Reset</button></div></form><p class="small dim">Words '
            'lost? Reset on the connector’s host instead: <span class="mono">moolakata-'
            "connector reset</span>.</p>",
            status,
        )

    # ----- POST -----

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        form = self._form()
        if form is None:
            return
        self.refused = ""
        handler = {
            "/welcome": self.post_welcome,
            "/welcome/words": self.post_offered_words,
            "/welcome/check": self.post_check,
            "/welcome/vault": self.post_vault,
            "/unlock": self.post_unlock,
            "/lock": self.post_lock,
            "/pair": self.post_pair,
            "/unpair": self.post_unpair,
            "/reset": self.post_reset,
        }.get(path)
        if handler is None:
            self._send(404, b"Not here.", "text/plain; charset=utf-8")
            return
        if (
            path != "/welcome"
            and not path.startswith("/welcome/")
            and not (self.page.core.vault.exists())
        ):
            self.go()
            return
        handler(form)

    def post_welcome(self, form: dict) -> None:
        if self.page.core.vault.exists():
            self.go()
            return
        token, offer = self.page.offer()
        self.show_words(token, offer)

    def show_words(self, token: str, offer: Offer) -> None:
        grid = "".join(
            f'<div><span class="small dim">{i}.</span> <b>{e(w)}</b></div>'
            for i, w in enumerate(offer.words, 1)
        )
        fp = fingerprint(offer.key)
        fp = " ".join(fp[i : i + 4] for i in range(0, 16, 4))
        self.html(
            "The vault’s words",
            "Put these 12 words in your password manager, in order. They’re shown here once.",
            f'<div class="words">{grid}</div><div class="small dim">Vault <code>{e(fp)}</code> · '
            f'{e(dt.date.today().strftime("%b %-d, %Y"))}</div><div class="notice">A reload, or '
            "another browser, shows other words: only the ones you confirm next open the vault."
            f'</div><form method="post" action="/welcome/check"><input type="hidden" '
            f'name="token" value="{e(token)}"><button class="btn primary wide">I’ve kept them'
            "</button></form>",
        )

    def _offered(self, form: dict) -> tuple[str, Offer] | None:
        token = form.get("token", "")
        offer = self.page.on_offer(token)
        if offer is None:
            self.html(
                "Those words aren’t on offer",
                "An hour passed, or a vault was made with other words meanwhile.",
                '<form method="post" action="/welcome"><button class="btn primary wide">Show new '
                "words</button></form>"
                if not self.page.core.vault.exists()
                else '<a class="btn primary wide" href="/">Back to its status</a>',
                410,
            )
            return None
        return token, offer

    def post_offered_words(self, form: dict) -> None:
        if got := self._offered(form):
            self.show_words(*got)

    def post_check(self, form: dict, message: str | None = None, status: int = 200) -> None:
        got = self._offered(form)
        if got is None:
            return
        token, offer = got
        fields = "".join(
            f'<label class="field"><span>Word {n + 1}</span><input class="in" name="word{n + 1}" '
            'autocomplete="off" autocapitalize="none" spellcheck="false" required></label>'
            for n in offer.picks
        )
        self.html(
            "Check what you kept",
            "Type three of the words from your password manager.",
            notice(message) + f'<form method="post" action="/welcome/vault"><input type="hidden" '
            f'name="token" value="{e(token)}">{fields}<p class="small dim">Four letters of each '
            'are enough. A wrong word is refused.</p><div class="row"><button class="btn" '
            'formaction="/welcome/words" formnovalidate>Back</button><span class="spacer"></span>'
            '<button class="btn primary">Make the vault</button></div></form>',
            status,
        )

    def post_vault(self, form: dict) -> None:
        got = self._offered(form)
        if got is None:
            return
        _, offer = got
        typed = offer.words
        wrong = [
            n + 1
            for n in offer.picks
            if not _matches(typed[n], form.get(f"word{n + 1}", "").strip().lower())
        ]
        if wrong:
            self.post_check(form, "Those aren’t the words shown: check them.", 422)
            return
        core = self.page.core
        if offer.reset:
            core.reset(" ".join(typed))
            log.info(
                "a reset on its page made the vault %s, from %s",
                core.vault.fingerprint(),
                self.client_address[0],
            )
        else:
            if core.vault.exists():
                self.page.taken()
                self.go()
                return
            core.made(offer.key)
            log.info(
                "its page made the vault %s, from %s",
                core.vault.fingerprint(),
                self.client_address[0],
            )
        self.page.taken()
        self.go()

    def post_unlock(self, form: dict) -> None:
        if not self.page.core.vault.locked:
            self.go()
        elif self._words(form, unlock=True) is None:
            self.home(self.refused, 403)
        else:
            log.info("unlocked on its page, from %s", self.client_address[0])
            self.go()

    def post_lock(self, form: dict) -> None:
        if self._words(form) is None:
            self.form_lock(self.refused, 403)
            return
        self.page.core.lock()
        log.info("locked on its page, from %s", self.client_address[0])
        self.go()

    def post_pair(self, form: dict) -> None:
        if self._words(form, unlock=True) is None:
            self.form_pair(self.refused, 403)
            return
        try:
            fp = self.page.core.pair(form.get("code", "").strip())
        except (ServerError, VaultError, ValueError) as err:
            self.form_pair(str(err), 422)
            return
        log.info("paired on its page, from %s", self.client_address[0])
        self.html(
            "Paired",
            "Compare this connector’s fingerprint with what Settings › Connector shows in "
            "MoolaKata.",
            f'<div class="fingerprint">{e(fp)}</div><p class="small">If they match, '
            "<b>Confirm</b> there, with your password. Until then MoolaKata hands it no sign-in "
            "and takes no file from it. If they differ, someone else answered the code: "
            '<b>Unpair</b> in MoolaKata.</p><a class="btn primary wide" href="/">Done</a>',
        )

    def post_unpair(self, form: dict) -> None:
        if self._words(form, unlock=True) is None:
            self.form_unpair(self.refused, 403)
            return
        self.page.core.unpair()
        log.info("unpaired on its page, from %s", self.client_address[0])
        self.go()

    def post_reset(self, form: dict) -> None:
        if form.get("confirm", "").strip() != "RESET":
            self.form_reset("Type RESET to go on: nothing changed.", 422)
            return
        if self._words(form) is None:
            self.form_reset(self.refused, 403)
            return
        token, offer = self.page.offer(reset=True)
        self.show_words(token, offer)


def _matches(word: str, typed: str) -> bool:
    return typed == word or (len(typed) >= 4 and word.startswith(typed))


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        # A browser refusing the certificate, a client that hangs up: nothing to report.
        log.debug("the page's connection from %s ended early", client_address[0], exc_info=True)


def serve(core, settings: Settings, data: Path) -> ThreadingHTTPServer:
    """Its page, on its own port, in threads of its own (S18.11)."""
    cert, key = certificate(data, settings)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    page = Page(core, settings)
    handler = type("PageHandler", (Handler,), {"page": page})
    server = Server(("", settings.port), handler)
    # The handshake in each request's own thread, so a client that says nothing holds no one up.
    server.socket = context.wrap_socket(
        server.socket, server_side=True, do_handshake_on_connect=False
    )
    threading.Thread(target=server.serve_forever, name="connector-page", daemon=True).start()
    return server
