"""The coverage site (requirements S17.5.8): each merge's totals added to the history the
published site holds, never starting it over by mistake, and the pages built from it."""

import json
import re
import subprocess

import pytest

from moolakata.dev import coverage
from moolakata.dev import coverage_site as cs


def area(lines, branches, count=100):
    return {"files": 1, "lines": lines, "branches": branches, "lineCount": count}


def point(commit, areas, pr=None):
    return {"commit": commit, "date": "2026-10-30T06:00:00-05:00", "pr": pr,
            "subject": f"work <{commit}>", "areas": areas}  # fmt: skip


def site(served: dict):
    """A stand-in for the published site: what each path answers, None for a 404."""

    def get(url):
        path = url.removeprefix(cs.PUBLISHED).split("?")[0]
        answer = served.get(path)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return get


def test_the_history_is_read_back_and_never_started_over(monkeypatch):
    history = [point("a" * 40, {"server/core": area(90.0, 80.0)})]
    monkeypatch.setattr(cs, "get", site({"history.json": json.dumps(history).encode()}))
    assert cs.fetch_history(cs.PUBLISHED, "1") == history
    # No site at all: the first merge starts the history.
    monkeypatch.setattr(cs, "get", site({}))
    assert cs.fetch_history(cs.PUBLISHED, "1") == []
    # A site without its history is a mistake somewhere, not a fresh start.
    monkeypatch.setattr(cs, "get", site({"": b"<html>"}))
    with pytest.raises(SystemExit, match="not starting it over"):
        cs.fetch_history(cs.PUBLISHED, "1")


def test_a_run_done_again_replaces_its_own_point():
    one, two = point("1" * 40, {}), point("2" * 40, {})
    again = point("1" * 40, {"connector": area(50.0, None)})
    assert cs.add([one, two], again) == [two, again]
    assert cs.add([one], two) == [one, two]


def test_an_entry_names_its_pull_request(monkeypatch):
    def git(*args):
        out = "c" * 40 + "\n2026-10-30T06:00:00-05:00\nReview 3: the import claims (#19)\n"
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(coverage, "git", git)
    e = cs.entry({"connector": area(80.0, 70.0)})
    assert (e["commit"], e["pr"], e["subject"]) == (
        "c" * 40,
        19,
        "Review 3: the import claims (#19)",
    )
    monkeypatch.setattr(
        coverage, "git", lambda *a: subprocess.CompletedProcess(a, 0, "d" * 40 + "\nx\nNo PR\n", "")
    )
    assert cs.entry({})["pr"] is None


def test_server_and_browser_are_their_areas_weighted_by_lines():
    areas = {
        "server/core": area(100.0, 50.0, count=300),
        "server/ledger": area(50.0, None, count=100),
        "browser/app": area(40.0, 60.0),
    }
    h = point("e" * 40, areas)
    assert cs.figure(h, "server", "lines") == 87.5
    assert cs.figure(h, "server", "branches") == 50.0
    assert cs.figure(h, "browser", "lines") == 40.0
    assert cs.figure(h, "server/ledger", "branches") is None
    assert cs.figure(h, "server/gone", "lines") is None


def test_a_chart_breaks_where_an_area_was_not_measured():
    history = [
        point("1" * 40, {"server/core": area(90.0, 80.0)}, pr=1),
        point("2" * 40, {}, pr=2),
        point("3" * 40, {"server/core": area(91.0, 81.0)}, pr=3),
        point("4" * 40, {"server/core": area(92.0, 82.0)}, pr=4),
    ]
    svg = cs.chart(history, "server/core")
    lines = re.search(r'class="line lines" d="([^"]+)"', svg)[1]
    assert lines.count("M") == 2 and lines.count("L") == 1
    # The point alone and each series' last point carry a dot.
    assert svg.count('class="dot lines"') == 2 and svg.count('class="dot branches"') == 2
    assert ">#1</text>" in svg and ">#4</text>" in svg


def test_the_site_holds_the_reports_the_history_and_a_page(monkeypatch, tmp_path):
    out = tmp_path / "coverage"
    (out / "html" / "server").mkdir(parents=True)
    (out / "html" / "server" / "index.html").write_text("server report")
    totals = {"server/core": area(90.0, 80.0), "browser/app": area(60.0, None)}
    (out / "totals.json").write_text(json.dumps(totals))
    monkeypatch.setattr(coverage, "OUT", out)
    monkeypatch.setattr(cs, "SITE", out / "site")
    monkeypatch.delenv("MK_COVERAGE_SITE", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    before = point("0" * 40, {"server/core": area(89.0, 80.0)}, pr=17)
    monkeypatch.setattr(cs, "get", site({"history.json": json.dumps([before]).encode()}))

    assert cs.build() == 0
    history = json.loads((out / "site" / "history.json").read_text())
    assert len(history) == 2 and history[0]["commit"] == "0" * 40
    assert history[-1]["areas"] == totals
    assert (out / "site" / "server" / "index.html").read_text() == "server report"
    page = (out / "site" / "index.html").read_text()
    assert "<title>MoolaKata coverage</title>" in page
    assert "work &lt;" + "0" * 40 + "&gt;" in page  # an old subject, escaped
    assert "<td>90.0%</td><td class='delta'>+1.0</td>" in page
    assert page.count('<figure class="chart"') == 2 + len(totals)


def test_ci_fails_when_the_history_cannot_be_read(monkeypatch, tmp_path):
    (tmp_path / "totals.json").write_text("{}")
    monkeypatch.setattr(coverage, "OUT", tmp_path)
    monkeypatch.setattr(cs, "SITE", tmp_path / "site")
    monkeypatch.setattr(cs, "get", site({"history.json": OSError("unreachable")}))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "MojoKata/MoolaKata")
    with pytest.raises(OSError):
        cs.build()
    # A preview goes on without it.
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert cs.build() == 0
    assert len(json.loads((tmp_path / "site" / "history.json").read_text())) == 1


def test_the_site_is_the_repositorys_own_pages(monkeypatch):
    monkeypatch.delenv("MK_COVERAGE_SITE", raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "SomeOne/MoolaKata")
    assert cs.site_url() == "https://someone.github.io/MoolaKata/"
    monkeypatch.setenv("MK_COVERAGE_SITE", "http://localhost:8000")
    assert cs.site_url() == "http://localhost:8000/"
