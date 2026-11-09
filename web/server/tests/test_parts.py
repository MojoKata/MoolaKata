"""CI's parts split by measured time (S17.10.1, tests/parts.py): every test in exactly one
part, an xdist_group's tests together, the heavy ones spread, and the times gathered from a
run's parts."""

import json

import parts

from moolakata.dev import citimes


def test_the_heaviest_go_first_each_to_the_part_with_the_least():
    assert parts.assign([30, 30, 30, 30, 1, 1, 1, 1], 4) == [0, 1, 2, 3, 0, 1, 2, 3]
    # 10 and 6 apart, 5 beside the 6, then 4 beside the 10: 14 / 11.
    assert parts.assign([4, 10, 5, 6], 2) == [0, 0, 1, 1]
    # Equal weights spread in order, as the count's split did.
    assert parts.assign([1.0] * 7, 3) == [0, 1, 2, 0, 1, 2, 0]


def items():
    """Four worlds of 30 s that a split by count put in one part, a group, short tests."""
    out = [(f"tests/test_w.py::test_a_world[{i}]", None) for i in range(28)]
    out += [("tests/test_g.py::test_one", "g"), ("tests/test_g.py::test_two", "g")]
    out += [(f"tests/test_s.py::test_{i}", None) for i in range(40)]
    return out


TIMES = {f"tests/test_w.py::test_a_world[{i}]": 30.0 for i in range(0, 28, 7)}
TIMES |= {"tests/test_g.py::test_one": 20.0, "tests/test_g.py::test_two": 20.0}


def test_every_test_is_in_exactly_one_part_and_a_group_stays_whole():
    tests = items()
    chosen = [parts.choose(tests, k, 7, TIMES, 0.2) for k in range(1, 8)]
    for i, _ in enumerate(tests):
        assert sum(c[i] for c in chosen) == 1, tests[i]
    group = [k for k, c in enumerate(chosen) for i, t in enumerate(tests) if c[i] and t[1] == "g"]
    assert len(set(group)) == 1 and len(group) == 2
    # The same choice every time: each xdist worker makes it on its own.
    assert chosen == [parts.choose(tests, k, 7, TIMES, 0.2) for k in range(1, 8)]


def test_the_heavy_ones_are_spread_where_counting_put_them_together():
    """Every seventh test is a 30 s world: by count all four fell in part 1."""
    tests = items()
    by_count = [sum(TIMES.get(t, 0.2) for i, (t, _) in enumerate(tests) if i % 7 == k)
                for k in range(7)]  # fmt: skip
    by_time = []
    for k in range(1, 8):
        keep = parts.choose(tests, k, 7, TIMES, 0.2)
        by_time.append(sum(TIMES.get(t, 0.2) for (t, _), ok in zip(tests, keep, strict=True) if ok))
    assert max(by_count) > 120 and max(by_time) <= 42
    assert sum(by_time) == sum(by_count)


def test_a_run_writes_its_long_tests_by_name_and_the_short_ones_as_a_total():
    r = parts.Recorder()
    for phase in (0.5, 0.75, 0.1):  # setup, call, teardown
        r.add("tests/test_a.py::test_long", phase)
    r.add("tests/test_a.py::test_short", 0.25)
    r.add("tests/test_a.py::test_other", 0.25)
    assert r.written() == {"tests": {"tests/test_a.py::test_long": 1.4}, "shortTotal": 0.5,
                           "shortCount": 2}  # fmt: skip


def test_a_runs_parts_are_gathered_into_one_file(tmp_path):
    a = {"tests": {"tests/test_a.py::x": 3.0}, "shortTotal": 1.0, "shortCount": 4}
    b = {"tests": {"tests/test_b.py::y": 2.0}, "shortTotal": 2.0, "shortCount": 8}
    assert citimes.gathered([a, b]) == {
        "short": 0.25, "tests": {"tests/test_a.py::x": 3.0, "tests/test_b.py::y": 2.0},
    }  # fmt: skip
    path = tmp_path / "durations.json"
    path.write_text(json.dumps(citimes.gathered([a, b])))
    assert parts.load(path) == ({"tests/test_a.py::x": 3.0, "tests/test_b.py::y": 2.0}, 0.25)
    assert parts.load(tmp_path / "none.json") == ({}, 1.0)


def test_the_committed_times_name_tests_of_at_least_keep_seconds():
    if not parts.DURATIONS.exists():
        return
    times, short = parts.load()
    assert 0 < short < parts.KEEP
    assert all(t >= parts.KEEP and "::" in n for n, t in times.items())
