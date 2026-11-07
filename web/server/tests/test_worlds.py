"""The generated worlds see the bugs they are there for (requirements S17.5): each world runs
under each bug it names (`PLANTS`), put back on purpose, and must fail. A world that passes
with a bug planted has stopped reaching the data shape that shows it."""

import pytest
import test_account_world
import test_budget_world
import test_option_world
import test_tax_moves_world
import test_tax_world
from worlds import accounts, budget, catches, options, tax, tax_moves

WORLDS = {
    "account": (accounts.PLANTS, test_account_world.check_world),
    "option": (options.PLANTS, test_option_world.check_world),
    "budget": (budget.PLANTS, test_budget_world.check_world),
    "tax": (tax.PLANTS, test_tax_world.check_world),
    "tax-moves": (tax_moves.PLANTS, test_tax_moves_world.check_world),
}

GAPS = {"budget": budget.GAPS}


def _marks(name, plant):
    why = GAPS.get(name, {}).get(plant.name)
    return [pytest.mark.xfail(strict=True, reason=why)] if why else []


CASES = [
    pytest.param(name, plant, seed, id=f"{name} {seed}: {plant.name}", marks=_marks(name, plant))
    for name, (plants, _) in WORLDS.items()
    for plant, seeds in plants
    for seed in seeds
]


@pytest.mark.parametrize(("name", "plant", "seed"), CASES)
def test_worlds_catch_their_plants(server, name, plant, seed):
    check = WORLDS[name][1]
    assert catches(lambda: check(server, seed), plant), (
        f"{name} world {seed} passes with {plant.name!r} planted ({plant.why})"
    )
