# Settings: Key storage

Everything the server stores is encrypted under one master key, which is the recovery phrase:
never stored, entered when the server starts, and changed with **Rotate**.

![Settings: Key storage](shots/settings-keys.png)

## Fingerprint

A short name for the key that reveals nothing about it, such as `mk-3f9a…c21e`.

## Unlocked

When the phrase was last entered. The server locks again at every restart, until someone
enters the phrase on the locked screen or with `moolakata keys unlock` on the host.

## Recovery phrase

The master key written as 12 words. The welcome showed it once, when the server was new, and
nothing shows it again: without it nothing here, no backup, and no restart of the server opens.

## Verify key

Type the 12 words from one of your copies: MoolaKata checks that they open this server's key,
changes nothing, and records the check. Do it once a year for each copy, and whenever you make a
new one; the yearly alert opens it. `moolakata keys verify` on the host does the same.

## Test

Checks, writing nothing, that the keyring on disk is the one the phrase unlocked, and that the
database and a secret open with the data key in memory. Activity records the test.

## Previous keys

The master keys this server was rotated away from, each with how many copies on this host still
need its phrase. A rotation re-encrypts every copy it is told to, so the count is usually none; the
host's own snapshots and backups made before the rotation still open with that phrase for as
long as the host keeps them, and are yours to count. **Forget** drops a key from the list once
nothing needs it; destroy its sheet and password-manager entry then.

## Copies on this host

Every copy MoolaKata can see: the backups in the backup directory, the copies made before a
migration (`pre-upgrade/`), what a restore set aside (`before-restore-*/`), and a new keyring a
re-encryption left unexplained, set aside beside the keyring. Each carries its
own keyring and says how it opens: with this phrase, with this phrase but an earlier data key,
or only with a previous phrase. **Remove** deletes one, after your password and the phrase. The
host's own snapshots and backups are copies too, outside this list.

## Last re-encryption {#last-reencryption}

When the last re-encryption finished and why (a rotation, Settings or the host), anything it set
aside that opened under neither key, and what it did with each copy: a copy left under an old
key is marked, since it still opens with the old phrase. A rotation that didn't finish (the
keyring stayed under the old phrase) is said here: rotate again.

## Rotate

A new recovery phrase, and a new data key with it: for a leaked or lost phrase, or the yearly
reminder. It asks for your password and the current phrase, or a break-glass code from the host
when the phrase is lost, then shows the new phrase and takes three of its words back. MoolaKata
restarts, and the unlock with the new phrase re-encrypts everything before it serves.

## Re-encrypt now

A new data key for the database, the receipt files and every secret, the phrase unchanged. It
never runs while the server serves: MoolaKata restarts at once, locked, and the unlock runs it
first, after a verified backup, with the phrase given there wrapping the new key, its progress
on the locked screen. It asks for your password again. Once asked for, it runs at that unlock;
a second waits until it has. A rotation re-encrypts too.

## Scheduled {#scheduled}

A re-encryption waiting for the restart: the unlock runs it before the server serves.

## Remind admins to rotate after {#rotation-reminder}

How old the master key may get before admins are alerted to rotate it: 12 months by default, or
**Never**.

## After a restore {#after-restore}

The first unlock after a restore opens every receipt file and secret with the restored keys,
and lists here what doesn't open: receipts to put back from the host's own backup of the same
moment, and secrets to enter again. A receipt file that opened under no key was set aside in
`receipts-set-aside/` in the data directory.

## The copies on this host {#copies-at-re-encryption}

For each copy, what the re-encryption does with it: **Re-encrypt** (the default) rewrites it
under the new data key, after the main job; **Delete** removes it; **Leave as it is** keeps it
under its old data key, which this phrase still opens. A copy under an earlier phrase cannot be
rewritten: leave it or delete it. A backup made after the choices, the re-encryption's own
first one among them, is re-encrypted, the first one last.
For when the data key may have been read: a memory dump or a debugging session on the live server,
or a master key or recovery phrase that leaked while any copy of the data directory or a backup
could have been taken with it. It closes nothing made before it: every earlier copy still opens
with the key it was made under, so a leak also means deleting those copies wherever they are. It
doesn't change the master key, which **Rotate** does.
