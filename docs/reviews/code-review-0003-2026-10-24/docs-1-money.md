# Code review 3, Phase 1: block docs-1-money

**Block:** `docs-1-money` (docs/REVIEW.md §5). **Commit read:** `6916954` (the working tree equals
it for these files). **Started:** Oct 24, 06:43 PM (Chicago). **Checking:** quick; every claim
is at 0 confirmations.

**Read whole:** `docs/requirements/README.md` (R1–R3 and its tables), S1–S9
(`S1-accounts.md`, `S2-holdings-and-lots.md`, `S3-positions-and-options.md`, `S4-prices.md`,
`S5-portfolios-and-charts.md`, `S6-projections.md`, `S7-budgets-gifts-and-giving.md`,
`S8-taxes.md`, `S9-receipts.md`), `later.md`, `gaps.md`, `questions.md`.
**Searched, not read whole:** `docs/mockups/MoolaKata-mock.html` (526 KB), by the screens,
labels, buttons and `GUIDES` entries of S1–S9.

Line numbers are the file's at `6916954`.

## Claims

Each claim: kind, severity (High, Med, Low as `gaps.md` ranks them), confirmations (0 for
all: a quick review), status (open), the requirement, the lines quoted, what goes wrong,
remedy and alternatives. All rest on reading alone.

### D1-1: Capital at risk is defined twice for one short option, and the two disagree

- **Kind:** the same thing specified twice, differently. **Severity:** Med. **Conf:** 0.
  **Status:** open.
- **Req:** S3.5.5, S3.5.6, S3.9.2.
- **Where:**
  - `S3-positions-and-options.md:68`: "| cash-secured put | strike × multiplier × contracts,
    less the premium |"; `:70`: "| naked call, short straddle and strangle | *unlimited*, or the
    broker's margin requirement the owner types |"; `:78–79`: "An unlimited risk counts as
    such: a total with one in it is *unlimited*, never the sum of the rest."
  - `:81–83`: "an investing account and a portfolio show **Capital at risk** beside their
    options' market value, counting each option outside a strategy as a single leg (S3.9.2)."
  - `:131–133`: "**Capital at risk**: for a long option, the premium paid; for a short one, the
    strike on every share the most contracts open at once cover (the cash to buy them for a
    put, the shares to deliver for a call)."
- **What goes wrong:** one short call, 1 contract at a $250 strike, never grouped (S3.5.1
  proposes single legs only as covered calls), counts in the account's *Capital at risk* as
  $25,000 by S3.9.2. Grouped by hand as a *short call (naked)*, the same leg counts as
  *unlimited* by S3.5.5, and makes the account's total *unlimited*. A short put likewise counts
  strike × 100 without the premium ungrouped, and less the premium grouped. The account's total
  then depends on whether the owner pressed **Group**, and mixes a capital-required measure
  (S3.9.2, meant for the per-trade return) with a max-loss measure (S3.5.5) in one sum.
- **Remedy:** S3.5.6 counts an ungrouped leg by the S3.5.5 row of its single-leg shape (long
  option: premium; short put: strike less premium; naked call: *unlimited* or the margin
  typed), and S3.9.2 says its figure is the per-trade return's base only.
- **Alternatives:** keep S3.9.2 for both, and drop the *unlimited* row for single legs (a naked
  call's capital is the shares to deliver); or show the two figures under different names
  (*capital at risk* and *capital required*).

- **Check:** confirmed. Read S3.5.5 (`:62–79`), S3.5.6 (`:80–84`) and S3.9.2 (`:131–135`): an
  ungrouped option counts by S3.9.2 (strike on the shares covered), a grouped one by the S3.5.5
  row (*unlimited* for a naked call, strike less premium for a cash-secured put), and S3.5.6
  sums both into one account figure. S3.9.2's last sentence makes a leg in a strategy take the
  strategy's figure, which is the difference the claim describes, not an answer to it. Lines
  match.

### D1-2: Budget alerts go to "its owner", but the active budget can be another user's

- **Kind:** contradiction within the block. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S7.6, S7.12, S7.12.5.
- **Where:** `S7-budgets-gifts-and-giving.md:106–107`: "**Budget alerts** come from a user's
  active budget only (S7.12), raised as alerts to its owner (S12.11)"; `:253–254`: "Each user
  follows at most one **active** budget, among those they own or that are shared with them";
  `:269–271`: "a household budget shared at `write` can be active for both, while one of them
  tries a scenario of their own".
- **What goes wrong:** Alice owns the household budget and shares it at `write` with Bob. Bob
  makes it active; Alice makes a scenario of her own active. Read as written, *Cash before
  payday* comes from Bob's active budget and is raised to its owner, Alice, who doesn't follow
  it, and Bob, who does, hears nothing. S7.12.2 ("Only the active budget … raises budget
  alerts") leaves the same doubt.
- **Remedy:** S7.6 says the alerts go to each user whose active budget it is.
- **Alternatives:** alerts go to the owner and to every `write` receiver who has it active.

- **Check:** confirmed. S7.6 (`:106–107`) says "its owner"; S7.12 (`:253–254`, `:269–271`) lets
  a receiver have a shared budget active. S12.11.1.3 (`S12-web-ui.md`, "for each user: … the
  active budget's cash before payday (S7.6)") reads as the remedy's reading, so the two sections
  disagree rather than S7 alone being unclear; severity and remedy unchanged.

### D1-3: R2.8 defines a portfolio as possibly "a part of" its accounts, which S5 leaves to L5

- **Kind:** term used other than its section defines it. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** R2.8, S5.1, L5.
- **Where:** `README.md:225`: "**Portfolio:** a named set of accounts, or of a part of them
  (S5)"; `S5-portfolios-and-charts.md:3`: "**A portfolio** is a named set of accounts";
  `:21–23`: "A portfolio of chosen holdings … come[s] later ([later work](later.md), L5)";
  `later.md:44`: "a portfolio of chosen holdings of its accounts".
- **What goes wrong:** the terminology promises a portfolio over part of an account, which no
  section specifies and L5 schedules after the first release. A reader of R2 (or a unit
  checking the portfolio code) looks for it in S5 and finds a later item.
- **Remedy:** R2.8 reads "a named set of accounts (S5)", or adds "(a part of them, later: L5)".

- **Check:** confirmed. README `:225` says "or of a part of them (S5)"; S5.1 (`:3`) and its
  `:21–23` leave "a portfolio of chosen holdings" to L5 (`later.md:44`). No section specifies a
  portfolio over part of an account.

### D1-4: Items marked "later" with no L id: they are in no list

- **Kind:** CLAUDE.md rule (later work has lasting ids) / behaviour named and never scheduled.
  **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S6.4.2, S6.4.3, S6.5, S7.6.2, S9.8.3; `later.md` (preamble).
- **Where:** `S6-projections.md:69`: "(log-normal; a historical bootstrap later)"; `:85`:
  "**Glide path** *(later)*"; `:87`: "**Tax-aware buckets** (later): taxable, deferred and free
  balances projected apart"; `S7-budgets-gifts-and-giving.md:114`: "*(later)*: a category
  passing a threshold, a large transaction."; `S9-receipts.md:86–88`: "Smaller,
  script-specific recognition models … can replace them later the same way".
- **What goes wrong:** `later.md:3–5` says later work is "Work planned for after the first
  release … Each item has a lasting id", and the README's table lists L1–L12. These five are
  in neither, so no milestone, gap or later item holds them: Phase 2's "not built" test
  (REVIEW.md §7) can't tell them from forgotten work, and S6.5 is a first-level item that
  `doccheck.txt` lists as cited by no code for that reason.
- **Remedy:** each becomes an L item (L13 onwards) cited where it is named, or is moved to
  `out-of-scope.md` or `rejected-ideas.md` if it isn't planned.

- **Check:** confirmed. Read the five lines (S6.4.2 `:69`, S6.4.3 `:85`, S6.5 `:87`, S7.6.2
  `:114`, S9.8.3 `:86–88`); a search of `later.md`, `README.md`, `gaps.md` and
  `rejected-ideas.md` for glide path, bootstrap and tax-aware finds none, and `later.md` is
  L1–L12 only. (`doccheck.txt` lists S6.5 uncited by code, as the claim says; "for that reason"
  is an inference.)

### D1-5: "Comes later" points at out-of-scope, not at later work

- **Kind:** reference / the same thing classed twice. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** R1.26, S1.5, S1.6.
- **Where:** `README.md:204–205`: "other coins and exchanges' APIs come later (S1.5, S1.6)";
  `S1-accounts.md:167–168`: "Reading an exchange through its API comes later ([out of
  scope](out-of-scope.md))"; `:169`: "Other coins and chains come later ([out of
  scope](out-of-scope.md))"; `out-of-scope.md:172–173`: "Coins and chains other than bitcoin,
  and reading crypto exchanges through their APIs (later)."
- **What goes wrong:** out of scope means MoolaKata doesn't do it; later means it is planned
  with an L id. These are both and neither: no L item, and the out-of-scope list says
  "later". A reviewer can't tell whether a request for an exchange API is settled (§3.6) or
  scheduled.
- **Remedy:** choose one: L items for coins and exchange APIs (with what is known), or drop
  "later" from the three places and keep them out of scope. **Needs the user** (which one).

- **Check:** corrected. Lines: the out-of-scope quote is at `out-of-scope.md:3–4` (the file is
  15 lines), not `:172–173`; the quoted text, the README (`:204–205`) and S1 (`:167–169`)
  citations are right. Severity unchanged. The claim holds: no L item covers coins or exchange
  APIs, and out-of-scope says "(later)". Still needs the user.

### D1-6: S9.8.8 says "Not in this version"

- **Kind:** CLAUDE.md rule (no versions or status). **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S9.8.8.
- **Where:** `S9-receipts.md:137–139`: "**Not in this version**: line items, handwriting,
  multi-receipt photos, currencies other than USD, and non-Latin scripts."
- **What goes wrong:** "this version" is a status the requirements don't carry (CLAUDE.md,
  README rule 3); it leaves open whether these are later work (no L id) or out of scope. One of
  them is already out of scope by R1.23 (currencies), and S9.8.3 says the shipped models read
  Chinese, so "non-Latin scripts" is about the parser, not the models.
- **Remedy:** "**Not read**: …", with each either out of scope or an L item (as D1-4).

- **Check:** confirmed. `S9-receipts.md:137` reads "Not in this version"; R1.23
  (`README.md:192`) makes other currencies out of scope; S9.8.3 (`:82`) says the shipped
  recognition models "read Latin script as well as Chinese", against "non-Latin scripts" at
  `:138`.

### D1-7: later.md L2 says Massive is "not yet tried with a live key"

- **Kind:** CLAUDE.md rule (no status). **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** L2, S4.3.
- **Where:** `later.md:20`: "**Massive** (formerly Polygon.io), Basic plan: shipped as the
  fallback (S4.3) but not yet tried with a live key: its limits, its history for expired
  contracts."
- **What goes wrong:** a statement of where testing stands, which goes in the repository's
  README (CLAUDE.md); it goes stale silently once someone tries it. ("formerly Polygon.io",
  here and at `S4-prices.md:33`, names the vendor and is fine.)
- **Remedy:** "**Massive**, Basic plan: the fallback (S4.3), to be tried with a live key: its
  limits, its history for expired contracts."

- **Check:** confirmed. `later.md:20` reads "shipped as the fallback (S4.3) but not yet tried
  with a live key", a testing status; `S4-prices.md:33` and the same line's "formerly
  Polygon.io" are the vendor's name, as the claim says.

### D1-8: S1.4 sends the reader to S8.6 for the contribution limits an admin corrects; they are S16.11

- **Kind:** reference. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S1.4, S8.6, S16.11.
- **Where:** `S1-accounts.md:163–165`: "Contribution limits per year are a table shipped with
  the app and updated with it, which an admin can correct in Settings (S8.6)."
  `S8-taxes.md:36–38` (S8.6) is the Retirement panel and names no Settings; `S16-settings.md:50–51`:
  "**Tax tables**: … shipped and correctable: contribution limits and thresholds".
- **What goes wrong:** every other mention of the tables in the block cites S16.11 (S1.8.2,
  S4.3, S8.14.5.3, L7); this one points at a panel that uses the limits.
- **Remedy:** "(Settings › Tax tables, S16.11), shown against contributions in S8.6".

- **Check:** confirmed. `S1-accounts.md:163–165` cites S8.6, a panel (`S8-taxes.md:36–38`) that
  names no Settings; the correctable table is S16.11 (`S16-settings.md:50`), which S1.8.2
  (`:270`), S4.3 (`:31`), S8.14.5.3 (`:102`) and `later.md:65` cite.

### D1-9: Where a possible wash sale is listed: S3.8.5 says S8.3, S8.4 claims it, S8.15 calls S8.4 "Issues"

- **Kind:** reference / the same thing in two places. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S3.8, S3.8.5, S8.3, S8.4, S8.15.
- **Where:** `S3-positions-and-options.md:93–94`: "Options on the same underlying are flagged for
  review, not decided (S8.3)"; `:114–115`: "a possible wash sale is listed among the tax book's
  issues (S8.3)"; `S8-taxes.md:27–28` (S8.3): "**Wash sales** found (S3.8), … and the flags left
  for review"; `:29–32` (S8.4): "**Missing or doubtful data**: … possible wash sales the rules
  leave to the preparer (S3.8.5)"; `:124–125`: "listed in the tax book's Issues (S8.4)".
- **What goes wrong:** the tax book's *Issues* is S8.4 by S8.15, but S3.8.5 names S8.3 as the
  issues; a flagged wash sale is specified for both panels. A unit checking the code can't
  tell whether listing it under Wash sales only, or under Issues only, is right.
- **Remedy:** S3.8 and S3.8.5 cite S8.4 for the issue, and S8.3 says the flags are listed in
  Issues (S8.4) and counted here.

- **Check:** confirmed. S3.8 (`:94`) and S3.8.5 (`:114–115`) send possible wash sales to S8.3;
  S8.3 (`:27–28`) lists "the flags left for review" while S8.4 (`:29–32`) lists the same flags
  under "Missing or doubtful data" and S8.15 (`:124–125`) calls S8.4 the tax book's Issues. The
  same flags are specified for two panels.

### D1-10: Two different strings are each "the OCC ticker"

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S2.1, S4.5, S3.10.3.
- **Where:** `S2-holdings-and-lots.md:6`: "An option's symbol follows OCC (`AAPL
  261218C00250000`)"; `S4-prices.md:48–49`: "An option is named by its OCC ticker
  (`O:MSFT261120P00480000`: underlying, expiry, put or call, and the strike in thousandths)."
- **What goes wrong:** the OCC symbol pads the root to six characters (`AAPL  2612…`); the
  `O:` prefix and unpadded root of S4.5 are Massive's own form. S3.10.3 ("an option named by
  its OCC ticker is made a contract") and S3.2.1 read a file's OCC ticker, so a reader can't
  tell which form a file or a source is matched in, or whether `O:` is ever stored.
- **Remedy:** S4.5 shows the OCC form and says Massive is asked with `O:` and the root
  unpadded.

- **Check:** confirmed. `S2-holdings-and-lots.md:6` gives the symbol as `AAPL  261218C00250000`
  (root padded; the claim's quote has the double space collapsed) and `S4-prices.md:48–49` calls
  `O:MSFT261120P00480000` "its OCC ticker". S3.10.3 (`:150`) and S3.2.1 (`:12`) name the "OCC
  ticker" for import without saying which form.

### D1-11: S4.5's typed mark, intrinsic value and greeks sit inside its item 3, on Massive

- **Kind:** structure (an item's text under the wrong number). **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S4.5, S4.5.3.
- **Where:** `S4-prices.md:57–61`: "3. **Massive** is asked for one contract at a time, with its
  history. A typed mark is a price on the / option's instrument, entered from the open position
  (**Type a mark**). Intrinsic value is / the underlying's latest close past the strike … Greeks
  / are out of scope". Lines 58–61 are indented three spaces, so Markdown continues item 3.
- **What goes wrong:** the typed mark and intrinsic value, which hold for every source (S3.7),
  read as part of S4.5.3 (Massive), and code citing them cites S4.5.3.
- **Remedy:** move lines 57 (from "A typed mark") to 61 to a paragraph after the list, or to
  an item 4.

- **Check:** confirmed. `S4-prices.md:57–61`: lines 58–61 follow item 3's first line with no
  blank line, so the typed mark, intrinsic value and the Greeks sentence are part of S4.5.3
  (Massive). Nothing cites S4.5.3 yet (searched requirements, schema and web/), so the
  code-citing consequence is only potential.

### D1-12: R3.5 says price sources are off until configured; S4 never says which are on, and loads benchmarks "always"

- **Kind:** contradiction / behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** R3.5, S4.2.3, S4.3, S4.4.
- **Where:** `README.md:303–304`: "Price sources and the bitcoin explorer are off until
  configured."; `S4-prices.md:15–18`: "**Settings › Prices** lists the enabled sources … **Add
  a source** picks from every source MoolaKata ships. A source that needs a key can't be enabled
  without one."; `:40–41`: "SPY, VT and BND are always loaded, as the benchmarks (S5.2.1)."
- **What goes wrong:** S1.6.2.1 spells out the explorer's "off until saved" (a wallet says it
  waits); S4 has no such rule. On a new server it isn't said whether CBOE and Coinbase (no key)
  are enabled, or whether an admin must add them; if they are off, "always loaded" loads
  nothing and the benchmark charts are empty without saying why.
- **Remedy:** S4.2.3 says a new server enables no source (R3.5), what the screens show until an
  admin adds one (*no price source: Settings › Prices*), and S4.4 says the benchmarks load once
  a source that serves them is enabled.
- **Alternatives:** the keyless sources (CBOE, Coinbase) are enabled at the welcome, which R3.5
  then names as its exception. **Needs the user** (which).

- **Check:** confirmed. R3.5 (`README.md:303–304`) says price sources are off until configured;
  S4.2.3 (`:15–18`) says only that a keyed source can't be enabled without a key; S4.4 (`:40`)
  says "always loaded"; no section (S4, S13, S16, README) says which sources a new server
  enables. Needs the user stands.

### D1-13: Who owns a category, and who may add or change one, is never said

- **Kind:** behaviour named and never specified (candidate gap). **Severity:** Med. **Conf:** 0.
  **Status:** open.
- **Req:** S7.2, S7.12.6, S10.3.1 (the Budget row), S14.10.1.1.
- **Where:** `S7-budgets-gifts-and-giving.md:36–40`: "**Categories** form a two-level tree
  (*Housing › Rent*). … A default set ships, and each category may carry a **tax tag** … and
  **Keep receipts for** a number of years"; `:273–275`: "a transaction's category, splits, tags
  and reimbursable mark are the transaction's"; `S10-users-and-sharing.md:89`: "| **Budget** |
  its categories, plan, moves, …"; `S14-storage-and-secrets.md:103–104`: "An admin sets it, in
  Settings › Storage".
- **What goes wrong:** the requirements never say whether categories are the server's, a
  user's, or a budget's, nor who adds, renames, re-parents or deletes one. Each reading breaks
  something else: per budget (S10.3's table) contradicts S7.12.6 (the category is the
  transaction's, the same in every budget); per user leaves Bob's transaction in Alice's
  shared account showing a category Bob's tree lacks, and Bob's rules (S2.7) setting one
  Alice's budget doesn't have; per server lets any user rename *Groceries* for everyone, while
  only an admin may set its retention (S14.10.1.1). The mockup's budget plan has **Add a
  category**, with no word on whose it becomes. Phase 2 has no rule to check the category
  routes against.
- **Remedy:** a G item (G25), or S7.2 specifies it: categories are the server's (one tree for
  the household, so shared accounts and budgets agree); any user adds a child category; renaming,
  moving and deleting a shipped or another user's category is an admin's; retention stays an
  admin's (S14.10.1.1). Activity records each change.
- **Alternatives:** per user with a shared household tree under a group; or per server with
  every user free to edit, recorded in Activity. **Needs the user.**

- **Check:** confirmed. S7.2 (`:36–40`), S10.3.1's Budget row (`S10-users-and-sharing.md:89`),
  S7.12.6, S2.7 (rules are "per user", `S2:38`) and S14.10.1.1 (`:103`, an admin sets retention)
  do not settle who owns or edits a category; `schema.md` has only the `Cat` prefix and
  `Category.parentId`, and gaps.md and questions.md have no item. The mockup's **Add a
  category** is at `:1971`.

### D1-14: A quarterly statement's value raises a stale alert every quarter before the next can arrive

- **Kind:** the same thing specified twice, differently. **Severity:** Med. **Conf:** 0.
  **Status:** open.
- **Req:** S4.3 (the "No free ticker" row), S1.11.7.1, S1.11.7.3.
- **Where:** `S4-prices.md:35`: "| No free ticker: 529 portfolios, 401(k) collective trusts,
  … | **manual** | — | a value from a statement or an import, or a typed price, with its date. A
  statement value older than 90 days is marked stale and raises an alert (S12.11) |";
  `S1-accounts.md:388–391`: "quarterly for 401(k), 403(b), 457(b) and 529 plans";
  `:398–400`: "a statement is overdue once the interval has passed since the last one ended,
  plus a grace period (15 days for monthly, 30 for quarterly, 60 for yearly)".
- **What goes wrong:** a 401(k)'s collective trust priced from the Mar 31 statement is 90 days
  old on Jun 29 and raises S4.3's alert; the Jun 30 statement can't exist yet, and S1.11.7
  holds the account's own overdue alert until Jul 30. Every quarterly 401(k) and 529 alerts each
  quarter for about a month, about the same missing statement S1.11.7 times with a grace period
  on purpose; a yearly-statement plan alerts for most of each year.
- **Remedy:** S4.3's statement values are stale when the account's statement is overdue
  (S1.11.7.3), and raise no alert of their own: the overdue statement's alert covers them.
- **Alternatives:** 90 days becomes the interval plus its grace period, per account.

- **Check:** confirmed. S4.3's row (`S4-prices.md:35`) marks a statement value stale at 90 days
  and S12.11.1.2 raises that as its own alert; S1.11.7.1 (`:390`) makes 401(k) and 529
  statements quarterly and S1.11.7.3 (`:398–399`) holds the overdue alert 30 days past the
  quarter. Mar 31 plus 90 days is Jun 29, Jul 30 is the overdue date: the arithmetic holds.

### D1-15: The benchmark's "60/40 mix" is named and never specified

- **Kind:** behaviour named and never specified (candidate gap). **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S5.2.1, S4.4.
- **Where:** `S5-portfolios-and-charts.md:16`: "against a **benchmark** (SPY, VT, a 60/40
  mix)"; `S4-prices.md:40–41`: "SPY, VT and BND are always loaded, as the benchmarks".
- **What goes wrong:** which funds the 60 and 40 are (VT or SPY, with BND, as S4.4's loading
  suggests), and whether the mix is rebalanced (daily, monthly, yearly, never) are not said;
  each choice gives a different line over 5Y.
- **Remedy:** S5.2.1: "a 60/40 mix of VT and BND, rebalanced monthly" (or the choice made).

- **Check:** corrected. Scope: the funds are not wholly unsaid. The mockup's New portfolio
  dialog offers "60/40 VT/BND" (`MoolaKata-mock.html:2093`), which settles VT and BND in the
  design reference though S5.2.1 doesn't say so; what no document says is the rebalancing.
  Remedy as written, with S5.2.1 naming VT and BND to match the mockup. Severity unchanged.

### D1-16: S3.9 makes an option trade an entity, which R2.20 says a trade is not

- **Kind:** term used other than R2 defines it. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** R2.20, S3.9, S3.9.1, S3.10.4.
- **Where:** `README.md:267–268`: "*Trade* as an entity: a trade is a pair of transactions on a
  position."; `S3-positions-and-options.md:128–130`: "An option trade runs from the first
  contract opened in an account to the moment none is open. Premium in and out are the cash
  received and paid, fees included"; `:157–159`: "On Option trades, the old contract's trade
  ends *adjusted*".
- **What goes wrong:** S3.9's option trade is any number of transactions (scale-ins, partial
  closes), listed on its own tab with its own dates, P/L and end state: an entity in all but
  name, and not "a pair". A reader holding R2.20 looks for pairs.
- **Remedy:** R2.20 adds: "an **option trade** (S3.9.1) is a position's run from open to none
  open, a view, not a stored record", or S3.9 uses another word (*a run*).

- **Check:** confirmed. R2.20 (`README.md:266–268`) lists "*Trade* as an entity: a trade is a
  pair of transactions on a position" among the words not used; S3.9.1 (`:128–130`) defines an
  option trade as any run from first open to none open, with its own tab, dates and P/L (`:126`,
  `:158`).

### D1-17: S8.7 flags charitable gifts "above" the threshold; S8.9 says "$250 or more"

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S8.7, S8.9.
- **Where:** `S8-taxes.md:40–41`: "Charitable gifts above the substantiation threshold show
  whether a receipt is attached."; `:48–49`: "a written acknowledgement is flagged as missing
  for any single gift of $250 or more".
- **What goes wrong:** a $250.00 gift is flagged by S8.9 and not by S8.7's "above"; the two
  panels disagree about the same gift. (IRC §170(f)(8) reads "$250 or more".)
- **Remedy:** S8.7: "Charitable gifts of $250 or more (S8.9)".

- **Check:** corrected. S8.7 (`S8-taxes.md:39–41`) names no figure: "the substantiation
  threshold" is not defined there, so "above" conflicts with S8.9's "$250 or more" (`:48–49`)
  only if the two are the same threshold, which the claim assumes and no section says. The
  remedy (name the figure, $250 or more, in S8.7) holds and is stronger for it. Severity
  unchanged.

### D1-18: "One active projection per savings target": what makes two targets the same is not said

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S6.7.1, S6.2.3.
- **Where:** `S6-projections.md:92–94`: "**At most one per subject**: one retirement projection
  per person or couple, one education projection per beneficiary, one per savings target.
  Making one active asks before turning off the one it replaces."
- **What goes wrong:** a savings target is an amount by a date (S6.2.3) with no identity of its
  own: two savings projections for a house deposit at different amounts are either one subject
  (and making the second active turns off the first) or two (and any number can be active).
  The code must pick one, and the rule can't be checked.
- **Remedy:** savings projections have no limit on active ones (each is its own target), or a
  savings projection names its target (*House deposit*) and one per name is active.

- **Check:** confirmed. S6.7.1 (`S6-projections.md:92–94`) gives a savings target no identity:
  S6.2.3 (`:30–32`) defines one as an amount by a date, and neither `schema.md` nor the mockup
  (`:1373`, a free-text subject) says what makes two targets the same.

### D1-19: "The 4% rule" is never defined, and the mockup shows it as 4% of the balance

- **Kind:** term not defined / mockup vs section. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S6.2.1.
- **Where:** `S6-projections.md:16–17`: "**withdrawals** (the 4% rule, a fixed amount rising
  with inflation, or a percentage of the balance)"; `MoolaKata-mock.html:1404`: "`field('Withdrawal',
  sel(['4% of balance', 'Fixed $80,000/yr, rising with inflation', 'Fixed % …'], '4% of
  balance'))`"; the projections guide: "Withdrawal: A percentage of the balance each year, or a
  fixed amount that rises with inflation."
- **What goes wrong:** the 4% rule is usually 4% of the balance at retirement, then that dollar
  amount rising with inflation; S6.2.1 lists it beside "a percentage of the balance", so it must
  differ from it, but the mockup's default *4% of balance* is the percentage-of-balance method,
  and its guide drops the rule. The two readings give different chances the money lasts.
- **Remedy:** S6.2.1 defines it ("4% of the balance at retirement, then that amount rising with
  inflation") and the mockup's choice and guide follow.

- **Check:** confirmed. S6.2.1 (`:16–17`) lists "the 4% rule" beside "a percentage of the
  balance" and never defines it; the mockup's Withdrawal choices are `4% of balance`, a fixed
  amount and `Fixed % …` (`:1404`), and its guide (`:2396`) describes only a percentage or a
  fixed amount. No other document defines the rule.

### D1-20: Allocation is shown and named, never specified, and L5 defers it

- **Kind:** behaviour named and never specified / contradiction with later work.
  **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S5, S5.2, S3.5.6, L5 (and S12.2.1, the Dashboard).
- **Where:** `README.md:44`: "| **S5** | … | Portfolios across accounts, performance, allocation
  and the charts |"; `S3-positions-and-options.md:83`: "Allocation charts keep market value.";
  `S5-portfolios-and-charts.md:21–23`: "allocation against a target with its drift and
  rebalancing … come later"; `later.md:44–46`: "**allocation** (donut and treemap) by asset class,
  account type …, against an optional **target allocation**"; the mockup's Dashboard
  (`MoolaKata-mock.html:903`) has an **Allocation** donut with **Details**.
- **What goes wrong:** S5 lists three charts, none of them allocation; L5 puts allocation by
  asset class among later work; yet the Dashboard (S12.2.1, mockup) and S3.5.6 assume an
  allocation chart now. How a holding is put in a class is said only for projections
  (S6.4.2.2). A unit can't say whether the Dashboard's allocation is built to its requirement.
- **Remedy:** S5.2 adds a fourth chart, allocation by asset class (classes as S6.4.2.2 assigns
  them), and L5 keeps only the target, drift, rebalancing and the other breakdowns.

- **Check:** confirmed. S5.2 (`S5:14–22`) lists three charts; L5 (`later.md:44–46`) defers
  allocation by asset class; S12.2.1 (`S12-web-ui.md:29–30`) and the mockup's Dashboard card
  (`:903`) show allocation; S3.5.6 (`:83`) refers to allocation charts. S6.4.2.2 (`:77–80`) is
  the only classing rule.

### D1-21: The Dashboard's net-worth chart in the mockup isn't stacked by account group

- **Kind:** mockup vs section. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S5.3.
- **Where:** `S5-portfolios-and-charts.md:24–25`: "**Net worth** on the Dashboard: assets minus
  liabilities over time, with the composition stacked by account group."; the mockup's
  Dashboard (`MoolaKata-mock.html`, the card before *Allocation*): "Net worth … `lineChart({ …
  series: [{ name: 'Net worth', … values: rangeSlice(NETWORTH) }] })`", one line.
- **What goes wrong:** the design reference shows one line where the section asks for the
  composition stacked by group; whichever the app builds, one of the two is wrong.
- **Remedy:** the mockup stacks the groups (banking, investing, retirement, crypto, physical
  assets, less liabilities) under the net-worth line, or S5.3 drops the stacking.

- **Check:** confirmed. S5.3 (`S5:24–25`) asks for the composition "stacked by account group";
  the mockup's Dashboard net-worth card (`:901–902`) is one `lineChart` series, `Net worth`, and
  the mockup's net-worth guide (`:2151`) says nothing of stacking.

### D1-22: The mockup's button is **Mark…**; S4.5 names it **Type a mark**

- **Kind:** mockup vs section. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S4.5.
- **Where:** `S4-prices.md:57–58`: "A typed mark is a price on the option's instrument, entered
  from the open position (**Type a mark**)."; `MoolaKata-mock.html:1239` (the Open tab's row
  action) and `:2343` (the positions guide): "at a mark you type (**Mark…**)".
- **What goes wrong:** a bold name in a section is the control's label (R3, S12.7 guides are
  keyed to fields); the code can match one or the other.
- **Remedy:** one label in both (*Type a mark…* or *Mark…*).

- **Check:** confirmed. `S4-prices.md:57–58` names **Type a mark**; the mockup has **Mark…** at
  `:1239` and `:2343`. (The built app's button reads "Type a mark…",
  `web/ui/screens/positions.js:244`, so the mockup is the one out of step.)

### D1-23: An account's reserve **shortfall** has no state in the mockup

- **Kind:** mockup vs section (a state not shown; CLAUDE.md asks the mockup to show each
  state). **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S7.10.4.
- **Where:** `S7-budgets-gifts-and-giving.md:221–222`: "An account whose balance is below its
  reserves' total shows the **shortfall**."; the mockup's *Where the money is*
  (`MoolaKata-mock.html:1326` and around) shows *to move*, *backed*, *unassigned* and the
  withdrawals allowed, and the word *shortfall* appears nowhere in it.
- **What goes wrong:** the design reference has no form for the shortfall, so the app's is
  unreviewed.
- **Remedy:** the mockup's sample data gets an account in shortfall (or a MOCK pill state for
  it), with its guide entry.

- **Check:** confirmed. S7.10.4 (`S7:221–222`) says the account "shows the **shortfall**"; a
  case-insensitive search of the mockup finds no "shortfall", and *Where the money is*
  (`:1320–1327`) shows only *to move*, *backed*, unassigned money and the withdrawals allowed.

### D1-24: The mockup gives a gift the status *received*; S7.8.1's statuses don't include it

- **Kind:** mockup vs section. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S7.8.1, S7.8.3.
- **Where:** `S7-budgets-gifts-and-giving.md:133–134`: "a **status** (*idea*, *planned*,
  *bought*, *given*)"; `:140–141`: "**Gifts received** can be recorded too (from whom, for
  what), with a **thank-you sent** tick."; `MoolaKata-mock.html:2268` (gifts guide): "Status:
  Idea, planned, bought, given, or received for a gift to you, with a thank-you tick." (and its
  sample `status: 'received'`).
- **What goes wrong:** whether a received gift is a status of a gift or a record of its own
  (from whom) decides its fields and whether it can be *planned*; `schema.md` ("`Gift`, given
  or received") leans to the mockup.
- **Remedy:** S7.8.1 lists *received* as a status, for a gift to the user, with its giver and
  the thank-you tick.

- **Check:** confirmed. S7.8.1 (`S7:133–134`) lists four statuses; S7.8.3 (`:140–141`) records
  gifts received separately; the mockup's guide (`:2268`) lists *received* as a status and its
  sample data has `status: 'received'` (`:585`, row rendering at `:1527`); `schema.md:236` says
  "`Gift`, given or received".

### D1-25: S9.6 shows a tax document's file to the filers only; S8.14.3 and S10.3 share documents with helpers, and S9.6 omits several kinds S9.3 links to

- **Kind:** contradiction across sections (who sees what). **Severity:** Med. **Conf:** 0.
  **Status:** open. (A disagreement between documents, naming no weakness of a running server,
  so not withheld under REVIEW.md §2.)
- **Req:** S9.6, S9.3, S8.14.3, S8.16, S10.3.1 (the Tax book row), L6.
- **Where:** `S9-receipts.md:31–34`: "whoever can read a transaction can see its receipts, a
  gift's through the gift plans that show the gift, a donation's by its owner and those who see
  the giving plan it counts in, and a tax document's file by the tax book's filers (S8.16). An
  unattached receipt is its owner's alone."; `S8-taxes.md:80–82`: "A user who helps prepare the
  return … gets **write**: they can edit filings, attach documents and resolve issues";
  `S10-users-and-sharing.md:92`: "| **Tax book** | its panels, filings and documents (S8.14.3)
  |"; `later.md:56–57`: "a tax book's document files crossing a link with Include receipts"
  (later, so local shares already carry them); `S9-receipts.md:17–20` (S9.3): receipts also link
  to "physical-asset items …, loans …, 529 qualified expenses", and statements are kept on
  accounts (S1.3.3).
- **What goes wrong:** a preparer given **write** on a tax book attaches the W-2 PDF and then,
  by S9.6, can't open it, nor the filed return; by S10.3 and S8.14.3 they can. Read literally,
  S9.6 also gives no rule for a receipt kept only on a physical-asset item, a loan or a 529
  expense, or a statement kept on an account, so the code's choice there (owner only, or every
  reader of the account) can't be checked.
- **Remedy:** S9.6: a tax document's file is seen by whoever can read the tax book (filers and
  its shares); a receipt on an item, a loan, a 529 expense or an account (a statement) by
  whoever can read the account.
- **Alternatives:** keep tax-document files to filers and `write` helpers, not `read` shares,
  and say so in S10.3's row. **Needs the user** if the narrower one is meant.

- **Check:** corrected. Scope narrowed, severity unchanged (Med). The first half holds as
  written: S9.6 (`S9:31–34`) gives a tax document's file to "the tax book's filers" while
  S8.14.3 (`S8:76–82`) gives helpers **write** to "attach documents" and S10.3.1's Tax book row
  (`S10:92`) shares its documents. The second half overstates: S10.3.1's Account row (`:87`)
  already says an account's share includes "its … receipts" and S9.6 opens "whoever can read a
  transaction can see its receipts", so a receipt on an item, loan or statement is the
  account's; what is left unsaid is a 529 qualified expense (a transaction?) and an unattached
  statement. Remedy: the tax-document sentence, plus saying which of those kinds follow the
  account.

## doccheck.txt: the "To read" lines in this block

Judged fine, no claim (each is an example, a label, behaviour or a vendor's name, not
changelog language): `README.md:216` (2026-12-18, an instrument's example), `S1-accounts.md:162`
(2027-03-01, an example), `S1:233` ("no longer on the chain", a state's label), `S1:258`
("proposed", behaviour), `S3:112` ("no longer does", behaviour), `S3:126` ("unrealized now"),
`S4:33` and `later.md:20` ("formerly Polygon.io", the vendor's name), `S7:27` and `S7:32`
("proposed", behaviour), `S7:189` ("now and then"). The same `later.md:20` line's "not yet
tried" is D1-7. Read and found by hand beyond the list: `S9-receipts.md:137` "Not in this
version" (D1-6). Also judged fine: S6.3.1's model dates ("Bitcoin24 (2024)", "since 2022", "2030
targets": facts about the models), S8.1's "From tax year 2025" (a tax rule), `gaps.md`'s "Built
in milestone 7 part 9" (where G23 is scheduled), `questions.md`'s "Q1–Q29 are answered" (the
numbering).

Phase 0's mechanical problems: none (`doccheck.txt`: 0). Uncited first-level items in this
block (S1.4, S1.5, S2.1, S4.1, S4.8, S4.9, S6.2, S6.5, S6.6, S7.6, S8.10) are Phase 2's to judge;
S6.5 is part of D1-4.

## Summary of the claims

| Id | Req | Sev | Kind | In one line |
|---|---|---|---|---|
| D1-1 | S3.5.5 | Med | twice, differently | An ungrouped short option's capital at risk (S3.9.2) differs from the same leg grouped (S3.5.5): $25,000 or *unlimited* |
| D1-2 | S7.6 | Low | contradiction | Budget alerts go "to its owner" though the active budget may be a receiver's |
| D1-3 | R2.8 | Low | term | R2.8's portfolio of "a part of" accounts is L5's later work |
| D1-4 | S6.5 | Low | CLAUDE.md / unscheduled | Five "later" items have no L id |
| D1-5 | S1.5 | Low | reference | "Comes later" links to out-of-scope; needs the user |
| D1-6 | S9.8.8 | Low | CLAUDE.md | "Not in this version" |
| D1-7 | L2 | Low | CLAUDE.md | "not yet tried with a live key" |
| D1-8 | S1.4 | Low | reference | Limits corrected in Settings cite S8.6, not S16.11 |
| D1-9 | S3.8.5 | Low | reference | Possible wash sales: S8.3 or S8.4 (Issues) |
| D1-10 | S4.5 | Low | twice, differently | Two forms called "the OCC ticker" |
| D1-11 | S4.5 | Low | structure | Typed mark and intrinsic value nested under S4.5.3 (Massive) |
| D1-12 | R3.5 | Low | contradiction / gap | Which price sources a new server enables is unsaid; benchmarks "always loaded"; needs the user |
| D1-13 | S7.2 | Med | candidate gap | Who owns a category and who may change one is unsaid; needs the user |
| D1-14 | S4.3 | Med | twice, differently | A quarterly statement's value alerts stale at 90 days, before S1.11.7's overdue |
| D1-15 | S5.2.1 | Low | candidate gap | The 60/40 benchmark's funds and rebalancing unsaid |
| D1-16 | R2.20 | Low | term | S3.9's option trade is an entity R2.20 rules out |
| D1-17 | S8.7 | Low | twice, differently | "Above" the threshold vs "$250 or more" |
| D1-18 | S6.7.1 | Low | unspecified | "One active per savings target": no target identity |
| D1-19 | S6.2.1 | Low | term / mockup | "The 4% rule" undefined; mockup shows 4% of balance |
| D1-20 | S5.2 | Low | unspecified | Allocation shown (Dashboard, S3.5.6) but unspecified, and L5 defers it |
| D1-21 | S5.3 | Low | mockup | Net worth not stacked by group in the mockup |
| D1-22 | S4.5 | Low | mockup | **Mark…** vs **Type a mark** |
| D1-23 | S7.10.4 | Low | mockup | No shortfall state in the mockup |
| D1-24 | S7.8.1 | Low | mockup | Gift status *received* in the mockup, not in S7.8.1 |
| D1-25 | S9.6 | Med | contradiction | Tax-document files to filers only (S9.6) vs shared with helpers (S8.14.3, S10.3); S9.6 misses items, loans, 529 expenses, statements |

High 0, Med 4 (D1-1, D1-13, D1-14, D1-25), Low 21. All at 0 confirmations, open. Needing the
user: D1-5, D1-12, D1-13, D1-25 (if the narrower reading is meant). No §6 gate claim (none is
High); D1-25 and D1-1 are the two the units will most likely be checked against, and are worth
deciding before the units for S9 and S3.

## Claims digest

One line per fact another block could contradict, with its id. Terms, limits and defaults,
states, who may do what, what is sent or stored where.

### README (R1–R3)

- R1.1: Python server, FastAPI under Hypercorn; SQLite via SQLAlchemy and Alembic; browser app with no build step (Preact, HTM, @preact/signals, preact-iso), vendored, plain ES modules, strict CSP; no Node.js; Deno type-checks and lints; Playwright for Python runs browser tests.
- R1.2: single-page app at `/ui`, dark-mode first; sidebar, signed-in user at its foot, theme button, DEV pill in dev mode, update pill; desktop browsers only; phones get a separate PWA later.
- R1.3: F1 help pane, one Markdown guide per screen or panel, follows the focused field; a test fails when a field has no heading in its guide.
- R1.4: the clickable mockup in `docs/mockups/`, opens from disk, sends nothing; MOCK pill.
- R1.5: `moolakata dev`: self-signed cert, emails to a folder, canned price feeds, seed data, rules as strict as production.
- R1.6: admins manage users, groups and Settings; admins are trusted operators; the app can't keep out someone holding the recovery phrase and the host.
- R1.7: any user creates accounts and portfolios and shares them at `read` or `read/write`.
- R1.8 / R1.22: a link carries read-only shares of the eight shareable kinds (account, portfolio, budget, gift plan, giving plan, tax book, projection, person) to named people on the other server, both ways, never read/write; linked servers exchange their lists of active users.
- R1.9: money never a float: `Decimal` in Python, exact number literals in JSON (S13.8.2.1), integers or decimal text in SQLite (S14.3). Exception: projections' NumPy floats (S6.9).
- R1.10: prices are end-of-day closes, delayed, never live.
- R1.11: never moves money, places an order or signs; never stores a wallet's private key or seed; only addresses or extended public keys.
- R1.12: receipts are files on the server (PDF or image), attached to transactions, tax items or nothing.
- R1.13: everything stored is encrypted at rest (SQLCipher DB, receipt files, each secret); one master key = a 12-word recovery phrase, never stored; welcome shows it once to the first admin; after every start the server is locked until an admin enters it (locked screen or host); no key file, no keys process, no Vault/external key service.
- R1.14: charts are Apache ECharts, vendored, loaded only by screens with charts.
- R1.15: code in `web/` (`web/ui`, `web/server` = package `moolakata`); docs in `docs/`.
- R1.16: MoolaKata informs, does not advise; screens say so where it matters.
- R1.17: receipts read on the server with RapidOCR, CPU only, models shipped, sandboxed background job; results are suggestions.
- R1.18 / R2.10: each link's data in its own linked copy (SQLCipher DB + one encrypted file per receipt, own folder), opened by its access key (12 generated words, kept by the receiving household), never the master key; syncs while locked; key released after an hour unused.
- R1.20: SQLAlchemy Core tables, plain dataclasses; table names singular capitalised, fields camelCase; ids = short prefix + Crockford-encoded UUIDv7 (`User_01k7…`).
- R1.21 / R2.15: a tax book per user or married couple and tax year (calendar year); one filing per return (federal, state, local); another user can get write to help; never files.
- R1.23 / S4.8: USD only; no foreign accounts, no conversion; an instrument trading only in another currency is priced by hand.
- R1.24: records are soft-deleted (when, by whom); a view per table works out deletion through parents; exceptions in `schema.md`.
- R1.25: Alerts screen with a live count; admins alerted when a source has failed for more than 48 hours; each user chooses email each, a daily summary, or nothing.
- R1.26: account data from files the user brings (OFX/QFX, CSV, PDF statements, photos); no bank aggregation; the Connector fetches for accounts whose owners turn sync on; bitcoin is the only chain watched.
- R2.1: institution is a label on an account, not an entity with credentials.
- R2.2: an account is owned by one user; has an account type.
- R2.4: cash is an instrument priced at $1.
- R2.6: transaction kinds: deposit, withdrawal, purchase, sale, dividend, interest, fee, transfer, option open, close, expiry, assignment, exercise; a bank transaction has a payee and a category.
- R2.8: portfolio owned by one user; *All my accounts* is everyone's implicit first portfolio (see D1-3).
- R2.9: share = one item, one level (`read` or `write`), to a user, group, or named users of a linked server (always `read`).
- R2.10: a linked copy is locked until someone it shares with enters the words; locks again after an hour unused.
- R2.13: budget method tracking or envelope; one active budget per user; others are scenarios; reserve = plan line toward a target; move = money between categories for a month.
- R2.14: receipt file types PDF, JPEG, PNG, HEIC, WebP.
- R2.18: a person has name, sex, birthday, relationships; every user is a person.
- R2.20: words not used: *wallet* except self-custody crypto; *asset* alone for a security; *trade* as an entity (a pair of transactions on a position).
- R2.21–R2.23: the Connector is paired with one MoolaKata server; a driver per institution (Schwab, OFX Direct Connect); a Connection is one sign-in, owned by the user whose sign-in it is.
- R2.24: relationship kinds: spouse, couple, child, friend, colleague, family; dated.
- R2.26: connector's identity key (signs calls) and sealing key (browser seals credentials to it; public half held by MoolaKata, private half in the vault).
- R3.1: the only outbound calls: price sources, bitcoin explorer/node, SMTP, linked servers; each visible in Settings; the Connector calls institutions its Connections name, hosts shown in Settings › Connector.
- R3.2: the ledger is the truth; balance snapshots stand in where no history, marked as such.
- R3.4: a share is never re-shared; revoking ends access on the next request, on a linked server at its next exchange.
- R3.5: a new account is shared with no one; a new link carries nothing; price sources and the bitcoin explorer are off until configured.
- R3.6: MoolaKata holds no bank/exchange credentials; the Connector's vault, which MoolaKata can neither open nor ask for.
- R3.7: no caches between DB and request; a record validated whole; a refusal names the field and reason.
- R3.8: Activity names fields, never values (amounts stay out).
- R3.9: OpenAPI generated from routes; UI JSDoc types from it; a check fails on drift.
- R3.10: past figures stay; a closed or deleted record shows by name marked *(closed)* or *(deleted)*.

### S1 Accounts

- S1.1: account types and groups: Banking (`checking`, `savings`, `money-market`, `cd`, `cash`, `payment-app`), Liabilities (`credit-card`, `mortgage`, `heloc`, `auto-loan`, `student-loan`, `personal-loan`, `loan`), Investing (`brokerage`), Retirement (`ira`, `roth-ira`, `401k`, `403b`, `457b`, `hsa`), Education (`529`), Giving (`daf`), Crypto (`crypto-exchange`, `crypto-wallet`), Physical assets (`precious-metals`, `collectables`, `real-estate`, `vehicle`, `other-asset`).
- S1.1: a `daf` counts in no one's net worth by default; **Count in net worth** overrides.
- S1.2: every account: name, type, institution, optional last 4, owner, **active** switch (closed stays for history), notes, how kept current; `savings`/`money-market` also **Withdrawals allowed a month** (empty = none).
- S1.3.2: imports idempotent: match by file id (OFX `FITID`) or by date, amount and payee, amounts in cents; an id-less row matched takes the id; a repeated id is kept as a duplicate suspect; an OFX file with several accounts is refused.
- S1.3.2: a broker file's positions are a holdings check; lots change only through transactions, except accounts kept by snapshots.
- S1.3.3: statement import (PDF text layer, or photo/scan via RapidOCR), all on the server; must add up opening→closing or the difference is resolved or accepted; statement file kept as a receipt on the account.
- S1.3.3.1: sign order: running balance, explicit sign (`-`, `( )`, `CR`), section heading, words (marked guessed); card statements turned to the account's side once.
- S1.3.3.2: statement reading in the receipt reader's worker; up to 30 pages within five minutes; Settings › Imports can turn it off.
- S1.3.3.3: opening balance = reported balance the day before the period; closing = balance on the last day.
- S1.3.3.4: learned per institution per owner: section signs, first words of left-out lines.
- S1.3.3.5: combined statements split by account header; matched by last four digits; PDF kept once on each account it filled.
- S1.3.3.6: a statement kept without reading counts as the statement expected (S1.11.7) but not as coverage; same file not kept twice on an account.
- S1.3.3.7: learned column positions are later work (L10).
- S1.3.3.8: brokerage/plan statements read from a text layer only (photos kept unread); summary ending value checked within half a percent or $1, whichever is more; positions become a holdings check; trades, options activity, corporate actions, margin are not read (L1).
- S1.3.5: Connector: files fetched for a Connection, imported as an upload.
- S1.4: contribution year per contribution; birth year from the profile; contribution limits are a shipped table an admin can correct.
- S1.6.1: wallet holds addresses, xpub/ypub/zpub (legacy/nested/native segwit) or output descriptor; gap limit 20 by default, 1 to 200; at most ten derivation rounds per check; mainnet only.
- S1.6.1.4: descriptors `pkh()`, `sh(wpkh())`, `wpkh()`, `tr()` (BIP 86), `wsh(sortedmulti())`/`wsh(multi())` up to 15 keys with origins; checksum checked; `sh(wsh())` and taproot script trees refused (L11).
- S1.6.2: source set by an admin in Settings › Bitcoin: public Esplora explorer (mempool.space suggested, or Blockstream) or own node (mempool/Esplora, Electrum server, Bitcoin Core RPC); nothing read until an admin saves the section; own node's credentials are a secret (S14.4); named host lets the egress guard allow it on the LAN.
- S1.6.2.3: Bitcoin Core: a watch-only descriptor wallet per account named `moolakata-<account id>`, rescanned from the start the first time; only public keys and addresses sent.
- S1.6.2.4: Electrum server certificate trusted on first use (SHA-256 fingerprint confirmed by an admin); a changed certificate is refused and admins alerted until confirmed.
- S1.6.2.5: wallets checked every hour and on **Check now**; failure past the alert threshold alerts admins and each wallet's owner; message never names an address or amount.
- S1.6.2.6: a transaction recorded once by txid after 6 confirmations; a deleted one never re-recorded; received = transfer in without basis unless matched; fee = sale of the fee's sats plus a fee of the same amount; coinjoin fee share capped at what the wallet put in less what came back.
- S1.6.2.7: a recorded transaction missed by two reads in a row is marked *no longer on the chain* and the owner alerted; never deleted silently.
- S1.6.3: the form refuses anything like a private key or seed (WIF, 64 hex, 12/24 BIP-39 words, xprv); browser clears it before sending; server checks again and never repeats it.
- S1.6.4: bitcoin counted in whole sats; a wallet balance sent as an integer of sats; quantities stored as exact 8-place decimals; Profile choice BTC (default) or sats; price per bitcoin in USD.
- S1.7: transfers: opposite cash amounts in two of the owner's accounts within 4 days, closest in date; ties link neither.
- S1.7.1: bitcoin transfers between own accounts within 3 days (amount less fee) are proposed; owner confirms; a rejected pair isn't proposed again; coins carry their lots.
- S1.8: 529: state, plan, beneficiary (a person), opening date, expected state deduction (typed); contributions by contributor against the annual gift exclusion; five-year election; withdrawals matched to qualified expenses; Roth rollover shown after 15 years open, excluding the last five years' contributions; counts in the owner's net worth.
- S1.9.1: loan term 1 to 600 months; rate 0% to 40% to three decimals; a reset's rate to four.
- S1.9.2: interest rounded half up to the cent; under $1 left by rounding goes with the last payment.
- S1.9.3: payments split by the schedule (principal, interest, escrow, PMI, fees), never wholly principal; bank transactions of the last 90 days within 2% of the payment offered to link.
- S1.9.5: PMI can be dropped on request at 80% of the original value, automatically at 78%.
- S1.9.7: in budgets, Split (default; shipped *Loan payments › Interest, Escrow, PMI and fees, Principal*) or Whole.
- S1.10.2: spot valuation = fine weight × spot (premium/discount 0% by default); a valuation older than 12 months is stale; vehicles depreciate by a yearly percentage.
- S1.10.5: selling an item flags collectables (metals included) on Form 8949; personal-use losses not deductible.
- S1.11: reconciliation on the *Reconcile* tab; loans checked on their Overview.
- S1.11.2: anchors in order: CSV running balance, OFX ledger balance, statement closing balance, typed balance.
- S1.11.4: an open mismatch raises an alert after 7 days; accepted differences are balance adjustments shown in Activity.
- S1.11.5: duplicate suspects asked *both real?* once, answer kept.
- S1.11.6: ticking off marks a period reconciled; editing inside asks first.
- S1.11.7: statements expected: monthly (banking, cards, brokerage, exchanges, IRAs, HSAs, loans), quarterly (401(k), 403(b), 457(b), 529, DAF), none (cash, kept by hand, wallets, physical assets); learned after three statements, files more often than every 20 days teach nothing; overdue after interval + grace (15 / 30 / 60 days); no alert for none or nothing imported.

### S2 Holdings, lots and transactions

- S2.1: instruments kept once per server; classes `cash`, `equity`, `etf`, `mutual-fund`, `money-market`, `bond`, `option`, `crypto`, `metal`, `other`; option multiplier 100 by default; stored `AAPL 18DEC26 250 C`, shown `AAPL 18 Dec 26 250 C`.
- S2.2: a transfer in without basis makes a lot marked *basis missing*.
- S2.3: lot methods FIFO (default), LIFO, HIFO, specific identification, average cost; the method in force is recorded on each sale; changing it applies to later sales.
- S2.4: corporate actions (split, reverse split, symbol change, spin-off with Form 8937 %, merger with IRC §356 boot, return of capital) adjust lots, never history; recorded on Positions with **Corporate action…**.
- S2.7: categorisation rules are payee rules, per user, ordered, first match wins, in **Transactions › Rules**; regex after `re:` (Python, case-insensitive, at most 200 chars, nested repeats refused); amount range without sign, direction, one account; set category, *Rename to*, tags.
- S2.7.3: on import, the importing user's rules apply to new bank rows that aren't transfers; set a category only where none; never touch a split.
- S2.7.4: *Apply to the uncategorised*: Activity records the count, never an amount.
- S2.7.5: rules never shared, never across a link.
- S2.8.1: a closed year for an account = its tax book counts it and has the federal return filed or accepted; open again while an amended federal return is not started, in progress or rejected.
- S2.8.2–3: an edit moving a closed year's realized gains is refused with the years named, can be made anyway; recorded on each closing tax book until an amended return or *No amendment needed*.
- S2.9: reimbursable mark with amount and optional *by whom*; paybacks within 90 days offered; awaited part not counted in budgets; Activity records marking and pairing, never an amount.

### S3 Positions and options

- S3.1: a position is open while any lot is open.
- S3.2.1: CSV option rows must say open/close or how it ended; a plain buy or sell of an option refuses the file.
- S3.3: short options are negative lots; gains short-term (IRC §1234(b)); option closes take lots oldest first whatever the account's method.
- S3.4: assignment/exercise folds premium into basis or proceeds; a call assigned or put exercised with no shares is a short sale; deleting the assignment deletes its stock trade, not the reverse.
- S3.5.1: grouping proposed for legs on one underlying, one account, same day, and short call against ≥100 shares (covered call); *Not a strategy* isn't proposed again.
- S3.5.5: capital at risk now and at open, per the table; an unlimited one makes the total *unlimited* (see D1-1).
- S3.6: OTM expiry applied automatically the day after; at the strike counts as OTM; ITM asks.
- S3.7: option mark: source close, else typed mark, else intrinsic, labelled.
- S3.8: wash sales: same instrument within 30 days either side; user's accounts incl. IRAs and the spouse's on the sale date; IRA replacement disallows for good (Rev. Rul. 2008-5); options and short sales flagged, not adjusted; worked out again on any trade change.
- S3.9.2: per-trade capital at risk: long = premium; short = strike × shares covered.
- S3.10.1: whole-number split: contracts × ratio, strike ÷ ratio rounded to the thousandth.
- S3.10.2: other adjustments: new root (e.g. *AAPL1*), deliverable changes, multiplier stays 100; asked on Positions › Strategies.

### S4 Prices

- S4.1: prices free and daily; no intraday quotes.
- S4.2: sources implement `TickerSource` (`quotes`, `history`, optional `lookup`), one module in `prices/` each; a keyed source can't be enabled without its key (a secret).
- S4.3: CBOE delayed quotes (stocks, ETFs, options; closes from 2010; close after 4:15 PM Eastern; unofficial, personal use); Tiingo (fallback; mutual funds; 500 symbols a month, 50 requests an hour, 1,000 a day); money-market at $1.00; Coinbase for major coins; PAXG for gold; SLV/PPLT/PALL ÷ metal per share (shipped with the tax tables) for other metals; Massive Basic as options fallback (5 calls a minute, two years); manual for other coins, Treasuries, I/EE bonds, no-ticker holdings; a statement value over 90 days old is stale and alerts.
- S4.4: daily refresh at 6:00 PM Eastern by default; held or watched instruments; backfill from a week before the first transaction, at most five years; SPY, VT, BND always loaded; **Refresh prices**; failure past the threshold alerts.
- S4.5: option close older than the last trading day is stale; CBOE chain once a day, mid of bid/ask rounded to the cent, else last trade; dated by the underlying's last trade; index roots SPX/SPXW, NDX/NDXP, RUT/RUTW, VIX/VIXW.
- S4.6: daily closes kept for ever; charts read stored prices only.
- S4.7: every price carries source and `as_of`; a stock price older than 2 trading days is stale.
- S4.9: linked servers never call price sources for each other; shared data carries values and `as_of`.
- S4.10: a typed price is its typer's; values another user's accounts only when they type one too.

### S5 Portfolios and charts

- S5.1: a portfolio may include an account shared with its owner at `read`; viewers see only accounts shared with them (also across a link); **Share these accounts too** offered at read; never includes a linked server's account.
- S5.2: charts: value over time (1M, 3M, YTD, 1Y, 5Y, All, brush; contributions apart; benchmark SPY, VT, 60/40), performance (TWR and IRR), holdings.
- S5.3: Dashboard net worth: assets minus liabilities, stacked by account group.
- S5.4: series computed on the server (`GET /ui/api/portfolios/{id}/series?metric=value&range=1Y`); the browser only draws.

### S6 Projections

- S6.1: projection has owner, name, goal type, built on (accounts, a portfolio or a typed amount), active flag; shared like an account (S10.3); viewers see results and only the accounts shared with them.
- S6.2.1: retirement horizon age 95 by default; withdrawals: 4% rule, fixed rising with inflation, or % of balance; other income from an age.
- S6.2.2: education costs from NCES Digest table 330.10, shipped with the tax tables.
- S6.3: assumptions per user in **Profile › Assumptions**; general inflation 2.5%, education inflation 5% by default; fees per projection.
- S6.3.1: bitcoin models (your assumption, power law, log regression, stock-to-flow, Saylor Bitcoin24, ARK 2030), figures shipped in Settings › Tax tables.
- S6.4.2: Monte Carlo 1000 runs by default, log-normal, no correlation; 10th/50th/90th percentile fan; typed amount mix 60/40 unless set; savings answer at a 90% chance.
- S6.7.1: at most one active per subject (person/couple, beneficiary, savings target); making one active asks before replacing.
- S6.7.3: tracking band never narrower than 2% of the median either way; typed-amount projections not tracked.
- S6.7.5: falling behind alerts, checked monthly.
- S6.8.3: a shared active projection shows on the receiver's Dashboard only with **Show on my Dashboard** (off by default).
- S6.9: computed on the server with NumPy floats (the R1.9 exception), seeded; percentiles rounded to cents and sent as exact numbers; start value and tracking exact.
- S6.10: payoff planner: extra monthly, yearly, lump sums, biweekly (26 half-payments), rounding up; recast with the servicer's fee; saved plans per loan, one *the plan I'm following*.

### S7 Budgets, gifts and giving

- S7.1: budgets per user or per group (a group shares at `write`); monthly with yearly lines; owner chooses accounts, shares, deletes; `write` changes plan, moves, leave-outs; receivers see an account shared with the owner only if it is shared with them too.
- S7.1.2: a plan change applies from its month on.
- S7.1.3: method fixed at creation; **Copy as scenario** for the other method.
- S7.1.4: options reserves and moves; envelope budgets always have moves.
- S7.1.5: estimate from 3, 6 or 12 months; recurring looked for three years back.
- S7.2: categories two-level; expense, income, savings or transfer; tax tag; **Keep receipts for** years, empty for ever (S14.10.1); shipped *Cash*, *Savings* (*Emergency fund, Retirement, Investing, Education*), *Loan payments* (owner of categories unsaid: D1-13).
- S7.3.1: pending transactions don't count; matched transfers between budget accounts and transfer categories never count.
- S7.3.2: transfers leaving or entering the budget count by category; to/from a `cash` account as *Cash*; uncategorised listed as **Left/Entered the budget**.
- S7.3.3: a loan account is never one of a budget's accounts.
- S7.3.5: leave-outs are the budget's own; Activity records them.
- S7.3.7: rollover per monthly line; yearly lines compare year to date, never roll over.
- S7.3.10: month figures kept and worked out again on change; **Refresh**.
- S7.4: progress bars amber at 90%, red over; trends over 12 months; budgets have no export.
- S7.5.1: recurring series: ≥3 transactions, same payee and sign, weekly to yearly intervals, amounts within half of usual, found in the last 15 months.
- S7.5.2: changed = last amount moved 5% or more (fixed amounts only).
- S7.6: budget alerts only from a user's active budget; *Cash before payday* per checking account.
- S7.7.1: gift plan reminder lead time 14 days by default; birthday, wedding anniversary and relation come from the person.
- S7.7.3: upcoming occasions = the next 60 days; inside lead time on the Dashboard; entering lead time alerts.
- S7.8.1: gift status idea, planned, bought, given; linking a cost to a transaction needs write on its account and is recorded in Activity.
- S7.8.5: gift plans and gifts are their owner's; shareable read or write; a gift for a person who is a user is never shown to that user; across a link the owner's server leaves those gifts out before sending.
- S7.8.6: a deleted person's bought/given/received gifts stay as *Name (deleted)*; their ideas and planned gifts are deleted.
- S7.8.7: gift-tax flag over the annual exclusion (cash and 529 contributions; five-year election a fifth a year) → Form 709.
- S7.9.1: giving plan per year, per user or group; target % of income (10% by default) or fixed; counts the owner's accounts only.
- S7.9.2: income = *Income* categories (default), typed gross, or typed AGI.
- S7.9.3: QCD from age 70½; checks later (L7).
- S7.9.4: DAF counted when funded (default) or when it grants; never twice.
- S7.9.5: pledges due from the 25th (monthly) or December 1 (yearly) while under-given; a due pledge alerts its owner.
- S7.10: reserves: balance worked out, never stored; **Funded** at target; always roll over; held-in account; **Where the money is**: *to move*, **backed**, **shortfall**, **unassigned** landed money; warning past **Withdrawals allowed a month**; only the active budget says what to move.
- S7.11: moves by hand only (**Cover from…**, **Move**), per month, recorded in Activity; deleting undoes; owner and `write` make them, `read` sees them.
- S7.12: at most one active budget per user, owned or shared; first budget made active; **Make active** asks, rewrites nothing, Activity records it; only the active budget feeds the Dashboard, raises budget alerts, says what to move; a linked household's budgets are never made active here.
- S7.12.6: category, splits, tags and reimbursable mark are the transaction's, the same in every budget.
- S7.13: envelope: *To Budget* starts in the budget's first month; yearly line assigns a twelfth; card payment line worked out; owed-not-backed; categories always carry; overspent carried negative by default.
- S7.14: month's review offered from the 1st; **Mark reviewed** records who and when; *changed since reviewed*; months never locked.

### S8 Taxes

- S8.1: Form 8949 boxes A–F; digital assets G–L from tax year 2025 (wallet sales in I or L); *VARIOUS* only when a snapshot stood in.
- S8.2: exports Form 8949 CSV, TXF (V042, boxes A–F and wash-sale adjustment only; others counted beside it), PDF summary.
- S8.4: Issues include lots without basis, sales without lot, unresolved expiries, transfers between users, crypto without acquisition, possible wash sales, edits since filing.
- S8.6: contributions against limits (catch-up by age), Roth eligibility by MAGI as entered, backdoor-Roth, RMDs.
- S8.9: acknowledgement flagged for a single gift of $250 or more; goods over $500 a year → Form 8283; an item over $5,000 → appraisal; DAF grants and gifts to non-deductible organisations listed as not deductible.
- S8.10: 529 non-qualified part's earnings may carry a 10% additional tax.
- S8.14: tax book per tax year for one user or a married couple filing jointly; filers spouses on Dec 31 (or one died); a named filer accepts before their accounts count; accounts counted once; an added account counts while its adder can see it.
- S8.14.3: filers own the tax book and change its sharing; shares to users/groups, read-only to linked servers' named people; `write` helpers edit filings, attach documents, resolve issues, but not add accounts, delete, or change sharing.
- S8.14.4: new tax book copies filers, accounts, dependents; last year's received documents become expected, once every filer accepts.
- S8.14.5: dependents: qualifying child suggested under 19, or under 24 and a student; ages on Dec 31 under 17, under 13; claimed on two books flagged on both without naming the other; Form 8615 threshold from the tax tables.
- S8.15: filing progress: not started, in progress, filed, accepted, rejected; federal due date from Settings › Tax tables, moved past weekends, federal holidays and DC Emancipation Day (IRC §7503); overdue unfiled without extension shows in *Needs attention*; *Changed after filing* stays until an amended federal return or **No amendment needed** (name and day recorded).
- S8.16: tax documents' files kept as receipts with the same storage and protection.
- S8.17: carried forward: AGI, total tax, refund/owed, overpayment applied, capital-loss carryovers, 8606 basis, charitable carryovers; shown under **From last year**.
- S8.18: never computes tax owed, chooses filing status, applies state rules, or decides judgement questions.
- S8.19: network fees are sales by default; a tax book setting (chosen at creation, changeable) treats fees on own-account transfers as not taxed; exports say which.

### S9 Receipts

- S9.1: upload by drag-and-drop or picker; PDF, JPEG, PNG, WebP, HEIC (converted to JPEG for display, orientation applied); at most 25 MB each (a Setting); phone capture belongs to the PWA.
- S9.2: stored as `receipts/<random-id>.mkr` under the data directory, encrypted (S15.3), written once, rewritten only by re-encryption; streaming format of S11.9.6 under the receipts key (S15.3.2), file id as associated data; dedupe by hash in the DB; same person's re-upload returns their receipt; another's upload is their own receipt over the one file.
- S9.3: links to transactions, tax items, tax documents, physical-asset items, loans, 529 qualified expenses, gifts and donations, or nothing (inbox); whoever can change a linked thing can detach it.
- S9.4: viewing served `Content-Disposition: inline`, `Content-Security-Policy: sandbox`, `X-Content-Type-Options: nosniff`, from a path that needs the session; type checked by content.
- S9.5: thumbnails made in the worker (Pillow, pypdfium2 first page), stored in the DB as small WebP.
- S9.6: sharing follows what it's attached to; unattached is the owner's alone; attaching needs write; crosses a link only with **Include receipts**, as encrypted files in the linked copy (see D1-25).
- S9.7: deleted only by its owner and only when nothing links to it; file kept while any live receipt names its hash; backups leave the receipts directory out; **Keep** holds for ever; *Kept until…* / *Kept for ever*.
- S9.8.2: text layer = at least 20 characters per page; images greyscaled, long side 2,000 px; at most the first 3 PDF pages at 300 DPI; matching within 5 days, up to 25% larger (tip), best plus two alternatives, in accounts the user can write to.
- S9.8.3: PP-OCRv6 small models from the rapidocr wheel (~31 MB), pinned by `uv.lock`, SHA-256 checked before loading; never downloaded at run time.
- S9.8.4: one job at a time by default (a Setting); separate worker process, decrypted file over a pipe, no temp files; ONNX Runtime 2 threads, lower priority, 1.5 GB resident cap watched by the server, 60 s per receipt; restarted after crash/timeout; length-prefixed JSON checked field by field; seccomp denies network sockets; Landlock (Linux ≥ 5.13) denies the data directory; no inherited fds but the pipe, no environment, no core dump; server non-dumpable; every brought file (receipts, statements, thumbnails, HEIC, OFX and CSV) parsed in the worker; without Landlock reading stays on, Settings › Receipts says so and admins have an alert; Pillow bomb limit and 40 million pixel cap.
- S9.8.5: full text in FTS5; text and fields follow the receipt's sharing, cross a link only with the receipt, never in Activity or the log.
- S9.8.6: **Read again**, **Re-read all receipts**; only empty or OCR-suggested fields replaced.
- S9.8.7: Settings › Receipts: **Read receipts** on by default, jobs at a time, queue state.

### later.md, gaps.md, questions.md

- Later: L1–L12 open (L1 brokerage statement trades; L2 option sources; L3 Treasury rates; L4 user's export as a streamed ZIP after the password again; L5 portfolio charts; L6 more of a linked window; L7 limits in projections and QCD checks; L8 `Idempotency-Key` on every create, repeats within 24 hours; L9 Alpha Vantage, CoinGecko; L10 learned columns; L11 miniscript; L12 who paid in a household budget). Next free L13.
- L2: Schwab Trader API's sign-in token lasts seven days, so it belongs in a Connector driver.
- L8: `POST /ui/api/transactions` honours `Idempotency-Key` today (S13.8.8).
- L12: until then a group budget counts every transaction in its accounts, whoever paid.
- Gaps: G23 (real receipt fixtures, Low) open; next free G25 (G24 used).
- Questions: Q30 (connector's vault: one sealed file with AES-256-GCM under HKDF-SHA256 of the 12 words, or SQLCipher; Low) open; Q1–Q29 answered; next free Q31.
- gaps.md ranks: High blocks the first release, Med needed before it, Low can follow (REVIEW.md §1 reads "next release").

## Found while checking

Unverified: noticed by the checker while reading the documents, covered by no claim above, and
not yet judged by anyone else (docs/REVIEW.md §8). Line numbers are those of `6916954`.

### D1-F1: The phone PWA "comes later" with no L id, as D1-4 and D1-5 describe for other items

- **Kind:** CLAUDE.md rule (later work has lasting ids) / the same thing classed twice.
  **Severity:** Low.
- **Req:** S12.8, R3 (desktop only); `later.md` (preamble).
- **Where:**
  - `out-of-scope.md:10–11`:

    ```text
    gifts. State 529 deduction rules. Tax filing or tax computation. Running a relay for links. Phone support in the web app: a
    mobile PWA with a narrower, focused set of features comes later, as its own piece of work.
    ```

  - `README.md:116`: "Phones will get a separate, focused PWA later, not the whole web app
    (S12.8, [out of scope](out-of-scope.md))."
- **What goes wrong:** the PWA is called later work and is listed as out of scope, and no L
  item holds it (`later.md` is L1–L12), so it has the two-way classing D1-5 raises for coins
  and exchange APIs, and a unit can't tell whether it is scheduled.
- **Remedy:** decide it with D1-5: an L item for the PWA, or "later" dropped from the three
  places that say it.

- **Check:** rejected. Already D2-25 (`docs-2-platform.md`: "A relay and the phone PWA are 'later' and 'not now', linked to out of scope; neither has an L id"), which quotes the same `out-of-scope.md` and README lines and the same missing L id; DC-4 joins it with D1-5. Nothing here that D2-25 does not hold.

### D1-F2: S9.6 cites S8.16 for the tax book's filers; filers are S8.14.1

- **Kind:** reference. **Severity:** Low.
- **Req:** S9.6, S8.14.1, S8.16.
- **Where:** `S9-receipts.md:33–34`: "a tax document's file by the tax book's filers (S8.16)";
  `S8-taxes.md:69` (S8.14.1) is "**Filers**: one user, or two who are spouses (S10.10.4)…" and
  S8.16 (`:132`) is "**Tax documents**".
- **What goes wrong:** the reference points at the section about the documents, which says who
  issued them and where they are kept, not who the filers are or who else may see the tax
  book (S8.14.3); a reader following it finds no rule for the sentence's subject.
- **Remedy:** "by the tax book's filers (S8.14.1)", or, with D1-25's remedy, by whoever can
  read the tax book (S8.14.3, S10.3.1).

- **Check:** corrected. **Severity now:** Low. Scope narrowed. The sentence at `S9-receipts.md:33-34` is about "a tax document's file", and S8.16 (`S8-taxes.md:132`) is the section on tax documents, so its citation is not wrong; what the sentence lacks is a pointer to who the filers are (S8.14.1, `:69`) and who else reads the tax book (S8.14.3). That is D1-25's finding about the same sentence, and D1-25's remedy ("whoever can read the tax book") rewrites it, so this folds into that remedy: cite S8.14.3 there.
