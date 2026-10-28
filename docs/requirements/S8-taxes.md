# S8. Taxes

The Taxes screen gathers, for one **tax book** (one user or married couple, one tax year,
S8.14), what a preparer or tax software needs. It
produces worksheets and exports. It never files, and says so (R1.16).

1. **Realized gains and losses**: every sale and closed option in taxable accounts, as **Form
   8949** rows (description, acquired, sold, proceeds, cost basis, adjustment code and amount,
   gain or loss), split into short- and long-term and by the box that the broker's basis
   reporting determines, with **Schedule D** totals. Securities go in A, B or C (short-term)
   and D, E or F (long-term). From tax year 2025, digital assets have boxes of their own, and
   never C or F: G, H or I short-term and J, K or L long-term, for basis reported to the IRS on
   a Form 1099-DA, basis not reported, and no 1099-DA at all; a self-custody wallet's sales go
   in I or L. Years before 2025 put them in A to F. What a crypto account holds (an exchange's
   or a wallet's) is a digital asset, whether typed or imported. A written option's row has
   the premium received as its proceeds and what closing it cost as its basis, dated from its
   opening to its close; a row's acquired date is *VARIOUS* only when a snapshot stood in for
   the lot's history (R3.2). Sources: the [2025 Form
   8949](https://www.irs.gov/pub/irs-pdf/f8949.pdf) and [its
   instructions](https://www.irs.gov/pub/irs-pdf/i8949.pdf), kept in `docs/external/`.
2. **Exports**: Form 8949 CSV, **TXF** (which TurboTax and others import), and a PDF summary
   for a preparer. Each export says what it covers and what it does not. TXF (format V042)
   carries boxes A to F and the wash-sale adjustment only: a row with another code (C, L) or in
   a digital asset's box (G to L) is left out of it and entered from the CSV. A book with such
   rows counts them by why beside the TXF export (*TXF leaves out 4 sales (3 digital assets,
   1 collectable): enter them from the CSV.*).
3. **Wash sales** found (S3.8), with the disallowed amounts and the replacement lots, and
   the flags left for review.
4. **Missing or doubtful data**: lots without a basis, sales without a matching lot, options
   with an unresolved expiry, transfers between users' accounts (a gift's carry-over basis),
   crypto without a known acquisition, possible wash sales the rules leave to the
   preparer (S3.8.5), and edits made since the federal return was filed (S8.15).
5. **Income**: interest (1099-INT), dividends ordinary, qualified and capital-gain
   distributions (1099-DIV), foreign tax paid, and crypto income (staking, rewards) at fair
   value when received.
6. **Retirement**: contributions per account against the year's limits (with catch-up by
   age), Roth eligibility by MAGI as the user enters it, backdoor-Roth steps (non-deductible
   contribution, conversion, Form 8606 figures), distributions, and RMDs due.
7. **Deductions and credits**: totals of tax-tagged categories (S7.2) with their
   transactions and **receipts**. Charitable gifts above the substantiation threshold show
   whether a receipt is attached. Medical, childcare, education, HSA, and estimated tax
   payments by quarter.
8. **Documents checklist**: the 1099s, W-2s and statements expected for the year from the
   accounts held, each marked received (attach the PDF, S9) or missing (S8.16). A received 1099-B can
   be **reconciled** against MoolaKata's own totals, with the differences listed.
9. **Charitable giving** (S7.9): deductible donations by organisation and type (cash,
   goods, appreciated securities, DAF contributions; QCDs apart, since they are not
   deducted), each with its acknowledgement: a written acknowledgement is flagged as
   missing for any single gift of $250 or more, goods over $500 in a year note Form 8283,
   and an item over $5,000 notes that it needs an appraisal. Grants from a DAF and gifts to
   non-deductible organisations are listed apart, as not deductible.
10. **Education (529)** (S1.8): contributions per beneficiary and per contributor (with what
    the owner noted about the state deduction), distributions from Form 1099-Q against the
    qualified expenses and their receipts, and the part not covered, whose earnings may be
    taxable with a 10% additional tax. MoolaKata shows the figures. The preparer applies the
    rules, and the coordination with education credits.
11. **Gifts** (S7.8.7): each person who received more than the annual exclusion in the
    year, from cash gifts and 529 contributions, with the five-year 529 elections still
    running, as a prompt to file **Form 709**.
12. **Loans** (S1.9.6): mortgage interest, points, PMI and property tax paid through escrow
    (Form 1098) per property, and student-loan interest (Form 1098-E).
13. **Physical assets** (S1.10.5): sales of items, with collectables (metals included) marked
    on Form 8949 for the collectables rate, and losses on personal-use property shown as not
    deductible. A sold primary residence shows its gain and the years owned and lived in;
    the exclusion is the preparer's to apply.
14. **Tax books.** A tax book is the tax record of one **tax year** for one user, or for a
    married couple filing jointly. Each household member who files has their own, and a
    couple filing separately has two.
    1. **Filers**: one user, or two who are spouses (S10.10.4) on the last day of the year, or
       of whom one died during it. Creating a tax book names the year and the filers. A user
       named as a filer by someone else accepts before the tax book counts their accounts or
       shows anything from their year before.
    2. **Accounts counted**: the filers' own accounts, each counted once even when the filers
       share it with each other. A filer can add an account they can see (a custodial account
       in a child's name) or leave one out, and the panels say what was left out. An added
       account counts only while the filer who added it can still see it.
    3. **Helping**: the filers hold the tax book as its owners, and any of them changes its
       sharing. Anyone else sees it only through a share: to users and groups, or, read only,
       to named people on a linked server, such as a preparer with a server of their own
       (S10.3.3). A user who helps prepare the return, such as a grown child or a preparer with
       an account here, gets **write**: they can edit filings, attach documents and resolve
       issues, but not add accounts, delete the tax book or change its sharing.
    4. **New tax book** copies the filers, accounts and dependents from the year before, and
       turns last year's received documents into this year's expected ones (S8.16), once every
       filer of the new book has accepted it.
    5. **Dependents**: the people the filers claim for the year, chosen from the household's
       people (S10.10). MoolaKata doesn't decide who qualifies (S8.18); dependents feed the
       panels, the checklist and a few flags.
       1. **Each** has how they are claimed (*qualifying child* or *qualifying relative*,
          suggested from the family tree: a child or grandchild under 19, or under 24 and a
          student), the months they lived with the filers, a *full-time student* tick, and
          the accounts the book counts that are in their name (a custodial account).
       2. **One tax book a year**: a person claimed on two tax books for the same year is
          flagged on both, without saying whose the other is. A dependent can still have a tax
          book of their own, which notes that they are claimed on another.
       3. **What they feed**: each one's age on Dec 31 in Deductions and credits (S8.7),
          with who is under 17, who is under 13, and who ages out this year; a dependent
          student's 1098-T and 529 withdrawals in Education (S8.10); their expected documents
          in the checklist (S8.8), such as a student's 1098-T or, when childcare was paid for
          one under 13, a childcare provider's statement; and a dependent child's unearned
          income (interest, dividends and gains) in the accounts in their name flagged when it
          passes the year's threshold for Form 8615, from the tax tables (S16.11).
       4. **A new tax book** copies them a year older, and leaves out anyone past a
          qualifying child's age who isn't claimed as a relative, saying whom.
15. **Filings**: one per return: federal (Form 1040), a state's or a locality's. An
    **amended return** is a filing of its own that names the one it amends. Each filing has:
    1. the jurisdiction, the form, and the **filing status** as typed (MoolaKata never
       chooses it);
    2. who prepared it, and how it was sent (e-file or paper);
    3. its **progress** (not started, in progress, filed, accepted or rejected), the due date
       (federal from Settings › Tax tables, moved past a Saturday, a Sunday or a legal
       holiday, federal or the District of Columbia's Emancipation Day as observed, IRC
       §7503; others typed), an **extension** (date filed, new due date), the date filed,
       and the confirmation or submission number;
    4. the **result**: the refund or the amount owed, matched to the transaction that paid or
       received it, and any overpayment applied to the next year;
    5. the **estimated payments** for its jurisdiction, by quarter, matched to transactions
       (S8.7);
    6. its **documents** (S8.16.2): the forms as filed, and what the tax authority sent.

    A filing past its due date that is not filed and has no extension shows in the
    Dashboard's *Needs attention*.

    **Changed after filing.** An edit made anyway to a closed year (S2.8.3) is listed in the
    tax book's Issues (S8.4) and in the Dashboard's *Needs attention*, with how much the
    realized gains moved since the federal return was filed and in which accounts
    (*Realized gains changed by +$412.50 after the federal return was filed: Brokerage, 2
    edits*). It stays until a filer or a helper with write adds an amended federal return,
    which settles every change made before it, or chooses **No amendment needed**, which
    settles them with their name and the day. A later edit made anyway, once the year is
    closed again (S2.8.1), is listed afresh.
16. **Tax documents**: each has its form, who issued it, the account it is for, notes, and
    its file, which is kept as a receipt (S9) with the same storage and protection. One kept
    opens to change any of these, its file given later among them, or to remove it; a filer
    or a helper with write changes one another filer attached a file to.
    1. **Received**, kept in the tax book: W-2s, 1099s, 1098s, 1095s, K-1s, 5498s and
       property-tax bills. They make up the checklist of S8.8, expected from the accounts
       held and last year's documents, each received or missing.
    2. **Filed**, kept in a filing: the return as filed with its schedules, the e-file
       acknowledgement, an extension, the preparer's copy and worksheets, and what the tax
       authority sends, such as notices, letters, the reply and transcripts. MoolaKata
       doesn't produce these. It keeps them because next year's preparation often needs
       them.
17. **Carried forward**: on each filing, the figures next year needs, typed from the filed
    return: adjusted gross income (needed to sign next year's e-filed return), total tax, the
    refund or amount owed, the overpayment applied, capital-loss carryovers (short and long
    term), the Form 8606 basis, and charitable-contribution carryovers. The next tax book
    shows them under **From last year**. It also puts the capital-loss carryover in its
    Summary and the 8606 basis in the backdoor-Roth figures (S8.6), and shows last year's
    total tax beside the estimated payments.
18. **What MoolaKata does not do**: compute the tax owed, choose a filing status, apply state
    rules, or decide questions of judgement (substantially identical, cost-basis elections).
    It shows the numbers and their sources.
19. **Bitcoin network fees**: paying a network fee in bitcoin disposes of that bitcoin, and
    is recorded as a **sale** of the fee's sats at their market value that day, taken from
    the lots like any sale (by the account's lot method), its small gain or loss in the Form
    8949 rows. This is the common reading and the default; a tax book's settings (chosen with
    it, and changed later) can treat fees on transfers between the owner's own accounts as not
    taxed instead, for a preparer who reads it so: those sales leave Form 8949, their basis
    going with them. The exports say which was used.
