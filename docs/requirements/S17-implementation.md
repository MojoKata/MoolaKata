# S17. Implementation

1. **Layout**:

   ```
   README.md
   .github/workflows/    check.yml (web/check on every pull request), release.yml (S17.10)
   docs/                 requirements/ (README.md and its sections), schema.md, api.md,
                         link-protocol.md, connector-protocol.md, operations.md,
                         DEPLOY.md (a test server on Proxmox or TrueNAS, its screenshots
                         in deploy/), dependencies.md (the register, S17.2.1),
                         test-plan.md (the manual tests, S17.9.7.8),
                         mockups/MoolaKata-mock.html
   web/
     VERSION  dev.sh  release.sh  check  pins
     ui/                 index.html, deno.json, app/{main,router,config,hooks,format}.js,
                         api/, store/, screens/, components/, charts/ (the chart wrappers),
                         account-types/ (one module per type: fields, icon, help),
                         styles/{tokens,base,components}.css, assets/icons.svg,
                         guides/, vendor/, tests/, mockup/
     server/             src/moolakata/: main.py, app.py, config.py, runtime.py, listener.py,
                         middleware.py, static.py, settings.py, tasks.py, alerts.py, mail.py,
                         mcp.py, ui/ (routes per area), auth/, keys/ (the master key, its
                         phrase, secrets), store/ (tables/, entities/, repos/, mapping.py,
                         alembic/), ledger/ (lots, gains, corporate actions), washes.py,
                         options/, prices/ (one TickerSource per source), bitcoin/ (esplora,
                         electrum, core, descriptors), importers/ (ofx, csv, statements),
                         budgets/, projections/, loans/ (schedules, payoff planner), assets/
                         (items, valuations), education/, people/, gifts/ (occasions, holiday
                         tables), giving/, taxes/ (8949, txf, limits tables), receipts/
                         (storage, thumbnails, the reader and its worker, the field parser,
                         retention), links/, dev/ (dev mode, seed data, the wheel check)
     install/            Dockerfile, compose.yaml, compose.tls.yaml, compose.truenas.yaml,
                         compose.connector-truenas.yaml, moolakata.toml, smoke.sh, proxy/
                         (reverse-proxy examples)
   connector/            the MoolaKata Connector (S18): its core, drivers, page and image
   publish/truenas/      the server's and the connector's apps for TrueNAS's catalog,
                         check.sh, which tries them, and create-pr.sh, which proposes them
                         (S17.8.3.1)
   ```

2. **Server dependencies**, each a ruling, kept short because each runs with the database: fastapi, pydantic,
   hypercorn, sqlalchemy, alembic, argon2-cffi, cryptography (AES-GCM, Ed25519 for links),
   httpx, segno (two-step QR), **Pillow** and **pypdfium2** (thumbnails and receipt reading,
   S9.5, S9.8), **sqlcipher3** (the wheel that bundles SQLCipher, for the main database and the
   linked copies, S14.1, S11.9), **rapidocr** with **onnxruntime** (receipt reading, S9.8). rapidocr brings
   numpy, opencv-python-headless, shapely, pyclipper and pyyaml with it, about 100 MB in all;
   the image carries them, and they load only in the receipt worker. **ofxtools** reads OFX
   and QFX files (pure Python, GPL-3.0-only, compatible with MoolaKata's GPLv3). **pi-heif** reads iPhone photos
   (HEIC): it decodes only, so it is smaller than pillow-heif, which also encodes. **numpy** is a direct dependency for projections
   (S6) as well as RapidOCR's.
   Standard library for email (`smtplib`), config (`tomllib`), logging and the command line.
   Pinned exactly in `uv.lock`, Python 3.14 (S17.9.7.1).
   1. **The dependency register and the egress audit.** `docs/dependencies.md` lists every
      library the server, the browser app and the build run with: its version, what it is for,
      why it was chosen, what it could do that MoolaKata must not (a call out of the house
      above all), with the switch that stops it and where MoolaKata throws it, and when to look
      at it again. A library that can reach out is marked **egress**, one that sends telemetry
      **telemetry** as well. **Every change to `uv.lock` or the vendor manifest is followed by
      an audit** before it is committed: `web/dev.sh audit` scans the installed wheels and the
      vendored files for URLs and the words of telemetry and update checks, diffs the findings
      against the register, and runs the server and the receipt worker in a network namespace
      with no interfaces through a receipt read, a price refresh against the stubs, a backup
      and a pass of the tasks, failing on any socket opened to a non-loopback address. The
      hashes of the files it was audited against are kept beside the register, in
      `web/audit.json`, and `web/check` fails when they no longer match, which costs nothing on
      an ordinary run: the audit itself runs when a dependency changes, not on every test
      cycle.
3. **The browser app: no build step.** The files in `web/ui` are the files the browser loads.
   1. **Libraries**: Preact (rendering), HTM (JSX-like tagged templates, no `eval`),
      @preact/signals (state), preact-iso (routes and lazy screens), plus the chart library
      (S17.4). Each is **vendored**: its npm tarball is committed under `web/ui/vendor/`,
      named with its exact version in `manifest.json`, and `vendor.py extract` unpacks the
      files the import map points at. No npm, no network at install.
      1. **Adopting a version** goes only through `web/dev.sh vendor add NAME VERSION`. It
         refuses a version published less than 14 days ago unless `--young` gives the reason
         (a security fix), which the manifest entry keeps. It checks the download against
         the registry's integrity hash. Where the registry holds SLSA provenance, it verifies
         it through Sigstore: built by GitHub Actions from the repository the manifest
         records for the package, for this name, version and tarball. A package whose pinned
         version had provenance is refused a version without it. It warns of npm
         dependencies, which must be vendored too unless the served files bundle them. It
         writes the manifest entry (version, publish date, tarball, integrity, repository,
         whether provenance was verified, the unpack directory and the served files), and,
         for an update, a diff of the served files, which is reviewed before the commit.
      2. **The hash** in `manifest.json` is npm's own integrity value for the tarball, so
         anyone can confirm the committed file is what the registry published. `vendor.py
         extract` (in `web/check`, `web/dev.sh` and the image build) refuses a tarball that
         doesn't match it.
   2. **An import map** in `index.html` resolves `import 'preact'` to the vendored file.
      JavaScript with JSDoc types, type-checked by Deno. No minification and no source maps,
      so a stack trace names a file in the repository.
   3. **Strict Content Security Policy**: `script-src 'self' 'nonce-…'` (the nonce covers only
      the import map), `style-src 'self'`, no inline scripts or styles, no `eval`. No
      third-party requests: no CDN, no web fonts, no analytics.
   4. **Size budget**: under 150 KB compressed for the first screen; every other screen is a
      module loaded by a native `import()` on first visit.
   5. **Cache-busting**: the app is served under `/ui/v/<version>/`, with a one-year cache
      in a release. A build between releases (a `-dev` version, S17.10.2.2) and the dev server
      serve the same paths with `no-cache`, since their files change under one version.
      `index.html`, templated with the version and the nonce, is `no-store`.
   6. **Plain CSS** with custom properties and `@layer`: `tokens.css` (colours and sizes, dark
      first), `base.css`, `components.css`. Icons are one SVG sprite.
   7. **The server is the only state.** The browser remembers only how the page looks: theme,
      sidebar, help pane, page size, privacy mode.
   8. Current Chrome, Edge, Safari and Firefox; no polyfills.
4. **Charts.** The constraints come from S17.3: an ES module the import map can point
   at, vendored with no bundler, working under `script-src 'self'` and `style-src 'self'`
   with no `eval` and no injected `<style>`, colours from `tokens.css`, both themes, and a
   size that is fine if it loads only with the chart screens. Three candidates are worth
   considering:

   | | **Apache ECharts** 5/6 (Apache-2.0) | **uPlot** (MIT) | **Lightweight Charts** (TradingView, Apache-2.0) |
   | --- | --- | --- | --- |
   | Size (gzip) | ~330 KB full ESM build; ~150 KB hand-picked, but picking needs a bundler, so we'd vendor the full file | ~20 KB | ~45 KB |
   | Charts we need | **all**: line/area with range zoom, donut, **treemap**, **Sankey** (cash flow), candlesticks, stacked bars, Monte Carlo fan (stacked bands), markers | line/area/bars, bands for the fan, markers; **no** donut, treemap or Sankey: we'd draw those as our own SVG | financial time series only: line, area, candles, histogram, markers for trades; **no** donut, treemap, Sankey, fan |
   | Rendering | canvas or **SVG** (switchable; SVG suits theming and print) | canvas | canvas |
   | Performance | good to ~100k points | best by far: millions of points | very good, built for price series |
   | Theming | registered themes, built from our CSS variables at run time | CSS file plus options | options |
   | CSP | clean (sets inline styles only through the DOM, which `style-src` allows) | clean; ships its own CSS file, served as ours | clean |
   | Accessibility | ARIA description generation built in | none | none |
   | Catch | size; a large API surface | we write and maintain the non-time-series charts | **requires a TradingView attribution link on the chart**; only covers prices |

   **Apache ECharts**, lazily imported by the chart screens through a small
   `app/charts/` wrapper (theme from tokens, table-view toggle, number formatting). Sign-in and
   the first screen's budget (S17.3.4: under 150 KB) stay unaffected. It is the only one
   of the three that covers every chart in S5–S7 without code of our own. **uPlot** is the
   choice if size and a minimal surface matter more than coverage, at the cost of a few
   hundred lines of our own SVG for donut, treemap and Sankey. **Lightweight Charts** is
   best kept as a possible *addition* for the holding-detail price chart, not the base.
   Chart.js (MIT, ~70 KB) was considered: it is wide enough except for treemap and Sankey
   (plugins), but its time axis needs a separate date-adapter dependency and its ESM build
   imports a further package. It offers less than ECharts for little size saved.

   The mockup draws its charts with small hand-written SVG functions, so it stays one small
   file and doesn't pre-empt this choice.
5. **Tests and checks**, all run by `web/check`, with no Node.js: pytest with a throwaway SQLite per test (most of the
   weight: lots, gains, wash sales, option assignment, imports, budgets, projections, sharing,
   links), browser component tests in headless Chromium driven by Playwright for Python, Deno
   check/lint/fmt, ruff, OpenAPI and typedef drift, mockup drift, the help-guide checks and
   the dependency register's hash check (S17.2.1).
   Browser tests use a small in-page runner (`web/ui/tests/run.js`) and a fake API; one
   smoke test drives a running dev server. **Golden files**: a fixture portfolio with known
   8949 rows and TXF output, checked byte for byte. **Receipt reading**: the field parser is
   tested on OCR text, and a set of fixture receipts (phone photos, flatbed scans, text-layer
   PDFs; skewed, faded, rotated) runs through the real RapidOCR worker against expected date,
   total and merchant, with an accuracy floor that a change must not drop below.
6. **`web/dev.sh`** is the developer's front door: alone it prints its commands (`setup`,
   `run`, `test`, `check`, `mail`, `mockup`, `help-shots`, `deno`, `vendor`, `audit`,
   `base-update`, `mocks`). `web/pins` holds the versions and hashes of the dev-only downloads
   (Deno, Playwright's Chromium).
7. **Dev mode** (`web/dev.sh run --seed --stubs`, `moolakata dev`) runs the whole server from a
   checkout as the current user, relaxing the surroundings, never the rules: sessions, CSP,
   encryption and sharing behave as in production. The one exception is the recovery phrase: a
   dev server makes its key on first run and keeps the phrase in `web/.dev/phrase`, so it
   unlocks itself at every start; its data is throwaway, and an installed server never does
   this (S15.4). `https://localhost:37373` with a self-signed certificate, `web/.dev/` for
   data, receipts and mail, seed users (`admin`, `alice`, `bob`, a *Household* group), a year
   of seeded transactions across every account type, open and closed option positions with an
   assignment and a wash sale, budgets, two projections, receipts, a **stub price source**
   (deterministic random walks, `--stubs`), and a **stub wallet source** (a made-up history,
   the same for an address every time), which nothing outside answers. The stub is a source
   Settings › Bitcoin saves like any other, and a seeded server saves it; until then wallets
   wait, as an installed server's do (S16.7). A second dev server on another port with `--peer`
   lets links be exercised on one machine. Emails are written to `web/.dev/mail/` and their
   links printed. A red **DEV** pill shows on every screen. For testing from another machine,
   `--listen` sets the address it listens on and each `--hostname` adds a name (or address) to
   its certificate, which is made again when it doesn't cover them all; `web/dev.md` describes
   the setups. Dev mode refuses to run as root, outside a checkout or on an installed server's
   data directory, and never calls a real provider unless one is configured; the image leaves
   dev mode's code out.
8. **Packaging: one Docker (OCI) image for the server** (the connector has an image of its own,
   S18.10) holding its own Python and venv, the browser app, RapidOCR's models and the
   `moolakata` command, running as an unprivileged user (uid 10001). It serves on port 37373
   and takes two mounts: the **data directory** (database, keyring, receipts, linked copies)
   and the **backup directory**. `moolakata.toml` is mounted too, at `/etc/moolakata.toml`;
   where mounting a file is awkward, the same TOML is given in the environment variable
   `MOOLAKATA_CONFIG`, read when `--config` names no file. The configuration holds no secret
   either way: secrets never come from environment variables, and no key is mounted at all: the master key is the recovery phrase,
   entered after every start (S15.4). `install/compose.yaml` is the example to start from; it
   publishes the plain-HTTP listener on the host's loopback only (the proxy examples reach the
   service by name), gives the container the host's time zone (`/etc/localtime` and `TZ`,
   S14.9.2), and keeps the logs Docker holds to five files of 10 MB. The example
   `moolakata.toml` trusts only the proxy's own address (S13.3). `docs/operations.md` is the
   runbook: installing, upgrading, backups, health, logs, restoring and drills. The image is
   about 600 MB, most of it the receipt reader (ONNX Runtime, OpenCV and the models); the
   reader's worker takes about 350 MB more while it runs, which a host too small for it avoids
   by turning reading off (S9.8.7).
   1. **Architectures**: one multi-architecture image for **amd64** and **arm64**. A release
      builds each natively, on a GitHub runner of its own architecture (S17.10); a build of
      the other architecture on a developer's machine runs under QEMU emulation. Every
      dependency must install from a published wheel for both (onnxruntime, opencv, numpy,
      pi-heif, sqlcipher3 among them), so nothing is compiled in the image; a check fails
      when one has no arm64 wheel. Each architecture's release gate is `web/install/smoke.sh`
      on its own runner (a refused start, the welcome's key and first admin, a locked restart and
      its unlock, health, a sign-in, a receipt read, the connector's vault made on its page and
      its unlock after a restart, clean stops); the trial on household hardware
      (a Raspberry Pi, an arm64 NAS), which alone measures the reader's speed there
      (S9.8.4.5), is in the manual test plan (S17.9.7.8), and a release says whether it was
      run.
   2. **Published images.** Each release is published as `ghcr.io/mojokata/moolakata` and
      `ghcr.io/mojokata/moolakata-connector`, tagged with the version, one tag for both
      architectures. There is no other tag, no `latest` and none that moves: a server starts
      locked after every update (S15.4), so an upgrade is always the household's decision.
      Each image has a build-provenance attestation that anyone can check. The check
      `gh attestation verify oci://ghcr.io/mojokata/moolakata:<version> -R MojoKata/MoolaKata
      --signer-workflow MojoKata/MoolaKata/.github/workflows/release.yml --source-ref
      refs/tags/v<version> --deny-self-hosted-runners` passes only for an image that
      `release.yml` built from the version's tag on GitHub's own runners. Each release is
      also on Docker Hub, as `docker.io/mojokata/moolakata` and
      `docker.io/mojokata/moolakata-connector`, copied with the same digests, so the same
      attestation and the same check cover those copies.
      The compose files name them, so a host pulls them. The image can still be built from
      the source, and carried to a host with no internet access (`docker save` and
      `docker load`). Catalogs make the install a form rather than a file: TrueNAS's apps
      catalog first (S17.8.3.1); others may follow.
   3. **Documented hosts**: **Proxmox** (Docker in a VM, or in an LXC container with nesting
      on) and **TrueNAS** (a custom app from `install/compose.truenas.yaml`, its configuration
      in `MOOLAKATA_CONFIG` and a one-time step giving the datasets to the server's account,
      so nothing is typed in a shell). `DEPLOY.md`
      takes a test server onto each, step by step, from a fresh Debian VM on Proxmox VE and
      from TrueNAS Community Edition's **Install via YAML**; `operations.md` covers their
      mounts, backups and upgrades.
      1. **TrueNAS's catalog**: `publish/truenas/` holds MoolaKata and the MoolaKata
         Connector as two apps for TrueNAS's community catalog (`ix-dev/community/moolakata/`
         and `ix-dev/community/moolakata-connector/` in `truenas/apps`), each with its
         metadata, its install form, its compose template and its test values (one plain,
         one with a certificate, one on host paths and the host network). TrueNAS decides
         what its catalog includes; until the apps are in it, **Install via YAML** is the
         way, and once they are, TrueNAS's own update bot moves their images to each new
         release.
      2. **The server's form**: its time zone, in TrueNAS's own field, which a user's
         **Auto** zone follows (S14.9.2); the addresses browsers use, for the certificate the
         server makes for itself; the web port (37373); a certificate from **System ›
         Certificates**, or none for the server's own, its help saying that TrueNAS restarts
         the app when it renews the certificate and the server then starts locked (S15.4);
         the data and the backups storage, each an ixVolume (the default) or a host path,
         a host path given to the server's account when its top directory belongs to
         anyone else and it holds no files yet, its help saying that the folders above it
         must let the account through (an SMB dataset needs it given Traverse); the host
         network, the Docker networks to
         join and labels, as every catalog app has them; and limits of 2 CPUs and 4 GB.
      3. **The connector's form**: the same for its page (S18.11.1): its time zone; its
         addresses, at least one, since the first is the one MoolaKata links to and the
         install stops without it; its port (37374); a certificate, with the same help; one
         storage for its data; and limits of 1 CPU and 1 GB. Neither form offers extra
         environment variables or storage, which every other catalog app has: neither app
         has a setting to tune or reads anything outside its own storage, and the
         connector's one other variable, a development switch, would let it reach the
         addresses its egress check refuses.
      4. **What the templates fix**: `tls` mode, its configuration in `MOOLAKATA_CONFIG` (the
         connector's in its own variables); each image's own account (10001, 10002), which
         the catalog's permissions step gives the storage to, so there is no user and group
         section; the image's health check (alive, S13.6); no capabilities, no new
         privileges, `/tmp` and the socket's directory in memory; a read-only root
         filesystem unless a certificate is chosen, since compose copies a chosen
         certificate into the container and a read-only root can't take it; and notes,
         shown at install, on the welcome and the locked start.
      5. **Tried before TrueNAS sees them**: `check.sh` renders each test case with TrueNAS's own
         renderer, in a checkout of their catalog, starts it, and fails unless it came up
         alive, as its image's account, with the root filesystem the case calls for and the
         certificate it was given or made. `create-pr.sh` runs it, checks each image's
         provenance (S17.8.2) and pins it by its digest, and puts both apps on a branch of
         `truenas/apps` where TrueNAS's tools add their library and metadata. Nothing leaves
         the machine until the maintainer runs it again with `--open`, which pushes the
         branch to their fork and opens the pull request as a draft, or updates the open one.
         The request links the icons and screenshots TrueNAS copies to its own servers: the
         server's favicon, and in `publish/truenas/media/` the connector's icon (its page's
         mark) and screenshots of the release's pages over the dev seed's household.
   4. **TLS**: the example `compose.yaml` runs in `proxy` mode behind the household's
      reverse proxy. A second example runs `tls` mode with a self-signed certificate for
      testing on a local network (S13.3).
   5. **The base image's updates.** The Dockerfile pins its base by digest, so a rebuild
      changes nothing until the digest moves, and the image never runs `apt-get upgrade` at
      build: the same Dockerfile gives the same image. The digest moves with each release,
      and between releases when Debian or Python publishes a fix for something the image
      uses (OpenSSL, zlib, libjpeg, expat, SQLite, Python itself): `web/dev.sh base-update`
      fetches the tag's current digest, writes it into the Dockerfile and the register
      (`docs/dependencies.md`, with the date and what the move picked up), and prints the
      Debian packages that changed between the two for the commit message. `web/check`
      warns, without failing, when the pinned digest is older than 90 days, since the check
      needs the network and a release shouldn't fail on it.
9. **Milestones**. The requirements describe the finished product; this is the
   order to build it in. Each milestone ends with `web/check` passing, a Docker image that
   runs, and the generated mockup covering what was built.
   1. **Milestone 1, the foundation and one household's accounts:**
      1. **Repository and tooling**: the layout of S17.1, `web/dev.sh`, `web/check`
         (pytest, ruff, Deno, Playwright, OpenAPI and typedef drift), `uv.lock`, and the
         Docker image for amd64 and arm64 with `compose.yaml` (S17.8).
      2. **Server core**: configuration, the listener in both modes (S13.3), the refused
         start (S13.6), the security policies (S13.7), the API conventions (S13.8), the live
         stream (S12.6), background tasks (S13.4) and dev mode with seed data (S17.7).
      3. **Storage and keys**: the SQLCipher database, the master key with its recovery
         phrase, `keys` commands and data key (S15), Alembic, the schema conventions with
         prefixed ids, soft-delete fields and `<Table>Effective` views, and the schema
         checks (`schema.md`); backups (S14.6).
      4. **Users**: the default admin's setup, invitations (email written to a folder until
         SMTP is set), sign-in, sessions, password reset, the active flag, groups, and
         Profile (time zone, theme). Two-step sign-in can wait for milestone 2.
      5. **Accounts and transactions**: account types for banking, cards, brokerage and
         retirement (S1.1, without loans, 529s, physical assets or crypto); manual entry,
         CSV and OFX/QFX import (S1.3.1–S1.3.2); transactions with categories; holdings and
         lots from brokers' files (S2); transfers matched (S1.7); reconciliation's coverage
         and anchors (S1.11).
      6. **Prices**: the `TickerSource` interface with Tiingo, Coinbase, manual and the dev
         stub (S4), the daily refresh, stored closes and staleness.
      7. **Sharing between users**: accounts and portfolios, read and write, users and
         groups (S10.3–S10.7), and Activity (S10.8).
      8. **The app**: the frame, navigation, help pane with its guides, theme and privacy
         mode (S12); Dashboard (net worth, accounts, needs attention), Accounts, an account's
         Overview, Transactions and Reconcile, the Transactions screen, Portfolios with
         Performance and Holdings, Settings (General, Sign-in and sessions, Passwords,
         Prices, Imports, Backups, Key storage) and Users and Groups.
      9. **The mockup** generated from the app for these screens (S12.9); the hand-written
         mockup stays the reference for everything not built yet.
   2. **Milestone 2**, in nine parts:
      1. **Two-step sign-in** (S10.1.6): TOTP set up from a QR code in Profile, the code
         after the password, ten recovery codes, and an admin's reset.
      2. **SMTP and emails**: Settings › Email with **Send a test email**, every email of
         S10.1.9 sent through it, and sign-up with its approval (S10.1.4).
      3. **Alerts** (S12.11): the screen, its badge, the emails and their daily summary,
         Settings › Alerts, and the causes milestone 1 and 2 have built.
      4. **Budgets** (S7.1–S7.5): planned, actual and rollover per category, the budget
         screens and recurring transactions.
      5. **Receipts** (S9.1–S9.7): upload, encrypted storage, thumbnails, the viewer, links
         and the inbox, sharing and retention.
      6. **Reading receipts** (S9.8): the worker process, RapidOCR with its shipped models,
         the field parser, matching, search and Settings › Receipts.
      7. **Statement import** (S1.3.3.1–S1.3.3.4): bank and card statements, read and
         checked, with their layout learned per institution.
      8. **Projections and assumptions** (S6.1–S6.9): Profile › Assumptions, the models,
         scenarios, active projections with tracking, the Dashboard's Plans card, and
         Settings › Tax tables with the contribution limits and the bitcoin models' figures.
         Retirement and savings-target goals; the education goal comes with 529s.
      9. **The mockup** generated from the app for these screens, and the Docker image.
   3. **Milestone 3**, in nine parts:
      1. **Loans** (S1.9): terms, the amortization schedule, payments split from their
         transfers, reconciling with the servicer, and the loan's screen.
      2. **The payoff planner** (S6.10): plans against the schedule, recast, and the extra
         invested instead.
      3. **Physical assets** (S1.10): items, their valuations (spot for metals, dated
         values, depreciation), real estate with its loans' equity, and selling.
      4. **529 plans** (S1.8) and the **education goal** (S6.2.2), with the college-cost
         averages in the tax tables.
      5. **Gifts** (S7.7–S7.8): people, occasions and holidays, gifts and ideas, history,
         privacy, the gift-tax flag and the occasion alerts.
      6. **Charitable giving** (S7.9): giving plans, donations and organisations, pledges,
         donor-advised funds and the Giving screen.
      7. **Tax books** (S8.14–S8.17): filers, accounts counted, sharing, filings, tax
         documents and what is carried forward.
      8. **The tax panels and exports** (S8.1–S8.13): Form 8949 and Schedule D with wash
         sales, income, retirement, deductions, the documents checklist, giving, education,
         gifts, loans and physical assets; 8949 CSV, TXF and the PDF summary.
      9. **The mockup** generated from the app for these screens, and the Docker image.
   4. **Milestone 4**, in nine parts:
      1. **Positions** (S3.1, S3.9): the Positions screen, open and closed, with each lot's
         holding period, and realized and unrealized gains by year, month, account and
         instrument.
      2. **Options** (S3.2, S3.3): option contracts as instruments, the four opening and
         closing trades, short options as negative lots, and their gains at close.
      3. **Expiry, assignment and exercise** (S3.4, S3.6): expiry applied the day after out
         of the money, an in-the-money expiry asked about, and assignment and exercise
         folding the premium into the stock's basis or proceeds.
      4. **Option marks and trades** (S3.7, S3.9, S4.5): marks from a source, typed, or
         intrinsic; per-trade P/L and return on capital at risk; options in Form 8949 and
         flagged for wash-sale review; and the wash-sale basis carried into the replacement
         lot.
      5. **Bitcoin wallets** (S1.6.1, S1.6.3): addresses and extended public keys, the
         addresses derived from them with a gap limit, and the form that refuses keys and
         seed phrases.
      6. **Bitcoin sources** (S1.6.2): Settings › Bitcoin with a public explorer or the
         household's own node (Esplora, an Electrum server, Bitcoin Core), and the wallets'
         balances and history kept current from it.
      7. **Access tokens** (S10.9.1): Profile › Access tokens, their scope and expiry, shown
         once and stored as a hash.
      8. **The MCP endpoint** (S10.9): `/mcp` over Streamable HTTP, read-only tools through
         the user's shares, limited and recorded in Activity.
      9. **The mockup** generated from the app for these screens, and the Docker image.
   5. **Milestone 5**, in nine parts:
      1. **Link keys and the protocol** (S11.1.3): each server's Ed25519 link key,
         signed calls with their timestamp and nonce checks, the `/link` listener, the
         `Link` record, and `docs/link-protocol.md` with how versions differ.
      2. **Invitations** (S11.1, S11.6, S11.7): the link code, the request and its
         approval, Settings › Linked servers with Pause and End link, and each side's
         active users and household name and avatar sent at every exchange, kept as remote
         `User` records.
      3. **Sharing with linked people** (S10.3.3, S10.4): the Share dialog's people on each
         linked server (None · Read) and Include receipts, and shares suspended or removed
         with their remote user or link.
      4. **The linked copy and its access key** (S11.9.1–S11.9.4, S11.9.8): the copy's
         folder and SQLCipher database, the 12-word access key and the keys derived from it,
         unlocking with its limits, the sweeper that locks an unused copy, Lock now and
         Reset copy.
      5. **Sealed files** (S11.9.5, S11.9.6): the streaming MKR1 format, the inbox of sealed
         changes applied in order once unlocked with each signature checked, receipts
         written straight into the copy, and the full snapshot when the inbox overflows.
      6. **Pulls** (S11.3.1, S11.4, S11.5, S11.8): each shared item worked out at its source
         as the people it names see it, versioned so only changes travel, signed, pulled
         hourly and on Pull now by whichever side can reach the other, copies deleted when a
         share or link ends, and each pull recorded on both sides.
      7. **The linked household window** (S12.10): the avatar menu and the Linked households
         card, `/ui/linked/<link-id>/` with the household's avatar and name, a colour per
         user, the header strip, the locked state asking for the words, and the screens
         read only from the copy.
      8. **Alerts and receipts across links** (S11.5.1, S12.11): a failing link and a first
         share waiting for its access key alerted, receipts and tax documents shown from the
         copy through decryption, and what an older or newer peer does.
      9. **The mockup** generated from the app for these screens, and the Docker image, with
         two servers linked.
   6. **Milestone 6**, what the requirements settled after milestone 5, in nine parts:
      1. **People and relationships** (S10.10, S7.7): people with sex and dates, every user
         a person, dated relationships and the family tree, gift plans, the duplicate-name
         check and ask-to-share, the spouse read by date for wash sales and tax books, and a
         deleted person's gifts. Tax-book dependents (S8.14.5).
      2. **Statements, more of them** (S1.3.3.5, S1.3.3.6, S1.11.7): a combined statement
         split per account, a statement kept without reading, and statements expected per
         account with their alert.
      3. **Brokerage and plan statements** (S1.3.3.8): the summary as a balance anchor, the
         positions as a holdings check, the cash activity, and trades offered to the trade
         dialog.
      4. **File retention and pruning** (S14.10, S16.17): when each record ended, a
         category's and the statements' retention, each file's *Kept until* and Keep, and
         Settings › Storage with Prune.
      5. **Strategies** (S3.5): grouping proposed and by hand, rolls, the shapes, max profit
         and loss, breakevens, and capital at risk now and at open on Positions, the account
         and the portfolio.
      6. **Adjusted contracts** (S3.10): whole-number splits applied with the stock's, other
         adjustments from the OCC memo with their root and deliverable, linked on import,
         assigned and exercised by deliverable, and marked under the new root.
      7. **Bitcoin, the rest** (S1.6, S1.7.1, S8.19): output descriptors, the node's
         certificate trusted on first use, confirmations and reorgs, bitcoin kept in sats
         with Profile's BTC or sats, transfers between wallets matched with their lots, and
         network fees as sales.
      8. **Links, the rest** (S11, S12.10): every screen of each shared kind in the linked
         window, `/link/` as a path, sync oldest to newest with its progress, and Pause for a
         duration with Resume now (S12.13).
      9. **The mockup** generated from the app for these screens, and the Docker image.
   7. **Milestone 7**, what the first release still needs, in ten parts. The build has no
      bitcoin node, arm64 machine, second network or Schwab developer account, so what needs
      one is built against a mock here and tried for real from the manual test plan
      (S17.9.7.8):
      1. **Python 3.14**: `requires-python`, a fresh `uv.lock` with its egress audit
         (S17.2.1), the image's base, the wheel check and the register, so the connector
         starts on it too. Every native dependency publishes wheels for it on both
         architectures, and 3.14 is supported two years longer than 3.12.
      2. **The connector protocol**: `docs/connector-protocol.md` in the form of the link
         protocol (pairing from the one-time code, the signed calls, the report, collecting
         a sealed credential, posting a file, the refusals, the version rule), and the
         `Connector` and `Connection` tables (`schema.md` §3.2).
      3. **MoolaKata's side** (S18.4, S18.5): the `/connector/v1/` routes, pairing with its
         code and re-authentication, Settings › Connector with Pair and Unpair, the two
         admin alerts and the silent-connector check (S13.4).
      4. **Connections in the app** (S18.6, S18.7): the account's **Sync using MoolaKata
         Connector** switch, Profile › Connections, the credential dialog sealing to the
         connector's key in the browser (X25519 in WebCrypto), the command for typing them
         on the connector's host, and the owner's alert.
      5. **The connector core** (S18.1–S18.3): `connector/`, its vault and words, lock and
         unlock over its socket, pairing, signed calls, the egress allowlist, its image and
         the `connector` service in `install/compose.yaml` (S18.10), and `operations.md` §8.
      6. **The posting path** (S18.8), proved end to end with a driver that needs no
         credentials.
      7. **OFX Direct Connect and Schwab** (S18.9.1, S18.9.2), each built against a mock of its
         institution: a fake OFX server, and a stub serving recorded shapes of the Trader API's
         answers. The live Schwab trial is in the test plan.
      8. **Mocks and the manual test plan**: a fake Esplora, Electrum server and Bitcoin
         Core RPC speaking the subset MoolaKata uses, for the tests and the generated
         mockup's recordings; the arm64 image built under QEMU and smoke-run under
         emulation; and `docs/test-plan.md`, one numbered test per thing the build can't
         try, each with the environment it needs, its steps and what passing looks like:
         wallets against Fulcrum, electrs, Bitcoin Core 27 and later and a self-hosted
         mempool; links over an overlay such as Tailscale and over a forwarded port; the
         arm64 image on real hardware; the Schwab driver with a real developer account; an
         install on Proxmox and on TrueNAS (`DEPLOY.md` §3–4); and a restore drill
         onto a new host. A release says which were run.
      9. **Hardening**: `web/dev.sh audit` and the register's hash check in `web/check`
         (S17.2.1), the base image's update process (S13.7.11), and the real receipt
         fixtures for the reader (S17.5).
      10. **The mockup** generated from the app for these screens, both images, and
         `web/check`.
   8. **Milestone 8**, what the second review of the requirements against the code found the
      first release still needs, in nine parts:
      1. **Access**: host commands over the server's Unix socket, and the example's trusted
         proxy narrowed to the proxy's own address (S13.3, S13.6); a linked household's
         receipts served as a local receipt is (S11.9.6.5); access tokens made with the
         password again and stopped by a password change (S10.9.4); the password again on every
         action of S13.7.2, a secret cleared when its host changes (S16.2, S16.7); and access
         between users as S7.1.1, S7.9.1, S8.14, S9.6 and S10.10 say.
      2. **Transport**: TLS verified on links and the connector, a certificate of a server's
         own pinned through its code (S11.1, S18.4); signed answers naming the caller and the
         request; only `link-ended` ending a link (S11.6); link changes and receipts sealed end
         to end to the receiving copy's key (S11.4, `docs/link-protocol.md`).
      3. **The reader's sandbox** (S9.8.4.2), with every file a person or the connector brings
         parsed in it.
      4. **Key operations**: the journal, re-encryption only while the server isn't serving,
         rotation that re-encrypts (S15.7), the restore that re-wraps the receipts (S15.6.8),
         host commands taking the data directory's lock (S15.4.7), and the unlock's report of
         what a restored database can't open, re-encryption's progress and restoring a
         `pre-upgrade/` copy.
      5. **Figures**: the lots, wash sales, reinvestments, deductions, options from broker
         files and loan rates the review found wrong, and Form 8949's digital-asset boxes
         (S8.1).
      6. **Categorisation and payee rules** (S2.6, S2.7).
      7. **The rest of what was promised**: symbol changes, spin-offs and mergers (S2.4); the
         closed-year confirmation (S2.8); a short stock lot from an assignment with no shares
         (S3.4); `/link`'s rate limits (S13.7.5.4) and uploads in flight (S13.7.6); the
         orphan-file sweeper and who viewed linked data (S11.8, S11.9.6.6); the recovery-code
         and new-address emails (S10.1.9); a tax document's file through its tax book and
         receipts on gifts and donations (S8.16, S9.3); the alerts S12.11.1 lists that aren't
         raised yet; problem types and codes in the OpenAPI document (S13.8.3); and a separate
         allowlist for each driver, with its test (S18.1.2).
      8. **The connector**: the Folder driver taken out (S18.9), the lost-host response
         (S18.4.4, S18.5.4), the credential bound to the host sealed with it (S18.7.3), the
         sealing key signed by the identity key, the sign-in host pinned, and the quick
         exchange of a landed address (S18.5).
      9. **The rest of the review's findings**, the generated mockup and help shots for what
         changed, both images, and `web/check`.
   9. **Milestone 9**, what the second review's account of its findings against the code
      (`docs/reviews/initial-code-review-2.md`, section 12) found still open, in nine parts:
      1. **Sign-in**: a two-step sign-in ended after five wrong codes, one code checked at a
         time, the slowdown before the check, and the lockout counting an IPv6 address by its
         /64 (S10.1.6.3, S13.7.5.1); reactivation, re-authentication and the current-password
         check behind the sign-in guard, a reactivation request answered the same whatever the
         account, and sign-up taking the same time for an address already known (S10.1.4.1,
         S10.1.7); and what errors and logs may hold (S13.7.8, S13.7.9).
      2. **Email queued in the database** (S16.2, S15.1.7): an email waits there until it is
         sent or its link expires, a refused one keeps only its recipient, subject and error,
         and a written email stays in the mail folder as long as its link works.
      3. **The connector**: the key MoolaKata's `hello` gives hashed against the pairing's
         fingerprint (S18.4.2), and `connect` showing the host the credentials will go to and
         filing them once the admin confirms it (S18.7.2).
      4. **Links**: a call not yet signed by a known key refused before it opens a transaction
         (S13.7.5.4); a copy's key gone with its release; a change applied once and in order
         (S11.9.5.3); a pull recorded with its link (S11.8); a shared budget naming only the
         accounts shared (S11.3.1); a person shared to a linked server (S10.3); what flows each
         way in Settings › Linked servers (S11.7); and the link protocol's answers and
         refusals stated once (`docs/link-protocol.md` §1.3, §7).
      5. **The host and the reader**: a PDF page rendered within the pixel cap (S9.8.4.3);
         uploads held in memory (S13.7.6); Remove copy asking for the phrase too (S16.13);
         `verify-backup` showing when a backup was made; the live stream's alert event without
         a title; dev mode only from a checkout; pruning that counts no deleted receipt
         (S14.10.5); a restore that leaves the receipt files where they are (S15.6.8); and an
         unlock counted as a check of the recovery phrase (S15.6.5).
      6. **Figures**: an option's expiry decided on the expiry day's close only (S3.6); a wash
         sale's replacement in an IRA (S3.8.3); an adjusted strike rounded (S3.10.1); PMI in a
         payoff plan (S1.9.5); a portfolio's returns keeping a deleted account, a donated
         replacement's holding period, and TXF's codes (S5.2, S7.9.3, S8.2); and the last
         money columns in cents (S14.3).
      7. **Imports, wallets, alerts and the contract**: imports' answers in exact numbers
         (R1.9); no wallet read until Settings › Bitcoin is saved (S16.7); skips learned only
         from lines left out by choice (S1.3.3.4); the stale statement value's alert (S4.3);
         a loan's statements checked on its Overview (S1.11); and every problem code, and
         every 422, in the OpenAPI document (S13.8.3).
      8. **Tests**: a golden-file case for each figure the second review found wrong (S17.5),
         a `Location` test that follows what it names, and tests for the fixes that had none.
      9. **The rest**: the generated mockup and help shots for what changed, both images, the
         review's section 12 brought up to date, and `web/check`.
   10. **The first release** is the nine milestones. The build's branch is committed and pushed
      part by part, and merges into `main` only once all of it is built and the requirements
      have their final approval.
   11. **After the first release**: the items of [later work](later.md), L1 to L12.
   12. **Milestone 10**, after the first release: budgets as S7 describes them, in ten parts,
       each pushed on its own and the whole checked at its end:
       1. **What a budget counts** (S7.2, S7.3.1–S7.3.3, S7.3.9): savings categories and the
          shipped *Cash*, *Savings* and *Loan payments*; refunds in the month they land, and
          pending transactions left out; money leaving or entering the budget, listed to sort
          when it has no category, and the accounts left out named when a budget is made or
          edited; and loan payments counted at the bank, split by the schedule or whole as each
          loan says (S1.9.7), starting with a test of how a matched loan payment counts before
          the change.
       2. **Cash and payment apps** (S1.1, S1.7, S1.11.7): the `cash` and `payment-app` types,
          their icons, forms and statement defaults; cash taken out paired with its deposit in a
          cash account; and a cash account outside a budget counted as *Cash*.
       3. **Reimbursable spending** (S2.9, S7.3.4): the mark on a transaction or a split, with
          its amount and who owes it; **Awaiting reimbursement**; paybacks offered and paired,
          one deposit paying back several; and what budgets count of each.
       4. **A budget's method, options and plan** (S7.1.3–S7.1.6, S7.3.6–S7.3.8, S7.2.1): the
          method and options chosen at creation and the options changed in its settings; each
          card's *paid from* and each savings account's *moved from*, with the default worked
          out (S7.1.6); *Gifts* and *Giving* planned by their plans; what overspending
          does, per line; a savings line naming a projection; and **Estimate from history**.
       5. **Reserves** (S7.10): targets changing from a month on, balances worked out, Funded,
          the question before a balance stops being kept, *held in* across several accounts,
          and **Where the money is** with *to move*, *backed*, a shortfall, landed money left
          unassigned until given, and **Withdrawals allowed a month** (S1.2) with moves back
          summed into one transfer and the warning past the limit.
       6. **Moves and leave-outs** (S7.11, S7.3.5, S12.2.3): moves between categories, reserves among them, and
          **Cover from…**, the month's moves, their Activity, a move in a past month; and a
          transaction's **In budgets** line with each budget's **Leave out**.
       7. **The active budget and scenarios** (S7.12, S12.2.1, S12.2.6): each user's active
          budget, **Make active**, **Copy as scenario…**, **Compare**, the scenario's banner,
          the Budgets list, and the Dashboard's card of the active budget's month.
       8. **Envelope budgets** (S7.13): *To Budget* from the budget's first month, assignments
          by the plan and by moves, card payment lines, *owed, not backed*, a starting debt,
          and what an overspent envelope does at the month's end.
       9. **The review, the cache and the alert** (S7.14, S7.3.10, S7.6, S12.11): a month
          marked reviewed and flagged when it later changes; month figures kept, worked out
          again when what they come from changes, and **Refresh**; and the cash before payday on each checking account with
          recurring payments.
       10. **The rest**: a golden-file case for every new figure (S17.5): carries and
           rollover, reserves, moves, *to move*, *To Budget*, card payment lines, a loan's
           split, reimbursements and money leaving the budget; the generated mockup and help
           shots for what changed; both images; and `web/check`.
10. **Continuous integration and releases**, on GitHub Actions, whose standard runners are
    free for a public repository.
    1. **Checks**: `.github/workflows/check.yml` runs `web/check` on every pull request and
       every push to `main`, after `web/dev.sh setup`, with uv installed from
       `install/build-requirements.txt` by its hashes.
    2. **Releases**: `.github/workflows/release.yml`, on a `v<version>` tag matching
       `web/VERSION`, builds both images on an amd64 and an arm64 runner, runs
       `smoke.sh` on each (S17.8.1), pushes the images that passed to `ghcr.io/mojokata`
       under per-architecture tags, joins them under the version's tag, and attests each
       (GitHub's build provenance, signed through Sigstore's public instance and recorded in
       its transparency log, and kept in GitHub's attestation store, not in the registry).
       Then it copies both joined images to Docker Hub with their digests unchanged
       (S17.8.2), and drafts the GitHub release with the tag's install files attached: the
       compose files, the example `moolakata.toml` and the proxy examples. On a pull request that touches what goes into the images, it builds and
       smoke-runs both and pushes nothing. A new package on ghcr.io starts private: after the
       first release, an owner of MojoKata makes both public, once.
       1. **Tags and releases**: the maintainer who makes a release signs its tag with their
          own GPG key and pushes it. Once the published images check out, the same
          maintainer publishes the draft with its notes (`docs/RELEASE.md`; `web/release.sh`
          runs these steps from a terminal, one command each). Releases are immutable
          (GitHub's setting, with a ruleset on `v*` tags): once a release is published, its
          tag and files can't change, and GitHub attests the release.
       2. **The version between releases**: `web/VERSION`, which the server, the app and
          the API's document read, and the connector's own version name a release only on
          that release's commit. Once a release is published, `main` moves to the next minor
          release with `-dev` (after 1.4.2, `1.5.0-dev`), so a build from `main` never
          carries a released version. The next release's pull request gives it the number that
          release takes, whether patch, minor or major. The compose files and the install guide
          keep naming the last release meanwhile, since that is what they install.
    3. **Their own dependencies**: the actions are GitHub's own (`actions/checkout`,
       `actions/attest-build-provenance`), pinned by commit and listed in the register
       (S17.2.1). Everything else is the repository's own scripts and the runners' own
       `gh`. Each job's token has only the permissions it needs: `contents: read`
       everywhere, `packages: write` to push, `id-token` and `attestations: write` for the
       attestation alone, and `contents: write` only to draft the release. The one secret,
       Docker Hub's token, lives in an environment (`docker-hub`) that only runs for `v*`
       tags can read.
