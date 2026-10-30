# S15. Encryption and the master key

This section is for the admin who installs and runs the server. It explains what MoolaKata
encrypts and how, how to back up and protect the master key with its recovery phrase, and
what key rotation does.

**Terms used here.**

| Term | What it is |
|---|---|
| **master key** | 128 random bits, made once at install and **never stored anywhere**: an admin enters it after every start. The one key an admin ever handles. |
| **recovery phrase** | the master key written as 12 words: the only form it ever takes outside the server's memory (S15.4, S15.6). |
| **locked** | the server's state from start until the phrase is entered: serving, but holding no key (S15.4.3). |
| **data key** | 256 random bits that everything is encrypted under, stored only **wrapped** (encrypted) under the master key. |
| **keyring** | the file in the data directory that holds the wrapped data key, so it travels with every backup. |
| **database key, receipts key, secrets key** | the keys derived from the data key, one for each kind of thing (S15.3.2). |
| **fingerprint** | a short name for a master key that reveals nothing about it, `mk-3f9a…c21e` (S15.3.5). |
| **copy** | anything that holds the data as it was at some moment. **On this host**, where MoolaKata can see and act on it: a backup in the backup directory, a `pre-upgrade/` copy, a `before-restore-*/` folder, each carrying its own keyring. **Elsewhere**, where only the admin can: the host's snapshots, replicas and backups, a VM image, a disk. A copy opens with the keys of its day, for as long as it exists. |
| **rotation** | a new master key and phrase, and with them a new data key: the keyring is wrapped under the new key and everything is re-encrypted (S15.7.1). |
| **re-encryption** | a new data key; the database, the receipt files and every secret are encrypted again under it, while the server isn't serving. A rotation brings one; on its own it leaves the master key unchanged (S15.7.2). |

**How the keys fit together.** The phrase, entered at each start, unwraps one data key in the
data directory, and the data key derives a key for each kind of thing:

```
 in the admin's keeping (never on the server)   in the data directory (in every backup and copy)

 +---------------------+    unwraps    +----------------+  derives   +---------------+  opens  +-------------+
 | recovery phrase     | ------------> | data key       | ---------> | database key  | ------> | database    |
 | typed at each start |    keyring    | (kept wrapped) |            +---------------+         +-------------+
 +---------------------+               +----------------+            | receipts key  | ------> | receipt     |
                                                                     +---------------+         | files       |
   knowing this                                                      | secrets key   | ------> | each secret |
   + any copy of that = everything in that copy                      +---------------+         +-------------+
```

Nothing on the right opens without the phrase, and the phrase opens nothing without a copy of
the data directory or a backup. No key is on the host, so a stolen disk, a snapshot or a
replica holds only the right-hand side, and the whole host can be backed up as it is.

1. **What is encrypted, and what is not.**
   1. **The database**: the whole main database, with SQLCipher, including the full text read
      from receipts and the thumbnails.
   2. **The receipt files**: each in its own encrypted file (S9.2).
   3. **Secrets, each on its own as well**: every *secret* the server holds so it can act for
      its users: price-source API keys, the bitcoin node's credentials, the SMTP password,
      this server's private link key (S11.1), and each user's two-step seed, a seed still
      being set up included (S14.4). A credential sealed for the connector (S18.7.1) sits in
      the database as a box only the connector opens. The Electrum server's certificate
      fingerprint (S1.6.2.4) is not a secret, but its integrity matters, and the encrypted
      database gives it that.
   4. **Backups**, which are copies of the encrypted database with its keyring (S14.6); the
      receipt files are in the host's own backup of the data directory, encrypted as they
      are.
   5. **Encrypted under their own access keys, not the master key**: everything a link
      brings in, in its linked copy (S11.9). The master key cannot open it, so neither losing
      nor rotating the master key touches it.
   6. **Hashed, never encrypted**: passwords (argon2id) and session, invitation, reset and
      confirmation tokens (SHA-256 of a random value). They never need to be read back, so
      there is no key that could reveal them.
   7. **Not encrypted**: the configuration file; the logs, which must never hold amounts, names
      or secrets; the `tls/` pair in the data directory in `tls` mode (S13.3), which is for
      testing: being plain, it protects the listener, and a phrase typed through it, only from
      those who hold no copy of the data directory; and the **mail folder**, where emails are
      written while SMTP is not set up (S16.2): each holds a link that works once, an
      invitation's for a week and the others' for a day at most, so each file is removed once
      its link has expired. Emails waiting to go out through SMTP are queued in the database,
      which is encrypted.
2. **No external key service, and no key file.** MoolaKata keeps no master key at all: the
   phrase is entered after every start and held in memory only while it is used. HashiCorp
   Vault, cloud KMSs (AWS, GCP, Azure), HSMs and TPM sealing are **not supported**: on a
   household server, an external service adds a dependency that must be running, backed up
   and secured itself. A key file on the host was weighed and turned down too
   ([rejected ideas](rejected-ideas.md)): it is the one thing that must be kept out of
   every snapshot and backup of the host, and a phrase typed at each start needs no such
   care.
3. **How it works: three levels of keys.**
   1. **The master key**: 128 random bits made once at install and never stored. It exists
      as its **recovery phrase**, the same 128 bits written as 12 words from the BIP39
      English word list, the last word carrying a checksum, in the admin's keeping; and in
      the server's memory only while it unwraps the data key at an unlock, or wraps one at a
      rotation or re-encryption (S15.4). MoolaKata uses the words only as a way to write the
      key down. It never applies BIP39's wallet derivation to them. The master key encrypts
      one thing: the data key. It is never stored on the host or in the database, never
      written to a log, never sent over the network but to the server itself (at the unlock,
      **Verify key**, **Remove** and **Rotate**, S16.13), never shown in the UI but when it is
      made (the welcome, **Rotate**), and never in a backup.
   2. **The data key**: 256 random bits, made at install, stored only **wrapped**
      (AES-256-GCM) under a key derived from the master key with HKDF-SHA256 (label
      `moolakata master`). The wrapped data key sits in the data directory (`keyring`), so it
      travels with every backup. From the data key, HKDF-SHA256 derives, each under its own
      label:
      1. the **database key**, which SQLCipher uses as its raw key;
      2. the **receipts key**, an X25519 key pair: receipt files use the streaming format of
         S11.9.6 with this key in place of a linked copy's key;
      3. the **secrets key**, which wraps the secrets' own data keys.
   3. **Secret data keys**: each secret gets its own random 256-bit data key when it is
      saved. The server encrypts the value with **AES-256-GCM** under it, using a random
      96-bit nonce. The **associated data** names where the secret belongs: record type, the
      record's stable id, and field. The secret's data key is then wrapped under the secrets
      key. The row stores the ciphertext, its nonce and the wrapped key.
   4. **Using a secret**: when a task needs it (a price refresh, a bitcoin wallet read, an
      email, a two-step code checked), the server unwraps its data key, decrypts the value,
      uses it for that call and discards it; the link key, which signs every link and
      connector answer, is decrypted for each. GCM authenticates every step, so a tampered
      ciphertext, a wrong key, or a ciphertext copied onto another record or field fails to
      decrypt instead of producing a wrong value. Secrets are encrypted on their own as well
      as inside the database, so that a database opened for maintenance (S14.7) shows no
      secret in the clear. This is hygiene, not a boundary: the database key and the secrets
      key both derive from the data key, so whoever can open the database can open every
      secret with a few more lines; what the layer stops is a mistake, a query or an export
      that prints a key by accident.
   5. **The master key id** is the first 16 hex digits of `SHA-256("moolakata key id" ‖ key)`.
      It identifies a key without revealing it. Its short form (`mk-3f9a…c21e`) is the
      **fingerprint** shown in Settings, on the recovery sheet and in the commands below. The
      wrapped data key records which master key wrapped it, and names the data key by an id
      made the same way (`SHA-256("moolakata data key id" ‖ data key)`), so the server knows
      which copies hold the data key it has without unwrapping them.
   6. **Why three levels**: rotating the master key re-wraps one 32-byte data key and nothing
      else; the database and the files never need re-encrypting for it; the phrase need not
      stay in memory (S15.4.3); and each secret still stands or falls on its own, with
      associated data that keeps a ciphertext on the record and field it was made for, so a
      copy pasted elsewhere, by a bug or a hand, fails rather than decrypts.
   7. **What a stolen copy gives away**: a copy of the data directory or a backup **without
      the master key** (the recovery phrase) reveals nothing but sizes and dates. With the
      phrase, it reveals everything in that copy. No key is on the host's disk, so a stolen
      disk, a snapshot or a replica is such a copy and nothing more. An attacker who has root
      on the running, unlocked server can read the data key and the database, and no design
      changes that. This is why S15.8 treats a leaked phrase as a leaked copy: every copy
      made under a key opens with that key for as long as the copy exists.
4. **Entering the phrase: the locked start.**
   1. **The server starts locked.** It holds no key until an admin enters the recovery phrase.
      (With no keyring yet, it starts **uninitialised** and welcomes its first admin, S15.4.4.)
      Locked, it serves only what unlocking needs: `/healthz` answers 503 `locked`, `/ui` shows
      the locked screen (S12.14), and every other path answers 503 (S13.6). Nothing runs: no
      prices, no backups, no link exchanges, and the connector's reports are refused until the
      unlock. Every restart locks it again, and nothing unlocks it but a person: an automatic
      unlock from a file or a script was weighed and turned down ([rejected
      ideas](rejected-ideas.md)). A re-encryption that waits for the unlock (S15.7.2) runs
      then, before the server serves.
   2. **Two ways to enter it**, either of which an admin uses: the locked screen, in a desktop
      browser; or `moolakata keys unlock` on the host, run inside the server's container, which
      hands the phrase to the server over its Unix socket (`/run/moolakata/sock`, in a
      directory only the server's account can open, S13.6), never over the network. The phrase
      is the authentication, since no user can be checked before the database opens: a wrong
      phrase is refused, wrong phrases count toward the sign-in lockout (S13.7.5.1), and every
      attempt is logged with the caller's address. The locked screen's field turns off the
      browser's autocorrect, autocapitalize, spellcheck and autocomplete, and masks the words
      in every supported browser, with the eye to show them (S12.14).
   3. **What the server holds.** At unlock it unwraps the data key from the keyring and derives
      the database, receipts and secrets keys (S15.3.2); those, and the data key itself, stay
      in memory for as long as it runs. The master key is dropped as soon as the data key is
      unwrapped, and held again only while it wraps one: at a rotation, which brings the new
      one, and at a re-encryption, which runs with the phrase given at the unlock or typed on
      the host. Python cannot promise that no copy lingers in memory until it is reclaimed, the
      caveat of S11.9.4.2.
   4. **Made by the welcome** (S12.14), on a new server. With no keyring the server starts
      **uninitialised**, and its page welcomes the household's first admin: **Show my recovery
      phrase** makes a master key from the operating system's random source, in the server's
      memory only, and shows its 12 words with the fingerprint. Every visit makes a new one,
      and none is written until it is confirmed, so whoever only looked at a phrase knows
      nothing of the key the server keeps. Three of its words typed back (S15.6.1) write the
      keyring, the data key wrapped under the master key, into the data directory, and the
      server is unlocked at once; the welcome goes on to the admin's account (S10.1.2).
      Nothing else is written. The phrases on offer are held for an hour each, 20 at most, as
      the connector's welcome holds its own (S18.11.2). The welcome is the only way to make a
      key: no host command makes one, since a terminal, and the log Docker keeps of a
      container's, would hold the phrase. It refuses where a keyring exists: a backup brings
      its own keyring back with `db restore`. Whoever reaches an uninitialised server first
      can make its key: a household that finds its new server asking for words nobody wrote
      down empties its data directory (or reinstalls) and starts again, with nothing lost.
   5. **Uninitialised, refused and locked.** With no keyring the server is uninitialised:
      `/healthz` answers 503 `uninitialised`, `/ui` shows only the welcome, and every other
      path answers 503 (S13.6). It **refuses to start** (exit 78, S13.6) when the keyring
      cannot be read, and when the database is there without its keyring: a key made then
      could not open it, so the welcome makes none, and the refusal
      names the two ways on, `db restore` or an emptied data directory. A wrong phrase at unlock is refused and the server stays locked. A
      database the phrase opens the keyring for but the server cannot use (one from a newer
      release) is refused at the unlock, with the reason in the log, and the server stays
      locked.
   6. **Never** in a file, an environment variable, the image, the configuration or a
      script. A phrase pasted into a chat, a ticket or a screenshot is a leaked phrase
      (S15.8).
   7. **Commands**, each asking for the phrase it needs, with echo off, and keeping none of it:
      `moolakata keys fingerprint` (the key in use, no phrase needed), `verify` (S15.6.5),
      `reencrypt` (S15.7.2), `unlock` (S15.4.2) and `break-glass` (S15.5.2), and `moolakata db
      backup`, `verify-backup`, `restore` (S15.6.8) and `shell` (S14.7). **None shows a
      phrase**: a key is made and rotated in the browser (S15.4.4, S15.7.1), since Docker's log
      keeps what a container's first process writes, its terminal included. `unlock` and
      `break-glass` speak to the running server over its Unix socket from inside its container
      (`docker compose exec`, whose output Docker's log doesn't keep), and `db backup` asks the
      running server to make the backup the same way. The rest, and `db backup` when the
      server is stopped, run as one-off containers of the same image (`docker compose run
      --rm`) as the server's own account. Those that change the data directory (`restore`,
      `reencrypt`, and `db backup` run this way) take its lock first, so none runs beside the
      server: one that finds the server running refuses, naming the way to do it through the
      server; `db backup` run this way opens the database read only and migrates nothing.
      `db shell` shows the data itself: run as a one-off container's first process it asks
      before going on, since Docker's log will keep what it shows, and under `exec` it
      doesn't ask. What a one-off command did is queued in the data directory and reaches
      Activity within a quarter of an hour, or at the next unlock (S15.7.4), since a one-off
      container cannot open the database.
5. **What losing it costs.** Everything this server holds is encrypted under the master
   key, which exists only as its phrase, so **losing the recovery phrase loses all of it**:
   the database, the receipts, every backup and every copy the host holds, and the server
   cannot even start serving again. There is no back door, and no one can recover it,
   including the people who make MoolaKata.
   1. **The host lost, the phrase kept** (a failed disk, a rebuilt host): install, put the data
      directory's receipts back from the host's own backup, taken as near the backup's time as
      it has, restore the backup (S15.6.8), start, and unlock with the phrase. Nothing is lost
      that those two kept: a receipt the restored database names and the host's backup lacks is
      reported at the unlock.
   2. **The phrase lost while the server is running**: nothing is lost yet, but the next
      restart will lose everything. **Rotate at once** (S15.7.1), with a **break-glass code** in
      place of the lost phrase: `docker compose exec moolakata moolakata keys break-glass`, run
      on the host, asks the running, unlocked server over its socket for one, and Settings ›
      Key storage › **Rotate** takes it, with an admin's password, for 15 minutes and once.
      The server keeps only its hash, in memory, so a restart voids it; a wrong one counts
      toward the sign-in lockout, as a wrong phrase does; and every admin is alerted that one
      was asked for. The socket needs no phrase for it, and that proves nothing about who
      asks: whoever reaches the socket of an unlocked server can already read its data key
      from the process's memory (S15.6.7), so the code gives them nothing they lack. The new
      phrase is shown in the browser, never on the host's terminal, and the server restarts
      and re-encrypts with it. Back it up before anything else. A server stopped before that
      is a server lost; a locked server issues no code.
   3. Linked copies are not affected either way: they open with their own access keys, and
      are pulled again from their sources (S11.9.9).
6. **Backing up and protecting the master key.**
   1. **Back it up as it is made.** The welcome (S15.4.4) and **Rotate** (S15.7.1) show the
      **recovery phrase** in the browser, 12 numbered words, with the fingerprint, the server's
      name and the date, and will not finish until three words chosen at random are typed
      back. Nothing shows it
      again afterwards: the phrase is not stored, so a copy lost is a copy gone, and a phrase
      with no copy left is replaced by rotating (S15.5.2). Each word is recognised by its first
      four letters, and the last word's checksum catches most mistakes when the phrase is typed
      back in.
   2. **Keep at least two copies in two places**, at least one of them offline. For example:
      1. the printed sheet in a fire-resistant safe at home or a bank safe-deposit box;
      2. a secure note in the household's password manager (Bitwarden, 1Password, KeePassXC),
         in a vault that the second person below can also open. The same manager usually
         holds the linked copies' words (S11.9.2) and the connector's (S18.3), so one breach
         of it opens everything: give the phrase a vault of its own there, or let the printed
         sheet be its first copy;
      3. optionally, a USB stick holding the export encrypted with a passphrase (`age -p` or
         `gpg -c`), stored apart from the first copy.
   3. **Never keep it with the database backups**: not in the same directory, on the same
      disk, in the same cloud bucket, or in the same archive. A backup that holds both the
      database and the phrase protects nothing.
   4. **Never put it** in git, a ticket, a chat message, email, a shared drive, a container
      image, or a screenshot.
   5. **Check the backup.** **Verify key** in Settings › Key storage, or `moolakata keys
      verify` on the host, asks for the whole phrase and says whether it unwraps the keyring,
      without changing anything; a wrong phrase counts toward the lockout, as at the unlock
      (S15.4.2). Settings › Key storage records each confirmation: which fingerprint, and
      when. Check the copies once a year: that the sheet
      is readable, and that the password manager entry still verifies. Settings reminds admins
      when a year has passed. Every unlock is a check as well: a copy that unlocks the server
      is a good copy, and Settings › Key storage and the yearly reminder count it as a
      confirmation.
   6. **Two people should be able to recover it**: the admin and one trusted person, such as a
      partner, an executor or an adult child. Write down where the copies are, alongside the
      household's estate documents, because financial records are needed exactly when the
      person who set up the server is not available.
   7. **Protect the host as well**: root access limited to the people who run the server,
      since root on the running, unlocked server reads everything (S15.3.7). Disk
      encryption on the host is a good habit but no longer carries the key: nothing on the
      disk opens without the phrase, so the data directory and the backup directory can be
      snapshotted, replicated and sent to a NAS or a cloud bucket as they are, as long as
      the recovery phrase never goes with them. **Know where every copy is**: the copies on
      this host are listed in Settings › Key storage, with how each opens; a copy anywhere
      else (the host's snapshots and backups above all) is never seen or pruned by MoolaKata,
      opens with the key of its day for as long as it exists, and is yours to delete after a
      rotation or a leak (S15.7.3, S15.8).
   8. **Restoring onto a new host**: install MoolaKata, restore the backup with `moolakata db
      restore`, which asks for the phrase and checks it opens the backup's keyring, then start
      and unlock. The restore runs with the server stopped (the server holds a lock on the data
      directory while it runs): it checks the backup as `db verify-backup` does, refuses one
      from a newer release, and moves what it replaces (the database, its keyring and the
      linked copies) aside into `before-restore-<time>/` in the data directory rather than
      deleting it. The receipt files stay where they are: when they don't open with the
      backup's data key (a re-encryption since the backup), the restore re-wraps them from the
      replaced keyring's key to the backup's, a journaled step as a re-encryption's is
      (S15.7.2), asking for the replaced keyring's phrase when it is another. A backup made
      under an earlier phrase restores under that phrase: the restore names its fingerprint,
      says the current phrase will no longer unlock the server, and asks before going on. At
      the unlock the server opens the restored database and reports anything it cannot open,
      receipts and secrets among them, and each link's copy starts again, pulled in full
      (S11.9.9). `operations.md` has the step-by-step runbook, and a check rehearses it.
7. **Key rotation and re-encryption.**
   1. **Rotating the master key** replaces the recovery phrase, and with it the data key: the
      keyring is wrapped under the new master key at once, and the database, the receipt files
      and every secret are re-encrypted under a new data key (S15.7.2). Re-wrapping alone would
      change only which phrase opens the keyring: an old phrase and any copy made before would
      still give the data key that opens every later copy, so a rotation always re-encrypts. It
      is done in Settings › Key storage:
      1. **Rotate** (admins) asks for the password again and **the current phrase**, or a
         break-glass code from the host when it is lost (S15.5.2), so an admin's session alone
         can't change the phrase the household holds; a wrong one counts toward the sign-in
         lockout. It lists **the copies on the host**, each re-encrypted (the default), deleted
         or left, as at a re-encryption (S15.7.2). It then makes a new key in the server's
         memory, shows its recovery phrase as the welcome does (an hour each, 20 at most, none
         kept until confirmed) and asks for three words back. The re-encryption is journaled
         first, naming the new key and each copy's choice; then the keyring is wrapped under
         the new key, recording the previous key's fingerprint and the date; and the server
         **restarts at once** (S15.7.2), so the unlock with the new phrase re-encrypts before
         the server serves. The rotation, and later each copy's outcome, are recorded in
         Activity. A stop between the journal and the keyring leaves the keyring under the old
         phrase: the unlock with it re-encrypts all the same, and Key storage says the rotation
         didn't finish;
      2. **back up the new phrase at once** (S15.6). The server unlocks with the new phrase
         from the restart on;
      3. verify the new phrase (Verify key);
      4. **keep the previous phrase until every copy made under it is gone**. Settings › Key
         storage lists each previous key with how many copies on this host still need it, which
         after a rotation that re-encrypted every copy is none; the host's own snapshots and
         backups made before the rotation are outside that count and open with the previous
         phrase for as long as the host keeps them: the admin counts those. Then **Forget**
         drops the key from the list, and the old phrase's recovery sheet and password-manager
         entry are destroyed.
   2. **Re-encrypting** makes a new data key: the database is re-keyed (`PRAGMA rekey`), every
      receipt file is encrypted again under it, and every secret gets a fresh data key and
      nonce. It **never runs while the server serves**: it runs at an unlock, before the server
      serves, with its progress on the locked screen and `/healthz` answering 503
      `re-encrypting` (S13.6), or on the host with `moolakata keys reencrypt`, the server
      stopped, which asks for the phrase. A rotation brings one. On its own, Settings › Key
      storage › **Re-encrypt now** (admins, the password again) schedules one, the master key
      unchanged. Once one is scheduled **the server restarts itself at once**: it stops
      cleanly and starts again in the same process, locked, so no restart policy is relied on
      and no key crosses the restart; the admin unlocks it with the phrase, and the
      re-encryption runs at that unlock. The browser waits on the locked screen, and says to
      start the server on the host if it isn't back within a minute. One scheduled is never
      withdrawn or replaced: a second is refused until it has run. **A verified backup is made
      first**, under the old key, and **no backup runs while a re-encryption does**. **The
      copies on the host** are listed when it is scheduled, and for each the admin chooses
      **re-encrypt** (the default: rewritten under the new data key after the main job),
      **delete**, or **leave** (it keeps its old data key, which this phrase still opens); a
      copy under an earlier phrase cannot be rewritten and is left or deleted. A copy the
      choices don't name, the run's own first backup among them, is re-encrypted when it
      holds the data key being replaced, the first backup last, once everything else is done.
      **A journal** in the data directory records each step, the copies' choices among them,
      and the new data key's keyring, written beside the keyring as `keyring.next`, with the
      keyring it replaces kept as `keyring.old` until the store has opened under the new one.
      **Interrupted** by a stop or a crash, even between a step and its record, the
      re-encryption carries on from the journal at the next unlock, with the phrase given
      then, redoing nothing and never making a second new data key once the journal names
      one; a pending one under another phrase is refused at the unlock by name, and a
      `keyring.next` that the journal doesn't explain is set aside, never deleted, and listed
      among the copies on the host. A receipt or a secret that opens under neither key, or a
      receipt damaged past its first part, is set aside and reported in Settings › Key
      storage, never fatal; the log names it. It is
      for when **the data key may have been read**: a memory dump or a debugging session on the
      live server, and **any leak of the recovery phrase** (S15.8.1), since a leaked phrase
      opens the data key in every copy it could have been taken with. It closes nothing made
      before it (S15.7.3).
   3. **What neither does: a copy keeps the keys of its day.** Rotation and re-encryption
      change what copies made *after* them need; they change nothing about copies made
      before, which still open with the key and phrase of their day:

      ```
       copies made:   B1 ---- B2 ---- B3 ---|---- B4 ---- B5 ----
                                            |
          rotate (re-encrypts)  -------->   |  B4, B5 under a new phrase and a new data key;
                                            |  B1–B3 still open with the old phrase
          re-encrypt alone  ------------>   |  B4, B5 under a new data key, the same phrase;
                                            |  B1–B3 still open with the phrase
          delete B1–B3, everywhere  ---->   |  the only step that closes them
      ```

      1. Neither protects a copy made before it. A backup taken before a rotation opens with
         the old key, which is why the old key is destroyed only once every such copy is
         gone, and why a leaked key means deleting the copies it could open (S15.8).
      2. Neither changes the secrets themselves. A price source's API key is the same key
         after rotation or re-encryption, and anyone who already read it can still use it.
      3. Neither touches passwords, which are hashed, or linked copies, which have their
         own access keys.
   4. **Rotation is recorded** in Activity for admins: when, by whom, the old and new
      fingerprints and whether the phrase or a break-glass code allowed it, as is every `keys
      verify`; a command run while the server was down is queued in the data directory and
      recorded at the next unlock. Key material is never recorded.
8. **When a key may have leaked, and rotation otherwise.**
   1. **A leaked phrase is a leaked copy.** Whoever holds the recovery phrase and any copy
      made under it (a lost recovery sheet beside a cloud bucket of backups, a snapshot of
      the host, a disk with the data directory on it, sold or lost) holds the data key, and
      with it everything in that copy, for ever. Rotating the master key, re-encrypting, and
      revoking secrets each protect something else (S15.7.3); nothing but deleting the copy
      protects the copy. The reasons a phrase counts as leaked:
      1. a lost or exposed recovery sheet, a compromised password-manager vault, or a
         recovery phrase that was typed, photographed or pasted where it shouldn't be;
      2. someone who held a copy of the phrase, or had root on the running server, no
         longer should;
      3. the server was compromised (and after rebuilding it).
   2. **What to do, in this order**, each step for what it alone protects:
      1. **revoke and reissue the secrets at their source**: new price-source keys, a new
         password for the bitcoin node, a new SMTP password, the connector unpaired and
         paired again (S18.4.4). A secret already read is usable until its source refuses it,
         whatever happens to the keys here;
      2. **rotate the master key** (S15.7.1), which re-encrypts as well, and back up the new
         phrase, so the leaked phrase opens nothing made from now on, and no longer unlocks the
         server;
      3. **delete every copy made before the rotation, everywhere it was copied**: on this
         host, from the list in Settings › Key storage, or by choosing **delete** for each at
         the rotation; elsewhere, the host's snapshots, replicas, backups and VM images, on
         both ends of any replication. A copy that cannot be deleted is one the finder of the
         phrase can read, and should be treated as read: its secrets revoked (step 1 covers
         them) and its contents assumed known;
      4. then destroy the old phrase's sheet and password-manager entry, which the deleted
         copies no longer need.
   3. **A memory dump or a debugging session on the live server** exposes the data key, and the
      master key only if the dump was taken during an unlock, a rotation or a re-encryption
      (S15.4.3). Re-encrypt (S15.7.2), the phrase unchanged; rotate instead when the dump could
      have caught the phrase. The copies made before are only at risk if the dump itself has
      left the house.
   4. **Otherwise, rotate on a calm schedule: once a year is plenty** for a household server.
      Each rotation re-encrypts, so a sheet found later opens only copies made before its
      rotation. Every rotation means a new backup of the key in two places and an old one to
      destroy later. Rotating more often adds that work and the risk of a key with no backup,
      without adding security. Settings shows the key's age and reminds admins after a
      configurable period (12 months by default; off is allowed).
   5. **Never rotate without a tested backup of the new key.** Rotate when there is time to
      make and verify the backups the same day, not at the end of a maintenance window.
   6. **Keep the previous key exactly as long as the copies that need it**, then destroy every
      copy of it. A previous key kept for ever is a second key to protect.
   7. **Re-encrypt** for its reasons (S15.7.2). It is not a substitute for rotating the
      master key, or for revoking a leaked secret, and it closes no copy made before it.
