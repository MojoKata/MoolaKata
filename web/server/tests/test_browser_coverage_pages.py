"""The coverage site's pages open in Chromium without an error (requirements S17.5.8,
S17.5.8.6): the hardening page draws its tables in the browser, so a script error would publish
an empty page that no check of the built HTML would notice."""

import json

import pytest
from test_hardening import ISSUES

from moolakata.dev import coverage, hardening
from moolakata.dev import coverage_site as cs

pytestmark = pytest.mark.browser


def area(lines, branches):
    """An area of one file, 1,000 lines and as many branches, at these percentages."""
    return coverage.counted(1, 1000, round(lines * 10), 1000, round(branches * 10))


@pytest.fixture
def site(monkeypatch, tmp_path):
    """The site built from areas in every band, a merge before them, and a sweep's issues."""
    out = tmp_path / "coverage"
    (out / "html").mkdir(parents=True)
    totals = {"server/core": area(97.2, 91.0), "server/taxes": area(92.4, 83.2),
              "browser/app": area(86.4, 89.8), "kit": area(98.4, 95.5),
              "connector": area(70.0, 55.0)}  # fmt: skip
    (out / "totals.json").write_text(json.dumps(totals))
    (out / "files.json").write_text("[]")
    before = {"commit": "0" * 40, "date": "2026-11-14T06:00:00-05:00", "pr": 553,
              "subject": "before", "areas": {k: area(90.0, 85.0) for k in totals}}  # fmt: skip
    monkeypatch.setattr(coverage, "OUT", out)
    monkeypatch.setattr(cs, "SITE", out / "site")
    monkeypatch.setattr(cs, "MOCKUPS", tmp_path / "no-mockups")
    monkeypatch.setattr(cs, "get", lambda url: json.dumps([before]).encode())
    monkeypatch.setattr(hardening, "fetch_issues", lambda repo: ISSUES)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert cs.build() == 0
    return out / "site"


@pytest.mark.parametrize("name", ["index", "hardening"])
def test_a_coverage_page_opens_without_an_error_and_stars_its_top_figures(browser, site, name):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    problems = []
    page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
    page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
    page.goto((site / f"{name}.html").as_uri())
    assert problems == []
    # Every row drawn, and the figures at 95% or more starred: server/core's lines, the kit's
    # lines and branches, and the Kit sum's on the coverage page.
    assert page.locator("td .star[title]").count() >= 3
    page.close()
