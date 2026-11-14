"""Screenshots shown in a pull request's conversation, for a change to be looked at: the images
go to the fork's `pr-shots` branch (a folder per pull request, never merged) and a comment shows
them inline, linked by that commit so they never change. The working tree is left alone: the
commit is made through an index of its own.

    web/dev.sh pr-screenshots PR FILE... [--note TEXT]
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

UPSTREAM = "MojoKata/MoolaKata"
BRANCH = "pr-shots"


def run(*args: str, env: dict | None = None, check: bool = True) -> str:
    out = subprocess.run(args, capture_output=True, text=True, env=env, check=False)  # noqa: S603 - git and gh, with this tool's own arguments
    if check and out.returncode:
        sys.exit(f"{' '.join(args)}: {out.stderr.strip() or out.stdout.strip()}")
    return out.stdout.strip()


def fork_of(url: str) -> str:
    """owner/repo from a remote's address, ssh or https."""
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        sys.exit(f"origin isn't a GitHub repository: {url}")
    return m.group(1)


def body(pr: int, fork: str, sha: str, names: list[str], note: str = "") -> str:
    """The comment: each image inline, at the commit that holds it."""
    raw = f"https://raw.githubusercontent.com/{fork}/{sha}/pr-{pr}"
    parts = [note.strip()] if note.strip() else []
    parts.append(f"Screenshots for review ({len(names)}), from `{fork}@{sha[:8]}`:")
    parts += [f"**{n}**\n\n![{n}]({raw}/{n})" for n in names]
    parts.append("🤖 Generated with [Claude Code](https://claude.com/claude-code)")
    return "\n\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("pr", type=int)
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--note", default="", help="a line before the images")
    a = p.parse_args(argv)
    missing = [str(f) for f in a.files if not f.is_file()]
    if missing:
        sys.exit(f"no such file: {', '.join(missing)}")
    names = [f.name for f in a.files]
    if len(set(names)) != len(names):
        sys.exit("two files with one name: they'd overwrite each other in the folder")
    fork = fork_of(run("git", "remote", "get-url", "origin"))
    run("git", "-c", "protocol.version=0", "fetch", "-q", "origin", BRANCH, check=False)
    parent = run("git", "rev-parse", "-q", "--verify", f"origin/{BRANCH}", check=False)
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if parent:
            run("git", "read-tree", parent, env=env)
        for f in a.files:
            blob = run("git", "hash-object", "-w", str(f))
            run("git", "update-index", "--add", "--cacheinfo", f"100644,{blob},pr-{a.pr}/{f.name}",
                env=env)  # fmt: skip
        tree = run("git", "write-tree", env=env)
    msg = f"Screenshots for #{a.pr}"
    sha = run("git", "commit-tree", tree, *(["-p", parent] if parent else []), "-m", msg)
    run("git", "-c", "protocol.version=0", "push", "-q", "origin", f"{sha}:refs/heads/{BRANCH}")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as b:
        b.write(body(a.pr, fork, sha, names, a.note))
    print(run("gh", "pr", "comment", str(a.pr), "-R", UPSTREAM, "--body-file", b.name))
    os.unlink(b.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
