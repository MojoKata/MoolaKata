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
| C39 | a budget re-shared a read-shared account | done, decided (S7.1.1) | half holds: the month's figures follow the viewer (`budgets.account_ids`), but a review's stored figures and *Where the money is* pass such an account on (U05-21) |
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
  ```python
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

### U05-2: a reserve's balance is carried into its line after its target is taken off

- **Kind:** differs. **Req:** S7.10.3 ("Taking its category out of the plan, or its target off,
  asks first and names the balance that stops being kept; a balance is never carried into a
  line without a target").
- **Code:** `web/server/src/moolakata/ui/budgets.py:821-826` stores every reserve line with
  rollover on:
  ```python
  new.amount,
  new.cadence,
  new.rollover or new.target is not None,  # a reserve always rolls over
  ```
  and `budgets/__init__.py:599-609` (`_carry`) walks every earlier month from the category's
  first line, carrying any rolling monthly line, a reserve's months included:
  ```python
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

### U05-3: copying an envelope budget with this month's moves fails when a move went into a card's payment line

- **Kind:** bug. **Req:** S7.12.4 ("with this month's moves when asked"), S7.13.2.
- **Code:** `web/server/src/moolakata/ui/budgets.py:1330-1342` copies a move without its
  `cardId`:
  ```python
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

### U05-4: Compare over a range of months counts a rolled-over remainder once in every month it carries through

- **Kind:** wrong figure. **Req:** S7.12.3 ("for a month or a range of months: per category,
  what is available, spent and remaining").
- **Code:** `web/server/src/moolakata/ui/budgets.py:1377-1388` sums each month's *available*,
  which already holds what rolled into it:
  ```python
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

### U05-5: a reviewed month isn't flagged when a late transaction lands outside the plan, uncategorised, or leaving the budget

- **Kind:** differs. **Req:** S7.14 ("A reviewed month whose figures later change (a late
  transaction, a recategorised one, a move in it) is flagged *changed since reviewed*").
- **Code:** `web/server/src/moolakata/ui/budgets.py:1413-1440` keeps `spent` but never compares
  it, nor anything of what is to sort:
  ```python
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

### U05-6: an envelope budget that plans a category and its parent takes spending from both, and To Budget rises

- **Kind:** wrong figure. **Req:** S7.13.1 ("To Budget is the cash in the budget's accounts,
  less what its categories hold"), S7.1.2 ("A plan line on a parent category counts its
  children with it").
- **Code:** `web/server/src/moolakata/budgets/envelope.py:113-133` works each planned
  category's envelope from `_actual`, which counts a category with its children
  (`budgets/__init__.py:372-379`), so a child's spending comes off the child's envelope and the
  parent's:
  ```python
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

### U05-7: landed money spread among reserves that hold nothing all goes to the last one

- **Kind:** bug. **Req:** S7.10.5 ("spread among them by balance").
- **Code:** `web/server/src/moolakata/ui/budgets.py:1225-1235`:
  ```python
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

### U05-8: the month cache can keep figures worked out before a write under the generation after it

- **Kind:** bug. **Req:** S7.3.10 ("a month's figures are kept, and worked out again when
  anything they come from changes").
- **Code:** `web/server/src/moolakata/budgets/__init__.py:396-401` reads the cache, works the
  month out, and stores it under whatever generation holds when it is done:
  ```python
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

### U05-9: an estimate keeps one recurring series per category: two yearly bills in one category become the last one's line

- **Kind:** wrong figure. **Req:** S7.1.5 ("The recurring transactions of S7.5 … are offered as
  lines of their own (*Rent $1,850 a month*, *Car insurance $1,140 a year*), a yearly one as a
  reserve when reserves are on").
- **Code:** `web/server/src/moolakata/budgets/plan.py:204-220`, each yearly or quarterly series
  overwrites its category's proposal, the history average and any earlier series alike:
  ```python
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

### U05-10: a HELOC draw into a budget's account is taken for a loan payment: it lowers spending, or vanishes

- **Kind:** wrong figure. **Req:** S7.3.3 ("Loan payments count at the bank account they come
  from"), S7.3.2 (a transfer entering the budget from an account it doesn't count "counts like
  any transaction, by the category of its side in the budget … One with no category … is listed
  under … **Entered the budget**").
- **Code:** `web/server/src/moolakata/budgets/__init__.py:202-207` sends every matched transfer
  with a loan account to `_count_loan_payment`, whichever way the money goes:
  ```python
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

### U05-11: saving a gift plan cuts every gift from its anniversaries and custom occasions

- **Kind:** bug. **Req:** S7.7.1 (anniversaries "each with its own date"), S7.7.3 ("each with
  its budget, the gifts planned so far, and what is still missing"), S7.8.1 (a gift is for "an
  occasion (and its year)").
- **Code:** `web/server/src/moolakata/ui/gifts.py:314-331`, every save deletes the plan's
  occasions and adds new ones with new ids:
  ```python
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

### U05-13: spending by person leaves out a deleted person, and a plan budgeted per occasion shows no budget

- **Kind:** differs. **Req:** S7.8.6 ("gifts bought, given or received stay, still count in past
  spending, and show the person as *Emma (deleted)*"), S7.8.4 ("the spending per year against
  their budget"), S7.7.1 ("a yearly **gift budget** or one per occasion").
- **Code:** `web/server/src/moolakata/gifts/__init__.py:393-399` builds *by person* from the
  live plans only, with the plan's yearly budget:
  ```python
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

### U05-14: donations are read only from the *Giving* category itself: not its sub-categories, nor a split's Giving part

- **Kind:** wrong figure. **Req:** S7.9.3 ("**Donations** come from transactions categorised
  under *Giving* (tax tag *charitable*, S7.2)"), S7.3.1 ("A split transaction counts through
  its splits").
- **Code:** `web/server/src/moolakata/giving/__init__.py:131-153`:
  ```python
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

### U05-15: a pledge paid by a transaction the Giving screen counts still raises *due*, and a month's alert lapses unpaid

- **Kind:** differs. **Req:** S7.9.5 ("A pledge is **due** from the 25th of the month for a
  monthly one, and from December 1 for a yearly one, while less than it has been given to the
  organisation in that month or year; a due pledge raises an alert to its owner (S12.11.1.3),
  resolved by the donation").
- **Code:** `web/server/src/moolakata/alerts.py:701-722` counts recorded donations only, and
  only while the period is the current one:
  ```python
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

### U05-16: a write share of a giving plan can add a donation but can't change or delete it, nor add or change an organisation

- **Kind:** differs. **Req:** S10.3.2 ("write: also change what the item holds … for the other
  kinds, edit their entries"), S10.3 (a giving plan's share includes "its target, pace,
  donations and organisations"), S7.9.1.
- **Code:** `web/server/src/moolakata/ui/giving.py:549-551` files a write receiver's donation
  under the plan's owner:
  ```python
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

### U05-21: a budget's receiver sees figures of an account shared with its owner but not with them, through the review and *Where the money is*

- **Kind:** privacy. **Req:** S7.1.1 ("Its receivers see the figures from the owner's own
  accounts, and from an account shared with the owner only if that account is shared with them
  too, so a budget never passes on an account someone else shared (R3.4)").
- **Code:**
  1. `web/server/src/moolakata/ui/budgets.py:1524` stores a review's figures as the reviewer
     sees them (`_figures(budgets.month_view(s, b, m, clock.today(), c.id))`), and `_reviewed`
     (`:1460-1466`) compares them with the viewer's own, writing both into the text:
     `f"{label}: spent {a[1]} then, {b[1]} now"` (`:1434`).
  2. `budgets/reserves.py:143-148, 157-164, 209` takes the held-in account from the plan line
     (`ln.heldInId`), whoever views, and reads all its transactions and its balance; `where`
     (`ui/budgets.py:1104-1137`) returns them, the account named *an account not shared* but its
     balance, transfers (payees, amounts) and landed money shown.
  3. `_moves_out` (`ui/budgets.py:888`) names a card move by any credit card on the server.
- **What goes wrong:** case: Carol shares her card with Alice (read); Alice's household budget
  counts it and is shared with Bob at write; the card is not shared with Bob. Alice marks
  October reviewed. Bob opens the review: *changed since reviewed: Dining: spent 812.40 then,
  355.10 now*, the $457.30 being Carol's card, which Bob can't see anywhere else; the flag also
  never clears for him, since his figures never match Alice's. Likewise, a reserve held in an
  account Carol shared with Alice shows Bob that account's balance and transfers.
- **Run:** no, reading alone. Low: one household's members, a narrow arrangement (an account
  shared to the owner by a third person, inside a shared budget).
- **Remedy:** keep a review's figures per viewer's reach, or store only the owner-view and
  compare each viewer against figures worked out from the accounts they share; leave out of
  *Where the money is* any held-in account the viewer can't see (its reserves listed with
  *held in an account not shared*); name cards from the viewer's accounts.
- **Alternatives:** S7.14 says a review compares figures per user, each marking it for
  themselves.

### U05-22: *Cash before payday* counts each recurring payment once before payday, and none that is due today or late

- **Kind:** wrong figure. **Req:** S7.6.1 ("when its balance, less the recurring payments
  expected from it before its next expected money in … would fall below zero").
- **Code:** `web/server/src/moolakata/alerts.py:559-565` takes one date per series, its next:
  ```python
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

### U05-23: the Giving screen's projected year end leaves out this month's unpaid monthly pledges; the donation guide says *basis* for short-held shares

- **Kind:** wrong figure. **Req:** S7.9.6 ("the projected year end"), S7.9.5 (pledges "shown as
  expected donations"), S7.9.3 ("otherwise the lesser of the market value and the basis").
- **Code:** `web/server/src/moolakata/giving/__init__.py:210-211` counts a monthly pledge for the
  months after this one only, given or not:
  ```python
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

### U05-24: deleting an account outside a budget erases the past transfers to it from the budget's months

- **Kind:** wrong figure. **Req:** R3.10 ("A record that ends or is deleted … changes what comes
  after its end, never what came before: past budget months … keep it"), S7.3.2, S7.3.3.
- **Code:** `web/server/src/moolakata/budgets/__init__.py:245-259` finds a transfer's other half
  only in live accounts, and `:202-204` drops a transfer whose other half isn't found:
  ```python
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

### U05-26: a reserve set to put in $0 a month disappears with its balance, unasked

- **Kind:** bug. **Req:** S7.10.1 ("At the target it is **Funded** and puts in nothing"),
  S7.10.3 ("Taking its category out of the plan, or its target off, asks first and names the
  balance that stops being kept").
- **Code:** `web/server/src/moolakata/budgets/__init__.py:321-327` treats any line of 0 as no
  plan, a target or not:
  ```python
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
| U05-21 | privacy | Low | S7.1.1 | 0 | open | Review figures and Where the money is pass on an account shared with the owner |
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
