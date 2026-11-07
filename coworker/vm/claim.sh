#!/bin/sh
# claim.sh VM PROJECT: PROJECT needs VM. It leaves an empty file <vm>.<project> beside the VM's
# folder in $VM_DIR (default ~/vm), and the VM is kept while any such file is left
# (coworker/vm/README.md).
set -eu
DIR=${VM_DIR:-$HOME/vm}
VM=$(basename "${1:?usage: claim.sh VM PROJECT}")
P=${2:?usage: claim.sh VM PROJECT}
case $P in ''|*[!A-Za-z0-9_-]*|lock) echo "claim.sh: a project name is letters, digits, - and _" >&2; exit 2 ;; esac
mkdir -p "$DIR"
touch "$DIR/$VM.$P"
if [ -f "$DIR/$VM/vm.env" ]; then echo "$P claims $VM"; else echo "$P claims $VM, not set up yet: no $DIR/$VM/vm.env"; fi
