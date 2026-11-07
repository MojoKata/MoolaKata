#!/usr/bin/env bash
# The terminal steps of docs/RELEASE.md, one command each. Run alone to list them.
set -euo pipefail

WEB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$WEB")"
# shellcheck source=uv-path
source "$WEB/uv-path"
REPO=MojoKata/MoolaKata
OWNER=mojokata
IMAGES=(moolakata moolakata-connector)
SIGNER="$REPO/.github/workflows/release.yml"
# gh reads docker.io as index.docker.io; registry-1.docker.io is the registry itself, which
# serves the same images and is the one some networks let through.
HUB_API=registry-1.docker.io
# A command's scratch directory, removed when the script ends.
TMP=""
trap '[[ -z $TMP ]] || rm -rf "$TMP"' EXIT

usage() {
  cat <<'USAGE'
web/release.sh <command> <version>

The steps of docs/RELEASE.md that run from a terminal, in their order. Each checks what it
can first, and asks before anything that can't be taken back.

  sign VERSION [COMMIT]
               §5: sign the tag vVERSION on MojoKata's main (or COMMIT) with your GPG
               key, check the signature, then push it, which starts release.yml
  watch VERSION
               §6: follow the tag's release.yml run, then list the draft's files
  check VERSION
               §7: both images on both registries: both platforms, the same digests,
               the strict attestation check, and a pull without signing in
  publish VERSION NOTES [--households]
               §8: publish the draft with the notes file, as a pre-release unless
               --households; then verify the release and each of its files
  next VERSION
               §9: once web/VERSION's release is published, move web/VERSION and the
               connector to VERSION-dev, and regenerate the API's document
  attach VERSION
               add the tag's eight install files to a release that can still take
               them: a draft, or one published before immutability (0.1.0)
  copy VERSION
               §11: copy both images to Docker Hub, digests unchanged, when
               release.yml's copy can't
  token        §12: check a new Docker Hub token, then store it as the docker-hub
               environment's secret
  setup        §12: check the setup done once (docs/GENESIS.md): immutable releases,
               the rulesets on tags and main, the docker-hub environment, both
               registries

Needs git, gh signed in as a maintainer, and Docker with buildx. VERSION is like 0.2.0.
USAGE
}

die() {
  echo "release.sh: $*" >&2
  exit 1
}

confirm() {
  local answer
  read -r -p "$1 [y/N] " answer || true
  [[ $answer == [yY] || $answer == [yY][eE][sS] ]]
}

need() {
  local tool
  for tool in "$@"; do
    command -v "$tool" >/dev/null || die "needs $tool"
  done
}

version_arg() {
  [[ ${1:-} =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "a version like 0.2.0, not '${1:-}'"
}

# The remote that points at MojoKata/MoolaKata: `upstream` in a fork, `origin` in a clone.
remote() {
  local name
  for name in $(git -C "$ROOT" remote); do
    case "$(git -C "$ROOT" remote get-url "$name")" in
      *[:/]MojoKata/MoolaKata | *[:/]MojoKata/MoolaKata.git)
        echo "$name"
        return
        ;;
    esac
  done
  die "no remote points at github.com/$REPO"
}

fetch_tag() {
  git -C "$ROOT" fetch -q "$(remote)" tag "v$1" || die "no tag v$1 on $REPO"
}

# The install files a release carries, as release.yml's draft job attaches them (§6).
install_files() {
  git -C "$ROOT" ls-tree -r --name-only "v$1" -- web/install |
    grep -E '^web/install/(compose[^/]*\.yaml|moolakata\.toml|proxy/[^/]+)$'
}

digest() {
  docker buildx imagetools inspect "$1" --format '{{.Manifest.Digest}}'
}

platforms() {
  docker buildx imagetools inspect "$1" \
    --format '{{range .Manifest.Manifests}}{{.Platform.OS}}/{{.Platform.Architecture}} {{end}}'
}

verify_image() {
  gh attestation verify "oci://$1" -R "$REPO" --signer-workflow "$SIGNER" \
    --source-ref "refs/tags/v$2" --deny-self-hosted-runners >/dev/null
}

cmd_sign() {
  version_arg "${1:-}"
  need git gpg
  local version=$1 up commit tagger key
  up=$(remote)
  git -C "$ROOT" fetch -q "$up"
  commit=$(git -C "$ROOT" rev-parse --verify "${2:-$up/main}^{commit}")
  [[ "$(git -C "$ROOT" show "$commit:web/VERSION")" == "$version" ]] ||
    die "web/VERSION at ${commit:0:12} says $(git -C "$ROOT" show "$commit:web/VERSION"), not $version (§3)"
  [[ -z "$(git -C "$ROOT" ls-remote --tags "$up" "refs/tags/v$version")" ]] ||
    die "v$version is already on $REPO (§11 says how to delete a wrong one)"
  ! git -C "$ROOT" rev-parse -q --verify "refs/tags/v$version" >/dev/null ||
    die "v$version is already a tag here, never pushed: git tag -d v$version to start again"
  tagger=$(git -C "$ROOT" var GIT_COMMITTER_IDENT | sed -E 's/ [0-9]+ [-+][0-9]{4}$//')
  key=$(git -C "$ROOT" config user.signingkey || echo "gpg's default key")
  echo "commit  $(git -C "$ROOT" log -1 --format='%h %s' "$commit")"
  echo "tagger  $tagger"
  echo "key     $key"
  echo "GitHub shows the tag Verified only if that key is on your account and the email is"
  echo "one of its verified addresses (§5)."
  confirm "Sign v$version on that commit?" || die "nothing done"
  git -C "$ROOT" tag -s "v$version" -m "MoolaKata $version" "$commit"
  git -C "$ROOT" tag -v "v$version"
  confirm "Push v$version to $up? This starts release.yml." ||
    die "v$version is signed here, not pushed: git push $up v$version, or git tag -d v$version"
  git -C "$ROOT" push "$up" "refs/tags/v$version"
  echo "next: web/release.sh watch $version"
}

cmd_watch() {
  version_arg "${1:-}"
  need gh
  local version=$1 run
  run=$(gh run list -R "$REPO" --workflow release.yml --branch "v$version" --limit 1 \
    --json databaseId --jq '.[0].databaseId // empty')
  [[ -n $run ]] || die "no release.yml run for v$version yet"
  if ! gh run watch -R "$REPO" --exit-status "$run"; then
    echo "the run failed: its annotations say which step, and §11 what to do" >&2
    gh run view -R "$REPO" "$run" --json jobs \
      --jq '.jobs[] | select(.conclusion == "failure") | "  \(.name): \(.url)"' >&2
    exit 1
  fi
  echo "== the release's files"
  gh release view "v$version" -R "$REPO" --json isDraft,assets \
    --jq '"draft: \(.isDraft)", (.assets[] | "  \(.name)")'
  echo "next: web/release.sh check $version"
}

cmd_check() {
  version_arg "${1:-}"
  need gh docker
  local version=$1 image from to ref found ghcr hub failed=0
  for image in "${IMAGES[@]}"; do
    from="ghcr.io/$OWNER/$image:$version" to="docker.io/$OWNER/$image:$version"
    echo "== $image"
    for ref in "$from" "$to"; do
      found=$(platforms "$ref" || true)
      if [[ $found == *linux/amd64* && $found == *linux/arm64* ]]; then
        echo "ok    $ref: linux/amd64 and linux/arm64"
      else
        echo "FAIL  $ref: not both platforms (${found:-not found})"
        failed=1
      fi
    done
    ghcr=$(digest "$from" || true) hub=$(digest "$to" || true)
    if [[ -n $ghcr && $ghcr == "$hub" ]]; then
      echo "ok    the same digest on both registries, $ghcr"
    else
      echo "FAIL  the digests differ: ${ghcr:-none} on ghcr.io, ${hub:-none} on Docker Hub"
      failed=1
    fi
    for ref in "ghcr.io/$OWNER/$image:$version" "$HUB_API/$OWNER/$image:$version"; do
      if verify_image "$ref" "$version"; then
        echo "ok    $ref: built by release.yml from v$version on GitHub's runners"
      else
        echo "FAIL  $ref: the strict attestation check failed"
        failed=1
      fi
    done
  done
  # An empty Docker config signs in nowhere, so these pulls are what anyone gets.
  TMP=$(mktemp -d)
  echo "== pulls without signing in"
  for ref in "ghcr.io/$OWNER/moolakata:$version" "docker.io/$OWNER/moolakata:$version"; do
    if DOCKER_CONFIG="$TMP" docker pull -q "$ref" >/dev/null; then
      echo "ok    $ref"
    else
      echo "FAIL  $ref"
      failed=1
    fi
  done
  [[ $failed == 0 ]] || die "something above failed: don't publish the release (§11)"
  echo "next: web/release.sh publish $version notes-$version.md"
}

cmd_publish() {
  version_arg "${1:-}"
  need git gh
  local version=$1 notes=${2:-} households=${3:-} name wanted got typed
  [[ -s $notes ]] || die "the release notes' file (§4) is missing or empty: '$notes'"
  [[ -z $households || $households == --households ]] || die "unknown option '$households'"
  [[ "$(gh release view "v$version" -R "$REPO" --json isDraft --jq .isDraft)" == true ]] ||
    die "v$version has no draft release to publish"
  fetch_tag "$version"
  wanted=$(install_files "$version" | xargs -n1 basename | sort)
  got=$(gh release view "v$version" -R "$REPO" --json assets --jq '.assets[].name' | sort)
  [[ $got == "$wanted" ]] || die "the draft's files aren't the tag's install files:
$(diff <(echo "$wanted") <(echo "$got") || true)
web/release.sh attach $version adds what is missing"
  if [[ -n $households ]]; then
    echo "v$version will be published for households: not a pre-release."
  else
    echo "v$version will be published as a pre-release, for testers."
  fi
  echo "Once published, its tag and files are locked for good (§8)."
  read -r -p "Type v$version to publish it: " typed || true
  [[ $typed == "v$version" ]] || die "nothing done"
  if [[ -n $households ]]; then
    gh release edit "v$version" -R "$REPO" --draft=false --prerelease=false --notes-file "$notes"
  else
    gh release edit "v$version" -R "$REPO" --draft=false --prerelease --notes-file "$notes"
  fi
  gh release verify "v$version" -R "$REPO"
  TMP=$(mktemp -d)
  gh release download "v$version" -R "$REPO" -D "$TMP"
  for name in $wanted; do
    gh release verify-asset "v$version" "$TMP/$name" -R "$REPO"
  done
  local major minor
  IFS=. read -r major minor _ <<<"$version"
  echo "next: the pull command on Docker Hub (§8), web/release.sh next $major.$((minor + 1)).0 (§9),"
  echo "then §10, run DEPLOY.md with the release"
}

cmd_next() {
  version_arg "${1:-}"
  need gh uv
  local version=$1 current dev file
  current=$(cat "$WEB/VERSION")
  [[ $current =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "web/VERSION says $current, not a release"
  # A failed build is tagged again under the same version (§11), so main keeps it until then.
  [[ "$(gh release view "v$current" -R "$REPO" --json isDraft --jq .isDraft 2>/dev/null)" == false ]] ||
    die "v$current isn't published yet (§8)"
  [[ $version != "$current" && "$(printf '%s\n' "$current" "$version" | sort -V | tail -1)" == "$version" ]] ||
    die "$version doesn't come after $current"
  dev="$version-dev"
  echo "$dev" >"$WEB/VERSION"
  sed -i "s/^version = \"${current//./\\.}\"$/version = \"$dev\"/" "$ROOT/connector/pyproject.toml"
  sed -i "s/^VERSION = \"${current//./\\.}\"$/VERSION = \"$dev\"/" "$ROOT/connector/moolakata_connector/__init__.py"
  for file in connector/pyproject.toml connector/moolakata_connector/__init__.py; do
    grep -qF "\"$dev\"" "$ROOT/$file" || die "$file didn't say $current: set $dev there by hand"
  done
  (cd "$WEB/server" && uv run --frozen python -m moolakata.contract write)
  git -C "$ROOT" diff --stat
  echo "next: web/dev.sh mockup, web/check, then the pull request Open $dev (§9)"
}

cmd_attach() {
  version_arg "${1:-}"
  need git gh tar
  local version=$1 files=()
  gh release view "v$version" -R "$REPO" --json isDraft,isImmutable,assets \
    --jq '"draft: \(.isDraft)  immutable: \(.isImmutable)", "attached: \([.assets[].name] | join(" "))"' ||
    die "no release for v$version"
  [[ "$(gh release view "v$version" -R "$REPO" --json isImmutable --jq .isImmutable)" == false ]] ||
    die "v$version is immutable: nothing can be attached (§11)"
  fetch_tag "$version"
  TMP=$(mktemp -d)
  git -C "$ROOT" archive "v$version" web/install | tar -x -C "$TMP"
  mapfile -t files < <(install_files "$version")
  printf '  %s\n' "${files[@]#web/install/}"
  confirm "Attach these ${#files[@]} files from v$version, replacing any of the same name?" ||
    die "nothing done"
  gh release upload "v$version" -R "$REPO" --clobber "${files[@]/#/$TMP/}"
  echo "attached: $(gh release view "v$version" -R "$REPO" --json assets --jq '[.assets[].name] | join(" ")')"
}

cmd_copy() {
  version_arg "${1:-}"
  need docker
  local version=$1 image from to
  for image in "${IMAGES[@]}"; do
    docker buildx imagetools inspect "ghcr.io/$OWNER/$image:$version" >/dev/null ||
      die "ghcr.io/$OWNER/$image:$version isn't there to copy"
  done
  echo "Sign in to Docker Hub as $OWNER (its password, or a token with Read & Write):"
  docker login docker.io -u "$OWNER"
  for image in "${IMAGES[@]}"; do
    from="ghcr.io/$OWNER/$image:$version" to="docker.io/$OWNER/$image:$version"
    docker buildx imagetools create -t "$to" "$from"
    [[ "$(digest "$to")" == "$(digest "$from")" ]] || die "$to's digest isn't $from's"
    echo "ok    $to: $(digest "$to")"
  done
  echo "next: web/release.sh check $version"
}

cmd_token() {
  need gh docker
  local token
  echo "Make the token first (§12): Docker Home › Account settings › Personal access tokens."
  read -r -s -p "The new token (not shown): " token || true
  echo
  [[ -n $token ]] || die "no token given"
  # A throwaway Docker config: the check signs in there, not in yours.
  TMP=$(mktemp -d)
  printf '%s' "$token" | DOCKER_CONFIG="$TMP" docker login docker.io -u "$OWNER" --password-stdin >/dev/null ||
    die "the token doesn't sign in to Docker Hub as $OWNER"
  echo "ok    it signs in as $OWNER"
  printf '%s' "$token" | gh secret set DOCKERHUB_TOKEN --env docker-hub -R "$REPO"
  gh secret list --env docker-hub -R "$REPO"
  echo "Now revoke the old token in Docker Home, and move the renewal reminder (§12)."
}

cmd_setup() {
  need gh curl
  local failed=0 got image ruleset token enforcement include rules bypass checks
  # One line per check: ok, or FAIL with what was found.
  report() {
    if [[ $2 == ok ]]; then
      echo "ok    $1"
    else
      echo "FAIL  $1: $2"
      failed=1
    fi
  }
  # gh prints an error's body on standard output, so a failed read is replaced whole.
  got=$(gh api "repos/$REPO/immutable-releases" --jq .enabled 2>/dev/null) || got=unreadable
  report "immutable releases" "$([[ $got == true ]] && echo ok || echo "$got (needs a maintainer's gh login, or the setting is off)")"
  ruleset=$(gh api "repos/$REPO/rulesets" --jq '[.[] | select(.target == "tag")][0].id // empty' 2>/dev/null) ||
    ruleset=""
  if [[ -z $ruleset ]]; then
    report "a tag ruleset" "none found"
  else
    got=$(gh api "repos/$REPO/rulesets/$ruleset" --jq \
      '[.enforcement, (.conditions.ref_name.include | join(",")), ([.rules[].type] | sort | join(",")), (.bypass_actors // [] | length)] | join(" ")' 2>/dev/null) ||
      got="unreadable"
    read -r enforcement include rules bypass <<<"$got"
    report "the tag ruleset is active" "$([[ $enforcement == active ]] && echo ok || echo "$enforcement")"
    report "it covers v* tags" "$([[ $include == refs/tags/v\* ]] && echo ok || echo "$include")"
    report "it restricts creating, updating and deleting them" \
      "$([[ $rules == *creation* && $rules == *update* && $rules == *deletion* ]] && echo ok || echo "$rules")"
    report "maintainers can bypass it" "$([[ $bypass -gt 0 ]] && echo ok || echo "no bypass list visible (needs a maintainer's gh login)")"
  fi
  ruleset=$(gh api "repos/$REPO/rulesets" --jq '[.[] | select(.target == "branch")][0].id // empty' 2>/dev/null) ||
    ruleset=""
  if [[ -z $ruleset ]]; then
    report "a ruleset on main" "none found (GENESIS.md §3 step 5)"
  else
    got=$(gh api "repos/$REPO/rulesets/$ruleset" --jq \
      '[.enforcement, (.conditions.ref_name.include | join(",")), ([.rules[].type] | sort | join(",")), ([.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context] | join(","))] | join(" ")' 2>/dev/null) ||
      got="unreadable"
    read -r enforcement include rules checks <<<"$got"
    report "main's ruleset is active" "$([[ $enforcement == active ]] && echo ok || echo "$enforcement")"
    report "it covers main" "$([[ $include == *~DEFAULT_BRANCH* || $include == *refs/heads/main* ]] && echo ok || echo "$include")"
    report "it takes pull requests only, once check passed" \
      "$([[ $rules == *pull_request* && $rules == *required_status_checks* && ,$checks, == *,check,* ]] && echo ok || echo "$rules, checks: ${checks:-none}")"
  fi
  got=$(gh api "repos/$REPO/environments/docker-hub/deployment-branch-policies" \
    --jq '[.branch_policies[] | "\(.type):\(.name)"] | join(",")' 2>/dev/null) || got=missing
  report "the docker-hub environment admits only v* tags" "$([[ $got == "tag:v*" ]] && echo ok || echo "$got")"
  got=$(gh secret list --env docker-hub -R "$REPO" --json name,updatedAt \
    --jq '.[] | select(.name == "DOCKERHUB_TOKEN") | .updatedAt' 2>/dev/null) || got=unreadable
  if [[ $got == unreadable || -z $got ]]; then
    report "DOCKERHUB_TOKEN" "${got:-missing} (needs a maintainer's gh login)"
  else
    report "DOCKERHUB_TOKEN, set ${got%%T*}" ok
    if (($(date +%s) - $(date -d "$got" +%s) > 330 * 86400)); then
      echo "      it was set over 11 months ago: renew it before it expires (§12)"
    fi
  fi
  got=$(gh variable get DOCKERHUB_USERNAME --env docker-hub -R "$REPO" 2>/dev/null) ||
    got="unreadable (needs a maintainer's gh login)"
  report "DOCKERHUB_USERNAME is $OWNER" "$([[ $got == "$OWNER" ]] && echo ok || echo "$got")"
  for image in "${IMAGES[@]}"; do
    got=$(curl -fsS "https://hub.docker.com/v2/repositories/$OWNER/$image/" 2>/dev/null |
      grep -o '"is_private":[a-z]*' || echo missing)
    report "docker.io/$OWNER/$image is public" "$([[ $got == '"is_private":false' ]] && echo ok || echo "$got")"
    token=$(curl -fsS "https://ghcr.io/token?scope=repository:$OWNER/$image:pull" 2>/dev/null |
      sed -nE 's/.*"token":"([^"]+)".*/\1/p')
    got=$(curl -fsS -o /dev/null -w ok -H "Authorization: Bearer $token" \
      "https://ghcr.io/v2/$OWNER/$image/tags/list" 2>/dev/null || echo "not public")
    report "ghcr.io/$OWNER/$image is public" "$got"
  done
  [[ $failed == 0 ]] || exit 1
}

cmd="${1:-}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
  sign) cmd_sign "$@" ;;
  watch) cmd_watch "$@" ;;
  check) cmd_check "$@" ;;
  publish) cmd_publish "$@" ;;
  next) cmd_next "$@" ;;
  attach) cmd_attach "$@" ;;
  copy) cmd_copy "$@" ;;
  token) cmd_token ;;
  setup) cmd_setup ;;
  "" | help | -h | --help) usage ;;
  *)
    usage >&2
    exit 1
    ;;
esac
