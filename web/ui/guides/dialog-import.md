# Import Transactions

An OFX, QFX or CSV file from your bank or broker, or a **statement**: its PDF, or a photo or scan of
it. Rows already imported are matched by the file's own transaction id, or by date, amount and
payee, so importing the same file again adds nothing; a row you deleted stays deleted. Notes a CSV
writes below its rows, after a blank line (a disclaimer, the time it was downloaded), are left
out.

A statement is read on this server, and shown for you to check before anything is saved.

A statement of several accounts, such as a combined checking and savings statement, is split
where each account's part begins, and each part is checked in turn.

## Into account

The account the file belongs to.

## File

The file you downloaded from your bank or broker, or a statement's PDF or photo.

## Keep a Statement without Reading It {#keep-without-reading}

Keeps a statement on its account as it is, for the record: one from an account kept current from
OFX, a brokerage statement, or one whose lines can't be read. Only its period is asked for.

## Which Columns Are Which?

Asked for a CSV from an institution the first time: check the columns MoolaKata guessed. What you
choose is saved for the next file from it.

## Date column {#map-date}

The column with each row's date: the posting or trade date.

## Description column {#map-payee}

The payee, merchant or description.

## Amount column {#map-amount}

One column with money in as + and money out as −.

## Debit column {#map-debit}

When money out has its own column instead.

## Credit column {#map-credit}

When money in has its own column.

## Running balance column {#map-balance}

Optional: every row's balance is then checked against MoolaKata's.

## Memo column {#map-memo}

Optional.

## Transaction id column {#map-id}

Optional: the institution's own id for each row, which makes re-imports exact.

## Action column {#map-action}

For an investing or crypto account's trade history: what each row is, a buy, a sale, a dividend,
a transfer. A buy's cash goes out and a sale's comes in, whatever sign the file writes.

## Symbol column {#map-symbol}

The ticker, fund symbol or coin each row trades. A five-letter symbol ending in X is taken for a
mutual fund, any other ticker for a listed share; in an exchange's file, a coin.

## Quantity column {#map-quantity}

How many shares or coins.

## Price column {#map-price}

Optional: the price per share or coin.

## Fees column {#map-fees}

Optional: commission, fees or spread.

## Date format {#map-date-format}

As the file writes its dates:

| Written as  | Format     |
| ----------- | ---------- |
| 10/12/2026  | `%m/%d/%Y` |
| 2026-10-12  | `%Y-%m-%d` |
| 10/12/26    | `%m/%d/%y` |
| 12-Oct-2026 | `%d-%b-%Y` |

## Spending is positive {#map-negate}

Card exports often show purchases as positive amounts: this flips them.
