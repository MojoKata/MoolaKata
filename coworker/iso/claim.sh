#!/bin/sh
# claim.sh ISO PROJECT: PROJECT needs ISO. It leaves an empty file <iso>.<project> beside the ISO in
# the shared folder, $ISO_DIR (default ~/claude-downloads/iso), and the ISO stays while any such
# file is left (coworker/iso/README.md).
set -eu
DIR=${ISO_DIR:-$HOME/claude-downloads/iso}
ISO=$(basename "${1:?usage: claim.sh ISO PROJECT}")
P=${2:?usage: claim.sh ISO PROJECT}
case $P in ''|*[!A-Za-z0-9_-]*|sha256|sha256sum|part|lock|bad) echo "claim.sh: a project name is letters, digits, - and _" >&2; exit 2 ;; esac
mkdir -p "$DIR"
touch "$DIR/$ISO.$P"
if [ -f "$DIR/$ISO" ]; then echo "$P claims $ISO"; else echo "$P claims $ISO, not here yet: download it to $DIR"; fi
