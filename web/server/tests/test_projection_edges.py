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


RETIRE = {"people": [{"name": "Jane", "birthYear": 1979, "retireAge": 62}],
          "income": [{"label": "Pension", "person": 0, "fromAge": 67, "monthly": 900}]}  # fmt: skip
PENSION = {"person": 0, "fromAge": 67, "monthly": 1}
US = "overrides.classes.usStocks"
TYPED = {"kind": "typed", "amount": 500000, "allocation": {"usStocks": 60, "bonds": 40}}


def _retire(c, built=TYPED, **inputs):
    return make(c, "Prjct", name="Retire", goal="retirement", builtOn=built,
                inputs={**RETIRE, **inputs})  # fmt: skip


@pytest.mark.parametrize(
    ("inputs", "field"),
    [
        ({"withdrawal": {"method": "fixed", "amount": "lots"}}, "withdrawal.amount"),
        ({"withdrawal": {"method": "fixed", "amount": None}}, "withdrawal.amount"),
        ({"withdrawal": {"method": "fixed"}}, "withdrawal.amount"),
        ({"withdrawal": {"method": "fixed", "amount": -1}}, "withdrawal.amount"),
        ({"withdrawal": {"method": "percent", "percent": None}}, "withdrawal.percent"),
        ({"withdrawal": {"method": "percent", "percent": 101}}, "withdrawal.percent"),
        ({"withdrawal": "fourPercent"}, "withdrawal"),
        ({"overrides": {"inflation": "x"}}, "overrides.inflation"),
        ({"overrides": {"inflation": 21}}, "overrides.inflation"),
        ({"overrides": {"classes": {"usStocks": {"return": None}}}}, f"{US}.return"),
        ({"overrides": {"classes": {"usStocks": {"volatility": -1}}}}, f"{US}.volatility"),
        ({"overrides": {"classes": {"usStocks": {"growth": 1}}}}, f"{US}.growth"),
        ({"overrides": {"classes": {"usStocks": 7}}}, US),
        ({"overrides": {"classes": {"gold": {"return": 5}}}}, "overrides.classes.gold"),
        ({"overrides": {"taxes": 5}}, "overrides.taxes"),
        ({"overrides": []}, "overrides"),
        ({"income": [{"person": "x", "fromAge": 67, "monthly": 1}]}, "income.0.person"),
        ({"income": [{"person": 1, "fromAge": 67, "monthly": 1}]}, "income.0.person"),
        ({"income": [{"person": 0, "fromAge": None, "monthly": 1}]}, "income.0.fromAge"),
        ({"income": [{"person": 0, "fromAge": 67, "monthly": None}]}, "income.0.monthly"),
        ({"income": [{**PENSION, "inflates": "no"}]}, "income.0.inflates"),
        ({"income": [{**PENSION, "label": 5}]}, "income.0.label"),
        ({"income": ["pension"]}, "income.0"),
        ({"people": ["Jane"]}, "people.0"),
        ({"people": [{"name": 5, "birthYear": 1979}]}, "people.0.name"),
        ({"contribution": None}, "contribution"),
        ({"contribution": 3000}, "contribution"),
        ({"runs": None}, "runs"),
        ({"bitcoinModel": "moon"}, "bitcoinModel"),
    ],
)  # fmt: skip
def test_every_input_the_model_reads_is_checked_at_its_field(jane, inputs, field):
    """S13.8.3, R3.11: an input the model reads that isn't of its kind and range is refused
    at its field, never a server error."""
    refused(_retire(jane, **inputs), f"inputs.{field}")


def test_a_target_date_that_isnt_text_is_refused(jane):
    r = make(jane, "Prjct", name="Car", goal="savings", builtOn=TYPED,
             inputs={"target": 1000, "date": 20280101})  # fmt: skip
    refused(r, "inputs.date", "date-invalid")


@pytest.mark.parametrize(
    "allocation",
    [{"usStocks": 300, "cash": -200}, {"usStocks": "60"}, {"usStocks": float("nan")},
     {"gold": 100}, {"usStocks": 0}, {}, [60, 40], "60/40", {"usStocks": 101}],
)  # fmt: skip
def test_a_typed_mix_is_shares_of_the_classes_never_levered(jane, allocation):
    """S6.4.2.2: a typed amount gives its own mix, each class's share 0 to 100, some of it
    held: never a negative share that levers another."""
    refused(_retire(jane, {**TYPED, "allocation": allocation}), "builtOn.allocation",
            "allocation-invalid")  # fmt: skip


@pytest.mark.parametrize("built", [{"kind": "accounts", "ids": 5},
                                   {"kind": "accounts", "ids": [{"id": "x"}]},
                                   {"kind": "portfolio", "id": 5}])  # fmt: skip
def test_what_it_is_built_on_names_ids(jane, built):
    r = _retire(jane, built)
    assert r.status_code == 422, r.text
    assert [e["field"] for e in r.json()["errors"]] == ["builtOn"]


def test_the_inputs_the_form_sends_are_taken(jane):
    r = _retire(jane, withdrawal={"method": "fixed", "amount": 60000},
                overrides={"inflation": 3, "classes": {"bonds": {"return": 3.5}}},
                bitcoinModel="", contribution={"amount": None, "growth": None})  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["result"]["assumptions"]["inflation"] == 3
    r = _retire(jane, {**TYPED, "allocation": {"usStocks": 100, "cash": 0}},
                withdrawal={"method": "percent"}, bitcoinModel="stockToFlow")  # fmt: skip
    assert r.status_code == 200, r.text
