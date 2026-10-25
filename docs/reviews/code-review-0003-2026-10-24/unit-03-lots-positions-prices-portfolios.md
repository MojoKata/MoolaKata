# Code review 3, unit 03: lots-positions-prices-portfolios

**Session:** Oct 24, 08:17 PM to 08:33 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S2 (holdings and lots: instruments, transfers in, lot methods, corporate
  actions, reinvestment, categorisation and payee rules, closed years, reimbursable spending),
  S3 (positions and options: positions, option trades from files, short options, assignment
  and exercise, strategies and capital at risk, expiry, the mark, wash sales, per-trade
  figures, adjusted contracts), S4 (prices: sources, the refresh, options' prices, history,
  staleness, linked servers, typed prices), S5 (portfolios and charts: what a portfolio
  holds and who sees it, its charts, net worth, series on the server), with the README lines
  they rely on (R1.9 money, R2.8 portfolio, R2.20 trade, R3.1/R3.5 outbound calls and sources
  off until configured, R3.2 imports never invent, R3.4 sharing).
- **Code (11,156 lines, 50 files):** `src/corporate.py`, `figures.py`, `reimbursements.py`,
  `valuation.py`, `washes.py`; `src/ledger/lots.py`, `performance.py`, `rules.py`;
  `src/options/__init__.py`, `adjust.py`, `strategies.py`; `src/prices/` (`__init__`, `base`,
  `cboe`, `coinbase`, `manual`, `massive`, `refresh`, `stub`, `tiingo`); migrations 0007,
  0008, 0017, 0018, 0019, 0022, 0030; `src/store/entities/prices.py`,
  `store/repos/rules.py`, `store/tables/options.py`, `store/tables/prices.py`;
  `src/ui/options.py`, `portfolios.py`, `positions.py`, `prices.py`, `reimbursements.py`,
  `rules.py`, `strategies.py`, `transactions.py`; `ui/components/corporate.js`,
  `optiontrade.js`, `rules.js`, `strategies.js`, `txtable.js`; `ui/screens/portfolio-dialog.js`,
  `portfolio.js`, `portfolios.js`, `positions.js`, `transaction-dialog.js`, `transactions.js`.
- **Tests (1,867 lines):** `test_adjusted.py`, `test_figures.py`, `test_options.py`,
  `test_positions.py`, `test_prices.py`, `test_reimbursements.py`, `test_rules.py`,
  `test_strategies.py`.
- **Guides:** `account-holdings`, `account-transactions`, `transactions`, `positions-open`,
  `-closed`, `-gains`, `-strategies`, `-trades`, `portfolios`, `portfolio-holdings`,
  `-performance`, `-projections`, `prices-coinbase`, `-manual`, `-tiingo`, `settings-prices`,
  `dialog-transaction`, `-rule`, `-rules`, `-corporate-action`, `-option-adjust`, `-option-mark`,
  `-option-settle`, `-option-trade`, `-strategy`, `-portfolio`, `-group`, `-assign`,
  `-adjustment`.
- **Cites no section:** `store/entities/prices.py` (judged when read).
- Shared with earlier units: the ledger repo (`store/repos/ledger.py`) and the importers are
  unit 01's (its U01-3 on `kept_by_snapshots`, U01-13 on B7's rerun test, U01-15 on a coin and
  a stock sharing a ticker); not raised again here.

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 2,921 lines (26%), 13 new files. Where it is (diffs in the job's `tmp/u03/`,
renames set aside):

- New: `corporate.py` (132) and `mig/0019` with `ui/components/corporate.js` (N4: symbol
  change, spin-off, merger); `ledger/rules.py` (81), `store/repos/rules.py` (108),
  `ui/rules.py` (287), `mig/0018`, `ui/components/rules.js` (N1: categorisation rules, S2.7);
  `reimbursements.py` (143), `ui/reimbursements.py` (206), `mig/0030` (S2.9, milestone 10);
  `mig/0017_figures.py` (cents for B23); `mig/0022_typed_prices_are_their_typers.py` (P7's typed
  prices, S4.10).
- `ledger/lots.py` (+301/−31): written options short-term (B11), the one anniversary rule
  `long_term` (B22), replacements carry `heldFrom` apart from `acquiredOn` (B2), IRA and Roth
  replacements add no basis (C46), assignment premium folded at replay (B12), corporate
  actions' pairs, `kept_by_snapshots` and snapshots as a check (B9), average cost over the pool
  (B1), return of capital over every lot with excess as gain (B10), short stock from an
  assignment with no shares (N7).
- `washes.py` (+59/−19): losses found on the adjusted replay until nothing changes (B2);
  shares from an option never a replacement (B8).
- `prices/refresh.py` (+75/−14): only held or watched instruments, options until expiry
  (B34), a bad answer fails one source for one instrument (B37), `status` per viewer (S4.10).
- `valuation.py` (+69/−18): typed prices per owner, the last-trade fallback from the owner's
  own accounts (P7, S4.10), typed price stale after 90 days.
- `ui/transactions.py` (+128/−19), `transaction-dialog.js` (+105/−10): closed-year refusal (N5,
  S2.8), reimbursable fields, rules on save, transfer-in edits reaching the lot (B37),
  deleting an assignment deletes its stock leg (B12).
- `options/__init__.py` (+16/−31), `options/strategies.py` (+52/−12), `ui/options.py` (+83/−2):
  expiry on the expiry day's close only (A26), strategy risk at open kept, closing on any
  outcome, unlimited risk (B12), the option-trade figures (S3.9).
- `ui/portfolios.py` (+35/−7): `with_deleted` for returns (B22); `ui/prices.py` (+32/−27):
  typed prices per typer; `figures.py`, `store/tables/prices.py`, `entities/prices.py`: small.
- Tests: `test_positions.py` +168, `test_prices.py` +84, `test_options.py` +99,
  `test_figures.py` +47, `test_strategies.py` +36, `test_reimbursements.py` and
  `test_rules.py` new.

### 3. Earlier reviews' findings in this area

Review 1: only its point 12 (Treasury data in S4.3; a document matter). Review 2, all marked
done in §12.2 (milestone 8 or 9): **B1** (average cost), **B2** (chained wash sales, tacked
date sorts FIFO), **B7** (method on every sale; rerun on a method change, test still missing:
unit 01's U01-13), **B8** (assignment stock as replacement), **B9** (positions as a check;
unit 01's import side), **B10** (return of capital), **B11** (written option short-term),
**B12** (assignment premium, deleting an assignment, risk at open, closing on assignment,
unlimited risk), **B22** (one anniversary rule; a portfolio's returns keep a deleted account),
**B23** (cents in `options.py`, `Transaction.proceedsAdjustment`), **B34** (refresh only held,
options until expiry, option staleness), **B37** (transfer-in edits reach holdings; one bad
answer aborts the refresh), **N1** (rules), **N4** (corporate actions), **N5** (closed years),
**N7** (assignment with no shares a short sale), **P7** (typed prices server-wide; last-trade
fallback reads every user's trades), **C45** (stale statement value alerts), **C46** (IRA
replacement), **C47** (strike to the thousandth), **A26** (expiry on the day's close only),
**A27** (backfill; benchmarks). Later: N3 (L5, portfolio allocation and the rest), N6 (L9,
Alpha Vantage and CoinGecko). Each re-checked below.

### 4. Phase 1 claims and decisions on these sections

- **D1-1** (needs the user, Med): a short option's capital at risk, S3.9.2's strike × shares
  against S3.5.5's *unlimited*; the code judged against both readings.
- **D1-12** (needs the user, Low): which price sources a new server has on, against R3.5; the
  code judged against both readings.
- **D1-3** (R2.8's "a part of" its accounts vs S5 and L5), **D1-9** (where a possible wash sale
  is listed), **D1-10** (two forms of "the OCC ticker"), **D1-11** (S4.5's mark inside its item
  3), **D1-14** (a quarterly statement's value alerts before the next can arrive), **D1-15**
  (the 60/40 benchmark unspecified), **D1-16** (an option trade an entity), **D1-20**
  (allocation shown, not specified), **D1-21** (net worth stacked by group), **D1-22**
  (**Mark…** vs **Type a mark**), **D2-26** (^VIX from Stooq in the mockup): documents; what
  the code does is noted where it bears.
- No decision recorded yet; none is a §6 gate.

### 5. Untraced candidates and uncited first-level items

- Untraced candidate: `store/entities/prices.py` (no cite).
- Uncited first-level items: S2.1 (instruments), S4.1 (free and daily), S4.8, S4.9; judged
  below under **Uncited first-level items**.

## Claims

(Work-pad ids U03-n; kinds and format per §7. Severity, confirmations (0) and status (open)
are in the table at the end.)

### U03-1: the underlying of an option held on its own is never priced

- **Kind:** differs. **Req:** S4.4 ("loads the day's close for every **held or watched**
  instrument"), S3.6 (expiry "by the underlying's closing price"), S3.7 and S4.5 (intrinsic
  value "the underlying's latest close"), S3.5.4–5 (shares and *now* at today's prices).
- **Code:** `web/server/src/moolakata/prices/refresh.py:183-199`, `priced()` starts from
  `held()`, the instruments an open lot holds, and nothing adds an open option's underlying:
  ```text
  def priced(s: Session, benchmarks: bool = True) -> list[tuple[Instrument, dt.date]]:
      """Every instrument held in a live account, or used as a benchmark, ...
      holding = held(s)
      ...
          if iid in holding:
              firsts[iid] = day
  ```
  and `refresh.py:329-337` fetches an option by its own OCC ticker only. Nothing in the unit
  "watches" an instrument (no watchlist table or route).
- **What goes wrong:** a cash-secured put or a long call on a stock the account doesn't hold
  (the usual case for both) leaves the stock unpriced for ever. Case: Alice sells to open 1 XYZ
  50 P; the refresh fetches `XYZ 20NOV26 50 P` and never `XYZ`. Then (1) `expire_due`
  (`options/__init__.py:227`) finds no close on the expiry day, so an option that expired out
  of the money is never applied automatically, and S3.6's "applied automatically the day
  after" becomes a question every time; (2) an option with no source mark has no intrinsic
  value (`valuation.intrinsic` needs `per_share`), so its position is unvalued; (3) the Open
  tab's *in the money* flag and the expiring-soon list read `per_share`, which falls back to
  the owner's own last trade in the stock (`valuation.prices`, `source "trade"`), however old.
  With U03-2, the fallback can even decide an expiry wrongly.
- **Run:** yes, a scratch test (`tmp/u03/t/test_u03.py::
  test_underlying_of_an_option_alone_is_not_priced`): after a sell-to-open on XYZ,
  `priced(s, benchmarks=False)` is `['XYZ 20NOV26 50 P']`. `test_options.py`'s expiry test
  inserts the underlying's close by hand, so no test sees this.
- **Remedy:** `priced()` adds the underlying (and an adjusted contract's deliverable parts) of
  every option an open lot holds, from the option's first transaction, and keeps it until the
  day after the option's expiry.
- **Alternatives:** have CBOE's chain answer, which carries the underlying's quote, store the
  underlying's close with the option marks (only when CBOE is the option source).

- **Check:** confirmed. Read `refresh.priced()`/`held()` (an option's own lots only; the underlying is added nowhere), `refresh()` (an option is fetched by its OCC ticker alone) and S4.4 (no watchlist exists anywhere in `prices/`, `ui/prices.py` or the tables); reran the scratch test: after a sell-to-open on XYZ, `priced()` is `['XYZ 20NOV26 50 P']`. It holds where the stock is held in no live account (held elsewhere it is priced); `valuation.intrinsic` and `expire_due` both go through `per_share`, which then has no close.

### U03-2: an automatic expiry is decided by any trade, any user's, on the expiry day, not by a close

- **Kind:** differs. **Req:** S3.6 ("The close used is the expiry day's; without it, the user
  is asked too"), S4.10 ("never from another user's").
- **Code:** `web/server/src/moolakata/options/__init__.py:227-232`:
  ```text
  close = per_share(s, c, c.expiry)
  if close is None or close[1] != c.expiry:
      continue  # only the expiry day's close decides (S3.6)
  if in_the_money(c, close[0]):
      continue
  settle(s, a.ownerId, a, s.get(Instrument, iid), "expired", c.expiry)
  ```
  `per_share` is called without an owner, so `valuation.prices(..., owner=None)`
  (`valuation.py:96-123`) falls back, with no `_owned` filter, to any account's statement value
  and then to **any user's last trade** of the stock on or before the day, as `source "trade"`.
  The check only asks that its date be the expiry day.
- **What goes wrong:** where no close is stored for the underlying (always so under U03-1, and
  for any day a source failed), a trade on the expiry day stands in for the close. Case: Alice
  is short 1 XYZ 55 C, not holding XYZ; XYZ closes at 56 on the expiry day, so the call was
  assigned. That morning Bob, another user, bought XYZ at 54 (or recorded an assignment of a
  52 put, whose stock leg is dated that day at 52). The next day `expire_due` takes 54 as the
  close, finds the call out of the money, and records it as **expired worthless** in Alice's
  account: her realized gain counts the whole credit, and the assignment's shares and cash are
  missing until she notices. Bob's trade also reaches Alice's account, against S4.10.
- **Run:** no; reading alone (the path is the one U03-1's run shows has no close).
- **Remedy:** `expire_due` reads only a stored close (`source == "close"`) for the expiry day,
  as `valuation.prices` would with the account owner; a typed price of the owner's may count
  if S3.6 is read to allow it.
- **Alternatives:** pass the account's owner to `per_share`, and refuse `source` `trade` and
  `statement` for this decision.

- **Check:** confirmed. Read `expire_due` (`per_share` called with no owner, only `close[1] != c.expiry` guards) and `valuation.prices` (owner None: `_owned` adds no filter, so any account's statement value and any user's last trade of the instrument, `source "trade"`, stand in); `Instrument` rows are shared across users (`repo.instrument` looks up by symbol). Contradicts S4.10 and valuation's own docstring ("Another user's ... trades never value an account"). Reading alone.

### U03-3: withheld

- **Kind:** security. **Severity:** Med. **Withheld** (details in `withheld.md`, §2).

- **Check:** corrected.

### U03-4: a specific-identification pick of a lot a wash sale split takes the rest from another lot

- **Kind:** wrong figure. **Req:** S2.3 (specific identification, "chosen per sale"), S3.8.3
  ("Where only some of a lot replaces, that part is split into its own lot").
- **Code:** `web/server/src/moolakata/ledger/lots.py:252-261`, the replacement part keeps the
  lot's id:
  ```text
  out.open.append(
      OpenLot(
          lot.lotId,
          lot.instrumentId,
  ```
  and `lots.py:636-643`, the picks find a lot by its id through a dict, which keeps one of the
  two parts:
  ```text
  if method == "specific" and picks:
      by_id = {lot.lotId: lot for lot in held}
      for p in picks:
          lot = by_id.get(p.lotId)
          take = min(p.quantity, lot.quantity, left) if lot else ZERO
  ```
  What the pick can't take from that part falls through to FIFO (`lots.py:644-652`).
- **What goes wrong:** Case (run): buy 10 AAPL at $100 on 2025-01-02 (lot K); buy 4 at $200
  on 2026-03-02 (M); sell M's 4 at $150 on 2026-03-20 (a $200 loss); buy 10 at $160 on
  2026-04-01 (L), 4 of which replace, so L shows as 6 (basis $960) and 4 (basis $840, held
  from 2026-03-14). Selling 10 on 2026-05-01 with the pick "lot L, 10" takes L's 4-share part
  and then **6 shares of K**, FIFO: L's other 6 stay open, K drops to 4. The sale's gain is
  worked out on K's $100 basis, long-term, instead of L's, short-term; the Open tab and Form
  8949 follow.
- **Run:** yes, `tmp/u03/t/test_u03.py::test_partial_wash_then_pick`: after the pick, the
  open lots are K 4 ($400) and L 6 ($960).
- **Remedy:** give the replacement part its own key (the lot's id with a suffix, or keep a
  list of parts per id) and let a pick of the lot take every part of it, the replacement part
  first or by the method's order within the lot.
- **Alternatives:** key `by_id` to a list of parts and spend the pick across them.

- **Check:** confirmed. Read `_replacement` (the split-off part is appended with `lot.lotId`, so two open lots share one id) and `_consume` (`by_id = {lot.lotId: lot ...}` keeps the later one; the pick's remainder falls to the method's order); reran the scratch test `test_partial_wash_then_pick`: after the pick the open lots are K 4 ($400) and L 6 ($960), as claimed.

### U03-5: a buy in another account that washes a closed year's loss changes that year unasked

- **Kind:** differs. **Req:** S2.8, S2.8.2 ("When it moves the realized gains of a closed year,
  it is refused with the years named"), S2.8.3, S3.8.4.
- **Code:** `web/server/src/moolakata/taxes/closed.py:60-63` (unit 04's file, used here), the
  guard looks at the edited account only:
  ```text
  def __init__(self, s: Session, account: Account, confirm: bool, by: str | None = None):
      self.s, self.account, self.confirm, self.by = s, account, confirm, by
      self.books = closing_books(s, account)
      self.before = gains(s, account, set(self.books)) if self.books else {}
  ```
  while `ui/transactions.py:683-686` reruns the whole household's wash sales before it checks:
  ```text
  if inst_id:
      washes.recompute(s, a.ownerId)
  if guard is not None:
      guard.check()
  ```
- **What goes wrong:** a wash sale across the year end is the classic case. Case (run): a
  brokerage sells 10 AAPL on 2025-12-20 at a $500 loss; the 2025 federal return is filed. On
  2026-01-05 the user records a buy of 10 AAPL in their **IRA**. The request answers 201 with
  no question, and the 2025 sale's realized loss goes from −500.00 to 0.00. Nothing is
  recorded on the 2025 tax book (S2.8.3), so the filed return no longer matches and nobody is
  told. The same happens with a buy in another taxable account, a spouse's account, an import,
  or a deleted buy that no longer replaces.
- **Run:** yes, `tmp/u03/t/test_u03.py::test_a_buy_in_another_account_moves_a_closed_year_unasked`:
  status 201, the 2025 sale −500.00 → 0.00.
- **Remedy:** the guard takes a before and after of every account whose gains the wash-sale
  rerun can move (the household's taxable accounts), or compares the household's `WashSale`
  rows before and after the rerun and checks the closed years of each sale whose row changed.
- **Alternatives:** the rerun keeps a closed year's wash sales as they were unless confirmed,
  and lists the change on the tax book.

- **Check:** confirmed. Read `closed.Guard` (before and after `gains` for the edited account only, `closing_books(s, account)`) and `create_transaction` (`washes.recompute(s, a.ownerId)` reruns the household's wash sales before `guard.check()`); the same pair is used by update, delete and settle. S2.8.2 says "moves the realized gains of a closed year" with no limit to the edited account. Reran the scratch test: status 201, the 2025 sale -500.00 to 0.00.

### U03-6: shares moved in or out count as growth in a portfolio's returns and contributions

- **Kind:** wrong figure. **Req:** S5.2.1 ("contributions shown apart from growth"), S5.2.2
  (time- and money-weighted returns).
- **Code:** `web/server/src/moolakata/figures.py:50` and `ui/portfolios.py:439` call
  ```text
  flows = perf.flows(led.transactions)
  ```
  without `prices`, and `ledger/performance.py:28-32` counts a securities transfer only with a
  price:
  ```text
  elif t.kind in ("transfer-in", "transfer-out") and t.instrumentId and t.quantity:
      price = (prices or {}).get(t.instrumentId, {}).get(t.date)
      if price is not None:
  ```
  No caller passes `prices`, so no transfer of shares is ever a flow.
- **What goes wrong:** Case: a portfolio holds a $100,000 brokerage; in June the household
  moves $50,000 of shares in from another broker (ACATS), or in December gives $20,000 of
  appreciated shares to its DAF (S7.9). The value series jumps by $50,000 or drops by $20,000,
  and the time-weighted return, IRR, *contributed* and *growth* take each as gain or loss:
  the year's TWR shows about +50% (or −20%) of performance that is no performance, and the
  benchmark line (`perf.benchmark`) gets no matching money. A transfer between two accounts
  of the same portfolio nets out; one from or to outside doesn't.
- **Run:** no; reading alone (`test_figures.py::test_flows_count_money_in_and_out_not_income`
  passes no securities transfer).
- **Remedy:** `combine` and `portfolio_returns` pass the instruments' price points
  (`valuation.price_points` for the transferred instruments) to `perf.flows`, falling back to
  the transfer's basis when no price is known for the day.
- **Alternatives:** value a transfer at its own `price` or `costBasis` when it carries one.

- **Check:** confirmed. Read `perf.flows` (a securities transfer counts only with a price from `prices`) and its two callers, `figures.combine` and `ui/portfolios.py`: neither passes `prices`; a share transfer's `amount` is 0 in the scratch tests (kind `transfer-in`, not `EXTERNAL`'s cash kinds), so no cash flow is recorded either. `valuation.series` values the arrived shares, so the series jumps without a flow. `test_figures.py` has no securities transfer. Reading alone.

### U03-7: any edit of a split transaction loses its paybacks: the paid-back part is awaited again

- **Kind:** bug. **Req:** S2.9 (a split marked to be paid back), S2.9.1, S2.9.2, S2.9.3.
- **Code:** `web/server/src/moolakata/ui/transactions.py:533-549`, every save replaces the
  splits with new rows and new ids:
  ```text
  def _set_splits(s: Session, t: Transaction, splits: list[SplitIn], by: str) -> None:
      for old in s.scalars(
          select(Split).where(Split.transactionId == t.id, Split.deleted == false())
      ):
          old.mark_deleted(by)
      for sp in splits:
          s.add(
              Split(
                  id=ids.new_id("Split"),
  ```
  called at `:785-787` whenever `splits` is sent, and `web/ui/screens/transaction-dialog.js:109`
  sends `splits` on every save. A pairing is keyed to the split's id
  (`reimbursements.py:86-88`, `paid[(r.spendingId, r.splitId)]`), so it stays on the deleted
  split.
- **What goes wrong:** Case (run): a $100 hotel bill split $50 / $50, the second part marked
  to be paid back by Acme and paired with Acme's $50 deposit; awaited $0. The owner opens the
  transaction and adds a memo. Afterwards the part shows **$50 awaited** under *Awaiting
  reimbursement*, ageing, while the deposit's $50 still counts as paired (`paired_out` 50.00),
  so it is no longer offered to pair again. If the owner then takes the mark off as "never paid
  back" (S2.9.3), the $50 counts as spending again while the deposit's $50 stays out of income.
- **Run:** yes, `tmp/u03/t/test_u03.py::test_editing_a_split_transaction_orphans_its_payback`:
  awaited `0.00 → 50.00`, the deposit still paired `50.00`.
- **Remedy:** `_set_splits` updates splits in place (the dialog sends each split's id, and the
  server keeps the rows whose id comes back), and only a split removed loses its pairings,
  which are then deleted with it.
- **Alternatives:** leave the splits alone when the list sent equals the one stored; or move a
  deleted split's pairings to the new split at the same position with the same mark.

- **Check:** confirmed. Read `_set_splits` (marks every old split deleted and adds rows with new ids), the PATCH route (`splits` in `sent` calls it) and the dialog (`body()` always sends `splits`), and `reimbursements.marked` (pairs keyed by `(spendingId, splitId)`, so they stay on the deleted split); reran the scratch test: awaited 0.00 to 50.00, the deposit still paired at 50.00.

### U03-8: a short sale's loss is taken as a wash sale and adjusted, where S3.8.5.1 flags it

- **Kind:** differs. **Req:** S3.8.5, S3.8.5.1 ("a loss on a **short sale** closed with shares
  bought within 30 days … flagged for review, never adjusted"), S3.4 (the short stock lot of an
  assignment with no shares).
- **Code:** `web/server/src/moolakata/ledger/lots.py:567-579`, shares bought while short close
  the short through `_cover`, whose disposal carries the buy as its `saleId`; and
  `web/server/src/moolakata/washes.py:129-132` takes every losing disposal of a stock as a
  loss sale, short covers included:
  ```text
  for d in led.replay().disposals:
      raw = d.raw_gain
      if d.instrumentId in classes and raw is not None and raw < 0 and d.saleId:
          losses.append((led.account, d))
  ```
- **What goes wrong:** Case (run): short 1 XYZ 50 C for $100, assigned on 2026-08-21 with no
  XYZ held, so the account is short 100 XYZ at 50 (S3.4). Shares bought on 08-25 at 60 cover it,
  a $900 loss. Another 100 bought on 09-05 at 58 are taken as its replacement: the whole $900
  is disallowed (realized 0.00, **W** 900.00) and added to the 09-05 lot's basis, though S3.8.5.1
  says the rules are unsettled there and only the preparer decides. The Closed tab names the
  cover's *how* as "buy".
- **Run:** yes, `tmp/u03/t/test_u03.py::test_a_short_sale_loss_is_adjusted_not_flagged`:
  one `WashSale` of 100 shares, $900 disallowed.
- **Remedy:** `washes._round` skips a disposal that closes a short (`d.written` on a stock, or a
  flag `short` on `Disposal`), leaving it to the S3.8.5.1 issue; `ui/positions._how` names a
  short cover *bought back*.
- **Alternatives:** none reasonable; the rule is the requirement's.

- **Check:** corrected. The code does take a short cover's loss as a wash sale (reran: one `WashSale` of 100 shares, $900.00), but S3.8.5.1 does not flag the claim's case: its short-sale item is a loss closed with shares bought within 30 days of another short sale of the stock, or of opening one, and a later plain purchase (09-05) is neither. What the requirements rule out is the adjustment: S3.8.1 matches a loss *sale*, and S3.8.5 says short-sale cases are never adjusted. Restate the requirement as S3.8.1 and S3.8.5; the remedy (skip a short cover in `washes._round`) and Low stand; the Closed tab's *buy* wording is a separate small point. Severity unchanged.

### U03-9: a portfolio's Holdings tab counts a loan's payments as cash, and leaves out items

- **Kind:** wrong figure. **Req:** S5.2.3 (Holdings: what the portfolio holds), S5.1.1 ("the
  portfolio's value is the value of what they can see"), S1.9 and S1.10 (a loan counts what is
  owed, an item what it is worth).
- **Code:** `web/server/src/moolakata/ui/portfolios.py:469-473`:
  ```text
  for a in accounts:
      led = repo.load(s, a)
      cash += led.balance()
      if not atypes.investing(a.type):
          continue
  ```
  and `:501`, `total = cash + sum(...)`. A loan's ledger balance is the sum of what was paid
  into it, not what is owed (`valuation.account_value` uses `loans.value` for that, and
  `assets.value` for items); the portfolio row's `value` (`value_of`, `:123-127`) does.
- **What goes wrong:** *All my accounts* holds every account. Case (run): checking $5,000 and a
  mortgage account with one $2,000 payment in it. The portfolio's value is $5,000 (what the
  mortgage owes counts against it once its terms are set); its Holdings tab shows *Cash in
  these accounts* $7,000 and *Total* $7,000. After five years of payments the "cash" holds
  every payment ever made, a house and its car are left out, and every holding's weight is
  taken against that wrong total.
- **Run:** yes, `tmp/u03/t/test_u03.py::test_holdings_cash_counts_a_loans_payments`: holdings
  cash 7000.00, total 7000.00, portfolio value 5000.00.
- **Remedy:** the Holdings tab counts cash only from bank and investing accounts, shows loans
  (what is owed) and physical-asset accounts (their items' value) as rows of their own, and its
  total is `value_of` the same accounts.
- **Alternatives:** leave loans and physical assets out of the Holdings tab, saying so under
  the table, with the total of what it lists.

- **Check:** confirmed. Read `portfolio_holdings` (`cash += led.balance()` before the `investing` test, for every account) against `valuation.account_value` (loan: `loans.value`, physical asset: `assets.value`) that `value_of` uses; reran the scratch test: holdings cash 7000.00 and total 7000.00, portfolio value 5000.00.

### U03-10: a corporate action is checked and sized by today's holding, not by the holding on its date

- **Kind:** bug. **Req:** S2.4, S2.4.1 ("the holding, the date, and what the action needs"),
  S2.8 (editing history is allowed), S3.10.1.
- **Code:** `web/server/src/moolakata/corporate.py:42-44`:
  ```text
  held = repo.load(s, account).replay().quantity(inst.id)
  if held <= 0:
      e.append(FieldError("instrumentId", "nothing-held", "Nothing of it is held here."))
  ```
  `held` is today's quantity, and sizes the merger's cash (`:81`) and the legs' quantities
  (`:83`, `:95`). `options/adjust.py:115-122` (`open_contracts`) and `:78` (`carry`) likewise
  take the options open today for a split dated in the past. The dialog
  (`web/ui/components/corporate.js:25-29`) offers only holdings open now.
- **What goes wrong:** history entered late can't be completed. Case: XYZ spun off NEWCO on
  2026-03-02 (Form 8937: 13.65% of the basis moves); the household sold all its XYZ in May and
  records the spin-off in October while checking its 1099-B. It is refused ("Nothing of it is
  held here"), so the sold lots keep their whole basis and the NEWCO shares that arrived have
  none: the May sale's gain is understated by the basis that should have moved, and NEWCO
  shows *basis missing*. A split recorded late adjusts options opened after it (pairs that move
  nothing) and misses those open at the split and closed since, whose closing trades then
  stand against a contract never opened (*close-without-open*) while the old one stays open.
- **Run:** no; reading alone.
- **Remedy:** replay the account up to the action's date (`replay` over the transactions dated
  on or before it) for the check, the quantities and the cash, and for the options open on that
  day; the dialog lists what was held on the date chosen.
- **Alternatives:** none simpler that keeps late entry working.

- **Check:** confirmed. Read `corporate.record` (`replay().quantity(inst.id)` with no date, refusing at 0 and sizing the merger's cash and legs), `adjust.carry` and `open_contracts` (today's quantity), and the dialog (lists only open holdings). A holding sold after the action's date is refused, so late entry fails as claimed; no test dates an action before a later sale. Reading alone.

### U03-11: a statement value is never marked stale, and Positions shows no price date or staleness

- **Kind:** differs. **Req:** S4.3 ("A statement value older than 90 days is marked stale"),
  S4.7 ("The UI shows *delayed* or *as of 4:00 PM* on every value derived from it. A price older
  than a threshold … is marked stale").
- **Code:** `web/server/src/moolakata/valuation.py:108-109`, a statement's price is made with
  `stale` left at its default, `False`:
  ```text
  if h.quantity:
      out[h.instrumentId] = Price(h.marketValue / h.quantity, h.asOf, "statement")
  ```
  (`prices/refresh.py:46-47` knows the 90 days, but only for stored `Price` rows, and statement
  values are `Holding` rows). `ui/positions.py:38-59`, `OpenRow` carries `priceSource` and no
  `priceAsOf` or `stale`, and `web/ui/screens/positions.js:189-193` shows only the source's word.
- **What goes wrong:** Case: a 401(k) collective trust valued from a statement dated
  2026-03-31. In October the portfolio's Holdings tab shows it without the *stale* pill, as
  current, though the alert of `alerts.py:509` fires for the same value. On Positions › Open,
  no position shows the date of its price, and a stock whose close is a week old (a source
  failing) looks as fresh as today's.
- **Run:** no; reading alone.
- **Remedy:** `valuation.prices` sets `stale` on a statement value by `refresh.is_stale(cls,
  "statement", asOf, day)`; `OpenRow` gains `priceAsOf` and `stale`, shown as the portfolio's
  Holdings tab shows them.
- **Alternatives:** none.

- **Check:** confirmed. Read `valuation.prices` (the statement `Price` takes `stale` False), `refresh.is_stale` (knows `"statement"` but only `stored_closes` calls it), `OpenRow` (no `priceAsOf` or `stale`) and `positions.js` (shows the source's word only), against `alerts.statement_values`, which does test 90 days. S4.3 and S4.7 as quoted. Reading alone.

### U03-12: a period's return is shown over less than the period when the history is shorter

- **Kind:** differs. **Req:** S5.2.2 (returns per period); the guide `portfolio-performance.md`
  ("a dash means the history doesn't go back that far").
- **Code:** `web/server/src/moolakata/figures.py:280-290`:
  ```text
  started = next((d for d, v in values if v), values[0][0])
  for key in ("1M", "3M", "YTD", "1Y", "3Y", "5Y"):
      first = first_day(key, today, None)
      if first < started and key in ("3Y", "5Y"):
          out[key] = None
          continue
      window = [(d, v) for d, v in values if d >= max(first, started)]
  ```
  Only 3Y and 5Y are left out when the history is shorter; the docstring (`:275-276`) says
  "none when the history doesn't reach back that far" for all of them.
- **What goes wrong:** Case: an account opened on 2026-07-01 that has gained 8% since. On
  2026-10-13 its *1Y* (and *YTD*) return reads 8.00%, the same as its 3M, as if it were a year's
  return; a reader comparing accounts takes a 3½-month gain for a 12-month one.
- **Run:** no; reading alone.
- **Remedy:** a period that starts before the history does is `None` (a dash), as for 3Y and
  5Y; YTD may keep the partial year if S5.2.2 says so.
- **Alternatives:** keep the figure and mark it *since <date>*.

- **Check:** corrected. **Lines:** the code is `figures.py:130-136` (`period_returns`) and its docstring `:125-126`, not 280-290/275-276 (the file has 162 lines). The behaviour holds (only 3Y and 5Y return None before `started`; 1M, 3M, YTD and 1Y start at `started`), but S5.2.2 is silent on short histories: the basis is the guide `portfolio-performance.md` ("a dash means the history doesn't go back that far", which can be read as only the sentence's 3 and 5 years) and the docstring. Severity unchanged.

### U03-13: the Gains tab counts a position with long- and short-term lots as all short-term

- **Kind:** wrong figure. **Req:** S3.9 ("unrealized now", with short- or long-term status per
  lot, S3.1).
- **Code:** `web/server/src/moolakata/ui/positions.py:316-323`:
  ```text
  for r in open_rows:
      if r.unrealized is None:
          continue
      ...
      g = un.setdefault(key, [ZERO, ZERO])
      g[1 if r.term == "long" else 0] += r.unrealized
  ```
  `r.term` is `mixed` whenever its lots differ (`_term`, `:107-112`), and a mixed position's
  whole gain goes to short-term.
- **What goes wrong:** Case: 100 VTI bought in 2023 (+$9,000 now) and 1 more last month (+$5).
  The Gains tab's unrealized row shows short-term $9,005 and long-term $0, the opposite of what
  selling would realize; someone deciding what to sell before year end reads it the wrong way.
- **Run:** no; reading alone.
- **Remedy:** split each position's unrealized gain by lot: each lot's value (its quantity at
  the position's price) less its basis, to the lot's term (by `heldFrom` or `acquiredOn`).
- **Alternatives:** none.

- **Check:** confirmed. Read `positions.gains` (`g[1 if r.term == "long" else 0] += r.unrealized`) and `_term` ("mixed" when the lots differ): a mixed position's whole gain goes to short-term. S3.9 and S3.1 as quoted. Reading alone.

### U03-14: the option's end can't be recorded "anyway" in a closed year

- **Kind:** differs. **Req:** S2.8.2 ("the dialog offers to make it anyway"), S3.4, S3.6.
- **Code:** `web/ui/components/optiontrade.js:153-158`, the Settle dialog posts without
  `confirm` and has no second button:
  ```js
  const save = useSubmit(async () => {
    await api.post(`/accounts/${row.accountId}/options/${row.instrumentId}/settle`, {
      how: f.how,
      date: f.date,
      contracts: clean(f.contracts),
    });
  ```
  while `ui/options.py:141-144` guards the route and answers 409 `closed-year`. The trade,
  corporate-action and transaction dialogs each offer *… anyway* (`optiontrade.js:63`,
  `corporate.js:57`, `transaction-dialog.js:171-172`).
- **What goes wrong:** Case: a put that expired on 2025-12-19, its end never recorded; the 2025
  return is filed. Recording *Expired worthless* on 2025-12-19 moves 2025's gains, so the dialog
  shows the 409's message and nothing else: the option stays open for ever.
- **Run:** no; reading alone.
- **Remedy:** the Settle dialog handles `closed-year` as the others do (*Record it anyway*,
  `params: { confirm: true }`).
- **Alternatives:** none.

- **Check:** confirmed. Read `Settle` in `optiontrade.js` (posts with no `confirm`, no second button, `FormError` only) and the `settle` route (`closed.Guard` then `guard.check()` raises 409 `closed-year` unless `confirm`); `Trade` and `CorporateAction` handle `closed-year` with *anyway* (`optiontrade.js:63`, `corporate.js:57`). Reading alone.

### U03-15: an option is shown as it is stored (`AAPL 18DEC26 250 C`), not as S2.1 shows it

- **Kind:** differs. **Req:** S2.1 ("stored as people read it, `AAPL 18DEC26 250 C`, and shown as
  `AAPL 18 Dec 26 250 C`"); the mockup shows the second form (`AAPL 18 Dec 26 250 C`,
  `MSFT 16 Oct 26 480 P`).
- **Code:** `web/server/src/moolakata/options/__init__.py:18-21` makes the stored form, and every
  screen prints `symbol` as it comes: `web/ui/screens/positions.js:86`, `:166`, `:284`
  (`${r.symbol}`), the strategies, option trades, corporate-action and settle dialogs
  (`optiontrade.js:164`, `` `${row.symbol}: what happened?` ``). No formatter turns
  `18DEC26` into `18 Dec 26` (`app/format.js` has none).
- **What goes wrong:** every option reads `MSFT 20NOV26 480 P` on Positions, Strategies, Option
  trades and in dialog titles, where the requirement and the mockup show `MSFT 20 Nov 26 480 P`.
- **Run:** no; reading alone (S2.1 is a first-level item no code cites).
- **Remedy:** one formatter in `app/format.js` for an option's symbol (`/^(\S+) (\d\d)([A-Z]{3})(\d\d) /`
  → `$1 $2 ${Mon} $4 `), used wherever an instrument's symbol is shown.
- **Alternatives:** the server sends a `display` beside `symbol`.

- **Check:** confirmed. Read `options.symbol` (stored form), `positions.js` and the dialogs (print `symbol` as it comes), `app/format.js` (no option formatter), S2.1 line 7 and the mockup (`AAPL 18 Dec 26 250 C`). Reading alone.

### U03-16: shares transferred in start their holding period on the day they arrive

- **Kind:** wrong figure. **Req:** S2.2 (lots created "by transfers in with a cost basis"),
  S2.4.1 ("Each lot keeps the day it was acquired"), S3.1 (days held, short- or long-term per
  lot); IRC §1223 (a carried-over basis carries its holding period).
- **Code:** `web/server/src/moolakata/ui/transactions.py:645-658`, a transfer-in's lot is
  acquired on the transaction's date, and `TxnIn` (`:126-148`) has no field for when the shares
  were bought:
  ```text
  if inst_id and body.kind in ("buy", "reinvest", "transfer-in"):
      basis = body.costBasis if body.kind == "transfer-in" else -body.amount
      s.add(
          Lot(
              ...
              acquiredOn=body.date,
  ```
  and an edit moves it to the new date again (`:777-782`). `Replay.moved`
  (`ledger/lots.py:99-101, 676-677`), which keeps the lots a transfer out took, is read only by
  bitcoin's pairs (`bitcoin/transfers.py:121`); a matched transfer of shares opens no carried
  lots (run: a transfer out and in linked by hand leave the shares *basis missing*).
- **What goes wrong:** Case: 100 VTI bought in 2019 at Schwab, moved to Fidelity on 2026-01-10
  (ACATS) and recorded as a transfer-in with its $15,000 basis, sold on 2026-03-02 at a $9,000
  gain. MoolaKata counts the lot as acquired 2026-01-10: the gain is short-term on the Closed
  and Gains tabs and on Form 8949 (box A/B instead of D/E), taxed at the ordinary rate, and the
  Open tab showed it short-term the whole time.
- **Run:** partly: `tmp/u03/t/test_u03.py::test_shares_moved_between_brokers_are_their_own_replacement`
  shows a linked transfer of shares carries no lots; the acquired date rests on reading.
- **Remedy:** a transfer-in of shares takes the day (or days, per lot) they were acquired, as it
  takes their basis; a transfer linked to the owner's transfer out opens the lots it left with,
  as bitcoin's pairs do (`Replay.moved`).
- **Alternatives:** S2.2 says a transfer-in asks for each lot's basis and acquired date, and the
  dialog offers several lots.

- **Check:** plausible. **Question:** should shares moved between the owner's own accounts (not bitcoin) arrive with the days they were acquired, or is a transfer in new shares from its own date until someone can type otherwise? S2.2 asks a transfer in only for a cost basis (the claim's Alternatives misquotes it as also asking an acquired date), S2.4.1 and S3.1 speak of lots that already exist, and S1.7.1's carried lots are bitcoin's alone. The code does what the claim says (`acquiredOn=body.date`; no acquired-date field in `TxnIn`; a linked transfer of shares opens no carried lots, rerun: basis missing); under a reading that holding periods carry over (IRC §1223, S3.1's short- or long-term per lot) it is a wrong figure, otherwise a gap.

### U03-17: the header calls prices stale for ever when anything is valued from a statement or at intrinsic value

- **Kind:** bug. **Req:** S4.7 (stale past a threshold), S4.3 (a statement value is stale
  after 90 days), S12.5 (the header's price status).
- **Code:** `web/server/src/moolakata/prices/refresh.py:398-406`:
  ```text
  ids = [i.id for i, _ in priced(s, benchmarks=False)] if viewer is None else _held_by(s, viewer)
  today = clock.today()
  closes = stored_closes(s, ids, today)
  ...
  stale = any(p.stale for p in closes.values()) or (bool(ids) and len(closes) < len(ids))
  ```
  Only stored closes and the viewer's typed prices count; a holding valued from a statement
  (`Holding.marketValue`), at intrinsic value, or by the owner's last trade has no stored close,
  so it makes the whole status stale.
- **What goes wrong:** Case: a household holds a 401(k) collective trust valued from last
  week's statement (S4.3's "No free ticker" row) next to stocks priced this evening. The header
  dot shows *stale* ("Some prices are older than they should be") every day, for ever. So does
  any option CBOE doesn't list once Massive isn't set up (valued at intrinsic value, S3.7), and
  a stock held in a shared account whose owner typed its price (the viewer's typed prices are
  read, not the owner's). The flag stops meaning anything.
- **Run:** no; reading alone.
- **Remedy:** judge each held instrument by the price that values it (`valuation.prices` with
  the owning account's owner, then intrinsic), stale by its own rule: a statement value after
  90 days, a typed price after 90 days, a close after S4.7's trading days; an instrument with no
  price at all counts as stale.
- **Alternatives:** leave statement-valued and intrinsic-valued instruments out of the header,
  which then speaks for fetched prices only, and say so in its tip.

- **Check:** confirmed. Read `refresh.status` (only `stored_closes` and the viewer's typed prices count, then `len(closes) < len(ids)` marks the whole header stale) and `_held_by`/`priced` (which include a statement-valued or intrinsic-valued holding in `ids`). Holds as claimed; a freshly bought instrument before the evening refresh is a further case. Reading alone.

### U03-18: no symbol is checked with a source before it is used

- **Kind:** not built. **Req:** S4.2.2 ("where it can, `lookup(symbol)` to check a symbol
  before it is used").
- **Code:** `web/server/src/moolakata/prices/base.py:75-77` declares `lookup`, and
  `prices/tiingo.py:49-55` implements it, but nothing calls it (no `.lookup(` outside the
  sources). A typed symbol becomes an instrument at once: `ui/transactions.py:584-590`
  ```text
  if body.symbol:
      symbol = body.symbol.strip().upper()
      ...
      return repo.instrument(s, symbol, None, "crypto" if crypto else "equity").id
  ```
  and likewise the option trade's underlying (`options.contract`) and the corporate action's
  new symbol (`corporate.py:92`).
- **What goes wrong:** Case: a buy typed as `VTIX` instead of `VTI`. MoolaKata makes the
  instrument `VTIX` (class `equity`), the refresh asks CBOE and Tiingo for it every day and
  stores nothing, the position is valued from the buy's own price for ever, and nothing says
  the symbol is unknown. A fund typed by hand is always `equity`, so a mutual fund is asked of
  CBOE first, which doesn't list it (S4.3), and its class is wrong in the wash-sale and
  projection classes.
- **Run:** no; reading alone (search: no caller of `lookup`).
- **Remedy:** on a new symbol, ask the enabled sources that can `lookup` (in
  a job or at the next refresh, never inside the request, S4.6) and mark an instrument no source
  knows (*unknown symbol*) where it is shown; take the class from the answer.
- **Alternatives:** S4.2.2 drops the promise, and the refresh's misses are listed per
  instrument in Settings › Prices.

- **Check:** confirmed. Searched `src/` for callers of `lookup(`: only the declaration in `prices/base.py`, Tiingo's implementation, and unrelated idempotency and invitation lookups; `_instrument` makes `repo.instrument(s, symbol, None, "equity")` at once. S4.2.2 as quoted. Searched, and read the two sources' code.

## Uncited first-level items

- **S2.1** (instruments): built under other words. One `Instrument` per symbol or CUSIP
  (`store/repos/ledger.instrument`), the classes with `money-market` (`store/tables/accounts.py:22`,
  C47's part done), option terms in `OptionContract` with the multiplier 100 by default, the
  stored form `AAPL 18DEC26 250 C` (`options.symbol`). The shown form is not built: U03-15.
- **S4.1** (free and daily, no intraday): built. CBOE takes the day's close only after
  4:15 PM Eastern (`cboe.py:123-131`), Coinbase leaves out the open UTC candle
  (`coinbase.py:161-163`), no source needs a paid plan, and nothing fetches intraday.
- **S4.8** (US dollars only): built by construction: no currency anywhere in the unit's tables
  or sources; Coinbase is asked for `<coin>-USD`, metals through USD proxies.
- **S4.9** (linked servers never call price sources for each other): built as far as this unit
  goes: nothing in `prices/` or `valuation.py` reaches a peer, and the links code (unit 08)
  imports `ui.prices` only for the egress list (`links/manage.py:442`). What a peer's shared data
  carries (values and `as_of`) is unit 08's to judge.

## Phase 1 claims against the code

- **D1-1** (a short option's capital at risk; open, needs the user): the code follows each
  section's text where it applies. Ungrouped, `strategies.risk_of_account` (`:552-562`) counts a
  long option's basis and a short one's strike × multiplier × contracts with no premium off
  (S3.9.2's reading); grouped, `capital_at_risk` gives a short put (no tick) strike × 100 less
  the credit and a naked call *unlimited* or the margin typed (S3.5.5). So the account's total
  depends on **Group**, exactly as D1-1 describes; under D1-1's remedy (an ungrouped leg counted
  by its S3.5.5 row) the ungrouped branch differs. Beside it: `ui/positions.option_trades`
  (`:427-435`) gives a strategy's legs its risk at open only when it is truthy, so a leg of a
  strategy whose risk at open is *unlimited* keeps its own S3.9.2 figure and a return, where
  S3.9.2 says it takes the strategy's. Left to the walk-through with D1-1; no claim.
- **D1-12** (which sources a new server has on; open, needs the user): no `PriceSource` row
  exists until an admin adds one (only `dev/devmode.py:68` makes any), and a keyless source is
  enabled when added (`ui/prices.py:208`). The benchmarks' instruments are made at start
  (`figures.ensure_benchmarks`) and are in `priced()`, but with no source they are counted
  `unpriced` and nothing loads. This matches D1-12's remedy reading (R3.5, off until
  configured; the benchmarks load once a source serving them is on) and differs from the
  alternative (CBOE and Coinbase on at the welcome). The header then says "no prices yet".
- **D1-3**: a portfolio is a set of accounts only (`PortfolioAccount`), as S5 says; R2.8's "a
  part of them" is not built (L5).
- **D1-10**: the code stores `AAPL 18DEC26 250 C`, asks sources with `O:` + root + `yymmdd` +
  `C`/`P` + strike in thousandths (`options.occ`), and reads both the padded and the `O:` form
  on import (`options/adjust.parse_occ`).
- **D1-11**: a typed mark is a `TypedPrice` on the option's instrument, used with any source.
- **D1-15**: the code's 60/40 is 60% VT and 40% BND rebalanced daily (`figures.benchmark_index`,
  `performance.mix`); the guide says "a 60/40 mix of VT and BND".
- **D1-16**: an option trade is worked out on each read (`ui/positions.option_trades`), never
  stored: it fits D1-16's remedy.
- **D1-14, D1-20, D1-21, D1-22, D2-26, D1-9**: the alert (`alerts.py`), the Dashboard and the
  tax book's issues are other units'; the Open tab's button reads **Type a mark…**
  (`positions.js:244`), as S4.5 and the guide say.

## Earlier findings re-checked

- **B1** (average cost): holds. `_consume` re-bases every held lot to the pool's average at
  each sale (`lots.py:653-664`).
- **B2**: holds. Losses are found on the adjusted replay until nothing changes
  (`washes.py:100-109`); FIFO sorts on `acquiredOn`, the tacked date kept apart in `heldFrom`.
- **B7**: the method is recorded on every sale (`ui/transactions.py:634`, `options.settle`,
  `corporate.py:90`); the rerun's test is unit 01's U01-13.
- **B8**: holds (`washes.py:58-78`).
- **B10, B11**: hold (`lots.py:344-378`; `Disposal.written`).
- **B12**: holds: premium folded at replay, deleting an assignment deletes its legs and a leg
  alone is refused (`ui/transactions.py:826-842`), risk at open kept, a strategy closes on any
  outcome (`strategies.view`), unlimited counted as such.
- **B22** (this unit's part): holds; `portfolio_returns` uses `with_deleted` (`:428`).
- **B23** (this unit's part): `deliverableCash` and `proceedsAdjustment` are cents (mig 0017).
- **B34**: half holds. Only held instruments are priced and an option only until expiry, with
  option staleness at one trading day; but "held" leaves out an option's underlying (U03-1).
- **B37** (this unit's part): holds: a transfer-in's lot follows its edit
  (`ui/transactions.py:777-784`); a bad answer fails one source for one instrument
  (`refresh.py:358-367`).
- **N1** (rules): built. **N4** (corporate actions): built; late entry fails (U03-10). **N5** (closed
  years): built; a cross-account wash sale escapes it (U03-5). **N7**: holds; its short sale's
  loss is then washed, not flagged (U03-8).
- **P7** (typed prices): holds for valuing accounts (`valuation._owned`, `TypedPrice` per
  user, mig 0022). Two calls still read every user's trades: `options.expire_due` (U03-2) and
  `options.deliverable` (`:202`), whose value weights for an adjusted contract's parts may come
  from another user's trade.
- **C45**: the alert holds (`alerts.py:495-523`); the marking doesn't (U03-11).
- **C46, C47, A26**: hold (`lots.adds_basis`; `adjust.adjusted_strike`; `expire_due`'s date
  check, with U03-2 on what passes it). **A27**: holds (`refresh.py:319-323`, `BENCHMARKS`).
- **N3, N6**: later work (L5, L9); not raised.

## Checked and sound

- `ledger/lots.py`: FIFO, LIFO, HIFO and average orders; partial lots and basis shares rounded to
  the cent with the last taking the remainder; short option lots closed oldest first with
  `written` short-term; expiry of long and short lots; assignment and exercise premium by leg
  cash (`_spread_premium`); a short stock lot from an assignment with no shares and its cover;
  return of capital over every lot with the excess as gain; spin-off basis split; merger boot by
  IRC §356 (`min(boot, gain)`, new basis old − boot + gain); all-cash merger as a sale; the IRA
  and Roth exception; `long_term` by the anniversary with 29 February.
- `washes.py`: 30 days either side, nearest first, each replacement counted once, a lot never its
  own replacement, spouse only on the sale date, losses only in taxable accounts, proportional
  disallowance, tacked holding period.
- `options/__init__.py`: OCC ticker, cash of a trade with fees, settle's legs and deliverable
  cash, ITM test, `per_share` for adjusted contracts; `adjust.py`: whole-number split only,
  strike to the thousandth half up, pairs undone together.
- `options/strategies.py`: payoff-based max profit, max loss and breakevens; shapes; calendar
  and diagonal; capital at risk now and at open; proposals (same day, covered call ≥ 100 shares,
  rolls, declined keys).
- `prices/`: source registration, key needed before enabling, key as a secret behind the
  password again, egress list from enabled sources, CBOE's chain read once per underlying, index
  roots, mid rounded half-even, the close only after 4:15 PM, Coinbase's open candle left out,
  JSON with `parse_float=Decimal`, one failing source falling back per instrument, `store`
  never overwriting a typed price.
- `valuation.py`: precedence close → owner's typed (later wins) → owner's statement → owner's
  last trade; options never valued from a trade; typed prices stale after 90 days.
- `figures.py` / `performance.py`: TWR chaining, IRR by bisection, the benchmark given the same
  money, deleted accounts counted to their deletion.
- `ui/portfolios.py`: viewers see only accounts shared with them (S5.1.1); only the owner
  chooses the accounts; *All my accounts* is own plus ticked shared.
- `ui/rules.py`, `store/repos/rules.py`, `ledger/rules.py`: per-user rules, order and first
  match, amount without sign, direction, account limited to writable ones, rename kept beside the
  bank's text, category only where none and never on a split's category, Activity counts only.
- `reimbursements.py`, `ui/reimbursements.py`: marks on a transaction or a split, offers within
  90 days, no more paired than awaited or than is left of the deposit, write needed on both.
- `taxes/closed.py` (unit 04's, read for S2.8): filed or accepted closes a year, an amended
  return in progress opens it, an edit made anyway recorded per closing book.

## Read lightly or not read

- Migrations 0007, 0008, 0017, 0018, 0019, 0030: read for what they create and convert, not
  line by line (0001 is unit 06's by search).
- `prices/stub.py` (dev only), `ui/components/txtable.js`, `ui/screens/transactions.js`,
  `ui/screens/portfolios.js`, `ui/components/strategies.js` and `rules.js`: read for what they
  send and show, not every line of layout.
- Tests: read by name and for the cases U03-1, U03-3, U03-6 lean on; not each assertion.
- Guides: all of the unit's read except `account-holdings`, `account-transactions`,
  `transactions`, `portfolios`, `portfolio-projections`, `prices-coinbase`, `prices-tiingo`,
  `dialog-transaction`, `dialog-rules`, `dialog-strategy`, `dialog-portfolio`, `dialog-group`,
  `dialog-assign`, `dialog-adjustment`, `dialog-option-adjust`, `dialog-option-trade` (skimmed
  by title only).
- Not judged: the importers' option and corporate-action rows (S3.2.1–2, S3.10.3, unit 01), the
  tax book's wash-sale issues (S3.8.5's listing, unit 04), the Share dialog's *Share these
  accounts too* (S5.1.2, unit 07), the Dashboard's net worth (S5.3, unit 09).

## Work pad: severity, confirmations, status

| Id | Kind | Sev | Req | Conf | Status | One line |
|---|---|---|---|---|---|---|
| U03-1 | differs | Med | S4.4 | 0 | open | The underlying of an option held on its own is never priced |
| U03-2 | differs | Med | S3.6 | 0 | open | An automatic expiry is decided by any user's trade on the expiry day, not a close |
| U03-3 | security | Med | withheld | 0 | open | Withheld |
| U03-4 | wrong figure | Med | S2.3 | 0 | open | A pick of a lot split by a wash sale takes the rest from another lot, FIFO |
| U03-5 | differs | Med | S2.8.2 | 0 | open | A buy in another account that washes a closed year's loss changes that year unasked |
| U03-6 | wrong figure | Med | S5.2.1 | 0 | open | Shares moved in or out count as growth in returns and contributions |
| U03-7 | bug | Med | S2.9 | 0 | open | Any edit of a split transaction loses its paybacks |
| U03-8 | differs | Low | S3.8.5.1 | 0 | open | A short sale's loss is washed and adjusted, not flagged |
| U03-9 | wrong figure | Med | S5.2.3 | 0 | open | The Holdings tab counts a loan's payments as cash and leaves out items |
| U03-10 | bug | Low | S2.4.1 | 0 | open | A corporate action is checked and sized by today's holding, not its date's |
| U03-11 | differs | Low | S4.7 | 0 | open | A statement value is never marked stale; Positions shows no price date |
| U03-12 | differs | Low | S5.2.2 | 0 | open | A period's return is shown over less than the period |
| U03-13 | wrong figure | Low | S3.9 | 0 | open | Gains counts a mixed-term position's unrealized gain as short-term |
| U03-14 | differs | Low | S2.8.2 | 0 | open | An option's end can't be recorded anyway in a closed year |
| U03-15 | differs | Low | S2.1 | 0 | open | Options are shown in their stored form, not S2.1's |
| U03-16 | wrong figure | Med | S2.2 | 0 | open | Shares transferred in start their holding period on arrival |
| U03-17 | bug | Low | S4.7 | 0 | open | The header calls prices stale for ever when anything is statement- or intrinsic-valued |
| U03-18 | not built | Low | S4.2.2 | 0 | open | No symbol is checked with a source before it is used |

Counts: 18 claims. By severity: High 0, Med 9 (U03-1, U03-2, U03-3, U03-4, U03-5, U03-6,
U03-7, U03-9, U03-16), Low 9. By kind: differs 8, wrong figure 5, bug 3, security 1 (withheld),
not built 1. None needs the user; D1-1 and D1-12 stay with the walk-through. Scratch tests in
the job's `tmp/u03/t/test_u03.py`, runs in `tmp/u03/run*.txt`.

## Found while checking

(Unverified: noticed by the checker, in no claim; the sweep checks each, §8.)

### U03-F1: two picks of one lot can take more than the lot holds

- **Kind:** bug. **Severity:** Low. **Req:** S2.3 (specific identification, "chosen per sale").
- **Code:** `web/server/src/moolakata/ledger/lots.py:636-643` (`_consume`), the picks loop plans
  each pick against the lot's whole quantity, where the method's loop after it subtracts what the
  plan already holds (`room = lot.quantity - sum(...)`):
  ```text
  for p in picks:
      lot = by_id.get(p.lotId)
      take = min(p.quantity, lot.quantity, left) if lot else ZERO
      if take > 0:
          plan.append((lot, take))
  ```
  and `ui/transactions.py:645-657` accepts any list of `PickIn`: each lot is checked to be in
  the account and of the instrument, never that a lot appears once or that the picks add up to
  the sale.
- **What goes wrong:** a request (not the dialog) that sends the same lot twice, 6 and 6 of a
  lot of 10, plans 12 shares from it; `_take` then runs twice and leaves the lot at -2 shares
  (a short lot out of nothing), with its basis and a gain worked out on shares that were never
  held. Reading alone.
- **Remedy:** subtract the plan's share of the lot inside the picks loop, as the method's loop
  does, and refuse duplicate lot ids in `picks` at the route.

### U03-F2: an adjusted contract's deliverable is weighted by any user's last trade

- **Kind:** differs. **Severity:** Low. **Req:** S4.10 ("a holding is valued from the viewer's
  own trades in it, never from another user's"), S3.10.5.
- **Code:** `web/server/src/moolakata/options/__init__.py:189-206` (`deliverable`, the call at `:202`), no owner is
  passed, so `valuation.prices` falls back to every account's statements and every user's trades:
  ```text
  found = valuation.prices(s, [i.id for i, _ in rows], day)
  if all(i.id in found for i, _ in rows):
      values = [found[i.id].price * q for i, q in rows]
  ```
  `settle` (`:124`) takes its parts' shares of the basis and the cash
  from these weights. U03-2 raises the same call in `expire_due`; this one is the P7 remainder
  that "Earlier findings re-checked" names, and no claim holds it.
- **What goes wrong:** where an adjusted contract's parts (a spin-off's two stocks) have no
  stored close for the day, another user's trade in either stock sets the weights that split the
  settlement's basis between the parts in this user's account. The figures differ by the gap
  between that trade's price and the owner's own.
- **Remedy:** pass the account's owner (`valuation.prices(..., day, owner)`), as `per_share`
  can, and fall back to the shares when the owner has no price.
