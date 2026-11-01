"""Builds docs/mockups/MoolaKata-app.html, the mockup generated from the app (requirements S12.9).

A seeded dev server runs on a fixed day with repeatable ids. Headless Chromium signs in as each
sample user and opens every screen, tab, range and dialog; each answer the app asks the API for
is recorded. The page that comes out holds the app's own modules, styles and icons, the guides
and those answers, with a small backend in the page that serves them, so it opens from disk
and sends nothing anywhere.

    python web/ui/mockup/build.py           write the file
    python web/ui/mockup/build.py --check   fail if the file is not what the app makes now
"""

import argparse
import base64
import contextlib
import difflib
import itertools
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from moolakata import exactjson
from moolakata.dev.settled import SETTLED, TRACK_FETCHES

UI = Path(__file__).resolve().parents[1]
ROOT = UI.parents[1]
OUT = ROOT / "docs" / "mockups" / "MoolaKata-app.html"
# The day the sample data is shown on: the seed's year ends here.
AT = "2026-10-12T16:00:00+00:00"
SHOWN_DIR = "/srv/moolakata"
# Each run's server makes a new self-signed certificate; the mockup shows one fixed fingerprint.
OWN_CERT = re.compile(r'("certificate":\s*")[0-9a-f]{64}(")')
SHOWN_CERT = "5e1a77c20b9d3f48c07e9a1255b3e8f09d04e1b722fa6c034b8e5a19d7c20e66"
PASSWORD = "moolakata-dev"  # noqa: S105 - dev mode's seed users
USERS = ("alice", "bob", "admin")
# The API allows a session 600 requests a minute (requirements S13.7.5); the crawl keeps under it.
API_PER_MINUTE = 500
# The crawl's jobs run side by side, each browser signed in as each user it crawls for. Most of a
# job is waiting for a page to settle, so more of them than there are CPUs still gain.
WORKERS = int(os.environ.get("MK_CRAWL_WORKERS", 0)) or max(4, os.process_cpu_count() or 1)
# The app's source, as the browser loads it; mockup/ adds the router and the MOCK pill's menu.
SOURCE_DIRS = ("app", "api", "store", "components", "screens", "charts", "account-types")
SETTINGS = (
    "general",
    "email",
    "sessions",
    "signup",
    "passwords",
    "prices",
    "bitcoin",
    "links",
    "connector",
    "imports",
    "receipts",
    "tax-tables",
    "backups",
    "storage",
    "keys",
    "network",
    "alerts",
)
# (path, button, guide): the dialogs that load something when they open.
DIALOGS = (
    ("/ui/accounts", "New account", "dialog-new-account"),
    ("/ui/accounts", "Import", "dialog-import"),
    ("/ui/transactions", "Add", "dialog-transaction"),
    ("/ui/portfolios", "New portfolio", "dialog-portfolio"),
    ("/ui/budgets", "New budget", "dialog-budget"),
    ("/ui/budgets", "Edit plan", "dialog-plan"),
    ("/ui/receipts", "Receipt Blue Bottle Coffee", "dialog-receipt"),
    ("/ui/projections", "New projection", "dialog-new-projection"),
    ("/ui/gifts/people", "Add a person", "dialog-person"),
    ("/ui/gifts/gifts", "Add a gift", "dialog-gift"),
    ("/ui/giving/donations", "Record a donation", "dialog-donation"),
    ("/ui/positions/open", "Record an option trade", "dialog-option-trade"),
    ("/ui/positions/strategies", "An underlying was adjusted…", "dialog-option-adjust"),
    ("/ui/giving/organisations", "Add an organisation", "dialog-organisation"),
    ("/ui/taxes/summary", "New tax book", "dialog-tax-book"),
    ("/ui/taxes/filings", "Add a filing", "dialog-filing"),
    ("/ui/profile", "Compare models", "dialog-bitcoin-models"),
    ("/ui/profile", "New token", "dialog-new-token"),
    ("/ui/profile", "New connection", "dialog-connection"),
    ("/ui/users", "New user", "dialog-new-user"),
    ("/ui/users", "New group", "dialog-group"),
    ("/ui/settings/prices", "Add a source", "dialog-add-source"),
    ("/ui/settings/links", "Enter a link code", "dialog-link-join"),
    ("/ui/settings/connector", "Pair a replacement…", "dialog-connector-pair"),
)
# POSTs that only work something out: the first answer is kept, for the page to show.
COMPUTED = re.compile(r"/ui/api/accounts/[^/]+/loan/(payoff|split)$")
IMPORTS = re.compile(r"""(\bfrom\s*|\bimport\s*\(?\s*)(['"])(\.{1,2}/[^'"]+)\2""")
SCREENS = re.compile(r"import\(`\.\./screens/\$\{name\}\.js`\)")


def steady(value):
    """A recorded answer without the last digits of floating-point arithmetic, which differ
    from one CPU to the next (a projection's percentiles): a decimal of more than 12
    significant digits is kept to 10, which no screen shows the difference of."""
    if isinstance(value, Decimal) and len(value.as_tuple().digits) > 12:
        return Decimal(format(value, ".10g"))
    if isinstance(value, dict):
        return {k: steady(v) for k, v in value.items()}
    if isinstance(value, list):
        return [steady(v) for v in value]
    return value


@dataclass(frozen=True)
class Mask:
    """A recorded value that differs from one machine or run to the next, and what the mockup
    shows in its place. `field` is dotted, with `[]` for every item of a list."""

    path: str
    field: str
    shown: object
    why: str


# What else keeps the recording the same everywhere: the crawl's server runs with TZ=UTC (the
# zone also decides the dates it works out), and steady() keeps long decimals to 10 digits.
MASKS = (
    Mask(
        "/ui/api/settings/backups",
        "backups[].bytes",
        2642261,
        "the backup made at the server's start races the stub prices' first fill",
    ),
    Mask("/ui/api/settings/keys/copies", "copies[].bytes", 2642771, "that backup, as a copy"),
)


def masked(path: str, body):
    """A recorded answer with each of MASKS for its path in place."""
    for m in MASKS:
        if m.path == path:
            _mask(body, m.field.split("."), m.shown)
    return body


def _mask(value, steps: list[str], shown) -> None:
    key, rest = steps[0], steps[1:]
    if not isinstance(value, dict) or key.removesuffix("[]") not in value:
        return
    inner = value[key.removesuffix("[]")]
    if not rest:
        value[key.removesuffix("[]")] = shown
    elif key.endswith("[]"):
        for item in inner:
            _mask(item, rest, shown)
    else:
        _mask(inner, rest, shown)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """moolakata dev, seeded, on the stub prices, frozen on AT."""

    def __init__(self, data: Path) -> None:
        self.port = free_port()
        self.base = f"https://127.0.0.1:{self.port}"
        self.log_path = data / "server.log"
        self.log = open(self.log_path, "wb")  # noqa: SIM115 - closed in stop()
        self.proc = subprocess.Popen(  # noqa: S603 - this checkout's own server
            [
                sys.executable,
                "-m",
                "moolakata.main",
                "dev",
                "--seed",
                "--stubs",
                "--frozen",
                AT,
                "--port",
                str(self.port),
                "--data",
                str(data),
            ],
            stdout=self.log,
            stderr=subprocess.STDOUT,
            # The zone is pinned as the day is, so every machine records the same answers.
            env={**os.environ, "TZ": "UTC"},
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if httpx.get(self.base + "/healthz", verify=False).status_code == 200:  # noqa: S501
                    return
            except httpx.TransportError:
                pass
            if self.proc.poll() is not None:
                break
            time.sleep(0.2)
        self.stop()
        sys.exit("the dev server did not start:\n" + self.log_path.read_text())

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=15)
        self.log.close()


def key_of(url: str) -> str:
    """A request's key, as the page's backend makes it: the path and the sorted query, less
    `since`, which only says "now"."""
    u = urlsplit(url)
    q = sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != "since")
    return u.path + ("?" + urlencode(q, safe="*") if q else "")


def fetch(route):
    """route.fetch(), sent once more when the connection it went out on was being closed.

    The server closes a connection left idle for 5 s. A request Playwright writes to one as it
    closes dies with "socket hang up", and unlike a browser, Playwright does not send it again.
    The server never read it; a GET, and the loan calculations, are safe to send twice anyway.
    """
    try:
        return route.fetch()
    except Exception as e:
        if not any(s in str(e) for s in ("socket hang up", "ECONNRESET")):
            raise
        return route.fetch()


# Headers of an answer that describe how it was sent, not what it says: a reply from the book
# is sent afresh.
RESENT = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"}


class Book:
    """What the crawl has recorded for one user, shared by the recorders crawling for them.

    Each answer is kept with the job it came in for (its place in the crawl's order): a GET's
    last, a computed POST's first, as one recorder doing every job in order would keep them. A
    GET answered once is answered again from here, so the server works out each answer once."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.answers: dict[str, tuple[int, dict]] = {}
        self.replies: dict[str, dict] = {}
        self.sent: deque[float] = deque()

    def pace(self) -> None:
        """Hold a request while the session is near the API's limit."""
        while True:
            with self.lock:
                now = time.monotonic()
                while self.sent and now - self.sent[0] > 60:
                    self.sent.popleft()
                if len(self.sent) < API_PER_MINUTE:
                    self.sent.append(now)
                    return
                wait = 61 - (now - self.sent[0])
            time.sleep(wait)

    def keep(self, key: str, job: int, answer: dict) -> None:
        with self.lock:
            if key not in self.answers or (
                job < self.answers[key][0]
                if key.startswith("POST ")
                else job >= self.answers[key][0]
            ):
                self.answers[key] = (job, answer)

    def kept(self) -> dict:
        return {k: self.answers[k][1] for k in sorted(self.answers)}


class Recorder:
    """A browser context crawling as one user, recording every answer the app's GETs receive
    into the user's book. The first signs in; the others take its session (`signed`)."""

    def __init__(
        self, browser, base: str, username: str, data: str, book: Book, signed: dict | None = None
    ) -> None:
        self.base = base
        self.data = data
        self.username = username
        self.book = book
        self.job = -1
        # Answers come from the book once signed in: before, the session's answer differs.
        self.replay = signed is not None
        self.ctx = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1440, "height": 900},
            timezone_id="America/New_York",
            locale="en-US",
            storage_state=signed,
        )
        self.page = self.ctx.new_page()
        self.page.clock.set_fixed_time(AT)
        self.ctx.add_init_script(TRACK_FETCHES)
        self.ctx.route("**/ui/api/**", self.through)
        self.page.goto(base + "/ui/")
        if not signed:
            self.page.fill("#f-username-or-email", username)
            self.page.fill("#f-password", PASSWORD)
            self.page.click("button.btn.primary")
        self.page.wait_for_selector(".side")
        self.settle()
        self.replay = True

    def settle(self) -> None:
        """Wait until the page has settled (moolakata.dev.settled) and still has 100 ms later,
        so what a screen starts once it has drawn (a fetch, a dialog's focus) has begun and the
        next step can't cut it off; after 30 s, go on as it is."""
        deadline = time.monotonic() + 30
        while (left := deadline - time.monotonic()) > 0:
            try:
                self.page.wait_for_function(SETTLED, timeout=left * 1000)
            except PlaywrightTimeout:
                return
            self.page.wait_for_timeout(100)
            if self.page.evaluate(SETTLED):
                return

    def through(self, route) -> None:
        """Pass each request to the server, keeping what a GET was answered."""
        req = route.request
        if req.url.endswith("/events"):
            # No stream while crawling: one left open by each page fills the browser's
            # connections. A 204 tells EventSource not to try again.
            route.fulfill(status=204)
            return
        key = req.method + " " + key_of(req.url)
        if req.method == "GET" and self.replay and key in self.book.replies:
            route.fulfill(**self.book.replies[key])
            return
        self.book.pace()
        if req.method == "POST" and COMPUTED.search(key_of(req.url)):
            r = fetch(route)
            # The first answer: what was worked out from the record as it was shown.
            self.book.keep(key, self.job, {"status": r.status, "body": exactjson.loads(r.text())})
            route.fulfill(response=r)
            return
        if req.method != "GET":
            route.fallback()
            return
        r = fetch(route)
        kind = r.headers.get("content-type", "")
        if not kind.startswith("application/json") and r.status == 200 and r.body():
            # A picture (a receipt's thumbnail): kept as it came, for the page's fetch.
            body = r.body()
            answer = {"status": r.status, "type": kind, "binary": base64.b64encode(body).decode()}
        else:
            # Where this run kept its data is a temporary directory; the mockup shows a fixed one.
            text = r.text().replace(self.data, SHOWN_DIR)
            text = OWN_CERT.sub(lambda m: m.group(1) + SHOWN_CERT + m.group(2), text)
            shown = masked(urlsplit(req.url).path, steady(exactjson.loads(text))) if text else None
            answer = {"status": r.status, "body": shown}
            body = text.encode()
        self.book.keep(key, self.job, answer)
        if self.replay:
            headers = {k: v for k, v in r.headers.items() if k.lower() not in RESENT}
            reply = {"status": r.status, "headers": headers, "body": body}
            with self.book.lock:
                self.book.replies.setdefault(key, reply)
        route.fulfill(response=r, body=body)

    def visit(self, path: str) -> None:
        self.page.goto(self.base + path)
        try:
            self.page.wait_for_selector(".content > *", timeout=20000)
        except Exception:
            sys.exit(f"{path} drew nothing in 20 s for {self.username}")
        self.settle()
        # Every range and chip a screen offers.
        chips = self.page.locator(".content .chips button")
        for i in range(chips.count()):
            chips.nth(i).click()
            self.settle()

    def api(self, path: str):
        return self.page.evaluate(f"async () => (await fetch('/ui/api{path}')).json()")

    def dialog(self, path: str, button: str) -> None:
        self.visit(path)
        target = self.page.get_by_role("button", name=button).first
        if not target.count() or not target.is_enabled():
            return
        target.click()
        self.page.wait_for_selector(".dialog")
        self.settle()
        # Its keys work from the frame after it draws: a dialog still open is asked again.
        for _ in range(3):
            self.page.keyboard.press("Escape")
            with contextlib.suppress(PlaywrightTimeout):
                self.page.wait_for_selector(".dialog", state="detached", timeout=5_000)
                return
        sys.exit(f"{path}: {button} stayed open after Escape for {self.username}")

    def hello(self) -> dict:
        self.ctx.unroute_all()
        return self.page.evaluate("""() => new Promise((done) => {
            const s = new EventSource('/ui/api/events');
            s.addEventListener('hello', (e) => { s.close(); done(JSON.parse(e.data)); });
        })""")

    def plan(self) -> list[tuple]:
        """The crawl's jobs for this user, in order: each screen, each account with its tabs and
        dialogs, each portfolio's tabs, then the dialogs."""
        session = self.api("/session")
        admin = session["user"]["admin"]
        paths = [
            "/ui/",
            "/ui/accounts",
            "/ui/transactions",
            "/ui/portfolios",
            "/ui/positions/open",
            "/ui/positions/strategies",
            "/ui/positions/closed",
            "/ui/positions/trades",
            "/ui/positions/gains",
            "/ui/activity",
            "/ui/alerts",
            "/ui/receipts",
            "/ui/projections",
            "/ui/gifts/upcoming",
            "/ui/gifts/people",
            "/ui/gifts/gifts",
            "/ui/gifts/spending",
            "/ui/giving/overview",
            "/ui/giving/donations",
            "/ui/giving/organisations",
            "/ui/giving/fund",
            "/ui/taxes/summary",
            "/ui/taxes/filings",
            "/ui/taxes/documents",
            "/ui/taxes/gains",
            "/ui/taxes/income",
            "/ui/taxes/retirement",
            "/ui/taxes/deductions",
            "/ui/taxes/giving",
            "/ui/taxes/education",
            "/ui/taxes/property",
            "/ui/taxes/issues",
        ]
        for x in self.api("/projections")["items"]:
            paths.append(f"/ui/projections/{x['id']}")
        for b in self.api("/budgets")["items"]:
            paths += [
                f"/ui/budgets/{b['id']}/{t}" for t in ("month", "cash-flow", "trends", "recurring")
            ]
        paths += ["/ui/profile", "/ui/transactions?category=none"]
        if admin:
            paths += ["/ui/users"] + [f"/ui/settings/{s}" for s in SETTINGS]
        jobs: list[tuple] = [("visit", p) for p in paths]
        for a in self.api("/accounts")["items"]:
            jobs.append(("account", a["id"], a["level"] != "read", a["name"]))
        for p in self.api("/portfolios")["items"]:
            jobs += [("visit", f"/ui/portfolios/{p['id']}/{tab}")
                     for tab in ("performance", "holdings", "projections")]  # fmt: skip
        for path, button, _ in DIALOGS:
            if admin or not path.startswith(("/ui/users", "/ui/settings")):
                jobs.append(("dialog", path, button))
        return jobs

    def run(self, job: tuple) -> None:
        kind, *args = job
        if kind == "visit":
            self.visit(*args)
        elif kind == "dialog":
            self.dialog(*args)
        else:
            account, writes, name = args
            self.visit(f"/ui/accounts/{account}")
            tabs = self.page.eval_on_selector_all(
                ".content .tabs a", "(links) => links.map((l) => l.getAttribute('href'))"
            )
            for t in tabs:
                self.visit(t)
            if writes:
                self.dialog(f"/ui/accounts/{account}/reconcile", "Type today's balance")
                self.dialog(f"/ui/accounts/{account}/reconcile", "Tick off against a statement")
                self.dialog(f"/ui/accounts/{account}", "Record a payment")
            self.dialog("/ui/accounts", f"Share {name}")

    def close(self) -> None:
        # A page still asking for something as it closes: its answer is no longer wanted.
        self.ctx.unroute_all(behavior="ignoreErrors")
        self.ctx.close()


def crawl(base: str, data: str, username: str, signed: dict, book: Book, jobs: list) -> None:
    """One worker: its own browser, in the user's session, taking the next job until none are
    left. Playwright's sync API keeps to the thread it started in."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        r = None
        try:
            r = Recorder(browser, base, username, data, book, signed)
            while True:
                with book.lock:
                    if not jobs:
                        break
                    r.job, job = jobs.pop(0)
                r.run(job)
        except BaseException:
            with book.lock:
                jobs.clear()  # the other workers stop too: the crawl has failed
            raise
        finally:
            if r:
                r.close()
            browser.close()


def record() -> tuple[dict, dict, list]:
    """Every user's answers, one user after another as each signs in (what one user sees can
    tell who has signed in so far). A user's first recorder signs in and plans the jobs, WORKERS
    workers run them in its session, and it asks for the event stream's hello last."""
    from playwright.sync_api import sync_playwright

    answers, hellos, users = {}, {}, []
    with tempfile.TemporaryDirectory(prefix="mk-mockup-") as tmp:
        server = Server(Path(tmp))
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                for username in USERS:
                    book = Book()
                    first = Recorder(browser, server.base, username, tmp, book)
                    jobs = list(enumerate(first.plan()))
                    # The longest first, so no worker is left with a long one at the end.
                    jobs.sort(key=lambda j: j[1][0] != "account")
                    signed = first.ctx.storage_state()
                    with ThreadPoolExecutor(WORKERS) as pool:
                        running = [
                            pool.submit(crawl, server.base, tmp, username, signed, book, jobs)
                            for _ in range(WORKERS)
                        ]
                        for f in running:
                            f.result()
                    answers[username] = book.kept()
                    me = answers[username]["GET /ui/api/session"]["body"]["user"]
                    users.append({"username": username, "name": me["displayName"]})
                    hellos[username] = first.hello()
                    first.close()
                browser.close()
        finally:
            server.stop()
    return answers, hellos, users


def specifier(path: Path) -> str:
    return "@mk/" + path.relative_to(UI).as_posix()


def data_url(text: str, mime: str = "text/javascript") -> str:
    return f"data:{mime};charset=utf-8;base64," + base64.b64encode(text.encode()).decode()


def modules(bare: dict[str, Path]) -> dict[str, str]:
    """Every module the app can load, under a name of its own, with its relative imports
    rewritten to those names: a module loaded from a data: address has nothing to be
    relative to."""
    todo = [p for d in SOURCE_DIRS for p in sorted((UI / d).rglob("*.js"))]
    todo += [UI / "mockup" / "iso.js", UI / "mockup" / "menu.js", *bare.values()]
    out: dict[str, str] = {}
    while todo:
        path = todo.pop()
        name = specifier(path)
        if name in out:
            continue
        text = path.read_text()

        def rewrite(m: re.Match, path=path) -> str:
            target = (path.parent / m.group(3)).resolve()
            if target.suffix not in (".js", ".mjs") or not target.is_file():
                return m.group(0)
            todo.append(target)
            return f"{m.group(1)}{m.group(2)}{specifier(target)}{m.group(2)}"

        text = IMPORTS.sub(rewrite, text)
        text = SCREENS.sub("import(`@mk/screens/${name}.js`)", text)
        out[name] = text
    return out


def embed(name: str, text: str) -> str:
    """A module's source, which sits in a <script> element as it is: it may not hold what
    would end that element early."""
    if re.search(r"</script|<!--", text, re.I):
        sys.exit(f"{name} holds </script or <!--, which the mockup cannot embed")
    return text


def lines(data: dict) -> str:
    """The recorded data as JSON with one answer, guide or user per line, so a change to the
    app shows in a diff as the lines it changed."""
    out = []
    for k in sorted(data):
        v = data[k]
        if isinstance(v, dict) and k in ("api", "events", "guides"):
            inner = []
            for k2 in sorted(v):
                v2 = v[k2]
                if k == "api":
                    rows = ",\n".join(
                        json.dumps(k3)
                        + ":"
                        + exactjson.dumps(v2[k3], sort_keys=True, ensure_ascii=False)
                        for k3 in sorted(v2)
                    )
                    inner.append(f"{json.dumps(k2)}:{{\n{rows}\n}}")
                else:
                    inner.append(
                        f"{json.dumps(k2)}:{json.dumps(v2, sort_keys=True, ensure_ascii=False)}"
                    )
            out.append(f"{json.dumps(k)}:{{\n" + ",\n".join(inner) + "\n}")
        else:
            out.append(f"{json.dumps(k)}:{json.dumps(v, sort_keys=True, ensure_ascii=False)}")
    return "{\n" + ",\n".join(out) + "\n}"


def assemble(answers: dict, hellos: dict, users: list) -> str:
    version = (ROOT / "web" / "VERSION").read_text().strip()
    page = (UI / "index.html").read_text()
    prefix = f"/ui/v/{version}/"
    page = page.replace("{{version}}", version).replace("{{dev}}", "0")
    page = page.replace(' nonce="{{nonce}}"', "")

    m = re.search(r'<script type="importmap">\s*(\{.*?\})\s*</script>', page, re.S)
    assert m, "index.html has no import map"
    bare = {k: UI / v.removeprefix(prefix) for k, v in json.loads(m.group(1))["imports"].items()}
    code = modules(bare)
    # The bare names point at modules by their own names; preact-iso is the mockup's router,
    # which loads the real one as @mk/preact-iso.
    aliases = {k: specifier(p) for k, p in sorted(bare.items())}
    aliases["@mk/preact-iso"] = aliases["preact-iso"]
    aliases["preact-iso"] = "@mk/mockup/iso.js"
    scripts = "".join(
        f'<script type="text/plain" data-module="{name}">\n{embed(name, code[name])}</script>\n'
        for name in sorted(code)
    )

    css = "\n".join(
        (UI / "styles" / f"{n}.css").read_text() for n in ("tokens", "base", "components")
    )
    sprite = (UI / "assets" / "icons.svg").read_text()
    sprite = re.sub(r"<\?xml.*?\?>\s*", "", sprite)
    sprite = sprite.replace(
        "<svg ",
        '<svg id="mk-icons" aria-hidden="true" style="position:absolute;width:0;height:0" ',
        1,
    )
    favicon = data_url((UI / "assets" / "favicon.svg").read_text(), "image/svg+xml")
    guides = {p.stem: p.read_text() for p in sorted((UI / "guides").glob("*.md"))}
    data = {
        "now": AT,
        "users": users,
        "api": answers,
        "events": hellos,
        "guides": guides,
        "aliases": aliases,
        "main": "@mk/app/main.js",
    }
    # JSON with no "<", which could end its <script> element early.
    blob = lines(data).replace("<", "\\u003c")
    runtime = (UI / "mockup" / "runtime.js").read_text()

    page = re.sub(r'<link rel="stylesheet"[^>]*>\n', "", page)
    page = re.sub(r'(<link rel="icon" href=")[^"]*', lambda m: m.group(1) + favicon, page)
    page = page.replace(
        '<meta name="mk-dev" content="0">',
        '<meta name="mk-dev" content="0">\n<meta name="mk-mockup" content="1">\n'
        '<meta name="mk-guides" content="../../web/ui/guides">',
    )
    # The page's runtime makes the import map from the modules below and then starts the app.
    page = page.replace(m.group(0) + "\n", "")
    page = re.sub(r'<script type="module" src="[^"]*main\.js"></script>\n', "", page)
    page = page.replace(
        "<title>MoolaKata</title>",
        "<title>MoolaKata</title>\n"
        "<!-- Generated by web/ui/mockup/build.py from the app (requirements S12.9). Do not edit:"
        " run web/dev.sh mockup. -->\n"
        f"<style>\n{css}</style>",
    )
    page = page.replace(
        '<div id="app"></div>\n',
        f'{sprite.strip()}\n<div id="app"></div>\n'
        f'<script type="application/json" id="mk-data">\n{blob}\n</script>\n'
        f"{scripts}<script>\n{embed('runtime.js', runtime)}</script>\n",
    )
    return page


def drift(old: str, new: str):
    """What changed, for a reader: a recorded answer by its fields, each with both values,
    and any other line as it is, cut short. An answer is one line of the file, often long."""

    def answer(line: str):
        try:
            return json.loads("{" + line.rstrip(",") + "}")
        except ValueError:
            return None

    def fields(a, b, path=""):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                yield from fields(a.get(k), b.get(k), f"{path}.{k}" if path else k)
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                yield from fields(x, y, f"{path}[{i}]")
        elif a != b:
            yield f"    {path}: {json.dumps(a)[:80]} -> {json.dumps(b)[:80]}"

    before, after = old.splitlines(), new.splitlines()
    ops = difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        pairs = zip(before[i1:i2], after[j1:j2], strict=False) if tag == "replace" else []
        for a, b in pairs:
            x, y = answer(a), answer(b)
            if x and y and x.keys() == y.keys():
                for key in x:
                    yield f"~ {key}"
                    yield from itertools.islice(fields(x[key], y[key]), 6)
            else:
                yield f"- {a[:160]}"
                yield f"+ {b[:160]}"
        if tag != "replace" or i2 - i1 != j2 - j1:
            for a in before[i1 + (j2 - j1) if tag == "replace" else i1 : i2]:
                yield f"- {a[:160]}"
            for b in after[j1 + (i2 - i1) if tag == "replace" else j1 : j2]:
                yield f"+ {b[:160]}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = p.parse_args(argv)
    html = assemble(*record())
    if args.check:
        now = OUT.read_text() if OUT.exists() else ""
        if now != html:
            for line in itertools.islice(drift(now, html), 400):
                print(line, file=sys.stderr)
            print(f"{OUT.relative_to(ROOT)} is out of date: run web/dev.sh mockup", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(html.encode()) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
