# S18. MoolaKata Connector

The **MoolaKata Connector** keeps accounts current from their institutions without MoolaKata
ever holding, using or seeing an institution's credentials. It is a second service: it keeps
the credentials in a vault of its own, its **drivers** fetch from each institution, and it
pushes what they fetch into MoolaKata's import. MoolaKata can't reach it, read its vault or
ask it for anything. People give it its words on **its page**, which it serves itself.

**Terms used here.**

| Term | What it is |
|---|---|
| **the vault** | one encrypted file in the connector's volume holding every Connection's credentials, the host each is bound to, and the private halves of the action key and the sealing key. It opens only with the words (S18.3). |
| **the words** | 12 BIP-39 words that are the vault's key, kept in the household's password manager and never stored. |
| **locked / unlocked** | whether the words have been given since the connector last started. Locked, it reports that it is locked and nothing more. |
| **its page** | the connector's own HTTPS page, on a port of its own, where its vault is made, its words given and its pairing done; anyone on the network sees its status, and every action asks for the words (S18.11). |
| **action key** | an Ed25519 key pair made at pairing, whose private half lives **in** the vault and signs every call but two, so MoolaKata knows the paired connector. Its fingerprint is the connector's, the one an admin confirms (S18.4.5). |
| **status key** | an Ed25519 key pair made at pairing, kept **beside** the vault (not in it), whose private half signs only a report that the connector is locked and its `unpaired`: a locked connector can still report, and a copy of its volume can say no more (S18.4.5). |
| **sealing key** | an X25519 key pair made at pairing. MoolaKata holds the public half and gives it to browsers; the private half lives **in** the vault and is the only thing that opens a sealed box (S18.4.5). |
| **sealed box** | a credential encrypted in the owner's browser to the sealing key, which MoolaKata stores and hands over but cannot open (S18.7.1). |
| **pairing / pairing code** | the one-time introduction of a connector to a MoolaKata server, from a code Settings shows (S18.4). |
| **Connection** | one sign-in at one institution, owned by a user; its record is in MoolaKata, its credentials in the vault (S18.6). |
| **bound host** | the host a Connection's credentials may be sent to: the one the owner's browser sealed with them, or the admin confirmed on the host, fixed when they are filed in the vault (S18.7.3). |
| **driver** | the part of the connector for one institution, which fetches from it (R2.22). Where nothing can be fetched, the file is uploaded by hand (S1.3). |

**What each side holds, and what crosses.**

```
   owner's browser
        |  seals a credential to the sealing key's public half
        v
 +------------------------------+                              +--------------------------------+
 | MoolaKata                    |   signed report, every 5 min |  MoolaKata Connector            |
 |                              | <--------------------------- |                                 |
 |  holds: action, status and   |   answer: Connections, their |  beside the vault:              |
 |         sealing public keys  |   settings and accounts, and |    status key ("locked" only)   |
 |         Connection records   |   sealed boxes, only while   |    the pairing's address + key  |
 |         sealed boxes (can't  |   the connector is unlocked  |  in the vault (needs the words):|
 |         open them)           | ---------------------------> |    action key (signs calls)     |
 |                              |   files for accounts,        |    sealing key (opens boxes)    |
 |  never: a credential, the    |   sign-in addresses,         |    credentials, each bound to   |
 |  private half of any key     |   "credential taken"         |    one host                     |
 +------------------------------+                              +--------------------------------+
 +------------------------------+                                   |
                                                                    |  only to the bound host
                                                                    v
                                                   an institution (Schwab, an OFX server)
```

1. **What it is**: one program, `moolakata-connector`, built from `connector/` in this
   repository into an image of its own, run beside MoolaKata as a second compose service
   (`connector`) or on another machine that can reach MoolaKata's address, such as a laptop.
   1. **A core** (the vault, the schedule, the pairing, the signed calls to MoolaKata and an
      egress allowlist) and **drivers**, one per institution or method, each fetching what
      its institution offers and turning it into files MoolaKata already imports (S18.8).
   2. **Small enough to read.** Python with the standard library, plus the `cryptography`
      wheel for the core alone (its Ed25519 and X25519 keys and the vault's AES-GCM, which
      the standard library doesn't provide) and at most one pinned, hashed dependency per
      driver; no import from MoolaKata. Each driver declares the hosts it talks to, the
      credentials it needs and what it sends, and a test fails when a driver reaches another
      host.
      1. **A driver's size is tracked**, since a driver holds its institution's credentials
         and knows its API: under 1,000 lines of code is **green**, 1,000 to 1,999
         **yellow**, and 2,000 or more **red**, a driver to read again before it grows. Lines
         of code leave out blank lines, comments and docstrings. Each driver's count and its
         colour's icon (🟢, 🟡, 🔴) are listed with it in the connector protocol's table of
         drivers (§6), and a test fails when one there is out of date, never for the size
         itself.
      2. **The core** (the vault, keys, signing, the client, the loop, the socket and the
         command line) has no limit: there is one core, kept as small as it can be.
2. **Isolation**: the rules the design rests on.
   1. **Separate**: its own process, unprivileged user (uid 10002), image and volume
      (`connector-data`: the vault and the connector's status key). MoolaKata never mounts
      that volume; the connector never mounts MoolaKata's data, keys or backups. The volume is
      `/var/lib/moolakata-connector` (mode 0700): `vault.json`, and `pairing.json` (mode 0600:
      MoolaKata's address and fingerprint, the status key's private half and the action and
      sealing keys' public halves), and `tls/`, its page's certificate when it makes its own (S18.11.1).
      The socket is `/run/moolakata-connector/sock` (mode 0600, on a tmpfs).
      `MOOLAKATA_CONNECTOR_DATA` and `MOOLAKATA_CONNECTOR_SOCKET` move the volume and the
      socket.
   2. **One way.** The connector only opens connections: to its institutions and to MoolaKata.
      It listens on one network port, for its own page (S18.11), which serves that page and
      its forms and nothing else; its other way in is a Unix socket inside its own container,
      for the commands an admin runs there (S18.3). MoolaKata has nothing to call and no way to
      ask for a credential. A call it makes follows no redirect (a 3xx answer is a failure, so
      nothing is sent again elsewhere), waits at most 60 seconds, and reads at most 25 MB of an
      answer. Its allowlist is kept per driver run: a run reaches its own driver's hosts and
      no other, not another driver's and not MoolaKata's, which only the connector's own calls
      reach; a test runs a driver with every other host refused. It refuses loopback,
      link-local and cloud metadata addresses, as MoolaKata's egress guard does (S13.5). It verifies every TLS
      certificate: an institution's against the system's roots, MoolaKata's against those roots
      or, for a certificate of MoolaKata's own, against the fingerprint the pairing code
      carried (S18.4.1).
   3. **What each side holds.** MoolaKata holds the connector's public keys and the records
      of S18.6, never a credential. The connector holds the credentials and the private
      halves of its action and sealing keys, sealed in its vault, and beside the vault a status
      key that can only say the connector is locked, or unpaired.
   4. **What a compromise costs**, stated for each thing that can be taken:
      1. **A compromised MoolaKata** gets no credential: the boxes it holds open only in the
         vault. It can serve altered code to a browser and capture credentials typed after the
         compromise (S18.7.1), and it can change a Connection's settings; but a credential is
         bound to the host the owner's browser sealed with it (S18.7.3), so a changed address
         sends nothing and asks the owner again. It cannot reach the connector or ask it for
         anything.
      2. **A compromised connector**, running and unlocked, holds the credentials it was
         given and can post files into the accounts whose owners turned it on (S18.6), which
         their owners would see. From MoolaKata it learns what the report's answer carries:
         each Connection's owner name, label, settings (an OFX server's address and account
         number, a routing number, a Schwab app key) and its accounts' names and last four
         digits; never an amount, a transaction or a password.
      3. **Root on the connector's running host** can read its memory while it is unlocked,
         words and all, and no design changes that.
      4. **A stolen volume, disk or backup of the connector**, or its powered-off machine,
         yields the status key and the pairing: whoever has it can report that the connector
         is locked, or tell MoolaKata it was unpaired, and nothing more. It reads none of the
         answers of S18.2.4.2, posts no file, sets no page address or sign-in address, and
         takes no sealed box, since all of that needs the action key in the vault (S18.4.5).
         An admin still **unpairs** a connector at once when its host is lost (S18.4.4). MoolaKata
         helps notice it: the address a connector's reports come from is recorded, the first
         one as known, and a report from another address alerts admins until one **accepts**
         the new address (the connector moved) or unpairs (S18.5.4). The vault stays closed
         without the words: no credential, and no sealing key, so no box sealed before or
         after the theft opens. This is why the action and sealing keys live in the vault.
      5. **Someone on the network without the words** can open its page and read its status
         (S18.11.3), which names no institution, Connection, account or credential, and can
         make wrong guesses, each logged with their address, five a minute from one address
         (S18.3.3). They can't unlock, lock, pair, unpair or reset it, nor keep the household
         from unlocking it. On a connector with no
         vault yet they could make one, whose words the household never saw: its page then
         asks for words nobody wrote down, and the household starts it again empty
         (S18.11.2), having lost nothing.
3. **The vault and its words.**
   1. **Made at install**, on its page (S18.11.2): a random 128-bit key, shown as **12 BIP-39
      words** with the vault's fingerprint, and the vault is made only once three of them,
      chosen at random, are typed back. On a terminal instead, `docker compose run --rm
      connector init` does the same before the first start, showing the words on the
      terminal and never on standard output, so no log keeps them. The admin keeps the words
      in the household's password manager. They are never stored; the vault key comes from them. The vault holds every
      Connection's credentials with the host each is bound to (S18.7.3), and the sealing key's
      private half (S18.4.5); a Schwab Connection's entry also holds the app's secret and its
      tokens with when they run out. It is one file, `vault.json`: its format's name, the
      vault's fingerprint, a nonce and the contents, sealed with AES-256-GCM under a key that
      HKDF-SHA256 derives from the words' 128 bits (label `moolakata connector vault key`),
      with the fingerprint as associated data. The words are a random key, not a password, so
      nothing stretches them. Each change seals the whole vault again with a fresh nonce,
      through a temporary file and a rename. The fingerprint, the first 16 hex digits of
      `SHA-256("moolakata connector vault" ‖ key)`, is kept in the clear, to tell another
      vault's words from a damaged file.
   2. **Locked at every start**: the connector starts locked, fetches nothing, and reports that
      it is locked (S18.5); MoolaKata down or locked is a state it reports and retries with a
      growing wait, never a reason to stop. An admin unlocks it on its page (S18.11.4), or
      with `docker compose exec connector moolakata-connector unlock`, which asks for the
      words without echo and hands them to the running connector over its Unix socket; the
      key stays in memory only. A restart, a crash or the host's reboot locks it again.
      **Lock** on its page, or `lock`, locks it at once, and `status` says what the connector
      is doing: whether it is locked and paired, its last report, and each Connection's
      state. The image's health check runs `status`, which answers whenever the connector
      runs, with a vault or without one, locked or not: healthy means alive.
   3. **Wrong words**: the checksum catches most typing slips at once; a phrase that is a
      valid one but not this vault's is refused by the vault's fingerprint. Wrong words make no
      one wait: the key is 128 random bits (S18.3.1), which no guessing rate reaches, and a
      wait would only let anyone on the network keep the connector locked. Its page takes five
      wrong tries a minute from one address, to bound the work and the log a flood makes; the
      host's `unlock` is never limited, its access being the authority (S18.3.4). Each wrong
      attempt on its page is logged with the address it came from and the kind of mistake,
      never what was typed.
   4. **Lost words**: the vault can't be opened. `moolakata-connector reset` on its host asks
      for it to be confirmed, deletes the vault, makes new words (shown as at `init`, three
      typed back), and unpairs: it tells MoolaKata first, with the status key, which needs no
      words (S18.4.5), so MoolaKata ends the pairing as Unpair would; when MoolaKata can't be
      reached it says so, and an admin unpairs there. The next `pair` makes new keys, and every
      Connection's credentials are entered again (S18.7). **Reset** on its page does the same
      for a household that still has the words but wants new ones (some were seen): it asks
      for the words, then shows new ones as its welcome does. Without the words, reset is done
      on the host, whose access is the authority.
4. **Pairing with MoolaKata**, once, as two servers are linked (S11.1).
   1. An admin chooses **Settings › Connector › Pair** in MoolaKata, which shows a one-time
      **pairing code**: the address the connector reaches MoolaKata at (Settings › Connector's
      own, S16.18, or the public URL when it is empty; never the link address, which may lead
      to a proxy that passes only `/link/`), its link key's fingerprint, a one-time secret,
      and, when MoolaKata's certificate is its own rather than a public one, the fingerprint of
      the certificate's key, valid 24 hours, in the form of a link code (`mkp1.`,
      `docs/link-protocol.md` §4.1), of which MoolaKata keeps only the secret's hash.
   2. On the connector's page, **Pair** with the code and the words (S18.11.4), or on its host
      with the vault unlocked: `docker compose exec connector moolakata-connector pair
      <code>`. The connector makes its **action key** (Ed25519, for signing its calls), its
      **status key** (Ed25519, for saying it is locked) and its **sealing key** (X25519, for
      credentials sent to it, S18.7.1), files the action and sealing keys' private halves in
      the vault (so `pair` is refused while the vault is locked), introduces itself with the
      code in one call (`POST /connector/v1/pair`, signed by the action key: the code and the
      three public keys, the sealing key and the status key signed with the action key, the
      action key with the status key), and both sides show the connector's fingerprint, its
      action key's, for the admin to compare: the connector shows its own, worked out from the
      key itself, never one an answer names, and refuses an answer that names another. Before anything is sent, the connector
      checks that the key MoolaKata's `hello` gives hashes to the code's fingerprint, and keeps
      that key with the pairing; a failed `pair` leaves any earlier pairing as it was. **The
      pairing is not trusted until an admin confirms it** (Settings › Connector › **Confirm**,
      the password again): a pairing code is a 24-hour bearer secret, and whoever answers it
      first is paired. Until the confirmation, the connector's reports are taken (so its
      fingerprint is known), but it is handed no sealed credential, no file it posts is taken
      (refused `not-confirmed`, and kept for a later run), and no one can seal a sign-in for
      it; the connection dialog says so. Fingerprints that differ mean someone else answered
      the code: Unpair.

      ```
       admin                MoolaKata                        connector host          connector
        | Pair (password again) |                                  |                     |
        |---------------------->| code mkp1.{address, fingerprint, |                     |
        |<----------------------| secret}; keeps SHA-256(secret)   |                     |
        |  carries the code to the connector's host ..............>| unlock (the words)  |
        |                       |                                  |-------------------->| vault open
        |                       |                                  | pair <code>         |
        |                       |                                  |-------------------->|
        |                       |        GET /connector/v1/hello   |                     |
        |                       |<-----------------------------------------------------|
        |                       |  {fingerprint, key} -------------------------------->| SHA-256(key) = code's? else stop
        |                       |                                  |   makes status key (beside the vault)
        |                       |                                  |   makes action and sealing keys (private halves into the vault)
        |                       |   POST /pair {code, keys, each signed by the other}, signed by the action key
        |                       |<-----------------------------------------------------|
        |                       |  keeps the public keys; answer signed by the link key  |
        |                       |------------------------------------------------------>|
        |  both sides show the connector's fingerprint; the admin compares them         |
      ```
   3. **Every call it makes is signed** with its action key, or, for a report that it is
      locked and its `unpaired`, its status key, with a timestamp and a nonce, as link calls
      are (S11.1.3), at `/connector/v1/` on MoolaKata's address, and every
      answer is signed by MoolaKata's link key, so the connector knows it reached the server
      it paired with. The path carries the protocol's version; a call also names it in a
      header, and one MoolaKata doesn't speak is refused naming the versions it does, as
      links are (`docs/link-protocol.md` §5). `docs/connector-protocol.md` states the
      protocol in the link protocol's form. MoolaKata keeps only the public keys. One
      connector is paired with a server at a time: pairing another replaces it, as Unpair
      would (S18.4.4).
   4. **Unpair** (Settings › Connector) ends the paired connector and withdraws a pairing code
      still waiting, refuses its keys from then on, stops every Connection, and turns every
      account's sync off. MoolaKata answers the connector's next call with a signed
      `not-paired`, at which the connector forgets the pairing and deletes the credentials it
      held for that server and its action and sealing keys. A locked vault can't be changed:
      the connector leaves a mark beside it, and its next unlock deletes them.
      `moolakata-connector unpair` on its host does the same from the connector's side, telling
      MoolaKata (`unpaired`); on a locked connector it asks for the words to delete them at
      once, and without them leaves the mark. A MoolaKata restored from a backup older than the
      pairing knows neither the pairing nor its Connections, so it too answers `not-paired`,
      and the connector deletes what it held: those credentials were filed for Connections the
      restored server no longer has (operations §6).
   5. **Where the keys live, and why.** The status key sits beside the vault, not in it, so a
      locked connector can still report; it can only say *the paired connector is locked* (or
      *unpaired*), and MoolaKata answers it with nothing about a Connection, an owner or an
      account. The action key, which signs everything else (full reports with each
      Connection's state, its page's address and sign-in addresses, file posts, taking a box),
      and the sealing key's private half live **in** the vault: a locked connector has no use
      for them (it can't fetch), and a copy of the connector's volume without the words must
      neither act as the connector nor open the boxes sealed to it. So no report a copy could
      send points an admin at another page to type the words into. MoolaKata hands a sealed box
      only in the answer to an action-key report (S18.5), and pairing needs the vault unlocked
      to file the keys. Files fetched before a **Lock** wait in memory for the next unlock.
5. **Status and alerts.** Every 5 minutes, after each run, and every 15 seconds for up to 10
   minutes while a Connection waits for a sign-in (so an address pasted back is exchanged at
   once, S18.7.1), the connector reports, signed. Locked, with its status key, it says only
   that, and is answered with an acknowledgement. Unlocked, with its action key, it reports
   each Connection's state and last run (*ok, 14 new*; *needs a sign-in*; *failing: the institution refused the
   password*) with the institution accounts it found (name and last four digits, S18.6.1). The
   answer carries what waits for the connector: each live Connection with its settings and
   accounts, sealed credentials to collect, by Connection (S18.7.1), **only when the pairing
   is confirmed** (S18.4.2), and Connections removed (S18.6.4), whose credentials it
   then deletes. MoolaKata shows the report and alerts admins (S12.11):
   1. **the connector is locked**: unlock it on its page, which Settings › Connector links to
      (S18.11.1), or on its host;
   2. **the connector hasn't been heard from for 15 minutes**: it is stopped, down, or can't
      reach MoolaKata;
   3. **a Connection needs a sign-in or is failing**, to admins and to the owner of each
      account it keeps current;
   4. **the connector reports from a new address** (S18.2.4.4): the alert names the address
      known and the new one, and stays until an admin accepts the new address in Settings ›
      Connector (the password again) or unpairs, whichever address reports after it.

   Reports never carry a credential, an amount or an account number beyond its last four
   digits.
6. **Connections.** A **Connection** is one sign-in at one institution, kept by the
   connector: *Alice's Schwab login*, using the Schwab driver.
   1. **Owned by a user**, the one whose sign-in it is, who names it. MoolaKata holds its
      record (owner, driver, label, state, last run) and, after its first run, **the
      institution accounts the driver found**, by name and last four digits. Its credentials
      exist only in the connector's vault.
   2. **An account's sync**: an account's settings carry **Sync using MoolaKata Connector**,
      offered once a connector is paired. Turning it on asks which Connection (one of the
      owner's, or **New connection…**) and which of its institution accounts this account
      is. Only the account's owner turns it on; an account shared with write can't be.
   3. A Connection can serve several accounts, and a joint account another owner holds
      only once that owner turns its sync on for their own account.
   4. **Profile › Connections** lists a user's own, with their state and accounts, **Sign
      in again**, **Change credentials** and **Remove**; removing one turns its accounts'
      sync off and the connector deletes its credentials. The credentials dialog of an OFX
      Connection shows its server address, which its owner may change there when the
      institution moves its server: the new address is saved first, with the password again,
      and the credentials typed then are sealed for its host (S18.7.3). **Settings ›
      Connector** lists every Connection's state for admins and the host its credentials go
      to, never its credentials or its settings.
7. **Entering credentials**, chosen per Connection.
   1. **Sealed for the connector** (the usual way): the owner types the credentials in
      MoolaKata, with their password again (S13.7.2) and only once an admin confirmed the
      pairing (S18.4.2), and **the browser encrypts them to the connector's sealing key**
      before anything is sent (an X25519 sealed box, made with the browser's own WebCrypto,
      which current Chrome, Edge, Safari and Firefox provide; a browser without it is offered
      only the stricter way below). The browser first checks the sealing key's signature by the
      action key the admin confirmed (S18.4.2), and seals, with the credentials, the host the
      dialog shows the owner they go to (*Sealed for ofx.example.com only*: the OFX server's,
      from the address the dialog shows, or the driver's own) and the time; the connector refuses a box older than
      the credential it holds. MoolaKata keeps only the ciphertext, which it can't open, until
      the connector collects it on its next report, files it in its vault and confirms which
      box it took (by its time); MoolaKata then deletes that box. A sign-in through the
      institution's own page (OAuth, as Schwab's) works the same way: the connector reports the
      sign-in address, which MoolaKata takes only on the driver's own sign-in host and shows
      with that host; the owner opens it, and pastes back the address they land on, sealed the
      same way, which the connector checks against the random `state` it put in the sign-in
      address. **What this trusts**: the encryption runs in the code MoolaKata serves, so a
      compromised MoolaKata could serve altered code and capture credentials typed after the
      compromise. It can never open credentials sent before.

      ```
       owner's browser              MoolaKata                      connector (unlocked)
        | GET /ui/api/connector        |                                 |
        |----------------------------->| sealing public key, fingerprint |
        | seals {username, password,   |                                 |
        | host, time} in WebCrypto     |                                 |
        | POST …/connections/{id}/credential {box}                       |
        |----------------------------->| stores the box; cannot open it  |
        |                              |     POST /report {locked: false}|
        |                              |<--------------------------------|
        |                              | answer: settings, accounts, box |
        |                              |-------------------------------->| opens the box with the
        |                              |                                 | sealing key from the vault;
        |                              |                                 | files the credentials, bound
        |                              |                                 | to the host sealed with them
        |                              |   POST …/credential/taken       |
        |                              |<--------------------------------|
        |                              | deletes the box                 |
      ```
   2. **Typed on the connector's host** (the stricter way): MoolaKata shows the command,
      `docker compose exec connector moolakata-connector connect <connection id>`, and an admin
      runs it and types the credentials there. MoolaKata never handles them at all; the admin
      does. The connector files them bound as below, so it must already know the Connection
      from a report; `connect` reports first when it doesn't, and shows the host the
      credentials will go to, and files them only once the admin confirms it.
   3. **Bound to one host.** A credential is sent only to the host it was filed for. When the
      connector files a credential, it records with it the host the owner's browser sealed with
      it, or the admin confirmed at `connect` (an OFX server's address; nothing for a driver
      whose hosts are fixed, like Schwab's), and refuses it when that host is not the one the
      Connection's settings name. Before every run it compares that bound host with what the
      settings name now: if they differ, it sends nothing, drops the credential, and reports
      the Connection as *needs a sign-in: the server address changed from A to B*, so the owner
      enters the credentials again, knowingly, for the new host. The owner's own way to change
      the address is the credentials dialog (S18.6.4): the address is saved and the new
      credentials sealed for its host in one step, and the connector, taking both from one
      report's answer, files them bound to the new host before its next run. A compromised MoolaKata, or
      anyone who can change a Connection's settings, can therefore never redirect a stored
      password to a host of their choosing.

      ```
       connector, before each run of an OFX Connection
        |  bound host (in the vault) == host in settings.url ?
        |     yes -> POST the OFX request to that host, and only there
        |     no  -> send nothing; delete the credential; report needs-sign-in
      ```
8. **What drivers send**: files MoolaKata already imports, posted for one account through the
   same import as an upload (S1.3): OFX or QFX, CSV with the account's saved mapping, or a PDF
   statement. Imports are idempotent, so a repeated post adds nothing. A post counts against
   the upload limit of the Connection's owner (S13.7.5.3); refused for the limit, the connector
   keeps the file and posts it on a later run, so a backlog (a long history fetched at once)
   arrives over a few hours rather than failing. Each file is posted on its own: one MoolaKata
   can't take now (the limit, the pairing's confirmation, MoolaKata locked or busy with
   uploads, out of reach, or an answer that isn't signed) waits for a later round; one it
   refuses for any other reason (a file it can't read, one over Settings › Imports' size,
   S16.8) is dropped, and its Connection shows the refusal; either way the next file and the
   next Connection are posted, and the report after the run is sent. Files waiting are held in
   memory, the newest ten per Connection (the Connection names any older one let go): after a
   restart the drivers fetch again, and the import's idempotence drops what arrived before. A PDF is kept without reading (S1.3.3.6), or,
   where MoolaKata reads that kind, waits in the account's inbox for its owner to check:
   nothing read from a PDF is saved unchecked. Every post is recorded in Activity as *by
   MoolaKata Connector, Alice's Schwab login*.
9. **The first drivers**, for the average cases. A driver pushes what it fetches from its
   institution; an institution with nothing to fetch from, such as UMB, is kept current by
   files its owner downloads and uploads (S1.3), since the downloads land on the owner's
   desktop, not on the server (a watched folder was weighed and turned down, [rejected
   ideas](rejected-ideas.md)).
   1. **OFX Direct Connect**: for institutions that still run an OFX server, fetching
      transactions and balances with the sign-in's username and password, bound to the server
      address the Connection named when they were filed (S18.7.3). Once a day, over `https`
      only, as an OFX 1.0.2 client, it asks for the last 45 days (the Connection's `days`), or
      90 while no account matches the Connection's account number; the server's sign-on codes
      15500 to 15503 mean *needs a sign-in*. Every value in the request is written as SGML
      wants it (`&`, `<` and `>` escaped) in Windows-1252, its header's character set; a
      credential or setting holding a character that set can't carry is never altered to fit:
      nothing is sent, and the Connection is *failing* with the reason. A server that answers
      with several accounts' statements has them kept to the Connection's own (by its
      account number's last four digits), since the import takes one account a file. Code
      15000 (a new password wanted) and 15502 (the sign-in locked) also mean *needs a
      sign-in*, with the owner told what the institution wants; 3000 (a second factor) is
      *failing*: OFX Direct Connect can't give one, and the owner uploads the institution's
      files instead; a statement refused with a code of its own is *failing* with that code.
   2. **Schwab**: Schwab's official Trader API, for positions, transactions and balances,
      posted as OFX, an option written whole (S3):
      1. **Trades**: a share's, an ETF's, a mutual fund's (a money market fund's among them),
         a bond's and an option's, each as its kind; an option's opening or closing from what
         Schwab says of the trade (`positionEffect`), as buy or sell to open or to close,
         with its contracts' shares (Schwab's multiplier, else 100), and a share's short sale
         and cover the same way (G28); an order of several legs (a spread, a roll) as one
         trade per leg, its fees with the first.
      2. **An option's end**: a `RECEIVE_AND_DELIVER` removing an option as an expiry,
         assignment or exercise by what it says; the shares that come with an assignment or
         exercise, a trade or a delivery with cash, as the trade the import pairs with it
         (S3.4); shares moved in or out with no cash as transfers.
      3. **Cash and income**: ACH, wires, journals and MoneyLink transfers; dividends and a
         bond's interest on the security; the bank sweep's interest; margin interest as a
         fee. A memorandum that moves nothing is written as nothing.
      4. **Positions** by kind (shares, funds, bonds, options, a short one below zero), with
         Schwab's market value, and the account's cash.
      5. **What it can't write whole** (an option trade that says neither opening nor
         closing, an option removed for a reason not given, a kind with no OFX form, such as a
         future) is left out of the file and named in the Connection's message, never
         dropped unsaid; the statement's cash check then shows what is missing. Its sign-in lasts seven days, so the Connection asks for a sign-in every
      week (S18.5.3). Once a day it asks for the last 45 days. The app registered at Schwab
      must name `https://127.0.0.1` as its callback, the address the owner lands on and pastes
      back (S18.7.1); an access token is used until a minute before it runs out. The access
      token lasts about 30 minutes and the refresh token about seven days; how long the code in
      the landing address lasts isn't published, so it is exchanged within seconds (S18.5).
      Source: [schwab-py's authentication
      notes](https://schwab-py.readthedocs.io/en/latest/auth.html), kept in
      `docs/external/schwab-py-auth.rst`.
10. **Packaging**: `install/compose.yaml` carries the `connector` service, from the
    `moolakata-connector` image of the same version, `restart: unless-stopped`, read only, all
    capabilities dropped, its page's port (37374) its only published one, and its own volume.
    On TrueNAS it is an app of its own: `install/compose.connector-truenas.yaml` for
    **Install via YAML**, and the MoolaKata Connector app for TrueNAS's catalog
    (S17.8.3.1).
    `docs/operations.md` covers installing it, its words, unlocking after a restart, pairing,
    running it on another machine instead, and unpairing a lost one.
11. **Its page.** The connector serves one small page of its own, so a household makes its
    vault, gives its words after a restart and pairs it from a browser, as MoolaKata's own
    welcome and locked screen work (S15.4), while MoolaKata never sees the words: the page is
    the connector's, on its own port, and MoolaKata only links to it.
    1. **Where**: HTTPS on port 37374 (`MOOLAKATA_CONNECTOR_PORT`), with a certificate of its
       own, made at its first start, kept in `tls/` in its volume and good for 825 days,
       naming `localhost` and each name in `MOOLAKATA_CONNECTOR_NAMES` (the addresses
       browsers use, separated by commas); or the certificate and key named by
       `MOOLAKATA_CONNECTOR_TLS_CERT` and `MOOLAKATA_CONNECTOR_TLS_KEY`. Its address, the
       first of those names with the port, goes in every report (`page`,
       `docs/connector-protocol.md`), and Settings › Connector links to it.
    2. **The welcome**: with no vault, the page says **Welcome to MoolaKata Connector** and
       offers **Show my words**: a new key on every visit, held in memory only (an hour each,
       20 at most), shown as its 12 words with the vault's fingerprint; three of them typed
       back make the vault, unlocked, and drop every other key on offer. Whoever reaches a
       connector with no vault first can make it: one whose page asks for words nobody wrote
       down is stopped, its volume emptied, and started again.
    3. **Its status, for anyone who opens it**: locked or unlocked, the MoolaKata address it
       is paired with (or not paired) and the connector's fingerprint, whether the pairing is
       confirmed, its last report and whether MoolaKata answered, how many Connections are
       working and how many need attention, and its version. Never an institution, a
       Connection's name, an account or a credential.
    4. **Its actions, each a form that takes the words**: **Unlock**; **Lock**; **Pair**, with
       MoolaKata's pairing code (the words unlock a locked vault first), after which it shows
       the connector's fingerprint to compare with Settings › Connector, where an admin
       confirms it (S18.4.2); **Unpair**, which forgets the pairing and the credentials kept
       for that server, as MoolaKata's Unpair makes it do (S18.4.4); and **Reset**, which
       also asks for RESET to be typed (S18.3.4). The page never takes or shows a
       credential: those are sealed in MoolaKata (S18.7.1) or typed on the host (S18.7.2).
    5. **How it is built**: forms the connector renders itself, with no JavaScript, from the
       standard library's HTTP server and `ssl` and the `cryptography` the core has
       (S18.1.2). Its content policy allows its own stylesheet and nothing else; forms post
       only to itself, and one from another origin is refused; no answer is cached or framed;
       a form's body is at most 16 KB. Its stylesheet uses MoolaKata's colour and type tokens,
       light and dark as the browser prefers, and a test fails when the two differ, so they
       read as one product.
