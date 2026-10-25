# Code review 3, unit 04: projections-taxes

**Session:** Oct 24, 08:35 PM to 08:50 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S6 (projections: goals, assumptions and bitcoin models, the Monte Carlo
  engine, what a projection is built on, tracking and alerts, sharing, the server's
  computation, the loan payoff planner S6.10 being unit 02's code), S8 (taxes: Form 8949
  boxes, exports CSV/TXF/PDF, gains, issues, income, retirement, deductions, giving,
  property, 529, gift tax, education, Form 8615, tax books and filers, sharing, dependents,
  filings and due dates, documents, carry-forwards, what it never does, network fees), with
  the README lines they rely on (R1.9 money and S6.9's float exception, R1.8 sharing, R3.4).
- **Code (8,415 lines, 25 files):** `src/projections/` (`__init__`, `assumptions`, `bitcoin`,
  `engine`, `taxtables`); `src/taxes/` (`__init__`, `books`, `closed`, `dates`,
  `dependents`, `exports`, `panels`); `src/store/entities/projections.py`, `taxes.py`;
  `src/store/tables/projections.py`, `taxes.py`; `mig/0003_tax_book_dependents.py`,
  `mig/0023_edits_after_filing.py`; `src/ui/projections.py`, `taxes.py`, `taxpanels.py`;
  `ui/components/plans.js`, `taxpanels.js`; `ui/screens/projections.js`, `taxes.js`.
- **Tests (1,479 lines):** `test_golden.py`, `test_projections.py`, `test_taxbooks.py`,
  `test_taxpanels.py`; golden files `tests/golden/form-8949-2026.csv`,
  `form-8949-review-2026.csv`, `moolakata-2026.txf` (the exports' evidence).
- **Guides:** `projections`, `portfolio-projections`, `taxes-summary`, `-gains`, `-income`,
  `-retirement`, `-deductions`, `-giving`, `-property`, `-education`, `-documents`,
  `-filings`, `-issues`, `forms`, `dialog-new-projection`, `-plan` (unit 02's payoff plan,
  read lightly), `-estimate`, `-tax-book`, `-tax-document`, `-filing`, `-dependent`.
- **Cites no section:** `store/entities/projections.py`, `store/entities/taxes.py`, and
  `taxes/__init__.py` (judged when read).
- Shared with earlier units, not raised again: U02-12 (an inherited item short-term on Form
  8949, `panels.py:318-336`), U03-5 (a wash sale from another account changes a filed year,
  `closed.py:60-63`), U03-13 (Gains tab's mixed-term position), U01's importers. The loan
  payoff code (`loans/payoff.py`, S6.10) is unit 02's.

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 829 lines (9%), 3 new files (`taxes/closed.py` 119, `taxes/dates.py` 51,
`mig/0023` 86). The diff (renames aside) is in the job's `tmp/u04/delta.diff`. Where it is:

- `taxes/closed.py` (new, N5, S2.8): the closed-year guard: gains before and after an edit,
  refused with the years named, *anyway* recorded on the book (S2.8.3); `mig/0023` and the
  `EditAfterFiling`-style rows in `store/tables/taxes.py`, `entities/taxes.py`.
- `taxes/dates.py` (new, B22, S8.15): the federal due date moved past weekends, federal
  holidays and Emancipation Day.
- `taxes/books.py` (+39/−8): `counted()` reads an added account only for those who can see
  it, and last year's book only when every filer accepted (P1); `expected()`.
- `taxes/panels.py` (+129/−20): the wash-sale rows, Form 8949's digital-asset boxes,
  option reviews, items (B22's anniversary rule), the retirement limits per person (B15),
  deduction splits' sign (B4), the issue *edits since filing* (S2.8.3).
- `taxes/exports.py` (+27/−4): TXF leaves out C, L and G–L rows and counts them (§12.5.2).
- `ui/taxes.py` (+55/−13): creating a book copies last year's added accounts only with
  every filer's acceptance (P1); adding an account needs a filer (P7); a filing's amended
  return settles the edits after filing (S8.15).
- `ui/taxpanels.py` (+43/−6), `ui/components/taxpanels.js` (+45/−6): the retirement per
  person panel, issues for edits since filing, the exports' counts.
- `projections/__init__.py` (+57/−18): the bitcoin model on bitcoin only (B14), Decimal start
  value and tracking (C40, B23), the floor as a minimum width (B22); `engine.py` (+10/−3);
  `taxtables.py` (+47/−3): figures for earlier years (B17); `ui/projections.py` (+44/−6):
  inputs bounded (B37).
- Tests: `test_golden.py` new (307), `test_taxbooks.py` +232, `test_taxpanels.py` +99,
  `test_projections.py` +109.

### 3. Earlier reviews' findings in this area

Review 1: nothing in S6 or S8. Review 2, all marked done in §12.2 unless said: **P1** (last
year's book leaks a non-consenting filer), **P7** (a write helper adds accounts; a tax book
shared to a linked server, and only its creator changes its sharing; a shared projection
shows the owner's account values), **P8** (Activity misses receivers; unit 07's code, the
tax-book side checked here), **B3** (a reinvested dividend counted twice on the income
panel), **B4** (deduction splits' sign), **B14** (bitcoin model on all crypto), **B15**
(retirement limits per account, not per person), **B16** (gift-tax flag; its S8.11 side
here), **B17** (a book before the earliest shipped year uses 2025's figures), **B22** (TXF
codes, decided as §12.5.2; tax due dates and holidays; the tracking floor), **B23**
(projection floats, `EstimatedPayment.amount` in cents), **B37** (projection inputs bounded),
**N5** (closed years), **N13** (a tax document's file through its book), **N14** (moved to
L7: projected contributions capped by limits), **C34** (tax book to a linked server, read
only), **C40** (S6.9's float exception), **C41** (crypto volatility spreads every model;
log-normal), **C42** (a spouse needs both people's confirmation), **C50** (8949's
digital-asset boxes). §12.2's test row: B3, B4, B15 tests asked for. Each re-checked below.

### 4. Phase 1 claims and decisions on these sections

- **D1-25** (needs the user, Med): who sees a tax document's file: filers only (S9.6) or
  also write helpers / every reader of the book (S8.14.3, S10.3). Judged against both.
- **D2-2** (needs the user, Med): a tax book's document files across a link (S11.4 vs
  S11.5.1, L6); noted where the code bears.
- **D1-4** (S6.5 and S6.4.2's "later" items with no L id), **D1-8** (S1.4 cites S8.6 for
  limits), **D1-9** (where a possible wash sale is listed: S8.3 or S8.4), **D1-17** (S8.7
  "above" vs S8.9 "$250 or more"), **D1-18** (one active projection per savings target),
  **D1-19** (the 4% rule undefined), **DC-14** (the federal due date not in S16.11's list),
  **D2-5**, **D2-9** (projections on a linked server): documents; what the code does is
  noted where it bears.
- No decision recorded yet; none is a §6 gate.

### 5. Untraced candidates and uncited first-level items

- Untraced candidates: `store/entities/projections.py`, `store/entities/taxes.py`,
  `taxes/__init__.py` (no cite).
- Uncited first-level items: S6.2, S6.5, S6.6, S8.10; judged below under **Uncited
  first-level items**.

## Claims

(Work-pad ids U04-n; kinds and format per §7. Severity, confirmations (0) and status (open)
are in the table at the end.)

### U04-1: a savings target less than a year away names a monthly saving that reaches half of it

- **Kind:** wrong figure. **Req:** S6.2.3 ("the monthly saving that would"), S6.4.2.4 ("the
  monthly saving that reaches the target with a 90% chance"), S6.4.2.1 ("A target date
  part-way through a year counts that part of it").
- **Code:** `web/server/src/moolakata/projections/engine.py:207-222`, the bisection's upper
  bound is one year's saving equal to the target:
  ```python
  def needed_saving(plan: Plan, target: float, at_index: int, chance: float = 0.9) -> float:
      ...
      lo, hi = 0.0, max(target, 1.0)
      ...
      for _ in range(40):
          mid = (lo + hi) / 2
          ...
          if (path[:, at_index] >= target).mean() >= chance:
              hi = mid
          else:
              lo = mid
      return hi
  ```
  while `projections/__init__.py:229-236` makes a date under a year away one part-year
  (`target_index = 1`, `last_part = span`), and `_simulate` (`engine.py:127-130`) adds only
  `contribution * part` in it. When even `hi` misses, the loop never tests above it and
  returns `hi` as if it were enough.
- **What goes wrong:** Case (run): today Oct 13, 2026; a $12,000 car by Apr 13, 2027, from
  nothing in cash. The answer says *$1,000 a month would reach it with a 90% chance*; run again
  at $1,000 a month, the chance is 0% and the median at the date $5,979. It needs about
  $2,000 a month. Any target under a year from a small start is off by the share of the year
  left; the headline figure the user acts on is wrong.
- **Run:** yes, `tmp/u04/t/test_u04p.py::test_savings_under_a_year`: `neededMonthly` 1000.0,
  then chance 0.0, median 5979.47 (`tmp/u04/run1.txt`).
- **Remedy:** start `hi` at a bound that is enough (`target / last_part` for a one-year
  target, or double `hi` until the chance is met before bisecting); a test with a target
  months away.
- **Alternatives:** compute the saving for a part-year in closed form (what is missing at the
  date divided by the months left), the bisection only for longer ones.

### U04-2: a projection built on a loan or a physical-asset account counts the loan's payments as cash and leaves the items out

- **Kind:** wrong figure. **Req:** S6.1.1 ("it starts from their **current values**"),
  S6.4.2.2 (the mix), S1.9, S1.10 (a loan's value is what is owed, an item's what it is
  worth).
- **Code:** `web/server/src/moolakata/projections/__init__.py:113-119`, `built_on()`:
  ```python
  for a in accounts:
      ledger = repo.load(s, a)
      investing = atypes.investing(a.type)
      cash = ledger.balance()
      by_class["cash"] = by_class.get("cash", Decimal(0)) + cash
      if not investing:
          continue
  ```
  A loan's ledger balance is what was paid into it, and a physical-asset account's items are
  never read; `valuation.account_value` (what the portfolio row shows) uses `loans.value` and
  `assets.value` for them, and `tracking()` (`:470-472`) uses `valuation.series`, which does
  too. The same pattern as unit 03's U03-9 (the portfolio's Holdings tab), here in the
  projection's start value and mix.
- **What goes wrong:** Case (run): a portfolio *Both* of checking ($5,000) and a mortgage with
  one $2,000 payment in it. The portfolio's value is $5,000; a savings projection built on it
  starts from **$7,000**, all of it cash. After five years of payments the start holds every
  payment ever made as cash growing at the cash return, a house is left out, and tracking (which
  values the loan and the items properly) is compared against a baseline from another
  figure (its `scale` hides the gap at the start, not the different growth).
- **Run:** yes, `tmp/u04/t/test_u04p.py::test_projection_on_checking_and_mortgage`:
  portfolio value 5000.00, projection `start` 7000.00, weights `{cash: 1.0}`.
- **Remedy:** `built_on()` values each account as `valuation.account_value` does: cash from
  bank and investing accounts only, a loan at minus what is owed (or left out, said under the
  chart), a physical-asset account at its items' value in the real-estate or metals class.
- **Alternatives:** refuse loans and physical-asset accounts in what a projection is built on,
  and leave them out of a portfolio's projection, saying so.

### U04-3: a bitcoin model's growth is applied a year early

- **Kind:** wrong figure. **Req:** S6.3.1 ("Each model gives a median path from today's
  price"), S6.4.2.3 ("A bitcoin model sets the median growth of the bitcoin each year").
- **Code:** `web/server/src/moolakata/projections/__init__.py:243-247` builds `crypto_path`
  as the growth from year *k* to *k+1* at index *k*:
  ```python
  prices = bitcoin.median_path(
      model, taxtables.figures(s, year), btc_now, list(range(year, year + years + 1))
  )
  if prices:
      crypto_path = [b / a for a, b in itertools.pairwise(prices)]
  ```
  and `engine.py:90` and `:108` read index *t* for the growth that brings the balance to year
  *t* (`_simulate`, `:125-128`: index *t* is "the balance t years on, after that year's
  growth"), so year *t* gets the growth of year *t* to *t+1*:
  ```python
  ratios = np.array(plan.crypto_path[: plan.years])
  ```
  The first year's growth (`ratios[0]`) is never used.
- **What goes wrong:** Case (run): stock-to-flow from Oct 2026 steps up about ten-fold at the
  2028 halving (its model price is 101.7k in 2027, 1,019k in 2028); the projection's expected
  path makes that jump in 2027 (100 → 1,001.9) a year before the model does. Every model is
  shifted the same way; for the smooth ones (power law, log regression) the error is a year's
  difference in the growth rate, for stock-to-flow a whole halving step.
- **Run:** yes, `tmp/u04/t/test_u04p.py::test_s2f_step_year` (`tmp/u04/run1.txt`).
- **Remedy:** `crypto_path[t-1]` for year *t* (or prepend 1.0 to the ratios), in `_returns`,
  `_expected_return` and `scenario_paths`; a test that the projection's bitcoin follows the
  model's price for the same year.
- **Alternatives:** none needed.

### U04-4: scenarios can't be compared side by side (S6.6)

- **Kind:** not built. **Req:** S6.6 ("**Scenarios compare** side by side, for example
  retiring at 60 against 65, or contributing $500 more a month"); uncited first-level item.
- **Code:** `web/ui/screens/projections.js:1-3` ("the active plans being followed and the
  scenarios, one at a time below them") and `:88-89`, one `Detail` for the chosen projection:
  ```js
  ${current
    ? html`<${Detail} key=${current.id} id=${current.id} reloadList=${list.reload} />`
  ```
  No route or screen sets two projections' answers or fans beside each other; the only
  comparison is the bitcoin models' (`/bitcoin-models`, S6.3.1.1). No milestone, gap or later
  item schedules it.
- **What goes wrong:** to weigh retiring at 60 against 65 a user opens one, notes its chance
  and median at retirement, opens the other, and compares from memory; the list rows give the
  headline only.
- **Run:** no, reading alone (`grep -i compare` over the screen and its guide).
- **Remedy:** a *Compare* view: two or more projections of the same goal, their answers in a
  row and their median paths on one chart.
- **Alternatives:** S6.6 says the list's headlines are the comparison, and the side-by-side
  goes to `later.md` with an L id.

### U04-5: the Inputs form can't set several things S6 names: other income, its age, the horizon, a birth year, several accounts, a projection's own assumptions

- **Kind:** differs. **Req:** S6.1.1 ("Built on chosen accounts"), S6.1.2 (contributions: "an
  amount, its frequency, growth per year, and until when"), S6.2.1 (each person's birth year
  and retirement age; other income "Social Security from an age, a pension, each with its
  amount"; the horizon "age 95 by default"), S6.3 ("Every projection uses them unless it
  overrides a figure").
- **Code:** `web/ui/screens/projections.js:388-404`, other income is only the rows already
  there, each with its monthly amount:
  ```js
  ${(f.income || []).map((/** @type {any} */ inc, /** @type {number} */ i) =>
    ...
        <${Field} label=${`${inc.label || 'Other income'} a month`} id=${'income-' + i}
          help="other-income"
          hint=${`From age ${inc.fromAge}, rising with inflation`}>
  ```
  `NewProjection` (`:608-615`) creates one *Social Security* row from 67 and no way to add a
  pension, remove a row or change `fromAge`; no field sets `horizonAge`, a person's
  `birthYear` (the hint shows it, `:337`), or `overrides` (which `prepare()` reads,
  `projections/__init__.py:181-186`); `BuiltOn` (`:522-527`) picks one account
  (`{ kind, ids: [id] }`), so several accounts only come through a portfolio; contributions
  are "per year" until retirement, with no frequency or end.
- **What goes wrong:** a couple with a pension from 60 and Social Security at 70 can't enter
  either; a user born in a year Profile doesn't hold (or a partner whose birthday is unset,
  `:603`, takes the user's) can't correct it; a user who wants 95 changed to 100 can't. The
  server takes every one of these (`_check_inputs`), so only the screen is missing them.
- **Run:** no, reading alone.
- **Remedy:** the form adds and removes other-income rows (label, person, from age, monthly,
  rises with inflation), shows birth year and horizon as fields, picks several accounts, and
  offers the per-projection overrides of S6.3 under an *Assumptions* fold.
- **Alternatives:** S6.1.2 drops frequency and "until when" (contributions are yearly until
  retirement or the date, as S6.4.2.1 has them), and S6.3 drops per-projection overrides but
  fees and the bitcoin model.

### U04-6: making an education projection active turns off the other one for the same person without asking

- **Kind:** differs. **Req:** S6.7.1 ("Making one active asks before turning off the one it
  replaces").
- **Code:** `web/ui/screens/projections.js:568-578`, the dialog names a replaced plan only for
  retirement, and even then without knowing it is the same subject:
  ```js
  const others = (/** @type {any[]} */ (list.data) || []).filter((r) =>
    r.active && r.goal === p.goal && r.id !== p.id && r.level === 'owner'
  );
  ...
      <p style=${{ marginTop: 0 }}>${others.length && p.goal === 'retirement'
        ? html`<b>${others[0].name}</b> stops being the active plan for the same people, if
          they are the same. Its tracking ends, and it stays as a scenario.`
        : 'It becomes an active plan.'}</p>
  ```
  while the server (`ui/projections.py:361-371`) replaces by `projections.subject()`, which
  for education is the beneficiary (`projections/__init__.py:415-417`).
- **What goes wrong:** *Emma's college (public)* is active; the user makes *Emma's college
  (private)* active; the dialog says "It becomes an active plan", and the first one's
  baseline and tracking are dropped (`other.baseline = None`), which can't be undone. For
  retirement, two plans for different people both show the warning naming the first active
  one, "if they are the same".
- **Run:** no, reading alone.
- **Remedy:** the server says what would be replaced before it acts (a `GET …/activate`
  preview, or `activate` answering 409 with the name unless `confirm` is passed), and the
  dialog names exactly that plan, for every goal.
- **Alternatives:** the dialog computes the subject the same way, from the list's inputs.

### U04-7: a projection's unchecked inputs answer 500, and a typed mix may be levered

- **Kind:** bug. **Req:** S13.8.3 (problems as problem+json, a field's error named), S6.4.2.2
  (a typed amount "gives its own mix").
- **Code:** `web/server/src/moolakata/ui/projections.py:200-261`, `_check_inputs()` checks
  neither `withdrawal.amount` nor `withdrawal.percent`, `overrides`, `income[].person`, nor a
  typed `builtOn.allocation`; `projections/__init__.py:85-92` takes the mix as given:
  ```python
  mix = spec.get("allocation") or {"usStocks": 60, "bonds": 40}
  total = sum(mix.values()) or 1
  ```
- **What goes wrong:** Case (run): `withdrawal: {method: fixed, amount: "lots"}`,
  `overrides: {inflation: "x"}` and `income: [{person: "x"}]` each raise in the engine
  (`ValueError`, `TypeError`), an unhandled 500 with an error id in place of a 422 naming the
  field; a typed allocation `{usStocks: 300, cash: -200}` is accepted (201) as weights 3.0 and
  −2.0, a levered portfolio no screen can show. The transaction rolls back, so nothing bad
  is stored; the browser's form sends none of these.
- **Run:** yes, `tmp/u04/t/test_u04p.py::test_unchecked_inputs` (`tmp/u04/run2.txt`).
- **Remedy:** `_check_inputs` checks every key `prepare()` reads: amounts and percents as
  numbers in range, `person` an index of `people`, overrides as `assumptions.check` checks a
  class, and an allocation's shares as numbers of 0 or more summing to more than 0.
- **Alternatives:** a pydantic model for the inputs, so the OpenAPI document states them too.

### U04-8: a shared projection names the owner's account a viewer isn't shared, and shows its mix

- **Kind:** privacy. **Req:** S6.1 ("a viewer sees its results, and the values and tracking of
  only the accounts shared with them"), S10.3, S5.1.1. Review 2's P7 (third point), marked
  done for tracking.
- **Code:** `web/server/src/moolakata/projections/__init__.py:188` builds on the owner's
  accounts for every viewer, and `:106-110` labels a single account by its name:
  ```python
  base = built_on(s, viewer if viewer == p.ownerId else p.ownerId, json.loads(p.builtOn))
  ...
  label = (
      (accounts[0].name if len(accounts) == 1 else f"{len(accounts)} accounts")
  ```
  `compute()` (`:284-289`) sends `start`, `builtOnLabel` and `weights` and
  `ui/projections.py:99` sends `builtOn` (the account ids) to any viewer; `tracking()` alone
  narrows to the viewer's accounts.
- **What goes wrong:** Alice shares *Retire at 62*, built on her *Fidelity Rollover IRA*,
  with Bob, who isn't shared the IRA. Bob's list and detail read "on Fidelity Rollover IRA",
  "Starts from $812,400 (US stocks 72%, bonds 20%, crypto 8%)". The total is arguably a
  result (the fan starts there), but the account's name and its asset mix are what S5.1.1
  hides in a portfolio. Low: a name and a mix, never a transaction.
- **Run:** no, reading alone.
- **Remedy:** for a viewer who isn't shared every account, the label is the count ("2
  accounts", or "accounts not shared with you"), `builtOn` carries no ids they can't see,
  and the weights are left out (or stated as the projection's mix, not the accounts').
- **Alternatives:** S6.1 says a share of a projection shows what it is built on, by name and
  mix, and the total.

### U04-9: an education goal for `{kind: user}` takes any user, a private or remote one's person included

- **Kind:** privacy. **Req:** S10.10.2 (a private person is seen through a share), S10.3.3.1
  (a remote user's person "is used only for gifts"), S6.2.2.
- **Code:** `web/server/src/moolakata/ui/projections.py:180-186`, a person is checked for the
  caller's level, a user only for existence:
  ```python
  if who.get("kind") == "person":
      ...
      return [] if p is not None and people.level(s, user_id, p) is not None else bad
  if who.get("kind") == "user":
      return [] if s.get(User, who.get("id") or "") is not None else bad
  ```
  and `projections/__init__.py:334-340` then reads that user's person's name and birth year
  into the answer (`name`, `firstYear` = birth year + start age).
- **What goes wrong:** Bob posts an education projection with `beneficiary: {kind: "user",
  id: <a remote user's id, as the share picker lists it>}`; the answer names that person and
  gives their birth year (as `firstYear − 18`), though the person is private or a linked
  server's. The browser never sends `kind: user` (its picker lists persons), so this is the
  API only. Low: a name and a year.
- **Run:** no, reading alone.
- **Remedy:** `kind: user` resolves to the user's person and checks `people.level` as a person
  does, local users only; or the API takes persons only.
- **Alternatives:** none needed.

### U04-10: a filed year's gains move unasked and unrecorded when the change isn't a hand edit: an import, a deleted account, *both real*, a matched transfer

- **Kind:** differs. **Req:** S2.8 ("An edit that changes a closed tax year's realized gains
  asks for confirmation first"), S2.8.2 ("a transaction added, changed or deleted, an option
  trade or its end, a corporate action"), S2.8.3, S8.4 (edits since filing among the issues),
  S8.15 (*Changed after filing*).
- **Code:** `web/server/src/moolakata/taxes/closed.py:55-63`, the guard is something a route
  makes and checks; only the transaction routes (`ui/transactions.py:608, 737, 817`) and the
  option routes (`ui/options.py:71, 141, 331`) make one:
  ```python
  class Guard:
      """Made before an edit and checked after it: when the edit moved a closed year's gains
      and isn't confirmed, refused with the years named (409 closed-year), ...
  ```
  `grep` finds no use of `closed` in `ui/imports.py`, the connector's posting, `ui/accounts.py`
  (`delete_account`, `:585-600`, soft-deletes the account, and `books.counted()` then drops it,
  `books.py:117-123`), nor `ui/transactions.py:894-950` (`link_transfer`, `both_real`).
- **What goes wrong:** Case (run): Alice's brokerage sold 10 VTI in 2025 for a $500 gain; her
  2025 federal return is filed. She deletes the account (it moved to another broker): the
  answer is 200 with no question, the 2025 book's Schedule D goes from $500 long-term to $0,
  and its Issues list nothing. Read alone, the same holds for: importing a statement or CSV
  that adds a 2025 sale she had missed (the classic reason to amend), a Connection's sync
  posting one, marking two identical sells *both real*, and matching a transfer that carries
  shares' basis into an account with a 2025 sale. U03-5 (a wash sale from another account) is
  the same gap by another path; this claim is the routes that never make a guard.
- **Run:** yes for the deletion, `tmp/u04/t/test_u04t.py::test_deleting_an_account_moves_a_filed_year`
  (`tmp/u04/run3.txt`: Schedule D 0.00 after the delete, no issue); the rest reading alone.
- **Remedy:** take the guard into the ledger's write path (the repo's add, change and delete,
  which imports, syncs and routes all use) or into the unit of work: before commit, compare
  the closed years' gains of every account the request touched with their values at its
  start. An import or a sync that would move a closed year stops at its review step with the
  years named and *Import anyway*; a sync records the change (S2.8.3) and alerts, as it can't
  ask. Deleting an account with a closed year asks the same question.
- **Alternatives:** a closed year's gains are snapshotted when the federal return is marked
  filed, and the tax book compares the live figure with the snapshot on every read, listing
  any difference as *changed after filing* whatever made it (this catches U03-5 too).

### U04-11: "From last year" reads the first last-year book that shares a filer: a book the filer never accepted, or one of two

- **Kind:** wrong figure. **Req:** S8.14.4 (a new book copies "from the year before"),
  S8.17 (the next tax book shows last year's carried figures, its capital-loss carryover in
  the Summary, the 8606 basis), S8.14.1 ("A user named as a filer by someone else accepts
  before the tax book ... shows anything from their year before"), S8.14 ("a couple filing
  separately has two").
- **Code:** `web/server/src/moolakata/taxes/books.py:331-344`:
  ```python
  mine = {f.userId for f in filers(s, book)}
  for b in s.scalars(
      select(TaxBook)
      .where(TaxBook.year == book.year - 1, TaxBook.deleted == false())
      .order_by(TaxBook.createdAt)
  ):
      if mine & {f.userId for f in filers(s, b)}:
          return b
  ```
  Any filer row counts, accepted or not, and only the first book is returned; `expected()`,
  `carried_from_last_year()`, `ui/taxes.py:_from_last_year` (accounts and dependents copied)
  and the panels' last-year tax all read it. Nothing stops a user being a filer on two books
  of a year (`create_book`, `ui/taxes.py:112-161`). (Beside it: `expected()`, `books.py:274-289`,
  turns last year's documents into expected ones whether or not *Start from last year* was
  ticked, though the new-book dialog and its guide say the switch does it.)
- **What goes wrong:** Cases (run):
  1. Married, filing separately in 2025: Bob first made a joint 2025 book naming Alice, which
     she never accepted (AGI $250,000, long-term carryover $9,000), then Alice made her own
     (AGI $60,000, carryover $1,200). Alice's 2026 book shows *From last year*: AGI
     **$250,000**, carryover **$9,000**: Bob's, from a book she can't open (404), and none of
     hers. Her Summary's carryover and her expected documents follow the wrong book too.
  2. Separate in 2025 (Alice $1,200, Bob $9,000 carryover), joint in 2026: the joint book
     shows Alice's $1,200 only; Bob's $9,000, which a joint return carries, is missing, and
     only Alice's accounts and dependents are copied.
- **Run:** yes, `tmp/u04/t/test_u04t.py::test_previous_takes_the_first_book_sharing_a_filer`
  and `::test_separate_then_joint` (`tmp/u04/run3.txt`).
- **Remedy:** last year's books are those where each filer of this book was an **accepted**
  filer; with several (separate then joint), *From last year* lists each with its filers'
  names, the Summary sums the carryovers, and the copy takes accounts and dependents from all.
  `create_book` refuses a second book of the same year for a filer already on one (or warns,
  as dependents are flagged, S8.14.5.2).
- **Alternatives:** the new-book dialog asks which of last year's books to start from when
  there is more than one.

### U04-12: saving the amended return again settles edits made after it was filed

- **Kind:** differs. **Req:** S8.15 (*Changed after filing*: an amended federal return
  "settles every change made before it"; "A later edit made anyway, once the year is closed
  again (S2.8.1), is listed afresh").
- **Code:** `web/server/src/moolakata/ui/taxes.py:842-845`, called from both `add_filing`
  (`:837`) and `change_filing` (`:873`):
  ```python
  def _amending(s, c: Caller, b: TaxBook, f: Filing) -> None:
      """An amended federal return settles the edits made since the return was filed (S8.15)."""
      if f.jurisdiction == "federal" and f.amendsId:
          closed.settle(s, b, c.id, "amended")
  ```
  and `closed.settle()` (`taxes/closed.py:113-119`) settles every unsettled change, whenever
  made.
- **What goes wrong:** Case (run): the 1040-X is filed Jun 20; the year is closed again. Alice
  makes an edit anyway (+$200 to 2025's gains), listed in Issues. In August the IRS accepts
  the 1040-X and she sets its progress to *Accepted*: the save settles the +$200 as
  *amended*, the issue and the Dashboard's *Needs attention* entry go, though the 1040-X
  never had it in. Typing a confirmation number, a result or a carried figure into the 1040-X
  does the same.
- **Run:** yes, `tmp/u04/t/test_u04t.py::test_patching_the_amended_return_settles_later_edits`:
  the issue before, `[]` after the PATCH (`tmp/u04/run3.txt`).
- **Remedy:** settle on adding an amended federal return, and on changing a filing into one
  (its `amendsId` newly set); otherwise settle only the changes made before the amended
  return was filed (`TaxBookChange.createdAt` ≤ its `filedOn`, or before it was added while
  it is being prepared).
- **Alternatives:** none needed.

### U04-13: a tax document can't be changed, removed or given its file later in the browser; through the API a co-filer can't change one the other filer attached a file to

- **Kind:** differs. **Req:** S8.8 ("each marked received (attach the PDF, S9) or missing"),
  S8.16, S8.14.3 (a helper with write can "attach documents"), S9.3 ("whoever can change one
  of them can detach it from that").
- **Code:** `web/ui/screens/taxes.js:907-920`, the document dialog only adds
  (`api.post(`/tax-books/${b.id}/documents`, …)`); the Documents tab (`:481-580`) offers
  *Attach* for a missing one and nothing on a received or filed one: no edit, no delete, no
  file for a document kept without one, though `PATCH /tax-documents/{id}` and `DELETE` exist
  (`ui/taxes.py:949-976`). And `_doc_values` (`ui/taxes.py:919-920`) re-checks the receipt on
  every change:
  ```python
  if body.receiptId:
      receipts.to_attach(s, c.id, body.receiptId)
  ```
  which needs write on the receipt; a co-filer has read on the other's (`receipts/__init__.py:
  248-249`, `best = "read"`).
- **What goes wrong:** a user who keeps the wrong form (a 1099-INT marked as the 1099-DIV) or
  the right one under the wrong account can't fix or remove it: the checklist shows it
  received for good. A W-2 kept from the checklist before its PDF arrived never gets the PDF.
  Through the API (run), Bob, an accepted co-filer, changing the note on the W-2 Alice
  attached gets **403 receipt-read-only**; a write helper likewise.
- **Run:** the co-filer's 403, yes, `tmp/u04/t/test_u04t.py::test_documents_files_and_helpers`
  (`tmp/u04/run4.txt`); the browser, reading alone.
- **Remedy:** each document row opens the dialog to change its form, issuer, account, notes
  and file, with *Remove*; `_doc_values` checks `to_attach` only when the receipt changes
  (a new `receiptId` differing from the stored one).
- **Alternatives:** none needed.

### U04-14: a write helper attaches a tax document but can't open its file, nor any the filers attached (D1-25)

- **Kind:** differs. **Req:** S8.14.3 (a helper with write "can edit filings, attach documents
  and resolve issues"), S10.3.1 (a tax book share includes "its panels, filings and
  documents"), against S9.6 ("a tax document's file by the tax book's filers (S8.16)").
  Phase 1's D1-25, open: **needs the user**.
- **Code:** `web/server/src/moolakata/receipts/__init__.py:248-249, 289-301`, a tax document
  gives its file to accepted filers only:
  ```python
  if best is None and _on_tax_document(s, user_id, r.id):
      best = "read"  # a tax document's file, for the book's filers (S8.16)
  ...
      if any(f.userId == user_id and f.acceptedAt for f in books.filers(s, book)):
          return True
  ```
- **What goes wrong:** Case (run): Alice and Bob's joint 2026 book is shared with Dave, their
  preparer, at write. Alice attaches the W-2's PDF. Bob opens it (200); Dave gets **404**, and
  so does a grown child helping at read. Dave sees the checklist mark it received, but can't
  read the figures he is preparing from. The code matches S9.6's reading (filers only) and not
  S8.14.3 and S10.3's (the share includes documents). A file Dave uploads himself he owns, so
  he opens his own but not theirs.
- **Run:** yes, `tmp/u04/t/test_u04t.py::test_documents_files_and_helpers` (`tmp/u04/run4.txt`).
- **Remedy:** decide D1-25. If documents go with the share (D1-25's remedy): a tax document's
  file is read by whoever can read the book (`books.level`), and written by those who can
  write it. If filers only: S8.14.3 and S10.3.1 say a helper attaches files but opens only
  their own, and the Documents tab says so beside a file a helper can't open.
- **Alternatives:** write helpers open the files, read shares don't (D1-25's alternative).

### U04-15: a Roth conversion or an IRA-to-IRA transfer counts as a contribution, over the limit; an HSA's employer money and catch-up are left out

- **Kind:** wrong figure. **Req:** S8.6 ("contributions per account against the year's limits
  (with catch-up by age) ... backdoor-Roth steps (non-deductible contribution, conversion
  ...)"), S1.4.
- **Code:** `web/server/src/moolakata/taxes/panels.py:491-508`, a contribution is any positive
  `deposit` or `transfer` without an instrument whose source isn't set otherwise:
  ```python
  Transaction.kind.in_(("deposit", "transfer")),
  ...
  func.coalesce(Transaction.contributionSource, "employee") == "employee",
  ```
  A matched transfer from another retirement account is never told apart (its other half's
  account isn't read); `:527-529` gives an HSA the family limit with no catch-up at 55, and
  the `employee` filter drops an employer's HSA money, which counts against the HSA limit.
- **What goes wrong:** Case (run): Alice converts $50,000 from her traditional IRA to her Roth
  IRA in 2026, the two halves matched as a transfer. The Retirement panel shows the Roth IRA
  *contributed $50,000.00 of $7,500*, **over the limit**, and the traditional IRA flagged with
  it (the person's IRA total); the conversion appears only as a $50,000 distribution. A
  trustee-to-trustee move between two IRAs, or a 401(k) rolled into an IRA without the
  *rollover* source set by hand, does the same. An HSA with $3,000 from the employer and
  $5,000 from the owner shows $5,000 against $8,750 where $8,000 counts.
- **Run:** yes for the conversion, `tmp/u04/t/test_u04t.py::test_roth_conversion_counts_as_contribution`
  (`tmp/u04/run5.txt`); the HSA, reading alone.
- **Remedy:** a transfer whose other half is in a retirement account (or a 529, S1.8) is a
  conversion or rollover, not a contribution, and is listed as such (S8.6's conversion step);
  an HSA counts employee and employer money against the limit, with $1,000 more at 55 (a
  tax-table figure, S16.11), and asks self-only or family on the account.
- **Alternatives:** the transfer dialog sets `contributionSource = rollover` on the receiving
  half whenever both accounts are retirement accounts.

### U04-16: Roth eligibility by MAGI and the backdoor-Roth steps are not built

- **Kind:** not built. **Req:** S8.6 ("Roth eligibility by MAGI as the user enters it,
  backdoor-Roth steps (non-deductible contribution, conversion, Form 8606 figures)").
- **Code:** `web/server/src/moolakata/taxes/panels.py:517-518`, the only trace of either:
  ```python
  if a.type == "roth-ira":
      note = (note + "; " if note else "") + "Roth eligibility depends on MAGI"
  ```
  and the carried 8606 basis (`:581-584`). No field takes a MAGI, no table holds the phase-out
  ranges (S16.11 lists none), and nothing pairs a non-deductible contribution with the
  conversion that follows it. The guide (`web/ui/guides/taxes-retirement.md`, *Contributions*)
  says MAGI "is the preparer's to check", which S8.6 doesn't. No milestone, gap or later item
  schedules it.
- **What goes wrong:** a couple above the Roth phase-out who contribute directly to a Roth IRA
  are never told; a backdoor Roth (a $7,500 non-deductible contribution, converted a week
  later) shows as two unrelated rows and, by U04-15, as over the limit.
- **Run:** no, reading alone.
- **Remedy:** a MAGI field on the book (as typed), the phase-out ranges per filing status in
  the tax tables, and a Roth contribution flagged above them; the backdoor steps as a short
  list: the non-deductible contribution, the conversion matched to it, the 8606 basis carried
  and the pro-rata note when other pre-tax IRA money exists.
- **Alternatives:** S8.6 drops both, the guide's sentence becomes the requirement, and the
  backdoor goes to `later.md`.

### U04-17: foreign tax paid and crypto income are not on the Income panel

- **Kind:** not built. **Req:** S8.5 ("foreign tax paid, and crypto income (staking, rewards)
  at fair value when received").
- **Code:** `web/server/src/moolakata/taxes/panels.py:395-428`, `income()` reads only
  `interest`, `dividend`, `reinvest` and `capital-gain`:
  ```python
  Transaction.kind.in_(("interest", "dividend", "reinvest", "capital-gain")),
  ```
  and `store/tables/accounts.py:51-81` (`TXN_KINDS`) has no kind for foreign tax withheld or
  for a staking or reward receipt; `grep -i "foreign\|staking\|reward"` finds none in the
  server. No milestone, gap or later item schedules them.
- **What goes wrong:** a household holding an international index fund (foreign tax on the
  1099-DIV, box 7, for the foreign tax credit) sees no foreign tax; a wallet's or exchange's
  staking rewards, taxable as ordinary income at their value when received and often reported
  on no form, appear nowhere on the book, and their lots' basis is whatever the import gave.
- **Run:** no, reading alone.
- **Remedy:** a dividend's foreign tax as a field (or a `foreign-tax` kind) imported from OFX's
  `<INCOME>`/1099-DIV data, summed by payer; a `reward` kind for crypto income, valued at the
  day's price, counted on the Income panel and giving the lot that basis.
- **Alternatives:** S8.5 drops both until L-numbered later work, and the Income guide says the
  1099-DIV's foreign tax and any crypto income are the preparer's to add.

### U04-18: options with an unresolved expiry, and crypto without a known acquisition, aren't among the Issues

- **Kind:** differs. **Req:** S8.4 ("options with an unresolved expiry ... crypto without a
  known acquisition, possible wash sales the rules leave to the preparer (S3.8.5)").
- **Code:** `web/server/src/moolakata/taxes/panels.py:869-957`, `issues()` lists edits after
  filing, left-out accounts, `sale-without-lot`, open lots and sales without a basis,
  dependents, Form 8615 and gift basis; nothing reads an option past its expiry with no end
  recorded (the alert `options_expired`, `alerts.py`, knows them), and a crypto lot is listed
  only when its basis is missing, not when its acquisition is a stand-in. The possible wash
  sales are on the Gains tab's *Wash sales* card with *review* (`:230-294`), not in Issues
  (D1-9's open question: S8.3 or S8.4).
- **What goes wrong:** a put that expired in December with no close found (S3.6 asks) is open
  on the tax book's year with no gain or loss on Form 8949, and the Issues tab, which the
  guide calls what to look at "before the return is prepared", says "Nothing to look at:
  every sale has a lot and a basis."
- **Run:** no, reading alone.
- **Remedy:** Issues lists each option in the book's accounts whose expiry is in the year and
  unresolved (linking to the position), crypto lots whose acquisition came from a snapshot
  (VARIOUS), and, once D1-9 is decided, a line per possible wash sale for review.
- **Alternatives:** none needed.

### U04-19: the *Physical assets sold* card picks rows by whether the description starts with a digit

- **Kind:** bug. **Req:** S8.13 (sales of items; "A sold primary residence shows its gain and
  the years owned and lived in").
- **Code:** `web/ui/components/taxpanels.js:559`:
  ```js
  const sold = p.rows.filter((/** @type {any} */ r) => !r.description.match(/^\d/));
  ```
  Securities' rows are `"{quantity} {symbol}"` (`panels.py:166`), except a return of capital
  over basis, `"{symbol} return of capital over basis"` (`:165`); items are their names
  (`:328`). `Residence` (`panels.py:825-856`) has the years owned and no years lived in.
- **What goes wrong:** an item named *1 oz Gold Eagle* or *1967 Mustang* is left off the card;
  *VTI return of capital over basis* is listed as a physical asset sold. A sold home shows the
  years owned only, where the exclusion's test is the years lived in.
- **Run:** no, reading alone.
- **Remedy:** the panels mark an item's row (`kind: item`, or the `collectable`/`code` fields
  plus an `itemId`) and the card filters on that; a residence carries the years lived in (from
  the item, as typed).
- **Alternatives:** S8.13 drops "and lived in" and says the preparer asks.

### U04-20: TXF writes a sale with no basis as a basis of $0.00; the PDF summary doesn't say how network fees were read

- **Kind:** wrong figure. **Req:** S8.2 ("Each export says what it covers and what it does
  not"), S8.19 ("The exports say which was used").
- **Code:** `web/server/src/moolakata/taxes/exports.py:111`:
  ```python
  f"${_money(r.basis) or '0.00'}",
  ```
  while the CSV leaves the cell empty (`:65`) and the panels flag the row (`panels.py:901-908`);
  `ui/taxpanels.py:417` puts `exports.COVERS` in the PDF, not `exports.covers(b.bitcoinFees)`
  as the CSV and the Summary do.
- **What goes wrong:** a sale whose lot has no basis yet (shares transferred in, a gift)
  imports into TurboTax as a gain of its whole proceeds, with nothing in the file or beside
  the TXF button saying one row's basis is unknown. The preparer's PDF of a book set to *not
  taxed* says nothing of it, while its 8949 rows leave the fee sales out.
- **Run:** no, reading alone.
- **Remedy:** leave a row without a basis out of the TXF and count it beside the export with
  the others (*1 sale with no basis*), or refuse the TXF while any row lacks one; the PDF takes
  `covers(b.bitcoinFees)`.
- **Alternatives:** none needed.

### U04-21: a corrected federal due date is taken as any list of numbers, and a bad one fails every tax book

- **Kind:** bug. **Req:** S16.11 (a corrected figure), S8.15.3 (the federal due date).
- **Code:** `web/server/src/moolakata/projections/taxtables.py:243-252`, the length check is
  meant for the bitcoin figures and compares a list with itself for any other:
  ```python
  if len(value) != len(_BTC.get(key, value)):
      raise Invalid(f"{len(_BTC[key])} numbers")
  return value
  ```
  and `taxes/books.py:161-162` unpacks and builds the date on every book read:
  ```python
  month, day = taxtables.figures(s, year)["federalDue"]
  return next_business_day(dt.date(year + 1, int(month), int(day)))
  ```
- **What goes wrong:** Case (run): `check("federalDue", v)` accepts `[4]`, `[4, 31]`, `[13, 1]`
  and `[4.5, 15]`. An admin who types *4, 31* for a postponed date saves it; every
  `GET /tax-books/{id}` of that year (it calls `federal_due`, `ui/taxes.py:521`) and every new
  federal filing then fails with an unhandled 500 until the figure is corrected.
- **Run:** yes, `tmp/u04/t/test_u04t.py::test_federal_due_correction_unchecked`
  (`tmp/u04/run5.txt`).
- **Remedy:** `federalDue` takes two whole numbers forming a real date (try
  `dt.date(2001, m, d)`), refused with *a month and a day* otherwise.
- **Alternatives:** store the due date as a date per year, not a month and day (DC-14).

### U04-22: the Taxes screen offers what the server refuses, and leaves out what S8.15 and S8.17 show

- **Kind:** differs. **Req:** S8.14.3 (a helper doesn't add accounts), S8.15.5 (estimated
  payments "matched to transactions"), S8.17 (the refund or amount owed carried; "puts the
  capital-loss carryover in its Summary").
- **Code:** `web/ui/screens/taxes.js:193-196` and `:214-230` show *Leave out*, *Count it* and
  *Add an account* when `b.canWrite`, which a write helper has, while `ui/taxes.py:570-571`
  refuses anyone but a filer (403 `filers-only`); `taxes.js:705-712` sends payments without
  `transactionId` and `filingForm` (`:667-672`) drops it, so a payment can't be matched in the
  browser and saving a filing unmatches any matched through the API; `CARRIED` (`:42-50`) and
  the server's `Carried` (`ui/taxes.py:263-270`) have no refund or amount owed, so *From last
  year* never shows them; `SummaryFigures` (`components/taxpanels.js:63-72`) shows short plus
  long with no carryover, which only the Gains tab's Schedule D card lists.
- **What goes wrong:** Dave, a preparer with write, clicks *Leave out* on the Summary and gets
  *Only its filers add or leave out accounts*; the estimated payments can be typed but never
  tied to the transfers to the IRS; next year's book shows last year's AGI but not that a
  $2,400 refund was due or how much was owed; the Summary's net gain ignores a $9,000
  carryover.
- **Run:** no, reading alone.
- **Remedy:** the account buttons show for filers (`b.level === 'owner'`); each payment row
  picks its transaction as the result does; *From last year* shows the result (refund or owed)
  from last year's filing; the Summary's KPI shows the carryover under the net.
- **Alternatives:** S8.17 drops the refund or amount owed from what is carried, as the
  filing's own result already holds it.

### U04-23: a projection's percentiles and answers go out as raw floats, not rounded to cents (C40 half done)

- **Kind:** differs. **Req:** S6.9 ("Its percentiles are rounded to cents and sent as exact
  numbers (S13.8.2.1)"), R1.9's exception as review 2's C40 decided it.
- **Code:** `web/server/src/moolakata/projections/engine.py:176-177` keeps NumPy's floats:
  ```python
  pct = {p: np.percentile(path, p, axis=0).tolist() for p in PERCENTILES}
  real = {p: (np.array(v) / deflate).tolist() for p, v in pct.items()}
  ```
  and `projections/__init__.py:279-292` sends them, with `expected`, the scenario paths and
  the answers' `atRetirement`, `atStart`, `needed`, `neededMonthly`, unrounded;
  `exactjson.marked` (`exactjson.py:39-48`) marks Decimals only and passes floats through.
- **What goes wrong:** Case (run, U04-1's): the median at the target date goes out as
  `5979.46611909651`; every point of every fan carries 11–15 digits, which the browser reads
  as exact decimals (`app/dec.js`) and the baseline stores as such. The start value and
  tracking are exact, as C40 asked; the other half isn't.
- **Run:** yes, seen in `tmp/u04/run1.txt` (`median at target [Exact(0.0),
  Exact(5979.46611909651)]`).
- **Remedy:** round each percentile, path and money answer to cents as a Decimal in
  `compute()` (`Decimal(repr(x)).quantize(CENTS)`), and the baseline as stored.
- **Alternatives:** S6.9 says the figures go out as floats, which the client rounds for show.

### U04-24: the guides say other than the screens and sections in four places

- **Kind:** differs. **Req:** S6.2 (education is a goal type), S8.1 (digital assets in G to
  L from 2025), S8.6 (Roth eligibility by MAGI "as the user enters it"), S6.2.1 (other
  income: Social Security "a pension, each with its amount").
- **Code:** `web/ui/guides/projections.md:3-4`: "**retirement**, or a **savings target** by a
  date. ... (Education goals come with 529 accounts.)", though the New projection dialog
  offers Education and the guide's own *For*, *Age school starts* sections explain it;
  `taxes-gains.md` (*Form 8949*): "C or F with no 1099-B, as for crypto and items", where a
  2025-on crypto sale goes in G to L (the golden CSV has G, I and K rows); `taxes-retirement.md`
  (*Contributions*): "Roth eligibility depends on MAGI, which is the preparer's to check";
  `projections.md` (*Other income*): "Social Security or a pension, from an age, a month",
  where the form can't add a pension (U04-5).
- **What goes wrong:** a user reading the Projections guide thinks education isn't there yet;
  one reading the Gains guide looks for their exchange's sales in box C.
- **Run:** no, reading alone.
- **Remedy:** the projections guide names the three goals; the gains guide lists G to L for
  digital assets from 2025; the retirement and other-income lines follow whichever way U04-16
  and U04-5 are settled.
- **Alternatives:** none needed.

### U04-25: Compare models has no price history behind it, and with no bitcoin price every model starts from an assumed $100,000

- **Kind:** differs. **Req:** S6.3.1.1 ("every model's median path on one chart (log scale)
  with the price history behind it"), S6.3.1 ("a median path from today's price").
- **Code:** `web/server/src/moolakata/ui/projections.py:530-537`, the route sends the paths
  and the price, no history:
  ```python
  price = projections._btc_price(s)
  ...
  rows = bitcoin.compare(taxtables.figures(s, year), price or 100_000.0, clock.today())
  ```
  and `projections/__init__.py:240`, `btc_now = _btc_price(s) or 100_000.0`, for a projection
  too; the dialog (`ui/screens/profile.js:720-760`) draws `rows` alone and, without a price,
  says nothing of the $100,000.
- **What goes wrong:** the comparison the section asks for (each model against what the price
  did, which is how stock-to-flow's record shows) can't be seen; on a server with no bitcoin
  source configured (R3.5, sources off until set), every model's path and table start from a
  made-up $100,000, and a typed what-if with crypto follows a model from that figure, with
  nothing on screen saying so.
- **Run:** no, reading alone.
- **Remedy:** the route adds the stored daily history of BTC (or the instrument's series, S4.6)
  and the dialog draws it under the paths; with no price, the dialog and the projection say
  *no bitcoin price yet: the models start from $100,000* or ask for one.
- **Alternatives:** S6.3.1.1 drops "with the price history behind it".

### U04-26: a filing with an extension filed but no new due date typed is shown past due

- **Kind:** differs. **Req:** S8.15 ("A filing past its due date that is not filed and has no
  extension shows in the Dashboard's *Needs attention*"), S8.15.3 (an extension: "date filed,
  new due date").
- **Code:** `web/server/src/moolakata/taxes/books.py:175-187`, the extension is read only
  through its new date:
  ```python
  def due_of(f: Filing) -> dt.date | None:
      return f.extendedDue or f.dueDate
  ...
      return (
          due is not None
          and due < today
          and f.progress not in ("filed", "accepted")
  ```
  `extensionFiledOn` is never read.
- **What goes wrong:** a user files Form 4868 on Apr 14 and types *Extension filed* only (the
  federal extension's date is fixed, Oct 15, so it is easy to leave out): from Apr 16 the
  filing shows *past its due date* and the Dashboard's *Needs attention* lists it, though it
  has an extension.
- **Run:** no, reading alone.
- **Remedy:** a federal extension filed on time gives `extendedDue` six months on (Oct 15,
  moved as S8.15.3 says) when none is typed; for others, `overdue` is false while an extension
  is filed and its date unknown, the filing saying *extended, new due date not typed*.
- **Alternatives:** the filing dialog requires *Extended to* with *Extension filed*.

## Uncited first-level items

- **S6.2** (goal types): built under other words. `projections/__init__.py:195-237` builds
  retirement, education and savings targets, `ui/projections.py:34` takes the three, and the
  New projection dialog offers them; the code cites S6.2.x only in docstrings, so the checker
  saw no `S6.2`. The guide still says education comes later (U04-24).
- **S6.5** (tax-aware buckets, *later*): not built, and correctly not, but it carries no L id
  (Phase 1's D1-4); nothing to add here.
- **S6.6** (scenarios compared side by side): **not built**, U04-4.
- **S8.10** (Education (529)): built under other words. `taxes/panels.py:691-753`
  (`education_panel`, `students`), cited as the range "S8.9–S8.12" (`:683`), shows
  contributions per beneficiary and contributor, the state deduction noted, the 1099-Q
  distributions against qualified expenses and the part not covered, and the guide's note on
  the 10% additional tax (`components/taxpanels.js:524-525`); the receipts behind the
  expenses are unit 02's (`edu.js`).

## Phase 1 claims against the code

- **D1-25** (needs the user): the code gives a tax document's file to the book's accepted
  filers only (`receipts/__init__.py:248-249, 289-301`): S9.6's reading. Against S8.14.3 and
  S10.3's (helpers attach and see documents) it differs: U04-14. Either way a write helper
  attaching a file is refused nothing, and a co-filer can't change a document with the
  other's file (U04-13).
- **D2-2** (needs the user): whether a tax book's document files cross a link is unit 08's
  code; on this side nothing marks a tax document's receipt for *Include receipts*, so the
  code matches L6's reading (later). Noted only.
- **D1-9** (where a possible wash sale is listed): the code lists the option reviews on the
  Gains tab's *Wash sales* card with *review* (`panels.py:230-294`), S3.8.5's and S8.3's
  reading; S8.4's Issues lists none (U04-18 notes it beside the unresolved expiries).
- **D1-18** (one active projection per savings target): `projections.subject()`
  (`__init__.py:418`) makes each savings projection its own subject, so any number can be
  active: the remedy's first reading. The guide (*Active*: "one per savings target") reads the
  same.
- **D1-19** (the 4% rule): the code defines it as 4% of the balance at retirement, then rising
  with inflation (`engine.py:146-153`), and the screen's choice and the guide say so: the
  remedy's reading. Only the hand-written mockup's *4% of balance* differs (a document matter).
- **DC-14** (the federal due date in the tax tables): the code already ships it as month and
  day per year (`taxtables.py:44-45, 116-128`), postponed years included (2019's Jul 15,
  2020's May 17), and a later year takes the latest's month and day: DC-14's remedy is what
  the code does; S16.11's list is what lags. A bad correction of it fails every book (U04-21).
- **D1-4** (S6.4.2's bootstrap, S6.4.3's glide path, S6.5): none is built; consistent with
  "later".
- **D1-8** (S1.4's limits): the code takes them from the tax tables (`panels.py:483`), S16.11.
- **D1-17** ($250 or more): `giving/__init__.py:30` flags at $250 or more, S8.9's reading
  (unit 05's code).
- **D2-5**, **D2-9** (projections on a linked server): unit 08's; this unit's code has no
  linked-window projection.

## Earlier findings re-checked

- **P1** (High, done): holds as written. `books.previous()` waits until every filer of the
  new book has accepted (`books.py:334-335`), an added account counts only while its adder,
  an accepted filer, can see it (`:148-153`), and C42's two-sided spouse is unit 07's. A new
  case beside it: last year's book is any that names a filer, accepted or not (U04-11).
- **P7** (Med, done): a helper with write can't add or leave out accounts on the server
  (`ui/taxes.py:570-571`), though the screen still offers it (U04-22); a tax book goes to a
  linked server read only and any accepted filer changes its sharing (`sharing.py:102-111,
  134`). The projection part half holds: tracking narrows to the viewer's accounts
  (`__init__.py:493-501`), but the label, account ids and mix of accounts not shared still go
  out (U04-8).
- **P8** (Low, done): unit 07's code; the tax book and projection routes record their creation
  and changes (`activity.record`), filings and documents record none (S10.8 doesn't ask).
- **B3** (High, done): holds; the importer's test (`test_importers.py:188`) keeps a
  reinvestment's `reinvest` row without `dividendType`, and the income panel counts a
  `reinvest` only when it carries one (`panels.py:416-419`).
- **B4** (High, done): holds; splits add `-amount` like whole transactions (`panels.py:645`),
  with a test (`test_taxpanels.py:209`).
- **B14** (Med, done): holds; the model drives `bitcoin_share` of the crypto
  (`__init__.py:72-77`, `engine.py:87-96`), with a test. U04-3 is a new fault in the same path.
- **B15** (Med, done): holds; limits per person and group (`panels.py:576-580`), with a test.
  U04-15 is a new case beside it (conversions).
- **B16** (Med, done): the S8.11 side lists the flagged people and five-year elections
  (`panels.py:764-787`); the counting is unit 05's and unit 02's (U02-11).
- **B17** (Med, done): holds; 2016 to 2026 ship (`taxtables.py:116-191`), `create_book`
  takes ten years back to one ahead (`ui/taxes.py:117-119`), and a later year takes the latest.
- **B22** (Low): TXF decided (§12.5.2) and built as decided, with counts beside the export and
  a golden file; tax due dates skip weekends, federal holidays and Emancipation Day
  (`taxes/dates.py`), with a test; the tracking floor is a minimum width (`widened()`), with
  a test. Holds.
- **B23** (Low, done): `EstimatedPayment.amount` is `Cents` (`store/tables/taxes.py:146`);
  a projection's start and tracking are Decimal. The percentiles' rounding (C40) does not hold:
  U04-23.
- **B37** (Med, done): the years a projection runs are bounded (birth year in the last 120,
  dates and first year within 100, `MAX_YEARS`), with a test; other inputs still raise
  (U04-7, a 500, not a stall).
- **N5** (Med, done): built (`taxes/closed.py`, `mig/0023`), with tests for a hand edit; but
  the guard is on hand edits only (U04-10), saving the amended return settles later edits
  (U04-12), and U03-5 (another account's wash sale).
- **N13** (Med, done): holds for co-filers (`receipts/__init__.py:289-301`, test
  `test_taxbooks.py:523`); helpers per D1-25 (U04-14).
- **N14**: moved to L7, and S6.1.2 says so; not raised.
- **C34** (done): holds (S8.14.3 states the read-only exception; `sharing.save` refuses write
  to a remote user).
- **C40** (done): half holds, U04-23.
- **C41** (done): holds; the crypto volatility spreads every model (`engine.py:87-96`), and
  draws are log-normal (`_lognormal`).
- **C42**: unit 07's (`people.joint_filers`).
- **C50** (done): holds; digital assets in G to L from 2025, I/L for a wallet, G/J for basis
  acquired from 2026 on an exchange (`panels.py:95-112`), in the golden CSV.
- **§12.2's tests row**: B3 (importer test), B4 and B15 now have tests; holds for this unit.

## Checked and sound

- `taxes/dates.py`: the legal holidays (federal, observed on the Friday or Monday, New Year's
  Day observed on Dec 31, Emancipation Day observed) and `next_business_day`; Apr 15, 2017
  (a Saturday) moves to Apr 18 through Emancipation Day on Monday the 17th, as the IRS did.
- `taxtables.py`'s shipped figures for 2016–2026: IRA, catch-up, 401(k), its catch-ups
  (60–63 from 2025), HSA self and family, RMD age (70½ until 2019, 72, 73), gift exclusion,
  QCD (indexed from 2024), Form 8615 threshold and the postponed due dates, checked against
  the published IRS figures from memory.
- `exports.py`'s TXF V042: the codes 321/711/712/323/713/714 for boxes A–F, the record's
  order (basis, then proceeds, then the wash-sale amount), `in_txf` and the counts by why
  against S8.2's sentence; the CSV's columns and the golden files' rows (a W adjustment
  bringing a loss to 0, a written put with the premium as proceeds, boxes G, I and K).
- `panels.box_of` and `_covered`: covered dates (equities 2011, funds 2012, other 2014), the
  digital-asset boxes, a wallet's I/L.
- `closed.closing_books`: a year closed by a filed or accepted federal return, opened while an
  amended one is not started, in progress or rejected, closed again once it is filed (S2.8.1),
  and `Guard.check`'s refusal and records per closing book (S2.8.2–3) for the routes that use
  it.
- `dependents.py`: ages on Dec 31, under 17 and 13, the qualifying-child suggestion (a child or
  grandchild under 19, or under 24 and a student), a person claimed on two books flagged
  without naming the other, a filer claimed elsewhere, Form 8615 on a qualifying child's
  counted accounts only, and the carry-over that leaves out and names those past the age.
- `books.counted`: accepted filers' own accounts once, left-out and added accounts, an added
  account only while its adder (an accepted filer) sees it.
- Who may do what on a tax book: `books.level` (creator and accepted filers own it, others by
  share), `delete_book` needs an owner, filings, documents and dependents need write,
  `count_account` needs a filer, `no_amendment` needs write, a named filer sees nothing until
  they accept (404).
- `engine.py`'s log-normal draws (arithmetic mean and volatility preserved), fees, the 4%
  rule, fixed and percentage withdrawals with other income, the education costs rising with
  their own inflation, the couple retiring when the last does, the part-year at a target date
  (apart from U04-1's bound), seeding.
- `tracking()`: the band anchored on the first actual balance, the 2% floor as a minimum
  width, the partial view for a viewer without every account, the monthly alert's month end.
- `ui/projections.py`'s access: read, write and owner levels; activation and deactivation by
  the owner; *Show on my Dashboard* for receivers only; tax-table corrections by admins, a
  shipped value removing the correction.

## Read lightly or not read

- `mig/0003_tax_book_dependents.py` and `mig/0023_edits_after_filing.py`: read for their
  tables against `store/tables/taxes.py` (0023's `Dec` column became `Cents` in 0024, unit
  06's schema check).
- `ui/taxpanels.py`'s response models (lines 1–180) skimmed; `taxes.js`'s Filing dialog's
  carried figures and payments read, its layout not.
- Tests: `test_projections.py`, `test_taxbooks.py`, `test_taxpanels.py` read for their names
  and the cases quoted; `test_golden.py`'s setup (lines 1–96, 153–300) not read line by line;
  the golden TXF and 8949 CSV read whole, `form-8949-review-2026.csv` not.
- Guides: `dialog-plan.md` and `dialog-estimate.md` are budgets' dialogs (unit 05), not read;
  `dialog-dependent.md`, `forms.md`, `dialog-new-projection.md` and `portfolio-projections.md`
  read quickly, nothing found.
- `valuation.series` and `loans`/`assets` values (unit 02's and 03's) read only where
  projections call them; `people.joint_filers` and `sharing.py` beyond `_may_share` and the
  remote-user check are unit 07's.
- The dashboard's *Needs attention* for overdue filings and changed years
  (`ui/dashboard.py:234-251`) read only for the calls into `closed` and `books`.
- Performance not measured: the projections list computes every projection's Monte Carlo and
  tracking on each `GET /projections`, which the account and portfolio pages call
  (`components/plans.js:13`); no claim without a measurement.

## Work pad: severity, confirmations, status

| Id | Kind | Sev | Req | Conf | Status | One line |
|---|---|---|---|---|---|---|
| U04-1 | wrong figure | Med | S6.4.2.4 | 0 | open | A savings target under a year names a monthly saving that reaches half of it |
| U04-2 | wrong figure | Med | S6.1.1 | 0 | open | A projection on a loan or items counts the loan's payments as cash and leaves items out |
| U04-3 | wrong figure | Low | S6.4.2.3 | 0 | open | A bitcoin model's growth is applied a year early |
| U04-4 | not built | Low | S6.6 | 0 | open | Scenarios can't be compared side by side |
| U04-5 | differs | Low | S6.2.1 | 0 | open | The Inputs form can't set other income, horizon, birth year, several accounts, overrides |
| U04-6 | differs | Low | S6.7.1 | 0 | open | Making an education projection active replaces the other without asking |
| U04-7 | bug | Low | S13.8.3 | 0 | open | A projection's unchecked inputs answer 500; a typed mix may be levered |
| U04-8 | privacy | Low | S6.1 | 0 | open | A shared projection names an account the viewer isn't shared, and its mix |
| U04-9 | privacy | Low | S10.10.2 | 0 | open | An education goal for a user takes any user's person, private or remote |
| U04-10 | differs | Med | S2.8.2 | 0 | open | A filed year's gains move unasked on an import, a deleted account, both-real, a transfer match |
| U04-11 | wrong figure | Med | S8.17 | 0 | open | From last year reads the first last-year book naming a filer, accepted or not |
| U04-12 | differs | Med | S8.15 | 0 | open | Saving the amended return again settles edits made after it was filed |
| U04-13 | differs | Med | S8.8 | 0 | open | A tax document can't be changed, removed or given its file later |
| U04-14 | differs | Med | S8.14.3 | 0 | open (needs the user, D1-25) | A write helper can't open a tax document's file |
| U04-15 | wrong figure | Med | S8.6 | 0 | open | A Roth conversion counts as a contribution over the limit; HSA employer money left out |
| U04-16 | not built | Low | S8.6 | 0 | open | Roth eligibility by MAGI and the backdoor-Roth steps |
| U04-17 | not built | Med | S8.5 | 0 | open | Foreign tax paid and crypto income on the Income panel |
| U04-18 | differs | Low | S8.4 | 0 | open | Unresolved option expiries and stand-in crypto acquisitions aren't Issues |
| U04-19 | bug | Low | S8.13 | 0 | open | Physical assets sold picked by a description's first character |
| U04-20 | wrong figure | Low | S8.2 | 0 | open | TXF writes a missing basis as $0.00; the PDF omits the fee reading |
| U04-21 | bug | Low | S16.11 | 0 | open | A bad federal due-date correction is accepted and fails every tax book |
| U04-22 | differs | Low | S8.17 | 0 | open | The Taxes screen offers helpers account changes, can't match payments, omits refund and carryover |
| U04-23 | differs | Low | S6.9 | 0 | open | Percentiles and answers go out as raw floats, not cents |
| U04-24 | differs | Low | S6.2 | 0 | open | Four guide lines say other than the screens and sections |
| U04-25 | differs | Low | S6.3.1.1 | 0 | open | Compare models has no price history; with no price every model starts at $100,000 |
| U04-26 | differs | Low | S8.15 | 0 | open | An extension filed with no new due date typed shows past due |

Counts: 26 claims. By severity: High 0, Med 9 (U04-1, U04-2, U04-10, U04-11, U04-12, U04-13,
U04-14, U04-15, U04-17), Low 17. By kind: differs 12, wrong figure 6, not built 3, bug 3,
privacy 2 (both Low, so not withheld). One needs the user: U04-14 (D1-25). Scratch tests in
the job's `tmp/u04/t/` (`test_u04p.py`, `test_u04t.py`), runs in `tmp/u04/run1.txt` to
`run5.txt`, the delta's diff in `tmp/u04/delta.diff`.
