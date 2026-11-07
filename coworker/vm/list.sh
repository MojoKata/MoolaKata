#!/bin/sh
# list.sh: every VM in $VM_DIR (default ~/vm), or claimed and not set up yet, with what it is, the
# projects that claim it and whether a run holds it now (coworker/vm/README.md, "Maintenance").
set -eu
DIR=${VM_DIR:-$HOME/vm}
[ -d "$DIR" ] || { echo "no $DIR"; exit 0; }
cd "$DIR"
names=$({ for f in *; do [ -d "$f" ] && echo "$f"; done
          for f in *.*; do [ -f "$f" ] || continue; s=${f##*.}
              [ "$s" = lock ] || echo "${f%."$s"}"; done; } | sort -u)
for v in $names; do
    c=""
    for f in "$v".*; do
        [ -e "$f" ] || continue
        s=${f#"$v".}
        case $s in *.*|lock) ;; *) c="$c $s" ;; esac
    done
    if [ -f "$v/vm.env" ]; then what=$( (. "./$v/vm.env"; echo "${VM_OS:-a VM}") )
    else what="not set up yet (no $v/vm.env)"; fi
    use=free
    if [ -e "$v.lock" ] && ! ( flock -n 9 ) 9>>"$v.lock"; then use="in use: $(cat "$v.lock")"; fi
    if [ -n "$c" ]; then echo "$v | $what | claimed by$c | $use"; else echo "$v | $what | unclaimed | $use"; fi
done
