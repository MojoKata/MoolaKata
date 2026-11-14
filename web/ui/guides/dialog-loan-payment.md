# Record a payment

A payment on the loan, split by its schedule.

## Paid on {#paid-on}

The day the servicer received it.

## Amount

What was paid, escrow included. Anything beyond the scheduled payment goes to principal as an
overpayment.

## From account {#from-account}

The bank account it came from: its half of the transfer is recorded as well, or, when that account
already holds the payment (imported first), paired with it rather than recorded again. **None**
records it on the loan only: for a payment from an account MoolaKata doesn't hold, or one already
in a bank account, which **Looks like a Payment** then offers to pair.

## Show the Split

How the schedule splits this amount on this day.

## The split {#split}

Principal, interest, escrow, PMI and fees. Correct a part from the servicer's statement when it
differs; the parts must add up to the amount.
