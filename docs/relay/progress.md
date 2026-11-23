# Relay progress: settling H1.9's mutation survivors

13 batches, 877 survivors and 31 no-tests changes, from the fork's CI runs 44963061557 and
44989210873 (mutmut on `af202cf5`): batches 1–4 `loans/__init__.py` and `loans/payoff.py`,
5–11 `ui/loans.py`, 12–13 `assets/__init__.py` and `ui/items.py`. One agent at a time; the
coordinator checks each batch before the next starts.

## Batch 1

File: `web/server/tests/test_loans_edges.py` (new; 12 tests, each under 0.1 s but the first's
session setup).

Counts (85): killed 66, bug 2, equivalent 17, remove 0, slow 0, process only 0, still left 0.

### Bug

- `moolakata.loans.x_history__mutmut_47` (`t.amount < 0` → `<= 0`, a row of 0.00 read as a
  draw of nothing). S1.9.3: Automatic counts only an amount above 0 as a payment (`modes`,
  `history`'s `paid`), but `history` puts a row of 0.00 among the payments: it is split by the
  schedule as a paid row of nothing, covers its payment day and, recorded here, starts the
  record. Input: a 300,000 mortgage from 2026-01-01 at 6%, Automatic, one row of 0.00 on
  2026-03-01, today 2026-10-13. Output: March has a paid row of 0.00 and no payment assumed,
  so the balance stays a month's principal above the schedule. With the change, March is
  assumed. Doubt: whether a row of nothing is meant to be a payment; if it is, Automatic is
  the one that's wrong (it should read recorded here), and this is still a bug, at `paid`.

  ```python
  def test_a_row_of_nothing_is_no_payment(book):
      # S1.9.3: assumed as scheduled, a payment day whose only row is 0.00 has none recorded.
      s, uid = book
      a = _account(s, uid)
      _loan(s, a)
      _txn(s, a, d(2026, 3, 1), "0.00")
      pays = L.history(s, a, d(2026, 10, 13))[0]
      assert [p.date.month for p in pays if p.assumed] == list(range(2, 11))
      assert all(p.transactionId is None for p in pays)
  ```

- `moolakata.loans.x_history__mutmut_106` (`automatic(paid, None)`: the connection ignored).
  With no payment above 0, recorded here and assumed as scheduled read alike unless a row of
  0.00 starts the record (the question above): it is killed only by a test that pins that.
  If a row of nothing is no payment, this is an equivalent; if it is one, the test is:

  ```python
  def test_a_connected_loans_record_starts_at_its_first_row(book):
      s, uid = book
      a = _account(s, uid)
      _loan(s, a)
      _txn(s, a, d(2026, 3, 1), "0.00")
      linked = dataclasses.replace(a, connectionId="Cnctn_x")
      pays = L.history(s, linked, d(2026, 10, 13))[0]
      assert not [p for p in pays if p.assumed and p.date > d(2026, 3, 31)]
  ```

### Equivalent

- `moolakata.loans.x_loan_of__mutmut_5`: `Loan.deleted == false()`, a filter the access view also applies.
- `moolakata.loans.x_modes__mutmut_7`: `Transaction.deleted == false()`, a filter the access view also applies.
- `moolakata.loans.x_history__mutmut_13`: `Transaction.deleted == false()`, a filter the access view also applies.
- `moolakata.loans.x_history__mutmut_23`: `Split.deleted == false()`, a filter the access view also applies.
- `moolakata.loans.x_history__mutmut_22`: every live split read, each kept under its own transaction's id; only this loan's are looked up (it costs a read of the household's splits, no output).
- `moolakata.loans.x_history__mutmut_67`: `keys.get(…, None)`: any default that isn't a part's category falls to principal, as "" does.
- `moolakata.loans.x_history__mutmut_69`: `keys.get(…)`, a default of None: the same.
- `moolakata.loans.x_history__mutmut_72`: `keys.get(…, "XXXX")`: the same.
- `moolakata.loans.x_history__mutmut_71`: `categoryId or "XXXX"`: no category's id is "" or "XXXX", so both miss and fall to principal.
- `moolakata.loans.x_settle__mutmut_6`: `covered` worked out with no days assumed too; it is read only when they are.
- `moolakata.loans.x_settle__mutmut_9`: `catch_up=None` is as falsy as `False`.
- `moolakata.loans.x_settle__mutmut_17`: a recorded payment covers the day whose date it is on, so no assumed one ever shares its date: the kind never breaks a tie.
- `moolakata.loans.x_settle__mutmut_32`: the same, assumed at kind 2.
- `moolakata.loans.x_settle__mutmut_89`: given a walker, `split_for` reads `draws` only to build one.
- `moolakata.loans.x_settle__mutmut_92`: given a walker, `split_for` reads `catch_up` only to build one.
- `moolakata.loans.x_settle__mutmut_93`: with no walker, `split_for` builds the same walk again from the payments before (the record's start the same first real payment): slower, the same split.
- `moolakata.loans.x_settle__mutmut_100`: the same as 93.

### Batch check

`web/dev.sh mutate run moolakata/loans/__init__.py` on the batch's 85 names, with `tests/test_loans_edges.py` added (log `web/.dev/relay-h19/batch-1.log`, exit 0): 66 killed, 19 survived, the 19 listed above and no others. No test was dropped as failing in the copy.

### Doubts

1. The two bugs are one question: is a row of 0.00 on a loan a payment? Automatic says no;
   the split, the covered day and the record's start say yes.
2. The four deleted-row filters (`loan_of_5`, `modes_7`, `history_13`, `history_23`) are
   listed as equivalents, as the doc says, though a test in an unscoped session (as server
   work reads) would kill each.
3. `modes_16` is killed with a connected copy of the account that isn't saved
   (`dataclasses.replace(a, connectionId=…)`), to need no Connection row.
