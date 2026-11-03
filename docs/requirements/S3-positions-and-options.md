# S3. Positions and options

1. **A position** is one instrument in one account. It is **open** while any lot is open,
   and **closed** when none is. The Positions screen lists open and closed positions with
   quantity, average cost, market value, unrealized gain or loss (amount and %), realized gain
   or loss, days held, and short- or long-term status per lot.
2. **Option transactions:** *buy to open*, *sell to open*, *buy to close*, *sell to close*,
   **expire** (worthless), **assigned** and **exercised**. Each carries contracts, premium per
   share, fees and commission.
   1. **From a broker's file**: an OFX file's option trades (`BUYOPT`, `SELLOPT`) are the four
      trades by their `OPTBUYTYPE` and `OPTSELLTYPE`, and its `CLOSUREOPT` is the option's
      end by its `OPTACTION`. A contract is named by its OCC ticker, or by the underlying,
      right, strike and expiry its `OPTINFO` gives. A CSV's option is read from its symbol
      (`AAPL  260918P00150000`, `AAPL 09/18/2026 150.00 P`, `-AAPL260918P150`), and its row
      must say whether it opens or closes (*Buy to Open*, *Sell to Close*) or how it ended
      (*Expired*, *Assigned*, *Exercised*): a plain buy or sell of an option refuses the file,
      naming the row.
   2. **An assignment or exercise in a file** is settled as one recorded by hand (S3.4), after
      the trades that opened it. The stock trade the broker lists with it (the one its
      `RELFITID` names, or a buy or sell of the underlying that day, of the contracts'
      shares) becomes the stock trade of S3.4, with the broker's cash and fees, so the shares
      aren't counted twice. One that can't be settled (the account holds none of the option,
      or its stock trade came with an earlier file) is named in the import's warnings, to be
      settled on Positions.
3. **Short options** are negative lots. The premium received is the credit; the gain is
   realized at close or expiry, and is short-term however long the option was open (IRC
   §1234(b)). Closing trades and expiries take an option's lots oldest first, whatever lot
   method the account uses for shares.
4. **Assignment and exercise** close the option lot and open or close stock lots at the strike,
   with the premium folded into the stock's basis or proceeds as the IRS rules for that case
   say: a long call exercised adds its premium to the stock's basis, a short put assigned
   subtracts its premium from it, a short call assigned adds its premium to the proceeds. The
   premium is worked out from the option's lots each time the account's figures are, so a
   corrected opening trade follows through. A call assigned, or a put exercised, with none of
   the shares held is a short sale at the strike: a short stock lot whose basis is what it
   brought in, closed by the shares bought later, its gain short-term. The resulting stock lots link back to the option,
   and deleting the assignment or exercise deletes its stock trade with it, after asking; the
   stock trade alone isn't deleted.
5. **Strategies**: legs held together (a covered call, a vertical spread, an iron condor)
   are grouped and shown as one. Grouping is a label: lots, gains, wash sales and taxes stay
   per leg.
   1. **Grouping is proposed, never forced.** Legs on one underlying opened in one account on
      the same day are offered as a strategy on the Positions screen (*Group as an iron
      condor?*), and a short call against 100 or more shares held, whenever they were
      bought, as a covered call. Legs can be grouped by hand (select them, **Group**) and a
      group undone at any time. A strategy's legs are in one account, on one underlying. A
      proposal turned down (*Not a strategy*) isn't made again.
   2. **Rolls**: a leg closed and another opened on the same underlying the same day is
      offered to stay in the group, or turned down. A strategy keeps its history (its legs,
      its rolls and its P/L from open to close, closed legs included); it opened when its
      first leg did, and closes when its last option leg does, however it ends: closed,
      expired, assigned or exercised.
   3. **The shapes recognised** (anything else is *Custom*): long call, long put, short call
      (naked), short put (*cash-secured* is the owner's tick); covered call, protective put,
      collar; bull and bear call spreads and put spreads; long and short straddles and
      strangles; iron condor, iron butterfly, butterfly; calendar and diagonal.
   4. **Figures**: cost or credit, mark, unrealized and realized P/L, **max profit**, **max
      loss** and **breakevens at expiry**, *unlimited* where it is, worked out from the payoff
      at each strike, at zero and beyond the highest, so a *Custom* strategy gets them too.
      Shares count at their value on the day the strategy opened. A calendar or diagonal
      shows its P/L only, as its outcome depends on volatility.
   5. **Capital at risk**, shown **now** and **at open**:

      | Strategy | Capital at risk |
      |---|---|
      | long options, debit spreads | the net premium paid |
      | credit spreads, iron condor and butterfly | the widest wing × multiplier × contracts, less the net credit |
      | cash-secured put | strike × multiplier × contracts, less the premium |
      | covered call, protective put, collar | the shares' market value, less the net premium |
      | naked call, short straddle and strangle | *unlimited*, or the broker's margin requirement the owner types |

      Each row is the strategy's max loss at expiry where that is finite, which is how a
      short put without the *cash-secured* tick, a long straddle or a butterfly are counted
      too; a calendar or diagonal risks its net debit, or the margin typed.
      *Now* uses today's prices; *at open* uses the legs the strategy opened with, as they
      were at the end of that day and at its prices, whatever is rolled or closed later, and
      is what a strategy's **return on capital at risk** is worked on. The shares' cost basis
      shows on their own leg. An unlimited risk counts as such: a total with one in it is
      *unlimited*, never the sum of the rest.
   6. **Where it shows**: Positions has a **Strategies** tab listing each strategy with its
      legs and these figures, and the proposals; an investing account and a portfolio show
      **Capital at risk** beside their options' market value, counting each option outside a
      strategy as a single leg (S3.9.2). Allocation charts keep market value.
6. **Expiry** is applied automatically the day after an option expires out of the money by the
   underlying's closing price. An in-the-money expiry asks the user what happened. The close
   used is the expiry day's, a price source's stored close: no one's typed price, statement
   value or trade decides it; without it, the user is asked too. A close exactly at the strike
   counts as out of the money.
7. **Valuation**: an open option's mark is the price source's daily option close where there is
   one (S4.5), otherwise the user's manual mark, otherwise intrinsic value, labelled as such.
8. **Wash sales**: a loss sale with a purchase of the same or a *substantially identical*
   instrument within 30 days either side is flagged, its disallowed loss computed and added to
   the replacement lot's basis. This covers the user's own accounts, IRAs included, and the
   accounts of the user's spouse on the date of the sale (S10.10.4). Options on the same
   underlying are flagged for review, not decided (S8.3).
   1. The match is the same instrument, a stock or fund (ETFs and mutual funds included),
      bought or reinvested within 30 days before or after a sale at a loss in a taxable
      account. Whether a different instrument is substantially identical is the preparer's
      call, and MoolaKata does not guess.
   2. Replacement shares are taken nearest the sale date first, each counted against one
      sale only, and the sold shares they replace in the order those were acquired, the
      earliest first (Treas. Reg. §1.1091-1(c)): the loss disallowed is that lot's, and its
      **W** goes on that lot's row of Form 8949, so a sale of a long-term and a short-term
      lot keeps each term's figure. The shares bought in the lot that was sold, and any
      shares the sale itself sold, are never its replacement.
      A partial replacement disallows the loss in proportion: 4 shares bought back of 10
      sold disallow 4/10 of the loss.
   3. The disallowed loss is taken off the sale's realized loss and added to the replacement
      shares' basis, and their holding period starts that many days earlier: the sold shares'
      days held carry over. Both take effect from the sale on: shares bought before it are a
      plain lot until then, so the sale never takes its lots by the loss it is about to have
      disallowed. Holdings, unrealized gain, the Closed tab (a **W** with the amount) and the
      later sale of those shares all use the adjusted basis and date. Where only some of a lot
      replaces, that part is split into its own lot. **A replacement in an IRA or a Roth IRA**
      is the exception: the loss is disallowed for good, with no basis added to the
      replacement (Rev. Rul. 2008-5).
   4. The household's wash sales are worked out again whenever a trade in it is added,
      changed, deleted or imported, so a later purchase that replaces an earlier loss, or a
      deleted one that no longer does, takes effect at once.
   5. **Flagged for review, never adjusted**: where the rules are unsettled or depend on
      facts MoolaKata can't see, a possible wash sale is listed among the tax book's issues
      (S8.3) with the trades involved, and no basis is changed:
      1. a loss on a **short sale** closed with shares bought within 30 days of another
         short sale of the same stock, or of opening one;
      2. a loss on an **option itself** (a call or put closed or expired at a loss) with the
         same option, or one on the same underlying, opened within 30 days either side;
      3. a loss on stock whose **replacement came through an option**: a put assigned to the
         user, or a call they exercised, within 30 days either side of the loss sale;
      4. a loss on stock with an **option on it bought or sold** within 30 days either side.

      The issue names the rule it may fall under and says the preparer decides.
9. **Gain/loss views**: realized by year, month, account, instrument and short- or long-term;
   unrealized now; and **per trade** for options (open date, close date, premium in and out,
   P/L, return on capital at risk).
   1. An option trade runs from the first contract opened in an account to the moment none
      is open. Premium in and out are the cash received and paid, fees included; a trade
      still open adds what it is worth at its current mark, as *if closed now*.
   2. **Capital at risk**: for a long option, the premium paid; for a short one, the strike
      on every share the most contracts open at once cover (the cash to buy them for a put,
      the shares to deliver for a call). The return is the P/L over it. A leg in a strategy
      takes its strategy's capital at risk at open instead (S3.5.5).
10. **Adjusted contracts**: when the underlying splits, merges, spins off a company or pays a
    large special dividend, the OCC adjusts its open options. The lot carries over to the
    adjusted contract: no sale, and no wash sale.
    1. **A whole-number split** (2:1, 4:1) is applied with the stock's split (S2.4), in the
       account the split is recorded or imported in: contracts × the ratio, strike ÷ the ratio
       rounded to the thousandth, as the OCC prints it, the basis spread over the new
       contracts. The old contract ends. Deleting the split undoes it. A reverse split, not a
       whole number, is adjusted as below.
    2. **Any other adjustment** gives the contract a new root (AAPL becomes *AAPL1*), keeps
       its strike, and changes its **deliverable**: shares other than 100 (150 for a 3:2
       split), shares and cash, or shares of two companies. Recording the corporate action
       asks for each open contract's new root, strike and deliverable, from the OCC's
       information memo (linked to its search), on Positions › Strategies (*An underlying was
       adjusted*); every account the user can change that holds the contract is adjusted.
       The multiplier stays 100: what changes is the deliverable.
    3. **On import**, an option named by its OCC ticker is made a contract. One whose root
       is adjusted (ending in a digit) links to the adjusted contract already here; while the
       account still holds the contract it adjusts, the import names it in a warning, to be
       adjusted from the memo so its lots carry over.
    4. **Assignment and exercise** of an adjusted contract open or close a lot for each
       instrument in its deliverable, and its cash goes into the proceeds or the basis. The
       strike paid or received, the premium and the cash are spread over the deliverable's
       parts by their market value that day (by their shares when a price is missing). On
       Option trades, the old contract's trade ends *adjusted* and the adjusted contract's
       continues on the same side.
    5. **Its mark** is CBOE's, which lists it under its new root in the underlying's chain
       (S4.5); without one, its intrinsic value is its deliverable's value less the strike
       × 100.
