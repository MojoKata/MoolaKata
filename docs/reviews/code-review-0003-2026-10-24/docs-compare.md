# Code review 3, Phase 1: the digests compared

Started Oct 24, 07:27 PM (Chicago). Commit read: `6916954` (branch `code-review-0003`).
Quick review: no checker; every claim here is at 0 confirmations.

**What was read.** `docs/REVIEW.md` whole; `log.md`; the three claims digests
(`docs-1-money.md` from its `## Claims digest`, `docs-2-platform.md` and `docs-3-protocols.md`
likewise); the claim headings of each block, and of a few claims only the lines needed to tell
whether a conflict found here is already one of them (D2-1, D2-3, D2-4, D3-1, D3-6, D1-13,
D1-24, D2-16, D2-19, D2-25); `map.md`'s units table. For each claim below, the cited lines of
the source documents were opened and are quoted; where a digest misstates its source, the
claim says so.

**Format.** As the blocks' claims (§7): work-pad id `DC-<n>`, kind, severity (`gaps.md`: High
blocks the next release, Med is needed before it, Low can follow it), both ids, the quoted
lines, what goes wrong, remedy, alternatives, the units of `map.md` it touches, and **Needs the
user** where a choice is needed. A **join** gives one id to block claims that are the same
cross-block problem seen from two sides; assembly gives a join one review id.

## Claims

### Joins: one problem seen from two blocks

#### DC-1: joins D2-1 and D3-1, a receipt over about 20 MB can't cross a link

- **Kind:** contradiction across blocks (join). **Severity:** Med. **Conf:** 0. **Status:** open.
- **Ids:** D2-1 (S13.5, S13.7.6, S16.10, S11.9.6) and D3-1 (`link-protocol.md` §1.4, §4, §4.3).
  D3-1 says itself that it is "the protocol's side of `D2-1`".
- **Where:** both claims quote the lines; the two that carry the conflict:
  - `S16-settings.md:46`: "**Receipts**: the size limit (25 MB by default, 1 to 100)".
  - `link-protocol.md:22–23`: "Bodies are JSON, UTF-8, at most 20 MB. A caller waits 10 seconds
    to connect and 20 seconds for each read, and cuts off an answer past 20 MB."
- **What goes wrong:** as D2-1 and D3-1 say: a receipt of 20–100 MB with **Include receipts**
  on can travel neither in `deliver` nor in a `file` answer. Read with D3-5 (receipts held
  until the part that names them arrives), the part that names such a receipt may never apply,
  so the unit should look for an exchange that stalls for good rather than one receipt left
  out; if it does stall, the claim becomes High there.
- **Remedy:** one decision, written into S13.5, S13.7.6 and `link-protocol.md` §1.4: sealed
  receipt bodies (`deliver` with `MK-Link-File`, `file` answers) are streamed and bounded by
  the receipt limit's maximum (S16.10's 100 MB plus the format's overhead), JSON bodies stay
  at 20 MB.
- **Alternatives:** cap a receipt that may cross a link at 20 MB and show it as *too large to
  share* on the receiving side; or lower S16.10's maximum to 20 MB.
- **Units:** 08 linked-servers (S11), 09 web-ui-architecture (S13.5, S13.7.6), 10
  encryption-settings (S16.10).
- **Needs the user:** which of the three.

#### DC-2: joins D2-3 with `DEPLOY.md` and `operations.md`, which disagree on whether a relied-on TrueNAS server runs `tls` mode

- **Kind:** contradiction across blocks (join, extending D2-3). **Severity:** Med. **Conf:** 0.
  **Status:** open.
- **Ids:** D2-3 (S13.3, S15.1.7, S16.15, S17.8.3.4); `DEPLOY.md` intro; `operations.md` §1 and
  §2.2. No block-3 claim covers it.
- **Where:**
  - `DEPLOY.md:5–7`: "both serve HTTPS themselves on port 37373 with a self-signed certificate
    (`tls` mode, requirements S13.3), which is what a test on a local network needs. A server
    the household relies on goes behind its reverse proxy instead ([`operations.md`](operations.md) §2)".
  - `operations.md:25–26`: "`install/compose.tls.yaml` runs its own HTTPS with a self-signed
    certificate, for trying it on a local network."
  - `operations.md:121–125` (§2.2, the runbook's TrueNAS install, the one DEPLOY sends a
    relied-on server to): "a **custom app** from **Install via YAML**
    (`install/compose.truenas.yaml`) … and the configuration in `MOOLAKATA_CONFIG`"; and
    `web/install/compose.truenas.yaml:34`: `mode = "tls"`.
- **What goes wrong:** DEPLOY sends a relied-on server to `operations.md` §2 to get it behind
  a proxy, and `operations.md` §2.2 installs it on TrueNAS in `tls` mode, the mode S13.3,
  S15.1.7 and S16.15 call testing-only. The decision D2-3 asks for has to reach these two
  documents and the TrueNAS compose file too, or they keep saying the opposite of it.
- **Remedy:** D2-3's decision, carried into `DEPLOY.md`'s intro, `operations.md` §1 and §2.2,
  and the comment in `compose.truenas.yaml`, in the same change.
- **Alternatives:** as D2-3.
- **Units:** 09 web-ui-architecture (S13.3), 10 encryption-settings (S15.1.7, S16.15), 11
  implementation (S17.8.3, the install files).
- **Needs the user:** with D2-3.

#### DC-3: joins D2-4 and D3-6, a link's states and what moves it between them

- **Kind:** behaviour named and never specified, across blocks (join). **Severity:** Low.
  **Conf:** 0. **Status:** open.
- **Ids:** D2-4 (S11.7's list leaves out *broken* and the request waiting for approval) and
  D3-6 (`link-protocol.md` §4, §7: *broken* allows no call, nothing leaves it, relinking with
  the same key unspecified). D3-6 already says "with `D2-4`".
- **Where:** as the two claims quote (`S11-linked-servers.md` S11.6, S11.7;
  `link-protocol.md` §4's state column and §7's `not-linked`).
- **What goes wrong:** the requirements and the protocol each list part of one state machine
  (*requested*, *pending*, *active*, *paused*, *unreachable*, *broken*, *ended*), and neither
  says what leaves *broken*. Fixed apart, the two lists would drift again.
- **Remedy:** one table of states, the calls each allows and what moves a link between them,
  in `link-protocol.md` §4, with S11.7 listing the same states by name and citing it.
- **Units:** 08 linked-servers.

#### DC-4: joins D1-5 and D2-25, "later" that points at out of scope

- **Kind:** reference across blocks (join). **Severity:** Low. **Conf:** 0. **Status:** open.
- **Ids:** D1-5 (S1.5: coins other than bitcoin "come later", linked to `out-of-scope.md`) and
  D2-25 (S11.2.3's relay "not now", S12.8's PWA "later", both to out of scope, no L id). D2-25
  says itself "decided with D1-5".
- **Where:** as the two claims quote.
- **What goes wrong:** the same pattern in two blocks: work promised as later lives in the
  file of what MoolaKata won't do, with no L id, so `later.md` doesn't hold it and
  `out-of-scope.md` contradicts the promise.
- **Remedy:** one rule for both: each is either later work (an L id, from L13) or out of
  scope (the "later" words go).
- **Units:** none (documents only).
- **Needs the user:** for each of the three (other coins, a relay, the phone PWA), later or
  out of scope.

#### DC-5: joins D2-19 with `schema.md`, which keeps the same unbounded queue rule

- **Kind:** behaviour named and never specified, across blocks (join, extending D2-19).
  **Severity:** Low. **Conf:** 0. **Status:** open.
- **Ids:** D2-19 (S16.2); `schema.md` §3.1 (`Email`) and §4.4.4.
- **Where:**
  - `schema.md:89`: "| Email | QueuedEmail | An email waiting to go out through SMTP, until it
    is sent or its link expires. |"
  - `schema.md:191–192`: "**work queues and counters**: receipt-reading jobs, emails waiting
    to go out (when sent or when their link expires)".
- **What goes wrong:** as D2-19: an email with no link (an alert, a notice) has no expiry, so
  a queued one that can't be sent is kept and retried for ever. `schema.md` repeats the rule,
  so fixing S16.2 alone leaves the schema saying the old thing.
- **Remedy:** D2-19's bound (say, a day for an email with no link, as the mail folder keeps
  it), written into S16.2 and both `schema.md` lines.
- **Units:** 07 users-sharing (the map puts `mail.py` there), 10 encryption-settings (S16.2).

### New conflicts between blocks

#### DC-6: S14.3 rounds half-even "except where a tax rule says otherwise"; S1.9.2 rounds a loan's interest half up

- **Kind:** the same thing specified twice, differently (a wrong-figure risk). **Severity:**
  Low. **Conf:** 0. **Status:** open.
- **Ids:** S14.3 (block 2 digest: "`HALF_EVEN` except where a tax rule says otherwise") and
  S1.9.2 (block 1 digest: "interest rounded half up to the cent").
- **Where:**
  - `S14-storage-and-secrets.md:35–36`: "Python uses `decimal.Decimal` with a context of 34
    digits and rounds `HALF_EVEN` except where a tax rule says otherwise."
  - `S1-accounts.md:292–294`: "Interest is rounded half up to the cent, and a balance of less
    than $1 left by rounding goes with the last payment."
- **What goes wrong:** S14.3 names one kind of exception and S1.9.2's isn't of that kind. Code
  that follows S14.3's context for the schedule computes interest of $123.445 as $123.44
  where the servicer (and S1.9.2) says $123.45, so the schedule drifts from the statement by a
  cent at a time and S1.9.3's "within 2%" matching is the only thing that hides it.
- **Remedy:** S14.3 says "except where a rule says otherwise (a tax rule, a loan's interest,
  S1.9.2)", or lists every place that rounds otherwise.
- **Units:** 02 items-loans-education-bitcoin (S1.9), 06 receipts-storage (S14.3).

#### DC-7: S1.6.2.3 names each Bitcoin Core wallet by the account's id; `schema.md` §2 says nothing visible on disk carries an id

- **Kind:** contradiction across blocks (privacy). **Severity:** Low. **Conf:** 0. **Status:**
  open. Not withheld: what it exposes is an account's creation time, on the household's own
  node, and the requirement is public; it tells no one how to attack a running server.
- **Ids:** S1.6.2.3 (block 1 digest: "a watch-only descriptor wallet per account named
  `moolakata-<account id>`") and `schema.md` §2 (block 3 digest: "file names and anything
  visible on disk … use separate random names, never an id").
- **Where:**
  - `S1-accounts.md:207–208`: "Bitcoin Core over JSON-RPC: a watch-only descriptor wallet for
    each wallet account (`moolakata-<account id>`)".
  - `schema.md:53–55`: "**IDs reveal when a row was created.** File names and anything else
    visible on disk, such as receipt files and a linked copy's files (requirements S11.9), use
    separate random names and never an ID."
  - `test-plan.md:44` (T3) expects the same name.
- **What goes wrong:** Bitcoin Core keeps each wallet as a directory named after it, on the
  node's disk, and lists it to anyone with RPC access; the UUIDv7 in the id gives the
  account's creation time to the millisecond, which the schema's rule exists to keep off disk.
- **Remedy:** the wallet is named `moolakata-<random>` with the name kept on the account, in
  S1.6.2.3 and T3.
- **Alternatives:** keep the id and add the node's wallets to `schema.md` §2 as a stated
  exception, with why.
- **Units:** 02 items-loans-education-bitcoin (S1.6).

#### DC-8: `operations.md` §3 says an older release refuses a migrated database at start; S13.6 and `operations.md` §5.1 say at the unlock

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Ids:** S13.6 (block 2 digest: "a DB from a newer release refused at unlock, server stays
  locked") and `operations.md` §3 (block 3 digest: "an older release refuses a migrated DB
  (`refusing to start:`)"); `operations.md` §5.1 agrees with S13.6.
- **Where:**
  - `operations.md:163–165`: "An older release refuses a database that a newer one has
    migrated: it says so in a `refusing to start:` line (§5.1)."
  - `operations.md:225–227`: "A server that started but stays locked after the phrase was
    entered says why in its log (`refusing to unlock:`): a database from a newer MoolaKata".
  - `S13-architecture.md:69–71`: "What the phrase then cannot open (a database from a newer
    release) is refused at the unlock, with the reason in the log, and the server stays
    locked."
- **What goes wrong:** the database is SQLCipher, so its revision can only be read after the
  unlock; S13.6 is the one the code can follow. An operator going back a release per §3 looks
  for a `refusing to start:` line and a container in `Restarting`, and finds a healthy locked
  server instead.
- **Remedy:** `operations.md` §3 says "it refuses to unlock, with a `refusing to unlock:` line
  (§5.1)".
- **Units:** 09 web-ui-architecture (S13.6), 06 receipts-storage (S14.1.3's migrations).

#### DC-9: `schema.md` keeps sign-in and access-key attempt counters as rows; S13.7.5.5 holds every counter in memory

- **Kind:** the same thing specified twice, differently (storage). **Severity:** Low.
  **Conf:** 0. **Status:** open.
- **Ids:** S13.7.5.5 (block 2 digest: "rate counters in memory; a restart clears them") and
  `schema.md` §4.4.4 (block 3 digest: "work queues and counters (… sign-in and access-key
  attempt counters …)").
- **Where:**
  - `S13-architecture.md:108–110`: "sign-in, two-step codes, re-authentication, … and the
    unlock (S15.4.3): 10 failures in 15 minutes lock **the address they came from**";
    `:115`: "linked copies' access keys: S11.9.3.3"; `:122`: "The counters are held in memory:
    a restart clears them."
  - `schema.md:191–193`: "**work queues and counters**: receipt-reading jobs, emails waiting
    to go out …, sign-in and access-key attempt counters, the background tasks' last runs, and
    the live stream's state".
- **What goes wrong:** one says the lockouts live in a table (they survive a restart, and are
  in every backup), the other that a restart clears them. The unlock's own counter can't be in
  the database at all, since the database is closed while locked (D2-17's side of it).
- **Remedy:** `schema.md` §4.4.4 drops the attempt counters (S13.7.5.5 holds them in memory),
  or S13.7.5.5 names which counters are kept in the database and why.
- **Units:** 09 web-ui-architecture (S13.7.5), 08 linked-servers (S11.9.3.3), 06
  receipts-storage (the store's tables).

#### DC-10: the link protocol keeps remote usernames up to 64 and display names up to 120; S10.1.1's limits (32, 80) govern the same `User` rows

- **Kind:** limit given differently. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Ids:** S10.1.1, S10.3.3.1 (block 2 digest: "username 2–32 chars …; display name ≤ 80";
  "a remote user is a `User` row with `linkId` set") and `link-protocol.md` §4.2 (block 3
  digest: "display name ≤ 120 chars, username ≤ 64, sex other than `female`/`male` as
  `male`").
- **Where:**
  - `S10-users-and-sharing.md:7–10`: "A username is 2 to 32 lowercase letters, digits, dots,
    dashes or underscores, beginning with a letter or digit; … A display name is at most 80
    characters".
  - `S10-users-and-sharing.md:108–111`: "**A remote user is a `User` record** with its
    `linkId` set … and its fields come only from its server (S11.3)."
  - `link-protocol.md:128–130`: "It keeps a display name of up to 120 characters and a
    username of up to 64, and a sex other than `female` or `male` as `male`".
- **What goes wrong:** whichever the code's `User` checks enforce, one document is wrong: a
  `CHECK` or validator built from S10.1.1 refuses a 33–64 character remote username the
  protocol says to keep, and a whole directory exchange may fail on one row. "Keeps … up to"
  also doesn't say whether a longer one is cut or refused.
- **Remedy:** S10.3.3.1 says a remote user's fields follow `link-protocol.md` §4.2, not
  S10.1.1, and §4.2 says a longer value is cut to the limit (or the row skipped, and which).
- **Units:** 07 users-sharing (S10), 08 linked-servers.

#### DC-11: S11.1.2 says the joining server sends "B's own address and key … and nothing else"; the protocol's `join` also carries its certificate's fingerprint

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Ids:** S11.1.2 (block 2 digest: "sends B's address and key signed with it, nothing else")
  and `link-protocol.md` §4.1.2 (block 3 digest: "`join` with `{code, address, t}` (its own
  cert fingerprint when own)").
- **Where:**
  - `S11-linked-servers.md:13–15`: "sends B's own address and key, signed with it, and
    nothing else: no user list crosses before A's admin approves."
  - `link-protocol.md:103–104`: "It then calls `join`, signed by its own key, with
    `{code, address, t}`, `t` being its own certificate key's fingerprint when its certificate
    is its own".
- **What goes wrong:** A needs `t` to verify B's own certificate when A calls B (S11.1.3), so
  the protocol is right; S11.1.2's "nothing else" reads as forbidding it, and a unit checking
  the code against S11.1.2 would flag a correct field.
- **Remedy:** S11.1.2: "sends B's own address and key, and its certificate's fingerprint when
  the certificate is its own, signed with the key; no user list crosses before A's admin
  approves."
- **Units:** 08 linked-servers.

#### DC-12: S9.2 encrypts local receipts in S11.9.6's format, whose key label and associated data are written only for links

- **Kind:** behaviour named and never specified, across blocks. **Severity:** Low. **Conf:** 0.
  **Status:** open. Not withheld: an unstated label is a gap in the description, not a
  weakness of the format.
- **Ids:** S9.2 (block 1 digest: "streaming format of S11.9.6 under the receipts key
  (S15.3.2), file id as associated data") and S11.9.6 (block 2 digest: "label
  `moolakata link receipt` or `moolakata link change`; … associated data names link, receipt
  or change, and chunk number").
- **Where:**
  - `S9-receipts.md:14–16`: "Files use the streaming format of S11.9.6 under the receipts key
    (S15.3.2), with the file's id as what the associated data names".
  - `S11-linked-servers.md:210–212`: "**Key**: HKDF-SHA256 over the X25519 exchange between
    the one-time key and the copy's key, with the salt, under the label `moolakata link
    receipt` or `moolakata link change`."
  - `S11-linked-servers.md:215–216`: "The associated data names the link, the receipt or
    change, and the chunk's number".
- **What goes wrong:** a household's own receipt has no link and no copy key; which label it
  is derived under, and what its associated data holds besides the file's id (the chunk's
  number?), is left to the code. Two readers of S9.2 could build files the other can't open,
  and a re-encryption or restore tool written later has nothing to check against.
- **Remedy:** S11.9.6 gives the local case: the receipts key in place of the copy's, its own
  label (`moolakata receipt`), and associated data of the file's id and the chunk's number.
- **Units:** 06 receipts-storage (S9.2), 10 encryption-settings (S15.3.2), 08 linked-servers
  (S11.9.6).

#### DC-13: a connector's file is limited to "the upload size in Settings", and Settings has two

- **Kind:** limit given differently / unspecified. **Severity:** Low. **Conf:** 0. **Status:**
  open. Related to D2-16 (statements up to 200 MB against 100 MB in flight), not the same.
- **Ids:** `connector-protocol.md` §1.4 (block 3 digest: "a file post multipart, the file ≤
  the upload size in Settings (S13.7.6)"), S13.7.6, S16.8 and S16.10 (block 2 digest:
  "Imports: statement file types and size (25 MB default, 1–200 MB)"; "Receipts: size limit
  25 MB (1–100)").
- **Where:**
  - `connector-protocol.md:54–55`: "a file post is multipart, the file up to the upload size
    in Settings (S13.7.6)."
  - `S13-architecture.md:124`: "uploads up to the size in Settings (25 MB by default)".
  - `S16-settings.md:38–39`: "the file types and size accepted for statement import (25 MB by
    default, 1 to 200)"; `:46`: "**Receipts**: the size limit (25 MB by default, 1 to 100)".
- **What goes wrong:** the connector posts statements (OFX, CSV, PDF), so S16.8's limit is the
  natural one, but S13.7.6 and the protocol name a single "size in Settings"; a PDF statement
  of 30 MB under a 200 MB statement limit is refused `too-large` if the code reads the
  receipts limit, and the driver drops it (S18.8: "other refusals drop the file").
- **Remedy:** S13.7.6 names both ("a receipt up to S16.10's size, a statement or other import
  file up to S16.8's"), and `connector-protocol.md` §1.4 and §7's `too-large` cite S16.8.
- **Units:** 12 connector, 09 web-ui-architecture (S13.7.6), 01 accounts-imports (S1.3).

#### DC-14: S8.15 reads the federal due date from Settings › Tax tables; S16.11's list of what the tables hold leaves it out

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Ids:** S8.15 (block 1 digest: "federal due date from Settings › Tax tables") and S16.11
  (block 2 digest: the tables' contents, with no due date).
- **Where:**
  - `S8-taxes.md:110–112`: "the due date (federal from Settings › Tax tables, moved past a
    Saturday, a Sunday or a legal holiday …)".
  - `S16-settings.md:50–54`: "**Tax tables**: per year, … shipped and correctable:
    contribution limits and thresholds, the annual gift exclusion, the 529-to-Roth lifetime
    limit, the QCD limit, the collectables rate, the unearned income above which Form 8615
    applies …, the shipped college-cost averages …, the bitcoin models' published figures …,
    and the metal per share of SLV, PPLT and PALL". And `:55–56`: "A year after the latest
    shipped uses the latest."
- **What goes wrong:** the unit for S16 has no row to check for the due date, and "a year
  after the latest uses the latest" would give a later year last year's date (April 15 of the
  wrong year) unless the due date is stored as a month and day.
- **Remedy:** S16.11 lists the federal due date (as month and day, before the IRC §7503
  moves), and says a later year takes the month and day, not the date.
- **Units:** 04 projections-taxes (S8.15), 10 encryption-settings (S16.11).

#### DC-15: `operations.md` says daily emails follow the container's time zone; S12.11.5 sends each user's summary in that user's zone

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Ids:** S12.11.5, S16.16, S14.9 (block 2 digest: "daily summary (time in Settings › Alerts,
  07:00 default, user's time zone …)") and `operations.md` §2.3 (block 3 digest: "container
  gets the host's time zone …, which backups and daily emails follow").
- **Where:**
  - `operations.md:91–92`: "The compose file gives the container the host's time zone
    (`/etc/localtime` and `TZ`), which backups and daily emails follow."
  - `S12-web-ui.md:250–251`: "**daily summary**: one email a day at the time set in Settings ›
    Alerts (07:00 by default, in each user's time zone, S14.9)".
- **What goes wrong:** true only for users on **Auto** (S14.9); an operator who reads
  `operations.md` expects a user in another zone to get the summary at the host's 07:00.
- **Remedy:** `operations.md` §2.3: "which backups follow, and the daily summary for each user
  whose time zone is Auto (S14.9)".
- **Units:** 09 web-ui-architecture (S12.11).

#### DC-16: the README gives the linked copy's release and the alert threshold as fixed figures; S11, S16 make both settings

- **Kind:** the same thing specified twice, differently (a default stated as a fixed value).
  **Severity:** Low. **Conf:** 0. **Status:** open. The block-2 digest notes the first ("S16.9
  makes the hour a setting") without a claim.
- **Ids:** R1.18, R2.10, R1.25 (block 1 digest: "key released after an hour unused"; "admins
  alerted when a source has failed for more than 48 hours") and S11.7.3, S16.9, S16.16 (block
  2 digest: "**Release linked keys after**, 1 hour by default", "5 minutes to 24 hours";
  "failure threshold 48 hours (1–336)").
- **Where:**
  - `README.md:168`: "The copy keeps syncing while it is locked, and its key is released after
    an hour unused (S11.9)."
  - `README.md:233–234`: "The copy is **locked** until someone it shares with enters the
    words, and locks again after an hour unused."
  - `README.md:197–198`: "above all admins when a source has failed for more than 48 hours."
  - `S16-settings.md:44–45`: "**Release linked keys after** (one hour unused by default, 5
    minutes to 24 hours)"; `:96–97`: "how long a source may fail before it raises an alert (48
    hours by default, 1 to 336)".
- **What goes wrong:** little in the code; a reader of R2.10, the terminology a unit checks
  terms against, takes the hour as fixed.
- **Remedy:** "after an hour unused by default" in R1.18 and R2.10, "for longer than the
  threshold, 48 hours by default" in R1.25.
- **Units:** none in practice (documents); S11.9.4 is unit 08, S16 unit 10.

#### DC-17: R1.7 names the share levels **read** and **read/write**; R2.9 and S10 call the second `write`

- **Kind:** term used other than R2 defines. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Ids:** R1.7 (block 1 digest: "shares them at `read` or `read/write`") and R2.9, S10.3.2,
  S10.4 (block 2 digest: "`read` or `write`"; "local: **None · Read · Write**").
- **Where:**
  - `README.md:131–132`: "Any user can create accounts and portfolios and share them with
    users or groups, **read** or **read/write** (S10)." (and `:8`, "read-only or read/write").
  - `README.md:227–229`: "at a **level**: `read` or `write` (S10)".
  - `S10-users-and-sharing.md:121`: "a three-way switch **None · Read · Write**".
- **What goes wrong:** R2 defines the levels as `read` and `write`; R1.7 uses a third name in
  bold, as if it were a level's label. Small, but the level's value is an API and database
  enum the units check.
- **Remedy:** R1.7 and the README's opening: "**read** or **write**".
- **Units:** none (documents); unit 07 checks the enum.

#### DC-18: S13.8.6 says secrets have no version; `schema.md` gives every table with an `id` one

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Ids:** S13.8.6 (block 2 digest: "link pairs and secrets have none") and `schema.md` §2
  (block 3 digest: "every table with an `id` has `version` …, `createdAt`, `updatedAt`"; §3.1
  has `Secr`).
- **Where:**
  - `S13-architecture.md:227–229`: "Pairs that only link two records (a receipt and a
    transaction, an account counted in someone's totals) and secrets, which are replaced
    outright, have no version."
  - `schema.md:50–52`: "**Record fields.** Each table with an `id` also has `version` (an
    integer that changes with every save, which the API's `If-Match` compares, requirements
    S13.8.6)".
- **What goes wrong:** the pairs are many-to-many tables with no `id`, so they agree; the
  secret is a `Secr` row with an `id`, so `schema.md`'s test (§5) requires a `version` the API
  section says it lacks. The likely meaning (the column exists, the API asks no `If-Match` for
  a secret) is said by neither.
- **Remedy:** S13.8.6: "… and secrets, which are replaced outright, are changed without
  `If-Match`."
- **Units:** 09 web-ui-architecture (S13.8.6), 10 encryption-settings (S15.3.3's secrets), 06
  receipts-storage (the store's tables).

#### DC-19: the configuration file's keys: DEPLOY and the example set `[server] name`, which no requirement names beside S16.1's server name

- **Kind:** behaviour named and never specified, across blocks. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Ids:** S13.3, S13.6, S16.1 (block 2 digest: "`[server] host` sets the listen address"; "a
  setting it doesn't know" refuses the start; "General: server name (shown to linked
  servers)") and `DEPLOY.md` §3.3 (block 3 digest: "`moolakata-tls.toml` with `[server] name,
  mode = "tls", port = 37373`, `[paths] data, backups`, `[tls] names`").
- **Where:**
  - `DEPLOY.md:160–170`: "`[server]` / `name = "moolakata"` / `mode = "tls"` / `port = 37373` /
    `[paths]` / `data = …` / `backups = …` / `[tls]` / `names = [...]`".
  - `web/install/moolakata.toml:5–8`: "# Shown in logs and the self-signed certificate. The name
    linked servers see is set in Settings › General. / name = "moolakata"".
  - `S16-settings.md:7`: "**General**: server name (shown to linked servers)".
  - `S13-architecture.md:55–57`: "a config file it can't use or with a key it doesn't know …
    it says why in one `refusing to start:` line and exits 78".
- **What goes wrong:** the server has two names, the config's (logs, the self-signed
  certificate S13.3 says "names the server") and S16.1's (linked servers), and the requirements
  name only the second. Since S13.6 refuses an unknown key, the set of keys is behaviour the
  code is checked against, yet only the example file and DEPLOY list it (`[server] name`,
  `mode`, `port`, `trusted_proxies`, `host`; `[paths]`; `[tls]`).
- **Remedy:** S13.3 (or S17.8) lists the configuration's keys with a line each, `[server]
  name` among them, and says which name the certificate carries.
- **Units:** 09 web-ui-architecture (S13.3, S13.6, and `config.py`, which the map puts there),
  11 implementation (the install files).

#### DC-20: S17.2 lists the server's dependencies "each a ruling" without python-multipart, which `dependencies.md` registers

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Ids:** S17.2 (block 2 digest: the list, ending "… pi-heif, numpy") and `dependencies.md`
  (block 3 digest: "python-multipart 0.0.32").
- **Where:**
  - `S17-implementation-02-server-dependencies.md:3–8`: "**Server dependencies**, each a
    ruling, kept short because each runs with the database: fastapi, pydantic, hypercorn,
    sqlalchemy, alembic, argon2-cffi, cryptography …, httpx, segno …, **Pillow** and
    **pypdfium2** …, **sqlcipher3** …, **rapidocr** with **onnxruntime**".
  - `dependencies.md:52`: "| python-multipart | 0.0.32 | multipart uploads | FastAPI's parser
    for files | parsing untrusted input: the request limits (S13.7.6) bound it |".
- **What goes wrong:** a direct dependency that parses every upload and the connector's file
  posts has no ruling; a unit checking `uv.lock` against S17.2 finds a dependency the
  requirements don't name. (S17.2 also calls cryptography "AES-GCM, Ed25519 for links", where
  S15 and S11.9 use its HKDF and X25519 too.)
- **Remedy:** S17.2 adds python-multipart (multipart uploads, bounded by S13.7.6), and
  cryptography's list reads "AES-GCM, HKDF, Ed25519, X25519".
- **Units:** 11 implementation (S17.2).

#### DC-21: S17.1's layout of `docs/` leaves out RELEASE.md, GENESIS.md, REVIEW.md, `reviews/`, `release/` and `external/`

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Ids:** S17.1 (block 2 digest: "`docs/` (requirements, schema.md, api.md, link-protocol.md,
  connector-protocol.md, operations.md, DEPLOY.md, dependencies.md, test-plan.md, mockups)")
  and the documents block 3 read (RELEASE.md, GENESIS.md, external/README.md), which RELEASE
  cites as S17.10.2's.
- **Where:** `S17-implementation-01-layout.md:7–12`: "docs/ requirements/ (README.md and its
  sections), schema.md, api.md, link-protocol.md, connector-protocol.md, operations.md,
  DEPLOY.md (…), dependencies.md (…), test-plan.md (…), mockups/MoolaKata-mock.html".
- **What goes wrong:** the layout is where a reader learns what lives where; the release
  process, the one-time setup, the review process and its reviews, and the outside copies the
  requirements rest on are missing from it.
- **Remedy:** S17.1's `docs/` line adds RELEASE.md (S17.10), GENESIS.md, REVIEW.md and
  `reviews/`, `release/` and `external/`.
- **Units:** 11 implementation (S17.1; a test may hold the layout).

### Found outside the comparison's scope

#### DC-22: S10.6 offers a **From linked servers** filter on the account lists; S12.10.5 and rejected idea 7 keep linked accounts out of them

- **Kind:** contradiction within block 2, which `docs-2-platform` didn't claim; recorded here
  so it isn't lost. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Ids:** S10.6 (block 2 digest: "filters All, Mine, Shared with me, Shared by me, From linked
  servers") and S12.10.5, rejected idea 7 (block 2 digest: "nothing from a linked household
  in this household's lists …"; "linked accounts shown among this household's own").
- **Where:**
  - `S10-users-and-sharing.md:130–133`: "**A shared account appears in the receiver's lists**
    … Filters: All, Mine, Shared with me, Shared by me, From linked servers."
  - `S12-web-ui.md:202`: "**Never mixed**: nothing from a linked household appears in this
    household's lists,".
  - `rejected-ideas.md:25–27`: "**Linked accounts shown among this household's own**, as locked
    rows, in totals or inside local portfolios. Another household's data is a world of its own
    and opens in its own window (S12.10)."
- **What goes wrong:** the filter can only show linked accounts in a local list, which S12.10.5
  forbids and the rejected idea turned down; the mockup has no such filter.
- **Remedy:** S10.6's filters end at **Shared by me**; linked households are reached as
  S12.10.1 says.
- **Units:** 07 users-sharing (S10.6), 09 web-ui-architecture (S12.10).

## Cross-block conflicts the blocks already claimed

Seen in the digests and left as they are, each already naming both sides: D1-8 (S1.4 against
S16.11), D1-25 (S9.6 against S8.14.3 and S10.3), D2-2 (S11.4, S11.5.1 against L6), D2-11
(S12.2.16 against S1.6.4's bitcoin unit), D2-20 (S14.1.5, S14.10 against `schema.md`), D2-22
(R1.5 against S17.7), D3-2, D3-3, D3-4 (the protocol against S11.4, S11.9.6), D3-7 (T5–T6
against S11.1.2), D3-12, D3-13, D3-14 (the connector protocol, operations and DEPLOY against
S18.4, S18.9.1), D3-15 (against S16.14), D3-16 (against S13.6), D3-17, D3-18 (RELEASE and
dependencies against S17.8.2, S17.10.3), D3-19 (against R2.9), D3-22 (S11.9.1's citation),
D3-23 (`/mcp` against S13.8.2).

**The digests against their sources.** Every digest line a claim here rests on was checked
against its source and held; none misstated it. Candidates dropped on reading the source: the
order of account groups (S1.1's table is not a display order, S12.2.2 is); Q30 against S18.3.1
(Q30 asks whether to change what S18.3.1 states); GENESIS's `DOCKERHUB_USERNAME` against
S17.10.3's "one secret" (it is a variable, `GENESIS.md:228`); `operations.md` §8's "add where it
calls from" against S16.14's default ranges (it is about a laptop away from home, which S16.14
says too); `If-Match`'s quotes in `api.md` (more specific, not contrary).

## Summary

| Id | Sev | Ids compared | In one line | Units |
|---|---|---|---|---|
| DC-1 | Med | D2-1 + D3-1 | A receipt over ~20 MB can't cross a link; may stall the exchange (join) | 08, 09, 10 |
| DC-2 | Med | D2-3 + DEPLOY, operations | The runbook installs a relied-on TrueNAS server in `tls` mode, which DEPLOY and S13.3 call testing (join) | 09, 10, 11 |
| DC-3 | Low | D2-4 + D3-6 | A link's states, and what leaves *broken* (join) | 08 |
| DC-4 | Low | D1-5 + D2-25 | "Later" pointing at out of scope (join) | — |
| DC-5 | Low | D2-19 + schema.md | The unbounded email queue, in `schema.md` too (join) | 07, 10 |
| DC-6 | Low | S14.3 / S1.9.2 | Half-even except tax rules, yet loan interest rounds half up | 02, 06 |
| DC-7 | Low | S1.6.2.3 / schema §2 | Bitcoin Core wallets named by account id, which carries its creation time | 02 |
| DC-8 | Low | S13.6 / operations §3 | A newer DB refused at start (operations) or at unlock (S13.6, operations §5.1) | 09, 06 |
| DC-9 | Low | S13.7.5.5 / schema §4.4.4 | Attempt counters in memory or in tables | 09, 08, 06 |
| DC-10 | Low | S10.1.1 / link-protocol §4.2 | Remote usernames up to 64 and names up to 120 against `User` limits of 32 and 80 | 07, 08 |
| DC-11 | Low | S11.1.2 / link-protocol §4.1.2 | "Nothing else" against `join`'s `t` | 08 |
| DC-12 | Low | S9.2 / S11.9.6 | Local receipt files' key label and associated data unstated | 06, 10, 08 |
| DC-13 | Low | connector §1.4 / S13.7.6, S16.8, S16.10 | "The upload size in Settings" when there are two | 12, 09, 01 |
| DC-14 | Low | S8.15 / S16.11 | The federal due date read from tax tables that don't list it | 04, 10 |
| DC-15 | Low | S12.11.5 / operations §2.3 | Daily emails in the host's zone or each user's | 09 |
| DC-16 | Low | R1.18, R2.10, R1.25 / S16.9, S16.16 | README states two settings' defaults as fixed | — (08, 10) |
| DC-17 | Low | R1.7 / R2.9, S10 | **read/write** against `write` | — (07) |
| DC-18 | Low | S13.8.6 / schema §2 | Secrets "have no version", every table with an `id` has one | 09, 10, 06 |
| DC-19 | Low | S13.3, S16.1 / DEPLOY §3.3 | The config file's keys, `[server] name` among them, are in no requirement | 09, 11 |
| DC-20 | Low | S17.2 / dependencies.md | python-multipart has no ruling | 11 |
| DC-21 | Low | S17.1 / RELEASE, GENESIS, external | The layout of `docs/` misses six entries | 11 |
| DC-22 | Low | S10.6 / S12.10.5, rejected 7 | A **From linked servers** filter on local lists (within block 2) | 07, 09 |

High 0, Med 2 (DC-1, DC-2, both joins of Med block claims), Low 20. Joins: DC-1 (D2-1, D3-1),
DC-2 (D2-3, with DEPLOY and operations), DC-3 (D2-4, D3-6), DC-4 (D1-5, D2-25), DC-5 (D2-19,
with `schema.md`); at assembly each takes one review id in place of its block claims'. All at
0 confirmations, open. Withheld: none (DC-7 and DC-12 say why).

**§6 gate candidates: none.** No conflict between blocks is High. The nearest is DC-1: if unit
08 finds that one oversize receipt stalls a link's exchange for good, it becomes High there,
and it is worth deciding before unit 08 either way.

## To decide before the units

Every Phase 1 claim of any block marked as needing the user, or as worth deciding before a
unit, with the joins in place of the claims they join. None is a §6 gate (none is High), so
none holds a unit up; deciding them first saves a unit from judging code against a rule that
is about to change.

| # | Id | Sev | The question | Units |
|---|---|---|---|---|
| 1 | D1-1 | Med | A short option's capital at risk: S3.9.2's strike × shares, or S3.5.5's *unlimited*, when ungrouped and grouped | 03 |
| 2 | D1-12 | Low | Which price sources a new server has on, and whether SPY, VT, BND load "always" against R3.5's off-until-configured | 03 |
| 3 | D1-13 | Med | Who owns a category, who may add or change one, and who sets its **Keep receipts for** (S7.2 against S14.10.1.1) | 05, 06 |
| 4 | D1-25 | Med | A tax document's file: filers only (S9.6) or also `write` helpers (S8.14.3, S10.3); and S9.6's missing kinds | 06, 04 |
| 5 | DC-1 (D2-1, D3-1) | Med | Receipts over 20 MB across a link: stream sealed bodies up to the receipt limit, cap linked receipts at 20 MB, or lower S16.10's maximum | 08, 09, 10 |
| 6 | D2-2 | Med | Do a tax book's document files cross a link now (S11.4, milestone 5) or with L6 (S11.5.1) | 08 |
| 7 | DC-2 (D2-3) | Med | Is `tls` mode a supported production mode (TrueNAS catalog, operations §2.2), or do those installs move to `proxy` | 09, 10, 11 |
| 8 | DC-4 (D1-5, D2-25) | Low | Other coins, a link relay, the phone PWA: each later work (an L id) or out of scope | — |
| 9 | D3-21 | Low | `schema.md` §3.2's "Reserved … not declared yet": keep the reservation as a statement, or drop the build status | 06 |

Units 01, 02 and 07 have nothing waiting; unit 01 can start once these are walked (or at once,
since none is a gate).
