# Dependencies

Every library MoolaKata runs with: what it is for, why it was chosen, what it could do that
MoolaKata must not (above all, reach out of the house), and when to look at it again. The
requirements set the rules (S17.2 the server's, S17.3.1 the browser's, S13.5 egress); this
page is the register.

**Audited against:** the hashes of `web/server/uv.lock` and `web/ui/vendor/manifest.json`
recorded in `web/audit.json` by `web/dev.sh audit --accept`, with what the scan found for each
package; `web/check` fails when either file no longer matches.

## The egress audit rule

A dependency can open a connection the egress guard (S13.5) never sees: the guard covers the
server's own HTTP client, not native code or a library's own client. So:

1. **Every change to `uv.lock` or `manifest.json` is followed by an audit** before it is
   committed: `web/dev.sh audit` scans the installed wheels and the vendored files for URLs
   and the words of telemetry and update checks, diffs the findings against this page, and
   runs the server and the receipt worker in a network namespace with no interfaces through a
   receipt read, a price refresh against the stubs, a backup and a pass of the tasks, failing
   on any socket opened to a non-loopback address.
2. **`web/check` only checks that the audit happened**: the hashes above must match the
   files, which costs nothing. The audit itself runs when a dependency changes, not on every
   test cycle.
3. **A finding is recorded here, with its switch.** A library that *can* reach out is marked
   **egress** in its Risks column with what turns it off and where MoolaKata does so; a
   library that is *known* to send telemetry is marked **telemetry** as well, and is the first
   to revisit when an alternative appears.

## Python (the server)

Pinned with hashes in `web/server/uv.lock`; Python 3.14 (every native wheel below exists for cp314 on both architectures, checked on PyPI 2026-10-15); installed in the image from wheels
for amd64 and arm64 (S17.8.1). *Direct* means named in `pyproject.toml`.

### Direct

| Library | Version | Purpose | Decision | Risks | Revisit |
|---|---|---|---|---|---|
| fastapi | 0.143.0 | the routes and the generated OpenAPI (R3.9) | the common choice with Pydantic; the contract check (S17.5) needs its OpenAPI | none known; pulls starlette and anyio | if the OpenAPI output drifts between releases and the typedef check keeps breaking |
| pydantic | 2.14.1 | request and response models, exact decimals (S13.8.2) | FastAPI's own; pydantic-core is Rust | none known | with FastAPI |
| hypercorn | 0.18.0 | the listener: HTTP/1.1 and HTTP/2, TLS in `tls` mode, SSE (S13.3) | the ASGI server with HTTP/2 and no C extension; uvicorn had no HTTP/2 | none known | if HTTP/2 or the graceful stop (S13.6) misbehave behind a proxy |
| sqlalchemy | 2.1.4 | Core tables mapped onto dataclasses (S14.1) | Core without the ORM's models keeps the schema free of logic; SQLModel rejected (rejected ideas 8) | none known; greenlet for its async bits, unused | — |
| alembic | 1.20.0 | numbered schema revisions (S14.1.3) | SQLAlchemy's own migration tool | none known | — |
| argon2-cffi | 25.1.0 | password hashes, argon2id (S13.7.3) | the reference binding | none known | — |
| cryptography | 50.0.2 | AES-GCM, HKDF, Ed25519 for links, X25519 for receipts and copies (S15.3, S11.9.6) | the one maintained Python crypto library with these primitives; Rust and OpenSSL inside | none known | on every OpenSSL advisory it carries |
| httpx | 0.28.1 | the one outbound client, behind the egress guard (S13.5) | sync and async, HTTP/2, a transport the guard can wrap | **the** egress path, by design: every call goes through the guard | — |
| sqlcipher3 | 0.6.3 | SQLCipher for the main database and the linked copies (S14.1, S11.9.11) | the wheel that bundles SQLCipher, so the image compiles nothing | few maintainers; a stale wheel would pin SQLCipher's version | each release: is its SQLCipher current, and does the arm64 wheel exist |
| ofxtools | 1.1.1 | reading OFX and QFX (S1.3.2) | the only maintained parser; pure Python; GPL-3.0-only, compatible | slow releases | if an institution's file it refuses can't be worked around |
| pillow | 12.3.0 | thumbnails, EXIF orientation, preparing images for OCR (S9.5, S9.8.2) | the standard | a decoder bug is reachable from an upload: the decompression-bomb limit and the pixel cap (S9.8.4.3) guard it; the worker is separate | on every Pillow security advisory |
| numpy | 2.5.4 | projections (S6.9) and RapidOCR's arrays | required by the OCR stack anyway | none known | — |
| python-multipart | 0.0.32 | multipart uploads | FastAPI's parser for files | parsing untrusted input: the request limits (S13.7.6) bound it | on its advisories |
| segno | 1.6.6 | the two-step QR code (S10.1.6) | pure Python, no image dependency | none known | — |
| pypdfium2 | 5.14.0 | a PDF's text layer and first-page render (S9.5, S9.8.2) | PDFium is the engine browsers ship; wheels for both architectures | parses untrusted PDFs: only in the worker, with its limits | on PDFium advisories |
| pi-heif | 1.4.0 | reading iPhone photos (HEIC) (S9.1) | decodes only, smaller than pillow-heif | libheif parses untrusted input: worker only | — |
| rapidocr | 3.10.0 | the OCR pipeline over the PP-OCR models (S9.8) | runs the models on ONNX Runtime with no service and no GPU; ships the models in its wheel | **egress**: downloads a model when its path is missing (`requests`); MoolaKata names every model's path and checks its hash first (S9.8.3), so it never does. Brings opencv, shapely, pyclipper, omegaconf, tqdm, requests, six, colorlog | when a smaller English-only model ships, or an engine without the `requests` and `tqdm` baggage |
| onnxruntime | 1.31.0 | runs the OCR models on the CPU (S9.8.2) | the runtime RapidOCR targets; CPU wheels for amd64 and arm64 | **egress, telemetry**: carries Microsoft's 1DS telemetry client with its collector URL (`mobile.events.data.microsoft.com`) compiled in. MoolaKata calls `disable_telemetry_events()` before the first session (`receipts/ocr.py`); a probe of the image saw no connection either way. In the image, where the home directory is unwritable, the import logs *Failed to persist telemetry device ID; using an in-memory identifier* once per worker start: expected, and better than the file it wanted to write. First on the list to replace | each release: whether the wheel's telemetry became opt-out at run time, and whether a build without it (or another runtime) is available |

### Transitive, worth knowing

| Library | Version | Pulled by | Risks |
|---|---|---|---|
| opencv-python-headless | 5.0.0.93 | rapidocr | native; parses images, but only after Pillow has decoded them; no network code known |
| requests, urllib3 | 2.34.2, 2.8.0 | rapidocr | **egress**: a general HTTP client; nothing in MoolaKata calls it; rapidocr uses it only for a model download that never happens (above) |
| tqdm | 4.70.1 | rapidocr | progress bars; **egress** by name only: its optional notifiers for Slack, Telegram and Discord, which nothing in MoolaKata or rapidocr imports |
| opentelemetry-api | from `uv.lock` | fastapi | the tracing API alone, which records nothing and sends nothing without an SDK and an exporter, neither of which is installed; its files name telemetry, which is what the audit's word scan flags |
| email-validator, dnspython | from `uv.lock` | fastapi (its email field types) | dnspython can look up DNS; email validation's deliverability check, which would, is never asked for |
| omegaconf, pyyaml | 2.4.0, 6.0.3 | rapidocr | config parsing; none |
| shapely, pyclipper | 2.2.0, 1.4.0 | rapidocr | geometry for text boxes; none |
| protobuf, flatbuffers | 7.36.2, 25.12.19 | onnxruntime | model file formats; parses only the shipped, hash-checked models |
| starlette, anyio, h11, h2 | 1.7.0, 4.15.1, 0.16.0, 4.4.1 | fastapi, hypercorn, httpx | the HTTP stack; parses untrusted requests behind the request limits |
| certifi | 2026.7.22 | httpx, requests | the CA bundle for outbound TLS; a stale bundle refuses a renewed root |
| cffi, argon2-cffi-bindings, greenlet, markupsafe, charset-normalizer, pydantic-core | — | the above | native, no network code known |

### Development only (never in the image)

| Tool | Version | Purpose | Risks |
|---|---|---|---|
| pytest | from `uv.lock` | the tests | — |
| ruff | from `uv.lock` | lint and format | — |
| coverage | from `uv.lock` | what the tests reach, in `web/check` and `web/dev.sh coverage` (S17.5.8) | none; its files name only its documentation |
| playwright | from `uv.lock` | browser tests; downloads its Chromium (`web/pins`) | **egress** at `web/dev.sh setup` only |
| sigstore | from `uv.lock` | verifying npm provenance in `vendor add` (S17.3.1) | **egress** at `vendor add` only |
| uv | 0.12.5 | the build stage's installer (`install/build-requirements.txt`, hashed) | fetches wheels at image build only |
| Deno | 2.9.7 | type-check, lint and format of the browser app (`web/pins`) | **egress** at `setup` only |
| python:3.14-slim-bookworm | by digest in the Dockerfile | the image's base | security updates arrive only when the digest moves: with each release and on a Debian or Python fix, by `web/dev.sh base-update` (S17.8.5). Last moved: 2026-10-15, from 3.12 to 3.14 (Docker Hub's build of 2026-10-06) |

## The connector

`connector/requirements.txt`, pinned with hashes for CPython 3.14 on amd64 and arm64; Python
3.14; the standard library and one dependency (S18.1.2). No driver has a dependency yet.

| Library | Version | Purpose | Decision | Risks | Revisit |
|---|---|---|---|---|---|
| cryptography | 50.0.2 | the identity and sealing keys, the vault's AES-GCM, opening sealed credentials | the one library with Ed25519, X25519 and AES-GCM; the standard library has none | none known; with the server's copy | with the server's |
| cffi, pycparser | 2.1.1, 3.11 | cryptography's binding | come with it | none known | — |
| python:3.14-slim-bookworm | by digest in `connector/Dockerfile` | the image's base | the same digest as the server's; moved with it (S17.8.5) | as the server's | with the server's |

## TrueNAS's catalog apps

What the two apps in `publish/truenas/` (S17.8.3.1) run with that is TrueNAS's, on a NAS or
while they are tried. None of it is in either image or in this repository: TrueNAS's tools copy
their library into the proposal itself.

| What | Version | Purpose | Risks | Revisit |
|---|---|---|---|---|
| TrueNAS's rendering library | `lib_version` in each `app.yaml` (2.3.17) | turns each template and the household's form into the compose file the NAS runs | TrueNAS's code, run by TrueNAS's middleware | when the catalog has a newer one: `lib_version`, then `check.sh` |
| ghcr.io/truenas/containers/container-utils | 1.1.1, by digest in each `ix_values.yaml` | the permissions step that gives the storage to each app's account before it starts | runs as root with CHOWN, FOWNER and DAC_OVERRIDE and no network, for a moment, on the household's NAS | TrueNAS's bot moves it once the apps are in the catalog; before then, at each proposal |
| ghcr.io/truenas/apps_validation:slim | TrueNAS's current, unpinned | the renderer `check.sh` and `create-pr.sh` run through TrueNAS's `ci.py` | **the Docker socket**: it renders with the machine's Docker, so run them on a development machine only; **egress** while they run (the catalog and the images) | — |

## GitHub Actions (checks and releases)

The workflows in `.github/workflows/` (S17.10) use GitHub's own actions only, each pinned by
the commit its release tag named; a release is adopted after 14 days, as a browser library is
(S17.3.1). Everything else they run is the repository's own scripts.

| Action | Version | Commit | Purpose | Risks | Revisit |
|---|---|---|---|---|---|
| actions/checkout | 7.0.1 (2026-07-20) | `3d3c42e5aac5ba805825da76410c181273ba90b1` | the source, in both workflows, without keeping the token (`persist-credentials: false`) | none known | when its major version changes |
| actions/upload-artifact | 7.0.2 (2026-10-07) | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | the coverage reports (S17.5.8) of each `check` run, kept 30 days | none known: it writes to the run's own storage with the job's token | when its major version changes |
| actions/attest-build-provenance | 4.2.2 (2026-08-06) | `4d101475d8b20a2381f78447822ac1eab6504dd8` | the build-provenance attestation of each released image (Sigstore's public instance) | **egress** to Sigstore and the registry, by design, in the release's last job only, which alone holds `id-token: write` | when its major version changes |
| GitHub-hosted runners | `ubuntu-24.04`, `ubuntu-24.04-arm` | — | the checks; the amd64 and arm64 builds and smoke runs | the images are GitHub's; free for a public repository | if GitHub's terms for public repositories change |

## JavaScript (the browser app)

Vendored as npm tarballs under `web/ui/vendor/`, adopted only through `web/dev.sh vendor
add` (S17.3.1): a 14-day cooldown, the registry's integrity hash, Sigstore provenance where the
package publishes it, and a reviewed diff. Loaded under a CSP with no third-party origin
(S17.3.3), so a library can't reach out even if it tried; the risk is what a release could do
inside the page.

| Library | Version | Published | Provenance | Purpose | Decision | Risks | Revisit |
|---|---|---|---|---|---|---|---|
| preact | 10.29.8 | 2026-08-01 | verified | rendering | small, no build step, HTM-friendly (R1.1) | none known | — |
| htm | 3.1.1 | 2022-04-26 | none | JSX-like templates without a compiler | the only way to write components with no build step | unmaintained since 2022 and publishes no provenance; stable, and the surface is tiny | if a Preact release stops working with it |
| @preact/signals-core | 1.14.4 | 2026-07-07 | verified | the signal primitives | pulled by @preact/signals | none known | — |
| @preact/signals | 2.11.3 | 2026-09-30 | verified | state (R1.1) | Preact's own | none known | — |
| preact-iso | 2.12.2 | 2026-08-11 | verified | routes and lazy screens (R1.1) | Preact's own router | none known | — |
| echarts | 6.1.0 | 2026-05-19 | none | every chart (S17.4) | the only candidate covering donut, treemap, Sankey and the fan without code of our own | large surface (~330 KB gzip, loaded only by chart screens); publishes no provenance, so a release is trusted on the integrity hash and the diff alone | if a smaller library gains treemap and Sankey, or if ECharts starts publishing provenance |
