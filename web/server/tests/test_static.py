import re

import pytest

from moolakata import paths
from moolakata.static import YEAR, Static


def test_root_redirects_to_ui(bare_client):
    r = bare_client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/ui/"


def test_page_is_templated_with_version_and_a_fresh_nonce(bare_client):
    a = bare_client.get("/ui/")
    b = bare_client.get("/ui/accounts/Acct_x")
    assert a.status_code == b.status_code == 200
    assert a.headers["cache-control"] == "no-store"
    version = paths.version()
    assert f"/ui/v/{version}/app/main.js" in a.text
    nonce_a = re.search(r'nonce="([^"]+)"', a.text).group(1)
    nonce_b = re.search(r'nonce="([^"]+)"', b.text).group(1)
    assert nonce_a != nonce_b
    csp = a.headers["content-security-policy"]
    assert f"script-src 'self' 'nonce-{nonce_a}'" in csp
    assert "style-src 'self';" in csp
    assert "unsafe" not in csp
    assert "frame-ancestors 'none'" in csp


def test_versioned_files_are_served(bare_client):
    version = paths.version()
    r = bare_client.get(f"/ui/v/{version}/app/main.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")


def test_only_a_releases_files_are_cached_for_a_year():
    """S17.3.5: a release's files never change under its version; a build between releases
    (S17.10.2.2) and the dev server change them under one."""
    for version, dev, cache in (
        ("0.2.0", False, YEAR),
        ("0.2.0-dev", False, "no-cache"),
        ("0.2.0", True, "no-cache"),
    ):
        r = Static(version, dev).file(version, "app/main.js")
        assert r.headers["cache-control"] == cache, (version, dev)


def test_an_old_version_is_not_found(bare_client):
    r = bare_client.get("/ui/v/0.0.0-old/app/main.js")
    assert r.status_code == 404
    assert r.json()["code"] == "old-version"


def test_only_the_served_directories_are_reachable(bare_client):
    version = paths.version()
    for rel in (
        "index.html",
        "deno.json",
        "vendor/vendor.py",
        "vendor/manifest.json",
        "tests/run.js",
        "mockup/build.py",
        "app/../deno.json",
        "app/%2e%2e/deno.json",
        # The ui-kit's own tests and pages (S17.3.10.4): its checks' and the Pages site's.
        "kit/tests/assert.js",
        "kit/pages/index.html",
        "kit/pages/catalog.js",
    ):
        r = bare_client.get(f"/ui/v/{version}/{rel}")
        assert r.status_code == 404, rel
    # The kit itself is the app's: its modules and its theme.
    for rel in ("kit/fields.js", "kit/theme/tokens.css", "kit/theme/icons.svg"):
        assert bare_client.get(f"/ui/v/{version}/{rel}").status_code == 200, rel


def test_unknown_api_paths_are_problems_not_the_page(bare_client):
    r = bare_client.get("/ui/api/nothing-here")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["status"] == 404
    assert body["errorId"].startswith("err_")
    assert body["errors"] == []


def test_demo_is_public_and_sandboxed(bare_client):
    r = bare_client.get("/demo")
    assert r.status_code == 200
    assert "MOCK" in r.text
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox allow-scripts allow-popups;")
    assert "allow-same-origin" not in csp
    assert "connect-src 'none'" in csp


def test_the_page_says_whether_the_guides_screenshots_are_here(tmp_path):
    """S12.7.5: a release carries the help guides' screenshots; a checkout has them only once
    made or downloaded, and without them the page asks for none."""
    ui = tmp_path / "ui"
    (ui / "guides").mkdir(parents=True)
    (ui / "index.html").write_text('<meta name="mk-shots" content="{{shots}}">')
    shown = lambda: Static("0.2.0", False, ui=ui).page().body.decode()  # noqa: E731
    assert shown() == '<meta name="mk-shots" content="">'
    (ui / "guides" / "shots").mkdir()
    assert shown() == '<meta name="mk-shots" content="">', "an empty folder holds none"
    (ui / "guides" / "shots" / "dashboard.png").write_bytes(b"\x89PNG")
    assert shown() == '<meta name="mk-shots" content="1">'


def test_a_file_outside_the_app_missing_or_of_no_served_type_is_not_found(tmp_path):
    """S17.3.5: only the app's own files, of the types it serves, are served; a link out of
    the app's folder is never followed."""
    from moolakata.errors import Problem

    ui = tmp_path / "ui"
    (ui / "app").mkdir(parents=True)
    (ui / "index.html").write_text("")
    (ui / "app" / "main.js").write_text("export {};")
    (ui / "app" / "notes.txt").write_text("# notes")
    (tmp_path / "secret.js").write_text("the data directory's")
    (ui / "app" / "out.js").symlink_to(tmp_path / "secret.js")
    static = Static("0.2.0", False, ui=ui)
    assert static.file("0.2.0", "app/main.js").body == b"export {};"
    (ui / "app" / "main.js").write_text("changed under a release")
    assert static.file("0.2.0", "app/main.js").body == b"export {};", "a release's, kept"
    for rel in ("app/out.js", "app/gone.js", "app/notes.txt"):
        with pytest.raises(Problem) as e:
            static.file("0.2.0", rel)
        assert (e.value.status, e.value.code) == (404, "not-found"), rel


def test_an_installation_without_the_demo_says_so(tmp_path):
    from moolakata.errors import Problem

    (tmp_path / "index.html").write_text("")
    static = Static("0.2.0", False, ui=tmp_path, demo=tmp_path / "MoolaKata-mock.html")
    with pytest.raises(Problem) as e:
        static.demo_page()
    assert (e.value.status, e.value.detail) == (
        404,
        "The demo is not part of this installation.",
    )


def test_the_apps_address_without_its_slash_leads_to_the_app(bare_client):
    r = bare_client.get("/ui", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/ui/"
