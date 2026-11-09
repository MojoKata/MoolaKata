"""A mutation run's record (requirements S17.5.12, docs/mutation-testing.md): the outcomes
mutmut leaves in its .meta files, counted by file, and kept for the hardening page with the
first run, the settling run and each file's content."""

import argparse
import json
import subprocess

import pytest

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


# The CI baseline (.github/workflows/mutate.yml): the jobs, the test map, and the runs gathered.


def test_modules_are_packed_by_size_the_largest_first_and_a_large_one_alone():
    jobs = mutate.pack({"a.py": 700, "b.py": 400, "c.py": 300, "d.py": 1200, "e.py": 50}, 1000)
    assert jobs == [["d.py"], ["a.py", "c.py"], ["b.py", "e.py"]]


def test_the_plan_groups_by_area_skips_current_modules_and_keeps_to_the_globs():
    modules = {
        "moolakata/ledger/post.py": 600,
        "moolakata/ui/transactions.py": 600,  # a route module counts in the area it serves
        "moolakata/ledger/lots.py": 300,
        "moolakata/money.py": 100,
        "moolakata/loans/__init__.py": 500,
    }
    jobs = mutate.plan_jobs(
        modules, ["server/ledger", "server/core"], 1000, {"moolakata/ledger/lots.py"}
    )
    assert [(j["name"], j["area"], j["lines"], j["modules"]) for j in jobs] == [
        ("core-1", "server/core", 100, "moolakata/money.py"),
        ("ledger-1", "server/ledger", 600, "moolakata/ledger/post.py"),
        ("ledger-2", "server/ledger", 600, "moolakata/ui/transactions.py"),
    ]


def test_every_server_module_has_a_job_and_none_of_the_dev_tools_or_migrations():
    modules = mutate.server_modules()
    assert "moolakata/money.py" in modules and "moolakata/ui/items.py" in modules
    assert not [m for m in modules if m.startswith("moolakata/dev/") or "/versions/" in m]
    jobs = mutate.plan_jobs(modules, ["server/*"], 1000, set())
    planned = [m for j in jobs for m in j["modules"].split()]
    assert sorted(planned) == sorted(modules)
    assert all(j["lines"] <= 1000 or len(j["modules"].split()) == 1 for j in jobs)


def test_a_route_module_takes_the_tests_the_map_says_reach_it():
    """No test file imports ui/tokens.py; the map names those that reach it through HTTP."""
    testmap = {
        "moolakata/ui/tokens.py": ["tests/test_tokens.py"],
        "moolakata/ui/x/y.py": ["tests/test_y.py"],
    }
    assert "tests/test_tokens.py" not in mutate.tests_for(["moolakata/ui/tokens.py"], [])
    found = mutate.tests_for(["moolakata/ui/tokens.py"], [], testmap)
    assert "tests/test_tokens.py" in found
    assert mutate.mapped(["moolakata/ui/x/"], testmap) == {"tests/test_y.py"}
    # The slow ones never, whatever the map says.
    assert "tests/test_account_world.py" not in mutate.tests_for(
        ["moolakata/ui/tokens.py"], [], {"moolakata/ui/tokens.py": ["tests/test_account_world.py"]}
    )


def test_the_map_names_each_modules_test_files_from_the_contexts(tmp_path, monkeypatch):
    import coverage

    monkeypatch.setattr(mutate, "TESTMAP", tmp_path)
    module = str(mutate.SERVER / "src" / "moolakata" / "money.py")
    for part, ctx in enumerate(["tests/test_ids_money.py", "tests/test_ledger.py"]):
        data = coverage.CoverageData(basename=str(tmp_path / ".coverage"), suffix=f"part{part}")
        data.set_context(ctx)
        data.add_lines({module: [1, 2]})
        data.set_context("")  # what ran outside a test: not a test file
        data.add_lines({module: [3]})
        data.write()
    assert mutate.testmap(None) == 0
    got = json.loads((tmp_path / "map.json").read_text())
    assert got == {"moolakata/money.py": ["tests/test_ids_money.py", "tests/test_ledger.py"]}


def test_gather_records_each_areas_first_run_from_its_jobs_and_keeps_its_survivors(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(mutate, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(mutate, "BASELINE", tmp_path / "baseline")
    monkeypatch.setattr(mutate.paths, "WEB", tmp_path)
    run = tmp_path / ".dev" / "mutate-ci" / "123"
    for name, rel, codes in [("ledger-1", "moolakata/ledger/post.py", [1, 0]),
                             ("ledger-2", "moolakata/ui/transactions.py", [1, 1, 33]),
                             ("core-1", "moolakata/money.py", [0])]:  # fmt: skip
        d = run / f"mutation-{name}"
        meta(d / "src", rel, codes)
        area = "server/core" if name.startswith("core") else "server/ledger"
        (d / "job.json").write_text(json.dumps({"name": name, "area": area, "modules": rel}))
        (d / "survivors.txt").write_text(f"# {name}\n")
    assert mutate.gather(argparse.Namespace(run=["123"], no_record=False)) == 0
    ledger = json.loads((tmp_path / "records" / "baseline-ledger.json").read_text())
    assert ledger["modules"] == ["moolakata/ledger/post.py", "moolakata/ui/transactions.py"]
    assert (
        ledger["first"]["killed"],
        ledger["first"]["survived"],
        ledger["first"]["no tests"],
    ) == (3, 1, 1)
    assert "pr" not in ledger  # a first run, settled by the area's sweep
    survivors = (tmp_path / "baseline" / "ledger" / "survivors.txt").read_text()
    assert survivors == "# ledger-1\n# ledger-2\n"
    assert (tmp_path / "records" / "baseline-core.json").exists()


def test_record_reads_runs_export_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(mutate, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(mutate.paths, "ROOT", tmp_path)
    for name, codes in [("a", [1, 0]), ("b", [1])]:
        meta(tmp_path / name / "src", f"moolakata/{name}.py", codes)
    a = args(name="x", first=True, from_=[str(tmp_path / "a"), str(tmp_path / "b")])
    assert mutate.record(a) == 0
    got = json.loads((tmp_path / "records" / "x.json").read_text())
    assert got["modules"] == ["moolakata/a.py", "moolakata/b.py"] and got["first"]["killed"] == 2


def test_the_copys_root_web_is_the_copy_so_a_test_reads_the_same_file_by_either(
    tmp_path, monkeypatch
):  # fmt: skip
    """From mutants/, paths takes the copy for web/ and its parent for the root: a test that
    reads root/web/install/Dockerfile found nothing while root/web was the root itself."""
    root, web = tmp_path / "repo", tmp_path / "repo" / "web"
    for name in mutate.BESIDE:
        (web / name).mkdir(parents=True)
    (web / "install" / "Dockerfile").write_text("FROM x\n")
    for name in mutate.ABOVE:
        (root / name).mkdir(parents=True)
    copy = web / ".dev" / "mutate" / "web" / "server"
    copy.mkdir(parents=True)
    monkeypatch.setattr(mutate.paths, "ROOT", root)
    monkeypatch.setattr(mutate.paths, "WEB", web)
    monkeypatch.setattr(mutate, "COPY", copy)
    (copy.parent / "web").symlink_to(copy.parent)  # an older copy's link, put right
    for _ in range(2):  # and again, as each run makes the copy
        mutate.link_copy()
        seen_web, seen_root = copy, copy.parent
        for name in mutate.BESIDE:
            assert (seen_root / "web" / name).resolve() == (web / name).resolve()
            assert (seen_web / name).resolve() == (web / name).resolve()
        for name in mutate.ABOVE:
            assert (seen_root / name).resolve() == (root / name).resolve()
        assert (seen_root / "web" / "server").resolve() == copy.resolve()
        assert (seen_root / "web" / "install" / "Dockerfile").read_text() == "FROM x\n"


def test_gather_takes_a_later_runs_job_over_the_earlier_and_records_no_area_that_ran_nothing(
    tmp_path, monkeypatch
):  # fmt: skip
    monkeypatch.setattr(mutate, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(mutate, "BASELINE", tmp_path / "baseline")
    monkeypatch.setattr(mutate.paths, "WEB", tmp_path)

    def job(run, name, area, rel, codes):
        d = tmp_path / ".dev" / "mutate-ci" / run / f"mutation-{name}"
        meta(d / "src", rel, codes)
        (d / "job.json").write_text(json.dumps({"name": name, "area": area, "modules": rel}))

    # Run 1: auth-1 stopped before its first change, keys-1 too; ledger-1 ran.
    job("1", "auth-1", "server/auth", "moolakata/auth/users.py", [None, None])
    job("1", "keys-1", "server/keys", "moolakata/keys/files.py", [None])
    job("1", "ledger-1", "server/ledger", "moolakata/ledger/post.py", [1, 0])
    # Run 2: auth-1 again, run.
    job("2", "auth-1", "server/auth", "moolakata/auth/users.py", [1, 1])
    assert mutate.gather(argparse.Namespace(run=["1", "2"], no_record=False)) == 1  # keys-1
    records = tmp_path / "records"
    auth = json.loads((records / "baseline-auth.json").read_text())
    assert (auth["first"]["killed"], auth["first"]["not run"]) == (2, 0)
    assert (records / "baseline-ledger.json").exists()
    assert not (records / "baseline-keys.json").exists()


def test_the_plan_keeps_only_the_jobs_named_and_refuses_a_name_it_does_not_have(capsys):
    every = json.loads(_plan(capsys, []))
    names = [every[0]["name"], every[-1]["name"]]
    again = json.loads(_plan(capsys, ["--jobs", *names]))
    assert [j["name"] for j in again] == names
    assert again == [j for j in every if j["name"] in names]
    assert mutate.main(["plan", "--all", "--jobs", "nowhere-9"]) == 1


def _plan(capsys, extra):
    assert mutate.main(["plan", "--all", *extra]) == 0
    return capsys.readouterr().out


def test_modules_no_test_reaches_are_run_as_nothing_exported_as_unreached_and_named(
    tmp_path, monkeypatch, capsys
):  # fmt: skip
    """receipts/worker.py runs only as a subprocess: no test file imports or maps to it."""
    work = tmp_path / "work"
    monkeypatch.setattr(mutate, "WORK", work)
    monkeypatch.setattr(mutate, "COPY", work / "web" / "server")
    monkeypatch.setattr(mutate, "UNREACHED", work / "unreached.txt")
    monkeypatch.setattr(mutate, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(mutate, "BASELINE", tmp_path / "baseline")
    monkeypatch.setattr(mutate.paths, "WEB", tmp_path)
    monkeypatch.setattr(mutate, "make_copy", lambda: pytest.fail("no copy without tests"))
    (tmp_path / "map.json").write_text("{}")
    worker = "moolakata/receipts/worker.py"
    assert mutate.main(["run", worker, "--map", str(tmp_path / "map.json")]) == 0
    run = tmp_path / ".dev" / "mutate-ci" / "7"
    out = run / "mutation-receipts-3"
    assert mutate.main(["export", str(out), "--name", "receipts-3", "--area",
                        "server/receipts", "--modules", worker]) == 0  # fmt: skip
    assert json.loads((out / "job.json").read_text())["unreached"] is True
    meta(run / "mutation-receipts-1" / "src", "moolakata/receipts/parser.py", [1])
    (run / "mutation-receipts-1" / "job.json").write_text(json.dumps(
        {"name": "receipts-1", "area": "server/receipts", "modules": "x"}))  # fmt: skip
    capsys.readouterr()
    assert mutate.main(["gather", "7"]) == 0  # recorded, the unreached named
    assert f"no test file reaches {worker}" in capsys.readouterr().out
    assert (tmp_path / "records" / "baseline-receipts.json").exists()
