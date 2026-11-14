# Account: Reconcile

Keeps the account's balance in step with the institution's. For files you import, it is a set of
quiet checks; ticking off is there when you want it.

![An account's Reconcile tab](shots/account-reconcile.png)

When the next statement or import is overdue, import it, or type today's balance from the
institution's site.

## Coverage

The periods your imports cover. A **gap** is a stretch nothing was imported for; an **overlap** is
two imports covering the same days, whose shared rows were matched, not doubled.

## Type Today's Balance

Copy the balance from the institution's site. MoolaKata compares it with its own for that day.

## Tick Off against a Statement

Enter a statement's closing date and balance, then tick transactions as cleared until the difference
is zero. The period is then reconciled, and editing a transaction inside it asks first.

## Balance Checks

Every balance the institution reported (an OFX file's balance, a CSV's balance column, a statement,
or a typed one), next to MoolaKata's for the same day. While the opening balance is worked out
from the earliest one reported, standing in for history before the first import, it is marked
**opening balance stand-in**.

## Mismatch

When they differ, the window between the last matching balance and this one is searched for what's
suspect: identical rows on one day, amounts that changed between imports, gaps, and the first row
where a CSV's running balance parts from MoolaKata's: check the transactions around that row.

## Possible duplicate

Two identical rows on one day. **Both Are Real** keeps both and remembers it; otherwise delete one
from Transactions.

## Accept as an Adjustment

Records the difference as a balance adjustment with a note, shown as such in the account and in
Activity.

## Statement Values {#value-checks}

A brokerage statement's ending value against what MoolaKata says the account was worth that day:
cash and holdings at that day's prices. Within half a percent counts as a match.

## Holdings check {#holdings-check}

The positions of the latest brokerage statement or broker's file against what MoolaKata holds
that day. A quantity that differs is shown with the difference: a missed split, a reinvestment
or a buy not entered yet. Positions never change the lots; a transaction does.
