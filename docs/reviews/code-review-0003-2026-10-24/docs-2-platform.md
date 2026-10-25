# Code review 3, Phase 1: block docs-2-platform

**Block:** `docs-2-platform` (docs/REVIEW.md §5). **Commit read:** `6916954` (the working tree
equals it for these files). **Started:** Oct 24, 06:54 PM (Chicago). **Checking:** quick; every
claim is at 0 confirmations.

**Read whole:** `docs/requirements/README.md` (R1–R3 and its tables), S10–S18
(`S10-users-and-sharing.md`, `S11-linked-servers.md`, `S12-web-ui.md`, `S13-architecture.md`,
`S14-storage-and-secrets.md`, `S15-encryption-and-master-key.md`, `S16-settings.md`,
`S17-implementation.md` and its ten item files `S17-implementation-01` … `-10`,
`S18-connector.md`), `out-of-scope.md`, `rejected-ideas.md`.
**Searched, not read whole:** `docs/mockups/MoolaKata-mock.html` (526 KB), by the screens,
labels, buttons, dialogs, states and `GUIDES` entries of S10–S18.

Line numbers are the file's at `6916954`.

## Claims

Each claim: kind, severity (High, Med, Low as `gaps.md` ranks them), confirmations (0 for
all: a quick review), status (open), the requirement, the lines quoted, what goes wrong,
remedy and alternatives. All rest on reading alone.

### D2-1: A receipt over about 20 MB can't cross a link, though receipts may be 25 MB by default and up to 100 MB

- **Kind:** contradiction within the block. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S13.5, S13.7.6, S16.10, S11.5.1, S11.9.6.
- **Where:**
  - `S13-architecture.md:50–52`: "Each call connects within 10 seconds and waits at most 20
    seconds for each read, and every answer is cut off past 20 MB, whether or not it announces
    its length."
  - `S13-architecture.md:123–125`: "JSON bodies up to 1 MB (a linked server's up to 20 MB,
    `docs/link-protocol.md` §1.4), uploads up to the size in Settings (25 MB by default)".
  - `S16-settings.md:46`: "**Receipts**: the size limit (25 MB by default, 1 to 100)".
  - `S11-linked-servers.md:206–207`: "use one streaming format, so a 25 MB receipt is never
    held whole in memory"; `:39–40`: "each exchange carries both directions, receipts included
    (the side that calls sends its own receipts' bytes in it)".
- **What goes wrong:** Alice uploads a 24 MB scan of a closing statement as a receipt (allowed:
  the default limit is 25 MB) on an account shared with *Include receipts* to her parents'
  server. When that server pulls the receipt (`file` in the link protocol), the answer is
  sealed (larger still: a header and 16 bytes per 64 KiB chunk) and is cut off past 20 MB by
  S13.5's ceiling, so the fetch fails at every pull; sent the other way it is a request body
  past S13.7.6's 20 MB. An admin who raises the receipt limit to 100 MB makes more receipts
  that can never cross. Nothing says what the receiving side shows for such a receipt, or
  whether the failure holds back the change that names it.
- **Remedy:** S13.5 and S13.7.6 exempt a link's receipt transfer from the 20 MB ceiling, with a
  ceiling of its own tied to S16.10's limit (or the receipt crosses in parts, as S11.4's
  changes do over 4 MB). Block 3 compares `link-protocol.md` §1.4 and §4.3.
- **Alternatives:** cap S16.10 at 20 MB less the sealing overhead; or say that a receipt over
  the link's ceiling crosses as its record only, marked *too large to send*.
- **Check:** corrected. The fetch direction holds: S13.5 cuts off every answer past 20 MB
  (`link-protocol.md` §1.4 repeats it) and `file` answers with the sealed receipt, so a receipt
  over about 20 MB can't be fetched. The other direction is overstated: a receipt's `deliver`
  body is `application/octet-stream`, not JSON, so S13.7.6's 20 MB for "a linked server's" JSON
  bodies need not apply (its uploads "up to the size in Settings" could cover it), and §1.4's
  "Bodies are JSON" is silent on it. Scope is the `file` answer, with the `deliver` body
  undecided; severity unchanged (Med). Remedy adds that S13.7.6 or §1.4 state the ceiling for a
  receipt's body.

### D2-2: Whether a tax book's document files cross a link: S11.4 and milestone 5 say yes, S11.5.1 and L6 say later

- **Kind:** the same thing specified twice, differently (and mockup). **Severity:** Med.
  **Conf:** 0. **Status:** open.
- **Req:** S11.4, S11.5.1, S17.9.5.8, L6.
- **Where:**
  - `S11-linked-servers.md:69–70`: "The snapshot holds each shared item as S11.3.1 says (for an
    account: balances, holdings, positions, transactions and series), and receipts and
    documents when the share includes them."
  - `S11-linked-servers.md:91–92`: "A tax book's document files come later ([later
    work](later.md), L6)."; `later.md:56–57` (L6): "a tax book's document files crossing a link
    with Include receipts (S11.5.1)".
  - `S17-implementation-09-milestones.md:125–127` (milestone 5, part 8): "receipts and tax
    documents shown from the copy through decryption".
  - Mockup, the Share dialog (`MoolaKata-mock.html:1793`): "Include receipts · Sends its
    receipts (a tax book's documents too) and the text read from them to ${srv}."
- **What goes wrong:** a filer shares the 2026 tax book with their CPA on a linked server and
  ticks *Include receipts*. By the Share dialog and S11.4 the W-2 and 1099 PDFs cross; by
  S11.5.1 they stay home until L6. The unit for links (and its privacy check) can't tell
  which behaviour is right, and a tax document is among the most sensitive files a household
  holds.
- **Remedy:** decide one. If L6 stands: S11.4 says "receipts when the share includes them",
  S17.9.5.8 says "receipts", and the mockup's line drops "(a tax book's documents too)". If
  they cross: L6 loses that clause and S11.5.1 says so. **Needs the user** (which).
- **Alternatives:** none beyond the two.
- **Check:** confirmed. S11.5.1 and `later.md` L6 say a tax book's document files come later;
  S17.9.5.8 (milestone 5, part 8) and the mockup's Share dialog (`MoolaKata-mock.html:1793`) say
  tax documents cross. S11.4's "receipts and documents" is ambiguous (the link protocol's `docs`
  are item documents), so the milestone and the mockup carry the contradiction.

### D2-3: `tls` mode is "for testing" (S13.3, S15.1.7, S16.15), yet the TrueNAS catalog apps fix `tls` mode for real households

- **Kind:** contradiction within the block. **Severity:** Med. **Conf:** 0. **Status:** open.
- **Req:** S13.3, S15.1.7, S16.15, S17.8.3.4.
- **Where:**
  - `S13-architecture.md:19–20`: "**`proxy`** is the expected setup. **`tls`** is for testing on
    a local network".
  - `S15-encryption-and-master-key.md:62–64`: "the `tls/` pair in the data directory in `tls`
    mode (S13.3), which is for testing: being plain, it protects the listener, and a phrase
    typed through it, only from those who hold no copy of the data directory".
  - `S16-settings.md:94`: "*Not a section*: `tls` mode is for testing (S13.3)".
  - `S17-implementation-08-packaging.md:82`: "**What the templates fix**: `tls` mode, its
    configuration in `MOOLAKATA_CONFIG`"; `:63–67`: the server's form offers "a certificate
    from **System › Certificates**, or none for the server's own".
- **What goes wrong:** the catalog is the install path the household is meant to take
  (S17.8.2, `S17-implementation-08-packaging.md:46`: "Catalogs make the install a form rather
  than a file"), and every install from it
  runs the mode three sections call testing-only, with the recovery phrase typed through a
  listener whose key S15.1.7 calls fit for testing. Either the catalog installs something the
  requirements don't support, or the "testing" wording is out of date and S15.1.7's caveat
  needs saying to every catalog household (and in the catalog's notes). Not withheld: it names
  no weakness the public documents don't already state (S15.1.7 says the pair is plain); it is
  a disagreement on which mode real installs use.
- **Remedy:** decide whether `tls` mode is a supported production mode. If yes: S13.3, S15.1.7
  and S16.15 say "`tls` serves a household that runs no proxy (the TrueNAS catalog's apps)",
  and S15.1.7 says what the plain pair means there and that a certificate from System ›
  Certificates is the better choice. If no: the catalog's templates run `proxy` mode behind
  TrueNAS's own proxy. **Needs the user.**
- **Alternatives:** keep "testing" and add an S17.8.3.4 sentence that the catalog is the one
  exception, with why.
- **Check:** confirmed. S13.3, S15.1.7 and S16.15 call `tls` mode testing-only; S17.8.3.4 says
  the catalog's templates fix `tls` mode and S17.8 makes the catalog the install form. No
  sentence makes the catalog an exception.

### D2-4: S11.7's list of a link's states leaves out *broken* and the request waiting for approval

- **Kind:** contradiction within the block (and mockup). **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S11.7, S11.6, S11.1.2.
- **Where:** `S11-linked-servers.md:102–104`: "lists each link: the peer's name and address,
  its fingerprint, state (active, paused until…, unreachable since…, ended)"; `:99–101`: "a
  `not-linked` answer … marks the link broken and alerts admins"; `:16–17`: "B's link waits
  for the approval"; mockup `MoolaKata-mock.html:1605–1607` shows the states *syncing*,
  *broken*, *unreachable since Oct 15* (its certificate changed, with **Accept it**), *paused
  until …* and *wants to link* (**Reject** · **Approve**).
- **What goes wrong:** the states a unit checks Settings › Linked servers against are four;
  the requirements themselves move a link into two more (*broken*, a request waiting for the
  admin's approval on A, *pending* on B as `link-protocol.md` §4.1.3 calls it), and the mockup
  shows a fifth (*syncing*). Which state a link with a changed certificate shows is not said.
- **Remedy:** S11.7 lists every state and what moves it: *requested* (A, with **Approve** and
  **Reject**), *pending* (B), *active*, *syncing* (the progress of S11.7.1), *paused until…*,
  *unreachable since…* (and the certificate-changed case with **Accept**), *broken*, *ended*.
- **Check:** confirmed. S11.7 lists active, paused, unreachable and ended; S11.6 moves a link to
  broken and S11.1.2 has B waiting for approval; the mockup (`:1605–1607`) shows syncing,
  broken, unreachable, paused and *wants to link*.

### D2-5: The linked copy's database holds five of the eight shareable kinds; portfolios, projections and people have no place

- **Kind:** contradiction within the block. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S11.9.1, S10.3, S12.10.3.4.
- **Where:** `S11-linked-servers.md:129–132`: "shared.db SQLCipher: accounts, holdings,
  positions, transactions, series, budgets, gift plans and gifts, giving plans, tax books,
  receipt records, the text read from receipts, thumbnails, and what has been applied";
  `S10-users-and-sharing.md:103–104`: "any of the eight kinds can also be shared with named
  users of a linked server"; `S12-web-ui.md:190–193`: the window shows "Portfolios,
  Positions …, Transactions, Projections (with their charts)".
- **What goes wrong:** a portfolio, a projection or a private person shared to a linked server
  has nowhere listed to live in the copy, so a reader may build the copy without them, or put
  them in the main database, which S11.9.1 forbids ("never in the main database").
- **Remedy:** the list in S11.9.1 adds portfolios (with their computed series), projections
  (inputs, results, tracking) and people (name, birthday, relationships).
- **Check:** confirmed. S11.9.1's `shared.db` list names accounts, holdings, positions,
  transactions, series, budgets, gift plans, giving plans, tax books and receipt records;
  S10.3.3's table has eight kinds, and portfolios, projections and persons have no place in it.

### D2-6: Link pulls are "hourly by default", and nothing sets another interval

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S11.4, S11.7, S16.9.
- **Where:** `S11-linked-servers.md:67–68`: "the receiving server **pulls a snapshot** of each
  linked share on a schedule (hourly by default, and on demand)"; S16.9 (`S16-settings.md:41–45`)
  lists the link address, the links, each copy's state and **Release linked keys after**, and
  no interval.
- **What goes wrong:** "by default" promises a setting that no section, the mockup or
  `link-protocol.md` §4.3.1 ("hourly and when an admin presses Pull now") has. A unit can't
  say whether a fixed hour is right.
- **Remedy:** "hourly, and on demand", or a **Pull every** field in S16.9 with its range.
- **Check:** confirmed. S11.4 says "hourly by default"; S16.9 has no interval, and
  `link-protocol.md` §4.3.1 and S17.9.5 say "hourly and" on demand with no setting.

### D2-7: What a link's audit records goes where S12.10.5 says nothing from a linked household goes, and the mockup's Activity names a linked account

- **Kind:** contradiction within the block (and mockup). **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S11.8, S12.10.5, S11.3, S11.9.1.
- **Where:** `S11-linked-servers.md:115–118`: "each pull is recorded on both sides (who, when,
  which shares, how much changed) … The receiving side records who viewed linked data, and
  every unlock (who), failed unlock, release …"; `S12-web-ui.md:202–203`: "**Never mixed**:
  nothing from a linked household appears in this household's lists, totals, charts, search,
  portfolios, budgets, taxes or Activity."; `S11-linked-servers.md:48–50`: the receiving admin
  sees each share "only as its kind, its owner's display name, who it names and the date …:
  its name and figures stay inside the encrypted linked copy"; mockup
  `MoolaKata-mock.html:1570`: Activity row "MoolaKata · pulled 2 linked shares from
  griffin-parents · Mom's Retirement".
- **What goes wrong:** S11.8's records have no stated home but Activity (R3.8 calls Activity the
  audit), which S12.10.5 bars. The mockup puts them in Activity and names the linked account
  ("Mom's Retirement"), a name S11.3 and S11.9.1 keep inside the encrypted copy, so the main
  database couldn't even hold it while the copy is locked.
- **Remedy:** S11.8 says where its records go (this household's Activity, for admins and the
  people the shares name) and that they name kinds, owners and counts, never an item's name;
  S12.10.5 says "Activity, but for S11.8's records"; the mockup's row reads "pulled 2 linked
  shares from griffin-parents" with *a linked account* in the About column.
- **Check:** confirmed. S11.8 records pulls and views with no home stated; S12.10.5 bars linked
  data from Activity; the mockup's Activity row (`:1570`) reads "pulled 2 linked shares from
  griffin-parents" about *Mom's Retirement*, an item name S11.3 keeps inside the encrypted copy.

### D2-8: The mockup's link invitation says it holds "no secret"; S11.1.1's code holds a one-time secret

- **Kind:** mockup against its section. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S11.1.1.
- **Where:** `S11-linked-servers.md:8–11`: "a one-time **link code** (valid 24 hours, `mkl1.…`)
  that holds A's link address, the fingerprint of A's link key, a one-time secret, of which A
  keeps only a hash"; mockup `MoolaKata-mock.html:2085–2087` (**Invite a server to link**):
  "It holds this server's link address and key fingerprint; no secret."
- **What goes wrong:** an admin told the code holds no secret may paste it into a chat or a
  ticket; whoever uses it first joins (the fingerprint comparison is the guard, but the
  dialog undersells the code).
- **Remedy:** the dialog says "It holds this server's link address, its key's fingerprint and
  a one-time secret: pass it only to their admin."
- **Check:** corrected. The contradiction holds (S11.1.1's code holds a one-time secret; the
  dialog at `:2085` says "no secret"), but "whoever uses it first joins" overstates it: S11.1.2
  has A's admin compare fingerprints and approve before anything crosses, which the dialog's own
  notice says. Severity unchanged (Low); the harm is an admin who handles the code carelessly,
  not an unapproved join.

### D2-9: The mockup's linked household window has no Projections

- **Kind:** mockup against its section. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S12.10.3.4.
- **Where:** `S12-web-ui.md:189–193`: "the screens for the kinds shared with you, **every screen
  and tab of each** …: Dashboard …, Accounts, Portfolios, Positions …, Transactions,
  Projections (with their charts), Budgets …, Gifts, Giving …, Taxes and Receipts"; mockup
  `MoolaKata-mock.html:2766`: `PEER_NAV` lists dashboard, accounts, portfolios, positions,
  transactions, budgets, gifts, giving, taxes, receipts, and `PEER_SCREENS` has no projections.
- **What goes wrong:** the design reference has no screen for a shared projection in the
  window, so the generated mockup and the app have nothing to match.
- **Remedy:** the mockup adds Projections to the linked window's navigation and screens.
- **Check:** confirmed. S12.10.3.4 lists Projections among the screens; `PEER_NAV` (`:2766`) and
  the keys of `PEER_SCREENS` have no projections.

### D2-10: The mockup puts Alerts before Users and Groups and Settings, and Imports before Bitcoin

- **Kind:** mockup against its section. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S12.2, S16 (preamble).
- **Where:** `S12-web-ui.md:28`: "**Navigation** (in this order)", with 13 Activity, 14 Users and
  Groups, Settings (admins), 15 Alerts (`:69–71`); mockup `MoolaKata-mock.html:661–667` and
  `:2748`: `NAV` ends Activity, Alerts, then an *Admin* heading with Users and Groups and
  Settings. `S16-settings.md:4–5`: "In the order below, except Storage (17) … and Connector
  (18)", so Bitcoin (7) comes before Imports (8); mockup `:2823`: `SETTINGS_SECS` has
  `imports` before `crypto`.
- **What goes wrong:** two orders the requirements fix differ from the design reference; the
  app follows one and a unit checks it against the other.
- **Remedy:** choose the order (the mockup's admin group at the foot is the more usual one) and
  make S12.2 or the mockup match; the same for Imports and Bitcoin.
- **Check:** confirmed. S12.2 puts Users and Groups and Settings (14) before Alerts (15); the
  mockup's `NAV` has Alerts above its Admin group. S16 puts Bitcoin (7) before Imports (8);
  `SETTINGS_SECS` (`:2823`) has `imports` before `crypto`.

### D2-11: What Profile holds: S12.2.16 leaves out Connections and the bitcoin unit, milestone 1 adds a theme, and the mockup shows the bitcoin unit twice

- **Kind:** contradiction within the block (and mockup). **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S12.2.16, S18.6.4, S1.6.4, S17.9.1.4, S12.1.1.
- **Where:** `S12-web-ui.md:72–74`: "the user tile opens **Profile** (name, sex, birthday,
  relationships (S10.10), email, avatar, password, two-step, alert emails, time zone (S14.9),
  assumptions for projections (S6.3), access tokens) and **Sign out**"; `S18-connector.md:265`:
  "**Profile › Connections** lists a user's own"; `S1-accounts.md:245`: "Each user chooses in
  Profile" (BTC or sats); `S17-implementation-09-milestones.md:18–19`: "Profile (time zone,
  theme)"; `S12-web-ui.md:8–10`: the theme is the sidebar's button, which "a click moves to the
  next" (and S17.3.7: the browser remembers it); mockup `MoolaKata-mock.html:1674`: Profile has
  both **Bitcoin in** and **Bitcoin amounts**, two selects for the same choice, each with a
  guide heading (`:2566`, `:2568`).
- **What goes wrong:** S12.2.16 reads as the whole list, so a unit finds Connections and the
  bitcoin unit "untraced" there; milestone 1 asks for a theme in Profile that no section puts
  there (it is a per-browser button); the mockup's duplicate field is copied into the app.
- **Remedy:** S12.2.16 adds Connections (S18.6.4) and the bitcoin unit (S1.6.4); S17.9.1.4 says
  "Profile (time zone)"; the mockup keeps one bitcoin-unit field and one guide heading.
- **Check:** confirmed. S12.2.16's list omits Connections (S18.6.4) and the bitcoin unit
  (S1.6.4); S17.9.1.4 says "Profile (time zone, theme)" while S12.1.1 makes the theme the
  sidebar's button; the mockup's Profile has both **Bitcoin in** and **Bitcoin amounts**
  (`:1674`) with two guide headings (`:2566`, `:2568`).

### D2-12: The mockup offers fixed choices where S16 sets ranges

- **Kind:** mockup against its section. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S16.3, S16.9, S16.10, S16.16.
- **Where:** `S16-settings.md:25–27`: idle lifetime "8 hours by default, 1 to 168", absolute "30
  days, 1 to 365", lockout "10 failures, 3 to 100, for 15 minutes, 1 to 1,440"; `:44–45`:
  **Release linked keys after** "5 minutes to 24 hours"; `:47`: jobs "1 by default, at most 4";
  `:96–97`: alerts "48 hours by default, 1 to 336". Mockup `MoolaKata-mock.html:1640`: **Idle
  timeout** select of 1 hour, 8 hours, 24 hours; **Longest session** 7, 30, 90 days;
  **Lockout** 5 minutes, 15 minutes, 1 hour; `:1601–1623` **Release linked keys after** 15 minutes, 1 hour, 4 hours unused;
  `:1645` **Jobs at a time** 1, 2, 4; `:1651` **Alert when a source has failed for** 24, 48,
  72 hours, 1 week.
- **What goes wrong:** the design reference shows selects where S16 asks for a number in a
  range; the app built from it can't take 12 hours or 3 jobs, and the range checks S16 names
  have no field to apply to.
- **Remedy:** the mockup's fields become numbers (or durations in S12.13's grammar) with S16's
  ranges in their hints, or S16 names the choices.
- **Check:** confirmed. The mockup offers idle 1/8/24 hours, longest 7/30/90 days, lockout
  5/15/60 minutes, release 15 minutes/1 hour/4 hours, jobs 1/2/4 and alert 24/48/72 hours/1
  week; S16 sets ranges (1 to 168, 1 to 365, 1 to 1,440, 5 minutes to 24 hours, at most 4 jobs,
  1 to 336).

### D2-13: Settings › Key storage's **Test** is never specified, and the section is called read-only beside five buttons

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S16.13.
- **Where:** `S16-settings.md:64–65`: "**Key storage** (S15): read-only but for **Verify key**
  and the rotation reminder's period"; `:74–79`: "Buttons: **Verify key** …, **Test** and
  **Re-encrypt at the next restart**, … **Cancel** withdraws one scheduled", and **Forget**
  (`:68`) and **Remove** (`:69`). Mockup `MoolaKata-mock.html:1665`: **Test** answers "Key
  storage answered: unwrapped the data key and opened a test secret".
- **What goes wrong:** no section says what **Test** does, who may press it, or what it
  records; the mockup's toast is the only account. "Read-only but for" two controls is
  contradicted by Forget, Remove, Re-encrypt and Cancel.
- **Remedy:** S16.13 says what **Test** checks (the data key in memory opens a secret and the
  database, nothing written) and drops "read-only but for …", or says "read-only but for the
  controls below".
- **Check:** confirmed. A search of S15 and S16 finds no sentence on what **Test** does; only
  the mockup's toast (`:1665`) says. S16.13 says "read-only but for **Verify key** and the
  rotation reminder's period" and then lists Forget, Remove, Test, Re-encrypt and Cancel.

### D2-14: S13.7.2, "one place for the rules", leaves out two actions other sections put behind the password again

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S13.7.2, S18.5.4, S16.18, S10.1.6.4.
- **Where:** `S13-architecture.md:82–83`: "**Security policies**. One place for the rules every
  request passes through; other sections refer here."; `:93–101` lists the actions that need
  the password again: "… pairing, confirming or unpairing the connector, sealing a
  Connection's credentials or changing its server's address, … changing the password, the
  email address or two-step …". `S18-connector.md:248–249`: "until an admin accepts the new
  address in Settings › Connector (the password again)"; `S10-users-and-sharing.md:53–57`: "an
  **admin's reset** in Users … Each needs the password again under S13.7.2."
- **What goes wrong:** accepting the connector's new address is not in S13.7.2's list, and an
  admin resetting *another* user's two-step is "changing … two-step" only on a generous
  reading. A unit that checks S13.7.2's list route by route passes both without the check.
- **Remedy:** S13.7.2 adds "accepting the connector's new address" and "resetting a user's
  two-step".
- **Check:** confirmed. S13.7.2's list has pairing, confirming and unpairing the connector but
  not accepting its new address, which S18.5.4 puts behind the password again; S10.1.6.4 puts an
  admin's two-step reset behind it under S13.7.2, which the list names only as "changing …
  two-step".

### D2-15: The phrase is "never sent over the network beyond the unlock request itself", yet Verify key and Remove send it from a browser

- **Kind:** contradiction within the block. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S15.3.1, S15.6.5, S16.13, rejected idea 20.
- **Where:** `S15-encryption-and-master-key.md:84–86`: "never written to a log, never sent over
  the network beyond the unlock request itself, never shown in the UI after install";
  `:239–241`: "**Verify key** in Settings › Key storage … asks for the whole phrase";
  `S16-settings.md:69–70`: "**Remove**, which asks for the password and the phrase";
  `rejected-ideas.md:74–75`: "The phrase stays the one secret, typed at the locked screen or on
  the host, and kept out of logs and browsers (S15.4.2)."
- **What goes wrong:** three statements of where the phrase goes disagree with two features
  that send it from the browser (S15.6.5, S16.13), and rejected idea 20 says it is kept out of
  browsers while the locked screen is one. A unit reading S15.3.1 strictly flags Verify key.
- **Remedy:** S15.3.1 reads "never sent over the network but to the server itself: at the
  unlock, **Verify key** and **Remove**", and rejected idea 20 reads "kept out of logs, and
  out of browsers but for the locked screen and Settings › Key storage".
- **Check:** confirmed. S15.3.1 says the phrase is never sent "beyond the unlock request
  itself"; S15.6.5 and S16.13 have the browser send it for **Verify key** and **Remove**;
  rejected idea 20 says it is kept out of browsers.

### D2-16: A statement may be up to 200 MB (S16.8), but a user's uploads in flight stop at 100 MB and are held in memory

- **Kind:** contradiction within the block. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S16.8, S13.7.6.
- **Where:** `S16-settings.md:38–39`: "the file types and size accepted for statement import
  (25 MB by default, 1 to 200)"; `S13-architecture.md:124–127`: "at most 100 MB of uploads in
  flight per user … an upload is held in memory, never spooled to a temporary file."
- **What goes wrong:** an admin sets the statement limit to 150 MB; a 120 MB statement passes
  S16.8 and is refused by S13.7.6's 100 MB in flight, with a refusal that names the wrong
  limit. S16.8's range also allows a file the size of the reader's whole memory budget held in
  RAM.
- **Remedy:** S16.8's range stops at 100 (or at S13.7.6's figure), or S13.7.6's ceiling is the
  larger of 100 MB and the statement limit.
- **Check:** confirmed. S16.8 allows 1 to 200 MB; S13.7.6 caps uploads in flight at 100 MB per
  user, held in memory; a single 150 MB upload can't pass.

### D2-17: The lockout of the unlock uses Settings › Sign-in and sessions, which can't be read while the server is locked

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S13.7.5.1, S16.3, S12.14.2, S16.14.
- **Where:** `S13-architecture.md:110–112`: "sign-in, two-step codes, … and the unlock
  (S15.4.3): 10 failures in 15 minutes lock **the address they came from** for 15 minutes";
  `S16-settings.md:26–27`: the lockout "(10 failures, 3 to 100, for 15 minutes, 1 to 1,440)";
  `S16-settings.md:89–91`: "The ranges are in the database, so while the server is locked they
  can't be read"; `S12-web-ui.md:289–290`: "after the lockout of S13.7.5.1 the screen says how
  long to wait".
- **What goes wrong:** S16.14 says what happens to its settings while locked; S16.3 doesn't, so
  the figures the unlock's lockout uses (the defaults, or an admin's 3 failures for a day) are
  unsaid. Not withheld: Low, and the phrase's 128 bits make guessing moot.
- **Remedy:** S16.3 adds "While the server is locked, the unlock uses the defaults: they are in
  the database (S16.14)."
- **Check:** confirmed. S13.7.5.1 locks the unlock's address after 10 failures; the figures are
  Settings' (S16.3), which S16.14 says can't be read while the server is locked, and no sentence
  names what the unlock uses then.

### D2-18: The welcome holds every phrase it shows until one is confirmed, with no bound; the connector's welcome keeps 20 for an hour

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S15.4.4, S12.14.1, S18.11.2.
- **Where:** `S15-encryption-and-master-key.md:158–161`: "makes a master key …, in the
  server's memory only, and shows its 12 words … Every visit makes a new one, and none is
  written until it is confirmed"; `S12-web-ui.md:280–281`: "A reload, or another browser,
  shows a new phrase; only the one confirmed is kept"; `S18-connector.md:384–386`: "a new key
  on every visit, held in memory only (an hour each, 20 at most)".
- **What goes wrong:** the server's welcome keeps keys on offer without the limit its
  connector twin states, so how many and for how long is left to the code; on an uninitialised
  server anyone who reaches it can make it hold any number. Low: only before the key is made.
- **Remedy:** S15.4.4 says the same as S18.11.2: "an hour each, 20 at most".
- **Check:** confirmed. S15.4.4 and S12.14.1 bound neither the count nor the age of the phrases
  on offer; S18.11.2 gives the connector's "an hour each, 20 at most", and no other section has
  such a limit.

### D2-19: A queued email is retried "until its link expires"; an email with no link has no end

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S16.2, S17.9.9.2.
- **Where:** `S16-settings.md:21–24`: "With a host, they go out in the background, queued in the
  database: an email that can't be sent stays queued and is tried again every five minutes,
  until its link expires"; `:19–21` (the mail folder): "a day for the rest, an email with no
  link among them"; `S17-implementation-09-milestones.md:245–247`: "an email waits there until
  it is sent or its link expires".
- **What goes wrong:** an alert email, a *password changed* notice or a new-address notice
  carries no link (S10.1.9). With the SMTP server down for a week, those wait and are retried
  every five minutes for ever, then all go out at once, days late. The mail folder gives such
  an email a day; the queue says nothing.
- **Remedy:** S16.2: "until its link expires, or a day for an email with no link", as the mail
  folder has it.
- **Check:** confirmed. S16.2 retries a queued email "until its link expires"; S16.2's mail
  folder gives an email with no link a day; S10.1.9's alert, notice and password-changed emails
  carry no link.

### D2-20: S14.1.5 cites `schema.md` as "(S1)", and S14.10 says no record is ever removed though sessions and tokens are

- **Kind:** reference / contradiction within the block. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S14.1.5, S14.10, S13.4, R1.24.
- **Where:** `S14-storage-and-secrets.md:27–30`: "**Soft deletes**: records are never removed.
  … [`schema.md`](schema.md) (S1) sets the fields, the views and the few exceptions.";
  `:92–93`: "records are never removed: not records, soft-deleted records (`schema.md` §4) or
  Activity"; `S13-architecture.md:35–36`: "an hourly prune that removes expired sessions and
  one-time tokens (`schema.md` §4.4.1)".
- **What goes wrong:** "(S1)" reads as the requirements' S1 (Accounts); the soft-delete rules
  are `schema.md` §4. S14.10 states the rule with no exception, while S13.4, R1.24 and
  `schema.md` §4.4 remove sessions, one-time tokens, a secret's old ciphertext, work queues
  and caches outright; a unit checking S14.10 literally flags the prune.
- **Remedy:** "(`schema.md` §4)" in S14.1.5; S14.10 reads "records are never removed, but for
  the exceptions of `schema.md` §4.4".
- **Check:** confirmed. S14.1.5 cites `schema.md` as "(S1)" (`schema.md` §4 holds the
  soft-delete rules); S14.10 says records are never removed with no exception, while S13.4's
  hourly prune removes expired sessions and tokens (`schema.md` §4.4.1).

### D2-21: Unpair "ends the paired connector, never a pairing code still waiting (which it withdraws as well)"

- **Kind:** contradiction within one sentence. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S18.4.4.
- **Where:** `S18-connector.md:219–220`: "**Unpair** (Settings › Connector) ends the paired
  connector, never a pairing code still waiting (which it withdraws as well)".
- **What goes wrong:** "never a pairing code" and "which it withdraws as well" say opposite
  things about a code shown and not yet used. Read one way, an admin who unpairs a lost
  connector leaves a live 24-hour bearer code (S18.4.2) behind; read the other, it is gone.
- **Remedy:** say which: "ends the paired connector, and withdraws a pairing code still
  waiting" (the safer), or "ends the paired connector; a pairing code still waiting stays
  until it expires or is withdrawn".
- **Check:** confirmed. S18.4.4 reads "ends the paired connector, never a pairing code still
  waiting (which it withdraws as well)"; the two halves disagree about a waiting code, and
  S18.4.2 calls such a code a 24-hour bearer secret.

### D2-22: R1.5 says dev mode keeps every rule as strict as production; S17.7 makes the recovery phrase an exception

- **Kind:** contradiction within the block. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** R1.5, S17.7.
- **Where:** `README.md:123–125`: "It uses a self-signed certificate, writes emails to a
  folder, uses canned price feeds and seed data, and keeps every rule as strict as production
  (S17.7)."; `S17-implementation-07-dev-mode.md:5–8`: "The one exception is the recovery
  phrase: a dev server makes its key on first run and keeps the phrase in `web/.dev/phrase`, so
  it unlocks itself at every start".
- **What goes wrong:** the decision a reader trusts first says there is no exception; the one
  there is touches the master key, the thing S15.4.6 says is never in a file.
- **Remedy:** R1.5 adds "but the recovery phrase, which a dev server keeps in a file of its own
  so it unlocks itself (S17.7)".
- **Check:** confirmed. R1.5 says dev mode "keeps every rule as strict as production"; S17.7
  names one exception, the phrase kept in `web/.dev/phrase`, while S15.4.6 says the phrase is
  never in a file.

### D2-23: S17.4 weighs candidates instead of stating the choice; the turned-down ones belong in rejected ideas

- **Kind:** CLAUDE.md rule (rejected ideas go to `rejected-ideas.md`; a statement, not a
  proposal). **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S17.4, R1.14.
- **Where:** `S17-implementation-04-charts.md:6–7`: "Three candidates are worth considering";
  `:9`: "**Apache ECharts** 5/6"; `:11`: "so we'd vendor the full file"; `:23–26`: "**uPlot**
  is the choice if size and a minimal surface matter more than coverage, … **Lightweight
  Charts** is best kept as a possible *addition* for the holding-detail price chart";
  `:27–29`: "Chart.js … was considered".
- **What goes wrong:** the item reads as the case for a decision (R1.14 has made it), with
  conditionals ("is the choice if …", "a possible addition"), an unpinned version ("5/6"), and
  three ideas weighed and turned down that `rejected-ideas.md` doesn't list, so they can be
  raised again (§3.6). "A possible addition for the holding-detail price chart" is L5's
  holding price chart without its id.
- **Remedy:** S17.4 states the choice and its constraints (ECharts, the major version vendored,
  lazily loaded through `app/charts/`); uPlot, Lightweight Charts and Chart.js go to
  `rejected-ideas.md` with their reasons; the price-chart remark cites L5 or goes.
- **Check:** confirmed. S17.4 reads as the case for a choice ("Three candidates are worth
  considering", "is the choice if", "ECharts 5/6", "best kept as a possible *addition*"); R1.14
  has chosen ECharts, and `rejected-ideas.md` has none of uPlot, Lightweight Charts or Chart.js.
  L5 names the holding's detail price chart.

### D2-24: Status and history words in S14, S15 and S17

- **Kind:** CLAUDE.md rule (present tense, no status, no changelog, no approval words).
  **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S14.1.3, S15.6.7, S17.8.3.1, S17.9, S17.10.2.
- **Where:**
  - `S15-encryption-and-master-key.md:253–254`: "Disk encryption on the host is a good habit
    but no longer carries the key" (it once did, with a key file).
  - `S14-storage-and-secrets.md:20–23`: "Until the first release, the revisions may be folded
    into one baseline".
  - `S17-implementation-08-packaging.md:60–62`: "TrueNAS decides what its catalog includes;
    until the apps are in it, **Install via YAML** is the way, and once they are, …".
  - `S17-implementation-09-milestones.md:130`: "**Milestone 6**, what the requirements settled
    after milestone 5"; `:158`: "what the first release still needs"; `:159–161`: "The build has
    no bitcoin node, arm64 machine, second network or Schwab developer account"; `:200–201`:
    "what the second review of the requirements against the code found the first release still
    needs"; `:229`: "the alerts S12.11.1 lists that aren't raised yet"; `:231`: "the Folder
    driver taken out"; `:237–238`: "what the second review's account of its findings … found
    still open"; `:277–279`: "merges into `main` only once all of it is built and the
    requirements have their final approval".
  - `S17-implementation-10-ci-and-releases.md:17–18`: "A new package on ghcr.io starts
    private: after the first release, an owner of MojoKata makes both public, once."
- **What goes wrong:** each records history or a state of the build that will stop being true
  without the requirements changing (S14.1.3 and S17.8.3.1 at a release or a catalog merge;
  S17.9's milestone headings describe how the plan came about rather than what each holds),
  and "final approval" is the approval language CLAUDE.md bars. The Folder driver is named only
  as removed.
- **Remedy:** S15.6.7: "Disk encryption on the host is a good habit, but it carries no key";
  S14.1.3: the folding rule moves to `RELEASE.md` or the handoff; S17.8.3.1: "**Install via
  YAML** works whether or not the catalog lists the apps"; each milestone heading says what it
  holds ("Milestone 6, in nine parts"); "taken out", "aren't raised yet" and "final approval"
  go; S17.10.2's one-time step moves to `RELEASE.md` (its GENESIS steps).
- **Alternatives:** keep S17.9 as a plan (a plan may speak of order) but drop the history
  clauses only.
- **Check:** confirmed. Each quoted clause is in the file as cited: S15.6.7 "no longer carries
  the key", S14.1.3 "Until the first release", S17.8.3.1 "until the apps are in it", S17.9's
  milestone headings and "final approval", S17.10.2's "starts private". Line numbers are within
  a line or two.

### D2-25: A relay and the phone PWA are "later" and "not now", linked to out of scope; neither has an L id

- **Kind:** reference / the same thing classed twice. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S11.2.3, R1.2, S12.8, `out-of-scope.md`.
- **Where:** `S11-linked-servers.md:37`: "3. *(not now)* a relay. MoolaKata does not run one
  ([out of scope](out-of-scope.md))."; `README.md:116–117`: "Phones will get a separate,
  focused PWA later, not the whole web app (S12.8, [out of scope](out-of-scope.md))";
  `S12-web-ui.md:149–150`: "phones will get a separate PWA"; `out-of-scope.md:10–11`: "Phone
  support in the web app: a mobile PWA with a narrower, focused set of features comes later, as
  its own piece of work."
- **What goes wrong:** the same pattern as D1-5 in block 1: "not now" and "later" promise work
  that no L item holds, while the link goes to what MoolaKata does not do. "(not now)" is also
  a status word. A reviewer can't tell whether a relay or a PWA is settled (§3.6) or planned.
- **Remedy:** S11.2.3 drops "*(not now)*" (a relay is out of scope); the PWA gets an L id (L13
  or after) cited from R1.2, S12.8 and `out-of-scope.md`, which keeps "Phone support in the
  web app". **Needs the user** (whether the PWA is planned work), decided with D1-5.
- **Check:** confirmed. S11.2.3 "*(not now)* a relay", R1.2 and S12.8 "later"; `out-of-scope.md`
  lists both the relay and phone support, and `later.md` has L1 to L12 with no PWA item.

### D2-26: The mockup's Watchlist prices ^VIX from Stooq, a rejected source

- **Kind:** mockup against `rejected-ideas.md`. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** rejected idea 13, S4.1, S12.2.12.
- **Where:** `rejected-ideas.md:41–43`: "**Stooq** as the no-key source for daily prices and
  metals spot. Since 2026 its downloads need a key obtained through a captcha …"; mockup
  `MoolaKata-mock.html:1567`: Watchlist row `['^VIX', 'CBOE Volatility Index', …, 'Stooq (EOD)']`.
- **What goes wrong:** the design reference shows a source the requirements turned down, and
  an index (^VIX) that no source of S4 is said to serve.
- **Remedy:** the row names a source S4 lists, or the row goes.
- **Check:** confirmed. `rejected-ideas.md` 13 turns Stooq down; the mockup's Watchlist row
  (`:1567`) names "Stooq (EOD)" for ^VIX; no S4 text names Stooq or a source for index levels
  (S4's VIX mention is about option chains).

## doccheck.txt: the "To read" lines in this block

Judged fine, no claim (each is a button's name or behaviour, not changelog language):
`S11:53` ("after the link is approved", behaviour), `S11:55` ("a user no longer on the list"),
`S11:113`, `S11:117`, `S12:188` (*Lock now*), `S13:173` ("as it now stands"), `S13:221` ("as it
is now (`current`)"), `S15:273` ("will no longer unlock the server", what the restore says),
`S15:371` ("from now on, and no longer unlocks", the rotation's effect), `S15:380` ("no longer
need"), `S17-02:27` ("no longer match", the check), `S17-09:112` (*Lock now*), `S17-09:119`
(*Pull now*), `S17-09:144` ("grouping proposed", behaviour), `S17-09:145` ("capital at risk now
and at open"), `S17-09:156` (*Resume now*), `S18:319` ("what the settings name now"). The one
that is changelog language: `S15:254` "no longer carries the key" (D2-24). Read and found by hand
beyond the list: `S11:37` "*(not now)*" (D2-25), and the status and history clauses of S14.1.3,
S17.8.3.1, S17.9 and S17.10.2 (D2-24). Also judged fine: S12.9's "while the app is being built"
(CLAUDE.md itself names the two mockups that way), rejected idea 13's "Since 2026" (a fact about
Stooq) and rejected idea 20's "where today a stolen copy" (the design compared with the idea).

Phase 0's mechanical problems: none (`doccheck.txt`: 0). Uncited first-level items in this
block, judged as documents only: S10.5, S12.14, S13.1, S14.2, S14.5, S15.1, S15.2, S15.5,
S17.1, S17.10 and S18.2 are specified clearly enough to build and check (S15.2 is a negative,
checked by absence; S14.5 restates S15.3.1 without disagreeing); S14.8 is a pointer to L4;
S16.15 is "not a section" by design; S17.9 is the build plan, not buildable itself (its wording
is D2-24). Whether code builds them is Phase 2's.

## Summary of the claims

| Id | Req | Sev | Kind | In one line |
|---|---|---|---|---|
| D2-1 | S13.5 | Med | contradiction | A receipt over ~20 MB can't cross a link (20 MB answer and body ceilings) though receipts are 25 MB by default, up to 100 |
| D2-2 | S11.5.1 | Med | twice, differently | Tax book document files cross a link (S11.4, S17.9.5.8, mockup) or wait for L6 (S11.5.1); needs the user |
| D2-3 | S13.3 | Med | contradiction | `tls` mode is "for testing" in three sections, yet the TrueNAS catalog fixes it for every install; needs the user |
| D2-4 | S11.7 | Low | contradiction / mockup | A link's states omit *broken* and the request awaiting approval |
| D2-5 | S11.9.1 | Low | contradiction | The linked copy's DB has no place for portfolios, projections or people |
| D2-6 | S11.4 | Low | unspecified | Pulls "hourly by default", with no setting |
| D2-7 | S11.8 | Low | contradiction / mockup | Link audit vs "nothing in Activity"; mockup Activity names a linked account |
| D2-8 | S11.1.1 | Low | mockup | Invitation dialog says the link code holds "no secret" |
| D2-9 | S12.10.3.4 | Low | mockup | Linked window has no Projections |
| D2-10 | S12.2 | Low | mockup | Alerts before the admin entries; Imports before Bitcoin |
| D2-11 | S12.2.16 | Low | contradiction / mockup | Profile omits Connections and BTC unit; milestone 1's theme; BTC unit twice in the mockup |
| D2-12 | S16.3 | Low | mockup | Fixed choices where S16 sets ranges |
| D2-13 | S16.13 | Low | unspecified | Key storage's **Test** unspecified; "read-only but for" beside five buttons |
| D2-14 | S13.7.2 | Low | twice, differently | Re-auth list omits accepting the connector's address and an admin's two-step reset |
| D2-15 | S15.3.1 | Low | contradiction | Phrase "never sent beyond the unlock", yet Verify key and Remove; rejected idea 20 "kept out of browsers" |
| D2-16 | S16.8 | Low | contradiction | Statement limit up to 200 MB vs 100 MB of uploads in flight |
| D2-17 | S13.7.5.1 | Low | unspecified | The unlock's lockout figures while Settings can't be read |
| D2-18 | S15.4.4 | Low | unspecified | The welcome's phrases on offer unbounded; the connector's are 20 for an hour |
| D2-19 | S16.2 | Low | unspecified | A queued email with no link is retried for ever |
| D2-20 | S14.1.5 | Low | reference / contradiction | `schema.md` cited as "(S1)"; S14.10's "never removed" vs the prune |
| D2-21 | S18.4.4 | Low | contradiction | Unpair "never a pairing code … which it withdraws as well" |
| D2-22 | R1.5 | Low | contradiction | Dev mode "every rule as strict" vs the phrase kept in a file |
| D2-23 | S17.4 | Low | CLAUDE.md | Charts item weighs candidates; turned-down ones not in rejected ideas |
| D2-24 | S17.9 | Low | CLAUDE.md | Status and history words in S14.1.3, S15.6.7, S17.8.3.1, S17.9, S17.10.2 |
| D2-25 | S11.2.3 | Low | reference | Relay "(not now)" and the PWA "later" point at out of scope, no L id; needs the user (with D1-5) |
| D2-26 | rejected 13 | Low | mockup | Watchlist ^VIX priced from Stooq |

High 0, Med 3 (D2-1, D2-2, D2-3), Low 23. All at 0 confirmations, open. Withheld: none (D2-3
and D2-17 are judged not to need it, each says why). Needing the user: D2-2, D2-3, D2-25. No
§6 gate claim (none is High); D2-2 and D2-1 touch the links unit (unit 08 in `map.md`) and are
worth deciding before it, and D2-3 before unit 11 (implementation, which holds packaging).

## Claims digest

One line per fact another block could contradict, with its id. Terms, limits and defaults,
states, who may do what, what is sent or stored where, and with what. The README's R1–R3 are
digested in `docs-1-money.md`; the lines below add only what this block's sections lean on.

### README (R1–R3), as this block uses it

- R1.13 / S15: one master key = 12-word recovery phrase, never stored; server locked after every start until an admin enters it (locked screen or host); no key file, no keys process, no external key service.
- R1.18 / R2.10: linked copy = SQLCipher DB + one encrypted file per receipt in its own folder; opens with its access key (12 generated words), never the master key; syncs while locked; key released after an hour unused (S16.9 makes the hour a setting, 5 min–24 h).
- R1.5: dev mode keeps every rule as strict as production (S17.7 excepts the phrase: D2-22).
- R1.6 / S10.2: admins are trusted operators: manage users, groups, Settings; can't be kept out by the app.
- R2.9: a share = one item of the eight kinds, `read` or `write`, to a user, group or named linked users (always `read`).
- R2.21–R2.23, R2.26: connector paired with one MoolaKata; a driver per institution; a Connection = one sign-in, owned by its user; identity key (Ed25519, signs, beside the vault) and sealing key (X25519, public half at MoolaKata, private half in the vault).
- R3.1: outbound calls only to price sources, the bitcoin explorer or node, SMTP, linked servers; the connector calls the institutions its Connections name.
- R3.4: revoking a share ends access on the next request; on a linked server at its next exchange.
- R3.5: a new link carries nothing until something is shared with it.
- R3.6: MoolaKata holds no bank or exchange credentials; the connector's vault, which MoolaKata can neither open nor ask for.
- R3.7: no caches between the DB and a request.
- R3.8: Activity names fields, never values.

### S10 Users, groups and sharing

- S10.1.1: a user: unique username, display name, unique email, optional avatar, argon2id password; sign in with username or email.
- S10.1.1: username 2–32 chars, lowercase letters, digits, `.`, `-`, `_`, starting with a letter or digit; usernames and emails match case-insensitively; display name ≤ 80 chars; email ≤ 254.
- S10.1.1: password rules are S13.7.3's: admin-set minimum (12 by default), a maximum, no common passwords.
- S10.1.2: the first admin is made by the welcome after the key: name, sex, email, password; username `admin`; signed in at once; a terminal-made key shows the same step at the first unlock while there are no users.
- S10.1.3: admins never set passwords; creating a user (name, sex, username, email, groups) emails an invitation; the link works once, 7 days; a new one ends the old.
- S10.1.4: sign-up only when an admin turns it on; needs SMTP and the public URL; optionally limited to email domains; the person gives name, sex, email, username and password, confirms the email, then waits for approval.
- S10.1.4.1: sign-up's answer is the same and takes as long whether or not the address has an account; only a new address gets a link; the link works once, 24 hours.
- S10.1.4.2: confirmed requests under Users and Groups › **Requests** with a badge count; Approve (optionally into a group) or Reject; emailed either way; Activity records request and decision; the request is kept.
- S10.1.5: password reset by emailed link from *Forgot password?*: once, 1 hour; a new request ends the old. Email change takes effect when the link to the new address is opened: once, 24 hours. An admin corrects a user's email only until they join.
- S10.1.6.1: TOTP per RFC 6238: SHA-1, 6 digits, 30-second steps, ±1 step, no step accepted twice; the seed is a secret (S14.4).
- S10.1.6.2: turned on in Profile: QR + key as text, confirmed by a code; then 10 recovery codes shown once: 16 chars of a 31-symbol alphabet (~79 bits), four groups of four, any case or spacing; only hashes kept; Profile shows how many left, warns at 3; **New recovery codes** replaces all.
- S10.1.6.3: a right password gives a two-step token lasting 5 minutes; no session until the code is right; a recovery code works once in place of a code; wrong codes count toward the address lockout (S13.7.5); 5 wrong codes end the token.
- S10.1.6.4: turning it off (Profile) or an admin's reset (Users) removes seed and codes; the reset ends the user's sessions; each, and turning on, is emailed and in Activity, as is a sign-in with a recovery code; each needs the password again.
- S10.1.7: inactive users can't sign in or be added to a share (here or from a link); their shares give nothing; switching off ends sessions at once and shows *account is disabled*; a reactivation request at most once a week, with username and password, counting toward the lockout; users and groups are deactivated, never deleted.
- S10.1.8: admin = member of the built-in **Admins** group; the last active admin can't be removed or deactivated.
- S10.1.9: emails, plain text: invitation, sign-up confirmation and decision, reset, email-change confirmation (new address) and notice (old address, after the change), sign-in from an address not seen in 30 days (addresses kept 30 days on the user; each session records its own), password changed, two-step on/off, recovery-code sign-in, access token made, reactivated, alerts; dev mode writes them to a folder.
- S10.2: an admin sees only what is shared with them, but holds the phrase and host, opens written emails (recorded in Activity with the addressee as owner), resets two-step, chooses the SMTP host and public URL; users are never deleted.
- S10.3: eight shareable kinds, each with one owner: account (transactions, holdings, positions, receipts, a loan's payoff plans, a physical-asset account's items), portfolio, budget, gift plan, giving plan, tax book, projection, person (private person: name, birthday, relationships).
- S10.3.1: `read`: see everything; can't change, attach receipts or re-share.
- S10.3.2: `write`: change what the item holds (for an account: add/edit transactions, import, categorise, attach receipts); never delete it, change its sharing, or see or change its secrets.
- S10.3.3: any kind may be shared to named users of a linked server, always `read`; each server sends its active users (display name, username, email, sex, stable id); groups never sent; a deactivated remote user's shares are suspended; when the link ends, the shares are removed.
- S10.3.3.1: a remote user is a `User` row with `linkId` set; no password, two-step or sessions (a `CHECK` enforces it); fields only from its server.
- S10.3.3.2: only local users can sign in, be in Users and Groups, be group members, be in Admins, be tax-book filers, be a spouse, own anything, receive alerts; a remote user's person is used only for gifts.
- S10.3.3.3: Settings › Linked servers lists each link's users, read only.
- S10.4: the Share dialog: active users, then active groups, then each linked server's people, alphabetical; local: **None · Read · Write**; linked: **None · Read**; **Include receipts** per linked server with anyone at Read, off by default; *via* a group shown; nothing changes until **Save**; removal ends access on the receiver's next request and deletes their annotations (tags).
- S10.5: a group's members hold its shares while in the group and it is active; direct + group gives the higher level.
- S10.6: shared account marks: *shared with me*, owner's avatar, eye (read) or pencil (write); owner sees *shared by me* and a count; filters All, Mine, Shared with me, Shared by me, From linked servers.
- S10.7: a receiver's totals count a shared account only with **Count in my totals** (off by default); a linked server's items never count.
- S10.8: Activity: changes worth showing, who and what, to the people concerned (owner, receivers, admins for users and groups); a receiver whose share is removed keeps that entry; never amounts.
- S10.9: MCP at `/mcp` (Streamable HTTP), read only, never writes.
- S10.9.1: access tokens per user in Profile › Access tokens: name, scope (everything the user can see, or chosen accounts and portfolios), expiry 30 days / 90 days (default) / a year; shown once; format `mkt_<id>.<secret>`; only a SHA-256 hash of the secret kept; sent as a bearer token; the list shows name, scope, expiry, last use, **Revoke**.
- S10.9.2: no write scope; a write share gives a token only read; reads through the user's shares at the moment of the call.
- S10.9.3: never through a token: secrets, Settings, unshared data, linked households.
- S10.9.4: a token works only at `/mcp`, never `/ui/api`; stops when revoked or expired, when its user is inactive, when its user's password is changed or reset; each call in Activity under the token's name; 60 calls a minute per token.
- S10.9.5: tools: `list_accounts`, `get_account_holdings`, `list_transactions` (≤ 500, by account, dates, payee), `list_positions`, `list_portfolios`, `get_portfolio`, `list_budgets`, `get_budget_month`, `list_upcoming_gifts`, `get_giving`, `list_tax_books`, `get_tax_panels`; a chosen-items token is refused by the household tools (budgets, gifts, giving, taxes).
- S10.9.6: JSON-RPC 2.0 over POST, JSON answers, no SSE (GET refused); bearer token; a foreign `Origin` refused.
- S10.10.1: a person: name, sex (*male* or *female*, required), birthday (year optional), `diedOn`; every user is a person; a new local user whose name matches a non-user person becomes that person; a remote user's person joins an existing one only on a local user's confirmation.
- S10.10.2: people are the household's, seen by every local user; the creator may make one private and share it; changed by the person once a user here, by its creator until then, and by an admin.
- S10.10.3: a name matching (case-insensitive) shows the existing person; a private one offers **Ask to share** (an alert to creator and admins); **A different person** needs both birth years, differing.
- S10.10.4: relationship kinds *spouse*, *couple*, *child*, *friend*, *colleague*, *family* (with label), dated; *child* runs parent→child; a user adds their own, an admin any; a spouse needs both confirmations (an admin confirms for a non-user); unconfirmed counts for gifts only.
- S10.10.4.1–3: one spouse at a time; no one their own ancestor; a marriage ends by divorce (end date) or death (`diedOn`); remarriage is a new row; the spouse is read on the sale date for wash sales and on the year's last day for a joint tax book.
- S10.10.5: the family tree is worked out from *child*, *spouse*, *couple* as of a date, never stored.

### S11 Linked servers

- S11.1.1: invitation on A: link code `mkl1.…`, valid 24 hours, one use, holding A's link address, A's link-key fingerprint, a one-time secret (A keeps only its hash), and A's certificate-key fingerprint when the certificate is A's own; **Withdraw** ends it.
- S11.1.2: B enters the code, connects to A, checks A's key against the fingerprint, sends B's address and key signed with it, nothing else; no user list before A's admin approves; A's admin compares B's fingerprint and approves or rejects; B waits for approval (now or at the next exchange).
- S11.1.3: each server holds the other's Ed25519 public key; every call signed over method, path, body hash, timestamp and nonce; refused: bad signature, timestamp > 60 s off, a nonce seen before; a clock refusal is named on the link; the one-time secret crosses once; TLS verified by both sides (public cert against system roots, own cert against the code's fingerprint); a changed certificate key is announced signed with the link key before the next exchange, an unannounced one waits for the admin to accept; signed answers name the caller and request.
- S11.2: links are HTTPS to link addresses = path `/link/` on the server's own address (no port of its own); reachable via one side serving (forwarded port or reverse proxy) or an overlay (Tailscale, WireGuard, ZeroTier; recommended); no relay (out of scope).
- S11.2: a link works if either side reaches the other; each exchange carries both directions, receipts included (the caller sends its own receipts' bytes); a link address is `https`, no query or fragment, never loopback, link-local or cloud metadata; set in Settings › Linked servers, the public URL when unset.
- S11.3: a link carries only what a user shared with named people there, always `read`; the receiving server shows each item only to the people named; the receiving admin sees each share only as kind, owner's display name, who it names and the share date; no re-share, not even to another link.
- S11.3: each exchange from the first after approval sends the active-user list (display name, username, email, sex, stable id) and the household name and avatar; remote users kept as records by id: added, updated in place, soft-deleted when off the list and restored on return; soft-deleted when the link ends; shares keep pointing at the same record.
- S11.3.1: items travel as their screens show them, computed at the source; entries name an account only when it is shared with the same people, else *an account not shared*; the receiver never recomputes and shows the age.
- S11.4: the receiver pulls a snapshot per linked share hourly "by default" (no setting: D2-6) and on demand; versioned, only changes travel; each change sealed by the source to the receiving copy's public key (sent by the receiver at each exchange); beside it, signed, the data kept while locked.
- S11.4: a first full snapshot or a large change travels oldest to newest; a change over ~4 MB comes in parts of whole records up to a date; each change and part signed by the source's link key.
- S11.4: the copy shows its age; pulls run whether or not unlocked; source unreachable → copy stays, marked stale; a removed share or link → the other side deletes the copy at its next exchange, or the receiving admin at once; Pause stops data, never a removal or an end.
- S11.5.1: receipts cross only with **Include receipts** on the share to that link (off by default), with dates, amounts, payees and OCR text; without it only the count of receipts per transaction crosses, and a gift's documents stay home; tax book document files come later (L6) (but see D2-2).
- S11.5.2: never across: secrets, categorisation rules, groups, gifts for a person who is a user of that server, the accounts behind a figure unless shared, anything not shared there; of users, only the active-user list; prices only as computed values with `as_of`.
- S11.6: either admin ends a link on their side; the other side learns at its next call and deletes its copies; only the peer's signed `link-ended` ends a link; a `not-linked` answer marks it broken and alerts admins; ending deletes nothing at the source.
- S11.7: Settings › Linked servers per link: peer name and address, fingerprint, state (active, paused until…, unreachable since…, ended; see D2-4), last pull, flows each way; *Pull now*, *Pause*, *End link*.
- S11.7.1: progress shown as date and quantity (*Up to July 2022 (47 MB of 2 GB)*).
- S11.7.2: Pause stops pulling and answering the peer's pulls for a typed duration (S12.13), `1d` by default; resumes by itself; *Resume now*; a paused link isn't alerted as unreachable.
- S11.7.3: the linked copy's row: changes waiting, when and by whom its key was made, unlocked by whom and until when; *Create the access key*, *Lock now*, *Reset copy*; **Release linked keys after**, 1 hour by default.
- S11.8: audit: each pull on both sides (who, when, which shares, how much changed); each pause and resume on the side that made it; the receiving side records who viewed linked data, every unlock (who), failed unlock, release (unused, Lock now, restart), key made, reset (where these go: D2-7).
- S11.9.1: each link's copy in `links/<random name>/` under the data directory: `shared.db` (SQLCipher: accounts, holdings, positions, transactions, series, budgets, gift plans and gifts, giving plans, tax books, receipt records, OCR text, thumbnails, what has been applied; see D2-5), `receipts/<random-id>.mkr`, `inbox/<sequence>.mks`; never in the main DB; folder named at random, never by link id.
- S11.9.1: the main DB holds only: the link, shared items' ids, kinds, owner's display name and the people named (not names or values), household name and avatar, the copy's public key, folder name, inbox length and newest `as_of`.
- S11.9.2: copy key = random 128 bits, shown once as 12 BIP39 English words (last word a checksum) = the access key.
- S11.9.2.1: made by the receiving admin when the link's first share arrives (Settings › Linked servers › **Create the access key**, password again per S13.7.2); words shown once, admin confirms saving them; pulls into the copy begin then.
- S11.9.2.2: HKDF-SHA256 from the copy key, each under its own label: the database key (SQLCipher raw key, `PRAGMA key = "x'…'"`) and the copy's X25519 private key (public half in the main DB).
- S11.9.2.3: the copy key is never stored, held in memory only while unlocked; no master-key slot.
- S11.9.3: unlocked for the whole server, not per user; asked of someone the copy's shares name when they open its window while locked; checksum and the derived public key checked; nothing reaches the browser; while unlocked, the owner's shares alone decide who sees what; the words without a share open nothing.
- S11.9.3.3: wrong words: 5 in a row → that user waits 15 minutes; at most 20 attempts an hour per copy from all users.
- S11.9.4: released after unused for the set time (1 hour default); *used* = a read for a person (screen or export in the window), not background work; a sweeper every minute; locking closes SQLCipher connections and overwrites the server's key bytes (a release, not guaranteed erasure); also locks at **Lock now** (anyone the copy shares with, and admins in Settings) and at restart; the header shows *unlocked by Alice at 14:05 · locks after an hour unused*.
- S11.9.5: pulls never wait for an unlock; changes written sealed to `inbox/` as numbered files; receipts sealed straight into `receipts/`; the inbox applied in order in one transaction at unlock, each signature checked, the sealed sequence number must follow the last applied; a failed change is set aside and reported and the copy asks for everything; applied files deleted; while unlocked, new pulls applied as they arrive.
- S11.9.5.4: inbox past 1,000 changes or 500 MB → discarded, full snapshot asked for.
- S11.9.5.5: a locked copy shows *synced 5 minutes ago · 12 changes waiting · locked* from the main DB.
- S11.9.6: one streaming format for receipts and inbox changes: header magic+version `MKR1`, one-time X25519 public key, random 32-byte salt, 7-byte nonce prefix, chunk size 64 KiB; key = HKDF-SHA256 over X25519(one-time, copy key) with the salt, label `moolakata link receipt` or `moolakata link change`; each chunk AES-256-GCM, nonce = prefix + 4-byte counter + last-chunk flag; associated data names link, receipt or change, and chunk number.
- S11.9.6.4: `shared.db` records each receipt's file name, length and plaintext SHA-256 (signed by the source); the hash checked as the file is shown, before its last part is sent.
- S11.9.6.5: a linked receipt is streamed through decryption with its type checked from its bytes at arrival and S13.7.7's headers; no plaintext on disk, no temp files, thumbnails in `shared.db`.
- S11.9.6.6: files written under a temp name, synced, renamed before the row commits; a sweeper removes files no row names.
- S11.9.6.7: the AES-GCM-HKDF streaming construction (Tink's), on `cryptography`.
- S11.9.7: a share removed at the source hides the item at the next exchange, no re-keying; new words only if they reach someone who can read the disk.
- S11.9.8: **Reset copy** (admins): deletes the folder, new copy key and words, pulls everything again.
- S11.9.9: MoolaKata backups leave linked copies out; the host's backup carries them encrypted; after a restore the copies are set aside, new access keys made, each pulled in full.
- S11.9.10: a stolen disk or backup, or root while locked, sees only size, number of receipts and arrival times; root or malware while unlocked can read it.
- S11.9.11: SQLCipher via the `sqlcipher3` wheel, a second SQLAlchemy engine per unlocked copy; each copy has its own numbered schema revisions applied at unlock.

### S12 Web UI

- S12.1: one frame around every signed-in screen, from one navigation list; sidebar with household avatar, name, version, DEV pill in dev mode, nav with count badges, user tile with theme button (moon dark, lightbulb light, palette system; click cycles); collapse button; browser remembers.
- S12.1.3: pager page sizes 100, 500, 1000 (kept per browser), "1–500 of 2,624", orange **+N new** pill; every password field has an eye toggle; a dialog masks the content but not the help pane.
- S12.1.4: orange update pill when the server's version changed since load; click reloads.
- S12.2: navigation order: Dashboard, Accounts, Transactions, Portfolios, Positions, Budgets, Projections, Gifts, Giving, Taxes, Receipts, Watchlist, Activity, Users and Groups and Settings (admins), Alerts; the user tile opens Profile and Sign out (mockup order differs: D2-10).
- S12.2.2: account groups on Accounts: Banking, Investing, Retirement, Education, Crypto, Giving, Liabilities, Physical assets; account page tabs Overview, Holdings, Transactions, Positions, Receipts, Reconcile, Sharing, Settings, plus Schedule, Payoff, Contributions, Withdrawals, Goal, Items by type.
- S12.2.16: Profile: name, sex, birthday, relationships, email, avatar, password, two-step, alert emails, time zone, assumptions, access tokens (see D2-11 for Connections and the bitcoin unit).
- S12.3: privacy mode: an eye in the header blurs every amount; the browser remembers.
- S12.4: numbers tabular, right-aligned, `$`; gains green and losses red and signed; abbreviated ($1.2M) in charts only.
- S12.5: every price-derived value shows its age on hover; the header shows the last refresh with a dot amber when stale.
- S12.6: one SSE stream `GET /ui/api/events`: fingerprints and counts only (prices refreshed, import finished, statement read, share received or removed, linked pull done, background task finished, sign-up request for admins, a new alert's count never its title, badge counts, server version); never extends the session; ends after a few minutes; sends the page to sign-in or *account is disabled* when the session ends.
- S12.7: help pane: F1 toggles; dim corner quarter-circle "Show help (F1)"; split up to half the window; guides `web/ui/guides/<screen>.md` and `<screen>-<panel>.md`; per-account-type parts by marker lines; follows focus by heading id from the label; a heading per field, switch and button; screenshots from the mockup (`web/dev.sh help-shots`, dark, 1280 px, PNG 256 colours); terms in `guides/terms.md`, forms in `guides/forms.md`, alphabetical, the mockup carries the same and a test keeps them alike.
- S12.8: everything by keyboard, labelled, WCAG AA, `prefers-reduced-motion`; dark first with light and system; desktop browsers only; English only; charts have a table view.
- S12.9: the hand-written mockup `docs/mockups/MoolaKata-mock.html` and the generated `MoolaKata-app.html` (`web/ui/mockup/build.py`, kept current by `web/check`); `docs/mockups/check.py` opens every screen, tab, Settings section and dialog headless and fails on any error.
- S12.10.1: linked households reached from the sidebar avatar's menu and a **Linked households** card on Accounts; each entry: avatar, name, count of items shared with you, last sync; no names or amounts; a household sharing nothing with you isn't listed.
- S12.10.2: opens `/ui/linked/<link-id>/` with `target="mk-linked-<link-id>"`; same sign-in, signing out in either ends both.
- S12.10.3: the window: the source's avatar and name; sidebar tinted by a per-user colour from a fixed palette; header strip *griffin-parents · read only · synced 41 min ago · unlocked by Alice at 14:05 · Lock now*; every screen and tab of each shared kind, read only (Dashboard, Accounts, Portfolios, Positions as holdings, Transactions, Projections, Budgets, Gifts, Giving, Taxes, Receipts); positions with gains, option trades, a loan's view and items come later (L6); no Settings, Profile, Watchlist, import, sharing or editing; the user tile shows *viewing griffin-parents*.
- S12.10.4: locked: only name, avatar and the request for the access key; returns there if the copy locks while open.
- S12.10.5: nothing from a linked household in this household's lists, totals, charts, search, portfolios, budgets, taxes or Activity.
- S12.11.1.1: admin alerts: a source failed longer than the threshold (48 h default: explorer or node, price source, email, a link's pulls; a clock > 1 minute off says *the clocks disagree*); a failed backup; the bitcoin node's certificate changed; a link's first share waiting for its access key; a link marked broken; the connector locked, silent 15 minutes, or reporting from an unknown address (until accepted or unpaired); a Connection needing a sign-in or failing; the yearly phrase check (a year after the phrase last opened the keyring by unlock, Verify key or `keys verify`, or after the key was made); the master key's rotation due; the receipt reader without Landlock; an admin's alert about another's account names owner and source, never the account's name or figures.
- S12.11.1.2: owner alerts: their wallet's explorer or node failing past the threshold; a statement or import overdue; a reconciliation mismatch open 7 days; a Connection for their account needing a sign-in or failing; a wallet transaction the chain dropped; an option past expiry not settled; a holding valued from a statement > 90 days old.
- S12.11.1.3: every user: a request to share a private person they created (to creator and admins); an occasion entering its lead time; an option expiring within a week; a pledge due; an active projection falling behind; the active budget's cash before payday.
- S12.11.2: one alert per cause; the alerts task runs every 15 minutes and after any other background task but the copies' sweeper; open while the cause lasts, resolved by itself; an admin who owns what failed gets it once, as owner; a user can dismiss for themselves; resolved alerts listed 90 days.
- S12.11.3–4: Alerts screen: open first, newest first, then resolved; opening marks seen; the badge counts open unseen alerts, live through SSE with a toast.
- S12.11.5: email per user: each alert (one email when it opens), daily summary (time in Settings › Alerts, 07:00 default, user's time zone; none on an empty day), none; admins start on each alert, others on daily summary; alert emails name kind and thing, never amounts.
- S12.12: amounts in the browser are `Dec` (`app/dec.js`): a BigInt at a scale; arithmetic with plain numbers throws.
- S12.13: durations: parts of a whole number and a unit `w`, `d`, `h`, `m`, largest first, each once, spaces optional (`1d`, `90m`, `2w 3d 4h`); `app/duration.js` and `moolakata/duration.py`; shown back as typed.
- S12.14.1: the welcome, while no keyring, on every `/ui` address: **Show my recovery phrase** (12 numbered words + fingerprint), **I've written them down** asks for three by number ("check your sheet" when wrong, **Back** shows them again), then the key is made, the server unlocked, **Set up the admin account**, then Dashboard; a reload or another browser shows a new phrase.
- S12.14.2: the locked screen, keyring but no key, on every `/ui` address: a masked field for the 12 words with the eye, autocorrect/autocapitalize/spellcheck/autocomplete off, **Unlock**, a line with the host command; re-encryption progress shown at unlock; a wrong phrase refused at the field; lockout per S13.7.5.1; then sign-in or Set up the admin account.

### S13 Architecture

- S13.1: one HTTPS address: `/` → `/ui`; `/ui/*` app, `/ui/api/*` API; `/link/*` linked servers; `/connector/v1/*` the connector's reports and files; `/mcp` agents; `/healthz`; `/demo` the clickable mockup to anyone, sandboxed with an opaque origin, no cookie or API reach.
- S13.2: `/ui/api` uses server-side sessions (random token stored hashed, HttpOnly, Secure, SameSite=Strict, `Origin` check on every change); `/link` signed peer requests; `/connector` the paired connector's signed requests; none accepted on another's path; `/mcp` only access tokens.
- S13.3: port 37373 on all container interfaces; modes in `moolakata.toml`: `proxy` (plain HTTP behind haproxy/Caddy/nginx; forwarded headers trusted only from configured proxy addresses, never a whole range) or `tls` (own HTTPS with HTTP/2; forwarded headers ignored); `proxy` is expected, `tls` "for testing" (D2-3); `tls` with no certificate makes a self-signed one in `tls/` (key mode 0600), unencrypted, naming the server, `localhost` and `[tls] names`, remade when the list changes; client = right-most `X-Forwarded-For` address not a trusted proxy; `[server] host` sets the listen address (all by default).
- S13.4: background tasks in the server process: price refresh, bitcoin reads, link pulls, option expiry, backups, email, alerts and the daily summary, receipt and statement reading (own worker process), the copies' sweeper, the overdue-statement and silent-connector check, the host-command events queue (every few minutes), an hourly prune of expired sessions and one-time tokens; recurring transactions found when shown; each records last run and error; thread pool with per-provider rate limits; never block a request.
- S13.5: one httpx client with an egress guard: only enabled price sources' hosts, the bitcoin explorer or node, SMTP, links; never loopback, link-local or cloud metadata unless allowed by name, and only the Email and Bitcoin hosts typed in Settings are allowed by name (a link address never); connects to the address checked (no second lookup); SMTP via stdlib past the same guard; each dependency audited for its own reach; connect ≤ 10 s, each read ≤ 20 s, answers cut off past 20 MB; SMTP waits 20 s.
- S13.6: SIGTERM ends event streams, waits ≤ 5 s for requests, stops; a second signal stops at once; a refused start prints one `refusing to start:` line and exits 78 (`EX_CONFIG`) for a config file it can't use or with a setting it doesn't know, an unreadable keyring, unloadable certificate, a data directory in use; compose uses `restart: unless-stopped`; Docker's back-off reaches once a minute.
- S13.6: uninitialised (no keyring): `/healthz` 503 `uninitialised`, `/ui` only the welcome and its routes, all else 503; locked (no key): `/healthz` 503 `locked`, `/ui` only the locked screen, all else (incl. `/link`, `/connector`, `/mcp`) 503 `locked` with `Retry-After`; a DB from a newer release refused at unlock, server stays locked; `/healthz` 503 `re-encrypting` during an unlock's re-encryption and `starting` before ready; `GET /ui/api/unlock` tells anyone: uninitialised or locked, the keyring's fingerprint, the version, and once unlocked whether the first admin is still to be set up; the image's health check = alive in any of these states.
- S13.6: host commands (`keys unlock`, `keys rotate`, `db backup`) reach the running server over `/run/moolakata/sock` in a 0700 directory on a tmpfs (`web/.dev/` in dev), never over the listener.
- S13.7.1: session token 256 random bits in cookie `mk_session` (`HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/ui`), stored as SHA-256; new token at sign-in and every privilege change (two-step passed, made admin), which starts its own absolute lifetime; idle 8 h and absolute 30 days by default; signing out, a password change and deactivation end every session of that user; `Max-Age` = absolute lifetime; after a password change the changing browser gets a new session; accepting an invitation signs in, a reset doesn't.
- S13.7.2: the password again (if last given > 10 minutes ago) for: changing password, email or two-step; making an access token; creating a linked copy's access key; resetting a copy; sharing with a linked server; pairing, confirming or unpairing the connector; sealing a Connection's credentials or changing its server's address; setting a Settings secret (SMTP, node, price-source key); changing the SMTP host or public URL; Settings › Network; who is in Admins; re-encrypting; removing a copy (plus the phrase) or forgetting a previous key; pruning files; removing orphan files; opening a written email (missing items: D2-14).
- S13.7.3: argon2id 64 MiB, 3 passes, parallelism 1; minimum length per S16.5; at most 1,024 chars; the 100,000 most common passwords refused; no other rules.
- S13.7.4: `SameSite=Strict` + `Origin` check on every changing request; missing or foreign `Origin` → 403; no CORS.
- S13.7.5.1: sign-in, two-step codes, re-authentication, the current-password check, reactivation requests and the unlock: 10 failures in 15 minutes lock the source address for 15 minutes; so do 10 password-reset requests; IPv6 counted by /64; a username failing from anywhere is only slowed (0.5 s per failure past the third, up to five), never locked; answered 429 with `Retry-After`.
- S13.7.5.3: API 600 requests a minute per session; uploads 60 files an hour per user.
- S13.7.5.4: `/mcp` 60 calls a minute per token; `/link` 60 a minute per link, and unsigned-by-a-known-key calls 60 a minute per address, checked before the body is read; `/connector` 60 calls a minute, its files counted against the upload limit.
- S13.7.5.5: rate counters in memory; a restart clears them.
- S13.7.6: JSON bodies ≤ 1 MB (a linked server's ≤ 20 MB); uploads ≤ the Settings size (25 MB default); ≤ 100 MB of uploads in flight per user; headers ≤ 16 KB; type checked from content; uploads held in memory, never spooled (see D2-1, D2-16).
- S13.7.7: every response: the CSP of S17.3.3, `nosniff`, `Referrer-Policy: no-referrer`, COOP and CORP same-origin, `Permissions-Policy` denying camera, microphone, geolocation, payment, `frame-ancestors 'none'`; HSTS one year in `tls` mode; receipt and statement files (a linked one's too) with `Content-Disposition`, their checked type and a `sandbox` CSP; `/demo`'s CSP `sandbox allow-scripts allow-popups`, inline script and style, `connect-src 'none'`.
- S13.7.8: errors carry no stack trace, SQL, host path or secret; each has an id that is in the log with status and code.
- S13.7.9: logs: no amounts, account or payee names, secrets, tokens or passwords; sign-ins, failures, lockouts and admin actions logged and in Activity; statement logging never on (the DB key is in `PRAGMA key`); engines hide statement parameters; a linked server's own message only in the log.
- S13.7.10: TLS 1.2 and 1.3 only; HTTP/2.
- S13.7.11: Python deps pinned with hashes in `uv.lock`; base image pinned by digest; browser libraries adopted after a 14-day cooldown, registry integrity hash, provenance where published (never dropped once present), reviewed diff.
- S13.8.1: plural nouns; `GET` reads, `POST` creates, `PATCH` changes sent fields, `PUT` replaces a once-per-parent thing (creating it), actions are `POST` to a verb (`/ui/api/links/{id}/pull`); `DELETE` soft-deletes, answers 200 `{deleted, parent}`; sign-out `DELETE /ui/api/session` answers 204.
- S13.8.2: JSON camelCase; ids prefixed; dates `YYYY-MM-DD`; timestamps RFC 3339 UTC; absent value = `null`, never omitted; money as a number literal with two places, quantities and prices at their own scale, always a decimal point; integers for counts, years, versions, sats; OpenAPI `"type": "number"` with `"format": "money"` or `"decimal"`; one exact encoder (`moolakata/exactjson.py`) for API, SSE, MCP and `/link`; browser `parseJson`; requests may send decimal strings; too many places refused.
- S13.8.3: errors `application/problem+json` (RFC 9457) with `type`, `title`, `status`, `detail`, error id, `errors` [{field, code, message}]; stable codes listed in OpenAPI.
- S13.8.4: status codes 200, 201 + `Location`, 202, 204, 400, 401, 403, 404 (absent or invisible, indistinguishable), 409, 412, 413, 415, 422, 428, 429, 503 (starting, or a linked copy locked).
- S13.8.5: lists `?offset=` (0) and `?limit=` (500 default, max 1000), answer `{items, total, offset, limit}`; `?sort=field|-field`.
- S13.8.6: every record has `version`; `PATCH`/`PUT`/`DELETE` send `If-Match`; missing → 428 `version-required`; stale → 412 `stale-version` with `current` and its `version`; a creating `PUT` sends `0`; a group of records has one version (their sum); link pairs and secrets have none.
- S13.8.7: long work answers 202 with `/ui/api/jobs/{id}` (state, progress, result).
- S13.8.8: `Idempotency-Key` only on `POST /ui/api/transactions`, 24 hours; others L8; imports idempotent by content.
- S13.8.9: `/ui/api` unversioned (OpenAPI states the release); `/link` versioned in its protocol; `/connector` by path `/connector/v1/`; `/mcp` by negotiated protocol version.
- S13.8.10: every read through the caller's shares and the soft-delete views; lists never hint at what is invisible.

### S14 Storage and secrets

- S14.1: one SQLite DB (WAL) under the data directory, SQLCipher-encrypted under a key derived from the data key, through `sqlcipher3`; links' data in a SQLCipher DB per link.
- S14.1.1–2: tables in SQLAlchemy Core under `store/tables/`; entities plain dataclasses in `store/entities/` importing nothing from SQLAlchemy; mapped by `store/mapping.py` (`map_imperatively`); calculation code must not import SQLAlchemy (a test).
- S14.1.3: numbered Alembic revisions, generated, reviewed, committed; a test fails on drift; at unlock the DB is copied (verified) to `pre-upgrade/`, three newest kept, then migrated one revision per transaction; committed revisions never change.
- S14.1.4: a repository module per table; `Database.tx()` = `BEGIN IMMEDIATE`, `Database.read()` = `PRAGMA query_only`; foreign keys on; 10-second busy timeout.
- S14.1.5: records never removed; deleting sets `deletedAt`, `deletedById` (`deleted` generated); views work out deletion through parents; exceptions in `schema.md` (D2-20).
- S14.2: receipt files owned by the server's account, mode 0600 in a 0700 directory.
- S14.3: money stored as integer cents; quantities and prices as decimal text to 18 places; Python `Decimal` context of 34 digits, `HALF_EVEN` except where a tax rule says otherwise; no float.
- S14.4: secrets (price-source keys, the node's credentials, the SMTP password, the link private key, two-step seeds, a seed being set up) each AES-256-GCM under its own data key wrapped by the secrets key (derived from the data key), associated data naming record and field; decrypted when used, never logged or sent to the browser (shown as *set*, when, by whom); passwords, recovery codes, session, reset and invitation tokens stored as hashes.
- S14.5: the master key: 128 random bits, only as the 12-word phrase and in memory while it unwraps the data key; never on the host, in the DB or a backup.
- S14.6: backups daily and verified, of the DB with its keyring and nothing else, to a directory set on the host; time of day and copies kept in Settings; never during a re-encryption; `PRAGMA integrity_check`; oldest pruned (backup pruning); `moolakata db backup` (through the server or alone when stopped); `db verify-backup` (newest by default) checks each file against the manifest, the manifest's HMAC-SHA256 under a key derived from the backup's data key, the recorded time against the name, and that it opens with the phrase typed (may be a previous one); each backup carries its keyring; a rotation re-encrypts backups; a restore puts DB and keyring back, leaves receipt files (re-wrapped when a re-encryption came between), sets linked copies aside; orphan files counted in Settings › Storage with **Remove**.
- S14.7: `moolakata db shell` on the host with the phrase typed; that and every `db`/`keys` command is queued in the data directory and recorded in Activity at the next unlock or within a quarter of an hour.
- S14.8: a user's export is L4.
- S14.9: timestamps stored UTC, shown in the viewer's zone; each user's zone in Profile: **Auto** (the server's, from the host's `/etc/localtime` and `TZ`) or a named zone; calendar dates have no zone; a trading day is New York's; "today" for a user follows their zone (tax-year default, occasion lead time, daily summary hour).
- S14.10: records, soft-deleted records and Activity are never removed; only files are pruned, by hand; price history kept for ever.
- S14.10.1: a category's **Keep receipts for** (years, empty = for ever; whole years ≥ 1; a warning under 7), inherited by a subcategory, set by an admin in Settings › Storage; statements one period in Settings › Storage (empty = for ever), counted from the statement's last day (or the account's last transaction once closed); a file's **Keep** toggle keeps it for ever.
- S14.10.2: a file expires at the latest end of its records plus the longest period; never when Keep is on, any record has no period, or it is attached to nothing; worked out, never stored.
- S14.10.3: shown: *Kept until Mar 2031* (bold within 90 days), *Kept while the lot is open*, *Kept for ever*, *Expired Mar 2031, prunable*.
- S14.10.4–5: Settings › Storage shows DB and receipts sizes, a pie (expired, expiring later, kept for ever) and per-year bars by category, sizes and counts only; **Prune N files (size)** previews by category, asks the count typed and the password (> 10 min), removes the files, records counts in Activity; no backup first; a shared file removed once no live receipt needs it; each record keeps its row and shows *File pruned Jan 3, 2034*.
- S14.10.6: pruning never touches a linked copy; a file pruned at the source leaves the copy at its next pull.

### S15 Encryption and the master key

- S15 terms: master key 128 random bits, never stored; recovery phrase = the master key as 12 words; locked = serving with no key; data key 256 random bits, stored only wrapped; keyring = the file holding the wrapped data key, in every backup; database, receipts and secrets keys derived from the data key; fingerprint `mk-3f9a…c21e`; copy = anything holding the data at a moment (on this host: a backup, a `pre-upgrade/` copy, a `before-restore-*/` folder; elsewhere: the host's snapshots etc.); rotation = new master key and phrase and new data key, always re-encrypting; re-encryption = new data key, everything rewritten while not serving.
- S15.1: encrypted: the whole main DB (SQLCipher, incl. OCR text and thumbnails); each receipt file; each secret on its own (price-source API keys, node credentials, SMTP password, the link private key, two-step seeds incl. one being set up); a credential sealed for the connector sits in the DB as a box only the connector opens; the Electrum certificate fingerprint is not a secret (integrity from the DB).
- S15.1.4–5: backups = encrypted DB with keyring; receipt files in the host's backup as they are; linked copies under their own access keys, untouched by losing or rotating the master key.
- S15.1.6: hashed: passwords (argon2id); session, invitation, reset and confirmation tokens (SHA-256 of a random value).
- S15.1.7: not encrypted: the config file; logs; the `tls/` pair (testing); the mail folder (each email there removed once its link expired: invitation a week, others a day at most); emails queued for SMTP live in the encrypted DB.
- S15.2: no Vault, KMS, HSM or TPM; no key file (rejected).
- S15.3.1: the master key = BIP39 English 12 words with checksum; words only as notation (no BIP39 wallet derivation); encrypts only the data key; never stored, logged, sent beyond the unlock request (see D2-15), shown after install, or in a backup.
- S15.3.2: data key wrapped AES-256-GCM under HKDF-SHA256(master key, label `moolakata master`) in `keyring`; HKDF-SHA256 from the data key, each under its own label: database key (SQLCipher raw key), receipts key (an X25519 pair; receipt files use S11.9.6's format with it), secrets key (wraps secrets' data keys).
- S15.3.3: each secret: its own random 256-bit data key; AES-256-GCM, random 96-bit nonce; associated data = record type, record's stable id, field; the row stores ciphertext, nonce and wrapped key.
- S15.3.4: a secret is unwrapped and decrypted for each use and discarded; the link key, which signs every link and connector answer, is decrypted for each.
- S15.3.5: master key id = first 16 hex digits of `SHA-256("moolakata key id" ‖ key)`, short form = fingerprint; the keyring records which master key wrapped it and the data key's id = `SHA-256("moolakata data key id" ‖ data key)`.
- S15.3.6–7: rotating re-wraps one 32-byte data key (and re-encrypts, S15.7.1); a copy without the phrase reveals only sizes and dates; root on the unlocked server reads everything.
- S15.4.1: the server starts locked; uninitialised with no keyring; locked: `/healthz` 503 `locked`, `/ui` the locked screen, all else 503; no prices, backups or link exchanges; connector reports refused; every restart locks; only a person unlocks (automatic unlock rejected); a waiting re-encryption runs at the unlock before serving.
- S15.4.2: two ways: the locked screen (desktop browser) or `moolakata keys unlock` in the container over the Unix socket; the phrase is the authentication; wrong phrases count toward the sign-in lockout; every attempt logged with the address.
- S15.4.3: at unlock the data key is unwrapped and the three keys derived, kept in memory while it runs; the master key dropped at once, held again only to wrap at a rotation or re-encryption.
- S15.4.4: the welcome makes a master key in memory, shows 12 words + fingerprint, a new one every visit, none written until three words are typed back, then the keyring is written and the server unlocked; `moolakata keys init` does the same on a terminal (never stdout; refuses without a terminal), after which the running server is locked until the phrase; both refuse where a keyring exists; whoever reaches an uninitialised server first can make its key.
- S15.4.5: refuses to start (exit 78) when the keyring can't be read, or the DB exists without its keyring (the refusal names `db restore` or an emptied data directory).
- S15.4.6: the phrase never in a file, env var, image, config or script.
- S15.4.7: commands: `keys init`, `fingerprint` (no phrase), `verify`, `rotate`, `reencrypt`, `unlock`; `db backup`, `verify-backup`, `restore`, `shell`; `unlock` and `rotate` over the socket (`docker compose exec`); `db backup` through the server; the rest, and `rotate`/`db backup` when stopped, as one-off containers (`docker compose run --rm`); `restore`, `reencrypt`, and stopped `rotate`/`db backup` take the data directory's lock and refuse beside a running server; a stopped `db backup` opens read-only, migrates nothing; one-off commands queued, reaching Activity within a quarter of an hour or at the next unlock.
- S15.5: losing the phrase loses everything (DB, receipts, backups, copies); no back door; host lost with phrase kept: restore receipts from the host backup, restore the DB backup, unlock (missing receipts reported); phrase lost while running: `keys rotate` over the socket needs no old phrase, re-encryption at the next unlock.
- S15.6.1: `keys init` and `keys rotate` show the phrase with fingerprint, server name and date, and need three random words back; each word recognised by its first four letters.
- S15.6.5: **Verify key** (Settings › Key storage) or `keys verify`: the whole phrase, checks it unwraps the keyring, changes nothing; wrong counts toward the lockout; each confirmation recorded (fingerprint, when); yearly reminder; every unlock counts as a confirmation.
- S15.6.7: Settings › Key storage lists the copies on this host and how each opens; copies elsewhere are never seen or pruned.
- S15.6.8: `moolakata db restore` runs with the server stopped (lock held), asks the phrase, checks like `verify-backup`, refuses a newer release's backup, moves the DB, keyring and linked copies to `before-restore-<time>/`, leaves receipt files (re-wrapping them, journaled, when the data key differs, asking the replaced keyring's phrase when another), warns when the backup's phrase differs; at unlock reports what it can't open; links pulled in full.
- S15.7.1: rotation on the host: `keys rotate` makes a new key, shows the phrase, three words back, wraps the keyring at once, records the previous fingerprint and date; over the socket needs no old phrase and re-encrypts at the next unlock; stopped, asks the current phrase and re-encrypts at once; copies on the host re-encrypted (default), deleted or left (`--reencrypt-all`, `--delete-old`, `--leave-all`); outcomes in Activity; previous keys listed with copies needing them; **Forget**.
- S15.7.2: re-encryption: new data key, `PRAGMA rekey`, every receipt file and every secret re-encrypted; never while serving (at an unlock with progress on the locked screen and `/healthz` `re-encrypting`, or `keys reencrypt` with the server stopped); **Re-encrypt at the next restart** (admins, password again) schedules one for the next unlock with that unlock's phrase; a verified backup first; no backup during it; copies on the host: re-encrypt (default), delete or leave (a copy under an earlier phrase only left or deleted); a journal records each step; new keyring written as `keyring.next`; interrupted runs resume at the next unlock; one pending under another phrase refused by name; an unexplained `keyring.next` set aside; a receipt or secret opening under neither key set aside and reported.
- S15.7.3: rotation and re-encryption change nothing for copies made before; secrets' values unchanged; passwords and linked copies untouched.
- S15.7.4: rotation and every `keys verify` recorded in Activity for admins (when, old and new fingerprints); a command run while down recorded at the next unlock; no key material recorded.
- S15.8.2: after a leak: revoke and reissue secrets at their source (incl. unpairing and re-pairing the connector), rotate, delete every copy made before, destroy the old phrase's copies.
- S15.8.3: a memory dump exposes the data key (and the master key only during an unlock, rotation or re-encryption): re-encrypt; rotate if the phrase could be caught.
- S15.8.4: rotation reminder after a configurable period, 12 months by default, off allowed.

### S16 Settings (admins)

- S16 order: General, Email, Sign-in and sessions, Sign-up, Passwords, Prices, Bitcoin, Imports, Linked servers, Connector, Receipts, Tax tables, Backups, Storage, Key storage, Network, Alerts; General first and selected; each section has its own guide.
- S16.1: General: server name (shown to linked servers), household name and avatar (image or initials; sent to linked servers, shown there as set here), public URL (email links built from it, never from the request), the server's time zone read from the host.
- S16.2: Email: host, port, security (STARTTLS, TLS, none), username, password (secret, password again), from address, **Send a test email** (to the admin, now); changing the host asks the password and clears the SMTP password; without a host emails are written to the mail folder in the clear, listed (who, subject, when) with **Open** (password again; recorded in Activity with the addressee as owner); mail-folder files removed after 1 hour (reset), a week (invitation), a day (the rest, linkless included); with a host, queued in the DB, retried every 5 minutes until the link expires (D2-19); a refused one keeps only recipient, subject and error.
- S16.3: idle lifetime 8 h (1–168 h); absolute 30 days (1–365); lockout 10 failures (3–100) for 15 minutes (1–1,440).
- S16.4: sign-up on/off (needs SMTP), optional email domains.
- S16.5: minimum password length 12 (8–128).
- S16.6: Prices: enabled sources with classes, keys, order, last run, error; **Add a source**; daily refresh time 6:00 PM Eastern by default.
- S16.7: Bitcoin: public Esplora (mempool.space suggested, Blockstream) or own node (mempool/Esplora address; Electrum host, port, TLS; Bitcoin Core host, port, RPC user, password); last read; **Test**; no wallet read until saved; changing the node host clears its password.
- S16.8: Imports: statement file types and size (25 MB default, 1–200 MB); whether statements are read on the server.
- S16.9: Linked servers: this server's link address (public URL when unset), the links, each copy's state, *Create the access key*, *Lock now*, *Reset copy*, **Release linked keys after** (1 hour default, 5 minutes to 24 hours).
- S16.10: Receipts: size limit 25 MB (1–100); **Read receipts** on/off; jobs at a time 1 (≤ 4); queue; **Re-read all receipts**; the no-Landlock note.
- S16.11: Tax tables per year, shipped and correctable (contribution limits and thresholds, gift exclusion, 529-to-Roth lifetime, QCD limit, collectables rate, Form 8615 unearned income, college-cost averages, bitcoin models' figures, metal per share of SLV, PPLT, PALL); a corrected figure marked with the shipped value; a year past the latest uses the latest.
- S16.12: Backups: time of day 02:30, copies kept 14 (1–365), each listed with size and the key it opens with, **Back up now**; directory set on the host.
- S16.13: Key storage: fingerprint and age, when and how the phrase last opened the keyring, previous keys with copies needing them and **Forget**, copies on this host with **Remove** (password and phrase), the host's own copies noted, last re-encryption, what can't be opened; **Verify key**, **Test** (D2-13), **Re-encrypt at the next restart** (per-copy choices), **Cancel**; rotation reminder 12 months (off allowed); the master key changed only on the host.
- S16.14: Network: allowed ranges per path, empty = any: the app (`/ui`, and `/mcp` with it), linked servers (`/link`), the connector (`/connector`, default `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10`, `::1`, `fc00::/7`); checked on the client address as the trusted proxy forwards it; `/healthz` and `/demo` answer any; outside → 404; ranges in the DB, so while locked the locked screen and unlock answer any address; shows mode, port and trusted proxies read only (`moolakata.toml` or `MOOLAKATA_CONFIG`).
- S16.16: Alerts: failure threshold 48 hours (1–336); daily summary 07:00 in each user's zone.
- S16.17: Storage: DB and receipts sizes, expired vs the rest, orphan files with **Remove**, per-year expiry by category, **Keep statements for**, each category's **Keep receipts for**, **Prune**.
- S16.18: Connector: **Pair**, the connector's fingerprint, **Confirm** (who and when), **Unpair**, locked or not, last report and its address (**Accept** when changed), every Connection's state, owner, accounts and the host its credentials go to, never credentials.

### S17 Implementation

- S17.1: layout: `docs/` (requirements, schema.md, api.md, link-protocol.md, connector-protocol.md, operations.md, DEPLOY.md, dependencies.md, test-plan.md, mockups); `web/` (VERSION, dev.sh, release.sh, check, pins, ui/, server/src/moolakata/, install/); `connector/`; `publish/truenas/`.
- S17.2: server dependencies: fastapi, pydantic, hypercorn, sqlalchemy, alembic, argon2-cffi, cryptography (AES-GCM, Ed25519), httpx, segno, Pillow, pypdfium2, sqlcipher3, rapidocr with onnxruntime (with numpy, opencv-python-headless, shapely, pyclipper, pyyaml, ~100 MB, loaded only in the receipt worker), ofxtools (GPL-3.0-only), pi-heif, numpy; stdlib for email, config, logging, CLI; pinned in `uv.lock`; Python 3.14.
- S17.2.1: `docs/dependencies.md` registers every library (version, purpose, egress/telemetry, the switch); `web/dev.sh audit` after every change to `uv.lock` or the vendor manifest (URL and telemetry scan, a run with no network interfaces failing on any non-loopback socket); hashes in `web/audit.json`, checked by `web/check`.
- S17.3: no build step; Preact, HTM, @preact/signals, preact-iso, ECharts vendored as npm tarballs in `web/ui/vendor/` with `manifest.json`; `web/dev.sh vendor add NAME VERSION` refuses a version < 14 days old unless `--young` with a reason, checks the integrity hash, verifies SLSA provenance via Sigstore where held (a package that had it can't drop it), writes the manifest entry and a diff; import map in `index.html`; JSDoc types checked by Deno; no minification or source maps.
- S17.3.3: CSP `script-src 'self' 'nonce-…'` (nonce for the import map only), `style-src 'self'`, no inline scripts or styles, no `eval`, no third-party requests.
- S17.3.4: first screen under 150 KB compressed; other screens loaded by `import()`.
- S17.3.5: app under `/ui/v/<version>/` with a one-year cache in a release; `-dev` builds and the dev server `no-cache`; `index.html` `no-store`.
- S17.3.7–8: the browser keeps only theme, sidebar, help pane, page size, privacy mode; current Chrome, Edge, Safari, Firefox; no polyfills.
- S17.4: Apache ECharts (full ESM build, ~330 KB gzip), lazily imported via `app/charts/` (D2-23).
- S17.5: `web/check` runs pytest (throwaway SQLite per test), Playwright browser tests, Deno check/lint/fmt, ruff, OpenAPI and typedef drift, mockup drift, help-guide checks, the register's hash check, the requirements' checks (ids resolve, README tables, ≤ 500 lines per section file, schema prefixes in order); golden files for 8949 and TXF; fixture receipts with an accuracy floor.
- S17.6: `web/dev.sh` commands: setup, run, test, check, mail, mockup, help-shots, deno, vendor, audit, base-update, mocks; `web/pins` holds dev-only downloads' versions and hashes.
- S17.7: dev mode (`web/dev.sh run --seed --stubs`, `moolakata dev`): `https://localhost:37373`, self-signed; data in `web/.dev/`; the phrase kept in `web/.dev/phrase` and the server unlocks itself; seed users `admin`, `alice`, `bob`, group *Household*; stub price and wallet sources; `--peer` second server; emails in `web/.dev/mail/`; red DEV pill; `--listen`, `--hostname`; refuses root, outside a checkout, or an installed data directory; the image leaves dev code out.
- S17.8: one OCI image, uid 10001, port 37373, mounts: data directory (DB, keyring, receipts, linked copies) and backup directory; `moolakata.toml` at `/etc/moolakata.toml` or in `MOOLAKATA_CONFIG`; the config holds no secret; secrets never from env vars; `install/compose.yaml` publishes the plain-HTTP listener on host loopback only, passes the host's time zone, logs 5 × 10 MB; image ~600 MB; the reader worker ~350 MB more while running.
- S17.8.1: amd64 and arm64, each built natively in a release; every dependency from a wheel for both; `web/install/smoke.sh` per architecture (refused start, welcome's key and admin, locked restart and unlock, health, sign-in, receipt read, connector vault and unlock, clean stops).
- S17.8.2: published as `ghcr.io/mojokata/moolakata` and `ghcr.io/mojokata/moolakata-connector`, version tag only (no `latest`), with build-provenance attestations (`gh attestation verify … --deny-self-hosted-runners`); also on Docker Hub (`docker.io/mojokata/…`) with the same digests.
- S17.8.3: documented hosts Proxmox (Docker in a VM or LXC with nesting) and TrueNAS (`install/compose.truenas.yaml`); TrueNAS catalog apps in `publish/truenas/` (`ix-dev/community/moolakata/`, `…-connector/`); server form: time zone, browser addresses, port 37373, a System › Certificates certificate or none, ixVolume or host path storage, host network, limits 2 CPUs and 4 GB; connector form: time zone, addresses (≥ 1), port 37374, certificate, one storage, limits 1 CPU and 1 GB; templates fix `tls` mode (D2-3), accounts 10001 and 10002, the alive health check, no capabilities, no new privileges, `/tmp` and socket dir in memory, read-only root unless a certificate is chosen; `create-pr.sh` pushes only with `--open`.
- S17.8.5: base image pinned by digest, moved per release and for Debian/Python fixes via `web/dev.sh base-update`; `web/check` warns past 90 days.
- S17.10.1: `.github/workflows/check.yml` runs `web/check` on every PR and push to `main`.
- S17.10.2: `release.yml` on a `v<version>` tag matching `web/VERSION`: both images on amd64 and arm64 runners, `smoke.sh` each, push to ghcr.io, join under the version tag, attest (Sigstore public instance), copy to Docker Hub with digests unchanged, draft the release with install files; releases immutable; tags GPG-signed by the releasing maintainer; after a release `main` moves to the next minor `-dev`.
- S17.10.3: actions only GitHub's own, pinned by commit; least-privilege token permissions; the one secret (Docker Hub token) in environment `docker-hub`, readable only for `v*` tags.

### S18 MoolaKata Connector

- S18 terms: the vault = one encrypted file (credentials, each one's bound host, the sealing key's private half), opens only with the words; the words = 12 BIP-39 words, the vault's key, never stored; locked connector reports and nothing more; its page = its own HTTPS page on its own port (status for anyone, every action takes the words); identity key Ed25519, made at pairing, beside the vault; sealing key X25519, made at pairing, public half at MoolaKata, private half in the vault; sealed box = a credential encrypted in the owner's browser to the sealing key, which MoolaKata stores and can't open; bound host = the host a credential may be sent to.
- S18 (diagram): the connector reports every 5 minutes, signed; the answer carries Connections, settings, accounts, and sealed boxes only while unlocked; the connector posts files, sign-in addresses and "credential taken".
- S18.1: one program `moolakata-connector` from `connector/`, own image, a second compose service or on another machine (a laptop) that reaches MoolaKata.
- S18.1.2: Python stdlib + `cryptography` for the core; at most one pinned, hashed dependency per driver; no import from MoolaKata; each driver declares its hosts, credentials and what it sends; a test fails when a driver reaches another host.
- S18.1.2.1: driver size in lines of code: < 1,000 green, 1,000–1,999 yellow, ≥ 2,000 red; listed in `connector-protocol.md` §6; a test fails when the list is stale, never for size.
- S18.2.1: own process, uid 10002, image, volume `connector-data` at `/var/lib/moolakata-connector` (0700): `vault.json`, `pairing.json` (0600: MoolaKata's address and fingerprint, identity private key, sealing public key), `tls/`; socket `/run/moolakata-connector/sock` (0600, tmpfs); `MOOLAKATA_CONNECTOR_DATA`, `MOOLAKATA_CONNECTOR_SOCKET`; MoolaKata never mounts its volume and vice versa.
- S18.2.2: the connector only opens connections (institutions, MoolaKata); listens only for its page; a Unix socket for commands; MoolaKata can't call it; no redirects followed; ≤ 60 s per call; ≤ 25 MB read; allowlist per driver run (its own hosts only, not MoolaKata's); refuses loopback, link-local, cloud metadata; verifies TLS (institutions against roots; MoolaKata against roots or the pairing code's certificate fingerprint).
- S18.2.4: a compromised MoolaKata gets no credential, can capture credentials typed after the compromise, can change settings but a changed host sends nothing; a compromised running connector holds its credentials and can post files; it learns each Connection's owner name, label, settings and accounts' names and last four digits, never amounts, transactions or passwords; a stolen connector volume gives the identity key and pairing (report, read answers, post files) until unpaired, never the vault; a report from a new address alerts admins until accepted or unpaired; a network visitor sees status only and can make wrong guesses (logged); on a connector with no vault anyone can make one.
- S18.3.1: vault made on its page (or `docker compose run --rm connector init` before first start): random 128-bit key as 12 BIP-39 words + the vault's fingerprint; made once three random words are typed back; `vault.json` = format name, fingerprint, nonce, contents sealed with AES-256-GCM under HKDF-SHA256(words' 128 bits, label `moolakata connector vault key`), fingerprint as associated data; no stretching; each change reseals the whole vault with a fresh nonce via temp file and rename; fingerprint = first 16 hex of `SHA-256("moolakata connector vault" ‖ key)`, kept in the clear; a Schwab entry also holds the app's secret and tokens with expiries.
- S18.3.2: starts locked at every start, fetches nothing, reports locked; MoolaKata down or locked → retries with growing wait; unlocked on its page or `docker compose exec connector moolakata-connector unlock` over the socket; key only in memory; **Lock** or `lock`; `status` (locked, paired, last report, each Connection's state); the health check runs `status` (alive = healthy).
- S18.3.3: wrong words: checksum catches slips; a valid other phrase refused by fingerprint; 5 wrong in a row (page and CLI together) → next wait 15 minutes; each wrong attempt on the page logged with its address.
- S18.3.4: lost words: `moolakata-connector reset` on the host deletes the vault, makes new words (three back) and unpairs; **Reset** on the page needs the words (and RESET typed).
- S18.4.1: **Settings › Connector › Pair** shows a one-time pairing code `mkp1.` (MoolaKata's address, link-key fingerprint, one-time secret, own-certificate fingerprint when not public), valid 24 hours, in the form of a link code; MoolaKata keeps only the secret's hash; the password again.
- S18.4.2: on the page (**Pair** with code and words) or `moolakata-connector pair <code>` with the vault unlocked: the connector makes the identity key (Ed25519) and sealing key (X25519), files the sealing private half in the vault (so `pair` is refused while locked), first checks that `GET /connector/v1/hello`'s key hashes to the code's fingerprint, then `POST /connector/v1/pair` with the code and both public keys (the sealing key signed by the identity key); both show the connector's fingerprint (the connector computes its own); a failed `pair` leaves an earlier pairing intact; untrusted until **Confirm** (password again): until then reports are taken but no sealed credential is handed over, no file is taken (`not-confirmed`, kept for later), no one can seal for it.
- S18.4.3: every connector call signed with the identity key, timestamp and nonce (as links); every MoolaKata answer signed by its link key; version in the path and a header, unknown refused naming supported; one connector per server: pairing another replaces it.
- S18.4.4: **Unpair** ends the connector, refuses its key, stops every Connection, turns every account's sync off; the connector's next call gets a signed `not-paired`, at which it deletes the credentials it held for that server and its sealing key (pairing codes: D2-21).
- S18.4.5: identity key beside the vault so a locked connector can report; sealing private half in the vault; a box is handed only to a connector reporting unlocked.
- S18.5: reports every 5 minutes, after each run, and every 15 s for up to 10 minutes while a Connection waits for a sign-in: locked or not, each Connection's state and last run, the institution accounts found (name and last four digits); the answer carries live Connections with settings and accounts, sealed credentials only when unlocked and confirmed, and removed Connections; admins alerted for: locked; not heard from for 15 minutes; a Connection needing a sign-in or failing (also to each kept account's owner); a report from a new address (until accepted, password again, or unpaired); reports never carry a credential, an amount or more than an account number's last four digits.
- S18.6: a Connection is owned by the user whose sign-in it is, who names it; MoolaKata holds owner, driver, label, state, last run and the institution accounts found (name, last four); credentials only in the vault.
- S18.6.2: **Sync using MoolaKata Connector** on an account, offered once a connector is paired; only the account's owner turns it on (not a write share); names a Connection and its institution account.
- S18.6.3–4: one Connection may serve several accounts; a joint account another owner holds only when that owner turns sync on; Profile › Connections lists a user's own with **Sign in again**, **Change credentials**, **Remove** (turns sync off; the connector deletes the credentials); Settings › Connector lists all Connections' states for admins, never credentials.
- S18.7.1: sealed for the connector: typed in MoolaKata with the password again, only after the pairing is confirmed; the browser checks the sealing key's signature by the confirmed identity key, then seals (X25519 sealed box in WebCrypto) the credentials with the host and the time; the connector refuses a box older than the credential it holds; MoolaKata keeps only the box until the connector collects it and confirms by time (`POST …/credential/taken`), then deletes it; OAuth (Schwab): the connector reports the sign-in address (taken only on the driver's own sign-in host), the owner pastes back the landing address, sealed, checked against the random `state`; a compromised MoolaKata could capture credentials typed after the compromise.
- S18.7.2: typed on the connector's host: `docker compose exec connector moolakata-connector connect <connection id>`; reports first if it doesn't know the Connection; shows the host and files only on the admin's confirmation.
- S18.7.3: a credential is bound to the host sealed with it (or confirmed at `connect`; none for fixed-host drivers like Schwab); refused when that host isn't the settings' host; before every run a mismatch sends nothing, drops the credential and reports *needs a sign-in: the server address changed from A to B*.
- S18.8: drivers post OFX/QFX, CSV (with the account's mapping) or a PDF statement through the same import as an upload; idempotent; counts against the Connection owner's upload limit; files refused for the limit are kept in memory and retried; after a restart drivers fetch again; other refusals drop the file and show on the Connection; a PDF is kept unread or waits in the account's inbox for its owner; each post in Activity *by MoolaKata Connector, Alice's Schwab login*.
- S18.9: institutions with nothing to fetch (UMB) are kept by uploads; a watched folder rejected.
- S18.9.1: OFX Direct Connect: username and password, bound to the server address; once a day, `https` only, OFX 1.0.2 client, last 45 days (`days`), or 90 while no account matches the account number; sign-on codes 15500–15503 = *needs a sign-in*.
- S18.9.2: Schwab Trader API (positions, transactions, balances) posted as OFX; a sign-in every week (refresh token ~7 days); once a day, last 45 days; callback `https://127.0.0.1`; access token ~30 minutes, used until a minute before expiry; the landing code exchanged within seconds.
- S18.10: `install/compose.yaml` carries the `connector` service (same version, `unless-stopped`, read-only, all capabilities dropped, only port 37374 published, own volume); TrueNAS: `install/compose.connector-truenas.yaml` and the catalog app.
- S18.11.1: its page: HTTPS on 37374 (`MOOLAKATA_CONNECTOR_PORT`), its own certificate made at first start in `tls/`, good for 825 days, naming `localhost` and `MOOLAKATA_CONNECTOR_NAMES`, or `MOOLAKATA_CONNECTOR_TLS_CERT`/`_KEY`; its address (first name + port) in every report (`page`); Settings › Connector links to it.
- S18.11.2: welcome with no vault: **Show my words**, a new key per visit held in memory (an hour each, 20 at most), three words back make the vault unlocked and drop the others.
- S18.11.3: status for anyone: locked or not, paired MoolaKata address, connector fingerprint, confirmed or not, last report and whether answered, counts of working and attention-needing Connections, version; never an institution, Connection name, account or credential.
- S18.11.4: actions, each a form taking the words: **Unlock**, **Lock**, **Pair** (code; unlocks first), **Unpair** (forgets pairing and that server's credentials), **Reset** (also RESET typed); the page never takes or shows a credential.
- S18.11.5: rendered by the connector, no JavaScript, stdlib HTTP server and `ssl` with `cryptography`; CSP allows only its own stylesheet; forms post only to itself, cross-origin refused; no caching or framing; form bodies ≤ 16 KB; stylesheet uses MoolaKata's tokens, a test keeps them alike.

### out-of-scope.md, rejected-ideas.md

- Out of scope: foreign accounts and currencies; coins other than bitcoin and exchange APIs ("later": D1-5); deleting a user and their data; trading or any write to an institution; real-time quotes and greeks; bill payment; automatic valuations of homes, vehicles, collectables; refinancing or payoff advice; gift shopping, wish lists, registries; state 529 deduction rules; tax filing or computation; running a relay for links; phone support in the web app (a PWA "later": D2-25); storing wallets' private keys or seeds; opting users in or out of the list sent to linked peers.
- Rejected 1–3: a separate keys process; external key services; leaving financial data unencrypted.
- Rejected 4: the master key as base32 (12 BIP39 words instead).
- Rejected 5–7: a per-user access key for linked copies; the receiving admin choosing who sees each linked share; linked accounts shown among this household's own.
- Rejected 8: SQLModel.
- Rejected 9: a portfolio showing an account its viewer can't see as one line.
- Rejected 10: write access for agents.
- Rejected 11: an RPM package.
- Rejected 12–14: Barchart, Stooq (needs a captcha key since 2026), Yahoo Finance as price sources.
- Rejected 15: bank aggregation (SimpleFIN Bridge and the like).
- Rejected 16: pruning records into summaries (a household's rows grow ~10 MB a year; files 50–100× faster).
- Rejected 17: a key per backup, or closing a copy already made, after a leak.
- Rejected 18: a master key file on the host.
- Rejected 19: automatic unlock of the server or the connector.
- Rejected 20: an unlock passphrase beside the recovery phrase.
- Rejected 21: a watched folder for the connector.
- Rejected 22: re-encrypting while serving.
- Rejected 23: keeping admins out of other users' accounts by app rules.

## Found while checking

Unverified, in the claim format (docs/REVIEW.md §7); the sweep checks them.

### D2-F1: No section states a size ceiling for a receipt's own body on a link

- **Kind:** behaviour named and never specified. **Severity:** Low. **Req:** S13.7.6, S11.9.6.
- **Where:** `docs/link-protocol.md:22–23`:

  ```text
  4. Bodies are JSON, UTF-8, at most 20 MB. A caller waits 10 seconds to connect and 20 seconds
     for each read, and cuts off an answer past 20 MB.
  ```

  and `docs/link-protocol.md:150–153`, where a receipt's sealed bytes are the body of a
  `deliver` call, `application/octet-stream`.
- **What goes wrong:** §1.4 and S13.7.6's "a linked server's up to 20 MB" speak of JSON
  bodies; a receipt's bytes are neither JSON nor, in S13.7.6's words, an upload by a user, so
  the request side of a receipt crossing a link has no stated limit, while the answer side is
  cut at 20 MB by S13.5 (D2-1).
- **Remedy:** state the ceiling for a receipt's body in §1.4 and S13.7.6, tied to S16.10's limit
  (see D2-1's remedy).

- **Check:** rejected. Already D2-1: its check's corrected scope says the `deliver` body is `application/octet-stream`, not JSON, "with the `deliver` body undecided", and its remedy adds that S13.7.6 or §1.4 "state the ceiling for a receipt's body", which is this item's remedy. DC-1 and U08-1 carry it on into the code (`middleware.py:243-247`).
