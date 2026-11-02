"""Generated budget worlds (requirements S7): a budget's method, viewer, accounts over months,
plan history, transactions of every shape and moves, drawn from a seed. A world is a plain
description first (`World`), so which data shapes the worlds reach is checked without a server
(`pairs`); `test_budget_world` then makes each through the API and holds its figures to every
budget invariant.

The axes and their values are `AXES`. Coverage is pairwise: across the worlds of
`SEEDS`, every pair of values of two axes of one record (a transaction, a line's month, a move)
meets at least once, but for the pairs that can't exist (`IMPOSSIBLE`).

Left out of the worlds, with the tests that cover them: loan payments (split by the schedule,
or whole for a receiver who can't see the loan: test_budgets, test_budget_history), plans
by gift and giving plans (test_budget_plan), and the envelope's card lines beyond a move to one
(test_envelope).
"""

import itertools
import random
from dataclasses import dataclass, field

MONTHS = ("2026-01", "2026-02", "2026-03", "2026-04")
TODAY = (2026, 4, 20)

# Per world.
METHODS = ("tracking", "envelope")
VIEWERS = ("owner", "receiver-all", "receiver-some")

# Per transaction.
SHAPES = ("plain", "split", "refund", "reimbursable", "left-out", "uncategorised", "transfer-cat")
OTHERS = ("none", "inside", "held-in", "outside", "cash", "deleted", "unseen")
SPANS = ("always", "from", "until", "gap", "closed")
POSITIONS = ("own-line", "parent-line", "both", "none")
ACCOUNT_TYPES = ("checking", "savings", "card")

# Per line and month.
KINDS = ("monthly", "rollover", "yearly", "reserve", "income")
STATES = ("set", "changed", "zero", "out", "replanned", "target-on", "target-off")

# Per move.
MOVES = ("category", "to-budget", "landed-given", "landed-kept", "card")

AXES = {
    "txn": {"method": METHODS, "viewer": VIEWERS, "shape": SHAPES, "other": OTHERS,
            "span": SPANS, "position": POSITIONS, "type": ACCOUNT_TYPES},
    "line": {"method": METHODS, "viewer": VIEWERS, "kind": KINDS, "state": STATES},
    "move": {"method": METHODS, "viewer": VIEWERS, "move": MOVES},
}  # fmt: skip

SEEDS = range(24)

# Accounts. Checking, Ally and Marcus always count (a reserve is held in an account the budget
# counts); Visa and Spare carry the spans; the rest are outside the budget.
IN_BUDGET = {"Checking": "checking", "Ally": "savings", "Marcus": "savings", "Visa": "card",
             "Spare": "savings"}  # fmt: skip
OUTSIDE = {"Brokerage": "brokerage", "Pocket": "cash", "Old": "savings", "Hidden": "savings"}
HELD = ("Ally", "Marcus")

# Categories by path: parents with children, and lone ones.
FAMILIES = {
    "Food": ("Food › Groceries", "Food › Dining out"),
    "Transportation": ("Transportation › Fuel", "Transportation › Car maintenance"),
    "Housing": ("Housing › Maintenance", "Housing › Utilities"),
}
LONE = ("Entertainment", "Travel")
INCOME = "Income › Salary"
TRANSFER = "Transfers › To savings"


def _impossible(kind: str, a: tuple[str, str], b: tuple[str, str]) -> bool:
    """Pairs no world can hold."""
    keys = {a[0]: a[1], b[0]: b[1]}
    if kind == "txn":
        # A transfer is whole: no splits, refunds or reimbursable parts on one.
        whole = ("split", "refund", "reimbursable")
        if keys.get("other", "none") != "none" and keys.get("shape") in whole:
            return True
        # Ally and Marcus always count; a span belongs to Visa or Spare (savings or card).
        if keys.get("type") == "checking" and keys.get("span", "always") != "always":
            return True
        # A transfer between the accounts reserves are held in leaves from one of them.
        if keys.get("other") == "held-in" and keys.get("type") in ("checking", "card"):
            return True
        if keys.get("other") == "held-in" and keys.get("span", "always") != "always":
            return True
        # An uncategorised transaction or a transfer category counts against no line.
        uncounted = keys.get("shape") in ("uncategorised", "transfer-cat")
        if uncounted and keys.get("position", "none") != "none":
            return True
        # An account the viewer can't see is a receiver's case; for the owner it is outside.
        if keys.get("other") == "unseen" and keys.get("viewer") == "owner":
            return True
    if kind == "line":
        if keys.get("kind") == "income" and keys.get("state") in ("target-on", "target-off"):
            return True
        if keys.get("kind") == "yearly" and keys.get("state") in ("target-on", "target-off"):
            return True
        if keys.get("kind") == "reserve" and keys.get("state") == "target-on":
            return True
        if keys.get("kind") in ("monthly", "rollover") and keys.get("state") == "target-off":
            return True
    envelope_only = ("to-budget", "card")
    return kind == "move" and keys.get("method") == "tracking" and keys.get("move") in envelope_only


def all_pairs(kind: str) -> set[frozenset]:
    """Every pair of values of two axes of one kind of record that can exist."""
    out = set()
    axes = AXES[kind]
    for x, y in itertools.combinations(axes, 2):
        for vx in axes[x]:
            for vy in axes[y]:
                if not _impossible(kind, (x, vx), (y, vy)):
                    out.add(frozenset({(x, vx), (y, vy)}))
    return out


@dataclass
class Line:
    category: str
    kind: str
    # Per month: the state and the line then (amount, target, held in), or None when out.
    months: list[tuple[str, dict | None]] = field(default_factory=list)


@dataclass
class Txn:
    account: str
    month: str
    day: int
    amount: str
    shape: str
    other: str
    category: str | None
    parts: list[tuple[str, str]] = field(default_factory=list)
    reimbursable: str | None = None


@dataclass
class Move:
    kind: str
    month: str
    frm: str | None
    to: str | None
    amount: str
    account: str | None = None  # landed money's, or a card's


@dataclass
class World:
    seed: int
    method: str
    viewer: str
    spans: dict[str, str]
    lines: list[Line]
    txns: list[Txn]
    moves: list[Move]

    def plan_at(self, month: str) -> dict[str, dict]:
        i = MONTHS.index(month)
        return {ln.category: ln.months[i][1] for ln in self.lines if ln.months[i][1] is not None}

    def position(self, category: str | None, month: str) -> str:
        if not category or category in (TRANSFER,):
            return "none"
        plan = self.plan_at(month)
        parent = next((p for p, kids in FAMILIES.items() if category in kids), None)
        mine = category in plan
        theirs = parent is not None and parent in plan
        if mine and theirs:
            return "both"
        if mine:
            return "own-line"
        if theirs:
            return "parent-line"
        return "none"

    def counts(self, account: str, month: str) -> bool:
        if account not in IN_BUDGET:
            return False
        span = self.spans.get(account, "always")
        i = MONTHS.index(month)
        return {"always": True, "from": i >= 1, "until": i <= 1, "gap": i in (0, 3),
                "closed": i <= 2}[span]  # fmt: skip

    def records(self) -> dict[str, list[dict]]:
        """Each record's axis values, as the pairs are counted."""
        base = {"method": self.method, "viewer": self.viewer}
        txns = [
            {
                **base,
                "shape": t.shape,
                "other": t.other,
                "type": IN_BUDGET[t.account],
                "span": self.spans.get(t.account, "always"),
                "position": self.position(
                    t.category if t.shape != "split" else t.parts[0][0], t.month
                ),
            }
            for t in self.txns
            if self.counts(t.account, t.month)
        ]
        lines = [
            {**base, "kind": ln.kind, "state": state} for ln in self.lines for state, _ in ln.months
        ]
        moves = [{**base, "move": m.kind} for m in self.moves]
        return {"txn": txns, "line": lines, "move": moves}


def pairs(world: World) -> dict[str, set[frozenset]]:
    out: dict[str, set[frozenset]] = {}
    for kind, records in world.records().items():
        got = set()
        for r in records:
            for x, y in itertools.combinations(AXES[kind], 2):
                got.add(frozenset({(x, r[x]), (y, r[y])}))
        out[kind] = got
    return out


def world(seed: int) -> World:
    """A world drawn from a seed: its method and viewer cycle through every pair of them; the
    rest is drawn at random, each axis's values dealt round so every world holds most."""
    rnd = random.Random(seed)
    method = METHODS[seed % 2]
    viewer = VIEWERS[(seed // 2) % 3]
    spans = {"Visa": SPANS[seed % len(SPANS)], "Spare": SPANS[(seed + 2) % len(SPANS)]}
    w = World(seed, method, viewer, spans, [], [], [])
    _plan(w, rnd)
    _txns(w, rnd)
    _moves(w, rnd)
    return w


def _amount(rnd, lo=20, hi=400) -> str:
    return f"{rnd.randint(lo, hi)}.{rnd.randint(0, 99):02d}"


def _plan(w: World, rnd: random.Random) -> None:
    """Lines over parents and children and lone categories, each kind, each state in turn."""
    pool = [*FAMILIES, *[k for kids in FAMILIES.values() for k in kids], *LONE]
    rnd.shuffle(pool)
    chosen = pool[:7]
    kinds = list(KINDS[:-1])
    for i, category in enumerate(chosen):
        kind = kinds[(i + w.seed) % len(kinds)]
        if kind == "reserve" and category in FAMILIES:
            kind = "rollover"  # a reserve is a child or a lone category
        _timeline(w, rnd, category, kind)
    _timeline(w, rnd, INCOME, "income")


def _timeline(w: World, rnd: random.Random, category: str, kind: str) -> None:
    def line(k: str) -> dict:
        out = {"amount": _amount(rnd, 50, 300), "cadence": "month", "rollover": False}
        if k == "rollover":
            out["rollover"] = True
        if k == "yearly":
            out |= {"cadence": "year", "amount": _amount(rnd, 600, 2400)}
        if k == "reserve":
            out |= {"target": _amount(rnd, 400, 900), "heldIn": rnd.choice(HELD)}
        if k == "income":
            out["amount"] = _amount(rnd, 3000, 5000)
        return out

    ln = Line(category, kind)
    cur: dict | None = line(kind)
    ln.months.append(("set", cur))
    for _ in MONTHS[1:]:
        options = ["changed", "zero", "out", "set"]
        if kind == "reserve":
            options.append("target-off")
        if kind in ("monthly", "rollover") and category not in FAMILIES:
            options.append("target-on")
        if cur is None:
            options = ["replanned", "out"]
        state = options[rnd.randrange(len(options))]
        if state == "changed":
            cur = {**cur, "amount": _amount(rnd, 50, 300)}
        elif state == "zero":
            cur = {**cur, "amount": "0.00"}
        elif state == "out":
            cur = None
        elif state == "replanned":
            cur = line(kind)
        elif state == "target-off":
            cur = {k: v for k, v in cur.items() if k not in ("target", "heldIn")}
        elif state == "target-on":
            cur = {**cur, "target": _amount(rnd, 400, 900), "heldIn": rnd.choice(HELD),
                   "cadence": "month", "rollover": True}  # fmt: skip
        ln.months.append((state, cur))
    w.lines.append(ln)


def _categories(w: World) -> list[str]:
    return [*FAMILIES, *[k for kids in FAMILIES.values() for k in kids], *LONE]


def _txns(w: World, rnd: random.Random) -> None:
    """About 60 transactions: shapes and other sides dealt round, the rest at random."""
    cats = _categories(w)
    in_accounts = list(IN_BUDGET)
    for i in range(60):
        month = MONTHS[i % len(MONTHS)]
        shape = SHAPES[(i + w.seed) % len(SHAPES)]
        other = OTHERS[(i * 3 + w.seed) % len(OTHERS)]
        if shape in ("split", "refund", "reimbursable"):
            other = "none"
        if other == "unseen" and w.viewer == "owner":
            other = "outside"
        account = in_accounts[(i + w.seed // 3) % len(in_accounts)]
        if other == "held-in":
            account = rnd.choice(HELD)
        if shape == "left-out" and not w.counts(account, month):
            account = "Checking"  # left out of a budget that counts it
        category = rnd.choice(cats)
        if shape == "uncategorised":
            category = None
        if shape == "transfer-cat":
            category = TRANSFER
        amount = "-" + _amount(rnd, 5, 250)
        t = Txn(account, month, rnd.randint(2, 19), amount, shape, other, category)
        if shape == "split":
            first = rnd.choice(cats)
            second = rnd.choice([c for c in cats if c != first])
            cents = int(amount.replace("-", "").replace(".", ""))
            a = rnd.randint(1, cents - 1)
            t.parts = [(first, f"-{a // 100}.{a % 100:02d}"),
                       (second, f"-{(cents - a) // 100}.{(cents - a) % 100:02d}")]  # fmt: skip
            t.category = None
        if shape == "refund":
            t.amount = amount[1:]
        if shape == "reimbursable":
            cents = int(amount[1:].replace(".", ""))
            part = rnd.randint(1, cents)
            t.reimbursable = f"{part // 100}.{part % 100:02d}"
        w.txns.append(t)


def _moves(w: World, rnd: random.Random) -> None:
    for i, month in enumerate(MONTHS):
        plan = w.plan_at(month)
        cats = [c for c, ln in plan.items() if c != INCOME]
        kinds = [MOVES[(i + w.seed) % len(MOVES)], MOVES[(i + w.seed + 2) % len(MOVES)]]
        for kind in kinds:
            if w.method == "tracking" and kind in ("to-budget", "card"):
                kind = "category"
            if kind == "category" and len(cats) >= 2:
                frm, to = rnd.sample(cats, 2)
                w.moves.append(Move("category", month, frm, to, _amount(rnd, 5, 40)))
            elif kind == "to-budget" and cats:
                w.moves.append(Move("to-budget", month, None, rnd.choice(cats),
                                    _amount(rnd, 5, 40)))  # fmt: skip
            elif kind == "card" and not w.counts("Visa", month):
                if len(cats) >= 2:
                    frm, to = rnd.sample(cats, 2)
                    w.moves.append(Move("category", month, frm, to, _amount(rnd, 5, 40)))
            elif kind == "card":
                w.moves.append(Move("card", month, rnd.choice(cats) if cats else None, None,
                                    _amount(rnd, 5, 40), account="Visa"))  # fmt: skip
            elif kind in ("landed-given", "landed-kept"):
                # Landed money waits in an account holding a reserve that month (S7.10.5).
                held = [c for c, ln in plan.items() if ln.get("heldIn")]
                if not held:
                    if len(cats) >= 2:
                        frm, to = rnd.sample(cats, 2)
                        w.moves.append(Move("category", month, frm, to, _amount(rnd, 5, 40)))
                    continue
                reserve = rnd.choice(held)
                to = reserve if kind == "landed-given" else None
                w.moves.append(Move(kind, month, None, to, _amount(rnd, 1, 9),
                                    account=plan[reserve]["heldIn"]))  # fmt: skip
