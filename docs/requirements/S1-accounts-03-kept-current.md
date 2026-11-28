# S1.3. How an account is kept current

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
      exchange's or a wallet's file a coin ([G#576](https://github.com/MojoKata/MoolaKata/issues/576): correcting one). Imports are idempotent: a
      re-imported file adds only what is new, matched by the file's transaction id (an OFX
      file's `FITID`) or by date, amount and payee, amounts compared in cents as stored. A row
      whose id isn't here yet still matches, by date, amount and payee, a row that has none (one
      typed by hand, or from a file without ids), which takes the id; failing that, a half of a
      transfer typed by hand (a loan payment recorded from the account, a move to savings) of
      the same amount within S1.7's days, the closest, and none when two are as close. Rows the owner deleted are
      matched too, and stay deleted: no file, nor the connector's overlapping downloads, brings
      one back. An id a file repeats is another row, kept beside the first and flagged with it
      as a duplicate suspect (S1.11.5). A loan's payment or draw dated before the loan starts
      is left out and kept on the import, as S1.9.3 says. An OFX file holds one account's statement: one with
      several is refused, asking for one account at a time. A broker's file's positions are a
      **holdings check** on the statement's day (its as-of, whatever day their prices are from),
      as a statement's are (S1.3.3.8.2): the lots change only through transactions. Every file's
      positions are kept, dated, once per day: the same file again adds nothing, and figures
      that differ replace the ones kept. They are the holdings of an account kept by snapshots
      (R3.2), one with no trades of its own (nothing that makes or takes away a lot: a buy, a
      sale, a reinvestment, shares moved in or out, a trade of options; income, fees and splits on
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
      2. **Reading** uses the receipt reader's worker (S9.8.4), page by page as a receipt is
         read (S9.8.2.1): a page's text layer when it has one, else OCR of the page, one at a
         time, up to 30 scanned pages within five minutes (a receipt's three pages and one
         minute are too few for a statement). Settings ›
         Imports can turn statement reading off.
      3. **Checking**: the period, both balances and each line can be corrected, and a line
         left out. A line already in the account (the same date and amount, each transaction
         there answering for one line) is shown ticked, *duplicate*, and can't be
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
         record, without its lines being read: a brokerage statement's trades ([F#557](https://github.com/MojoKata/MoolaKata/issues/557)), a
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
      7. **Learned column positions** *(after the first release: [F#565](https://github.com/MojoKata/MoolaKata/issues/565))*, for layouts with no section headings and no running balance, where the sign
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
         rest are entered by hand ([F#557](https://github.com/MojoKata/MoolaKata/issues/557)).
   4. **bitcoin watch** (self-custody wallets): balances and transactions read by address or
      xpub (S1.6);
   5. **the MoolaKata Connector**: files fetched from the institution by the connector's
      driver for a Connection the owner set up, and imported as an upload would be (S18).

   No bank-aggregation service is used: the user brings the files ([rejected ideas](rejected-ideas.md)).
