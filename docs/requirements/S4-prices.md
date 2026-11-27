# S4. Prices

1. **What prices must be**: **free** for a household to use, and **daily**. An end-of-day
   close is enough, and a delay of hours is fine: MoolaKata is not a trading app and fetches
   no intraday quotes. A source that needs a paid plan can be added (S4.2), but none is
   required.
2. **Price sources are integrations behind one interface, `TickerSource`.** Each is one module
   in `prices/` that registers itself, so adding a source is adding a module.
   1. **What a source declares**: its name, the instrument classes it serves, whether it
      needs an **API key** (and where to get a free one), its rate limits, and the terms it
      was written against, with the date.
   2. **What it does**: `quotes(instruments) → {instrument: (price, as_of)}` and `history(
      instrument, start, end) → daily closes`, or an answer that it doesn't list the symbol.
      A symbol is checked by the daily refresh (S4.4), with whichever sources the server has:
      a held instrument with no stored close that every enabled source serving its class was
      asked for, and either didn't list or knew no close of, is recorded as one no price source
      knows. Its holding and its position say *No price source knows VTIX*, and Settings ›
      Prices lists it. Its first close clears it, as does a refresh that finds it no longer
      held or has no source to ask; a source that fails leaves it as it was. An option's ticker
      and a metal's proxy are MoolaKata's own and never recorded.
   3. **Settings › Prices** lists the enabled sources, each with its classes, its key
      (*set*, with when and by whom; a key is a secret, S14.4), its order of preference per
      class, its last run and its last error, and below them **Symbols No Source Knows**
      (S4.2.2): each symbol held in an account the admin can see, its class and since when,
      and how many more are held only in accounts they can't see, counted and never named
      (R1.6). **Add a source** picks from every source MoolaKata ships. A source that needs a
      key can't be enabled without one. A new server enables no source (R3.5): the welcome
      offers the ones that need no key, each off until the admin turns it on (S12.14.1). Until
      a source that fetches is enabled, nothing is priced: the header's price status reads
      *No Price Source*, its tip saying an admin adds one in Settings › Prices, and for an
      admin it links there (S12.5); a benchmark chart says it has no prices yet (S5.2.1).
3. **Starting sources**, chosen for being free and daily. Their terms change, so each is
   checked again when a release ships.

   | Need | Source | Key | Notes |
   | --- | --- | --- | --- |
   | US stocks and ETFs, benchmarks (VT, SPY) | **CBOE delayed quotes** | none | anything listed on an exchange: daily closes back to 2010 for a backfill, and the day's close from the quote once the market has closed (4:15 PM Eastern); a symbol it doesn't list goes to the next source. Not an official API, for personal, non-commercial use |
   | Fallback for stocks and ETFs | **Tiingo** | free | 500 symbols a month, 50 requests an hour, 1,000 a day; for personal use |
   | Mutual funds | **Tiingo** | free | daily NAVs, posted around midnight Eastern; CBOE doesn't list them |
   | Money-market funds | none | — | held at $1.00, shown as such |
   | Crypto, major coins | **Coinbase** public prices | none | |
   | Crypto, other coins | **manual** | — | a typed price, with its date; a source for them comes later ([F#564](https://github.com/MojoKata/MoolaKata/issues/564)) |
   | Gold spot | **PAXG** (a token backed by one troy ounce of gold), from Coinbase | none | tracks spot closely; a proxy |
   | Silver, platinum and palladium spot | **SLV**, **PPLT** and **PALL** from CBOE (or Tiingo), divided by each fund's metal per share | free | the metal per share ships with the tax tables (S16.11) and is updated with them; within a fraction of a percent of spot |
   | Options | **CBOE delayed quotes** | none | the JSON behind cboe.com's quote pages: an underlying's whole chain in one answer, 15 minutes delayed, read after the close. Not an official API: CBOE offers it for personal, non-commercial use and may change it, so Settings says so |
   | Options, fallback | **Massive** (formerly Polygon.io), Basic plan | free | end-of-day prices and two years of history; 5 calls a minute, each page of a result counting as one |
   | Treasuries, I bonds and EE bonds | **manual** | — | a value typed from TreasuryDirect's published figures, with its date; a source for the Treasury's yield curve and savings-bond rates comes later ([F#559](https://github.com/MojoKata/MoolaKata/issues/559)) |
   | No free ticker: 529 portfolios, 401(k) collective trusts, individual corporate and municipal bonds | **manual** | — | a value from a statement or an import, or a typed price, with its date. A statement's value is marked stale once the statement after it is overdue (S1.11.7.3), or a year and 60 days on in an account that expects none, and raises an alert (S12.11) unless that overdue statement's own alert is up: it is for statements that arrive without valuing the holding |

4. **Schedule**: once a day, after the US market close (6:00 PM Eastern by default), a
   background task loads the day's close for every **held or watched** instrument (watched:
   the underlying of an open option, or an adjusted contract's deliverable parts, whether or
   not the account holds it, from the option's first trade, so its expiry has a close to decide
   it, S3.6), and backfills history when an instrument is first held, from a week before its first
   transaction and at most five years back. SPY, VT and BND are loaded as the benchmarks
   (S5.2.1), held or not, once a source that serves them is enabled. **Refresh prices** does the same on demand. Requests are spread to
   stay inside each source's limits (Tiingo's 50 an hour means a few hours for a large
   household): a refresh that would wait more than five minutes on a source's limits sets that
   source aside for the rest of it, tries the next one for that class, and runs again once the
   limits allow, picking up what was left. A source that fails falls back to the next one
   for that class; Settings shows the last error, and a failure lasting past the alert
   threshold raises an alert (S12.11). Intraday quotes are not fetched.
5. **Option marks**: the day's close from the source that serves options, else manual or
   intrinsic value (S3.7). Other option sources come later ([F#558](https://github.com/MojoKata/MoolaKata/issues/558)). A close older than the last trading day is marked stale.
   An option is named by its OCC ticker, as S2.1 has it (`MSFT  261120P00480000`: the root
   padded to six characters, expiry, put or call, and the strike in thousandths).
   1. **CBOE** is asked for each underlying's chain once a day, after the close, and every
      held contract on it is marked from that one answer: at the middle of its bid and ask,
      rounded to the cent, or at its last trade when it has no two-sided quote. The mark is
      dated by the underlying's last trade, so a chain read on a holiday adds nothing new.
   2. **Index options** are in their index's chain (`_SPX`), where weeklies and PM-settled
      contracts carry their own root: an SPX contract is looked for as SPX and then SPXW,
      and likewise NDX and NDXP, RUT and RUTW, VIX and VIXW.
   3. **Massive** is asked for one contract at a time, with its history, by its OCC ticker in
      Massive's own form: `O:` before it and the root unpadded (`O:MSFT261120P00480000`).
   4. **Without a close**, from any source: a typed mark, a price on the option's instrument
      entered from the open position (**Type a Mark**); failing that, its intrinsic value, the
      underlying's latest close past the strike, never below zero. The Open tab labels a mark
      that is typed or intrinsic. Greeks are out of scope
      ([NO#588](https://github.com/MojoKata/MoolaKata/issues/588)).
6. **Stored prices** are kept: daily closes for ever, each from a source that fetches (a
   price typed is the typer's own, S4.10, never a stored close).
   Charts read stored prices only, never a price source during a request.
7. **Every price carries its source and `as_of`.** The UI shows *delayed* or *as of 4:00 PM*
   on every value derived from it. A price older than a threshold (2 trading days for a
   stock) is marked stale, and so is one taken from a trade (S4.10), dated by its trade, by
   the same threshold.
8. **US dollars only**: every account, holding, price and total is in USD. Prices are fetched
   in USD, including crypto and metals spot. An instrument that trades only in another
   currency is priced by hand.
9. **Linked servers never call price sources for each other.** A peer's shared data carries its
   own stored closes, with their dates, for what its shared accounts hold or watch and for each
   shared portfolio's benchmark from the earliest day of its accounts, and the owner's typed
   prices for what those accounts hold (S11.3.1).
10. **A typed price** is its typer's: it values their own accounts, and another user's only
    when they type one too. It is for an instrument held or watched (S4.4) in an account the
    typer can change: a holding, or the underlying of an option traded there. Where an instrument has no stored close, a holding is valued from
    the viewer's own trades in it, never from another user's.
