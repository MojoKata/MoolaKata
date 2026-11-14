# Developing MoolaKata

What the build has reached, the conventions it keeps, the stack, and setting up a machine to
work on it. [`README.md`](README.md) says what MoolaKata is; the requirements
([`docs/requirements/`](docs/requirements/README.md)) say what it does.

**Status:** the nine milestones of the first release (requirements S17.9.1–S17.9.9) are built:
the server in `web/`, the MoolaKata Connector in `connector/`. Milestones 8 and 9 built what the
second review of the requirements against the code found the release still needed
([`docs/reviews/initial-code-review-2.md`](docs/reviews/initial-code-review-2.md)); its
section 12 says where each finding went, which no review has checked yet, and the choices
milestone 9 made. What the build couldn't try for real is in
[`docs/test-plan.md`](docs/test-plan.md); the gaps and the open questions are listed in the
requirements' README. Milestone 10 (S17.9.12), budgets as S7 describes them, is built.
Milestone 11 (S17.9.13) is built: every form that changes records, dialogs and screen forms
alike, edits a draft (S12.15, `web/ui/app/draft.js`) and saves it in one request,
`POST /ui/api/save` (S13.8.11).

**Coverage:** [mojokata.github.io/MoolaKata](https://mojokata.github.io/MoolaKata/) shows
what the tests reach on `main`, by area and by file, and how it has moved over the merges
(S17.5.8.5). Each `check` run's summary in Actions has the same table for its own commit.
Its [hardening page](https://mojokata.github.io/MoolaKata/hardening.html) follows review 3's
sweep by area: findings closed, coverage, mutation runs, and the path's steps done and left
(S17.5.8.6, [`docs/hardening/path.toml`](docs/hardening/path.toml)).

## Conventions

1. [`docs/schema.md`](docs/schema.md): the database conventions: naming, prefixed UUIDv7
   ids, soft deletes and the table prefixes.
2. [`CLAUDE.md`](CLAUDE.md): the working rules: keep the mockup in step with the
   requirements, keep the requirements a statement rather than a changelog, keep the repo
   free standing, and track gaps by id.

## Mockups

The hand-written mockup's source is
[`docs/mockups/MoolaKata-mock.html`](docs/mockups/MoolaKata-mock.html); it opens in a browser
from disk too. The one generated from the app isn't committed: CI builds it on every run, a
pull request's is linked from its run's summary, and `web/dev.sh mockup` builds one into
`docs/mockups/` to open from disk. The help guides' screenshots are made from it
(`web/dev.sh help-shots`).

Check the mockup after a change with

```
pip install playwright && playwright install chromium
python docs/mockups/check.py shots/
```

It opens every screen, tab, Settings section and dialog, fails on any page or console error
or a field without a help entry, and writes a screenshot of each to `shots/`.

## Stack

A Python server (FastAPI under Hypercorn, SQLite encrypted with SQLCipher, SQLAlchemy Core
tables mapped onto plain dataclasses, Alembic migrations) and a browser app with no build step
(Preact, HTM, signals and preact-iso as vendored ES modules under a strict CSP, charts with
Apache ECharts). Deno type-checks the JavaScript, and Playwright for Python runs the browser
tests. No Node.js. One Docker image for the server, for amd64 and arm64, on port 37373, and
one for the connector (S18). See requirements S17; [`docs/dependencies.md`](docs/dependencies.md)
lists every library with its purpose, its risks and when to look at it again.

## Development

Clone with `--recurse-submodules` (or run `git submodule update --init coworker` in a
checkout): `coworker/` is the [coworker](https://github.com/MojoKata/coworker) submodule, through
which the projects on one development machine share its large downloads and VMs, and say what
they need of it. Its `status` is the first step on a machine: it lists what the machine lacks for
MoolaKata (`.coworker/deps.json`, each need with its reason) and the command for each.

Needs Python 3 and curl; `setup` installs the pinned [uv](https://docs.astral.sh/uv/) (by the
hashes in `web/install/build-requirements.txt`, into a venv of its own in `web/.tools`), which
brings Python 3.14, and fetches the pinned Deno and Playwright's Chromium.

```
coworker/bin/coworker status     # once per machine: what it lacks, and how to add it
web/dev.sh setup                 # once
web/dev.sh run --seed --stubs    # https://localhost:37373, seed users and stub prices
web/check                        # every check, as CI runs it
```

`web/dev.sh` alone lists its commands. [`web/dev.md`](web/dev.md) covers testing the dev
server from a browser on another machine (an SSH forward, a name of its own, port 443).
Releases publish the images to `ghcr.io/mojokata` (`.github/workflows/release.yml`, on a `v*`
tag); [`docs/RELEASE.md`](docs/RELEASE.md) makes one, step by step, and `web/release.sh`
runs its steps from a terminal. [`docs/GENESIS.md`](docs/GENESIS.md) records how GitHub and
Docker Hub were set up for publishing. To build the server's image yourself, from the
repository's root:

```
docker buildx build -f web/install/Dockerfile -t ghcr.io/mojokata/moolakata:$(cat web/VERSION) --load .
```

and `web/install/compose.yaml` is the example to run it from. A new server welcomes its first
admin: it shows the recovery phrase once, takes three of its words back, and sets up the
`admin` account. A running server serves the clickable mockup at `/demo`.
