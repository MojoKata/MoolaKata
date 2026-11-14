#!/usr/bin/env bash
# Proposes MoolaKata's two apps to TrueNAS's community catalog (requirements S17.8.3.1), or
# updates the proposal. It runs check.sh, checks each image's provenance and pins it by its
# digest, copies both apps into a branch of truenas/apps where TrueNAS's own tools add their
# library and metadata, and commits. Only --open sends anything: it pushes the branch to your
# fork of truenas/apps and opens the pull request as a draft, or updates the one already open.
# TrueNAS decides what its catalog includes, and opening the request is the maintainer's call.
#
#   publish/truenas/create-pr.sh           prepare the branch, the request's text, and stop
#   publish/truenas/create-pr.sh --open    then push the branch and open or update the request
#
# Needs what check.sh needs, gh signed in, Docker with buildx, and for --open a fork of
# truenas/apps under your account. TRUENAS_PR names the checkout it works in
# (web/.dev/truenas-apps-pr by default).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="${TRUENAS_PR:-$ROOT/web/.dev/truenas-apps-pr}"
BODY="$WORK.md"
UPSTREAM=truenas/apps
BRANCH=moolakata
REPO=MojoKata/MoolaKata
SIGNER="$REPO/.github/workflows/release.yml"
APPS=(moolakata moolakata-connector)

say() { printf '== %s\n' "$*"; }
die() {
  echo "create-pr.sh: $*" >&2
  exit 1
}

value() { python3 -c 'import sys, yaml; d = yaml.safe_load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$@"; }

# Each app's image names the same release, which its app_version names too.
release() {
  local found=() app tag
  for app in "${APPS[@]}"; do
    tag="$(value "$HERE/$app/ix_values.yaml" "d['images']['image']['tag']")"
    [[ "$tag" == "$(value "$HERE/$app/app.yaml" "d['app_version']")" ]] ||
      die "$app: its image is $tag and its app_version another"
    found+=("$tag")
  done
  [[ "${found[0]}" == "${found[1]}" ]] || die "the apps name ${found[*]}"
  echo "${found[0]}"
}

# The image's digest, once its provenance shows release.yml built it from the version's tag.
pinned() {
  local image="ghcr.io/mojokata/$1:$2"
  gh attestation verify "oci://$image" -R "$REPO" --signer-workflow "$SIGNER" \
    --source-ref "refs/tags/v$2" --deny-self-hosted-runners >/dev/null ||
    die "$image: its provenance doesn't check out"
  docker buildx imagetools inspect "$image" --format '{{.Manifest.Digest}}'
}

checkout() {
  if [[ ! -d "$WORK/.git" ]]; then
    mkdir -p "$(dirname "$WORK")"
    git clone --quiet --depth 1 "https://github.com/$UPSTREAM.git" "$WORK"
  fi
  git -C "$WORK" fetch --quiet --depth 1 "https://github.com/$UPSTREAM.git" master
  git -C "$WORK" checkout --quiet --force -B "$BRANCH" FETCH_HEAD
  git -C "$WORK" clean --quiet -fdx
}

place() {
  local app="$1" version="$2" digest="$3" dir="$WORK/ix-dev/community/$1" theirs="" added
  if [[ -f "$dir/app.yaml" ]]; then
    theirs="$(value "$dir/app.yaml" "d['version']")"
    added="$(value "$dir/app.yaml" "d['date_added']")"
  else
    added="$(date -u +%F)"
  fi
  rm -rf "$dir"
  cp -r "$HERE/$app" "$dir"
  python3 - "$dir" "$version" "$digest" "$added" "$theirs" <<'PY'
import pathlib, re, sys
dir, version, digest, added, theirs = sys.argv[1:]
dir = pathlib.Path(dir)
values = dir / "ix_values.yaml"
text = values.read_text()
old = f'  image:\n    repository: ghcr.io/mojokata/{dir.name}\n    tag: "{version}"\n'
assert old in text, "ix_values.yaml's image entry"
values.write_text(text.replace(old, old.replace(f'"{version}"', f'"{version}@{digest}"')))
app = dir / "app.yaml"
text = app.read_text()
text = re.sub(r"^date_added: .*$", f"date_added: '{added}'", text, flags=re.M)
if theirs:
    # Already in the catalog: its version moves past the catalog's, by a patch at least.
    number = lambda v: tuple(int(n) for n in v.split("."))
    t = number(theirs)
    ours = number(re.search(r"^version: (.*)$", text, re.M).group(1))
    nxt = max((t[0], t[1], t[2] + 1), ours)
    text = re.sub(r"^version: .*$", "version: " + ".".join(map(str, nxt)), text, flags=re.M)
app.write_text(text)
PY
  # TrueNAS's renderer copies in its library, fills lib_version_hash and writes item.yaml.
  if ! (cd "$WORK" && python3 .github/scripts/ci.py --app "$app" --train community \
    --test-file basic-values.yaml --render-only=true >"$WORK.log" 2>&1); then
    cat "$WORK.log"
    die "$app: TrueNAS's renderer refused it"
  fi
  rm -rf "$dir/templates/rendered"
}

# The icons and screenshots the request links, for TrueNAS's CDN: files in the repository, and
# the app's pictures, which CI makes from main on every run and publishes on the Pages site.
MEDIA=(
  web/ui/assets/favicon.svg
  publish/truenas/media/moolakata-connector-icon.svg
  https://mojokata.github.io/MoolaKata/screenshots/truenas/moolakata-1.png
  https://mojokata.github.io/MoolaKata/screenshots/truenas/moolakata-2.png
  https://mojokata.github.io/MoolaKata/screenshots/truenas/moolakata-3.png
  https://mojokata.github.io/MoolaKata/screenshots/truenas/moolakata-4.png
  publish/truenas/media/moolakata-connector-1.png
  publish/truenas/media/moolakata-connector-2.png
)

# The links to them at a commit of MojoKata's main, each checked to be there.
media() {
  local sha="$1" path
  for path in "${MEDIA[@]}"; do
    if [[ $path == https://* ]]; then
      curl -sfI "$path" >/dev/null || die "$path isn't published yet"
    else
      curl -sfI "https://raw.githubusercontent.com/$REPO/$sha/$path" >/dev/null ||
        die "$path isn't on $REPO's main at ${sha:0:12} yet"
    fi
  done
}

body() {
  local version="$1" raw="https://raw.githubusercontent.com/$REPO/$2"
  cat >"$BODY" <<EOF
# App Addition

- [ ] I have opened an [issue](https://github.com/truenas/apps/issues) to discuss this app addition before submitting this pull request.

# AI

- [x] Part or All of this PR was generated by an LLM.

## Description

Adds MoolaKata and the MoolaKata Connector to the community train.

MoolaKata is a self-hosted personal finance server for a household: bank, card, brokerage,
retirement, 529 and bitcoin accounts in one place, with portfolios, projections, budgets,
gifts, receipts and tax books. The MoolaKata Connector is its companion: it keeps accounts
current from the household's institutions and holds their credentials itself, apart from the
server. Each is an app of its own, so the connector can run on another machine.

## App Information

- **Upstream**: https://github.com/$REPO
- **Documentation**: https://github.com/$REPO/blob/v$version/docs/DEPLOY.md
- **License**: GPL-3.0
- **App Version**: $version (images on ghcr.io, pinned by digest, each with a build provenance
  attestation: \`gh attestation verify oci://ghcr.io/mojokata/moolakata:$version -R $REPO\`)

## Testing

Tested locally, each case rendered and started, and the running app looked at (its health,
its user, its root filesystem and the certificate it serves):

- [x] moolakata: basic-values.yaml, https-values.yaml, hostnet-values.yaml
- [x] moolakata-connector: basic-values.yaml, https-values.yaml, hostnet-values.yaml

All tests passed successfully.

## Icons and Screenshots

Please upload the following to the CDN:

- MoolaKata, icon: $raw/${MEDIA[0]}
- MoolaKata Connector, icon: $raw/${MEDIA[1]}
- MoolaKata, screenshots: ${MEDIA[2]}, ${MEDIA[3]}, ${MEDIA[4]},
  ${MEDIA[5]}
- MoolaKata Connector, screenshots: $raw/${MEDIA[6]}, $raw/${MEDIA[7]}

## Special Notes

- First-time setup: the first visit to MoolaKata's page shows its recovery phrase once, takes
  three of its words back and sets up the admin account; the connector's page does the same
  with its 12 words. Neither is ever stored.
- Each starts locked after every restart, update or reboot, until someone enters the phrase
  (or the 12 words) on its page. That includes the restart when a chosen certificate renews.
- Each runs as its image's fixed user (10001 and 10002), so there is no user and group
  section; the permissions container gives the datasets to that user.
- Each serves HTTPS itself: a certificate from System › Certificates, or one it makes for the
  addresses given in its form. The root filesystem is read-only, except when a certificate
  is chosen, since compose can't copy one into a read-only container.
- Neither has Additional Environment Variables or Additional Storage: neither has a setting
  to tune or reads anything outside its own storage, and the connector's one other variable,
  a development switch, would let it reach the loopback and link-local addresses its egress
  check refuses.

## Checklist

- [x] App runs successfully locally
- [x] Only modified files under /ix-dev/ or /library/
- [x] README.md included
- [x] Multiple test scenarios tested
- [x] questions.yaml has clear descriptions and follows structure of existing apps
- [ ] All automated CI checks pass
EOF
}

main() {
  local open=0
  case "${1:-}" in
  "") ;;
  --open) open=1 ;;
  *) die "publish/truenas/create-pr.sh [--open]" ;;
  esac
  for cmd in gh docker git python3 curl; do
    command -v "$cmd" >/dev/null || die "needs $cmd"
  done
  local version me
  version="$(release)"
  me="$(gh api user --jq .login)" || die "gh isn't signed in"
  local sha
  sha="$(gh api "repos/$REPO/commits/main" --jq .sha)"
  media "$sha"
  say "MoolaKata $version, the apps checked first"
  "$HERE/check.sh"
  checkout
  local app digest
  for app in "${APPS[@]}"; do
    digest="$(pinned "$app" "$version")"
    say "$app: ghcr.io/mojokata/$app:$version@$digest"
    place "$app" "$version" "$digest"
  done
  (cd "$WORK" && python3 .github/scripts/port_validation.py >/dev/null) ||
    die "a default port the catalog already uses"
  git -C "$WORK" add ix-dev/community/moolakata ix-dev/community/moolakata-connector
  local verb=Add
  git -C "$WORK" cat-file -e "FETCH_HEAD:ix-dev/community/moolakata/app.yaml" 2>/dev/null && verb=Update
  git -C "$WORK" commit --quiet -m "$verb MoolaKata and MoolaKata Connector ($version)"
  body "$version" "$sha"
  git -C "$WORK" show --stat --format='%h %s' HEAD | tail -n +1
  say "the request's text: $BODY"
  if [[ "$open" == 0 ]]; then
    say "nothing sent; publish/truenas/create-pr.sh --open pushes $BRANCH to $me/apps and opens the request"
    return
  fi
  gh repo view "$me/apps" >/dev/null 2>&1 || die "no fork $me/apps: gh repo fork $UPSTREAM --clone=false"
  git -C "$WORK" push --quiet --force "git@github.com:$me/apps.git" "$BRANCH:$BRANCH"
  local open_pr
  open_pr="$(gh pr list -R "$UPSTREAM" --head "$BRANCH" --author "$me" --state open --json number --jq '.[0].number')"
  if [[ -n "$open_pr" ]]; then
    gh pr edit "$open_pr" -R "$UPSTREAM" --body-file "$BODY" >/dev/null
    say "updated https://github.com/$UPSTREAM/pull/$open_pr"
  else
    gh pr create -R "$UPSTREAM" --draft --base master --head "$me:$BRANCH" \
      --title "$verb MoolaKata and MoolaKata Connector" --body-file "$BODY"
  fi
}

main "$@"
