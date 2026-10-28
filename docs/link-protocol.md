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
   for each read, and cuts off an answer past 20 MB. A receipt's sealed bytes (a `deliver`
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
   link is not in a state that allows the call. Both hosts therefore keep their clocks with
   NTP; a `clock-skew` refusal is named as such on the link's state (S12.11.1.1).
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
   caller or another request, so an answer can't be handed on to anyone else. Refusals are
   signed too when the call carried a nonce, so a refusal can be told from a forgery.

## 4. Calls

| Path | Signed | Link states | What it does |
|---|---|---|---|
| `GET /link/v1/hello` | no | any | `{protocol, version, fingerprint, key}`, `key` being the link key's public half, whose SHA-256 is the fingerprint: lets a joining server check the fingerprint in a link code before it sends anything |
| `POST /link/v1/ping` | yes | pending, requested, active, paused | `{protocol, version, state}`: the link's state on the answering side |
| `POST /link/v1/join` | yes, by the caller's own key | an invitation | answers a link code (section 4.1); no directory crosses |
| `POST /link/v1/exchange` | yes | active; pending on the joining side | the directories both ways, and the answering side's change for the caller (section 4.3) |
| `POST /link/v1/next` | yes | active | the next part of a large change the caller is pulling (section 4.4) |
| `POST /link/v1/deliver` | yes | active | the caller's change for the answering side; or, before it, one of its receipts, sealed (section 4.3) |
| `POST /link/v1/file` | yes | active | `{id}`: one of the answering side's receipts, sealed to the caller's copy key (section 4.4), as `application/octet-stream`, refused `not-shared` unless a share to that link includes it; the answer's signature takes the sealed bytes' SHA-256 in place of the body's hash, and the caller checks it, and the hash the change carried, before keeping the file |
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
3. The inviting side turns the invitation into a request from that key and answers with no
   directory; its admin approves or rejects it. Directories cross from the first exchange after
   the approval. The joining side's link waits as **pending** until the first `exchange` from
   the inviting side, which only an approved link makes, or until its own `exchange` is
   answered as active.

### 4.2 Directories

Every `exchange` carries the sender's directory, and its answer the receiver's, from the first
exchange after the link is approved:

```json
{
  "household": {"serverName": "griffin-parents", "name": "Margaret & Tom", "avatar": {...}},
  "users": [{"id": "User_…", "username": "margaret", "displayName": "Margaret Griffin",
             "email": "margaret@parents.home", "sex": "female"}]
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
   can reach the other does, so one reachable side is enough.
2. The caller sends `{…directory, have, wantFull, copyKey}`: `have` is the sequence number of
   the last change it took from the answering side, `wantFull` asks for everything (a new or
   reset copy, an overflowed inbox, a change out of sequence), and `copyKey` is the public key
   of the caller's linked copy for this link (S11.9.2.2), which the answering side seals its
   change to. Before the caller's copy has an access key, `copyKey` is absent and the answer
   carries only the change's registry (section 4.4).
3. The answer carries `{…directory, state, version, have, wantFull, copyKey}` for the other
   direction, and `change`, the answering side's change for the caller, when there is one, with
   `more`, how many parts of it are still to come (section 4.4); the caller asks for each with
   `next`, sending its `have`, until `more` is 0.
4. The caller then makes its own change for the answering side, from the `have`, `wantFull` and
   `copyKey` in the answer, and sends it with `deliver`, a part at a time, each answered with
   the new `have`. The caller's receipts for a part travel in `deliver` calls of their own
   before it: each one's sealed bytes as the body, `application/octet-stream`, with
   `MK-Link-File` naming the receipt, the call signed over the sealed bytes' SHA-256 and read as
   it arrives, never whole in memory; the answering side keeps each as it came until the part
   that names it arrives, so it never has to call back to fetch them. The caller fetches the
   answering side's receipts with `file`.
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
| `seq` | registry | its number in the sender's sequence for this link |
| `asOf` | registry | when it was worked out |
| `full` | registry | it replaces everything the receiver has from this link |
| `items` | registry | items added or changed: `id`, `kind`, `ownerName`, `sharedAt`, `viewers` (the receiver's user ids it names), `includeReceipts`, `version` |
| `removed` | registry | ids of items no longer shared |
| `progress` | registry | in a large change's parts: `through`, the newest date the parts so far reach; `bytes`, what they hold; `total`, what the whole change holds |
| `fetch` | registry | the ids of the receipts the part sends, so the receiver can fetch them (or take them from the `deliver` calls before it) while its copy is locked |
| `sealed` | sealed | the rest, sealed to the receiver's `copyKey` in the streaming format of S11.9.6 under the label `moolakata link change`, its associated data naming the link (the sender's and the receiver's fingerprints, `<sender>><receiver>`, so a change sealed for one direction opens for no other) and `seq`, in unpadded base64url: each item's `name`; `docs`, documents added or changed (`itemId`, `path`, `viewer`, `body`); `docsRemoved`; `files`, receipts' files added, when their share includes them (their id, item, type, length, hash, thumbnail and what was read from them); and `filesRemoved` (unshared, or pruned at the source, S14.10.6) |
| `signature` | — | Ed25519 by the sender's link key over the registry and the SHA-256 of `sealed`, as canonical JSON (keys sorted, no spaces) |

A receipt's bytes are sealed by the source the same way, under the label `moolakata link
receipt`, the associated data naming the link (as for a change) and the receipt, and cross in
`deliver` or in the answer to `file`. The receiver keeps them as they came; its copy opens them
when they are shown, and its type is found from the bytes then, never from the change.

1. The sender works each item out as each person it names would see it, with the code its own
   screens use (S11.3.1). An item's documents are its row in its list (`path` empty) and what
   its screens read, by API path: an account's detail, balance series, holdings and its
   transactions; a portfolio's detail, holdings, returns and series; a budget's month, trends,
   cash flow and recurring payments; a tax book and its panels; a projection; a year's giving;
   a person's gifts; and a person shared on their own: their row (name and birthday) and
   their relationships to those the viewer may see (`/persons/{id}/relations`). An
   account that isn't shared with the same people is named in a document only as *an account
   not shared* (S11.3.1).
2. The sender keeps a hash of each document it last sent, so only what changed travels. A
   receiver whose `have` isn't the sender's last `seq` gets everything.
3. **A large change travels in parts**, oldest to newest (S11.4): past 4 MB, the first part
   carries the items and what was removed, and the records follow by date, a long document (an
   account's transactions) split into parts of whole records up to a date, each part signed and
   numbered as a change of its own with its `progress`. The copy fills from its earliest
   records and is usable up to a date while the rest arrives, and the receiver shows how far it
   has come (*Up to July 2022, 47 MB of 2 GB*). A part missed or out of turn makes the next
   exchange ask for everything. The source keeps the parts still to send in memory, so after it
   restarts `next` answers nothing and the caller's next exchange asks for everything.
4. The receiver checks the signature and that `seq` follows its `have` (or that the change is
   `full`); otherwise it asks for everything at its next exchange. It keeps the registry in its
   main database and writes `sealed` into the link's copy's inbox as it came (S11.9.5), where
   it is applied, its signature and its sequence checked again, once the copy is unlocked.
   Until the copy has an access key (S11.9.2.1), a pull keeps the registry only; making the key
   asks for everything at the next exchange.

### 4.5 A new certificate

A server whose certificate is its own (S13.3) and whose key changes calls `certificate`,
signed, on each active or paused link as soon as it sees the change, before its next exchange
(its own listener's certificate is read from its file; a proxy's, by connecting to the server's
own link address); the peer keeps the new fingerprint beside the old, and accepts either until
an exchange over the new one succeeds. A certificate whose key changes unannounced is refused, and the link shows *the
peer's certificate changed* until an admin there accepts the new fingerprint, which the peer's
admin reads out from their Settings › Linked servers.

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
4. Each server shows the peer's MoolaKata version (from `MK-Link-Version`) in Settings ›
   Linked servers.

## 6. Shared items

Each shared item travels as its screens show it, worked out at its source (S11.3.1), in the
changes of section 4.4. Items of a kind the receiver doesn't know are kept in its copy and not
shown (section 5.3).

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
| `not-linked` | the key has no link here; unsigned when the call's body is over 1 MB, refused on its headers before the body is read (S13.7.5.4) |
| `link-<state>` | the link exists here but its state doesn't allow the call |
| `limit` | (429, unsigned, with `Retry-After`) the 60 calls a minute of S13.7.5.4; the caller tries again at its next exchange |
| `locked` | (503, unsigned) the answering server is locked (S13.6); the caller tries again at its next exchange |
| `not-shared` | a file no share to that link includes |
| `protocol-unsupported` | (426) the call's protocol isn't one this server answers; `protocols` lists those it does (section 5) |
| `code-used` | a link code was used, expired or withdrawn |
| `already-linked` | the two servers already have a link |
| `change-refused` | a delivered change fails its signature check |

A `link-ended` answer to a signed call ends the link on the calling side, as `end` would: its
copy, the shares to it and its remote users go. A `not-linked` answer (a peer restored from an
older backup, say) only marks the link broken and alerts admins (S11.6). A caller takes an
unsigned `limit` or `locked` as the table says, and refuses any other answer that isn't signed
as `answer-unsigned`.
