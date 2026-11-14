"""The browser app's files (requirements S17.3) and the public demo.

The app is served under /ui/v/<version>/, with a one-year cache in a release; a build between
releases (a -dev version) and the dev server send no-cache, since their files change under one
version. Its page, index.html, is templated with the version and a fresh nonce for the import
map, and never cached. Any other path under /ui is a screen of the app, so it gets the page
too. /demo serves the hand-written clickable mockup under a sandbox of its own.
"""

import re
import secrets
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from . import paths
from .errors import Problem

# The directories of web/ui the browser may load; tests, the mockup builder and the vendored
# tarballs stay on the server.
SERVED_DIRS = frozenset(
    {
        "kit",
        "app",
        "api",
        "store",
        "screens",
        "components",
        "charts",
        "account-types",
        "styles",
        "assets",
        "guides",
        "vendor",
    }
)
# The ui-kit's own tests and pages (S17.3.10.4) are for its checks and the Pages site, not the app.
KIT_NOT_SERVED = frozenset({"tests", "pages"})
TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".png": "image/png",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
}
YEAR = "public, max-age=31536000, immutable"
# A release's version, three numbers: only its files are kept a year (S17.3.5, S17.10.2.2).
RELEASE = re.compile(r"\d+\.\d+\.\d+")

DEMO_CSP = (
    "sandbox allow-scripts allow-popups; default-src 'none'; "
    "script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; "
    "font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'none'"
)


def page_csp(nonce: str) -> str:
    return (
        f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; "
        "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )


class Static:
    def __init__(self, version: str, dev: bool, ui: Path = paths.UI, demo: Path = paths.DEMO):
        self.version = version
        self.dev = dev
        self.ui = ui.resolve()
        self.demo = demo
        self.template = (ui / "index.html").read_text()
        self._cache: dict[Path, bytes] = {}

    def page(self) -> HTMLResponse:
        nonce = secrets.token_urlsafe(18)
        html = (
            self.template.replace("{{version}}", self.version)
            .replace("{{nonce}}", nonce)
            .replace("{{dev}}", "1" if self.dev else "")
        )
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": page_csp(nonce),
            },
        )

    def file(self, version: str, rel: str) -> Response:
        if version != self.version:
            # A page from before an upgrade asking for an old file: the update pill reloads it.
            raise Problem(
                404,
                "old-version",
                "The app was upgraded; reload the page.",
                headers={"Cache-Control": "no-store"},
            )
        parts = rel.split("/")
        if not parts or parts[0] not in SERVED_DIRS or any(p in ("", ".", "..") for p in parts):
            raise Problem(404, "not-found", "Not found")
        if parts[0] == "vendor" and len(parts) < 3:
            # Only what vendor.py unpacked: not the tarballs, the manifest or the script.
            raise Problem(404, "not-found", "Not found")
        if parts[0] == "kit" and len(parts) > 2 and parts[1] in KIT_NOT_SERVED:
            raise Problem(404, "not-found", "Not found")
        target = (self.ui / rel).resolve()
        if not target.is_relative_to(self.ui) or not target.is_file():
            raise Problem(404, "not-found", "Not found")
        media = TYPES.get(target.suffix)
        if media is None:
            raise Problem(404, "not-found", "Not found")
        # Served from memory, on the event loop: a file read on a worker thread would wait
        # behind the API's requests when they are busy, and the page couldn't load.
        if self.dev:
            body = target.read_bytes()
        else:
            body = self._cache.get(target)
            if body is None:
                body = self._cache[target] = target.read_bytes()
        cache = YEAR if RELEASE.fullmatch(self.version) and not self.dev else "no-cache"
        return Response(body, media_type=media, headers={"Cache-Control": cache})

    def demo_page(self) -> Response:
        if not self.demo.is_file():
            raise Problem(404, "not-found", "The demo is not part of this installation.")
        return FileResponse(
            self.demo,
            media_type="text/html; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": DEMO_CSP,
            },
        )


def router(static: Static) -> APIRouter:
    r = APIRouter(include_in_schema=False)

    @r.get("/")
    def root():
        return RedirectResponse("/ui/", status_code=307)

    @r.get("/demo")
    def demo():
        return static.demo_page()

    @r.get("/ui")
    def ui_root():
        return RedirectResponse("/ui/", status_code=307)

    @r.get("/ui/v/{version}/{rel:path}")
    def ui_file(version: str, rel: str):
        return static.file(version, rel)

    @r.api_route("/ui/api/{rest:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
    def api_unknown(rest: str):
        # Registered after every API route (app.py includes this router last).
        raise Problem(404, "not-found", "Not found")

    @r.get("/ui/{rest:path}")
    def ui_page(rest: str):
        return static.page()

    return r
