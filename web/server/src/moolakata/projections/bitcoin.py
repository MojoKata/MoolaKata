"""Bitcoin models (requirements S6.3.1): published models of bitcoin's price, each a median path
from today's price and a range around it. These are models other people publish, shown for
comparison, not MoolaKata's view and not advice (R1.16). Their figures come from the tax
tables, dated, and are corrected there.
"""

import datetime as dt
import itertools
import math

GENESIS = dt.date(2009, 1, 3)
HALVING_2024 = 2024
BLOCKS_A_YEAR = 52_560
SUPPLY_2026 = 19.95e6

RECORDS = {
    "assumption": "Log-normal at your crypto return and volatility.",
    "powerLaw": "A fit to the price history; its spread is about a factor of two either way. It "
    "describes the past and says nothing about why it should continue.",
    "logRegression": "The rainbow chart's curve, fitted to the price history; its bands run from "
    "the fitted lows to the fitted tops.",
    "stockToFlow": "Value from the ratio of supply to new issuance, stepping up at each halving. "
    "It has run below its own band since 2022.",
    "saylor": "Bear, base and bull targets for 2045 by Michael Saylor, who holds bitcoin.",
    "ark": "Bear, base and bull targets for 2030 by ARK Invest, which holds bitcoin.",
}


def days_since_genesis(year: int) -> int:
    return (dt.date(year, 7, 1) - GENESIS).days


def power_law(year: int, f: dict) -> float:
    a, n = f["btcPowerLaw"]
    return a * days_since_genesis(year) ** n


def log_regression(year: int, f: dict) -> float:
    a, b = f["btcLogRegression"]
    return 10 ** (a * math.log(days_since_genesis(year)) - b)


def stock_to_flow(year: int, f: dict) -> float:
    a, b = f["btcStockToFlow"]
    supply = min(21e6, SUPPLY_2026 + (year - 2026) * 0.15e6)
    flow = 3.125 * BLOCKS_A_YEAR / 2 ** ((year - HALVING_2024) // 4)
    return math.exp(a) * (supply / flow) ** b / supply


def toward(now: float, now_year: int, target: float, target_year: int, year: int) -> float | None:
    """A straight line on a log scale from today's price to a target; None after the target's
    year, of which the target says nothing (S6.3.1.6)."""
    if year > target_year:
        return None
    span = max(1, target_year - now_year)
    rate = (target / now) ** (1 / span)
    return now * rate ** (year - now_year)


def scenarios(model: str, f: dict) -> tuple[int, list[float]] | None:
    """A model's bear, base and bull targets with their year, for those that give them."""
    if model == "saylor":
        return 2045, f["btcSaylor2045"]
    if model == "ark":
        return 2030, f["btcArk2030"]
    return None


def median_path(model: str, f: dict, now: float, years: list[int]) -> list[float | None] | None:
    """The model's price for each year, starting from today's; None for "your assumption". A
    target's model has no price after its target year (S6.3.1.6)."""
    if model == "powerLaw":
        curve = [power_law(y, f) for y in years]
    elif model == "logRegression":
        curve = [log_regression(y, f) for y in years]
    elif model == "stockToFlow":
        curve = [stock_to_flow(y, f) for y in years]
    elif (found := scenarios(model, f)) is not None:
        year, (_, base, _) = found
        return [toward(now, years[0], base, year, y) for y in years]
    else:
        return None
    # From today's price: the model's growth year by year, not a jump to its curve.
    out = [now]
    for prev, cur in itertools.pairwise(curve):
        out.append(out[-1] * cur / prev)
    return out


def _rounded(p: float | None) -> int | None:
    return None if p is None else round(p)


def compare(f: dict, now: float, today: dt.date) -> list[dict]:
    """Every model's figures for 2030, 2035 and 2045, and its median path, for Compare: a
    target's path stops at its year, and its figures after it are None (S6.3.1.6)."""
    years = list(range(today.year, 2046))
    rows = []
    for key, path in (
        ("powerLaw", median_path("powerLaw", f, now, years)),
        ("logRegression", median_path("logRegression", f, now, years)),
        ("stockToFlow", median_path("stockToFlow", f, now, years)),
        ("saylor", median_path("saylor", f, now, years)),
        ("ark", median_path("ark", f, now, years)),
    ):
        rows.append(
            {
                "model": key,
                "path": [(y, round(p)) for y, p in zip(years, path, strict=True) if p is not None],
                "at": {y: _rounded(path[years.index(y)]) for y in (2030, 2035, 2045)},
                "record": RECORDS[key],
            }
        )
    return rows
