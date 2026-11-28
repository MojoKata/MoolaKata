# S14. Storage and secrets

1. **One SQLite database** (WAL) under the data directory, through SQLAlchemy, for everything
   but what links bring in, which lives in a SQLCipher database per link (S11.9). The schema
   follows [`schema.md`](schema.md), which a test enforces. The database is encrypted with
   **SQLCipher** under a key derived from the data key (S15.3), through the same
   `sqlcipher3` engine as linked copies.
   1. **Tables** are declared with SQLAlchemy Core (`Table`, `Column`) in `store/tables/`,
      one module per area, on one `MetaData`. A table module holds only columns, keys,
      constraints and indexes.
   2. **Entities** are plain dataclasses in `store/entities/` that import nothing from
      SQLAlchemy. `store/mapping.py` maps each one onto its table
      (`registry.map_imperatively`); what a record belongs to is read by queries. Business logic lives in the
      feature modules (`ledger/`, `loans/`, `giving/` and the others), and a test fails when
      their calculation code imports SQLAlchemy.
   3. **Revisions:** each change to the tables is a numbered Alembic revision, generated,
      reviewed by hand and committed, and a test fails when tables and revisions disagree. At
      the unlock the server copies the database (verified) into `pre-upgrade/` in the data
      directory, keeping the three newest copies, and then migrates it, one revision per
      transaction. A committed revision is never changed: a change is a new revision.
   4. **Access:** each table has a repository module. A unit of work is `Database.tx()`
      (`BEGIN IMMEDIATE`) or `Database.read()` (`PRAGMA query_only`, which refuses any
      write). Foreign keys are on, with a 10-second busy timeout. A unit of work reads and
      writes for a user, through each table's access view, or names why it is the server's
      own; one that does neither reads nothing ([`schema.md`](schema.md) §7).
   5. **Soft deletes**: records are never removed. Deleting one sets its `deletedAt` and
      `deletedById` (its `deleted` is generated from `deletedAt`), and each table's view works out whether a record is
      deleted through the records it belongs to. [`schema.md`](schema.md) §4 sets the
      fields, the views and the few exceptions.
2. **Receipts** are files beside it (S9.2), and so are the linked copies (`links/`, S11.9.1)
   and what a link sends and receives on its way: each owned by the server's account, mode
   0600 in a 0700 directory, set when written, and a directory found looser (made by an image
   or a restore) set back at the next write into it.
3. **Decimals**: money is stored as **integer cents**, and quantities and prices as **decimal text** validated to a fixed scale (18
   places, enough for wei), through a small SQLAlchemy column type. JSON carries both as exact
   numbers (S13.8.2). Python uses `decimal.Decimal` with a context of 34 digits and rounds
   `HALF_EVEN` except where a section says otherwise (a tax rule; a loan's interest, S1.9.2;
   an adjusted option's strike, S3.10.1; a budget's proposed amounts, S7.1.5). No amount
   passes through a float.
4. **Secrets** (price-source keys, the bitcoin node's credentials, the SMTP password, the
   link private key, two-step sign-in seeds, a seed being set up) are encrypted each on its
   own with AES-256-GCM under a data key of their own, wrapped under the **secrets key**,
   which derives from the data key (S15.3.3), with associated data naming the record and
   field, so a ciphertext copied onto another record fails to decrypt. Secrets are decrypted
   when used, never logged, and never sent back to the browser: the UI shows a stored secret
   as *set*, with when and by whom. Passwords, two-step recovery codes, and session, reset
   and invitation tokens are stored as hashes.
5. **The master key**: 128 random bits that exist only as a 12-word recovery phrase, in the
   admin's keeping, and in the server's memory while it unwraps the data key at each start.
   It is never stored: not on the host, not in the database, not in a backup. S15 covers how
   it is made, entered, protected and rotated.
6. **Backups**: daily and verified, of the database **with its keyring, and nothing else**, to
   a directory set on the host; the time of day and the number of copies kept are Settings.
   **The host keeps backups of the filesystem**, the data directory with its receipt files, linked
   copies and keyring included (by snapshots, a replication or any backup tool); a backup here
   exists so that the live database file the host picks up has a coherent, verified twin beside
   it. Receipt files are never copied into a backup: the host's backup protects them, each
   written once and rewritten only by a re-encryption (S15.7.2). The backup directory therefore
   belongs inside what the host's backups hold, not on a disk apart. The server makes and verifies
   (`PRAGMA integrity_check`) the copies itself, never while a re-encryption runs (S15.7.2),
   and prunes by day (**backup pruning**): every backup of the most recent days that have one
   is kept, as many days as Settings › Backups keeps, never fewer than three, and the rest go;
   a backup cut off part-way is removed at the next backup and at start-up (S16.12).
   `moolakata db backup` makes one at once, through the running server or, with the server
   stopped, on its own (S15.4.7), and `moolakata db verify-backup` checks one (the newest by default) without
   changing it: every file against the manifest's hashes, the manifest against its own
   authentication code (HMAC-SHA256 under a key derived from the backup's data key, so a backup
   swapped for an older one or a manifest rewritten to match a changed file is caught by
   whoever holds the phrase), that the time the manifest records matches the backup's name (it
   shows that time, and refuses a backup renamed as another), and that it opens with the phrase
   typed, which may be a previous one. Each backup carries its own keyring, so it opens with
   the phrase of its day, and a rotation re-encrypts it (S15.7.1). A restore (S15.6.8) puts the
   database and keyring back, leaves the receipt files where they are (re-wrapped to the
   backup's key when a re-encryption came between), and sets the linked copies aside to be
   pulled again (S11.9.9); files the restored database does not name are counted in Settings ›
   Storage, with **Remove** (S16.17). The restore is documented, and tested by a check.
7. **Financial data at rest** is encrypted with the rest of the database (S15.1). Ordinary
   SQLite tools can't read it. `moolakata db shell` opens it on the host, with the recovery
   phrase typed: through `docker compose exec` beside the running server, or, when the server
   won't start, as a one-off container, where it asks first, since Docker's log keeps what it
   shows (S15.4.7); that it was opened, like every `db` and `keys` command run on the host, is
   queued in the data directory and recorded in Activity for admins at the next unlock or
   within a quarter of an hour (S15.4.7).
8. **Export** of a user's own data comes after the first release ([F#560](https://github.com/MojoKata/MoolaKata/issues/560)).
9. **Times and dates.**
   1. **Every timestamp is stored in UTC** (`deletedAt`, a session's start, an alert's
      opening, a price's `as_of`), and shown in the viewer's time zone.
   2. **Each user's time zone** is set in Profile: **Auto**, the server's time zone (from the
      host, which gives the container its `/etc/localtime` and `TZ`, S17.8; shown in Settings ›
      General), or a time zone they choose by name (`America/Denver`). A change asks **Since
      when?**, the date the new time zone is in effect from, today by default:
      1. **Today is a move**: the time zone in effect before it stays so for everything that
         came before. **An earlier date is a correction**: the new time zone was already in
         effect then.
      2. A user's time zones are kept with the date each is in effect from: each from 00:00
         of its date, in that time zone, until the next one starts; before every one, the
         earliest. A change replaces the ones from its date on. *Auto* is the server's time
         zone whenever it is used. A user who never changed it has theirs at every moment.
      3. A blank date, one before 1900, or one whose 00:00 in the new time zone hasn't come, is
         refused at its field (R3.11).
      4. A user's time zones are theirs alone to see and change.
   3. **Calendar dates have no time zone**: a transaction's date, a statement's period, the
      day of a balance or positions a file reports, a birthday and a due date are dates as
      the institution or the user wrote them, never shifted. A bitcoin transaction is a moment
      on the chain, not a date written: it is dated in the time zone in effect for its owner at
      that moment (S1.6.2.6.1).
   4. **A trading day** is the US market's, in New York time: a daily close is dated by its
      market day, whatever the viewer's time zone (S4.4).
   5. **"Today" for a user** follows their time zone: the year a tax year screen opens on,
      when an occasion's lead time starts, and the hour their daily summary email goes out
      (S12.11.5).
10. **Retention and file pruning**: records are never removed, but for the exceptions of
    `schema.md` §4.4: not records, soft-deleted records (`schema.md` §4) or Activity, so every
    figure can be looked back on as it was (R3.10). What can be removed, by hand, is the
    **files** of receipts and statements whose retention has run out: **file pruning**. Backups are pruned on their own, shorter
    schedule (S14.6), and price history is kept for ever (S4.6).
    1. **Retention periods**:
       1. **A category** has **Keep receipts for** a number of years, counted from when the
          record a receipt is attached to ended (`schema.md` §6). Empty, the default, keeps
          them for ever. A subcategory without its own takes its parent's. Any whole number
          of years from 1 is allowed; while it is under 7 the field warns that it is shorter
          than some IRS audit windows (7 covers them all).
          An admin sets it, in Settings › Storage, since it decides what file pruning may
          remove.
       2. **Statements** have one period, in Settings › Storage (S16.17), empty (for ever)
          by default. A statement ends with its own period, so it expires that many years
          after its last day; one without a date ends with its account's last transaction
          once the account is closed. A loan's other documents (a closing disclosure, S9.3)
          are kept while the loan is open, and end when it is paid off (closed): they take
          the statements' period from then.
       3. **A file** (a receipt or a statement) has a **Keep** toggle that keeps it for ever.
    2. **When a file expires**: at the latest end of the records it is attached to, plus the
       longest of their periods. It never expires when Keep is on, when any of those records
       has no period (a transfer, an uncategorised transaction, a category kept for ever, a
       physical-asset item, which has no category:
       [G#675](https://github.com/MojoKata/MoolaKata/issues/675)), or when it is attached to
       nothing. Expiry is worked out, never stored, so a changed
       period moves every date at once. A deleted receipt keeps no file (S9.7): one that no live
       receipt names has no expiry, and is pruned as a deleted receipt's (S14.10.4).
    3. **Shown on each file**: *Kept until Mar 2031*, in bold within 90 days of it;
       *Kept while the lot is open* while a record it is attached to hasn't ended; or
       *Kept for ever*. An expired file shows *Expired Mar 2031, prunable*.
    4. **Files are never pruned on their own.** An admin prunes them in **Settings ›
       Storage**: the size of the database and of the receipts directory, a **pie** of
       expired, expiring later, kept for ever and **deleted receipts** (the files only deleted
       receipts name, which keep no file: S9.7), and a **bar for each coming year** of what
       expires in it, by category. The pie's parts and the files no record names add up to
       the receipts directory's size. Sizes are the files' sizes on disk; the section shows
       sizes and counts only, never what the files hold.
    5. **Prune 1,284 files (2.1 GB)** names what has expired and the deleted receipts' files.
       It previews them by category, the deleted receipts as one of their own, any of which
       can be unticked (a deleted receipt's file kept so, until deleted receipts can be
       restored: [G#575](https://github.com/MojoKata/MoolaKata/issues/575)), asks the admin to
       type the count to confirm (*Type 1,284 to confirm*, the field empty until they do), and
       their password again if given over 10 minutes ago (S13.7.2), removes the files, and records
       the file pruning in Activity with its counts. No backup is made first: a backup holds no
       files (S14.6). A file several receipts share is removed once no live receipt needs it (a
       deleted one doesn't count), nor one an upload of the same bytes is reusing as the prune
       runs. Every receipt naming a file the prune removes, deleted ones included, is marked
       pruned with it, so none is left counted among the deleted receipts' files. The same file
       uploaded again after it is a new receipt with its file. Removing
       the files no record names (S16.17) goes by the linked copies' rule (S11.9.6.6): never a
       file an upload is still writing, and only one half an hour old. Each record keeps its row, amounts and links, and shows *File pruned Jan
       3, 2034* once its file is gone. A pruned file survives only in the host's own backups of
       the data directory, for as long as the host keeps them.
    6. **Linked copies follow their source.** File pruning never touches a linked copy
       (S11.9): a file the source prunes leaves the copy at its next pull, and the copy keeps
       nothing longer than its source does.
