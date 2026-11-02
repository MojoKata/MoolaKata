# S1. Accounts

1. **Account types**, each with its own icon and hue:

   | Type | Group | Holds | Tax treatment |
   | --- | --- | --- | --- |
   | `checking`, `savings`, `money-market`, `cd` | Banking | cash | taxable (interest) |
   | `cash` (cash on hand), `payment-app` (Venmo, PayPal, Cash App and the like) | Banking | cash | — |
   | `credit-card` | Liabilities | a negative balance | — |
   | `mortgage`, `heloc`, `auto-loan`, `student-loan`, `personal-loan`, `loan` (any other) | Liabilities | a loan with terms (S1.9) | mortgage and student-loan interest may be deductible |
   | `brokerage` | Investing | cash, stocks, ETFs, funds, bonds, options | taxable |
   | `ira` (traditional, SEP, SIMPLE) | Retirement | as brokerage | tax-deferred |
   | `roth-ira` | Retirement | as brokerage | tax-free (qualified) |
   | `401k`, `403b`, `457b` (traditional and Roth parts) | Retirement | funds, cash | tax-deferred / tax-free |
   | `hsa` | Retirement | cash, funds | triple tax-advantaged |
   | `529` (college savings) | Education | funds, cash, for one beneficiary (S1.8) | tax-free for qualified education |
   | `daf` (donor-advised fund) | Giving | funds, cash | deducted when contributed; grants are not deductible again (S7.9) |
   | `crypto-exchange` | Crypto | coins, fiat cash | taxable |
   | `crypto-wallet` (self-custody) | Crypto | bitcoin | taxable |
   | `precious-metals`, `collectables`, `real-estate`, `vehicle`, `other-asset` | Physical assets | items, each with its own basis and value (S1.10) | gains on collectables and metals: the collectables rate |

   A `daf` counts in no one's net worth by default: its money is already given away.
   **Count in net worth** on the account overrides that.

2. **Every account has** a name, its type, the institution, an optional masked number (last
   4), its owner, the day it **closed**, empty while open (a closed account counts in
   figures up to that day and stays for history and taxes; deleting one is a correction,
   R3.10), notes, and how it is kept current (S1.3). A `savings` or
   `money-market` account also has **Withdrawals allowed a month**, the bank's limit, empty
   for none, which budgets keep moves back within (S7.10.4).
3. **How an account is kept current**, one or more of the ways below. An account's **Keep it
   current by** setting is **Imports** (files and statements alike, and the connector's) or
   **Manual**; it sets only whether statements are expected (S1.11.7). Whether a file's or a
   statement's positions are the account's holdings is told by its transactions, never by the
   setting (S1.3.2):
   1. **manual**: transactions and balance snapshots typed in;
   2. **file import**: **OFX and QFX** files (the structured downloads most US banks and brokers
      offer; brokers' files also carry positions and trades), read with ofxtools; CSV, with a
      saved column mapping per institution; and brokers' and exchanges' trade-history CSVs. The
      first CSV from an institution asks **which columns are which**, its guesses checked: the
      date, description, amount (or debit and credit), running balance, memo and id, and for an
      account that holds instruments the action, symbol, quantity, price and fees. A trade's
      cash takes the sign its action gives it (a buy's goes out, a sale's comes in) whatever
      sign the file writes, shares or coins moved in or out move no cash, and an asset in the
      account's own currency is cash. The rows end at the first blank line below them: what
      follows (a disclaimer, the time the file was downloaded) is left out, and the step says
      how many lines were. A security a CSV names by its symbol alone is a mutual fund when the
      symbol is five letters ending in X, a listed share when it is any other ticker, and in an
      exchange's or a wallet's file a coin (G27: correcting one). Imports are idempotent: a
      re-imported file adds only what is new, matched by the file's transaction id (an OFX
      file's `FITID`) or by date, amount and payee, amounts compared in cents as stored. A row
      whose id isn't here yet still matches, by date, amount and payee, a row that has none (one
      typed by hand, or from a file without ids), which takes the id. Rows the owner deleted are
      matched too, and stay deleted: no file, nor the connector's overlapping downloads, brings
      one back. An id a file repeats is another row, kept beside the first and flagged with it
      as a duplicate suspect (S1.11.5). An OFX file holds one account's statement: one with
      several is refused, asking for one account at a time. A broker's file's positions are a
      **holdings check** on the statement's day (its as-of, whatever day their prices are from),
      as a statement's are (S1.3.3.8.2): the lots change only through transactions. Every file's
      positions are kept, dated, once per day: the same file again adds nothing, and figures
      that differ replace the ones kept. They are the holdings of an account kept by snapshots
      (R3.2), one with no trades of its own (nothing that makes or takes away a lot: a buy, a
      sale, a reinvestment, shares moved in or out, an option trade; income, fees and splits on
      a holding don't count), however it is kept current; and the statement price of an
      instrument no price source fetches (S4);
   3. **statement import**: a **PDF statement**, read from its text layer, or a **photo or
      scan** of one, read with RapidOCR as receipts are (S9.8), all on the server. MoolaKata
      finds the statement's period, its transactions and its opening and closing balances,
      and shows them for the user to check and correct before anything is saved. The
      transactions must add up from the opening to the closing balance; where they don't,
      the difference is shown and nothing is saved until it is resolved or accepted. What it
      learns about an institution's layout is kept per institution, so the next statement
      needs fewer corrections. Imports are idempotent here too. The statement file is kept as
      a receipt attached to the account (S9);
      1. **What it reads**: bank and card statements of one account, any number of pages, as
         UMB, Schwab Bank and card issuers lay them out. The period comes from a *Statement
         Period* or *Opening/Closing Date* line (else the first and last transaction); the
         balances from *Beginning/Opening/Previous* and *Ending/Closing/New Balance*; a
         transaction is a line that starts with a date and ends in amounts. Its sign comes
         from the running balance where there is one, else from an explicit sign (`-`,
         `( )`, `CR`), else from the section it is in (*Deposits and Other Credits*,
         *Withdrawals*, *Checks Paid*, *Purchases*, *Payments and Credits*), else from its
         words, and is then marked as guessed. Summary and daily-balance sections are left
         out. A card statement's figures are what is owed, and are turned to the account's
         side once; `CR` and `DR` already name the account's side (a payment is a credit),
         and are not turned.
      2. **Reading** uses the receipt reader's worker (S9.8.4): a text layer when the PDF has
         one, else OCR of every page, one at a time, up to 30 pages within five minutes (a
         receipt's three pages and one minute are too few for a statement). Settings ›
         Imports can turn statement reading off.
      3. **Checking**: the period, both balances and each line can be corrected, and a line
         left out. A line already in the account (the same date and amount, each transaction
         there answering for one line) is shown ticked, *already in the account*, and can't be
         unticked: it counts towards the closing balance and is never added again. The
         opening balance becomes
         the account's reported balance the day before the period, the closing balance its
         balance on the last day (S1.11).
      4. **What is learned per institution** (per owner): the sign of each section heading the
         person kept, a line kept with its description corrected told by the line it was read
         as. Lines to ignore are never learned on their own: a line the person unticks shows
         **Remember…** at its row's end, which asks *Ignore future lines starting with:*, its
         first three words filled in to be changed, with **OK** and **Cancel**. Taken, the row
         shows *Ignored next time* (✕ takes it back), and the rule is saved with the
         statement. A later statement's line a rule catches is shown, unticked and dimmed,
         with *Ignored (starts with "…")* and **Stop ignoring**, never dropped unseen. Profile
         lists each institution's ignored lines, each with **Remove**.
      5. **Several accounts in one statement** (a Schwab combined statement, a UMB statement
         with checking and savings): the statement is split where each account's part
         begins, at a header naming the account (*Account Number*, *Account ending*, an
         account's name followed by its number), and each part is read as a statement of its
         own. A part goes to the account whose last four digits (S1.1) its header shows, and
         to one the person chooses when none or several match; a part for an account
         MoolaKata doesn't hold can be left out. The parts are checked one after another in
         the same dialog, each against its own opening and closing balances, and nothing is
         saved until each part is saved or left out. The PDF is kept on each account it
         filled, once.
      6. **Kept without reading**: any statement can be kept on its account as it is, for the
         record, without its lines being read: a brokerage statement's trades (L1), a
         statement whose layout isn't read, or one the person only wants archived. MoolaKata
         reads its period and institution where it can (with statement reading off, the
         person types the period), for the person to check, and keeps the PDF on the account
         as a receipt (S9) named by its period (*UMB statement, Sep 1 – Sep 30, 2026*), as a
         read statement is kept. Its period is recorded as an import that adds nothing: it
         counts as the statement expected (S1.11.7) but not as coverage (S1.11.1), since its
         lines were never added. A statement whose lines can't be read is offered to be kept
         this way, and the same file isn't kept twice on an account. An account kept current
         from OFX or CSV is archived this way, its statements kept beside the imports that
         carry its activity.
      7. **Learned column positions** *(after the first release: [later work](later.md),
         L10)*, for layouts with no section headings and no running balance, where the sign
         of an amount comes from the column it is in (separate *Debits* and *Credits*
         columns):
         1. **Finding the columns**: on each page, the words of the lines that start with a
            date are grouped by where they sit across the page (their left and right edges
            in the PDF's text layer, or in the OCR's boxes), and the amounts fall into a few
            bands.
         2. **Naming them**: the check dialog shows the bands above the lines, each with a
            choice: *Date*, *Description*, *Debit* (money out), *Credit* (money in),
            *Amount* (signed), *Balance*, or *Ignore*. MoolaKata proposes names from the
            column headings it finds (*Withdrawals*, *Deposits*, *Debits*, *Credits*,
            *Balance*) and from the totals (debits and credits each adding up to a total the
            statement prints); the person corrects them, and each line's sign follows from
            the column its amount is in.
         3. **Learning them**: the named bands are kept with what is learned per institution
            (S1.3.3.4), as positions relative to the page's width, so the next statement
            from that institution is read by column with no naming, and a band that has
            moved (a new layout) is asked about again.
         4. **Order of the signs**: a running balance, then an explicit sign, then a learned
            column, then the section heading, then the words.
      8. **Brokerage and plan statements**: a Schwab, Fidelity or Vanguard brokerage
         statement, or a 401(k) or other plan statement (Empower's layout), read from a PDF's
         text layer only; a photo or scan of one is kept without reading (S1.3.3.6), since
         its tables don't survive OCR reliably. The layouts ship as rules for where each
         section begins, and what a person corrects is learned per institution as for banks
         (S1.3.3.4). Three parts are read, each checked in the same dialog:
         1. **The summary**: the starting and ending value, deposits, withdrawals, income
            and the change in value. The **ending value** becomes a balance anchor on the
            period's last day (S1.11), or a balance snapshot for an account kept by
            snapshots (R3.2). Being cash and holdings together, it is checked on the
            *Reconcile* tab against what the account was worth that day, at that day's
            prices, within half a percent or $1, whichever is more, apart from the cash
            anchors. An account kept by snapshots is one with no trades of its own (S1.3.2),
            however it is kept current.
         2. **The positions** on the last day: symbol (or CUSIP, or a fund's name),
            quantity, price and market value, a row split over two lines read as one. They
            become a **holdings check** at that date: each is matched to what MoolaKata
            holds, and a quantity that differs is shown with the difference, as an anchor
            shows a cash difference (a missed split, a dropped reinvestment). For an account
            kept by snapshots, they are its holdings on that date; for any account they are
            kept, as a file's are (S1.3.2), once per day: the same statement again adds
            nothing, and a figure corrected replaces the one kept. A cost basis on the
            statement is shown beside the lots' and never written over them. A difference
            that the statement's own trade lines account for is pointed at (*the Sep 24
            reinvestment of 5.1120 isn't entered yet*). The cash or sweep line is checked
            against the account's cash and becomes a cash anchor. The latest check shows on
            the *Reconcile* tab, worked out again as transactions are entered.
         3. **The cash activity**: deposits, withdrawals, dividends, interest and fees,
            checked against the summary's figures as bank lines are against their balances,
            for an account with no OFX, CSV or Connection to carry it. Lines already in the
            account are shown as such and never added again (S1.3.3.3), so a statement read
            beside its OFX adds nothing twice; a line left out can be remembered, as a bank
            statement's can (S1.3.3.4). Lines that don't add up
            to the summary's figures are flagged, not refused: a line may not have been read.

         **Not read**: trades (buys and sells), options activity, corporate actions and
         margin detail. Each shows as a line left out, *not read*; a trade offers *enter it
         as a trade*, with its figures filled into the trade dialog (S3) when chosen, and the
         rest are entered by hand (L1).
   4. **bitcoin watch** (self-custody wallets): balances and transactions read by address or
      xpub (S1.6);
   5. **the MoolaKata Connector**: files fetched from the institution by the connector's
      driver for a Connection the owner set up, and imported as an upload would be (S18).

   No bank-aggregation service is used: the user brings the files ([rejected ideas](rejected-ideas.md)).
4. **Retirement accounts** also carry: the **contribution year** of each contribution (a
   contribution made 2027-03-01 may be for 2026), employer match and vesting for a 401(k), and
   the account holder's **birth year** (from the profile) for limits and RMDs. Contribution
   limits per year are a table shipped with the app and updated with it, which an admin can
   correct in Settings (S8.6).
5. **Crypto exchanges** (Coinbase, Kraken and the like) are kept current from their CSV
   exports and statements, one import mapping per exchange. Reading an exchange through its
   API comes later ([out of scope](out-of-scope.md)).
6. **Self-custody wallets** hold **bitcoin**. Other coins and chains come later ([out of scope](out-of-scope.md)).
   1. **What the account holds**: addresses, an **xpub/ypub/zpub**, or an **output
      descriptor**, from which addresses are derived (with a gap limit of 20 unused addresses
      by default). Where a choice isn't settled here, MoolaKata does as Sparrow does, so a
      wallet exported from Sparrow derives the same addresses.
      1. An xpub's addresses are legacy (1…), a ypub's nested segwit (3…) and a zpub's
         native segwit (bc1q…), on the receive chain (0/i) and the change chain (1/i).
         Addresses typed are checked: legacy, script (3…), native segwit and taproot (bc1p…).
         Mainnet only: a testnet key or address is refused.
      2. Each chain is derived until the gap limit (1 to 200) of addresses in a row past the
         last used one are unused; when the explorer or node finds one used, more are
         derived, at most ten rounds in one check, so a long-used wallet fills in over a few
         hourly checks. The account's Settings lists the addresses watched, by chain and
         index.
      3. Taking a key or address out of the list stops watching its addresses.
      4. **Descriptors**, as Sparrow, Nunchuk and Bitcoin Core export them: single-key
         `pkh()`, `sh(wpkh())`, `wpkh()` and `tr()` (taproot, BIP 86), and multisig
         `wsh(sortedmulti(k, …))` and `wsh(multi(k, …))` of at most 15 keys, each key with
         its origin (`[fingerprint/path]xpub…`) and a `/0/*` and `/1/*` or `/<0;1>/*`
         ending. The descriptor's checksum is checked when it has one. A multisig wallet's
         addresses are derived from all its keys, and only its public keys are ever held.
         Other forms (`sh(wsh(…))`, a taproot descriptor with scripts) are refused, saying
         so. Miniscript policies beyond these come after the first release
         ([later work](later.md), L11).
   2. **Where balances and history come from**, set by an admin in Settings › Bitcoin:
      1. a **public explorer** with the Esplora API (mempool.space suggested, or Blockstream).
         No wallet is read until an admin saves Settings › Bitcoin (R3.5), and until then a
         wallet says it waits for that;
      2. **the household's own node**: its own mempool or Esplora instance, an **Electrum
         server** (Fulcrum, electrs), or **Bitcoin Core** over RPC with a watch-only
         descriptor wallet. An own node keeps the household's addresses private, and is
         recommended. Its address is named by the admin, so the egress guard (S13.5) lets
         MoolaKata reach it on the LAN; its credentials are a secret (S14.4).
      3. **How each is read.** Esplora: each address's transactions over HTTPS, with every
         input's previous output, so each transaction's effect on the wallet is known. An
         Electrum server: each address's history by its script hash over TCP (TLS by default),
         and the raw transactions, read by MoolaKata; its certificate is trusted on first use
         (below). Bitcoin
         Core over JSON-RPC: a watch-only descriptor wallet for each wallet account
         (`moolakata-<account id>`), its keys imported as descriptors over the addresses
         derived, rescanned from the start the first time, then its transactions listed. Only
         public keys and addresses are ever sent.
      4. **An Electrum server's certificate** is trusted on first use: **Test** in Settings ›
         Bitcoin shows its SHA-256 fingerprint, an admin confirms it, and it is kept. A server
         that later presents another certificate is refused, and admins alerted (*the node's
         certificate changed*), until an admin confirms the new one, as Sparrow does. Until
         one is confirmed, the server is only tested, never read.
      5. **When**: every hour, and at once with the wallet's **Check now**. **Test** in
         Settings › Bitcoin asks the saved explorer or node for the chain's height. A failure
         lasting past the alert threshold alerts admins and each wallet's owner (S12.11); its
         message never names an address or an amount.
      6. **What is recorded**: each transaction once, by its txid, once it has **6
         confirmations** (about an hour); until then it waits. A transaction its owner
         deleted is not recorded again. Bitcoin received is a **transfer in** of BTC
         without a basis, to be entered (Taxes lists it as missing) unless it is matched
         to a transfer out of another of the owner's accounts (S1.7.1);
         bitcoin sent is a **transfer out** of what left for others, and its network fee a
         sale of the fee's sats at that day's price beside a fee of the same amount, so the
         cash is unchanged (S8.19). In a transaction others put inputs into too (a coinjoin),
         the wallet's share of the fee is at most what it put in less what came back to it,
         never the whole transaction's, and the memo says it is a share; a fee recorded before bitcoin has a price is valued at the
         next check. A transfer out that was a sale or a payment is changed to one by its
         owner. The first
         coins held start a price refresh, so the wallet is valued at once.
      7. **A reorganised chain**: a recorded transaction that the explorer or node no longer
         has is never deleted silently. Once two reads in a row miss it, it is marked *no
         longer on the chain* and the owner alerted, to keep or delete it; a transaction kept
         stays kept.
   3. The form **refuses anything that looks like a private key or seed phrase** (WIF, 64
      hex digits, 12 or 24 BIP-39 words, an extended private key such as an xprv), says why,
      and never stores or logs it. The browser clears it from the form as it is typed, before
      anything is sent; the server checks again and its refusal never repeats it.
   4. **Amounts in sats.** Bitcoin is counted in whole **sats** (100,000,000 to the bitcoin),
      as bitcoin itself counts: never a fraction of a sat. A wallet's balance is sent as an
      integer of sats (S13.8.2), exact in every client since no amount of bitcoin reaches
      2^53 sats; a transaction's or a lot's quantity is kept as an exact decimal of bitcoin
      with 8 places (S14.3), the same whole number of sats. Each user chooses in Profile
      whether they are shown as **BTC** (`0.12345678 BTC`, the default) or **sats**
      (`12,345,678 sats`);
      the conversion is only in how they are shown. A price is per bitcoin, in dollars.
7. **Transfers** between two of a user's accounts are matched (same amount, a few days apart),
   so they count neither as spending nor as income, nor as a buy or sell of cash. Opposite
   amounts of cash, not trades, in two of the owner's accounts within 4 days of each other
   are linked as a transfer, the closest in date; when two are equally close, neither is,
   and the owner links one by hand. Cash taken out of a bank account pairs this way with
   its deposit in a `cash` account, and money sent to a payment app with its arrival there.
   1. **Bitcoin moved between the owner's accounts** (a wallet and an exchange, or two
      wallets): a transfer out and a transfer in of the same amount less the network fee,
      within 3 days, are **proposed** as a pair, on each account's Overview, and the owner
      confirms or rejects it; a rejected pair isn't proposed again. Once
      confirmed, the coins arrive with the **lots they left with**: their basis and the day
      each was acquired carry over, the fee aside (S8.19), so nothing is missing a basis and
      nothing is taxed. A transfer in left unmatched stays missing its basis (S8.4).
   2. **In a budget**, a transfer between one of its accounts and one it doesn't count is
      money leaving or entering it, and counts by its category (S7.3.2).
8. **529 plans.** A `529` account holds funds and cash like a brokerage account, plus:
   1. **The plan**: its state and name, the **beneficiary** (a person, S10.10), the
      opening date, and the state tax deduction the owner expects per year (typed: state
      rules are not modelled, S8.18).
   2. **Contributions** record who contributed (the owner, or a named relative), so gifts to
      the beneficiary can be totalled per contributor per year against the **annual gift
      exclusion** (in the tax tables, S16.11). A **five-year election** (superfunding)
      spreads one contribution over five years of exclusions and is shown that way.
   3. **Withdrawals** are matched with **qualified expenses** (tuition and fees, room and
      board, books, a computer, K-12 tuition, apprenticeships, student-loan repayment), each
      with its receipts (S9). Each year shows distributions (from Form 1099-Q) against the
      qualified expenses, and the part not covered, whose earnings may be taxable (S8.10).
   4. **Rollover to a Roth IRA**: once the account has been open 15 years, it shows how much
      could still roll over to the beneficiary's Roth IRA under the lifetime limit (in the
      tax tables), excluding contributions of the last five years.
   5. **The Goal tab** shows the beneficiary's education projection (S6.2.2).
   6. A 529 counts in its **owner's** net worth, not the beneficiary's.
9. **Loans and mortgages.** A loan account carries its **terms**:
   1. **Terms**: the original principal, the start date, the term (months), the interest
      rate, fixed or adjustable (an ARM's adjustment dates, caps and the rate after each
      reset, typed when known), the interest method (monthly amortization, or simple
      interest accrued daily, as most car loans use), the scheduled payment, and for a
      mortgage **escrow** (property tax, insurance) and **PMI**. A HELOC has a draw period
      with interest-only payments, then a repayment period. The term is 1 to 600 months, and
      the rate 0% to 40%, to three decimal places as a note states it (6.875%); a reset's
      rate takes four, as an index plus a margin can give (7.3125%).
   2. **The amortization schedule** is computed from the terms: each payment's interest,
      principal, escrow and remaining balance. It is recomputed when a payment differs
      from the schedule, the rate resets, or the loan is **recast**. Interest is rounded half
      up to the cent, and a balance of less than $1 left by rounding goes with the last
      payment.
   3. **Payments**: a payment transaction from a bank account (matched as a transfer, S1.7) is
      **split** into principal, interest, escrow, PMI and fees by the schedule, as is every
      payment into the loan however it arrives (imported, or typed in the loan's account): one
      with no split of its own is split by the schedule whenever the loan's figures are
      worked out, never counted wholly as principal. The user can
      correct a split from the servicer's statement. Principal beyond the schedule is
      recorded as an **overpayment**. Bank transactions of the last 90 days within 2% of the
      payment, not yet a transfer and not filed under another category, are offered on the
      loan's screen to link as its payments. A payment recorded or linked there is saved
      whole: the loan's transaction, its split and the bank account's half of the transfer
      together (S12.15).
   4. **Reconciling**: the servicer's statement balance can be typed in on a date, and a
      difference from the computed balance is shown until it is explained (a fee, a missed
      payment, a wrong rate).
   5. **The loan's screen** shows the balance, the rate, the payoff date, interest paid to
      date and still to pay, principal paid this year, the schedule, and the **payoff
      planner** (S6.10). A mortgage linked to a `real-estate` item shows the **equity** and the
      **loan-to-value**, and when PMI can be dropped (on request at 80% of the original
      value; automatically at 78%, when the schedule stops charging it).
   6. **Taxes**: mortgage interest, points and PMI (Form 1098), and student-loan interest
      (Form 1098-E) appear in Taxes (S8.12).
   7. **In budgets**, a payment counts at the bank account it came from (S7.3.3), as the loan
      says:
      1. **Split** (the default): by the schedule's split, interest, escrow, and PMI and fees
         each in its category, and principal, an overpayment with it, in a savings category
         (S7.2.1). The loan names the categories; by default they are the shipped *Loan
         payments › Interest*, *Escrow*, *PMI and fees* and *Principal*, so a plan line on
         the parent counts the whole payment. When the schedule is worked out again (a rate
         reset, a recast, a corrected split), the budget's months follow it.
      2. **Whole**: the full payment in the one category the loan names.
10. **Physical assets.** A physical-asset account (`precious-metals`, `collectables`,
    `real-estate`, `vehicle`, `other-asset`) holds **items**:
    1. **Every item has** a name, a category, a description, the **date acquired**, how it
       was acquired (bought, a gift, inherited), the **cost basis** (price plus premium,
       fees, shipping and improvements; a gift's carried-over basis; an inherited item's
       value at death), the quantity, where it is kept, a serial or certificate number, its
       condition or grade, the insured value and policy, **notes** (Markdown), and photos
       and documents (purchase receipt, appraisal, certificate, title), stored as receipts
       (S9).
    2. **Valuation**, one of:
       1. **spot**, for precious metals: the item's **fine weight** (weight per unit, in troy
          ounces, grams or kilograms, times purity, such as .9999, .925 or 22k, times
          quantity) times the metal's spot price (S4.3), adjusted by the premium or discount
          the user expects when selling (0% by default);
       2. **valuations**: dated values with their source (appraisal, recent sale, price
          guide, estimate), the latest one counting. A valuation older than 12 months is
          marked stale;
       3. **depreciation**, for vehicles: a yearly percentage from the purchase price, until a
          valuation replaces it.
    3. **Precious metals** are summarised by metal (gold, silver, platinum, palladium): fine
       ounces held, average cost per ounce, value at spot, and gain. Forms: coin, bar, round
       and jewellery. A numismatic coin worth more than its metal is a collectable instead.
    4. **Real estate** keeps the address (optional), purchase price and closing costs,
       **improvements** (each added to the basis with its receipts), valuations, whether it
       is the **primary residence**, and the loans secured by it (S1.9.5).
    5. **Selling** an item records the date, proceeds and fees, and realizes a gain or loss,
       flagged on Form 8949 as a **collectable** where it is one (metals included), which the
       tax tables tax at the collectables rate. A loss on personal-use property (a car, a
       home) is shown as not deductible (S8.13).
    6. **An account's chart** is its items' total value over time. The Items tab lists the
       items with cost basis, value, gain and age, and opens each one with its history,
       notes and documents.
11. **Reconciliation** keeps an account's balance in step with the institution's, for every
    account kept from files or statements: banking, cards, brokerage cash, and the retirement,
    plan, 529, HSA, DAF and exchange accounts whose statements S1.11.7 expects, each on its
    *Reconcile* tab. A loan is checked on its Overview instead, against the balance its servicer
    reports (S1.9.4), and its overdue statement leads there. For
    a user who only imports files it is a set of quiet, automatic checks; ticking off
    transactions by hand is an option.
    1. **Coverage**: each import records the dates it covers. The account's *Reconcile* tab
       shows a timeline of covered and uncovered periods, and flags a **gap** (*nothing
       between Aug 3 and Aug 14*) and an **overlap**.
    2. **Balance anchors**: a balance the institution reported, on a date, from (in order of
       preference) a CSV's **running-balance column** (every row is then an anchor, a day's
       balance being its last row's; a newest-first file, told by its dates, or by its running
       balances when they are all one day, is read from the bottom up), an OFX file's ledger
       balance, a statement's closing balance (S1.3.3), or a balance the
       user **types** from the institution's site. When an account's next statement or
       import is overdue (S1.11.7), it asks for one.
    3. **The check**: at each anchor, MoolaKata's balance for that day is compared with the
       anchor. A match stays quiet. A **mismatch** shows the difference, the window between
       the last matching anchor and this one, and what is suspect inside it: likely
       duplicates, amounts that changed between imports, and coverage gaps. With a
       running-balance column, it names the first row where the balances part.
    4. **Resolving** a mismatch: import the missing file, remove a duplicate, correct a
       transaction, or accept the difference as a **balance adjustment** with a note, which
       shows as such in the account and in Activity. An account with an open mismatch is
       marked in Accounts, and raises an alert after 7 days (S12.11).
    5. **Duplicate suspects** are flagged, never merged silently: two identical rows on one
       day, or two rows a file gave the same id, ask *both real?* the first time, and the
       answer is kept.
    6. **Ticking off** (optional, for accounts kept by hand): pick a statement's closing date
       and balance, tick transactions as cleared until the difference is zero, and the period
       is marked **reconciled**. Editing a transaction inside a reconciled period asks first.
    7. **Statements expected**: each account kept current by imports has the interval
       its institution issues them at, set in the account's settings:
       1. **Monthly, quarterly, yearly or none.** The default follows the account's type:
          monthly for banking, cards, brokerage, crypto exchanges, IRAs, HSAs and loans;
          quarterly for 401(k), 403(b), 457(b) and 529 plans and donor-advised funds; none for
          `cash` accounts and other accounts kept by hand, watched wallets and physical assets.
       2. **Learned**: once an account has three statements or imports, MoolaKata works out
          the interval they arrive at (the typical gap between the ends of what they cover;
          files downloaded more often than every 20 days teach nothing) and, where it differs
          from the one in force, proposes it in
          the account's settings (*Statements seem to arrive quarterly*); the owner accepts or
          dismisses it, and a dismissed proposal isn't made again for that interval.
       3. **Overdue**: a statement is overdue once the interval has passed since the last one
          ended, plus a grace period (15 days for monthly, 30 for quarterly, 60 for yearly),
          so a monthly statement ending Aug 31 is overdue from Oct 15. The alert (S12.11) names
          the statement missing (*the September statement*, *the July–September statement*,
          *the 2026 statement*), and clears when one covering it arrives, read or kept. An
          interval of none never alerts, nor does an account with nothing imported yet.
