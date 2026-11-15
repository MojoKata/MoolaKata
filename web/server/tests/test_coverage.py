"""The coverage floor (requirements S17.5.8.4): raised to what was measured less a count of
lines and branches, larger for the browser app's areas, and never lowered; and the job
summary's table (S17.5.8.3)."""

import json

from moolakata.dev import coverage


def counts(lines, reached, branches, taken):
    return coverage.counted(1, lines, reached, branches, taken)


def test_the_floor_leaves_each_sides_slack_and_only_rises(monkeypatch, tmp_path):
    (tmp_path / "totals.json").write_text(
        json.dumps(
            {
                # The browser's slack is 40: two fifths of this area's branches.
                "browser/charts": counts(484, 323, 101, 80),
                # The server's is 3: in a large area, a tenth of a point.
                "server/core": counts(9000, 7900, 3000, 2250),
                "connector": counts(1000, 900, 100, 70),
                "browser/account-types": counts(478, 478, 0, 0),
                "server/keys": counts(1000, 800, 200, 120),
            }
        )
    )
    floor = tmp_path / "floor.json"
    floor.write_text(json.dumps({"server/keys": {"lines": 85.0, "branches": 50.0}}))
    monkeypatch.setattr(coverage, "OUT", tmp_path)
    monkeypatch.setattr(coverage, "FLOOR", floor)
    monkeypatch.setattr(coverage.paths, "ROOT", tmp_path)
    assert coverage.cmd_floor() == 0
    assert json.loads(floor.read_text()) == {
        "browser/charts": {"lines": 58.4, "branches": 39.6},
        "server/core": {"lines": 87.7, "branches": 74.9},
        "connector": {"lines": 89.7, "branches": 67.0},
        "browser/account-types": {"lines": 91.6},
        # Never lowered: lines stay at 85 though 79.7 was measured.
        "server/keys": {"lines": 85.0, "branches": 58.5},
    }


def test_totals_measured_without_the_counts_are_measured_again(monkeypatch, tmp_path):
    (tmp_path / "totals.json").write_text(
        json.dumps({"server/core": {"files": 1, "lines": 90.0, "branches": 80.0, "lineCount": 9}})
    )
    monkeypatch.setattr(coverage, "OUT", tmp_path)
    assert coverage.cmd_floor() == 1


def test_the_summary_shows_bars_counts_and_the_sums_last():
    areas = {
        "browser/app": counts(1970, 1793, 514, 483),
        "connector": counts(1604, 1352, 358, 251),
        "kit": counts(1000, 950, 200, 180),
        "server/core": counts(4560, 3998, 1382, 1039),
        "server/keys": counts(574, 464, 94, 59),
    }
    floors = {"server/keys": {"lines": 85.0, "branches": 62.0}}
    text = coverage.summary(areas, floors, None, None, ["server/keys"])
    rows = [r for r in text.splitlines() if r.startswith("| ")]
    assert rows[1] == (
        "| browser/app | 1 | 🟢 `█████████░` 91.0% | 1,793 of 1,970 | 🟢 `█████████░` 94.0% | "
        "483 of 514 | — |"
    )
    assert rows[5].startswith(
        "| server/keys ⚠ | 1 | 🟢 `████████░░` 80.8% | 464 of 574 | 🟡 `██████░░░░` 62.8% |"
    )
    assert [r.split(" | ")[0] for r in rows[-4:]] == [
        "| **Server**",
        "| **Browser**",
        "| **Kit**",
        "| **Overall**",
    ]
    # The browser app's areas, without the kit; the kit alone; everything.
    assert rows[-3].startswith("| **Browser** | 1 | 🟢 `█████████░` 91.0% | 1,793 of 1,970 |")
    assert rows[-2].startswith("| **Kit** | 1 | ⭐ `██████████` 95.0% | 950 of 1,000 |")
    assert rows[-1].startswith("| **Overall** | 5 | 🟢 `█████████░` 88.1% | 8,557 of 9,708 |")
    assert coverage.bar(None) == "—" and coverage.bar(4.9) == "🔴 `░░░░░░░░░░` 4.9%"


def test_a_figure_s_band_is_a_star_from_95_green_from_80_and_red_under_60():
    """S17.5.8: the bands, at their edges, each with one mark."""
    got = [coverage.band(v) for v in (0.0, 59.9, 60.0, 79.9, 80.0, 94.9, 95.0, 100.0)]
    low, fair, good, top = ("low", "🔴"), ("fair", "🟡"), ("good", "🟢"), ("top", "⭐")
    assert got == [low, low, fair, fair, good, good, top, top]


def test_a_route_module_counts_in_the_area_it_serves():
    """S17.5.8.1: ui/budgets.py counts with budgets/, ui/positions.py with options/; a route that
    serves no package stays in server/ui."""
    at = "web/server/src/moolakata/"
    assert coverage.area_of(at + "ui/budgets.py") == "server/budgets"
    assert coverage.area_of(at + "ui/positions.py") == "server/options"
    assert coverage.area_of(at + "ui/settings.py") == "server/ui"
    assert coverage.area_of(at + "ui/__init__.py") == "server/ui"
    assert coverage.area_of(at + "valuation.py") == "server/core"
    assert coverage.area_of(at + "store/entities/taxes.py") == "server/store"
    # The map names route modules that exist, each to a package that exists.
    for route, package in coverage.ROUTE_AREAS.items():
        assert (coverage.SERVER / "ui" / f"{route}.py").exists(), route
        assert (coverage.SERVER / package / "__init__.py").exists(), package
        assert not (coverage.SERVER / route / "__init__.py").exists(), f"{route} is a package"


def test_a_run_that_skipped_the_kit_s_tests_shows_its_sums_as_not_run():
    """S17.5.8.3: Kit and Overall aren't measured from the app's use of the kit alone; Server and
    Browser are measured the same way either way."""
    areas = {"browser/app": counts(100, 90, 10, 9), "server/core": counts(100, 80, 10, 8)}
    text = coverage.summary(areas, {}, None, None, [], kit=False)
    rows = [r for r in text.splitlines() if r.startswith("| **")]
    assert rows == [
        "| **Server** | 1 | 🟢 `████████░░` 80.0% | 80 of 100 | 🟢 `████████░░` 80.0% "
        "| 8 of 10 |  |",
        "| **Browser** | 1 | 🟢 `█████████░` 90.0% | 90 of 100 | 🟢 `█████████░` 90.0% "
        "| 9 of 10 |  |",
        "| **Kit** | — | not run (kit unchanged) | — | — | — | |",
        "| **Overall** | — | not run (kit unchanged) | — | — | — | |",
    ]


def test_the_report_leaves_the_kit_out_when_its_tests_were_skipped(monkeypatch, tmp_path):
    """S17.5.8.4: the kit's row, floor and files are left out; its floor isn't held. With its
    tests run, a kit below its floor fails the check."""
    files = {
        "web/ui/app/main.js": coverage.File("browser/app", {1, 2}, {3}),
        "web/ui/kit/button.js": coverage.File("kit", {1}, {2, 3, 4}),
    }
    floor = tmp_path / "floor.json"
    floor.write_text(json.dumps({"kit": {"lines": 90.0}, "browser/app": {"lines": 50.0}}))
    monkeypatch.setattr(coverage, "OUT", tmp_path)
    monkeypatch.setattr(coverage, "FLOOR", floor)
    monkeypatch.setattr(coverage, "measure", lambda: (files, coverage.totals(files)))
    monkeypatch.setattr(coverage, "base_ref", lambda: None)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    monkeypatch.setenv("MK_KIT_TESTED", "0")
    assert coverage.cmd_report(check=True) == 0
    assert list(json.loads((tmp_path / "totals.json").read_text())) == ["browser/app"]
    assert [f["area"] for f in json.loads((tmp_path / "files.json").read_text())] == ["browser/app"]
    summary = (tmp_path / "summary.md").read_text()
    assert "| kit |" not in summary and "| **Kit** | — | not run (kit unchanged)" in summary

    monkeypatch.setenv("MK_KIT_TESTED", "1")
    assert coverage.cmd_report(check=True) == 1
    assert "**Below the floor:** kit." in (tmp_path / "summary.md").read_text()


def test_the_kit_is_an_area_of_its_own_and_a_sum_of_one():
    """S17.5.8.1: the ui-kit counts outside the browser app's areas; its tests and pages aren't
    code."""
    assert coverage.area_of("web/ui/kit/button.js") == "kit"
    assert coverage.area_of("web/ui/kit/tests/button_test.js") is None
    assert coverage.area_of("web/ui/components/share.js") == "browser/components"
    assert [a for a in ("kit", "kitchen", "browser/kit") if coverage.in_sum(a, "kit")] == ["kit"]
    assert coverage.in_sum("browser/app", "browser/") and coverage.in_sum("connector", "")
    assert not coverage.in_sum("kit", "browser/")


def test_ci_s_headline_names_each_side_and_the_kit_when_measured(capsys):
    """S17.5.8.3: the notice with the headline."""
    areas = {"browser/app": counts(100, 90, 10, 9), "server/core": counts(100, 80, 10, 8)}
    coverage.annotate(areas, None)
    assert (
        capsys.readouterr().out == "::notice title=Coverage::server 80.0% of lines, browser 90.0%\n"
    )
    coverage.annotate({**areas, "kit": counts(100, 95, 0, 0)}, None)
    assert "browser 90.0%, kit 95.0%\n" in capsys.readouterr().out
