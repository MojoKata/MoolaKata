"""Changes' diffs as `mutmut show` prints them, many in one process: run by `mutate` in its copy
(web/.dev/mutate/web) with the copy's own Python, where mutmut is installed.

Reads {"generate": bool, "names": {change: "src/moolakata/x.py"}} on stdin and prints
{change: diff} as JSON. With "generate", it first makes the copy's mutants (mutmut's own
generation, no test run), so the changes of a run made elsewhere, on the same code and the same
mutmut, read as that run's: mutmut names them in the order it makes them."""

import json
import os
import sys
from pathlib import Path


def main() -> int:
    asked = json.load(sys.stdin)
    from mutmut.__main__ import (  # the copy's mutmut, not the checkout's environment
        copy_also_copy_files,
        copy_src_dir,
        create_mutants,
        setup_source_paths,
    )
    from mutmut.mutation.diff_apply import get_diff_for_mutant

    if asked["generate"]:
        os.makedirs("mutants", exist_ok=True)
        copy_src_dir()
        copy_also_copy_files()
        setup_source_paths()
        create_mutants(os.cpu_count() or 4)
    out = {}
    for name, path in asked["names"].items():
        try:
            out[name] = get_diff_for_mutant(name, path=Path(path))
        except Exception:  # a change mutmut doesn't find has no diff
            out[name] = ""
    sys.stdout.write("\n" + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
