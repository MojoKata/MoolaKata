# Mutation testing

How an area's tests are measured by mutation (requirements S17.5.12), and what to do with what
it finds. Coverage says a line ran; a mutation run says whether any test would notice if the
line were wrong. In the values, taxes and options walk (review 3) it found gaps behind 98%
covered files, four bugs among them (CR3-398, CR3-399, CR3-404, CR3-405), and test data that
hid a change by giving the same answer either way.

## When

At the end of each area's hardening (a review walk's fix cycle), over the modules the area
owns, once its other tests are in. Not in `web/check`: every test that reaches a function
runs once per change to it, so a run takes minutes to hours, not seconds.

## A run

```sh
web/dev.sh mutate run moolakata/valuation.py moolakata/ledger/lots.py moolakata/loans/
```

Modules are paths under `web/server/src`; a folder means every module in it. The command:

1. **Copies the server** to `web/.dev/mutate` (mutmut changes the code it tests, so never the
   checkout), with what the server reads from beside itself linked in (`ui`, `audit.json`,
   `coverage-floor.json`, `dev.sh`, `install`; `connector`, `docs`, `.github`, `publish` a
   level up; `VERSION` copied where the build and the code look for it).
2. **Installs the lock's `mutation` group** in the copy (mutmut, pinned and audited like any
   tool in `uv.lock`; `setup` never installs it).
3. **Chooses the tests**: every fast test file that imports one of the modules, plus any named
   with `--tests` (a test that reaches a module only through the API is named that way). The
   generated worlds, the browser's tests and the audit's are never chosen: run once per
   change, a world takes hours, and a rule is pinned by a fast test.
4. **Writes mutmut's settings** in the copy and **runs it** with `--workers` (6 by default)
   from a fresh `mutants/` folder, so the map of which tests reach which function is built
   from the tests as they are (a rerun reusing the last map never tries tests added since).
5. **Watches its memory** as PSS (its workers rename themselves `mutmut: <change>`, and share
   pages) and stops the run past `--limit` (15 GB by default, inside the project's budget of
   about 20 GB; six workers peaked at 7 to 11 GB).
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

`--first` keeps the first run's outcomes, in total and by file, and its modules. The second,
after a full run once every survivor is settled (not an `--only` rerun, which holds only the
changes it reran), keeps that run's outcomes, the pull request it is settled in, the review ids
of the bugs it found, the equivalents left, and each module's content as git names it. A
module whose content on `main` differs from it has changed since its run, and its area's
mutation counts as needing another. The records are committed with the area's work.

The area's pull request also carries the run: the outcomes by file, the survivors by function
with what was done about each, a table of what is done and what is left (nothing, at the end),
and the equivalents left unmarked. The walk's Applied section names the commits.
