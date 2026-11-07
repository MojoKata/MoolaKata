#!/bin/sh
# lock.sh VM PROJECT [--no-wait] -- COMMAND [ARG...]: runs COMMAND while holding VM's lock,
# $VM_DIR/<vm>.lock (default ~/vm), so one project uses the VM at a time (coworker/vm/README.md).
# Another project's run waits, after saying whose run it waits for; with --no-wait it exits 75
# instead. The lock file names the holder while it runs; COMMAND sees COWORKER_VM_LOCKED=<vm>, so a
# script that re-runs itself under lock.sh knows it holds the lock. Exits with COMMAND's status.
set -eu
usage="usage: lock.sh VM PROJECT [--no-wait] -- COMMAND [ARG...]"
DIR=${VM_DIR:-$HOME/vm}
VM=$(basename "${1:?$usage}")
P=${2:?$usage}
shift 2
WAIT=1
[ "${1:-}" = --no-wait ] && { WAIT=0; shift; }
[ "${1:-}" = -- ] || { echo "$usage" >&2; exit 2; }
shift
[ $# -gt 0 ] || { echo "$usage" >&2; exit 2; }
[ -d "$DIR/$VM" ] || { echo "lock.sh: no VM $VM in $DIR" >&2; exit 1; }
L="$DIR/$VM.lock"
exec 9>>"$L"
if ! flock -n 9; then
    who=$(cat "$L" 2>/dev/null || true)
    [ "$WAIT" = 1 ] || { echo "$VM is in use: ${who:-by another run}" >&2; exit 75; }
    echo "$VM is in use: ${who:-by another run}; waiting for it"
    flock 9
fi
printf '%s, pid %s, since %s\n' "$P" "$$" "$(date '+%Y-%m-%d %H:%M:%S %Z')" > "$L"
COWORKER_VM_LOCKED=$VM
export COWORKER_VM_LOCKED
rc=0
"$@" || rc=$?
: > "$L"
exit "$rc"
