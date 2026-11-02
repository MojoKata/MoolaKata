# Walk: filed tax years

Review 3's open Med claims on filed tax years: CR3-27, CR3-33 (S2.8), CR3-34 (S8.17), walked
on branch `cr3-tax-years` from main `5e409cf`. As asked for every walk from this one on, the
area's test coverage (code and data shapes) and its speed are an item of their own.

**Found before the walk.** All three still hold: `taxes/closed.py` and `taxes/books.py`
`previous()` are as the claims cite them. The guard (`closed.Guard`) is made by six call
sites (`ui/transactions.py` 555, 1257, 1272; `ui/options.py` 57, 130, 331, 398), each for the
edited account only. Other writes that move realized gains and make none: imports
(`store/repos/ledger.py:582`), the Connection's file posting, account deletion, *both real*,
transfer matching, an account's lot method (`ui/accounts.py:589`), a spouse relationship
(`ui/people.py:344`), wallets (`ui/wallets.py:252`), and every wash-sale rerun across accounts.

**Coverage today** (main's Pages site, the last merge): `taxes/closed.py` 96 % lines,
90 % branches; `washes.py` 99 / 95; `taxes/books.py` 95 / 89; `ui/taxes.py` 88 / 65;
`taxes/dependents.py` 92 / 76. Two tests reach closed years
(`test_taxbooks.py:370, 418`), both a hand edit in the filed account. High line coverage of the
guard said nothing of the write paths that never call it.

## Decisions

1. **CR3-27, CR3-33: the filed figures recorded, one check for every write (locked Nov 2,
   6:52 AM).**
   1. When a federal return becomes filed or accepted (and when an amended one is filed, or
      *No amendment needed* is chosen), the tax book records its realized gains by account,
      short- and long-term: the filed figures.
   2. One check in the unit of work, at commit, for every request or job that wrote a table
      that feeds gains (the data version's input tables): for each closed book of the
      households touched, the gains before (read from the committed database) and after. A
      move is asked (a draft's save), refused 409 (a plain route), or recorded and alerted
      (1.1). The six `closed.Guard` call sites go; a new write path is covered by itself.
   3. The tax book compares its live gains with the filed figures plus the changes recorded
      on every read, so a difference nothing asked about still lists as *Changed after
      filing*.
   4. (1.1) A writer no one can ask (a Connection's posted file, a background job) keeps the
      write, records the change on the book and alerts; a statement import under review asks
      at its review step (*Import anyway*).
   5. (1.2) Deleting an account a closed year counts asks, naming the move (*2025's filed
      gains change by −$500; to keep them, close it*).
   6. (1.3) An account added to or left out of a filed book, or a sharing change that drops
      one, is a gains move like any other: asked and listed.
   7. Tests: generated sequences, pairwise over the write path (~12), the book's state (filed,
      accepted, amending, amended, not-needed, none), where it lands (same account, other
      taxable, IRA, spouse's, joint) and when (a sale in the closed year, a buy within 30 days
      after it, a change that moves nothing); the invariant: after any write, live gains =
      filed figures + recorded changes, or the write was refused and nothing changed. Old bugs
      planted must fail worlds. A replay-counting test holds the check to closed books'
      accounts on gains-moving writes.
   8. Rejected: a household-wide guard added to each path (the next path is unguarded unless
      remembered); listing only on the book (breaks S2.8's ask first).
2. **CR3-34: last year's books by accepted filer (locked Nov 2, 6:59 AM).**
   1. For each filer of a book, last year's book is the one they were an **accepted** filer
      of: one book, or two after filing separately. One function gives the list; every reader
      (*From last year*, the Summary's carryover, last year's total tax beside the estimated
      payments, the copied accounts and dependents, the expected documents) reads it.
   2. *From last year* lists each book under its filers' names. Joint after separate: the
      Summary sums the capital-loss carryovers and last year's total tax is the sum; AGI and
      the 8606 basis show per filer; accounts and dependents copy from both.
   3. (2.1) One book a year per filer: being an accepted filer on two books of a year is
      refused, at creation and at accepting, naming the other (*You're a filer on 2025's tax
      book with Bob*); a pending invitation blocks nothing. A waiting book gets **Decline**
      beside *Accept*: it takes the user off and tells the book's owner.
   4. (2.2) Separate after joint: each separate book shows the joint return's figures, marked
      *joint*; the Summary counts a carryover once the filer types their share, and an issue
      asks for it until then (S8.18: the split is a judgement).
   5. (2.3) Expected documents follow *Start from last year*: the choice is stored on the
      book, and the pending copy gets its own field.
   6. Tests: every pair of a couple's arrangements over two years (last year: none, solo,
      separate, joint, joint with a filer pending, a pending invite while filing alone,
      deleted; this year: solo, separate, joint; switch on and off), through the API: each
      book read is its filers' accepted one, nothing comes from a book a filer can't open,
      sums and copies right. The old `previous()` planted must fail cases.
   7. Rejected: the dialog asking which book (wrong for joint after separate); accepted
      filers but the first book (leaves separate then joint).
3. **The area's tests: generated tax worlds, a reference model, the panels in the browser,
   query budgets (locked Nov 2, 7:04 AM).** Measured first: `taxpanels.js` 22 % lines (139 of
   638), `screens/taxes.js` 75 / 66, `ui/taxes.py` branches 65 %, `dependents.py` 76 %; 25
   server tests, each a story, no axis named; a book read 13 ms / 52 queries, its panels
   55 ms / 147 queries, the list 10 ms / 17 queries, with 200 trades over three accounts
   (600 trades hit the API's 600-a-minute limit while seeding).
   1. `tests/tax_world.py`: worlds pairwise over the filers (solo, joint, separate, married
      mid-history, a spouse died in the year), account kinds (taxable, IRA/Roth/401k, HSA,
      529, bank, crypto, custodial, joint), sale shapes (terms, covered or not, washes in the
      account, across accounts, the spouse's, into an IRA, across a year's end; specific lot;
      options opened, closed, expired, assigned; splits and mergers; bitcoin fee sales under
      each setting), income kinds (interest, qualified and ordinary dividends, gain
      distributions, foreign tax, RMDs, contributions and conversions), the book's state
      (decision 1), counted-account overrides, dependents (ages about 13, 17, 19, 24; student)
      and last year's arrangement (decision 2); each made through the API.
   2. Rules on every world: Schedule D = the 8949 rows = the disposals of the counted taxable
      accounts; each disposal in one box; wash losses disallowed = the adjustments = the basis
      added to the replacements; the CSV and TXF reconcile with the panels; income by kind =
      its transactions; nothing from an account a filer can't see; decisions 1 and 2's
      invariants.
   3. A naive reference model in the tests (lots by method, washes by brute force over every
      pair of trades) works out the 8949 rows on its own; every world's rows equal it.
   4. Planted: the old bugs and wrong rules (a 31-day window, a long-term cutoff a day off, a
      wrong box) must each fail worlds.
   5. Browser: each panel shows the API's figures for a few worlds; the tax screen's new book,
      Accept and Decline, filing dialogs and issues.
   6. Speed: query counts asserted at about 50 and 500 trades (seeded without the API), not
      growing with the trades; the closed-year check's replays counted; times printed, not
      asserted.
   7. Floors raised on these files as they rise; each line left unreached named in this log
      with its reason; aim ≥ 90 % branches on `ui/taxes.py`, `dependents.py`, `taxpanels.js`.
   8. (3.1) Order: the worlds and the reference model first, run against today's code (they
      must fail on CR3-27, 33 and 34), then decisions 1 and 2 built against them.
   9. Rejected: invariants without a reference model (a rule wrong the same way everywhere
      passes); the decisions' own tests plus hand tests for unreached lines (leaves the
      crossings).

**Final approval** given Nov 2, 7:06 AM, with: as the suites grow, keep an eye on how long the
tests take and on running them in parallel on GitHub.

## Applied

1. **Generated tax worlds and the reference model** (decision 3, part 1). `tests/tax_world.py`
   draws 24 worlds (filers solo, joint or separate; four lot methods dealt over Alice's two
   brokerages, her exchange and wallet, and Bob's brokerage), each with 22 sale stories over
   13 axes (seller, class, method, picks, term, outcome, size, where and when a buy near the
   sale falls, how much it replaces, the year sold, a later sale of the replacement); all 856
   possible pairs of axis values meet in some world. `tests/tax_reference.py`, which imports
   nothing of MoolaKata, works out each book's Form 8949 from the description;
   `tests/test_tax_world.py` makes each world through the API (about 130 trades) and holds
   every book's rows to it, and Schedule D, the wash sales and the CSV export to the rows.
   24 worlds in 42 s on 8 workers. Found, each a new claim, the worlds failing on it marked
   strict xfail until fixed:
   1. **CR3-386**: a trade typed by hand makes its instrument a share whatever its symbol, so a
      fund bought in 2011 lands in box D, not E (CR3-14 decided the class by the symbol's
      shape, applied to imports only).
   2. **CR3-387**: average cost is applied to shares; S2.3 has it for funds and coins.
   3. **CR3-388**: a replacement bought before the loss sale takes the disallowed loss into its
      basis from the day bought, so highest-cost-first and average cost pick the sale's own
      lots by the loss it is about to have disallowed: the wash sales flip between two answers
      and the twelfth round's stands. And shares the sale itself sold count as its
      replacement (S3.8.2).
   4. **CR3-389**: specific identification (S2.3, *chosen per sale*; the guide's *you pick at
      each sale*) has no way to pick a sale's lots, in the save or the dialog: an account set
      to it sells first in. The worlds leave picks out (`reachable`) until it does;
      `test_a_sales_lots_can_be_picked` is a strict xfail.

   Decided (Nov 2, 7:27 AM, all as recommended):
   1. (4.1) CR3-386: a typed symbol's class by the same rule as an import's (five letters
      ending in X a fund).
   2. (4.2) CR3-387: in an account set to average cost, funds and coins take it; shares go
      first in. The account's Settings note says so.
   3. (4.3) CR3-388: the loss joins a replacement's basis, and its holding period moves, from
      the loss sale on; shares a sale sold never replace it (S3.8.2); the wash sales are
      asserted to settle, never cut off at a round.
   4. (4.4) CR3-389: built here: the sell dialog's **Choose lots…** lists the open lots
      (acquired, quantity, basis, term); the save takes the picks and keeps them on the sale,
      kept through an edit; the mockup and guide follow. CR3-26 with it: a pick of a lot a
      wash sale split takes from that lot's pieces. The worlds' picks axis turns on.
2. **Round 4, built** (each with focused tests that fail on the code before it): CR3-386
   `28deaf1` (a symbol's class by its shape, typed or on a statement); CR3-387 `0ccae13`
   (average cost for funds and coins; the lot method's note in both account screens, the
   guide, the mockup); CR3-388 `ac53220` (a replacement settles at its loss sale; a sale's own
   shares never replace it; the rounds settle or fail); CR3-389 `73bd340` + `90cb721` (picks as
   `LotPk` records; `GET /accounts/{id}/lots`; the sale's dialog lists the lots with a
   **Take** each; the mockup's *Record trade* for a sale, the guides). Found turning picks on:
   **CR3-390** `73bd340` (the sold shares a smaller buy-back replaces are the earliest
   acquired, Treas. Reg. §1.1091-1(c); each wash sale keeps its sold lot, `WashSale.lotId`,
   migration 0049, so its **W** stays on that lot's rows and terms). CR3-26 fixed with
   CR3-389. Every world passes, picks on.
3. **Decision 1, built** (`c9f1771`). Deviations and details:
   1. The check is `taxes.closed.check`, registered with `store.commit_checks`, which
      `Database.tx` runs before every commit. What a write touched is noted on its connection
      (`before_flush`), so the server's work inside it (`as_server`) is seen too; only fields
      gains are worked out from count (a memo, a category, a bank transaction, a new account
      cost no check). A check that reads as the server leaves the request's records unexpired
      (`as_server(..., expire=False)`): expiring them broke a route that read one after its
      commit (found by the import corpus).
   2. The save runs the check itself before its questions, so a move joins them; a route outside
      the save answers 409 `closed-year`, and the browser's API client asks once (*Change a
      filed year?*, the server's words, its button the server's: **Import anyway** at a
      statement's review) and sends the request again with `X-MoolaKata-Confirm: closed-year`.
      Writes no one answers (a server session, or a file read in the background, `unasked`)
      record.
   3. The filed figures are kept on the federal return that closed the year (`Filing.filedGains`,
      migration 0050, with the changes already in them), not a table of their own; the Issues
      list a difference no change explains as `differs-from-filed`.
   4. (1.2) The question names each year's move (*the realized gains of 2025 by −$500.00*), and
      for an account deleted adds *To keep them, close the account instead*.
   5. Tests (`test_filed_years.py`): ten ways of writing against six states of the return, 60
      cases, each asserting the refusal, the year unchanged until confirmed, the listing equal
      to the move, nothing listed for an open year, and no unexplained difference; a figure
      changed behind the server's back listed as one; a route refused until its request
      confirms; a counting test that a write moving no gains works out no book, and one that
      can works out its household's closed book twice. Left out of the matrix: *both real* and a
      matched transfer (the same check sees them; their own setups to come), a Connection's
      file (the background import's path).
4. **Decision 2, built** (`fb0c724`). `books.last_years` gives, for each filer, the book they
   accepted; `carried_from_last_year`, `federal_figures` (an amended return's, once filed),
   `carryover` and the expected documents read it. Details:
   1. The choice to start from last year is kept (`fromLastYear`), the copy waiting for every
      filer apart (`copyPending`); the share of a joint carryover is the book's
      (`carryoverShareShort`/`Long`), all in migration 0051, saved through the book's record.
   2. Decline (`POST /tax-books/{id}/decline`) takes the filer off and records
      `tax-book.declined` in the owner's Activity (*tells its owner*), not an alert.
   3. With two of last year's books, the retirement panel's single 8606 basis is none: each
      filer's shows under *From last year*.
   4. Tests (`test_last_year.py`): every 2025 arrangement (none, alone, separate, joint, joint
      with a filer pending, filing alone while invited, deleted) against every 2026 one (alone,
      separate, joint), the switch on and off: 42 cases, each holding *From last year*, the
      carryovers, last year's tax and the expected documents to the books the filers
      accepted; the share once typed; one book a year and Decline. The mockup gains
      *Taxes · filing separately after a joint return* and *named on a book: Accept or Decline*.
5. **More of decision 3** (`b5f6d50`): the worlds gain a 2-for-1 split between a story's
   buys and its sale (recorded as Positions records one), Second left out of Alice's 2026 book
   in half the worlds, and 16 income records a world (interest, dividends paid and reinvested
   of each type, capital-gain distributions, in each account and year), pairwise: 1,035 pairs
   of a story's axes, 115 of an income's. The reference model splits lots, counts what a book
   counts, and works out its income; every world holds the Income panel to it. Found:
   **CR3-392** (an untyped reinvested dividend in no figure) and **CR3-393** (the wash-sale list
   holding an account left out). Earlier, `d4c839f`: query budgets at 150 and 600 trades,
   which found the wash list's query a wash sale and **CR3-391** (an IRA replacement's adjusted
   basis with the loss added); `1dc425d`: the panels in the browser. Still to come of decision
   3: options and mergers in the worlds, bitcoin fee sales, dependents; Accept and Decline in
   the browser (the shared household's second user has no password to sign in with).
6. **Options, mergers, fees** (`COMMITOPT`). The worlds gain 10 option stories each (long or
   short, a call or a put, closed, expired, or assigned or exercised with its stock trade, a
   short or a long term, each year and account): 194 pairs. A story's split becomes an
   action, a merger for two new shares and $3.00 cash among them (IRC §356). The reference
   model follows: a written contract short term, its proceeds the credit; expiry; the
   premium in an assignment's or exercise's stock; a merger's cash a gain only as far as both
   go, the new shares of the old ones' class. Every world passes. Planting wrong rules: a
   31-day wash window fails 10 of 24 worlds, a long-term cutoff a day early 20; a share's
   basis reported from 2012, not 2011, failed none until the old lots were drawn on each side
   of the year reporting began (now 14). `test_bitcoin_fees.py`: a network fee's sale, every
   case of where the coins went, how the book reads fees, and the term (8 cases); nothing had
   covered fees before.
