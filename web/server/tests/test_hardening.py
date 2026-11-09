"""The hardening page (requirements S17.5.8.6): a review's findings by area, the mutation runs'
records against the code as it is, and the path's steps, done when their pull request merges."""

import json
import tomllib

from moolakata import paths
from moolakata.dev import coverage, hardening, mutate

REVIEW = """# Review

| Id | Req | Sev | Conf | Status | Description |
|---|---|---|---|---|---|
| [CR3-1](#cr3-1) | S7.1 | Med | 2 | fixed `abc1234` (#16) | A budget's plan |
| [CR3-2](#cr3-2) | S7.9.1 | Low | 1 | open | A giving plan's receiver |
| [CR3-3](#cr3-3) | R3.7 | Low | 1 | question | A rule of no section |
| [CR3-4](#cr3-4) | S13.7 | Med | 1 | fixed `def5678`, `0123abc` (#32) | A row without its last bar
| [CR3-5](#cr3-5) | S4.3 | Low | 1 | rejected | Found not to hold |

### CR3-1: a budget's plan

- **Kind:** bug.
- **Code:** `web/server/src/moolakata/ui/budgets.py:10-20`, and `ledger/post.py`.

### CR3-2: a giving plan's receiver

- **Where:** the requirements only.

### CR3-3: a rule

Nothing named.

### CR3-4: a row

- **Code:** `web/ui/screens/account.js:53`.
"""


def test_a_finding_counts_in_the_area_of_its_code_or_else_of_its_section():
    got = {f["id"]: f for f in hardening.findings(REVIEW)}
    assert sorted(got) == [1, 2, 3, 4, 5]
    assert got[1] | {} == {"id": 1, "sev": "Med", "desc": "A budget's plan", "state": "fixed",
                           "pr": 16, "area": "server/budgets"}  # fmt: skip
    assert got[2]["area"] == "server/giving" and got[2]["state"] == "open"
    assert got[3]["area"] == hardening.OTHER and got[3]["state"] == "question"
    # A row missing its last bar still ends at its line; its code names the browser's screens.
    assert got[4]["desc"] == "A row without its last bar" and got[4]["pr"] == 32
    assert got[4]["area"] == "browser/screens"
    assert got[5]["state"] == "closed" and got[5]["area"] == "server/prices"


def file_row(path, lines):
    return {"path": path, "area": coverage.area_of(path), "lineCount": lines, "linesReached": lines,
            "branchCount": 0, "branchesReached": 0}  # fmt: skip


def test_a_module_counts_as_tested_until_its_content_changes():
    src = "web/server/src/"
    dates, panels = "moolakata/taxes/dates.py", "moolakata/taxes/panels.py"
    files = [
        file_row(src + "moolakata/taxes/dates.py", 100),
        file_row(src + "moolakata/taxes/panels.py", 300),
        file_row(src + "moolakata/ui/taxpanels.py", 50),
        file_row(src + "moolakata/loans/__init__.py", 80),
    ]
    recs = [
        {"name": "taxes", "pr": 38, "modules": [dates, panels],
         "content": {dates: "a1", panels: "b1"}},
        # Not settled yet: no pull request, so it doesn't count.
        {"name": "loans", "modules": ["moolakata/loans/__init__.py"], "content": {}},
    ]  # fmt: skip
    blobs = {dates: "a1", panels: "b2"}
    found = [{"id": 1, "sev": "Med", "state": "open", "area": "server/taxes"},
             {"id": 2, "sev": "Low", "state": "fixed", "area": "server/taxes"}]  # fmt: skip
    got = hardening.figures({"server/taxes": {}, "server/loans": {}}, files, found, recs, blobs)
    assert got["server/taxes"] == {"open": 1, "med": 1, "fixed": 1, "all": 2,
                                   "statements": 450, "current": 100, "stale": 300}  # fmt: skip
    assert got["server/loans"]["current"] == 0 and got["server/loans"]["statements"] == 80


def test_a_step_is_done_when_its_pull_request_has_merged(monkeypatch):
    monkeypatch.setattr(hardening, "merged", lambda history: {h["pr"] for h in history})
    plan = {"step": [
        {"kind": "med", "findings": [1, 2], "pr": 40, "what": "Two bugs"},
        {"kind": "sweep", "areas": ["server/taxes"], "pr": 41},
        {"kind": "sweep", "areas": ["server/loans"]},
    ]}  # fmt: skip
    found = [{"id": 1, "area": "server/budgets"}, {"id": 2, "area": "server/taxes"}]

    def point(pr, lines, fixed, current):
        return {"pr": pr, "areas": {"server/taxes": {"lines": lines, "branches": 80.0}},
                "hardening": {"server/taxes": {"fixed": fixed, "current": current}}}  # fmt: skip

    history = [point(39, 90.0, 3, 0), point(40, 90.5, 4, 0), point(41, 92.0, 9, 500)]
    got = hardening.steps(plan, found, history)
    assert [s["done"] for s in got] == [True, True, False]
    assert got[0]["areas"] == ["server/budgets", "server/taxes"] and got[2]["what"] == "Sweep"
    assert got[1]["result"] == {"server/taxes": {"fixed": 5, "mutated": 500, "lines": 1.5,
                                                 "branches": 0.0}}  # fmt: skip
    # A merge before the page kept its figures has no result to show.
    assert hardening.result({"pr": 39, "areas": ["server/taxes"]}, history) is None


def test_the_path_names_areas_and_findings_that_exist():
    plan = tomllib.loads(hardening.PATH.read_text())
    found = {f["id"] for f in hardening.findings((paths.ROOT / plan["review"]).read_text())}
    areas = {coverage.area_of(p.relative_to(paths.ROOT).as_posix())
             for p in coverage.SERVER.rglob("*.py")} | {hardening.OTHER, "connector"}  # fmt: skip
    areas |= {f"browser/{d}" for d in coverage.BROWSER_DIRS}
    for n, step in enumerate(plan["step"], 1):
        assert step["kind"] in ("before", "tracker", "med", "sweep"), n
        assert set(step.get("areas", [])) <= areas, (n, step.get("areas"))
        assert set(step.get("findings", [])) <= found, (n, step.get("findings"))
        assert step["kind"] != "med" or step["findings"], n


def test_the_page_carries_its_figures(monkeypatch):
    monkeypatch.setattr(hardening, "merged", lambda history: {32, 38})
    files = [file_row("web/server/src/moolakata/taxes/dates.py", 100)]
    areas = {"server/taxes": coverage.counted(1, 100, 100, 0, 0)}
    last = {"commit": "f" * 40, "pr": 50, "date": "2026-11-09T06:00:00-06:00", "subject": "x (#50)",
            "areas": areas, "hardening": hardening.entry_figures(areas, files)}  # fmt: skip
    text = hardening.page([last], files, "https://github.com/MojoKata/MoolaKata")
    assert "/*DATA*/" not in text
    data = json.loads(text.split('type="application/json">', 1)[1].split("</script>", 1)[0])
    assert [s["done"] for s in data["path"][:3]] == [True, True, False]
    assert {r["name"] for r in data["runs"]} >= {"taxes", "values"}
    taxes = next(a for a in data["areas"] if a["area"] == "server/taxes")
    assert taxes["hardening"]["statements"] == 100 and taxes["findings"]
    assert len(mutate.COUNTED) == 5


def test_a_run_s_times_flag_a_job_past_the_budget_and_uneven_parts():
    """REVIEW.md §11.7: a job over the budget, or parts more uneven than SPREAD, is split
    further before a step is signed off; a skipped job doesn't count."""
    from moolakata.dev import citimes

    def job(name, start, end, conclusion="success"):
        return {"name": name, "started_at": f"2026-11-09T04:{start}Z",
                "completed_at": f"2026-11-09T04:{end}Z", "conclusion": conclusion}  # fmt: skip

    jobs = [
        job("server tests 1 of 3 (static server)", "00:00", "04:00"),
        job("server tests 2 of 3 (server)", "00:05", "06:30"),
        job("server tests 3 of 3 (server)", "00:05", "04:30"),
        job("browser tests 1 of 2", "00:10", "05:00"),
        job("browser tests 2 of 2", "00:10", "05:30"),
        job("coverage", "06:40", "07:10"),
        job("coverage site", "00:00", "59:00", conclusion="skipped"),
    ]
    lines, todo = citimes.report(jobs)
    assert lines[0].startswith("run: 7m10s")
    assert lines[1].strip() == "6m25s  server tests 2 of 3 (server)  ⚠ over budget"
    assert todo == [
        "server tests 2 of 3 (server): 6m25s, past the 6m00s budget",
        "server tests: parts from 4m00s to 6m25s, uneven",
    ]
