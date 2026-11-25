"""Assumptions (requirements S6.3), kept once per user in Profile › Assumptions: expected return
and volatility per asset class, general and education inflation, and the bitcoin model. Every
projection uses them unless it overrides a figure, so a user's projections agree."""

import json

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import ids
from ..store.entities.projections import AssumptionSet

# (key, label, expected return %, volatility %): long-run figures a household might use, not
# a forecast; each user sets their own.
CLASSES = [
    ("usStocks", "US stocks", 7.0, 16.0),
    ("intlStocks", "International stocks", 6.5, 17.0),
    ("bonds", "Bonds", 4.0, 6.0),
    ("cash", "Cash", 3.0, 1.0),
    ("crypto", "Crypto", 8.0, 65.0),
    ("realEstate", "Real estate", 5.0, 12.0),
    ("metals", "Metals", 4.0, 15.0),
]
CLASS_KEYS = [c[0] for c in CLASSES]
BITCOIN_MODELS = [
    ("assumption", "Your assumption (the crypto row)"),
    ("powerLaw", "Power law"),
    ("logRegression", "Log regression"),
    ("stockToFlow", "Stock-to-flow"),
    ("saylor", "Saylor, Bitcoin24 (bear, base, bull)"),
    ("ark", "ARK Invest 2030 (bear, base, bull)"),
]


def defaults() -> dict:
    return {
        "classes": {k: {"return": r, "volatility": v} for k, _, r, v in CLASSES},
        "inflation": 2.5,
        "educationInflation": 5.0,
        "bitcoinModel": "assumption",
    }


def row_of(s: Session, user_id: str) -> AssumptionSet | None:
    """The user's own figures, or None while they keep the shipped ones."""
    return s.scalars(
        select(AssumptionSet).where(
            AssumptionSet.ownerId == user_id, AssumptionSet.deleted == false()
        )
    ).first()


def load(s: Session, user_id: str) -> dict:
    row = row_of(s, user_id)
    out = defaults()
    if row is not None:
        saved = json.loads(row.figures)
        for k, v in saved.get("classes", {}).items():
            if k in out["classes"]:
                out["classes"][k].update(v)
        for k in ("inflation", "educationInflation", "bitcoinModel"):
            if k in saved:
                out[k] = saved[k]
    return out


def save(s: Session, user_id: str, figures: dict) -> None:
    row = row_of(s, user_id)
    text = json.dumps(figures, sort_keys=True)
    if row is None:
        s.add(AssumptionSet(id=ids.new_id("Asmpt"), ownerId=user_id, figures=text))
    else:
        row.figures = text


def _figure(v, lo: float, hi: float) -> bool:
    """A number within its bounds: never a yes or no, NaN or an infinity (R3.11)."""
    return isinstance(v, int | float) and not isinstance(v, bool) and lo <= v <= hi


def check(figures: dict) -> list[tuple[str, str]]:
    """Problems as (field, message): returns from −50% to 100%, volatility 0 to 200%,
    inflation 0 to 20%."""
    problems = []
    for k in CLASS_KEYS:
        c = figures.get("classes", {}).get(k, {})
        r, v = c.get("return"), c.get("volatility")
        if not _figure(r, -50, 100):
            problems.append((f"classes.{k}.return", "Between −50% and 100%."))
        if not _figure(v, 0, 200):
            problems.append((f"classes.{k}.volatility", "Between 0% and 200%."))
    for k in ("inflation", "educationInflation"):
        v = figures.get(k)
        if not _figure(v, 0, 20):
            problems.append((k, "Between 0% and 20%."))
    if figures.get("bitcoinModel") not in [m for m, _ in BITCOIN_MODELS]:
        problems.append(("bitcoinModel", "Choose a model."))
    return problems
