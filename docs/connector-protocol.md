# The connector protocol

How the MoolaKata Connector talks to the MoolaKata server it is paired with (requirements S18).
This document is the protocol's statement; the code that speaks it is
`web/server/src/moolakata/connector/` on the server's side and `connector/moolakata_connector/`
on the connector's. It follows the link protocol (`link-protocol.md`) wherever the two do the
same thing, so one reading covers both.

**Terms.** The **action key** (Ed25519) signs the connector's calls and is kept in its vault;
the **status key** (Ed25519) is kept beside the vault and signs only a report that the
connector is locked, and `unpaired`; the **sealing key** (X25519) is what a browser seals a
credential to, its public half held by MoolaKata and its private half kept in the vault; a **sealed box** is such a credential
as MoolaKata stores and hands over, unable to open it; the **vault** is the connector's
encrypted file of credentials and the sealing key, open only while the connector is
**unlocked** with its words; a credential's **bound host** is the one host it may ever be sent
to: the one sealed with it, fixed when it is filed. Requirements S18 defines them in full.

**The calls at a glance.**

```
 connector                                                  MoolaKata
   |  GET  /connector/v1/hello                                 |  unsigned: {protocol, version, fingerprint, key}
   |---------------------------------------------------------->|
   |  POST /connector/v1/pair {code, sealingKey, statusKey, …} |  once; signed by the new action key
   |---------------------------------------------------------->|
   |  POST /connector/v1/report {locked: true}                 |  locked: the status key's, answered
   |---------------------------------------------------------->|   {ok, certificate} and nothing more
   |  POST /connector/v1/report {locked: false, connections[]} |  every 5 minutes, the action key's
   |---------------------------------------------------------->|
   |<----------------------------------------------------------|  {connections: settings, accounts,
   |                                                           |   sealed (once confirmed)}, removed[],
   |                                                           |   confirmed, certificate
   |  POST …/connections/{id}/credential/taken                 |  the box is in the vault: delete it
   |---------------------------------------------------------->|
   |  POST …/connections/{id}/sign-in {address}                |  the owner must sign in at the institution
   |---------------------------------------------------------->|
   |  POST …/accounts/{id}/files  (multipart: meta, file)      |  through the owner's import
   |---------------------------------------------------------->|
   |  POST /connector/v1/unpaired                              |  the connector forgot this server;
   |---------------------------------------------------------->|   either key
   every answer to a signed call is signed back by MoolaKata's link key
```

## 1. Transport

1. The connector **only opens connections** (S18.2.2): HTTPS POSTs of JSON, or multipart for a
   file, to `/connector/v1/` on MoolaKata's address, the one in the pairing code. MoolaKata
   never calls the connector; everything the connector must learn comes back in the answers
   to its own calls.
2. **The connector verifies MoolaKata's TLS certificate**: a public one against the system's
   roots, and one that is MoolaKata's own (S13.3) against the fingerprint of its key that the
   pairing code carried (`t`, section 4.1); while the certificate is MoolaKata's own, every
   report's answer, signed, carries its key's fingerprint as `certificate`, so a new one is
   accepted beside the pinned one until it is in use. TLS keeps each message private; the signature on each answer
   (section 3), checked against the link key whose fingerprint the code carried, proves who
   wrote it. The connector follows no redirect, and reads at most 25 MB of an answer.
3. Everything but `hello` is signed, and every answer to a signed call is signed back.
4. JSON bodies are UTF-8, at most 1 MB; a file post is multipart, the file up to Settings ›
   Imports' size (S16.8), the one statements are held to (S13.7.6).
5. Only addresses in Settings › Network's **Allowed to connect** ranges reach `/connector`
   (S16.14); others get 404, as for `/ui`.

## 2. Keys and fingerprints

1. The connector has three keys, made at every pairing (S18.4.2, S18.4.5):
   1. an **action key** (Ed25519) that signs every call but two, kept **in** the vault;
   2. a **status key** (Ed25519), kept **beside** the vault so a locked connector can still
      report, which signs only a report that says it is locked and `unpaired`: so a copy of the
      connector's volume, without the words, can say no more than that (S18.2.4.4);
   3. a **sealing key** (X25519) that credentials are sealed to (S18.7.1), whose private half is
      kept **in** the vault, so a copy of the volume opens no box without the words.

   MoolaKata holds only their public halves. The connector's **fingerprint**, the one an admin
   compares and confirms, is its action key's.
2. MoolaKata signs its answers with its **link key** (`link-protocol.md` §2), the same key
   its peers know; a server without a link yet makes it at the first pairing.
3. A key's **fingerprint** is the SHA-256 of its raw 32-byte public key, in hex. The pairing
   code carries MoolaKata's whole; screens show the first 16 digits in four groups for the
   admin to compare (`c2f1 08aa 5e7d 91b3`).
4. Keys travel as their raw 32 bytes in unpadded base64url.

## 3. Signed calls

1. A call carries these headers:

   | Header | Value |
   |---|---|
   | `MK-Conn-Key` | the public half of the key that signs the call: the action key's, or the status key's (section 4) |
   | `MK-Conn-Time` | Unix seconds |
   | `MK-Conn-Nonce` | 16 random bytes, base64url |
   | `MK-Conn-Signature` | Ed25519 over the lines below, base64url |
| `MK-Conn-Body-SHA256` | the SHA-256 of the body, hex: the hash the signature covers, named so MoolaKata checks the signature before it reads the body |
   | `MK-Conn-Protocol` | the protocol version the call speaks (section 5) |
   | `MK-Conn-Version` | the connector's version, for Settings › Connector to show |

   The signed text is these lines, joined by `\n`:

   ```
   MK-CONN-1
   <method, upper case>
   <path with its query>
   <SHA-256 of the body, hex>
   <time>
   <nonce>
   <MoolaKata's link-key fingerprint>
   ```

   For a multipart post the body hash is over the raw request body as sent. Naming the
   receiver's fingerprint means a call can't be replayed against another server.
2. MoolaKata refuses, with the codes in section 7: a call without these headers, a time more
   than **60 seconds** from its own clock, a signature that doesn't verify, a nonce it has seen
   from that key in the last two minutes, a key that isn't the paired connector's (but at
   `pair`), a key the call may not be made with (section 4), and a paired connector whose
   pairing has ended. **All of this is checked before a byte of the body is read**, against the
   hash `MK-Conn-Body-SHA256` names; the body is then read and must hash to it. So only a call
   the paired connector signed has its body read, whatever key header a caller sends.
3. **Answers** are signed the same way: `MK-Conn-Time` and `MK-Conn-Signature` over

   ```
   MK-CONN-1-ANSWER
   <HTTP status>
   <SHA-256 of the body, hex>
   <time>
   <the call's nonce>
   <the connector's fingerprint>
   <SHA-256 of the call's body, hex>
   ```

   The connector refuses an answer that isn't signed by the key the pairing code named, or that
   names another caller (the key that signed the call) or another request. With TLS verified (section 1.2), a server
   pretending to be MoolaKata gets nothing past it: no report, no file, and no sealed
   credential is ever sent to it. Refusals are signed too when the call carried a nonce, a
   fault in a route included (`server-error`): only the three refusals MoolaKata makes before
   the call reaches its route are unsigned (section 7), and the connector acts on no other
   unsigned answer.
4. Rate: 60 calls a minute (S13.7.5.4); a file post also counts against the upload limit of the
   Connection's owner (S18.8).

## 4. Calls

| Path | Signed by | What it does |
|---|---|---|
| `GET /connector/v1/hello` | no one | `{protocol, version, fingerprint, key}`, `key` being the link key's public half, whose SHA-256 is the fingerprint: lets a connector check the fingerprint in a pairing code before it sends anything |
| `POST /connector/v1/pair` | the connector's new action key | introduces the connector with a pairing code (section 4.1) |
| `POST /connector/v1/report` | the action key; the status key while locked | the connector's state every 5 minutes, answered with the work waiting; locked, only that it is locked (section 4.2) |
| `POST /connector/v1/connections/{id}/credential/taken` | the action key | the sealed credential was filed in the vault: MoolaKata deletes its copy (section 4.3) |
| `POST /connector/v1/connections/{id}/sign-in` | the action key | a driver needs the owner to sign in at the institution's page: the address to open (section 4.3) |
| `POST /connector/v1/accounts/{id}/files` | the action key | a driver posts a file for one account (section 4.4) |
| `POST /connector/v1/unpaired` | either key | the connector was told to forget this server (`moolakata-connector unpair`): MoolaKata ends the pairing as Unpair would |

A call the status key signs but may not make is refused `status-key`.

### 4.1 Pairing

1. An admin's **Pair** (Settings › Connector) makes a pairing code: `mkp1.` and unpadded
   base64url of `{"a": address, "f": fingerprint, "c": secret, "t": certificate}`, as a link
   code is (`link-protocol.md` §4.1), `t` present when MoolaKata's certificate is its own.
   MoolaKata keeps only the SHA-256 of the secret and the code's expiry (24 hours); a code
   works once. Making a code needs the admin's password again (S13.7.2).
2. `moolakata-connector pair <code>`, run with the vault unlocked (it is refused otherwise,
   since the sealing key's private half goes into the vault), connects to the address,
   verifying TLS as section 1.2 says, calls `hello` and refuses to go on unless the key it
   answers with hashes to the code's fingerprint; it keeps that key with the pairing. It makes
   a new action key, status key and sealing key, then calls `pair`, signed by the action key,
   with `{code, sealingKey, sealingSignature, statusKey, statusSignature, actionSignature,
   version}`:
   1. `sealingSignature`, the action key's signature over `moolakata connector sealing key`, a
      zero byte and the sealing key, which browsers check before sealing (section 4.3);
   2. `statusSignature`, the action key's over `moolakata connector status key`, a zero byte
      and the status key; `actionSignature`, the status key's over `moolakata connector action
      key`, a zero byte and the action key: each signed by the other, so both are one
      connector's, and the two are never the same key.

   The new pairing is written only once `pair` succeeds, so a refused one leaves any earlier
   pairing as it was. MoolaKata has no pairing with these keys yet, so the signatures only prove
   the caller holds the keys it sends, and the secret proves it was given the code.
3. MoolaKata records the three public keys, ends any connector paired before (as Unpair does:
   every Connection stopped, every account's sync turned off, S18.4.4), and answers
   `{fingerprint, connectorFingerprint, serverName}`. Both sides show the connector's
   fingerprint, its action key's, for the admin to compare, each working it out from the key
   itself, never from what the other says: the connector refuses an answer whose
   `connectorFingerprint` isn't the one it works out, keeping nothing. A mismatch on the
   admin's side means someone else answered the code first, and the admin unpairs. Until the admin
   **confirms** the pairing in Settings (S18.4.2), the pairing is not trusted: reports are
   answered, but `sealed` is withheld and a file post is refused `not-confirmed`.
4. The connector then keeps with the pairing the address, the fingerprint, MoolaKata's key and
   its own keys: the status key and the public halves beside the vault, the action and sealing
   keys' private halves in it. One connector is paired with one server; `moolakata-connector unpair` forgets it
   and deletes every credential it held for it, as a signed `not-paired` answer from MoolaKata
   makes it do (S18.4.4).

### 4.2 Reports

Every 5 minutes, at once after an unlock, a run or a change the connector wants to tell of, and
every 15 seconds for up to 10 minutes while a Connection waits for a sign-in (so the address an
owner pastes back is exchanged within seconds), `POST /connector/v1/report`.

**Locked**, the report is the status key's and is `{"locked": true}`: MoolaKata takes from it
the time, the version and the address it came from (item 3 below), marks the connector locked,
and answers `{"ok": true, "certificate": …}` and nothing more, whatever else the body says; the
connector runs nothing and posts nothing until it is unlocked. **Unlocked**, the report is the
action key's:

```json
{
  "locked": false,
  "unlockedAt": "2026-10-15T06:02:00Z",
  "page": "https://connector.griffin.home:37374",
  "connections": [
    {
      "id": "Conn_01k7…",
      "state": "ok",
      "message": "14 new",
      "lastRunAt": "2026-10-15T05:40:12Z",
      "lastRunAdded": 14,
      "institutionAccounts": [{"name": "Individual", "last4": "4417"},
                              {"name": "Rollover IRA", "last4": "0921"}],
      "signInAddress": null
    }
  ]
}
```

1. `state` is one of `new` (credentials not yet received), `ok`, `needs-sign-in` (the
   institution wants the owner again: Schwab's weekly sign-in, a changed password), `failing`
   (with `message` saying why in the connector's words, never a credential, an amount or an
   account number beyond its last four digits, S18.5). A Connection the connector doesn't know
   (made in MoolaKata, not yet collected) is absent; MoolaKata keeps it as `new`.
2. The answer carries what waits for the connector:

   ```json
   {
     "connections": [
       {"id": "Conn_01k7…", "ownerName": "Alice", "driver": "schwab",
        "label": "Alice's Schwab login", "settings": {…},
        "accounts": [{"id": "Acct_01k7…", "syncAccount": "Individual ••4417",
                      "formats": ["ofx"]}],
        "sealed": {"ciphertext": "…", "sealedAt": "2026-10-15T05:30:00Z"}}
     ],
     "removed": ["Conn_01k6…"],
     "confirmed": true,
     "certificate": "9c41…"
   }
   ```

   `connections` is every live Connection for this connector with its driver, settings and the
   accounts whose sync names it, each with the formats MoolaKata takes for it; `sealed` is
   present while a credential waits (section 4.3), **the report said `locked: false`** (a
   locked connector has no sealing key to open it with) **and an admin confirmed the pairing**
   (section 4.1); `removed` names Connections whose owners removed them (S18.6.4), and the
   connector deletes their credentials and never reports them again. `confirmed` says whether
   an admin confirmed the pairing, which the connector's page shows (S18.11.3). `certificate`,
   while MoolaKata's certificate is its own, is its key's fingerprint (section 1.2).
3. MoolaKata records the report's time, so a connector silent for 15 minutes raises the alert
   of S18.5.2, and shows `locked` as S18.5.1 says. It records the address the report came from
   as well: the first is taken as the connector's; a report from another address is still
   answered but alerts admins until one accepts the new address or unpairs (S18.5.4), whichever
   address reports after it. It keeps `page`, the address of the connector's own page
   (S18.11.1), when it is an `https` address of a host and port and nothing more, and Settings ›
   Connector links to it; a report without one clears it.

### 4.3 Credentials

1. **Sealed in the browser** (S18.7.1): the owner's browser fetches the connector's sealing key
   with its signature by the action key (`GET /ui/api/connector`, the action key's fingerprint
   shown), checks the signature, and seals `{credentials, host, sealedAt}`, the
   host being the one the dialog shows the owner, as an X25519 sealed box (an ephemeral X25519
   key, HKDF-SHA256 over the exchange with the label `moolakata connector credential` and the
   Connection's id as salt, AES-256-GCM with a random 96-bit nonce; the box is the ephemeral
   public key, the nonce and the ciphertext, base64url), and sends the box to `POST
   /ui/api/profile/connections/{id}/credential`. MoolaKata stores the box as it is and hands
   it to the connector in the next report's answer.
2. The connector opens the box with the sealing key from its vault, refuses it when its host
   isn't the one the Connection's settings name or when it is older than the credential it
   holds, files the credentials in the vault under the Connection's id **bound to the host
   sealed with them** (section 6), and calls `credential/taken` with `{sealedAt}`; MoolaKata
   deletes that box, and only that one. A box the connector can't open (sealed to an earlier
   sealing key) is reported as the Connection `failing` with *the credentials were sealed for
   another connector*, and the owner is asked to enter them again.
3. **The bound host** (S18.7.3): before each run, the connector compares the bound host with
   the host the settings name now. If they differ it sends nothing, deletes the credential, and
   reports the Connection as `needs-sign-in` with *the server address changed from A to B:
   enter the credentials again*; a credential entered then is bound to the new host. No
   change to `settings` can therefore send a stored credential anywhere but where its owner
   entered it for.
4. **A sign-in through the institution's page** (OAuth, as Schwab's): the driver calls
   `sign-in` with `{address}`, the institution's sign-in address for this Connection, with a
   random `state` in it; MoolaKata takes it only on the driver's own sign-in host (refusing
   another with `address-invalid`) and shows it, with that host, to the owner under Profile ›
   Connections. The owner opens it, signs in, and pastes the address they land on into the same
   credential dialog, which seals it as in 4.3.1; the driver checks its `state`, reads the code
   from it and completes the sign-in at its next report, within seconds (section 4.2).
5. **Typed on the connector's host** (S18.7.2): `moolakata-connector connect <connection id>`
   shows the host the Connection's settings name, asks the admin to confirm it, asks for the
   credentials there and files them in the vault bound to that host; the connector must have
   heard of the Connection in a report (it reports first when it hasn't); nothing crosses the
   wire but the next report's state.

### 4.4 Files

`POST /connector/v1/accounts/{id}/files`, multipart with one `file` part and a `meta` part:

```json
{"connectionId": "Conn_01k7…", "format": "ofx", "fetchedAt": "2026-10-15T05:40:10Z",
 "fileName": "schwab-2026-10-15.ofx", "sha256": "…"}
```

1. The account must have its sync set to this Connection, and the Connection must belong to
   the account's owner; otherwise `account-not-synced`. Until an admin confirmed the pairing,
   `not-confirmed`: the connector keeps the file for a later run, as for `limit`.
2. The file goes through the same import as an upload by the owner (S1.3, S18.8): its type is
   checked from its content, imports are idempotent, a PDF is kept without reading or waits in
   the account's inbox, and a CSV uses the account's saved mapping (without one, the post is
   refused with `mapping-missing` and the Connection told so). Activity records it as *by
   MoolaKata Connector, Alice's Schwab login* under the owner.
3. The answer is `{imported: {added, matched, changed}, kept: bool}` as the import dialog would
   show it. `429` with `Retry-After` means the owner's upload limit; the connector keeps the
   file and posts it on a later run.
4. **Each file on its own** (S18.8): the connector keeps a file for a later round on a dropped
   connection or an answer that isn't signed, and on `locked`, `limit`, `uploads-in-flight`,
   `not-confirmed` and `server-error`; it drops it on any other refusal, and the Connection
   shows the refusal. Either way it posts the next file and the next Connection's, and sends
   the report after the run. It keeps the newest ten waiting per Connection.

## 5. Versions

1. The protocol has one number, `1`, in the path (`/connector/v1/`) and in `MK-Conn-Protocol`.
   A server answers the versions it lists as supported and refuses any other with
   `protocol-unsupported`, naming those it speaks, so the admin learns which side needs
   updating. A newer MoolaKata keeps answering the older protocol for at least one release
   after it adds a new one.
2. Within a version, a message may gain fields: a receiver ignores fields it doesn't know, and
   a sender never relies on a new field being understood.
3. Settings › Connector shows the connector's version (from `MK-Conn-Version`).

## 6. Drivers

What each driver posts, and what its `settings` hold (S18.9):

| Driver | Posts | Settings | Credentials (sealed, 4.3) | Size |
|---|---|---|---|---|
| `ofx-direct` | the OFX statement the institution's OFX server answers with, as it is | `url`, `org`, `fid`, `accountType` (`CHECKING`, `SAVINGS`, `CREDITCARD`, `INVESTMENT`), `accountId`, `bankId` (the routing number) for a bank account, and `days`, how many days back each run asks for (1 to 90, 45 when not set) | `{username, password}`, bound to the host of `url` when filed (4.3.3) | 🟢 110 |
| `schwab` | positions, transactions and balances from the Trader API, written as an OFX investment statement, one file per account | `appKey` | `{appSecret, landed}`: the app's secret and the address the owner landed on after signing in; the driver keeps the refresh token in the vault, and asks for a new sign-in when it has run out, after seven days. Bound to no host: the driver's is fixed | 🟢 230 |

**Size** is the driver's lines of code, leaving out blank lines, comments and docstrings, with
its colour (S18.1.2.1): 🟢 under 1,000, 🟡 1,000 to 1,999, 🔴 2,000 or more, a driver to read
again before it grows. `connector/tests/test_core.py` counts them and fails when a size here is
out of date, or a driver is missing from the table.

A driver's host is the one it declares (`api.schwabapi.com`), or, for OFX Direct Connect, the
server its owner named in the settings **and sealed with the credentials**; the egress
allowlist, kept per driver run, refuses every other, and loopback, link-local and cloud
metadata addresses with them, and a changed `url` asks for the credentials again (4.3.3). An
institution with nothing to fetch from has no driver: its files are uploaded by hand (S18.9).

## 7. Refusals

A refusal is JSON `{code, message}` with HTTP 403 (426 for a protocol, 429 for a limit, 404
for an account or Connection that doesn't exist or isn't this connector's, 413 for a file too
large, 500 for a fault), signed as section 3 says when the call carried a nonce. Three are made
before the call reaches its route, on its headers or as its body arrives, and are **unsigned**,
as problem JSON with `code`: `locked`, `uploads-in-flight` and `too-large` for a body past the
hard limit. The connector acts on those three by their status and code, and on no other
unsigned answer, which it treats as a failed call (`answer-unsigned`).

| Code | When |
|---|---|
| `unsigned` | the signing headers are missing or malformed |
| `clock-skew` | the call's time is more than 60 seconds off |
| `bad-signature` | the signature doesn't match the key, method, path, body, time, nonce and receiver |
| `replayed` | the nonce was seen from that key in the last two minutes |
| `not-paired` | the key isn't the paired connector's, or the pairing has ended |
| `status-key` | a call the status key may not make: only a report and `unpaired` are its |
| `keys-unsigned` | at pairing, the status and action keys don't sign each other, or are one key |
| `sealing-unsigned` | at pairing, the sealing key isn't signed by the action key |
| `not-confirmed` | an admin has not yet confirmed the pairing (S18.4.2); the file is kept for a later run |
| `code-used` | the pairing code was used, expired or withdrawn |
| `protocol-unsupported` | the call's protocol isn't one this server answers |
| `account-not-synced` | the account's sync doesn't name this Connection |
| `mapping-missing` | a CSV for an account with no saved mapping |
| `file-refused` | the file's content isn't a type MoolaKata imports, or the reader can't read it (its message says why) |
| `limit` | the owner's upload limit; `Retry-After` says when to try again. Also the 60 calls a minute of section 3.4 |
| `not-found` | (404) the Connection or account doesn't exist, or isn't this connector's |
| `address-invalid` | a sign-in address that isn't on the driver's own sign-in host |
| `too-large` | (413) a file over Settings › Imports' size (S16.8), signed; unsigned, a body past the hard limit (1 MB of JSON, that size and the form around it), refused before it is read |
| `uploads-in-flight` | (429, unsigned) more uploads are arriving at once than MoolaKata holds (S13.7.6); the file waits for a later round |
| `server-error` | (500) MoolaKata failed on the call; it logged why. The file waits for a later round |
| `locked` | (503, unsigned) MoolaKata is locked (S13.6); the connector tries again at its next report |

The connector refuses on its own side, sending nothing further: `not-moolakata` (the address
doesn't answer `hello` as MoolaKata), `fingerprint-mismatch` (the server's fingerprint isn't the
code's or the pairing's), `answer-unsigned` (an answer without its signature) and
`code-invalid` (not a pairing code, or a damaged one).
