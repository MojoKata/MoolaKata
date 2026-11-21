# S1.11. Reconciliation

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
       day (the same amount, holding and payee, the payee's case aside, or the bank's words
       when there is no payee), or two rows a file gave the same id, ask *both real?* the
       first time, and the answer is kept.
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
