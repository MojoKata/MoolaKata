"""The projection models (requirements S6.4, S6.9): deterministic and Monte Carlo, run on the
server with NumPy, seeded so the same inputs give the same figures, returning percentiles per
year and the goal's answer. A model, not a forecast.

Each year: the balance grows by the mix of its asset classes' returns, less fees; before
retirement (or until the target date) contributions are added, rising each year by their
growth; after retirement the withdrawal is taken, less what other income (Social Security, a
pension) covers. A class's yearly return is drawn log-normal from its expected return and
volatility, independently of the others. The bitcoin in a projection can follow a published
model instead: the model sets its median growth year by year and the crypto volatility spreads
it; a model with bear, base and bull cases gives those three paths in place of a fan.
"""

import hashlib
import itertools
import json
from dataclasses import dataclass, field

import numpy as np

from . import bitcoin

PERCENTILES = (10, 25, 50, 75, 90)
RUNS = 1000


@dataclass
class Plan:
    """What one run of the model needs, every amount in today's dollars, yearly."""

    start: float
    weights: dict[str, float]  # asset class → share of the balance, summing to 1
    returns: dict[str, float]  # expected yearly return, as a fraction
    vols: dict[str, float]
    inflation: float
    fees: float
    first_year: int
    years: int  # how many years to run, the first being this one
    contribution: float = 0.0  # a year, in the first year
    contribution_growth: float = 0.0
    contribute_years: int = 0  # years contributions are made
    # The share of the last of those years that is saved, when saving stops mid-year (school
    # starts on Sep 1): its contribution is that share of a year's.
    contribute_part: float = 1.0
    last_part: float = 1.0  # the share of the last year that counts, for a date mid-year
    withdraw_from: int | None = None  # the year index withdrawals start, if any
    withdrawal: dict = field(default_factory=dict)  # method, amount (a year) or percent
    income: list[tuple[int, float, bool]] = field(
        default_factory=list
    )  # (from index, a year, inflates)
    crypto_path: list[float] | None = None  # yearly growth ratios of a bitcoin model
    bitcoin_share: float = 1.0  # of the crypto, the part the model drives
    runs: int = RUNS
    seed: int = 0


@dataclass
class Result:
    years: list[int]
    percentiles: dict[int, list[float]]  # nominal
    real: dict[int, list[float]]  # in today's dollars
    lasted: float  # share of runs never running out
    final: np.ndarray  # each run's final balance (nominal)
    at: np.ndarray  # runs × years balances (nominal)
    expected: list[float]  # the deterministic path at expected returns


def seed_of(*parts) -> int:
    return int.from_bytes(
        hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).digest()[:4],
        "big",
    )


def _lognormal(rng, mean: float, vol: float, shape) -> np.ndarray:
    """Yearly returns with this arithmetic mean and volatility, never below −100%."""
    if vol <= 0:
        return np.full(shape, mean)
    s2 = np.log(1 + (vol / (1 + mean)) ** 2)
    m = np.log(1 + mean) - s2 / 2
    return np.exp(rng.normal(m, np.sqrt(s2), shape)) - 1


def _returns(plan: Plan, rng, runs: int) -> np.ndarray:
    total = np.zeros((runs, plan.years))
    for cls, w in plan.weights.items():
        if w <= 0:
            continue
        mean, vol = plan.returns.get(cls, 0.0), plan.vols.get(cls, 0.0)
        if cls == "crypto" and plan.crypto_path is not None:
            # The bitcoin: the model's median growth each year, spread by the crypto
            # volatility; other coins keep the crypto assumption (S6.3.1).
            ratios = np.array(plan.crypto_path[: plan.years])
            s2 = np.log(1 + vol**2)
            noise = np.exp(rng.normal(-s2 / 2, np.sqrt(s2), (runs, plan.years)))
            share = plan.bitcoin_share
            drawn = share * (ratios[None, :] * noise - 1)
            if share < 1:
                drawn = drawn + (1 - share) * _lognormal(rng, mean, vol, (runs, plan.years))
        else:
            drawn = _lognormal(rng, mean, vol, (runs, plan.years))
        total += w * drawn
    return total


def _expected_return(plan: Plan) -> np.ndarray:
    out = np.zeros(plan.years)
    for cls, w in plan.weights.items():
        if cls == "crypto" and plan.crypto_path is not None:
            share = plan.bitcoin_share
            model = np.array(plan.crypto_path[: plan.years]) - 1
            out += w * (share * model + (1 - share) * plan.returns.get(cls, 0.0))
        else:
            out += w * plan.returns.get(cls, 0.0)
    return out


def _simulate(plan: Plan, rets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Index 0 is today's balance; index t the balance t years on, after that year's growth,
    fees, contribution and withdrawal."""
    runs = rets.shape[0]
    bal = np.full(runs, plan.start, dtype=float)
    path = np.zeros((runs, plan.years))
    path[:, 0] = bal
    alive = np.ones(runs, dtype=bool) if plan.start > 0 else np.zeros(runs, dtype=bool)
    alive |= plan.contribute_years > 0
    first_withdrawal = None
    for t in range(1, plan.years):
        prices = (1 + plan.inflation) ** t
        part = plan.last_part if t == plan.years - 1 else 1.0
        bal = bal * (1 + rets[:, t] * part) * (1 - plan.fees * part)
        if t <= plan.contribute_years:
            share = part * (plan.contribute_part if t == plan.contribute_years else 1.0)
            bal = bal + plan.contribution * (1 + plan.contribution_growth) ** (t - 1) * share
        if plan.withdraw_from is not None and t >= plan.withdraw_from:
            method = plan.withdrawal.get("method", "fourPercent")
            if method == "costs":
                # An education goal: each year of school's cost, rising with its own
                # inflation, until school ends; whatever is left over stays.
                if t < plan.withdraw_from + int(plan.withdrawal.get("years", 4)):
                    cost = plan.withdrawal["amount"] * (1 + plan.withdrawal["growth"]) ** t
                    bal = bal - cost
                    alive &= bal >= -0.005
                bal = np.maximum(bal, 0.0)
                path[:, t] = bal
                continue
            if method == "percent":
                need = bal * plan.withdrawal.get("percent", 4.0) / 100
            else:
                if first_withdrawal is None:
                    # The 4% rule: 4% of the balance at retirement, then rising with prices.
                    first_withdrawal = (
                        bal * 0.04 / prices
                        if method == "fourPercent"
                        else np.full(runs, float(plan.withdrawal.get("amount", 0.0)))
                    )
                need = first_withdrawal * prices
            income = sum(
                (
                    amt * (prices if inflates else 1)
                    for start, amt, inflates in plan.income
                    if t >= start
                ),
                0.0,
            )
            bal = bal - np.maximum(0, need - income)
            alive &= bal > 0
        bal = np.maximum(bal, 0.0)
        path[:, t] = bal
    return path, alive


def run(plan: Plan) -> Result:
    rng = np.random.default_rng(plan.seed)
    rets = _returns(plan, rng, plan.runs)
    path, alive = _simulate(plan, rets)
    exp_path, _ = _simulate(plan, _expected_return(plan)[None, :].repeat(1, axis=0))
    years = [plan.first_year + t for t in range(plan.years)]
    deflate = np.array([(1 + plan.inflation) ** t for t in range(plan.years)])
    pct = {p: np.percentile(path, p, axis=0).tolist() for p in PERCENTILES}
    real = {p: (np.array(v) / deflate).tolist() for p, v in pct.items()}
    return Result(
        years=years,
        percentiles=pct,
        real=real,
        lasted=float(alive.mean()),
        final=path[:, -1],
        at=path,
        expected=exp_path[0].tolist(),
    )


def scenario_paths(plan: Plan, model: str, figures: dict, btc_now: float) -> dict[str, list]:
    """For a model with bear, base and bull cases: the three paths, each at expected returns
    for everything else."""
    found = bitcoin.scenarios(model, figures)
    if found is None:
        return {}
    year, targets = found
    out = {}
    years = [plan.first_year + t for t in range(plan.years + 1)]
    for name, target in zip(("bear", "base", "bull"), targets, strict=True):
        prices = [bitcoin.toward(btc_now, plan.first_year, target, year, y) for y in years]
        ratios = [b / a for a, b in itertools.pairwise(prices)]
        p = Plan(**{**plan.__dict__, "crypto_path": ratios})
        path, _ = _simulate(p, _expected_return(p)[None, :])
        out[name] = path[0].tolist()
    return out


DOUBLINGS = 40  # how far the search for a saving that is enough goes: 2**40 times the target
PRECISION = 1.0  # a year's saving, to the dollar


def needed_saving(plan: Plan, target: float, at_index: int, chance: float = 0.9) -> float | None:
    """The yearly saving that reaches the target by its date with this chance, to the dollar,
    on a smaller number of runs from the same seed; None when no saving does: a date of today,
    or more than the search goes to (CR3-31). The bound is doubled until it is enough, then
    halved toward the least that is: a bound assumed enough was wrong for a date under a
    year away, where a year's saving counts only its part."""
    if at_index < 1:
        return None  # today's balance: no saving changes it
    trial = Plan(**{**plan.__dict__, "runs": 400})
    rng = np.random.default_rng(plan.seed)
    rets = _returns(trial, rng, trial.runs)

    def reaches(saving: float) -> bool:
        path, _ = _simulate(Plan(**{**trial.__dict__, "contribution": saving}), rets)
        return bool((path[:, at_index] >= target).mean() >= chance)

    if reaches(0.0):
        return 0.0  # so the target is above every balance, and above 0
    lo, hi = 0.0, target
    for _ in range(DOUBLINGS):
        if reaches(hi):
            break
        lo, hi = hi, hi * 2
    else:
        return None
    # No mutant differs: >= halves once more, and hi still reaches it, within the precision.
    while hi - lo > PRECISION:  # pragma: no mutate
        mid = (lo + hi) / 2
        if reaches(mid):
            hi = mid
        else:
            lo = mid
    return hi
