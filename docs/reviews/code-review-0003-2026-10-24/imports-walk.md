# Walk-through: review 3's import claims

Started Oct 29, 2026. Decisions log; nothing is applied until the final approval. The claims are
those of unit 01 about reading a file into an account (S1.3, S1.5, S1.11); the unit's other
claims (CR3-17, CR3-169, CR3-173, CR3-343, CR3-344, CR3-360, CR3-374) and the connector's
(CR3-66 to CR3-70) are left for their own pieces of work.

## Items

1. CR3-13 (Med): a deleted transaction comes back with the next import that carries it
2. CR3-15 (Med): one cash dividend ends keeping by snapshots, and the holdings vanish
3. CR3-18 (Med): no account can be set to statement import
4. CR3-345 (Low): every file's positions are saved as holdings snapshots, trades or not
5. CR3-16 (Med): a brokerage statement's lines already present are learned as skips
6. CR3-14 (Med): a trade-history CSV makes its securities class `other`, which no source prices
7. CR3-19 (Med): a trade history's columns can't be mapped, so an exchange's CSV imports as cash
8. CR3-174 (Low): a coin and a listed stock with the same ticker become one instrument
9. CR3-170 (Low): an OFX file's end date and ledger balance move a day in UTC
10. CR3-175 (Low): two OFX rows sharing a FITID take the later one's date
11. CR3-171 (Low): a newest-first CSV of a single day keeps its oldest row's balance
12. CR3-172 (Low): uploads waiting for a mapping or a check are held in memory, uncounted
13. Found by the corpus: notes below a CSV's rows (a broker's disclaimer and download time)
    make a short upload "not a CSV" (415); in a longer one no date format reads every row, so
    none is proposed, and with one chosen the read stops at the first note ("Row 15: the date
    is not written as %m/%d/%Y") (`fidelity-trailer.csv`)
14. Found by the corpus: a plan statement imported again lists its holdings checks twice
    (`empower-401k.statement.txt`, invariant *again*)
15. Found by the corpus: a bank statement whose lines are already in the account starts them
    left out, so it doesn't add up until the difference is accepted, in the browser and on the
    server (`umb-statement.statement.txt`, invariant *again*; `_checked` and
    `StatementReview` sum the ticked lines only)

## Decisions

1. **Before the walk: how imports are tested.** Approved Oct 29, built before any finding is
   fixed: an import corpus (S17.5.7) of files shaped as institutions export them, each with
   expected results written by reading it; invariants over every file (again, reversed,
   overlap, deleted, zones); a table of sequences; a check that the browser offers what the
   server takes; each instrument's class checked against the real price sources, so dev
   mode's stub can't hide an unpriced class. Real exported files join later (G25). Each walk
   item's fix makes its expected failures pass and takes their marks away. Items 13 to 15 were
   found while building it.
2. **CR3-13 (1 of 15): match deleted rows too.** Matching a file's rows to the account's by
   identity (FITID, or date, amount and payee without one) is an import's first step, and it
   takes in deleted rows: a row that matches a deleted one counts as matched, and an import,
   overlapping or again, never changes a row's deleted flag. Deletes become uniform across the
   app, in this PR as their own commit: a Yes/No dialog, No the default (Enter and Esc), in
   place of every *Click again to delete*; the rule goes into S12. No "ignore on future
   imports" choice (weighed and withdrawn: identity decides). Seeing and recovering deleted
   things (*Show deleted*, *Recover*) is later work, recorded as G26.
3. **CR3-15 (2 of 15): a trade is what makes or takes away a lot.** Buy, sell, reinvestment, a
   transfer of shares in or out, an option trade, a corporate action. Income and fees on an
   instrument (cash dividends, interest, distributions, fees) don't end keeping by snapshots.
   Opening lots from a first import's positions is not taken up here.
4. **CR3-18 (3 of 15): the data decides, not a setting.** Holdings come from the lots when the
   account has trades of its own, and from its latest statement's positions when it has none
   (kept by snapshots), never from `keptBy`. A statement's lines start ticked unless already
   present (identity, decision 2), so `byFile` goes; a corpus sequence (an OFX, then the same
   month's PDF statement) proves a broker's statement lines match its file's. `keptBy` is two
   choices, *Imports* (files and statements alike) and *Manual*, and only sets the *Statements
   expected* default (none for Manual); the mockup's four-way *Method* select becomes those
   two, and S1.3 says it so.
5. **CR3-345 (4 of 15): not a bug; positions are kept from every file.** Each file's positions
   are kept, dated: a holdings check against the lots, the statement price of an instrument no
   source prices (`valuation.py`), and the holdings when the account has no trades (decision
   4). The review's remedy would take the statement price from a traded 401(k)'s unlisted
   funds. S1.3.2 says so; the corpus sequence is turned around (rows written, holdings from
   the lots); CR3-345's status becomes *not a bug*.
6. **CR3-16 (5 of 15): skips are the person's explicit rules, never learned on their own.** In a
   statement's review table (bank and brokerage alike), a line the person unticks (not one
   present) shows a dim *Remember…* at its row's end; it opens a popover on the row, "Ignore
   future lines starting with:", its field prefilled with the line's first three words, OK
   and Cancel (Enter, Esc). Taken, the row shows *Ignored next time ✕*; the rule is saved with
   the import's save, per owner and institution. A later statement's line a rule catches is
   shown, unticked and dimmed, with *Ignored (starts with "…") · Stop ignoring*, never dropped
   unseen. Settings › Imports lists *Ignored statement lines* per institution, each with
   *Remove*. Section-heading signs stay learned from the lines kept.
7. **CR3-14 (6 of 15): a CSV security's class by its symbol's shape.** In an investing account,
   a five-letter symbol ending in X is a `mutual-fund`, any other ticker-shaped symbol `equity`
   (an ETF lands as `equity`, priced alike), anything else `other`. No migration of existing
   instruments (none is needed yet). Correcting an instrument's class is later work, G27.
8. **CR3-19 (7 of 15): the trade columns are offered, guessed and signed by action.** The
   mapping step offers *Action*, *Symbol*, *Quantity*, *Price* and *Fees* for investing and
   crypto accounts; the guesses gain *quantity transacted* and *total (inclusive of fees…)*; a
   trade's cash takes its sign from its action (buy and fee out, sell in) whatever the file
   wrote; an asset in the account's currency is cash. The corpus's Coinbase expectations stand
   (the proposal plus *Notes* as the description). No shipped exchange mappings until G25's
   real files; Coinbase's *Convert* (two trades in a row) goes into G25's notes.
9. **CR3-174 (8 of 15): coins and listed securities are two namespaces.** A symbol is unique
   among coins and among the rest; an import looks for a coin in a crypto exchange or wallet
   account and for a listed security otherwise (CUSIP first). Equity, ETF and fund stay one
   family. The unique index becomes (symbol, coin or not): one Alembic revision, no data
   migration.
10. **CR3-170 (9 of 15): every date in an OFX file is the date the institution wrote.** Start,
    end, ledger balance and statement as-of are read raw, as the rows are, never through UTC;
    positions are dated by the statement's as-of, not their price's.
11. **CR3-175 (10 of 15): each OFX row's date is read from its own element**, by its place in
    the file, not from a map keyed by FITID; the corpus gains a FITID repeated on two days.
12. **CR3-171 (11 of 15): when the dates can't tell a CSV's order, the running balance does.**
    Rows that chain (a balance is the one before plus the amount) only newest first are
    flipped; chaining neither way, file order stands. A one-day newest-first case joins the
    corpus.
13. **CR3-172 (12 of 15): held uploads count against the user's 100 MB.** A new upload past it
    releases that user's oldest held one (its open dialog's next step says *This upload
    expired; upload the file again.*); closing or cancelling an import dialog releases its
    upload at once.
14. **Item 13 (13 of 15): a CSV's rows end at the first blank line after them.** What follows is
    a trailer, left out and said so in the mapping step (*3 lines below the rows were left
    out*); the CSV check and the date-format proposal look at the header and its rows only.
15. **Item 14 (14 of 15): a statement's positions and anchor are matched by identity.** A
    position is identified by account, date and instrument (or label), a value anchor by
    account, date and source; importing again adds nothing, and a value that differs replaces
    the old one. The file and statement paths share one helper.
16. **Item 15 (15 of 15): a statement's sum counts every line that will be in the account.** A
    present line shows ticked and disabled, *Already in the account* (identity keeps it from
    being added twice); the sum is the ticked lines, in the browser and on the server, the
    server finding the present lines itself. A line the person unticks leaves the sum and
    offers *Remember…*; a present line never does. S1.3.3.3 says present lines show as already
    in the account.

Final approval of decisions 2 to 16: Oct 29, 2026.

## Applied

On branch `cr3-imports` (PR #19), each with its requirements, mockup and tests; the corpus has
no expected failure left.

| Decision | Claim | Commit |
|---|---|---|
| 2 | CR3-13 | `b91a8be`; the delete question, G26: `0ba1337` |
| 3 | CR3-15 | `ff4aa3a` |
| 4 | CR3-18 | `5800025` |
| 5 | CR3-345 (not a bug) | `5800025` |
| 6 | CR3-16 | `5800025` |
| 7 | CR3-14, G27 | `16915ea` |
| 8 | CR3-19 | `8c9446d` |
| 9 | CR3-174 (migration 0042) | `68a0eb4` |
| 10, 11 | CR3-170, CR3-175 | `06ca8a5` |
| 12 | CR3-171 | `48f450b` |
| 13 | CR3-172 | `8c9446d` |
| 14 | item 13 | `8c9446d` |
| 15 | item 14 | `5800025` |
| 16 | item 15 | `5800025` |

Where the work differs from the decision as written, and why:

1. **Decision 3**: a split or corporate action is not a trade either. It only changes the lots
   there are, and an account kept by snapshots has none, so counting it would make the same
   holdings vanish.
2. **Decision 6**: the list of ignored lines is in **Profile**, not Settings › Imports. Settings
   is the admins'; the rules are each person's, per institution.
3. **Decision 4**: `keptBy` keeps its stored value `file` for *Imports*; `statement` is no
   longer taken (the browser never offered it).
4. **Decision 13**: the expired upload's dialog says the existing *That upload has expired;
   choose the file again.*
5. Claims that share code went into one commit (CR3-170 with CR3-175; CR3-19, CR3-172 and item
   13; CR3-16, CR3-18, CR3-345, items 14 and 15), the claims named in each message.
