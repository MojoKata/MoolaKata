# Code review 3, unit 05: budgets-gifts-giving

**Session:** Oct 24, 08:53 PM to 09:10 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S7 (budgets: what a budget counts S7.1–S7.3, its screens S7.4, recurring S7.5,
  budget alerts S7.6 and the cash-before-payday alert, gift plans and occasions S7.7, gifts
  S7.8, charitable giving S7.9, reserves S7.10, moves S7.11, the active budget and scenarios
  S7.12, envelope budgets and card payment lines S7.13, the month's review S7.14), with the
  README lines they rely on (R1.8 sharing, R1.9 money in cents, R3.4 a share never passed on,
  R3.10 a deleted thing kept by name).
- **Code (9,973 lines, 26 files):** `src/budgets/` (`__init__` 691, `cache` 88, `envelope`
  190, `plan` 228, `recurring` 115, `reserves` 226); `src/gifts/` (`__init__` 445,
  `holidays` 85); `src/giving/__init__.py` 287; `mig/0028`, `0031`–`0036` (the budget tables);
  `src/store/entities/budgets.py`, `giving.py`; `src/store/tables/budgets.py`, `giving.py`;
  `src/ui/budgets.py` 1,665, `gifts.py` 880, `giving.py` 703; `ui/screens/budgets.js` 1,800,
  `gifts.js` 881, `giving.js` 809. The cash-before-payday alert's logic lives in
  `src/alerts.py` (unit 09's file), judged here.
- **Tests (1,680 lines):** `test_budget_plan.py`, `test_budgets.py`, `test_envelope.py`,
  `test_gifts.py`, `test_giving.py`, `test_moves.py`, `test_reserves.py`, `test_review.py`,
  `test_scenarios.py`; golden file `tests/golden/budgets-2026.txt` (evidence of what the
  code produces).
- **Guides:** `budgets-*.md` (list, month, cash-flow, compare, recurring, reimbursements,
  review, trends, where), `gifts-*.md`, `giving-*.md`, and the dialogs these screens open
  (`dialog-budget`, `-budget-settings`, `-category`, `-move`, `-make-active`, `-plan`,
  `-estimate`, `-gift`, `-giving-plan`, `-donation`, `-organisation`, and any other found).
- **Cites no section:** `store/entities/budgets.py`, `store/entities/giving.py` (entity
  classes for the tables; judged when read).
- Shared with earlier units, not raised again: U03-7 (an edit of a split transaction orphans
  its paybacks, `ui/transactions.py`), U02-7 (a split loan payment always in the shipped
  categories, `LOAN_PARTS`), U02-15 (a loan payment recorded and then linked counts twice).

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 5,367 lines (53%); 15 new files. The budgets code is new whole:
`budgets/__init__.py` (691, the old 372-line module replaced), `cache.py`, `envelope.py`,
`plan.py`, `reserves.py`, migrations 0028 and 0031–0036, `store/tables/budgets.py` and
`entities/budgets.py`, `ui/budgets.py` (1,665) and `screens/budgets.js` (1,407 added). This
is milestone 10, never reviewed: read most carefully.

The moved files' changes (renames aside; diff in the job's `tmp/u05/delta-gifts.diff`) are
review 2's fixes:
- `gifts/__init__.py`: the gift-tax flag counts every 529 of the user's, plan or not, and a
  five-year election a fifth a year (B16).
- `giving/__init__.py`: `givers()` returns the owner alone (P2).
- `store/tables/giving.py`: amounts in `Cents` (B23).
- `ui/gifts.py`: a person's `sameAs` remote users to join (S10.10.1); `_paid` names an
  account not shared (P6); linking a gift's purchase needs write and is recorded (P7);
  `receipts.to_attach` (P3).
- `ui/giving.py`: a donated lot's term by `long_term(heldFrom or acquiredOn)` (B22); the
  owner's typed prices; a donation recorded in the plan the caller writes to; `to_attach` (P3).
- `screens/gifts.js`, `giving.js`: `thisYear()`, the *Join them* notice.

### 3. Earlier reviews' findings in this area

Review 1 has none in S7. Review 2's, all marked done (§12.2) or built in milestone 9:

| Id | What | State per review 2 | Re-checked here |
|---|---|---|---|
| P2 | a giving plan read every holder's money | done (`313e27e`) | holds: `giving.givers` returns the owner alone (`giving/__init__.py:60-65`); see U05-16 for what a write receiver can then do |
| P3 | attaching a receipt needed read only (gifts, giving) | done | holds: `receipts.to_attach` in `ui/gifts.py:737` and `ui/giving.py:690` |
| P6 | budget recurring rows carried the owner's account id and name to viewers and links; gift `paid.accountName` | built in m9 (`ce12371`) | half holds: recurring rows and gifts are done; the new envelope card lines and reserve rows name or id the same accounts (U05-25) |
| P7 | linking a gift's cost needed read, unrecorded | done | holds: write on the account, `gift.purchase-linked` in Activity (`ui/gifts.py:585-590, 632-646`) |
| P8 | Activity missed receivers of gift and giving plans | done | not re-checked (unit 07's Activity) |
| B16 | gift-tax flag missed 529s without a plan and five-year elections | done | holds (`gifts/__init__.py:371-391`); U02-11 already covers an election above five exclusions |
| B22 | donated shares' term by `acquiredOn`, not `heldFrom` | built in m9 (`6847ba9`) | holds (`ui/giving.py:468`) |
| B23 | `BudgetLine.amount` decimal text | built in m9 | holds: `Cents` (`store/tables/budgets.py:53`, `giving.py`) |
| C39 | a budget re-shared a read-shared account | done, decided (S7.1.1) | half holds: the month's figures follow the viewer (`budgets.account_ids`), but a review's stored figures pass such an account on (U05-21) |
| C48 | donated shares under a year: lesser of value and basis | done | holds in code (`ui/giving.py:522`); the donation guide still says *basis* (U05-23) |
| N13 | receipts on gifts and donations through `ReceiptLink` | done | holds (`ui/gifts.py:738-747`, `ui/giving.py:691-700`) |
| N14 | QCD checks | later (L7) | not raised (§3.6) |

### 4. Phase 1 claims and decisions on these sections

- **D1-2** (Low): budget alerts go "to its owner" while the active budget may be a receiver's
  (S7.6 vs S7.12.5). Judged against both readings in the claims.
- **D1-4** (Low): S7.6.2's *(later)* threshold alerts have no L id: not raised as not built.
- **D1-13** (Med, needs the user, open): who owns a category and who may change one (S7.2,
  S7.12.6, S10.3.1, S14.10.1.1). Judged against the readings: what the category routes do.
- **D1-23** (Low): no shortfall state in the mockup (S7.10.4).
- **D1-24** (Low): gift status *received* in the mockup, not S7.8.1.
- docs-compare row 3: D1-13 shared with unit 06 (retention).
- No §6 gate decision on S7.

### 5. Untraced candidates and uncited first-level items

- `store/entities/budgets.py`, `store/entities/giving.py` (cite nothing; entity classes).
- **S7.6** (budget alerts) is cited by no code: judged against `alerts.py`'s
  cash-before-payday alert.

## Claims

Kinds and format per docs/REVIEW.md §7. Severity, confirmations and status are in the work
pad table at the end.

### U05-1: spending paid straight from the account reserves are held in asks to move the same amount out of it again

- **Kind:** wrong figure. **Req:** S7.10.4 ("when they are behind, after a repair paid from
  checking or a card, it goes back to it … when they agree, the account is **backed**").
- **Code:** `web/server/src/moolakata/budgets/reserves.py:124-126`, *to move* is the reserves'
  balance less what was transferred in from the budget's accounts and the landed money given:
  ```text
  @property
  def toMove(self) -> Decimal:
      return self.total - self.movedIn - self.given
  ```
  and `moved_in` (`:180-187`) counts only transfers whose other half is in the budget's other
  accounts. Spending in a reserve's category lowers `total` wherever it is paid from, so a
  payment made from the held-in account itself lowers `total` while nothing lowers `movedIn`.
- **What goes wrong:** Case (run): a *Roof* reserve of $500 a month, target $5,000, held in Ally
  Savings; November's and December's $500 moved in from Checking: total $1,000, moved in
  $1,000, *backed*. The roofer is paid $700 straight from Ally. Ally now holds $300, the
  reserve $300: the account is backed, yet *Where the money is* says **$700 to move from Ally
  Savings to Checking** (`toMove` −700.00). Doing it leaves Ally $700 short of the reserve, and
  counts a withdrawal against the limit. The guide and S7.10.4 name only repairs paid from
  checking or a card, where the code is right.
- **Run:** yes, `tmp/u05/t/test_u05.py::test_spending_from_the_held_in_account_asks_to_move_it_back`:
  before `1000.00 1000.00 0.00`, after `300.00 1000.00 -700.00` with balance `300.00`
  (`tmp/u05/run1.txt`).
- **Remedy:** count money leaving the held-in account other than by a transfer to the budget's
  accounts (spending paid from it) as moved out: `moved_in` less every outflow of the account
  in a reserve's category (or simply every non-transfer debit since the reserves began), so
  *to move* stays what the reserves gained less what the account received for them, net.
- **Alternatives:** work *to move* from the account's balance: reserves' total less (balance
  less the account's own money), with the account's own money set when reserves begin and
  changed by *kept as the account's own*.

- **Check:** corrected. Read reserves.py whole and reran test_u05.py: before 1000.00 / 1000.00 /
  0.00, after 300.00 / 1000.00 / -700.00 with balance 300.00, as claimed. It holds, but S7.10.4's
  own formula (gained, *less spent*, less transferred in) gives -700 too, so the remedy must also
  reword S7.10.4 for a payment made from the held-in account itself. Severity unchanged.

### U05-2: a reserve's balance is carried into its line after its target is taken off

- **Kind:** differs. **Req:** S7.10.3 ("Taking its category out of the plan, or its target off,
  asks first and names the balance that stops being kept; a balance is never carried into a
  line without a target").
- **Code:** `web/server/src/moolakata/ui/budgets.py:821-826` stores every reserve line with
  rollover on:
  ```text
  new.amount,
  new.cadence,
  new.rollover or new.target is not None,  # a reserve always rolls over
  ```
  and `budgets/__init__.py:599-609` (`_carry`) walks every earlier month from the category's
  first line, carrying any rolling monthly line, a reserve's months included:
  ```text
  ln = in_force(mine, m).get(cat_id)
  if ln is None or not ln.rollover or ln.cadence != "month":
      carry = ZERO
  else:
      carry = (
          ln.amount
          + carry
  ```
- **What goes wrong:** Case (run): *Car maintenance* $100 a month with a $1,000 target from
  August, nothing spent: $400 at the end of November. In December the target is taken off,
  the line kept at $100 with rollover; the server answers 409 *holds 400.00: it stops being
  kept*, and on confirm December shows **carried $400.00, planned $500.00**. The balance the
  user was told stops being kept is carried into a line without a target. (Had the target
  capped the put-in, `_carry` would also count the full $100 a month a funded reserve never
  put in.)
- **Run:** yes, `test_u05.py::test_a_reserve_balance_carried_into_a_line_without_target`:
  `NOV reserve balance 400.00`, `DEC no target None carried 400.00 planned 500.00`.
- **Remedy:** `_carry` starts afresh after a run of lines with a target (a month whose line
  has a target sets `carry` to nothing), so a line without one carries only its own months.
- **Alternatives:** store reserves with `rollover` as the user set it and treat a target as
  rolling over in `reserves.reserve` alone.

- **Check:** confirmed. Read `set_plan` (`ui/budgets.py:819-833`) and `_carry`
  (`budgets/__init__.py:578-611`); reran the claim's test: NOV balance 400.00, DEC no target,
  carried 400.00, planned 500.00. Reserve lines are stored with rollover on and `_carry` tests
  rollover alone, never the target.

### U05-3: copying an envelope budget with this month's moves fails when a move went into a card's payment line

- **Kind:** bug. **Req:** S7.12.4 ("with this month's moves when asked"), S7.13.2.
- **Code:** `web/server/src/moolakata/ui/budgets.py:1330-1342` copies a move without its
  `cardId`:
  ```text
  s.add(
      BudgetMove(
          id=ids.new_id("BdgMv"),
          budgetId=b.id,
          month=month,
          fromCategoryId=m.fromCategoryId,
          toCategoryId=m.toCategoryId,
          amount=m.amount,
          note=m.note,
          transactionId=m.transactionId,
          createdById=c.id,
      )
  )
  ```
  while `store/tables/budgets.py:109-114` requires one of the four (`ck_BudgetMove_somewhere`).
- **What goes wrong:** Case (run): an envelope budget with a $60 move from *To Budget* into
  Visa's payment line this month; **Copy as scenario…** as envelope with *this month's moves*
  fails with `IntegrityError: CHECK constraint failed: ck_BudgetMove_somewhere` (a 500, and
  no copy). A move from a category into the card's line is copied as a move from that
  category to *To Budget*, silently changing what the copy holds. A tracking copy also drops
  landed money given to a reserve (`:1328-1329` skips any move without both categories), so
  the copy's reserve lacks it and the deposit shows as unassigned again.
- **Run:** yes, `test_u05.py::test_copy_with_a_card_move`: the IntegrityError above.
- **Remedy:** copy `cardId` with the move when the copy is an envelope budget whose accounts
  hold the card; skip a card move otherwise, and keep landed-money moves (they need no
  category on the *from* side).
- **Alternatives:** copy only category-to-category moves and say so in the dialog.

- **Check:** confirmed. Reran the claim's test: `IntegrityError ck_BudgetMove_somewhere`, a 500.
  The copy loop (`ui/budgets.py:1328-1342`) drops `cardId` and skips every landed-money move in a
  tracking copy; `store/tables/budgets.py:109-114` needs one of the four.

### U05-4: Compare over a range of months counts a rolled-over remainder once in every month it carries through

- **Kind:** wrong figure. **Req:** S7.12.3 ("for a month or a range of months: per category,
  what is available, spent and remaining").
- **Code:** `web/server/src/moolakata/ui/budgets.py:1377-1388` sums each month's *available*,
  which already holds what rolled into it:
  ```text
  avail = r.balance + r.actual if r.target is not None else r.planned
  got[0] += avail if r.cadence == "month" or m == last else 0
  got[1] += r.actual if r.cadence == "month" or m == last else 0
  ```
  (`Row.planned` is "this period's plan, with what rolled over into it",
  `budgets/__init__.py:337`; a reserve's `balance + actual` and an envelope row's `planned`
  hold the month's starting balance the same way.)
- **What goes wrong:** Case (run): *Entertainment* $100 a month with rollover from January,
  nothing spent; Compare with a copy for the year to March shows **available $600, spent $0**:
  100 + 200 + 300, where $300 was ever made available. Every rolling line, reserve and envelope
  category in a range overstates what was available, and so what remained, by its carried
  balances; the two budgets part by those carries, not by their plans.
- **Run:** yes, `test_u05.py::test_compare_a_range_counts_carries_again`:
  `('Entertainment', 600.00, 0.00)`.
- **Remedy:** for a range, available is the first month's carried balance plus each month's
  own plan and moves (`planned − carried` summed, plus the first month's `carried`); a
  reserve's the first month's start plus what was put in and moved.
- **Alternatives:** show a range as its last month's available and the range's spending.

- **Check:** corrected. **Severity now:** Med. Read `compare` (`ui/budgets.py:1377-1388`); reran
  the test: `('Entertainment', 600.00, 0.00)` for $300 ever made available. `planned` already
  holds the carried balance, so a range overstates available and left for every rolling line,
  reserve and envelope category: the range mode is wrong for most budgets.

### U05-5: a reviewed month isn't flagged when a late transaction lands outside the plan, uncategorised, or leaving the budget

- **Kind:** differs. **Req:** S7.14 ("A reviewed month whose figures later change (a late
  transaction, a recategorised one, a move in it) is flagged *changed since reviewed*").
- **Code:** `web/server/src/moolakata/ui/budgets.py:1413-1440` keeps `spent` but never compares
  it, nor anything of what is to sort:
  ```text
  for k, name in (("income", "Income"), ("saved", "Saved"), ("toBudget", "To Budget")):
      if then.get(k) != now.get(k) and not out:
          out.append(f"{name}: {then.get(k)} then, {now.get(k)} now")
  ```
  Only planned rows, income, saving and To Budget are compared; spending in a category with no
  line (`Month.unplanned`), the uncategorised count and the transfers that left or entered the
  budget (`Month.moved`) are not in `_figures` at all.
- **What goes wrong:** Case (run): November reviewed with only *Food* planned. A late $900 vet
  bill under *Entertainment* (no line) and a late uncategorised $50 arrive; the review shows
  **no changes** (`changes []`), though November now has $950 more spending and one
  transaction to sort. The month the user marked as done stays marked so.
- **Run:** yes, `test_u05.py::test_review_misses_unplanned_and_uncategorised`.
- **Remedy:** compare `spent`, the unplanned rows, the uncategorised count and the count and
  total of transfers to sort, and name each change.
- **Alternatives:** keep a hash of the month's counted transactions (ids, amounts, categories)
  with the review, and flag any difference.

- **Check:** confirmed. Reran the test: `changes []` after a late $900 under a category with no
  line and an uncategorised $50. `_figures` stores `spent` and `_changes`
  (`ui/budgets.py:1424-1440`) compares only planned rows and, when no row changed, one of income,
  saved and To Budget.

### U05-6: an envelope budget that plans a category and its parent takes spending from both, and To Budget rises

- **Kind:** wrong figure. **Req:** S7.13.1 ("To Budget is the cash in the budget's accounts,
  less what its categories hold"), S7.1.2 ("A plan line on a parent category counts its
  children with it").
- **Code:** `web/server/src/moolakata/budgets/envelope.py:113-133` works each planned
  category's envelope from `_actual`, which counts a category with its children
  (`budgets/__init__.py:372-379`), so a child's spending comes off the child's envelope and the
  parent's:
  ```text
  available = start + assigned + mv[cat_id] - _actual(tr, cash_spend, cat_id)
  ...
  spent = _actual(tr, cash_spend, cat_id) + charged
  ```
  `set_plan` (`ui/budgets.py:738-747`) refuses a category listed twice, not a parent and its
  child both listed.
- **What goes wrong:** Case (run): envelope budget, $1,000 of salary in, *Food* $300 and
  *Food › Groceries* $200 planned: To Budget $500. A $150 Kroger charge in Groceries leaves
  Food $150 and Groceries $50 (each lost $150) and **To Budget $650**: spending raised the money
  left to hand out by $150. In a tracking budget the same plan shows Groceries' spending in both
  rows, which reads as intended roll-up; in an envelope budget it makes money.
- **Run:** yes, `test_u05.py::test_envelope_parent_and_child_both_planned`: `ENV before 500.00`,
  `ENV after 650.00 150.00 50.00`.
- **Remedy:** in an envelope budget a parent's envelope counts only spending not in a child
  that has a line of its own (or `set_plan` refuses a parent and its child together in an
  envelope budget, saying why).
- **Alternatives:** S7.1.2 says a parent line counts only children with no line of their own,
  in both methods, and the tracking figures follow.

- **Check:** confirmed. Reran the test: To Budget 500.00 before, 650.00 after a $150 Groceries
  charge, Food 150.00 and Groceries 50.00. `_actual` counts a parent with its children
  (`budgets/__init__.py:372-379`) and `set_plan` (`ui/budgets.py:738-747`) refuses only a category
  listed twice, so each envelope loses the charge once.

### U05-7: landed money spread among reserves that hold nothing all goes to the last one

- **Kind:** bug. **Req:** S7.10.5 ("spread among them by balance").
- **Code:** `web/server/src/moolakata/ui/budgets.py:1225-1235`:
  ```text
  weights = [(k, max(v, Decimal(0))) for k, v in h.reserves]
  total = sum((w for _, w in weights), Decimal(0)) or Decimal(len(weights))
  ...
  else (body.amount * (w if total else 1) / total).quantize(Decimal("0.01"))
  ```
  When every balance is nothing, `total` falls back to the count, but `w` is still 0 (`total`
  is never falsy there), so every share but the last is $0 and the last takes the remainder.
- **What goes wrong:** Case (run): two reserves at Ally, both at $0 (a first month, or after a
  repair); $100 of interest **spread**: *Housing › Maintenance* $0.00, *Car maintenance*
  $100.00. The equal split the fallback was written for never happens.
- **Run:** yes, `test_u05.py::test_spread_with_no_balances`.
- **Remedy:** use weight 1 for each reserve when the balances sum to nothing
  (`w if any_positive else 1`).
- **Alternatives:** spread by target, or by the month's put-in, when no reserve holds anything.

- **Check:** confirmed. Reran the test: Housing Maintenance 0.00, Car maintenance 100.00. With
  every weight 0 `total` falls back to the count (never falsy) while `w` stays 0
  (`ui/budgets.py:1225-1235`), so the equal split the fallback was written for cannot happen.

### U05-8: the month cache can keep figures worked out before a write under the generation after it

- **Kind:** bug. **Req:** S7.3.10 ("a month's figures are kept, and worked out again when
  anything they come from changes").
- **Code:** `web/server/src/moolakata/budgets/__init__.py:396-401` reads the cache, works the
  month out, and stores it under whatever generation holds when it is done:
  ```text
  key = (budget.id, month, today, viewer)
  hit = cache.get(key)
  if hit is None:
      hit = _month_view(s, budget, month, today, viewer)
      cache.put(key, hit)
  ```
  `cache.put` (`budgets/cache.py:77-79`) files it under the current `_generation`, which the
  mapper events move on at **flush** (`:48-51`, `after_insert`/`after_update`/`after_delete`),
  before the writing transaction commits. Routes run on a thread pool in one process, so a
  read can run while a write is between its flush and its commit.
- **What goes wrong:** an import (or any write) flushes its transactions, moving the
  generation from G to G+1, and keeps working before it commits. Meanwhile the Dashboard's card
  or the budget screen reads the month: its read transaction sees the data before the import,
  misses the cache at G+1, works the month out without the import and stores it at G+1. The
  import commits; nothing else is written; every later read hits that entry and shows the month
  without the import, with nothing to say so, until another write anywhere or **Refresh**. The
  same holds for a read that began before a write and finishes after it. Two inputs are also
  not watched: group membership (`UserGroup`, which decides what a receiver's figures count
  through a share to a group, S7.1.1), and an account's `Holding` and `Import` rows, which
  `ledger.load` reads for the balances an envelope budget's To Budget and *Where the money is*
  stand on.
- **Run:** no, reading alone (a race; not reproduced).
- **Remedy:** take the generation when the computation starts and store under it (a write
  during the computation then makes the entry unreachable); move the generation on commit
  (`after_commit` on the session, or both flush and commit) rather than at flush alone; add
  `UserGroup`, `Holding` and `Import` to the watched tables.
- **Alternatives:** key a month by the latest `updatedAt` of the budget's inputs, read in the
  same transaction.

- **Check:** confirmed. Read `cache.py` and `month_view` (`budgets/__init__.py:396-401`): `put`
  files under the generation at `put` time, which mapper events move at flush, before `db.tx`
  commits (`store/db.py:105-114`). Ran B's `test_e16.py`: 50.00 before, between flush and commit,
  and after (the committed -70.00 never shows). `UserGroup`, `Holding`, `Import` are unwatched.

### U05-9: an estimate keeps one recurring series per category: two yearly bills in one category become the last one's line

- **Kind:** wrong figure. **Req:** S7.1.5 ("The recurring transactions of S7.5 … are offered as
  lines of their own (*Rent $1,850 a month*, *Car insurance $1,140 a year*), a yearly one as a
  reserve when reserves are on").
- **Code:** `web/server/src/moolakata/budgets/plan.py:204-220`, each yearly or quarterly series
  overwrites its category's proposal, the history average and any earlier series alike:
  ```text
  for x in recurring.detect(txns, today):
      cid = x.categoryId
      ...
      yearly = abs(x.usual) * (4 if x.every == "quarter" else 1)
      out[cid] = Proposal(
  ```
  and an income series is proposed as a reserve too (`target=_round(yearly) if b.reserves`,
  no check of the category's kind).
- **What goes wrong:** case: *Insurance* holds car insurance ($1,140 a year), home insurance
  ($2,400 a year) and a monthly health premium ($300). The history average would propose about
  $7,140 a year; the estimate proposes one line, whichever series `detect` lists last (sorted by
  next date), say *$2,400 a year* (*$200 a month toward a $2,400 target* with reserves on): the
  plan is $4,740 a year short. A yearly bonus under *Income › Bonus* is proposed, with reserves
  on, as a reserve with a target, which S7.10 makes for costs only. Monthly series are never
  offered as lines of their own (`:209-211`), so *Rent $1,850 a month* appears only as
  *Housing › Rent*'s average with "spent in N of M months".
- **Run:** no, reading alone.
- **Remedy:** sum the series of one category (and add the rest of its history average when
  something else is spent there), naming each in the detail; propose reserves for expense and
  savings categories only.
- **Alternatives:** S7.1.5 says the estimate is per category, with the recurring series named in
  its detail, since a plan holds one line per category.

- **Check:** confirmed. Read `plan.estimate` (`budgets/plan.py:204-220`): `out[cid]` is
  overwritten by each yearly or quarterly series (`detect` sorts by next date, `recurring.py:68`),
  monthly series are skipped (`:209-211`, against S7.1.5's *Rent $1,850 a month*), and no check of
  the category's kind precedes the income reserve. Reading alone.

### U05-10: a HELOC draw into a budget's account is taken for a loan payment: it lowers spending, or vanishes

- **Kind:** wrong figure. **Req:** S7.3.3 ("Loan payments count at the bank account they come
  from"), S7.3.2 (a transfer entering the budget from an account it doesn't count "counts like
  any transaction, by the category of its side in the budget … One with no category … is listed
  under … **Entered the budget**").
- **Code:** `web/server/src/moolakata/budgets/__init__.py:202-207` sends every matched transfer
  with a loan account to `_count_loan_payment`, whichever way the money goes:
  ```text
  if t.transferId:
      if other is None or other[1].id in inside:
          continue  # between two of the budget's accounts: no money moved in or out
      if other[1].type in _loan_types():
          _count_loan_payment(s, tr, out, t, other, loans_seen)
          continue
  ```
  There (`:274-281`) a loan counted *whole* adds the bank half's amount, positive for a draw, to
  its category; a *split* loan (the default) looks the transfer up among the loan's payments,
  where `loans.history` (`loans/__init__.py:202-205`) files a draw under `draws`, finds nothing
  and returns without counting or listing it.
- **What goes wrong:** case: a HELOC draw of $10,000 into Checking in May to pay a contractor,
  whose $10,000 is spent from Checking under *Home improvement*. With the loan counted whole in
  *Loan payments*, May's *Loan payments* shows **−$9,600 spent** (the $400 payment less the draw)
  and the month's spending falls by $10,000. With the default split the draw counts nowhere and
  is not under *Entered the budget*, so it can't be sorted. An escrow refund paid from the loan
  into Checking goes the same way.
- **Run:** no, reading alone.
- **Remedy:** only money out to the loan (`t.amount < 0`) is a payment; money in from a loan
  is money entering the budget (S7.3.2): counted by its category, or listed to sort.
- **Alternatives:** S7.3.3 names draws and escrow refunds and says how they count (for example
  as income in a *Loan proceeds* category).

- **Check:** corrected. **Severity now:** Low. The code does what the claim says
  (`budgets/__init__.py:205-207`, `loans/__init__.py:201-205`; read, not run), but the default
  counting is *split*, where the draw is only left unlisted; the wrong figure needs the loan set
  to *whole* (`ui/loans.py:69`) and a draw, which is rare.

### U05-11: saving a gift plan cuts every gift from its anniversaries and custom occasions

- **Kind:** bug. **Req:** S7.7.1 (anniversaries "each with its own date"), S7.7.3 ("each with
  its budget, the gifts planned so far, and what is still missing"), S7.8.1 (a gift is for "an
  occasion (and its year)").
- **Code:** `web/server/src/moolakata/ui/gifts.py:314-331`, every save deletes the plan's
  occasions and adds new ones with new ids:
  ```text
  def _set_occasions(s, gp: GiftPlan, wanted: list[OccasionIn], user_id: str) -> None:
      for o in gifts.occasions_of(s, [gp.id])[gp.id]:
          o.mark_deleted(user_id)
      for o in wanted:
          ...
          s.add(
              Occasion(
                  id=ids.new_id("Occsn"),
  ```
  called from `change_person` whenever `occasions` is sent (`:405-406`), and the plan dialog
  always sends it (`web/ui/screens/gifts.js:382-395`). A gift keeps its occasion as
  `occasion:<id>` (`ui/gifts.py:457`), matched by key in `gifts.upcoming`
  (`gifts/__init__.py:286`, `g.occasion == d.key`).
- **What goes wrong:** Case (run): Emma's plan has *Graduation* (Jan 10); a $200 watch is
  planned for it. Upcoming shows *Graduation: 1 planned, nothing bought*. Alice edits the plan's
  notes and saves: Upcoming now says **Graduation: no gift yet** with no gifts, and the watch's
  occasion reads **An occasion**. Each save of any plan does this to every gift for a custom
  occasion or an anniversary other than the wedding (holidays and birthdays are keyed by name);
  the occasion then raises its lead-time alert as if nothing were planned.
- **Run:** yes, `test_u05.py::test_saving_a_gift_plan_loses_its_gifts_occasions`:
  `UP BEFORE [('Graduation', '1 planned, nothing bought', 1)]`, `UP AFTER [('Graduation', 'no
  gift yet', 0)]`, `GIFT LABEL [('Watch', 'An occasion')]` (`tmp/u05/run2.txt`).
- **Remedy:** the dialog sends each dated occasion's id, and `_set_occasions` updates those in
  place, adds the new and deletes only those left out (moving their gifts to *An idea* or
  asking first).
- **Alternatives:** leave occasions alone when the list sent equals the one stored.

- **Check:** confirmed. Reran the test: Upcoming `1 planned, nothing bought` before the save, `no
  gift yet` after, the gift's label *An occasion*. `_set_occasions` (`ui/gifts.py:314-331`)
  deletes and recreates with new ids; `OccasionIn` has no id and `gifts.js:382-395` always sends
  `occasions`.

### U05-12: a gift plan shared with the person it is for shows them its notes, budget and dates

- **Kind:** privacy. **Req:** S7.8.5 ("A gift for a person who is a user is **never shown to
  that user**, even through a share, so a surprise stays one"), S7.7.1 (a plan's notes: "sizes,
  likes, what they already have").
- **Code:** `web/server/src/moolakata/gifts/__init__.py:36-58`, `visible_plans` lists every plan
  shared with the user, the one for their own person included, and `ui/gifts.py:169-227`
  (`people_view`) returns it whole: `giftBudget`, `notes`, `occasions` with their budgets; only
  `lastGift` is blanked for the caller's own person (`:220`). `sharing.py` puts no limit on whom
  a gift plan is shared with.
- **What goes wrong:** case: Alice shares her gift plans with the group *Household* so Bob can
  plan the children's gifts with her; the plan for Bob goes with them. Bob's People tab lists
  *Bob*, with Alice's notes ("wants the Seiko, size L"), his gift budget and the budgets of his
  birthday and Christmas. The gifts stay hidden, but what they will be does not.
- **Run:** no, reading alone. Low: within a household, no money or account crosses.
- **Remedy:** `visible_plans` leaves out, for anyone but its owner, a plan whose person is the
  viewer, as `upcoming` already does (`gifts/__init__.py:274-275`); the Share dialog says so.
- **Alternatives:** refuse to share a gift plan with its own person, or with a group they are
  in.

- **Check:** plausible. **Question:** does S7.8.5's *a gift for a person who is a user is never
  shown to that user* reach the plan's notes, budget and dates, or only its gifts? The code does
  what the claim says (`ui/gifts.py:169-227`, only `lastGift` blanked), and S10.3's table says a
  gift-plan share includes *its person's occasions, budget, notes and gifts*.

### U05-13: spending by person leaves out a deleted person, and a plan budgeted per occasion shows no budget

- **Kind:** differs. **Req:** S7.8.6 ("gifts bought, given or received stay, still count in past
  spending, and show the person as *Emma (deleted)*"), S7.8.4 ("the spending per year against
  their budget"), S7.7.1 ("a yearly **gift budget** or one per occasion").
- **Code:** `web/server/src/moolakata/gifts/__init__.py:393-399` builds *by person* from the
  live plans only, with the plan's yearly budget:
  ```text
  byPerson=[
      (x.person, by_person.get(pid, ZERO), x.plan.giftBudget)
      for pid, x in plans.items()
      if me is None or pid != me.personId
  ],
  ```
  `plans` comes from `visible_plans` (`:339`), which drops a deleted person (`:49-51`), and
  `delete_person` deletes their plan (`:428-431`).
- **What goes wrong:** case: Emma is deleted in March after $400 of birthday and Christmas
  gifts last year. Gifts › Spending for last year lists everyone but Emma *by person*, while
  *by occasion* and *by year* still count her $400, so the two lists no longer add up and her
  row (*Emma (deleted)*) is not there. A plan with budgets per occasion (birthday $50, Christmas
  $100) shows its person with no budget to compare with.
- **Run:** no, reading alone.
- **Remedy:** add a row for every person in `by_person` whose plan is gone, named with
  *(deleted)*; a plan's budget is its yearly one or the sum of its occasions' for the year.
- **Alternatives:** list a deleted person's spending under *Others (deleted)*.

- **Check:** confirmed. Read `spending` (`gifts/__init__.py:335-399`): `byPerson` is built from
  `visible_plans`, which drops a deleted person (`:49-51`), while `by_occasion` and `by_year`
  count every gift; `delete_person` deletes the plan (`:428-431`). A plan with budgets per
  occasion has `giftBudget` None. Reading alone.

### U05-14: donations are read only from the *Giving* category itself: not its sub-categories, nor a split's Giving part

- **Kind:** wrong figure. **Req:** S7.9.3 ("**Donations** come from transactions categorised
  under *Giving* (tax tag *charitable*, S7.2)"), S7.3.1 ("A split transaction counts through
  its splits").
- **Code:** `web/server/src/moolakata/giving/__init__.py:131-153`:
  ```text
  cats = [c.id for c in s.scalars(select(Category).where(Category.builtIn == "giving"))]
  ...
          select(Transaction).where(
              Transaction.accountId.in_(accounts),
              Transaction.categoryId.in_(cats),
  ```
  Only the shipped *Giving* itself (`ledger/categories.py:81` ships it with no children), and
  only the transaction's own category: splits are not read.
- **What goes wrong:** case: the household adds *Giving › Church* and *Giving › Food bank* to
  tell its giving apart; from then on its monthly $300 to the church counts nowhere on the
  Giving screen: not toward the target, not by organisation, not among acknowledgements due.
  A $120 charity-auction receipt split $80 *Giving*, $40 *Dining* doesn't count either. The
  budget's *Giving* line (which counts children, `budgets._actual`) and the Giving screen then
  disagree on the same money.
- **Run:** no, reading alone.
- **Remedy:** read transactions and splits in *Giving* and its children (or any category with
  the *charitable* tax tag), each split part as its own gift.
- **Alternatives:** S7.9.3 says only *Giving* itself counts, and the category routes refuse a
  child under it.

- **Check:** confirmed. Read `giving.donations` (`giving/__init__.py:131-153`):
  `categoryId.in_(cats)` with `cats` the shipped *Giving* alone, and a split transaction has
  `categoryId` None (`ui/transactions.py:549-551`). Reading alone; a child of *Giving* is
  reachable only through the API (U05-20), but a split with a *Giving* part is ordinary.

### U05-15: a pledge paid by a transaction the Giving screen counts still raises *due*, and a month's alert lapses unpaid

- **Kind:** differs. **Req:** S7.9.5 ("A pledge is **due** from the 25th of the month for a
  monthly one, and from December 1 for a yearly one, while less than it has been given to the
  organisation in that month or year; a due pledge raises an alert to its owner (S12.11.1.3),
  resolved by the donation").
- **Code:** `web/server/src/moolakata/alerts.py:701-722` counts recorded donations only, and
  only while the period is the current one:
  ```text
  if o.pledgeEvery == "month" and today.day >= 25:
      first, period = today.replace(day=1), f"{today:%B}"
  ...
  select(Donation).where(
      Donation.organisationId == o.id,
  ```
  while the Giving screen counts toward an organisation every transaction under *Giving* whose
  payee is its name (`giving/__init__.py:150-153`, `ui/giving.py:140-141`, `given_to`).
- **What goes wrong:** case: a $50 monthly pledge to St. Mark's, paid by card on the 3rd and
  imported under *Giving* with the payee *St. Mark's*. The Giving screen shows the month given;
  on the 25th the alert *Your pledge to St. Mark's is due* is raised anyway and stays until the
  month ends. And when a pledge really is unpaid, the alert disappears on the 1st of the next
  month (the check looks only at the current month), resolved without a donation.
- **Run:** no, reading alone.
- **Remedy:** the alert counts what `giving.donations` counts for the organisation (recorded,
  and transactions matched by name); a month's alert holds until that month is met or the
  pledge is changed.
- **Alternatives:** S7.9.5 says the alert covers the current month only, and the Giving screen
  counts only recorded donations toward a pledge.

- **Check:** corrected. Scope. Read `alerts.pledges_due` (`alerts.py:701-722`) against
  `giving.donations`: the alert counts `Donation` rows only while the Giving screen counts matched
  *Giving* transactions, so the first half holds as written. The second half (the alert lapses on
  the 1st) follows S7.9.5's *in that month*, so it is a reading question, not a defect by itself.

### U05-16: a write share of a giving plan can add a donation but can't change or delete it, nor add or change an organisation

- **Kind:** differs. **Req:** S10.3.2 ("write: also change what the item holds … for the other
  kinds, edit their entries"), S10.3 (a giving plan's share includes "its target, pace,
  donations and organisations"), S7.9.1.
- **Code:** `web/server/src/moolakata/ui/giving.py:549-551` files a write receiver's donation
  under the plan's owner:
  ```text
  plan, lvl = giving.plan_for(s, c.id, body.date.year)
  # Recorded in the plan the caller writes to: its owner's giving (S7.9.1).
  owner = plan.ownerId if plan is not None and lvl == "write" else c.id
  ```
  but every later change needs the caller to own it (`:616-620`, `_own`:
  `if d is None or d.deleted or d.ownerId != c.id: raise Problem(404, …)`), and `canWrite`
  says the same (`:413`). Organisations are changed only by their owner (`:309-313`), and one a
  receiver adds is theirs (`:303`), so it is not among the plan's (`_orgs_view` lists the
  owner's, `:242-245`) and is refused for the plan's donations (`:554-555`).
- **What goes wrong:** case: Alice shares her giving plan with Bob at write. Bob records a $500
  gift to the food bank from Checking: it lands in Alice's plan. The letter arrives; Bob can't
  tick *acknowledged* or attach it (404 *Not found*), can't fix the organisation, can't delete
  it; Alice must. Bob adds *Habitat for Humanity*: it never shows in the plan's organisations
  and can't be chosen for a donation. A read receiver with no plan of his own gets the shared
  plan as his year's (`giving.plan_for`), so he can't record a donation to his own
  organisations at all (`organisation-unknown`).
- **Run:** no, reading alone.
- **Remedy:** `_own` and `_own_org` accept the plan's owner and its write receivers; a write
  receiver's new organisation belongs to the plan's owner. `plan_for` gives a user their own
  giving when the only plan for the year is someone else's at read.
- **Alternatives:** S7.9.1 says a giving plan is shared to read only, and the Share dialog
  offers no write for it.

- **Check:** corrected. Scope. Reran calibration run B's `test_e5.py`: a write receiver's donation
  lands in the owner's plan and his PATCH and DELETE answer 404, as claimed. But his added
  organisation answers 500 and saves nothing (`ui/giving.py:306`), not "never shows"; the 500s are
  claim U05-36. Severity unchanged.

### U05-17: Edit plan saved unchanged rewrites the plan: moves baked in, reserves refused, an envelope's yearly lines cut to a twelfth

- **Kind:** bug. **Req:** S7.1.2 ("The plan holds from a month on"), S7.11 (a move is "for one
  month"), S7.10.1, S7.13.1 ("a yearly line a twelfth of its amount" each month).
- **Code:** `web/ui/screens/budgets.js:1625-1636`, the plan dialog starts each line from the
  month's row, taking *planned less carried* as the line's amount:
  ```js
  rows.map((r) => ({
    categoryId: r.categoryId,
    amount: String(dec(r.planned).sub(dec(r.carried))),
  ```
  but `Row.planned` is not the line's amount: for a tracking line it is amount + carried + the
  month's moves (`budgets/__init__.py:490-491`); for a reserve it is the month's put-in and
  `carried` its starting balance (`:473-474`); for an envelope row it is start + assigned +
  moved, a yearly line assigning a twelfth (`:435-444`, `envelope.py:116-118`). The estimate
  dialog keeps the rows it doesn't replace the same way, and sends no `target` or `heldInId`
  for them (`budgets.js:1539-1546`).
- **What goes wrong:** Cases (run, the dialog's lines sent as it builds them):
  1. Tracking: *Dining* $300 and *Entertainment* $200, with a $40 move from Entertainment to
     Dining this month. Opening **Edit plan** and saving with nothing changed sends Dining
     $340 and Entertainment $160: from this month on, every month, the move is in the plan,
     and this month counts it twice (Dining $380 available).
  2. With a reserve (*Car maintenance* $100 a month, target $1,000, $300 held at the start of
     December) the same save sends **−$200** for it, and the server refuses the whole plan
     (*422 amount-negative, Plan zero or more*). Any reserve past its second month blocks
     saving the plan until its amount is retyped.
  3. Envelope: *Entertainment* $1,200 a year. Saved unchanged it becomes **$100 a year**
     ($8.33 assigned a month), and To Budget jumps from $4,900 to $4,991.67.
  4. **Estimate from history** keeps the other rows the same way and drops their targets: a
     reserve with a balance answers 409 *reserve-balance*, which that dialog has no *Save
     anyway* for; one at nothing loses its target silently.
- **Run:** yes, `test_u05.py::test_plan_dialog_saved_unchanged` (`SENT [('160.00', None),
  ('340.00', None), ('-200.00', '1000.00')]`, `PUT 422 … amount-negative`) and
  `::test_plan_dialog_envelope_yearly` (`ENVSENT [('100.00', 'year')]`, then `planned 8.33`,
  To Budget `4900.00 → 4991.67`), `tmp/u05/run3.txt`. The browser itself was not driven.
- **Remedy:** the month view sends each row's line as stored (its `amount`, `target`,
  `heldInId`, alongside the figures), and both dialogs start from that; a test that saves the
  dialog's lines unchanged and finds the plan unchanged.
- **Alternatives:** the dialogs read `GET /budgets/{id}/plan?month=` (a route returning the
  lines in force) rather than the month's figures.

- **Check:** confirmed. Read `budgets.js:1625-1636` and `Row.planned`
  (`budgets/__init__.py:473-474, 490-491`, `envelope.py:116-118`); reran both tests: sent
  160.00/340.00/-200.00 with the target, PUT 422 `amount-negative`, envelope `('100.00','year')`,
  To Budget 4900.00 to 4991.67. The browser was not driven.

### U05-18: turning reserves off changes nothing: the lines with targets go on as reserves

- **Kind:** differs. **Req:** S7.1.4 ("**Options**, chosen when the budget is made and turned on
  or off later in its settings, so a budget shows only what it uses: **reserves** (S7.10)");
  the settings guide (`web/ui/guides/dialog-budget-settings.md`): "Turned off, the reserves'
  lines stay in the plan as ordinary lines."
- **Code:** `Budget.reserves` is read only when a plan is saved (`ui/budgets.py:772-781`, a
  target refused without it) and by the estimate (`budgets/plan.py:215-219`). The month's
  figures (`budgets/__init__.py:463-485`, `if ln.target is not None and ln.cadence == "month":`),
  envelope assignment (`envelope.py:120-121`) and *Where the money is* (`reserves.py:143-148`)
  test the line's `target` alone; `change_budget` (`ui/budgets.py:618-624`) only flips the flag.
- **What goes wrong:** case: a budget with a *Roof* reserve ($150 a month, target $5,000, held
  at Ally) has reserves turned off in Settings. The month still shows *Roof* under **Reserves**
  with its balance and *Funded*, puts in only up to the target, and *Where the money is* still
  asks to move money to Ally; the plan dialog no longer shows the Target column, so its next
  save drops the target and asks about the balance. What the guide promises (ordinary lines)
  happens only then, and only through a 409.
- **Run:** no, reading alone.
- **Remedy:** with reserves off, lines are read as ordinary lines (the targets kept, unused, so
  turning reserves back on restores them), after asking, as S7.10.3 does, about the balances
  that stop being kept.
- **Alternatives:** refuse to turn reserves off while a line has a target, naming them.

- **Check:** confirmed. Grepped `.reserves`: it is read only by `set_plan` (`ui/budgets.py:773`),
  the estimate (`plan.py:215-219`) and the options toggle; `_month_view`, `envelope.month` and
  `held_in` test `ln.target` alone. The settings guide's *ordinary lines* sentence is as quoted.
  Reading alone.

### U05-19: Compare shows no totals, no To Budget and no reserve balances; three screen texts say other than the code

- **Kind:** differs. **Req:** S7.12.3 ("per category, what is available, spent and remaining,
  the reserves' balances, and *To Budget* for an envelope budget, with the totals and where the
  two part"), S7.10.4 ("A reserve held nowhere reads *in the budget's accounts*"), S7.13.4.
- **Code and what differs:**
  1. `web/ui/screens/budgets.js:766-799` renders the rows only: no totals row, nothing marking
     the categories where the two budgets part, and `toBudget`/`otherToBudget`, which the server
     sends (`ui/budgets.py:1408-1409`), are never shown; a reserve appears as its available and
     spent, not its balance.
  2. `budgets.js:923`, a reserve shows `in ${held}` only when it has an account; one held
     nowhere says nothing (S7.10.4's *in the budget's accounts*).
  3. `web/ui/guides/budgets-month.md` (*To Budget*): "Income adds to it; only assigning money
     takes from it." Money leaving the budget's accounts takes from it too (S7.13.4, and
     `envelope.py:159`, cash at the month's end), as do a left-out purchase and an overspent
     line set to *from next month's To Budget* (`envelope.py:136-137`, taken in the same
     month).
  4. `budgets.js:1062-1063`, every card on *Where the money is* says "paying the card moves
     nothing in a tracking budget", in an envelope budget too, where a payment takes from the
     card's line.
- **Run:** no, reading alone.
- **Remedy:** a totals row and To Budget in Compare, with the rows where the two differ marked
  and reserves shown by balance; *in the budget's accounts* for a reserve held nowhere; the
  guide's sentence says income adds to To Budget and money leaving the accounts takes from it;
  the card note by method.

- **Check:** confirmed. All four parts read: `budgets.js:766-799` renders rows only and
  `toBudget`/`otherToBudget` are used nowhere in Compare; `:923` shows `in ${held}` only with an
  account; `guides/budgets-month.md:25` says only assigning takes from To Budget
  (`envelope.py:136-137, 159` say otherwise); `:1062-1063` is the same text for every method.

### U05-20: categories are the server's; any user adds one through the API, the browser can't, and nobody renames or removes one (D1-13)

- **Kind:** not built. **Req:** S7.2 ("**Categories** form a two-level tree … A default set
  ships"), S7.12.6, S14.10.1.1; Phase 1's D1-13 (who owns a category and who may change one,
  open, **needs the user**).
- **Code:** `web/server/src/moolakata/ui/transactions.py:951-1056`: one tree for the server
  (`list_categories` reads every live `Category`, no owner); `POST /categories` lets **any**
  user add a top-level or child category of any kind, with any tax tag, and records it nowhere
  but `createdById`; `PATCH /categories/{id}` is an admin's and changes only `keepReceiptsYears`.
  There is no route to rename, re-parent or delete a category, and no screen calls
  `POST /categories` (the browser only lists them: `components/txtable.js:17`,
  `screens/budgets.js:1623`, …).
- **Against the readings:** with categories per user or per budget, the code differs throughout.
  With D1-13's proposed reading (the server's, any user adds a child, renaming, moving and
  deleting a shipped or another user's category an admin's, each change in Activity), the code
  holds the first part only: a user adds top-level categories too, and with a tax tag that
  feeds every user's Taxes (S8.5); no one can rename or delete; nothing goes to Activity.
- **What goes wrong:** in the browser a household can't add *Pets* or *Giving › Church*, so the
  shipped tree is all it has, and S7.2's two-level tree beyond the default set is reachable only
  through the API; there, Bob can add *Medical › Botox* tagged *medical*, which then appears in
  Alice's category lists and her deductions' tag choices, and no one can remove it.
- **Run:** no, reading alone.
- **Remedy:** decide D1-13 first (needs the user); then a category screen (or a field in the
  plan and transaction dialogs) to add one, and the rename, move and delete the decision
  gives, recorded in Activity.
- **Alternatives:** S7.2 says the shipped tree is fixed until later work, and `POST /categories`
  is removed or kept admin-only.

- **Check:** plausible. **Question:** D1-13: are categories the server's (any user adds, an admin
  renames or removes), a user's or a budget's, and does the browser add them? The code does what
  the claim says (`ui/transactions.py:1008-1056`, no route to rename or delete, no screen posts
  `/categories`), and S7.2 says only that a default set ships.

### U05-21: a budget's receiver sees figures of an account shared with its owner but not with them, through the review

- **Kind:** privacy. **Req:** S7.1.1 ("Its receivers see the figures from the owner's own
  accounts, and from an account shared with the owner only if that account is shared with them
  too, so a budget never passes on an account someone else shared (R3.4)").
- **Code:**
  1. `web/server/src/moolakata/ui/budgets.py:1524` stores a review's figures as the reviewer
     sees them (`_figures(budgets.month_view(s, b, m, clock.today(), c.id))`), and `_reviewed`
     (`:1460-1466`) compares them with the viewer's own, writing both into the text:
     `f"{label}: spent {a[1]} then, {b[1]} now"` (`:1434`).
  2. Withheld (part 2 of this claim; see its check).
  3. `_moves_out` (`ui/budgets.py:888`) names a card move by any credit card on the server.
- **What goes wrong:** case: Carol shares her card with Alice (read); Alice's household budget
  counts it and is shared with Bob at write; the card is not shared with Bob. Alice marks
  October reviewed. Bob opens the review: *changed since reviewed: Dining: spent 812.40 then,
  355.10 now*, the $457.30 being Carol's card, which Bob can't see anywhere else; the flag also
  never clears for him, since his figures never match Alice's.
- **Run:** no, reading alone. Low: one household's members, a narrow arrangement (an account
  shared to the owner by a third person, inside a shared budget).
- **Remedy:** keep a review's figures per viewer's reach, or store only the owner-view and
  compare each viewer against figures worked out from the accounts they share; name cards from
  the viewer's accounts.
- **Alternatives:** S7.14 says a review compares figures per user, each marking it for
  themselves.

- **Check:** corrected. **Severity now:** Med (part 2 only; parts 1 and 3 stay Low). **Withhold:**
  yes (part 2). Split in two: (a) parts 1 and 3, the review's stored figures and a card's name,
  Low as written; (b) part 2, withheld; my full reasoning for (b) is in `withheld.md`.

### U05-22: *Cash before payday* counts each recurring payment once before payday, and none that is due today or late

- **Kind:** wrong figure. **Req:** S7.6.1 ("when its balance, less the recurring payments
  expected from it before its next expected money in … would fall below zero").
- **Code:** `web/server/src/moolakata/alerts.py:559-565` takes one date per series, its next:
  ```text
  ins = sorted(x.next for x in series if x.usual > 0 and x.next > today)
  horizon = ins[0] if ins else today + dt.timedelta(days=31)
  outs = sorted(
      (x.next, -x.usual) for x in series if x.usual < 0 and today < x.next < horizon
  )
  ```
- **What goes wrong:** case: Checking holds $700 on the 2nd; payday is the 15th (a monthly
  salary series); daycare takes $400 every week (the 4th and the 11th). The alert subtracts one
  $400 and finds $300 left: no alert, though the account dips to −$100 on the 11th. With no
  income series the horizon is 31 days and a weekly payment still counts once. A payment whose
  next date is today (`today < x.next`), or one a few days late and still to come, is left out
  too. The same holds for a twice-monthly payment before a monthly payday.
- **Run:** no, reading alone.
- **Remedy:** for each outgoing series, step its dates by its interval from `next` (and from a
  late one's due date) up to the horizon, counting each; include payments due today that
  haven't posted.
- **Alternatives:** none simpler.

- **Check:** corrected. **Severity now:** Med. Read `alerts.cash_short` (`alerts.py:559-565`): one
  date per series, `today < x.next`; claim as written. A weekly, two-weekly or twice-monthly bill
  is counted once, and a payment due today or late is left out, so the alert misses real dips in
  ordinary households, which is the alert's whole purpose.

### U05-23: the Giving screen's projected year end leaves out this month's unpaid monthly pledges; the donation guide says *basis* for short-held shares

- **Kind:** wrong figure. **Req:** S7.9.6 ("the projected year end"), S7.9.5 (pledges "shown as
  expected donations"), S7.9.3 ("otherwise the lesser of the market value and the basis").
- **Code:** `web/server/src/moolakata/giving/__init__.py:210-211` counts a monthly pledge for the
  months after this one only, given or not:
  ```text
  if o.pledgeEvery == "month":
      out += o.pledge * (12 - today.month)
  ```
  and `web/ui/guides/dialog-donation.md` says: "For shares held a year or less, the deduction is
  their basis", where the code takes the lesser of value and basis (`ui/giving.py:522`), as
  S7.9.3 and review 2's C48 say.
- **What goes wrong:** case: a $100 monthly pledge, nothing given yet in December: *projected*
  is what was given plus $0, though $100 is still expected this month; on December 1 every
  monthly pledge vanishes from the projection. (A monthly pledge already met this month is, on
  the other hand, right to leave out.) The guide tells a user donating shares that dropped below
  basis that they deduct the basis, which is more than the code (rightly) counts.
- **Run:** no, reading alone.
- **Remedy:** add this month's monthly pledge less what was given to the organisation this
  month (not below nothing); the guide says "the lesser of their market value and their basis".

- **Check:** confirmed. `pledged_ahead` (`giving/__init__.py:210-211`) multiplies by `12 -
  today.month`, so this month's unpaid pledge is missed; `guides/dialog-donation.md:36-37` says
  *basis* while `ui/giving.py:522` takes `min(value, basis)`, as S7.9.3 does. Reading alone, both
  halves.

### U05-24: deleting an account outside a budget erases the past transfers to it from the budget's months

- **Kind:** wrong figure. **Req:** R3.10 ("A record that ends or is deleted … changes what comes
  after its end, never what came before: past budget months … keep it"), S7.3.2, S7.3.3.
- **Code:** `web/server/src/moolakata/budgets/__init__.py:245-259` finds a transfer's other half
  only in live accounts, and `:202-204` drops a transfer whose other half isn't found:
  ```text
  .where(
      Transaction.id.in_(transfer_ids[chunk : chunk + 500]),
      Transaction.deleted == false(),
      Account.deleted == false(),
  )
  ...
  if t.transferId:
      if other is None or other[1].id in inside:
          continue  # between two of the budget's accounts: no money moved in or out
  ```
- **What goes wrong:** Case (run): October's $300 from Checking to Ally Savings (outside the
  budget), filed under *Savings › Emergency fund*: October shows saved $300. Ally is closed and
  deleted in December: October now shows **saved $0.00**, the line's actual $0.00, and a
  reviewed October is flagged as changed. The same happens to cash taken out to a deleted
  `cash` account (*Cash* spending gone) and to every past payment to a paid-off loan that is
  deleted (its interest, escrow and principal gone from past months).
- **Run:** yes, `test_u05.py::test_deleting_the_other_account_changes_past_months`:
  `OCT BEFORE saved 300.00 300.00`, `OCT AFTER saved 0.00 0.00` (`tmp/u05/run4.txt`).
- **Remedy:** read the other half and its account whether deleted or not (a deleted account's
  transfers keep counting by their category up to its deletion, as R3.10 says), and treat a
  missing half (a deleted transaction) as money leaving or entering the budget.
- **Alternatives:** none.

- **Check:** corrected. **Severity now:** Med. Reran the test: October saved 300.00 before, 0.00
  after the account is deleted. R3.10 says deleting changes what comes after, *never what came
  before*, and closing a savings, cash or loan account is routine; every earlier month and every
  review of it changes.

### U05-25: an envelope budget's card lines and its reserves name, or give the id of, the owner's accounts not shared with the viewer, across links too (P6 again, in new code)

- **Kind:** privacy. **Req:** S11.3.1 (an account not shared is named *an account not shared*),
  S7.1.1; review 2's P6 (done for recurring rows and gifts).
- **Code:** `web/server/src/moolakata/ui/budgets.py:700-710` returns each card line with
  `accountId=x.accountId, name=x.name` straight from `envelope.Card` (`envelope.py:149-156`,
  `name=a.name`), and every reserve row with its `heldInId` (`:108-110`, `MonthRow.heldInId`);
  `budget_month` is what a linked server's user is served (`links/serve.py:163-165`). The
  recurring rows beside them hide the same accounts (`ui/budgets.py:1642-1654`: "An entry
  names its account only to someone the account is shared with too").
- **What goes wrong:** case: Alice's envelope budget counts her own *Chase Sapphire* card and
  holds the *Roof* reserve in her *Ally Savings*; she shares the budget (not the accounts) with
  Bob, or with her parents' linked server. Their month view lists the card line as *Chase
  Sapphire* with its account id, and the reserve with Ally's account id, while the Recurring tab
  of the same budget calls both *an account not shared*.
- **Run:** no, reading alone. Low: names and ids, no figures beyond what the budget shares.
- **Remedy:** name card lines and give `heldInId` through `_names` (the viewer's reach), as the
  recurring rows do; *an account not shared* and no id otherwise.

- **Check:** confirmed. Read `budget_month` (`ui/budgets.py:700-710`): `CardLine` takes `x.name`
  and `accountId` unfiltered, `MonthRow.heldInId` is the plan line's, and `budget_recurring`
  (`:1642-1654`) hides the same accounts through `account_level`; `links/serve.py:165` serves
  `budget_month`. Reading alone, Low as rated.

### U05-26: a reserve set to put in $0 a month disappears with its balance, unasked

- **Kind:** bug. **Req:** S7.10.1 ("At the target it is **Funded** and puts in nothing"),
  S7.10.3 ("Taking its category out of the plan, or its target off, asks first and names the
  balance that stops being kept").
- **Code:** `web/server/src/moolakata/budgets/__init__.py:321-327` treats any line of 0 as no
  plan, a target or not:
  ```text
  def in_force(all_lines: list[BudgetLine], month: dt.date) -> dict[str, BudgetLine]:
      """Per category, the line that holds in a month (a line of 0 is no plan)."""
      ...
      return {k: v for k, v in out.items() if v.amount != 0}
  ```
  so `reserves.reserve` (`reserves.py:80-86`) resets the balance to nothing that month, while
  `set_plan`'s question (`ui/budgets.py:806-818`) is asked only when the new line has no target.
- **What goes wrong:** Case (run): *Emergency fund* $500 a month toward $10,000 since August,
  $2,000 held. In December the user sets the monthly amount to $0 to pause it, target kept: the
  save is accepted without a question (200), and December's month has **no Emergency fund row**:
  the $2,000 balance is gone from the budget, from Compare and from *Where the money is* (where,
  if other reserves are held in the same account, *to move* then asks for $2,000 back to
  checking; held there alone, the account leaves the page).
- **Run:** yes, `test_u05.py::test_a_reserve_set_to_put_in_nothing`: `NOV0 2000.00`, `PUT0 200`,
  `DEC0 []` (`tmp/u05/run5.txt`).
- **Remedy:** a line with a target is in force at any amount (0 puts in nothing and keeps the
  balance); only a line of 0 without a target takes the category out of the plan.
- **Alternatives:** refuse an amount of 0 with a target, saying to leave the amount and let
  *Funded* stop it, or ask as for taking the target off.

- **Check:** confirmed. Reran the test: NOV0 2000.00, PUT0 200, DEC0 `[]`. `in_force` drops any
  line of 0 (`budgets/__init__.py:327`), `reserve` then resets to nothing (`reserves.py:81-86`),
  and `set_plan`'s question is skipped when the new line still has a target (`ui/budgets.py:808`).

## Claims added after assembly

Claims that calibration runs B (Sonnet 5.5, high effort) and C (Opus 5.5, medium effort) made and
this unit's own run did not, as `model-experiment.md` judged them, re-read against the code at
`6916954` and checked here. Their severity is given in the claim, as the table at the end is not
touched by the checking pass.

### U05-27: in an envelope budget that plans a category and its parent, a card's payment line sets a charge aside twice

*From calibration run B's U05-3 (the card line, the part U05-6 does not give), checked by the
comparison.*

- **Kind:** wrong figure. **Severity:** Low. **Req:** S7.13.2 ("A charge to the card from a
  category with money in it moves that much from the category to the payment line"), S7.1.2.
- **Code:** `web/server/src/moolakata/budgets/envelope.py:124-131`, run for every planned
  category, parent and child alike:
  ```text
  charged = ZERO
  for cid in card_ids:
      charge = _actual(tr, per_card[cid], cat_id)
      covered = min(max(charge, ZERO), max(available - charged, ZERO))
      if charge < 0:  # a refund to the card comes back to the category
          covered = charge
      line[cid] += covered
      charged += covered
  ```
  `_actual` counts a category with its children (`budgets/__init__.py:372-379`), so the child's
  charge goes onto the line once under the child and once under the parent. This is U05-6's
  cause, here in the card's line.
- **What goes wrong:** case (run in calibration run B's scratch): *Food* and *Food › Groceries*
  both planned, a $100 grocery charge on the Visa: the card owes $100 and its payment line sets
  aside $200 (*Food* 400.00, *Groceries* 200.00). The payment of $100 then takes $100 from the
  line (`:146`), leaving $100 set aside for a card that owes nothing.
- **Run:** yes, calibration run B's `test_e20.py` (reran here): `setAside 200.00, owed 100.00`.
- **Remedy:** as U05-6: a parent's envelope counts only spending not in a child with a line of
  its own (the charge then goes on the line once), or `set_plan` refuses a parent and its child
  together in an envelope budget.
- **Alternatives:** none beside U05-6's.

- **Check:** confirmed. Read `envelope.month` (`:113-146`) and reran calibration run B's
  `test_e20.py`: `setAside 200.00, owed 100.00`. The loop runs once per planned category and
  `_actual` includes children, so the child's card charge is added to `line[cid]` for both; the
  same cause as U05-6.

### U05-28: when two users follow the same budget, *Cash before payday* alerts only one of them

*From calibration run B's U05-19 (and C's U05-2), checked by the comparison.*

- **Kind:** bug. **Severity:** Med. **Req:** S7.6 ("raised as alerts to its owner"), S7.6.1,
  S7.12.5 ("a household budget shared at `write` can be active for both"); D1-2 is judged in
  this unit's Phase 1 section.
- **Code:** `web/server/src/moolakata/alerts.py:572`, the cause's key leaves out the user, and
  `:843`, `evaluate` keeps causes by key:
  ```text
  key=f"cash:{b.id}:{a.id}",
  ...
  holding[cause.key] = cause
  ```
  `cash_short` loops over every user whose active budget it is (`:539-542`) and yields a cause
  for each, so the second user's cause replaces the first's.
- **What goes wrong:** Alice owns the household budget and shares it at write with Bob; both
  follow it. Checking dips below zero before payday. One alert opens, for whichever of the two
  the users' rows list last; the other never hears of it. Calibration run B's test: one
  `cash-short` alert, for Bob; the owner of the account and the budget gets none.
- **Run:** yes, calibration run B's `test_e17.py` (reran here), and calibration run C's
  `test_two_followers_one_alert` (reran): one alert, for Bob.
- **Remedy:** `key=f"cash:{b.id}:{a.id}:{u.id}"`, as the occasion alert includes the user
  (`alerts.py:749`).
- **Alternatives:** one alert per budget and account, shown to every follower.

- **Check:** confirmed. Read `cash_short` and `evaluate` (`alerts.py:539-581, 836-845`): `holding`
  is a dict by key, so two causes with one key keep one; reran B's `test_e17.py` and C's
  `test_two_followers_one_alert`: one `cash-short` alert, for Bob (the second user).

### U05-29: the month's *uncategorised* count includes every split transaction and every transaction left out of the budget, and sorting never clears it

*From calibration run B's U05-1 (and C's U05-5), checked by the comparison.*

- **Kind:** wrong figure. **Severity:** Med. **Req:** S7.3.1 ("A split transaction counts through
  its splits"), S7.3.5 (a left-out transaction "counts nowhere in it"), S7.4, S7.14.
- **Code:** `web/server/src/moolakata/budgets/__init__.py:293-308`:
  ```text
  Transaction.transferId.is_(None),
  Transaction.categoryId.is_(None),
  Transaction.instrumentId.is_(None),
  ```
  A transaction with splits has `categoryId` None (`ui/transactions.py:549-551`), and the count
  looks neither at splits nor at the budget's leave-outs (`Tree.skip`, which `amounts` honours).
  The Transactions screen's own *Uncategorised* filter leaves splits out
  (`ui/transactions.py:366-371`).
- **What goes wrong:** case (run): one $100 purchase split into two categorised parts: the month
  says `uncategorised: 1`, the review lists it as a loose end, and the link *1 uncategorised
  transaction to sort* opens a list with nothing in it. It cannot be cleared: it is fully
  categorised. After a car bought outright is left out of the budget, the count is 2 though
  `spent` is unchanged. Every split transaction in a budget's accounts is counted for ever.
- **Run:** yes, calibration run B's `test_e1.py` (reran here): `UNCAT ... 1`, then `2` after
  leaving out the car, `spent 100.00`; calibration run C's `test_split_counts_as_uncategorised`
  gives `UNCAT 2`.
- **Remedy:** count a transaction as uncategorised when it has no splits and no category, or a
  split with no category, and skip `tr.skip`.
- **Alternatives:** share one *needs a category* predicate with the Transactions screen's filter.

- **Check:** confirmed. Read `uncategorised` and the Transactions filter
  (`ui/transactions.py:366-371`, which excludes transactions with splits); reran B's `test_e1.py`:
  `1` for a fully split purchase and `2` after leaving out the car. Splits are ordinary here, so
  Med holds.

### U05-30: Copy as scenario keeps a line's held-in account when the copy does not count that account

*From calibration run B's U05-12 (the copy part) and C's U05-14 (its last sentence), checked by
the comparison.*

- **Kind:** bug. **Severity:** Low. **Req:** S7.10.4 ("one of the budget's accounts"), S7.12.4
  ("the same accounts and plan").
- **Code:** `web/server/src/moolakata/ui/budgets.py:1303`, the copy's accounts are the source's
  that the copier can see, and `:1304-1318` copies each line whole:
  ```text
  _set_accounts(s, b, [a for a in budgets.account_ids(s, src, c.id) if a in mine], c.id)
  ...
  heldInId=ln.heldInId,
  ```
  `set_plan` refuses a `heldInId` that is not one of the budget's accounts (`:782`); the copy
  does not.
- **What goes wrong:** Bob, who sees only some of Alice's accounts, copies her budget as a
  scenario: a reserve held in an account the copy does not count still names it. The copy's
  reserves are held in an account that is not one of its accounts.
- **Run:** yes, calibration run B's `test_e12.py` (reran here), the copy case: the copy keeps
  the held-in account.
- **Remedy:** clear `heldInId` (keeping the target) for an account not among the copy's.
- **Alternatives:** refuse the copy while a reserve is held in an account the copier cannot hold.

- **Check:** confirmed. Read `copy_budget` (`ui/budgets.py:1303-1318`) against `set_plan`
  (`:782`): the lines copy `heldInId` unfiltered. Reran B's `test_e12.py`: the copy keeps an
  account it does not count. Low, as rated.

### U05-31: landed money is listed as unassigned only in the month it landed

*From calibration run B's U05-21 (and C's U05-16), checked by the comparison.*

- **Kind:** differs. **Severity:** Low. **Req:** S7.10.5 ("is listed under **Where the money
  is** as **unassigned** until the user gives it").
- **Code:** `web/server/src/moolakata/budgets/reserves.py:195-201`:
  ```text
  for t in txns:
      landed = t.amount > 0 and not (t.transferId and others.get(t.transferId) in inside)
      if not landed or month_of(t.date) != month:
          continue
  ```
  Only deposits dated in the month shown are listed, and `give_landed` looks the deposit up in
  the month it is dated in (`ui/budgets.py:1207-1214`).
- **What goes wrong:** $40 of interest lands in Ally on November 3 and is not given. On
  December 1 the *Where the money is* of December lists nothing for it, though it is still
  unassigned; it shows again only if the user opens November. The month's review of November
  lists it only for November.
- **Run:** no, reading alone.
- **Remedy:** list every deposit since the reserves began with something left to give, whatever
  its month, and let it be given from the month shown.
- **Alternatives:** S7.10.5 says unassigned money is listed for its own month.

- **Check:** confirmed. Read `held_in` (`reserves.py:194-201`) and `give_landed`
  (`ui/budgets.py:1207-1214`): the deposit is listed and can be given only through its own month's
  view. S7.10.5's *until the user gives it* reads as persisting; low, since November's view still
  has it.

### U05-32: in an envelope budget with reserves, landed money given to a reserve changes *Where the money is* but not the reserve's row nor To Budget

*From calibration run B's U05-11 (and C's U05-10), checked by the comparison.*

- **Kind:** wrong figure. **Severity:** Low. **Req:** S7.10.5 ("Money given to a reserve is put
  into it as a move (S7.11) and counts as moved in"), S7.13.1, S7.1.4.
- **Code:** `web/server/src/moolakata/budgets/envelope.py:100-102` skips the moves that give
  landed money:
  ```text
  for x in moves:
      if x.month != m or x.transactionId:
          continue
  ```
  while `reserves.net_moves` (`reserves.py:30-38`), which `reserve` and `held_in` use, counts
  them.
- **What goes wrong:** case (run): an envelope budget with reserves holds *Car maintenance* in
  Ally; $100 is transferred in and $40 of interest lands there. Before giving it: To Budget
  $2,940 and the reserve's row balance $100. After *Give to a reserve*: *Where the money is*
  says the reserves hold $140, but the row still says $100 and To Budget is still $2,940: the
  $40 is both in the reserve and still cash to hand out.
- **Run:** yes, calibration run B's `test_e10.py` (reran here): `BEFORE 2940.00 / 100.00`, `AFTER
  2940.00 / 100.00 | where total 140.00`.
- **Remedy:** `envelope.month` treats a given-landed move as money moved from To Budget into its
  category, as other moves are (a *kept as the account's own* one has no category and moves
  nothing).
- **Alternatives:** say in S7.1.4 that an envelope budget has no reserves.

- **Check:** confirmed. Read `envelope.month` (`:100-110`) against `net_moves`; reran B's
  `test_e10.py`: row balance 100.00 and To Budget 2940.00 before and after, Where total 140.00
  after.

### U05-33: in a tracking budget a move to or from a yearly line changes only the other side

*From calibration run B's U05-14 (and C's U05-8), checked by the comparison.*

- **Kind:** bug. **Severity:** Low. **Req:** S7.11 ("each one's available amount that month
  changes by it"), S7.3.7 (a yearly line compares with the year to date).
- **Code:** `web/server/src/moolakata/budgets/__init__.py:486-491`:
  ```text
  if ln.cadence == "year":
      planned, carried = ln.amount, ZERO
      actual = _actual(tr, ytd, cat_id)
  else:
      carried = _carry(s, tr, accts, every, cat_id, month, moved_by) if ln.rollover else ZERO
      planned = ln.amount + carried + mv
  ```
  `mv` is read for the row (`:432`, shown as `moved`) but a yearly row's `planned` leaves it
  out. `make_move` accepts any category and the Move dialog lists yearly rows on both sides.
- **What goes wrong:** case (run): *Entertainment* $100 a month, *Housing › Insurance* $1,200 a
  year; a $40 move from Entertainment to Insurance in December: Entertainment reads planned
  60.00, *−$40 moved out*; Insurance reads planned 1,200.00, *+$40 moved in*, remaining
  1,200.00. The $40 is in neither line; moved the other way, it appears from nowhere.
  *Cover from…* on an overspent yearly row never covers it.
- **Run:** yes, calibration run B's `test_e14.py::test_move_to_yearly_line` (reran here) and C's
  `test_move_to_yearly_line`: planned 60.00 and 1200.00, moved 40.00.
- **Remedy:** a yearly line's planned adds the year's moves to the month, or a move with a
  yearly line on either side is refused.
- **Alternatives:** say in S7.11 that moves are between monthly lines.

- **Check:** confirmed. Read `_month_view` (`:486-491`); reran B's
  `test_e14.py::test_move_to_yearly_line`: Entertainment planned 60.00 moved -40.00, Insurance
  planned 1200.00 moved 40.00. Low: yearly lines are a minority and the dialog is the only way in.

### U05-34: a birthday or wedding anniversary cannot carry a budget of its own, so a plan budgeted per occasion leaves them out

*From calibration run C's U05-24, checked by the comparison.*

- **Kind:** differs. **Severity:** Low. **Req:** S7.7.1 ("a yearly **gift budget** or one per
  occasion"; the birthday and wedding anniversary "come from the person"), S7.7.3 (each date
  "with its budget"), S7.3.6.
- **Code:** a budget is kept on the plan (`GiftPlan.giftBudget`) or on an `Occasion` row; the
  birthday and the wedding anniversary come from the person and carry none
  (`gifts/__init__.py:196-211`, `dates_in`):
  ```text
  Date(
      "birthday",
      "Birthday",
      _safe(year, p.birthMonth, p.birthDay),
      None,
      "birthday",
  ```
  The budgets' *Gifts* line sums `o.budget` over the `Occasion` rows only (`budgets/plan.py:117-120`).
- **What goes wrong:** Emma's plan budgets $40 for Christmas and $60 for her birthday, per
  occasion. There is nowhere to put the $60: Upcoming shows her birthday with no budget, and the
  household budget's *Gifts* line plans $40 for her year.
- **Run:** no, reading alone.
- **Remedy:** a birthday and a wedding-anniversary budget on the gift plan, used by `dates_in`,
  Upcoming and `planned_elsewhere`.
- **Alternatives:** S7.7.1 says per-occasion budgets are for the plan's own dates, and a birthday
  is budgeted only through the yearly budget.

- **Check:** confirmed. Read `dates_in` (`gifts/__init__.py:179-224`) and `planned_elsewhere`
  (`plan.py:115-122`): the person's dates have `budget` None and no row to hold one, while S7.7.3
  gives every date shown *its budget*. A birthday is the commonest occasion, so a per-occasion
  plan cannot be used for it.

### U05-35: the Giving screen's income counts no split transaction, so a split paycheck leaves the target at nothing

*From calibration run B's U05-16 (and C's U05-18), checked by the comparison; the donations half is
U05-14.*

- **Kind:** wrong figure. **Severity:** Med. **Req:** S7.9.2 ("the year's transactions in
  *Income* categories"), S7.3.1 ("A split transaction counts through its splits").
- **Code:** `web/server/src/moolakata/giving/__init__.py:172-191`, `income()`:
  ```text
  cats = [c.id for c in s.scalars(select(Category).where(Category.kind == "income"))]
  ...
  Transaction.categoryId.in_(cats),
  ```
  A transaction with splits has `categoryId` None (`ui/transactions.py:549-551`), so none of its
  parts is read, whatever their categories.
- **What goes wrong:** case (run): a $5,000 paycheck entered as Salary $4,000 and Other income
  $1,000: the Giving screen's income is $0.00 and a 10% target is $0 (`target`,
  `giving/__init__.py:195-200`); the percentages in *history* are blank for the same reason. A
  household that enters its paychecks with splits (salary, withholding, retirement) gets a
  target and a pace from only its unsplit income. The budget's own figures count the same
  paycheck through its splits.
- **Run:** yes, calibration run B's `test_e15.py` (reran here): `GIVING income 0.00 given 0.00
  target 0.00`.
- **Remedy:** read amounts through the splits as `budgets.amounts` does (a split's category and
  amount, else the transaction's), for income and for donations alike.
- **Alternatives:** none.

- **Check:** confirmed. Read `giving.income` (`:168-192`): only `Transaction.categoryId.in_(income
  cats)`, splits not read; reran B's `test_e15.py`: income 0.00, target 0.00. Med: a split
  paycheck is the ordinary way to enter one here.

### U05-36: a giving plan's receiver gets a 500 when adding an organisation (write) or recording a donation (read), saves nothing, and cannot keep a plan of their own that year

*From calibration run B's U05-6 (items 1, 2 and 4; the rest is U05-16), checked by the comparison.*

- **Kind:** bug. **Severity:** Med. **Req:** S7.9.1 ("per user, or per group"), S10.3.2 (a write
  share edits entries), S10.3.1 (read cannot change).
- **Code:** `web/server/src/moolakata/ui/giving.py:300-306`, `add_organisation`, and `:604-605`,
  `_out`:
  ```text
  o = Organisation(id=ids.new_id("Orgzn"), ownerId=c.id, **values)
  ...
  return next(x for x in _orgs_view(s, c) if x.id == o.id)
  ```
  `_orgs_view` and `donations_view` list the rows of `giving.givers(...)`, the plan owner's
  (`giving/__init__.py:60-65`), so what a receiver has just made, owned by them, is not in the
  list the route looks it up in: `StopIteration`, a 500, and `db.tx` rolls back. `put_plan`
  (`:204-207`) answers 403 to a receiver at read, and at write edits the owner's plan.
- **What goes wrong:** Alice shares her 2026 giving plan with Bob. (1) At write, Bob adds an
  organisation: 500, nothing saved (U05-16 says it "never shows"). (2) At read, Bob records a
  donor-advised-fund contribution from his own account: 500 (any donation of his is filed
  under himself and read back the same way). (3) At read or write, Bob's `PUT /giving/plan` for
  2026 answers 403 *shared with you to read* (or changes Alice's): he cannot keep a plan of
  his own for a year in which one is shared with him, though a giving plan is per user.
- **Run:** yes, calibration run B's `test_e5.py` (reran here): the DAF contribution at read
  raises `StopIteration` (500), the organisation add at write raises `StopIteration`, and the
  own-plan PUT at read answers 403.
- **Remedy:** read the new row back by id instead of through the view, let a receiver's own
  plan win (`put_plan` makes one when no *own* plan exists), and accept the plan's writers in
  `_own`/`_own_org` (U05-16).
- **Alternatives:** say in S7.9.1 that a shared plan is the receiver's only plan that year, and
  refuse a receiver's organisation or donation with a 403.

- **Check:** confirmed. Read `add_organisation`, `_out`, `put_plan` and `givers`; reran
  calibration run B's `test_e5.py`: `StopIteration` for the DAF contribution at read and the
  organisation add at write, 403 for the own-plan PUT at read; `db.tx` rolls back
  (`store/db.py:112-114`). Only the DAF case was run for donations.

### U05-37: three help guides say other than S7 or the code

*From calibration run B's U05-26 (items 1, 3 and 5) and C's U05-23.4, checked by the comparison
(D43 to D45); the other guide mismatches are in U05-18, U05-19 and U05-23.*

- **Kind:** differs. **Severity:** Low. **Req:** S7.5.1, S7.9.1, S7.7.3.
- **Where:**
  1. `web/ui/guides/budgets-recurring.md:7-8` lists "weekly, two-weekly, monthly, quarterly or
     yearly" and leaves out *twice a month*, which S7.5.1 and `recurring.INTERVALS`
     (`budgets/recurring.py:19-26`) have.
  2. `web/ui/guides/giving-overview.md:15`: "**Share** shares the plan, so a household gives
     toward one target." S7.9.1: a plan counts its owner's accounts only, and sharing "shows
     them, and never reads the accounts of those it is shared with"; the code counts the
     owner's (`giving.givers`).
  3. `web/ui/guides/gifts-upcoming.md:3`: "everyone's birthdays": S7.7.3 and the code
     (`gifts.upcoming`) list the dates in the user's own and shared gift plans, not everyone's.
- **What goes wrong:** a reader looks for a twice-monthly payment among the intervals; a
  household that shares a plan expects its members' giving to count toward it; a user expects
  every person's birthday in Upcoming.
- **Remedy:** reword each.
- **Alternatives:** none.

- **Check:** corrected. Item 1 holds exactly (the guide's list omits *twice a month*). Item 2
  holds in part: a shared plan does show one target, but only the owner's accounts count toward
  it, which the sentence hides. Item 3 is a wording nit (*everyone's* for the people in the user's
  plans); severity Low unchanged.

### U05-38: in an envelope budget the *Gifts* and *Giving* lines show a plan, but nothing is assigned to them

*From calibration run B's U05-28, checked by the comparison.*

- **Kind:** differs. **Severity:** Low. **Req:** S7.3.6, S7.13.1 ("the plan's lines assign their
  amounts (a yearly line a twelfth of its amount)").
- **Code:** `web/server/src/moolakata/budgets/__init__.py:513-533` adds the rows of
  `plan.planned_elsewhere` to every budget's month (`planned=amount`, `cadence="year"`), but
  `envelope.month` (`budgets/envelope.py:94, 113`) assigns only the lines of `in_force(every,
  m)`, and these are not lines (`set_plan` refuses to save them, `planned-elsewhere`).
- **What goes wrong:** case (run): an envelope budget; Emma's gift plan has a yearly gift budget
  of $1,200; $3,000 of income and a $500 *Food* line: To Budget $2,500 (a twelfth, $100, set
  aside for gifts would make it $2,400), and the *Gifts* row reads planned 1,200.00, remaining
  1,200.00. A $100 toy purchase takes To Budget from $2,500 to $2,400: the envelope's "$1,100
  left" is not money set aside.
- **Run:** yes, calibration run B's `test_e19.py` (reran here): `TB 2500.00` before, `2400.00`
  after, *Gifts* remaining 1100.00.
- **Remedy:** `envelope.month` assigns a twelfth of each `planned_elsewhere` amount to its
  category like a yearly line.
- **Alternatives:** show them in an envelope budget as a note, not as an envelope row.

- **Check:** confirmed. Read `_month_view` (`:513-533`) and `envelope.month` (`:94, 113-123`): the
  rows are added after the envelope and have no envelope; reran B's `test_e19.py`: To Budget
  2500.00 before and 2400.00 after, Gifts remaining 1100.00.

### U05-39: no test holds the month cache's inputs, Compare over a range, copying with moves, the review's flags beyond planned rows, a second follower's alert or a shared giving plan's receivers

*From calibration run B's U05-27, checked by the comparison.*

- **Kind:** test gap. **Severity:** Low. **Req:** S7.3.10, S7.12.3, S7.12.4, S7.14, S7.6.1, S7.9.1.
- **What the tests hold, and what they don't:** `test_review.py::test_month_figures_are_kept_and_refreshed`
  writes with a bulk `update()` and checks Refresh; the cache's seventeen inputs
  (`budgets/cache.py:19-45`) are exercised only through transactions and plan lines; nothing
  tests a share, a category, a group membership or the in-flight read. `test_scenarios.py`
  compares one month (`"month": "2026-10"`) and copies without moves; `test_review.py`'s flag
  test changes only a planned row; `test_cash_before_payday` has one follower and a monthly
  payment; `test_giving.py::test_a_shared_plan_counts_its_owners_accounts_only` reads as the
  owner and as a reader and records nothing as a receiver. No test has a parent and a child
  planned in an envelope budget, a move to a yearly line, a split paycheck or a category under
  *Giving*, or a deleted account's transfers.
- **Remedy:** a test with each case in U05-4, U05-5, U05-6, U05-8, U05-3, U05-24, U05-28,
  U05-33, U05-35 and U05-36, written with its fix.
- **Alternatives:** none.

- **Check:** confirmed. Grepped `web/server/tests`: no test copies with `withMoves`, Compare is
  called for one month only, the review test changes a planned row, `test_cash_before_payday` has
  one user and a monthly payment, the shared-plan giving test records nothing as a receiver. Cache
  inputs and the envelope parent and child items read for, not each assertion.

### U05-40: withheld

- **Kind:** privacy. **Severity:** Med. **Withheld** (details in `withheld.md`, §2).

- **Check:** confirmed.

## Phase 1 items judged against the code

- **D1-2** (budget alerts "to its owner"): `alerts.cash_short` (`alerts.py:540-579`) runs per
  user whose active budget it is, over the accounts that user's view counts, and raises the
  alert to that user (`user_id=u.id`). It matches D1-2's remedy (each user who follows the
  budget), not S7.6's literal "to its owner": an owner who follows a scenario hears nothing of
  the household budget. Left to the walk-through with D1-2; no claim of its own.
- **D1-13** (who owns a category): U05-20, needs the user.
- **D1-23** (no shortfall in the mockup): the app shows it (*short of its reserves by …*,
  `budgets.js:997-1005`); only the mockup lacks it.
- **D1-24** (gift status *received*): the code has it (`gifts/__init__.py:22`), as the mockup
  and D1-24's remedy do; only S7.8.1 lacks it.
- **S7.6** (the uncited first-level item): built, as `alerts.cash_short` (it cites S7.6.1);
  S7.6.2's threshold alerts are *(later)* with no L id (D1-4), not raised as not built. U05-22
  is what is wrong with S7.6.1.
- **Untraced candidates:** `store/entities/budgets.py` and `store/entities/giving.py` are the
  mapped classes of S7's tables (`store/tables/budgets.py`, `giving.py`): they serve S7, not
  untraced.

## Checked and sound

- What a budget counts (`budgets.amounts`): splits through their splits, transfer categories
  and matched transfers between the budget's accounts never, money leaving or entering by its
  category or listed to sort, cash to a `cash` account as *Cash*, reimbursable parts and their
  paybacks left out, leave-outs skipped per budget; refunds lower spending in their month. The
  golden file `tests/golden/budgets-2026.txt` agrees with a hand check of September to
  December (rollover 40 → 75 → 115 on *Food*, the move of 40 on both rows, the reserve going
  to −60 and back).
- The plan from a month on (`in_force`, `set_plan`'s same-month update), the yearly line
  against the year to date, rollover carrying negative, *Not in the plan*, the amber/red
  states (90%, over).
- Reserves' balance worked out, never stored, capped put-in, *Funded*, the 409 before a
  balance stops being kept (but U05-2, U05-26); landed money given and *kept as the account's
  own*, the withdrawals warning, *summed into one transfer*; only the active budget says what
  to move (`where`, `review`).
- Envelope To Budget, card payment lines (covered charge, part payment, owed not backed,
  refunds), moves from and to To Budget and into a card's line (but U05-6 and U05-19.3).
- Moves: write to make, read to see, Activity on make and delete, per budget.
- The active budget: first budget made active, deleting a budget clears it for everyone
  following it, *Make active* rewrites nothing and is recorded; a receiver's figures follow
  their reach (`account_ids(viewer)`, C39) for the month, trends, cash flow and recurring.
- Recurring detection (intervals, tolerances, missed, changed only for fixed amounts) and the
  15-month and three-year windows.
- Gifts: a gift for the viewer hidden even through a share (received ones excepted), upcoming
  60 days and lead times, the occasion alert, deleting a person (ideas and planned for them
  alone deleted, a shared idea loses only them), the gift-tax flag with every 529 and
  five-year elections (B16), linking a purchase (P7), `paid` naming an account not shared (P6).
- Giving: the owner's accounts only (P2), DAF counted once by the plan's choice, deductibility
  by kind and organisation, the $250 acknowledgement, Form 8283 and appraisal notes, shares
  from a lot with no gain and the lesser of value and basis (C48, B22), pledges due from the
  25th or December 1.
- Money is `Cents` in every S7 table (B23).

## Read lightly or not read

- Migrations `0028`, `0031`–`0036`: read for what they create against `store/tables/budgets.py`
  (unit 06's schema check holds them to the tables); their data steps not traced.
- `web/ui/screens/gifts.js` (881) and `giving.js` (809): read for the plan dialog's body
  (U05-11) and the occasions list; the rest not line by line. `budgets.js` read whole.
- `ui/giving.py:1-100` (models) and `ui/gifts.py`'s people routes beyond the plan: skimmed.
- `reimbursements.paired_out` and the *Reimbursements* tab's route (unit 03's, U03-7) read only
  where budgets call them.
- Tests: names and the setups used for the scratch tests; `test_cash_before_payday` and
  `test_month_figures_are_kept_and_refreshed` not read line by line.
- Performance not measured: a month view walks every month since each rolling or reserve line
  began (`_carry`, `reserves.reserve`) and an envelope budget every month since it began,
  loading each account's whole ledger per month (`envelope._cash`); cached, but each write
  anywhere in the watched tables recomputes it. No claim without a measurement.
- The Dashboard's budget card (`ui/dashboard.py:114-125`) read only for its call.

## Work pad: severity, confirmations, status

| Id | Kind | Sev | Req | Conf | Status | One line |
|---|---|---|---|---|---|---|
| U05-1 | wrong figure | Med | S7.10.4 | 0 | open | Spending paid from the held-in account asks to move it out again |
| U05-2 | differs | Low | S7.10.3 | 0 | open | A reserve's balance carries into its line after the target is taken off |
| U05-3 | bug | Low | S7.12.4 | 0 | open | Copy with this month's moves fails (500) on a card-line move |
| U05-4 | wrong figure | Low | S7.12.3 | 0 | open | Compare over a range counts carried remainders again each month |
| U05-5 | differs | Low | S7.14 | 0 | open | A reviewed month isn't flagged for late unplanned, uncategorised or left-the-budget transactions |
| U05-6 | wrong figure | Med | S7.13.1 | 0 | open | Envelope parent and child both planned: spending taken twice, To Budget rises |
| U05-7 | bug | Low | S7.10.5 | 0 | open | Spreading landed money over empty reserves gives it all to the last |
| U05-8 | bug | Med | S7.3.10 | 0 | open | The month cache can keep pre-write figures under the post-write generation |
| U05-9 | wrong figure | Low | S7.1.5 | 0 | open | Estimate keeps one recurring series per category; income proposed as a reserve |
| U05-10 | wrong figure | Med | S7.3.3 | 0 | open | A HELOC draw counts as a negative loan payment, or vanishes |
| U05-11 | bug | Med | S7.7.3 | 0 | open | Saving a gift plan cuts gifts from their custom occasions and anniversaries |
| U05-12 | privacy | Low | S7.8.5 | 0 | open | A gift plan shared with its own person shows them notes and budget |
| U05-13 | differs | Low | S7.8.6 | 0 | open | Spending by person drops a deleted person; per-occasion budgets show none |
| U05-14 | wrong figure | Low | S7.9.3 | 0 | open | Donations read from *Giving* itself only, not children or split parts |
| U05-15 | differs | Low | S7.9.5 | 0 | open | Pledge alert ignores transactions the screen counts; lapses at month's end |
| U05-16 | differs | Low | S10.3.2 | 0 | open | A giving plan's write receiver can't change or delete donations or organisations |
| U05-17 | bug | High | S7.1.2 | 0 | open | Edit plan saved unchanged bakes in moves, refuses reserves, cuts envelope yearly lines |
| U05-18 | differs | Low | S7.1.4 | 0 | open | Turning reserves off leaves the lines working as reserves |
| U05-19 | differs | Low | S7.12.3 | 0 | open | Compare lacks totals, To Budget, reserve balances; three screen texts differ |
| U05-20 | not built | Med | S7.2 | 0 | open (needs the user, D1-13) | Categories: any user adds through the API, the browser can't, nobody renames or removes |
| U05-21 | privacy | Low | S7.1.1 | 0 | open | Review figures pass on an account shared with the owner |
| U05-22 | wrong figure | Low | S7.6.1 | 0 | open | Cash before payday counts each series once, none due today or late |
| U05-23 | wrong figure | Low | S7.9.6 | 0 | open | Projected year end omits this month's unpaid monthly pledges; guide says basis |
| U05-24 | wrong figure | Low | R3.10 | 0 | open | Deleting an outside account erases past transfers to it from budget months |
| U05-25 | privacy | Low | S11.3.1 | 0 | open | Card lines and reserve rows name or id accounts not shared with the viewer |
| U05-26 | bug | Med | S7.10.1 | 0 | open | A reserve set to $0 a month disappears with its balance, unasked |

Counts: 26 claims. By severity: High 1 (U05-17), Med 7 (U05-1, U05-6, U05-8, U05-10, U05-11,
U05-20, U05-26), Low 18. By kind: wrong figure 9, differs 7, bug 6, privacy 3 (all Low, none
withheld), not built 1. One needs the user: U05-20 (D1-13). Earlier findings: P6 and C39 half
hold (U05-25, U05-21); P2, P3, P7, B16, B22, B23, C48 (code), N13 hold. Scratch test in the
job's `tmp/u05/t/test_u05.py`, runs in `tmp/u05/run1.txt` to `run5.txt`, the moved files'
diff in `tmp/u05/delta-gifts.diff`.

## Found while checking

What the checker noticed that no claim covers, unverified and not added to the claims.

### U05-F1: a changed review names at most one of the totals, and none when a row changed

- **Kind:** differs. **Severity:** Low. **Req:** S7.14 ("flagged *changed since reviewed*, with
  what changed").
- **Code:** `web/server/src/moolakata/ui/budgets.py:1437-1439`:
  ```text
  for k, name in (("income", "Income"), ("saved", "Saved"), ("toBudget", "To Budget")):
      if then.get(k) != now.get(k) and not out:
          out.append(f"{name}: {then.get(k)} then, {now.get(k)} now")
  ```
  `not out` tests the list that the loop itself grows: the first total that differs is named, the
  other totals are not, and no total is named when any category row changed.
- **What goes wrong:** October is reviewed. A late $3,000 paycheck lands (income and To Budget
  both change) and a planned category's spending changes as well: the flag lists only the
  category (*Food: spent …*). With the row unchanged, income and To Budget both changing names
  only *Income*. The month is flagged either way, but the list of *what changed* is partial.
- **Remedy:** compare each total on its own (`then.get(k) != now.get(k)`, without `not out`) and
  list each that differs.
- **Alternatives:** keep the whole month's figures with the review and list every difference.
