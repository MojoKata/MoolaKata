# Reviewing MoolaKata

How a review of MoolaKata is run: the requirements and the other documents first, then the
code subsystem by subsystem against the sections that describe it. A review answers three
questions for each part of the code: are its requirements built, does its code have
requirements, and does the code do what they say. Along the way it looks for bugs, most of
all in what changed since the last review.

The process is built around one limit: no single session can hold the requirements, the
documents and the code at once (together they are several times what fits). So the work is
cut into pieces that each fit with room to think, every piece writes what it finds to a file
as it goes, and what passes between pieces is files, never a session's memory.

Reviews 1 and 2 came
before this process and keep their names and ids. Review 3 is the first run this way.

## 1. The choices a review makes

Each review makes three choices before it starts, and its summary issue records them (§10).

1. **Scope**:
   - **Full**: all the code is read whole against its sections.
   - **Incremental**: the code changed since the last review's commit is read, with enough
     of what surrounds it to judge it. Code that keys, sign-in, links or secrets depend on
     (S10.1, S11, S14.4, S15, S18.3) is read whole whenever any of it changed.
2. **Checking**:
   - **Checked**: every claim is checked by a second, independent context before it enters
     the review (§8).
   - **Quick**: no second pass. Each claim enters at 0 confirmations and is confirmed before
     anyone acts on it (§11). It saves about a third of each unit's time.
3. **Serial or parallel**: serial unless the user asks, in their own words and for this
   review, for parallel agents or a workflow (§12). It is never assumed, never carried over
   from an earlier review, and never a default.

**Choosing.** Phase 0 measures the change since the last review (§4.3) and recommends scope
and checking by these rules of thumb:

| Choice | Recommended when |
|---|---|
| Incremental | under ~25% of the code's lines changed, and no unit over ~50% |
| Full | anything more, or the last review is too old to build on |
| Quick | a small delta, as triage or a look at one area |
| Checked | a release-readiness review, or any change to code keys, sign-in, links or secrets depend on |

Moves, renames and file splits count as changed: they have to be read again. The reviewer
says what the numbers recommend and confirms the choice with the user either way: a full
review asked for on a delta small enough for an incremental one, a quick one asked for where
checking is advised, and the reverse of each.

**Severity** follows `requirements/gaps.md`: **High** blocks the next release, **Med** is
needed before it, **Low** can follow it.

## 2. The files

| Where | What |
|---|---|
| GitHub issues and a project | the review's outcome: one issue per finding, under its area's step (§10) |
| `review/<nnnn>/` on the review's branch | its work pad: `<nnnn>` the review's number in four digits |
| `docs/reviews/check_docs.py` | the mechanical checks of Phase 0 (§4.1) |

The work pad holds everything a session needs from earlier ones while the review runs. It
lives on the review's branch only, and is never merged: what outlives the review is in its
issues, each standing on its own, and in the requirements.

| File | Written by | What |
|---|---|---|
| `log.md` | every session | one line per session: its start and end (`date`, Chicago time), phase or unit, what it wrote, what is left |
| `doccheck.txt`, `cites.tsv` | Phase 0 | `check_docs.py`'s report and its citations by item |
| `delta.txt` | Phase 0 | the change since the last review, per unit (§4.3) |
| `map.md` | Phase 0 | the units: sections, code paths, tests, lines (§4.2) |
| `docs-<block>.md` | Phase 1 | a block's claims and its claims digest (§5) |
| `docs-compare.md` | Phase 1 | the conflicts between the digests |
| `unit-<nn>-<name>.md` | Phase 2 | a unit's brief, claims, verdicts and what was found while checking (§7, §8) |
| `sweep.md` | the sweep | the verdicts on what was found while checking (§8) |

The ids in the work pad are its own: `D1-4` for the fourth claim of Phase 1's first block,
`U07-12` for unit 7's twelfth. A finding's lasting id is its issue's number, given when it is
filed (§10).

**The commit.** A review reads one commit, recorded in `log.md` when Phase 0 starts. Nothing
merges to `main` while it runs; if something must, the units still read the review's commit
(`git show <commit>:<path>`), and the delta is measured to it.

**Read only.** A review changes no code, documents or requirements but its own files, except
the decisions taken at the gate (§6). Nothing is fixed along the way, however small: the
review describes the commit it read. Fixes come after filing (§11).

**The branch.** A review has its own branch, `code-review-<nnnn>`, on the fork, from `main` at
the review's commit. Each session ends by committing its work-pad files and pushing the
branch, so nothing lives only on this machine; `withheld.md` (below) is never committed. The
branch is never merged: the fixes are made on their steps' branches, each pull request naming
the issues it closes.

**Withheld claims.** The repository is public, and households run its releases. A
**security** or **privacy** claim rated High or Med, written down, tells anyone how to attack
a server that runs the release. From the moment it is made, its details go into the work
pad's `withheld.md`, which `.gitignore` keeps out of git; the unit's file names only
its work-pad id. It is filed not as an issue but as a draft security advisory on the
repository, private to its maintainers, and published with its fix.

**While no household relies on a server**, the user may set withholding aside, as they did
for review 3: every claim is then published as it is written, `withheld.md` isn't used, and a
review's summary issue says so. A review asks the user at Phase 0 which holds.

## 3. A session's habits

These hold in every phase, and keep each session inside its context with room to reason:

1. **Start from the work pad.** Read `log.md`, the brief for the piece, and only the files it
   names. Never rely on another session's memory.
2. **Write as you go.** Each claim goes into the work pad when it is made, not at the end, so
   a long session that is summarised loses nothing.
3. **Read what you judge whole; search for the rest.** The sections and code a piece reviews
   are read whole. An Explore agent may locate callers or uses elsewhere, but its excerpts
   are never the evidence for a claim.
4. **Keep large output out of the conversation.** Test runs, diffs and listings go to a file
   in the work pad or the job's scratch directory, and only their summary is read.
5. **Every claim carries its evidence**: the file and line, the quoted lines of code (or of
   the document), and the requirement id. Re-read the cited lines before writing the claim.
6. **The settled stays settled.** `rejected-ideas.md`, `later.md`, `out-of-scope.md`, the open
   gaps and questions, and a review's recorded decisions are not raised again without a new
   reason, which the claim states.
7. **Run little.** A claim may be reproduced with one test file, one test, or a request
   against `web/dev.sh run`. Anything that takes over a minute is asked for first; `web/check`
   is never started by a review; the connector's tests run in a session of their own.
8. **End with the log.** The last act of a session is its line in `log.md`, its commit and
   push (§2), and, when it is the last session of the day, the state of the review in
   `docs/handoff.md`.
9. **Quote code in ```` ```text ```` fences.** `web/check` runs `ruff format --check` over
   `docs/reviews`, and ruff formats ```` ```python ```` blocks in Markdown: it would rewrite
   the quoted lines. Never run `ruff format` without `--check` there.
10. **A withheld claim is only an id.** Everywhere committed (another claim, an earlier
   finding's re-check, a log row, a scratch file's name) it appears as its id, kind and
   severity, never beside words on what it is about (§2).
11. **Scratch stays out of the repository.** Scratch tests and scripts live in the job's
   scratch directory, even for a moment; `PYTHONPATH=tests web/dev.sh uv run pytest -p
   conftest <path>` runs one with the server's fixtures.

## 4. Phase 0: the measures and the map

### 4.1 The mechanical checks

```
python3 docs/reviews/check_docs.py --cites <pad>/cites.tsv > <pad>/doccheck.txt
```

It reports what needs no judgement: requirement ids cited in the documents or the code that
no section numbers; gaps, questions and later items cited that are not open; the README's
tables against the files; section files past 500 lines; the schema's prefix tables out of
order; the next free G, Q and L numbers; and the first-level items no code cites. It also
lists words and dates a statement doesn't carry (CLAUDE.md), for a reader to judge: a
button's *Lock now* is fine, "now stores" is not. `web/check` runs it with `--quiet`
(requirements S17.5), so its problems are normally fixed before a review starts; any that
remain become Phase 1 claims, and no agent spends its context finding them by reading.

### 4.2 The map

One session builds `map.md`: for each requirement section, the code that builds it, the tests
that check it, and their sizes. `cites.tsv` gives the start (the code cites its items, as in
`(S13.7.2)`); the session fills the rest from the code's layout and imports. The map then
cuts the code into **units** of about 10,000 lines of code each, with their sections:

1. a big package that serves many sections (`store/`, the server's `ui/`) is split by the
   sections its modules serve, and each part goes to the unit of its sections;
2. small sections that share code are joined;
3. code that cites no section and serves none is listed as **untraced**, with the unit it
   sits beside; that unit's session judges it (§7).

Units are numbered in requirement order, so a step's findings are filed (§10) in the
requirements' order. The map records, per unit, its sections, paths, tests and line counts.

### 4.3 The delta

From the last review's commit (its header) to this one's, per unit, with renames found:

```
git diff -M --numstat <last>..<commit> -- <unit's paths> > <pad>/delta.txt
```

Summed against the unit's lines, it gives the share changed that §1 decides from. Phase 0
ends with the recommendation and the user's choice, both in `log.md`.

## 5. Phase 1: the documents

Three sessions, one after another, each reading one block whole:

| Block | Reads |
|---|---|
| `docs-1-money` | the requirements' README (R1–R3) and S1–S9, with `later.md`, `gaps.md`, `questions.md` |
| `docs-2-platform` | the README (R1–R3) and S10–S18, with `out-of-scope.md` and `rejected-ideas.md` |
| `docs-3-protocols` | `schema.md`, `link-protocol.md`, `connector-protocol.md`, `operations.md`, `api.md`, `DEPLOY.md`, `RELEASE.md`, `test-plan.md`, `dependencies.md` |

Each looks for: contradictions within its block; terms used other than R2 defines them;
behaviour named and never specified (a candidate gap); the same thing specified twice,
differently; references to removed or renumbered items; rules in CLAUDE.md the documents
break; and what the mockup shows against what its sections say, for the screens its block
covers (from the mockup's text, not screenshots). It turns `doccheck.txt`'s problems for its
block into claims.

Each block also writes a **claims digest**: one line per fact another block could
contradict, with its id. A fact is a term and what it means, a limit or default (a number, a
duration, a size), a state and what moves it, who may do what, and what is sent or stored
where. A fourth session reads only the three digests and writes `docs-compare.md`: the
conflicts between blocks, each a claim with both ids. The digests stay in the work pad, so an
incremental review reads only the sections changed since and compares their new digests
against the old ones.

In a checked review, Phase 1's claims are checked like the units' (§8), each block's at the
end of its session.

## 6. The gate

A High claim from Phase 1 that two documents disagree on behaviour the code will be checked
against is decided before the units that depend on it: the user and the reviewer walk through
each, and the decision is written into the requirements (with the mockup, if the user sees
it) and into the review's decisions. A unit waits only while such a claim touches its own
sections; every other unit goes ahead. Med and Low claims hold nothing up.

## 7. Phase 2: the units

One session per unit, in the map's order. Its brief, written at the top of its
`unit-<nn>-<name>.md` before it starts:

1. the unit's sections and code paths, and its tests, from `map.md`;
2. its delta from `delta.txt`, read first: recent merges are where the bugs are;
3. the earlier reviews' findings in its area, with their state, to re-check that what was
   marked done still holds;
4. the Phase 1 claims and decisions on its sections;
5. the untraced code the map gave it.

The session reads its sections whole, then its code (whole in a full review; the delta and
what surrounds it in an incremental one), and writes a claim for each:

| Kind | The question |
|---|---|
| **not built** | an item of its sections that no code builds and no milestone, gap or later item schedules |
| **untraced** | code that serves no requirement: dead, left over, or a requirement that was never written down |
| **differs** | the code does something other than what its requirement says |
| **wrong figure** | money, tax, quantities or dates miscounted |
| **security** | secrets, keys, transport, injection, a forged or replayed request |
| **privacy** | one user or household seeing or changing what isn't theirs (S10) |
| **bug** | a fault no requirement names: errors, races, a failure part-way, a resource left open |
| **test gap** | a requirement, or a fix from an earlier review, that no test holds |

A claim in the work pad has: its work-pad id; the kind; the severity; the requirement id
(`—` for untraced); the file and line, with the quoted lines; what goes wrong, as a concrete
case where there is one; the remedy; and alternatives where there are reasonable ones. Where
it was run (a test, a request against `web/dev.sh run`), it says so, and how; where it rests
on reading alone, it says that.

## 8. Checking (checked reviews)

When the unit's claims are written, the session starts **one checker**: a subagent with a
fresh context, given the claims file, the review's commit and this section, and nothing of
the session's reasoning. For each claim it reads the cited code and requirement for itself,
looks for what would make the claim false (a guard elsewhere, a caller that never passes the
case, a reading of the requirement that allows it), and gives one verdict:

| Verdict | Meaning |
|---|---|
| **confirmed** | the claim holds as written |
| **corrected** | it holds once its severity, scope, lines or remedy are changed, which the verdict gives; a claim may be split or two joined |
| **plausible** | the code does what the claim says, but whether that is wrong depends on how a requirement is read: it becomes a question to walk through |
| **rejected** | it does not hold, with the reason |

The checker also writes what it noticed that no claim covers, under **Found while checking**,
each unverified and in the claim format. It never adds them to the claims itself: nothing
enters the review on the word of the context that found it.

The verdicts are written into the unit's file beside each claim. Rejected claims stay there,
with their reasons, so the next review does not raise them again without new evidence; they
never get a review id.

**The sweep.** After the last unit, one session checks everything found while checking,
across all units, the same way, and writes `sweep.md`. Each one it confirms goes to the unit
it belongs to.

## 9. Confirmations and status

A claim's **confirmations** count the independent contexts that found it holds:

- **0** when it is made;
- **+1** for each confirmation by an agent or session that did not make it and has not
  confirmed it before, by a test that reproduces it, or by the user;
- a **corrected** verdict counts as a confirmation of the corrected claim;
- **plausible** adds nothing: the claim is a question until it is answered;
- **rejected** drops it.

A filed finding's **status** is its issue's: **open**; open with the `question` label, a
choice for the user; **closed as completed**, fixed, its body or closing comment naming the
pull request ("Fixed by #44"); **closed as not planned**, with the reason (found not to hold,
or decided to leave as it is). Confirmations after filing are comments on its issue.

## 10. Filing

One session files the review from the work pad, into the sweep's GitHub project ("Hardening
Sweep <n> (H<n>)"):

1. **A summary issue**, "H<n> Code review <n>: summary", closed once filed: the commit read,
   the last review's commit it is measured from, scope, checking, serial or parallel (and, if
   parallel, that the user asked for it), the verdict in one line, a few lines on what matters
   most, *checked and sound* (what was looked at closely and found right, so the next review
   need not repeat it) and *where things stand* (what was left unread or read lightly, and
   where to start).
2. **A step issue per area to sweep**, "H<n>.<step> Sweep <areas>", in the order they are to
   be done, labelled `hardening` and with each area's `area:` label; one more for the
   requirement and document findings, and one for the tooling's.
3. **A sub-issue per finding** under its area's step, "H<n>.<step>-<k> <description>": one
   sentence, at most a line; a finding that needs more is two. Labelled `hardening`, its
   area's `area:` label, and `question` when it is a choice for the user. Its body starts with
   its severity ("severity Med", which the hardening page reads) and holds all of it: kind,
   requirements, code with the quoted lines, what goes wrong, how it was run, remedy,
   alternatives. Nothing it needs is left in the work pad.
4. **The project's fields**, Step, Kind (Sweep, Tooling, Finding, Question) and Area, set on
   each issue as it is filed.

A finding's area is that of the first code it names, else its section's. The issues are filed
by a script from the work pad's files, safe to run again, after a dry run the user reads.

## 11. After the review

1. **Confirm before acting.** A claim at 0 confirmations is not fixed, decided or written
   into the requirements until someone confirms it: a test that reproduces it, or a reading
   of the code and requirement that doesn't lean on the claim. Whoever takes it up does this
   first, and it adds one.
2. **Walk through** the plausible claims and the ones that need a choice, one at a time, with
   options and a recommendation. Answers go into the requirements and the decisions; a
   question left open takes the next Q id.
3. **Each change goes on its issue**: a confirmation or a decision as a comment, a severity
   changed by a decision in its body. The pull request that fixes a finding closes it
   ("Closes #212"); code cites the requirements, never the issue, unless a comment needs more
   than it can hold (CLAUDE.md, *Code comments*).
4. **A quick review can be checked later**: a checking pass over its claims (§8) raises their
   confirmations, and its header then reads "quick, checked later".
5. **What a review recommends but no one takes up** goes to the gaps, the questions or later
   work with an id, so it is not lost when the next review starts.
6. **Each area's fix cycle ends with its hardening**, in the same pull request: the area's
   code and data-shape coverage looked at again (what the code branches on, each fact a record
   carries crossed with what can happen to it, the dimensions the generated worlds leave out)
   and a mutation run over its modules (S17.5.12, `mutation-testing.md`), until every
   surviving change is caught by a fast test or marked with its reason. What it finds is
   fixed there and filed as a closed sub-issue of its step; what belongs to another area
   goes to that area's step.
7. **The path keeps the sweep in view** (S17.5.8.6): the step issues are the path to the end
   of the sweep, and the hardening page checks each one off as its issue is closed. Opening a
   step's pull request adds "**Pull request:** #<n>" to its issue's body; when it merges, the
   issue is closed with "done by #<n>" in its body. Its first and settling mutation runs are
   recorded (`web/dev.sh mutate record`, naming the findings they found by issue, `--found
   '#412'`) and committed with it.
   Before a step is signed off, its last CI run's times are checked (`web/dev.sh ci-times`): a
   job past the budget (6 minutes), or a family of parts more uneven than 1.4 to 1 whose slowest
   part is the run's slowest job, is split further in that step (more parts, or the parts' times
   refreshed with `web/dev.sh ci-durations`, by which they are split), so CI stays as quick as
   the tests allow while they grow. Making a test itself quicker (fewer cases or seeds, smaller
   data, a cheaper fixture, a test reworked or dropped) trades some checking for time: it is put
   to the user first, with what it costs, what it saves and a recommendation.
   Each step also answers the **coverage question**, as its walk's last round and again at its
   sign-off: from CI's coverage artifact (`server.json` per function, `browser.lcov` per line),
   whether each changed function's lines and branches are at diminishing returns (the 90s), and
   whether every data axis the change brings is written out with its points (each fact a record
   carries, each choice a caller makes, each kind of refusal). The tests it calls for go in the
   same pull request.
8. **The sweep starts from the baseline** (`mutation-testing.md`, *The CI baseline*): every
   server module's first mutation run is made on CI before the sweeps, so an area's sweep
   begins with its survivors in hand, and only the modules changed since are run again. A
   test that catches a survivor and changes nothing the code does is written without asking;
   a survivor that shows a bug, an equivalent to leave unmarked, or a test that would be slow
   goes to the area's walk, which opens the sweep, so the area's questions are asked once.
   Every step's pull request says whether it changes code the baseline ran: `web/dev.sh mutate
   stale` names each module changed since its latest run (the baseline's, until its area's
   sweep settles it), and the pull request lists them, or says none changed. A changed module's
   baseline survivors are stale: its area's sweep runs it again instead of starting from them.
   How the baseline is made again, whole or in part, is in `mutation-baseline.md`.

## 12. Parallel agents, when asked

Only when the user asks for it in their own words for the review at hand (§1). The review's
header records it; the next review asks again. When asked:

1. Phase 1's three blocks run at once; the comparison waits for all three.
2. Units run 3 or 4 at a time, no more: the machine also runs the lab's VM, and a loaded
   machine has made the mockup crawl time out.
3. Checking runs one checker per claim rather than one per unit.
4. The sweep is split by unit.
5. A **workflow** (one script that runs the agents) needs the user to say "use a workflow"
   and to raise the workflow size limit in `/config`. A workflow resumes only from the
   session that started it, so a long one is cut by phase.

Everything else is the same: the briefs, the work-pad files, the rule that only an
independent context confirms a claim, and the filing. Parallel only changes how long it
takes.

**Wall time.** Review 3 (full, quick, about 102,000 lines of code in 12 units) ran as serial
sessions, each a subagent started by a coordinating session; parallel and workflow are
estimates from it:

| | Serial (review 3, measured) | Parallel (3–4 at once) | Workflow |
|---|---|---|---|
| Phases 0 and 1 | 1 h 5 min | ~45 min | ~30 min |
| Phase 2, quick | 3 h 22 min (13–19 min a unit) | ~1 h 15 min | ~45 min |
| Filing | 25 min (scripted, §10) | 25 min | 25 min |
| Checking after assembly, and the sweep | 1 h 48 min (4–14 min a piece) | ~40 min | ~20 min |

Review 3 took about 5.9M tokens: 1.0M for Phase 1, 4.4M for the units (about 370k each), and
0.4M for the assembly and a sweep for hints at withheld claims. Its checking pass, run after
assembly on Sonnet 5.5 (§14), took about 3.0M more: 125k to 310k a checker, about half a
discovery unit's.

The walk through the gate and the decisions comes on top, at the user's pace. A quick review
saves about a third of Phase 2; an incremental one of a small delta, most of it.

## 13. Starting a session

Each session starts with the same kind of prompt, naming the review, its piece and this
document:

```
Code review 4 (review/0004/ on the code-review-0004 branch), following docs/REVIEW.md:
run unit 07 (§7, then §8). Start from log.md and the unit's brief.
```

The reviewer of the previous piece leaves the next brief written, so the prompt stays this
short.

## 14. Models and effort

Each piece runs on the model and effort below, passed to the subagent that runs it. Review 3
measured them on one unit (S7's code, new since review 2) run three ways from the same brief;
the record was review 3's `model-experiment.md`, in git's history:

| Run of unit 05 | True High and Med found (16 in all) | False | Tokens | Time | Cost at API prices |
|---|---|---|---|---|---|
| Opus 5.5, default effort | 13 (81%), the High among them | 0 | 377k | 17 min | ~$1.80 |
| Sonnet 5.5, high effort | 12 (75%), the High among them | 0 (3 doubtful) | 443k | 23 min | ~$1.05 |
| Opus 5.5, medium effort | 10 (62%), without the High | 0 (2 doubtful) | 287k | 13 min | ~$1.40 |

No run found more than 81% of what the three found together, and each found defects the others
missed; two runs together found all 16, or 15. Hence:

1. **Phase 0 and the coordinating session**: Opus 5.5, default effort.
2. **Phase 1's blocks and comparison**: Sonnet 5.5, high effort. They read prose for
   contradictions; Sonnet did as well on the unit's guides and requirement text.
3. **Discovery in a unit**: Opus 5.5 at its default effort, never lowered to medium (that run
   missed the unit's one High).
4. **A second discovery run**, Sonnet 5.5 at high effort and blind to the first, for code no
   review has read (a new milestone) and for units that keys, sign-in, links or secrets
   depend on. Its claims join the unit's file under their own ids, and the checker judges
   both runs' claims. It adds about 60% to such a unit's cost.
5. **Checking (§8) and the sweep**: Sonnet 5.5, high effort: a model other than the
   discovery run's, and the run that reproduced the most. It rates higher than Opus, so a
   severity it raises is a correction like any other, and Med or High privacy and security
   claims it raises go to `withheld.md`.
6. **Filing**: the scripts (§10), then Opus 5.5 at default effort for the parts that need
   judgement and for the withholding.

One unit is one sample, and no Phase 1 block, checker or filing was compared. Review 4
measures again on a Phase 1 block and a security unit, and this section changes with what it
finds.
