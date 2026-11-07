#!/bin/sh
# env.sh VM: how to reach VM, from its folder's vm.env, as shell assignments to eval:
#   eval "$(coworker/vm/env.sh win10)"
# sets VM_HOME (the VM's folder) and each VM_* setting in vm.env, with the key and known-hosts paths
# made absolute (coworker/vm/README.md, "vm.env").
set -eu
DIR=${VM_DIR:-$HOME/vm}
VM=$(basename "${1:?usage: env.sh VM}")
H="$DIR/$VM"
[ -f "$H/vm.env" ] || { echo "env.sh: no $H/vm.env (coworker/vm/README.md)" >&2; exit 1; }
H=$(cd "$H" && pwd -P)
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
(
    unset VM_OS VM_CONTAINER VM_SSH_HOST VM_SSH_PORT VM_SSH_USER VM_SSH_KEY VM_KNOWN_HOSTS
    . "$H/vm.env"
    for k in VM_SSH_PORT VM_SSH_USER VM_SSH_KEY; do
        eval "v=\${$k:-}"
        [ -n "$v" ] || { echo "env.sh: $H/vm.env sets no $k" >&2; exit 1; }
    done
    abs() { case $1 in /*) printf '%s' "$1" ;; ?*) printf '%s/%s' "$H" "$1" ;; esac; }
    echo "VM_HOME=$(q "$H")"
    echo "VM_OS=$(q "${VM_OS:-}")"
    echo "VM_CONTAINER=$(q "${VM_CONTAINER:-}")"
    echo "VM_SSH_HOST=$(q "${VM_SSH_HOST:-127.0.0.1}")"
    echo "VM_SSH_PORT=$(q "$VM_SSH_PORT")"
    echo "VM_SSH_USER=$(q "$VM_SSH_USER")"
    echo "VM_SSH_KEY=$(q "$(abs "$VM_SSH_KEY")")"
    echo "VM_KNOWN_HOSTS=$(q "$(abs "${VM_KNOWN_HOSTS:-known_hosts}")")"
)
