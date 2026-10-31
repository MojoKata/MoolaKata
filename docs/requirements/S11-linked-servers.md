# S11. Linked servers

Two households, each with its own MoolaKata on its own LAN, share read-only views with each
other: a parent and an adult child, partners who keep separate servers, or a client and their
preparer.

1. **A link joins two servers**, made by admins on both sides:
   1. Admin A creates an **invitation** on server A: a one-time **link code** (valid 24 hours,
      `mkl1.…`) that holds A's link address, the fingerprint of A's link key, a one-time
      secret, of which A keeps only a hash, and, when A's certificate is its own rather than a
      public one, the fingerprint of the certificate's key. **Withdraw** ends an invitation
      sooner.
   2. Admin B enters the code on server B, which connects to A, checks A's key against the
      fingerprint, and sends B's own address and key, signed with it, and nothing else: no user
      list crosses before A's admin approves. A's admin sees the request with B's fingerprint,
      compares it with B's admin, and approves or rejects it. B's link waits for the approval,
      which reaches it at once or at its next exchange.
   3. Each server then holds the other's **Ed25519 public key**. Every call between them is
      signed with the sender's key over the method, path, body hash, a timestamp and a nonce,
      and names its body's hash in a header, so all of it is checked before a byte of the body
      is read. The receiver refuses a bad signature, a timestamp more than 60 seconds off when
      the call arrives, and a nonce it has seen; a body that then takes minutes to arrive (a
      large receipt over a slow line) is no clock problem, and an answer's time is held to
      when its headers arrived the same way. A refusal for the clock is named as such on the link, since the fix is NTP
      on one host, not the network (S12.11.1.1). The code's one-time secret crosses once, in
      the join; what makes the link is the key each side records and the fingerprint the admins
      compare, and no secret is shared after that. The connection itself is TLS that each side
      verifies: a public certificate against the system's roots, a certificate of the server's
      own against the fingerprint its link code carried; a server whose certificate's key
      changes announces the new one to its peers, signed with its link key, before its next
      exchange, and a key a peer wasn't told of waits for its admin to accept it. A signed answer names the caller and the request it answers, so it can't be replayed
      to another. The protocol is specified in `docs/link-protocol.md`.
2. **Reachability**: links are HTTPS between the servers' **link addresses**: the path
   `/link/` on the server's own address, with no port or address of its own, which a reverse
   proxy can expose apart from `/ui` (`docs/operations.md` shows how). Two LANs need one of:
   1. one side reachable from the other (a forwarded port or a reverse proxy). That side
      **serves** and the other **pulls**;
   2. both on one overlay network, such as **Tailscale**, **WireGuard** or ZeroTier. This is
      the recommended setup and needs no open port;
   3. *(not now)* a relay. MoolaKata does not run one ([out of scope](out-of-scope.md)).

   A link works when **either** side can reach the other: each exchange carries both
   directions, receipts included (the side that calls sends its own receipts' bytes in it), so
   whichever side can reach the other makes it. A link address is `https`, with no query or
   fragment, and never a loopback, link-local or cloud metadata address, whoever names it
   (S13.5). Each server's **link address** is set in Settings › Linked servers (its public URL
   when not set), and the link listener answers under `/link/`.
3. **What a link carries**: only what a user on one server has shared with named people on the
   other (S10.3.3), always **read**, never write. The shares travel with the data, and the
   receiving server shows each item only to the people it names. The receiving admin does not
   choose who sees what. They see each share only as its kind, its owner's display name, who it
   names and the date it was shared: its name and figures stay inside the encrypted linked copy
   (S11.9). A linked share cannot be re-shared on the other side, not even with another link.
   Each server also sends the other its **list of active users** (display name, username,
   email, sex and stable id) and its **household name and avatar** (S16.1), at every exchange
   from the first one after the link is approved. The receiving server keeps each remote user
   as a record, updated by its id: a new user is added, a changed name, username, email or
   active flag is updated in place, and a user no longer on the list is soft-deleted, and
   restored if they return. When the link ends, its users are soft-deleted. Shares that name a
   remote user keep pointing at the same record throughout. Each remote user is a person here
   too, for gifts (S10.10.1).
   1. **Each item travels as its screens show it, worked out at the source.** A budget's
      actuals, a giving plan's pace and a tax book's panels are computed from accounts that may
      not be shared themselves. The owner's server sends the figures and the entries that make
      them up (a donation's date, organisation and amount; a Form 8949 row), never the accounts
      behind them: an entry names its account, by name or id, only when that account is shared
      with the same people, and otherwise says *an account not shared*. An account shared as
      well arrives as its own item. The receiving server never recomputes; it shows what
      arrived, with its age.
4. **How data moves**: the receiving server **pulls a snapshot** of each linked share on a
   schedule (hourly by default, and on demand). The snapshot holds each shared item as S11.3.1
   says (for an account: balances, holdings, positions, transactions and series), and receipts
   and documents when the share includes them. It is versioned, and only changes travel. Each
   change is **sealed by the source to the receiving copy's public key** (S11.9.2.2), which the
   receiver sends with each exchange, so it crosses unreadable to anyone but that copy,
   whatever the transport; beside it, signed, travels what the receiving server keeps while the
   copy is locked (S11.9.1). A **first full snapshot**, or a large change, travels **oldest to
   newest**, so the copy fills from its earliest records and is usable, up to a date, while the
   rest arrives: a change over about **4 MB** comes in parts, each whole records up to a date,
   which the receiver fetches one after another and applies as each arrives. Each change, and
   each part, is **signed by the source's link key**, so the receiver can check it again when
   it applies it later. The receiver keeps its last copy in the link's encrypted **linked
   copy** (S11.9) and shows its age (*as of 2 hours ago*). Pulls run whether or not anyone has
   unlocked the copy. A receipt that doesn't come with its change never holds the change back:
   the change is applied without it, the receipt shows as *not arrived*, and it is asked for
   again at each exchange (`docs/link-protocol.md` §4.3.5). Whatever fails in an exchange is
   recorded on the link, and alerts as unreachable pulls do (S12.11.1). When the source is
   unreachable, the copy stays, marked stale. When the
   share or the link is removed, the other side learns at its next exchange and deletes the
   copy, or the receiving admin does at once. A Pause (S11.7.2) stops data, never a removal or
   an end, which still cross.
5. **What crosses a link, and what never does**:
   1. **Receipts** cross only when the owner ticks **Include receipts** on the share to that
      link (off by default). Receipts are large and personal, so sending them is a choice made
      per share. They then travel with their dates, amounts, payees and the text read from them
      (S9.8), so the receiving side never runs OCR on them. Without the tick, the other side
      sees only how many receipts a transaction has, and a gift's documents (their file names,
      notes and links) stay home too. A tax book's document files come later ([later
      work](later.md), L6).
   2. **Never**: secrets, categorisation rules, groups, gifts for a person who is a user of
      that server (S7.8.5), the accounts behind a shared item's figures unless they are
      shared too, and anything not shared with someone on that server. Of the source's
      users, only the active-user list (S11.3) crosses. Prices travel only as values already computed, with their
      `as_of` (S4.9).
6. **Ending a link**: either admin ends it on their own side. The other side learns at its next
   call and deletes its copies. Only the peer's signed `link-ended` ends a link there: a
   `not-linked` answer (a peer restored from an older backup, say) marks the link broken and
   alerts admins, who end it or link again. Ending a link deletes nothing on the source.
   **Linking again** is a new link code and join, from either side: the old link with that
   server, ended or broken, makes way for the new one (a broken one is ended first, its copy
   deleted), and the new link pulls everything afresh. A link that is neither is the one the
   two servers have, and a second join with it is refused. The states and what moves a link
   between them are `docs/link-protocol.md` §4.6.
7. **Settings › Linked servers** lists each link: the peer's name and address, its
   fingerprint, state (invited, requested, pending, active, paused until…, unreachable
   since…, broken, ended), the last pull, and
   what flows each way, with *Pull now*, *Pause* and *End link*.
   1. **Progress**: while a pull is under way, how far it has come both in time and in
      quantity: *Up to July 2022 (47 MB of 2 GB)*, the date being the newest record applied so
      far and the sizes what has arrived of what the source said it would send.
   2. **Pause** stops pulling, and answering the peer's pulls, for a **duration** the admin
      types (S12.13), `1d` by default, after which the link resumes on its own; *Resume now*
      ends it early. A paused link shows when it resumes, and isn't alerted as unreachable.
   3. **The linked copy**: the changes waiting to be applied, when its access key was made
      and by whom, and whether it is unlocked (by whom, and when it will lock), with *Create
      the access key* (S11.9.2), *Lock now* and *Reset copy* (S11.9.8). The section also
      sets **Release linked keys after** (S11.9.4), one hour unused by default.
8. **Audit**: each pull is recorded on both sides (who, when, which shares, how much changed),
   and each pause and resume on the side that made it. The receiving side records who viewed
   linked data, and every unlock (who), failed unlock, release (unused, Lock now or restart),
   access key made, and reset of a linked copy.
9. **Linked copies: kept apart and encrypted**. What a link brings in is
   someone else's money. A copy of it should not sit readable on this server's disk or in
   its backups, or be readable by malware on this server while nobody is using it. Its
   access key protects it at rest. Who sees what in it is decided by the owner's shares,
   not by the key.
   1. **The linked copy.** Each link's received shares live in one folder under the data
      directory, `links/<random name>/`, never in the main database:

      ```
      links/<random name>/        named at random, never by the link's id (schema.md §2.5)
        shared.db                 SQLCipher: accounts, holdings, positions, transactions,
                                  series, budgets, gift plans and gifts, giving plans, tax
                                  books, receipt records, the text read from receipts,
                                  thumbnails, and what has been applied
        receipts/<random-id>.mkr  one encrypted file per receipt (S11.9.6)
        inbox/<sequence>.mks      sealed changes waiting to be applied (S11.9.5)
      ```

      The main database holds only what is needed while the copy is locked: the link, the
      shared items' ids, kinds, owner's display name and the people they name (not their
      names or values), the household's name and avatar, the copy's public key, the copy's
      folder name, and the inbox's length and newest `as_of`. File and folder names are
      random, so the folder shows no names, payees or dates, and not even when the link was
      made.
   2. **The access key.** Each linked copy has a random 128-bit **copy key**, shown once as
      **12 words** from the BIP39 English word list (the last word carries a checksum). The
      words are the copy's **access key**.
      1. **Made by the receiving admin**, when the link's first share arrives: Settings ›
         Linked servers › **Create the access key**. The server makes the copy key, shows the
         words once, and asks the admin to confirm they have saved them, typically in the
         household's password manager, where the people the shares name can reach them. The
         receiving admin is trusted with the copy: holding the words, they could open it, as
         anyone with the words could (S11.9.10).
         Pulls into the copy begin then.
      2. Separate keys are derived from the copy key with HKDF-SHA256, each under its own
         label: the **database key**, which SQLCipher uses as its raw key (`PRAGMA key =
         "x'…'"`), and the **copy's private key** (X25519), whose public half is stored in
         the main database.
      3. The copy key is **never stored**, in any form. The server holds it only in memory
         while the copy is unlocked. There is **no master-key slot**: the master key (S15)
         cannot open a linked copy.
   3. **Unlocking.** The copy is unlocked for the whole server, not per user.
      1. When someone the copy's shares name opens its window (S12.10) while it is locked,
         the server asks them for the 12 words. It checks the checksum and that the words
         derive the copy's stored public key, then holds the copy key in memory. Nothing
         about it reaches the browser.
      2. While it is unlocked, **the owner's shares alone decide who sees what** (S11.3):
         each user sees only the items that name them. Anyone named can open the window
         without the words until the copy locks again. Knowing the words without a share
         opens nothing.
      3. **Wrong words**: five in a row make that user wait 15 minutes, and the copy
         accepts at most 20 attempts an hour from all users together.
   4. **Locking.**
      1. The key is **released after it goes unused** for the time set in Settings › Linked
         servers (S11.7), one hour by default. *Used* means a read made for a person: a
         screen or export in the linked household's window. Background work, such as
         applying a pull, does not count.
      2. A sweeper task checks every minute and locks each copy past its time. Locking closes
         the copy's SQLCipher connections, which wipes SQLCipher's own copy of the key, and
         overwrites the server's copy of the key bytes, which each new connection reads, so
         none opens after the release. Python cannot promise that no other copy lingers in
         memory until it is reclaimed, so this is a release, overwritten where possible, not a
         guaranteed erasure.
      3. It also locks at **Lock now** (in the linked household's window, and in Settings ›
         Linked servers for admins), which anyone the copy shares with can press, and when
         the server restarts.
      4. While a copy is locked, its window asks for the words. Nothing from it appears
         anywhere else at any time (S12.10).
      5. The window's header says who unlocked it and when it will lock: *unlocked by Alice
         at 14:05 · locks after an hour unused*. Every unlock, failure and release is
         recorded (S11.8).
   5. **Staying in sync while locked.** Pulls (S11.4) never wait for an unlock.
      1. Each change arrives **sealed** by the source to the copy's public key (S11.4) and is
         written to `inbox/` as it came, as the next numbered file. Sealing needs only the
         public key, so the receiving server never holds a change in the clear.
      2. Receipts arrive sealed the same way and are written straight into `receipts/`. They
         never wait in the inbox; one that arrives after its change (S11.4) reaches the copy
         as soon as it is open.
      3. The inbox is **applied** in order, in one transaction, as soon as the copy is
         unlocked. Each change's signature is checked first, and its sequence number, sealed
         inside it, must follow the last one applied, so an older change put back is refused; a
         change that fails (its signature, its sequence or its shape) is set aside and
         reported, and the copy asks the source for everything. Applied files are deleted.
         While a copy stays unlocked, new pulls are applied as they arrive.
      4. If the inbox grows past 1,000 changes or 500 MB, the server discards it and asks the
         source for a **full snapshot**, sealed the same way.
      5. A locked copy still shows its sync state from the main database: *synced 5 minutes
         ago · 12 changes waiting · locked*.
   6. **Encrypted files** (receipts and inbox changes) use one streaming format, so a 25 MB
      receipt is never held whole in memory.
      1. **Header**: magic and version (`MKR1`), a one-time X25519 public key, a random 32-byte
         salt, a 7-byte nonce prefix, and the chunk size (64 KiB).
      2. **Key**: HKDF-SHA256 over the X25519 exchange between the one-time key and the copy's
         key, with the salt, under the label `moolakata link receipt` or `moolakata link
         change`. Every file therefore has its own key.
      3. **Chunks**: each 64 KiB chunk is sealed with AES-256-GCM. Its nonce is the prefix, a
         4-byte chunk counter and a last-chunk flag, so a chunk cannot be reordered, dropped or
         cut off unnoticed. The associated data names the link, the receipt or change, and the
         chunk's number, so a file renamed or copied onto another receipt fails to open.
      4. `shared.db` records each receipt's file name, length and plaintext SHA-256, which came
         signed from the source. The hash is checked as the file is shown, before its last part
         is sent, so an older copy swapped in is caught.
      5. **Showing a receipt** streams it through decryption into the response, with the type
         checked from its bytes when it arrived (S9.4) and the headers of S13.7.7, as a local
         receipt is. **Plaintext never touches the disk**: there are no temporary files, and
         thumbnails are kept in `shared.db`.
      6. **Writing**: each file is written under a temporary name, synced to disk and renamed
         before its row is committed. A sweeper removes files that no row names, left behind
         after a crash.
      7. This is the AES-GCM-HKDF streaming construction (the one Tink uses), built on the
         `cryptography` library. It needs no further dependency.
   7. **Who can open what.** The owner's shares decide what each user sees (S11.3), and the
      words decide whether the copy can be opened at all. A share removed at the source
      reaches the copy at its next exchange (S11.4), which then hides the item from that user,
      with no re-keying. New words are needed only if they reach someone who could also read
      this server's disk (S11.9.10).
   8. **Lost words.** **Reset copy** (Settings › Linked servers, admins) deletes the folder,
      makes a new copy key with new words, and pulls everything again from the source.
      Nothing is lost: the linked copy is only a copy, and the source keeps the data. The
      master key has a recovery phrase because it is the only way into this server's own
      data (S15.6); a copy key does not need one.
   9. **Backups** leave linked copies out (S14.6); the host's own backup of the data
      directory carries them, encrypted under their access keys. After a restore, which sets
      them aside, the admin makes a new access key for each link, and each copy is pulled in
      full from its source.
   10. **What this protects against, and what it does not.** A stolen disk, a backup that
       leaves the house, and root reading files while the copy is locked reveal nothing of a
       linked copy beyond its size, its number of receipts and when changes arrived, unless
       they also have the words, which the receiving admin makes and holds (S11.9.2.1, S10.2).
       It does **not** protect against root, or malware running as the server, while the copy
       is unlocked: the key is then in the server's memory, and no design changes that.
       Releasing the key after an hour unused keeps that window short. Nor does it protect
       against someone with the words reading the copy's files outside the app. The source's
       owner is trusting the people they name and the household that keeps the words.
   11. **The engine**: SQLCipher through the `sqlcipher3` wheel, which bundles SQLCipher,
       opened as a second SQLAlchemy engine for each unlocked copy. Each copy keeps its own
       numbered history of schema revisions (as Alembic does for the main database, S14.1),
       applied in order when it is unlocked.
