"""Generated loan-payment sequences (`worlds.halves`), made through the API (requirements S1.7,
S1.9.3, CR3-22): whatever the path and the order, one real payment is one loan row and one bank
row, paired; two payments are never more than their rows."""

import datetime as dt
from decimal import Decimal

import pytest
from conftest import make_user, sign_in
from edits import change, loan_payment, saved, terms
from test_accounts import add, new_account, upload
from worlds import halves as hw

from moolakata import clock

T0 = dt.datetime(hw.TODAY.year, hw.TODAY.month, hw.TODAY.day, 15, 0, tzinfo=dt.UTC)


def test_the_sequences_meet_every_pair_of_data_shapes():
    worlds = [hw.world(seed) for seed in hw.SEEDS]
    assert not hw.AXES.missing(worlds), hw.AXES.missing(worlds)


def _rows(c, account_id):
    rows = c.get("/ui/api/transactions", params={"pageSize": 1000}).json()["items"]
    return [r for r in rows if r["accountId"] == account_id]


def _bank_side(c, bank: str, seq: hw.Sequence, k: int) -> None:
    if seq.axes["bank"] == "import":
        data = hw.ofx(seq.bank_day, seq.bank_amount, f"p{k}", f"0001234{k:05d}")
        job = upload(c, bank, f"s{k}.ofx", data)
        assert job["state"] == "done", (job.get("error"), job.get("result"))
    else:
        add(c, bank, f"-{seq.bank_amount}", seq.bank_day.isoformat(), payee="ROCKET MORTGAGE")


def _loan_side(c, loan: str, bank: str, seq: hw.Sequence) -> None:
    day, amount = seq.loan_day.isoformat(), str(seq.loan_amount)
    path = seq.axes["loan"]
    if path == "typed":
        add(c, loan, amount, day, kind="deposit", payee="Payment")
        return
    if path == "from":
        # As the dialog does: pair with the bank's half already there, else record both.
        found = c.get(f"/ui/api/accounts/{loan}/loan/halves",
                      params={"account": bank, "date": day,
                              "amount": amount}).json()["items"]  # fmt: skip
        if found:
            r = loan_payment(c, loan, day, amount, transaction=found[0]["transactionId"])
        else:
            r = loan_payment(c, loan, day, amount, from_account=bank)
    else:
        r = loan_payment(c, loan, day, amount)
    assert r.status_code == 200, r.text


def _act_on_candidates(c, loan: str) -> None:
    """The user pairs what *Looks like a payment* offers to pair; a plain Link is a new
    payment of their choosing, which no sequence asks for."""
    for x in c.get(f"/ui/api/accounts/{loan}/loan/candidates").json()["items"]:
        if x["pairWith"]:
            r = change(c, "Txn", x["pairWith"], kind="transfer", transferWithId=x["transactionId"])
            assert r.status_code == 200, r.text


@pytest.mark.parametrize("seed", list(hw.SEEDS), ids=lambda s: f"world{s}")
def test_one_payment_is_one_row_each_side(server, seed):
    check_world(server, seed)


def check_world(server, seed: int) -> None:
    clock.fix(T0)
    try:
        make_user(server, "alice")
        c = sign_in(server, "alice")
        wrong = []
        for k, seq in enumerate(hw.world(seed).sequences):
            bank = new_account(c, name=f"Checking {k}", mask=f"{4000 + k}")["id"]
            add(c, bank, "20000.00", "2026-09-01")
            loan = new_account(c, name=f"Home {k}", type="mortgage", mask=f"{5000 + k}")["id"]
            saved(terms(c, loan, principal="300000", startDate="2026-01-01", termMonths=360,
                        rate="6"))  # fmt: skip
            steps = [
                lambda bank=bank, seq=seq, k=k: _bank_side(c, bank, seq, k),
                lambda loan=loan, bank=bank, seq=seq: _loan_side(c, loan, bank, seq),
            ]
            if seq.axes["order"] == "loan-first":
                steps.reverse()
            for step in steps:
                step()
            _act_on_candidates(c, loan)
            loans = _rows(c, loan)
            banks = [r for r in _rows(c, bank) if Decimal(r["amount"]) < 0]
            if seq.same and seq.axes == {**seq.axes, "bank": "typed", "loan": "from",
                                         "order": "loan-first"}:  # fmt: skip
                # The user typed the bank's half after the dialog recorded it: their own second
                # entry, which the duplicate suspects show (S1.11.5), not one row.
                ok = len(loans) == 1 and len(banks) == 2
            elif seq.same:
                ok = (
                    len(loans) == 1 and len(banks) == 1 and loans[0]["transferId"] == banks[0]["id"]
                )
            else:
                made_half = seq.axes["loan"] == "from"
                ok = len(loans) == 1 and len(banks) == 1 + made_half
            if not ok:
                paired = [r["transferId"] for r in loans]
                wrong.append(f"{seq.axes} days {seq.loan_day}/{seq.bank_day}: {len(loans)} loan "
                             f"rows, {len(banks)} bank debits, paired {paired}")  # fmt: skip
        assert not wrong, "\n".join(wrong)
    finally:
        clock.fix(None)
