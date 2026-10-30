"""The coverage floor (requirements S17.5.8.4): raised to what was measured less a count of
lines and branches, larger for the browser app's areas, and never lowered."""

import json

from moolakata.dev import coverage


def counts(lines, reached, branches, taken):
    return {
        "files": 1,
        "lines": coverage.pct(reached, lines),
        "branches": coverage.pct(taken, branches),
        "lineCount": lines,
        "linesReached": reached,
        "branchCount": branches,
        "branchesReached": taken,
    }


def test_the_floor_leaves_each_sides_slack_and_only_rises(monkeypatch, tmp_path):
    (tmp_path / "totals.json").write_text(
        json.dumps(
            {
                # The browser's slack is 20: a fifth of this area's branches.
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
        "browser/charts": {"lines": 62.6, "branches": 59.4},
        "server/core": {"lines": 87.7, "branches": 74.9},
        "connector": {"lines": 89.7, "branches": 67.0},
        "browser/account-types": {"lines": 95.8},
        # Never lowered: lines stay at 85 though 79.7 was measured.
        "server/keys": {"lines": 85.0, "branches": 58.5},
    }


def test_totals_measured_without_the_counts_are_measured_again(monkeypatch, tmp_path):
    (tmp_path / "totals.json").write_text(
        json.dumps({"server/core": {"files": 1, "lines": 90.0, "branches": 80.0, "lineCount": 9}})
    )
    monkeypatch.setattr(coverage, "OUT", tmp_path)
    assert coverage.cmd_floor() == 1
