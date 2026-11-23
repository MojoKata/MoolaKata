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

## Batch 3

File: `web/server/tests/test_loans_edges.py` (13 tests added, one parametrized; each under
0.01 s).

Counts (56): killed 32, bug 7, equivalent 6, remove 11, slow 0, process only 0, still left 0.

### Bug

- `moolakata.loans.x_schedule__mutmut_35` and `moolakata.loans.x_schedule__mutmut_40` (the
  walk's `settled` dropped, so `_walk` starts the record at `_record_starts`). The same
  question as batch 2's doubt 1 (`_walk_1`, `_walk_2`): they differ only when the first payment
  recorded here is dated after today, and then they give batch 2's test its answer (Apr 5's
  row an overpayment of 500, as its split has it). Batch 2's test is the one to write:
  `test_a_second_payment_toward_a_day_ahead_is_an_overpayment_in_the_schedule_too`.
- `moolakata.loans.x_schedule__mutmut_174` and `moolakata.loans.x_schedule__mutmut_178`
  (`owed` read from every payment, not those to today). S1.9.2: the schedule ahead starts
  after the last day paid (`max(paid) + 1`), a payment dated after today counted, but from
  today's balance, which leaves that payment's principal out: the first row ahead repeats it.
  Input: 300,000 at 6% from 2026-01-01, assumed as scheduled, today 2026-02-10, a payment of
  1,798.65 dated 2026-03-01. Output: Mar 1 (paid) leaves 299,401.21; Apr 1 (ahead) pays 300.14
  of principal and leaves 299,401.21 again. The changes start from 299,401.21 (Apr 1 pays
  301.64, leaves 299,099.57). Doubt: whether a payment dated after today is meant to count
  (the same question as batch 2's).

  ```python
  def test_ahead_the_balance_counts_a_payment_dated_ahead_whose_day_it_paid():
      t = _mortgage()
      rows = L.schedule(t, [(d(2026, 3, 1), L.scheduled_payment(t), "a")], [], d(2026, 2, 10))
      mar, apr = rows[1:3]
      assert apr.balance == mar.balance - apr.principal
  ```

- `moolakata.loans.x_schedule__mutmut_184` (`previous` taking a row on the first day ahead).
  S1.9.1: a daily-interest loan accrues simple interest between payments. Recorded here,
  March missed, a payment on Apr 1 pays March (catching up) and has paid the interest to Apr 1;
  today Apr 1,
  April is the first day ahead, but its interest is counted from Feb 1's payment again: 59
  days, 189.32, on 19,519.81. The change gives 0 days, 0. Input: 20,000 at 6% daily from
  2026-01-01 over 60 months, payments of 386.66 on 2026-02-01 and 2026-04-01, today
  2026-04-01. Doubt: only a catch-up payment dated on the first day ahead reaches it.

  ```python
  def test_a_daily_interest_day_ahead_accrues_from_a_payment_made_that_day():
      t = L.Terms(principal=D(20000), start=d(2026, 1, 1), months=60, rate=D(6), method="daily")
      pi = L.scheduled_payment(t)
      recorded = [(d(2026, 2, 1), pi, "a"), (d(2026, 4, 1), pi, "b")]
      rows = L.schedule(t, recorded, [], d(2026, 4, 1), mode="recorded")
      apr = [r for r in rows if not r.past][0]
      assert (apr.date, apr.interest) == (d(2026, 4, 1), 0)
  ```

- `moolakata.loans.x_schedule__mutmut_201` and `moolakata.loans.x_schedule__mutmut_203` (the
  level on the first day ahead, when that day works it out again, from what was owed the day
  before rather than today). S1.9.2: on such a day the level "becomes what pays off the
  balance then owed". Recorded here, the first day ahead can be one passed, in its grace; a
  draw since then is in today's balance, so the row ahead's level counts it, while the split
  of the payment once made (`_Walker.look`, from `_owed_before(e)`) doesn't. Input: a HELOC of
  24 months at 12% from 2026-01-01, drawn 10,000 on Feb 10, 1,000 on Mar 20 (in repayment, so
  Apr 1 re-levels) and 5,000 on Apr 3; Mar 1 paid 488.86; today Apr 10. Output: Apr 1 ahead
  is 794.04 of principal and interest (15,611.14 over 22); paid on Apr 12, its split's level is
  539.72 (10,611.14 over 22). The changes give 539.72. Doubt: which balance the screen's
  payment due next should level from while that day is in its grace.

  ```python
  def test_ahead_a_day_in_its_grace_that_re_levels_has_the_level_its_payment_is_split_by():
      t = L.Terms(principal=D(0), start=d(2026, 1, 1), months=24, rate=D(12), drawMonths=2)
      level = L.level_payment(D(10000), D(12), 23)
      draws = [(d(2026, 2, 10), D(10000)), (d(2026, 3, 20), D(1000)), (d(2026, 4, 3), D(5000))]
      rows = L.schedule(t, [(d(2026, 3, 1), level, "a")], draws, d(2026, 4, 10), mode="recorded")
      apr = [r for r in rows if not r.past][0]
      assert apr.principal + apr.interest == L.level_payment(D("10611.14"), D(12), 22)
  ```

### Equivalent

- `moolakata.loans.x_schedule__mutmut_44`: `zip(…, strict=None)`: `walked` is built one per payment, so the lengths always match.
- `moolakata.loans.x_schedule__mutmut_47`: the same, `strict` left out.
- `moolakata.loans.x_schedule__mutmut_48`: the same, `strict=False`.
- `moolakata.loans.x_schedule__mutmut_132`: not recorded here, `paid` holds every day before today (`settled` is today), so `max(paid) + 1` is never below the loop's `k`: the grace (or none) can't move it.
- `moolakata.loans.x_schedule__mutmut_134`: the same, a day for none.
- `moolakata.loans.x_schedule__mutmut_212`: `balance_on(…, e - 1)` leaves a payment on `e` out anyway.

### Remove

- `moolakata.loans.x_schedule__mutmut_216`: `first` can't matter: on the first day ahead, a day that works the level out again gives `_level_on` (`e == day`, `owed`) the same `_level_at(t, day, owed)` the loop would.
- `moolakata.loans.x_schedule__mutmut_217`: the same.
- `moolakata.loans.x_schedule__mutmut_238`: the same (`None` is as falsy as `False`).
- `moolakata.loans.x_schedule__mutmut_219`: the 1,200-row guard restates the term's end: the term is 1 to 600 months (S1.9.1, refused past it in `ui/loans.py`) and a row on or after the end takes all that is owed, so the loop ends within 600 rounds.
- `moolakata.loans.x_schedule__mutmut_223`: the same.
- `moolakata.loans.x_schedule__mutmut_224`: the same.
- `moolakata.loans.x_schedule__mutmut_225`: the same.
- `moolakata.loans.x_schedule__mutmut_226`: the same.
- `moolakata.loans.x_schedule__mutmut_227`: the same.
- `moolakata.loans.x_schedule__mutmut_341`: the date check past `t.end + 600` months can't end a loop that wouldn't end anyway: its day is past the end only after a row on or after the end, which left nothing owed.
- `moolakata.loans.x_schedule__mutmut_346`: the same.

### Batch check

`web/dev.sh mutate run moolakata/loans/__init__.py` on the batch's 56 names, with
`tests/test_loans_edges.py` added (log `web/.dev/relay-h19/batch-3.log`, exit 0): 32 killed,
24 survived, the 24 listed above and no others. No test was dropped as failing in the copy.

### Doubts

1. Three of the bugs turn on payments or draws dated after today, or a first day ahead still
   in its grace (`schedule_35`/`_40` with batch 2's doubt 1, `_174`/`_178`, `_201`/`_203`): the
   schedule ahead reads today's balance where the splits read the balance on the day.
2. `first` (`_216`, `_217`, `_238`) is listed as Remove only while `_201`/`_203` stand: if the
   first day ahead levels from what was owed the day before, `first` is what keeps the loop
   from levelling it again from today's balance, and its survivors need a test then.
3. `_effects_3` is killed reading S1.9.2's "a fee or charge added to what is owed being one" as
   a HELOC draw in its repayment period (the code's reading): a charge on a mortgage leaves its
   level payment. If a mortgage's charge is meant to re-level too, that test is wrong.
4. `schedule_347` (`break` → `return`) is killed by a loan whose term ended in 1970 with a
   charge in 2025; it stays passing if the date check (`_341`, `_346`) is removed.
5. The tests call `paid_off`, `due_on` and `schedule` directly; none calls a private helper.

## Batch 4

File: `web/server/tests/test_loans_edges.py` (13 tests added, one parametrized; each under
0.01 s; `payoff` imported at the top as `P`).

Counts (60): killed 54, bug 1, equivalent 3, remove 2, slow 0, process only 0, still left 0.

### Bug

- `moolakata.loans.x__missed__mutmut_20` (`p.date <= day` for a missed day's `since`).
  S1.9.1: a daily-interest loan accrues simple interest between payments. Recorded here, March
  missed, a payment on Apr 1 pays March (catching up), its split taking the interest from
  Feb 1 to Apr 1; April, missed, has its interest counted from Feb 1 again: 59 days, 191.21,
  the same interest twice. The change accrues it from Apr 1's payment: 0. Input: 20,000 at 6%
  daily from 2026-01-01 over 60 months, payments of 386.66 on 2026-02-01 and 2026-04-01, today
  2026-04-20. The same question as batch 3's `schedule_184` (the first day ahead), here for a
  day missed. Doubt: only a catch-up payment dated on a later missed day reaches it.

  ```python
  def test_recorded_here_a_daily_interest_day_missed_accrues_from_a_payment_made_that_day():
      t = L.Terms(principal=D(20000), start=d(2026, 1, 1), months=60, rate=D(6), method="daily")
      pi = L.scheduled_payment(t)
      recorded = [(d(2026, 2, 1), pi, "a"), (d(2026, 4, 1), pi, "b")]
      rows = L.schedule(t, recorded, [], d(2026, 4, 20), mode="recorded")
      [apr] = [r for r in rows if r.status == "missed"]
      assert (apr.date, apr.interest) == (d(2026, 4, 1), 0)
  ```

### Equivalent

- `moolakata.loans.x__missed__mutmut_6`: day 1 is never missed: the record starts at the first payment recorded, which pays day 1 when the record starts there (a later start settles it, and before Feb 1 any payment toward a later day catches it up first).
- `moolakata.loans.x__missed__mutmut_16`: a missed day always comes after the first payment recorded (its grace ends before the next payment day), so `since` always has a date and its default is never read.
- `moolakata.loans.x__missed__mutmut_18`: the same, the default left out.

### Remove

- `moolakata.loans.x_summary__mutmut_54`: `owed > 0` restates `ahead`: the schedule has rows ahead only while the balance today, read from the same payments, is above 0.
- `moolakata.loans.x_summary__mutmut_55`: the same (`>= 0`).

### Batch check

`web/dev.sh mutate run moolakata/loans/__init__.py moolakata/loans/payoff.py` on the batch's
60 names, with `tests/test_loans_edges.py` added (log `web/.dev/relay-h19/batch-4.log`, exit
0): 54 killed, 6 survived, the 6 listed above and no others. No test was dropped as failing in
the copy.

### Doubts

1. `summary_16`, `_22`, `_23` (its own `settle`'s `catch_up`) are killed by calling `summary`
   with payments as (date, amount, id) to split, as `settle` and `schedule` take them. The
   server passes `history`'s payments, already settled the same way, so there that `settle` adds
   and splits nothing: if `summary` is meant to take only settled payments, its `settle` is a
   Remove and the test `test_recorded_here_the_summary_splits_a_late_payment_as_paying_the_day_missed`
   goes with it.
2. `summary_117`, `_121`, `_125`, `_130`, `_134` (sums with no `ZERO` start) are killed reading
   R1.9 (amounts are `Decimal` in Python): an empty sum gave int 0. The API's `Money` would turn
   either into the same "0", so if R1.9 is read as the API's output only, they are equivalents.
3. `_missed_4` (day 0 looked at) is killed with a HELOC drawn before its start date (a
   withdrawal on the account dated before the loan's start): the only shape that has anything
   owed the day before the start.
4. `expected_extra_41`/`_42` need a daily-interest loan with PMI on the 78% bound and a
   round-up (the only place the plan reads the balance left); one parametrized test, one value
   each side of the bound.
5. The tests call `due_on`, `schedule`, `summary`, `split_new`, `settle`, `plan_outcomes` and
   `expected_extra` directly; none calls a private helper.

## Batch 5

File: `web/server/tests/test_loans_routes.py` (new; 12 tests, one parametrized; two through
the API, under 0.7 s each with the app's first start; the rest call `ui.loans.view` in an
unscoped session, each under 0.2 s).

Counts (70): killed 63, bug 0, equivalent 7, remove 0, slow 0, process only 0, still left 0.

### Equivalent

- `moolakata.ui.loans.x_view__mutmut_69`: `loans.history(s, a, None)` reads None as `clock.today()`, which is `view`'s `today`.
- `moolakata.ui.loans.x_view__mutmut_72`: the same, `today` left out.
- `moolakata.ui.loans.x_view__mutmut_91`: `Anchor.deleted == false()`, a filter the access view also applies.
- `moolakata.ui.loans.x__equity__mutmut_18`: `assets.spots(…, None)`: `valuation.prices` reads None as `clock.today()`, which is `view`'s `today`.
- `moolakata.ui.loans.x__equity__mutmut_23`: `it.metal or "XXXX"` differs only for an item with no metal, which is never at spot (the table's check), and `spots` holds only spot items' metals: neither "" nor "XXXX" is a key.
- `moolakata.ui.loans.x__equity__mutmut_41`: `Loan.deleted == false()`, a filter the access view also applies; unscoped too, a deleted loan's account values at 0 (`loans.value` reads only its live loan, and a loan's terms are never deleted alone).
- `moolakata.ui.loans.x__equity__mutmut_52`: `sum(…)` with no start is int 0 when no other loan is on the item, and `owed + 0` is the same Decimal.

### Batch check

`web/dev.sh mutate run moolakata/ui/loans.py` on the batch's 70 names, with
`tests/test_loans_routes.py` added (log `web/.dev/relay-h19/batch-5.log`, exit 0): 63 killed,
7 survived, the 7 listed above and no others. No test was dropped as failing in the copy.

### Doubts

1. `_account_7`/`_11` (the permission asked for dropped) are killed through `follow_plan` by a
   reader of a loan shared at Read (S10.4): 403 `share-read-only`.
2. `_equity_14`–`_33` (spot) are killed by a personal loan secured by gold at spot: `_terms`
   lets any item secure a loan, though S1.9.5 names a home. If only a property or vehicle may
   secure one, the metal branch can't be reached through the API and those are Remove.
3. Two deleted-row filters (`view_91`, `_equity_41`) are listed as equivalents, as the doc
   says; the servicer test leaves out a deleted anchor on purpose, which would kill `view_91`
   in the unscoped session.
4. The view tests make rows directly (`Loan`, `Item`, `Anchor`, `TypedPrice`) in the unscoped
   session and call `view`; the PMI bounds' original values (372,347.30 and 368,635.50) are
   picked so 80% and 78% fall exactly on a row's balance.
