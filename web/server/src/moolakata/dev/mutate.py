"""Mutation runs (requirements S17.5.12, docs/mutation-testing.md): `web/dev.sh mutate`.

    web/dev.sh mutate run <module>... [--tests FILE...] [--workers N] [--only NAME...]
                                     [--only-file FILE]
    web/dev.sh mutate summary
    web/dev.sh mutate check <change> <test file>
    web/dev.sh mutate record <name> --first | --pr N [--found CR3-n...] [--equivalent N]
                                    [--from DIR...]
    web/dev.sh mutate testrun | testmap | plan [--rest <run>...] | export <dir> | gather <run>
                                                                         (the CI baseline)
    web/dev.sh mutate baseline [--repo R] [--ref REF] [--jobs NAME...] | stale   (baseline.py)

`run` makes a scratch copy of the server in web/.dev/mutate (mutmut changes the code it tests,
so never the checkout), links what the server reads from beside itself, installs the lock's
`mutation` group there, writes mutmut's settings, and runs it over the modules named (paths
under web/server/src, such as moolakata/valuation.py or moolakata/loans/), with the fast tests
that import them plus any named, never the generated worlds or the browser's. Its test map is
built afresh every run: a rerun reusing the last one never tries tests added since. `--only`
reruns chosen changes (names or globs, `moolakata.ledger.lots.x__consume__mutmut_*`). The run
is stopped if its processes pass the memory limit, measured as PSS, since mutmut's workers
rename themselves `mutmut: <change>`. At the end, and with `summary`, it prints the outcomes by
file and the survivors by function, and writes each survivor's change to survivors.txt.

`check` runs one change against one test file by hand, with the changed code ahead of the
installed one: what `mutation-testing.md` calls checking one change.

`record` keeps the last run in docs/hardening/mutation/<name>.json, which the hardening page
(coverage_site) reads: with `--first`, the area's first run (its outcomes, and the modules);
without, the run that ends the settling, with the pull request it is settled in, the bugs it
found and the equivalents left, and each file's content (its git blob id), so a file changed
since shows its run as needing another. `--from` reads the run from directories `export` wrote
instead of the last local run.

The CI baseline (`.github/workflows/mutate.yml`, docs/mutation-testing.md) runs every module on
GitHub's runners side by side. `testrun` runs the fast tests under coverage with each test's
file as its context (`moolakata.dev.testmap`); `testmap` combines what the parts measured into
web/.dev/testmap/map.json, each module's reaching test files, which `run --map` adds to those
importing it (a route module is reached through HTTP, not imported). `plan` packs the modules,
area by area, into jobs of about `--size` code lines (a module larger than that is a job of its
own), leaving out those whose settled run is current; with `--rest <run>...`, instead, jobs
for the changes those runs left unrun (a job out of time), split by mutmut's estimates and run
with `run --only-file`; `export` keeps a job's outcomes, survivors and log in a directory for
its artifact; `gather` downloads a run's artifacts and records each area's first run as
`baseline-<area>`, with its survivors in web/.dev/mutate-results/baseline/, a change's outcome
from whichever job finished it, and each module's content in the commit its jobs ran
(`first_content`); a module two runs saw differently is not recorded.
"""

import argparse
import ast
import contextlib
import fnmatch
import functools
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

from .. import paths

SERVER = paths.WEB / "server"
WORK = paths.WEB / ".dev" / "mutate"
# The copy is laid out as the repository: mutmut runs its tests from the copy's mutants/, where
# `paths` takes the copy for web/ and its parent for the root, so the copy is named web and
# its parent holds what the root does. A path a test takes relative to the root reads as it
# does in the checkout (web/server/src/...).
COPY = WORK / "web"
RECORDS = paths.ROOT / "docs" / "hardening" / "mutation"
TESTMAP = paths.WEB / ".dev" / "testmap"
BASELINE = paths.WEB / ".dev" / "mutate-results" / "baseline"
UNREACHED = WORK / "unreached.txt"  # the last run's modules, when no test file reached them
REPO = "MojoKata/MoolaKata"
LIMIT_GB = 15.0  # stops the run; the project's budget is about 20 GB (6 workers: 7 to 11)
# One change's worker may write this much of its own (beyond the pages it shares with the run
# it was forked from): past it, the change keeps allocating (one of assets' grew a worker to
# 9.3 GB before mutmut's time limit) and the worker is stopped, the change counted killed,
# rather than the whole run stopped at --limit. The others' PSS stayed under 2.3 GB.
WORKER_GB = 3.0
OUT_OF_MEMORY = -signal.SIGUSR1  # mutmut records a worker stopped so with this exit code

# What the server reads from beside itself (BESIDE) and from the root (ABOVE), at import and in
# tests, linked into the copy and its parent.
BESIDE = ["ui", "audit.json", "coverage-floor.json", "dev.sh", "install"]
ABOVE = ["connector", "docs", ".github", "publish", ".dockerignore"]
# Tests never run once per change: the generated worlds (hours each), the browser's, the audit's.
SLOW = re.compile(r"(_world|_worlds|^test_browser|^test_app|^test_mockup|^test_no_network)")
OUTCOME = {1: "killed", 3: "killed", OUT_OF_MEMORY: "killed", 0: "survived", 5: "no tests",
           33: "no tests", 34: "skipped",
           36: "timeout", 24: "timeout", -24: "timeout", 152: "timeout", 255: "timeout",
           37: "type check", None: "not run"}  # fmt: skip


def _module_names(module: str) -> list[str]:
    """How a test can import a module: `moolakata.ledger.lots` and `from moolakata.ledger
    import lots`, as patterns."""
    dotted = module.removesuffix(".py").removesuffix("/").replace("/", ".")
    parent, _, name = dotted.rpartition(".")
    out = [re.escape(dotted) + r"\b"]
    if parent:
        out.append(rf"from {re.escape(parent)} import [^\n]*\b{re.escape(name)}\b")
    return out


def fast_tests() -> list[Path]:
    """The test files a mutation run may use: not the worlds, the browser's or the audit's."""
    return [f for f in sorted((SERVER / "tests").glob("test_*.py")) if not SLOW.search(f.stem)]


def mapped(modules: list[str], testmap: dict[str, list[str]]) -> set[str]:
    """The test files the map says reach any module named (a directory names those in it)."""
    out: set[str] = set()
    for m in modules:
        for module, tests in testmap.items():
            if module == m or module.startswith(m.rstrip("/") + "/"):
                out.update(tests)
    return out


def tests_for(
    modules: list[str], extra: list[str], testmap: dict[str, list[str]] | None = None
) -> list[str]:
    """The fast tests that import any module named, those the map says reach one, and those
    named."""
    pats = [re.compile(p) for m in modules for p in _module_names(m)]
    reach = mapped(modules, testmap or {})
    found = []
    for f in fast_tests():
        name = f"tests/{f.name}"
        if name in reach or any(p.search(f.read_text()) for p in pats):
            found.append(name)
    for x in extra:
        name = f"tests/{Path(x).name}"
        if name not in found:
            found.append(name)
    return found


def make_copy() -> None:
    """The scratch copy: the server's code, tests and lock, its links, and its environment."""
    COPY.mkdir(parents=True, exist_ok=True)
    for name in ("src", "tests", "mutants"):
        shutil.rmtree(COPY / name, ignore_errors=True)
    shutil.copytree(SERVER / "src", COPY / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(SERVER / "tests", COPY / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "uv.lock", "README.md"):
        if (SERVER / name).exists():
            shutil.copy2(SERVER / name, COPY / name)
    # The build reads ../VERSION; the code, from the mutants' side, the copy's own.
    for at in (COPY, COPY.parent):
        shutil.copy2(paths.WEB / "VERSION", at / "VERSION")
    link_copy()
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    uv = shutil.which("uv") or "uv"
    sync = [uv, "sync", "--frozen", "--group", "mutation", "--quiet"]
    subprocess.run(sync, cwd=COPY, env=env, check=True)  # noqa: S603 - our own command


def link_copy() -> None:
    """The copy's links: what web/ holds beside the server, the server's own folder (the copy
    itself, so web/server/src is its code), and what the root holds, a level up."""
    for name in BESIDE:
        _link(COPY / name, paths.WEB / name)
    _link(COPY / "server", COPY)
    for name in ABOVE:
        _link(COPY.parent / name, paths.ROOT / name)


def _link(at: Path, to: Path) -> None:
    if at.is_symlink() or at.exists():
        if at.is_symlink():
            at.unlink()
        else:
            return
    at.symlink_to(to)


# Each change's tests run in one process, and a test's temporary folder goes when it passes:
# pytest keeps every test's folder of its last three sessions, and all of a session a timeout
# stopped, and a change runs a session of its own (a copy of the store each test, a gigabyte
# a session for a well-tested module), which filled a CI runner's disk. Each change's worker
# names itself for the watcher (`mutant_name.py`).
PYTEST_ARGS = ["-p", "no:xdist", "-p", "no:cacheprovider", "-o", "tmp_path_retention_policy=failed",
               "-p", "moolakata.dev.mutant_name"]  # fmt: skip


def configure(modules: list[str], tests: list[str]) -> None:
    """mutmut's settings in the copy's pyproject.toml: the modules, the tests, `PYTEST_ARGS`."""
    only = []
    for m in modules:
        path = f"src/{m}"
        only.append(path.rstrip("/") + "/*" if (SERVER / path).is_dir() else path)
    text = (COPY / "pyproject.toml").read_text()
    text = re.sub(r"\n\[tool\.mutmut\][^\[]*", "\n", text)
    text += (
        "\n[tool.mutmut]\n"
        'source_paths = ["src"]\n'
        f"only_mutate = {json.dumps(only)}\n"
        f"pytest_add_cli_args_test_selection = {json.dumps(tests)}\n"
        f"pytest_add_cli_args = {json.dumps(PYTEST_ARGS)}\n"
        # Every session in a fork of a process that only imported the tests: in mutmut's fork
        # mode the stats ran in the process the workers fork from, and they inherited what the
        # tests left there (the imports' thread pool, its thread gone in the fork: an upload's
        # job never ran, and auth-1's clean tests failed).
        'process_isolation = "forkserver"\n'
        'also_copy = ["tests"]\n'
    )
    (COPY / "pyproject.toml").write_text(text)


def _mutmut_pids() -> list[int]:
    """This checkout's mutmut and its workers, still running: they rename themselves
    `mutmut: <change>`, and another worktree's run is in its own copy."""
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
            if not (cmd.startswith("mutmut: ") or "/bin/mutmut run" in cmd):
                continue
            if Path(f"/proc/{pid}/cwd").resolve().is_relative_to(COPY.resolve()):
                out.append(int(pid))
        except OSError:
            continue
    return out


def _pss_gb() -> float:
    """The run's memory: mutmut and its workers, each page shared counted once (PSS)."""
    total = 0
    for pid in _mutmut_pids():
        try:
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    total += int(line.split()[1])
        except OSError:
            continue
    return total / 1024 / 1024


def _own_gb(pid: int) -> float:
    """What a worker has written of its own: its private pages, not those it shares."""
    total = 0
    for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
        if line.startswith(("Private_Clean:", "Private_Dirty:")):
            total += int(line.split()[1])
    return total / 1024 / 1024


def _workers() -> dict[int, tuple[str, float]]:
    """This run's workers still running: each one's change and its own memory."""
    out = {}
    for pid in _mutmut_pids():
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
            if cmd.startswith("mutmut: "):
                out[pid] = (cmd.removeprefix("mutmut: ").strip(), _own_gb(pid))
        except OSError:
            continue
    return out


def runaways(workers: dict[int, tuple[str, float]], cap: float) -> list[int]:
    """The workers past the memory one change may use."""
    return [pid for pid, (_, gb) in workers.items() if gb > cap]


def mutmut_command(args) -> list[str]:
    """The copy's mutmut over the changes `--only` and `--only-file` name, or every one."""
    only = [
        *(args.only or []),
        *(Path(args.only_file).read_text().split() if args.only_file else []),
    ]
    return [str(COPY / ".venv" / "bin" / "mutmut"), "run", "--max-children", str(args.workers),
            *only]  # fmt: skip


def run(args) -> int:
    testmap = json.loads(Path(args.map).read_text()) if args.map else None
    tests = tests_for(args.modules, args.tests or [], testmap)
    print(f"mutating {', '.join(args.modules)}")
    print(f"with {len(tests)} test files: {', '.join(t.removeprefix('tests/') for t in tests)}")
    UNREACHED.unlink(missing_ok=True)
    if not tests:
        # mutmut can't run without tests; every change is untested. `export` says so.
        print("no test file reaches these modules (one run as a subprocess, say): nothing run")
        shutil.rmtree(COPY / "mutants", ignore_errors=True)
        for name in ("survivors.txt", "mutmut.log"):
            (WORK / name).unlink(missing_ok=True)
        UNREACHED.parent.mkdir(parents=True, exist_ok=True)
        UNREACHED.write_text("\n".join(args.modules) + "\n")
        return 0
    make_copy()
    configure(args.modules, tests)
    cmd = mutmut_command(args)
    log = (WORK / "mutmut.log").open("w")
    # The copy's own mutmut, with arguments from the command line it was run with.
    proc = subprocess.Popen(cmd, cwd=COPY, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603
    peak, largest, stopped = 0.0, 0.0, threading.Event()

    def watch() -> None:
        nonlocal peak, largest
        while proc.poll() is None:
            workers = _workers()
            largest = max([largest, *(gb for _, gb in workers.values())])
            for pid in runaways(workers, args.worker_limit):
                name, gb = workers[pid]
                print(f"stopped {name}: {gb:.1f} GB of its own, past {args.worker_limit:.1f} GB")
                with contextlib.suppress(OSError):
                    os.kill(pid, -OUT_OF_MEMORY)
            gb = _pss_gb()
            peak = max(peak, gb)
            if gb > args.limit:
                print(f"stopping: {gb:.1f} GB past the {args.limit:.0f} GB limit")
                stopped.set()
                proc.terminate()
                return
            time.sleep(5)

    threading.Thread(target=watch, daemon=True).start()
    while proc.poll() is None:
        time.sleep(30)
        print(f"  {_progress()}", flush=True)
    log.close()
    print(
        f"peak memory {peak:.1f} GB (PSS), a worker's own at most {largest:.1f} GB; "
        f"log: {WORK / 'mutmut.log'}"
    )
    summary(None)
    return 1 if stopped.is_set() else proc.returncode


def _progress() -> str:
    try:
        tail = (WORK / "mutmut.log").read_bytes()[-400:].decode(errors="replace")
    except OSError:
        return "starting"
    lines = [x for x in tail.replace("\r", "\n").split("\n") if x.strip()]
    return lines[-1].strip()[:100] if lines else "starting"


def codes(src: Path) -> dict[str, dict[str, int | None]]:
    """Each change's exit code from mutmut's .meta files under `src`, by file."""
    out = {}
    for meta in sorted(src.rglob("*.meta")):
        rel = meta.relative_to(src).as_posix().removesuffix(".meta")
        out[rel] = json.loads(meta.read_text())["exit_code_by_key"]
    return out


def outcomes(src: Path) -> tuple[dict[str, Counter], dict[str, Counter], list[str]]:
    """A run's outcomes from mutmut's .meta files under `src`: by file, by function, and the
    survivors' names."""
    return counted(codes(src))


def counted(by_file_codes: dict[str, dict[str, int | None]]):
    """Exit codes by file as outcomes: by file, by function, and the survivors' names."""
    by_file: dict[str, Counter] = defaultdict(Counter)
    by_fn: dict[str, Counter] = defaultdict(Counter)
    survivors = []
    for rel, keys in by_file_codes.items():
        for name, code in keys.items():
            outcome = OUTCOME.get(code, "suspicious")
            by_file[rel][outcome] += 1
            by_fn[name.rsplit("__mutmut_", 1)[0]][outcome] += 1
            if outcome == "survived":
                survivors.append(name)
    return by_file, by_fn, survivors


def summary(_args) -> int:
    """The outcomes by file and the survivors by function, and each survivor's change."""
    by_file, by_fn, survivors = outcomes(COPY / "mutants" / "src")
    if not by_file:
        print("no run yet")
        return 1
    print("\nby file: killed, timeout, survived, no tests, not run")
    for rel, c in by_file.items():
        print(f"  {rel:40} {c['killed']:5} {c['timeout']:4} {c['survived']:5} "
              f"{c['no tests']:4} {c['not run']:5}")  # fmt: skip
    print("\nsurvivors by function")
    for fn, c in sorted(by_fn.items(), key=lambda x: -x[1]["survived"]):
        if c["survived"]:
            print(f"  {c['survived']:4} of {sum(c.values()):4}  {fn.removeprefix('moolakata.')}")
    write_survivors(WORK / "survivors.txt", survivors, src_of(COPY / "mutants" / "src"))
    print(f"\n{len(survivors)} survivors; each change in {WORK / 'survivors.txt'}")
    return 0


def src_of(src: Path) -> dict[str, str]:
    """Each change's file, as mutmut names it from the copy (src/moolakata/x.py), by its .meta."""
    return {n: f"src/{rel}" for rel, keys in codes(src).items() for n in keys}


def shown(names: dict[str, str], generate: bool = False) -> dict[str, str]:
    """`mutmut show`'s diff of each change, in one process in the copy (`mutant_diffs`); with
    `generate`, of the copy's mutants made afresh."""
    cmd = [str(COPY / ".venv" / "bin" / "python"), "-m", "moolakata.dev.mutant_diffs"]
    asked = json.dumps({"generate": generate, "names": names})
    r = subprocess.run(cmd, cwd=COPY, input=asked, capture_output=True, text=True, check=True)  # noqa: S603
    return json.loads(r.stdout.rsplit("\n", 1)[-1])


def write_survivors(path: Path, survivors: list[str], files: dict[str, str]) -> None:
    """Each survivor's name and its diff's lines, as `diffs` reads them."""
    got = shown({n: files[n] for n in survivors}) if survivors else {}
    with path.open("w") as out:
        for name in survivors:
            out.write(f"# {name}\n" + "".join(x + "\n" for x in hunk(got.get(name, ""))))


def hunk(shown: str) -> list[str]:
    """The lines of `mutmut show`'s diff: those unchanged around the change (` `), removed
    (`-`) and added (`+`), without its headers."""
    lines = shown.splitlines()
    at = next((i for i, x in enumerate(lines) if x.startswith("@@")), len(lines))
    return [x for x in lines[at + 1 :] if x[:1] in (" ", "-", "+")]


# A record's outcomes, in this order; "suspicious" and the rest count as not run.
COUNTED = ("killed", "timeout", "survived", "no tests", "not run")


def counts(by_file: dict[str, Counter]) -> dict:
    """Outcomes as a record keeps them: the totals, and each file's."""

    def row(c: Counter) -> dict:
        out = {k: c[k] for k in COUNTED[:-1]}
        out["not run"] = sum(c.values()) - sum(out.values())
        return out

    whole = sum(by_file.values(), Counter())
    return {**row(whole), "files": {f: row(c) for f, c in sorted(by_file.items())}}


def blob(path: Path) -> str:
    """A file's content as git names it, so a later checkout can tell whether it changed."""
    cmd = [shutil.which("git") or "git", "hash-object", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
    return r.stdout.strip()


def recorded(
    record: dict, by_file: dict[str, Counter], first: bool, args, content: dict | None = None
) -> dict:
    """`record` with this run added: the first run's outcomes, modules and each one's content
    as it ran (`first_content`, the checkout's unless given), or the settling run's outcomes,
    pull request, bugs found, equivalents and each file's content."""
    out = dict(record)
    if first:
        out["first"] = counts(by_file)
        out["modules"] = sorted(by_file)
        here = [f for f in sorted(by_file) if (SERVER / "src" / f).exists()]
        out["first_content"] = content or {f: blob(SERVER / "src" / f) for f in here}
        return out
    out["last"] = counts(by_file)
    out["pr"] = args.pr
    out["found"] = sorted(
        {*out.get("found", []), *(args.found or [])}, key=lambda i: int(i.split("-")[1])
    )
    if args.equivalent is not None:
        out["equivalent"] = args.equivalent
    out["content"] = {
        f: blob(SERVER / "src" / f) for f in sorted({*out.get("modules", []), *by_file})
    }
    return out


@functools.cache
def blob_at(repo: str, commit: str, rel: str) -> str:
    """A server file's content (its git blob id) at a run's commit, fetched from the run's
    repository when the checkout lacks it."""
    git = shutil.which("git") or "git"
    spec = [git, "rev-parse", f"{commit}:web/server/src/{rel}"]
    r = subprocess.run(spec, cwd=paths.ROOT, capture_output=True, text=True)  # noqa: S603
    if r.returncode:
        fetch = [git, "fetch", "--no-tags", "-q", f"https://github.com/{repo}", commit]
        subprocess.run(fetch, cwd=paths.ROOT, check=True)  # noqa: S603 - our own command
        r = subprocess.run(spec, cwd=paths.ROOT, capture_output=True, text=True, check=True)  # noqa: S603
    return r.stdout.strip()


def contents(dirs: list[Path]) -> tuple[dict[str, str], list[str]]:
    """Each module's content in the commits its jobs ran on (`downloaded` keeps each run's),
    those with nothing to change included, and the modules two of them saw differently: their
    outcomes don't add up."""
    seen: dict[str, set[str]] = defaultdict(set)
    for d in dirs:
        ran = json.loads((d.parent / "run.json").read_text())
        named = json.loads((d / "job.json").read_text())["modules"].split()
        for rel in {*codes(d / "src"), *named}:  # with those mutmut found nothing to change in
            seen[rel].add(blob_at(ran["repo"], ran["commit"], rel))
    one = {m: next(iter(b)) for m, b in sorted(seen.items()) if len(b) == 1}
    return one, sorted(m for m, b in seen.items() if len(b) > 1)


def merged(dirs: list[Path]) -> dict[str, dict[str, int | None]]:
    """The exit codes of runs `export` kept, change by change: a later run's outcome over an
    earlier one's, and an outcome over none (a job finishing what another left unrun mutates
    the same modules, and runs only those changes)."""
    out: dict[str, dict[str, int | None]] = defaultdict(dict)
    for d in dirs:
        for rel, keys in codes(d / "src").items():
            for name, code in keys.items():
                if code is not None or name not in out[rel]:
                    out[rel][name] = code
    return dict(out)


def outcomes_of(dirs: list[Path]) -> tuple[dict[str, Counter], list[str]]:
    """The outcomes by file and the survivors of runs `export` kept, together."""
    by_file, _, survivors = counted(merged(dirs))
    return by_file, survivors


def record(args) -> int:
    if args.from_:
        by_file, _ = outcomes_of([Path(d) for d in args.from_])
    else:
        by_file, _, _ = outcomes(COPY / "mutants" / "src")
    if not by_file:
        print("no run yet")
        return 1
    if not args.first and args.pr is None:
        print("name the pull request the run is settled in: --pr N")
        return 1
    path = RECORDS / f"{args.name}.json"
    old = json.loads(path.read_text()) if path.exists() else {"name": args.name}
    if not args.first and "first" not in old:
        print(f"{path.name} has no first run: record it with --first before settling")
        return 1
    new = recorded(old, by_file, args.first, args)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new, indent=2) + "\n")
    print(f"{path.relative_to(paths.ROOT)}: the {'first' if args.first else 'settling'} run")
    return 0


def code_lines(path: Path) -> int:
    lines = path.read_text().splitlines()
    return sum(1 for x in lines if x.strip() and not x.lstrip().startswith("#"))


def server_modules() -> dict[str, int]:
    """Each server module a mutation run covers, with its code lines: not the dev tools or the
    migrations, which coverage leaves out too, nor a file without code."""
    out = {}
    for p in sorted((SERVER / "src" / "moolakata").rglob("*.py")):
        rel = p.relative_to(SERVER / "src").as_posix()
        if rel.startswith("moolakata/dev/") or "/alembic/versions/" in rel:
            continue
        if n := code_lines(p):
            out[rel] = n
    return out


def current_modules() -> set[str]:
    """The modules whose settled run is current: their content unchanged since."""
    from . import hardening  # it reads this module's records

    runs = hardening.module_runs(hardening.records(), hardening.head_blobs())
    return {m for m, r in runs.items() if not r["stale"]}


def pack(modules: dict[str, int], size: int) -> list[list[str]]:
    """Modules in jobs of about `size` code lines, the largest first, each into the first job
    with room; a module larger than `size` is a job of its own."""
    jobs: list[tuple[int, list[str]]] = []
    for m, n in sorted(modules.items(), key=lambda kv: (-kv[1], kv[0])):
        for i, (total, ms) in enumerate(jobs):
            if total + n <= size:
                jobs[i] = (total + n, [*ms, m])
                break
        else:
            jobs.append((n, [m]))
    return [sorted(ms) for _, ms in jobs]


def slug(area: str) -> str:
    return area.removeprefix("server/").replace("/", "-")


def plan_jobs(modules: dict[str, int], areas: list[str], size: int, skip: set[str]) -> list[dict]:
    """The baseline's jobs: each area's modules (of those the globs name) packed by size."""
    from . import coverage

    by_area: dict[str, dict[str, int]] = defaultdict(dict)
    for m, n in modules.items():
        area = coverage.area_of(f"web/server/src/{m}") or "server/core"
        if m in skip or not any(fnmatch.fnmatch(area, a) for a in areas):
            continue
        by_area[area][m] = n
    out = []
    for area in sorted(by_area):
        for k, ms in enumerate(pack(by_area[area], size), 1):
            lines = sum(by_area[area][m] for m in ms)
            out.append({"name": f"{slug(area)}-{k}", "area": area, "lines": lines,
                        "size": f"{lines} lines", "modules": " ".join(ms)})  # fmt: skip
    return out


def plan(args) -> int:
    if args.rest:
        given = downloaded(args.rest)
        if args.jobs:  # only these baseline jobs' unrun changes: another's are under way
            given = {n: d for n, d in given.items() if source_of(n) in args.jobs}
        jobs, names = rest_jobs(given)
        out = Path(args.rest_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, these in names.items():
            (out / f"{name}.txt").write_text("\n".join(these) + "\n")
        print(json.dumps(jobs))
        print(f"{len(jobs)} jobs, {sum(len(x) for x in names.values())} changes", file=sys.stderr)
        return 0
    modules = server_modules()
    if args.modules:
        modules = {m: n for m, n in modules.items() if m in args.modules}
    skip = set() if args.all or args.modules else current_modules()
    jobs = plan_jobs(modules, args.areas, args.size, skip)
    if args.jobs:  # an earlier run's jobs again: the same tree's plan names them the same
        unknown = sorted(set(args.jobs) - {j["name"] for j in jobs})
        if unknown:
            print(f"not in the plan: {' '.join(unknown)}", file=sys.stderr)
            return 1
        jobs = [j for j in jobs if j["name"] in args.jobs]
    print(json.dumps(jobs))
    total = sum(j["lines"] for j in jobs)
    print(f"{len(jobs)} jobs, {total} code lines", file=sys.stderr)
    return 0


def testrun(_args) -> int:
    """The fast tests under coverage, each test's file its context: one part of the map."""
    TESTMAP.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "COVERAGE_FILE": str(TESTMAP / ".coverage"), "COVERAGE_CORE": "ctrace"}
    files = [f"tests/{f.name}" for f in fast_tests()]
    cmd = [sys.executable, "-m", "coverage", "run", "-m", "pytest", "-q", "-n", "auto",
           "-m", "not browser and not audit", "-p", "moolakata.dev.testmap", *files]  # fmt: skip
    # A failing test still maps what it reached; CI's check is where tests must pass.
    r = subprocess.run(cmd, cwd=SERVER, env=env)  # noqa: S603 - our own command
    print(f"tests exited {r.returncode}")
    return 0


def testmap(_args) -> int:
    """The parts' measurements combined: each module's reaching test files, in map.json."""
    import coverage

    data_file = TESTMAP / ".coverage"
    cov = coverage.Coverage(data_file=str(data_file))
    cov.combine([str(TESTMAP)], keep=False)
    data = coverage.CoverageData(basename=str(data_file))
    data.read()
    out: dict[str, list[str]] = {}
    for f in data.measured_files():
        if "/moolakata/" not in f:
            continue
        rel = "moolakata/" + f.split("/moolakata/", 1)[1]
        reach = set().union(*data.contexts_by_lineno(f).values())
        out[rel] = sorted(c for c in reach if c.startswith("tests/"))
    (TESTMAP / "map.json").write_text(json.dumps(dict(sorted(out.items())), indent=1) + "\n")
    print(f"{TESTMAP / 'map.json'}: {len(out)} modules")
    return 0


def export(args) -> int:
    """The last run's outcomes (mutmut's .meta files), survivors and log, in `dir`. A run
    stopped by the job's time limit is stopped here for good first; what it finished is kept,
    since mutmut saves each outcome as it comes."""
    for pid in _mutmut_pids():
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    src = COPY / "mutants" / "src"
    for meta in src.rglob("*.meta"):
        at = out / "src" / meta.relative_to(src)
        at.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(meta, at)
    by_file, _, survivors = outcomes(src)
    # Each survivor's change: from its summary, or, a run stopped before it, from its mutants;
    # its name always.
    if (WORK / "survivors.txt").exists():
        shutil.copy2(WORK / "survivors.txt", out / "survivors.txt")
    else:
        try:
            write_survivors(out / "survivors.txt", survivors, src_of(src))
        except OSError, subprocess.CalledProcessError, ValueError:
            (out / "survivors.txt").write_text("".join(f"# {n}\n" for n in survivors))
    if (WORK / "mutmut.log").exists():
        shutil.copy2(WORK / "mutmut.log", out / "mutmut.log")
    job = {"name": args.name, "area": args.area, "modules": args.modules}
    if UNREACHED.exists():
        job["unreached"] = True
    (out / "job.json").write_text(json.dumps(job) + "\n")
    changes = sum(sum(c.values()) for c in by_file.values())
    print(f"{out}: {changes} changes, {len(survivors)} survivors")
    return 0


# A job's changes left unrun are run by later jobs, each given as many as its time allows by
# mutmut's estimates. mutmut runs a job's changes the quickest first, so those left are the
# slowest: each at least the slowest it reached (its estimate is a change's worst case, every
# one of its tests run, as for a survivor). A killed change stops at its first failing test, and
# fewer than half survive, so a job is given twice what its worst case allows. An estimate is
# its tests' time alone, not a change's session around them, so no more than half what the
# slowest job of its latest round finished in the same time either (those left are slower than
# those it reached): the first run, then the round that left them. A job that runs out of time
# again leaves the rest to the next round.
REST_MINUTES = 240  # of the job's 330, the rest for the stats and the clean run
JOB_MINUTES = 330
REST_WORKERS = 4
MATRIX = 256  # GitHub's most jobs in one run; more wait for the next round


def source_of(name: str) -> str:
    """The baseline job a job finishing its changes belongs to (`auth-1.r2-3`: auth-1's)."""
    return name.split(".r", 1)[0]


def round_of(name: str) -> int:
    """The round of a job finishing its changes (`auth-1.r2-3`: 2), 0 for the baseline job's."""
    m = re.search(r"\.r(\d+)-\d+$", name)
    return int(m.group(1)) if m else 0


def pace(named: list[tuple[str, Path]]) -> int:
    """The fewest changes a job of the latest round that finished any finished in its time."""
    by_round: dict[int, list[int]] = defaultdict(list)
    for name, d in named:
        if n := sum(c is not None for keys in merged([d]).values() for c in keys.values()):
            by_round[round_of(name)].append(n)
    return min(by_round[max(by_round)]) if by_round else 0


def slowest(dirs: list[Path]) -> float:
    """The largest of mutmut's estimates, in seconds, in the runs `export` kept."""
    most = 0.0
    for d in dirs:
        for meta in (d / "src").rglob("*.meta"):
            est = json.loads(meta.read_text()).get("estimated_durations_by_key") or {}
            most = max([most, *est.values()])
    return most


def rest_jobs(jobs: dict[str, Path]) -> tuple[list[dict], dict[str, list[str]]]:
    """Jobs for the changes the runs left unrun, each baseline job's split by its estimates,
    and each new job's changes."""
    by_source: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for name, d in jobs.items():
        by_source[source_of(name)].append((name, d))
    out: list[dict] = []
    names: dict[str, list[str]] = {}
    for source, named in sorted(by_source.items()):
        dirs = [d for _, d in named]
        first = json.loads((dirs[0] / "job.json").read_text())
        if first.get("unreached"):
            continue
        if ran_nothing(dirs):  # its setup failed: run again by name once the cause is fixed
            print(f"{source} ran nothing: run it again by name", file=sys.stderr)
            continue
        unrun = sorted(n for keys in merged(dirs).values() for n, c in keys.items() if c is None)
        if not unrun:
            continue
        worst = slowest(dirs)
        each = int(2 * REST_MINUTES * 60 * REST_WORKERS / worst) if worst else len(unrun)
        each = min(each, int(pace(named) * REST_MINUTES / JOB_MINUTES / 2))
        parts = max(1, -(-len(unrun) // max(1, each)))
        r = max(round_of(n) for n, _ in named) + 1
        for k in range(parts):
            these = unrun[k::parts]  # dealt out, so one function's changes are spread
            name = f"{source}.r{r}-{k + 1}"
            names[name] = these
            out.append({"name": name, "area": first["area"], "lines": 0,
                        "size": f"{len(these)} changes", "modules": first["modules"],
                        "only": f"{name}.txt"})  # fmt: skip
    if len(out) > MATRIX:
        print(f"{len(out) - MATRIX} jobs wait for the next round", file=sys.stderr)
        out = out[:MATRIX]
        names = {j["name"]: names[j["name"]] for j in out}
    return out, names


def head_of(repo: str, run: str) -> str:
    """The commit a workflow run ran."""
    view = [shutil.which("gh") or "gh", "run", "view", run, "-R", repo,
            "--json", "headSha", "-q", ".headSha"]  # fmt: skip
    return subprocess.run(view, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603


def downloaded(runs: list[str]) -> dict[str, Path]:
    """The mutate workflow's runs' artifacts, downloaded once, by job name: a job run again in
    a later run replaces the earlier one."""
    jobs: dict[str, Path] = {}
    for given in runs:
        repo, _, run = given.rpartition(":")  # owner/repo:run for a fork's run
        dest = paths.WEB / ".dev" / "mutate-ci" / run
        if not dest.exists():
            gh = [shutil.which("gh") or "gh", "run", "download", run, "-R", repo or REPO,
                  "-p", "mutation-*", "-D", str(dest)]  # fmt: skip
            subprocess.run(gh, check=True)  # noqa: S603 - our own command
        if not (dest / "run.json").exists():  # the commit it ran, for each module's content
            ran = {"repo": repo or REPO, "run": run, "commit": head_of(repo or REPO, run)}
            (dest / "run.json").write_text(json.dumps(ran) + "\n")
        for job in sorted(dest.glob("*/job.json")):
            jobs[json.loads(job.read_text())["name"]] = job.parent
    return jobs


def diffs(dirs: list[Path]) -> dict[str, list[str]]:
    """Each survivor's lines of `mutmut show`'s diff, by name, from the jobs' survivors.txt
    (a later job's over an earlier one's: the same code, so the same change)."""
    out: dict[str, list[str]] = {}
    for d in dirs:
        f = d / "survivors.txt"
        lines: list[str] = []
        for x in f.read_text().splitlines() if f.exists() else []:
            if x.startswith("# "):
                lines = out[x[2:].split(":")[0].strip()] = []
            else:
                lines.append(x)
    return out


@functools.cache
def source(content: str) -> str:
    """A file's text by its git blob id."""
    cmd = [shutil.which("git") or "git", "cat-file", "-p", content]
    return subprocess.run(cmd, cwd=paths.ROOT, capture_output=True, text=True, check=True).stdout  # noqa: S603


def function_of(name: str) -> str:
    """The function a change is in, from mutmut's name for it: `x__show__mutmut_8` is
    `_show`, `xǁSpanǁholds__mutmut_7` is `Span.holds`."""
    key = re.sub(r"__mutmut_\d+$", "", name.rsplit(".", 1)[1])
    return ".".join(key[1:].split("ǁ")[1:]) if key.startswith("xǁ") else key[2:]


def line_of(text: str, function: str, diff: list[str]) -> int | None:
    """The line of a module where a change's first removed line is: where its unchanged and
    removed lines are found in its function, when found there once."""
    tree = ast.parse(text)
    *owner, fn = function.split(".")
    body = tree.body
    for cls in owner:
        body = next((n.body for n in body if isinstance(n, ast.ClassDef) and n.name == cls), [])
    node = next((n for n in body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                 and n.name == fn), None)  # fmt: skip
    old = [x for x in diff if x[:1] in (" ", "-")]
    first = next((i for i, x in enumerate(old) if x[:1] == "-"), None)
    if node is None or first is None:
        return None
    start = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1
    lines = [x.strip() for x in text.splitlines()[start : node.end_lineno]]
    want = [x[1:].strip() for x in old]  # mutmut prints a method's code dedented
    at = [i for i in range(len(lines) - len(want) + 1) if lines[i : i + len(want)] == want]
    return start + at[0] + first + 1 if len(at) == 1 else None


def survivor_entries(
    dirs: list[Path], content: dict[str, str], made: dict[str, list[str]] | None = None
) -> list[dict]:
    """The surviving changes of runs `export` kept, each with its module, function, line and
    the lines it removed and added, in the module's order; a change the jobs kept no diff of
    takes it from `made` (`remade`)."""
    by_name = {n: rel for rel, keys in merged(dirs).items() for n, c in keys.items() if c == 0}
    kept = diffs(dirs)
    out = []
    for name, rel in by_name.items():
        diff = kept.get(name) or (made or {}).get(name, [])
        function = function_of(name)
        found = diff and rel in content
        out.append({
            "name": name, "module": rel, "function": function,
            "line": line_of(source(content[rel]), function, diff) if found else None,
            "removed": [x[1:] for x in diff if x[:1] == "-"],
            "added": [x[1:] for x in diff if x[:1] == "+"],
        })  # fmt: skip
    number = lambda e: int(e["name"].rsplit("_", 1)[1])  # noqa: E731
    return sorted(out, key=lambda e: (e["module"], e["line"] or 0, e["function"], number(e)))


def unshown(dirs: list[Path]) -> dict[str, str]:
    """The survivors the jobs kept no diff of (a job stopped before its summary), by file."""
    kept = diffs(dirs)
    return {n: rel for rel, keys in merged(dirs).items() for n, c in keys.items()
            if c == 0 and not kept.get(n)}  # fmt: skip


def remade(missing: dict[str, str], content: dict[str, str]) -> dict[str, list[str]]:
    """The diffs of survivors no job kept, from mutmut's mutants made again in the copy from
    the checkout: the same code and mutmut name the same changes. A module whose code is no
    longer what the runs mutated is left out."""
    here = {f for f in set(missing.values()) if (SERVER / "src" / f).exists()}
    same = {f for f in here if content.get(f) == blob(SERVER / "src" / f)}
    asked = {n: f"src/{f}" for n, f in missing.items() if f in same}
    if not asked:
        return {}
    make_copy()
    configure(sorted(same), [])
    got = shown(asked, generate=True)
    print(f"{len(asked)} survivors' changes made again from mutmut's mutants of the checkout")
    return {n: hunk(d) for n, d in got.items() if d}


def ran_nothing(dirs: list[Path]) -> bool:
    """Whether a job `export` kept, with those finishing its changes, was stopped before its
    first change had an outcome."""
    by_file, _ = outcomes_of(dirs)
    return not any(c[k] for c in by_file.values() for k in COUNTED[:-1])


def gather(args) -> int:
    """Baseline runs' artifacts downloaded, each area's first run recorded as `baseline-<area>`,
    and its survivors kept for the sweep. A job run again in a later run replaces the earlier
    one, and the jobs finishing a job's changes add theirs to its; an area with a job that ran
    nothing (stopped before its first change, with nothing finished for it since) is not
    recorded."""
    jobs = downloaded(args.run)
    by_area: dict[str, list[Path]] = defaultdict(list)
    for d in jobs.values():
        by_area[json.loads((d / "job.json").read_text())["area"]].append(d)
    unreached = [
        d for d in jobs.values() if json.loads((d / "job.json").read_text()).get("unreached")
    ]
    print("area: changes, killed, survived, no tests, not run")
    unrun: list[str] = []
    differ: list[str] = []
    kept: list[tuple[str, list[Path], dict[str, str]]] = []
    for area, dirs in sorted(by_area.items()):
        by_file, _ = outcomes_of(dirs)
        c = counts(by_file)
        total = sum(c[k] for k in COUNTED)
        print(f"  {area:22} {total:6} {c['killed'] + c['timeout']:6} {c['survived']:6} "
              f"{c['no tests']:5} {c['not run']:5}")  # fmt: skip
        by_source: dict[str, list[Path]] = defaultdict(list)
        for d in dirs:
            if d not in unreached:
                by_source[source_of(json.loads((d / "job.json").read_text())["name"])].append(d)
        empty = [s for s, ds in sorted(by_source.items()) if ran_nothing(ds)]
        if empty:
            unrun += empty
            continue
        content, mixed = contents([d for d in dirs if d not in unreached])
        if mixed:  # the runs saw different code: its outcomes don't add up
            differ += mixed
            continue
        kept.append((area, dirs, content))
        if not args.no_record:
            name = f"baseline-{slug(area)}"
            path = RECORDS / f"{name}.json"
            old = json.loads(path.read_text()) if path.exists() else {"name": name}
            path.parent.mkdir(parents=True, exist_ok=True)
            new = recorded(old, by_file, True, args, content)
            path.write_text(json.dumps(new, indent=2) + "\n")
    # The diffs no job kept, made again at once for every area, then each area's survivors.
    missing = {n: f for _, dirs, _ in kept for n, f in unshown(dirs).items()}
    made = remade(missing, {f: b for _, _, c in kept for f, b in c.items()}) if missing else {}
    keep = BASELINE if args.no_record else RECORDS / "survivors"  # an area's to a file
    keep.mkdir(parents=True, exist_ok=True)
    for area, dirs, content in kept:
        found = survivor_entries(dirs, content, made)
        lines = ",\n".join(json.dumps(e, ensure_ascii=False) for e in found)
        (keep / f"{slug(area)}.json").write_text(f"[\n{lines}\n]\n")
    print(f"survivors by area in {keep}")
    for d in unreached:
        job = json.loads((d / "job.json").read_text())
        print(f"no test file reaches {job['modules']} ({job['area']}): for its sweep")
    if unrun:
        print(f"ran nothing, so their areas are not recorded: {' '.join(sorted(unrun))}")
    if differ:
        print("changed between the runs, so their areas are not recorded (run them again on "
              f"one commit): {' '.join(differ)}")  # fmt: skip
    return 1 if unrun or differ else 0


def check(args) -> int:
    """One change against one test file, the changed code ahead of the installed one."""
    mutants = COPY / "mutants"
    test = f"tests/{Path(args.test).name}"
    if (SERVER / test).exists():
        shutil.copy2(SERVER / test, mutants / test)
    env = {**os.environ, "PYTHONPATH": str(mutants / "src"), "MUTANT_UNDER_TEST": args.change}
    env.pop("VIRTUAL_ENV", None)
    python = str(COPY / ".venv" / "bin" / "python")
    flags = ["-q", "-p", "no:randomly", "-p", "no:xdist", "-p", "no:cacheprovider"]
    r = subprocess.run([python, "-m", "pytest", test, *flags], cwd=mutants, env=env)  # noqa: S603
    print("caught" if r.returncode else "not caught: every test passed with the change")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="web/dev.sh mutate", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="what", required=True)
    r = sub.add_parser("run", help="mutate modules and run the tests that reach them")
    r.add_argument("modules", nargs="+", help="paths under web/server/src")
    r.add_argument("--tests", nargs="*", help="test files to add to those importing the modules")
    r.add_argument("--workers", type=int, default=6)
    r.add_argument("--only", nargs="*", help="rerun only these changes (names or globs)")
    r.add_argument("--only-file", help="and those named in this file, one a line")
    r.add_argument("--limit", type=float, default=LIMIT_GB, help="stop past this many GB")
    r.add_argument(
        "--worker-limit",
        type=float,
        default=WORKER_GB,
        help="stop a change's worker past this many GB of its own; the change is killed",
    )
    r.add_argument("--map", help="a test map (testmap's map.json): its tests are added")
    sub.add_parser("summary", help="the last run's outcomes and survivors")
    c = sub.add_parser("check", help="one change against one test file")
    c.add_argument("change")
    c.add_argument("test")
    k = sub.add_parser("record", help="keep the last run in docs/hardening/mutation/")
    k.add_argument("name", help="the run's name, such as taxes or routes-trades")
    k.add_argument("--first", action="store_true", help="the area's first run")
    k.add_argument("--pr", type=int, help="the pull request the run is settled in")
    k.add_argument("--found", nargs="*", help="review ids of the bugs its survivors showed")
    k.add_argument("--equivalent", type=int, help="survivors left as equivalents")
    k.add_argument("--from", dest="from_", nargs="*", help="directories `export` wrote")
    sub.add_parser("testrun", help="the fast tests under coverage, a context per test file")
    sub.add_parser("testmap", help="each module's reaching test files, from testrun's parts")
    pl = sub.add_parser("plan", help="the baseline's jobs, as JSON")
    pl.add_argument("--areas", nargs="*", default=["server/*"], help="area globs")
    pl.add_argument("--size", type=int, default=1000, help="code lines per job")
    pl.add_argument("--all", action="store_true", help="also modules whose run is current")
    pl.add_argument("--modules", nargs="*", help="only these modules (a trial)")
    pl.add_argument("--jobs", nargs="*", help="only these jobs, by name, run again")
    pl.add_argument(
        "--rest",
        nargs="*",
        help="instead, the changes these runs left unrun (as gather takes them)",
    )
    pl.add_argument("--rest-dir", default=str(paths.WEB / ".dev" / "rest"),
                    help="where each such job's changes are written")  # fmt: skip
    e = sub.add_parser("export", help="the last run's outcomes, kept in a directory")
    e.add_argument("dir")
    e.add_argument("--name", required=True)
    e.add_argument("--area", required=True)
    e.add_argument("--modules", required=True)
    g = sub.add_parser("gather", help="a CI baseline run's artifacts, recorded by area")
    g.add_argument("run", nargs="+",
                   help="the mutate workflow's run ids, the earliest first (owner/repo:id for "
                        "a fork's)")  # fmt: skip
    g.add_argument("--no-record", action="store_true", help="survivors only")
    from . import baseline  # it drives this module's commands

    baseline.add_parsers(sub)
    args = p.parse_args(argv)
    commands = {"run": run, "summary": summary, "check": check, "record": record,
                "testrun": testrun, "testmap": testmap, "plan": plan, "export": export,
                "gather": gather, **baseline.COMMANDS}  # fmt: skip
    return commands[args.what](args)


if __name__ == "__main__":
    sys.exit(main())
