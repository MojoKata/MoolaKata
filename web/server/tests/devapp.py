"""A seeded dev server and alice's pages on it, for the browser tests that drive the whole app
(test_app.py, test_app_guides.py): opening a screen as a person would, and checking a
screen's or a dialog's guide (S12.7.6)."""

import contextlib
import re
import socket
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import httpx
import pytest

from moolakata.dev.settled import SETTLED, TRACK_FETCHES

# A failed request shows in the console without its address; failed responses are checked by
# address instead, where the session check before signing in may answer 401.
LOAD_FAILED = re.compile(r"Failed to load resource")
EXPECTED_FAILURES = re.compile(r"/ui/api/session$")
# The API allows a session 600 requests a minute (S13.7.5); a test opens screens far faster
# than a person, so it keeps under that instead.
API_PER_MINUTE = 500
SETTINGS_SECTIONS = (
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
    "keys",
    "network",
    "alerts",
)


# The dev server's data directory, where its emails are written.
DEV: dict[str, Path] = {}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def dev_server(tmp_path_factory):
    data = tmp_path_factory.mktemp("dev")
    port = free_port()
    log = open(data / "server.log", "wb")  # noqa: SIM115 - closed below
    # A file, not a pipe: a pipe nobody reads fills up and stops the server mid-request.
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "moolakata.main",
            "dev",
            "--seed",
            "--stubs",
            "--port",
            str(port),
            "--data",
            str(data),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"https://127.0.0.1:{port}"
    DEV["data"] = data
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if httpx.get(base + "/healthz", verify=False).status_code == 200:
                break
        except httpx.TransportError:
            pass
        if proc.poll() is not None:
            pytest.fail("dev server exited: " + (data / "server.log").read_text())
        time.sleep(0.2)
    yield base
    proc.terminate()
    proc.wait(timeout=15)
    log.close()


@contextlib.contextmanager
def as_alice(base: str):
    """A page in a Chromium of its own, signed in as alice, with what went wrong on it in
    `problems`: a session of its own, so its own share of the API's limit."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
        ctx.add_init_script(TRACK_FETCHES)
        pg = ctx.new_page()
        pg.problems = []
        pg.api_times = deque()
        pg.on("request", lambda r: "/ui/api/" in r.url and pg.api_times.append(time.monotonic()))
        pg.on("pageerror", lambda e: pg.problems.append(f"page error on {pg.url}: {e}"))
        pg.on(
            "console",
            lambda m: (
                m.type == "error"
                and not LOAD_FAILED.search(m.text)
                and pg.problems.append(f"console on {pg.url}: {m.text}")
            ),
        )
        pg.on(
            "response",
            lambda r: (
                r.status >= 400
                and not EXPECTED_FAILURES.search(r.url)
                and pg.problems.append(f"{r.status} for {r.url}")
            ),
        )
        pg.goto(base + "/ui/")
        pg.fill("#f-username-or-email", "alice")
        pg.fill("#f-password", "moolakata-dev")
        pg.click("button.btn.primary")
        pg.wait_for_selector(".side")
        pg.base = base
        yield pg
        browser.close()


@pytest.fixture(scope="module")
def page(dev_server):
    """One page for a module's tests, which run one after another."""
    with as_alice(dev_server) as pg:
        yield pg


GUIDE_CHECK = """(scope) => {
  const root = document.querySelector(scope);
  const guide = document.querySelector('.help .guide');
  if (!root || !guide) return { error: 'no ' + (!root ? scope : 'help pane') };
  const anchors = [...guide.querySelectorAll('[data-anchor]')].map((h) => h.dataset.anchor);
  const fields = [...root.querySelectorAll('[id^="f-"], [data-help]')]
    .map((el) => el.dataset.help || el.id.slice(2))
    .filter((id, i, all) => all.indexOf(id) === i);
  const missing = fields.filter((f) => !anchors.includes(f));
  const order = fields.filter((f) => anchors.includes(f)).map((f) => anchors.indexOf(f));
  const backwards = order.findIndex((v, i) => i > 0 && v < order[i - 1]);
  return {
    key: guide.dataset.guide,
    missingGuide: guide.textContent.includes("guide is missing"),
    missing, fields,
    backwards: backwards < 0 ? null : fields.filter((f) => anchors.includes(f))[backwards],
  };
}"""


def check_guide(page, scope: str, where: str) -> None:
    """The guide shown has a heading for each field, in the fields' order. Asked again until
    it does or 10 s pass, as a field drawn late (its record still loading) gets its heading
    once it is there; the last answer is the one judged."""
    for _ in range(200):
        r = page.evaluate(GUIDE_CHECK, scope)
        if "error" not in r and not r["missing"] and r["backwards"] is None:
            break
        page.wait_for_timeout(50)
    assert "error" not in r, f"{where}: {r}"
    assert not r["missingGuide"], f"{where}: no guide {r['key']}"
    assert r["missing"] == [], f"{where} ({r['key']}): fields without a heading: {r['missing']}"
    assert r["backwards"] is None, f"{where} ({r['key']}): {r['backwards']} sends the guide up"


def visit(page, path: str) -> None:
    """Open a screen and wait until what it loads has arrived, as a person would, so the
    server isn't left with a queue of abandoned requests."""
    pace(page)
    page.goto(page.base + path)
    try:
        page.wait_for_selector(".content > *", timeout=15000)
    except Exception:
        page.screenshot(path=str(Path(__file__).parent.parent / ".pytest_cache" / "stuck.png"))
        raise AssertionError(f"{path} drew nothing in 15 s") from None
    for _ in range(200):
        if not page.evaluate("document.querySelector('.content [aria-busy=\"true\"]')"):
            break
        page.wait_for_timeout(50)
    # Settled, so the next screen never tears this one down half-loaded (S17.5.8).
    page.wait_for_function(SETTLED, timeout=15000)
    page.wait_for_timeout(300)


def pace(page) -> None:
    """Wait while this session is near the API's limit."""
    times = page.api_times
    while times and time.monotonic() - times[0] > 60:
        times.popleft()
    if len(times) >= API_PER_MINUTE:
        page.wait_for_timeout(1000 * (61 - (time.monotonic() - times[0])))


def account_ids(page) -> dict[str, str]:
    return page.evaluate("""async () => Object.fromEntries(
        (await (await fetch('/ui/api/accounts')).json()).items
        .map((a) => [a.type, a.id]))""")


def wait_guide(page, key: str) -> None:
    """Wait for the help pane to show a guide. Polled from outside the page: a string
    evaluated inside it is refused by the app's CSP, which is the point."""
    for _ in range(100):
        if page.evaluate("document.querySelector('.help .guide')?.dataset.guide") == key:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"the help pane never showed {key}")


def open_dialog(page, path: str, button: str, guide: str) -> None:
    assert page.problems == [], page.problems
    visit(page, path)
    page.get_by_role("button", name=button).first.click()
    page.wait_for_selector(".dialog")
    wait_guide(page, guide)
    check_guide(page, ".dialog", f"{path} › {button}")


def close_dialog(page) -> None:
    """Escape; a dialog the sweep changed (a part added to see its guide) asks first."""
    page.keyboard.press("Escape")
    page.wait_for_function(
        "!document.querySelector('.dialog') || !!document.querySelector('.dialog-ask')"
    )
    asked = page.locator(".dialog-ask")
    if asked.count():
        asked.get_by_role("button", name="Discard").click()
    page.wait_for_selector(".dialog", state="detached")
