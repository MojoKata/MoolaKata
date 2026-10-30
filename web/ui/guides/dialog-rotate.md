# Rotate the master key

A new master key and recovery phrase, and with them a new data key. MoolaKata then restarts,
locked: unlock it with the new phrase, and it re-encrypts the database, the receipt files and
every secret before it serves, the copies on this host as you choose. For a leaked or lost
phrase, or when the yearly reminder says it is time.

## Current recovery phrase

The server's 12 words, as they are now, with your password: a session someone took over can't
change the phrase the household holds. A wrong phrase counts like a wrong password.

## The phrase is lost {#lost-phrase}

While the server runs, a lost phrase is replaced by rotating. A **break-glass code** stands in
for it: run `docker compose exec moolakata moolakata keys break-glass` on the host and type the
code it shows. It works once, for 15 minutes, and every admin is told one was asked for. Once
the server stops, a lost phrase can't be replaced, so rotate now.

## Break-glass code

The code from the host, such as `BG-7K3Q-9XWM`, in any case, with or without its dashes.

## The copies on this host {#copies-at-re-encryption}

For each copy, what the re-encryption does with it: **Re-encrypt** (the default) rewrites it
under the new data key and the new phrase; **Delete** removes it; **Leave as it is** keeps it
under its old keys, so it still opens with the old phrase. A copy under an earlier phrase can
only be left or deleted.

## The new recovery phrase

Shown once: write the 12 words on paper, in order, and keep two copies in two places, one of
them offline. Keep the old phrase too until every copy made under it is gone, the host's own
snapshots and backups among them.

## Words back

Three of the new phrase's words, from your sheet. Four letters of each are enough. **Rotate and
restart** then rotates, and MoolaKata restarts; the page waits for it on the locked screen.
