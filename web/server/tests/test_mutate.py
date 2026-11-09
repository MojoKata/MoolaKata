"""A mutation run's record (requirements S17.5.12, docs/mutation-testing.md): the outcomes
mutmut leaves in its .meta files, counted by file, and kept for the hardening page with the
first run, the settling run and each file's content."""

import argparse
import json
import subprocess

from moolakata.dev import mutate


def meta(src, rel, codes):
    path = src / f"{rel}.meta"
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = {f"{rel.replace('/', '.')}.x_f__mutmut_{i}": c for i, c in enumerate(codes, 1)}
    path.write_text(json.dumps({"exit_code_by_key": keys}))


def test_outcomes_are_counted_by_file_and_the_odd_ones_count_as_not_run(tmp_path):
    # killed (1), survived (0), no tests (33), timeout (36), not run (None), suspicious (99)
    meta(tmp_path, "moolakata/taxes/dates.py", [1, 1, 0, 33, 36, None, 99])
    meta(tmp_path, "moolakata/money.py", [3])
    by_file, _, survivors = mutate.outcomes(tmp_path)
    assert survivors == ["moolakata.taxes.dates.py.x_f__mutmut_3"]
    c = mutate.counts(by_file)
    assert {k: c[k] for k in mutate.COUNTED} == {
        "killed": 3, "timeout": 1, "survived": 1, "no tests": 1, "not run": 2,
    }  # fmt: skip
    assert c["files"]["moolakata/money.py"] == {
        "killed": 1, "timeout": 0, "survived": 0, "no tests": 0, "not run": 0,
    }  # fmt: skip


def args(**kw):
    return argparse.Namespace(**{"pr": None, "found": None, "equivalent": None, **kw})


def test_a_record_keeps_the_first_run_then_the_settling_one_with_each_files_content(tmp_path):
    meta(tmp_path, "moolakata/money.py", [1, 0, 0])
    first, _, _ = mutate.outcomes(tmp_path)
    record = mutate.recorded({"name": "money"}, first, True, args())
    assert record["modules"] == ["moolakata/money.py"]
    assert record["first"]["survived"] == 2 and "last" not in record
    meta(tmp_path, "moolakata/money.py", [1, 1, 1])
    last, _, _ = mutate.outcomes(tmp_path)
    done = mutate.recorded(
        record, last, False, args(pr=40, found=["CR3-460", "CR3-452"], equivalent=0)
    )
    assert done["first"]["survived"] == 2 and done["last"]["killed"] == 3
    assert (done["pr"], done["found"], done["equivalent"]) == (40, ["CR3-452", "CR3-460"], 0)
    # The content as git names it: what the checkout's HEAD would show for the same file.
    file = mutate.SERVER / "src" / "moolakata" / "money.py"
    named = subprocess.run(["git", "hash-object", str(file)], capture_output=True, text=True)
    assert done["content"] == {"moolakata/money.py": named.stdout.strip()}


def test_the_backfilled_records_name_files_that_exist():
    """Each record under docs/hardening/mutation/ names modules of the server as it is."""
    for path in sorted(mutate.RECORDS.glob("*.json")):
        record = json.loads(path.read_text())
        assert record["name"] == path.stem
        for module in record["modules"]:
            assert (mutate.SERVER / "src" / module).exists(), (path.name, module)
        assert set(record.get("content", {})) <= set(record["modules"])
