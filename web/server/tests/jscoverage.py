"""The browser app's coverage from the browser tests (requirements S17.5.8): when MK_JS_COVERAGE
names a directory, every page the tests open in Chromium records V8's precise coverage, and
before it closes, each of the app's files it ran is written there in the form `deno test
--coverage` writes, so `deno coverage` reads both together.

Pages are found by wrapping Playwright's `new_page` and `close`: a page opened another way (a
pop-up) is not measured."""

import contextlib
import json
import os
import uuid
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "ui"
# What a test waits for before it moves on, so it leaves each screen in the same state every run
# and the code the tests reach doesn't depend on their timing (S17.5.8). TRACK_FETCHES, run in
# each page before its own scripts, counts the requests in flight until their bodies are read;
# SETTLED holds once none has been for 150 ms (time for a screen to start what it fetches
# next), no Loading placeholder shows, and each chart has drawn (ECharts loads on first use and
# draws its SVG into the box). The page's open event stream is not a fetch, so it never counts.
TRACK_FETCHES = """(() => {
  let pending = 0;
  let quiet = 0;
  const fetch0 = window.fetch.bind(window);
  window.__mkSettled = () => pending === 0 && performance.now() - quiet > 150;
  window.fetch = (...args) => {
    pending++;
    const answer = fetch0(...args);
    answer.then((r) => r.clone().arrayBuffer()).catch(() => {}).finally(() =>
      setTimeout(() => {
        pending--;
        quiet = performance.now();
      }, 0)
    );
    return answer;
  };
})();"""
# A function, not an expression: the app's CSP refuses eval.
SETTLED = """() => (!window.__mkSettled || window.__mkSettled())
  && !document.querySelector('[aria-busy="true"]')
  && [...document.querySelectorAll('.chart-box')].every((b) => b.querySelector('svg'))"""
_started: set = set()


def _start(page) -> None:
    cdp = page.context.new_cdp_session(page)
    cdp.send("Profiler.enable")
    cdp.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})
    page._mk_coverage = cdp
    _started.add(page)


def _take(page, out: Path) -> None:
    """The page's coverage so far, of the app's own files (served under /ui/v/<version>/)."""
    if page not in _started or page.is_closed():
        return
    _started.discard(page)
    # Settled first, as browser.wait() does, so a page counts the same each run; a page gone
    # elsewhere or never settling gives what ran.
    with contextlib.suppress(Exception):
        page.wait_for_function(SETTLED, timeout=5_000)
    try:
        scripts = page._mk_coverage.send("Profiler.takePreciseCoverage")["result"]
    except Exception:  # a page that crashed has nothing to give
        return
    for sc in scripts:
        _, _, rest = sc["url"].partition("/ui/v/")
        rel = rest.partition("/")[2].split("?")[0]
        if not rel or rel.startswith("vendor/") or not (UI / rel).is_file():
            continue
        sc["url"] = (UI / rel).as_uri()
        (out / f"{uuid.uuid4()}.json").write_text(json.dumps(sc))


def install() -> None:
    out = os.environ.get("MK_JS_COVERAGE")
    if not out:
        return
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import Browser, BrowserContext, Page

    def opened(new_page):
        def wrapped(self, *a, **kw):
            page = new_page(self, *a, **kw)
            _start(page)
            return page

        return wrapped

    def closing(close, pages):
        def wrapped(self, *a, **kw):
            for page in pages(self):
                _take(page, out)
            return close(self, *a, **kw)

        return wrapped

    Browser.new_page = opened(Browser.new_page)
    BrowserContext.new_page = opened(BrowserContext.new_page)
    Page.close = closing(Page.close, lambda p: [p])
    BrowserContext.close = closing(BrowserContext.close, lambda c: list(c.pages))
    Browser.close = closing(Browser.close, lambda b: [p for c in b.contexts for p in c.pages])
