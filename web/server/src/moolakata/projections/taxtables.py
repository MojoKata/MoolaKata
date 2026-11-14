"""The tax tables (requirements S16.11): per year, figures that ship with MoolaKata and are
updated with it, which an admin can correct in Settings › Tax Tables if the IRS changes one
before an update. Projections take contribution limits and the bitcoin models' published
figures from here; taxes, 529s and giving take the rest as they are built.

Each figure has a kind, which says how it is checked and shown: money (dollars), percent,
number, or a list of numbers (the bitcoin models' parameters and targets).
"""

import json
from dataclasses import dataclass

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from .. import clock
from ..store.entities.projections import TaxFigure


@dataclass(frozen=True)
class Figure:
    key: str
    label: str
    kind: str  # money, percent, number, numbers
    group: str
    source: str


FIGURES = [
    Figure("iraLimit", "IRA contribution limit", "money", "Retirement", "IRS"),
    Figure("iraCatchUp", "IRA catch-up (50+)", "money", "Retirement", "IRS"),
    Figure("k401Deferral", "401(k) employee deferral", "money", "Retirement", "IRS"),
    Figure("k401CatchUp", "401(k) catch-up (50–59, 64+)", "money", "Retirement", "IRS"),
    Figure("k401CatchUp6063", "401(k) catch-up (60–63)", "money", "Retirement", "IRS"),
    Figure("hsaSelf", "HSA, self-only", "money", "Retirement", "IRS"),
    Figure("hsaFamily", "HSA, family", "money", "Retirement", "IRS"),
    Figure("hsaCatchUp", "HSA catch-up (55+)", "money", "Retirement", "IRS"),
    Figure("rmdAge", "RMD starting age", "number", "Retirement", "IRS"),
    Figure("giftExclusion", "Annual gift exclusion", "money", "Gifts and giving", "IRS"),
    Figure("rothFrom529", "529 to Roth IRA, lifetime", "money", "Gifts and giving", "IRS"),
    Figure("qcdLimit", "QCD limit", "money", "Gifts and giving", "IRS"),
    Figure("collectablesRate", "Collectables rate (max)", "percent", "Taxes", "IRS"),
    # A dependent child's unearned income above which Form 8615 applies (S8.14.5.3).
    Figure("form8615Threshold", "Form 8615 unearned income", "money", "Taxes", "IRS"),
    # The federal return's due date in the following year: month and day (S8.15.3).
    Figure("federalDue", "Federal return due (month, day)", "numbers", "Taxes", "IRS"),
    # A year of college, tuition, fees, room and board, for the education goal (S6.2.2).
    Figure(
        "collegePublic",
        "College a year, public four-year (in-state)",
        "money",
        "Education",
        "NCES Digest of Education Statistics, table 330.10",
    ),
    Figure(
        "collegePrivate",
        "College a year, private nonprofit four-year",
        "money",
        "Education",
        "NCES Digest of Education Statistics, table 330.10",
    ),
    # Metal spot from the trusts' share prices (S4.3): troy ounces each share holds, which
    # falls a little each year by the trust's fee.
    Figure("slvOzPerShare", "Silver per SLV share (troy oz)", "number", "Metal spot", "iShares"),
    Figure("ppltOzPerShare", "Platinum per PPLT share (troy oz)", "number", "Metal spot", "abrdn"),
    Figure("pallOzPerShare", "Palladium per PALL share (troy oz)", "number", "Metal spot", "abrdn"),
    Figure(
        "btcPowerLaw",
        "Bitcoin power law (A, n)",
        "numbers",
        "Bitcoin models",
        "Santostasi's fit: price = A × days since the genesis block ^ n",
    ),
    Figure(
        "btcLogRegression",
        "Bitcoin log regression (a, b)",
        "numbers",
        "Bitcoin models",
        "the rainbow chart's curve: log10(price) = a × ln(days) − b",
    ),
    Figure(
        "btcStockToFlow",
        "Bitcoin stock-to-flow (a, b)",
        "numbers",
        "Bitcoin models",
        "PlanB (2019): market value = e^a × SF^b",
    ),
    Figure(
        "btcSaylor2045",
        "Saylor 2045 (bear, base, bull)",
        "numbers",
        "Bitcoin models",
        "Michael Saylor, Bitcoin24 (2024)",
    ),
    Figure(
        "btcArk2030",
        "ARK 2030 (bear, base, bull)",
        "numbers",
        "Bitcoin models",
        "ARK Invest, Big Ideas (2025)",
    ),
]
BY_KEY = {f.key: f for f in FIGURES}

_BTC = {
    "btcPowerLaw": [1e-17, 5.8],
    "btcLogRegression": [2.66167155, 17.91837619],
    "btcStockToFlow": [14.6, 3.3],
    "btcSaylor2045": [3_000_000, 13_000_000, 49_000_000],
    "btcArk2030": [500_000, 1_200_000, 2_400_000],
}

# The figures of a tax year, for every year a tax book may cover (ten back, S8.14): the IRS's
# limits and thresholds as they were. 2019's and 2020's returns were due on the postponed
# dates; the 60-63 catch-up starts in 2025 (before, it is the usual one); a 529 rolled over to
# a Roth from 2024; the RMD age was 70½ until 2019.
_PAST = (
    # year, IRA, catch-up, 401(k), catch-up, 60-63, HSA self, family, RMD age, gift
    # exclusion, 529 to Roth, QCD, Form 8615, federal due
    (2016, 5500, 1000, 18000, 6000, 6000, 3350, 6750, 70.5, 14000, 0, 100000, 2100, [4, 15]),
    (2017, 5500, 1000, 18000, 6000, 6000, 3400, 6750, 70.5, 14000, 0, 100000, 2100, [4, 15]),
    (2018, 5500, 1000, 18500, 6000, 6000, 3450, 6900, 70.5, 15000, 0, 100000, 2100, [4, 15]),
    (2019, 6000, 1000, 19000, 6000, 6000, 3500, 7000, 70.5, 15000, 0, 100000, 2200, [7, 15]),
    (2020, 6000, 1000, 19500, 6500, 6500, 3550, 7100, 72, 15000, 0, 100000, 2200, [5, 17]),
    (2021, 6000, 1000, 19500, 6500, 6500, 3600, 7200, 72, 15000, 0, 100000, 2200, [4, 15]),
    (2022, 6000, 1000, 20500, 6500, 6500, 3650, 7300, 72, 16000, 0, 100000, 2300, [4, 15]),
    (2023, 6500, 1000, 22500, 7500, 7500, 3850, 7750, 73, 17000, 0, 100000, 2500, [4, 15]),
    (2024, 7000, 1000, 23000, 7500, 7500, 4150, 8300, 73, 18000, 35000, 105000, 2600, [4, 15]),
)
_KEYS = (
    "iraLimit",
    "iraCatchUp",
    "k401Deferral",
    "k401CatchUp",
    "k401CatchUp6063",
    "hsaSelf",
    "hsaFamily",
    "rmdAge",
    "giftExclusion",
    "rothFrom529",
    "qcdLimit",
    "form8615Threshold",
    "federalDue",
)

SHIPPED: dict[int, dict] = {
    # The HSA catch-up at 55 is the statute's $1,000, not indexed (IRC §223(b)(3)).
    **{
        row[0]: {
            **dict(zip(_KEYS, row[1:], strict=True)),
            "collectablesRate": 28,
            "hsaCatchUp": 1000,
        }
        for row in _PAST
    },
    2025: {
        "iraLimit": 7000,
        "iraCatchUp": 1000,
        "k401Deferral": 23500,
        "k401CatchUp": 7500,
        "k401CatchUp6063": 11250,
        "hsaSelf": 4300,
        "hsaFamily": 8550,
        "hsaCatchUp": 1000,
        "rmdAge": 73,
        "giftExclusion": 19000,
        "rothFrom529": 35000,
        "qcdLimit": 108000,
        "collectablesRate": 28,
        "form8615Threshold": 2700,
        "federalDue": [4, 15],
        "collegePublic": 26000,
        "collegePrivate": 58000,
        "slvOzPerShare": 0.8634,
        "ppltOzPerShare": 0.0915,
        "pallOzPerShare": 0.0915,
        **_BTC,
    },
    2026: {
        "iraLimit": 7500,
        "iraCatchUp": 1100,
        "k401Deferral": 24500,
        "k401CatchUp": 8000,
        "k401CatchUp6063": 11250,
        "hsaSelf": 4400,
        "hsaFamily": 8750,
        "hsaCatchUp": 1000,
        "rmdAge": 73,
        "giftExclusion": 19000,
        "rothFrom529": 35000,
        "qcdLimit": 111000,
        "collectablesRate": 28,
        "form8615Threshold": 2700,
        "federalDue": [4, 15],
        "collegePublic": 27100,
        "collegePrivate": 60300,
        "slvOzPerShare": 0.8591,
        "ppltOzPerShare": 0.0909,
        "pallOzPerShare": 0.0909,
        **_BTC,
    },
}


def years() -> list[int]:
    return sorted(SHIPPED)


def _year(year: int) -> int:
    """A year the tables don't reach yet uses the latest one shipped."""
    known = years()
    return year if year in SHIPPED else (known[-1] if year > known[-1] else known[0])


def of_year(year: int) -> list[Figure]:
    """The figures a year ships: a past tax year has its tax figures only; the college costs,
    the metal per share and the bitcoin models start with the years that use them."""
    return [f for f in FIGURES if f.key in SHIPPED[_year(year)]]


def figures(s: Session, year: int | None = None) -> dict[str, object]:
    """A year's figures, with any admin's corrections. A figure a past year doesn't ship (one
    only today's figures need) is the earliest year's that has it."""
    y = _year(year or clock.today().year)
    out = {
        **{k: v for later in sorted(SHIPPED, reverse=True) for k, v in SHIPPED[later].items()},
        **SHIPPED[y],
    }
    for row in s.scalars(
        select(TaxFigure).where(TaxFigure.year == y, TaxFigure.deleted == false())
    ):
        if row.key in BY_KEY:
            out[row.key] = json.loads(row.value)
    return out


def corrected(s: Session, year: int) -> set[str]:
    return {
        r.key
        for r in s.scalars(
            select(TaxFigure).where(TaxFigure.year == year, TaxFigure.deleted == false())
        )
    }


class Invalid(ValueError):
    pass


def check(key: str, value) -> object:
    f = BY_KEY.get(key)
    if f is None:
        raise Invalid("there is no such figure")
    if f.kind == "numbers":
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
        ):
            raise Invalid("numbers separated by commas")
        if len(value) != len(_BTC.get(key, value)):
            raise Invalid(f"{len(_BTC[key])} numbers")
        return value
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise Invalid("a number, zero or more")
    if f.kind == "percent" and value > 100:
        raise Invalid("a percentage up to 100")
    return value
