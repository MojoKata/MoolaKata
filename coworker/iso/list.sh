#!/bin/sh
# list.sh [--verify]: every ISO in the shared folder, $ISO_DIR (default ~/claude-downloads/iso),
# or claimed and not there yet, with its size and the projects that claim it; "unclaimed" marks one no project needs
# (coworker/iso/README.md, "Maintenance"). With --verify, whether each one there matches its
# <iso>.sha256 (this reads every ISO: a minute or two).
set -eu
DIR=${ISO_DIR:-$HOME/claude-downloads/iso}
[ -d "$DIR" ] || { echo "no $DIR"; exit 0; }
cd "$DIR"
claims_of() {
    out=""
    for f in "$1".*; do
        [ -e "$f" ] || continue
        s=${f#"$1".}
        case $s in *.*|sha256|sha256sum|part|lock|bad) ;; *) out="$out $s" ;; esac
    done
    echo "$out"
}
names=$({ for f in *.iso; do [ -e "$f" ] && echo "$f"; done
          for f in *.iso.*; do [ -e "$f" ] || continue; s=${f#*.iso.}
              case $s in *.*|sha256|sha256sum|part|lock|bad) ;; *) echo "${f%."$s"}" ;; esac; done; } | sort -u)
for i in $names; do
    c=$(claims_of "$i")
    if [ -f "$i" ]; then size=$(du -h "$i" | cut -f1)
    elif [ -f "$i.part" ]; then size="not here yet, $(du -h "$i.part" | cut -f1) downloaded"
    else size="not here yet"; fi
    v=""
    if [ "${1:-}" = --verify ] && [ -f "$i" ]; then
        if [ -f "$i.sha256" ] && sha256sum -c --status "$i.sha256" 2>/dev/null; then v=" | SHA-256 ok"
        else v=" | SHA-256 doesn't match, or no <iso>.sha256 sha256sum can read"; fi
    fi
    if [ -n "$c" ]; then echo "$i | $size | claimed by$c$v"; else echo "$i | $size | unclaimed$v"; fi
done
