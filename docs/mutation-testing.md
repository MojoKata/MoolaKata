# Mutation testing

How an area's tests are measured by mutation (requirements S17.5.12), and what to do with what
it finds. Coverage says a line ran; a mutation run says whether any test would notice if the
line were wrong. In the values, taxes and options walk (review 3) it found gaps behind 98%
covered files, four bugs among them (CR3-398, CR3-399, CR3-404, CR3-405), and test data that
hid a change by giving the same answer either way.

## The outcomes, by example

| Outcome | Meaning | What is done |
|---|---|---|
| 🎉 killed | a test noticed the change | nothing: the goal |
| ⏰ timeout | the change made the tests hang | counts as caught |
| 🙁 survived, a gap | the tests miss a real mistake | a test; a walk item if it shows a bug |
| 🙁 survived, an equivalent | the change alters no output | marked, listed, or the code rewritten |
| 🫥 no tests | no chosen test reaches the code | tests written, or the test map looked at |

The rules for each (REVIEW.md §11.8, *Each survivor* below):

1. **Killed** and **timeout** need nothing. A timeout is a change that left a loop running far
   longer than the tests take unchanged, and a bug like it would hang the tests in CI.
2. **A survivor that is a gap** gets a fast test, named for the rule it pins, with data that
   tells the change apart. A test that only catches the survivor, changing nothing the code
   does, is written without asking. One that shows the code is wrong is a bug: it gets a
   review id and goes to the area's walk, as does a test that would be slow.
3. **An equivalent** is marked `# pragma: no mutate` with its reason on the line above, only
   when every change on its statement is equivalent, since a mark silences them all.
   Otherwise it stays unmarked and is listed with the area's results (`record --equivalent`).
   Rewriting the code so the change can't exist is better than either. Equivalents left are
   named at the area's walk.
4. **No tests** is a gap wider than a survivor: nothing reaches the code. Tests are written
   for it; but on the CI baseline, a route module's *no tests* may be the map missing a test
   that reaches it another way (from a process the test starts), so it is looked at first.

Each sweep ends with no survivor unsettled in its area.

### Example 1: killed and survived

```python
# fees.py
def late_fee(balance: float, days_late: int) -> float:
    if days_late > 30:
        return balance * 0.05
    return 0.0

# test_fees.py
def test_late_fee():
    assert late_fee(1000, 45) == 50.0   # late: 5%
    assert late_fee(1000, 10) == 0.0    # not late: nothing
```

mutmut makes one small change at a time (a *mutant*) and runs the tests against each:

| # | Change | `late_fee(1000, 45)` | `late_fee(1000, 10)` | Outcome |
|---|---|---|---|---|
| 1 | `0.05` → `1.05` | 1050 ≠ 50: fails | 0 | 🎉 killed |
| 2 | `*` → `/` | 20000 ≠ 50: fails | 0 | 🎉 killed |
| 3 | `return 0.0` → `return 1.0` | 50 | 1 ≠ 0: fails | 🎉 killed |
| 4 | `> 30` → `>= 30` | 50 | 0 | 🙁 survived |
| 5 | `30` → `31` | 50 | 0 | 🙁 survived |

The function is fully covered, yet nothing checks where the 30-day line is: `>= 30` or `31`
typed by mistake would pass. The two survivors on one line are one gap, the bound, and a test
on each side of it catches both:

```python
    assert late_fee(1000, 30) == 0.0    # day 30: not late yet   (catches #4)
    assert late_fee(1000, 31) == 50.0   # day 31: late           (catches #5)
```

It pins what the code does and changes nothing, so it is written without asking. Had the
requirement said day 30 *is* late, the survivor would have shown a bug, for the walk.

### Example 2: no tests and timeout

```python
# fees.py
def waive(fee: float, reason: str) -> float:      # no test calls this
    if reason == "first-time":
        return 0.0
    return fee

def months_to_pay(balance: float, payment: float) -> int:
    months = 0
    while balance > 0:
        balance -= payment
        months += 1
    return months

# test_fees.py
def test_months_to_pay():
    assert months_to_pay(300, 100) == 3
```

| # | Change | What happens | Outcome |
|---|---|---|---|
| 1 | `"first-time"` → `"XXfirst-timeXX"` | no chosen test calls `waive` | 🫥 no tests |
| 2 | `return 0.0` → `return 1.0` | the same | 🫥 no tests |
| 3 | `balance -= payment` → `balance += payment` | the balance grows and the loop never ends | ⏰ timeout |
| 4 | `months += 1` → `months += 2` | 6 ≠ 3: fails | 🎉 killed |

*No tests*: mutmut doesn't run a test at all, since none reaches `waive`; its lines show as
missed on the coverage site too. *Timeout*: mutmut stops a change once the tests take far
longer than unchanged, and counts it as caught.

### Example 3: an equivalent survivor

```python
# loans.py
def remaining(balance: float, paid: float) -> float:
    left = balance - paid
    if left <= 0:
        return 0.0
    return left

# test_loans.py
def test_remaining():
    assert remaining(1000, 400) == 600.0   # still owed
    assert remaining(1000, 1000) == 0.0    # paid off exactly
    assert remaining(1000, 1200) == 0.0    # overpaid: never negative
```

| # | Change | Outcome |
|---|---|---|
| 1 | `<= 0` → `<= 1` | 🙁 survived, a gap: `assert remaining(1000, 999.5) == 0.5` catches it |
| 2 | `return 0.0` → `return 1.0` | 🎉 killed: the overpaid case gives 1 |
| 3 | `<= 0` → `< 0` | 🙁 survived, and no test can catch it |

Change 3 differs from the code only when `left` is exactly 0: the code returns `0.0` from the
`if`, the change skips it and returns `left`, which is `0.0` too. No output differs for any
input: it is equivalent, not a gap. A mark on the `if` would silence change 1 as well, which a
test catches, so the line stays unmarked and change 3 is listed as an equivalent. Better still,
`return max(balance - paid, 0.0)` gives the same answers with no `<=` to change.

## When

At the end of each area's hardening (a review walk's fix cycle), over the modules the area
owns, once its other tests are in; its first run is the CI baseline's (below), made before the
sweeps. Not in `web/check`: every test that reaches a function
runs once per change to it, so a run takes minutes to hours, not seconds.

## A run

```sh
web/dev.sh mutate run moolakata/valuation.py moolakata/ledger/lots.py moolakata/loans/
```

Modules are paths under `web/server/src`; a folder means every module in it. The command:

1. **Copies the server** to `web/.dev/mutate/web` (mutmut changes the code it tests, so never
   the checkout), laid out as the repository: mutmut runs the tests from the copy's
   `mutants/`, where the code takes the copy for `web/` and its parent for the root, so a path
   a test takes relative to the root reads as in the checkout. What the server reads from
   beside itself is linked in (`ui`, `audit.json`, `coverage-floor.json`, `dev.sh`, `install`,
   and `server` to the copy itself; `connector`, `docs`, `.github`, `publish`, `.dockerignore`
   a level up; `VERSION` copied where the build and the code look for it).
2. **Installs the lock's `mutation` group** in the copy (mutmut, pinned and audited like any
   tool in `uv.lock`; `setup` never installs it).
3. **Chooses the tests**: every fast test file that imports one of the modules, plus any named
   with `--tests` (a test that reaches a module only through the API is named that way). The
   generated worlds, the browser's tests and the audit's are never chosen: run once per
   change, a world takes hours, and a rule is pinned by a fast test.
4. **Writes mutmut's settings** in the copy and **runs it** with `--workers` (6 by default)
   from a fresh `mutants/` folder, so the map of which tests reach which function is built
   from the tests as they are (a rerun reusing the last map never tries tests added since).
   mutmut runs in its forkserver mode: its main process only imports and collects the tests,
   and every session (the stats, the clean run, each change) runs in a fork of it. In its fork
   mode the stats ran in the process every worker is forked from, and the workers inherited
   what the tests left there: the imports' thread pool, its thread gone in the fork, so an
   upload's job never ran.
   Before the changes, mutmut checks that one can fail the tests by making every changed
   function raise, so the tests call none as conftest loads (the records' mapping is a
   session fixture): pytest takes an error while conftest loads for a usage error, which
   mutmut takes for a broken command, and a job changing `store/mapping.py` never ran.
   Each change's tests run in one process, and a test's temporary folder goes when it passes
   (pytest keeps them otherwise, and a session over a well-tested module, a copy of the store
   each test, reaches a gigabyte: enough sessions filled a CI runner's disk).
5. **Watches its memory** as PSS (its workers rename themselves `mutmut: <change>`, and share
   pages) and stops the run past `--limit` (15 GB by default, inside the project's budget of
   about 20 GB; six workers peaked at 7 to 11 GB). A change's worker that writes more than `--worker-limit`
   of its own (3 GB by default, beyond the pages it shares with the process it was forked
   from) is stopped and the change counted killed: such a change keeps allocating, and before
   mutmut's time limit ended it, one grew a worker to 9.3 GB and stopped a whole run.
6. **Prints** the outcomes by file and the survivors by function, and writes each survivor's
   change to `web/.dev/mutate/survivors.txt`. `web/dev.sh mutate summary` prints them again.

`--only <names or globs>` reruns chosen changes
(`moolakata.ledger.lots.x__consume__mutmut_*` for one function), still with a fresh map.

Each change ends in one of these:

| | Outcome | Meaning |
|---|---|---|
| 🎉 | killed | a test failed: the change is noticed |
| 🙁 | survived | every test passed with the change: a gap, or a change that alters nothing |
| 🫥 | no tests | no selected test reaches the function |
| ⏰ | timeout | far slower than the tests unchanged (usually a loop the change made endless); counts as caught |
| 🤔 | suspicious | ended some other way |
| 🔇 | skipped | mutmut was told not to run it |
| 🧙 | caught by type check | a type checker refused the change (not used here) |

In the copy, `.venv/bin/mutmut show <name>` prints one change and `.venv/bin/mutmut browse`
walks them all.

## The CI baseline

Every server module's run, side by side on GitHub's standard runners, started by hand: the
**mutate** workflow (`.github/workflows/mutate.yml`) in the repository's Actions tab, **Run
workflow** on `main`. Its inputs: the areas (globs, every one by default), the code lines per
job (1000), whether to run modules whose settled run is current too (no), the jobs at once
(14 of the account's 20, leaving room for pull requests' checks), and the jobs to run, by name
(every one; a name only runs an earlier run's job again, which the same tree's plan names the
same).

1. **The test map** (6 jobs): the fast tests run once under coverage, each test's setup, call
   and teardown measured in a context named by its file (`moolakata.dev.testmap`, through
   `web/dev.sh mutate testrun`); `mutate testmap` combines the parts into `map.json`, each
   module's reaching test files. A route module is reached through HTTP, not imported, so the
   files importing it are not enough; `run --map` takes both.
2. **The plan**: `mutate plan` packs each area's modules into jobs of about the size, the
   largest first (a module larger than the size is a job of its own), as the coverage site
   draws its areas, leaving out the modules whose settled run is current.
3. **The jobs**: each runs `mutate run <modules> --map map.json --workers 4 --limit 12` (a
   runner has 4 CPUs and 16 GB) and stops it at 5½ hours, before the runner's 6; mutmut saves
   each outcome as it comes, so what it finished is kept, and the rest counts as not run.
   `mutate export` keeps the outcomes, the survivors and the log as the job's artifact
   (`mutation-<area>-<n>`, 90 days).

Then, on this machine:

```sh
web/dev.sh mutate gather <run id>...    # gh run download; one record per area (owner/repo:id for a fork's run)
```

`gather` downloads each run's artifacts to `web/.dev/mutate-ci/<run>`, prints each area's
outcomes, records its first run as `docs/hardening/mutation/baseline-<area>.json` (as `record
--first` does) and writes its survivors to `web/.dev/mutate-results/baseline/<area>/`. The
records are committed; the area's sweep settles its record with `record baseline-<area> --pr N`
after a full run of its modules. A job that ran out of time leaves changes not run: its modules
go again (`--only` on what is left, or a smaller size), on CI or here. A job stopped before its
first change (the memory limit, or a test failing in the copy) is run again by name, with the
`jobs` input, once the cause is fixed; `gather <first run> <rerun>` takes a later run's job over
the earlier one's, and records no area with a job that ran nothing. A module no test file
reaches (one run only as a subprocess, where coverage doesn't follow) has nothing to run: its
job says so, and `gather` names it for the area's sweep.

A pull request that changes the workflow or these tools runs a trial on two small modules,
`duration.py` and `ui/tokens.py` (which no test file imports), so the whole chain is checked
before it is merged.

## Checking one change by hand

```sh
web/dev.sh mutate check moolakata.ledger.performance.x_twr__mutmut_6 tests/test_figures.py
```

runs one test file against one change, with the changed code ahead of the installed one
(without that, the original code is imported and every change seems to survive), and says
whether it was caught. It copies the test file in first, so a test just written can be tried.

## Each survivor

Read every survivor, by function and line, and settle it one of three ways:

1. **A test.** Most survivors are a rule no test states, or test data that hides the change
   (a return of 21% over two steps came out 21% with the first step skipped, too). Write a
   fast test, plain values where the code allows, named for the rule it pins, with data that
   tells the change apart: a value exactly on a bound, two parts of different sizes, a
   rounding remainder.
2. **A change to the code.** A survivor on code that can't matter (a line never reached, a
   parameter never read, a guard that restates another) is a reason to remove the code, not
   to mark it. A survivor in a data shape nothing makes is a reason to make the shape
   impossible (CR3-405: a lot without its transaction).
3. **A mark**, only when no output can differ, said on the line above:

   ```python
   # Ids are unique, so the first four decide: no sort key changes the order.
   events.sort(key=lambda e: e[:4])  # pragma: no mutate
   ```

   mutmut honours a mark only at the end of a statement's first line, never inside brackets,
   and a statement spread over lines takes `# pragma: no mutate start` and `# pragma: no
   mutate end` around it. A mark silences every change on its statement, the caught ones
   too: where a statement's other changes are caught, leave it unmarked and list its
   equivalents with the area's results instead.

A survivor that shows a wrong answer is a bug: it gets its review id, and a test that fails on
the code as it was.

## The record

Each area's runs are kept in `docs/hardening/mutation/<name>.json`, for the hardening page
(requirements S17.5.8.6):

```sh
web/dev.sh mutate record taxes --first                           # after the area's first run
web/dev.sh mutate record taxes --pr 38 --found CR3-441 --equivalent 3   # after the settling run
```

`--from <dir>...` reads the run from directories `export` wrote (a CI job's artifacts)
instead of the last run here.

`--first` keeps the first run's outcomes, in total and by file, and its modules. The second,
after a full run once every survivor is settled (not an `--only` rerun, which holds only the
changes it reran), keeps that run's outcomes, the pull request it is settled in, the review ids
of the bugs it found, the equivalents left, and each module's content as git names it. A
module whose content on `main` differs from it has changed since its run, and its area's
mutation counts as needing another. The records are committed with the area's work.

The area's pull request also carries the run: the outcomes by file, the survivors by function
with what was done about each, a table of what is done and what is left (nothing, at the end),
and the equivalents left unmarked. The walk's Applied section names the commits.
