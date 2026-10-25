# Code review 3, unit 02: items-loans-education-bitcoin

**Session:** Oct 24, 08:00 PM to 08:12 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S1.6 (self-custody bitcoin wallets: what a wallet holds, descriptors, sources,
  Bitcoin Core, Electrum TOFU, when, what is recorded, reorgs, the secret check, sats), S1.8
  (529 plans: the plan, contributions, withdrawals against qualified expenses, Roth rollover,
  the Goal tab), S1.9 (loans and mortgages: terms, schedule, payments, reconciling on the
  Overview, the screen, taxes, budgets), S1.10 (physical assets: items, valuation, metals,
  real estate, selling, the chart), with the README lines they rely on (R1.9 money, R1.11 no
  private keys, R1.26 bitcoin the only chain, R3.1/R3.5 outbound calls and the explorer off
  until configured) and S6.10 (the payoff planner the loan code builds). S1.1–S1.5, S1.7 and
  S1.11 were unit 01's; S6's projections are unit 04's.
- **Code (8,647 lines, 29 files):** `src/assets/__init__.py`; `src/bitcoin/` (`descriptor`,
  `keys`, `sources`, `stub`, `sync`, `transfers`, `wallet`); `src/education/__init__.py`;
  `src/loans/__init__.py`, `loans/payoff.py`; migrations 0009 and 0021;
  `src/store/entities/assets.py`, `entities/education.py`; `src/store/tables/assets.py`,
  `education.py`, `loans.py`, `wallets.py`; `src/ui/education.py`, `items.py`, `loans.py`,
  `wallets.py`; `ui/components/edu.js`, `items.js`, `loan.js`, `payoff.js`, `wallet.js`.
- **Tests (1,406 lines):** `test_assets.py`, `test_descriptors.py`, `test_education.py`,
  `test_loans.py`, `test_wallets.py`.
- **Guides:** `account-529`, `account-contributions`, `account-goal`, `account-loan`,
  `-mortgage`, `-heloc`, `-auto-loan`, `-personal-loan`, `-student-loan`, `-payoff`,
  `-schedule`, `dialog-loan-payment`, `account-crypto-wallet`, `account-items`,
  `-precious-metals`, `-collectables`, `-real-estate`, `-vehicle`, `-other-asset` (935 lines).
- **Cites no section:** `store/entities/assets.py` (mirrors the tables).

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 352 lines (4%), 1 new file. Most files only renamed. Where the content is
(read in `git diff -M 294792b 6916954`, renames set aside):

- `mig/0021_wallets_kept.py` (new, 62): `Transaction.offChainMissedAt`, `offChainKeptAt`, by a
  table rebuild (B35).
- `bitcoin/sync.py` (+44/−15): `chosen()` (nothing read until Settings › Bitcoin is saved, the
  stub too; C36), `mark_gone` needs two misses and keeps Keep (B35), `sync_all` catches each
  wallet's failure (B35), the coinjoin fee share `min(fee, -net)` and a fee-only row "Network
  fee" (B13), `lotMethod` on a send.
- `bitcoin/keys.py` (+32/−11), `ui/components/wallet.js` (+12/−4): `_seed_phrase` (twelve
  words in a row, one mistyped, numbered or comma-separated) and keys looked for inside a
  descriptor (B36), in the server and the browser.
- `bitcoin/wallet.py` (+10/−2): an address derived or typed twice is watched once (B35).
- `bitcoin/sources.py` (+13/−8): JSON read with `parse_float=Decimal` (B23); Electrum connects
  to the address the egress guard checked.
- `ui/wallets.py` (+15): 200,000 characters and 1,000 entries at most (B37); **Check now**
  refused (409) until Settings › Bitcoin is saved.
- `loans/__init__.py` (+26/−7): `PMI_ENDS` 78% and `pmi_due` (B21); every payment in the
  loan's account split by the schedule, however it arrived (B21).
- `loans/payoff.py` (+15/−17): the plan's rounding-up counts PMI only while due (B21); the
  invested alternative in decimals (B23).
- `ui/loans.py` (+34/−6), `ui/components/loan.js` (+43/−4), `store/tables/loans.py`
  (+12/−7): the rate as `Rate`/`ResetRate` (B6); `budgetCounting` split/whole and
  `budgetCategoryId` (S1.9.7, new); money columns in cents (B23).
- `assets/__init__.py` (+3/−2), `store/tables/assets.py`: depreciation by a decimal power,
  money columns in cents (B23).
- `store/tables/education.py`: `stateDeduction`, `QualifiedExpense.amount` in cents (B23);
  `ui/education.py`, `ui/items.py`: attaching a receipt through `receipts.to_attach` (P3).
- `store/entities/education.py`: `Relationship.confirmed1At/2At` (S10.10, unit 07's).
- `edu.js`, `items.js`: a shared `today()`.
- Tests: `test_wallets.py` +126, `test_loans.py` +60, the rest renames.

### 3. Earlier reviews' findings in this area

Review 1: none in these sections (its S14.4 point on the Electrum fingerprint is a document
matter). Review 2 (§12.2 marks all done): **B6** (rate type, three/four places), **B13**
(coinjoin fee share), **B21** (payments split by schedule whatever made them; PMI ends at 78%;
payoff's PMI after it ends), **B22** (items' holding periods by one anniversary rule),
**B23** (floats in `assets/__init__.py`, `loans/payoff.py`, Bitcoin Core amounts; money
columns in cents, `QualifiedExpense.amount`), **B35** (a repeated derived address; two misses
before *no longer on the chain*; Keep kept), **B36** (secret check inside descriptors and on
separated words), **B37** (wallet keys capped; its test, review 2's Tests row), **C36** (no
wallet read until Settings › Bitcoin is saved; dev's stub exempt, 12.5.5), **K13** (a changed
node host clears its password), **P3** (attaching a receipt needs write on it; `ui/education.py`),
**B16** (529 deposits in the gift-tax flag: unit 05's code, read only where this unit's
contributions feed it), A16, A24, A25 (confirmed behaviours). Each re-checked below.

### 4. Phase 1 claims and decisions on these sections

- **DC-6** (S14.3's half-even vs S1.9.2's half up for interest): documents; the code is judged
  against S1.9.2 and noted.
- **DC-7** (Bitcoin Core wallet named `moolakata-<account id>` vs schema §2): what the code
  names it is noted.
- **D1-5 / DC-4** (other coins "later" linked to out of scope; needs the user): the code
  watches bitcoin only, which fits both readings.
- **D1-12** (R3.5 off until configured): S1.6.2.1's explorer rule is checked here (C36).
- **D2-11** (the bitcoin unit in Profile, not in S12.2.16's list): where the code keeps it.
- **D1-25** (who sees a receipt kept on an item, a loan or a 529 expense): unit 06; noted only.
- No decision recorded yet; none is a §6 gate.

### 5. Untraced candidates and uncited first-level items

- Untraced candidate: `store/entities/assets.py` (no cite; judged when read).
- Uncited first-level items: none in S1.6, S1.8–S1.10 (S1.4 and S1.5 went to unit 01, which
  judged them).

## Claims

(Work-pad ids U02-n; kinds and format per §7. Severity, confirmations (0) and status (open)
are in the table at the end.)

### U02-1: taking a key out of a wallet marks every transaction it brought *no longer on the chain*

- **Kind:** bug. **Req:** S1.6.1.3 ("Taking a key or address out of the list stops watching its
  addresses"), S1.6.2.7 ("a recorded transaction that the explorer or node no longer has …
  marked *no longer on the chain* and the owner alerted").
- **Code:** `web/server/src/moolakata/bitcoin/wallet.py:39-42`:
  ```text
  for value, k in current.items():
      if value not in wanted:
          k.mark_deleted(user_id, now)
          s.execute(delete(WalletAddress).where(WalletAddress.keyId == k.id))
  ```
  and `bitcoin/sync.py:246-264` (`mark_gone`), which counts as missed every recorded `btc:`
  transaction of the account not in the read:
  ```text
  seen = {f"btc:{t.txid}" for t in txs}
  ...
      elif r.offChainMissedAt is None:
          r.offChainMissedAt = now  # one miss: a node catching up, or a reorganisation
      else:
          r.offChainAt = now
  ```
- **What goes wrong:** once a key's addresses are no longer read, its transactions are no
  longer in the history, and `mark_gone` takes that for the chain having dropped them. Case: a
  wallet holds a zpub; a sync records 0.5 in, 0.2 out, 0.1 in; the owner replaces the zpub
  with another key (or an xpub they entered by mistake, or a typed address they no longer
  want watched); two hourly reads later all three are marked *no longer on the chain*, and the
  owner gets the S12.11.1.2 alert "a bitcoin transaction is no longer on the chain" for coins
  that are still there. The alert invites deleting them, which takes the coins and their basis
  out of holdings and taxes.
- **Run:** yes, a scratch test (`tmp/u02/t/test_u02_wallets.py::
  test_removing_a_key_marks_its_transactions_off_chain`, using `test_wallets.Fake`): after the
  key is replaced and two syncs, all three transactions carry `offChainAt`.
- **Remedy:** `mark_gone` judges only transactions that touched an address still watched (keep
  the addresses a recorded transaction touched, or its key, and skip those whose addresses are
  all gone); or replacing a key asks what becomes of its recorded transactions (kept as they
  are, the default, or deleted).
- **Alternatives:** keep a removed key's addresses watched read-only until its transactions are
  kept or deleted; or mark the removed key's transactions kept (`offChainKeptAt`) when it is
  taken out.

- **Check:** confirmed. Read `wallet.replace` (deletes the removed key's addresses) and `sync.mark_gone` (counts every recorded `btc:` row not in the read as missed) and `alerts.py:119-126` (alerts on any `offChainAt`); reran the scratch test (passes: all three transactions carry `offChainAt` after two syncs). No guard keeps a removed key's transactions out of `mark_gone`; S1.6.2.7's "the explorer or node no longer has" is not what happened.

### U02-2: an address a key derives, typed as well and then taken out, is never watched again

- **Kind:** bug. **Req:** S1.6.1 ("addresses derived … with a gap limit"), S1.6.1.2, S1.6.1.3.
- **Code:** `web/server/src/moolakata/bitcoin/wallet.py:110-116`:
  ```text
  last_used = max((r.idx for r in rows if r.used), default=-1)
  top = max((r.idx for r in rows), default=-1)
  for i in range(top + 1, last_used + k.gapLimit + 1):
      at = address(chain, i)
      if at in taken:
          continue
  ```
  An index skipped because another key (or a typed address) holds it is passed over for good:
  later calls start at `top + 1`.
- **What goes wrong:** case: the owner pastes a zpub with its first receive address (the review
  2 fix B35 for that case keeps it to one row, held by the typed address). Later they tidy the
  list down to the zpub alone. The typed address's row goes with it, and the zpub's receive 0
  is never derived again: the wallet watches 39 addresses, not 40, and coins later sent to its
  first address are never seen. (Two keys that derive all the same addresses recover, since the
  second holds no rows and starts again at 0; it is a key that holds rows on both sides of the
  skipped index that never goes back.) The used flag of the shared address counts only for the
  row's key, so the other key's gap is counted from a lower index.
- **Run:** yes, a scratch test (`tmp/u02/t/test_u02_wallets.py::
  test_a_typed_address_taken_out_leaves_the_keys_own_address_unwatched`): after the second
  save, receive 0 is not among the watched addresses (`watched == 39`).
- **Remedy:** `extend` derives every index from 0 to `last_used + gapLimit` and adds what is
  missing (a set difference against the key's rows), rather than starting at `top + 1`; and
  `last_used` reads the used flag of any row with that address in the account.
- **Alternatives:** keep one row per key and address (unique on key, address) and dedupe only
  when reading, so each key's chain is whole.

- **Check:** confirmed. Read `wallet.extend` (`range(top + 1, ...)` skips an index held by another row for good) and reran the scratch test: after the typed address is taken out, receive 0 is not watched and `watched` is 39.

### U02-3: an Electrum read that spans a new block takes the server's header notice for an answer

- **Kind:** bug. **Req:** S1.6.2.3 (an Electrum server's history read over TCP), S1.6.2.5.
- **Code:** `web/server/src/moolakata/bitcoin/sources.py:274` subscribes to headers in the
  middle of a read:
  ```text
  tip = self.call("blockchain.headers.subscribe")["height"] if txs else 0
  ```
  and `:222-242` takes the next line as the answer to whatever was asked, never checking its
  `id`:
  ```text
  line, self.buf = self.buf.split(b"\n", 1)
  out = json.loads(line, parse_float=Decimal)
  if out.get("error"):
      ...
  return out.get("result")
  ```
- **What goes wrong:** after `blockchain.headers.subscribe`, an Electrum server (Fulcrum,
  electrs) pushes a `{"method": "blockchain.headers.subscribe", "params": […]}` line whenever a
  block is found. The read then asks for every transaction and every input's previous
  transaction one call at a time, which for a long-used wallet is hundreds of round trips; a
  block found meanwhile (one every ten minutes on average) is read as the answer to the next
  `blockchain.transaction.get` or `blockchain.block.header`, whose `result` is `None`, and
  `bytes.fromhex(None)` raises `TypeError`. The wallet's read fails for that hour ("a wallet
  couldn't be read; the server's log says why" from `sync_all`, or a 500 from **Check now**,
  which catches only `SourceError`), and the larger the wallet the likelier.
- **Run:** no, reading alone (no Electrum server here); the protocol's notifications are as the
  Electrum protocol documents them.
- **Remedy:** match each answer to its request by `id`, skipping lines with a `method` and no
  `id`; or read the tip with `blockchain.headers.subscribe` on a connection of its own, or
  before the history and never again on the same one.
- **Alternatives:** none needed.

- **Check:** confirmed. Read `Electrum.call` (takes the next line, never compares `id`) and `history` (subscribes to headers mid-read, then makes one call per transaction and per input). A pushed header notice has no `result`, so `bytes.fromhex(None)` raises `TypeError`, which `sync_wallet` (catches `SourceError` only) turns into a 500 and `sync_all` into the generic failure. Reading alone; the notification is as the Electrum protocol documents it.

### U02-4: a HELOC in its draw period shows a payment of $0, and nothing is offered to link

- **Kind:** wrong figure. **Req:** S1.9.1 ("A HELOC has a draw period with interest-only
  payments"), S1.9.3 (bank transactions "within 2% of the payment … offered"), S1.9.5 (the
  screen shows the payment).
- **Code:** `web/server/src/moolakata/loans/__init__.py:284-287` (`_pi_payment`) gives the
  repayment period's level payment on the terms' principal while drawing:
  ```text
  if t.drawMonths and not _in_draw(t, day):
      left = max(1, _months_between(day, t.end))
      return level_payment(owed, t.rate_on(day), left)
  return scheduled_payment(t)
  ```
  and `scheduled_payment` (`:160-166`) is `level_payment(t.principal, …)`, where a HELOC's
  `principal` is what was owed at the start (usually 0; draws come later). `summary` (`:412`)
  takes it as the payment, and `ui/loans.py:546-549` looks for bank transactions near it:
  ```text
  sm, _ = loans.summary(loans.terms_of(row), payments, draws, clock.today())
  want = sm.total
  if not want:
      return []
  ```
- **What goes wrong:** case: a HELOC opened Jan 1 with principal 0, 240 months, 8%, a
  120-month draw period, and $30,000 drawn Feb 1. The schedule's next row is right (interest
  $200.00, principal 0), but the loan's screen shows **Payment $0.00**, the payment dialog
  opens at $0.00 (`loan.js:438`, `amount: v.total`), and *Looks like a payment* never lists the
  $200 bank debits, for the whole ten-year draw period. A HELOC whose terms carry an opening
  balance shows the repayment period's P&I instead of the interest due.
- **Run:** yes, a scratch script against `loans.summary` (`tmp/u02/loans_check.py`, case A):
  `payment 0.00 total 0.00`, first row's payment `200.00`.
- **Remedy:** while `_in_draw(t, day)`, `_pi_payment` returns that month's interest on the
  balance owed (as the schedule's row does), so the summary, the dialog and the candidates use
  the interest-only payment; after the draw period the level payment over what is left.
- **Alternatives:** take the summary's payment from the schedule's next row (its principal plus
  interest), which already follows the draw period, resets and recasts.

- **Check:** confirmed. Read `_pi_payment`, `scheduled_payment`, `summary` and `candidates` (`if not want: return []`); reran `loans_check.py` case A: `payment 0.00 total 0.00` with the schedule's first row at 200.00. A HELOC with a non-zero opening balance shows the repayment period's P&I instead of the interest, as the claim's last sentence says.

### U02-5: a plan that rounds the payment up still expects PMI after it has ended (B21's remainder)

- **Kind:** wrong figure. **Req:** S6.10.5 (whether actual overpayments are "ahead of it or
  behind"), S1.9.5 (PMI ends at 78%); review 2's B21 ("A payoff plan's extra payments still
  add the full PMI after it has ended"), marked done.
- **Code:** `web/server/src/moolakata/loans/payoff.py:158-169` calls the extras without the
  balance:
  ```text
  extras = _Extras(dataclasses.replace(plan, lumps=[x for x in plan.lumps if x[0] > since]), t)
  ...
          total += extras(day, pi)
  ```
  so `:81` takes the full PMI:
  ```text
  pmi = self.terms.pmi if owed is None else self.terms.pmi_due(owed)
  ```
  `ui/loans.py:822` uses it for the plan being followed.
- **What goes wrong:** B21's fix reached the planner's schedule (`schedule` passes the balance)
  but not *the plan I'm following*. Case: a $300,000 loan at 6%, escrow $300, PMI $90 that has
  ended (78% of the original value passed), following "round each payment up to $100" for five
  payments: the schedule rounds $2,098.65 up, $1.35 a month, $6.75 in all; the expected figure
  rounds $2,188.65 up, $11.35 a month, $56.75. A borrower who pays exactly the plan is shown
  $50 behind it, and further behind every month.
- **Run:** yes, a scratch script (`tmp/u02/loans_check.py`, case C): `expected_extra 56.75`
  against the schedule's `6.75` over the same months.
- **Remedy:** `expected_extra` works out the balance on each payment day (from the history, or
  the schedule's rows) and passes it, so `_Extras` charges PMI only while `pmi_due`; or take the
  expected figure from the planned schedule's own `overpayment` on the days since.
- **Alternatives:** none needed. A test like `test_rounding_up_counts_pmi_only_while_it_is_due`
  for the followed plan.

- **Check:** confirmed. Read `expected_extra` (calls `extras(day, pi)` with no balance, so `_Extras` takes the full `terms.pmi`) against `schedule` (passes `scheduled`), and `_following` at `ui/loans.py:822`; reran case C: `expected_extra 56.75` against the schedule's `6.75`. The lines are 160-166 (the claim's 158-169 holds with its context); severity unchanged.

### U02-6: after a rate reset or a recast, one extra payment makes every later payment count as an overpayment

- **Kind:** wrong figure. **Req:** S1.9.3 ("Principal beyond the schedule is recorded as an
  overpayment"), S1.9.5 (the screen), S6.10.5 (actual overpayments since a plan was chosen).
- **Code:** `web/server/src/moolakata/loans/__init__.py:276-283`:
  ```text
  recast = [d for d, _ in t.recasts if d <= day]
  reset = [d for d, _ in t.resets if d <= day]
  if recast or reset:
      # Re-amortized from then on over what is left of the term: the end stays.
      return level_payment(owed, t.rate_on(day), max(1, _months_between(day, t.end) + 1))
  ```
  `_scheduled_principal` (`:270-273`) calls it for every past payment with that payment's own
  balance, so after any reset or recast the scheduled payment is re-amortized every month.
- **What goes wrong:** the servicer re-amortizes at the reset (or recast) and then keeps the
  payment level until the next one; overpayments shorten the loan (as `schedule` itself says,
  `:341-342`). Here, once a reset date has passed, an extra payment lowers the "scheduled"
  payment of each later month, so the borrower's unchanged level payment is counted as an
  overpayment again every month. Case: $300,000 at 6% from Jan 2025, an ARM reset to 7% on Jan
  1 2026 (level $1,991.99 from then), the borrower pays that, plus $10,000 once on Mar 1 2026.
  By Jan 2027 the loan's **Overpaid** is $10,694.16, not $10,000: each month after March shows
  an overpayment of $67–69 that was never made, and a followed plan shows the borrower ahead by
  that much.
- **Run:** yes, a scratch script (`tmp/u02/loans_check.py`, case D).
- **Remedy:** `_pi_payment` re-amortizes once, at the latest reset or recast on or before the
  day, from the balance owed on that day, and keeps that payment until the next change, as
  `schedule` does ahead; the past rows' scheduled principal uses the same.
- **Alternatives:** keep the level payment worked out at each change on the loan (a computed
  list beside `resets` and `recasts`).

- **Check:** confirmed. Read `_pi_payment` (any reset or recast on or before the day re-amortizes over the balance owed then) and `_scheduled_principal`, which every past payment's overpayment uses; reran case D: overpaid 10694.16 with 67-69 a month after the one extra payment, against the 10,000 paid.

### U02-7: a split loan payment always counts in the shipped categories; the loan can't name its own

- **Kind:** differs. **Req:** S1.9.7.1 ("The loan names the categories; by default they are the
  shipped *Loan payments › Interest*, *Escrow*, *PMI and fees* and *Principal*").
- **Code:** `web/server/src/moolakata/store/tables/loans.py:30-33` keeps one category, for
  *Whole* only:
  ```text
  Column("budgetCounting", Text, nullable=False, server_default=text("'split'")),
  Column("budgetCategoryId", Text, ForeignKey("Category.id")),
  ```
  `ui/loans.py:403` drops it unless whole (`"budgetCategoryId": body.budgetCategoryId if
  body.budgetCounting == "whole" else None`), `web/ui/components/loan.js:186-195` shows a
  category picker only for *whole*, and `budgets/__init__.py:150-157` (`LOAN_PARTS`) maps each
  part to a fixed shipped key.
- **What goes wrong:** a household that budgets its mortgage's escrow under *Housing › Property
  tax* and *Insurance*, or its principal under a savings category of its own, can't: a split
  payment always lands in *Loan payments › …*. The requirement's "the loan names the
  categories" is not built. (The shipped tree also differs a little in wording: *PMI* and
  *Fees* are two categories, where S1.9.7.1 names one, *PMI and fees*.)
- **Run:** no, reading alone.
- **Remedy:** a category per part on the loan (interest, escrow, PMI and fees, principal),
  defaulting to the shipped ones, offered in the terms form when *Split* is chosen, and used by
  `_count_loan_payment`.
- **Alternatives:** S1.9.7.1 says the split's categories are the shipped ones, which a user
  may rename but not change per loan, and names *PMI* and *Fees* apart; the mockup to match.

- **Check:** confirmed. Read the `Loan` columns, the terms save at `ui/loans.py:403` (`budgetCategoryId` kept only for *whole*), `LOAN_PARTS` and `_count_loan_payment` (a split payment always lands in the shipped keys, *PMI* and *Fees* apart). S1.9.7.1's "The loan names the categories; by default they are the shipped" is read as per-loan naming, and S7.2's *PMI and fees* is one category where `ledger/categories.py:108-109` has two.

### U02-8: an ARM's caps and a mortgage's points are kept nowhere

- **Kind:** not built. **Req:** S1.9.1 ("an ARM's adjustment dates, caps and the rate after
  each reset, typed when known"), S1.9.6 ("mortgage interest, points and PMI (Form 1098) …
  appear in Taxes").
- **Code:** the terms hold resets as a date and a rate only, `web/server/src/moolakata/ui/loans.py:43-45`:
  ```text
  class Reset(Model):
      date: dt.date
      rate: ResetRate
  ```
  and `TermsIn` (`:53-70`) has no caps and no points; the Taxes panel's loan row
  (`taxes/panels.py:790-797`) carries `interest`, `pmi` and `propertyTax`, no points. Nothing in
  `loans/`, `ui/loans.py` or `components/loan.js` names either (searched: `cap`, `points`).
- **What goes wrong:** an ARM's periodic and lifetime caps can't be typed, so an assumed future
  reset rate above the cap isn't caught (S6.10.6 shows future rates as the user's assumption);
  points paid at closing, deductible on Schedule A in the year paid (for a home purchase) and
  reported in Form 1098's box 6, don't appear in Taxes, so the mortgage row understates what
  the 1098 shows. The mockup shows neither.
- **Run:** no, reading alone.
- **Remedy:** caps (initial, periodic, lifetime) on the terms, a reset's rate checked against
  them; points (amount, date paid) on a mortgage's terms, shown on the Taxes loan row for the
  year paid; the mockup with both.
- **Alternatives:** drop "caps" from S1.9.1 (the reset's rate is typed anyway) and "points"
  from S1.9.6, or record them as a gap.

- **Check:** confirmed. Searched `loans/`, `ui/loans.py`, `store/tables/loans.py`, `components/loan.js` and `taxes/panels.py` for caps and points: none; `Reset` is a date and a rate, `LoanRow` has `interest`, `pmi` and `propertyTax`. Not in `gaps.md`, `later.md` or the milestones.

### U02-9: a 529's rollover to a Roth IRA is counted as a distribution not covered by expenses

- **Kind:** wrong figure. **Req:** S1.8.3 ("Each year shows distributions (from Form 1099-Q)
  against the qualified expenses, and the part not covered, whose earnings may be taxable
  (S8.10)"), S1.8.4.
- **Code:** `web/server/src/moolakata/education/__init__.py:178-194`:
  ```text
  for t in s.scalars(
      select(Transaction).where(
          Transaction.accountId == account.id,
          Transaction.deleted == false(),
          Transaction.amount < 0,
          Transaction.kind.not_in(NOT_MONEY_IN_OR_OUT),
          Transaction.instrumentId.is_(None),
      )
  ):
      taken[t.date.year] += -t.amount
  ...
  return [WithdrawalYear(y, taken[y], spent[y], max(taken[y] - spent[y], ZERO)) for y in years]
  ```
  while `rollover()` (`:225-236`) recognises the same transfers to a `roth-ira` as rollovers.
- **What goes wrong:** case: a 529 open 16 years transfers $7,000 to the beneficiary's Roth IRA
  in 2026 (the S1.8.4 rollover the screen proposes), and pays no qualified expenses that year.
  The 529's Withdrawals and the Taxes education panel (`taxes/panels.py:713`) show 2026:
  distributions $7,000, **not covered $7,000**, "whose earnings may be taxable" with S8.10's
  10% additional tax, though a rollover within the limit is neither. A 529-to-529 rollover (to
  a sibling's plan) is miscounted the same way.
- **Run:** no, reading alone.
- **Remedy:** leave transfers to a `roth-ira` (and to another `529`) out of `notCovered`; show
  them on their own line ("rolled over") beside the distributions.
- **Alternatives:** count them in `distributions` (1099-Q reports them) and in a covered column
  of their own, so the year still adds up to the 1099-Q.

- **Check:** confirmed. Read `withdrawals`: any cash row with `amount < 0` whose kind isn't in `NOT_MONEY_IN_OR_OUT` (a transfer's kind, `transfer`, is not) is a distribution, and `rollover` separately recognises transfers to a `roth-ira`; `education_panel` feeds `notCovered` to Taxes. Reading alone.

### U02-10: what could still roll over to a Roth IRA leaves out the earnings on old contributions

- **Kind:** wrong figure. **Req:** S1.8.4 ("how much could still roll over … under the lifetime
  limit …, excluding contributions of the last five years").
- **Code:** `web/server/src/moolakata/education/__init__.py:237-246`:
  ```text
  cutoff = _years(today, -ROTH_RECENT_YEARS)
  old = sum((r.amount for r in rows if r.date <= cutoff), ZERO)
  eligible = max(old - used, ZERO)
  ...
      available=min(max(limit - used, ZERO), eligible),
  ```
  while the screen says (`web/ui/components/edu.js:313-314`): "Contributions of the last five
  years, and their earnings, can't roll over".
- **What goes wrong:** the cap is the old contributions alone, so the earnings on them never
  count. Case: a 529 opened in 2008 with $20,000 contributed by 2012, worth $60,000 now: the
  screen shows **Could still roll over $20,000**, where the account could roll the lifetime
  $35,000 (the balance less the last five years' contributions and their earnings is far
  above it). The figure contradicts the note printed under it.
- **Run:** no, reading alone.
- **Remedy:** eligible = the account's value less the last five years' contributions (and
  their earnings, estimated by the account's return since each, or simply the contributions
  where earnings can't be told), less what was rolled over; `available` its minimum with the
  lifetime limit left.
- **Alternatives:** S1.8.4 and the note say the cap is the older contributions alone
  (conservative), and the code stays.

- **Check:** plausible. **Question:** does S1.8.4's "excluding contributions of the last five years" cap what could roll over at the older contributions alone (as built), or at the account's value less the last five years' contributions and their earnings? The code does what the claim says (`eligible = old - used`, the balance never read), so whether it is wrong depends on that reading. The screen's note ("Contributions of the last five years, and their earnings, can't roll over") is not contradicted by the figure, as the claim says: it names only what is excluded. The same figure also overstates where the account is worth less than its old contributions.

### U02-11: a five-year election above five times the exclusion is spread over five years, not counted in the first

- **Kind:** wrong figure. **Req:** S1.8.2 ("A five-year election … spreads one contribution over
  five years of exclusions and is shown that way"), S7.8.7, S8.11.
- **Code:** `web/server/src/moolakata/education/__init__.py:151-156`:
  ```text
  if r.fiveYear:
      for k in range(5):
          counted[(r.contributor, r.date.year + k)] += (r.amount / 5).quantize(
              Decimal("0.01")
          )
  ```
- **What goes wrong:** the election spreads at most five times the year's exclusion; anything
  above it is a gift in the year it is made. Case: a grandparent puts $100,000 into a 529 in
  2026 and elects, with an exclusion of $19,000: $95,000 is spread ($19,000 a year, none over)
  and $5,000 is a 2026 gift beyond it, so 2026 is $24,000, over by $5,000, and 2027–2030 are at
  the exclusion. The code counts $20,000 in each of the five years and flags every one of them
  over by $1,000 (five Form 709 years where the election's one return covers it). The fifths
  are also each rounded, so five of them can miss the contribution by a few cents.
- **Run:** no, reading alone (the arithmetic is the quoted lines').
- **Remedy:** spread `min(amount, 5 × the contribution year's exclusion)` over the five years
  and count the rest in the first; put any cent left by rounding in the first year.
- **Alternatives:** refuse an election above five times the exclusion and say why.

- **Check:** confirmed. Read `gift_years` (`r.amount / 5` in each of five years, no cap) and `taxtables.figures(...)["giftExclusion"]` per year; S1.8.2's "spreads one contribution over five years of exclusions" bounds the spread at five exclusions, so the rest is a first-year gift. The cents claim also holds (an amount like 10,000.01 rounds to 10,000.00 in five fifths).

### U02-12: an inherited item sold within a year goes on Form 8949 as short-term

- **Kind:** wrong figure. **Req:** S1.10.1 (how an item was acquired: "bought, a gift,
  inherited"; "an inherited item's value at death"), S1.10.5 (a sale realizes a gain on Form
  8949), S8.13.
- **Code:** `web/server/src/moolakata/taxes/panels.py:318-336` (the Form 8949 rows for items,
  built on this unit's `Item`):
  ```text
  long_term = lots.long_term(it.acquiredOn, it.soldOn)
  ...
              longTerm=long_term,
              box="F" if long_term else "C",
  ```
  `it.acquiredHow` (`store/tables/assets.py:18`, checked `bought`, `gift`, `inherited`) is
  never read for the holding period.
- **What goes wrong:** property from a decedent is held long-term whatever its holding period
  (IRC §1223(9)). Case: a coin collection inherited on 2026-03-01 at a stepped-up value of
  $40,000, sold 2026-09-01 for $46,000: MoolaKata files the $6,000 gain in box C, short-term,
  where it is long-term (box F, and for a collectable the 28% rate rather than ordinary income).
  A gift with a carried-over basis likewise takes the donor's holding period, which the form
  only gets if the owner types the donor's date as *date acquired*; the item dialog's guide
  (`web/ui/guides/dialog-item.md`, *Date acquired*) says the opposite: "The day it was bought,
  given or inherited. A sale's holding period starts here."
- **Run:** no, reading alone.
- **Remedy:** an item acquired `inherited` is long-term on any sale; the item form's *date
  acquired* hint says that for a gift with the donor's basis it is the donor's date (or a
  second date, *held since*, as lots have `heldFrom`). S1.10.1 or S8.13 states both.
- **Alternatives:** none needed.

- **Check:** confirmed. Read `taxes/panels._items` (`lots.long_term(it.acquiredOn, it.soldOn)`, `acquiredHow` never read) and `ledger/lots.long_term` (the anniversary rule only); the guide's *Date acquired* line says what the claim quotes. IRC section 1223(9) makes property from a decedent long-term; the requirements are silent on it, so the remedy's last sentence (S1.10.1 or S8.13 states it) stands.

### U02-13: an item's value history is worked out on every read and never shown

- **Kind:** untraced. **Req:** — (S1.10.6, "opens each one with its history, notes and
  documents", is met by the valuations list; the month-end series serves nothing).
- **Code:** `web/server/src/moolakata/ui/items.py:300-318`:
  ```text
  # Its value at each month's end since it was acquired, for its history.
  ...
  while month <= end:
      ...
      history.append((day, assets.value_on(it, d, max(day, first), current)))
  ```
  sent as `ItemDetail.history` (`:143`); `web/ui/components/items.js` never reads it (no
  `history` in the file or in `screens/account.js`).
- **What goes wrong:** every item read (opening the dialog, and the answer to every save,
  valuation, improvement, document and sale) works out a value per month since acquisition
  and loads the metal's whole price history for it: a house bought in 1990 is 430 points, sent
  and thrown away. Nothing is wrong on screen; it is work and payload no requirement asks for.
- **Run:** no, reading alone.
- **Remedy:** show it (a small chart in the item dialog, which S1.10.6's "history" may have
  meant) or drop the field and its loop.
- **Alternatives:** none needed.

- **Check:** plausible. **Question:** does S1.10.6's "opens each one with its history, notes and documents" mean the item's value over time (then the series is built and the dialog doesn't show it: not built in the UI, not untraced), or its valuations list (then the series is dead)? The code does what the claim says: `ItemDetail.history` is computed per read and no `.js` file reads it (searched `history` in `items.js`, `screens/account.js` and the components); the mockup's item dialog shows valuations only.

### U02-14: a wallet's descriptor is listed as an "Address"

- **Kind:** bug. **Req:** S1.6.1, S1.6.1.4 (descriptors held), S1.6.1.2 ("The account's
  Settings lists the addresses watched").
- **Code:** `web/ui/components/wallet.js:143-145`:
  ```js
  ${k.kind === 'xpub'
    ? `Extended public key · ${SCRIPT[k.script] || k.script} · ${k.addresses} addresses`
    : `Address · ${SCRIPT[k.script] || k.script}`}
  ```
  (and `ui/wallets.py:24`, `kind: str  # xpub or address`, though `descriptor` is the third).
- **What goes wrong:** a `wpkh([…]xpub…/<0;1>/*)#…` or a 2-of-3 `wsh(sortedmulti(…))` saved in a
  wallet's Settings is shown as "Address · native segwit (bc1q…)" or "Address · segwit script
  (bc1q…)", with no count of the addresses it derives, so the owner can't tell their multisig
  descriptor was read as a descriptor.
- **Run:** no, reading alone.
- **Remedy:** a third label, "Descriptor · {script} · {n} addresses" (multisig: "k of n"), and
  the model's comment naming the three kinds.
- **Alternatives:** none needed.

- **Check:** confirmed. Read `keys.py:343-366` (`Entry` kind is `xpub`, `descriptor` or `address`) and `wallet.js:143-145`, which labels everything but `xpub` an address; `ui/wallets.py:24`'s comment names two kinds.

### U02-15: a payment recorded on the loan alone, then linked as the guide says, is counted twice

- **Kind:** wrong figure. **Req:** S1.9.3 (a payment "matched as a transfer"; bank transactions
  "offered on the loan's screen to link as its payments").
- **Code:** `web/server/src/moolakata/ui/loans.py:478-507`: linking a bank transaction always
  makes a new loan-side row, whether or not the loan already holds that payment:
  ```text
  if body.transactionId:
      other = s.get(Transaction, body.transactionId)
      ...
  txn = Transaction(
      id=ids.new_id("Txn"),
      accountId=a.id,
      ...
  ```
  and `candidates` (`:556-568`) offers any bank debit within 2% that isn't a transfer, with no
  regard to loan payments already recorded on that day. The guide for the payment dialog
  (`web/ui/guides/dialog-loan-payment.md`) says: "**None** records it on the loan only, for a
  payment already in the bank account that you'll link later."
- **What goes wrong:** case: the October payment of $1,798.65 is in Checking (imported). The
  owner records it on the loan with *From account: None*, as the guide says, and the loan owes
  $299,701.35. *Looks like a payment* then offers the Checking debit; **Link** records a second
  payment, and the loan owes $299,402.70: two payments for one, in the balance, net worth, the
  schedule, the interest on Taxes and the budget's split.
- **Run:** yes, a scratch test (`tmp/u02/t/test_u02_loans.py::
  test_payment_recorded_on_loan_only_then_linked_counts_twice`): two loan rows, balance
  $299,402.70.
- **Remedy:** linking first looks for an unlinked payment on the loan of the same amount within
  a few days and pairs the two (`transferId` both ways) rather than making a new row;
  `candidates` leaves out a bank debit that such a loan payment already answers, or offers it
  as "pair with the payment of Oct 1".
- **Alternatives:** drop *None* from the dialog and the guide (a payment is always recorded with
  its bank half or linked to it), and let the S1.7 transfer matching pair a loan row typed or
  imported on its own.

- **Check:** confirmed. Read `add_payment` (a `transactionId` always makes a new loan-side row and sets `transferId` both ways) and `candidates` (no look at loan rows already recorded); `dialog-loan-payment.md` says what the claim quotes. Reran the scratch test: it passes with two loan rows and the balance down twice.

### U02-16: the wallet and loan guides say less than, or other than, S1.6.2 and S1.9.3

- **Kind:** differs. **Req:** S1.6.2.6, S1.6.2.7, S1.9.3.
- **Where:** `web/ui/guides/account-crypto-wallet.md`, *Check now*: "bitcoin sent as a transfer
  out, its network fee included", where S1.6.2.6 (and the same guide's *What is recorded*) make
  the fee a sale of its own beside the transfer out of what left for others; *What is recorded*:
  "A transaction the explorer or node no longer has is marked _no longer on the chain_", where
  S1.6.2.7 marks it only once two reads in a row miss it, and "a transaction kept stays kept"
  is not said. The loan guides' *Looks like a payment* (`account-loan.md`, `-mortgage.md`,
  `-heloc.md`, `-auto-loan.md`, `-personal-loan.md`, `-student-loan.md`): "within 2% of the
  payment that aren't a transfer yet", leaving out S1.9.3's "and not filed under another
  category", which the code applies (`ui/loans.py:563-566`), so an owner looking for a rent-
  categorised debit isn't told why it isn't offered.
- **What goes wrong:** the help contradicts what the screen records (a fee "included" in the
  transfer out) and leaves out the rules that explain what the owner sees.
- **Run:** no, reading alone.
- **Remedy:** *Check now*: "bitcoin sent as a transfer out, and its network fee as a sale of its
  own (below)"; *What is recorded*: "once two reads in a row miss it … Keep it, and it stays
  kept"; *Looks like a payment*: "… that aren't a transfer yet or filed under another
  category".
- **Alternatives:** none needed.

- **Check:** confirmed. Read `account-crypto-wallet.md` (*Check now*: "its network fee included", while the code records the fee out of the transfer's quantity and as a sale beside it; *What is recorded* has no two-read rule or "stays kept"), the six loan guides ("that aren't a transfer yet") and `candidates` (category must be empty or *Loan payments*), against S1.6.2.6, S1.6.2.7 and S1.9.3.

### U02-17: a bitcoin transaction is dated in the server's zone, not its owner's

- **Kind:** wrong figure. **Req:** S1.6.2.6 (each transaction recorded), S14.9.2, S14.9.5
  ("Today" and dates for a user follow their zone), S8.1 (the fee's sale on Form 8949).
- **Code:** `web/server/src/moolakata/bitcoin/sync.py:204` and `:222`:
  ```text
  zone = ZoneInfo(timezones.host_zone())
  ...
          date=t.confirmedAt.astimezone(zone).date(),
  ```
  where `timezones.zone_for(user.timeZone)` (`timezones.py:136-138`) gives the owner's.
- **What goes wrong:** a block time has no calendar date until a zone gives it one, and the
  owner's is the one S14.9 sets for them. Case: a server in America/Chicago, an owner whose
  Profile says America/Los_Angeles; coins sent at 22:30 Pacific on Dec 31 2026 (06:30 UTC,
  00:30 Chicago on Jan 1) are dated Jan 1 2027: the network fee's sale lands in the 2027 tax
  year and the transfer pairs (S1.7.1, 3 days) and lots are dated a day late for that owner.
  With *Auto* (the default) both agree, so it shows only for an owner who chose a zone.
- **Run:** no, reading alone.
- **Remedy:** date each transaction in `timezones.zone_for(owner.timeZone)` of the account's
  owner.
- **Alternatives:** date bitcoin by UTC everywhere and say so in S1.6.2.6 (simpler, but a day
  off for every US owner in the evening).

- **Check:** plausible. **Question:** in which zone does a bitcoin transaction's block time become the calendar date it is recorded under: the server's (as built), the account owner's, or UTC? S14.9.3 says a transaction's date is never shifted but a block time has no date until a zone gives one, and S14.9.5 (cited by the claim) covers only "Today", not recorded dates, so no requirement settles it. The code does what the claim says (`host_zone()` at `sync.py:204`); the two agree for *Auto*.

## Uncited first-level items

None in this unit's sections: S1.6, S1.8, S1.9 and S1.10 are each cited by the code. (S1.4 and
S1.5 were judged by unit 01.) The untraced candidate `store/entities/assets.py` mirrors
`store/tables/assets.py` field for field and serves S1.10: not untraced.

## Phase 1 claims against the code

- **DC-6** (S14.3's half-even against S1.9.2's half up): the code follows S1.9.2: `loans.cents`
  rounds `ROUND_HALF_UP` (`loans/__init__.py:48-49`) for interest, level payments and splits.
- **DC-7** (Bitcoin Core wallet named by the account's id): the code follows S1.6.2.3 as
  written, `name = f"moolakata-{account_id}"` (`bitcoin/sync.py:77`); the schema §2 reading
  (a random name kept on the account) is not built.
- **D1-5 / DC-4** (other coins "later" pointing at out of scope): only bitcoin is watched
  (`bitcoin/`), which fits both readings.
- **D1-12** (R3.5's "off until configured"): for wallets, `sync.chosen` reads nothing until
  Settings › Bitcoin is saved, in the hourly task, **Check now** (409) and a single read, the
  dev stub included (`bitcoin/sync.py:43-47, 88-89, 272-273`, `ui/wallets.py:189-195`).
- **D2-11** (the bitcoin unit in Profile): the code keeps it on the user (`bitcoinUnit`,
  `ui/profile.py`, `screens/profile.js`), as S1.6.4 says; S12.2.16's list is the documents'.
- **D1-25** (who sees receipts on items, loans, 529 expenses): items and expenses attach through
  `receipts.to_attach` and list each receipt at the caller's level; unit 06 weighs D1-25.

## Earlier findings re-checked

| Finding | Still holds? |
|---|---|
| B6 (rate to three places, a reset's to four) | yes: `Rate`/`ResetRate` (`ui/conventions.py:84-107`, `ui/loans.py:43-58`), 0–40% checked; `test_a_rate_as_the_note_states_it` |
| B13 (coinjoin fee share) | yes: `fee = min(t.fee, -t.net)`, memo says "this wallet's share" (`bitcoin/sync.py:216-226`); `test_a_coinjoins_fee_is_the_wallets_share_never_the_whole` |
| B21 (payments split by the schedule whatever made them; PMI ends at 78%; payoff's PMI after it ends) | **half**: `history()` splits every unsplit payment (`loans/__init__.py:206-219`), `pmi_due` ends PMI at 78% in splits, schedule and the planner; *the plan I'm following* still rounds up with the full PMI (U02-5) |
| B22 (items' holding period by the anniversary rule) | yes for bought items: `lots.long_term(acquiredOn, soldOn)` (`taxes/panels.py:320`); inherited items are not long-term (U02-12) |
| B23 (floats in money paths; money in cents) | yes in this unit: depreciation a Decimal power (`assets/__init__.py:140-143`), the payoff's invested value in Decimal (`loans/payoff.py:141-148`), explorer and node JSON read with `parse_float=Decimal` (`bitcoin/sources.py:100, 239, 332`); `Item`, `Loan`, `EducationPlan.stateDeduction`, `QualifiedExpense.amount` in `Cents`. A float stays only in a projection's input (`ui/education.py:547`), as C40 allows |
| B35 (a repeated address; two misses; Keep kept; each wallet's failure its own) | yes: `taken` in `wallet.extend`, `offChainMissedAt`/`offChainKeptAt` (migration 0021), `sync_all` catches per wallet; tests for each. A removed key now trips the two-miss rule (U02-1); a skipped index is never re-derived (U02-2) |
| B36 (secret check inside descriptors; seeds however separated) | yes, server (`bitcoin/keys.py:299-338`) and browser (`components/wallet.js:27-44`); `test_secrets_are_recognised` covers numbered, comma and descriptor cases |
| B37 (wallet keys bounded; its test) | yes: 200,000 characters, 1,000 entries, gap 1–200 (`ui/wallets.py:53-55, 143-155`); `test_a_wallets_keys_are_bounded` |
| C36 (no wallet read until Settings › Bitcoin is saved) | yes; and the dev stub now waits too, as S17.7 says (review 2's 12.5.5 had the stub exempt; S17.7 changed since, and the code follows S17.7) |
| K13 (a changed node host clears its password) | yes: `ui/settings.py:56-63` clears the stored node password when `bitcoinNodeHost` changes |
| P3 (attaching a receipt needs write on it) | yes in this unit: `receipts.to_attach` in `ui/items.py:634` and `ui/education.py:473` |
| A24 (ten rounds; 15 keys; a deleted transaction not recorded again) | yes: `ROUNDS = 10`, `len(parsed) <= 15`, `have` counts deleted rows (`bitcoin/sync.py:25, 197-203`, `descriptor.py:209`) |
| A25 (term 1–600, rate 0–40%, half up, under $1 with the last payment) | yes: `ui/loans.py:332-335`, `loans/__init__.py:48-49, 367-369` |

## Checked and sound

- Address and key handling: base58check and bech32/bech32m decoding with the version/constant
  pairing, segwit program lengths, mainnet only with testnet refused by prefix; BIP32 public
  derivation (no hardened child from a public key); the three script types from xpub, ypub,
  zpub; `script_of`/`address_of_script` round trips; Core descriptors from a ypub/zpub turned
  into an xpub with the right wrapper.
- Descriptors: BIP 380 checksum; BIP 86 taproot tweak with the even-y internal key; multisig
  witness script `OP_k <keys> OP_n OP_CHECKMULTISIG` with sorted keys for `sortedmulti`;
  `sh(wsh())` and taproot script trees refused with a reason; one ending across a multisig's keys.
- The secret check runs before anything else in `put_wallet`, never repeats the text, and
  request validation errors carry only the message, not the input (`errors.py:103-112`).
- Esplora paging (25 confirmed a page, `txs/chain/<last>`), Electrum's TOFU (refused unless the
  confirmed fingerprint matches; Test bypasses only to show it), Electrum connecting to the
  address the egress guard checked, Core's per-chain descriptors with ranges.
- Recording: 6 confirmations (unknown depth taken as deep), one row per txid, deleted ones never
  again, the fee as a sale beside a fee of the same amount, valued later when no price yet;
  BEGIN IMMEDIATE keeps an hourly read and **Check now** from recording a txid twice.
- Bitcoin transfer pairs: same quantity, other account, within 3 days, rejected pairs not
  proposed again; confirming carries the out's lots (acquired day and basis) into the in.
- Loans: level payment, monthly and daily interest, the HELOC's interest-only rows and
  re-amortization after the draw, ARM resets and recasts in the schedule ahead (level between
  changes), the last payment taking what rounding left, a typed split that must add up, linking
  needs write on the bank account and an equal amount, candidates within 2% over 90 days in
  accounts the caller can write.
- Payoff planner: monthly (from/until), yearly, lumps on the first payment day on or after
  them, biweekly as a twelfth, rounding up, recast with its fee taken off interest saved, the
  invested comparison compounded monthly to the plan's payoff; one plan followed at a time.
- 529: contributions per contributor per year against each year's exclusion, the 15-year date,
  rollover limit used by transfers to a `roth-ira`, beneficiary and contributors limited to
  people the caller can see, expenses' kinds and a tax year of their own.
- Items: purity parsing (.9999, 99.99%, 999.9, 22k), fine ounces in three units, spot ×
  (1 + premium), valuations' latest counting and stale after 365 days, depreciation from the
  basis until a valuation replaces it (rate checked 0 < r < 100, so no `0 ** 0`), improvements
  and closing costs in the basis by date, sale gain, collectables and the personal-use loss on
  the 8949 row, metals summarised by what is held.
- Access: every route checks the account (read to view; write to change, sync, pay, plan, sell,
  attach); bitcoin transfer pairs are answered by their owner only.

## Read lightly or not read

- `web/ui/components/edu.js`, `items.js`, `loan.js` and `payoff.js`: read in part (the parts
  each claim cites, the fields and the summaries); not every dialog line.
- Bitcoin Core: whether Core tops up an imported ranged descriptor itself (so the range check in
  `Core.wallet` rarely re-imports, each re-import rescanning from block 0) could not be run;
  `importdescriptors`' per-request results are not checked. Electrum and Core were read, not
  run (no node here).
- Esplora's request count for a long-used wallet (every address, every round, up to ten rounds
  an hour) against mempool.space's limits: not measured.
- `budgets/__init__.py` (`_count_loan_payment`) and `taxes/panels.py` were read only where this
  unit's loans, items and 529s feed them (units 04 and 05).
- Tests: `test_wallets.py` and `test_loans.py` read in the parts used; `test_assets.py`,
  `test_education.py`, `test_descriptors.py` by their test names.
- Migration 0009 skimmed (its tables match the current ones).

## Work pad: severity, confirmations, status

| Id | Kind | Req | Sev | Conf | Status | Description |
|---|---|---|---|---|---|---|
| U02-1 | bug | S1.6.1.3, S1.6.2.7 | Med | 0 | open | Taking a key out of a wallet marks its recorded transactions *no longer on the chain* and alerts |
| U02-2 | bug | S1.6.1, S1.6.1.2 | Low | 0 | open | An address typed as well as derived, then taken out, is never watched again |
| U02-3 | bug | S1.6.2.3 | Low | 0 | open | An Electrum read that spans a new block takes the header notice for an answer and fails |
| U02-4 | wrong figure | S1.9.1, S1.9.3 | Med | 0 | open | A HELOC in its draw period shows a $0 payment, and no bank debit is offered to link |
| U02-5 | wrong figure | S6.10.5, S1.9.5 | Low | 0 | open | The followed plan's rounding up still counts PMI after it ended (B21's remainder) |
| U02-6 | wrong figure | S1.9.3 | Low | 0 | open | After a reset or recast, one extra payment makes every later payment count as overpaid |
| U02-7 | differs | S1.9.7.1 | Low | 0 | open | A split loan payment always counts in the shipped categories; the loan can't name them |
| U02-8 | not built | S1.9.1, S1.9.6 | Low | 0 | open | An ARM's caps and a mortgage's points are kept nowhere |
| U02-9 | wrong figure | S1.8.3, S1.8.4 | Low | 0 | open | A 529's rollover to a Roth IRA counts as a distribution not covered by expenses |
| U02-10 | wrong figure | S1.8.4 | Low | 0 | open | What could still roll over to a Roth IRA leaves out the earnings on old contributions |
| U02-11 | wrong figure | S1.8.2 | Low | 0 | open | A five-year election above 5× the exclusion is spread, not counted in its first year |
| U02-12 | wrong figure | S1.10.1, S1.10.5 | Low | 0 | open | An inherited item sold within a year goes on Form 8949 as short-term |
| U02-13 | untraced | — | Low | 0 | open | An item's month-end value history is worked out on every read and never shown |
| U02-14 | bug | S1.6.1.4 | Low | 0 | open | A wallet's descriptor is listed as an "Address" |
| U02-15 | wrong figure | S1.9.3 | Med | 0 | open | A payment recorded on the loan alone, then linked as the guide says, counts twice |
| U02-16 | differs | S1.6.2.6, S1.6.2.7, S1.9.3 | Low | 0 | open | The wallet and loan guides misstate the fee, the two-miss rule and the candidates' rule |
| U02-17 | wrong figure | S1.6.2.6, S14.9 | Low | 0 | open | A bitcoin transaction is dated in the server's zone, not its owner's |

**Counts:** 17 claims. High 0, Med 3, Low 14. By kind: wrong figure 9, bug 4, differs 2, not
built 1, untraced 1, test gap 0, security 0, privacy 0. None withheld; none needs the user
(U02-7, U02-8 and U02-10 each offer a documents-side alternative to choose at the walk-through).
Scratch runs in the job's `tmp/u02/` (`t/test_u02_wallets.py`, `t/test_u02_loans.py`,
`loans_check.py`).

**Ended:** Oct 24, 08:12 PM.

## Found while checking

(Unverified: noticed by the checker, in no claim; the sweep checks each, §8.)

### U02-F1: a loan payment can be linked to a row of the loan's own account

- **Kind:** bug. **Severity:** Low. **Req:** S1.9.3 ("Bank transactions … are offered on the
  loan's screen to link as its payments").
- **Code:** `web/server/src/moolakata/ui/loans.py:480-484` (`add_payment`): the `transactionId`
  is checked for freedom, write access and the amount, never for being in another account:
  ```text
  other = s.get(Transaction, body.transactionId)
  if other is None or other.deleted or other.transferId:
      raise refuse("transactionId", "not-found", "That bank transaction isn't free.")
  access.account(s, c.id, other.accountId, "write")
  if other.amount != -body.amount:
  ```
  while `candidates` leaves the loan's own account out (`x.id != a.id`, `:553`), so only a
  request made by hand reaches it.
- **What goes wrong:** posting a `transactionId` of a draw (a negative row) in the loan's own
  account pairs it with the new payment row, both in the same account, and the payment's
  parts are split by the schedule though no money came from a bank: the balance and the
  schedule take a payment that is the draw's mirror.
- **Remedy:** refuse a `transactionId` in the loan's own account or in any loan account.

- **Check:** confirmed. **Severity now:** Low. Read `ui/loans.py:455-500` (`add_payment`): a `transactionId` is checked for free (`not deleted`, no `transferId`), for write access and for the amount, and `other.accountId` is compared with neither the loan's own account nor any loan account; `candidates` leaves the loan's account out (`x.id != a.id`, `:553`, and `not loans.is_loan(x.type)`), so only a hand-made request gets there. `body.fromAccountId` is not compared with the loan either. The pairing then makes the loan-side row `kind="transfer"` and splits it by the schedule. Reading alone; a user with write on the loan is needed, so Low.
