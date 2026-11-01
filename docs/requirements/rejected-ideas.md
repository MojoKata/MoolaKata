# Rejected ideas

Ideas that were weighed and turned down, kept so they are not raised again without a new
reason.

1. **A separate keys process** that alone holds the data key and wraps and unwraps keys over a
   Unix socket. A compromised web process could then not copy the key, but it costs a second
   account and a socket, and the web process can already read everything the key protects while
   it runs. The phrase is held only during an unlock, and the data key in the server's memory
   (S15.4.3).
2. **External key services** (HashiCorp Vault, cloud KMSs, HSMs, TPM sealing): another service
   to run, back up and secure, for little gain over a phrase entered at each start with its
   copies kept offline (S15.2).
3. **Leaving the financial data unencrypted** and relying on disk encryption and encrypted
   backups. Backups leave the house, so the database and receipts are encrypted by MoolaKata
   (S15.1).
4. **The master key written as base32** on a recovery sheet. Twelve BIP39 words are easier
   to write down, read back and type, and catch typos better (S15.6.1).
5. **A personal access key per user for linked copies**, with the copy key sealed to each
   user (by a passphrase of their own, or by their password). The owner's shares already
   decide who sees what, so the key only has to protect the copy at rest. One key per copy,
   unlocked for the server, is simpler and recovers more easily (S11.9.3).
6. **The receiving admin choosing who sees each linked share.** Servers exchange their user
   lists, so the owner names the people (S11.3).
7. **Linked accounts shown among this household's own**, as locked rows, in totals or inside
   local portfolios. Another household's data is a world of its own and opens in its own
   window (S12.10).
8. **SQLModel** for the tables. It merges the table, the API model and the entity into one
   class. Tables are declared with SQLAlchemy Core and mapped onto plain dataclasses, so the
   schema carries no logic (S14.1).
9. **A portfolio showing an account its viewer can't see** as one line with its value. It
   still discloses a figure the owner didn't share; viewers see only what is shared with
   them, and the Share dialog offers to share the rest (S5.1).
10. **Write access for agents.** An agent reads through a token and can never change
    anything, whatever shares its user holds (S10.9).
11. **An RPM** with its own Python, beside or in place of the Docker image. A home server is
    far more often a NAS, a Raspberry Pi or a container host than a RHEL machine (S17.8).
12. **Barchart** for prices. Its website's terms forbid robots, data mining and applications
    built on it without written consent, and its API (OnDemand) is a paid commercial
    product (S4.1).
13. **Stooq** as the no-key source for daily prices and metals spot. Since 2026 its downloads
    need a key obtained through a captcha, with a daily quota, which a server can't keep up
    (S4.3).
14. **Yahoo Finance** (unofficial). It has no API terms and breaks without notice.
15. **Bank aggregation** (SimpleFIN Bridge and the like). It costs each user a subscription
    and gives a third party standing read access to their accounts. Statements and exports
    the user downloads cover the same ground (S1.3).
16. **Pruning records** from the database, leaving yearly or monthly summaries in their
    place. A household's rows grow by about 10 MB a year, while its receipt and statement
    files grow 50 to 100 times faster; removing rows saves little, loses history that
    can't be brought back once backups age out, and makes every report add summaries to
    what survived. Only files are pruned, by their retention (S14.10).
17. **A key per backup**, or any way to close a copy already made, after a master-key leak:
    re-wrapping each backup's keyring under a key the leaked phrase does not open. Whoever
    holds the leaked phrase and a copy of the backup as it was already has its data key; a
    later re-wrap changes only the copy MoolaKata still holds, not theirs. A copy opens with
    the keys of its day for as long as it exists, so the answer to a leak is to delete the
    copies, not to re-key them (S15.7.3, S15.8).
18. **A master key file on the host**, read by the server's account at start, mounted read
    only from a directory kept out of every backup. It gives unattended restarts, and it
    costs the one thing on the host that must never be snapshotted, replicated or backed up
    with the rest: a chore at every install, and a mistake waiting in every snapshot. The
    recovery phrase already is the key; entering it after each start keeps nothing on disk
    and lets the whole host be backed up as it is (S15.4).
19. **An automatic unlock** of the server or the connector after a restart, from a file or
    a script on the host. It is a key file by another name: whatever can unlock without a
    person is on the disk, in the snapshots and in the replicas. A restart needs a person,
    with the phrase or the vault's words (S15.4.1, S18.3.2).
20. **An unlock passphrase beside the recovery phrase**: the data key wrapped a second time,
    under a key stretched from a passphrase an admin chooses, so that restarts use the
    passphrase and the phrase stays offline. A leaked passphrase plus a copy opens everything,
    as a leaked phrase does, so a leak costs the same; and every copy of the keyring becomes an
    offline guessing target only as strong as the passphrase, where today a stolen copy is
    nothing without 128 random bits. The phrase stays the one secret, typed at the locked
    screen or on the host, kept out of logs, and in a browser only where S15.3.1 lists it.
21. **A watched folder for the connector**: a downloads folder mounted into the connector, its
    new files posted to accounts by name. A driver's job is to push what it fetches from an
    institution; where nothing can be fetched, the owner downloads on their own desktop, not on
    the server, and uploads by hand (S1.3, S18.9). A shared folder also hands one user's
    statements to another's rules.
22. **Re-encrypting while the server keeps serving**: every receipt read would need to try two
    keys while the pass runs, and requests would race the rewrite. A re-encryption runs at an
    unlock, before the server serves, or on the host with the server stopped; a few minutes of
    downtime at a planned restart suit a household server (S15.7.2).
23. **Keeping admins out of other users' accounts**, by limiting what Settings › Email can
    open, showing every admin action on an account to its user at sign-in, or asking a second
    admin to approve a reset. An admin holds the recovery phrase and the host, so no rule in
    the app keeps out one who sets out to look; a household with one admin couldn't use a
    second approval. Admins are trusted operators, and the app keeps others' money off their
    screens by default (S10.2).
24. **One polymorphic access view for every kind**, `ItemAccess(kind, targetId, userId, …)`,
    in place of a view per table: every join would have to carry the kind, a child's view
    couldn't chain to its parent's by name, and the view's name would no longer say whose
    records it holds ([`schema.md`](schema.md) §7).
25. **Visibility checked per route in Python**, each route asking a level function before
    it reads: every route had to remember, and one that read a related record without asking
    (a receipt's other links, CR3-47) leaked it. Every read and write goes through the
    tables' access views instead ([`schema.md`](schema.md) §7).
