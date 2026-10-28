"""What the browser tests share (requirements S17.5.2): a server from this checkout, headless
Chromium, one household seeded once through the API, signing in, and waiting with a reason.

Test modules import the fixtures they use (`from browser import browser, household  # noqa`).
The server runs on the real clock, so months count back from today."""

import datetime as dt
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field

import httpx
import pytest

from moolakata.config import load
from moolakata.keys import cli as keys_cli
from moolakata.keys import phrase

PASSWORD = "a long admin passphrase"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(tmp, keyed: bool):
    """A server from this checkout, as the image runs it: with a keyring, locked; without,
    uninitialised (S15.4.4). Its base address, its process and its key (None without)."""
    port = free_port()
    config = tmp / "moolakata.toml"
    config.write_text(f"""
[server]
name = "smoke"
mode = "proxy"
host = "127.0.0.1"
port = {port}
[paths]
data = "{tmp / "data"}"
backups = "{tmp / "backups"}"
socket = "{tmp / "run" / "sock"}"
""")
    key = keys_cli.init(load(config), say=lambda _: None, confirm=False) if keyed else None
    log = open(tmp / "server.log", "wb")  # noqa: SIM115 - a file: an unread pipe fills up
    proc = subprocess.Popen(
        [sys.executable, "-m", "moolakata.main", "--config", str(config), "serve"],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            r = httpx.get(base + "/healthz")
            if r.status_code == 503 and r.json()["status"] in ("locked", "uninitialised"):
                break
        except httpx.TransportError:
            pass
        if proc.poll() is not None:
            pytest.fail(f"server exited: {(tmp / 'server.log').read_text()}")
        time.sleep(0.1)
    return base, proc, key


def stop(proc) -> None:
    proc.terminate()  # SIGTERM: a clean stop within the 5-second grace (S13.6)
    assert proc.wait(timeout=8) == 0


def unlocked(tmp):
    """A keyed server, opened with its phrase as the unlock page or `keys unlock` open it
    (S15.4.3). Its base address and its process."""
    base, proc, key = start(tmp, keyed=True)
    r = httpx.post(
        base + "/ui/api/unlock",
        json={"phrase": " ".join(phrase.to_words(key))},
        headers={"Origin": base},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    assert httpx.get(base + "/healthz").status_code == 200
    return base, proc


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_page(browser, url):
    """A page at a desktop window's size, and the list of what went wrong on it: page errors,
    console errors, and answers of 400 or more."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    problems = []
    page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
    # The session check before signing in answers 401 by design; its "Failed to load resource"
    # carries no address, so failed responses are checked by address instead.
    page.on(
        "console",
        lambda m: (
            m.type == "error"
            and "Failed to load resource" not in m.text
            and problems.append(f"console: {m.text}")
        ),
    )
    page.on(
        "response",
        lambda r: (
            r.status >= 400
            and not r.url.endswith("/ui/api/session")
            and problems.append(f"{r.status} for {r.url}")
        ),
    )
    page.goto(url)
    return page, problems


def wait(page, selector: str, problems: list, **kw) -> None:
    """Wait for a selector; a timeout names what the page reported on the way, and leaves a
    screenshot where MK_FAIL_SHOT says."""
    from playwright.sync_api import TimeoutError as Late

    try:
        page.wait_for_selector(selector, **kw)
    except Late:
        shot = os.environ.get("MK_FAIL_SHOT")
        if shot:
            page.screenshot(path=shot)
        pytest.fail(f"{selector} {kw}: never; the page said {problems}")


def months_back(n: int) -> str:
    """The month `n` months before this one, as 2026-10."""
    today = dt.date.today()
    y, m = divmod(today.year * 12 + today.month - 1 - n, 12)
    return f"{y:04d}-{m + 1:02d}"


def client(base: str) -> httpx.Client:
    """An API client for the server. The session cookie is Secure, which httpx won't send over
    http, so it is carried by hand."""
    c = httpx.Client(base_url=base, headers={"Origin": base}, timeout=30)

    def keep(response: httpx.Response) -> None:
        for v in response.headers.get_list("set-cookie"):
            name, _, rest = v.partition("=")
            c.headers["Cookie"] = f"{name}={rest.split(';', 1)[0]}"

    c.event_hooks["response"] = [keep]
    return c


def made(r: httpx.Response) -> dict:
    assert r.status_code in (200, 201), r.text
    return r.json()


def save(c: httpx.Client, ops: list[dict], confirm: list | None = None) -> httpx.Response:
    """A draft's save (S13.8.11), as a dialog sends it."""
    return c.post("/ui/api/save", json={"ops": ops, "confirm": confirm or []})


@dataclass
class Household:
    """The household every browser test shares, seeded once: an admin, a checking account
    with groceries bought in each of the last three months, and two budgets from this month: a
    tracking one with reserves and moves (a rolling line, a move between two lines, a reserve
    with its target) and an envelope one with a yearly line."""

    base: str
    c: httpx.Client
    cats: dict[str, str]
    checking: dict
    budget: dict
    envelope: dict
    extra: dict = field(default_factory=dict)


def seed(base: str) -> Household:
    from test_budgets import save_plan

    c = client(base)
    r = c.post(
        "/ui/api/welcome/admin",
        json={"password": PASSWORD, "email": "admin@home.lan", "displayName": "Admin",
              "sex": "female"},
    )  # fmt: skip
    if r.status_code == 409:
        r = c.post("/ui/api/session", json={"login": "admin", "password": PASSWORD})
    assert r.status_code == 200, r.text
    acct = made(c.post("/ui/api/accounts", json={"name": "Checking", "type": "checking"}))
    cats = {x["path"]: x["id"] for x in c.get("/ui/api/categories").json()["items"]}
    dining, fun = cats["Food › Dining out"], cats["Entertainment"]
    repair, groceries = cats["Transportation › Car maintenance"], cats["Food › Groceries"]
    for n in (1, 2, 3):
        made(
            c.post(
                "/ui/api/transactions",
                json={"accountId": acct["id"], "date": f"{months_back(n)}-05",
                      "amount": "-120.00", "payee": "Kroger", "categoryId": groceries},
            )
        )  # fmt: skip
    b = made(c.post("/ui/api/budgets", json={"name": "Household", "accountIds": [acct["id"]]}))
    v = c.get(f"/ui/api/budgets/{b['id']}").json()["version"]
    made(
        c.patch(
            f"/ui/api/budgets/{b['id']}",
            json={"reserves": True, "moves": True},
            headers={"If-Match": str(v)},
        )
    )
    b = c.get(f"/ui/api/budgets/{b['id']}").json()
    lines = [{"categoryId": dining, "amount": "300.00", "rollover": True},
             {"categoryId": fun, "amount": "200.00"},
             {"categoryId": repair, "amount": "100.00", "target": "1000.00"}]  # fmt: skip
    made(save_plan(c, b, f"{months_back(0)}-01", lines))
    made(
        c.post(
            f"/ui/api/budgets/{b['id']}/moves",
            json={"month": f"{months_back(0)}-01", "fromCategoryId": fun,
                  "toCategoryId": dining, "amount": "40.00"},
        )
    )  # fmt: skip
    env = made(
        c.post(
            "/ui/api/budgets",
            json={"name": "Envelopes", "method": "envelope", "accountIds": [acct["id"]]},
        )
    )
    yearly = [{"categoryId": fun, "amount": "1200.00", "cadence": "year"}]
    made(save_plan(c, env, f"{months_back(0)}-01", yearly))
    return Household(base, c, cats, acct, b, env)


@pytest.fixture(scope="session")
def served(tmp_path_factory):
    """One unlocked server for the browser tests that sign in."""
    base, proc = unlocked(tmp_path_factory.mktemp("browser"))
    yield base
    stop(proc)


@pytest.fixture(scope="session")
def household(served) -> Household:
    h = seed(served)
    yield h
    h.c.close()


def signed_in(browser, h: Household, path: str, ready: str):
    """A page signed in as the household's admin at `path`, once `ready` shows."""
    page, problems = open_page(browser, h.base + "/ui/")
    r = page.request.post(
        h.base + "/ui/api/session",
        data={"login": "admin", "password": PASSWORD},
        headers={"Origin": h.base},
    )
    assert r.ok, r.text()
    page.goto(h.base + path)
    wait(page, ready, problems)
    return page, problems
