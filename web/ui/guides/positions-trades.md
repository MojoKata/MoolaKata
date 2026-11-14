# Positions: Option Trades

Each option trade from its first contract opened to its last one closed, with what it made.

![Option trades](shots/positions-trades.png)

## Show

All positions, or only stocks and funds, options, or crypto. Option trades are listed whichever
is chosen.

## Option Trades

Each contract in each account: long or short and the most contracts open at once, when it was
opened and closed and how (sold, bought back, expired, assigned or exercised), the premium
received and paid (fees included), and the P/L. A trade still open shows the P/L if it were
closed at its current mark. An assigned or exercised option's premium is also folded into the
shares' basis or proceeds; here it is counted once, as the option's.

## Capital Required {#capital-required}

What the trade tied up, and the return on it. A long option requires its premium. A short one
requires the strike on every share its contracts cover: the cash to buy them for a put, the
shares to deliver for a call. A leg of a strategy takes its strategy's capital at risk at open
instead, where that is finite. Capital at risk is another figure: what a position can lose
(the account's and the strategies'), *unlimited* for an uncovered call.
