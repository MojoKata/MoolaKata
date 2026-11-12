# S2. Holdings, lots and transactions

1. **Instruments** are kept once per server: symbol, name, class (`cash`, `equity`, `etf`,
   `mutual-fund`, `money-market`, `bond`, `option`, `crypto`, `metal`, `other`), and for
   options the underlying, right (call/put), strike, expiry and multiplier (100 by default). A
   symbol names one coin and one listed security at most: a coin and a share may share a ticker
   (SOL is Solana and ReneSola), so a file's symbol is looked for among the coins in an
   exchange's or a wallet's account and among the rest elsewhere, a CUSIP first. A security
   known by its symbol alone (typed in a trade, or named so in a CSV or on a statement) is a
   mutual fund when the symbol is five letters ending in X, a listed share when it is any other
   ticker, and a coin in an exchange's or a wallet's account (G27: correcting one). An
   option's symbol follows OCC (`AAPL  261218C00250000`); it is stored as people read it, `AAPL
   18DEC26 250 C`, and shown as `AAPL 18 Dec 26 250 C`.
2. **Lots** are created by buys and by transfers in with a cost basis. Every lot is made by
   a transaction: value that arrives comes with what moved it in, so returns count it as money
   in, not growth (S5.2). A transfer in takes its
   lots as they were bought: each with its day bought, quantity and basis, adding up to the
   shares moved in, so a sale's term and gain count from the day bought, not the day they
   arrived. One paired with a transfer out of another of the owner's accounts carries that
   one's lots instead (S1.7.1). A transfer in without its lots (a broker's file says nothing
   of them) is one lot marked *day bought missing* and *basis missing*: its term shows as
   unknown, and Taxes lists it until both are typed (S8.4). What is known of a lot goes with it
   wherever it goes: a sale from it has its term unknown and its Form 8949 date *VARIOUS*, and
   Taxes lists the sale too; a symbol change, spin-off or merger carries the mark to the new
   shares. Editing the transfer's date moves only a lot whose day bought is missing.
3. **Sales consume lots** by the account's **lot method**: FIFO (the default), LIFO, HIFO,
   specific identification (chosen per sale), or **average cost** (mutual funds, and crypto
   where elected: a listed share in an account set to average cost is sold first in). The method in force at the sale is recorded on it, however the sale arrives
   (typed, imported or synced); changing an account's method applies to the sales after the
   change, and the wash sales are worked out again (S3.8.4).
4. **Corporate actions**: splits, reverse splits, symbol changes, spin-offs (manual basis
   allocation), mergers (cash and/or stock) and return of capital adjust lots, never history.
   Return of capital is spread over every lot of the holding by quantity, a lot without a basis
   keeping its share until its basis is entered; what exceeds a lot's basis is a capital gain.
   1. **Recorded** on Positions with **Corporate action…** (or read from a broker's file, for a
      split): the holding, the date, and what the action needs. Each lot keeps the day it was
      acquired and any holding period a wash sale tacked to it.
   2. **A split** multiplies every lot's shares by its ratio, the basis unchanged.
   3. **A symbol change** moves every lot whole to the new symbol.
   4. **A spin-off** gives new shares at its ratio for each one held, and moves the share of
      each lot's basis the company states (its Form 8937, typed in percent) to them; the rest
      stays with the shares held.
   5. **A merger** moves every lot to the acquirer at its ratio. Cash paid besides the shares
      is a gain only as far as the lot's gain goes, worked out from the acquirer's price that
      day (IRC §356); the new shares' basis is the old less the cash plus that gain, and the
      gain is a row of Form 8949. A merger paid all in cash is a sale of every lot.
   6. A move between instruments is a pair of transactions, one on each; deleting either
      deletes both, after asking. Options on the shares are adjusted as S3.10 says.
   7. **The action is kept** as typed, its transactions made from it: deleting the action, or
      one of its transactions, undoes it whole. One read from a broker's file is its
      transaction alone.
5. **Dividends and interest**: qualified and ordinary dividends, reinvestment (a dividend plus
   a buy), and capital-gain distributions, with the classification the 1099 will use.
6. **Bank transactions** have a payee (normalised by **payee rules**), a category (S7.2), an
   optional split across categories, a memo, tags, receipts, and a reimbursable mark (S2.9).
7. **Categorisation rules**, which are also the **payee rules** of S2.6: an ordered list per
   user, in **Transactions › Rules**, first match wins.
   1. **What a rule matches**: the payee as the institution wrote it, by text it contains (case
      aside) or, after `re:`, a regular expression (RE2's syntax, with no back-references,
      look-arounds, atomic groups, possessive repeats or conditionals, each refused in those
      words; case aside unless the pattern turns it on with `(?-i)`; at most 200 characters);
      and, when given, an amount range
      (from and to, of the amount without its sign), a direction (money in, money out, or
      either) and one account.
   2. **What it sets**, one or more of: the **category**; the **payee** shown (*Rename to*),
      the institution's text kept beside it; and **tags**, the user's own (S2.6).
   3. **On import** (a file, a statement or a connector's fetch), the rules of the user who
      imports are applied to each new row that is a bank transaction (not a trade) and not a
      transfer between the owner's accounts (S1.7). A row's category is set only when it has
      none, and a split is never touched.
   4. **On demand**, *Apply to the uncategorised* runs the user's rules over the uncategorised
      transactions in the accounts they can change, and says how many it set; Activity records
      that count, never an amount (S10.8).
   5. **The list**, on the *Rules* tab (S12.2.3.2), shows each rule's conditions and what it
      sets, and adds, edits, deletes and moves a rule up or down; each change is recorded in
      Activity as a rule change. A rule
      whose account or category was deleted shows it as deleted; one whose account went
      matches nothing. Rules are their user's own: never shared, and never across a link
      (S11.5.2).
   6. **From a transaction**: its dialog offers *Make a rule*, which opens **New rule** over
      it (S12.15.7): the *Rules* tab's fields, the payee and category filled in. Its **Save**
      makes the rule, and the transaction's dialog stays as it was.
   7. **The receipt reader** passes the merchant it read through the uploader's rules: a rule
      that renames a payee renames the merchant the same way (S9.8.2.5.3).
8. **Editing history** is allowed. Every derived figure (balances, lots, gains, budgets,
   charts) follows on the next request. A change that moves a closed tax year's realized
   gains asks for confirmation first.
   1. **A closed year**, for an account, is one whose tax book counts the account and has its
      federal return filed or accepted (S8.15). While an amended federal return for that tax
      book is being prepared (not started, in progress or rejected), the year is open again
      and changes ask nothing; once the amended return is filed, the year is closed again.
   2. **Every write is checked**, whatever makes it: a transaction added, changed or deleted, a
      lot picked, an option trade or its end, a corporate action, a trade in another account
      or a spouse's that makes or ends a wash sale (S3.8), an account deleted, an account added
      to or left out of the tax book, a marriage recorded, a statement or a file imported. Once
      its changes are in, the closed books of the households it touched are worked out as they
      were and as they would be. When it moves a closed year's realized gains, it is refused
      with the years named (*This changes the realized gains of 2025, a year whose return is
      filed*), and the dialog offers to make it anyway, saying the return may need amending (a
      statement's review: **Import anyway**). A change that moves no closed year's gains (a
      memo, a category) asks nothing. A write no one is there to answer (a file read in the
      background, a Connection's file, an option expiring on its own) is kept, and recorded as
      below.
   3. **A change made anyway** is recorded on each tax book that closed the year: the account,
      how much the change moved the year's realized gains, and who made it. The tax book shows
      it until an amended federal return is added or someone chooses *No amendment needed*
      (S8.15).
9. **Reimbursable** spending: a transaction, or one split of it, can be marked as to be paid
   back, with how much (all of it unless said otherwise) and optionally by whom (*Acme Corp*,
   *Sam*). It keeps its category, for taxes and reports.
   1. **Awaiting**: a mark not yet paid back in full is listed under **Awaiting
      reimbursement** (S7.4) with its age, and budgets don't count the part awaited (S7.3.4).
   2. **Paybacks**: a deposit, not a transfer, of the amount awaited or less, within 90 days
      after the spending, is offered to pair with it; the owner confirms it or picks another.
      One deposit can pay back several (an expense report). The paired part of a deposit
      doesn't count as income; the rest counts by its category.
   3. **Never paid back**: lowering the amount to what was paid back, or taking the mark off,
      makes the rest count as spending again, in the month it was spent.
   4. **The transaction's own**: the mark is the same in every budget (S7.12.6). Activity
      records marking and pairing, never an amount (S10.8).
