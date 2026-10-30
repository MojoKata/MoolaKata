# Walk-through: review 3's key-storage claims

Started Oct 30, 2026. Decisions log; nothing is applied until the final approval. The claims are
those of unit 10 about the keys, re-encryption and backups (S15, S16.13). Five need a choice and
are walked here; the others (CR3-58, 59, 118, 120, 123, 296, 298, 299, 305, 307, 309, 355) take
their remedies as written, agreed Oct 30.

## Items

1. CR3-60 (Med): copies made after a re-encryption's choices, the run's own first backup
   among them, are left under the old data key unasked
2. CR3-61 (Med): the re-encryption a rotation brought can be cancelled in Settings, with no
   password again
3. CR3-63 (Med): an admin's session alone deletes every backup but one: *Copies kept* set to
   1, then *Back up now*
4. CR3-369 (Low, question) with CR3-354 (Low): `db shell`'s output, and `keys init`'s sheet
   under a tty, are kept in Docker's log
5. CR3-301 (Low): the rotation reminder's period can't be changed in the browser

## Decisions

1. **CR3-60 (1 of 5): re-encrypt now, the server restarting itself.** A rotation through the
   running server (`keys rotate` over the socket) and Settings › Key storage's re-encryption
   schedule the run and then restart the server: it exits cleanly and Docker's
   `restart: unless-stopped` brings it back locked; the admin, who has the phrase in hand,
   unlocks it (locked screen or `keys unlock`) and the re-encryption runs at that unlock, the
   path that exists. No key crosses the restart (S15.4.1, phrase only). If the server isn't
   back within about a minute, the screen and `keys rotate` say to start it on the host.
   *Re-encrypt at the next restart* becomes *Re-encrypt now (MoolaKata restarts)*, with no
   Cancel. Any copy under the data key being replaced that the choices don't name, the run's
   own first backup among them, takes the default, re-encrypt; the first backup is rewritten
   last, once the rest has succeeded. The rotation's report says *re-encrypted* only for
   copies the run can rewrite, and *left: needs the phrase of …* for the rest. Weighed:
   re-encrypting in place with the server paused (no reliance on the restart policy, but a
   new pause-and-reopen path), stopping daily backups while one waits, deleting the first
   backup after the run.
2. **CR3-61 (2 of 5): settled by decision 1, with guards.** The server never serves while a
   re-encryption waits, so Cancel (its route and button) goes; scheduling refuses over any
   pending re-encryption instead of replacing one not yet begun (`keys rotate` over the socket
   already does); *Re-encrypt now* keeps the password again (S16.13). Weighed: a *Rotate back*
   that re-wraps under the old phrase.
3. **CR3-63 (3 of 5): a floor of 3, the phrase to lower below the backups present, pruning by
   day.** *Copies kept* runs from 3 to 365 (S16.12); lowering it below the number of backups
   present asks for the password and the phrase, as **Remove** does, a wrong phrase counting
   toward the sign-in's lockout; the prune keeps the latest backup of each of the last N days,
   so **Back up now** never pushes out an earlier day's. Weighed: a floor alone, a cap of two
   **Back up now** a day (each only sets the pace: the daily task alone prunes down to a
   lowered count within that many days); the lower count for later backups only; one prune a
   run; a lowered count that waits a week, emailed to every admin, with **Undo**.
4. **CR3-369 and CR3-354 (4 of 5): keys are made and rotated in the browser only; the host
   gives a break-glass code.** Tested Oct 30: under `docker run -t`, Docker's log keeps both
   standard output and `/dev/tty`; under `docker exec`, with or without a tty, it keeps
   neither. So:
   1. `keys init` goes: the welcome is the one way to make a key (it already was the way in
      for the TrueNAS app; the browser is needed for the first admin regardless).
   2. **Rotate** joins Settings › Key storage: the password again and **the current phrase or
      a break-glass code**; the new sheet shown and three words typed back, as the welcome
      does; then the restart of decision 1, unlocked with the new phrase.
   3. `keys rotate` goes from the host, the stopped-server rotation with it. For a lost phrase
      (S15.5.2), `docker compose exec moolakata moolakata keys break-glass` asks the running,
      unlocked server over its socket for a code: single use, 15 minutes, its hash in memory
      only (a restart voids it), its issue in Activity with an alert to every admin, a wrong
      code counting toward the sign-in's lockout as a wrong phrase does. S15.7.1 says why the
      socket needs no phrase: whoever reaches it on an unlocked server can already read its
      data key from memory, so it gives nothing new; it is not a check of who asks. A locked
      server's socket issues no code.
   4. No host command shows a phrase any more; `unlock` and `verify` read one with echo off.
      `db shell` under `run` (PID 1) asks first: "Docker's log will keep what this shows; go
      on? [y/N]"; under `exec` it doesn't.
   5. The docs (S14.7, S15.4.4, S15.4.7, S15.5.2, S15.6.1, S15.7.1, `operations.md`,
      `test-plan.md`), `compose.yaml`'s comments, the mockup's *On the host* list and the
      rotation alert's text ("Rotate in Key storage") follow.
   Weighed: `keys init` under `exec` with a PID-1 refusal; rotation kept on the host; docs
   only; writing the sheet to a file only the admin reads (a phrase in a file).
5. **CR3-301 (5 of 5): a field in Key storage.** "Remind admins to rotate after [12] months",
   with *Never* for off; saved like any other setting, no password again (it deletes and
   shows nothing). Weighed: dropping the setting for a fixed 12 months.

Final approval of decisions 1 to 5, and of the remedies as written for CR3-58, 59, 118, 120,
123, 296, 298, 299, 305, 307, 309 and 355: Oct 30, 2026. Built on branch `cr3-keys`, one PR.

## Applied

On branch `cr3-keys`, with the requirements, both mockups, the guides and tests, in one commit,
`bcbcdbb`: the decisions share their code (the journal, the restart, Key storage), so they went
in together.

| Decision | Claims | What changed |
|---|---|---|
| 1 | CR3-60 | `runtime.restart`, `main.serve` re-executes; unlisted copies re-encrypted, the first backup last |
| 2 | CR3-61 | no Cancel route or button; `schedule` refuses over any pending run |
| 3 | CR3-63 | *Copies kept* 3 to 365, its own dialog and route, the phrase to lower it; `prune` by day |
| 4 | CR3-369, CR3-354 | `keys init` and `keys rotate` gone; **Rotate** in Key storage; `keys break-glass`; `db shell` asks under `run` |
| 5 | CR3-301 | **Remind admins to rotate after** in Key storage |
| as written | CR3-58, CR3-296 | the keyring step decided by the data key's id; the rotation journaled before the keyring |
| as written | CR3-59 | a receipt damaged past its first part set aside; no `.tmp` left |
| as written | CR3-298 | a failed unlock relocks; `restored.json` kept until checked |
| as written | CR3-305, CR3-355 | the host queue moved aside, read under its lock, removed once recorded |
| as written | CR3-299 | `.part` backups removed at a backup and at start-up; a set-aside keyring listed |
| as written | CR3-309 | the last re-encryption always shown, each copy's outcome marked |
| as written | CR3-118, CR3-120, CR3-123 | S16.13's **Test**, S15.3.1's phrase, S15.4.4's bound |
| as written | CR3-307 | tests: a stop after each step, a damaged chunk, a failed unlock, the rotation in the browser |

Where the work differs from the decision as written, and why:

1. **Decision 1**: the server restarts by stopping cleanly and re-executing itself in the same
   process, so no restart policy is relied on, Docker's or any other. A browser test rotates,
   watches it come back locked, and unlocks it with the new phrase. The "start it on the host"
   line stays, for a start that fails.
2. **Decision 3**: the prune keeps every backup of the most recent days, not only each day's
   latest: keeping the latest alone would let **Back up now** delete that day's earlier backup.
   *Copies kept* is changed in a dialog of its own, since a setting's draft carries no phrase;
   the settings save refuses a lower value with `phrase-needed`.
3. **Decision 4**: the copies a rotation is told to delete are deleted by the re-encryption at
   the unlock, a journaled step, not at once. The welcome, dev mode and the tests make a
   keyring with `master.create_keyring`. `db restore` asks its yes/no question on standard
   input. The break-glass alert lasts two days.
4. **CR3-123**: the welcome already held its phrases an hour each, 20 at most; S15.4.4 now says
   so.
