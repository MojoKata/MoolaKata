# New account: details

## Name

What it's called in your lists.

## Institution

The bank, broker or plan administrator.

## Last 4 {#mask}

The last four digits of the account number.

## Plan state {#plan-state}

A 529's sponsoring state, which may not be yours.

## Plan name {#plan-name}

my529, Bright Start, and so on.

## Beneficiary

Who a 529 is for: one of the household's people, or **Add a person…**.

## Their name {#new-name}

The new person's name.

## Sex {#new-sex}

The new person's: it chooses the words for the family tree, such as daughter or son.

## Year of birth {#new-birth-year}

Their year of birth, for when school starts.

## Opened {#opened-on}

The day it was opened: a Roth IRA rollover is possible 15 years on.

## State tax deduction a year {#state-deduction}

What you expect to deduct on your state return each year, typed.

## Extended public keys or addresses {#wallet-keys}

A self-custody wallet's public data: an **xpub**, **ypub** or **zpub** (exported from the wallet
as its account's extended public key), or bitcoin addresses, one a line. From a key, MoolaKata
derives the wallet's receive and change addresses itself.

> Never enter a seed phrase or a private key. The form clears anything that looks like one (12
> or 24 words, a WIF or 64-hex private key, an xprv) at once, and MoolaKata never stores or
> logs it.

## Gap limit

How many unused addresses past the last used one are derived and watched on each chain. 20 suits
most wallets; raise it for one that skipped addresses.

## Keep it current by {#kept-by}

**Imports**: files and statements you import, or the connector fetches; statements are then
expected. Or **Manual**: typed by hand. Whether its positions are its holdings is told by its
trades, not by this.

## Lot method

Which lots a sale takes; FIFO, the oldest first, unless you choose otherwise.

## Opening balance

Optional. Without it, the first balance an imported file reports stands in.

## Opening balance date {#opening-date}

The day the opening balance applies to.

## Original principal

A loan's amount borrowed, from the closing disclosure or the loan agreement.

## Start date

The day the loan was made; the first payment is due a month later.

## Term (months) {#term-months}

In months: 360 for a 30-year mortgage, 60 for a five-year car loan.

## Interest rate

The note rate, not the APR, to three places as the note states it (6.875%). An adjustable
rate's resets, to four places, are typed when known.

## Interest method

Most mortgages amortize monthly. Most car loans charge simple interest daily.

## Scheduled payment

Principal and interest per payment. Blank: computed from the terms.

## Escrow for property tax {#escrow-tax}

A mortgage's property tax collected with each payment.

## Escrow for insurance {#escrow-insurance}

Homeowner's insurance collected with each payment.

## PMI per month {#pmi}

Mortgage insurance, until it can be dropped.

## Secured by {#secured-by}

The property or vehicle the loan is secured by, from a physical-asset account. The Overview then
shows your equity in it and the loan-to-value.

## Home's original value {#original-value}

The appraisal or price when the loan was made. PMI can be dropped on request once the balance is 80%
of it, and ends by itself at 78%.

## Draw period (months) {#draw-months}

A HELOC's months of interest-only drawing before repayment.

## In budgets {#in-budgets}

How its payments count in budgets, at the bank account each comes from. **Split by the schedule**
puts interest, escrow, PMI and fees each in its category and principal in a savings category, all
under _Loan payments_, so a plan line on _Loan payments_ counts the whole payment. **The whole
payment** counts it all in one category.

## Counts in {#budget-category}

The category the whole payment counts in: _Loan payments_ unless you choose another.
