# Check a brokerage statement

A brokerage or plan statement's PDF, read from its text layer: its summary, its positions on the
last day and its cash activity, checked here before anything is saved. A photo or scan isn't read,
since its tables don't survive OCR reliably: keep it on the account instead.

## Summary {#summary}

The starting and ending value, deposits, withdrawals, income and the change in value. The ending
value becomes a balance anchor on the last day, checked on the Reconcile tab against what the
account was worth that day, cash and holdings at that day's prices.

## Positions {#positions}

Each holding the statement shows, against what MoolaKata holds that day. A difference is shown,
and pointed at the statement's own trade lines when they account for it (a reinvestment or a buy
not entered yet). The statement's cost basis is kept beside the lots' and never written over them.
For an account kept by snapshots (one with no trades of its own, however it is kept current), the
positions become its holdings on that date. The same statement again adds nothing. The cash or sweep line is checked against the account's
cash, and becomes a cash anchor.

## Cash activity {#cash-activity}

Deposits, withdrawals, dividends, interest and fees, each kept as a transaction when ticked. A line
already in the account (its OFX brought it) is ticked, counted and never added again. A line you
untick offers **Remember…**, as a bank statement's does, to ignore lines like it from then on. When
the lines read don't add up to the summary's figures, a line may not have been read: check them.

Trades, options activity, corporate actions and margin lines aren't read. A trade opens the trade
dialog with its figures filled in; the others are entered by hand.
