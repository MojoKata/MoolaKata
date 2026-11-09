"""CI's parts (requirements S17.10.1): `MK_TEST_PART=k/n` keeps the k-th of n parts of the tests
the marks chose, split by measured time so the parts take about as long as each other. A unit
is a test, or an xdist_group's tests together (they run one after another); each weighs its
tests' times from `durations.json`, a test not named there what a short test takes. The units
go longest first, each to the part with the least so far, the first such on a tie: every xdist
worker collects the same tests, so each makes the same choice. Times out of date make the parts
less even, never a test run twice or not at all.

With `MK_DURATIONS=<file>`, a run writes what its tests took (setup, call and teardown): those
of at least KEEP seconds by name, the rest as a total and a count. `web/dev.sh ci-durations`
gathers a CI run's files into `durations.json`."""

import json
from collections import defaultdict
from pathlib import Path

DURATIONS = Path(__file__).parent / "durations.json"
KEEP = 1.0  # seconds: a test at least this long is named in durations.json


def load(path: Path = DURATIONS) -> tuple[dict[str, float], float]:
    """The named tests' times, and what a test not named takes."""
    if not path.exists():
        return {}, 1.0
    d = json.loads(path.read_text())
    return d["tests"], d["short"]


def assign(weights: list[float], n: int) -> list[int]:
    """Each unit's part (0 to n-1): the heaviest first, each to the part with the least."""
    load = [0.0] * n
    out = [0] * len(weights)
    for i in sorted(range(len(weights)), key=lambda i: (-weights[i], i)):
        p = min(range(n), key=lambda j: (load[j], j))
        out[i] = p
        load[p] += weights[i]
    return out


def choose(items: list[tuple[str, str | None]], k: int, n: int, times: dict[str, float],
           short: float) -> list[bool]:  # fmt: skip
    """Whether each test, given as (node id, its xdist_group or None), is in part k of n."""
    units: dict[str, list[int]] = {}
    for i, (nodeid, group) in enumerate(items):
        units.setdefault(f"group:{group}" if group else nodeid, []).append(i)
    keys = list(units)
    weights = [sum(times.get(items[i][0], short) for i in units[u]) for u in keys]
    part = assign(weights, n)
    keep = [False] * len(items)
    for u, p in zip(keys, part, strict=True):
        for i in units[u]:
            keep[i] = p == k - 1
    return keep


class Recorder:
    """What each test took, added up over its phases, for MK_DURATIONS."""

    def __init__(self) -> None:
        self.took: dict[str, float] = defaultdict(float)

    def add(self, nodeid: str, duration: float) -> None:
        self.took[nodeid] += duration

    def written(self) -> dict:
        long = {t: round(s, 1) for t, s in sorted(self.took.items()) if s >= KEEP}
        rest = [s for s in self.took.values() if s < KEEP]
        return {"tests": long, "shortTotal": round(sum(rest), 2), "shortCount": len(rest)}
