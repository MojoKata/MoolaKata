"""Whether a traditional IRA contribution is deductible (requirements S8.6): a nullable boolean
on the contribution, or on each of its parts, null until decided; on nothing else."""

import datetime as dt

import pytest
from conftest import make_user, sign_in
from edits import change, make, saved
from test_accounts import add, new_account

from moolakata import clock

T0 = dt.datetime(2026, 10, 24, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def ann(server):
    clock.fix(T0)
    make_user(server, "ann")
    yield sign_in(server, "ann")
    clock.fix(None)


def _refused(r, code: str) -> None:
    assert r.status_code == 422, r.text
    (e,) = r.json()["errors"]
    assert (e["field"], e["code"]) == ("deductible", code)


def test_a_contribution_is_undecided_until_marked_and_keeps_its_mark(ann):
    ira = new_account(ann, name="IRA", type="ira")["id"]
    t = add(ann, ira, "7000.00", "2026-01-10", kind="deposit")
    assert t["deductible"] is None
    assert saved(change(ann, "Txn", t, deductible=False))["deductible"] is False
    got = ann.get(f"/ui/api/transactions/{t['id']}").json()
    assert got["deductible"] is False


@pytest.mark.parametrize(
    "type_, fields",
    [
        ("checking", {}),  # not a retirement account
        ("roth-ira", {}),  # a Roth contribution is never deducted
        ("ira", {"contributionSource": "rollover"}),  # money moved, not contributed
        ("ira", {"contributionSource": "employer"}),
    ],
)
def test_a_mark_on_anything_but_ones_own_traditional_ira_contribution_is_refused(
    ann, type_, fields
):
    acct = new_account(ann, name="Acct", type=type_)["id"]
    r = make(ann, "Txn", accountId=acct, date="2026-01-10", kind="deposit", amount="7000.00",
             deductible=True, **fields)  # fmt: skip
    _refused(r, "deductible-not-a-contribution")


def test_a_withdrawal_from_an_ira_is_not_deductible_or_not(ann):
    ira = new_account(ann, name="IRA", type="ira")["id"]
    r = make(ann, "Txn", accountId=ira, date="2026-01-10", kind="withdrawal",
             amount="-100.00", deductible=False)  # fmt: skip
    _refused(r, "deductible-not-a-contribution")


def test_a_split_contribution_is_marked_part_by_part(ann):
    """A contribution partly deductible (S8.6): 3,000 deducted and 4,000 not, each part with
    its own mark; with parts, the contribution itself carries none."""
    ira = new_account(ann, name="IRA", type="ira")["id"]
    parts = [{"amount": "3000.00", "deductible": True}, {"amount": "4000.00", "deductible": False}]
    r = make(ann, "Txn", accountId=ira, date="2026-01-10", kind="deposit", amount="7000.00",
             splits=parts)  # fmt: skip
    assert r.status_code == 200, r.text
    got = ann.get(f"/ui/api/transactions/{r.json()['id']}").json()
    assert sorted((x["amount"], x["deductible"]) for x in got["splits"]) == [
        ("3000.00", True), ("4000.00", False)]  # fmt: skip
    r = make(ann, "Txn", accountId=ira, date="2026-01-11", kind="deposit", amount="7000.00",
             deductible=False, splits=parts)  # fmt: skip
    _refused(r, "deductible-on-parts")


def test_a_part_of_a_checking_deposit_is_not_deductible_or_not(ann):
    bank = new_account(ann, name="Bank", type="checking")["id"]
    parts = [{"amount": "60.00", "deductible": False}, {"amount": "40.00"}]
    r = make(ann, "Txn", accountId=bank, date="2026-01-10", kind="deposit", amount="100.00",
             splits=parts)  # fmt: skip
    _refused(r, "deductible-not-a-contribution")


def test_a_contribution_moved_in_from_the_bank_is_marked(server, ann):
    """A contribution made as a transfer from a bank account is the owner's own (S8.6)."""
    bank = new_account(ann, name="Bank", type="checking")["id"]
    ira = new_account(ann, name="IRA", type="ira")["id"]
    out = add(ann, bank, "-7000.00", "2026-01-10", kind="transfer")
    r = make(ann, "Txn", accountId=ira, date="2026-01-10", kind="transfer", amount="7000.00",
             transferWithId=out["id"], deductible=False)  # fmt: skip
    assert r.status_code == 200, r.text
