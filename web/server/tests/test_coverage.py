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
    assert rows[4].startswith(
        "| server/keys ⚠ | 1 | 🟢 `████████░░` 80.8% | 464 of 574 | 🟡 `██████░░░░` 62.8% |"
    )
    assert [r.split(" | ")[0] for r in rows[-3:]] == [
        "| **Server**",
        "| **Browser**",
        "| **Overall**",
    ]
    assert rows[-1].startswith("| **Overall** | 4 | 🟢 `█████████░` 87.4% | 7,607 of 8,708 |")
    assert coverage.bar(None) == "—" and coverage.bar(4.9) == "🔴 `░░░░░░░░░░` 4.9%"


def test_a_figure_s_band_is_green_from_80_and_red_under_60():
    """S17.5.8: the bands, at their edges."""
    got = [coverage.band(v)[0] for v in (0.0, 59.9, 60.0, 79.9, 80.0, 100.0)]
    assert got == ["low", "low", "fair", "fair", "good", "good"]


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
