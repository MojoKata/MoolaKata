"""Projections (requirements S6.1–S6.9): what a projection is built on and worth today, its
asset mix, the plan the model runs, the goal's answer, and tracking an active one against its
baseline. Retirement and savings-target goals are built now; education comes with 529s
(S1.8, milestone 3).
"""

import datetime as dt
import itertools
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import access, clock, valuation
from ..ledger import types as atypes
from ..store import scoping
from ..store.entities.accounts import Account, Instrument
from ..store.entities.projections import Projection
from ..store.entities.users import User
from ..store.repos import ledger as repo
from . import assumptions, bitcoin, engine, taxtables

INTL = re.compile(
    r"\b(international|intl|ex-?us|emerging|developed|world ex|foreign|global ex)\b|"
    r"^(VXUS|VEA|VWO|IXUS|EFA|IEFA|IEMG|VTIAX|FTIHX|SWISX)$",
    re.I,
)
BOND = re.compile(
    r"\b(bond|treasury|aggregate|income|fixed)\b|^(BND|AGG|BNDX|SCHZ|VBTLX|FXNAX)$", re.I
)
REIT = re.compile(r"\b(reit|real estate)\b|^(VNQ|SCHH|VGSLX)$", re.I)
SLACK = Decimal("0.02")
CENTS = Decimal("0.01")
MAX_YEARS = 101  # a projection runs at most 100 years on from this one
BTC = re.compile(r"^(BTC|XBT)\b", re.I)


def asset_class(inst: Instrument) -> str | None:
    """The assumption row a holding follows (S6.3), from its class and, for funds, its name."""
    c = inst.instrumentClass
    name = f"{inst.symbol or ''} {inst.name or ''}"
    if c in ("cash", "money-market"):
        return "cash"
    if c == "bond":
        return "bonds"
    if c == "crypto":
        return "crypto"
    if c == "metal":
        return "metals"
    if c == "option":
        return None
    if REIT.search(name) or REIT.search(inst.symbol or ""):
        return "realEstate"
    if BOND.search(name) or BOND.search(inst.symbol or ""):
        return "bonds"
    if INTL.search(name) or INTL.search(inst.symbol or ""):
        return "intlStocks"
    return "usStocks"


@dataclass
class BuiltOn:
    value: Decimal
    weights: dict[str, float]
    accounts: list[Account]
    label: str
    bitcoin: Decimal  # the value held in bitcoin, which a bitcoin model can follow

    @property
    def bitcoin_share(self) -> float:
        """Bitcoin's part of the crypto: a bitcoin model drives it, the crypto assumption the
        rest (S6.3.1)."""
        crypto = self.weights.get("crypto", 0) * float(self.value) if self.value > 0 else 0
        return min(1.0, float(self.bitcoin) / crypto) if crypto else 0.0


def built_on(s: Session, user_id: str, spec: dict) -> BuiltOn:
    """Its accounts' current values and their mix by asset class; or a typed amount with the
    mix the projection gives it."""
    kind = spec.get("kind", "typed")
    if kind == "typed":
        amount = Decimal(str(spec.get("amount", 0)))
        mix = spec.get("allocation") or {"usStocks": 60, "bonds": 40}
        total = sum(mix.values()) or 1
        # A what-if names no coins: its crypto is taken as bitcoin, for a bitcoin model.
        crypto = Decimal(str(mix.get("crypto", 0))) / Decimal(str(total))
        return BuiltOn(
            amount,
            {k: v / total for k, v in mix.items()},
            [],
            f"a typed {amount:,.0f}",
            (amount * crypto).quantize(Decimal("0.01")),
        )
    if kind == "portfolio":
        from ..ui.portfolios import seen_accounts

        p, _ = access.portfolio(s, user_id, spec["id"])
        accounts = seen_accounts(s, user_id, p)
        label = f"Portfolio: {p.name}"
    else:
        visible = {a.id: a for a, _ in access.visible_accounts(s, user_id)}
        accounts = [visible[i] for i in spec.get("ids", []) if i in visible]
        label = (
            (accounts[0].name if len(accounts) == 1 else f"{len(accounts)} accounts")
            if accounts
            else "no accounts"
        )
    by_class: dict[str, Decimal] = {}
    btc = Decimal(0)
    for a in accounts:
        ledger = repo.load(s, a)
        investing = atypes.investing(a.type)
        cash = ledger.balance()
        by_class["cash"] = by_class.get("cash", Decimal(0)) + cash
        if not investing:
            continue
        for pos in valuation.positions(s, ledger):
            if pos.value is None:
                continue
            inst = s.get(Instrument, pos.instrumentId)
            cls = asset_class(inst) if inst else None
            if cls is None:
                continue
            by_class[cls] = by_class.get(cls, Decimal(0)) + pos.value
            if cls == "crypto" and inst and BTC.match(inst.symbol or ""):
                btc += pos.value
    value = sum(by_class.values(), Decimal(0))
    positive = {k: v for k, v in by_class.items() if v > 0}
    total = sum(positive.values(), Decimal(0))
    weights = {k: float(v / total) for k, v in positive.items()} if total else {"cash": 1.0}
    return BuiltOn(value, weights, accounts, label, btc)


def _btc_price(s: Session) -> float | None:
    inst = s.scalars(select(Instrument).where(Instrument.symbol.in_(("BTC", "BTC-USD")))).first()
    if inst is None:
        return None
    found = valuation.prices(s, [inst.id]).get(inst.id)
    return float(found.price) if found else None


def people_of(s: Session, owner: User, inputs: dict) -> list[dict]:
    """Retirement's people: those listed, else the owner (and their spouse for a couple)."""
    from .. import people as household

    born = household.birth_year(s, owner.id)
    out = []
    for p in inputs.get("people") or []:
        out.append(
            {
                "name": p.get("name") or "",
                "birthYear": int(p.get("birthYear") or born or 1980),
                "retireAge": int(p.get("retireAge") or 65),
            }
        )
    if not out:
        out.append({"name": owner.displayName, "birthYear": born or 1980, "retireAge": 65})
    return out


@dataclass
class Prepared:
    plan: engine.Plan
    base: BuiltOn
    figures: dict  # the assumptions used, after overrides
    retire_index: int | None
    target_index: int | None
    people: list[dict]
    model: str


def prepare(s: Session, p: Projection, viewer: str) -> Prepared:
    """The model's plan from the projection's inputs, its owner's assumptions and what it is
    built on today."""
    inputs = json.loads(p.inputs or "{}")
    owner = s.get(User, p.ownerId)
    figures = assumptions.load(s, p.ownerId)
    for k, v in (inputs.get("overrides") or {}).get("classes", {}).items():
        if k in figures["classes"]:
            figures["classes"][k].update(v)
    for k in ("inflation",):
        if (inputs.get("overrides") or {}).get(k) is not None:
            figures[k] = inputs["overrides"][k]
    model = inputs.get("bitcoinModel") or figures["bitcoinModel"]
    base = built_on(s, viewer if viewer == p.ownerId else p.ownerId, json.loads(p.builtOn))
    today = clock.today()
    year = today.year
    retire_index = target_index = None
    people = []
    contribution = float(inputs.get("contribution", {}).get("amount", 0) or 0)
    growth = float(inputs.get("contribution", {}).get("growth", 0) or 0) / 100
    if p.goal == "retirement":
        people = people_of(s, owner, inputs)
        horizon = int(inputs.get("horizonAge") or 95)
        youngest = max(x["birthYear"] for x in people)
        years = min(MAX_YEARS, max(2, youngest + horizon - year + 1))
        # The household retires when the last of them does: contributions stop and the
        # withdrawals start then.
        retire_year = max(x["birthYear"] + x["retireAge"] for x in people)
        retire_index = max(1, retire_year - year)
        contribute_years = retire_index - 1 if retire_index > 1 else 0
        income = []
        for item in inputs.get("income") or []:
            who = people[min(int(item.get("person", 0)), len(people) - 1)]
            start = max(1, who["birthYear"] + int(item.get("fromAge", 67)) - year)
            income.append(
                (start, float(item.get("monthly", 0)) * 12, bool(item.get("inflates", True)))
            )
        withdrawal = inputs.get("withdrawal") or {"method": "fourPercent"}
    elif p.goal == "education":
        school = education_school(s, inputs, year)
        target_index = min(school["startIndex"], MAX_YEARS - school["years"])
        years = target_index + school["years"]
        contribution = float(inputs.get("monthly", 0) or 0) * 12
        contribute_years = target_index - 1
        income = []
        withdrawal = {
            "method": "costs",
            "amount": school["cost"],
            "growth": figures["educationInflation"] / 100,
            "years": school["years"],
        }
        retire_index = target_index
        last_part = 1.0
    else:
        target_date = dt.date.fromisoformat(inputs.get("date") or f"{year + 3}-01-01")
        span = max((target_date - today).days, 1) / 365.25
        target_index = max(1, math.ceil(span))
        # The last year counts only up to the date: 1.6 years is a year and 0.6 of one.
        last_part = span - (target_index - 1)
        years = target_index + 1
        contribution = float(inputs.get("monthly", 0) or 0) * 12
        contribute_years = target_index
        income, withdrawal = [], {}
    if p.goal in ("retirement", "education"):
        last_part = 1.0
    btc_now = _btc_price(s) or 100_000.0
    crypto_path = None
    if model not in ("assumption", None) and base.bitcoin > 0:
        prices = bitcoin.median_path(
            model, taxtables.figures(s, year), btc_now, list(range(year, year + years + 1))
        )
        if prices:
            crypto_path = [b / a for a, b in itertools.pairwise(prices)]
    c = figures["classes"]
    plan = engine.Plan(
        start=float(base.value),
        weights=base.weights,
        returns={k: v["return"] / 100 for k, v in c.items()},
        vols={k: v["volatility"] / 100 for k, v in c.items()},
        inflation=figures["inflation"] / 100,
        fees=float(inputs.get("fees", 0.1) or 0) / 100,
        first_year=year,
        years=years,
        contribution=contribution,
        contribution_growth=growth,
        contribute_years=contribute_years,
        last_part=last_part,
        withdraw_from=retire_index,
        withdrawal=withdrawal,
        income=income,
        crypto_path=crypto_path,
        bitcoin_share=base.bitcoin_share,
        runs=int(inputs.get("runs", engine.RUNS)),
        seed=engine.seed_of(p.id, inputs, str(base.value)),
    )
    return Prepared(plan, base, figures, retire_index, target_index, people, model)


def compute(s: Session, p: Projection, viewer: str) -> dict:
    """The fan, the answer and the assumptions in full (S6.9)."""
    prep = prepare(s, p, viewer)
    plan = prep.plan
    result = engine.run(plan)
    inputs = json.loads(p.inputs or "{}")
    out = {
        "years": result.years,
        "percentiles": {str(k): v for k, v in result.percentiles.items()},
        "real": {str(k): v for k, v in result.real.items()},
        "expected": result.expected,
        "start": prep.base.value,  # exact, as the tracking figures are (S6.9)
        "builtOnLabel": prep.base.label,
        "weights": prep.base.weights,
        "assumptions": prep.figures,
        "bitcoinModel": prep.model,
        "bitcoinShare": prep.base.bitcoin_share,
        "runs": plan.runs,
        "seed": plan.seed,
        "scenarios": {},
    }
    if prep.model in ("saylor", "ark") and prep.base.bitcoin > 0:
        out["scenarios"] = engine.scenario_paths(
            plan, prep.model, taxtables.figures(s, plan.first_year), _btc_price(s) or 100_000.0
        )
    if p.goal == "retirement":
        horizon = int(inputs.get("horizonAge") or 95)
        out["answer"] = {
            "kind": "retirement",
            "chance": result.lasted,
            "horizonAge": horizon,
            "atRetirement": result.percentiles[50][min(prep.retire_index, plan.years - 1)],
            "retireYear": plan.first_year + prep.retire_index,
            "people": prep.people,
        }
    elif p.goal == "education":
        out["answer"] = _education_answer(s, p, prep, result, inputs)
    else:
        target = float(inputs.get("target", 0) or 0)
        idx = prep.target_index
        chance = float((result.at[:, idx] >= target).mean()) if target else 1.0
        needed = engine.needed_saving(plan, target, idx) / 12 if target else 0.0
        out["answer"] = {
            "kind": "savings",
            "chance": chance,
            "target": target,
            "date": inputs.get("date"),
            "monthly": float(inputs.get("monthly", 0) or 0),
            "neededMonthly": needed,
        }
    return out


def education_school(s: Session, inputs: dict, year: int) -> dict:
    """The beneficiary and their years of school: from their birth year and the age school
    starts, the years of it, and the cost of a year in today's dollars (typed, or a shipped
    average)."""
    from ..store.entities.education import Person

    who = inputs.get("beneficiary") or {}
    name, birth = "the beneficiary", None
    if who.get("kind") == "user":
        u = s.get(User, who.get("id") or "")
        who = {"kind": "person", "id": u.personId if u else ""}
    if who.get("kind") == "person":
        person = s.get(Person, who.get("id") or "")
        if person is not None:
            name, birth = person.name, person.birthYear
    start_age = int(inputs.get("startAge") or 18)
    first = int(inputs.get("firstYear") or 0) or ((birth or year - 10) + start_age)
    basis = inputs.get("costBasis") or "public"
    if basis in ("public", "private"):
        figure = "collegePublic" if basis == "public" else "collegePrivate"
        cost = float(taxtables.figures(s, year)[figure])
    else:
        cost = float(inputs.get("cost") or 0)
    return {
        "name": name,
        "birthYear": birth,
        "firstYear": first,
        "startIndex": max(1, first - year),
        "years": max(1, int(inputs.get("schoolYears") or 4)),
        "cost": cost,
        "basis": basis,
    }


def _education_answer(s: Session, p: Projection, prep: Prepared, result, inputs: dict) -> dict:
    """The projected balance when school starts against what its years will cost, the
    percentage funded, and the monthly contribution that would fund it fully (S6.2.2)."""
    plan = prep.plan
    school = education_school(s, inputs, plan.first_year)
    start = prep.target_index
    growth = plan.withdrawal["growth"]
    rate = sum(w * plan.returns.get(c, 0.0) for c, w in plan.weights.items()) - plan.fees
    costs = [school["cost"] * (1 + growth) ** t for t in range(start, start + school["years"])]
    # What the years of school are worth at the start, the balance going on growing.
    needed = sum(c / (1 + rate) ** (k + 1) for k, c in enumerate(costs))
    at_start = result.percentiles[50][start - 1]
    funded = min(100.0, at_start / needed * 100) if needed else 100.0
    monthly = 0.0
    if needed and at_start < needed:
        trial = engine.Plan(**{**plan.__dict__, "withdraw_from": None})
        monthly = engine.needed_saving(trial, needed, start - 1, chance=0.5) / 12
    return {
        "kind": "education",
        "name": school["name"],
        "firstYear": school["firstYear"],
        "years": school["years"],
        "costToday": school["cost"],
        "costBasis": school["basis"],
        "costs": costs,
        "atStart": at_start,
        "needed": needed,
        "funded": funded,
        "chance": result.lasted,
        "monthly": float(inputs.get("monthly", 0) or 0),
        "neededMonthly": monthly,
    }


def headline(p: Projection, answer: dict) -> str:
    if answer["kind"] == "education":
        return f"{answer['funded']:.0f}% funded for {answer['name']}'s {answer['years']} years"
    if answer["kind"] == "retirement":
        return f"{answer['chance'] * 100:.0f}% chance the money lasts to {answer['horizonAge']}"
    return f"{answer['chance'] * 100:.0f}% chance of {answer['target']:,.0f} by {answer['date']}"


# ---------- active projections and tracking (S6.7) ----------


def subject(p: Projection) -> str:
    """At most one active projection per subject: the people of a retirement, a savings
    target's own name."""
    inputs = json.loads(p.inputs or "{}")
    if p.goal == "retirement":
        people = sorted(
            str(x.get("birthYear")) + (x.get("name") or "").lower()
            for x in (inputs.get("people") or [{"name": p.ownerId}])
        )
        return f"{p.ownerId}:retirement:{'|'.join(people)}"
    if p.goal == "education":
        who = inputs.get("beneficiary") or {}
        return f"{p.ownerId}:education:{who.get('kind')}:{who.get('id')}"
    return f"{p.ownerId}:{p.goal}:{p.id}"


def make_baseline(result: dict) -> dict:
    return {
        "years": result["years"],
        "p10": result["percentiles"]["10"],
        "p50": result["percentiles"]["50"],
        "p90": result["percentiles"]["90"],
    }


def _on_baseline(base: dict, start: dt.date, day: dt.date) -> tuple[float, float, float]:
    """The baseline's band on a day: between its yearly points, a straight line."""
    t = (day - start).days / 365.25
    i = min(int(t), len(base["p50"]) - 2)
    f = t - i
    at = lambda xs: xs[i] + (xs[i + 1] - xs[i]) * f  # noqa: E731
    return at(base["p10"]), at(base["p50"]), at(base["p90"])


def widened(lo: Decimal, mid: Decimal, hi: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Day-to-day noise isn't a plan going wrong: the band is never narrower than 2% of its
    median either way, a floor on its width, never a margin added to a wide one (S6.7.3)."""
    floor = abs(mid) * SLACK
    return min(lo, mid - floor), mid, max(hi, mid + floor)


def tracking(s: Session, p: Projection, viewer: str, upto: dt.date | None = None) -> dict | None:
    """The actual balance of what it is built on since the baseline, against the band, and
    whether it is on track, ahead or behind (on the last day given: the alert checks it as of
    the end of the last month). A viewer who isn't shared every account it is built on sees
    the status, and the balance of only the accounts shared with them, with no band (S6.1):
    worked out as the server over the owner's accounts."""
    if not p.active or not p.baseline or p.baselineAt is None:
        return None
    with scoping.as_server(s, "a projection's tracking, over its owner's accounts") as srv:
        return _tracking(srv, srv.get(Projection, p.id), viewer, upto)


def _tracking(s: Session, p: Projection, viewer: str, upto: dt.date | None) -> dict | None:
    base = json.loads(p.baseline)
    spec = json.loads(p.builtOn)
    start = p.baselineAt.date()
    today = upto or clock.today()
    points: list[tuple[dt.date, Decimal]] = []
    if spec.get("kind", "typed") == "typed":
        return {"status": "untracked", "points": [], "baseline": base, "since": start.isoformat()}
    on = built_on(s, p.ownerId, spec)
    seen = (
        None
        if viewer == p.ownerId
        else {a.id for a, _ in access.visible_accounts(s, viewer)} & {a.id for a in on.accounts}
    )
    totals: dict[dt.date, Decimal] = {}
    theirs: dict[dt.date, Decimal] = {}
    step = max(1, (today - start).days // 60)
    for a in on.accounts:
        for day, value in valuation.series(
            s, repo.load(s, a), atypes.investing(a.type), start, today, step
        ):
            totals[day] = totals.get(day, Decimal(0)) + value
            if seen is not None and a.id in seen:
                theirs[day] = theirs.get(day, Decimal(0)) + value
    # The actual balances stay exact (S6.9); the band is the model's, to the cent.
    for day in sorted(totals):
        if day >= start:
            points.append((day, totals[day]))
    status = "on track"
    # The baseline grows from the balance the day it was set; prices that arrive later that
    # day move the start, so the band is anchored on the first actual balance.
    first = Decimal(repr(base["p50"][0])) if base["p50"] else Decimal(0)
    scale = points[0][1] / first if points and first > 0 and points[0][1] > 0 else Decimal(1)
    band = []
    for d, _ in points:
        lo, mid, hi = widened(*(Decimal(repr(v)) * scale for v in _on_baseline(base, start, d)))
        band.append((d, lo.quantize(CENTS), mid.quantize(CENTS), hi.quantize(CENTS)))
    if points:
        _, lo, _, hi = band[-1]
        value = points[-1][1]
        status = "behind" if value < lo else "ahead" if value > hi else "on track"
    if seen is not None and len(seen) < len(on.accounts):
        return {
            "status": status,
            "points": [(d.isoformat(), theirs[d]) for d in sorted(theirs) if d >= start],
            "band": [],
            "baseline": base,
            "since": start.isoformat(),
            "partial": True,
        }
    return {
        "status": status,
        "points": [(d.isoformat(), v) for d, v in points],
        "band": [(d.isoformat(), lo, mid, hi) for d, lo, mid, hi in band],
        "baseline": base,
        "since": start.isoformat(),
    }


def visible(s: Session, user_id: str) -> list[tuple[Projection, str]]:
    r = access.reach(s, user_id)
    shared = [i for (k, i) in r.levels if k == "projection"]
    rows = s.scalars(
        select(Projection)
        .where(
            Projection.deleted == false(),
            (Projection.ownerId == user_id) | Projection.id.in_(shared),
        )
        .order_by(Projection.name)
    ).all()
    return [
        (p, lvl)
        for p in rows
        if (lvl := access.level_of(s, user_id, "projection", p.ownerId, p.id, p.deleted, r))
    ]
