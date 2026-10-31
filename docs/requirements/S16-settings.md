# S16. Settings (admins)

One screen with a section list on the left, **General first** and selected when Settings opens.
Each section has its own help guide. In the order below, except Storage (17), which follows
Backups, and Connector (18), which follows Linked servers; 15 is not a section:

1. **General**: server name (shown to linked servers), the **household name and avatar** (an
   image, or initials; shown at the top of the sidebar here, and sent to linked servers,
   which always show them as set here, S12.10), public URL (links in emails are built from
   it, never from the request), and the server's time zone, read from the host (S14.9).
2. **Email (SMTP)**: host, port, security (STARTTLS, TLS or none), username, password (a
   secret, set with the password again), from address, and **Send a test email**, which sends
   to the admin at once and says what failed. Changing the host asks for the password again and
   clears the stored SMTP password, which is entered again for the new host (S13.7.2). Until a
   host is set, emails are written to the mail folder in the data directory, in the clear, and
   the section lists them (who for, subject, when) with **Open**, which shows one, links and
   all, after the admin's password again, so an invitation or reset link can be passed on, and
   records the opening in Activity with the user it is addressed to as its owner (S10.2); each
   file is removed once its link has expired: an hour after it was written for a password
   reset, a week for an invitation, and a day for the rest, an email with no link among them
   (S10.1, S15.1.7). With a host, they go out in the background, queued in the
   database: an email that can't be sent stays queued and is tried again every five minutes,
   until its link expires; one the server refuses outright is set aside, keeping only its
   recipient, subject and the error; and the section shows the queue and the last error.
3. **Sign-in and sessions**: idle and absolute session lifetimes (8 hours by default, 1 to
   168, and 30 days, 1 to 365), and the lockout of an address after failed sign-ins (10
   failures, 3 to 100, for 15 minutes, 1 to 1,440, S13.7.5.1).
4. **Sign-up**: on or off (it needs SMTP), optionally limited to email domains.
5. **Passwords**: the minimum length (12 by default, 8 to 128).
6. **Prices** (S4.2.3): the enabled sources with their classes, keys, order, last run and
   error; **Add a source**; and the time of the daily refresh (6:00 PM Eastern by default).
7. **Bitcoin** (S1.6): the explorer or node for self-custody wallets: a public Esplora
   (mempool.space suggested, or Blockstream) or the household's own node (its own mempool or
   Esplora by its address; an Electrum server by host, port and TLS; Bitcoin Core by host,
   port, RPC user and password), with when the wallets were last read and a **Test** button. No
   wallet is read until an admin saves this section (R3.5). Changing the node's host clears its
   stored password, which is entered again for the new host.
8. **Imports** (S1.3): the file types and size accepted for statement import (25 MB by
   default, 1 to 200), and whether statements are read on the server (in the receipt
   reader's worker, S9.8).
9. **Linked servers** (S11.7): this server's **link address** (its public URL when not set,
   S11.2), the links, and each linked copy's state: changes waiting, its access key (*Create
   the access key*, made when and by whom), locked or unlocked (by whom, and when it will
   lock), *Lock now* and *Reset copy*, and **Release linked keys after** (one hour unused by
   default, 5 minutes to 24 hours).
10. **Receipts**: the size limit (25 MB by default, 1 to 100); **Read receipts** on or off,
    jobs at a time (1 by default, at most 4), the reading queue, and **Re-read all receipts**
    (S9.8.7). On a host without Landlock, the section says that reading runs without its file
    sandbox here, which admins are alerted to as well (S9.8.4.2).
11. **Tax tables**: per year, for every year a tax book may cover (S8.14), shipped and
    correctable: contribution limits and thresholds, the annual gift exclusion, the 529-to-Roth
    lifetime limit, the QCD limit, the collectables rate, the unearned income above which Form
    8615 applies (S8.14.5.3), the shipped college-cost averages (S6.2.2), the bitcoin models'
    published figures (S6.3.1), and the metal per share of SLV, PPLT and PALL (S4.3). A
    corrected figure is marked, with the shipped value beside it; setting it back to the
    shipped value removes the correction. A year after the latest shipped uses the latest. The
    college-cost averages and the metal per share arrive with the features that use them (529s,
    physical assets).
12. **Backups**: the time of day (02:30 by default) and the **copies kept**: the days of
    backups kept, every backup of each of the most recent days that have one (14 by default,
    3 to 365, so one bad copy is never the only one); a second backup the same day, **Back up
    now**, never pushes out an earlier day's. Fewer days than the backups there are deletes
    some at the next backup, so it asks for the password again and the recovery phrase, as
    **Remove** does (S16.13): an admin's session alone deletes no backup. Each backup is
    listed with its size and the key it opens with, with **Back up now**; the backup
    directory is set on the host. The section says what a backup is: the
    database with its keyring, never the receipt files, which the host backs up with the
    data directory (S14.6).
13. **Key storage** (S15): the master key's fingerprint and age, when
    the phrase last opened the keyring and how (an unlock, **Verify key**, or `keys verify` on
    the host), the previous keys, each with how many copies on this host still need its phrase
    and **Forget**, the **copies on this host** (every backup, pre-upgrade copy, before-restore
    folder and set-aside keyring, with its date, size and how it opens, and **Remove**, which
    asks for the password and the phrase) under one line that says the host's own snapshots
    and backups are copies too (counting the backup directory's own copies only, and saying
    so: copies kept elsewhere are the admin's to count, S15.7.1.4), and **the last
    re-encryption**, always: when, why (a rotation, Settings or the host), anything it set
    aside that opened under neither key, each copy's outcome with those still under an old
    key marked, and a rotation that didn't finish. Buttons: **Verify key** (the 12 words,
    checked against the keyring without changing anything and recorded as a confirmation,
    S15.6.5); **Test**, which writes nothing and checks that the keyring on disk is the one
    the phrase unlocked and that the database and a secret open with the data key in memory,
    recorded in Activity; **Rotate** (S15.7.1: the password again and the current phrase or
    a break-glass code, each copy's choice, the new phrase shown and three of its words
    typed back); and **Re-encrypt now**, which asks, for each copy on the host, whether to
    re-encrypt, delete or leave it, with what re-encryption is for and that it closes no copy
    made before it (S15.7.2). Both restart the server, which then asks for the phrase; the
    page waits on the locked screen. Its one setting is the rotation reminder's period,
    **Remind admins to rotate after** (12 months by default, or **Never**, S15.8.4).
14. **Network**: the address ranges allowed to reach each path, one list per line, empty for
    any: **the app** (`/ui`, and `/mcp` with it: an agent sits where a person's browser does,
    and its token is already the user's); **linked servers** (`/link`); and **the connector**
    (`/connector`, S18), by default the private ranges and the overlays' (`127.0.0.0/8`,
    `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10` for Tailscale, `::1`,
    `fc00::/7`), so a connector on a laptop away from home (S18.1) needs an admin to widen it.
    The address checked is the client's as the trusted proxy forwards it (S13.3). `/healthz`
    and `/demo` answer any address. An address outside a path's ranges is answered 404, as for
    what doesn't exist. The ranges are in the database, so while the server is locked they
    can't be read: the locked screen and the unlock then answer any address that reaches the
    listener, and the proxy is what limits them. The section also shows, read only, how the
    listener runs: its mode (`proxy` or `tls`), its port, and the trusted proxies' addresses
    (S13.3), all set in its configuration (`moolakata.toml`, or `MOOLAKATA_CONFIG`, S17.8).
15. *Not a section*: `tls` mode is for testing (S13.3), and Settings › Network shows how the
    listener runs.
16. **Alerts** (S12.11): how long a source may fail before it raises an alert (48 hours by
    default, 1 to 336), and the time of the daily summary email (07:00 by default, in each
    user's time zone).
17. **Storage** (S14.10): the size of the database and of the receipts directory, files
    expired against the rest, the files no record names with **Remove** (S14.6), what
    expires each coming year by category, **Keep statements for** (years, empty for ever),
    each category's **Keep receipts for**, and **Prune**.
18. **Connector** (S18): pairing with the MoolaKata Connector (**The connector reaches MoolaKata
    at**, the address a pairing code carries, the public URL when empty, S18.4.1; **Pair**, the
    connector's fingerprint, **Confirm** once the fingerprints were compared, who confirmed and when,
    **Unpair**), whether it is locked, its last report and the address it reports from (with
    **Accept** when that address changed, S18.2.4.4), and every Connection's state, owner,
    accounts and the host its credentials go to, never the credentials.
