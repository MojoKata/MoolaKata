"""A mutation run's record (requirements S17.5.12, docs/mutation-testing.md): the outcomes
mutmut leaves in its .meta files, counted by file, and kept for the hardening page with the
first run, the settling run and each file's content."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import tomllib

import pytest

from moolakata.dev import mutate


@pytest.fixture(autouse=True)
def _one_commit(monkeypatch):
    """The runs gathered here all ran one commit, where each module reads the same."""
    monkeypatch.setattr(mutate, "head_of", lambda repo, run: f"commit-{run}")
    monkeypatch.setattr(mutate, "blob_at", lambda repo, commit, rel: f"blob-{rel}")
    monkeypatch.setattr(mutate, "remade", lambda missing, content: {})  # no copy made here


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
    assert json.loads((tmp_path / "records" / "survivors" / "ledger.json").read_text()) == [
        {"name": "moolakata.ledger.post.py.x_f__mutmut_2", "module": "moolakata/ledger/post.py",
         "function": "f", "line": None, "removed": [], "added": []},
    ]  # fmt: skip
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


def test_the_copy_is_laid_out_as_the_repository_so_a_test_reads_by_either_path(
    tmp_path, monkeypatch
):  # fmt: skip
    """From mutants/, paths takes the copy for web/ and its parent for the root: a test that read
    root/web/install/Dockerfile found nothing while the copy was web/server, and a server path
    taken relative to the root read server/src/... (no area)."""
    assert mutate.COPY == mutate.WORK / "web"
    root, web = tmp_path / "repo", tmp_path / "repo" / "web"
    for name in mutate.BESIDE:
        (web / name).mkdir(parents=True)
    (web / "install" / "Dockerfile").write_text("FROM x\n")
    for name in mutate.ABOVE:
        (root / name).mkdir(parents=True)
    copy = web / ".dev" / "mutate" / "web"
    copy.mkdir(parents=True)
    monkeypatch.setattr(mutate.paths, "ROOT", root)
    monkeypatch.setattr(mutate.paths, "WEB", web)
    monkeypatch.setattr(mutate, "COPY", copy)
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
        server = seen_web / "server" / "src"
        assert server.relative_to(seen_root).as_posix() == "web/server/src"


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
    # Run 2 from a fork, by owner/repo:id; both already downloaded.
    given = ["1", "someone/MoolaKata:2"]
    assert mutate.gather(argparse.Namespace(run=given, no_record=False)) == 1  # keys-1
    records = tmp_path / "records"
    auth = json.loads((records / "baseline-auth.json").read_text())
    assert (auth["first"]["killed"], auth["first"]["not run"]) == (2, 0)
    assert (records / "baseline-ledger.json").exists()
    assert not (records / "baseline-keys.json").exists()


def _job(root, run, name, area, rel, codes, estimates=None):
    d = root / ".dev" / "mutate-ci" / run / f"mutation-{name}"
    meta(d / "src", rel, codes)
    if estimates is not None:
        path = d / "src" / f"{rel}.meta"
        data = json.loads(path.read_text())
        data["estimated_durations_by_key"] = estimates
        path.write_text(json.dumps(data))
    (d / "job.json").write_text(json.dumps({"name": name, "area": area, "modules": rel}))
    return d


def test_gather_takes_each_changes_outcome_from_whichever_job_finished_it(tmp_path, monkeypatch):
    monkeypatch.setattr(mutate, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(mutate, "BASELINE", tmp_path / "baseline")
    monkeypatch.setattr(mutate.paths, "WEB", tmp_path)
    users = "moolakata/auth/users.py"
    _job(tmp_path, "1", "auth-1", "server/auth", users, [1, None, None, None])
    _job(tmp_path, "2", "auth-1.r1-1", "server/auth", users, [None, 0, 1, None])
    # keys-1 ran nothing, then a job finishing its changes ran one: its area is recorded.
    _job(tmp_path, "1", "keys-1", "server/keys", "moolakata/keys/files.py", [None, None])
    _job(tmp_path, "2", "keys-1.r1-1", "server/keys", "moolakata/keys/files.py", [None, 1])
    assert mutate.gather(argparse.Namespace(run=["1", "2"], no_record=False)) == 0
    first = json.loads((tmp_path / "records" / "baseline-auth.json").read_text())["first"]
    assert (first["killed"], first["survived"], first["not run"]) == (2, 1, 1)
    assert sum(first[k] for k in mutate.COUNTED) == 4  # each change once, not once a job
    assert (tmp_path / "records" / "baseline-keys.json").exists()


def test_the_changes_left_unrun_are_split_by_the_slowest_estimate_and_dealt_out(tmp_path):
    users = "moolakata/auth/users.py"
    # A job may take 2 * 240 min * 4 workers of worst cases: 3 of 38,400 s each.
    worst = 2 * mutate.REST_MINUTES * 60 * mutate.REST_WORKERS / 3
    estimates = {"moolakata.auth.users.py.x_f__mutmut_1": worst}
    # And no more than half what the first run finished in its 330 minutes, scaled to 240: of
    # 9 reached, 3 (at 8 reached, 2).
    codes = [1] * 9 + [None] * 7
    jobs = {
        "auth-1": _job(tmp_path, "1", "auth-1", "server/auth", users, codes, estimates),
        "core-1": _job(tmp_path, "1", "core-1", "server/core", "moolakata/money.py", [1, 0]),
        # Stopped before its first change: run again by name, not here.
        "keys-1": _job(tmp_path, "1", "keys-1", "server/keys", "moolakata/keys/files.py", [None]),
    }
    got, names = mutate.rest_jobs(jobs)
    assert [j["name"] for j in got] == ["auth-1.r1-1", "auth-1.r1-2", "auth-1.r1-3"]
    unrun = sorted(f"moolakata.auth.users.py.x_f__mutmut_{i}" for i in range(10, 17))
    assert names["auth-1.r1-1"] == unrun[0::3]
    assert sorted(n for these in names.values() for n in these) == unrun
    assert got[0] == {
        "name": "auth-1.r1-1",
        "area": "server/auth",
        "lines": 0,
        "size": "3 changes",
        "modules": users,
        "only": "auth-1.r1-1.txt",
    }
    # A round left changes unrun again: the next round's jobs are numbered after it.
    jobs["auth-1.r1-2"] = _job(
        tmp_path, "2", "auth-1.r1-2", "server/auth", users, [None] * 9 + [1, 1] + [None] * 5
    )
    again, names = mutate.rest_jobs(jobs)
    assert {j["name"].rsplit("-", 1)[0] for j in again} == {"auth-1.r2"}
    assert sorted(n for these in names.values() for n in these) == unrun[2:]
    # The first run reached fewer: the jobs are smaller than the estimates allow.
    fewer = _job(tmp_path, "3", "auth-1", "server/auth", users, [1] * 8 + [None] * 8, estimates)
    assert [len(x) for x in mutate.rest_jobs({"auth-1": fewer})[1].values()] == [2, 2, 2, 2]


def test_a_later_round_is_sized_by_the_slowest_job_of_the_round_that_left_its_changes(tmp_path):
    money = "moolakata/money.py"
    # The first run reached 30 of 50: jobs of 30 * 240 / 330 / 2, 10 each, for the 20 left.
    first = _job(tmp_path, "1", "core-1", "server/core", money, [1] * 30 + [None] * 20)
    assert [len(x) for x in mutate.rest_jobs({"core-1": first})[1].values()] == [10, 10]
    jobs = {"core-1": first}
    for name, codes in [
        ("core-1.r1-1", [None] * 30 + [1] * 10 + [None] * 10),
        # Out of time at 4 of its 10: the 6 left are slower still, a job of 4 * 240 / 330 / 2.
        ("core-1.r1-2", [None] * 40 + [0] * 4 + [None] * 6),
        # Stopped before its first change: it says nothing of the pace.
        ("core-1.r1-3", [None] * 50),
    ]:
        jobs[name] = _job(tmp_path, "2", name, "server/core", money, codes)
    got, names = mutate.rest_jobs(jobs)
    assert [j["name"] for j in got] == [f"core-1.r2-{k}" for k in range(1, 7)]
    assert [len(x) for x in names.values()] == [1] * 6


def test_the_plan_for_the_rest_writes_each_jobs_changes_for_run_to_read(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(mutate.paths, "WEB", tmp_path)
    _job(tmp_path, "7", "auth-1", "server/auth", "moolakata/auth/users.py", [1, None], {})
    out = tmp_path / "rest"
    assert mutate.main(["plan", "--rest", "someone/MoolaKata:7", "--rest-dir", str(out)]) == 0
    jobs = json.loads(capsys.readouterr().out)
    assert [j["name"] for j in jobs] == ["auth-1.r1-1"]
    listed = out / jobs[0]["only"]
    assert listed.read_text().split() == ["moolakata.auth.users.py.x_f__mutmut_2"]
    # With --jobs, only those baseline jobs' unrun changes.
    _job(tmp_path, "7", "keys-1", "server/keys", "moolakata/keys/files.py", [1, None], {})
    named = ["plan", "--rest", "7", "--jobs", "keys-1", "--rest-dir", str(tmp_path / "r2")]
    assert mutate.main(named) == 0
    assert [j["name"] for j in json.loads(capsys.readouterr().out)] == ["keys-1.r1-1"]
    a = argparse.Namespace(only=["x.y__mutmut_1"], only_file=str(listed), workers=4)
    assert mutate.mutmut_command(a)[-2:] == [
        "x.y__mutmut_1",
        "moolakata.auth.users.py.x_f__mutmut_2",
    ]
    assert (
        mutate.mutmut_command(argparse.Namespace(only=None, only_file=None, workers=4))[-1] == "4"
    )


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


def test_mutmuts_tests_run_in_one_process_and_drop_a_passing_tests_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(mutate, "COPY", tmp_path)
    monkeypatch.setattr(mutate, "SERVER", tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n\n[tool.mutmut]\nold = 1\n')
    mutate.configure(["moolakata/money.py"], ["tests/test_money.py"])
    got = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert "old" not in got["tool"]["mutmut"]
    assert got["tool"]["mutmut"]["only_mutate"] == ["src/moolakata/money.py"]
    assert got["tool"]["mutmut"]["pytest_add_cli_args"] == [
        "-p", "no:xdist", "-p", "no:cacheprovider", "-o", "tmp_path_retention_policy=failed",
        "-p", "moolakata.dev.mutant_name",
    ]  # fmt: skip
    assert got["tool"]["mutmut"]["process_isolation"] == "forkserver"


def test_conftest_imported_again_closes_the_clients_an_earlier_import_opened():
    """mutmut runs several pytest sessions in one process: each imports conftest again, while
    a test module keeps the sign_in it first imported. One list, opened.py's, for all of them."""
    import conftest
    import opened

    spec = importlib.util.spec_from_file_location("conftest_again", conftest.__file__)
    again = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(again)
    assert again.opened.clients is conftest.opened.clients is opened.clients
    assert not hasattr(conftest, "_signed_in")


def test_conftest_loads_while_the_mapping_raises_as_under_mutmuts_forced_failure(monkeypatch):
    """mutmut checks that a change can fail the tests by making every changed function raise:
    called as conftest loads, a raising map_all was pytest's usage error (exit 4), which mutmut
    takes for a broken command, so a job changing mapping.py never ran."""
    import conftest

    from moolakata.store import mapping

    def raising():
        raise RuntimeError("forced failure")

    monkeypatch.setattr(mapping, "map_all", raising)
    spec = importlib.util.spec_from_file_location("conftest_failing", conftest.__file__)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


def test_a_worker_past_its_memory_is_named_and_its_change_counted_killed(tmp_path):
    workers = {
        11: ("m.x_f__mutmut_1", 0.8),
        12: ("m.x_f__mutmut_2", 3.1),
        13: ("m.x_g__mutmut_1", 3.0),
    }
    assert mutate.runaways(workers, 3.0) == [12]
    meta(tmp_path, "moolakata/money.py", [mutate.OUT_OF_MEMORY, 0])
    by_file, _, survivors = mutate.outcomes(tmp_path)
    assert by_file["moolakata/money.py"]["killed"] == 1 and len(survivors) == 1


def test_the_signal_that_stops_a_worker_ends_python_with_the_code_counted_killed():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    time.sleep(0.5)
    os.kill(child.pid, -mutate.OUT_OF_MEMORY)
    assert child.wait(timeout=10) == mutate.OUT_OF_MEMORY


def test_a_changes_worker_takes_the_name_the_watcher_finds(monkeypatch):
    from moolakata.dev import mutant_name

    named = []
    monkeypatch.setattr(mutant_name, "title", named.append)
    for under_test in ("stats", "fail", "", "moolakata.money.x_parse__mutmut_3"):
        monkeypatch.setenv("MUTANT_UNDER_TEST", under_test)
        mutant_name.pytest_configure(None)
    assert named == ["mutmut: moolakata.money.x_parse__mutmut_3"]


def test_gather_keeps_each_modules_content_as_its_runs_ran_it_and_refuses_code_that_differs(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(mutate, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(mutate, "BASELINE", tmp_path / "baseline")
    monkeypatch.setattr(mutate.paths, "WEB", tmp_path)
    users, roles = "moolakata/auth/users.py", "moolakata/auth/roles.py"
    d = _job(tmp_path, "1", "auth-1", "server/auth", users, [1, None])
    # roles.py has nothing mutmut changes: its content is kept all the same.
    (d / "job.json").write_text(json.dumps(
        {"name": "auth-1", "area": "server/auth", "modules": f"{users} {roles}"}))  # fmt: skip
    _job(tmp_path, "2", "auth-1.r1-1", "server/auth", users, [None, 0])
    assert mutate.gather(argparse.Namespace(run=["1", "2"], no_record=False)) == 0
    got = json.loads((tmp_path / "records" / "baseline-auth.json").read_text())
    assert got["first_content"] == {roles: f"blob-{roles}", users: f"blob-{users}"}
    assert json.loads((tmp_path / ".dev/mutate-ci/2/run.json").read_text())["commit"] == "commit-2"
    # Run 2 saw another users.py: the outcomes don't add up, so the area isn't recorded.
    (tmp_path / "records" / "baseline-auth.json").unlink()
    monkeypatch.setattr(mutate, "blob_at", lambda repo, commit, rel: f"{commit}-{rel}")
    assert mutate.gather(argparse.Namespace(run=["1", "2"], no_record=False)) == 1
    assert f"changed between the runs, so their areas are not recorded (run them again on one " \
           f"commit): {users}" in capsys.readouterr().out  # fmt: skip
    assert not (tmp_path / "records" / "baseline-auth.json").exists()


def test_stale_names_modules_changed_since_their_latest_run_and_those_in_none(
    tmp_path, monkeypatch, capsys
):
    from moolakata.dev import baseline, hardening

    a, b, c, d = (f"moolakata/{x}.py" for x in "abcd")
    recs = [
        {"name": "baseline-core", "modules": [a], "first_content": {a: "a1", b: "b1"}},
        # Settled, then changed, then run again by the baseline: the baseline's is the latest.
        {"name": "values", "pr": 32, "modules": [a, c], "content": {a: "a0", c: "c1"}},
    ]
    monkeypatch.setattr(hardening, "records", lambda: recs)
    monkeypatch.setattr(mutate, "server_modules", lambda: {a: 1, b: 1, c: 1, d: 1})
    monkeypatch.setattr(
        baseline, "current", lambda ms: [{b: "b2", c: "c2"}.get(m, "a1") for m in ms]
    )
    assert mutate.main(["stale"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"baseline-core: changed since its first run: {b}",
        f"values: changed since settled in #32: {c}",
        f"in no run: {d}",
    ]
    monkeypatch.setattr(
        baseline, "current", lambda ms: [{b: "b1", c: "c1"}.get(m, "a1") for m in ms]
    )
    monkeypatch.setattr(mutate, "server_modules", lambda: {a: 1, b: 1, c: 1})
    assert mutate.main(["stale"]) == 0
    assert capsys.readouterr().out == "every module is as its run mutated it\n"


def test_the_baseline_runs_rest_rounds_until_nothing_is_unrun_then_records(tmp_path, monkeypatch):
    from moolakata.dev import baseline

    monkeypatch.setattr(baseline, "STATE", tmp_path / "state.json")
    started, left = [], iter([([], 30), ([], 4), ([], 0)])

    def dispatch(repo, ref, inputs):
        started.append(inputs)
        return str(100 + len(started))

    monkeypatch.setattr(baseline, "dispatch", dispatch)
    monkeypatch.setattr(baseline, "wait", lambda repo, run: [])
    monkeypatch.setattr(baseline, "unrun_after", lambda runs: next(left))
    gathered = []
    monkeypatch.setattr(mutate, "gather", lambda a: gathered.append(a.run) or 0)
    assert mutate.main(["baseline", "--repo", "someone/MoolaKata", "--ref", "base"]) == 0
    runs = ["someone/MoolaKata:101", "someone/MoolaKata:102", "someone/MoolaKata:103"]
    assert started[0] == {"areas": "server/*", "jobs": "", "parallel": "20"}
    assert started[1] == {"rest": " ".join(runs[:1]), "parallel": "20"}
    assert started[2] == {"rest": " ".join(runs[:2]), "parallel": "20"}
    assert gathered == [runs]
    assert json.loads((tmp_path / "state.json").read_text())["runs"] == runs


def test_the_baseline_stops_on_a_job_that_ran_nothing_or_a_round_that_gains_nothing(
    tmp_path, monkeypatch, capsys
):
    from moolakata.dev import baseline

    monkeypatch.setattr(baseline, "STATE", tmp_path / "state.json")
    started = []
    monkeypatch.setattr(baseline, "dispatch", lambda repo, ref, i: started.append(i) or "7")
    monkeypatch.setattr(baseline, "wait", lambda repo, run: [])
    monkeypatch.setattr(mutate, "gather", lambda a: pytest.fail("nothing to record"))
    monkeypatch.setattr(baseline, "unrun_after", lambda runs: (["store-5"], 10))
    assert mutate.main(["baseline"]) == 1
    assert "then: web/dev.sh mutate baseline --jobs store-5" in capsys.readouterr().out
    # Fixed, it's run again by name, and the loop goes on where it stopped.
    left = iter([([], 12), ([], 12)])
    monkeypatch.setattr(baseline, "unrun_after", lambda runs: next(left))
    assert mutate.main(["baseline", "--jobs", "store-5"]) == 1
    assert started[1]["jobs"] == "store-5" and started[2]["rest"]
    assert "as many as the round before: stopped" in capsys.readouterr().out
    assert len(json.loads((tmp_path / "state.json").read_text())["runs"]) == 3


def test_a_dispatch_reads_its_runs_id_from_the_link_gh_prints(monkeypatch):
    from moolakata.dev import baseline

    calls = []
    link = "https://github.com/someone/MoolaKata/actions/runs/42998791763\n"
    monkeypatch.setattr(baseline, "gh", lambda *a: calls.append(a) or link)
    got = baseline.dispatch("someone/MoolaKata", "base", {"rest": "1 2", "jobs": ""})
    assert got == "42998791763"
    assert calls == [("workflow", "run", "mutate.yml", "-R", "someone/MoolaKata", "--ref", "base",
                      "-f", "rest=1 2")]  # fmt: skip


def test_the_changes_left_after_the_runs_leave_out_jobs_that_ran_nothing(tmp_path, monkeypatch):
    from moolakata.dev import baseline

    monkeypatch.setattr(mutate.paths, "WEB", tmp_path)
    _job(tmp_path, "1", "auth-1", "server/auth", "moolakata/auth/users.py", [1, None, None])
    _job(tmp_path, "2", "auth-1.r1-1", "server/auth", "moolakata/auth/users.py", [None, 1, None])
    _job(tmp_path, "1", "keys-1", "server/keys", "moolakata/keys/files.py", [None, None])
    assert baseline.unrun_after(["1", "someone/MoolaKata:2"]) == (["keys-1"], 1)


SHOWN = """# moolakata.money.x_f__mutmut_2: survived
--- src/moolakata/money.py
+++ src/moolakata/money.py
@@ -1,4 +1,4 @@
 def total(xs):
-    return sum(xs)
+    return None
"""

MONEY = """import functools


class Span:
    def holds(self, x):
        return x


@functools.cache
def total(xs):
    return sum(xs)


def again(xs):
    return sum(xs)
"""


def test_a_changes_diff_reads_without_its_headers_and_its_function_from_its_name():
    assert mutate.hunk(SHOWN) == [" def total(xs):", "-    return sum(xs)", "+    return None"]
    assert mutate.hunk("") == []
    assert mutate.function_of("moolakata.ui.profile.x__show__mutmut_8") == "_show"
    assert mutate.function_of("moolakata.budgets.xǁSpanǁholds__mutmut_7") == "Span.holds"


def test_a_changes_line_is_where_its_lines_are_found_once_in_its_function():
    # The unchanged line above tells the two `return sum(xs)` apart; a decorator counts in.
    assert mutate.line_of(MONEY, "total", [" def total(xs):", "-    return sum(xs)"]) == 11
    assert mutate.line_of(MONEY, "again", ["-    return sum(xs)", "+    return None"]) == 15
    # A method's code, as mutmut prints it, dedented.
    assert mutate.line_of(MONEY, "Span.holds", [" def holds(self, x):", "-    return x"]) == 6
    assert mutate.line_of(MONEY, "total", ["-    return max(xs)"]) is None  # not there
    assert mutate.line_of(MONEY, "gone", ["-    return sum(xs)"]) is None
    twice = MONEY + "\n\ndef both(xs):\n    return 1\n    return 1\n"
    assert mutate.line_of(twice, "both", ["-    return 1", "+    return 2"]) is None


def test_gather_keeps_each_survivor_with_its_line_and_diff_and_makes_the_missing_ones(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(mutate, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(mutate, "BASELINE", tmp_path / "baseline")
    monkeypatch.setattr(mutate.paths, "WEB", tmp_path)
    monkeypatch.setattr(mutate, "source", lambda content: MONEY)
    money = "moolakata/money.py"
    d = _job(tmp_path, "1", "core-1", "server/core", money, [1, 0, 0])
    # The job's summary kept change 2's diff; change 3's job stopped before it.
    (d / "survivors.txt").write_text(
        "# moolakata.money.py.x_f__mutmut_2\n def total(xs):\n-    return sum(xs)\n"
        "+    return None\n# moolakata.money.py.x_f__mutmut_3\n"
    )
    asked = []

    def remade(missing, content):
        asked.append(missing)
        return {"moolakata.money.py.x_f__mutmut_3": ["-    return sum(xs)", "+    return 0"]}

    monkeypatch.setattr(mutate, "remade", remade)
    assert mutate.gather(argparse.Namespace(run=["1"], no_record=False)) == 0
    assert asked == [{"moolakata.money.py.x_f__mutmut_3": money}]
    got = json.loads((tmp_path / "records" / "survivors" / "core.json").read_text())
    # `f` isn't in MONEY: the line is found in a named function only.
    assert [(e["name"][-1], e["line"], e["removed"], e["added"]) for e in got] == [
        ("2", None, ["    return sum(xs)"], ["    return None"]),
        ("3", None, ["    return sum(xs)"], ["    return 0"]),
    ]


def test_the_missing_diffs_are_made_again_only_where_the_code_is_what_the_runs_mutated(
    monkeypatch,
):
    a, b = "moolakata/money.py", "moolakata/duration.py"
    monkeypatch.undo()  # the real `remade`, its copy's steps stubbed
    calls = []
    monkeypatch.setattr(mutate, "blob", lambda path: "same" if path.name == "money.py" else "x")
    monkeypatch.setattr(mutate, "make_copy", lambda: calls.append("copy"))
    monkeypatch.setattr(mutate, "configure", lambda ms, tests: calls.append(("only", ms)))
    monkeypatch.setattr(mutate, "shown", lambda names, generate: calls.append(
        (names, generate)) or {n: SHOWN for n in names})  # fmt: skip
    got = mutate.remade({"m.x_f__mutmut_2": a, "d.x_g__mutmut_1": b}, {a: "same", b: "old"})
    assert got == {"m.x_f__mutmut_2": mutate.hunk(SHOWN)}
    assert calls == ["copy", ("only", [a]), ({"m.x_f__mutmut_2": f"src/{a}"}, True)]
    assert mutate.remade({"d.x_g__mutmut_1": b}, {b: "old"}) == {}  # nothing the same: no copy


def test_export_keeps_each_survivors_diff_from_the_mutants_when_the_run_was_stopped(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    monkeypatch.setattr(mutate, "WORK", work)
    monkeypatch.setattr(mutate, "COPY", work / "web")
    monkeypatch.setattr(mutate, "UNREACHED", work / "unreached.txt")
    monkeypatch.setattr(mutate, "_mutmut_pids", lambda: [])
    meta(work / "web" / "mutants" / "src", "moolakata/money.py", [1, 0])
    asked = []
    monkeypatch.setattr(mutate, "shown", lambda names: asked.append(names) or
                        {n: SHOWN for n in names})  # fmt: skip
    out = tmp_path / "out"
    args = ["export", str(out), "--name", "core-1", "--area", "server/core", "--modules", "x"]
    assert mutate.main(args) == 0
    assert asked == [{"moolakata.money.py.x_f__mutmut_2": "src/moolakata/money.py"}]
    assert (out / "survivors.txt").read_text() == (
        "# moolakata.money.py.x_f__mutmut_2\n def total(xs):\n-    return sum(xs)\n"
        "+    return None\n"
    )
