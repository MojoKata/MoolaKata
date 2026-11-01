#!/usr/bin/env python3
"""What a CI job's web/check failed, as GitHub annotations (requirements S17.10.1): they show
on the pull request and through the API, where a reader without access to the run's log can
see them.

    python3 web/check-failures.py <web/check's log>
"""

import sys


def say(title: str, text: str) -> None:
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error title={title.replace(',', ';').replace(':', ' ')}::{text}")


def main(path: str) -> None:
    log = open(path, errors="replace").read()
    # Each step web/check reports failed, with its own output, in parts of 60 lines (GitHub
    # keeps 10 annotations a step: the last 7 parts of each, at most).
    for section in log.split("\n== ")[1:]:
        name, _, body = section.partition("\n")
        if "\n   FAILED: " in "\n" + body:
            lines = body.rstrip("\n").splitlines()
            parts = [lines[i : i + 60] for i in range(0, len(lines), 60)][-7:]
            for n, part in enumerate(parts, 1):
                say(f"{name} ({n} of {len(parts)})", "\n".join(part))
    for line in log.splitlines():
        if line.startswith(("FAILED tests/", "ERROR tests/")):
            say("pytest", line)


if __name__ == "__main__":
    main(sys.argv[1])
