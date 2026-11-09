"""Mutation runs (requirements S17.5.12, docs/mutation-testing.md): `web/dev.sh mutate`.

    web/dev.sh mutate run <module>... [--tests FILE...] [--workers N] [--only NAME...]
    web/dev.sh mutate summary
    web/dev.sh mutate check <change> <test file>
    web/dev.sh mutate record <name> --first | --pr N [--found CR3-n...] [--equivalent N]

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
since shows its run as needing another.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

from .. import paths

SERVER = paths.WEB / "server"
WORK = paths.WEB / ".dev" / "mutate"
COPY = WORK / "web" / "server"
RECORDS = paths.ROOT / "docs" / "hardening" / "mutation"
LIMIT_GB = 15.0  # stops the run; the project's budget is about 20 GB (6 workers: 7 to 11)

# What the server reads from beside itself, at import and in tests, linked into the copy. The
# tests run from the copy's mutants/, where `paths` takes the copy for web/ and its parent for
# the repository's root.
BESIDE = ["ui", "audit.json", "coverage-floor.json", "dev.sh", "install"]
ABOVE = ["connector", "docs", ".github", "publish"]
# Tests never run once per change: the generated worlds (hours each), the browser's, the audit's.
SLOW = re.compile(r"(_world|_worlds|^test_browser|^test_app|^test_mockup|^test_no_network)")
OUTCOME = {1: "killed", 3: "killed", 0: "survived", 5: "no tests", 33: "no tests", 34: "skipped",
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


def tests_for(modules: list[str], extra: list[str]) -> list[str]:
    """The fast tests that import any module named, and those named."""
    pats = [re.compile(p) for m in modules for p in _module_names(m)]
    found = []
    for f in sorted((SERVER / "tests").glob("test_*.py")):
        if SLOW.search(f.stem):
            continue
        text = f.read_text()
        if any(p.search(text) for p in pats):
            found.append(f"tests/{f.name}")
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
    for name in BESIDE:
        _link(COPY / name, paths.WEB / name)
    _link(COPY / "server", COPY)
    for name in ABOVE:
        _link(COPY.parent / name, paths.ROOT / name)
    _link(COPY.parent / "web", COPY.parent)
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    uv = shutil.which("uv") or "uv"
    sync = [uv, "sync", "--frozen", "--group", "mutation", "--quiet"]
    subprocess.run(sync, cwd=COPY, env=env, check=True)  # noqa: S603 - our own command


def _link(at: Path, to: Path) -> None:
    if at.is_symlink() or at.exists():
        if at.is_symlink():
            at.unlink()
        else:
            return
    at.symlink_to(to)


def configure(modules: list[str], tests: list[str]) -> None:
    """mutmut's settings in the copy's pyproject.toml: the modules, the tests, one process."""
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
        'pytest_add_cli_args = ["-p", "no:xdist", "-p", "no:cacheprovider"]\n'
        'also_copy = ["tests"]\n'
    )
    (COPY / "pyproject.toml").write_text(text)


def _pss_gb() -> float:
    """The run's memory: mutmut and its workers, each page shared counted once (PSS)."""
    total = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
            if not (cmd.startswith("mutmut: ") or "/bin/mutmut run" in cmd):
                continue
            # Only this checkout's run: another worktree's runs in its own copy.
            if not Path(f"/proc/{pid}/cwd").resolve().is_relative_to(COPY.resolve()):
                continue
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    total += int(line.split()[1])
        except OSError:
            continue
    return total / 1024 / 1024


def run(args) -> int:
    tests = tests_for(args.modules, args.tests or [])
    print(f"mutating {', '.join(args.modules)}")
    print(f"with {len(tests)} test files: {', '.join(t.removeprefix('tests/') for t in tests)}")
    make_copy()
    configure(args.modules, tests)
    cmd = [str(COPY / ".venv" / "bin" / "mutmut"), "run", "--max-children", str(args.workers),
           *(args.only or [])]  # fmt: skip
    log = (WORK / "mutmut.log").open("w")
    # The copy's own mutmut, with arguments from the command line it was run with.
    proc = subprocess.Popen(cmd, cwd=COPY, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603
    peak, stopped = 0.0, threading.Event()

    def watch() -> None:
        nonlocal peak
        while proc.poll() is None:
            gb = _pss_gb()
            peak = max(peak, gb)
            if gb > args.limit:
                print(f"stopping: {gb:.1f} GB past the {args.limit:.0f} GB limit")
                stopped.set()
                proc.terminate()
                return
            time.sleep(10)

    threading.Thread(target=watch, daemon=True).start()
    while proc.poll() is None:
        time.sleep(30)
        print(f"  {_progress()}", flush=True)
    log.close()
    print(f"peak memory {peak:.1f} GB (PSS); log: {WORK / 'mutmut.log'}")
    summary(None)
    return 1 if stopped.is_set() else proc.returncode


def _progress() -> str:
    try:
        tail = (WORK / "mutmut.log").read_bytes()[-400:].decode(errors="replace")
    except OSError:
        return "starting"
    lines = [x for x in tail.replace("\r", "\n").split("\n") if x.strip()]
    return lines[-1].strip()[:100] if lines else "starting"


def outcomes(src: Path) -> tuple[dict[str, Counter], dict[str, Counter], list[str]]:
    """A run's outcomes from mutmut's .meta files under `src`: by file, by function, and the
    survivors' names."""
    by_file: dict[str, Counter] = defaultdict(Counter)
    by_fn: dict[str, Counter] = defaultdict(Counter)
    survivors = []
    for meta in sorted(src.rglob("*.meta")):
        rel = meta.relative_to(src).as_posix().removesuffix(".meta")
        for name, code in json.loads(meta.read_text())["exit_code_by_key"].items():
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
    mutmut = str(COPY / ".venv" / "bin" / "mutmut")
    with (WORK / "survivors.txt").open("w") as out:
        for name in survivors:
            show = [mutmut, "show", name]
            shown = subprocess.run(show, cwd=COPY, capture_output=True, text=True)  # noqa: S603
            diff = [x for x in shown.stdout.splitlines() if re.match(r"^[-+][^-+]", x)]
            out.write(f"# {name}\n" + "\n".join(diff) + "\n")
    print(f"\n{len(survivors)} survivors; each change in {WORK / 'survivors.txt'}")
    return 0


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
    r = subprocess.run(["git", "hash-object", str(path)], capture_output=True, text=True, check=True)  # noqa: S603, S607
    return r.stdout.strip()


def recorded(record: dict, by_file: dict[str, Counter], first: bool, args) -> dict:
    """`record` with this run added: the first run's outcomes and modules, or the settling
    run's outcomes, pull request, bugs found, equivalents and each file's content."""
    out = dict(record)
    if first:
        out["first"] = counts(by_file)
        out["modules"] = sorted(by_file)
        return out
    out["last"] = counts(by_file)
    out["pr"] = args.pr
    out["found"] = sorted({*out.get("found", []), *(args.found or [])}, key=lambda i: int(i.split("-")[1]))
    if args.equivalent is not None:
        out["equivalent"] = args.equivalent
    out["content"] = {f: blob(SERVER / "src" / f) for f in sorted({*out.get("modules", []), *by_file})}
    return out


def record(args) -> int:
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
    r.add_argument("--limit", type=float, default=LIMIT_GB, help="stop past this many GB")
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
    args = p.parse_args(argv)
    return {"run": run, "summary": summary, "check": check, "record": record}[args.what](args)


if __name__ == "__main__":
    sys.exit(main())
