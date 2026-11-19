# Relay brief: H1.8's ledger survivors

Temporary: `docs/relay/` is deleted before PR #599 merges. Read this whole brief, then
`docs/relay/progress.md`, then your batch file. Nothing else from earlier agents.

## Goal

H1.8 (#69) sweeps `server/ledger`. A CI mutation run (fork run 44505709314) left these
survivors in `ui/transactions.py`, `ui/accounts.py` and `ledger/balances.py`: changes to the
code that every test still passes. Your batch is one file, `docs/relay/batch-N.txt` (each
change's name, then its diff), with the bare names in `batch-N.names`. The code at the head of
`h1-8-ledger` is the code the run mutated.

## The rule (REVIEW.md §11.8)

For each survivor, exactly one of:

1. **Killed**: write a test that fails with the change and passes without it, and changes
   nothing the code does. No question needed. This is nearly every survivor.
2. **Equivalent**: no input can tell the change apart (`x or None` where `x` is never falsy
   but `None`, a default no caller relies on, a bound no value reaches). Don't mark it; list it
   in the progress file with one line saying why no input tells it apart.
3. **Bug**: the change shows the code doing something the requirements
   (`docs/requirements/`) say it shouldn't, or a test you'd write would pin a behaviour that
   looks wrong. Don't fix it and don't pin it; list it with the requirement id and a sentence.
4. **Unreachable**: the mutated code is reached by no request (a branch no caller can take).
   Don't remove it; list it with why.
5. **Slow**: the only test that would tell it apart needs a browser, a generated world, or
   more than a second. Don't write it; list it.

Many survivors share one line or one cause: one good test often kills several. Prefer one
test per behaviour over one test per change.

## What you may change

- **Only test files** under `web/server/tests/`. Never a file under `web/server/src/`, the
  docs, the mockup, or anything outside the tests.
- Add to the test file that already covers the route or function (find it with `grep`;
  transactions and accounts routes are mostly in `test_accounts.py` and `test_ledger.py`). A new
  file only when no file fits, named `test_<module>_<topic>.py`.
- Tests are fast and isolated (`pytest -n 8` safe): use the existing fixtures and helpers in
  the file and `tests/conftest.py`; call a pure function directly where one exists; no sleeps
  or timed waits (`moolakata.dev.waits` only); no browser tests, no generated worlds.
- Hold each refusal to its field, code **and** words, as the file's existing tests do.
- Before you add a helper, check the file for a top-level name you'd shadow:
  `grep -oE "^(def \w+|[A-Z_0-9]+ =)" <file> | sort | uniq -d` must print nothing.
- Comments say why, cite requirement ids (`S2.2`), never a review or this relay.

## Checks before you commit (all must pass)

1. Each test file you touched, **whole**: `web/dev.sh test tests/<file> -n 8` (from the repo
   root; never only your new tests with `-k`).
2. The duplicate-name grep above, on each touched file.
3. `web/check static` (formatting and lint, about 6 s). If it reformats, rerun 1.
4. The batch's mutation check: `web/dev.sh mutate run <module> --only-file /home/dev/kata/MoolaKata/docs/relay/batch-N.names --tests tests/<each file you touched> --workers 6`
   (one `<module>` per source file in your batch, such as `moolakata/ui/transactions.py`;
   without `--tests` it runs only the test files that import the module; the names file's path
   must be absolute, as `mutate run` reads it from another directory). About a minute's
   setup, then seconds a change: 10 to 25 minutes for a batch, so run it as a background command
   and wait for its own completion notice. Never wait with a loop that searches the process
   list (`pgrep -f`, `ps | grep`): its pattern matches its own command line, so it never ends. It prints killed and survived per file and writes the survivors to
   `web/.dev/mutate/survivors.txt`. Every change you counted as killed must show as killed; anything still
   surviving is either fixed with another test or moved to one of the lists, with why.
   Don't run anything else under `mutate`, and don't start a second one while one runs.

## Commit and report

1. Commit on `h1-8-ledger` (never push, never another branch, never amend or rebase), with
   only your test files and `docs/relay/progress.md`. Message: a first line saying what the
   tests hold (as the branch's earlier commits do), then a body naming the batch, ending with
   the `Co-Authored-By:` line the branch's commits carry. Let git sign it; if signing fails,
   stop and report.
2. Append to `docs/relay/progress.md`, under `## Batch N`: the test files touched; counts
   (killed, equivalent, bug, unreachable, slow, still surviving); then each listed survivor's
   name and its one line; then doubts for the coordinator.
3. Your final message to the coordinator: the commit's hash, the counts, and the doubts.
   Short; the progress file holds the detail.

Memory: the machine is shared. Leave no process running when you finish.
