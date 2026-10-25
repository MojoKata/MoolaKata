# Code review 3, unit 11: implementation

**Session:** Oct 24, 10:37 PM to Oct 24, 10:49 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S17 (implementation), its summary and ten item files: S17.1 layout, S17.2 server
  dependencies (S17.2.1 the register and audit), S17.3 the browser app (vendoring, CSP, size,
  caching), S17.4 charts, S17.5 tests and checks, S17.6 `web/dev.sh`, S17.7 dev mode, S17.8
  packaging (S17.8.1 architectures and smoke, S17.8.2 publishing, S17.8.3 hosts and the TrueNAS
  catalog, S17.8.5 the base image), S17.9 milestones (the build plan), S17.10 CI and releases;
  with `docs/DEPLOY.md`, `docs/RELEASE.md`, `docs/dependencies.md` as far as this code builds
  them, and the README's R1–R3 lines they rely on (R1.5 dev mode, R1.14 charts, R3.1 outbound
  calls).
- **Code (8,301 lines, 77 files):** `src/dev/` (seeds, `mocks.py`, `audit.py`, `wheels.py`,
  `devmode.py`, `base.py`), `src/static.py`, `web/check`, `web/dev.sh`, `web/release.sh`,
  `web/pins`, `web/VERSION`, `web/dev.md`, `web/server/pyproject.toml`, `.dockerignore`,
  `web/install/` (Dockerfile, build-requirements.txt, four compose files, `moolakata.toml`,
  `proxy/`, `smoke.sh`), `publish/truenas/` (the two catalog apps, `check.sh`,
  `create-pr.sh`), `.github/workflows/{check,release}.yml`, `ui/mockup/` (`build.py`,
  `help_shots.py`, `iso.js`, `menu.js`, `runtime.js`), `ui/deno.json`.
- **Tests (1,016 lines):** `tests/conftest.py`, `test_install.py`, `test_mocks.py`,
  `test_mockup_app.py`, `test_static.py`, `test_vendor.py`.
- **Guides:** `ui/guides/new-server.md`, as far as install goes.
- **Cites no section:** `ui/deno.json` (the packaging and CI files show none only because
  `check_docs.py` doesn't scan them).

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 3,250 lines (39%), 33 new files. New: `web/release.sh` (418),
`.github/workflows/check.yml` (63) and `release.yml` (162), the whole of `publish/truenas/`
(two apps, `check.sh` 152, `create-pr.sh` 256), `web/install/compose.truenas.yaml` (56),
`compose.connector-truenas.yaml` (42), `moolakata.toml` (28), `src/dev/seed_budgets.py` (146).
Changed most: `tests/test_install.py` (+311/−30), `smoke.sh` (+114/−62), `ui/mockup/build.py`
(+140/−18), `ui/mockup/runtime.js` (+112/−41), `compose.yaml` (+45/−20), `tests/conftest.py`
(+40/−22), `seed_accounts.py` (+30), `compose.tls.yaml` (+24/−17), `seed.py` (+20/−8),
`Dockerfile` (+19/−15), `seed_links.py`, `seed_connector.py` (+17/−11 each), `static.py` (+9/−5),
`web/check` (+7/−6), `web/dev.sh` (+8/−8), `pyproject.toml` (+4/−4); the rest renamed only.
Read first: `release.sh`, both workflows, the TrueNAS apps and scripts, the compose files,
`Dockerfile`, `smoke.sh`.

### 3. Earlier reviews' findings in this area

Review 1 has none on this unit's files beyond the Docker-secret sentence (F4.4, S15.4.5: unit
10's). Review 2 (§12.2):

| Finding | What | State per review 2 | To re-check |
|---|---|---|---|
| K25 (last point) | dev mode is in the image and doesn't refuse outside a checkout (`main.py:53`) | built in m9 parts 4/5 | `devmode.py`, `main.py`, `Dockerfile`, `.dockerignore` |
| K1 | the host-loopback port in `compose.yaml` let a container reach the key routes | done (m8 part 1, the socket) | `compose.yaml`'s ports, the socket's mount |
| K10 (point 2) | `docker compose run` keeps the sheet in Docker's log | done (m8 part 4) | compose's logging, `smoke.sh` (U10-15 covers `db shell`) |
| B28 | the container runs in UTC: compose passes no `TZ` or `/etc/localtime` | done (m9 part 9) | the four compose files, the TrueNAS templates |
| C29 | `web/dev.sh`'s list in S17.6 omits `vendor`, `audit`, `base-update`, `mocks`; the register's hashes in `web/audit.json` | done | S17.6 against `dev.sh`; S17.2.1 |
| C51 | S17.9.8's "the first release is the seven milestones" | done | S17.9's wording against what is built |
| Tests (§12.2 last row) | golden-file tests with each figure's fix (S17.5) | m9 part 8, but B7's rerun | unit 01's U01-13 holds it; not raised again |
| §12.3.3 | the arm64 image never run on arm64 hardware | open (test-plan T7) | `release.yml` runs smoke on an arm64 runner |

### 4. Phase 1 claims and decisions on these sections

None decided (the walk-through comes after assembly). Judged here against both readings:

- **DC-2 / D2-3** (Med, needs the user): `tls` mode is "for testing" (S13.3, S15.1.7, S16.15,
  DEPLOY intro) yet the TrueNAS templates and `compose.truenas.yaml` fix `tls` mode.
- **D2-22**: R1.5's "every rule as strict as production" against S17.7's phrase in a file.
- **D2-23**: S17.4 weighs chart candidates; **D2-24**: status words in S17.8.3.1, S17.9, S17.10.2.
- **DC-19**: the configuration's keys (`[server] name`) named only in DEPLOY and the example.
- **DC-20**: python-multipart has no ruling in S17.2.
- **DC-21**: S17.1's layout of `docs/` leaves out RELEASE.md, GENESIS.md, REVIEW.md, `reviews/`,
  `release/`, `external/`.
- **D3-16**: DEPLOY and operations differ on memory, what to empty, a restore's path, health states.
- **D3-17**: S17.8.2's one tag against the per-architecture tags `release.yml` pushes.
- **D3-18**: the attestation's job; RELEASE §12's list of `setup`'s checks.
- **D3-10 to D3-14**: the connector protocol's pairing, refusals and addresses: only as far as
  the TrueNAS connector app and `compose.connector-truenas.yaml` carry them.
- **Release-process memory**: `main` moves to the next `-dev` after each release (RELEASE §9,
  `release.sh next`).

### 5. Untraced candidates and uncited first-level items

- Untraced candidates: `ui/deno.json`.
- Uncited first-level items: S17.1 (layout), S17.9 (the build plan: each milestone item marked
  built is checked to be built), S17.10 (CI and releases).

## Claims

### U11-1: the egress audit's no-network run can't see a native or worker connection: in a namespace with no interface, an attempt leaves nothing to find

- **Kind:** differs. **Severity:** Low. **Req:** S17.2.1 (dependencies.md, the egress audit rule 1).
- **Code:** `web/server/tests/test_no_network.py:15–30`, `:39–44`, `:78–79`:
  ```python
  for table in ("/proc/net/tcp", "/proc/net/tcp6", "/proc/net/udp", "/proc/net/udp6"):
      ...
          remote = line.split()[2]
  ...
  def connect(self, address, *a, **k):
      if isinstance(address, tuple):
          host = str(address[0])
          if not host.startswith(("127.", "::1", "localhost")):
              attempts.append(f"{host}:{address[1]}")
  ...
  assert watched == [], f"a socket was opened to {watched}"
  assert _peers() == set(), f"native code reached {_peers()}"
  ```
  run by `web/dev.sh:115`: `unshare -U -n uv run --frozen pytest -q -m audit tests/test_no_network.py`.
- **What goes wrong:** S17.2.1 says the run fails "on any socket opened to a non-loopback
  address", and the test's docstring says "by Python or by native code". Inside `unshare -n`
  there is no route, so a `connect()` or a UDP `sendto()` to any outside address fails at once
  with `ENETUNREACH`, and the socket never gets a remote address in `/proc/net/*`: `_peers()`
  is empty whatever native code tried. The only thing that can fail the test is the
  monkeypatched `socket.socket.connect`, which sees Python connects in the test's own process
  only: not `sendto` (a DNS lookup, a UDP beacon), not native code (a library's C or Rust
  client), and nothing in the receipt worker, which is a separate process (`Worker()` at
  `:63`). A dependency update that adds a native telemetry ping or a model download in the
  worker passes the run silently: it just fails to connect. (The worker's seccomp filter
  stops it in production, but the audit is meant to find it, so the register can say so.)
- **Run:** a scratch script in `unshare -U -n` (`tmp/u11/netns_probe.py`): a TCP connect to
  1.1.1.1:443 and a UDP `sendto` to 8.8.8.8:53 both fail with errno 101, and
  `/proc/net/tcp` is empty, `/proc/net/udp` shows the UDP socket with remote `00000000:0000`.
- **Remedy:** record attempts where they can be seen: run the server and the worker under a
  seccomp or `strace -f -e trace=connect,sendto,sendmsg` filter that logs every non-`AF_UNIX`
  destination (or an `LD_PRELOAD` shim, or a namespace whose only route goes to a local
  catcher that logs SYNs and datagrams), and fail on any non-loopback one.
- **Alternatives:** S17.2.1 and `dependencies.md` say what the run proves: that the server
  works with no network, not that nothing tried.

### U11-2: a rerun of `release.yml` on a published tag rebuilds the images and moves the version's tag on both registries

- **Kind:** differs. **Severity:** Low. **Req:** S17.8.2 ("none that moves"), `RELEASE.md` §2
  ("A version is never reused"), §11 ("don't move its image").
- **Code:** `.github/workflows/release.yml:48–59` (push `"ghcr.io/$owner/$image:$version-${{ matrix.arch }}"`),
  `:84`:
  ```sh
  docker buildx imagetools create -t "$ref:$version" "$ref:$version-amd64" "$ref:$version-arm64"
  ```
  and `:132`: `docker buildx imagetools create -t "$to" "$from"`; nothing checks first whether
  `$ref:$version` exists.
- **What goes wrong:** *Re-run all jobs* on 0.2.0's run (a click anyone with write access can
  make, and §11 sends maintainers to that page for every failure) builds new images, whose
  digests differ (the build is not byte-reproducible: timestamps, bytecode), overwrites
  `0.2.0-amd64`/`-arm64`, re-joins `0.2.0` onto them, attests the new digests and copies them
  over `docker.io/mojokata/*:0.2.0`. Testers who pulled before hold one image, households after
  another, both "0.2.0", both attested; `release.sh check` passes for the new one. The git tag
  and the release are immutable, the image tag is not.
- **Remedy:** the build job (on `push`) and the joining job refuse when
  `ghcr.io/$owner/$image:$version` already resolves (`imagetools inspect` succeeds), unless its
  digest is the one being written; the Docker Hub job likewise refuses to replace an existing
  tag whose digest differs.
- **Alternatives:** RELEASE §11 warns never to re-run a release run after the joining job
  succeeded.
- **Run:** reading alone.

### U11-3: `release.yml` builds and smoke-runs on pull requests only when the packaging changes, not the code that goes into the images

- **Kind:** differs. **Severity:** Low. **Req:** S17.10.2 ("On a pull request that touches what
  goes into the images, it builds and smoke-runs both"), `RELEASE.md` §3 step 7.
- **Code:** `.github/workflows/release.yml:13–19`:
  ```yaml
  pull_request:
    paths:
      - .github/workflows/release.yml
      - web/install/**
      - web/server/uv.lock
      - connector/Dockerfile
      - connector/requirements.txt
  ```
  while the images take `web/server/src`, `web/server/pyproject.toml`, `web/VERSION`, `web/ui`,
  `docs/mockups/MoolaKata-mock.html` (`web/install/Dockerfile:19–29`) and the connector's
  package.
- **What goes wrong:** a pull request that changes only server code (say, an import the
  slim image lacks, a start that no longer refuses with 78, or a change to `sandbox.py`'s
  aarch64 numbers) passes `check` (amd64, no image) and merges; the smoke run first meets it
  on the next release's pull request, which touches `web/install/` for the versions, long
  after the change and among everything else since.
- **Remedy:** add `web/server/src/**`, `web/server/pyproject.toml`, `web/ui/**`, `web/VERSION`,
  `docs/mockups/MoolaKata-mock.html` and `connector/**` to the paths.
- **Alternatives:** S17.10.2 says "that touches the images' packaging", and accepts that a
  code change is first smoke-run at the release's pull request.
- **Run:** reading alone.

### U11-4: `release.sh sign` tags any commit it is given, one that was never on MojoKata's `main` included, and the push publishes it

- **Kind:** bug. **Severity:** Low. **Req:** S17.10.2.1; `RELEASE.md` intro ("A release is a
  `v<version>` tag on `main`"), §5 step 1.
- **Code:** `web/release.sh:120–123`, `:136`, `:140`:
  ```sh
  git -C "$ROOT" fetch -q "$up"
  commit=$(git -C "$ROOT" rev-parse --verify "${2:-$up/main}^{commit}")
  [[ "$(git -C "$ROOT" show "$commit:web/VERSION")" == "$version" ]] ||
  ...
  git -C "$ROOT" tag -s "v$version" -m "MoolaKata $version" "$commit"
  ...
  git -C "$ROOT" push "$up" "refs/tags/v$version"
  ```
- **What goes wrong:** `web/release.sh sign 0.2.0 HEAD` from a local branch with an unpushed
  fix signs that commit, and the tag push uploads the commit with it: `release.yml` builds and
  publishes code no pull request reviewed and `check` never ran on. The maintainer's ruleset
  bypass lets the push through, and the confirmation shows only the commit's subject.
- **Remedy:** refuse unless `git merge-base --is-ancestor "$commit" "$up/main"` holds (RELEASE
  §5's "that pull request's commit" is on `main`), and show whether `check` passed on it
  (`gh api repos/$REPO/commits/$commit/check-runs`).
- **Run:** reading alone.

### U11-5: `release.sh publish` checks the draft's files by name only, so a changed file is published and locked for good

- **Kind:** security. **Severity:** Low (not withheld). **Req:** `RELEASE.md` §8 ("checks that
  the draft holds exactly the tag's install files"), S17.10.2.
- **Code:** `web/release.sh:219–221`:
  ```sh
  wanted=$(install_files "$version" | xargs -n1 basename | sort)
  got=$(gh release view "v$version" -R "$REPO" --json assets --jq '.assets[].name' | sort)
  [[ $got == "$wanted" ]] || die "the draft's files aren't the tag's install files:
  ```
  then `:237–242` verify the published release and assets against GitHub's own attestation of
  what was published, not against the tag.
- **What goes wrong:** anyone with write access can replace a draft's `compose.yaml` (same
  name) between the draft job and `publish`, say with an image pinned to another digest. The
  name check passes, publishing makes the file immutable, and `verify-asset` then attests the
  substituted file as the release's.
- **Remedy:** compare each asset's SHA-256 (`gh release view --json assets` gives `digest`)
  with `git show "v$version:web/install/<name>" | sha256sum`, before asking for the typed tag.
- **Run:** reading alone.

### U11-6: `release.sh copy` signs in to Docker Hub in the maintainer's own Docker config and leaves the `mojokata` credential there

- **Kind:** security. **Severity:** Low (not withheld). **Req:** `RELEASE.md` §11 (the copy),
  §12 (the token's care: "without touching your own Docker logins").
- **Code:** `web/release.sh:300–301`:
  ```sh
  echo "Sign in to Docker Hub as $OWNER (its password, or a token with Read & Write):"
  docker login docker.io -u "$OWNER"
  ```
  where `cmd_token` (`:318–320`) and `cmd_check` (`:195–199`) use a throwaway `DOCKER_CONFIG`.
- **What goes wrong:** after a copy, `~/.docker/config.json` keeps the shared `mojokata`
  account's password or token (base64, unless a credential helper is set) for good, on the
  maintainer's machine, where any later `docker push` can write to the household images.
- **Remedy:** `TMP=$(mktemp -d)` and `DOCKER_CONFIG="$TMP"` for the login and the copy, as
  `token` does.
- **Run:** reading alone.

### U11-7: `create-pr.sh` pins a digest it resolved apart from the one whose provenance it checked

- **Kind:** security. **Severity:** Low (not withheld). **Req:** S17.8.3.5 ("checks each
  image's provenance (S17.8.2) and pins it by its digest").
- **Code:** `publish/truenas/create-pr.sh:49–55`:
  ```sh
  pinned() {
    local image="ghcr.io/mojokata/$1:$2"
    gh attestation verify "oci://$image" -R "$REPO" --signer-workflow "$SIGNER" \
      --source-ref "refs/tags/v$2" --deny-self-hosted-runners >/dev/null ||
      die "$image: its provenance doesn't check out"
    docker buildx imagetools inspect "$image" --format '{{.Manifest.Digest}}'
  }
  ```
- **What goes wrong:** the tag is resolved twice, once by `gh` and once by `imagetools`. If
  `0.2.0` moves between the two (U11-2's rerun, or a push by anyone holding `packages: write`),
  the catalog request pins a digest no one verified; `check.sh`, run before, also tried the
  images by tag. TrueNAS's catalog then serves every catalog household that digest.
- **Remedy:** resolve the digest first, then verify `oci://ghcr.io/mojokata/$1@$digest` with the
  same flags, and pin that digest.
- **Run:** reading alone.

### U11-8: `web/dev.sh base-update` writes the move into `web/audit.json`, not the register S17.8.5 names

- **Kind:** differs. **Severity:** Low. **Req:** S17.8.5 ("writes it into the Dockerfile and
  the register (`docs/dependencies.md`, with the date and what the move picked up)").
- **Code:** `web/server/src/moolakata/dev/base.py:64–66`:
  ```python
  rec = record()
  rec["base"] = {"image": image, "digest": new, "movedAt": dt.date.today().isoformat()}
  AUDIT.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
  ```
  and `RELEASE.md` §3 step 3: "Bring the base image's row in `docs/dependencies.md` up to date
  by hand".
- **What goes wrong:** the requirement promises the register is written by the command; the
  code leaves `dependencies.md:85` ("Last moved: 2026-10-15 …") to a person, and nothing
  checks the two agree, so the register's date drifts from the Dockerfile's digest while
  `web/check`'s 90-day warning reads `audit.json`.
- **Remedy:** S17.8.5 says what the code does (the digest and date in `web/audit.json`, the
  register's row by hand at the release, RELEASE §3), or `base-update` rewrites the row's
  *Last moved* clause and `web/check` compares it with `audit.json`.
- **Run:** reading alone.

### U11-9: `web/pins` holds no hash for Playwright's Chromium, only a revision checked after the download

- **Kind:** differs. **Severity:** Low. **Req:** S17.6 ("`web/pins` holds the versions and
  hashes of the dev-only downloads (Deno, Playwright's Chromium)").
- **Code:** `web/pins:5–7`: `PLAYWRIGHT_CHROMIUM_REVISION=1243`; `web/dev.sh:65–72`:
  ```sh
  (cd "$SERVER" && uv run --frozen playwright install chromium-headless-shell >/dev/null)
  local dir="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
  if [[ ! -d "$dir/chromium_headless_shell-$PLAYWRIGHT_CHROMIUM_REVISION" ]]; then
  ```
- **What goes wrong:** Deno's zip is checked against a SHA-256 before it runs; Chromium,
  which runs every browser test and the mockup crawl (and on CI), is whatever Playwright's CDN
  served, checked only by the name of the folder it unpacked to. A substituted build passes.
- **Remedy:** a SHA-256 of the headless-shell archive per architecture in `web/pins`, checked
  on the files Playwright unpacked (or download the archive in `dev.sh`, check it, and point
  `PLAYWRIGHT_BROWSERS_PATH` at it).
- **Alternatives:** S17.6 says the Chromium is pinned by Playwright's version in `uv.lock` and
  its revision, without a hash.
- **Run:** reading alone.

### U11-10: the egress scan counts a URL on GitHub, Google, Cloudflare or PyPI as noise, so a new download or update check there passes unflagged

- **Kind:** security. **Severity:** Low (not withheld). **Req:** S17.2.1 ("scans the installed
  wheels and the vendored files for URLs … diffs the findings against the register").
- **Code:** `web/server/src/moolakata/dev/audit.py:30–40`, `:55`:
  ```python
  NOISE = re.compile(
      r"(^|\.)(w3\.org|github\.com|githubusercontent\.com|readthedocs\.io|python\.org|pypi\.org|"
      ...
      r"cloudflare\.com|google\.com|googleapis\.com|googlesource\.com|chromium\.org|"
  ...
          if not NOISE.search(host):
  ```
- **What goes wrong:** the pattern drops every subdomain of these hosts, endpoints included:
  `raw.githubusercontent.com` and `objects.githubusercontent.com` (where model and binary
  downloads usually live), `api.github.com` (update checks), `pypi.org/pypi/<x>/json` (the
  common "a newer version exists" check), `storage.googleapis.com`, `jsdelivr.net`. A new
  release of rapidocr that fetches a model from GitHub, or a library that checks PyPI for
  updates, shows nothing new in `web/dev.sh audit`, and with U11-1 the no-network run doesn't
  catch it either.
- **Remedy:** treat as noise only documentation hosts by exact name (`docs.python.org`,
  `www.w3.org`, `github.com/<org>/<repo>` paths as links), and report API and download hosts
  (`api.github.com`, `raw.githubusercontent.com`, `objects.githubusercontent.com`,
  `*.googleapis.com`, `pypi.org/pypi`, CDNs) as findings, which the register then accepts
  once.
- **Run:** reading alone.

### U11-11: the browser component tests S17.5 describes, an in-page runner and a fake API in `web/ui/tests/`, don't exist

- **Kind:** differs. **Severity:** Low. **Req:** S17.5 ("Browser tests use a small in-page
  runner (`web/ui/tests/run.js`) and a fake API; one smoke test drives a running dev server"),
  S17.1 (`web/ui/ … tests/`).
- **Code:** no `web/ui/tests/` in the repository (`git ls-files web/ui | grep -i test` finds
  none); `web/check:35–38` skips it when absent; the browser tests are
  `web/server/tests/test_app.py:1–3` ("The browser app against a seeded dev server in headless
  Chromium …: every screen, tab and dialog opens without a page or console error") and
  `test_browser_smoke.py`.
- **What goes wrong:** what S17.5 promises (components tested on their own against a fake API,
  so a component's states, errors and edge cases are driven deliberately) is not what is
  built (every screen opened against the seed, checked for errors and guides). A component
  state the seed never produces (a 409 conflict, an empty list, a refused save) is never
  rendered by any test.
- **Remedy:** S17.5 and S17.1 describe what is built (Playwright over a seeded dev server and
  the generated mockup's crawl, no component runner), or the runner and fake API are written.
- **Run:** reading and a listing.

### U11-12: nothing holds the first screen's 150 KB budget

- **Kind:** test gap. **Severity:** Low. **Req:** S17.3.4 ("under 150 KB compressed for the
  first screen").
- **Code:** no test or check measures it (`grep` of `web/server/tests` for the budget finds
  nothing); `web/ui/app/router.js:6` loads screens by `import()`, and `screens/dashboard.js:12,14`
  statically imports `charts/chart.js` and `./new-account.js`, which bring in, among others,
  `screens/projections.js`, `components/loan.js` and `components/edu.js` (the walk's largest).
- **What goes wrong:** the budget holds today, and only by luck: a scratch walk of the static
  imports from `app/main.js` and the Dashboard (`tmp/u11/first_screen.py`, gzip level 6)
  gives 103 KB in 74 files, the sign-in screen 57 KB. One static import of a heavy module into
  a component the frame uses (ECharts is 330 KB gzipped) passes every check.
- **Remedy:** a test that walks the static import graph of `main.js` plus the sign-in and
  Dashboard screens, gzips each file and the three stylesheets, and fails over 150 KB; and
  that `echarts` is reached only through `import()`.
- **Run:** the scratch walk above, against the working tree (equal to `6916954` for code).

### U11-13: the seeded linked server's address is a real host name, which a dev server seeded without `--stubs` calls every hour

- **Kind:** differs. **Severity:** Low. **Req:** S17.7 ("never calls a real provider unless one
  is configured").
- **Code:** `web/server/src/moolakata/dev/seed_links.py:58`: `address="https://money.parents.ts.net",`
  (its docstring, `:4–5`: "Its address is never reached: dev mode with stubs makes no outside
  calls"); `runtime.py:133–137` skips the exchange only `if server.config.stubs`; `dev.sh run`
  allows `--seed` alone.
- **What goes wrong:** `web/dev.sh run --seed` (no `--stubs`, to try a real price source) makes
  the hourly exchange with `money.parents.ts.net`: a DNS query and, if it resolves, a signed
  link call to a name under Tailscale's real domain, from a developer's machine, unasked. The
  connector's seed uses reserved names (`ofx.umb.example`), the link's does not.
- **Remedy:** a reserved name (`https://money.parents.example`), or skip the seeded link's
  exchange in dev mode whatever `--stubs` says.
- **Run:** reading alone.

### U11-14: dev mode is cited as S17.6 (`web/dev.sh`) where it is S17.7

- **Kind:** differs. **Severity:** Low. **Req:** S17.7 (dev mode), S17.6 (`web/dev.sh`).
- **Code:** `web/install/Dockerfile:23`: "# Dev mode's code stays out of the image: its seed users
  and their fixed password (S17.6)."; `web/server/src/moolakata/main.py:56`: "# Only from a
  checkout (S17.6): the image carries no dev.sh"; `web/server/tests/test_config.py:152`:
  "# S17.6: the image carries no dev.sh, and leaves dev mode's code out."
- **What goes wrong:** S17.6 says nothing about the image or dev mode's refusals; the rule
  ("the image leaves dev mode's code out", "refuses to run … outside a checkout") is S17.7's.
  A reader tracing the image's exclusion to its requirement lands on the wrong item, and
  `check_docs.py` counts these as S17.6's.
- **Remedy:** cite S17.7 in the three places.
- **Run:** reading alone.

### U11-15: the release gate's receipt read runs in the smoke container's own Python, not through the reader's worker and its sandbox

- **Kind:** test gap. **Severity:** Low. **Req:** S17.8.1 (the gate: "a receipt read"),
  S9.8.4.2 (the worker's sandbox, by architecture).
- **Code:** `web/install/smoke.sh:102–108`:
  ```sh
  docker run --rm "${PF[@]}" "${LOCKED[@]}" --entrypoint python "moolakata:$TAG" -c '
  ...
  from moolakata.receipts import ocr
  ...
  r = ocr.read(b.getvalue(), "image/png"); assert r.lines, "nothing read"; print("   read", r.method)'
  ```
  where the server reads through `receipts/worker.py` after `_lock_down` (seccomp from
  `sandbox.ARCHES`, `sandbox.py:27–28`, Landlock, no core).
- **What goes wrong:** the gate proves the OCR stack loads on each architecture, not that a
  receipt can be read the way a running server reads it: in the worker, under the seccomp
  filter whose numbers differ per machine, with `-I`, no environment and the read-only root.
  `check.yml` runs on amd64 only, so the aarch64 filter (`0xC00000B7, 198, 425`) is executed
  by no automated run; a wrong number there would kill or wrongly free every arm64 worker and
  still pass the release gate.
- **Remedy:** the smoke run reads a receipt through the running server (upload over the API as
  the signed-in admin, wait for its fields), or runs `Worker().read(...)` and the worker's
  `selftest` (no network, the data directory unreadable) inside the locked-down container on
  each architecture.
- **Run:** reading alone.

## Summary of the claims

Every claim at 0 confirmations, status open (quick review). None withheld: no security or
privacy claim here is rated above Low. None needs the user (DC-2 is judged above and left to the
walk-through).

| Id | Kind | Sev | Req | In one line |
|---|---|---|---|---|
| U11-1 | differs | Low | S17.2.1 | The no-network run can't see a native or worker connection: an attempt in an empty namespace leaves no trace |
| U11-2 | differs | Low | S17.8.2 | A rerun of `release.yml` on a published tag rebuilds and moves the version's tag on both registries |
| U11-3 | differs | Low | S17.10.2 | Pull requests are smoke-run only when the packaging changes, not the code in the images |
| U11-4 | bug | Low | S17.10.2.1 | `release.sh sign` tags and pushes any commit, one never on `main` included |
| U11-5 | security | Low | S17.10.2 | `release.sh publish` checks the draft's files by name, not content |
| U11-6 | security | Low | S17.10.2 | `release.sh copy` leaves the shared Docker Hub credential in the maintainer's Docker config |
| U11-7 | security | Low | S17.8.3.5 | `create-pr.sh` pins a digest resolved apart from the one it verified |
| U11-8 | differs | Low | S17.8.5 | `base-update` writes `audit.json`, not the register S17.8.5 names |
| U11-9 | differs | Low | S17.6 | No hash pins Playwright's Chromium |
| U11-10 | security | Low | S17.2.1 | The egress scan treats GitHub, Google, Cloudflare and PyPI hosts as noise |
| U11-11 | differs | Low | S17.5 | No component runner or fake API in `web/ui/tests/` |
| U11-12 | test gap | Low | S17.3.4 | Nothing holds the first screen's 150 KB budget |
| U11-13 | differs | Low | S17.7 | The seeded link's real host name is called hourly by a dev server without `--stubs` |
| U11-14 | differs | Low | S17.7 | Dev mode cited as S17.6 in three places |
| U11-15 | test gap | Low | S17.8.1 | The release gate reads a receipt outside the worker and its sandbox |

By severity: High 0, Med 0, Low 15. By kind: differs 8, security 4, test gap 2, bug 1.

## Phase 1 items judged against the code

- **DC-2 / D2-3** (`tls` mode for a relied-on TrueNAS server; needs the user, left to the
  walk-through). The code runs `tls` on every TrueNAS path: `web/install/compose.truenas.yaml:34`
  (`mode = "tls"`) and the catalog template `publish/truenas/moolakata/templates/docker-compose.yaml:21`;
  the proxy-mode example is `compose.yaml` alone (`moolakata.toml:11`). It follows S17.8.3.4
  ("What the templates fix: `tls` mode") and so the reading that `tls` serves a household with
  no proxy. Against the other reading (S13.3, S15.1.7, S16.15, DEPLOY's intro: testing only) it
  installs a testing mode as the catalog's only one. Under the first reading, S15.1.7's caveat
  doesn't reach catalog households: neither the form's certificate help
  (`moolakata/questions.yaml:197–208`: "With none, it makes one of its own … browsers ask before they
  trust it") nor the install notes (template `:58–59`) say that the self-made key sits plain
  in the data directory and its snapshots.
- **DC-19** (`[server] name`). `moolakata.toml:5–8` sets it, and the listener puts it in the
  self-signed certificate beside `localhost` (`listener.py:99`, unit 09's); the code matches
  DEPLOY and the example, and no requirement lists the key.
- **DC-20** (python-multipart). `web/server/pyproject.toml:20` names it directly; the code
  matches `dependencies.md:52`, not S17.2's list.
- **DC-21** (S17.1's `docs/`). The tree has `RELEASE.md`, `GENESIS.md`, `REVIEW.md`, `reviews/`,
  `release/`, `external/` (and the git-excluded `handoff.md`), none in S17.1; and S17.1's
  `web/ui/tests/` doesn't exist (U11-11).
- **D2-22** (R1.5 against S17.7's phrase file). `dev/devmode.py:24–33` keeps the phrase in
  `<data>/../phrase`, mode 0600, as S17.7 says; the conflict is the documents'.
- **D2-23** (S17.4 weighing). The code vendors ECharts 6.1.0's full ESM build
  (`index.html` import map) and loads it only by `import('echarts')` in `charts/chart.js:13`,
  as S17.4's stated choice; nothing of uPlot or Lightweight Charts exists.
- **D3-16** (memory). The catalog form's limit is 4096 MB with the reader's 350 MB in its help
  (`moolakata/questions.yaml` resources), as S17.8.3.2 says; the compose files set no limit.
  The 2-or-4 GB disagreement is between the documents only.
- **D3-17** (per-architecture tags). `release.yml:57–58` pushes `<version>-amd64`/`-arm64`,
  which stay on ghcr.io: the code matches RELEASE §2 and GENESIS §4, not S17.8.2's "no other
  tag". U11-2 adds that the version's own tag moves on a rerun.
- **D3-18**. `id-token: write` is on the joining and attesting job (`release.yml:67–71`), not
  the last (`draft`, `:142–143`, `contents: write` only): the code matches RELEASE, and
  `dependencies.md:119` is the one that is wrong. `release.sh setup` checks the `main` ruleset
  (`:358–371`), as GENESIS §7 says and RELEASE §12's list omits.
- **D3-10 to D3-14**. The connector's app and `compose.connector-truenas.yaml` carry only its
  page's port, names and certificate; nothing of the pairing fields, the refusals or the
  pairing code's address. No bearing here.
- **The `-dev` bump after a release** (memory; RELEASE §9, S17.10.2.2). `release.sh next`
  (`:249–270`) refuses until `web/VERSION`'s release is published and the new version comes
  after it, writes `<next>-dev` into `web/VERSION` and the connector's two files, and
  regenerates `openapi.json`; `web/VERSION` is `0.2.0-dev` while the compose files, the
  TrueNAS apps and DEPLOY name 0.1.0, which `test_install.py:_the_installed_release` holds.
  It matches. (`next` takes any later version, not only the next minor; RELEASE §9 lets the
  maintainer pick it.)

## Earlier findings re-checked

- **K25, its last point** (dev mode in the image): holds done. `Dockerfile:24` removes
  `src/moolakata/dev` in the build stage and the final stage copies only `/opt/moolakata`;
  `dev.sh` is never copied, and `main.py:60–61` refuses `moolakata dev` without it;
  `.dockerignore` leaves out `web/.dev` (the dev phrase); `test_config.py:151–165` holds both.
- **K1** (the host-loopback port reaching the key routes): holds done here. The key routes
  are on the socket in a 0700 tmpfs of the server's account (`compose.yaml:30`,
  `compose.tls.yaml:22`, the TrueNAS files, the catalog template `:51`), and the example
  trusts one address (`moolakata.toml:16`). (Whole networks still accepted by the config:
  U09-5.)
- **K10, point 2** (the sheet in Docker's log): holds for the install files. `compose.yaml:3`
  runs `keys init` with `run --rm`, and the welcome makes the key in the browser (the smoke run
  goes through it). `db shell` is U10-15.
- **B28** (UTC in the container): holds done. `/etc/localtime` read only and `TZ` in
  `compose.yaml:24–26` and `compose.tls.yaml:16–18`, `/etc/localtime` in both TrueNAS compose
  files, TrueNAS's own `TZ` field in both catalog forms; `timezones.zone_from` treats the empty
  `TZ` that `${TZ:-}` gives as unset.
- **C29**: holds. `dev.sh` lists the twelve commands S17.6 names; S17.2.1 names
  `web/audit.json`.
- **C51**: holds as text (S17.9.10 names nine milestones); its wording is D2-24's.
- **§12.3.3** (the arm64 image never on arm64): `release.yml:32–33` now builds and smoke-runs it
  natively on `ubuntu-24.04-arm`; household hardware stays T7.

## S17.1, S17.9 and S17.10 (uncited first-level items)

- **S17.1**: built but for `web/ui/tests/` (U11-11); `docs/` has six entries it doesn't name
  (DC-21). The server's and the app's lists are examples, not exhaustive, and every name they
  give exists.
- **S17.9**: every milestone is marked built (README's **Status**). The items that are this
  unit's are built: the layout, `dev.sh`, `web/check` and its steps, `uv.lock`, both images on
  both architectures (M1.1, each milestone's "the Docker image"); dev mode with seed data
  (M1.2); Python 3.14 in `requires-python`, both Dockerfiles and the wheel check (M7.1); the
  fake Esplora, Electrum and Core (`dev/mocks.py`, loopback only), the arm64 smoke under QEMU,
  `docs/test-plan.md` (M7.8); the audit and the register's hash check in `web/check`, the base
  image's update process (M7.9; the real receipt fixtures are G23, open); dev mode only from a
  checkout (M9.5). The feature items were judged by their units; those found not built or
  half built against an item S17.9 lists as built include U01-6 (vesting), U04-4 (scenarios
  side by side, M2.8), U04-16 (Roth MAGI), U10-19 (S16.15), and U11-11 here.
- **S17.10**: built: `check.yml` (S17.10.1, uv from `build-requirements.txt` by hash),
  `release.yml`'s five jobs (S17.10.2), `release.sh` (S17.10.2.1), the `-dev` move
  (S17.10.2.2), actions pinned by commit and listed (S17.10.3, held by
  `test_install.py:412–425`), least-privilege job permissions, the Docker Hub token only in the
  `docker-hub` environment. Differences: U11-2, U11-3; D3-17 and D3-18 above.
- **`ui/deno.json`** (cites no section): serves S17.3.2 (JSDoc types checked by Deno) and
  S17.5 (Deno check, lint and fmt, `web/check:39–41`), and S17.1 lists it. Not untraced.
- **`web/ui/vendor/vendor.py`** is on no unit's list in `map.md`; it builds S17.3.1–S17.3.1.2,
  so it was read here (see below).

## Checked and sound

- `web/ui/vendor/vendor.py`: `add` refuses a release under 14 days without `--young` and
  records the reason; checks the download against the registry's SRI; verifies npm's SLSA
  provenance offline against GitHub Actions' issuer and the repository already recorded for
  the package, for this package URL and SHA-512; refuses a version without provenance after
  one with; warns of dependencies; writes the served files' diff for review. `extract`
  verifies every tarball's hash before unpacking only the listed regular files. `.dockerignore`
  keeps the extracted files out, so the image unpacks from the verified tarballs.
- The Dockerfile: base by digest, uv by hashes, `uv sync --frozen` from the lock's hashes, no
  `apt-get`, multi-stage so the dev code removed in the build stage never reaches a layer of
  the final image, files root's and read-only to uid 10001, `USER 10001:10001`, data and backup
  directories 0700.
- The compose files: read-only root, `cap_drop: [ALL]`, `no-new-privileges`, `/tmp` and the
  socket's directory in memory, logs bounded to 5 × 10 MB, proxy mode published on loopback
  only, one trusted proxy address inside the fixed subnet, no key mounted, the connector's
  volume never the server's; the TrueNAS one-time `permissions` step root with `CHOWN` alone,
  no network, read-only, ending before the app starts.
- The catalog apps: fixed accounts, health checks, read-only root unless a certificate, the
  tmpfs mounts, no extra environment or storage, the connector's install refused without an
  address; the test-values certificate is a throwaway made for the tests.
- `release.yml`: the tag must equal `v` + `web/VERSION`; what is pushed is the image that passed
  smoke on its own architecture; attestations with `push-to-registry: false`; the Docker Hub
  copy checks digests are unchanged; the draft job deletes only drafts for its tag and uses
  `--verify-tag`; `persist-credentials: false` on every checkout; secrets only in `env:`, never
  on a command line. `check.yml`'s annotation step escapes `%`, CR, LF, `:` and `,`.
- `release.sh`: `sign` refuses a version already tagged remotely or locally and a commit whose
  `web/VERSION` disagrees, asks before signing and before pushing; `publish` asks for the tag
  typed back and verifies the release and each asset after; `token` checks the token in a
  throwaway Docker config and never echoes it; `setup` reads each setting GENESIS §7 lists.
- `dev/devmode.py` and `main.py`'s dev path: refuses root, an image, `/var/lib/moolakata`;
  another installed data directory is refused anyway, since its keyring has no phrase file
  beside it (`devmode.py:35–41`); the stub price source is `dev_only` and the stub wallet source
  is refused outside `--stubs` (`ui/settings.py:86–88`, `bitcoin/sync.py:57–58`).
- `dev/wheels.py`: glibc-only platform tags, the project's CPython or a lower abi3, both
  architectures, sdists flagged; `dev/audit.py check` compares both files' hashes.
- `static.py`: only the listed directories, no `..` or empty parts, `vendor/` only below a
  package directory, resolved paths kept inside `web/ui`, known types only; a year's cache only
  for a three-number version outside dev mode; the page `no-store` with a fresh nonce; `/demo`
  sandboxed without `allow-same-origin`, so it can't reach the API or cookies.
- The mockup builder: modules embedded only when free of `</script` and `<!--`, the data blob
  with `<` escaped; the crawl's server bound to loopback with the dev seed only.
- `smoke.sh` covers each step S17.8.1 lists; `check.sh` checks what S17.8.3.5 lists.
- The first screen's size today: 103 KB gzipped for the Dashboard, 57 KB for sign-in (U11-12).

## Read lightly or not read

- The seed modules other than `seed.py`, `seed_links.py`, `seed_connector.py` and
  `seed_wallets.py` (`seed_accounts`, `_assets`, `_budgets`, `_education`, `_gifts`, `_giving`,
  `_loans`, `_options`, `_projections`, `_receipts`, `_sharing`, `_taxes`): dev data only, read
  for outside calls and secrets, not for their figures.
- `dev/mocks.py`: read for what it binds (loopback) and its options, not its protocol subsets.
- `publish/truenas/*/questions.yaml`: read for the form's fields, defaults and help, not every
  TrueNAS-standard block. `build-requirements.txt`'s two hashes were not checked against PyPI.
- `RELEASE.md` §4 and `GENESIS.md` (block 3 read them); `DEPLOY.md` §3.1, §3.2, §4.1, §5, §7,
  §8 skimmed for what the install files must match.
- `test_mocks.py`, `test_mockup_app.py`, `test_static.py`, `test_vendor.py`: by their test names
  and asserts, not run.

