"""What the ui-kit's page tests share (requirements S17.5.13): its pages served from this
checkout as they are, under their own CSP, to headless Chromium; a page that fails on any page or
console error; each test's screenshot, kept for the run's artifact; and, when MK_JS_COVERAGE
names a directory, the kit's coverage from every page, in the form `deno coverage` reads."""

import json
import os
import threading
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from playwright.sync_api import sync_playwright

UI = Path(__file__).resolve().parents[2]
# The kit's pages, by the names their addresses take (#numbers), as the catalog lists them.
PAGES_IN_ORDER = ["numbers", "tags", "dates", "fields", "state", "overlays", "notes", "theme"]
SHOTS = UI.parent / ".dev" / "kit-shots"
VIEWPORT = {"width": 1440, "height": 900}


class Files(SimpleHTTPRequestHandler):
    """The ui directory's files, each with its type; nothing logged."""

    extensions_map: ClassVar = {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml",
        ".json": "application/json",
        "": "application/octet-stream",
    }

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


@pytest.fixture(scope="session")
def kit():
    """The pages' address: a server for the ui directory on a free port, for the session."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Files, directory=str(UI)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/kit/pages/index.html"
    httpd.shutdown()


@pytest.fixture(scope="session")
def chromium():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _coverage(page, out: Path) -> None:
    """What the page ran of the kit's own files, as `deno test --coverage` writes it."""
    try:
        scripts = page._kit_cdp.send("Profiler.takePreciseCoverage")["result"]
    except Exception:  # a page that crashed has nothing to give
        return
    for sc in scripts:
        rel = sc["url"].partition("://")[2].partition("/")[2].split("?")[0]
        if not rel.startswith("kit/") or not (UI / rel).is_file():
            continue
        sc["url"] = (UI / rel).as_uri()
        (out / f"{uuid.uuid4()}.json").write_text(json.dumps(sc))


@pytest.fixture
def page(chromium, kit, request):
    """A page of the kit, opened by `page.goto(kit + '#numbers')`. Any page error or console
    error fails the test; its screenshot is kept under its test's name."""
    pg = chromium.new_page(viewport=VIEWPORT)
    problems = []
    pg.on("pageerror", lambda e: problems.append(f"page error: {e}"))
    pg.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
    out = os.environ.get("MK_JS_COVERAGE")
    if out:
        pg._kit_cdp = pg.context.new_cdp_session(pg)
        pg._kit_cdp.send("Profiler.enable")
        pg._kit_cdp.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})
    pg.problems = problems
    yield pg
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        _coverage(pg, Path(out))
    SHOTS.mkdir(parents=True, exist_ok=True)
    shot(pg, request.node.name)
    pg.close()
    assert problems == []


def shot(page, name: str) -> None:
    """The page as it is, kept as a PNG of 256 colours for the run's artifact."""
    from io import BytesIO

    from PIL import Image

    SHOTS.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    png = page.screenshot(full_page=True)
    Image.open(BytesIO(png)).convert("RGB").quantize(256).save(SHOTS / f"{safe}.png")


def open_page(page, kit: str, name: str):
    """A kit page by its name, drawn."""
    page.goto(f"{kit}#{name}")
    page.wait_for_selector(".kit-page h1")
    return page
