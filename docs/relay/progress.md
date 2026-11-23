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

## Batch 2

File: `web/server/tests/test_loans_edges.py` (13 tests added, two parametrized; each under
0.01 s).

Counts (81): killed 47, bug 6, equivalent 12, remove 16, slow 0, process only 0, still left 0.

### Bug

- `moolakata.loans.x__owed_before__mutmut_8` (the principal counted as owed before the loan
  started). S1.9.3: after a day's interest, escrow and PMI, "the rest is principal". A payment
  dated on the loan's start day has nothing owed the day before, so `split_for` files it all
  as fees and the balance doesn't fall. Input: 300,000 at 6% from 2026-01-01, a payment of 500
  on 2026-01-01. Output: interest 0, principal 0, fees 500. The change gives 500 of interest
  instead, which is not right either. Doubt: whether a payment on (or before) the start day
  is meant to be possible; nothing refuses one. The test, if it is principal:

  ```python
  def test_a_payment_on_the_day_the_loan_starts_pays_principal():
      p = L.split_for(_mortgage(), [], [], d(2026, 1, 1), D(500))
      assert (p.interest, p.principal, p.fees) == (0, D(500), 0)
  ```

- `moolakata.loans.x__walk__mutmut_1` and `moolakata.loans.x__walk__mutmut_2` (the walk's record start from `_record_starts`,
  recorded here). S1.9.3: the record starts at the first payment recorded's day. `settle`
  splits with the record starting there (`start`), but `schedule` walks the same payments with
  it starting at `min(until, today)`. They differ only when that first payment is dated after
  today: its day is ahead, the walk then reads it as paying the day before it (caught up), and
  a second payment toward the same day shows no overpayment, though its split made it all
  principal beyond the schedule. Input: 300,000 at 6% from 2026-01-01, recorded here, today
  2026-02-10, payments of 1,798.65 on 2026-04-01 and 500 on 2026-04-05. Output: the Apr 5 row's
  overpayment is 0 (its split's is 500). The changes make the walk start where the split does,
  and give 500. Doubt: whether a payment dated ahead of today is meant to count this way.

  ```python
  def test_a_second_payment_toward_a_day_ahead_is_an_overpayment_in_the_schedule_too():
      t = _mortgage()
      rec = [(d(2026, 4, 1), L.scheduled_payment(t), "a"), (d(2026, 4, 5), D(500), "b")]
      rows = L.schedule(t, rec, [], d(2026, 2, 10), mode="recorded")
      assert [r.overpayment for r in rows if r.status == "paid"] == [0, D(500)]
  ```

- `moolakata.loans.xǁ_Walkerǁ__init____mutmut_12`, `moolakata.loans.xǁ_Walkerǁ__init____mutmut_19`,
  `moolakata.loans.xǁ_Walkerǁ__init____mutmut_23` (the oldest day not paid starting
  one day later, at a payment day, or on odd days). In `settle` and `split_for` the walker's
  `settled` is the record's start, and the first payment recorded always pays that day, so the
  oldest day not paid ends up the same: equivalent there. Through `schedule` (`settled` =
  `min(until, today)`) they differ only in the case above, a first payment dated after today
  (19: today a payment day, as 2026-03-01 with payments on Apr 1 and Apr 5; 23: today
  2026-04-10, payments on May 20 and May 25; 12: today 2026-01-20, payments of 1,798.65 on
  Mar 20 and Mar 25 and 500 on Mar 28): each gives the last payment's row an overpayment of 500
  where the code gives 0, as the split does. Doubt: equivalents once the walk starts the record
  where the split does; until then, killed only by a test pinning that case one way or the
  other.

### Equivalent

- `moolakata.loans.x_day_of__mutmut_12`: starting a month lower, the loop steps past it: that day's grace has always passed by a day two months on.
- `moolakata.loans.x__days_paid__mutmut_24`: with `low == k`, `k = low` changes nothing.
- `moolakata.loans.xǁ_Walkerǁ_day_for__mutmut_9`: the same, in the walker.
- `moolakata.loans.x__record_starts__mutmut_4`: `split_for` always passes the new payment, recorded, so `real` is never empty; `_walk`'s call is never reached (below).
- `moolakata.loans.x__owed_before__mutmut_13`: `sum(…)` with no start is 0 when empty, and a Decimal plus 0 is the same Decimal.
- `moolakata.loans.x_balance_on__mutmut_12`: the same.
- `moolakata.loans.x_balance_on__mutmut_19`: the same.
- `moolakata.loans.x__due__mutmut_2`: a payment on the day itself is in `prior`, but `balance_on(…, day - 1)` and the level's `p.date < e` (e ≤ day) leave it out.
- `moolakata.loans.x__due__mutmut_54`: `balance_on(…, e - 1)` leaves a payment on `e` out anyway.
- `moolakata.loans.x_split_for__mutmut_11`: the new payment's amount is never read (`look` and `_record_starts` read its date and `assumed`).
- `moolakata.loans.x_split_for__mutmut_17`: the record's start is read only for catching up, which needs `catch_up`.
- `moolakata.loans.x_split_for__mutmut_91`: with `rest == 0` the short branch's `min`s change nothing and principal is 0 either way.

### Remove

- `moolakata.loans.x__days_paid__mutmut_25`: the grace clause restates `low < k`: `day_of` gives the first day whose grace hasn't passed, so every day before it has.
- `moolakata.loans.x__days_paid__mutmut_30`: the same.
- `moolakata.loans.xǁ_Walkerǁ_day_for__mutmut_10`: the same, in the walker.
- `moolakata.loans.xǁ_Walkerǁ_day_for__mutmut_15`: the same.
- `moolakata.loans.x__days_paid__mutmut_32`: the list of days each payment pays is never read: `_covered`, its one caller, keeps only the set.
- `moolakata.loans.xǁ_Walkerǁ__init____mutmut_20`: the settled days need not be in `covered`: `low` starts past them and only rises, so they are never looked up.
- `moolakata.loans.xǁ_Walkerǁadd__mutmut_8`: a daily-interest loan's `_Day.interest` is never read (`split_for` works its interest from the days since the last payment), so the `method == "daily"` branch can't matter.
- `moolakata.loans.xǁ_Walkerǁadd__mutmut_11`: the same.
- `moolakata.loans.xǁ_Walkerǁadd__mutmut_12`: the same.
- `moolakata.loans.xǁ_Walkerǁadd__mutmut_32`: `_Day.owed` is never read.
- `moolakata.loans.x__walk__mutmut_3`: `_walk`'s one caller, `schedule`, always passes `settled`, so its `if catch_up and settled is None` branch is never reached.
- `moolakata.loans.x__walk__mutmut_4`: the same.
- `moolakata.loans.x__walk__mutmut_5`: the same.
- `moolakata.loans.x__walk__mutmut_6`: the same.
- `moolakata.loans.x__walk__mutmut_7`: the same.
- `moolakata.loans.x__due__mutmut_84`: the row's balance from `_due` is never read: `_as_scheduled` doesn't read it and `_missed` sets it again.

### Batch check

`web/dev.sh mutate run moolakata/loans/__init__.py` on the batch's 81 names, with
`tests/test_loans_edges.py` added (log `web/.dev/relay-h19/batch-2.log`, exit 0): 47 killed,
34 survived, the 34 listed above and no others. No test was dropped as failing in the copy.

### Doubts

1. The bug on the walks is one question: does a first payment recorded here, dated after
   today, start the record at its day (as `settle` reads it) or at today (as `schedule`'s walk
   and `_covered` read it)? `_walk_1`, `_walk_2` and `__init___12`, `_19`, `_23` all turn on it.
2. A payment on the loan's start day is filed as fees (`_owed_before_8`): a bug, or a case
   nothing should make?
3. Not a survivor of this batch, found writing the tests: `_Walker.add` sets a day's scheduled
   principal from its first payment's interest (`_scheduled_principal(t, owed, p.interest, …)`),
   so a first payment short of the interest makes the day's scheduled principal too large and
   hides a later overpayment. 300,000 at 6% from 2026-01-01, payments of 1,000 and 1,298.65 on
   2026-02-01: the second's overpayment is 0, though 500 of principal is beyond the 298.65 due
   (paying 1,500 then 798.65 gives 500). S1.9.3. The test that fails on the code:

   ```python
   def test_a_first_payment_short_of_the_interest_leaves_the_days_principal_as_scheduled():
       t = _mortgage()
       rec = [(d(2026, 2, 1), D(1000), None), (d(2026, 2, 1), D("1298.65"), None)]
       out = L.settle(t, rec, [], d(2026, 2, 10), None)
       assert [p.overpayment for p in out] == [0, D(500)]
   ```

4. The tests call `split_for`, `settle`, `schedule`, `day_of` and `balance_on` directly; none
   calls a private helper.
