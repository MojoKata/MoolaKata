# S5. Portfolios and charts

1. **A portfolio** is a named set of accounts, owned by a user and shareable like an account
   (S10). A portfolio may include an account shared with its owner at `read`.
   1. **Viewers see only the accounts in it that are shared with them.** The others are
      hidden, and left out of every figure, chart and holding the viewer sees, so the
      portfolio's value is the value of what they can see. This holds across a link too.
   2. **Sharing a portfolio** whose accounts are not all shared with the people chosen: the
      Share dialog names the accounts each of them can't see and offers **Share these
      accounts too** (at read, and only for accounts the owner may share). Declining keeps
      them hidden from those people.
   3. A portfolio never includes an account from a linked server: linked data is shown only
      in its own window (S12.10).
2. **Charts each portfolio has:**
   1. **Value over time** (line or area; 1M, 3M, YTD, 1Y, 5Y, All, and a range brush), with
      contributions shown apart from growth, against a **benchmark** (SPY, VT, a 60/40 mix).
      A contribution is money that came in or left from outside, valued as the chart values
      it that day: cash, shares moved in or out, an item added or sold (at what its sale
      brought), a loan's opening balance and its draws; a move between two of the portfolio's
      accounts is none;
   2. **Performance**: time-weighted and money-weighted (IRR) returns per period, per account
      and per portfolio;
   3. **Holdings**: what the portfolio holds, by account and by instrument, with each loan
      (what is still owed) and each item (what it is worth, S1.10) on a row of its own; its
      total is the portfolio's value. A weight is a share of what is held, cash and items
      included; a loan takes none.

   A portfolio of chosen holdings, allocation against a target with its drift and rebalancing,
   income by month, and a holding's price chart with its trades come later ([later
   work](later.md), L5).
3. **Net worth** on the Dashboard: assets minus liabilities over time, with the composition
   stacked by account group.
4. **Charts are drawn in the browser** from series the server computes (`GET
   /ui/api/portfolios/{id}/series?metric=value&range=1Y`). The server does the money
   arithmetic and the browser only draws.
