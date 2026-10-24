# MoolaKata

A self-hosted personal finance server for a household: bank, card, brokerage, retirement,
529 and bitcoin accounts in one place, kept current from files the household downloads
(OFX/QFX, CSV, PDF statements and photos of them, read on the server). It charts portfolios,
tracks options, projects retirement and education goals, keeps budgets, gifts, giving,
receipts and tax books, and prepares the numbers a tax return needs. Several people share one
server, and households on other MoolaKata servers can share with named people here, read
only, in a window of their own.

**Status:** the nine milestones of the first release (requirements S17.9.1–S17.9.9) are built:
the server in `web/`, the MoolaKata Connector in `connector/`. Milestones 8 and 9 built what the
second review of the requirements against the code found the release still needed
([`docs/reviews/initial-code-review-2.md`](docs/reviews/initial-code-review-2.md)); its
section 12 says where each finding went, which no review has checked yet, and the choices
milestone 9 made. What the build couldn't try for real is in
[`docs/test-plan.md`](docs/test-plan.md); the gaps and the open questions are listed in the
requirements' README. Milestone 10 (S17.9.12), budgets as S7 describes them, is the next to be
built.

**Release:** 0.1.0, a pre-release for testers. Its images are `ghcr.io/mojokata/moolakata` and
`ghcr.io/mojokata/moolakata-connector`, for amd64 and arm64, each with a provenance attestation
`gh attestation verify` checks. The same images, with the same digests, are on Docker Hub as
`mojokata/moolakata` and `mojokata/moolakata-connector`. [`docs/DEPLOY.md`](docs/DEPLOY.md)
installs it on a Proxmox VE VM or on TrueNAS.

## Where to start

1. [`docs/requirements/`](docs/requirements/README.md): what MoolaKata is and does, in the
   present tense. Its README holds the decisions (R1), the terminology (R2) and the design
   principles (R3), and lists the sections S1–S18, the gaps not yet specified (G1, G2, …)
   and the open questions (Q1, Q2, …). S17 has the stack, the layout and the milestones
   (S17.9: the order to build in); S18 is the MoolaKata Connector, a second service.
2. [`docs/schema.md`](docs/schema.md): the database conventions: naming, prefixed UUIDv7
   ids, soft deletes and the table prefixes.
3. [`docs/mockups/MoolaKata-mock.html`](docs/mockups/MoolaKata-mock.html): the clickable
   mockup, the design reference for every screen. Open it in a browser from disk; it sends
   nothing anywhere. The purple **MOCK** pill jumps to any screen, switches users, changes
   state and opens every dialog. **F1** toggles the help pane.
4. [`docs/mockups/MoolaKata-app.html`](docs/mockups/MoolaKata-app.html): the mockup generated
   from the app for the screens built so far (`web/dev.sh mockup`), on recorded sample data.
   It opens from disk too; its **MOCK** pill jumps to screens and dialogs and switches users.
   The help guides' screenshots are made from it (`web/dev.sh help-shots`).
5. [`CLAUDE.md`](CLAUDE.md): the working rules: keep the mockup in step with the
   requirements, keep the requirements a statement rather than a changelog, keep the repo
   free standing, and track gaps by id.

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

Needs Python 3.14, [uv](https://docs.astral.sh/uv/) and curl; `setup` fetches the pinned Deno
and Playwright's Chromium.

```
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

## Deploying

[`docs/DEPLOY.md`](docs/DEPLOY.md) builds the image and puts a server where people can test
it, step by step, on a fresh VM on Proxmox VE or on TrueNAS.
[`docs/operations.md`](docs/operations.md) is the runbook from then on: upgrades, backups,
restoring, keys and the connector. [`publish/truenas/`](publish/truenas/) holds the server and
the connector as apps for TrueNAS's community catalog, ready to propose there
([`docs/RELEASE.md`](docs/RELEASE.md) §12); until TrueNAS takes them, DEPLOY.md's **Install
via YAML** is how they go on a NAS.

## License

GPL-3.0, see [`LICENSE`](LICENSE).
