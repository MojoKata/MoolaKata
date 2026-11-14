"""How the tests wait (requirements S17.5), checked on the tests themselves so a new one can't
drift: for a condition or an event through `moolakata.dev.waits`, never a sleep of its own;
for a length of time only through `idle`, with its reason written out."""

import ast
import asyncio
import time
from pathlib import Path

import pytest

from moolakata.dev import waits

ROOT = Path(__file__).resolve().parents[3]
# Every test the checks run: the server's, the ui-kit's pages and the connector's.
TEST_DIRS = [ROOT / "web/server/tests", ROOT / "web/ui/kit/tests", ROOT / "connector/tests"]
# Waits for a length of time, by the name they are called by.
RAW = {"sleep", "wait_for_timeout"}


def scanned() -> list[Path]:
    """Every test file but this one, whose own idles are refused on purpose."""
    files = sorted(
        p
        for d in TEST_DIRS
        for p in d.rglob("*.py")
        if "__pycache__" not in p.parts and p != Path(__file__).resolve()
    )
    assert len(files) > 100, "the tests are where this looks for them"
    return files


def calls(path: Path):
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            yield name, node


def test_no_test_sleeps_for_a_time_of_its_own():
    raw = [
        f"{p.relative_to(ROOT)}:{node.lineno} {name}()"
        for p in scanned()
        for name, node in calls(p)
        if name in RAW
    ]
    assert raw == [], (
        "wait with moolakata.dev.waits: until or eventually for a condition, idle (with why) "
        f"to see that nothing happens; these sleep: {raw}"
    )


def test_every_idle_says_why_it_waits_for_time():
    def says_why(node: ast.Call) -> bool:
        why = next((k.value for k in node.keywords if k.arg == "why"), None)
        return (
            isinstance(why, ast.Constant) and isinstance(why.value, str) and bool(why.value.strip())
        )

    silent = [
        f"{p.relative_to(ROOT)}:{node.lineno}"
        for p in scanned()
        for name, node in calls(p)
        if name == "idle" and not says_why(node)
    ]
    assert silent == [], f"an idle without its reason written out as why=: {silent}"


def test_the_scan_finds_each_way_to_sleep(tmp_path):
    # The forms a raw wait takes, and an idle without a written reason, are all seen.
    src = tmp_path / "t.py"
    src.write_text(
        "import time, asyncio\nfrom time import sleep\n"
        "time.sleep(1)\nsleep(1)\nasyncio.sleep(1)\npage.wait_for_timeout(100)\n"
        "idle(1)\nidle(1, why='')\nidle(1, why=reason)\nidle(1, why='a reason')\n"
    )
    found = [(name, n.lineno) for name, n in calls(src)]
    assert [x for x in found if x[0] in RAW] == [
        ("sleep", 3), ("sleep", 4), ("sleep", 5), ("wait_for_timeout", 6),
    ]  # fmt: skip
    idles = [n for name, n in calls(src) if name == "idle"]
    assert [n.lineno for n in idles] == [7, 8, 9, 10]


def test_a_condition_is_waited_for_and_a_timeout_names_it():
    ticks = iter(range(100))
    waits.eventually(lambda: next(ticks) == 3)
    started = time.monotonic()
    with pytest.raises(AssertionError, match=r"never true in 0\.2 s: the job done"):
        waits.eventually(lambda: False, timeout=0.2, what="the job done")
    assert time.monotonic() - started >= 0.2


def test_a_condition_is_waited_for_in_the_event_loop_too():
    async def scenario():
        done = []
        asyncio.get_running_loop().call_later(0.1, done.append, True)
        await waits.turn()
        await waits.eventually_async(lambda: done == [True], what="the callback")
        with pytest.raises(AssertionError, match=r"never true in 0\.1 s: never"):
            await waits.eventually_async(lambda: False, timeout=0.1, what="never")

    asyncio.run(scenario())


def test_idle_refuses_a_wait_without_its_reason():
    for why in ("", "   "):
        with pytest.raises(ValueError, match="why it waits for time"):
            waits.idle(0.01, why=why)
    with pytest.raises(ValueError):
        waits.idle(0, why="a reason")
    waits.idle(0.01, why="a reason")
