# Code review 3, unit 01: accounts-imports

**Session:** Oct 24, 07:43 PM to 07:58 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S1.1 (account types), S1.2 (what every account has), S1.3 (keeping current:
  manual, file import, statement import S1.3.3.1–8, bitcoin watch only as the type, the
  Connector only as an upload), S1.4 (retirement accounts), S1.5 (crypto exchanges), S1.7
  (transfers; S1.7.1 bitcoin pairs read only where this unit's code touches them), S1.11
  (reconciliation, S1.11.1–7), with R1.9, R1.26, R3.2 and R3.3 that they rely on. S1.6, S1.8–S1.10
  are unit 02's.
- **Code (8,858 lines, 57 files):** `src/importers/` (brokerage, csvfile, ofx, parsed,
  statements), `src/ledger/` (balances, categories, expected, holdingcheck, reconcile,
  transfers, types), `src/store/entities/accounts.py`, `src/store/repos/ledger.py`,
  `src/store/tables/accounts.py`, `src/ui/accounts.py`, `src/ui/imports.py`, migrations 0004,
  0005, 0029, `ui/account-types/*.js`, `ui/screens/account.js`, `accounts.js`, `import.js`,
  `new-account.js`.
- **Tests (2,025 lines):** `test_accounts.py`, `test_brokerage.py`, `test_created.py`,
  `test_expected.py`, `test_importers.py`, `test_ledger.py`, `test_statements.py`.
- **Guides:** `ui/guides/account-*.md`, `accounts.md`, `import*.md`, `new-account*.md` (not
  those for items, loans, 529, wallets, payoff).
- **Cites no section:** none listed for this unit (`store/entities/accounts.py` shows no cite
  but mirrors the tables).

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 930 lines (10%), 4 new files. Most files only renamed. Where the content is:

- `store/repos/ledger.py` (+219/−53): `apply_import` rewritten: FITID repeats kept as `id#n`,
  FITID rows fall back to date/amount/payee, cents comparison (B19); option ends from files
  settled through `options.settle`, the broker's stock leg matched (`_stock_legs`, `_settle`)
  (B5); positions become HoldingChecks unless kept by snapshots (B9); crypto accounts' `other`
  class becomes `crypto`; `lotMethod` recorded on imported disposals (B7); rules applied on
  import (N1, S2.7.3).
- `importers/parsed.py` (new, 246; replaces a 64-line file): OCC parsing, rows, cover.
- `importers/csvfile.py` (+33): OCC option rows, newest-first files reversed (B18).
- `importers/ofx.py` (+53): option trades and ends (B5), reinvest's dividendType (B3).
- `importers/statements.py` (+14): CR/DR not turned twice (B20); `learn` skips present lines
  (C44).
- `ledger/reconcile.py`: duplicates by FITID base (B19); `needs_anchor` by overdue (B43).
- `ledger/types.py`: `cash`, `payment-app`; `reconcilable` widened (B33).
- `ledger/expected.py`: `cash` never.
- `ledger/categories.py`: savings kind, cash, loan payment parts (S7, unit 05's in substance).
- `store/tables/accounts.py`, `entities/accounts.py`: `withdrawalsAMonth`, Rule,
  Reimbursement, new txn kinds and columns (the latter unit 03/05's).
- `ui/accounts.py`: `withdrawalsAMonth` field; wash sales recomputed on a lot-method change
  (B7); `needs_anchor` by import; capital-at-risk unlimited.
- `ui/imports.py`: results as exact numbers (C31), `parsing.*` (the sandboxed reader, K4),
  statement time limit and pages (B20), present lines teach nothing (C44).
- `mig/0029` (new): cash and payment-app types. `ui/account-types/cash.js`, `payment-app.js`
  (new), `index.js`, `screens/account.js` (+39), `screens/import.js`.
- Tests: `test_created.py` (new, 323), `test_accounts.py` +134, `test_importers.py` +67.

### 3. Earlier reviews' findings in this area

Review 1: none in this unit's sections. Review 2 (§12.2 marks all done): B3 (reinvest counted
twice), B5 (options from files), B7 (lot method on imported sales; rerun of wash sales has no
test, §12.5.8), B9 (OFX positions a check), B18 (newest-first CSV), B19 (re-import
idempotency), B20 (CR/DR flipped twice; OCR page cap; done differently), B33 (Reconcile tab
for retirement, plan, exchange; loans on Overview, §12.5.1), B43 (anchor asked when overdue),
C31 (import results as numbers), C43, C44 (present lines teach nothing), A22 (transfers rule),
A23 (OFX one account; value check ½% or $1); the Tests row (B3 had no test). Each re-checked
below under "Earlier findings re-checked".

### 4. Phase 1 claims and decisions on these sections

- D1-5 / DC-4 (S1.5: exchange APIs "come later" linked to out-of-scope): needs the user,
  documents only; the code builds no exchange API (matches either reading).
- D1-8 (S1.4 cites S8.6 for limits in Settings; they are S16.11): documents only.
- D1-14 (S4.3 stale-at-90-days vs S1.11.7 overdue): unit 03's S4.3; noted where `expected.py`
  is read.
- DC-13 / D2-16 (which size limit a connector or statement upload meets): unit 09/12 mostly;
  checked where `ui/imports.py` reads its limit.
- D1-25 (who sees a statement kept on an account): unit 06; noted only.
- No decision recorded yet; none is a §6 gate; "unit 01 has nothing waiting".

### 5. Untraced candidates and uncited first-level items

- No untraced file named by the map.
- Uncited first-level items: **S1.4** (retirement accounts: contribution year, match and
  vesting, birth year, limits) and **S1.5** (crypto exchanges): judged below.

## Claims

(Work-pad ids U01-n; kinds and format per §7. Severity, confirmations (0) and status (open)
are in the table at the end.)

### U01-1: a transaction deleted from an imported account comes back with the next import

- **Kind:** bug. **Req:** S1.3.2 ("a re-imported file adds only what is new"), S1.11.4 ("remove
  a duplicate"), S1.11.5, S18 (the Connector's daily downloads).
- **Code:** `web/server/src/moolakata/store/repos/ledger.py:299-307`:
  ```python
  existing = s.scalars(
      select(Transaction).where(
          Transaction.accountId == account.id, Transaction.deleted == false()
      )
  ).all()
  ...
  by_fit = {x.fitId: x for x in existing if x.fitId}
  ```
  and `:327-349`: a row whose FITID (or date, amount and payee) matches nothing live is added.
- **What goes wrong:** the match is made against live rows only, so a row the owner deleted is
  "new" again in every later file that carries it. Case: `bank.ofx` imported (5 added); the owner
  deletes one of them (say a true duplicate, `20260903-1#2`, as S1.11.4 tells them to); the same
  file, or the next download that overlaps it, adds it back (`added: 1, matched: 4`). With the
  Connector's OFX driver fetching 45 days every day (S18.9), a deleted row returns daily for six
  weeks, and the mismatch it caused returns with it; a FITID a bank repeats in every file can't
  be got rid of at all.
- **Run:** yes, a scratch test against the test server (`u01/t/test_u01_scratch.py::
  test_deleted_row_returns_on_reimport`): upload `fixtures/bank.ofx`, `DELETE` one
  transaction, upload again: `added == 1`.
- **Remedy:** match a file's rows against deleted rows too (by FITID, and by date, amount and
  payee for rows without one), counting a match with a deleted row as matched, not added; keep
  the deleted row's id for that.
- **Alternatives:** keep a per-account list of FITIDs the owner deleted (a "skip" list), shown
  in Reconcile with an undo; or ask on delete of an imported row whether the file should bring it
  back.

### U01-2: a broker's trade-history CSV makes every security class `other`, which no price source fetches

- **Kind:** wrong figure. **Req:** S1.3.2 ("brokers' and exchanges' trade-history CSVs"), S2.1
  (the instrument classes), S4.3 (the sources by class).
- **Code:** `web/server/src/moolakata/importers/csvfile.py:280-285`:
  ```python
  out.securities[symbol] = Security(
      key=symbol,
      symbol=symbol,
      name=None,
      instrumentClass="option" if option else "other",
  )
  ```
  `store/repos/ledger.py:296-297` keeps `other` (only a crypto account turns it to `crypto`);
  `prices/tiingo.py:17` `classes = frozenset({"equity", "etf", "mutual-fund"})`,
  `prices/cboe.py:64` `{"option", "equity", "etf"}`; only `manual` (and dev mode's `stub`)
  serve `other`. Entering the same trade by hand makes it `equity` (`ui/transactions.py:590`).
- **What goes wrong:** a brokerage kept from its broker's CSV history (Schwab, Fidelity and
  Vanguard all offer one) gets every stock, ETF and fund it trades as class `other`, so the
  daily refresh never prices them: the holdings show no value (or only a typed price), and the
  account's value, net worth, portfolios and projections leave them out. Instruments are kept
  once per server by symbol, so the first CSV to name a symbol also fixes it as `other` for every
  later account that imports it by symbol. Dev mode's stub source prices `other`, so the dev
  server hides it.
- **Run:** yes, scratch test `test_csv_trade_history_instrument_class`: a one-row trade CSV into
  a brokerage makes the instrument class `other`, served by `['manual', 'stub']` only.
- **Remedy:** a CSV security in an investing account is `equity` (as a typed trade is), or
  `mutual-fund` where its name says fund; let a later file or the owner correct the class; and
  the price refresh treats `other` with a ticker-shaped symbol as `equity` for the sources that
  take it.
- **Alternatives:** ask the class once per new symbol in the mapping step.

### U01-3: one cash dividend stops an account being kept by snapshots, and its holdings vanish

- **Kind:** differs. **Req:** S1.3.2 ("For an account kept by snapshots (R3.2), with no trades
  of its own, they are its holdings"), S1.3.3.8.1 ("An account kept by snapshots is one kept from
  statements only, with no trades of its own"), R3.2.
- **Code:** `web/server/src/moolakata/ledger/lots.py:144-146`:
  ```python
  def kept_by_snapshots(transactions: list, lots: list) -> bool:
      """No trades of its own: no transaction in an instrument, and no lot typed on its own."""
      return not any(t.instrumentId for t in transactions) and all(x.transactionId for x in lots)
  ```
  used by `store/repos/ledger.py:399-406` (positions become a check instead) and by
  `lots.replay` (`:163-166`, snapshots dropped).
- **What goes wrong:** any transaction naming an instrument counts as a trade: a cash dividend,
  interest on a bond, a capital-gain distribution. A buy-and-hold brokerage or a 401(k) whose
  OFX carries positions and a dividend (most quarterly files do) is then not kept by snapshots:
  its positions are only a holdings check, and its holdings are the lots its trades made, none.
  Case: positions VTI 100 on Sep 30 and a cash dividend on VTI Sep 15: `replay(...).quantity`
  is 100 without the dividend and 0 with it; the account's value drops to its cash, and Reconcile
  shows a difference of 100. Lots can't come from a dividend, so nothing in the files ever fixes
  it; the owner must type every lot.
- **Run:** yes, `u01/snap.py` (lots.replay with and without the dividend: 100, then 0).
- **Remedy:** a trade is a transaction that makes or takes away a lot (buy, sell, reinvest,
  transfer in or out, an option trade, a corporate action); income and fees on an instrument
  don't end keeping by snapshots.
- **Alternatives:** S1.3.2 says income counts too, and the account's first import offers to
  turn its first positions into opening lots (basis missing) so the check has something to hold.

### U01-4: correcting a statement line's description teaches MoolaKata to skip every line that starts like it

- **Kind:** bug. **Req:** S1.3.3.3 ("each line can be corrected"), S1.3.3.4 ("the first words of
  lines they left out, which are skipped next time").
- **Code:** `web/server/src/moolakata/importers/statements.py:384-394`:
  ```python
  kept_keys = {(r.date, r.description) for r in kept}
  ...
  for r in st.rows:
      if (r.date, r.amount) in present:
          continue
      if (r.date, r.description) not in kept_keys and r.description:
          words = " ".join(r.description.lower().split()[:3])
          if words and words not in out["skip"]:
              out["skip"].append(words)
  ```
  `kept` is what the dialog sent back (`ui/imports.py:1153-1163`, from `StatementRowIn`, with
  the description as the person edited it, `web/ui/screens/import.js:487-489, 391-392`);
  `st.rows` is the parse as read. `statements.parse:250-251` drops a skipped line before it is
  shown.
- **What goes wrong:** a kept line whose description was corrected no longer matches its
  parsed self by (date, description), so it is taken for a line left out, and its first three
  words become a skip. Case (run): a UMB-like statement with `09/03 DEBIT CARD PURCHASE AMAZN
  MKTP 60.00` and `09/04 DEBIT CARD PURCHASE KROGER 123 40.00`; the person keeps both and renames
  the first to *Amazon*; learned: `{'skip': ['debit card purchase']}`; the next statement from
  that institution parses to no rows at all, so it is refused as "No transactions were found"
  and offered to be kept unread. When only some lines start that way they vanish silently and
  the statement no longer adds up. Nothing in the app shows or resets a learned layout
  (`StatementLayout` is written only here and in the copy mapping), so it lasts for good, for
  every account of that owner at that institution.
- **Run:** yes, `u01/learn.py` (statements.parse, learn, parse again).
- **Remedy:** learn from what the person decided, not from a re-keyed match: the dialog sends
  each row's index (or its parsed date and description) with the edited one, and only rows sent
  with `include: false` teach a skip; a skip is learned only from a description shared by no
  kept line.
- **Alternatives:** show skipped lines left out (*skipped, as learned*) instead of dropping
  them, so a wrong skip can be ticked back and unlearned; and a way to forget an institution's
  layout (Settings › Imports or the dialog).

### U01-5: a brokerage statement read beside the account's files teaches its cash lines as skips

- **Kind:** bug (C44 of review 2, still open for brokerage statements). **Req:** S1.3.3.4 ("A
  line left out because it was already in the account teaches nothing"), S1.3.3.8 ("learned per
  institution as for banks"), S1.3.3.8.3 ("every line does [start left out] when the account is
  kept from files").
- **Code:** `web/server/src/moolakata/ui/imports.py:793-802`:
  ```python
  have = {(a.date, a.amount) for a in b.activity}
  left = [
      x.description
      for x in body.rows
      if not x.include and x.kind in CASH_KINDS and (x.date, x.amount) in have
  ]
  ...
  learned = brokerage.learn(json.loads(row.layout) if row else None, b, left)
  ```
  `have` is the statement's own lines, not what the account held. `web/ui/screens/import.js:72`
  starts every line unticked when `byFile`, and every present line otherwise.
- **What goes wrong:** every cash line left out, those already in the account and all of a
  file-kept account's, has its first three words learned as a skip for the owner's statements
  from that institution (`brokerage.parse:310` drops them unseen). Case: Schwab brokerage kept
  from OFX; its September statement is read to keep it, every line unticked as S1.3.3.8.3 says;
  *Qualified Dividend VTI*, *Bank Interest …* and *Funds Received …* become skips; the owner's
  Schwab IRA kept from statements only then loses those lines from every later statement, and
  its dividends, interest and deposits are never entered (flagged against the summary, at best).
- **Run:** no; reading alone (the call chain is the four lines above; `brokerage.learn` adds
  every description it is given).
- **Remedy:** as `_apply` does for bank statements: take `_present(s, account.id)` before
  `apply_import` and leave out of `left` every row present there, and teach nothing when the
  account is kept from files.

### U01-6: S1.4's vesting for a 401(k) is built nowhere

- **Kind:** not built. **Req:** S1.4 ("employer match and vesting for a 401(k)").
- **Code:** none. `store/tables/accounts.py:288-291` has `contributionSource` (`employee`,
  `employer`, `rollover`), which carries the match; `grep -ri vest` finds no vesting field,
  table, screen or guide, and no gap, question or L item names it.
- **What goes wrong:** an unvested employer match counts as the owner's money in the account's
  value, net worth and retirement projections (S6), with no way to say part of it would be lost on
  leaving the job. S1.4 names vesting and never says what it holds (a schedule, a vested
  percentage, a date), so it is also a candidate gap.
- **Run:** no; search and reading.
- **Remedy:** record it as a gap (what vesting holds and where it shows) or as later work with an
  L id; until then S1.4 says the match only.
- **Alternatives:** a vested percentage typed on the account's settings, shown beside the value.

### U01-7: an OFX file's end date and ledger balance move to the next day in UTC; positions are dated by their price

- **Kind:** wrong figure (dates). **Req:** S1.11.1 (coverage), S1.11.2 (an OFX file's ledger
  balance, compared on its day), S1.3.2 (a broker's file's positions are a check "on that day"),
  S14.9.3 (the reason `_raw_dates` exists).
- **Code:** `web/server/src/moolakata/importers/ofx.py:117`, `:130`, `:177`, `:186`:
  ```python
  out.coveredFrom, out.coveredTo = _day(tl.dtstart), _day(tl.dtend)
  ...
  out.balances.append((_day(st.ledgerbal.dtasof), st.ledgerbal.balamt))
  ...
  asOf=_day(pos.dtpriceasof) or _day(st.dtasof),
  ```
  `_day` takes ofxtools' UTC datetime's date; only the rows' dates are read raw (`_raw_dates`,
  `:59-71`).
- **What goes wrong:** (1) `DTEND` and `DTASOF` of `20260930200000[-5:EST]` become Oct 1 while
  the Sep 30 row stays Sep 30 (run): the anchor is compared with the balance at the end of Oct 1,
  so Oct 1 rows from the next file make it a mismatch, and the coverage and the statement
  expected end a day late (a monthly account's next is named *the November statement*). (2) An
  `INVPOS`'s `DTPRICEASOF` is the date of its price, often the previous close, while its
  `UNITS` are as of the statement's `DTASOF`: a Sep 30 buy in the same file shows as a holdings
  difference against Sep 29 (run with `DTPRICEASOF` moved to Sep 29: the check is dated Sep 29).
- **Run:** yes, `u01/ofxdates.py` (the fixtures with an evening EST time and an earlier price
  date).
- **Remedy:** read `DTSTART`, `DTEND`, `LEDGERBAL`'s and `INVSTMTRS`'s `DTASOF` as the
  institution wrote them, as the rows are; date positions by the statement's `DTASOF`.

### U01-8: a newest-first CSV that covers a single day keeps its oldest row's balance as the day's

- **Kind:** bug. **Req:** S1.11.2 ("a newest-first file, told by its dates, is read from the
  bottom up").
- **Code:** `web/server/src/moolakata/importers/csvfile.py:303-304`:
  ```python
  if len(out.rows) > 1 and out.rows[0].date > out.rows[-1].date:
      out.rows.reverse()
  ```
  and `ledger/balances.py:25-27` (a day's balance is its last row's, in creation order).
- **What goes wrong:** a file whose rows all fall on one day (a day's download) can't be told by
  its dates, so a newest-first one is kept in file order and the day's anchor is its oldest
  row's running balance: a mismatch on a balance that is right, with the first parting named on
  a row that is fine.
- **Run:** no; reading alone.
- **Remedy:** when the dates tie, tell the order by the running balance (each row's balance less
  its amount is the next row's balance in a newest-first file).

### U01-9: retirement, plan, 529, DAF and exchange accounts still have no Reconcile tab in the browser (B33)

- **Kind:** differs (review 2's B33, marked done, half holds). **Req:** S1.11 ("the retirement,
  plan, 529, HSA, DAF and exchange accounts whose statements S1.11.7 expects, each on its
  *Reconcile* tab"), S1.3.3.8.1–2 (a plan statement's value and holdings checked "on the
  *Reconcile* tab").
- **Code:** the server widened `ledger/types.py:114-125` (`reconcilable` is true for every type
  but loans, `crypto-wallet`, `cash` and physical assets) and sends it as
  `AccountRow.reconcilable`; the account page takes the tab from the browser's own type modules
  instead, `web/ui/screens/account.js:53`:
  ```js
  ...(type?.reconcilable ? [['reconcile', 'Reconcile']] : []),
  ```
  where `web/ui/account-types/ira.js`, `roth-ira.js`, `401k.js`, `403b.js`, `457b.js`,
  `hsa.js`, `529.js`, `daf.js` and `crypto-exchange.js` all say `reconcilable: false`.
- **What goes wrong:** a 401(k) whose Empower statement was read has its value check and its
  holdings check written (`ui/imports.py:742-789`) and nowhere to see them; its *balance
  needed* pill (`screens/accounts.js:130`) and the statement-overdue and mismatch alerts
  (`alerts.py:449`, which uses the server's rule) link to `/reconcile`, which falls back to the
  Overview (`account.js:57`). An IRA or exchange with a cash mismatch is marked in Accounts and
  alerted after 7 days with no tab to resolve it on.
- **Run:** no; reading (the flags and the one line that reads them).
- **Remedy:** take the tab from `a.reconcilable` as the server sends it (and drop the flag from
  the type modules), or set the nine modules to `true`; a test that the two agree for every
  type.

### U01-10: no account can be set to statement import, so a plan statement's positions are never its holdings

- **Kind:** differs. **Req:** S1.3 ("one or more of": manual, file import, statement import, …),
  S1.3.3.8.1–2 (the ending value "a balance snapshot for an account kept by snapshots"; the
  positions "for an account kept by snapshots … its holdings on that date"), R3.2; the
  mockup's Method choices (`docs/mockups/MoolaKata-mock.html:1171, 1816`: *OFX / QFX import*,
  *Statement import (PDF or photo)*, *CSV import*, *Manual*).
- **Code:** `web/ui/screens/new-account.js:24-27`:
  ```js
  export const KEPT_BY = /** @type {[string, string][]} */ ([
    ['file', 'File import (OFX, QFX or CSV)'],
    ['manual', 'Manual'],
  ]);
  ```
  used by the New account form (`:149-153`, sent as `keptBy: [f.keptBy]`) and the account's
  Settings (`screens/account.js:824, 838, 952-954, 972-975`); against
  `web/server/src/moolakata/ui/imports.py:512-526`:
  ```python
  def snapshot_kept(s, account: Account) -> bool:
      ...
      if json.loads(account.keptBy or "[]") != ["statement"]:
          return False
  ```
  which decides whether `save_brokerage` (`:754-789`) writes the statement's positions as
  `Holding` rows.
- **What goes wrong:** the server accepts `statement` (`ui/accounts.py:37`) but the browser
  never offers it, so `snapshot_kept` is false for every account made in the app. A 401(k) kept
  from its quarterly Empower PDFs, as S1.3.3.8 describes, gets a value anchor and a holdings
  check from each statement and never a holding: its Holdings tab stays empty and its value,
  net worth and retirement projection count it as its cash, zero. The dialog tells the person
  "The ending value becomes a balance anchor" (`screens/import.js:621`), never the snapshot path.
  Saving Settings also cuts a `keptBy` of several methods to its first (`account.js:824, 838`).
- **Run:** no; reading (the two lists and the one test the server makes).
- **Remedy:** offer *Statement import (PDF or photo)* in both places, as the mockup does (and the
  methods as several choices, as S1.3 says, or S1.3 says one); decide kept by snapshots by the
  ledger (no trades of its own, U01-3) rather than by `keptBy` alone, so one rule serves
  `save_brokerage` and `lots.replay`.
- **Alternatives:** make `snapshot_kept` true for an account with no trades of its own whatever
  `keptBy` says.

### U01-11: a trade history's columns can't be named in the mapping dialog, so an exchange's CSV imports as cash

- **Kind:** differs. **Req:** S1.5 ("kept current from their CSV exports … one import mapping
  per exchange"), S1.3.2 ("brokers' and exchanges' trade-history CSVs", "a saved column mapping
  per institution").
- **Code:** `web/server/src/moolakata/importers/csvfile.py:151-153` drops every trade column
  unless both a symbol and a quantity column were guessed:
  ```python
  if not (mapping["symbol"] and mapping["quantity"]):
      for f in ("action", "symbol", "quantity", "price", "fees"):
          mapping[f] = None
  ```
  with the quantity guesses `["quantity", "shares", "units", "qty"]` (`:65`); and the dialog
  offers only the bank columns, `web/ui/screens/import.js:29-38`:
  ```js
  const COLUMNS = /** @type {[string, string, string][]} */ ([
    ['date', 'Date column', ...], ['payee', ...], ['amount', ...], ['debit', ...],
    ['credit', ...], ['balance', ...], ['memo', ...], ['id', ...],
  ]);
  ```
  so `action`, `symbol`, `quantity`, `price` and `fees` can't be chosen by the person.
- **What goes wrong:** a file whose quantity column is named otherwise (Coinbase's history
  names it *Quantity Transacted*, as its own `GUESSES` entries for *Spot Price at Transaction*
  and *Fees and/or Spread* show the reader was written for) is proposed as a bank file, and the
  person has no way to say which column is the asset or the quantity: every buy, sell and send
  becomes a `deposit` or `withdrawal` by the amount's sign, no instrument, no lot. And where a
  trade history writes its totals unsigned (a buy as a positive *Subtotal*), even a mapped file
  makes a buy's lot with a negative basis (`store/repos/ledger.py:514-524`, `costBasis=
  -row.amount`), since nothing ties a trade's sign to its action. (The Coinbase column names
  are from its export as commonly documented, not from a file in the repository.)
- **Run:** no; reading (the drop and the dialog's list).
- **Remedy:** the mapping dialog offers the trade columns (action, symbol or asset, quantity,
  price, fees) whenever the account is an investing or crypto one; add *quantity transacted*
  (and *asset*) to the guesses; give a buy's or a sell's cash the sign its action says.
- **Alternatives:** ship mappings for the exchanges S1.5 names, as the statement layouts ship.

### U01-12: uploads waiting for a mapping or a check are held in memory for 30 minutes, uncounted

- **Kind:** bug (a resource held). **Req:** S13.7.6 ("at most 100 MB of uploads in flight per
  user … an upload is held in memory"), S13.7.5.3 ("uploads: 60 files an hour per user"), S16.8
  (imports up to 200 MB).
- **Code:** `web/server/src/moolakata/ui/imports.py:46, 120-129`:
  ```python
  HELD_MINUTES = 30
  ...
  _held[key] = Held(
      data, account_id, user_id, name, now + dt.timedelta(minutes=HELD_MINUTES), **extra
  )
  ```
  called for every CSV without a saved mapping (`:165`), every statement to check (`:408, 423,
  468, 534, 581`) and every statement to keep (`:1081`); entries go only when used or when a
  later `_hold` sweeps the expired ones.
- **What goes wrong:** the in-flight limit (`middleware.py:263`) counts a body only while it is
  received; once the job holds it, it counts against nothing. One user's 60 uploads an hour,
  never confirmed, keep about 30 files in memory at a time: 750 MB at the default 25 MB, 6 GB at
  S16.8's 200 MB, on the same process that serves every household member (with the read lines and
  parse of each statement besides).
- **Run:** no; reading.
- **Remedy:** count held uploads against the user's 100 MB, refusing a new one past it (or
  dropping their oldest held one), and cap held uploads per user.

### U01-13: no test reruns wash sales when the lot method changes (review 2, §12.5.8, still open)

- **Kind:** test gap. **Req:** S2.3 ("changing it applies to later sales"), B7 of review 2.
- **Code:** `web/server/src/moolakata/ui/accounts.py:578-582`:
  ```python
  if "lotMethod" in changed:
      # Sales keep the method recorded on them; the wash sales are worked out again (S2.3).
      from .. import washes

      washes.recompute(s, a.ownerId)
  ```
  `tests/test_accounts.py:401-428` checks the method recorded on each sale, and no test changes
  the method with a wash sale in the account (`grep lotMethod tests/` finds three PATCHes, none
  near a wash sale).
- **What goes wrong:** nothing yet; the rerun can be removed or broken without a test failing,
  which review 2 recorded as left open.
- **Run:** no; search.
- **Remedy:** a test: a loss sale and a replacement within 30 days under FIFO, the method changed
  to LIFO before a later sale that picks the replacement lot, and the wash sale's disallowed
  loss and replacement basis checked after the change.

### U01-14: the reconcile screen and guides say less, or other, than S1.11 and S1.3.3.8

- **Kind:** differs. **Req:** S1.11.3 ("it names the first row where the balances part"),
  S1.11.5 ("two identical rows on one day, or two rows a file gave the same id"), S1.3.3.8.1
  ("within half a percent or $1, whichever is more"), S1.11.7.1 (the defaults), S1.3 (the
  methods).
- **Code and text:**
  - `web/ui/screens/account.js:573-578`: *"The file's running balance parts from MoolaKata's at
    one row; check the transactions around it."*: `firstParting` (a transaction id) is sent and
    never shown or linked.
  - `account.js:536`: *"Possible duplicate: N identical rows on one day"*, and
    `guides/account-reconcile.md` "Possible duplicate": *"Two identical rows on one day"*: a
    repeated FITID's rows (B19) need be neither.
  - `account.js:1089-1090` and `account-reconcile.md` "Statement values": *"within half a percent
    counts as a match"*, leaving out the $1.
  - `guides/account-settings.md` "Statements expected": the defaults leave out exchanges
    (monthly), DAFs (quarterly), `cash`, wallets and physical assets (none); "Method": *"from
    files you import (OFX, QFX or CSV), or by hand"* (no statements, see U01-10).
  - `guides/account-credit-card.md`: *"Card exports often show purchases as positive: the import
    flips them"*: only when the person sets *Spending is positive* in the mapping
    (`import.js:187-191`).
- **What goes wrong:** the person can't find the row S1.11.3 promises to name, and reads rules
  narrower or wider than the code applies.
- **Run:** no; reading.
- **Remedy:** link the first parting row (to the transaction, or highlight it in a list of the
  window's rows); say "or two rows the file gave the same id"; add "or $1, whichever is more";
  give the full defaults; say the import flips them when the mapping says so.

### U01-15: an exchange's coin and a listed stock with the same ticker become one instrument

- **Kind:** wrong figure. **Req:** S1.5, S2.1 ("Instruments are kept once per server"), S4.3
  (prices by class).
- **Code:** `web/server/src/moolakata/store/repos/ledger.py:157-168` (found by symbol whatever its
  class, and given the file's CUSIP when it has none) and `:296-297`; `store/tables/accounts.py:170`
  `unique_live(Instrument, "symbol")`.
- **What goes wrong:** tickers are shared between coins and listed shares: SOL (Solana, and
  ReneSola on the NYSE), LINK, COMP, FET. Case: Alice's Coinbase CSV brings *SOL* first, made
  `crypto`; Bob's Schwab OFX then buys ReneSola as `SOL` with its CUSIP: `instrument()` finds the
  coin by symbol, gives it the CUSIP, and Bob's 100 shares are priced at Solana's close (about
  $150 against $2). In the other order Alice's coins are priced as the stock. Nothing warns.
- **Run:** no; reading.
- **Remedy:** match by symbol only within a compatible class (a coin with a coin, a listed
  security with a listed security, CUSIP first); keep a coin's symbol in its own namespace (as
  the price source names it, `SOL-USD`) or make the uniqueness (symbol, class).

### U01-16: two OFX rows that share a FITID take the later one's date

- **Kind:** wrong figure (dates). **Req:** S1.3.2 ("An id a file repeats is another row, kept
  beside the first"), S14.9.3.
- **Code:** `web/server/src/moolakata/importers/ofx.py:62-71`:
  ```python
  out: dict[str, dt.date] = {}
  for el in root.iter():
      ...
      if fitid and raw and len(raw.strip()) >= 8:
          r = raw.strip()
          out[fitid] = dt.date(int(r[:4]), int(r[4:6]), int(r[6:8]))
  ```
  and `:121` / `:221` / `:229`, `dates.get(t.fitid) or …`.
- **What goes wrong:** the raw dates are keyed by FITID, so when a bank repeats a FITID (the case
  B19 made two rows of), every row with it takes the last one's date. Case: FITID `1001` on a
  Sep 3 $40 debit and a Sep 9 $40 debit: both are saved on Sep 9, the account's balance from
  Sep 3 to Sep 8 is $40 too high (and any check in those days with it), and the pair looks like
  a same-day duplicate the person is invited to delete.
- **Run:** no; reading.
- **Remedy:** key the raw dates by the element's position (the n-th `STMTTRN`/`INVTRAN`), or
  read each row's date from its own element.

## Uncited first-level items

- **S1.4** (retirement accounts): built under other words, but for vesting. The contribution
  year is a column set on import and when typed, and editable (`store/repos/ledger.py:510`,
  `ui/transactions.py:635-637`, `screens/transaction-dialog.js:337-346`); the employer match is
  `contributionSource = 'employer'`; the birth year comes from the profile
  (`taxes/panels.py:489`); the limits are the shipped tax tables an admin corrects (S16.11, unit
  10). Vesting: not built (U01-6). D1-8's wrong citation (S8.6 for S16.11) is the documents'.
- **S1.5** (crypto exchanges): built under other words: the `crypto-exchange` type, its CSVs
  with one mapping per institution (`ImportMapping`, unique per owner and institution), its
  statements through the brokerage reader, and what its files trade made `crypto`
  (`store/repos/ledger.py:292-297`). A trade history whose columns aren't guessed can't be mapped
  (U01-11); coins sharing a stock's ticker merge (U01-15). Reading an exchange's API is not built,
  as S1.5 says (later or out of scope: D1-5/DC-4, needs the user, no code either way).

## Phase 1 claims against the code

- **D1-5 / DC-4** (exchange APIs "come later" pointing at out of scope): no code reads an
  exchange's API, which fits both readings.
- **D1-14** (S4.3's stale-at-90-days alert against S1.11.7's overdue): `ledger/expected.py`
  builds S1.11.7 as written (grace 15/30/60, named statement, cleared by any import, none never
  alerts); the 90-day stale alert is unit 03's to check.
- **DC-13 / D2-16** (which size limit applies): every import route here (`upload`,
  `keep_upload`) reads S16.8's `importMaxMb`, OFX, CSV and statements alike, so this unit
  follows the "S16.8 for statements and import files" reading; the connector's posts are unit
  12's.
- **D1-25** (who sees a statement kept on an account): `_keep_file` (`ui/imports.py:921-936`)
  stores the PDF as a receipt owned by **the uploader** (`c.id`), not the account's owner, and
  attaches it to the account: a write sharer who reads the owner's statement owns its file. For
  unit 06 to weigh with D1-25; not a claim here.

## Earlier findings re-checked

| Finding | Still holds? |
|---|---|
| B3 (reinvestment's income counted twice) | yes: `importers/ofx.py:201-213`, and `test_a_reinvested_dividend_is_income_once_and_a_buy_with_none` |
| B5 (options from files) | yes: OFX `BUYOPT`/`SELLOPT`/`CLOSUREOPT` (`ofx.py:234-252`), CSV OCC rows (`csvfile.py:258-274`), ends settled with the broker's stock leg (`repos/ledger.py:530-610`); tests in `test_importers.py`, `test_accounts.py:369` |
| B7 (lot method on imported sales; rerun on change) | the method is recorded (`repos/ledger.py:509`) and wash sales rerun (`ui/accounts.py:578-582`); the rerun still has no test (U01-13) |
| B9 (a file's positions are a check) | yes, but "kept by snapshots" counts any instrument row as a trade (U01-3) |
| B18 (newest-first CSV) | yes for files over several days; a one-day file can't be told (U01-8) |
| B19 (re-import idempotency) | cents, FITID fallback and repeated FITIDs hold (`test_reimports_match_by_cents_by_row_and_keep_a_repeated_id`); deleted rows come back (U01-1); repeated FITIDs share a date (U01-16) |
| B20 (CR/DR turned twice; OCR pages) | yes: `statements.py:268-275`, 30 pages in 300 s (`receipts/ocr.py:20`, `reading.py:39`) |
| B33 / C43 (Reconcile tab for every statement account) | **half**: the server's rule and the alerts are widened; the browser's tab is not (U01-9). Loans on their Overview as decided (12.5.1) |
| B43 (ask for a balance when overdue) | yes: `ledger/reconcile.py:141-144` |
| C31 (import results as exact numbers) | yes: `ui/imports.py:106`, `_text` returns the Decimal |
| C44 (present lines teach nothing) | yes for bank statements; **no** for brokerage statements (U01-5); and an edited line teaches a skip (U01-4) |
| A22 (transfers: 4 days, closest, ties none) | yes: `ledger/transfers.py`, `repos/ledger.py:184-207` |
| A23 (one account per OFX; ½% or $1) | yes: `ofx.py:91-94`, `reconcile.py:147-164` |

## Checked and sound

- `importers/parsed.py:from_json`: every field from the reader's worker checked for type, length
  and a finite decimal, rows and securities capped, anything else refused (S9.8.4.2).
- OCC parsing in three spellings with a real expiry date; OFX option trades and ends mapped to the
  four trades and three ends; `_stock_legs` picks the stock side right for exercise and assignment
  of calls and puts.
- Statements: a card's CR/DR left as the account's side and a minus turned once; a December line
  on a January statement given the year before; the opening anchor the day before the period,
  the closing on its last day; a combined statement's parts each checked against their own
  balances and the PDF kept once on each account (receipts deduplicated by hash per owner).
- Kept statements: excluded from coverage, counted as arrived, refused when the same file is
  already on the account.
- Statements expected: defaults by type and kept-by, learned from three ends with the 20-day
  floor, a dismissed interval not proposed again, overdue after interval plus grace, named.
- Coverage gaps and overlaps; balance checks with the window and its suspects; the value check's
  tolerance (½% or $1).
- Access: every import route checks write on the account (`upload`, `_run`, statement save, each
  part's chosen account, keep, brokerage save), held uploads are bound to the uploader, jobs are
  read by their owner only; anchors, adjustments and reconciliations need write; settings,
  sync and the limit are the owner's; delete is the owner's.
- `withdrawalsAMonth`: savings and money-market only, 1 to 99 or empty.
- A `daf` made without *Count in net worth* counts in no one's (`ui/accounts.py:439-441`).
- Migration 0029's table rebuild runs with foreign keys off and a `foreign_key_check` after
  (`store/migrate.py:107-122`), views dropped first and synced after.
- Re-import: amounts compared in cents (`money.to_cents`) and the loose key in cents.

## Read lightly or not read

- `importers/brokerage.py`'s layout rules (Schwab, Fidelity, Empower section words): read, not
  checked against real statements (none in the repository beyond the tests' text).
- `csvfile.GUESSES` against real banks' and exchanges' exports: from memory only (U01-11 says so).
- `ledger/categories.py` (S7.2's tree, unit 05's substance) and the S2.9/S2.7 columns in
  `store/tables/accounts.py` and `entities/accounts.py` (Rule, Reimbursement): skimmed.
- `ledger/lots.py`, `valuation.py`, `options/`, `washes.py` and `alerts.py` were read only where
  this unit's code calls them (units 03 and 09).
- `tests/test_created.py` not read; `test_brokerage.py` and `test_statements.py` read in part.
- The account-type modules: read for their flags, not each hint.

## Work pad: severity, confirmations, status

| Id | Kind | Req | Sev | Conf | Status | Description |
|---|---|---|---|---|---|---|
| U01-1 | bug | S1.3.2, S1.11.4 | Med | 0 | open | A deleted transaction comes back with the next import that carries it |
| U01-2 | wrong figure | S1.3.2, S2.1, S4.3 | Med | 0 | open | A broker's trade-history CSV makes its securities class `other`, which no source prices |
| U01-3 | differs | S1.3.2, S1.3.3.8.1, R3.2 | Med | 0 | open | One cash dividend ends keeping by snapshots, and the file's positions stop being holdings |
| U01-4 | bug | S1.3.3.3, S1.3.3.4 | High | 0 | open | Correcting a statement line's description teaches a skip of every line that starts like it |
| U01-5 | bug | S1.3.3.4, S1.3.3.8 | Med | 0 | open | A brokerage statement's lines already present, or all of a file-kept account's, are learned as skips |
| U01-6 | not built | S1.4 | Low | 0 | open | Vesting for a 401(k) is built nowhere and specified nowhere |
| U01-7 | wrong figure | S1.11.1, S1.11.2, S1.3.2 | Low | 0 | open | An OFX file's end and ledger balance move a day in UTC; positions are dated by their price |
| U01-8 | bug | S1.11.2 | Low | 0 | open | A newest-first CSV of a single day keeps its oldest row's balance as the day's |
| U01-9 | differs | S1.11, S1.3.3.8 | Med | 0 | open | Retirement, plan, 529, DAF and exchange accounts have no Reconcile tab in the browser (B33) |
| U01-10 | differs | S1.3, S1.3.3.8, R3.2 | Med | 0 | open | No account can be set to statement import, so a plan statement's positions are never holdings |
| U01-11 | differs | S1.5, S1.3.2 | Med | 0 | open | A trade history's columns can't be mapped, so an exchange's CSV imports as cash |
| U01-12 | bug | S13.7.6 | Low | 0 | open | Uploads waiting for a mapping or check stay in memory 30 minutes, outside the per-user limit |
| U01-13 | test gap | S2.3 | Low | 0 | open | No test reruns wash sales when the lot method changes |
| U01-14 | differs | S1.11.3, S1.11.5, S1.3.3.8.1 | Low | 0 | open | The Reconcile screen and guides leave out the first parting row, the $1 and the full defaults |
| U01-15 | wrong figure | S1.5, S2.1 | Low | 0 | open | A coin and a listed stock with the same ticker become one instrument |
| U01-16 | wrong figure | S1.3.2 | Low | 0 | open | Two OFX rows sharing a FITID take the later one's date |

**Counts:** 16 claims. High 1, Med 7, Low 8. By kind: bug 5, differs 5, wrong figure 4, not
built 1, test gap 1, untraced 0, security 0, privacy 0. None withheld; none needs the user
(U01-6 may become a gap or an L item, the user's call at the walk-through).

**Ended:** Oct 24, 07:58 PM.
