# Relay brief: settling H1.9's mutation survivors

Temporary: `docs/relay/` is deleted before PR #630 merges. Read this whole brief, then
`docs/relay/progress.md`, then your batch file. Nothing else from earlier agents.

## Goal

H1.9 hardens the loans and assets areas (PR #630, branch `h1-9-loans-assets`). A full mutation
run of both areas on the fork's CI (runs 44963061557 and 44989210873, mutmut on commit
`af202cf5`) left 877 survivors: 762 in server/loans, 115 in server/assets. There were also 31
changes with no tests in `ui/loans.py`. Every one is settled before the step signs off: a
survivor is a change to the code that no test notices, which means a rule no test states.

The 13 batches go by module and function, in the module's order:

| Batches | Module (under `web/server/src/moolakata/`) | Test file for new tests |
|---|---|---|
| 1–4 | `loans/__init__.py`, and `loans/payoff.py` in 4 | `tests/test_loans_edges.py` |
| 5–11 | `ui/loans.py` (11 also has the no-tests) | `tests/test_loans_routes.py` |
| 12–13 | `assets/__init__.py`, `ui/items.py` | `tests/test_assets_edges.py` |

Your batch is `docs/relay/batch-N.txt` (each survivor: its name, function, line, and the lines
it removed and added) and its bare names in `batch-N.names`. The code at the head of
`h1-9-loans-assets` is the code the survivors were taken from. The one exception is
`ui/items.py`'s `_outside`, `_periods_owned` and `_period_owned`, which changed afterwards;
batch 12's header says how those are run.

Read `docs/mutation-testing.md`, sections *Each survivor* and *Checking one change by hand*,
before you start. Its three kinds "settled the same way every time" apply here.

## The rule

Every survivor ends with exactly one outcome:

1. **Killed**: you write a fast test that fails with the change and passes without it, and it
   changes nothing the code does. This is the usual outcome, and it needs no one's approval.
2. **Bug**: the survivor shows the code gives a wrong answer by the requirements
   (`docs/requirements/`, cited by id). List it with the requirement, the input, the wrong
   output, and the test you would write (in the progress file, as a code block). **Don't
   commit a failing test, and don't change the code.**
3. **Equivalent**: no input makes any output differ. List it with one line saying why (as in
   the doc's Example 3). This includes a filter that the access view also applies (see the
   doc). **Don't add a mark.**
4. **Remove**: the code can't matter (a line never reached, a parameter never read, a guard
   that restates another). List it with why. **Don't change the code.**
5. **Slow**: the only test that would kill it is slow (a browser, a generated world, more than
   about a second). List it with the test it needs.
6. **Process only**: for a no-tests change, the function is reached only through a process a
   test starts. List it with the test that reaches it.

Hints:

- One test per rule, never one per survivor. Most survivors on one line or one condition fall
  to a single test whose data sits exactly on the bound: two parts of different sizes, or a
  rounding remainder. Name the test for the rule it pins
  (`test_pmi_ends_once_owed_reaches_78_percent`).
- Plain values first. Call the module's function directly where it allows that. For a route,
  go through the API as `tests/test_loans.py` and `tests/test_assets.py` do, using their
  fixtures from `tests/conftest.py`.
- A refusal is pinned by its field and its words, not just its status.
- An access check that restates the session's scoping is tested directly with an unscoped
  session, as the doc says. Never list it as Remove.
- When you can't tell whether a survivor is a bug or an equivalent, list it as a Bug with your
  doubt. The coordinator decides.

## What you may change

- **Only** your batch's test file from the table (create it if it doesn't exist yet), plus
  `docs/relay/progress.md`. Never anything under `web/server/src/`, never another test file,
  `conftest.py` or a fixture: not even for a moment to try something by hand. A helper you need
  goes inside your test file.
- Keep the file's existing order: add your tests at the end, under a comment naming your batch's
  functions (`# loans.history, loans.settle`).
- Keep the project's conventions:
  - **Speed:** fast, isolated tests. No browser, no sleeps or hard waits, generous timeouts.
  - **Comments:** a comment says why the test is as it is, and cites requirement ids
    (`S1.9.3`), never this relay, a batch or a survivor's name.
  - **Names:** no duplicate top-level names in the file.

## Checks before you commit (all must pass)

Run from `/home/dev/kata/MoolaKata/web/server`:

1. **Your test file, whole:**
   `.venv/bin/python -m pytest tests/<your file> -q --durations=10`.
   No test may take over about a second.
2. **Lint and formatting:**
   `.venv/bin/ruff format tests/<your file> && .venv/bin/ruff check tests/<your file>`.
   If the formatter changed anything, run check 1 again. Then check for duplicate names:
   `grep -E '^def test_' tests/<your file> | sort | uniq -d` must print nothing.
3. **The batch's own check**, a mutation run of just your batch's names. Its modules are those
   in your batch's header:

   ```sh
   web/dev.sh mutate run <modules> \
     --map /home/dev/kata/MoolaKata/web/.dev/relay-h19/testmap/map.json \
     --tests tests/<your file> \
     --only-file /home/dev/kata/MoolaKata/docs/relay/batch-N.names \
     > /home/dev/kata/MoolaKata/web/.dev/relay-h19/batch-N.log 2>&1; echo "exit $?" >> /home/dev/kata/MoolaKata/web/.dev/relay-h19/batch-N.log
   ```

   Here `<modules>` are paths such as `moolakata/loans/__init__.py`. The run can take up to an
   hour or so, since a survivor runs every test that reaches its function. Start it as a
   background command (`run_in_background`), then wait for the log's `exit` line, for example
   with Monitor and an until-loop that greps the log for `^exit `. Never search the process
   list. When it ends, `web/dev.sh mutate summary` prints the survivors left. Every one must be
   one you listed (Bug, Equivalent, Remove, Slow or Process only). If others are left, add
   tests and run again.

   While you're writing tests, try one change at a time with
   `web/dev.sh mutate check <name> tests/<your file>` (the doc's *Checking one change by hand*).
   It reads the mutants the last run built in the shared copy, so it answers "not caught" for
   every change of a module no run there has mutated yet: while the copy holds another
   module's, rely on the batch run instead.
   Only run one mutation run at a time: the copy it works in is shared. Don't change
   `--workers` or `--limit` (the machine is shared; the defaults keep inside its budget).

   If the run drops a test as failing in its copy, follow `docs/mutation-testing.md` and the
   run's own suggestion. Never delete a test or weaken what it checks; list what you did under
   your doubts.

## Commit and report

1. **Commit** on `h1-9-loans-assets`, with only your test file and `docs/relay/progress.md`.
   Never push, never switch to another branch, and never amend or rebase. Message:
   `H1.9 relay batch N: tests for <functions>' survivors: <the rules, in a few words>`, with a
   blank line and then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Let git sign
   it. Never set `user.*` and never pass `--no-gpg-sign`; if signing fails, stop and report.
2. **Append** to `docs/relay/progress.md`, under `## Batch N`:
   - the file you touched;
   - the counts: killed, bug, equivalent, remove, slow, process only, still left. They add up
     to your batch's total, and "still left" is 0;
   - each listed survivor's name and its one line;
   - the batch check's result;
   - your doubts for the coordinator.
3. **Your final message** to the coordinator: the commit's hash, the counts and the doubts. Keep
   it short; the progress file holds the detail.

The machine is shared. Leave no process running when you finish: wait for your mutation run to
end, and stop any background command you started (by its task, never `pkill -f` or `killall`).
