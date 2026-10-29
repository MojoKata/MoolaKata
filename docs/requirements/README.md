# MoolaKata: requirements

MoolaKata is a self-hosted **personal finance server** for a
household or a small group of people. It holds their accounts (bank, brokerage, crypto
exchange, self-custody wallets, IRA, Roth IRA, 401(k)), tracks holdings and positions (options
included), charts portfolios, projects future value, keeps budgets and receipts, and prepares
the numbers a tax return needs. Several people use one server. They share accounts and
portfolios with each other, read-only or read/write, and share read-only with people on
**other MoolaKata servers** on other LANs.

**How the requirements are organised.** This file holds what applies everywhere: the
decisions (R1), the terminology (R2) and the design principles (R3). Each subject has its own
section file, S1 to S18, listed below. A reference names a part by its id and number:
`R1.16` is item 16 of the decisions here, `S9.8.7` item 8.7 of the receipts section, `G8` a
gap, `L1` later work and `Q8` an open question.

1. **Lasting ids.** Section ids (S1, S2, …) and their first-level items (`S1.2`) are never
   renumbered or reused: a new section or first-level item takes the next free number, and
   one that is removed leaves its number unused. Deeper items may be renumbered, with every
   reference updated in the same change. Gaps (G), later work (L) and questions (Q) keep
   their ids the same way.
2. **Splitting a section.** A section file that grows past 500 lines moves its first-level
   items to files of their own, named by the item's number (`S1-accounts-02-brokerage.md`
   holds S1.2), and keeps a summary with a table of them in the form of the one below.
   References do not change.
3. **A statement, not a changelog.** The requirements say what MoolaKata is and does, in the
   present tense, and carry no dates, versions or status of their own; git holds their
   history, and the repository's README says where the build stands.

**Mockup:** [`../mockups/MoolaKata-mock.html`](../mockups/MoolaKata-mock.html) is the
clickable mockup. It is one file that opens from disk and sends nothing anywhere. It is
hand-written, and alongside it a second mockup is generated from the app for the screens built
so far (S12.9). Its purple **MOCK** pill jumps to any screen, switches between users, and
opens the dialogs.

## Sections

| Id | Section | What it covers |
|---|---|---|
| **S1** | [Accounts](S1-accounts.md) | Account types, how accounts are kept current (manual entry, CSV, OFX, statements, bitcoin watch), retirement, crypto, 529s, loans, physical assets, transfers and reconciliation |
| **S2** | [Holdings, lots and transactions](S2-holdings-and-lots.md) | Instruments, lots and their cost basis, corporate actions and payee rules |
| **S3** | [Positions and options](S3-positions-and-options.md) | Positions, option contracts and their lifecycle |
| **S4** | [Prices](S4-prices.md) | Free daily prices: the sources per asset class, the daily refresh, stored closes and staleness |
| **S5** | [Portfolios and charts](S5-portfolios-and-charts.md) | Portfolios across accounts, performance, allocation and the charts |
| **S6** | [Projections](S6-projections.md) | Goals (retirement, education, savings), assumptions, the models, scenarios, active plans and the loan payoff planner |
| **S7** | [Budgets, gifts and giving](S7-budgets-gifts-and-giving.md) | Budgets and categories, recurring transactions, people and occasions, gifts and charitable giving |
| **S8** | [Taxes](S8-taxes.md) | Tax books, tax documents, what a return needs, and the tax tables |
| **S9** | [Receipts](S9-receipts.md) | Upload, encrypted storage, viewing, links, sharing, retention and reading receipts on the server |
| **S10** | [Users, groups and sharing](S10-users-and-sharing.md) | Users, sign-in, groups, what can be shared and how, Activity and the MCP endpoint |
| **S11** | [Linked servers](S11-linked-servers.md) | Read-only sharing between households on separate MoolaKata servers |
| **S12** | [Web UI](S12-web-ui.md) | The frame, navigation, screens, help pane, live updates, linked households' windows and Alerts |
| **S13** | [Architecture](S13-architecture.md) | The listener and its modes, background tasks, the egress guard, the refused start, security policies and API conventions |
| **S14** | [Storage and secrets](S14-storage-and-secrets.md) | The database, files, secrets, backups, time zones and retention |
| **S15** | [Encryption and the master key](S15-encryption-and-master-key.md) | The master key and its recovery phrase, the data key, rotation and recovery, for the admin who runs the server |
| **S16** | [Settings (admins)](S16-settings.md) | Every section of the Settings screen |
| **S17** | [Implementation](S17-implementation.md) | The stack, the repository layout, checks, dev mode, the Docker images and where they are published, the milestones, CI and releases |
| **S18** | [MoolaKata Connector](S18-connector.md) | The second service that holds institutions' credentials, fetches with its drivers and pushes into MoolaKata's import |

## Gaps

Areas named but not yet specified ([gaps.md](gaps.md)), each ranked High, Med or Low.

| Id | Gap | Rank |
|---|---|---|
| **G23** | [Real receipt fixtures for the reader](gaps.md#g23-real-receipt-fixtures-for-the-reader--low) | Low |

A new gap takes the next id after G24.

## Open questions

What waits on a decision ([questions.md](questions.md)), each ranked High, Med or Low.

| Id | Question | Rank |
|---|---|---|
| **Q30** | [How the connector stores its secrets](questions.md#q30-how-the-connector-stores-its-secrets--low) | Low |

A new question takes the next id after Q30.

## Later work

Work planned for after the first release ([later.md](later.md), S17.9.11).

| Id | Item | What it is |
|---|---|---|
| **L1** | [Reading a brokerage statement's trades](later.md#l1-reading-a-brokerage-statements-trades) | buys and sells, options activity and corporate actions on a brokerage statement; until then each is offered to the trade dialog |
| **L2** | [Other option price sources](later.md#l2-other-option-price-sources) | Schwab Trader API through a connector driver, MarketData.app, Massive with a live key, Tradier |
| **L3** | [Treasury yields and savings-bond rates](later.md#l3-treasury-yields-and-savings-bond-rates) | a price source for Treasuries, I bonds and EE bonds from the Treasury's published data; until then they are priced by hand |
| **L4** | [A user's export of their own data](later.md#l4-a-users-export-of-their-own-data) | a ZIP of a user's accounts, transactions, lots and receipts, streamed, after the password again |
| **L5** | [Portfolio charts beyond value, returns and holdings](later.md#l5-portfolio-charts-beyond-value-returns-and-holdings) | chosen holdings, allocation with a target and rebalancing, income by month, a holding's price chart |
| **L6** | [More of a linked household's window](later.md#l6-more-of-a-linked-households-window) | positions with gains, loans, physical-asset items, and a tax book's files across a link |
| **L7** | [Limits checked in projections and giving](later.md#l7-limits-checked-in-projections-and-giving) | contribution caps in projections, and QCD age, limit and source checks |
| **L8** | [`Idempotency-Key` on every create](later.md#l8-idempotency-key-on-every-create) | beyond `POST /ui/api/transactions` |
| **L9** | [More price sources](later.md#l9-more-price-sources) | Alpha Vantage as the last stock fallback, CoinGecko for coins Coinbase doesn't list |
| **L10** | [Learned column positions for statements](later.md#l10-learned-column-positions-for-statements) | a statement's Debit and Credit columns found, named once and learned per institution; until then a sign comes from the line itself or its words |
| **L11** | [Miniscript wallet policies](later.md#l11-miniscript-wallet-policies) | timelocked recovery paths and decaying multisig in `wsh()`, and taproot script trees; until then refused |
| **L12** | [Who paid in a household budget](later.md#l12-who-paid-in-a-household-budget) | each member's share of a group budget's costs, who paid what, and who owes whom |

## Also here

- [Open questions](questions.md): what waits on a decision, listed above.
- [Later work](later.md): what comes after the first release.
- [Out of scope](out-of-scope.md): what MoolaKata does not do.
- [Rejected ideas](rejected-ideas.md): ideas weighed and turned down, with the reason.

# R1. Decisions

The rulings the rest of the requirements apply.

1. **The stack** (S17): a Python server (FastAPI under Hypercorn), SQLite through
   **SQLAlchemy** with **Alembic** migrations, and a browser app with **no build step** (Preact,
   HTM, @preact/signals, preact-iso, vendored and pinned, loaded as plain ES modules under a
   strict CSP). There is **no Node.js anywhere**. Deno type-checks and lints, and Playwright for
   Python runs the browser tests.
2. **A single-page app at `/ui`**, dark-mode first, in one frame: a collapsible
   sidebar, the signed-in user at its foot, the theme button, a DEV pill in dev mode and an
   update pill. It is built for desktop browsers. Phones will get a separate, focused PWA
   later, not the whole web app (S12.8, [out of scope](out-of-scope.md)).
3. **Context-sensitive help on every screen**: the F1 help pane, with one Markdown guide per
   screen or panel that follows the focused field (S12.7). A test fails when a field has
   no heading in its guide.
4. **A clickable mockup** in `docs/mockups/`, opened from disk. It shows every screen and
   dialog on sample data, and its MOCK pill drives it (S12.9).
5. **A dev mode, `moolakata dev`**, runs the whole server from a checkout as the current user.
   It uses a self-signed certificate, writes emails to a folder, uses canned price feeds and
   seed data, and keeps every rule as strict as production (S17.7).
6. **Users, groups, invitations, sign-up approval, two-step sign-in and deactivation** (S10.1).
   An admin's extra powers are managing users and groups and the server's Settings. **Admins
   are trusted operators**: the app keeps other users' money off their screens unless it is
   shared with them, but cannot keep out someone who holds the recovery phrase and the host
   (S10.2).
7. **Users own accounts.** Any user can create accounts and portfolios and share them with
   users or groups, **read** or **read/write** (S10).
8. **Linked servers.** Two MoolaKata servers on different LANs can be linked. A link carries
   **read-only** shares of any of the eight shareable kinds (S10.3), each to named people on
   the other server, both ways, and is never read/write (S11).
9. **Money is never a float.** Amounts and quantities are decimals end to end: `Decimal` in
   Python, exact number literals in JSON (S13.8.2.1), and integers or decimal text in SQLite
   (S14.3).
10. **Prices are delayed, never live.** MoolaKata is not a trading app. It reads end-of-day
    closes from free sources, through pluggable **price sources** (S4).
11. **Read-only by construction toward institutions.** MoolaKata never moves money, places an
    order or signs a transaction. It never stores a self-custody wallet's private key or seed
    phrase, only public addresses or extended public keys (S1.6).
12. **Receipts are files on the server**, PDF or image, uploaded from the browser and attached
    to transactions, tax items or nothing (S9).
13. **Everything the server stores is encrypted at rest**: the database
    (SQLCipher), the receipt files, and each secret on its own. All of it opens with one
    **master key**, which is a **12-word recovery phrase** that is never stored anywhere: a new
    server's welcome shows it once to its first admin, who writes it down, and after every
    start the server is locked until an admin enters the phrase, on its locked screen or on the
    host (S15.4). There is no key file, no separate keys process, and **no Vault
    or other external key service** (S15.2).
14. **Charts: Apache ECharts**, vendored and loaded only by the screens that draw charts
    (S17.4).
15. **The code lives in `web/`**: `web/ui` (the browser app) and `web/server` (the Python
    package `moolakata`). The docs are in `docs/` (S17.1).
16. **MoolaKata informs and does not advise.** Tax reports, projections and gain/loss figures
    are worksheets for the user or their preparer. They are not tax, legal or investment
    advice, and the screens say so where it matters (S8.18).
17. **Receipts are read on the server with RapidOCR**: open source, CPU
    only, models shipped with the app, run as a sandboxed background job. Results are
    suggestions the user confirms (S9.8).
18. **What a link brings in is kept apart and encrypted**. Each link's shared data lives in its own **linked copy**: a SQLCipher
    database plus one encrypted file per receipt, in a folder of its own, never in the main
    database. It opens with the copy's own **access key**, 12 generated words that the
    receiving household keeps in its password manager, never with the master key. The key
    protects the copy at rest; who sees what is decided by the owner's shares. The copy
    keeps syncing while it is locked, and its key is released after an hour unused (S11.9).
19. **Beyond investments**: MoolaKata also covers **529 plans** (S1.8),
    **mortgages and other loans** with payoff and overpayment projections (S1.9, S6.10),
    **physical assets** such as precious metals, collectables, property and vehicles, with
    notes, purchase dates and cost basis (S1.10), **gifts** to the people in a user's life
    for their birthdays, anniversaries and holidays (S7.7, S7.8), and **charitable giving**
    against a target set as a percentage of income (S7.9).
20. **Schema conventions**: tables are declared with SQLAlchemy Core,
    with no logic beside them, and mapped onto plain dataclasses (S14.1). Table names are
    singular and capitalized, field names camelCase, and primary keys a short prefix plus a
    Crockford-encoded UUIDv7, such as `User_01k7ab4vstfggspkjt3my8wzr2`.
    [`schema.md`](schema.md) holds the conventions and the list of prefixes.
21. **Taxes are kept in tax books**: one per user, or married couple,
    and year. A tax book holds the documents received and one **filing** per return
    (federal, state, local), each with the forms as filed, the tax authority's letters and
    any amendment. Another user can be given write access to help prepare it (S8.14).
    MoolaKata still prepares worksheets only and never files.
22. **Owners choose people on other servers**. Linked servers exchange their lists of active
    users, so an owner shares any of the eight shareable kinds (account, portfolio, budget,
    gift plan, giving plan, tax book, projection, person) with named people on another server,
    as they do with people on their own (S10.3). What a household shares is shown in a **window
    of its own**, never mixed with this household's data (S12.10). This suits household
    servers; a server for more than a household would need users to opt in to being listed
    ([out of scope](out-of-scope.md)).
23. **US dollars only.** Every account, price, total and report is in USD. There are no
    foreign accounts and no currency conversion (S4.8, [out of scope](out-of-scope.md)).
24. **Records are soft-deleted.** Deleting marks a record deleted, with when and by whom, and
    a view per table works out whether it is deleted through what it belongs to. The few
    exceptions are listed in [`schema.md`](schema.md) (S14.1.5).
25. **Alerts** tell people when something needs them, above all admins when a source has
    failed for more than 48 hours. They show as a live count on the **Alerts** screen, and
    each user chooses to be emailed each one, a daily summary, or nothing (S12.11).
26. **Account data comes from files the user brings.** Bank, card, brokerage and exchange
    accounts are kept current from files: OFX/QFX and CSV downloads, PDF statements, and
    photos of statements read on the server. There is no bank-aggregation service (S1.3,
    [rejected ideas](rejected-ideas.md)); the household's own MoolaKata Connector fetches
    such files for the accounts whose owners turn its sync on (S18). **Bitcoin** is the one chain watched, through a public explorer or the household's
    own node; other coins and exchanges' APIs come later (S1.5, S1.6).

# R2. Terminology

1. **Institution:** a bank, broker, exchange, plan administrator or blockchain that holds the
   money. It is a label on an account, not an entity with credentials.
2. **Account:** one place money is held, owned by one user: a checking account, a brokerage
   account, a Roth IRA, a Coinbase account, a Bitcoin wallet. Every account has an **account
   type** (S1.1) that decides its fields, tax treatment and screens.
3. **Holding:** what an account holds of one **instrument** (cash, a stock, a fund, a coin, an
   option contract) at a point in time: its quantity, cost basis and value.
4. **Instrument:** a thing with a price, such as `AAPL`, `VTI`, `BTC`, or `AAPL 2026-12-18
   250 C`. Cash is an instrument with a price of $1.
5. **Lot:** one acquisition of an instrument: date, quantity, cost, and what remains open.
   Gains, holding periods and wash sales are computed per lot.
6. **Transaction:** one dated movement in an account: deposit, withdrawal, purchase, sale,
   dividend, interest, fee, transfer, option open, close, expiry, assignment or exercise. A
   bank transaction has a payee and a budget **category**.
7. **Position:** an instrument held in an account, followed from **open** to **closed**, with
   its realized and unrealized gain or loss. Options are positions (S3).
8. **Portfolio:** a named set of accounts, or of a part of them (S5), owned by one user and
   charted as one. *All my accounts* is everyone's implicit first portfolio.
9. **Share:** a grant of one item, of the eight kinds of S10.3, to a user, a group or named
   users of a linked server, at a **level**: `read` or `write` (S10). A share to a linked
   server's users is always `read`.
10. **Linked server (peer):** another MoolaKata server this one has a **link** with (S11).
    What a link brings in is kept in that link's **linked copy**, encrypted under its own
    **access key**: 12 generated words that the receiving household keeps. The copy is
    **locked** until someone it shares with enters the words, and locks again after an hour
    unused. It is shown in its own **linked household** window (S11.9, S12.10).
11. **Price source:** an integration (a `TickerSource`) that supplies daily prices for one
    or more instrument classes (S4).
12. **Projection:** how money will grow toward a goal (retirement, education or a savings
    target), from contributions, returns and withdrawals over time. An **active** projection
    is the plan being followed, tracked against its baseline (S6).
13. **Budget:** planned amounts per category over chosen accounts, compared month by month
    with the actual transactions, by its **method**: **tracking** or **envelope**. A user
    follows one **active** budget; the others are **scenarios**. A **reserve** is a plan
    line saving toward a **target**; a **move** puts money from one category to another for
    a month (S7).
14. **Receipt:** an uploaded file (PDF, JPEG, PNG, HEIC, WebP) with a date, an amount and
    links to what it supports (S9).
15. **Tax book:** the tax records of one user, or of a married couple filing jointly, for one
    **tax year** (a calendar year): the tax documents they received (W-2s, 1099s), and a
    **filing** per return (federal, state or local) with the forms as filed and what the tax
    authority sent back (S8.14–S8.17). The Taxes screen shows one tax book at a time.
16. **Loan:** a liability account with terms (principal, rate, term, payment) from which
    MoolaKata computes an **amortization schedule**. A **mortgage** is a loan secured by a
    property. An **overpayment** is principal paid beyond the schedule (S1.9).
17. **Physical asset:** a thing of value that is not a security: precious metals,
    collectables, property, a vehicle. A physical-asset account holds **items**, each with
    its own purchase date, cost basis, valuations and notes (S1.10).
18. **Person:** someone in the household's life: every user is one, and so are children,
    parents and friends who never sign in. A person has a name, sex, birthday and
    **relationships** with other people, from which the family tree is worked out (S10.10).
    A person can be a 529 plan's beneficiary (S1.8).
19. **Gift:** something given to (or received from) a person for an occasion, from idea to
    given, with its cost (S7.8). A user's **gift plan** for a person holds their budget,
    occasions and notes for that person (S7.7). **Giving** means charitable donations, tracked against a
    **giving target** (S7.9).
20. **Words not used:** *Wallet* for anything but a self-custody crypto wallet. *Asset* on
    its own for a security: the UI says holding or instrument, and keeps *asset* for
    *physical asset* (term 17). *Trade* as an entity: a trade is a pair of
    transactions on a position.
21. **MoolaKata Connector (the connector):** the second service that holds institutions'
    credentials in a vault MoolaKata can't open, fetches with its drivers, and pushes what they
    fetch into MoolaKata's import (S18). It is **paired** with one MoolaKata server.
22. **Driver:** the part of the connector for one institution, which fetches from it (Schwab,
    OFX Direct Connect).
23. **Connection:** one sign-in at one institution, kept by the connector and owned by the
    user whose sign-in it is; an account's sync names a Connection and the institution
    account it is (S18.6).
24. **Relationship:** a dated link between two people: *spouse*, *couple*, *child*,
    *friend*, *colleague* or *family* (S10.10.4).
25. **Strategy:** option legs, and shares, held together as one (a covered call, an iron
    condor), with its combined P/L, max profit and loss and capital at risk; a label over the
    lots, which keep their own gains (S3.5).
26. **Identity key, sealing key:** the connector's two key pairs, made at pairing. The
    identity key signs its calls and sits beside its vault; the sealing key is what a browser
    encrypts a credential to (a **sealed box**), its public half held by MoolaKata and its
    private half kept in the vault (S18.4.5).

# R3. Design principles

1. **One server, on the household's own LAN.** All data stays on hardware its users control.
   The only outbound calls are to price sources, the bitcoin explorer or node, the SMTP server,
   and linked servers that a user or admin set up, and each is visible in Settings (S16). The
   MoolaKata Connector, a second service, calls the institutions its Connections name, each
   Connection's host shown in Settings › Connector (S18).
2. **The ledger is the truth.** Holdings, balances, positions, gains and charts are derived
   from transactions and lots. A **balance snapshot** may stand in for history where none is
   available, such as an opening balance or a 401(k) statement, and it is marked as such.
3. **Exact arithmetic.** Decimals everywhere, with rounding only at display or where the tax
   rules say to round (S14.3).
4. **Least privilege in sharing.** A share grants one item, at one level, to whom it names. It
   is never re-shared. Revoking it ends access on the next request, and on a linked server at
   its next exchange (S11.4).
5. **Safe defaults.** A new account is shared with no one. A new link carries nothing until
   something is shared with it. Price sources and the bitcoin explorer are off until
   configured.
6. **Never hold the keys to the money.** There are no private keys, seed phrases or trading
   permissions, and MoolaKata itself holds no credentials for a bank or an exchange: the
   sign-ins the MoolaKata Connector keeps live only in its own vault, which MoolaKata can
   neither open nor ask for (S18.2).
7. **One store, live on the next request.** There are no caches between the database and a
   request, so a change (a share revoked, a rule edited) applies to the very next one. A record
   is validated as a whole when saved, every change is saved explicitly, and a refusal names
   the field and the reason, which the UI shows at that field.
8. **Audit names fields, never values.** Activity says "Alice changed the
   category of 3 transactions", and amounts stay out of the log.
9. **The contract is generated.** OpenAPI comes from the routes, the UI's JSDoc types come
   from it, and a check fails on drift (S17.5).
10. **History reads as it was.** Past figures are left as they were, so they are recognised
    when looked back on. A record that ends or is deleted (an account closed, a person
    deleted) changes what comes after its end, never what came before: past budget months,
    returns and gifts keep it, shown by its name and marked *(closed)* or *(deleted)*
    (`schema.md` §6).
