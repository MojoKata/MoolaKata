# S1.9. Loans and mortgages

9. **Loans and mortgages.** A loan account carries its **terms**:
   1. **Terms**: the original principal, the start date, the term (months), the interest
      rate, fixed or adjustable (an ARM's adjustment dates and the rate after each reset,
      typed when known, from the servicer's notice or as an assumption, S6.10.6), the
      interest method (monthly amortization, or simple interest accrued daily, as most car
      loans use), the scheduled payment, and for a mortgage **escrow** (property tax,
      insurance), **PMI** and the **points** paid at closing: the amount, the day paid (by the
      first payment) and whether they bought the home or refinanced it, all three or none. A
      HELOC has a draw period with interest-only payments, then a repayment period. The
      original principal is more than 0, except a HELOC's, which may be 0 (**Min: $0.00**,
      R3.11), as a line of credit opened with nothing drawn is; escrow, PMI and points are
      each *none* while blank, and points typed are more than 0. The term is 1
      to 600 months, and the rate 0% to 40%, to three decimal places as a note states it
      (6.875%); a reset's rate takes four, as an index plus a margin can give (7.3125%).
   2. **The amortization schedule** is computed from the terms: each payment's interest,
      principal, escrow and remaining balance. It is recomputed when a payment differs
      from the schedule, the rate resets, or the loan is **recast**. Between the payment days
      that change it (the first after a rate reset, a recast, or a HELOC draw in its repayment
      period, a fee or charge added to what is owed being one, and a HELOC's first repayment
      day) the principal and interest due stays level; on such a day it becomes what pays off
      the balance then owed by the term's last payment day, that day counted. Interest, and
      the level principal and interest itself as a lender rounds it, are rounded half up to
      the cent, and a balance of less than $1 left by rounding goes with the last payment.
      Where payments are so small that their rounding adds up to a payment or more, the
      balance is paid off that many payments before the term's last day.
   3. **Payments**: a payment transaction from a bank account (matched as a transfer, S1.7) is
      **split** into principal, interest, escrow, PMI and fees by the schedule, as is every
      payment into the loan however it arrives (imported, or typed in the loan's account): one
      with no split of its own is split by the schedule whenever the loan's figures are
      worked out, never counted wholly as principal. The user can
      correct a split from the servicer's statement. Principal beyond the schedule is
      recorded as an **overpayment**. Bank transactions of the last 90 days within 2% of the
      payment, not yet a transfer and not filed under another category, are offered on the
      loan's screen to link as its payments. A transaction is the other half of a payment
      already recorded on the loan alone when S1.7 matches them (the same amount, days
      apart): it is offered to **pair** with that payment, which records nothing new; one
      within those days of an unpaired payment of another amount isn't offered. Recording a
      payment from a bank account that already holds its half pairs with it the same way. A payment recorded or linked there is saved
      whole: the loan's transaction, its split and the bank account's half of the transfer
      together (S12.15). A payment day that passes with no payment recorded is read by the
      loan's **Payments** setting (its Settings):
      1. **Recorded here**: every payment is recorded in MoolaKata from the first one recorded,
         so one not recorded 15 days after its day (a servicer's usual grace period) is
         **missed**; the payment days before that first one count as paid as scheduled (a loan
         entered years in has nothing missed before its record starts). The schedule shows
         the row as missed with what was due; the loan's screen says how many are missed and
         what is overdue (their payments: the interest of the missed months is owed with them,
         not added to the balance); the balance owed stays what it was, and the schedule ahead
         starts from the next payment day.
      2. **Assumed as scheduled**: the payments are made elsewhere and not all recorded, so a
         payment day with none recorded counts as paid as the schedule says. The balance
         follows the schedule, and nothing is missed.
      3. **Automatic** (the setting's default): *Recorded here* once the loan has a payment
         recorded (a bank payment linked to it is one) or a connection importing its
         statements; *Assumed as scheduled* until then. The screen names which applies.

      A payment goes with the payment day whose grace it is made in, from 15 days after one
      day to 15 days after the next; recorded here, a payment made after a missed day pays the
      oldest one missed first, as a servicer applies one. A payment day's interest, escrow and
      PMI are due once: a later payment toward the same day pays what the earlier ones left of
      them, and the rest is principal, an overpayment. A payment short of them pays the
      interest, then the escrow, then PMI, and no principal.
   4. **Reconciling**: the servicer's statement balance can be typed in on a date, and a
      difference from the computed balance is shown until it is explained (a fee, a missed
      payment, a wrong rate).
   5. **The loan's screen** shows the balance, the rate, the payment due next (the schedule's
      next row, which the payment dialog and the bank transactions offered read too; in a
      HELOC's draw period its interest alone, noted *interest only until* the period's end),
      the payoff date, interest paid to date and still to pay, principal paid this year, the
      schedule, and the **payoff
      planner** (S6.10). A mortgage linked to a `real-estate` item shows the **equity** and the
      **loan-to-value**, and when PMI can be dropped (on request at 80% of the original
      value; automatically at 78%, when the schedule stops charging it). The original value is
      the one typed, else the home's basis when the loan was made.
   6. **Taxes**: mortgage interest, points and PMI (Form 1098), and student-loan interest
      (Form 1098-E) appear in Taxes (S8.12). Points that bought the home show in the year
      paid (Form 1098's box 6); a refinance's are spread evenly over the term's payments, so
      each year shows the share of its payments, and the year the loan is paid off what is
      left.
   7. **In budgets**, a payment counts at the bank account it came from (S7.3.3), as the loan
      says:
      1. **Split** (the default): by the schedule's split, interest, escrow, and PMI and fees
         each in its category, and principal, an overpayment with it, in a savings category
         (S7.2.1). The loan names the categories; by default they are the shipped *Loan
         payments › Interest*, *Escrow*, *PMI and fees* and *Principal*, so a plan line on
         the parent counts the whole payment. When the schedule is worked out again (a rate
         reset, a recast, a corrected split), the budget's months follow it.
      2. **Whole**: the full payment in the one category the loan names.
