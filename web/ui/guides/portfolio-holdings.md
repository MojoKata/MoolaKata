# Portfolio: Holdings

What the portfolio's accounts hold, added up by instrument, with each loan and item on a row of
its own. The total is the portfolio's value.

![A portfolio's Holdings](shots/portfolio-holdings.png)

## Weight

Each holding's share of what the portfolio holds: cash, holdings and items. What a loan owes takes
no weight.

## Loans and items

A loan's row is what is still owed on it, which counts against the total; an item's, what it is
worth, from its valuations, spot or depreciation.

## Cost basis

What you paid for what you hold, fees included.

## Stale

A price older than it should be: two trading days for a stock, or 90 days for a typed price.

## Options · capital at risk {#capital-at-risk}

The options' market value in these accounts, and what they put at risk: the most each strategy can lose at expiry, and
each option on its own counted the same way, as a strategy of its shape: a long option its premium,
a short put its strike less its premium, a short call the account's shares cover as a covered
call, and an uncovered one *unlimited*.
