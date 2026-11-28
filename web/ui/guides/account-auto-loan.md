@@ overview

> A car loan: most charge simple interest daily, so paying early saves interest.

## Loan

What is owed, the rate, the payment (and with escrow), the next due date, the payoff date against
the original schedule, interest paid so far and still to pay, and principal paid this year.
**Overpaid** is principal paid beyond the schedule. **Missed**, with payments recorded here, is how
many payment days passed 15 days with no payment recorded, and what they were due.

## Record a Payment

A payment on the loan, split into principal, interest, escrow, PMI and fees by the schedule. From a
bank account, its half of the transfer is recorded too.

## Servicer's balance

The principal the servicer says is owed, typed from its statement. A difference from the schedule's
balance shows until it is explained: a fee, a missed payment, a wrong rate.

## Equity

When the loan is secured by a property or vehicle: what it's worth less every loan it secures, the
loan-to-value, and for a mortgage with PMI, when it can be dropped.

## Following

The payoff plan you're following (the Payoff tab), and whether what you've overpaid since you chose
it is ahead of the plan or behind.

## Looks like a Payment

Bank transactions of the last 90 days within 2% of the payment that aren't a transfer yet or filed under another category. **Link**
makes one the transfer into this loan, split by the schedule. When the loan already holds the
payment, recorded with *From account: None*, **Pair** makes the two one transfer and records
nothing new; a transaction a few days from a payment of another amount isn't offered, as it is most
likely that payment.

## Left Out of Imports

A payment or draw an import brought dated before the loan's start date is left out, since a loan
has none before it starts, and kept here with the file it came in. **Move the Start** opens the
terms: once the start date is on or before the rows, **Add Them** adds them, each checked again
against the start. **Leave Them Out** lets them go for good. Both need write on the loan; the alert
for them ends once they are added or left out.

## Documents {#documents}

The loan's documents other than its statements: a closing disclosure, the note, a payoff letter.
**Add Document** uploads files and keeps them with the loan, and **Attach from the inbox** keeps a
receipt already uploaded; × detaches one, back to the inbox. Each is kept while the loan is open,
and from the day it is paid off (closed) for as long as statements are kept (Settings › Storage).
Statements come by an import or the connector, and are listed with the account's receipts.

@@ settings

## Loan Terms

The terms give the schedule; saving them recomputes it.

## Original principal

What was borrowed, from the closing disclosure or the loan agreement: more than $0.

## Start date

The day the loan was made; the first payment is due a month later.

## Term (months) {#term-months}

In months: 360 for a 30-year mortgage, 60 for a five-year car loan.

## Interest rate

The note rate, not the APR, to three places as the note states it (6.875%).

## Interest method

Most mortgages amortize monthly. Most car loans charge simple interest daily, so paying early saves
interest.

## Scheduled payment

Principal and interest per payment. Blank: computed from the terms; type the servicer's figure if it
differs by a few cents.

## Secured by {#secured-by}

The property or vehicle the loan is secured by, from a physical-asset account. The Overview then
shows your equity in it and the loan-to-value.

## In budgets {#in-budgets}

How its payments count in budgets, at the bank account each comes from. **Split by the schedule**
puts each part of a payment in the category the loan names for it below: interest, escrow, PMI and
fees as spending, principal as saved. A new loan starts with the shipped ones under _Loan
payments_, so a plan line on _Loan payments_ counts the whole payment until one is changed. **The
whole payment** counts it all in one category; the parts' categories are kept for a return to the
split.

Only a mortgage has escrow and PMI: this loan keeps them in the shipped ones.

## Counts in {#budget-category}

The category the whole payment counts in. It can't be left blank: **default** fills in _Loan
payments_.

## Interest {#interest-category}

The category a payment's interest counts in, _Loan payments › Interest_ to start with. It can't be
left blank: **default** fills in that one.

## Fees {#fees-category}

The category a payment's fees count in, _Loan payments › Fees_ to start with. It can't be left
blank: **default** fills in that one.

## Principal {#principal-category}

The savings category a payment's principal counts in as saved, an overpayment with it:
_Loan payments › Principal_ to start with, or a savings category of your own. Only a savings
category can hold it, and it can't be left blank: **default** fills in _Loan payments ›
Principal_.

## New category…

At the end of the list: opens **New Category** over this dialog. The category it makes
is chosen here when you add it, and everyone sees it: the household has one tree of categories.

## Payments {#payments-mode}

How a payment day with no payment recorded reads. **Recorded here**: every payment is recorded in
MoolaKata from the first one, so one not recorded 15 days after its day is missed; the Overview says
how many and what is overdue, and the balance stays what it was. The days before the first payment
recorded count as paid as scheduled. **Assumed as scheduled**: the payments are made
elsewhere, so a day with none recorded counts as paid as the schedule says. **Automatic** is
recorded here once the loan has a payment recorded or a connection keeping it, and assumed until
then; it names which applies.

## Rate resets

An adjustable rate's new rate from each reset date, typed when known. The schedule from that date is
re-amortized at the new rate.

## Recasts

The servicer re-amortizes the balance over the rest of the term after a lump sum, for a fee: a lower
payment, the same payoff date.
