#!/bin/sh
# download.sh ISO PROJECT ISO_URL SHA_URL: downloads ISO into the shared folder, $ISO_DIR (default
# ~/claude-downloads/iso), checks its SHA-256 and claims it for PROJECT (coworker/iso/README.md).
# The ISO arrives as ISO.part beside it and is renamed only once its SHA-256 matches; run the same command again after a
# failure and it resumes. An ISO already there that matches is only claimed. SHA_URL may hold the one
# hash or a list naming the ISO (a mirror's sha256sum.txt); what's kept is ISO.sha256, "<hash>  <iso>",
# for sha256sum -c. A host this machine can't reach directly is fetched through a container
# (curlimages/curl), when Docker is here. One download of an ISO at a time: another waits on ISO.lock.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
DIR=${ISO_DIR:-$HOME/claude-downloads/iso}
usage="usage: download.sh ISO PROJECT ISO_URL SHA_URL"
ISO=$(basename "${1:?$usage}")
P=${2:?$usage}
URL=${3:?$usage}
SHAURL=${4:?$usage}
case $P in ''|*[!A-Za-z0-9_-]*|sha256|sha256sum|part|lock|bad) echo "download.sh: a project name is letters, digits, - and _" >&2; exit 2 ;; esac
mkdir -p "$DIR"
DIR=$(cd "$DIR" && pwd)
cd "$DIR"
exec 9>"$ISO.lock"
flock -n 9 || { echo "another download of $ISO is running; waiting for it"; flock 9; }

CURL="-fsSL --retry 5 --retry-delay 5 --connect-timeout 20 --speed-time 60 --speed-limit 10000"
fetch() {      # fetch URL OUT [-C -]: here, or through a container where this machine can't reach the host
    rc=0
    # shellcheck disable=SC2086
    curl $CURL ${3:-} -o "$2" "$1" || rc=$?
    case $rc in 6|7|28|35) ;; *) return $rc ;; esac
    command -v docker >/dev/null || return $rc
    echo "this machine can't reach $(echo "$1" | cut -d/ -f3) (curl exit $rc); fetching through a container"
    rc=0
    # shellcheck disable=SC2086
    docker run --rm --user "$(id -u):$(id -g)" -v "$DIR:/d" -w /d curlimages/curl:8.11.1 $CURL ${3:-} -o "$2" "$1" || rc=$?
    return $rc
}

# the expected SHA-256
fetch "$SHAURL" "$ISO.sha256.tmp" || { rm -f "$ISO.sha256.tmp"; echo "download.sh: couldn't fetch $SHAURL" >&2; exit 1; }
want=$(awk -v f="$ISO" '{n = $2; sub(/^\*/, "", n)} NF == 1 {print $1; exit} n == f {print $1; exit}' "$ISO.sha256.tmp")
rm -f "$ISO.sha256.tmp"
echo "$want" | grep -Eq '^[0-9a-fA-F]{64}$' || { echo "download.sh: no SHA-256 for $ISO in $SHAURL" >&2; exit 1; }
printf '%s  %s\n' "$want" "$ISO" > "$ISO.sha256"

if [ -f "$ISO" ]; then
    if sha256sum -c --status "$ISO.sha256"; then "$HERE/claim.sh" "$ISO" "$P"; exit 0; fi
    echo "$ISO is here but doesn't match its SHA-256; downloading it again (the old copy is $ISO.bad)"
    mv "$ISO" "$ISO.bad"
fi

[ -f "$ISO.part" ] && echo "resuming $ISO from $(du -h "$ISO.part" | cut -f1)" || echo "downloading $ISO"
before=$(stat -c %s "$ISO.part" 2>/dev/null || echo 0)
rc=0
fetch "$URL" "$ISO.part" "-C -" || rc=$?
after=$(stat -c %s "$ISO.part" 2>/dev/null || echo 0)
# a complete .part makes the resume fail (416, nothing left to send): the hash says whether it's whole
got=$(sha256sum "$ISO.part" 2>/dev/null | cut -d' ' -f1)
if [ "$got" != "$want" ]; then
    if [ "$rc" != 0 ] && [ "$after" -gt "$before" ]; then
        echo "download.sh: $ISO stopped (curl exit $rc) at $(du -h "$ISO.part" | cut -f1); run the same command to resume" >&2
    elif [ "$rc" != 0 ] && [ "$before" -gt 0 ]; then
        echo "download.sh: $ISO.part can't be resumed (curl exit $rc, no progress): it may be whole but corrupt; delete it to start over" >&2
    elif [ "$rc" != 0 ]; then
        echo "download.sh: $ISO couldn't be fetched (curl exit $rc) from $URL" >&2
    else
        echo "download.sh: $ISO downloaded, but its SHA-256 doesn't match $SHAURL; delete $ISO.part to start over" >&2
    fi
    exit 1
fi
mv "$ISO.part" "$ISO"
echo "$ISO: SHA-256 matches"
"$HERE/claim.sh" "$ISO" "$P"
