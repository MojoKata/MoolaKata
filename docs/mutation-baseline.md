# The CI mutation baseline

Every server module's first mutation run, made on GitHub's runners before the sweeps
(REVIEW.md §11.8), so each area's sweep starts with its survivors in hand. This file is the
procedure, the limits that shape it, what the first baseline (November 9 to 11, 2026) ran into
and how each problem was settled, and how to check it and make it again. How a single run works,
and the workflow's inputs, are in `mutation-testing.md` (*The CI baseline*); the requirement is
S17.10.4.

What it leaves:

- `docs/hardening/mutation/baseline-<area>.json`, committed: each area's outcomes, by file, and
  every module's content as the runs mutated it (`first_content`, git blob ids).
- `docs/hardening/mutation/survivors/<area>.json`, committed (about 5 MB for the first
  baseline): each surviving change, one a line, with its module, function, line and the lines
  it removed and added, in the module's order, for the area's sweep.
- The runs' artifacts on GitHub, kept 90 days, from which `gather` can write both again.

## Making it

### Scripted

```sh
web/dev.sh mutate baseline                                   # MojoKata/MoolaKata, main
web/dev.sh mutate baseline --repo you/MoolaKata --ref baseline-run    # on a fork
```

1. **Before**: `gh` signed in, as someone who can start workflows on the repository. On
   MojoKata/MoolaKata that takes an admin; on a fork it takes the fork's owner, with Actions
   turned on and the branch named by `--ref` pushed at the commit to measure (`git push origin
   upstream/main:refs/heads/baseline-run`).
2. **The first run**: it starts the mutate workflow with every area (`--areas` narrows it) and
   `--parallel` jobs at once (20, the account's whole allowance: see the limits below; on
   MojoKata, where pull requests' checks need runners too, pass 14).
3. **Waiting**: it looks at the run every 5 minutes and prints its jobs' states as they change.
   A failed job is printed and counts as unrun; its changes come back in the next round.
4. **After each run** it gathers every run so far without recording (`gather --no-record`):
   - a job that ran nothing (stopped before its first change) **stops the loop**, naming the
     jobs. Their logs say why (see the problems below). Once the cause is fixed and merged,
     `web/dev.sh mutate baseline --jobs <names>` runs them again by name and goes on;
   - changes left unrun (jobs out of time) start a **rest round** over every run so far, then
     the loop waits for it, and so on;
   - nothing unrun: it gathers once more and writes the records.
5. **It stops** too when a round leaves as many unrun as the round before, or after `--rounds`
   rounds (5): something is wrong that another round won't fix.
6. Its runs are kept in `web/.dev/mutate-baseline.json`: started again, it picks up where it
   stopped (a run still under way is waited for, not started again). `--new` starts afresh.
7. **Then, by hand**: a branch from main with the 21 records, and a pull request with the area
   table `gather` printed. The area's sweep later settles its record with `mutate record
   baseline-<area> --pr N`.

It runs for days: start it where it can keep running (a `tmux` session), or start it again
when it stops; nothing is lost.

### By hand

The same loop, step by step, as the first baseline was made:

1. Start the workflow: Actions › mutate › Run workflow, or `gh workflow run mutate.yml -R
   <repo> --ref <ref> -f parallel=20`.
2. When it ends: `web/dev.sh mutate gather --no-record <run>`, the area table with *not run*.
   A run of a fork is named `owner/repo:id`; MojoKata's by its id alone. Never gather a run
   still under way: its artifacts are downloaded once, into `web/.dev/mutate-ci/<run>`, and a
   partial download stays.
3. Jobs that ran nothing: fix the cause, then run them again by name: `-f jobs="auth-1 store-5"`.
4. Changes left unrun: `-f rest="<every run so far>"`. To preview the round's jobs first:
   `web/dev.sh mutate plan --rest <runs...> --rest-dir /tmp/rest`.
5. Again from 2 until nothing is unrun; then `web/dev.sh mutate gather <every run, the earliest
   first>` writes the records.

Two runs at once need two branches: the workflow's concurrency group is its ref, and a second
dispatch on the same ref cancels the first.

## Limits

| Limit | Value | What it means here |
|---|---|---|
| Jobs at once | 20 per account (GitHub Free) | The fork and MojoKata each have 20, so a run on each doubles the pace |
| Jobs in one run | 256 (a matrix's most) | `plan --rest` keeps to it; the rest wait for the next round |
| A job's time | 6 hours | Each job stops mutmut at 330 minutes and keeps what it finished |
| A runner | 4 CPUs, 16 GB | 4 workers, the run stopped past 12 GB, a change's worker past 3 GB (counted killed) |
| Artifacts | 90 days | The survivors can be written again from them until then |
| Starting a run | write access (MojoKata: admin) | Most of the first baseline ran on a fork |

A fork's run can read MojoKata's runs' artifacts (the repository is public), so a rest round on
the fork can take over from a run on MojoKata.

## The first baseline (November 9 to 11, 2026)

Eight runs over about 49 hours, 643 job-hours, every one of its 84,190 changes run on one source
state: no server module outside `moolakata/dev/` changed between the first run's commit
(bd26827) and the last's, which `gather` now checks.

| Run | Where | Commit | What | Mutate jobs | Started → ended (Chicago) | Job-hours |
|---|---|---|---|---|---|---|
| 42654862597 | MojoKata | bd26827 | The whole server, 14 at once | 59 (46 failed) | Nov 9 10:26 AM → 6:37 PM | 72 |
| 42735794520 | fork | de0af1d | The 46 again (cancelled: memory again) | 46 (25 failed) | Nov 9 7:26 PM → 11:09 PM | 58 |
| 42760330691 | fork | c3b9aa2 | The 41 not yet run, with the fixes | 41 (2 failed) | Nov 9 11:09 PM → Nov 10 11:48 AM | 151 |
| 42789426259 | fork | e7c487e | auth-1 again (forkserver mode) | 1 | Nov 10 3:17 AM → 8:55 AM | 6 |
| 42823235504 | fork | 7fcf008 | store-5 again (the conftest fix) | 1 | Nov 10 7:17 AM → 12:54 PM | 6 |
| 42869697619 | fork | cf2f7ad | Rest round 1: 9,161 changes | 55 (1 failed) | Nov 10 11:54 AM → Nov 11 3:47 AM | 242 |
| 42880136286 | fork | f7014f6 | store-5's rest: 311 changes | 4 | Nov 10 12:55 PM → 6:41 PM | 10 |
| 42998791763 | fork | 2f98ab5 | Rest round 2: the last 842 | 43 | Nov 11 3:52 AM → 11:02 AM | 98 |

The result, area by area, is in PR #42 and the records: 72.0% of the changes caught (60,594,
timeouts among them), 20,088 survived, 3,508 reached by no test.

## What it ran into, and how each was settled

| # | Problem | Seen | Cause | Settled by |
|---|---|---|---|---|
| 1 | Jobs stopped past the 12 GB limit, before their first change or partway | 39 jobs of the first run; back on the second | `sign_in()` entered a `TestClient` and never left it, so each signed-in test left its event loop's thread holding the app. CI's test parts never showed it: they split the tests, and mutmut runs a job's tests in one process. When the first fix didn't hold, the cause was that mutmut runs several pytest sessions in one process, and pytest imports conftest again for each, while a test module keeps the `sign_in` it first imported | `sign_in`'s clients closed after their test, through a list in `tests/opened.py` that every import of conftest shares (#41): auth-2's tests 8.7 GB → 2.8 GB |
| 2 | One change grew its worker to 9.3 GB | assets-1 | A change that makes a loop run away | The watcher stops a change's worker past 3 GB of its own and counts the change killed (`--worker-limit`, #41) |
| 3 | Tests failing in mutmut's copy, not in the checkout | 4 jobs, then 2 more | The copy was laid out as `web/server`, so a path relative to the repository's root read wrong and `.dockerignore` was missing | The copy laid out as the repository (`web/.dev/mutate/web`), #41 |
| 4 | A runner's disk full after 5½ hours | importers-1 | pytest keeps each test's folder for its last three sessions, and under mutmut each change is a session (about 1 GB a change over `imports.py`'s tests) | `tmp_path_retention_policy=failed` in mutmut's pytest arguments, #41 |
| 5 | auth-1's clean tests failed | auth-1 | mutmut's fork mode ran the stats in the process its workers fork from, and they inherited `ui/imports.py`'s thread pool with its thread gone | mutmut's forkserver mode: each change runs in a fork of a process that only collected the tests (#41) |
| 6 | mutmut's forced-failure check a "usage error" (pytest exit 4) | store-5, every run | The check makes every changed function raise; conftest called `mapping.map_all()` as it loaded, and store-5 changes `store/mapping.py`, so conftest failed to load | The mapping in a session-scoped autouse fixture: still before every test, and under the check each test fails as it should (#41, asked first since it changes a test file) |
| 7 | No test file reaches `receipts/worker.py` | receipts-3 | It runs only as a subprocess, where coverage doesn't follow | Run as nothing, exported as unreached, named by `gather` for receipts' sweep |
| 8 | A runner shut down | bitcoin-1 | GitHub's side | Run again by name |
| 9 | Most jobs reached the time limit with changes unrun: 9,971 in all | almost every job | mutmut runs a job's quickest changes first, so the unrun tail is the slowest; a runner gives 6 hours at most, and a smaller job size can't split a module larger than one job | The `rest` input: each job's unrun changes split into jobs of their own (`run --only-file`), round after round, each change's outcome taken from whichever job finished it (#41) |
| 10 | Rest jobs sized by mutmut's estimates ran about twice slower than estimated | the first links rest jobs | An estimate is a change's tests' time alone, not the pytest session around them | A rest job also takes no more than half what its job's first run finished in the time (cf2f7ad, #41) |
| 11 | Round 2, as planned, would have put auth's 92 slowest leftovers in one job | round 2's plan | Its size came from the first run's pace, though those left were the slowest of round 1's jobs, which had run out of time at 47 to 62 changes | Sized by the slowest job of the round that left them (2f98ab5, #41): 43 jobs instead of 13, and none ran out of time |
| 12 | Starting the workflow on MojoKata refused (HTTP 403) | dispatching as the account that ran the fixes (the first run was started by an admin) | Starting a workflow there takes an admin | The rest on the fork, which has its own 20 jobs; the fork's runs read MojoKata's first run's artifacts |
| 13 | A second run on the same branch cancels the first | planning parallel runs | The workflow's concurrency group is its ref | A branch on the fork for each run under way at once (`baseline-rest`, `baseline-rest-store5`, ...), deleted after |
| 14 | One rest job's stats run failed: a test failed before any change ran | store-2.r1-12 | Unknown: in forkserver mode mutmut discards that run's output, so the failing test can't be named. The other 37 store-2 jobs passed it | Its 95 changes ran in round 2. Still open: see below |
| 15 | The records kept outcomes but not the code they were measured on, so nothing showed which modules a later change made stale | after the baseline | `record --first` kept no content; only a settled run did | Each record keeps `first_content`; `gather` refuses an area whose modules two runs saw differently; `mutate stale` and the hardening page name the modules changed since |
| 16 | 6,603 of the 20,088 survivors had a name and no diff | every job stopped by its time limit | A job's survivors' diffs were written by its summary, which a job stopped at 330 minutes never reaches; export kept the names alone | `export` writes them from the job's mutants; for the first baseline, `gather` made them again from mutmut's mutants of the checkout, the same code (300 of 300 sampled matched what the jobs kept). Each survivor's line is found in its function: all but 476 |
| 17 | The survivors lived on one machine, as text, until the artifacts expired | after the baseline | `gather` wrote them under `web/.dev/` | Committed as JSON, a file an area (`docs/hardening/mutation/survivors/`) |

## Checking it, and making it again

**Is it still current?** `web/dev.sh mutate stale` names every module whose content is no
longer what its latest run mutated (the baseline's, until its area's sweep settles it; then the
settled run's), and the server's modules no run has recorded. Each step's pull request lists
what it names, or says nothing changed (REVIEW.md §11.8); the hardening page marks such a module
*baseline, changed since*. A test-only change leaves the outcomes standing, except where it
removes or weakens a test.

**A changed module** needs nothing more from the baseline: its area's sweep runs it again
(`web/dev.sh mutate run`) before working from its survivors, and settles the run.

**Part of it again on CI**, an area or two whose code changed a lot before their sweep:

```sh
web/dev.sh mutate baseline --new --areas server/auth server/keys
```

Always whole areas: `gather` writes each area's record from the runs given, so a run of part of
an area's modules would record that part alone. Commit the records it rewrites; git keeps the
earlier first run.

**All of it again** (a new major version of mutmut, the test map or the runners changed, or
the code moved on so far that most of it is stale): `web/dev.sh mutate baseline --new`, then
the records' pull request. Expect about two days and 650 job-hours on one account at 20 jobs at
once, less with the fixes above already in; started on MojoKata as well as a fork, the two
accounts' 40 jobs halve it.

## Still open

1. **A possibly intermittent test in the store suite** (problem 14): if a stats run fails
   again, run that job with mutmut's `debug` setting, which keeps the run's output (each test's
   line, `-vv`), to name the test.
2. **`receipts/worker.py`** has no test that reaches it under coverage: receipts' sweep decides
   how to test it.
3. **A route module's *no tests*** may be the test map missing a test that reaches it through
   HTTP rather than a real gap; each sweep checks those first.
4. **476 survivors have no line**: their unchanged and removed lines are found more than once
   in their function, or not at all. The sweep finds them by name: `mutmut show <name>` in a
   copy of the same code. The artifacts, from which `gather` can write the records and the
   survivors again, expire 90 days after each run (from February 7, 2027); the committed files
   don't.
5. **The rest sizing's constants** (240 of a job's 330 minutes, half the measured pace) are
   rules of thumb from one baseline: round 2 finished every job well within its time, so they
   may be loosened if a later baseline shows the same.
