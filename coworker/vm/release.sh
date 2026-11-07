#!/bin/sh
# release.sh VM PROJECT: PROJECT no longer needs VM. Removes PROJECT's claim. A VM is never deleted
# by a script: with the last claim gone, this says so, and the machine's owner decides
# (coworker/vm/README.md).
set -eu
DIR=${VM_DIR:-$HOME/vm}
VM=$(basename "${1:?usage: release.sh VM PROJECT}")
P=${2:?usage: release.sh VM PROJECT}
rm -f "$DIR/$VM.$P"
left=""
for f in "$DIR/$VM".*; do
    s=${f##*/"$VM".}
    case $s in '*'|*.*|lock) ;; *) left="$left $s" ;; esac
done
if [ -z "$left" ]; then
    echo "$P released $VM; no project claims it now: ask the machine's owner before deleting $DIR/$VM"
else
    echo "$P released $VM; kept, claimed by$left"
fi
