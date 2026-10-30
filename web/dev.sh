#!/usr/bin/env bash
# MoolaKata's developer front door. Run alone to list the commands.
set -euo pipefail

WEB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$WEB")"
SERVER="$WEB/server"
TOOLS="$WEB/.tools"
# shellcheck source=pins
source "$WEB/pins"
unset VIRTUAL_ENV

usage() {
  cat <<'USAGE'
web/dev.sh <command>

  setup        install the Python environment (uv), Deno and Playwright's Chromium,
               and unpack the vendored browser libraries
  run [args]   run the dev server (moolakata dev): https://localhost:37373
               --seed  seed users and a year of data    --stubs  stub price source
               --peer  a second server on another port, for links
               --listen ADDR  --hostname NAME  --port N  --data DIR
                       for testing from another machine: see web/dev.md
  test [args]  run pytest (arguments pass through)
  coverage [args]
               pytest (arguments pass through) and the browser modules' tests,
               measured: coverage by area and of the changed lines, with HTML
               and a preview of the coverage site, in web/.dev/coverage/
  check        run every check: what CI runs (web/check)
  mail         list the emails dev mode has written
  mocks        fake bitcoin backends (Esplora, Electrum, Core) on local ports
  audit [--accept]
               the egress audit after a dependency change: the scan, the
               no-network run; --accept records it (docs/dependencies.md)
  base-update [--packages]
               move the base image's digest to the current one
  codegen      regenerate the generated code: the OpenAPI document, the browser's
               types and its drafts' fields (web/ui/api/), from the routes
  mockup       rebuild docs/mockups/MoolaKata-app.html from the app
  help-shots   rebuild the help guides' screenshots from the mockup
  deno [args]  run the pinned Deno
  vendor add NAME VERSION [--young REASON]
               adopt a browser library's version: cooldown, registry hash and
               provenance checked, diff of the served files written for review
USAGE
}

deno_bin() { echo "$TOOLS/deno-$DENO_VERSION/deno"; }

setup_deno() {
  local bin arch sum zip
  bin="$(deno_bin)"
  [[ -x "$bin" ]] && return 0
  arch="$(uname -m)"
  case "$arch" in
    x86_64) sum="$DENO_SHA256_x86_64" ;;
    aarch64 | arm64) arch=aarch64; sum="$DENO_SHA256_aarch64" ;;
    *) echo "no pinned Deno for $arch" >&2; return 1 ;;
  esac
  mkdir -p "$(dirname "$bin")"
  zip="$(dirname "$bin")/deno.zip"
  curl -fsSL -o "$zip" \
    "https://github.com/denoland/deno/releases/download/v$DENO_VERSION/deno-$arch-unknown-linux-gnu.zip"
  echo "$sum  $zip" | sha256sum -c --quiet -
  python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extract("deno", sys.argv[2])' \
    "$zip" "$(dirname "$bin")"
  chmod 0755 "$bin"
  rm -f "$zip"
}

setup_playwright() {
  (cd "$SERVER" && uv run --frozen playwright install chromium-headless-shell >/dev/null)
  local dir="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
  if [[ ! -d "$dir/chromium_headless_shell-$PLAYWRIGHT_CHROMIUM_REVISION" ]]; then
    echo "Playwright installed a Chromium other than revision $PLAYWRIGHT_CHROMIUM_REVISION;" \
      "update PLAYWRIGHT_CHROMIUM_REVISION in web/pins" >&2
    return 1
  fi
}

cmd="${1:-}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
  setup)
    (cd "$SERVER" && uv sync --frozen)
    python3 "$WEB/ui/vendor/vendor.py" extract
    setup_deno
    setup_playwright
    echo "ready: web/dev.sh run --seed --stubs"
    ;;
  run)
    python3 "$WEB/ui/vendor/vendor.py" extract
    # The server runs from web/server, so a --data path is made absolute from here first.
    args=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --data) args+=(--data "$(realpath -m -- "$2")"); shift 2 ;;
        --data=*) args+=(--data "$(realpath -m -- "${1#--data=}")"); shift ;;
        *) args+=("$1"); shift ;;
      esac
    done
    cd "$SERVER" && exec uv run --frozen moolakata dev "${args[@]}"
    ;;
  test)
    cd "$SERVER" && exec uv run --frozen pytest "$@"
    ;;
  coverage)
    # What the tests reach (S17.5.8), as web/check measures it, for the tests named.
    out="$WEB/.dev/coverage"
    rm -rf "$out" && mkdir -p "$out/server" "$out/js"
    "$WEB/dev.sh" deno test --quiet --no-check --config "$WEB/ui/deno.json" \
      --import-map "$WEB/ui/tests/import_map.json" --coverage="$out/js" "$WEB/ui/tests/" >/dev/null
    cd "$SERVER"
    COVERAGE_FILE="$out/server/.coverage" COVERAGE_CORE=sysmon MK_JS_COVERAGE="$out/js" \
      uv run --frozen coverage run -m pytest "$@" || true
    uv run --frozen python -m moolakata.dev.coverage report
    exec uv run --frozen python -m moolakata.dev.coverage site
    ;;
  mocks)
    # Fake bitcoin backends on local ports (S17.9.7.8); point Settings › Bitcoin at them.
    cd "$SERVER" && exec uv run --frozen python -m moolakata.dev.mocks "$@"
    ;;
  audit)
    # The egress audit (S17.2.1): what the wheels and vendored files could reach, and the
    # server run with no network. --accept records the scan and the files' hashes.
    cd "$SERVER"
    if [[ "${1:-}" == "--accept" ]]; then
      exec uv run --frozen python -m moolakata.dev.audit accept
    fi
    uv run --frozen python -m moolakata.dev.audit scan || true
    echo
    echo "== the server with no network (unshare -U -n)"
    unshare -U -n uv run --frozen pytest -q -m audit tests/test_no_network.py
    ;;
  base-update)
    # Move the base image's digest to the current one (S17.8.5); --packages diffs Debian's.
    cd "$SERVER" && exec uv run --frozen python -m moolakata.dev.base update "$@"
    ;;
  check)
    exec "$WEB/check" "$@"
    ;;
  mail)
    ls -1t "$WEB/.dev/mail" 2>/dev/null || echo "no mail yet"
    ;;
  codegen)
    # The generated code (S17.6): the OpenAPI document, the browser's types and its drafts'
    # fields, from the routes and the kinds the save takes. A few seconds; web/check fails
    # when any is out of date. The generated mockup and help shots have their own commands.
    cd "$SERVER" && exec uv run --frozen python -m moolakata.contract write
    ;;
  mockup)
    cd "$SERVER" && exec uv run --frozen python "$WEB/ui/mockup/build.py"
    ;;
  help-shots)
    cd "$SERVER" && exec uv run --frozen python "$WEB/ui/mockup/help_shots.py" "$@"
    ;;
  vendor)
    cd "$SERVER" && exec uv run --frozen python "$WEB/ui/vendor/vendor.py" "$@"
    ;;
  deno)
    setup_deno
    exec "$(deno_bin)" "$@"
    ;;
  *)
    usage
    ;;
esac
