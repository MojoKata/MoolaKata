# Code review 3, Phase 1: block docs-3-protocols

**Block:** `docs-3-protocols` (docs/REVIEW.md §5). **Commit read:** `6916954` (the working tree
equals it for these files). **Started:** Oct 24, 07:10 PM (Chicago). **Checking:** quick; every
claim is at 0 confirmations.

**Read whole:** `docs/schema.md`, `docs/link-protocol.md`, `docs/connector-protocol.md`,
`docs/operations.md`, `docs/api.md`, `docs/DEPLOY.md`, `docs/RELEASE.md`, `docs/test-plan.md`,
`docs/dependencies.md` (§5's list), and `docs/GENESIS.md` and `docs/external/README.md`.
**Searched, not read whole:** the requirement items these documents cite, each opened by search
only where a document states a fact its cited item also states.

**A note on the process, not a claim about the product:** §5's table does not list
`docs/GENESIS.md` (312 lines) or `docs/external/README.md` (27 lines), and no other block reads
them, so without this session no review would. They are read here; §5's row for this block could
name them.

Line numbers are the file's at `6916954`.

## Claims

Each claim: kind, severity (High, Med, Low as `gaps.md` ranks them), confirmations (0 for
all: a quick review), status (open), the requirement or document, the lines quoted, what goes
wrong, remedy and alternatives. All rest on reading alone.

### D3-1: The link protocol's 20 MB ceiling and "bodies are JSON" leave no way for a receipt over about 20 MB to cross, and misdescribe two calls

- **Kind:** contradiction within the block, and with S13.7.6 and S16.10. **Severity:** Med.
  **Conf:** 0. **Status:** open. This is the protocol's side of `D2-1`, which asked this block
  to compare `link-protocol.md` §1.4 and §4.3; `docs-compare` may join the two.
- **Req:** S13.5, S13.7.6, S16.10, S11.9.6; `link-protocol.md` §1.4, §4, §4.3.
- **Where:**
  - `link-protocol.md:22–23`: "Bodies are JSON, UTF-8, at most 20 MB. A caller waits 10 seconds
    to connect and 20 seconds for each read, and cuts off an answer past 20 MB."
  - `link-protocol.md:91` (`file`): "one of the answering side's receipts, sealed to the caller's
    copy key (section 4.4), as `application/octet-stream`".
  - `link-protocol.md:150–153`: "The caller's receipts for a part travel in `deliver` calls of
    their own before it: each one's sealed bytes as the body, `application/octet-stream`".
  - `S16-settings.md:46`: "**Receipts**: the size limit (25 MB by default, 1 to 100)";
    `S11-linked-servers.md:206–207`: "so a 25 MB receipt is never held whole in memory".
- **What goes wrong:** two calls carry raw sealed bytes, not JSON, so §1.4's first sentence is
  wrong for them, and nothing gives them a ceiling of their own: the 20 MB applies. A 24 MB
  receipt (under the default limit) sealed in the streaming format (a header plus 16 bytes per
  64 KiB chunk) is over 20 MB: the `file` answer is cut off at every hourly exchange, and the
  same receipt pushed by `deliver` is a body past 20 MB. A receipt of up to 100 MB, which an
  admin may allow, never crosses. Nothing says what the receiving side shows, or whether the
  part that names the receipt waits for it.
- **Remedy:** §1.4 says JSON bodies are at most 20 MB and the two sealed-receipt bodies (the
  `deliver` body and the `file` answer) at most S16.10's maximum plus the format's overhead,
  read as a stream (S11.9.6); S13.5 and S13.7.6 name that exception.
- **Alternatives:** receipts cross in chunks of a few MB (a `file` with a range, a `deliver`
  with an offset); or a receipt over the ceiling crosses as its record only, marked *too large
  to send*, as `D2-1` suggests.
- **Check:** corrected. The `file` half holds and is firm: S13.5 (`S13-architecture.md:51`) cuts off every answer past 20 MB, `link-protocol.md:91` answers with the sealed receipt, so a receipt over about 20 MB never arrives (25 MB is S16.10's default). The `deliver` half rests on §1.4's own "Bodies are JSON, UTF-8, at most 20 MB" read literally for an octet-stream body; S13.7.6 names only JSON bodies and uploads "up to the size in Settings", so the requirement side is ambiguous (see D2-1's verdict). Severity unchanged (Med); scope: say the `file` fetch is the certain failure, `deliver` the same by §1.4's words.

### D3-2: When a received receipt's type is found: "when shown" in the link protocol, "when it arrived" in S11.9.6.5, and the change carries one anyway

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S11.9.6.5, S9.4; `link-protocol.md` §4.4.
- **Where:**
  - `link-protocol.md:180–181`: "The receiver keeps them as they came; its copy opens them when
    they are shown, and its type is found from the bytes then, never from the change."
  - `link-protocol.md:175`: `files`, "receipts' files added … (their id, item, type, length,
    hash, thumbnail and what was read from them)".
  - `S11-linked-servers.md:220–222`: "**Showing a receipt** streams it through decryption into
    the response, with the type checked from its bytes when it arrived (S9.4)".
- **What goes wrong:** receipts arrive sealed and usually while the copy is locked (S11.9.5), so
  the receiver can't read their bytes on arrival; S11.9.6.5's "when it arrived" can't be done
  as written, and the code will be checked against one of two moments. The `type` in `files`
  is a third source that the protocol says is never used.
- **Remedy:** S11.9.6.5 says the type is found from the bytes when the copy first opens the
  receipt (and kept in `shared.db`), as the protocol says; `files` drops `type`, or the
  protocol says it is shown only until the bytes are read.
- **Check:** confirmed. `link-protocol.md:180–181` finds the type "from the bytes then" (when shown), never from the change; `:175` still lists `type` in `files`; `S11-linked-servers.md:220–222` says "when it arrived". Receipts arrive sealed to the copy's key (S11.9.5.2), so the receiver can't read them on arrival: the two moments differ and the third source exists.

### D3-3: The caller is to check "the hash the change carried" before keeping a fetched receipt, but that hash is sealed where a locked copy can't read it

- **Kind:** contradiction within the block, and with S11.9.6.4. **Severity:** Low. **Conf:** 0.
  **Status:** open. Not withheld: the bytes are still signed by the peer's link key (the
  answer's signature over their SHA-256), so this names no forged or replayed message; it is a
  check that can't be done where the document puts it.
- **Req:** S11.9.5, S11.9.6.4; `link-protocol.md` §4, §4.4.
- **Where:**
  - `link-protocol.md:91` (`file`): "the answer's signature takes the sealed bytes' SHA-256 in
    place of the body's hash, and the caller checks it, and the hash the change carried, before
    keeping the file".
  - `link-protocol.md:174`: `fetch`, registry: "the ids of the receipts the part sends";
    `:175`: the `hash` is in `files`, inside `sealed`, "which only the copy opens" (`:163–164`).
  - `S11-linked-servers.md:217–218`: "`shared.db` records each receipt's file name, length and
    plaintext SHA-256 … The hash is checked as the file is shown".
- **What goes wrong:** pulls run while the copy is locked (S11.9.5), when the receiving server
  can read only the registry; the registry names the receipts but carries no hash, and the
  hash in `files` is of the plaintext anyway. "Before keeping the file" can only check the
  answer's signature; a code reviewer can't tell which check the protocol requires.
- **Remedy:** the protocol says the caller checks the answer's signature over the sealed
  bytes before keeping them, and the plaintext hash when the copy opens them (S11.9.6.4).
- **Alternatives:** the registry's `fetch` carries each sealed file's SHA-256, so the check
  before keeping is possible while locked.
- **Check:** confirmed. `link-protocol.md:91` has the caller check "the hash the change carried" before keeping the file; that hash is in `files`, inside `sealed` (`:175`), and the registry's `fetch` (`:174`) carries ids only; S11.9.6.4 checks the plaintext hash as the file is shown. A locked copy (S11.9.5) can't do the first check where §4 puts it.

### D3-4: A large change's parts still to send are kept "in memory", with a 2 GB change as the example

- **Kind:** behaviour specified in a way that can't hold (a bug candidate). **Severity:** Low.
  **Conf:** 0. **Status:** open.
- **Req:** S11.4, S11.7.1; `link-protocol.md` §4.4.3; DEPLOY.md §1.
- **Where:**
  - `link-protocol.md:198–201`: "the receiver shows how far it has come (*Up to July 2022, 47 MB
    of 2 GB*). … The source keeps the parts still to send in memory, so after it restarts
    `next` answers nothing and the caller's next exchange asks for everything."
  - `DEPLOY.md:18–19`: "with **2 GB of memory** for MoolaKata (1 GB with receipt reading turned
    off".
- **What goes wrong:** read literally, the source holds the rest of a first full snapshot in
  memory while the peer pulls it part by part; for the protocol's own 2 GB example that is more
  than DEPLOY gives the whole server. Two links pulling at once double it. A server that runs
  out of memory restarts locked (S13.6), and the peer then asks for everything again.
- **Remedy:** the protocol says what is kept between `next` calls: a cursor (the item and date
  reached) from which each part is worked out when asked, so memory holds at most one part
  (about 4 MB); a restart still answers nothing and the caller asks for everything.
- **Alternatives:** the parts are written sealed to a spool under the data directory and
  deleted as they are fetched or when the exchange is abandoned.
- **Check:** confirmed. `link-protocol.md:199–201` says the source "keeps the parts still to send in memory" and gives a 2 GB change as its own example; `DEPLOY.md:18–19` gives the server 2 GB. Read literally the two don't fit; nothing in S11.4 or S11.7.1 says what else is kept.

### D3-5: Receipts delivered ahead of their part are kept "until the part that names it arrives", with nothing for a part that never comes

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open. Not withheld: only an approved, signing peer can deliver, and the effect is
  disk used on the receiving side, which the admin can end by ending the link.
- **Req:** S11.9.5.2, S11.9.6.6; `link-protocol.md` §4.3.4.
- **Where:**
  - `link-protocol.md:150–155`: "The caller's receipts for a part travel in `deliver` calls of
    their own before it … the answering side keeps each as it came until the part that names it
    arrives, so it never has to call back to fetch them."
  - `S11-linked-servers.md:224–226`: "each file is written under a temporary name, synced to disk
    and renamed before its row is committed. A sweeper removes files that no row names, left
    behind after a crash."
- **What goes wrong:** the caller delivers three receipts, then its part is refused
  (`change-refused`) or the caller restarts and its next exchange asks for everything: the three
  files have no row. Either the sweeper removes them at once (they have no row even while
  waiting, so it could remove them before their part arrives) or nothing ever does.
- **Remedy:** the protocol says how long a delivered receipt waits for its part (until the end
  of that exchange, or an hour), and the sweeper's rule leaves files that wait and removes them
  after that.
- **Check:** confirmed. `link-protocol.md:150–155` keeps a delivered receipt "until the part that names it arrives"; S11.9.5.2 writes receipts straight into `receipts/` and S11.9.6.6's sweeper removes "files that no row names": a waiting receipt has no row, and no rule says how long it waits or who removes it if its part never comes.

### D3-6: The link protocol's states: *broken* allows no call the table names, nothing moves a link out of it, and linking again with the same key is unspecified

- **Kind:** behaviour named and never specified; with `D2-4` (S11.7's list of states).
  **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S11.6, S11.7; `link-protocol.md` §4, §4.1, §7.
- **Where:**
  - `link-protocol.md:83–93`: the calls' "Link states" are `pending`, `requested`, `active`,
    `paused` (and "an invitation" for `join`); `:254`: "`link-<state>` | the link exists here but
    its state doesn't allow the call"; `:260`: "`already-linked` | the two servers already have a
    link".
  - `link-protocol.md:264–265`: "A `not-linked` answer (a peer restored from an older backup, say)
    only marks the link broken and alerts admins (S11.6)."
  - `S11-linked-servers.md:100–101`: "marks the link broken and alerts admins, who end it or link
    again"; `:103`: "state (active, paused until…, unreachable since…, ended)".
- **What goes wrong:** B is restored from a backup made before the link. A's next exchange gets
  `not-linked` and marks the link broken. The admins "link again": B invites, A joins with the
  same link key. Nothing says whether A's join is refused `already-linked` (A still holds a
  broken link with B's key), whether a second link with the same key is made beside it (then a
  signed call from B matches two links), or whether the new one replaces the broken one; nor
  whether a broken link still answers `ping` or `end`, or ever recovers by itself.
- **Remedy:** §4 lists every state on each side (invitation, requested, pending, active, paused,
  broken, ended) with the calls each allows; §4.1 says a join from a key whose link here is
  broken replaces that link (its copy and remote users go, as `end` would).
- **Check:** confirmed. §4's "Link states" column (`link-protocol.md:83–93`) never lists *broken*; the only places that name it are `:264–265`, S11.6 and S12.11; `already-linked` (`:260`) has no definition for a broken link; nothing says whether a broken link answers `ping` or `end`, or how it leaves that state. (The relink case is clearest when the peer that kept the broken link is the inviting side, which is the one that answers `join`.)

### D3-7: S11.1.2's approval that reaches the joining side "at once" has no call in the protocol, and the test plan expects *active* within a minute

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S11.1.2; `link-protocol.md` §4.1.3; `test-plan.md` T5–T6.
- **Where:**
  - `S11-linked-servers.md:16–17`: "B's link waits for the approval, which reaches it at once or at
    its next exchange."
  - `link-protocol.md:107–111`: "The joining side's link waits as **pending** until the first
    `exchange` from the inviting side, which only an approved link makes, or until its own
    `exchange` is answered as active."
  - `test-plan.md:57–59`: "A: compare the fingerprints by phone, Approve. Passing: both show
    *active* within a minute".
- **What goes wrong:** exchanges are hourly (§4.3.1), and nothing says the inviting side makes
  one when its admin approves. In T6's one-way setup (only A serves), A can't reach B, so B
  learns at its own next exchange, up to an hour later; T5.2 fails though the code does what
  the protocol says.
- **Remedy:** the protocol says the approving side calls `exchange` at once when it can reach
  the peer, and the joining side, while pending, calls `ping` (or `exchange`) every minute for
  the first ten minutes, as the connector reports every 15 s while waiting (S18.5).
- **Alternatives:** T5.2 passes "within an hour, or at once after Pull now on B".
- **Check:** corrected. The gap holds: S11.1.2 (`:16–17`) has the approval reach the joiner "at once or at its next exchange", `link-protocol.md:107–111` has no call for "at once", and exchanges are hourly or by Pull now (§4.3.1). The T6 example is wrong: T5.2 is step 2 (`test-plan.md:57–59`), run with both servers reachable, before step 4 closes one side; the failure needs no one-way setup, only that nothing makes an exchange at approval. Severity unchanged (Low); drop the T6 sentence.

### D3-8: The kinds a shared item travels as are never named on the wire

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** R2.9, S10.3, S11.3.1; `link-protocol.md` §4.2, §4.4, §5.3, §6.
- **Where:**
  - `link-protocol.md:171`: `items`: "`id`, `kind`, `ownerName`, …"; `:129–130`: "a kind of up to
    20 characters".
  - `link-protocol.md:228–230`: "Shared items carry their kind (section 6). An item of a kind this
    server doesn't know is kept in the linked copy but not shown".
  - `link-protocol.md:234–238` (§6, whole): "Each shared item travels as its screens show it …
    Items of a kind the receiver doesn't know are kept in its copy and not shown (section 5.3)."
- **What goes wrong:** §5.3's compatibility rule turns on the kind's string, and §6, which §5.3
  points to for it, names none. Two releases that spell a kind differently (`taxBook`,
  `tax-book`, `TaxBook`) each hide the other's tax books as "a kind this server doesn't know".
- **Remedy:** §6 lists the eight kinds' wire names (R2.9, S10.3), each with its documents
  (§4.4.1 already lists them, by kind, without the names).
- **Check:** confirmed. S10.3's table (`S10-users-and-sharing.md:83–94`) names eight kinds in words; `link-protocol.md` §4.4 (`kind`, up to 20 characters), §5.3 and §6 turn compatibility on the kind's string and never give a spelling. §4.4.1 lists the documents per item in prose without wire names.

### D3-9: The unsigned `hello` of both protocols and `/healthz` tell anyone the exact MoolaKata version, though nothing they serve needs it

- **Kind:** security. **Severity:** Low. **Conf:** 0. **Status:** open. Not withheld: Low, and a
  version number is no weakness of itself; it only spares an attacker a guess when a release
  has one.
- **Req:** S13.6, S16.14, S11.1.2, S18.4.2; `link-protocol.md` §4, `connector-protocol.md` §4,
  `operations.md` §1.1, §5.
- **Where:**
  - `link-protocol.md:85`: "`GET /link/v1/hello` | no | any | `{protocol, version, fingerprint,
    key}` … lets a joining server check the fingerprint in a link code before it sends
    anything"; `connector-protocol.md:127` likewise for `/connector/v1/hello`.
  - `operations.md:196–197`: "point an uptime monitor … at `https://<your address>/healthz`: it
    answers `{"status": "ok", "version": …}`"; `S16-settings.md:87–88`: "`/healthz` and `/demo`
    answer any address".
  - `operations.md:30–46` (§1.1): the household exposes only `/link/` to the internet.
- **What goes wrong:** a household that follows §1.1 exposes `/link/` alone, and
  `/link/v1/hello` then names its exact release to every scanner, unsigned; a public uptime
  monitor does the same through `/healthz`. The joining server needs only `protocol`,
  `fingerprint` and `key`; the peer's version reaches Settings from `MK-Link-Version` on signed
  calls (`link-protocol.md:45`, §5.4). (S13.6 has `GET /ui/api/unlock` name the version to
  anyone who reaches `/ui`, which §1.1 keeps on the household's network.)
- **Remedy:** `hello` answers `{protocol, fingerprint, key}`, and `/healthz` its status alone;
  the version stays on signed answers and signed-in screens.
- **Alternatives:** keep it, and say in S13.6 that the version is public by choice.
- **Check:** confirmed. `link-protocol.md:85` and `connector-protocol.md:127` put `version` in the unsigned `hello`; `operations.md:196–197` has `/healthz` answer `{"status": "ok", "version": …}`, and S16.14 lets `/healthz` answer any address; §1.1 exposes only `/link/`. Each protocol's text uses `hello` only for the fingerprint check, and signed calls carry `MK-Link-Version`. Low, not a security or privacy claim at Med or High.

### D3-10: The connector protocol disagrees with itself on the pairing call's fields and the report's answer

- **Kind:** contradiction within a document. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S18.4.2, S18.5; `connector-protocol.md` §1.2, §4.1, §4.2.
- **Where:**
  - `connector-protocol.md:23`: "`POST /connector/v1/pair {code, sealingKey, sealingSig}`" against
    `:147`: "with `{code, sealingKey, sealingSignature, version, protocol}`".
  - `connector-protocol.md:48–50`: "every report's answer, signed, carries its key's fingerprint
    as `certificate`", while the answer it shows (`:197–208`) has `connections`, `removed` and
    `confirmed` and no `certificate`; the glance (`:27–28`) shows neither `confirmed` nor
    `certificate`, and gives `sealed` as "only if unlocked", leaving out the confirmation
    `:213–214` also requires.
  - `connector-protocol.md:159–160`: "The connector then keeps, per server, the address, … One
    connector is paired with one server".
- **What goes wrong:** a test or a second implementation written from the glance sends
  `sealingSig` and is refused; one written from §4.2's example never reads `certificate`, so a
  renewed own certificate is refused at the next report instead of being accepted beside the
  pinned one (§1.2).
- **Remedy:** one field name (`sealingSignature`, as S18.4.2's "the sealing key signed with the
  identity key" and §4.1.2 give); `certificate` and `confirmed` in the example and the glance;
  "keeps with the pairing" for "per server".
- **Check:** confirmed. `connector-protocol.md:23` has `sealingSig` and `:147` `sealingSignature`; `:48–50` says every report's answer carries `certificate`, which neither §4.2's example (`:197–208`) nor the glance (`:27–28`) shows; the glance also omits `confirmed` and the confirmation `:213–214` requires for `sealed`; `:159` says "per server" against `:160`'s one server.

### D3-11: Which refusals are unsigned differs between the two protocols, though the connector's "follows the link protocol wherever the two do the same thing"

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open. Not withheld: about answers the caller can't verify and therefore drops,
  not about one it would wrongly accept.
- **Req:** S13.7.5.4, S13.7.6, S18.8; `link-protocol.md` §7, `connector-protocol.md` §3.3, §7.
- **Where:**
  - `connector-protocol.md:6–7`: "It follows the link protocol (`link-protocol.md`) wherever the
    two do the same thing".
  - `link-protocol.md:253`, `:255`: `not-linked` "unsigned when the call's body is over 1 MB,
    refused on its headers before the body is read"; `limit` "(429, unsigned, with
    `Retry-After`)".
  - `connector-protocol.md:317–319`: "signed as section 3 says when the call carried a nonce";
    `:338`: only `locked` is "(503, unsigned)"; `:334`: `limit`; `:337`: "`too-large` | (413) a
    body over 1 MB of JSON, or a file over the upload size"; `:113`: an answer's signature
    covers "SHA-256 of the call's body"; `:342`: the connector refuses "`answer-unsigned` (an
    answer without its signature)".
- **What goes wrong:** to sign a `too-large` answer MoolaKata must read and hash the whole
  oversized body it is refusing; to sign a `limit` it must verify before rate-limiting. If the
  code refuses on the headers, as the link protocol does, the answer is unsigned, and the
  connector drops it as `answer-unsigned`: it doesn't keep the file for a later run as §4.4.3
  says for 429, and learns nothing of a file over the limit.
- **Remedy:** the connector protocol marks `limit` and `too-large` unsigned, as the link
  protocol marks `limit`, and says the connector acts on an unsigned `locked`, `limit` or
  `too-large` and on nothing else unsigned.
- **Check:** confirmed. `link-protocol.md:253`, `:255` mark `not-linked` (over 1 MB) and `limit` unsigned; `connector-protocol.md:338` marks only `locked`, `:317–319` signs refusals "when the call carried a nonce", and `:113` has the answer's signature cover the call's body hash, which a `too-large` refusal made on headers can't have. The connector's `answer-unsigned` (`:342`) would drop such an answer.

### D3-12: A MoolaKata restored from a backup older than the pairing makes the connector delete every credential, where a link in the same case is only marked broken

- **Kind:** the same case specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S18.4.4, S11.6; `connector-protocol.md` §4.1.4, §7; `link-protocol.md` §7;
  `operations.md` §6.
- **Where:**
  - `connector-protocol.md:160–162`: "`moolakata-connector unpair` forgets it and deletes every
    credential it held for it, as a signed `not-paired` answer from MoolaKata makes it do";
    `:327`: "`not-paired` | the key isn't the paired connector's, or the pairing has ended".
  - `link-protocol.md:264–265`: "A `not-linked` answer (a peer restored from an older backup, say)
    only marks the link broken and alerts admins (S11.6)."
- **What goes wrong:** an admin pairs a connector on Monday evening; Tuesday's disk failure is
  restored from Monday's 02:30 backup (operations §6.2), which holds no pairing. The
  connector's next report gets a signed `not-paired`, and it deletes every Connection's
  credentials and its sealing key: every owner enters every sign-in again, and Schwab's
  sign-in too. One code serves both "this server ended our pairing" and "this server doesn't
  know you", and only the first should destroy anything; the link protocol makes exactly that
  distinction.
- **Remedy:** two codes: `unpaired` (the pairing this server ended: delete, as now) and
  `not-paired` (an unknown key: stop, alert on the connector's page, keep the vault until
  `unpair` or a new pairing).
- **Alternatives:** keep one code, and have operations §6 say that restoring a backup older
  than the pairing costs every credential.
- **Check:** corrected. The case holds: S18.4.4 (`S18-connector.md:222–224`) and `connector-protocol.md:160–162` make a signed `not-paired` delete every credential and the sealing key, and `:327` gives the same code to "the key isn't the paired connector's"; a link's `not-linked` only marks it broken (`link-protocol.md:264–265`, S11.6). The remedy's new code `unpaired` clashes with the connector's own call `POST /connector/v1/unpaired` (`:35`, `:133`): name the code otherwise (`pairing-ended`, say). Severity unchanged (Low).

### D3-13: OFX Direct Connect's `days` setting, which S18.9.1 names, is missing from the driver's settings

- **Kind:** contradiction with a requirement. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S18.9.1; `connector-protocol.md` §6.
- **Where:**
  - `S18-connector.md:351–352`: "it asks for the last 45 days (the Connection's `days`), or 90
    while no account matches the Connection's account number".
  - `connector-protocol.md:301`: `ofx-direct` settings: "`url`, `org`, `fid`, `accountType` (…),
    `accountId`, and `bankId` (the routing number) for a bank account".
- **What goes wrong:** the settings that cross in the report's answer have no `days`; either
  the driver can't honour a Connection's own period, or `days` travels unlisted.
- **Remedy:** §6 adds `days` (45 by default) to `ofx-direct`'s settings, or S18.9.1 drops "(the
  Connection's `days`)".
- **Check:** confirmed. `S18-connector.md:350–351` has OFX Direct Connect ask for "the last 45 days (the Connection's `days`)"; no other line of S18 defines a `days` field, and `connector-protocol.md:301` lists the driver's settings without it.

### D3-14: Which address the pairing code carries: "MoolaKata's address", the public URL, or "the public URL, or the link address"

- **Kind:** behaviour named and never specified. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S18.4.1, S11.2, S16.9; `connector-protocol.md` §1.1, §4.1; `operations.md` §8;
  `DEPLOY.md` §8.3.
- **Where:**
  - `connector-protocol.md:42–43`: "to `/connector/v1/` on MoolaKata's address, the one in the
    pairing code"; `:137–138`: `{"a": address, …}`; `S18-connector.md:167`: "**pairing code**: MoolaKata's address".
  - `operations.md:350–351`: "The connector reaches MoolaKata at the address in the code (the
    public URL, or the link address)".
  - `DEPLOY.md:475–477`: "**Settings › General › Public URL** must be the address the connector
    reaches it at …: the pairing code carries it."
- **What goes wrong:** the link address may differ from the public URL (S11.2, S16.9), and
  operations §1.1 shows a proxy that passes only `/link/*` at the link address. A code that
  carries the link address sends the connector's calls to a proxy that answers `/connector/v1/`
  with 404, and the pairing fails with `not-moolakata`.
- **Remedy:** S18.4.1 and the protocol say the code carries the public URL, and operations §8
  step 5 drops "or the link address".
- **Alternatives:** a connector address of its own in Settings › Connector, defaulting to the
  public URL.
- **Check:** confirmed. S18.4.1 (`S18-connector.md:167`) and `connector-protocol.md:43`, `:137–138` say "MoolaKata's address"; `operations.md:350–351` says "the public URL, or the link address"; `DEPLOY.md:475–477` says the Public URL; S11.2 and S16.9 make the link address a separate setting that may differ from the public URL, and §1.1 proxies only `/link/`.

### D3-15: "Allowed to connect", the name three documents give Settings › Network's ranges, is not one S16.14 gives

- **Kind:** term used other than its section defines it. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S16.14; `connector-protocol.md` §1.5, `operations.md` §8, `test-plan.md` T13.
- **Where:**
  - `connector-protocol.md:56`: "Only addresses in Settings › Network's **Allowed to connect**
    ranges reach `/connector`"; `operations.md:367`: "Settings › Network › Allowed to connect";
    `test-plan.md:137–138`: "Settings › Network › Allowed to connect".
  - `S16-settings.md:81–84`: "**Network**: the address ranges allowed to reach each path, one
    list per line … **the app** …; **linked servers** (`/link`); and **the connector**".
- **What goes wrong:** S16.14 names three lists by path (the app, linked servers, the
  connector); the documents name one field, "Allowed to connect", that no section defines. A
  tester following T13 looks for a label the screen may not have.
- **Remedy:** S16.14 gives the lists a label (*Allowed to connect*, per path), or the documents
  say "Settings › Network, the connector's ranges".
- **Check:** corrected. S16.14 (`S16-settings.md:81–84`) gives no label for the ranges, as claimed, but the mockup, the reference for the screen, does: `MoolaKata-mock.html:1643` has three fields, *Allowed to use the app (/ui)*, *Allowed to link (/link)* and *Allowed to connect (/connector)* (its guide, `:2548`, a heading *Allowed to connect*). So the screen has the label the three documents use, and the gap is S16.14 naming none of the three. Severity unchanged (Low); remedy: S16.14 names the three labels as the mockup shows them.

### D3-16: operations.md and DEPLOY.md differ on the VM's memory, what to empty after a stolen welcome, a restore's path, and the health states

- **Kind:** the same thing specified twice, differently. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S13.6, S15.4.4, S17.8; `operations.md` §2, §2.1, §3, §5; `DEPLOY.md` §1, §3.1, §4.3,
  §7.
- **Where:**
  1. Memory: `DEPLOY.md:18–19`: "**2 GB of memory** for MoolaKata (1 GB with receipt reading
     turned off"; `operations.md:112–113`: "Give the VM 2 GB of memory, or 1 GB with receipt
     reading turned off"; but `DEPLOY.md:89–90`: "4 GB of memory (MoolaKata needs 2 GB; the rest
     leaves the receipt reader room)", which makes 2 GB the need without the reader.
  2. A welcome someone else finished: `operations.md:98–100`: "its `data/` emptied … and started
     again"; `DEPLOY.md:373–375`: "empty its `data` and `backups` folders … Remove everything in
     them".
  3. Going back: `operations.md:162–163`: "restore the copy made before the upgrade with `db
     restore data/pre-upgrade/<copy>`", a host path, where §6.1 (`:239`) runs `db restore` in
     the container with container paths (`/var/backups/moolakata/<backup>`); the copy is at
     `/var/lib/moolakata/pre-upgrade/<copy>` there.
  4. Health: `operations.md:196–200` lists `ok`, `re-encrypting`, `locked`, `uninitialised`;
     `DEPLOY.md:297–298`: "`uninitialised`, `locked` or `ok`"; S13.6 (`S13-architecture.md:71–72`)
     also answers `starting` "between the unlock and readiness".
- **What goes wrong:** (1) a reader sizes a VM at 2 GB from one page and 4 GB from the other;
  (3) the command as written finds no file in the container; (4) an uptime monitor set up from
  either page meets a `starting` neither names.
- **Remedy:** one memory figure with its reason in both; one list of what to empty (`data` and
  `backups`, with the reason DEPLOY gives); the container path in §3; `starting` in both lists.
- **Check:** confirmed. Read all four: `DEPLOY.md:18–19` and `:89–90` (2 GB with the reader against 2 GB without it), `operations.md:98–100` against `DEPLOY.md:373–375` (`data/` against `data` and `backups`), `operations.md:162–163` (a host path) against `:239` and `DEPLOY.md:166` (`/var/lib/moolakata`), `operations.md:196–200` and `DEPLOY.md:297–298` against S13.6 (`S13-architecture.md:71–72`, `starting`).

### D3-17: S17.8.2's "no other tag … and none that moves" against the per-architecture tags the release pushes, keeps and overwrites

- **Kind:** contradiction with a requirement. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S17.8.2; `RELEASE.md` §2, §6, §11; `GENESIS.md` §4.
- **Where:**
  - `S17-implementation-08-packaging.md:33–34`: "tagged with the version, one tag for both
    architectures. There is no other tag, no `latest` and none that moves".
  - `RELEASE.md:70–71`: "Each image gets exactly its version's tag on both registries (`0.2.0`),
    plus the build's per-architecture tags on ghcr.io"; `:296–297`: "pushes its images as
    `0.2.0-amd64` or `0.2.0-arm64`"; `:463–464`: "The next run overwrites the per-architecture
    tags".
  - `GENESIS.md:151–152`: "Each package keeps `0.1.0`, `0.1.0-amd64` and `0.1.0-arm64`."
- **What goes wrong:** the requirement says one tag; the published packages carry three, and
  after a failed build the `-amd64`/`-arm64` tags move, which S17.8.2 says no tag does. A check
  written from S17.8.2 (one tag per version) fails on every release.
- **Remedy:** S17.8.2 names the per-architecture tags as the build's own, on ghcr.io only, not
  for installs, and moved only before a release is published.
- **Alternatives:** the joining job deletes them once the joined tag is attested.
- **Check:** confirmed. S17.8.2 (`S17-implementation-08-packaging.md:33–34`) says one tag, "no other tag … none that moves"; `RELEASE.md:70–71`, `:296–297` and `:463–464` push per-architecture tags and overwrite them on a re-run, and `GENESIS.md:151–152` shows them kept beside `0.1.0`. RELEASE says only that no tag moves "to a newer release", a narrower claim than S17.8.2's.

### D3-18: dependencies.md puts the attestation in "the release's last job", and RELEASE.md §12's list of what `setup` checks leaves out the `main` ruleset

- **Kind:** contradiction within the block. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S17.10.3; `dependencies.md` (GitHub Actions), `RELEASE.md` §6, §12, `GENESIS.md` §7.
- **Where:**
  - `dependencies.md:119`: "**egress** to Sigstore and the registry, by design, in the release's
    last job only, which alone holds `id-token: write`".
  - `RELEASE.md:318–319`: "From 0.2.0 on, the Docker Hub copy and the draft follow the joining
    job" (the job that attests, `:298–299`).
  - `RELEASE.md:482–485`: "`web/release.sh setup` checks everything `GENESIS.md` set up:
    immutable releases, the tag ruleset and its bypass list, the `docker-hub` environment …, and
    both registries' repositories being public (GENESIS.md §7)"; `GENESIS.md:296–297` (§7
    item 3): "the `main` branch's ruleset: active, on `main`, taking changes only through pull
    requests whose `check` passed".
- **What goes wrong:** a reader checking the workflow's permissions against the register looks
  for `id-token: write` on the last job (the draft), which must not have it. RELEASE's list
  reads as complete and omits a check `setup` makes.
- **Remedy:** "in the joining and attesting job only"; RELEASE §12 adds the `main` ruleset, or
  says "everything GENESIS.md §7 lists".
- **Check:** confirmed. `dependencies.md:119` says the release's "last job only" holds `id-token: write`; `RELEASE.md:294–322` has four jobs and the attesting one second (`.github/workflows/release.yml:70` puts it on `publish`, the second job; `draft` is last). `RELEASE.md:482–485` lists what `setup` checks without the `main` ruleset that `GENESIS.md:296–297` (§7 item 3) has.

### D3-19: schema.md's description of `Share` is narrower than R2.9's

- **Kind:** term used other than R2 defines it. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** R2.9, S10.3; `schema.md` §3.1.
- **Where:**
  - `schema.md:123`: "| Share | Share | A grant of an account or portfolio to a user, group or
    linked server. |"
  - `README.md` R2.9: "**Share:** a grant of one item, of the eight kinds of S10.3, to a user, a
    group or named users of a linked server, at a **level**: `read` or `write`".
- **What goes wrong:** the table says two kinds and a share "to a linked server"; R2.9 says eight
  kinds and named users there (S11.3: a link carries only what is shared with named people).
  A reader of the schema takes a share to a link as going to the whole household.
- **Remedy:** "A grant of one item, of the eight kinds, to a user, a group or named users of a
  linked server, at a level."
- **Check:** confirmed. `schema.md:123` says "of an account or portfolio to a user, group or linked server"; R2.9 (`requirements/README.md:227–229`) says one item of the eight kinds of S10.3 to a user, a group or named users of a linked server.

### D3-20: `LotPicks.saleId` is under two rulings, without the note `Lot.transactionId` gets

- **Kind:** contradiction within a document. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** `schema.md` §6.3, §6.4.
- **Where:**
  - `schema.md:241–242`: "each foreign key is declared with one of these".
  - `schema.md:263` (deleted with): "`Lot.transactionId` (also keeps ref); `LotPicks.lotId`,
    `LotPicks.saleId`"; `:264` (keeps ref): "`Lot.transactionId`, `Lot.instrumentId`;
    `LotPicks.saleId`".
- **What goes wrong:** §6.3 allows one ruling per key; `Lot.transactionId` is marked as having
  both, `LotPicks.saleId` is listed twice without it. A check of the declarations against the
  table can't tell whether the second listing is meant or left over.
- **Remedy:** mark `LotPicks.saleId` "(also keeps ref)" as `Lot.transactionId` is, and have §6.3
  say a key may be both *deleted with* and *keeps ref* (deleted with its parent, and ending no
  earlier than it).
- **Check:** confirmed. `schema.md:263` lists `LotPicks.saleId` under *deleted with* and `:264` under *keeps ref*, with no note, while `Lot.transactionId` is in both and the first listing says "(also keeps ref)"; §6.3 (`:241–242`) says each key is declared with one ruling.

### D3-21: schema.md's §3.2 "Reserved" records what is "not declared yet", a build status

- **Kind:** CLAUDE.md (schema.md follows the requirements' no-status rule). **Severity:** Low.
  **Conf:** 0. **Status:** open. **Needs the user:** whether a reserved prefix is a standing
  rule or a status line.
- **Req:** CLAUDE.md "Requirements are a statement, not a changelog" (`docs/schema.md` follows
  the same rule); `schema.md` §3.
- **Where:**
  - `schema.md:70`: "The prefixes of the tables that exist."
  - `schema.md:143–144`: "The prefixes of the entities the requirements name whose tables are not
    declared yet. A row moves to §3.1 when its table is." (one row: `Posn`, `Position`).
- **What goes wrong:** the two lists describe the build's progress (which tables exist), and the
  §3.2 row changes when the code does, not when the design does; CLAUDE.md keeps that out of
  schema.md. It also leaves R2.7's Position, a defined term, with a prefix and no table, which
  is Phase 2's to judge.
- **Remedy:** one table of prefixes, each row the entity's; whether a table is declared is the
  code's to say (the §5 check can still fail on a declared table with no row).
- **Alternatives:** keep §3.2, worded as a rule ("a prefix may be reserved for an entity the
  requirements name before its table is declared").
- **Check:** plausible. **Question:** is §3.2's *Reserved* (a prefix held for an entity before its table is declared) a standing rule of the naming scheme, or a build-status line that CLAUDE.md keeps out of schema.md? Read `schema.md:70`, `:143–144` and `Posn` (no code declares it): the text is accurate today, but "not declared yet" and "A row moves to §3.1 when its table is" describe progress, while a prefix reserved for a named entity could be worded as a rule.

### D3-22: S11.9.1 cites "schema.md §2.5", which doesn't exist

- **Kind:** reference to a removed or renumbered item. **Severity:** Low. **Conf:** 0.
  **Status:** open.
- **Req:** S11.9.1; `schema.md` §2.
- **Where:**
  - `S11-linked-servers.md:128`: "links/<random name>/        named at random, never by the link's
    id (schema.md §2.5)".
  - `schema.md:34–55`: §2 "Primary keys" is a list of unnumbered bullets; the rule meant is its
    last: "**IDs reveal when a row was created.** File names and anything else visible on disk,
    such as receipt files and a linked copy's files (requirements S11.9), use separate random
    names and never an ID." (`:53–55`).
- **What goes wrong:** the reference points at no item; `check_docs.py` checks requirement ids,
  not a document's section numbers, so nothing caught it.
- **Remedy:** cite "schema.md §2", or number §2's bullets so §2.5 exists.
- **Check:** confirmed. `S11-linked-servers.md:128` cites "schema.md §2.5"; `schema.md` §2 (`:34–55`) is a list of bullets with no subsection numbers, and its last bullet is the rule about random file names.

### D3-23: `/mcp`'s tool arguments are snake_case, where schema.md says the API's JSON uses the database's camelCase names with no layer that translates

- **Kind:** contradiction within the block. **Severity:** Low. **Conf:** 0. **Status:** open.
- **Req:** S13.8.2, S10.9.5; `schema.md` §1, `api.md` §2.
- **Where:**
  - `schema.md:30–32`: "The same names are used in Python and in the API's JSON. A table's
    columns, the attributes of its entity dataclass and the fields the browser receives all have
    the same spelling, so there's no layer that translates names."
  - `api.md:52–62`: arguments `account_id`, `portfolio_id`, `budget_id`, `book_id`.
  - `S13-architecture.md:161`: "**API conventions**, for `/ui/api` and, where they apply, `/mcp`";
    S13.8.2: "field names camelCase, as in the database (`schema.md` §1)".
- **What goes wrong:** `/mcp` translates `account_id` to `accountId`, the layer schema.md says
  doesn't exist; a reader can't tell whether its answers' fields are camelCase too.
- **Remedy:** S13.8.2 and schema.md §1 say MCP tool names and arguments follow MCP's
  snake_case (as S10.9.5's tool names do), and its answers' fields stay camelCase.
- **Alternatives:** camelCase arguments (`accountId`), as everywhere else.
- **Check:** corrected. The facts hold (`api.md:52–62` snake_case arguments; `schema.md:30–32` "no layer that translates names"), but it is a gap rather than a contradiction: schema.md §1 speaks of "the API's JSON" and "the fields the browser receives", and S13.8 (`S13-architecture.md:161`) applies its conventions to `/mcp` only "where they apply", so no sentence says whether `/mcp`'s arguments or answers follow camelCase. Kind: behaviour named and never specified. Severity unchanged (Low); the remedy stands.

## doccheck.txt: the "To read" lines in this block

One line falls in this block, and it is fine: `schema.md:139` ("proposed as a pair", what a
transfer match is, not changelog language). The documents other than `schema.md` are not held
to the no-status rule (CLAUDE.md names the requirements and `schema.md`), so DEPLOY's "the
steps were run on …", RELEASE's "written from 0.1.0's release" and GENESIS's **As set up**
records are judged fine as what those documents are for. Read by hand beyond the list:
`schema.md` §3's "tables that exist" and "not declared yet" (D3-21). Phase 0's mechanical
problems: none for this block; the prefix table was also read for order (byte order, `A`–`Z`
before `a`–`z`) and is sorted.

**GENESIS.md and external/README.md, judged as documents only.** GENESIS §5.2's Docker Hub
overview for the connector depends on Q30, which is open (`questions.md`): not raised again
(§3.6). `external/README.md` cites schwab-py as the source of Schwab's token lifetimes, a fact
about Schwab's API rather than the source of a MoolaKata design, so CLAUDE.md's free-standing
rule is judged kept. Neither raised a claim.

**Settled, not raised:** the queued email with no link (`schema.md` §4.4.4, `D2-19`); hourly
pulls with no setting (`link-protocol.md` §4.3.1, `D2-6`); the identity key beside the vault
letting a stolen volume report and post files (`operations.md` §8 step 13, stated by S18.2.4.4
as a choice); a compromised MoolaKata serving altered sealing code (S18.7.1 states it).

## Summary of the claims

| Id | Req | Sev | Kind | In one line |
|---|---|---|---|---|
| D3-1 | S13.7.6 | Med | contradiction | Link bodies "JSON, at most 20 MB", yet `deliver` and `file` carry sealed receipts that may be 25–100 MB (the protocol side of D2-1) |
| D3-2 | S11.9.6.5 | Low | twice, differently | A received receipt's type found "when shown" (protocol) or "when it arrived" (S11.9.6.5); `files` carries a `type` never used |
| D3-3 | S11.9.6.4 | Low | contradiction | The caller checks "the hash the change carried" before keeping a receipt, but that hash is sealed |
| D3-4 | S11.4 | Low | bug candidate | A large change's parts kept in memory, with a 2 GB example on a 2 GB server |
| D3-5 | S11.9.6.6 | Low | unspecified | Receipts delivered ahead of a part that never comes: kept for ever, or swept at once |
| D3-6 | S11.6 | Low | unspecified | *broken* allows no listed call, nothing leaves it, and relinking with the same key is unspecified (with D2-4) |
| D3-7 | S11.1.2 | Low | unspecified | Approval reaching the joining side "at once" has no call; T5.2 expects *active* within a minute |
| D3-8 | R2.9 | Low | unspecified | The eight kinds' wire names are never listed, though §5.3's compatibility rule turns on them |
| D3-9 | S13.6 | Low | security | Unsigned `hello` and `/healthz` name the exact version to anyone |
| D3-10 | S18.4.2 | Low | contradiction | `sealingSig` vs `sealingSignature`; the answer's `certificate` and `confirmed` missing from its example and glance |
| D3-11 | S13.7.5.4 | Low | twice, differently | Unsigned refusals: link has `limit` unsigned, connector only `locked`; a signed `too-large` needs the body it refuses |
| D3-12 | S18.4.4 | Low | twice, differently | A restore older than the pairing makes the connector delete every credential; a link in that case is only broken |
| D3-13 | S18.9.1 | Low | contradiction | `ofx-direct` settings lack the `days` S18.9.1 names |
| D3-14 | S18.4.1 | Low | unspecified | The pairing code's address: "MoolaKata's", the public URL, or "the public URL, or the link address" |
| D3-15 | S16.14 | Low | term | "Allowed to connect" is a name S16.14 never gives |
| D3-16 | S17.8 | Low | twice, differently | operations vs DEPLOY: VM memory (2 vs 4 GB), what to empty, a host path in `db restore`, `starting` left out |
| D3-17 | S17.8.2 | Low | contradiction | "No other tag … none that moves" vs per-architecture tags kept and overwritten |
| D3-18 | S17.10.3 | Low | contradiction | Attestation "in the release's last job"; RELEASE §12 omits the `main` ruleset check |
| D3-19 | R2.9 | Low | term | schema.md: a share is "of an account or portfolio … to a linked server" |
| D3-20 | schema §6.3 | Low | contradiction | `LotPicks.saleId` under two rulings without the "(also keeps ref)" note |
| D3-21 | CLAUDE.md | Low | CLAUDE.md | schema.md §3's "tables that exist" / "not declared yet" is build status; needs the user |
| D3-22 | S11.9.1 | Low | reference | S11.9.1 cites "schema.md §2.5", which doesn't exist |
| D3-23 | S13.8.2 | Low | contradiction | `/mcp` arguments snake_case vs schema.md's "no layer that translates names" |

High 0, Med 1 (D3-1), Low 22. All at 0 confirmations, open. Withheld: none (D3-3, D3-5, D3-9
and D3-11 each say why not). Needing the user: D3-21. No §6 gate claim (none is High). D3-1
(with D2-1), D3-2 to D3-8 touch the links unit, D3-10 to D3-14 the connector's, and are worth
reading before those units.

## Claims digest

One line per fact another block could contradict: the document's anchor, then the requirement
id it cites, if any. Terms, limits and defaults, encodings and algorithms, states, who may call
or do what, and what is sent, signed, sealed or stored where.

### schema.md

- §1.1–1.2: tables singular and capitalised (`User`); many-to-many tables plural (`UserGroups`, `TaxBookFilers`), keyed by the pair of foreign keys, no `id`, no prefix.
- §1.3: field names camelCase; acronyms of 3+ letters written as words (`htmlEncode`).
- §1.4: primary key `id`; a foreign key ends in `Id`; id = prefix + `_` + Crockford base32 UUIDv7 (`User_01k7ab4vstfggspkjt3my8wzr2`); first 10 chars = 48-bit ms timestamp.
- §1 (end): the same names in Python, the DB and "the API's JSON"; no translating layer (but `/mcp` arguments are snake_case: D3-23). S13.8.2.
- §2: prefix ≤ 5 chars, starts with a capital, unique across tables; UUIDv7 as exactly 26 lowercase chars of `0123456789abcdefghjkmnpqrstvwxyz` (no i, l, o, u), first char 0–7; decoder rejects uppercase and the left-out letters.
- §2: `id TEXT PRIMARY KEY`, `WITHOUT ROWID`, `CHECK (id GLOB '<Prefix>_*' AND length(id) = len(prefix)+27)`.
- §2: every table with an `id` has `version` (changes with every save; `If-Match` compares it, S13.8.6), `createdAt`, `updatedAt`.
- §2: file names and anything visible on disk (receipt files, a linked copy's files) use separate random names, never an id (S11.9; S11.9.1 cites it as "§2.5": D3-22).
- §3: prefix lists sorted by prefix in byte order (`A`–`Z` before `a`–`z`); §3.1 has 66 prefixes; §3.2 reserves `Posn` (Position) for a table not declared.
- §3.1 descriptions another block may contradict: `Cnctr` Connector = the paired connector, its public keys and its reports' state (S18.4); `Conn` Connection = one sign-in, kept by the connector, owned by a user (S18.6); `Email` QueuedEmail kept "until it is sent or its link expires"; `LItem` LinkedItem = an item a link brings in, as the main DB knows it (kind, owner, who it names); `Link` = state, address and key; `Secr` Secret = a secret sealed on its own (API key, password, private key); `Share` = "an account or portfolio to a user, group or linked server" (D3-19); `Token` AccessToken = read-only token for `/mcp`, kept as a hash of its secret; `Strat` Strategy includes "a proposal turned down" (S3.5); `XfrMt` TransferMatch = a bitcoin transfer between the owner's accounts proposed as a pair; `WAddr` worked out again; `WashS` worked out again from the trades; `Actv` Activity "never an amount"; `Alert` one per cause, open until the cause clears; `TaxFg` an admin's correction of a shipped tax figure for a year; `TxChg` an edit to a year whose federal return was filed; `User` includes a linked server's users (with `linkId`); `Persn` every user and people who never sign in.
- §4: records are never removed, only marked deleted; fields `deleted` (virtual generated from `deletedAt`), `deletedAt`, `deletedById` (null when the server deleted); `CHECK` keeps `deletedById` null while `deletedAt` is; restoring clears both; re-adding a deleted many-to-many row restores it. Every table, many-to-many included.
- §4.2: *deleted with* = FK `ondelete="CASCADE"` to a soft-deletable table; each table has a `<Table>Effective` view with `effectiveDeleted` and `effectiveDeletedAt` (earliest along the chain), generated from the declarations; code reads through the views.
- §4.3: unique indexes partial, `WHERE NOT deleted`.
- §4.4 exceptions, removed outright: sessions and one-time tokens (invitation, sign-up confirmation, reset, email change, a sign-in awaiting its two-step code) when used or expired; two-step recovery codes when used or replaced; a secret's old ciphertext when replaced or removed; linked copies (with the share or link, at Reset copy) and an inbox change once applied (S11.9); work queues and counters (receipt jobs, emails when sent or their link expires, sign-in and access-key attempt counters, tasks' last runs, live stream state); caches (thumbnails, computed series, wash sales, a wallet's addresses, a budget's month figures S7.3.10, what a link brings in, replaced each pull).
- §4.4: Activity entries and alerts are never deleted; alerts resolve then age out of the list (S12.11).
- §5: a test fails on a name breaking §1, a table with an `id` and no §3.1 row (or a row naming no table, a duplicate, an unsorted list), a missing `WITHOUT ROWID` or id `CHECK`, missing §4.1 fields or `CHECK`, or a missing or mismatched `<Table>Effective` view.
- §6 (S14.10): `endedAt` is worked out, never stored, for tables a file can attach to (`Transaction`, `Account`, `Item`, `QualifiedExpense`, `Gift`, `Donation`), by `receipts/retention.py`; asked only by file pruning and *Kept until*.
- §6.2: a deleted record's own end = earlier of its declared end and `effectiveDeletedAt`; no declared end → ends only when effectively deleted.
- §6.2 never end: `Instrument`, `Price` (S4.6), `TypedPrice`, `TaxFigure`, `Setting` while set, `TaxBook` and its filings, payments, documents, dependents; `User` (made inactive, not deleted, S10.2).
- §6.2 its date: `Transaction`, `Anchor`, `Holding`, `HoldingCheck`, `Reconciliation`, `Donation`, `QualifiedExpense`, `Receipt` (its date or upload).
- §6.2 an event: `Account` deleted or closed with nothing open; `Lot` sale of its last share; `Import` its latest transaction; `BudgetLine` the month before a later line for its category; `Gift` later of occasion and purchase; `GivingPlan` end of its year; `Item` its sale; `AccessToken` expiry or revoking; `SignupRequest` decided or expired; `Link` unlinked; `Connector` unpaired or replaced; `Connection` removed; `Relationship` its `to` date; `Strategy` its last option leg closed.
- §6.3 rulings: deleted with, keeps ref, keeps name, nullifies, prevents delete; a record's `endedAt` is the latest of its own end and that of every record that keeps a ref to it or is deleted with it (null if any is null); whatever ends still counts before its end (R3.10).
- §6.4: unlisted keys to a user or person keep name; nullifies: `Anchor.importId`, `Holding.importId`, `User.activeBudgetId`, an account's `connectionId` (sync turns off, S18.6.4); prevents delete: `Category.parentId`, `Filing.amendsId`; `Connection.ownerId` deleted with the user; `Connection.connectorId` keeps ref; `Share.itemId/userId/groupId`, `AccessToken.userId`, `User.linkId` deleted with.
- §6.4: deleting a person deletes the gifts still ideas or planned for that person alone; bought, given or received keep the name (S7.8.6).

### link-protocol.md

- §1.1: link calls are HTTPS POSTs of JSON to the peer's link address, under `/link/v1/`; the public URL by default, or the address set in Settings › Linked servers.
- §1.2 (S13.5): a link address is `https`, no query or fragment, never resolving to loopback, link-local or cloud metadata, whoever names it; LAN and overlay allowed.
- §1.2 (S13.3): the caller verifies the peer's TLS: public cert against system roots; own cert against the key fingerprint the link code carried (`t`) or announced since (§4.5).
- §1.3: everything but `hello` is signed; every answer to a signed call is signed, but for refusals §7 marks unsigned.
- §1.4: bodies JSON UTF-8 ≤ 20 MB; connect timeout 10 s; 20 s per read; answers cut off past 20 MB (D3-1: sealed receipts are octet-stream).
- §2.1: one link key per server, Ed25519, made the first time needed; private half a sealed secret (S14.4), never leaves the server.
- §2.2: fingerprint = SHA-256 of the raw 32-byte public key, hex; codes carry it whole; screens show the first 16 hex digits in four groups.
- §2.3: keys travel as raw 32 bytes, unpadded base64url.
- §3.1: headers `MK-Link-Key`, `MK-Link-Time` (Unix seconds), `MK-Link-Nonce` (16 random bytes, base64url), `MK-Link-Signature` (Ed25519, base64url), `MK-Link-Protocol`, `MK-Link-Version` (MoolaKata version, shown in Settings).
- §3.1: signed text, `\n`-joined: `MK-LINK-1`, method upper case, path with query, SHA-256 of body (hex), time, nonce, receiver's fingerprint.
- §3.2: refused: missing headers, time > 60 s from the receiver's clock, bad signature, a nonce seen from that key in the last 2 minutes, an unknown key or a state that doesn't allow the call; `clock-skew` is named on the link's state (S12.11.1.1); both hosts keep NTP.
- §3.3: answers signed with `MK-Link-Time` and `MK-Link-Signature` over `MK-LINK-1-ANSWER`, HTTP status, SHA-256 of answer body, time, the call's nonce, the caller's fingerprint, SHA-256 of the call's body; the caller refuses an answer not signed by the expected key or naming another caller or request; refusals are signed when the call carried a nonce.
- §4: `GET /link/v1/hello` unsigned, any state → `{protocol, version, fingerprint, key}`.
- §4: `POST /link/v1/ping` signed; states pending, requested, active, paused → `{protocol, version, state}`.
- §4: `POST /link/v1/join` signed by the caller's own key; against an invitation; no directory crosses.
- §4: `POST /link/v1/exchange` signed; active, or pending on the joining side; directories both ways and the answering side's change.
- §4: `POST /link/v1/next` signed; active; the next part of a large change.
- §4: `POST /link/v1/deliver` signed; active; the caller's change, or before it one of its sealed receipts.
- §4: `POST /link/v1/file` signed; active; `{id}` → one receipt sealed to the caller's copy key, `application/octet-stream`; refused `not-shared` unless a share to that link includes it; the answer's signature covers the sealed bytes' SHA-256.
- §4: `POST /link/v1/certificate` signed; active, paused; `{fingerprint}` of the caller's next TLS cert key.
- §4: `POST /link/v1/end` signed; requested, pending, active, paused; the link ended on the calling side.
- §4.1 (S11.1.1): link code = `mkl1.` + unpadded base64url of `{"a": address, "f": fingerprint, "c": secret, "t": certificate}`; `t` = SHA-256 of the inviting side's TLS cert key when the cert is its own, absent for a public one; the inviter keeps only SHA-256 of the secret; one use, 24 hours.
- §4.1.2: the joiner verifies TLS, calls `hello`, refuses unless `key` hashes to `f`; then `join` with `{code, address, t}` (its own cert fingerprint when own), signed by its own key.
- §4.1.3: the invitation becomes a request from that key (state *requested* on the inviter); its admin approves or rejects; directories cross from the first exchange after approval; the joiner stays *pending* until the inviter's first exchange or its own exchange answered active (no "at once": D3-7).
- §4.2 (S11.3): directory `{household: {serverName, name, avatar}, users: [{id, username, displayName, email, sex}]}`; only active local users; the receiver keeps remote users by `id`: added, updated, soft-deleted when off the list, restored on return.
- §4.2: the receiver keeps a display name ≤ 120 chars, username ≤ 64, sex other than `female`/`male` as `male`; an item's kind ≤ 20 chars, owner's name ≤ 120.
- §4.2 (S10.10.1): each remote user has a person here (name and sex from the directory), used only for gifts.
- §4.3.1: either side may exchange, hourly and on **Pull now**; whichever can reach the other does.
- §4.3.2: the call sends `{…directory, have, wantFull, copyKey}`: `have` = last `seq` taken; `wantFull` for a new or reset copy, overflowed inbox, or out-of-sequence change; `copyKey` = public key of the caller's linked copy (S11.9.2.2); absent before the copy has an access key, and then the answer carries only the registry.
- §4.3.3: the answer carries `{…directory, state, version, have, wantFull, copyKey}` and `change` with `more` (parts still to come), fetched with `next` until `more` is 0.
- §4.3.4: the caller then delivers its own change a part at a time with `deliver`, each answered with the new `have`; its receipts go first in their own `deliver` calls (sealed bytes as body, `application/octet-stream`, `MK-Link-File` naming the receipt, signed over the sealed bytes' SHA-256, read as a stream), kept by the answering side until the part naming them arrives; the caller fetches the other side's receipts with `file`.
- §4.3.5 (S11.4, S11.7.2): a paused side refuses data with `link-paused` saying until when; the caller waits, no failure, no alert; a removal and an end still cross.
- §4.4: a change = **registry** (kept in the receiver's main DB while the copy is locked, S11.9.1) + **sealed** part (only the copy opens).
- §4.4 registry fields: `seq`, `asOf`, `full`, `items` (`id`, `kind`, `ownerName`, `sharedAt`, `viewers` = receiver's user ids, `includeReceipts`, `version`), `removed`, `progress` (`through`, `bytes`, `total`), `fetch` (receipt ids the part sends).
- §4.4 `sealed`: to the receiver's `copyKey`, S11.9.6 streaming format, label `moolakata link change`, AD = link (`<sender fp>><receiver fp>`) and `seq`, unpadded base64url; holds item names, `docs` (`itemId`, `path`, `viewer`, `body`), `docsRemoved`, `files` (id, item, type, length, hash, thumbnail, what was read), `filesRemoved` (unshared or pruned at the source, S14.10.6).
- §4.4 `signature`: Ed25519 by the sender's link key over the registry and SHA-256 of `sealed`, as canonical JSON (keys sorted, no spaces).
- §4.4: receipt bytes sealed the same way, label `moolakata link receipt`, AD naming the link and the receipt; cross in `deliver` or a `file` answer; the receiver keeps them as they came; the type is found from the bytes when shown, never from the change (D3-2).
- §4.4.1 (S11.3.1): each item worked out as each named person would see it, with the source's own screen code; documents by API path: an account's detail, balance series, holdings, transactions; a portfolio's detail, holdings, returns, series; a budget's month, trends, cash flow, recurring payments; a tax book and its panels; a projection; a year's giving; a person's gifts; a person shared alone: their row (name, birthday) and relationships to those the viewer may see (`/persons/{id}/relations`); an account not shared with the same people appears as *an account not shared*.
- §4.4.2: the sender keeps a hash of each document last sent; only changes travel; a receiver whose `have` isn't the last `seq` gets everything.
- §4.4.3 (S11.4): past 4 MB a change travels in parts, oldest to newest: first part = items and removals, then records by date, long documents split into whole records up to a date; each part signed and numbered as its own change with `progress`; the receiver shows *Up to July 2022, 47 MB of 2 GB*; a missed or out-of-turn part → the next exchange asks for everything; parts still to send kept in the source's memory, lost on restart (D3-4).
- §4.4.4: the receiver checks the signature and that `seq` follows `have` (or `full`), else asks for everything next time; registry into the main DB, `sealed` into the copy's inbox as it came (S11.9.5), applied with signature and sequence checked again once unlocked; no access key → registry only, and making the key asks for everything.
- §4.5 (S13.3): a server with its own cert whose key changes calls `certificate` on each active or paused link as soon as it sees it, before its next exchange (own listener: from its file; behind a proxy: by connecting to its own link address); the peer accepts old or new until an exchange over the new succeeds; an unannounced change is refused, shown as *the peer's certificate changed*, until an admin there accepts the fingerprint.
- §5.1: protocol number `1` in `MK-Link-Protocol`; others refused `protocol-unsupported` (426) with `protocols` (list of numbers); a newer MoolaKata answers the older protocol for ≥ 1 release after adding one.
- §5.2: within a version, fields may be added; receivers ignore unknown fields; senders never rely on new ones.
- §5.3, §6: an item of an unknown kind is kept in the copy, not shown, with a note that the other side is newer (kind names never listed: D3-8).
- §5.4: Settings › Linked servers shows the peer's MoolaKata version from `MK-Link-Version`.
- §7: refusal = JSON `{code, message}`, HTTP 403 unless stated, signed unless marked unsigned; `message` only for the caller's log, never copied into an alert or email (S13.7.9).
- §7 codes: `unsigned` (headers missing or malformed); `clock-skew` (> 60 s); `bad-signature`; `replayed` (nonce from that key in last 2 min); `not-linked` (no link here; unsigned when the body is over 1 MB, refused on headers, S13.7.5.4); `link-<state>`; `limit` (429, unsigned, `Retry-After`, 60 calls a minute, S13.7.5.4; retry at next exchange); `locked` (503, unsigned, S13.6; retry at next exchange); `not-shared`; `protocol-unsupported` (426); `code-used` (used, expired or withdrawn); `already-linked`; `change-refused` (a delivered change fails its signature check).
- §7: a signed `link-ended` ends the link on the caller: its copy, shares to it and remote users go; `not-linked` only marks the link broken and alerts admins (S11.6); the caller acts on unsigned `limit`/`locked` only, any other unsigned answer refused as `answer-unsigned`.

### connector-protocol.md

- Header: follows the link protocol wherever the two do the same thing; code in `web/server/src/moolakata/connector/` and `connector/moolakata_connector/`.
- Terms (R2.26, S18): identity key Ed25519 signs calls, kept beside the vault; sealing key X25519, public half at MoolaKata, private in the vault; sealed box = a credential MoolaKata stores and can't open; vault open only while unlocked with its words; bound host = the one host a credential may be sent to, fixed when filed.
- §1.1 (S18.2.2): the connector only opens connections: HTTPS POSTs of JSON (multipart for a file) to `/connector/v1/` at the address in the pairing code; MoolaKata never calls the connector.
- §1.2: the connector verifies MoolaKata's TLS (public: roots; own: the code's `t`); while the cert is MoolaKata's own, every report answer carries its key's fingerprint as `certificate`, a new one accepted beside the pinned one until in use; follows no redirect; reads ≤ 25 MB of an answer (S18.2.2 adds: waits ≤ 60 s).
- §1.3: everything but `hello` signed; every answer to a signed call signed back by MoolaKata's link key.
- §1.4: JSON bodies UTF-8 ≤ 1 MB; a file post multipart, the file ≤ the upload size in Settings (S13.7.6).
- §1.5 (S16.14): only addresses in Settings › Network's connector ranges ("Allowed to connect": D3-15) reach `/connector`; others 404.
- §2.1 (S18.4.5): two keys made at pairing; identity key beside the vault so a locked connector reports; sealing key's private half in the vault; MoolaKata holds only the public halves.
- §2.2: MoolaKata signs answers with its link key; a server with no link makes it at the first pairing.
- §2.3–2.4: fingerprint = SHA-256 of raw 32-byte public key, hex; screens show first 16 digits in four groups; keys as raw 32 bytes unpadded base64url.
- §3.1: headers `MK-Conn-Key`, `MK-Conn-Time`, `MK-Conn-Nonce` (16 bytes base64url), `MK-Conn-Signature`, `MK-Conn-Protocol`, `MK-Conn-Version` (shown in Settings › Connector); signed text `MK-CONN-1`, method, path with query, SHA-256 of body (multipart: the raw body as sent), time, nonce, MoolaKata's link-key fingerprint.
- §3.2: refused: missing headers, time > 60 s off, bad signature, nonce seen from that key in last 2 min, a key not the paired connector's, a pairing that has ended.
- §3.3: answers signed over `MK-CONN-1-ANSWER`, status, SHA-256 of answer body, time, the call's nonce, the connector's fingerprint, SHA-256 of the call's body; the connector refuses answers not signed by the key the code named; refusals signed when the call carried a nonce.
- §3.4: 60 calls a minute (S13.7.5.4); a file post also counts against the owner's upload limit (S18.8; S13.7.5.3: 60 files an hour per user).
- §4 calls: `GET /connector/v1/hello` unsigned → `{protocol, version, fingerprint, key}`; `POST /pair` signed by the new identity key; `POST /report` every 5 min; `POST /connections/{id}/credential/taken`; `POST /connections/{id}/sign-in` `{address}`; `POST /accounts/{id}/files` multipart; `POST /unpaired` (the connector forgot this server; MoolaKata ends the pairing as Unpair would).
- §4.1.1 (S18.4.1, S13.7.2): **Pair** needs the admin's password again; code = `mkp1.` + unpadded base64url `{"a","f","c","t"}` as a link code; MoolaKata keeps SHA-256 of the secret and the expiry (24 h); one use.
- §4.1.2: `moolakata-connector pair <code>` needs the vault unlocked; verifies TLS, calls `hello`, refuses unless `key` hashes to `f`, keeps that key; makes new identity and sealing keys; calls `pair` with `{code, sealingKey, sealingSignature, version, protocol}` (glance says `sealingSig`: D3-10); `sealingSignature` = identity key's signature over the sealing key, which browsers check; the new pairing is written only once `pair` succeeds.
- §4.1.3 (S18.4.2–S18.4.4): MoolaKata records both public keys, ends any connector paired before (every Connection stopped, every account's sync off), answers `{fingerprint, serverName}`; each side derives the connector's fingerprint from the identity key itself; until an admin **Confirms**, reports are answered but `sealed` is withheld and file posts refused `not-confirmed`.
- §4.1.4: the connector keeps address, fingerprint, MoolaKata's key and its own keys; one connector ↔ one server; `unpair` or a signed `not-paired` deletes every credential for that server (S18.4.4 adds: and its sealing key) (D3-12).
- §4.2 (S18.5): reports every 5 min, at once after an unlock, a run or a change, and every 15 s for up to 10 min while a Connection awaits a sign-in.
- §4.2 report body: `{locked, unlockedAt, page, connections: [{id, state, message, lastRunAt, lastRunAdded, institutionAccounts: [{name, last4}], signInAddress}]}`.
- §4.2.1: `state` ∈ `new` (credentials not yet received), `ok`, `needs-sign-in`, `failing` (with `message`, never a credential, amount, or account number beyond its last four, S18.5); a Connection the connector doesn't know is absent and MoolaKata keeps it `new`.
- §4.2.2 answer: `{connections: [{id, ownerName, driver, label, settings, accounts: [{id, syncAccount, formats}], sealed: {ciphertext, sealedAt}}], removed: [ids], confirmed: bool}`; `sealed` only while a credential waits, the report said `locked: false`, and the pairing is confirmed; `removed` = Connections whose owners removed them (S18.6.4): the connector deletes their credentials; `confirmed` shown on the connector's page (S18.11.3).
- §4.2.3: MoolaKata records each report's time; silent 15 minutes → alert (S18.5.2); shows `locked` (S18.5.1); records the source address: the first is the connector's, another still answered but alerts admins until one accepts it or unpairs (S18.5.4); keeps `page` if it is `https` host:port only, cleared by a report without one; Settings › Connector links to it.
- §4.3.1 (S18.7.1): the browser fetches the sealing key with its identity-key signature from `GET /ui/api/connector`, checks it, seals `{credentials, host, sealedAt}` as an X25519 sealed box: ephemeral X25519, HKDF-SHA256 over the exchange, label `moolakata connector credential`, salt = the Connection's id, AES-256-GCM with a random 96-bit nonce; box = ephemeral public key ‖ nonce ‖ ciphertext, base64url; `PUT /ui/api/connections/{id}/credential`; MoolaKata stores it as is until the next report's answer.
- §4.3.2: the connector opens it with the vault's sealing key, refuses a host other than the Connection's settings name or a box older than the credential it holds, files it bound to the sealed host, calls `credential/taken` `{sealedAt}`; MoolaKata deletes that box only; a box it can't open → `failing` *the credentials were sealed for another connector*.
- §4.3.3 (S18.7.3): before each run, bound host vs the settings' host now; on a difference it sends nothing, deletes the credential, reports `needs-sign-in` *the server address changed from A to B*.
- §4.3.4: OAuth sign-in: the driver posts `sign-in` `{address}` with a random `state`; MoolaKata takes it only on the driver's own sign-in host (else `address-invalid`) and shows it with that host under Profile › Connections; the owner pastes the landing address into the credential dialog, sealed as 4.3.1; the driver checks `state` and completes at its next report.
- §4.3.5 (S18.7.2): `moolakata-connector connect <connection id>` on the connector's host shows the host, asks the admin to confirm it, takes the credentials there, files them bound to that host; the connector must have heard of the Connection (reports first).
- §4.4: file post: multipart `file` + `meta` `{connectionId, format, fetchedAt, fileName, sha256}`; the account's sync must name this Connection and the Connection belong to the account's owner, else `account-not-synced`; unconfirmed → `not-confirmed`, kept for a later run.
- §4.4.2 (S1.3, S18.8): the same import as the owner's upload: type from content, idempotent, a PDF kept unread or waiting in the account's inbox, CSV needs the saved mapping (`mapping-missing`); Activity: *by MoolaKata Connector, Alice's Schwab login* under the owner.
- §4.4.3: answer `{imported: {added, matched, changed}, kept: bool}`; 429 + `Retry-After` = the owner's upload limit; the file is kept and posted later.
- §5: protocol `1` in the path and `MK-Conn-Protocol`; `protocol-unsupported` naming those spoken; a newer MoolaKata answers the older for ≥ 1 release; fields may be added; Settings › Connector shows `MK-Conn-Version`.
- §6 (S18.9): `ofx-direct` posts the OFX server's statement as is; settings `url`, `org`, `fid`, `accountType` (`CHECKING`, `SAVINGS`, `CREDITCARD`, `INVESTMENT`), `accountId`, `bankId` for a bank (no `days`: D3-13); credentials `{username, password}` bound to `url`'s host; 91 lines.
- §6: `schwab` posts positions, transactions, balances from the Trader API as one OFX investment statement per account; settings `appKey`; credentials `{appSecret, landed}`; refresh token kept in the vault, new sign-in when it runs out after seven days; bound to no host (fixed `api.schwabapi.com`); 230 lines.
- §6 (S18.1.2.1): driver size colour: green < 1,000 lines, yellow 1,000–1,999, red ≥ 2,000; `connector/tests/test_core.py` fails when the table's size is stale or a driver is missing.
- §6: egress allowlist per driver run: the driver's host only; loopback, link-local and cloud metadata refused; a changed `url` asks for the credentials again; an institution with nothing to fetch has no driver.
- §7: refusal JSON `{code, message}`, 403; 426 protocol, 429 limit, 404 not found, 413 too large, 503 locked (unsigned); signed when the call carried a nonce.
- §7 codes: `unsigned`, `clock-skew` (> 60 s), `bad-signature`, `replayed` (2 min), `not-paired` (key not the paired connector's, or pairing ended), `not-confirmed` (S18.4.2), `code-used`, `protocol-unsupported`, `account-not-synced`, `mapping-missing`, `file-refused` (content not an imported type), `limit` (upload limit or 60/min), `not-found` (404), `address-invalid`, `too-large` (413: JSON > 1 MB or file > upload size), `locked` (503 unsigned, S13.6).
- §7: connector-side refusals, sending nothing further: `not-moolakata` (no MoolaKata `hello`), `fingerprint-mismatch` (not the code's or pairing's), `answer-unsigned`, `code-invalid`.

### api.md

- Table: `/ui/api` called by the browser app, signed in with the session cookie (S13.7.1); `/mcp` by an AI assistant, read only (S10.9), with an access token made in Profile; `/link` and `/connector/v1` are signed and take neither session nor token.
- §1 (S13.8.9): `/ui/api` carries no version of its own; its contract is `web/ui/api/openapi.json` (generated from routes) with JSDoc types in `web/ui/api/types.js`; `web/check` fails when either differs; the server doesn't serve the document.
- §1 (S13.8.2): money, quantities, prices, ratios are JSON numbers with their own digits and always a decimal point (`1234.50`, `10.0`, `0.0345`); counts, years, versions are integers; read with `parse_float=Decimal` or the app's `parseJson` (`web/ui/app/dec.js`) giving `Dec`; requests send exact numbers, or a decimal string.
- §1 (S13.8.5): lists take `?offset=` and `?limit=` (500 default, max 1000), answer `{items, total, offset, limit}`.
- §1 (S13.8.6): every `PATCH`, `PUT`, `DELETE` of a versioned record carries `If-Match: "<version>"`; missing → 428; stale → 412 with the record as it is and its `version`; a creating `PUT` sends `"0"`.
- §1 (S13.8.1): a `DELETE` answers `{deleted, parent}`.
- §1: errors `application/problem+json`, status codes, jobs, `Idempotency-Key`, visibility: as S13.8.
- §2: `/mcp` = MCP over HTTP: JSON-RPC 2.0, one `POST /mcp` per call, `Authorization: Bearer <token>`; tokens made in **Profile › Access tokens**, read only; a token for **chosen items** reads only the accounts and portfolios it names and is refused the *household* tools; 60 calls a minute per token; each call in Activity under the token's name; exact numbers.
- §2 tools (args snake_case: D3-23): `list_accounts` (type, balance, 30-day change); `get_account_holdings` (`account_id`; quantity, value, cost, gain); `list_transactions` (`account_id`, `from`, `to`, `payee`, `limit`; newest first, ≤ 500); `list_positions` (`kind`: `all`, `stocks`, `options`, `crypto`); `list_portfolios`; `get_portfolio` (`portfolio_id`); household: `list_budgets`, `get_budget_month` (`budget_id`, `month` `YYYY-MM`), `list_upcoming_gifts`, `get_giving` (`year`), `list_tax_books`, `get_tax_panels` (`book_id`).
- §2: `tools/list` gives each tool's argument schema; a test fails when a tool is missing from the table.

### operations.md

- §1 (S17.8): one container from `moolakata:<version>`, uid 10001, port 37373; mounts `data/` → `/var/lib/moolakata` (DB, keyring, receipts, linked copies, pre-upgrade copies), `backups/` → `/var/backups/moolakata`, `moolakata.toml` → `/etc/moolakata.toml` read only, never a secret.
- §1 (S15.4): the master key is the recovery phrase, never stored; locked after every start until entered on the locked screen or `keys unlock`; nothing on the host holds a key.
- §1: `install/compose.yaml` runs `proxy` mode behind the household's proxy; `install/proxy/` has Caddy, nginx, haproxy examples; `install/compose.tls.yaml` = own HTTPS, self-signed, "for trying it on a local network"; each release attaches these files.
- §1.1 (S11.2): no separate link port; a proxy may pass only `/link/*`; `/ui` stays on the household's network or overlay.
- §2.1 (S17.8.2): images `ghcr.io/mojokata/moolakata:<version>` and `…/moolakata-connector`, one tag for amd64 and arm64; same digests on Docker Hub `mojokata/…`; `gh attestation verify` (DEPLOY §2).
- §2.1 (S17.8.1): `web/install/smoke.sh [linux/arm64]` builds and runs both images: refused start, welcome's key and first admin, locked restart and unlock, health, sign-in, receipt read, connector vault and unlock, clean stops.
- §2.3 (S13.3): `trusted_proxies` = the proxy's own address, never a range; `proxy` mode publishes plain HTTP on the host's loopback only; compose project range `172.30.37.0/24`, commented proxy `172.30.37.10`; host proxy reaches from gateway `172.30.37.1`; container gets the host's time zone (`/etc/localtime`, `TZ`), which backups and daily emails follow.
- §2.4 (S15.4.4, S10.1.2): with no keyring the server is uninitialised; **Show my recovery phrase** shows 12 words once, three typed back make the key; **Set up the admin account** makes `admin`, signed in at once; store the phrase per S15.6 (two copies, two places, one offline, never with backups); a stolen welcome → stop, empty `data/`, start again; or `keys init` on a terminal before first start.
- §2.1 (Proxmox): VM with 2 GB, or 1 GB with reading off (DEPLOY says 4 GB: D3-16); LXC with nesting "not yet tried on a real host".
- §2.2 (TrueNAS): custom app from `install/compose.truenas.yaml`, datasets as host paths, one-time `permissions` step to uid 10001, config in `MOOLAKATA_CONFIG` (read when `--config` names no file).
- §2.3 (S15.8): every snapshot and replica is a copy that opens with the phrase of its day; MoolaKata can't see or prune it; restore from the verified copy in `backups/`, not the live DB in a snapshot.
- §3: change tags on `moolakata` and `connector` services; at the unlock the server copies the DB into `data/pre-upgrade/` and checks it, migrates one revision at a time, keeps the three newest copies; `/healthz` answers `ok` once it serves; an older release refuses a migrated DB (`refusing to start:`).
- §4 (S14.6): MoolaKata's backup never copies receipts or linked copies; daily at the time in Settings › Backups, a verified copy of the DB with its keyring into `backups/moolakata-<date>-<time>/` with `manifest.json` (size and hash per file); keeps 14 by default; no backup during a re-encryption; **Back up now** or `db backup` (running: asks the server; stopped: with the phrase); a backup opens with its day's phrase, carries its keyring; a rotation re-encrypts them; a failed backup alerts admins (and email by choice).
- §5: signed calls between servers and from the connector refused past a minute's clock difference; image health check every 30 s (`moolakata health` → `/healthz`), healthy whenever the server answers (S13.6); `/healthz` `{"status": "ok", "version": …}` when ready, 503 `re-encrypting`, `locked`, `uninitialised` (`starting` not listed: D3-16).
- §5: alerts: failed backup; a price source, email, bitcoin node or linked server failing longer than Settings › Alerts allows; a recovery phrase not confirmed.
- §5: logs one line per event on stdout, never amounts, account or payee names, secrets or passwords; five files of 10 MB; Settings › Storage shows DB and receipts size and what file pruning could remove (S14.10).
- §5.1: a refused start = one `refusing to start:` line and exit code 78; Docker's back-off reaches once a minute; causes: keyring unreadable, DB without keyring, config problem or unknown key, data directory in use; `refusing to unlock:` for a newer DB or a keyring the phrase doesn't open (names its fingerprint).
- §6.1: `db verify-backup` asks for the phrase, reports the manifest's time, refuses a backup whose name says another time; `db restore` (stopped) checks again, refuses a newer release's backup, moves the DB, keyring and linked copies into `data/before-restore-<time>/`; receipt files stay, re-wrapped to the backup's key when a re-encryption came after it; a backup from an earlier phrase restores under that phrase; Settings › Storage counts files the restored DB no longer names, with Remove; linked households pull again in full.
- §6.2: onto a new host, don't start first; put `data/receipts/` back from the host's backup; then restore.
- §6.3: monthly `db verify-backup`; yearly rehearsal of §6.2 and **Verify key** (S15.6.5).
- §7 (S15.7.1): `keys rotate` while running needs no old phrase, shows the new one, asks three words back, re-encrypts at the next unlock; stopped, asks for the current phrase and re-encrypts at once; lists every copy on the host (backups, pre-upgrade, before-restore) with re-encrypt (Enter), delete, leave, `--reencrypt-all`; Settings › Key storage shows which copies still need the previous phrase; **Forget** it.
- §7 (S15.7.2): **Re-encrypt at the next restart** (phrase unchanged) runs before the server serves, with progress on the locked screen; or `keys reencrypt` stopped.
- §7.1 (S15.8): a leaked phrase: revoke source secrets, unpair and re-pair the connector, rotate and restart, delete every earlier backup and copy, destroy the old phrase's copies.
- §8 (S18): connector = `connector` service, `moolakata-connector` image of the same version, volume `connector-data` MoolaKata never mounts; publishes port 37374 (its page, S18.11); TrueNAS: an app of its own.
- §8.2: `MOOLAKATA_CONNECTOR_NAMES` = the addresses browsers use for its page (its cert names them; MoolaKata links to the first); welcome shows 12 words, three typed back make the vault; or `connector init`.
- §8.3: the page shows to anyone on the network: locked or not, what it is paired with, last report, how many Connections work; every action asks for the words; wrong words logged with their address; own cert via `MOOLAKATA_CONNECTOR_TLS_CERT`/`_KEY` read only.
- §8.4–8.5: unlock after every start (page or `connector unlock`); MoolaKata alerts admins while locked; pairing per §4.1; **Confirm** in Settings › Connector before any sign-in or file; the code's address must resolve inside the container ("the public URL, or the link address": D3-14).
- §8.7–8.13: `connect` on the host, fields typed without echo; `status`; alerts when locked or silent 15 min; another machine needs its address in Settings › Network; Unpair from either side deletes the credentials (from MoolaKata's side at the connector's next report); `reset` makes a new vault and words and unpairs; logs never a credential, amount or account number beyond the last four; a lost host: unpair at once (the copy holds the identity key: can report and post files until then).

### DEPLOY.md

- Intro (S13.3): both documented test installs serve HTTPS themselves on 37373 in `tls` mode with a self-signed cert, "what a test on a local network needs"; a relied-on server goes behind a proxy (operations §2).
- §1 (S17.8.1): amd64 or arm64, 2 GB memory (1 GB with reading off), ~3 GB disk; internet to `ghcr.io`, `github.com`, `release-assets.githubusercontent.com`; the 12-word phrase asked after every start.
- §2: image under 1 GB; installs 0.1.0; attestation command with `--signer-workflow …/release.yml --source-ref refs/tags/v0.1.0 --deny-self-hosted-runners`; Docker Hub rate-limits anonymous pulls, ghcr.io doesn't.
- §3.1: Proxmox VM: Debian 13 genericcloud, 2 cores, 4 GB, 32 GB disk, cloud-init, `--onboot 1`.
- §3.3: `compose.tls.yaml` as `compose.yaml`; `moolakata-tls.toml` with `[server] name, mode = "tls", port = 37373`, `[paths] data, backups`, `[tls] names = [address]`; `docker compose up -d moolakata` (the connector needs its own setup).
- §3.4 (S13.6): `restart: unless-stopped`; starts locked; `docker compose ps` healthy whenever it answers; `/healthz` `locked` or `ok`.
- §4.2: TrueNAS YAML: `permissions` service (moolakata image, root, `cap_add: [CHOWN]`, no network, read-only) chowns both datasets to 10001; server: `restart: unless-stopped`, port 37373, `MOOLAKATA_CONFIG`, `read_only`, tmpfs `/tmp` and `/run/moolakata` (0700, uid 10001), `cap_drop: [ALL]`, `no-new-privileges`, `stop_grace_period: 10s`, logs 5 × 10 MB; NAS time zone is the server's.
- §4.3: TrueNAS shows **Running** whenever it answers (new, locked, open); any restart or YAML edit locks it; `/healthz` says `uninitialised`, `locked` or `ok`.
- §5 (S15.6, S10.1.2): the welcome: write the 12 words with the fingerprint; each visit or browser shows other words, only the confirmed ones become the key; three typed back; admin account = name, sex, email, password ≥ 12 chars; sign in as `admin`; invitations go to the mail folder until SMTP is set, listed in Settings › Email with **Open**; F1 help; `/demo` is the clickable mockup.
- §5: unlock on the host with `docker compose exec moolakata moolakata keys unlock`; TrueNAS: `sudo docker exec -it ix-moolakata-moolakata-1 moolakata keys unlock`; **Verify key** yearly; the yearly alert opens it.
- §6: upgrade = change the tag (TrueNAS: both `image:` lines in **Edit App YAML**), unlock; the connector takes the same version and comes back locked.
- §7: a stolen welcome → empty `data` and `backups` (D3-16); a lost phrase: `keys rotate` while running and unlocked.
- §8 (S18): connector page on 37374; vault words separate from the recovery phrase, kept in the household's password manager; TrueNAS connector app: dataset `connector`, `permissions` chown to uid 10002, `MOOLAKATA_CONNECTOR_NAMES`, tmpfs `/run/moolakata-connector` (uid 10002), same hardening.
- §8.3: Settings › General › Public URL must be the address the connector reaches (the code carries it); **Pair** and **Confirm** each need the password again; code good for 24 hours; Settings › Connector links to the connector's page from its first report; the page shows the pairing confirmed within 5 minutes; owners add sign-ins under Profile › Connections, sealed in their browser.

### RELEASE.md and GENESIS.md

- RELEASE intro (S17.10.2, S17.8.1, S17.8.2): a release = a `v<version>` tag on `main` + a GitHub release; `release.yml` builds both images on an amd64 and an arm64 runner, runs `smoke.sh` on each (the gate), pushes to `ghcr.io/mojokata`, joins each image's two architectures under the version's tag, attests both.
- RELEASE §2: semver; `release.yml` refuses a tag that isn't `v` + `web/VERSION`; MAJOR = the upgrade needs something from people (a hand migration step, config key, mount, re-pairing, linked servers upgrading together); any release may carry an automatic migration; no exception for 0.x.
- RELEASE §2 (S15.4): exactly the version's tag on both registries plus per-architecture tags on ghcr.io (D3-17); no `latest`, no moving tag; a version is never reused; browsers cache `/ui/v/<version>/` for a year (S17.3.5); `main` moves to the next minor `-dev` once a release is published; a `-dev` build's files are served without the year's cache.
- RELEASE §3: the version is hand-written in `web/VERSION`, `connector/pyproject.toml`, `connector/moolakata_connector/__init__.py`, four `web/install/compose*.yaml`, two TrueNAS apps' `ix_values.yaml` and `app_version`, `docs/DEPLOY.md`, `docs/operations.md`, README's **Release** line (14 files); base image `python:3.14-slim-bookworm` pinned by digest in both Dockerfiles, moved each release by `web/dev.sh base-update` (S17.8.5), recorded in `web/audit.json`.
- RELEASE §3.5: every release updates README, DEPLOY, operations, test-plan, guides, `api.md`, `connector-protocol.md`, `link-protocol.md` (and the notes say what each protocol change means across releases), `dependencies.md`; requirements carry no versions.
- RELEASE §3.6–3.8: `web/check` (~20 min locally, ~30 min in CI) must end `all checks passed`; a PR touching `web/install/` runs `check` and `release` (build and smoke both architectures, no push); squash-merge.
- RELEASE §4 (S17.9.7.8): notes sections: Before you upgrade (major only), What's new, Upgrading, Compatibility, Tried by hand (which of T1–T13, by whom, on what; T7 arm64 on household hardware), Images (with the attestation command).
- RELEASE §5: the tag is signed by the maintainer's own GPG key and pushed by hand; `release.yml` then builds, smoke-runs, publishes to ghcr.io, joins and attests, copies to Docker Hub with the same digests, and drafts the release with install files; the maintainer checks, then publishes the draft; GitHub's **Draft a new release** form is never used (its tag carries no signature).
- RELEASE §6: five jobs: build and smoke (amd64), build and smoke (arm64) push `<v>-amd64`/`<v>-arm64`; one tag per image, attested; Docker Hub copy (in the `docker-hub` environment, skipped with a warning if unset); the draft with four `compose*.yaml`, the example `moolakata.toml`, `Caddyfile`, `nginx.conf`, `haproxy.cfg` (eight files); only the draft job's token can write to the repository.
- RELEASE §7: attestations kept in GitHub's store, not as `sha256-<digest>` tags; Docker Content Trust not used; anonymous pulls must work on both registries.
- RELEASE §8: published with `--prerelease` while for testers; `gh release verify` and `verify-asset`; publishing makes the release immutable (tag, files); Docker Hub overviews' pull command moved by hand.
- RELEASE §9–§11: `web/release.sh next` writes `<next>-dev` and regenerates `openapi.json`; DEPLOY's second paragraph names the release it was run with (T10, T11); before publishing a version may be re-tagged; after, fix forward with a new patch.
- RELEASE §12: Docker Hub token (Repo Read & Write, ≤ 1 year) stored as `DOCKERHUB_TOKEN` in the `docker-hub` environment; `setup` warns past 11 months; immutable releases and the tag ruleset stay on; TrueNAS catalog via `publish/truenas/create-pr.sh` (images pinned by digest; `--open` opens a draft PR) (S17.8.3.1).
- GENESIS §1 (S17.10.3): the maintainer is an owner of the MojoKata org, signs and pushes tags, is in the tag ruleset's bypass list, holds Docker Hub's sign-in; the build's fork has read access only; each `release.yml` job's token has only what it needs.
- GENESIS §3.1: org Actions policy allows MojoKata and selected actions plus GitHub's own; workflow default permissions read; each workflow declares `contents: read` (checked by `test_install.py`); fork PRs need approval for first-time contributors (GitHub's default).
- GENESIS §3.2: tag ruleset *Release rules*, Active, `refs/tags/v*`, restricts creation, update, deletion, blocks force pushes; bypass: Organization admin role and the maintainer, Always.
- GENESIS §3.3: immutable releases on (repository setting); 0.1.0 published before it, stays editable.
- GENESIS §3.5: `main` ruleset *Main rules*, Active: PR required (0 approvals), squash only, required check `check`, no up-to-date requirement, deletions and force pushes blocked; bypass Organization admin and the maintainer, for pull requests only.
- GENESIS §4: packages public on ghcr.io; `push-to-registry: false` for attestations; each package keeps `0.1.0`, `0.1.0-amd64`, `0.1.0-arm64`.
- GENESIS §5: Docker Hub personal account `mojokata` (2FA on); public repos `mojokata/moolakata` and `mojokata/moolakata-connector`; token *MoolaKata releases* expires October 20, 2027; environment `docker-hub` admits only `v*` tags, holds `DOCKERHUB_TOKEN` and `DOCKERHUB_USERNAME`; not in the Docker-Sponsored OSS program (anonymous pull limit 100 per 6 h per address); the connector's overview text depends on Q30.
- GENESIS §6: 0.1.0 was a lightweight unsigned tag made by the web form, three jobs, files attached later, copied to Docker Hub by hand.
- GENESIS §7: `release.sh setup` checks immutable releases, the tag ruleset, the `main` ruleset, the `docker-hub` environment (secret age), both images public on both registries; by hand: package creation, Actions settings, Docker Hub 2FA, overviews, token expiry, OSS membership.

### test-plan.md

- Intro (S17.9.7.8): T1–T13 are what the build can't try; a release says which were run, by whom, on what; tests start from a server installed per operations.md with the dev seed's figures.
- T1–T4: Fulcrum, electrs, Bitcoin Core ≥ 27 with RPC, a self-hosted mempool/Esplora; mainnet; Test shows *answered: block N*; an Electrum server with TLS shows its cert's SHA-256 to confirm; a `crypto-wallet` account derives both chains 20 past the last used; a send's network fee is a sale of that many sats beside a fee (S8.19); nothing under 6 confirmations recorded; a new receive within an hour (or at once with Check now); Core: wallet `moolakata-<account id>` with descriptors imported, watch-only, rescanned from the start; a node down longer than Settings › Alerts → one alert for admins and one for the owner, no address or amount; a replaced Electrum cert stops reads and alerts *the node's certificate changed*.
- T5–T6: the public URL as the peer reaches it; Invite, Enter a link code, compare fingerprints by phone, Approve → both *active* within a minute with household name, users, version (D3-7); share an account, budget, tax book with **Include receipts**; on B **Create the access key**, open the linked window with the words; nothing shared appears in B's own lists or totals; one-way reachability keeps syncing; Pause `1h` and **Resume now**; End on A → B learns at its next call and deletes its copy; behind the proxy `/ui` 404 and `/link/v1/hello` answers.
- T7: a Raspberry Pi 4 (4 GB) or 5 or arm64 NAS; `/healthz` `locked` first; healthy within two minutes of the unlock; receipt read 3–10 s on a Pi 5 (S9.8.4.5); memory under 2 GB with reading on (1 GB off); the connector reports and Settings › Connector links to its page.
- T8: Schwab app approved for the Trader API with `https://127.0.0.1` as callback; within five minutes the connection says *needs a sign-in*; the sign-in address's host is `api.schwabapi.com`; *ok* within a minute; within a day positions, the last 45 days of trades and dividends, the cash balance; Activity shows posts as by the connector; after eight days a new sign-in is asked and the owner alerted.
- T9: OFX Direct Connect with URL, ORG, FID, routing and account number; *ok* within a day; a second run adds nothing; a changed password → *needs a sign-in* and the owner alerted.
- T10–T11: DEPLOY §3/§4 on real hosts; a snapshot holds neither the keyring's fingerprint nor the phrase's words; the daily backup lands.
- T12: restore refuses a changed backup and a wrong phrase; every receipt opens; Storage counts no unnamed file; linked copies pull again.
- T13: before **Confirm**, no sign-in can be sealed and the connector's page says *not confirmed yet*; wrong words refused and logged with the address; a relay with another cert → the connector sends nothing and says why; an address outside the allowed ranges → 404; closed twenty minutes → *not heard from* alert; a changed OFX server address → *needs a sign-in: the server address changed*.

### dependencies.md

- Audit (S17.2.1, S13.5): hashes of `web/server/uv.lock` and `web/ui/vendor/manifest.json` in `web/audit.json` (`web/dev.sh audit --accept`); `web/check` fails when they don't match; every lock change is followed by `web/dev.sh audit` (URL and telemetry word scan, a run with no network interfaces failing on any non-loopback socket); findings marked **egress** / **telemetry** with their switch.
- Server: Python 3.14; wheels for amd64 and arm64 (S17.8.1): fastapi 0.143.0, pydantic 2.14.1, hypercorn 0.18.0 (HTTP/1.1, HTTP/2, TLS in `tls` mode), sqlalchemy 2.1.4 (Core only; SQLModel rejected, rejected idea 8), alembic 1.20.0, argon2-cffi 25.1.0 (argon2id, S13.7.3), cryptography 50.0.2 (AES-GCM, HKDF, Ed25519 for links, X25519 for receipts and copies), httpx 0.28.1 (the one outbound client, behind the egress guard), sqlcipher3 0.6.3 (main DB and linked copies, S11.9.11), ofxtools 1.1.1 (GPL-3.0-only), pillow 12.3.0, numpy 2.5.4, python-multipart 0.0.32, segno 1.6.6 (two-step QR, S10.1.6), pypdfium2 5.14.0 (worker only), pi-heif 1.4.0, rapidocr 3.10.0 (egress: model download never happens; every model path named and hash-checked, S9.8.3), onnxruntime 1.31.0 (telemetry: `disable_telemetry_events()` before the first session, in `receipts/ocr.py`).
- Transitive: opencv-python-headless 5.0.0.93, requests 2.34.2 / urllib3 2.8.0 (egress, uncalled), tqdm 4.70.1, opentelemetry-api (no SDK, no exporter), email-validator/dnspython (deliverability never asked), certifi 2026.7.22.
- Dev only: pytest, ruff, playwright (egress at setup), sigstore (egress at `vendor add`), uv 0.12.5, Deno 2.9.7; base image `python:3.14-slim-bookworm` by digest, moved each release (S17.8.5), last moved 2026-10-15 from 3.12.
- Connector (S18.1.2): standard library + `cryptography` 50.0.2 (+ cffi 2.1.1, pycparser 3.11), pinned with hashes for CPython 3.14 amd64/arm64; same base digest as the server.
- TrueNAS catalog (S17.8.3.1): `lib_version` 2.3.17; `container-utils` 1.1.1 by digest (root with CHOWN, FOWNER, DAC_OVERRIDE, no network); `apps_validation:slim` unpinned, uses the Docker socket: development machines only.
- GitHub Actions (S17.10): only GitHub's own, pinned by commit, adopted after 14 days (as S17.3.1): `actions/checkout` 7.0.1 (`persist-credentials: false`), `actions/attest-build-provenance` 4.2.2 (id-token write "in the release's last job only": D3-18); runners `ubuntu-24.04`, `ubuntu-24.04-arm`.
- Browser (S17.3.1, S17.3.3): vendored npm tarballs via `web/dev.sh vendor add` (14-day cooldown, registry integrity hash, Sigstore provenance where published, reviewed diff), CSP with no third-party origin: preact 10.29.8, htm 3.1.1 (no provenance), @preact/signals-core 1.14.4, @preact/signals 2.11.3, preact-iso 2.12.2, echarts 6.1.0 (no provenance; ~330 KB gzip, chart screens only; S17.4).

### external/README.md

- Copies kept of outside documents the requirements rest on: `schwab-py-auth.rst` (commit `43c4614`, MIT; S18.9.2: access token ~30 min, refresh token ~7 days, code lifetime unpublished), `irs-f8949-2025.pdf` (S8.1: boxes A to L), `irs-i8949-2025.pdf` (S8.1: G to L for digital assets; C and F not for them); each with its SHA-256; a new tax year's copy is added beside, not over; commercial pages cited by link only.

## Found while checking

Unverified, in the claim format (docs/REVIEW.md §7); the sweep checks them.

### D3-F1: A locked copy's inbox is capped at 500 MB, and the protocol's own example of a large first change is 2 GB

- **Kind:** bug candidate (behaviour specified in a way that can't hold). **Severity:** Low.
  **Req:** S11.4, S11.9.5.4, S11.7.1.
- **Where:** `S11-linked-servers.md:202–203`:

  ```text
  4. If the inbox grows past 1,000 changes or 500 MB, the server discards it and asks the
     source for a **full snapshot**, sealed the same way.
  ```

  and `link-protocol.md:199`: "(*Up to July 2022, 47 MB of 2 GB*)", the parts of a large first
  change each "a change of its own" (§4.4.3).
- **What goes wrong:** while a copy is locked, each part of a large first snapshot is written
  to `inbox/` and applied only at the unlock. A source whose snapshot is over 500 MB (the
  protocol's example is 2 GB) overflows the inbox part-way, the server discards it, and asks
  for a full snapshot again, so a copy that stays locked through the transfer never fills.
  Nothing says whether parts count against the cap, or whether a first snapshot is exempt.
- **Remedy:** S11.9.5.4 says what counts toward the cap and either exempts a snapshot in
  progress (its parts are kept until the cap's own larger limit) or states that a copy locked
  during a large first snapshot restarts it.

- **Check:** confirmed. **Severity now:** Low. Read S11.9.5.4 (`S11-linked-servers.md:202-203`), `link-protocol.md:190-199` (parts of a large first change, "47 MB of 2 GB") and the code: `links/changes.py:31-32` sets `MAX_CHANGES = 1000` and `MAX_BYTES = 500 MB`, and `enqueue` (`:126-133`) sums every waiting part's file, discards the inbox and sets `needsFull` past either. So each part of a snapshot counts, a locked copy cannot take one over 500 MB, and the next pull asks for everything again. Receipts go to `receipts/`, not the inbox (S11.9.5.2), so the 2 GB example is mostly files; a household's records alone rarely reach 500 MB. That makes it Low: the spec's cap and its example disagree, and nothing says parts count.
