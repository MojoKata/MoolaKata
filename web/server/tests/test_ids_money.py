import uuid
from decimal import Decimal

import pytest

from moolakata import ids, money


def test_ids_have_the_schema_form_and_sort_by_time():
    made = [ids.new_id("Txn") for _ in range(5000)]
    assert made == sorted(made)
    assert len(set(made)) == len(made)
    for i in made[:50]:
        assert len(i) == len("Txn_") + 26
        assert ids.is_id(i, "Txn")
        assert ids.decode(i[4:]).version == 7


def test_encoding_matches_the_schema_example():
    u = uuid.UUID("0199d4b2-6f3a-7c21-9b4e-5a1d3c8e7f02")
    assert ids.encode(u) == "01k7ab4vstfggspkjt3my8wzr2"
    assert ids.decode("01k7ab4vstfggspkjt3my8wzr2") == u


@pytest.mark.parametrize(
    "bad",
    [
        "01K7AB4VSTFGGSPKJT3MY8WZR2",
        "01k7ab4vstfggspkjt3my8wzri",
        "01k7ab4vstfggspkjt3my8wzrl",
        "01k7ab4vstfggspkjt3my8wzro",
        "01k7ab4vstfggspkjt3my8wzru",
        "81k7ab4vstfggspkjt3my8wzr2",
        "01k7ab4vst",
    ],
)
def test_each_id_has_exactly_one_spelling(bad):
    with pytest.raises(ValueError):
        ids.decode(bad)


def test_amounts_refuse_floats_and_excess_places():
    assert money.parse("1234.50") == Decimal("1234.50")
    for bad in (1.5, True, None, "abc", "NaN", "Infinity"):
        with pytest.raises(money.AmountError):
            money.parse(bad)
    with pytest.raises(money.AmountError, match="2 decimal places"):
        money.parse("1.005", places=2)


def test_cents_round_half_even():
    assert money.to_cents(Decimal("0.125")) == 12
    assert money.to_cents(Decimal("0.135")) == 14
    assert money.cents_str(123450) == "1234.50"
    assert money.cents_str(-5) == "-0.05"
    assert money.quantity_str(Decimal("12.500000000000000000")) == "12.5"
    assert money.quantity_str(Decimal("1E+2")) == "100"


@pytest.mark.parametrize("d", ["-0", "-0.00", "-0.004", "-0.005", "0", "0.004"])
def test_an_amount_that_rounds_to_zero_is_written_without_a_sign(d):
    """A short option worth nothing is worth 0.00, never -0.00: in the API, the exports and
    every sentence or printed form (CR3-436)."""
    from moolakata import exactjson
    from moolakata.taxes import exports
    from moolakata.ui import conventions

    assert money.money_str(Decimal(d)) == "0.00"
    assert money.grouped(Decimal(d)) == "0.00"
    assert exactjson.dumps([conventions._money_out(Decimal(d))]) == "[0.00]"
    assert exports._money(Decimal(d)) == "0.00"


def test_a_written_amount_keeps_its_sign_and_groups_its_thousands():
    assert money.money_str(Decimal("-0.006")) == "-0.01"
    assert money.grouped(Decimal("-1234.5")) == "-1,234.50"
    assert money.grouped(Decimal("1234567.891")) == "1,234,567.89"
