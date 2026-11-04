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
   2. **What it does**: `quotes(instruments) → {instrument: (price, as_of)}`, `history(
      instrument, start, end) → daily closes`, and, where it can, `lookup(symbol)` to check a
      symbol before it is used.
   3. **Settings › Prices** lists the enabled sources, each with its classes, its key
      (*set*, with when and by whom; a key is a secret, S14.4), its order of preference per
      class, its last run and its last error. **Add a source** picks from every source
      MoolaKata ships. A source that needs a key can't be enabled without one.
3. **Starting sources**, chosen for being free and daily. Their terms change, so each is
   checked again when a release ships.

   | Need | Source | Key | Notes |
   | --- | --- | --- | --- |
   | US stocks and ETFs, benchmarks (VT, SPY) | **CBOE delayed quotes** | none | anything listed on an exchange: daily closes back to 2010 for a backfill, and the day's close from the quote once the market has closed (4:15 PM Eastern); a symbol it doesn't list goes to the next source. Not an official API, for personal, non-commercial use |
   | Fallback for stocks and ETFs | **Tiingo** | free | 500 symbols a month, 50 requests an hour, 1,000 a day; for personal use |
   | Mutual funds | **Tiingo** | free | daily NAVs, posted around midnight Eastern; CBOE doesn't list them |
   | Money-market funds | none | — | held at $1.00, shown as such |
   | Crypto, major coins | **Coinbase** public prices | none | |
   | Crypto, other coins | **manual** | — | a typed price, with its date; a source for them comes later (L9) |
   | Gold spot | **PAXG** (a token backed by one troy ounce of gold), from Coinbase | none | tracks spot closely; a proxy |
   | Silver, platinum and palladium spot | **SLV**, **PPLT** and **PALL** from CBOE (or Tiingo), divided by each fund's metal per share | free | the metal per share ships with the tax tables (S16.11) and is updated with them; within a fraction of a percent of spot |
   | Options | **CBOE delayed quotes** | none | the JSON behind cboe.com's quote pages: an underlying's whole chain in one answer, 15 minutes delayed, read after the close. Not an official API: CBOE offers it for personal, non-commercial use and may change it, so Settings says so |
   | Options, fallback | **Massive** (formerly Polygon.io), Basic plan | free | end-of-day prices and two years of history; 5 calls a minute, each page of a result counting as one |
   | Treasuries, I bonds and EE bonds | **manual** | — | a value typed from TreasuryDirect's published figures, with its date; a source for the Treasury's yield curve and savings-bond rates comes later (L3) |
   | No free ticker: 529 portfolios, 401(k) collective trusts, individual corporate and municipal bonds | **manual** | — | a value from a statement or an import, or a typed price, with its date. A statement value older than 90 days is marked stale and raises an alert (S12.11) |

4. **Schedule**: once a day, after the US market close (6:00 PM Eastern by default), a
   background task loads the day's close for every **held or watched** instrument (watched:
   the underlying of an open option, or an adjusted contract's deliverable parts, whether or
   not the account holds it, from the option's first trade, so its expiry has a close to decide
   it, S3.6), and backfills history when an instrument is first held, from a week before its first
   transaction and at most five years back. SPY, VT and BND are always loaded, as the
   benchmarks (S5.2.1). **Refresh prices** does the same on demand. Requests are spread to
   stay inside each source's limits (Tiingo's 50 an hour means a few hours for a large
   household). A source that fails falls back to the next one
   for that class; Settings shows the last error, and a failure lasting past the alert
   threshold raises an alert (S12.11). Intraday quotes are not fetched.
5. **Option marks**: the day's close from the source that serves options, else manual or
   intrinsic value (S3.7). A close older than the last trading day is marked stale.
   An option is named by its OCC ticker (`O:MSFT261120P00480000`: underlying, expiry, put or
   call, and the strike in thousandths).
   1. **CBOE** is asked for each underlying's chain once a day, after the close, and every
      held contract on it is marked from that one answer: at the middle of its bid and ask,
      rounded to the cent, or at its last trade when it has no two-sided quote. The mark is
      dated by the underlying's last trade, so a chain read on a holiday adds nothing new.
   2. **Index options** are in their index's chain (`_SPX`), where weeklies and PM-settled
      contracts carry their own root: an SPX contract is looked for as SPX and then SPXW,
      and likewise NDX and NDXP, RUT and RUTW, VIX and VIXW.
   3. **Massive** is asked for one contract at a time, with its history. A typed mark is a price on the
   option's instrument, entered from the open position (**Type a mark**). Intrinsic value is
   the underlying's latest close past the strike, never below zero. The Open tab labels a
   mark that is typed or intrinsic. Greeks
   are out of scope ([out of scope](out-of-scope.md)).
6. **Stored prices** are kept: daily closes for ever.
   Charts read stored prices only, never a price source during a request.
7. **Every price carries its source and `as_of`.** The UI shows *delayed* or *as of 4:00 PM*
   on every value derived from it. A price older than a threshold (2 trading days for a
   stock) is marked stale.
8. **US dollars only**: every account, holding, price and total is in USD. Prices are fetched
   in USD, including crypto and metals spot. An instrument that trades only in another
   currency is priced by hand.
9. **Linked servers never call price sources for each other.** A peer's shared data carries its
   own values and their `as_of` (S11.5).
10. **A typed price** is its typer's: it values their own accounts, and another user's only
    when they type one too. It is for an instrument held or watched (S4.4) in an account the
    typer can change: a holding, or the underlying of an option traded there. Where an instrument has no stored close, a holding is valued from
    the viewer's own trades in it, never from another user's.
