# Walk: values, tax documents and contributions, options and returns

Review 3's open Med claims in three groups, walked on branch `cr3-values-taxes-options` from
main `5de99cc`, one PR for all three:

1. Loans and items in the figures: CR3-21, CR3-22 (S1.9), CR3-30 (S5.2.3), CR3-32 (S6.1.1).
2. Tax documents and contributions: CR3-9, CR3-74 (S9.6), CR3-10 (S11.5.1), CR3-37 (S8.6),
   CR3-38 (S8.5), CR3-73 (S2.2).
3. Options and returns: CR3-6 (S3.5.5), CR3-23 (S4.4), CR3-24 (S3.6), CR3-28 (S5.2.1).

Each group's tests, code coverage, data shapes and speed are an item of their own, and the
harness the batch shares is item 16.

**Found before the walk.** Every claim still holds on `5de99cc`. Beyond the claims:

1. Three places work out what an account holds on their own (`ui/portfolios.py:430`,
   `projections/__init__.py:117`, `ui/accounts.py:664`), each taking a ledger's balance as
   cash; only `valuation.account_value` values loans and items. A projection leaves options
   out of its start (`asset_class` gives them `None`) while its tracking (`valuation.series`)
   counts them.
2. Recording a loan payment *From account: Checking* when Checking already holds the imported
   debit makes a second bank half.
3. `valuation.prices` without an owner falls back to every user's statements and trades; five
   callers pass none (expiry, an adjusted contract's deliverable weights, metals' spot, bitcoin
   sync's fee value, a projection's bitcoin price). The price precedence is written twice,
   in `prices` and in `price_points`, and they differ on the fallbacks.
4. The app's Share dialog shows *Include receipts* on a tax book, where it sends nothing.
5. Main's CI run 41482467904 (the #31 merge) failed on a flaky browser test:
   `test_app_guides.py::test_every_screen_and_tab_has_its_guide[1]`, `visit()`'s 15 s settle
   wait on `/ui/users`; the same tree passed on the PR. Not rerun: this PR's CI covers it.

**Coverage before** (the Pages site, main at `5e409cf`; lines / branches): `ui/portfolios.py`
87 / 65 %, `ui/loans.py` 89 / 67, `ui/items.py` 87 / 68, `ui/accounts.py` 92 / 75,
`projections/__init__.py` 93 / 77, `loans/__init__.py` 95 / 85, `valuation.py` 96 / 91;
`ui/taxes.py` 88 / 65, `ui/transactions.py` 84 / 68, `receipts/__init__.py` 80 / 71,
`importers/ofx.py` 87 / 71, `links/serve.py` 88 / 77, `taxes/panels.py` 93 / 87,
`ledger/lots.py` 96 / 88; `ui/options.py` 89 / 73, `options/__init__.py` 90 / 83,
`options/strategies.py` 94 / 83, `prices/refresh.py` 95 / 83, `ledger/performance.py` 95 / 88.

**How they slipped.** Each wrong figure is computed in more than one place, and the tests
held one of them: the HELOC test reads the schedule, not the summary; the portfolio's value is
tested, its Holdings tab and a projection's start on a loan are not; transfer paths are tested
one at a time; contributions with plain deposits; transfer-ins for their basis, never their
date; tax files for the filers; the expiry test inserts the underlying's close by hand, which
production never stores; flows with no shares moved; capital at risk one strategy at a time;
no test sets a second user's data beside the first's.

## Decisions

All locked Nov 3, 2026, as recommended.

1. **CR3-30, CR3-32: one breakdown of an account (6:11 AM).** `valuation` splits an account
   into parts: cash, each security, options, a loan at minus what is owed, items by kind.
   `account_value` is the sum of the parts and `series` follows them. The portfolio's
   Holdings tab lists every part (loans and items as rows of their own) and its total is the
   portfolio's value; an account's Holdings reads the same parts; a projection starts from the
   parts in their classes, and tracking sums the same parts. Invariant: Holdings total =
   portfolio value = sum of the parts = the series' last point.
   1. (1.1) A projection grows precious-metals items (the metals class); real estate,
      vehicles, collectables, other items, loans and options are left out and named under its
      chart (*Left out: Mortgage −$298,000; Car $18,000; 2 option positions $1,200*).
   2. Rejected: each consumer calling `account_value` for loans and items (leaves three copies
      and the options mismatch); refusing loans and items (shows less, totals still differ).
2. **CR3-21: the summary's payment from the schedule's next row (6:15 AM).** *Payment* is the
   next row's principal and interest, the total its whole payment (escrow, PMI): one source for
   the screen, the payment dialog, *Looks like a payment* and the schedule. In the draw period
   the screen adds *interest only until <date>*. `_pi_payment`'s draw branch goes. Fixes
   daily-interest loans and the last payment with it. Rejected: interest computed in
   `_pi_payment` while drawing (a second interest calculation).
3. **CR3-22: find a transfer's other half before making it, on every path (6:18 AM)**, by
   S1.7's rule (`ledger/transfers.py`: equal and opposite, within 4 days, unpaired).
   1. **Link** pairs the bank debit with an unpaired loan payment it matches (no new row);
      only without one does it make one.
   2. **Looks like a payment** shows such a debit as *Pair with the payment of <date>*, and
      leaves out a debit when an unpaired loan payment of another amount lies within 4 days.
   3. **Record a payment** with a *From account* pairs with a matching unpaired debit already
      there, saying so.
   4. *None* stays; its guide line: "for a payment from an account MoolaKata doesn't hold, or
      one already in a bank account: *Looks like a payment* offers to pair it."
   5. Rejected: fixing Link alone (leaves *From account*'s duplicate); dropping *None* (breaks a
      loan paid from a bank MoolaKata doesn't hold).
4. **Group 1's tests (6:24 AM).**
   1. An account world: account kinds (checking; a brokerage with stocks, funds, bonds,
      crypto, long and short options, an unpriced holding), loan shapes (mortgage, HELOC in
      and after its draw period, a daily-interest car loan, an ARM after a reset, a recast,
      no terms, paid off), items (metals, real estate, a vehicle) and the viewer (owner, one
      who sees part); pairwise, about 40 cases. Invariants: Holdings total = value = sum of the
      parts = the series' last point = the account's share of net worth; a projection's start
      plus what it leaves out = the portfolio's value, tracking's first point = the start; for
      every loan shape, the summary's payment = the schedule's next row. A reference model;
      the old bugs planted must fail; about 15 s locally.
   2. A transfer-halves sequence world: the path (import, record with *From*, with *None*,
      Link, typed in the bank, typed in the loan) × two orders × amount (equal, within 2 %,
      different) × days apart (0, 3, 5); about 25 sequences. Invariant: each real payment is
      one loan row and one bank row, paired.
   3. Browser: Holdings rows for loans and items, a projection's *Left out*, *Pair with*, the
      dialog's pairing note. Floors from CI, aiming ≥ 85 % branches in `ui/portfolios.py`,
      `ui/loans.py`, `ui/items.py`, `ui/accounts.py`; the CI time added reported.
   4. `visit()` (`tests/devapp.py`): a 60 s settle wait, a failure that names the path and
      the requests still pending, no fixed waits.
5. **CR3-9, CR3-74: a file is seen by whoever can read what it is attached to (6:29 AM).** A
   tax document's file is opened by whoever can read the book (filers, write helpers, read
   shares) and attached, replaced or removed by whoever can write it. S9.6: a receipt on an
   item, a loan, a 529 expense or an account statement is seen by whoever can read that
   account. Rejected: filers and write helpers only (a level of its own for tax files, while
   the panels show the same figures); filers only (a preparer can't read what they prepare
   from).
6. **CR3-10: a tax book's document files cross a link with *Include receipts* (6:32 AM)**, as
   encrypted files in the linked copy, as an account's receipts do; `allowed_file` covers them
   and the linked window's Documents tab opens them. L6 loses the clause; S11.4 and S11.5.1 say
   they cross. The toggle shows only on kinds with files to send, its line saying what it
   sends. Rejected: L6 standing (a linked preparer sees the checklist, not the W-2).
7. **CR3-37: each retirement-account movement classified once, on both halves (6:34 AM).** A
   contribution (employee, employer), a rollover (the same tax treatment, trustee-to-trustee
   moves too), a conversion (pre-tax to Roth) or a distribution; one function decides from a
   matched transfer's other account, the source field overrides and gains `conversion`. The
   Retirement panel counts employee money against the IRA and deferral limits, employee and
   employer money against the HSA's; lists conversions under S8.6's backdoor-Roth steps with
   their 8606 figures, and rollovers apart, not as distributions.
   1. (7.1) An HSA's coverage on the account (*self-only*, *family*; unset keeps the family
      limit, noted *set the coverage*); a tax-table figure `hsaCatchUp` ($1,000 at 55).
   2. Rejected: the transfer dialog setting `rollover` (misses imported halves matched later;
      no conversion; no HSA).
8. **CR3-38: foreign tax and crypto income built (6:37 AM).** A `foreign-tax` kind (a cash
   line tied to its payer; imported from brokers' history lines, typed in the dialog; on the
   Income panel by payer beside the dividends) and a `reward` kind (crypto received as income,
   at the day's price; ordinary income on the Income panel by source; it makes a lot with that
   basis; imported from exchanges' staking and reward lines; a wallet's receipt can be marked
   one). Imports for the average cases (a Schwab brokerage, a Coinbase-style CSV), checked
   against real sample files; other formats recorded as a G id. Rejected: rewards alone (foreign
   tax left to the preparer); both later (rewards' basis wrong, so their gains).
9. **CR3-73: one carried-lots rule (6:40 AM).** A matched transfer pair of any instrument
   carries the lots its out-half took whole (acquired, basis, `heldFrom`, stand-in) through the
   replay, as bitcoin's pairs and corporate actions do. An unpaired typed transfer-in takes
   one or more lots, each with its acquired date and basis (S2.2); a date edit no longer moves
   them. An unpaired imported one without lot data: lots marked *acquired date and basis
   missing*, term *unknown*, listed on the Open tab and among the tax book's issues until
   filled. Rejected: one acquired date on a transfer-in (wrong for a holding bought over years;
   pairs and imports left).
10. **Group 2's tests (6:42 AM).**
    1. A file-access matrix: attachment kind (transaction, gift, donation, tax document, item,
       loan, 529 expense, statement, unattached) × reader (owner, accepted and unaccepted
       filer, write share, read share, group, linked person with and without *Include
       receipts*, stranger), each cell against one table mirroring S9.6, on the list, open,
       attach and remove routes and the link's `allowed_file`; in-process.
    2. The tax world gains axes: retirement movements (employee and employer contributions,
       IRA→IRA, 401(k)→IRA, a conversion, a distribution; imported, typed, a matched pair), the
       HSA (coverage × age 54 or 55 × an employer share), foreign tax and rewards (a reward
       sold later), transfer-ins (paired, typed with several lots, imported without dates and
       filled) across the one-year line; the reference model gains the limits, the 8606
       figures, each lot's term and the Income panel's totals; old bugs planted.
    3. The import corpus: foreign-tax lines, reward and staking lines, an OFX transfer-in.
    4. Browser: a helper opens a filer's W-2; the linked window opens a tax book's file; the
       Retirement panel's conversion, rollover and HSA rows; the transfer-in dialog's lot rows.
       Floors from CI, aiming ≥ 85 % branches in `ui/taxes.py`, `ui/transactions.py`,
       `receipts/__init__.py`; CI time reported, the tax world split further if it grows.
11. **CR3-6: one meaning per name (6:44 AM).** *Capital at risk* is always S3.5.5's maximum
    loss: an option outside a strategy counts as an implicit one-leg strategy through the same
    payoff code (long: its premium; short put: strike less premium; a short call covered by
    shares held: a covered call; uncovered: *unlimited*). S3.9.2's figure is *capital
    required*, the per-trade return's base (*return on capital required*); a strategy's leg
    uses its strategy's capital at risk at open, or capital required where that is unlimited.
    Rejected: S3.9.2's figure for both (understates a naked call); patching `risk_of_account`
    (a second copy of the shape rules).
12. **CR3-23: one definition of what needs a price (6:45 AM).** `priced()`: what is held; the
    underlying of every open option (and an adjusted contract's deliverable parts) from the
    option's first transaction until the day after its expiry; metals' spot; benchmarks. S4.4's
    "watched" is the underlying of an open option. Rejected: the underlying from CBOE's chain
    (one source only).
13. **CR3-24: two questions, two functions (6:48 AM).** `valuation.prices` requires an owner,
    its fallbacks that owner's data alone; `valuation.closes(s, ids, day)` gives stored market
    closes only. Expiry reads `closes` for the expiry day, or asks (S3.6). An adjusted
    contract's deliverable weights, a fee's value and items' spot take the account owner's
    `prices`; a projection's bitcoin price takes `closes`.
    1. (13.1, 6:57 AM) One implementation of the precedence: `price_points`; `prices(owner,
       day)` is its last point on or before the day, `closes()` the same with only `close`.
       Invariant: for every instrument and day, `prices()` = `price_points()`' last point.
    2. Rejected: `expire_due` alone reading a close (leaves four owner-less callers).
14. **CR3-28: the series reports its own flows (6:51 AM).** `valuation.series` returns each
    day's value and the money that came from outside: cash in and out, shares moved (at the
    series' own price that day, a carried-forward one included), items added or disposed of
    (at their value), a loan's opening balance and draws. The time-weighted return, IRR,
    contributions and the benchmark read them; moves between a portfolio's accounts net out;
    `perf.flows`' price parameter goes. Invariant: a day with only an outside move has zero
    growth. Rejected: price points passed to `perf.flows` (its price can differ from the
    series'; items and loans left); a transfer's own price or basis (the gain still growth).
15. **Group 3's tests (6:57 AM).**
    1. An option world: call or put, long or short, covered or not, grouped or not, an
       adjusted contract, the expiry case (out of, in, at the money; no close; only a typed
       price; only another user's trade that day), the price source (closes, CBOE's chain,
       none); pairwise, about 40 cases, prices through the real refresh with a fake source,
       never closes inserted by hand. Invariants: grouped = ungrouped capital at risk; an
       expiry applied only on a stored close and only out of the money; the underlying in
       `priced()` from the option's first transaction to the day after expiry. Old bugs
       planted.
    2. A cross-user price guard: decoy trades and statement values from a second user change
       nothing at any entry that reads a price (positions, Holdings, item values, a fee's
       value, projections, expiry, deliverable weights); `prices()` has no default owner; 13.1's
       invariant.
    3. Flows in the account world: every kind of outside move; growth zero on a day with only
       that move; a portfolio with only moves has a time-weighted return of 0, the benchmark
       the same money.
    4. Browser: an ungrouped naked call makes the account's and the portfolio's *Capital at
       risk* *unlimited*; the per-trade table says *return on capital required*. Floors from
       CI, aiming ≥ 85 % branches in `ui/options.py`, `options/__init__.py`,
       `options/strategies.py`, `prices/refresh.py`; CI time reported.
16. **The batch's harness (7:05 AM).**
    1. A shared kit for worlds, `tests/worlds/`: axes, impossible pairs, the pairwise check, a
       seed search, a runner for planted bugs (each world names the bugs it must catch; a
       meta-test fails on a survivor), per-world timing. The budget and tax worlds move onto
       it.
    2. A decoy household in every world, with conflicting data (the same symbols, amounts and
       dates; its own trades, statements, files and transfers); adding or removing it changes
       no figure.
    3. Property tests (Hypothesis, a new dev dependency, listed under S17.3 and in
       `dependencies.md`; derandomized in CI): the loan schedule (never below 0; principal paid
       = principal + draws; next row = summary), carried lots (quantity and basis conserved
       across pairs, splits and mergers), flows (value change − flow = growth), transfer
       matching (symmetric; a row never paired twice).
    4. Boundary axes: rounding (fractional shares, 4-decimal prices, a third of a cent),
       calendar edges (a loan starting on the 29th to 31st, February, a leap day, an expiry on
       a market holiday, weekends), the holding period's one-year line.
    5. Query budgets at about 50 accounts and 500 trades: the portfolio's Holdings, opening a
       projection and its tracking, the loan screen, the Retirement panel.
    6. A one-off mutation run at the end (mutmut on `valuation.py`, `loans/`,
       `ledger/performance.py`, `ledger/lots.py`), a measure, not a gate; asked before it runs.

**Final approval** given Nov 3, 7:05 AM: one PR for all three groups. Build order: group 1
(with 16.1, 16.2, 16.5), then group 3 (item 14 builds on item 1), then group 2; 16.6 last.

## Applied

All on one branch, `cr3-values-taxes-options` (PR #32), in the approved order.

1. **One breakdown of an account** (decisions 1, 2; CR3-30, CR3-32; `9be0407`).
   `valuation.parts` lists an account's cash, positions, items and loan; its value is their
   sum, and the Holdings tab, a projection's start and tracking read it. The portfolio's
   weights are on its gross value, a loan's none. A projection names what it leaves out
   (`BuiltOn.leftOut`). Found building it, a new claim: **CR3-394**, a past day's value
   counted today's shares at that day's prices; the ledger now replays to a day.
2. **A loan's payment and its other half** (decisions 3, 4; CR3-21 `cde432f`, CR3-22
   `39e33b6`). The summary's payment is the schedule's next row; a HELOC in its draw period
   pays its interest (`_pi_payment`'s draw branch stays: the schedule calls it). *Looks like a
   payment* pairs with a payment already recorded (**Pair**), and the payment dialog finds
   the account's debit before making a half.
3. **The harness** (decision 16): the worlds' kit (`tests/worlds`, `80145d4`) with axes,
   decks, planted bugs and per-world timing; `visit()` waits 60 s and names what it waits on
   (`0782a8d`, the flaky guide test on main's run 41482467904).
4. **Generated worlds and properties** (decision 16.1–16.5):
   1. Account worlds with a reference model and a decoy household (`40bd9da`, `1bac493`).
   2. Payment sequences (`test_halves_world`) found **CR3-395**: a statement imported after
      a payment recorded from its account added the debit again; fixed in `97c71fd` (the
      checkpoint's B1).
   3. The budget worlds caught none of their plants: they had no reference for spending. Given
      one (`89d4521`, the checkpoint's A1); their gaps list is empty.
   4. Hypothesis properties of loan schedules, transfer matching (`f8d4b07`), carried lots
      and money moved alone (`e4943a9`).
   5. Query budgets for the figures built on accounts (`2903d93`): 13 to 24 queries an
      account, as on main; Holdings takes about 1.5 s at 50 accounts. A measure, not fixed
      here.
5. **Prices** (decisions 5, 6, 13, 13.1; CR3-24 `41a7c63`, CR3-23 `a8725ff`). One order of
   sources (`_tiers`, `_effective`), always an owner's; the market's closes apart
   (`valuation.closes`), which an expiry reads. An open option's underlying is priced, held or
   not, and a price may be typed for it; nothing in the browser offers that yet (the Prices
   screen lists holdings).
6. **The series' own flows** (decision 7; CR3-28 `acf9c3f`): shares, items and a loan moved
   in or out aren't growth. S5.2.1 says what a contribution is (`4e33314`).
7. **Capital at risk** (decision 8; CR3-6 `f3a06fe`): an option alone is a strategy of its own
   shape; a trade's return is on its capital required. Option worlds priced through the real
   refresh (`25112b1`); they leave adjusted contracts out (a deliverable of parts is covered
   by `test_options`).
8. **Tax documents' files** (decisions 9, 10; CR3-9, CR3-74 `e7daa03`; CR3-10 `cb06ef7`). The
   linked book's Documents tab is new; the share dialog's *Include receipts* shows only for
   kinds with files. The file matrix (`fe07ad9`) asks every kind of attachment of every kind
   of reader. A browser test across two servers wasn't added: the link API's tests cover it.
9. **Money moved for taxes** (decisions 11, 12; CR3-37 `b98465e`, CR3-38 `f0ec713`, CR3-73
   `cda3f23`). Pairs of moved holdings cover any instrument, not bitcoin alone. The tax
   worlds weren't extended: money moved has worlds of its own (`worlds/tax_moves.py`,
   `01c9c05`), with plants for CR3-37 and CR3-73.
10. **Found by CI**: **CR3-396** (`1f51622`): the release smoke run (failing on main since
    PR #27) posted the welcome from curl without a body or a length and got 401.
11. **Found by CI, again**: Positions refused a lot whose term is unknown (CR3-73's own
    change, `213c097`), and the Users screen stuck on its skeleton: **CR3-397** (`00220e3`).
12. **Mutation run** (16.6): mutmut 3.8.0 on `ee70d9b`, over `valuation.py`, `loans/`,
    `ledger/performance.py` and `ledger/lots.py`, with the 13 test files that reach them (the
    accounts world left out). 3,583 mutants: 2,757 killed, 5 timeouts, 754 survived, 67 reached by
    no test; 78.6% of those reached are caught. `loans/__init__.py` catches all but one; `lots.py`
    and `valuation.py` about 70%. Survivors cluster in `valuation.flows` and `series`, and in
    `lots.replay`, `consume`, `transaction`, `option`, `cover` and `corporate`: the next tests'
    targets. Survivors include equivalent mutants, so the rate is an upper bound. Peak memory
    10.9 GB. The summary is on PR #32.
13. **The mutation run's actions, and the area's coverage looked at again** (16.6, and the
    walk's look at code and data-shape coverage): tests for each function whose survivors showed
    a whole behaviour unchecked (`ec8fa47`, `2126f1e`, `02e4806`, `1971153`); every fact a lot
    carries crossed with every operation, and a property over random histories (`cc2f7af`);
    adjusted contracts as a dimension of the option world (`58b5b56`); returns of capital in the
    tax world (`45e81bd`); the price sources' every answer, adjusted contracts' cash, refusals
    and undoing, and every strategy shape, from CI's coverage data for the whole suite
    (`96d6d19`, `0d243a9`), which the coverage artifact now carries (`be96bf3`). Found on the
    way: **CR3-398** to **CR3-405**. Every survivor was then read and settled file by file, with
    86 more fast tests (`8e0a3a4`, `594783e`, `6083243`), code removed where only a mark would
    keep it, and marks with their reasons; the final pass over the 35 functions that had
    survivors caught 1,584 of 1,607 changes, and leaves 14 known equivalents unmarked (a mark
    would also hide changes tests catch). A run is now one command, `web/dev.sh mutate`
    (S17.5.12, `docs/mutation-testing.md`, `f1ac467`); the browser's coverage slack is 40 lines,
    its run-to-run spread measured at 32 (`aab42cd`). **R3.11** (input means what it says) and
    **ValueInput** came of CR3-403 (`5681c11`, `809d634`); issues #33 (other fields to fix to
    R3.11) and #34 (an intermittent 500 from `GET plan529`; a browser test now shows the
    server's log on a 5xx, `84c55b7`).