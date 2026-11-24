# The link protocol

How two MoolaKata servers talk once their admins have linked them (requirements S11). This
document is the protocol's statement; the code that speaks it is `web/server/src/moolakata/links/`.

## 1. Transport

1. Links are HTTPS POSTs of JSON to the peer's **link address**, the base URL under which
   its `/link/v1/` paths are reached: the public URL by default, or the address set in
   Settings › Linked servers when `/link` is exposed apart from `/ui` (a forwarded port, a
   reverse proxy rule, or an overlay network such as Tailscale).
2. A link address is `https`, with no query or fragment, and never resolves to a loopback,
   link-local or cloud metadata address, whoever names it (S13.5); it may be on the LAN or an
   overlay. **The caller verifies the peer's TLS certificate**: a public one against the
   system's roots, and one that is the peer's own (S13.3) against the fingerprint of its key
   that the link code carried (`t`, section 4.1) or that the peer has announced since (section
   4.5). TLS keeps each message private on the way; the signatures (section 3) prove who wrote
   it; and the shared data itself is sealed to the receiving copy's key (section 4.4), so not
   even a proxy in front of the peer reads it.
3. Everything but `hello` is signed, and every answer to a signed call is signed back, but for
   the refusals §7 marks unsigned, which come before the answering server can sign to the call.
4. Bodies are JSON, UTF-8, at most 20 MB. A caller waits 10 seconds to connect and 20 seconds
   for each read, and cuts off an answer past 20 MB as it decodes (a caller asks for gzip or
   deflate at most, and refuses any other content coding). A receipt's sealed bytes (a `deliver`
   body with `MK-Link-File`, a `file` answer) are read as they arrive, never whole in memory,
   and are bounded instead by the largest receipt Settings allows (S16.10, 100 MB) sealed: its
   header and a 16-byte tag for each 64 KiB chunk (section 4.4). Each side bounds them so,
   whatever its own receipt setting, so a receipt either side may keep can cross.

## 2. Keys and fingerprints

1. Each server has one **link key**, an Ed25519 key pair made the first time it is needed.
   The private half is a sealed secret (S14.4) and never leaves the server.
2. A key's **fingerprint** is the SHA-256 of its raw 32-byte public key, in hex. Link codes
   carry it whole; screens show its first 16 digits in four groups (`3f9a 21c0 9b7e d4e5`)
   for admins to compare.
3. Keys travel as their raw 32 bytes in unpadded base64url.

## 3. Signed calls

1. A call carries these headers:

   | Header | Value |
   |---|---|
   | `MK-Link-Key` | the caller's public key |
   | `MK-Link-Time` | Unix seconds |
   | `MK-Link-Nonce` | 16 random bytes, base64url |
   | `MK-Link-Signature` | Ed25519 over the lines below, base64url |
   | `MK-Link-Body-SHA256` | the SHA-256 of the body, hex: the hash the signature covers, named so the receiver checks the signature before it reads the body |
   | `MK-Link-Protocol` | the protocol version the call speaks (section 5) |
   | `MK-Link-Version` | the caller's MoolaKata version, for Settings to show |

   The signed text is these lines, joined by `\n`:

   ```
   MK-LINK-1
   <method, upper case>
   <path with its query>
   <SHA-256 of the body, hex>
   <time>
   <nonce>
   <the receiver's fingerprint>
   ```

   Naming the receiver's fingerprint means a call can't be replayed against another server.
2. The receiver refuses, with the codes in section 7: a call without these headers, a time
   more than **60 seconds** from its own clock, a signature that doesn't verify, a nonce it
   has seen from that key in the last two minutes, and a key it has no link with or whose
   link is not in a state that allows the call. **All of this is checked before a byte of the
   body is read**, against the hash `MK-Link-Body-SHA256` names; the body is then read and
   must hash to it. So only a call a linked server signed has its body read, and only such a
   call counts against its link's limit (S13.7.5.4), whatever key header a caller sends; one
   that fails counts against its address. The time is the call's when it arrives: a body that
   takes long to come is no clock problem. Both hosts therefore keep their clocks with NTP; a
   `clock-skew` refusal is named as such on the link's state (S12.11.1.1).
3. **Answers** are signed the same way: `MK-Link-Time` and `MK-Link-Signature` over

   ```
   MK-LINK-1-ANSWER
   <HTTP status>
   <SHA-256 of the body, hex>
   <time>
   <the call's nonce>
   <the caller's fingerprint>
   <SHA-256 of the call's body, hex>
   ```

   The caller refuses an answer that isn't signed by the key it expects, or names another
   caller or another request, so an answer can't be handed on to anyone else, and holds its
   time to when the answer's headers arrived, not to when its body was read. Refusals are
   signed too when the call carried a nonce, a fault in a route included (`server-error`), so
   a refusal can be told from a forgery.

## 4. Calls

| Path | Signed | Link states | What it does |
|---|---|---|---|
| `GET /link/v1/hello` | no | any | `{protocol, fingerprint, key}`, `key` being the link key's public half, whose SHA-256 is the fingerprint: lets a joining server check the fingerprint in a link code before it sends anything; unsigned, it names no MoolaKata release |
| `POST /link/v1/ping` | yes | pending, requested, active, paused | `{protocol, version, state}`: the link's state on the answering side |
| `POST /link/v1/join` | yes, by the caller's own key | an invitation | answers a link code (section 4.1); no directory crosses |
| `POST /link/v1/exchange` | yes | active; pending on the joining side | the directories both ways, and the answering side's change for the caller (section 4.3) |
| `POST /link/v1/next` | yes | active | the next part of a large change the caller is pulling (section 4.4) |
| `POST /link/v1/deliver` | yes | active | the caller's change for the answering side; or, before it, one of its receipts, sealed (section 4.3) |
| `POST /link/v1/file` | yes | active | `{id}`: one of the answering side's receipts, sealed to the caller's copy key (section 4.4), as `application/octet-stream`, refused `not-shared` unless a share to that link includes it; the answer's signature takes the sealed bytes' SHA-256 in place of the body's hash, and the caller checks it before keeping the file, which it can while its copy is locked; the plaintext's SHA-256, which the change carried sealed, is checked as the copy shows the file (S11.9.6.4) |
| `POST /link/v1/certificate` | yes | active, paused | `{fingerprint}`: the caller's next TLS certificate key, announced before it is used (section 4.5) |
| `POST /link/v1/end` | yes | requested, pending, active, paused | the link ended on the calling side |

### 4.1 Joining

1. A link code is `mkl1.` and unpadded base64url of `{"a": address, "f": fingerprint, "c":
   secret, "t": certificate}`, `t` being the SHA-256 of the inviting side's TLS certificate key
   when that certificate is its own, and absent when it is a public one. The inviting side
   keeps only the SHA-256 of the secret, and the code works once, for 24 hours.
2. The joining server connects to the address, verifying TLS as section 1.2 says, calls `hello`
   and refuses to go on unless the key it answers with hashes to the code's fingerprint. It
   then calls `join`, signed by its own key, with `{code, address, t}`, `t` being its own
   certificate key's fingerprint when its certificate is its own: the inviting side has no link
   with that key yet, so the signature only proves the caller holds the key it sends, and the
   secret proves it was given the code.
3. The inviting side turns the invitation into a request from that key and answers with its
   `version` and no directory; its admin approves or rejects it. Directories cross from the first exchange after
   the approval. The joining side's link waits as **pending** until the first `exchange` from
   the inviting side, which only an approved link makes, or until its own `exchange` is
   answered as active.

### 4.2 Directories

Every `exchange` carries the sender's directory, and its answer the receiver's, from the first
exchange after the link is approved:

```json
{
  "household": {"serverName": "doe-parents", "name": "Jeremy & Candace", "avatar": {...}},
  "users": [{"id": "User_…", "username": "candace", "displayName": "Candace Doe",
             "email": "candace@parents.home", "sex": "female"}]
}
```

Only active local users are listed. The receiver keeps each as a remote user by its `id`:
added, updated in place, soft-deleted when it leaves the list and restored when it returns.
It keeps a display name of up to 120 characters and a username of up to 64, and a sex other
than `female` or `male` as `male`; of each item, a kind of up to 20 characters and an owner's
name of up to 120.
Each remote user has a person here, with the name and sex the directory gives (requirements
S10.10.1), used only for gifts.

### 4.3 Exchanges

1. Either side may make an exchange, hourly and when an admin presses **Pull now**; whichever
   can reach the other does, so one reachable side is enough. A server makes one exchange of a
   link at a time; while its own runs, it answers the peer's `exchange`, `next` and change
   `deliver` for that link with `busy` (section 7) rather than wait, so two servers exchanging
   with each other at once never wait on each other.
2. The caller sends `{…directory, have, wantFull, registryOnly, copyKey}`: `have` is the
   `upTo` of the last change it took from the answering side (section 4.4), `wantFull` asks
   for everything (a new or reset copy, a change out of sequence, a copy at a later schema
   revision than the change), `registryOnly` asks for the registry alone, while the caller's
   copy can't take data (no worker for the answering side's release, section 5.5, or its
   inbox at its cap, S11.9.5.4), and `copyKey` is the public key of the caller's linked copy
   for this link (S11.9.2.2), which the answering side seals its change to. Before the
   caller's copy has an access key, `copyKey` is absent and the answer carries only the
   change's registry (section 4.4).
3. The answer carries `{…directory, state, version, have, wantFull, registryOnly, copyKey}`
   for the other direction, and `change`, the first part of the answering side's change for
   the caller, when there is one, with `cursor` when more parts are to come (section 4.4.3);
   the caller asks for each with `next`, sending its `have` and the `cursor`, until a part
   comes without one.
4. The caller then makes its own change for the answering side, from the `have`, `wantFull` and
   `copyKey` in the answer, and sends it with `deliver`, a part at a time, each answered with
   the new `have`. The caller's receipts for a part travel in `deliver` calls of their own
   before it: each one's sealed bytes as the body, `application/octet-stream`, with
   `MK-Link-File` naming the receipt, the call signed over the sealed bytes' SHA-256 and read as
   it arrives, never whole in memory; the answering side keeps each as it came until the part
   that names it arrives, so it never has to call back to fetch them. A delivered receipt waits
   for its part only while the change it belongs to is under way, never for ever: once that
   change is given up (a part refused, the caller's next exchange begun, which reads its change
   again from the same `have` and delivers the receipts again, or a restart on the answering
   side), it no longer waits, and is swept as a file no row names (S11.9.6.6). The caller
   fetches the answering side's receipts with `file`.
5. **A receipt never holds a change back.** One that can't be delivered or fetched (a
   connection dropped, its file gone at the source) is left out: the change is taken without
   it, the receiver keeps the receipt as not arrived, and asks for it with `file` at each
   exchange until it comes. Whatever fails after the `exchange` call is recorded on the link as
   a failed call is, so a link that keeps failing is alerted (S12.11.1).
6. A side whose link is paused refuses data with `link-paused`, its message saying until when;
   the caller waits and doesn't count it as a failure, so no one is alerted. A removal and an
   end still cross a paused link (S11.4).

### 4.4 Changes

A change brings the receiver from its `have` to now. It has two parts, the **registry**, which
the receiving server keeps in its main database while the copy is locked (S11.9.1), and the
**sealed** part, which only the copy opens:

| Field | Part | Meaning |
|---|---|---|
| `from` | registry | the `have` it starts from: the `upTo` of the change before it, or none for everything |
| `upTo` | registry | the sender's data version when its first part was read (schema.md §8): the change holds what was written up to it |
| `release` | registry | the sender's MoolaKata release and schema revision, which draw and migrate the receiver's copy (section 5.5) |
| `asOf` | registry | when it was read |
| `full` | registry | it replaces everything the receiver has from this link |
| `items` | registry | items added or changed: `id`, `kind`, `ownerName`, `sharedAt`, `viewers` (the receiver's user ids it names), `includeReceipts`, `version` |
| `removed` | registry | ids of items no longer shared |
| `progress` | registry | in a large change's parts: `from`, the date of the oldest record the change holds; `through`, the newest date the parts so far reach; `bytes`, what they hold; `total`, what the sender reckoned the whole change holds when it read the first part |
| `cursor` | registry | in a large change's parts, where the next part starts (the date and record reached); absent in the last part |
| `fetch` | registry | the ids of the receipts the part sends, so the receiver can fetch them (or take them from the `deliver` calls before it) while its copy is locked |
| `sealed` | sealed | the rest, sealed to the receiver's `copyKey` in the streaming format of S11.9.6 under the label `moolakata link change`, its associated data naming the link (the sender's and the receiver's fingerprints, `<sender>><receiver>`, so a change sealed for one direction opens for no other) and `upTo`, in unpadded base64url: each item's `name`; `rows`, records added or changed (their table, and the row whole in the sender's schema, with its `changeSeq`); `totals`, a budget's monthly totals added or changed (`itemId`, `viewer`, the key and its figures, and the stamp they were worked out at); `docs`, documents added or changed (`itemId`, `path`, `viewer`, `body`, `stamp`); `docsRemoved`; `files`, receipts' files added, when their share includes them (their id, item, length, hash, thumbnail and what was read from them, but no type: the receiver finds that from the bytes); and `filesRemoved` (unshared, or pruned at the source, S14.10.6) |
| `signature` | — | Ed25519 by the sender's link key over the registry and the SHA-256 of `sealed`, as canonical JSON (keys sorted, no spaces) |

A receipt's bytes are sealed by the source the same way, under the label `moolakata link
receipt`, the associated data naming the link (as for a change) and the receipt, and cross in
`deliver` or in the answer to `file`. The receiver keeps them as they came. Its copy finds the
receipt's type from its bytes when the receipt arrives in it (as the change that names it is
applied, or, for a receipt that comes after its change, as it is placed), keeps it in
`shared.db`, and never takes it from the change (S11.9.6.5).

1. **What a change holds**, by kind (section 6): the records of its shared items with a
   `changeSeq` above `from` and up to `upTo` (all of them when `full`, or for an item newly
   shared or naming someone new); a budget's monthly totals; and the documents the sender
   works out, each for the person it names (`viewer`), with the code its own screens use. A
   row or figure names an account that isn't shared with the same people only as *an account
   not shared* (S11.3.1).
2. **Finding what changed.** Records are found by their `changeSeq` (schema.md §8), so the
   sender keeps nothing for them but what the receiver tells it in `have`. Totals and
   documents are worked out in the same read transaction as the records, its data version
   read first, so all of a change is as of one `upTo`; each carries its `stamp`, that version
   and the day. The sender keeps, for each, the stamp and hash it sent, and works it out again
   only when the data version has moved past its stamp or the day has turned, sending it only
   when its hash differs. A receiver whose `have` isn't an `upTo` the sender sent gets
   everything.
3. **A large change travels in parts**, oldest to newest across every item together (S11.4):
   the first part carries the items and what was removed, then the records follow by date,
   cut at about 4 MB on whole records up to a date, each part signed as a change of its own
   with its `progress` and `cursor`; totals and documents come in the last part. The sender
   reads each part when `next` asks for it, from the `cursor` the caller sends, in a read
   transaction of its own, and holds nothing between parts: a restart on either side carries
   on from the `cursor`. A record written while the parts are being read has a `changeSeq`
   above `upTo`, so the next change holds it. The copy fills from its earliest records and is
   usable up to a date while the rest arrives, and the receiver shows how far it has come
   (*Up to Jul 1, 2024 (47 MB of 2 GB)*, S11.7.1).
4. The receiver checks the signature and that `from` is its `have` (or that the change is
   `full`); otherwise it asks for everything at its next exchange. It applies a row only when
   its `changeSeq` is above the one its copy holds for that row, so nothing steps back. It
   keeps the registry in its main database and writes `sealed` into the link's copy's inbox
   as it came (S11.9.5), its registry beside it sealed to the copy's key (S11.9.1), where it
   is applied, its signature and its `from` checked again, once the copy is unlocked.
   Until the copy has an access key (S11.9.2.1), a pull keeps the registry only; making the
   key asks for everything at the next exchange.
5. **Nothing counts as sent until the receiver has it.** The sender keeps a change's totals'
   and documents' stamps and hashes as pending, and makes them the ones it sent only when a
   later `have` reaches that change's `upTo`. A change that never arrived is read again from
   the same `have`.
6. **Registry only.** A caller that sends `registryOnly` gets a change with its registry
   alone (`items`, `removed`, the directory) and no `sealed` part, so removals and an end
   take effect while its copy takes no data; its `have` stays where it was, and its first
   exchange without `registryOnly` catches up from it.

### 4.5 A new certificate

A server whose certificate is its own (S13.3) and whose key changes calls `certificate`,
signed, on each active or paused link as soon as it sees the change, before its next exchange
(read by connecting to the server's own link address, or, when that can't be reached and the
server serves TLS itself, from its listener's file); the peer keeps the new fingerprint beside the old, and accepts either until
an exchange over the new one succeeds. A certificate whose key changes unannounced is refused, and the link shows *the
peer's certificate changed* until an admin there accepts the new fingerprint, which the peer's
admin reads out from their Settings › Linked servers.

### 4.6 A link's states

A link is **invited**, **requested**, **pending**, **active**, **paused** or **ended**; the
calls each allows are the table's in section 4. **Broken** is a mark on a pending, active or
paused link, never a state: the peer answered `not-linked`. These events move a link, and
nothing else does (`links/lifecycle.py`, held to this table by a test):

| Event | From | To |
|---|---|---|
| `invite`: an admin makes a link code | — | invited |
| `join-here`: an admin enters the other server's code | — | pending |
| `join-arrives`: the other server answers this one's code | invited | requested |
| `approve` | requested | active |
| `peer-active`: the other side's exchange, or its answer, says active | pending, active | active |
| `pause` | active | paused |
| `resume`: an admin, or the pause running out | paused | active |
| `end-here` | invited, requested, pending, active, paused | ended |
| `link-ended`: the peer's signed `link-ended` | requested, pending, active, paused, ended | ended |
| `not-linked`: the peer's answer; marks the link broken | pending, active, paused | the same |
| `good-call`: any answered call; the broken mark goes | any | the same |
| `link-again`: a new link with the same peer, either side's join | ended; a broken pending, active or paused | ended, and put aside |

Linking again (S11.6) is a join like any other, from either side: the link already held with
that key, ended or broken, is put aside in the join's own transaction (a broken one ended
first, its copy deleted), and the new link takes its place; a link that is neither is the one
the two servers have, and the join is refused `already-linked`. The new link pulls in full.

## 5. Versions

1. The protocol has one number, `1`, sent in `MK-Link-Protocol` on every call. A server
   answers the versions it lists as supported, and refuses any other with
   `protocol-unsupported`, naming those it speaks in `protocols` (a list of numbers), so the
   admins learn which server needs updating. A newer MoolaKata keeps answering the older protocol for at least one release
   after it adds a new one.
2. Within a protocol version, a message may gain fields: a receiver ignores fields it doesn't
   know, and a sender never relies on a new field being understood.
3. Shared items carry their kind (section 6). An item of a kind this server doesn't know is
   kept in the linked copy but not shown, and the window notes that a newer MoolaKata on the
   other side shares something this one can't show yet.
4. Each server shows the peer's MoolaKata version (from `MK-Link-Version`, and the `version`
   of the peer's signed answers) in Settings › Linked servers.
5. **The copy follows the sender's release** (S11.10). Each change names the sender's release
   and schema revision (`release`, section 4.4). The receiver draws and migrates the copy with
   a worker running that release, installed from the release's bundle on GitHub (S17.10.2),
   checked against its attestation, once its admin has allowed downloads for the link. When
   an exchange shows the peer on a release the receiver doesn't have, it fetches it at once. A
   change from a later revision than the copy's is applied after that release's worker
   migrates the copy; one from an earlier revision asks for everything. A release that wasn't
   published, or was published more than 12 months ago, isn't run: until a worker can run, the
   receiver's exchanges send `registryOnly`, and its window says what's missing (S12.10.6).

## 6. Shared items

Each shared item travels as its source's own release needs to draw it (S11.3.1), in the
changes of section 4.4:

| Kind | Records (`rows`) | Worked out at the source |
|---|---|---|
| account | the account and its type's rows, its transactions, splits, reimbursements, transfer pairs, lots, picks, corporate actions, stated holdings, holding checks, option contracts, strategies, statement balances and reconciliations; the instruments and categories they use; its transactions' public tags; the closes of what it holds or watches, and its owner's typed prices for them; a wallet as its balance, transactions and holdings, never its keys or addresses | — |
| person | the person, and relationships between two people both shared with the viewer | — |
| gift plan | the plan, its occasions and gifts; a gift's linked transaction as a small entry (date, amount, account or *an account not shared*) | — |
| portfolio | the portfolio and which accounts it holds; the closes of its benchmark, from the earliest day of its accounts | — |
| budget | the budget, the accounts it counts by month, its plan lines, moves and reviews | `totals`: per month and category, per month and account, per recurring series (S7.3.10) |
| tax book | the book, its filers, the accounts it counts, dependents, filings, changes, estimated payments and documents | `docs`: each panel |
| giving plan | the plan, its organisations and donations | `docs`: the year's giving and its donations |
| projection | — | `docs`: the projection |

Items of a kind the receiver's worker doesn't know are kept in its copy and not shown
(section 5.3).

## 7. Refusals

A refusal is JSON `{code, message}`, with HTTP 403 unless the table says otherwise, signed to
the call as section 3 says, unless the table says unsigned. The `message` is for the caller's
log: the caller tells its admins of a refusal in its own words, by its code, and never copies the
message into an alert or an email (S13.7.9).

| Code | When |
|---|---|
| `unsigned` | the signing headers are missing or malformed |
| `clock-skew` | the call's time is more than 60 seconds off |
| `bad-signature` | the signature doesn't match the key, method, path, body, time, nonce and receiver |
| `replayed` | the nonce was seen from that key in the last two minutes |
| `not-linked` | the key has no link here, refused on the call's headers before its body is read |
| `link-<state>` | the link exists here but its state doesn't allow the call |
| `limit` | (429, with `Retry-After`) the 60 calls a minute of S13.7.5.4: signed when they are the link's, unsigned when they are an address's, refused before the call is checked; the caller tries again at its next exchange |
| `too-large` | (413) a `join` over 16 KB, signed; unsigned, a body past the hard limit (20 MB of JSON, the largest sealed receipt), refused before it is read |
| `server-error` | (500) a fault in the route, logged on the answering side |
| `busy` | (429, with `Retry-After`) the answering server is making its own exchange of this link (section 4.3); the caller tries again at its next exchange, and isn't alerted |
| `locked` | (503, unsigned) the answering server is locked (S13.6); the caller tries again at its next exchange |
| `not-shared` | a file no share to that link includes |
| `file-refused` | a delivered file whose `MK-Link-File` isn't a file id |
| `protocol-unsupported` | (426) the call's protocol isn't one this server answers; `protocols` lists those it does (section 5) |
| `code-used` | a link code was used, expired or withdrawn |
| `already-linked` | the two servers already have a link that is neither ended nor broken (section 4.6) |
| `change-refused` | a delivered change fails its signature check |

A `link-ended` answer to a signed call ends the link on the calling side, as `end` would: its
copy, the shares to it and its remote users go. A `not-linked` answer (a peer restored from an
older backup, say) only marks the link broken and alerts admins (S11.6). A caller takes an
unsigned `limit`, `locked` or `too-large` as the table says, and refuses any other answer that
isn't signed as `answer-unsigned`.
