"""Projections at their edges (requirements S6): each input refused at its field (R3.11,
S13.8.3), never an error out of the model."""

import pytest
from conftest import make_user, sign_in
from edits import make
from test_projections import T0

from moolakata import clock


@pytest.fixture
def jane(server):
    clock.fix(T0)
    make_user(server, "jane", born=1979)
    yield sign_in(server, "jane")
    clock.fix(None)


def refused(r, field, code="input-invalid"):
    assert r.status_code == 422, r.text
    assert [(e["field"], e["code"]) for e in r.json()["errors"]] == [(field, code)]


@pytest.mark.parametrize("amount", ["NaN", "inf", "-inf", float("nan"), float("inf"), -1,
                                    1e11, "1e11", "lots", "", True, None])  # fmt: skip
def test_a_typed_amount_is_a_finite_number_in_range(jane, amount):
    """R3.11: a typed amount that isn't a number of 0 or more within its bound is refused at
    its field, never sent on to the model."""
    built = {"kind": "typed", "amount": amount, "allocation": {"usStocks": 100}}
    r = make(jane, "Prjct", name="What if", goal="savings", builtOn=built,
             inputs={"target": 1000, "date": "2028-01-01"})  # fmt: skip
    refused(r, "builtOn.amount", "amount-invalid")


def test_a_typed_amount_of_nothing_its_most_or_a_decimal_is_taken(jane):
    for amount in (0, 1e10, "1000.50"):
        built = {"kind": "typed", "amount": amount, "allocation": {"cash": 100}}
        r = make(jane, "Prjct", name="What if", goal="savings", builtOn=built,
                 inputs={"target": 1000, "date": "2028-01-01"})  # fmt: skip
        assert r.status_code == 200, r.text
