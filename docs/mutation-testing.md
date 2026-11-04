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

## The setup

mutmut changes the code it tests, so it runs on a scratch copy, never the checkout.

1. **A copy**: `web/server` copied to a scratch folder (not a worktree: mutmut writes a
   `mutants/` tree beside the code). The server reads a few files from beside itself at
   import and in tests; link them into the copy: `VERSION` (copied), `ui`, `server` (to the
   copy itself), `audit.json`, `coverage-floor.json`, `dev.sh`, `install`, and one level up
   `connector`, `docs`, `.github`, `publish` and `web` (to the copy's parent).
2. **Its own environment**: the project's locked dependencies (`uv export --frozen
   --no-hashes --all-groups`, without the project itself, then the project installed with
   `--no-deps`) and mutmut 3.8.0. mutmut needs libcst, whose latest builds may not have a
   wheel for the Python in use; pin an index date that has one (`uv pip install
   --exclude-newer <date>`).
3. **Its configuration**, in the copy's `pyproject.toml`:

   ```toml
   [tool.mutmut]
   source_paths = ["src"]
   only_mutate = ["src/moolakata/valuation.py", "src/moolakata/ledger/lots.py"]  # the area's modules
   pytest_add_cli_args_test_selection = ["tests/test_ledger.py", "tests/test_lot_rules.py"]  # its fast tests
   pytest_add_cli_args = ["-p", "no:xdist", "-p", "no:cacheprovider"]
   also_copy = ["tests"]
   ```

   `only_mutate` names files: without it mutmut mutates all of `src`, and one worker reached
   9 GB. The test selection is the fast tests that reach the area; the generated worlds
   (`test_tax_world`, `test_option_world`, `test_account_world` and the like) stay out.

## A run

`mutmut run --max-children 6` from the copy. Six workers peaked at 7 to 11 GB, inside the
project's budget of about 20 GB; watch it while it runs. mutmut renames its forked workers
`mutmut: <mutant>`, so measure the process tree's PSS (`/proc/<pid>/smaps_rollup`), not its RSS,
and stop the run past 15 GB.

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

`mutmut results` lists them; `mutmut show <name>` prints one change.

## Reruns

`mutmut run <name or glob> ...` reruns chosen changes (`moolakata.ledger.lots.x__consume__mutmut_*`
for one function). **It chooses each change's tests from the map its last full run made**:
tests added since are never tried ("cached results were kept" says so). After adding tests,
delete `mutants/` before a rerun, and copy the new tests and their names into the selection.

## Checking one change by hand

From the copy's `mutants/` folder, with the changed code ahead of the installed one:

```sh
PYTHONPATH=$PWD/src MUTANT_UNDER_TEST=<name> ../.venv/bin/python -m pytest tests/<file> \
  -q -p no:randomly -p no:xdist -p no:cacheprovider
```

A failing run means the tests catch it. Without `PYTHONPATH` the original code is imported and
every change seems to survive; check the command against a change a test is known to catch.

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

The area's pull request carries the run: the outcomes by file, the survivors by function
with what was done about each, a table of what is done and what is left (nothing, at the end),
and the equivalents left unmarked. The walk's Applied section names the commits.
