#!/bin/sh
# release.sh ISO PROJECT: PROJECT no longer needs ISO. Removes PROJECT's claim, and the ISO with its
# checksum only when no other project's claim is left (coworker/iso/README.md).
set -eu
DIR=${ISO_DIR:-$HOME/claude-downloads/iso}
ISO=$(basename "${1:?usage: release.sh ISO PROJECT}")
P=${2:?usage: release.sh ISO PROJECT}
rm -f "$DIR/$ISO.$P"
left=""
for f in "$DIR/$ISO".*; do
    s=${f##*/"$ISO".}
    case $s in '*'|*.*|sha256|sha256sum|part|lock|bad) ;; *) left="$left $s" ;; esac
done
if [ -z "$left" ]; then
    rm -f "$DIR/$ISO" "$DIR/$ISO.sha256" "$DIR/$ISO.sha256sum.txt" "$DIR/$ISO.part" "$DIR/$ISO.bad" "$DIR/$ISO.lock"
    echo "$P released $ISO; no project claims it, so it's removed"
else
    echo "$P released $ISO; kept, claimed by$left"
fi
