# Later work

Work planned for after the first release (S17.9.11), with what is already known about it. Each
item has a lasting id (L1, L2, …), kept as gaps' and questions' are. When an item is taken up,
it is specified in its section and removed from here; its id is never used again. The
[README](README.md#later-work) lists them.

## L1: Reading a brokerage statement's trades

**What it is:** reading the trades (buys and sells) on a brokerage statement, its options activity and its corporate actions (splits, mergers, spin-offs). A misread quantity or price would corrupt lots and gains, so this waits until the summary, positions and cash activity (S1.3.3.8) have proven themselves; until then each such line is shown as not read, with its figures offered to the trade dialog.

**Touches:** S1.3.3.8, S3.

## L2: Other option price sources

**What it is:** CBOE's delayed quotes (S4.5) aren't an official API and could change or close. The alternatives, each to be tried before it is relied on:

- **Schwab Trader API** (official, free with a Schwab account): real-time chains and marks; its sign-in token lasts seven days, so it belongs in a driver of the MoolaKata Connector (S18), not the server.
- **MarketData.app** (official, a free key with a daily request limit): chains and end-of-day quotes.
- **Massive** (formerly Polygon.io), Basic plan: shipped as the fallback (S4.3) but not yet tried with a live key: its limits, its history for expired contracts.
- **Tradier** (official, free with an account): delayed chains.

**Touches:** S4.3, S4.5, S18.

## L3: Treasury yields and savings-bond rates

**What it is:** a price source for Treasuries, I bonds and EE bonds from the Treasury's published
yield curve and savings-bond rates (free official data), with its host named in the egress
guard (S13.5). Until then they are priced by hand (S4.3), from TreasuryDirect's figures.

**Touches:** S4.3, S13.5, S16.6.

## L4: A user's export of their own data

**What it is:** a user exports their own data (accounts, transactions, lots, receipts) as a ZIP
of CSVs and files, at any time: the way out, and the backup a single user can keep. Built as a
job that streams the ZIP to the response, receipts decrypted on the way and never written to a
temporary file, after the password again (S13.7.2).

**Touches:** S14.8, S13.7.2.

## L5: Portfolio charts beyond value, returns and holdings

**What it is:** a portfolio of chosen holdings of its accounts; **allocation** (donut and
treemap) by asset class, account type (taxable, deferred, free), sector, region and single
holding, against an optional **target allocation**, with the drift and a rebalancing suggestion
(what to buy or sell, preferring the tax-advantaged accounts); **income**: dividends and
interest by month, trailing twelve months, and forecast; and a **holding's detail**: a price
chart (line, or candles from daily OHLC where available) with the user's buys and sells marked.

**Touches:** S5.1, S5.2, S4.

## L6: More of a linked household's window

**What it is:** in a linked household's window (S12.10), positions with their gains and option
trades, a loan's view with its payoff plans, and a physical-asset account's items; and a tax
book's document files crossing a link with Include receipts (S11.5.1).

**Touches:** S11.3.1, S11.5.1, S12.10.3.4.

## L7: Limits checked in projections and giving

**What it is:** a projection's contributions to retirement accounts capped by the limits of
S1.4, and a qualified charitable distribution checked for the giver's age (70½), the year's
limit and that it came from an IRA (S7.9.3), both from the tax tables (S16.11).

**Touches:** S6.1.2, S7.9.3.

## L8: `Idempotency-Key` on every create

**What it is:** every `POST` that creates honours `Idempotency-Key`, a repeat within 24 hours
returning the first answer, as `POST /ui/api/transactions` does (S13.8.8).

**Touches:** S13.8.8.

## L9: More price sources

**What it is:** **Alpha Vantage** (free key, 25 requests a day) as the last fallback for stocks
and ETFs, and **CoinGecko** (Demo plan, about 10,000 calls a month, attribution shown in
Settings and on the charts that use it) for coins Coinbase doesn't list. Until then such coins
are priced by hand (S4.3).

**Touches:** S4.3, S13.5, S16.6.

## L10: Learned column positions for statements

**What it is:** reading a bank or card statement with no section headings and no running
balance, where an amount's sign comes from the column it is in (*Debits* and *Credits*): the
columns are found by where the amounts sit across the page, named once in the check dialog,
and learned per institution, as S1.3.3.7 describes. Until then such a line's sign comes from
an explicit sign where it has one, else from its words, marked as guessed (S1.3.3.1).

**Touches:** S1.3.3.1, S1.3.3.4, S1.3.3.7.

## L11: Miniscript wallet policies

**What it is:** watching bitcoin wallets whose descriptors are miniscript policies beyond the
single-key and multisig forms of S1.6.1.4: spending conditions inside `wsh()` (a recovery key
that can spend after a timelock, a multisig whose threshold drops over time), as Liana and
Bitcoin Core export them, and taproot descriptors with script trees. Their addresses are
derived from the policy, and only public keys are held. Until then such a descriptor is
refused, saying so.

**Touches:** S1.6.1.4.

## L12: Who paid in a household budget

**What it is:** in a budget a group shares (S7.1), each member's share of its costs (equal,
by income, or set per category), who paid what from their own accounts, and who owes whom at
the month's end, with the settling transfer paired like any other (S1.7). Until then a group
budget counts every transaction in its accounts, whoever paid.

**Touches:** S7.1, S7.3, S10.3.
