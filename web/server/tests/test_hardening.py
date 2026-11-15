"""The hardening page (requirements S17.5.8.6): the sweep's issues by area, the mutation runs'
records against the code as it is, and the path's steps, done when their issue is closed."""

import io
import json

from moolakata.dev import coverage, hardening, mutate

API = "https://api.github.com/repos/MojoKata/MoolaKata/issues/"


def issue(n, title, *labels, parent=None, state="open", reason=None, body=""):
    """An issue as GitHub's API gives it."""
    return {"number": n, "url": API + str(n), "title": title, "body": body, "state": state,
            "state_reason": reason, "labels": [{"name": x} for x in labels],
            "parent_issue_url": parent and API + str(parent)}  # fmt: skip


ISSUES = [
    issue(1, "H1.5 Med bugs in the server", "hardening", state="closed", reason="completed",
          body="Step 5 of the first hardening sweep (H1): done by #44."),
    issue(2, "H1.5-1 A budget's plan (CR3-25)", "hardening", "area:server/budgets", parent=1,
          state="closed", reason="completed", body="From review 3, severity Med. Fixed by #44."),
    issue(3, "H1.1 Values: the first mutation runs", "hardening", "area:server/prices",
          state="closed", reason="completed",
          body="done by #32.\n\n**Coverage gains it reported** (in points): prices +8.5 / +14.0."),
    issue(4, "H1.8 Sweep server/taxes", "hardening", "area:server/taxes"),
    issue(5, "H1.8-1 A tax rule (CR3-95)", "hardening", "area:server/taxes", parent=4,
          body="From code review 3 (**CR3-95**), severity Low."),
    issue(6, "H1.8-2 Who decides (CR3-367)", "hardening", "area:server/taxes", "question",
          parent=4),
    issue(7, "H1.8-3 Not a bug (CR3-345)", "hardening", "area:server/taxes", parent=4,
          state="closed", reason="not_planned"),
    issue(8, "H1.25 Dev tooling", "hardening", body="**Pull request:** #70"),
    issue(9, "H1.25-1 A finding named by its issue alone", "hardening", parent=8),
    issue(10, "Something else", "hardening"),
]  # fmt: skip


def test_a_sweep_s_steps_and_findings_come_from_its_issues():
    path, found = hardening.from_issues(ISSUES)
    assert [(s["n"], s["issue"], s["kind"], s["done"], s["pr"]) for s in path] == [
        (1, 3, "before", True, 32), (5, 1, "med", True, 44), (8, 4, "sweep", False, None),
        (25, 8, "tooling", False, 70)]  # fmt: skip
    assert path[0]["gains"] == "prices +8.5 / +14.0" and path[0]["areas"] == ["server/prices"]
    # A step with no area of its own covers its findings' areas.
    assert path[1]["areas"] == ["server/budgets"] and path[1]["findings"] == [2]
    assert path[2]["findings"] == [5, 6, 7] and path[3]["areas"] == [hardening.OTHER]
    got = {f["id"]: f for f in found}
    assert got[2] == {"id": 2, "cr": "CR3-25", "sev": "Med", "desc": "A budget's plan",
                      "state": "fixed", "pr": 44, "area": "server/budgets"}  # fmt: skip
    assert [got[n]["state"] for n in (5, 6, 7, 9)] == ["open", "question", "closed", "open"]
    assert got[5]["sev"] == got[6]["sev"] == "Low" and got[9]["cr"] is None
    assert got[9]["area"] == hardening.OTHER and 10 not in got


def test_the_issues_are_read_page_by_page(monkeypatch):
    pages = [[issue(n, f"H1.8-{n} x") for n in range(100)], [issue(100, "H1.8 Sweep")],
             [{"number": 101, "title": "a pull request", "pull_request": {}}]]  # fmt: skip
    asked = []

    def urlopen(req, timeout):
        asked.append((req.full_url, req.get_header("Authorization")))
        return io.BytesIO(json.dumps(pages[len(asked) - 1]).encode())

    monkeypatch.setattr(hardening.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    got = hardening.fetch_issues("MojoKata/MoolaKata")
    assert len(got) == 101 and len(asked) == 2
    assert "labels=hardening&state=all" in asked[0][0] and asked[1][0].endswith("page=2")
    assert asked[0][1] == "Bearer t"


def test_a_mutation_run_s_bugs_are_named_by_review_number_or_issue():
    found = hardening.from_issues(ISSUES)[1]
    recs = [{"found": ["CR3-95", "#9", "CR3-999"]}, {}]
    assert hardening.bug_ids(recs, found) == {5, 9}


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


def test_a_baseline_module_reads_changed_once_its_content_is_not_what_the_baseline_mutated():
    rules, users, dates = (
        "moolakata/rules.py",
        "moolakata/auth/users.py",
        "moolakata/taxes/dates.py",
    )
    recs = [
        {"name": "baseline-core", "modules": [rules, users],
         "first_content": {rules: "r1", users: "u1"}},
        # Settled since: its settled run is what counts, not the baseline's.
        {"name": "baseline-taxes", "pr": 50, "modules": [dates], "first_content": {dates: "d0"},
         "content": {dates: "d1"}},
        # A first run recorded before runs kept their content: nothing to tell.
        {"name": "values", "modules": ["moolakata/valuation.py"]},
    ]  # fmt: skip
    blobs = {rules: "r1", users: "u2", dates: "d1", "moolakata/valuation.py": "v"}
    assert hardening.baseline_runs(recs, blobs) == {rules: "current", users: "changed"}


def test_a_step_is_done_when_its_issue_is_closed():
    path = [{"n": 5, "done": True, "pr": 40, "areas": ["server/taxes"]},
            {"n": 8, "done": True, "pr": 41, "areas": ["server/taxes"]},
            {"n": 9, "done": False, "pr": None, "areas": ["server/loans"]}]  # fmt: skip

    def point(pr, lines, fixed, current):
        return {"pr": pr, "areas": {"server/taxes": {"lines": lines, "branches": 80.0}},
                "hardening": {"server/taxes": {"fixed": fixed, "current": current}}}  # fmt: skip

    history = [point(39, 90.0, 3, 0), point(40, 90.5, 4, 0), point(41, 92.0, 9, 500)]
    got = hardening.steps(path, history)
    assert [s["done"] for s in got] == [True, True, False] and got[2]["result"] is None
    assert got[1]["result"] == {"server/taxes": {"fixed": 5, "mutated": 500, "lines": 1.5,
                                                 "branches": 0.0}}  # fmt: skip
    # A merge before the page kept its figures has no result to show.
    assert hardening.result({"pr": 39, "areas": ["server/taxes"]}, history) is None


def test_the_page_carries_its_figures():
    files = [file_row("web/server/src/moolakata/taxes/dates.py", 100)]
    areas = {"server/taxes": coverage.counted(1, 100, 100, 0, 0)}
    last = {"commit": "f" * 40, "pr": 50, "date": "2026-11-09T06:00:00-06:00", "subject": "x (#50)",
            "areas": areas, "hardening": hardening.entry_figures(areas, files, ISSUES)}  # fmt: skip
    text = hardening.page([last], files, "https://github.com/MojoKata/MoolaKata", ISSUES)
    assert "/*DATA*/" not in text
    data = json.loads(text.split('type="application/json">', 1)[1].split("</script>", 1)[0])
    assert [s["done"] for s in data["path"]] == [True, True, False, False]
    assert data["issues"].endswith("/issues?q=label%3Ahardening+no%3Aparent-issue")
    assert {r["name"] for r in data["runs"]} >= {"taxes", "values"}
    taxes = next(a for a in data["areas"] if a["area"] == "server/taxes")
    assert taxes["hardening"]["statements"] == 100 and taxes["hardening"]["open"] == 2
    assert [f["id"] for f in taxes["findings"]] == [5, 6, 7]
    assert len(mutate.COUNTED) == 5


def test_a_run_s_times_flag_a_job_past_the_budget_and_uneven_parts():
    """REVIEW.md §11.7: a job over the budget, or parts more uneven than SPREAD that set the
    run's time, is split further before a step is signed off; uneven parts that don't set it
    aren't, and a skipped job doesn't count."""
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
        job("browser tests 3 of 3", "00:10", "02:10"),
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
