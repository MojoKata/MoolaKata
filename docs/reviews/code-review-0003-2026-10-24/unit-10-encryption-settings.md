# Code review 3, unit 10: encryption-settings

**Session:** Oct 24, 10:21 PM to Oct 24, 10:36 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S15 (encryption and the master key: S15.1 what is encrypted and what is plain;
  S15.2 the threat model; S15.3 the key hierarchy, the phrase, the data key, the keyring, secrets;
  S15.4 the unlock, the locked state, the welcome's phrases, the host's part; S15.5 recovery;
  S15.6 the phrase's care, verification, backups and copies with their keyrings, restore;
  S15.7 rotation, re-encryption, copies' choices, Forget; S15.8 a leak) and S16 (settings: every
  Settings section and what it stores, S16.1–S16.18), with the README's R1–R3 lines they rely on
  (R1.13 encrypted at rest, R1.17, R2's key terms), and S14.4 (secrets), S14.6 (backups), S14.7
  (maintenance, `db` commands) whose code lives here.
- **Code (6,287 lines, 18 files):** `src/host.py`, `src/keys/{__init__,cli,files,master,phrase,
  secrets,welcome}.py`, `src/runtime.py`, `src/settings.py`, `src/store/{cli,copies,maintenance,
  reencrypt}.py`, `src/ui/{settings,unlock}.py`, `ui/screens/{locked,settings}.js`.
- **Tests (544 lines):** `tests/test_keys.py`, `tests/test_runtime.py`, `tests/test_unlock.py`.
- **Guides:** `ui/guides/locked.md`; `settings-keys.md`, `settings-backups.md`,
  `settings-general.md`, `settings-network.md`, `settings-email.md`, `settings-imports.md`,
  `settings-bitcoin.md`, `settings-tax-tables.md`, `settings-connector.md` (as far as S16 goes);
  the dialogs these screens open: `dialog-verify-key.md`, `dialog-remove-copy.md`,
  `dialog-copy.md`, `dialog-written-email.md`, `dialog-prune.md`, `dialog-rebaseline.md`,
  `dialog-source-key.md`. Other units read settings-links, -receipts, -storage, -prices,
  -alerts, -signup, -passwords, -sessions.
- **Cites no section:** none listed by the map for this unit.

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 2,510 lines (39%), 6 new files. New: `host.py` (191, the host commands over
the server's socket, review 2's K1/K6), `keys/cli.py` (567, the `keys` commands moved and grown),
`keys/welcome.py` (55, the welcome's phrases on offer), `store/cli.py` (104, the `db` commands),
`store/reencrypt.py` (379, the journaled re-encryption, K5), `ui/unlock.py` (125, the unlock
route). Changed most: `ui/settings.py` (+280/−46), `store/maintenance.py` (+240/−152),
`settings.js` (+212/−61), `runtime.py` (+206/−57), `test_unlock.py` (+141/−21),
`test_keys.py` (+98/−15), `locked.js` (+72/−13), `store/copies.py` (+32/−18),
`keys/master.py` (+22/−12), `settings.py` (+22/−5). Guides changed: `settings-keys.md`
(+35/−16), `settings-connector.md` (+23/−13), `locked.md` (+12/−4), `dialog-verify-key.md`
(new), `dialog-copy.md` (new), `dialog-remove-copy.md` (new), `settings-email.md`,
`settings-network.md`, `settings-bitcoin.md`, `settings-backups.md`. Read first: `reencrypt.py`,
`host.py`, `keys/cli.py`, `maintenance.py`, `ui/unlock.py`, `keys/welcome.py`, `runtime.py`.

### 3. Earlier reviews' findings in this area

Review 2 (§12.2; m8/m9 = milestone 8/9):

| Finding | What | State per review 2 | To re-check |
|---|---|---|---|
| K5 | re-encryption or rotation failing part-way leaves the server unopenable; one bad file stops it for ever; old engine after rekey; rotation reports "refused" after changing the keyring; copies re-keyed before their keyring; Forget outside the lock | done (m8 part 4: journaled, never while serving) | `reencrypt.py`, `maintenance.py`, `copies.py`, `ui/unlock.py`, `keys/cli.py` |
| K6 | `db backup` and offline `keys rotate` unguarded against the live data directory | done (m8 parts 1, 4) | `store/cli.py`, `keys/cli.py`, `host.py`, the data-directory lock |
| K9 | restore after a re-encryption opens no receipt; revives a retired phrase; links left stale | done (m8 part 4) | `maintenance.restore`, `copies.py`, files' key ids |
| K10 | the phrase leaks: sheet on stdout, the field's mask and autocorrect | done (m8 part 4) | `keys/cli.py` (tty), `locked.js` |
| K11 | rotation alone does not cut the old phrase off (requirements text) | done | S15.7 text against `rotate` |
| K13 | a changed SMTP or node host receives the stored secret | done | `ui/settings.py` (host change clears the secret) |
| K14 | re-authentication missing (price source key) | done | `ui/settings.py` routes' `recent_auth` |
| K23 | Remove copy asks only the password; Settings › Network while locked | m9 part 5 | `ui/settings.py` remove copy; the network guide |
| K25 | `verify-backup` doesn't show or compare the manifest's `made` | m9 part 5 | `store/cli.py`, `maintenance.verify` |
| C5 | a restore rewrites a before-restore folder's receipts | m9 part 5 | `copies.py` |
| C11 | an unlock counts as a phrase check | m9 part 5 | `ui/unlock.py`, Key storage's last check |
| C12 | "who confirmed" for a host command; pre-upgrade copy at the unlock | done | `host.py`, `ui/settings.py` |
| C36 | bitcoin explorer off until Settings › Bitcoin is saved | m9 part 7 (12.5.5) | `settings.py` defaults |
| A13 | keyrings name their data key by id; `keyring.next` | confirmed | `master.py`, `reencrypt.py` |
| A14 | ranges can't be read while locked | kept | `settings.py`, guide |
| A15 | each setting's bounds and defaults | confirmed | `settings.py` |

Review 1's F1 (rotation vs re-encryption), F4 (secrets wrapped under the secrets key), F6 (mail
folder), F10 (the TLS key), F12 (`keys phrase` unrecorded, Docker secrets) were
requirements-level and carried into review 2's K/C items above. Unit 06's withheld claims are
not repeated here.

### 4. Phase 1 claims and decisions on S14.4/6/7, S15, S16

None is decided yet; each is judged against the code (and both readings where open).

- **DC-2 = D2-3** (Med; needs the user): `tls` mode "for testing" (S15.1.7, S16.15) against
  the TrueNAS install. Here: what S15.1.7's caveat means for the phrase in each reading.
- **D2-3:** see DC-2.
- **D2-13** (Low): Key storage's **Test** unspecified; "read-only but for". Here: what Test does.
- **D2-15** (Low): the phrase sent from the browser by Verify key and Remove. Here: what is sent.
- **D2-17** (Low): which lockout figures the unlock uses while Settings can't be read.
- **D2-18** (Low): no bound on the phrases the welcome keeps on offer. Here: `keys/welcome.py`.
- **DC-13** (Low): the connector's file limit names one of two upload settings. Here: which
  setting the code reads (with S16.8, S16.10).
- **DC-14** (Low): the federal due date's tax tables not listed in S16.11. Here: what
  `settings.py`/Tax tables store.
- **DC-16** (Low): README's fixed hour and 48 hours vs S16.9, S16.16 settings.
- **D2-24** (Low): status words in S14, S15 (S15.6.7 "no longer").
- Also on these sections: D2-12 (mockup selects vs S16 ranges), DC-18 (secrets' version),
  D2-16 (statements up to 200 MB vs 100 MB in flight; unit 09 found U09-23), DC-1 (receipts
  over 20 MB across a link, S16.10's maximum).

### 5. Untraced candidates and uncited first-level items

- Cites no section: none given by the map.
- Uncited first-level items: **S15.1** (what is encrypted and what is plain), **S15.2**,
  **S15.5** (recovery), **S16.15**.

## Claims

### U10-1: a re-encryption interrupted just after `keyring.next` replaces the keyring makes a third data key on resume, and the database and receipts are lost

- **Kind:** bug. **Severity:** Med. **Req:** S15.7.2 ("**A journal** in the data directory
  records each step before it is taken … **Interrupted** by a stop or a crash, the
  re-encryption carries on from the journal at the next unlock, with the phrase given then,
  redoing nothing").
- **Code:** `web/server/src/moolakata/store/reencrypt.py:233-239`:
  ```text
      old_ring_path = config.data_dir / OLD
      if steps.get("keyring"):
          old_ring = master.read_keyring(old_ring_path)
          new_ring = ring
      else:
          old_ring = ring
          new_ring = master.read_keyring(nxt) if nxt.exists() else None
  ```
  `:271-278` (`if new_ring is None: new = master.new_data_key() … master.write_keyring(nxt,
  new_ring) … _step(config, j, "next", new_ring.data_key_id)`), and `:303-308`:
  ```text
      if not steps.get("keyring"):
          if not old_ring_path.exists():
              shutil.copy2(config.keyring_path, old_ring_path)
              os.chmod(old_ring_path, 0o600)
          os.replace(nxt, config.keyring_path)
          _step(config, j, "keyring", True)
  ```
  The journal's `next` step records the new data key's id, but nothing reads it back.
- **What goes wrong:** the step is taken (the rename) before it is recorded. A stop, crash or
  power cut between `os.replace` and the journal's write leaves: the keyring holding the new
  data key D2, `keyring.old` holding D1, no `keyring.next`, and a journal whose steps say
  rekeyed, secrets and receipts done but not `keyring`. At the next unlock the run takes the
  keyring (D2) for the *old* one, finds no `keyring.next`, makes a third data key D3, skips the
  database, secrets and receipts as done, and puts D3 in the keyring; then it deletes
  `keyring.old`. The database and every receipt file are under D2, which is now nowhere: the
  server refuses every unlock with "does not open with the data key", and only the backup made
  at the run's start (and receipts from the host's own backups from before the run) remain.
  The window is short (a rename and one synced write), but the loss is total and silent until
  the unlock.
- **Run:** yes, `/home/dev/.claude/jobs/b8ac83ff/tmp/u10/crash_keyring_step.py` (output
  `crash_keyring_step.txt`): `_step` made to stop at `"keyring"`; the resumed run put a new
  data key id (`6cb2…`) in the keyring where the journal's `next` was `c8a5…`, and
  `open_store` then refused; `keyring.old` was gone.
- **Remedy:** on resume, when `steps` has `next` and the keyring's `dataKeyId` equals it, the
  keyring step is done (record it and go on); never make a new data key once `next` is in the
  journal (refuse instead, naming the files). Keep `keyring.old` until the report is written
  and the store has opened.
- **Alternatives:** record `keyring` as "about to be done" before the rename, and on resume
  decide by comparing the keyring's `dataKeyId` with `next`.
- **Check:** confirmed. Read `reencrypt.py:218-332` whole: the rename at `:307` comes before the journal write at `:308`; a resume with no `keyring` step and no `keyring.next` takes `new_ring = None` (`:239`) and makes a third data key (`:271-278`), and nothing reads the journal's `next`. Ran a copy of `crash_keyring_step.py`: the keyring's id after the resume differed from the journal's `next`, `open_store` refused, `keyring.old` was gone.

### U10-2: a receipt file damaged after its first 64 KiB stops a re-encryption at every unlock, the server locked for good (K5's first case, half done)

- **Kind:** bug. **Severity:** Med. **Req:** S15.7.2 ("A receipt or a secret that opens under
  neither key is set aside and reported in Settings › Key storage, never fatal"); review 2's K5.1.
- **Code:** `web/server/src/moolakata/store/reencrypt.py:130-136` (whether a file opens is
  decided by its first chunk: `next(files.open_stream(path, key, name))`) and `:151-155`:
  ```text
          if opens(path, new_key, name):
              continue
          if opens(path, old_key, name):
              files.write(path, files.open_stream(path, old_key, name), new_key.public_key(), name)
              continue
  ```
  `keys/files.py:91-94` raises `FileError` for a later chunk that fails; nothing in
  `rewrap_files` or `run` catches it. `runtime.py:362-364` keeps only the exception's type:
  `server.unlock_error = str(e) if isinstance(e, RefuseStart) else type(e).__name__` and logs
  "the re-encryption at the unlock failed: FileError".
- **What goes wrong:** a receipt file cut short or with a flipped bit past its first 64 KiB
  (a disk error, a file restored from the host's backup half written) opens under the old key
  by its first chunk, so it is rewritten, and the rewrite raises at the damaged chunk. The run
  stops with the journal still pending, leaving a `<id>.tmp` beside the file. Every later
  unlock resumes, meets the same file and stops again: the server stays locked, the locked
  screen and the log say only "FileError", with no file named, and the only way on is to find
  and delete the file by hand. The same holds for `keys reencrypt`, an offline rotation, and a
  restore's re-wrap (`maintenance._rewrap_restored`).
- **Run:** yes, `/home/dev/.claude/jobs/b8ac83ff/tmp/u10/rewrap_damaged.py` (output
  `rewrap_damaged.txt`): a 200 KB file with one byte changed in its second chunk; `opens` said
  True, `rewrap_files` raised `FileError`, and `bbbb.tmp` was left in the folder.
- **Remedy:** in `rewrap_files`, catch `FileError` from the rewrite, remove the `.tmp`, and set
  the file aside as one that opens under neither key (reported as damaged); and log the file's
  name with any failure of the run.
- **Alternatives:** decide `opens` by reading the whole file (doubles the read time of a
  re-encryption).
- **Check:** confirmed. `opens` decides by the first chunk (`reencrypt.py:130-136`); `files.open_stream` raises `FileError` at a later bad chunk (`files.py:91-94`), and neither `rewrap_files` nor `run` catches it; `runtime._complete` (`:362-364`) keeps only the type's name. Ran a copy of `rewrap_damaged.py`: `FileError` raised, `bbbb.tmp` left beside the file. S15.7.2 says such a file is set aside, "never fatal".

### U10-3: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).
- **Check:** confirmed.

### U10-4: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).
- **Check:** confirmed.

### U10-5: a rotation writes the new keyring before its re-encryption is in the journal, so a stop between them leaves a rotation that only re-wrapped, unrecorded

- **Kind:** bug. **Severity:** Low. **Req:** S15.7.1 ("so a rotation always re-encrypts"; "The
  outcome of each is recorded in Activity with the rotation"), S15.7.2 ("**A journal** … records
  each step before it is taken, the copies' choices among them"); review 2's K5.3–4.
- **Code:** `web/server/src/moolakata/store/maintenance.py:516-531` (through the running
  server):
  ```text
      ring = master.rotated(store.keys.ring, store.keys.data_key, new_master, at)
      master.write_keyring(config.keyring_path, ring)
      new = master.Unlocked(ring.master_id, ring, store.keys.keys, store.keys.data_key)
      outcomes, later = {}, {}
      for c in copies.copies(config):
          choice = choices.get(c.name, "reencrypt")
          if choice == "delete":
              copies.remove(c)
      ...
      reencrypt.schedule(config, later, None, "rotation")
  ```
  and `keys/cli.py:306-313` (offline: `master.write_keyring(...)`, then
  `reencrypt.schedule(config, choices, None, "rotation")`, then `reencrypt.run(config,
  new_key)`). `host.py:88-93` catches only `RefuseStart`; the Activity record (`:95-103`) and
  `srv.store`'s new keyring (`:89`) come only after a clean return.
- **What goes wrong:** the server is stopped (a `docker compose restart`, an OOM kill, a power
  cut) after the keyring is written but before the journal is, or `copies.remove` raises on a
  copy chosen for deletion. The keyring is wrapped under the new phrase with the old data key,
  and no re-encryption is pending: the next unlock opens with the new phrase and re-encrypts
  nothing, so the old phrase plus any copy made before still opens everything made after.
  Nothing records the rotation (the route's Activity line and the command's host event come
  after), and `keys rotate` reports a transport error or "the server refused the rotation",
  though the keyring changed (K5.3's report, in a smaller window). The offline path is the
  same between `write_keyring` and `schedule`; there, if `run` then fails (U10-2), the command
  ends in an exception with the keyring rotated and nothing queued for Activity.
- **Run:** no; rests on reading.
- **Remedy:** write the journal first (`why: rotation`, the choices, and the new keyring as
  `keyring.next` wrapped under the new phrase), then delete the copies chosen for deletion,
  then put the keyring in place as a journaled step; record the rotation in Activity (or the
  host queue) as soon as the keyring changes, and report the outcome exactly when a later step
  fails.
- **Alternatives:** none simpler that keeps the old phrase usable until the journal exists.
- **Check:** confirmed. Read `maintenance.rotate_running:516-531` (the keyring is written before the copies loop and before `reencrypt.schedule`), `keys/cli.py:306-313` (the same order offline) and `host.rotate` (only `RefuseStart` caught; the Activity record comes after a clean return). `test_keys.py:189-199` and `test_store.py:621,735` run only rotations that finish.

### U10-6: setting SMTP security to *None* needs no password again and keeps the stored password, which then goes to the server in the clear

- **Kind:** security. **Severity:** Low. **Req:** S16.2 ("password (a secret, set with the
  password again) … Changing the host asks for the password again and clears the stored SMTP
  password"), S13.7.2, S14.4; review 2's K13.
- **Code:** `web/server/src/moolakata/ui/settings.py:46`: `REAUTH = {"smtpHost", "publicUrl"}`
  and `:57-60` (only `smtpHost` and `bitcoinNodeHost` clear their secret); `mail.py:131-139`:
  ```text
      else:
          conn = _vetted(smtplib.SMTP, address)(smtp.host, smtp.port, timeout=SMTP_TIMEOUT)
      with conn:
          conn.ehlo()
          if smtp.security == "starttls":
              conn.starttls(context=context)
              conn.ehlo()
          if smtp.username:
              conn.login(smtp.username, smtp.password or "")
  ```
- **What goes wrong:** K13's remedy protects the SMTP password against a change of *host*, but
  a change of `smtpSecurity` from STARTTLS to None (and the port to 25) is an ordinary save:
  no password again, the secret kept. The next email, or **Send a test email** at once, logs
  in with the stored password over plain SMTP, readable by anyone on the path to the
  provider. Whoever has an admin's session (the case S13.7.2's password-again guards against)
  gets the household's mail password out without ever seeing it.
- **Run:** no; rests on reading.
- **Remedy:** treat `smtpSecurity` (and `smtpPort`) like `smtpHost`: the password again, and
  the stored password cleared when security is lowered to None; or refuse AUTH over a plain
  connection unless the host is a private address.
- **Alternatives:** keep the password but refuse to send it without TLS (`login` only after
  `starttls` or on `SMTP_SSL`), so None works only for a relay that needs no login, as the
  field's hint ("None only for a relay on your own network") suggests.
- **Check:** corrected. Severity unchanged (Low). The code is as quoted (`REAUTH` and `_clear_moved_secrets` cover the host only; `mail.deliver` logs in whatever the security), but S16.2 asks for the password again only for the host, and the stored password goes only to the host already configured. A session holder alone cannot read it: the "readable" half needs a second party on the network path, and the last sentence of "What goes wrong" (the session gets the password out without seeing it) overstates. Scope it as a hardening gap beside K13: lowering the transport protection is an ordinary save with the secret kept.

### U10-7: saving Settings › Bitcoin with mempool.space, the suggested choice, never marks it saved, so no wallet is ever read

- **Kind:** bug. **Severity:** Med. **Req:** S16.7 ("No wallet is read until an admin saves
  this section (R3.5)"), S1.6.2; review 2's C36.
- **Code:** `web/server/src/moolakata/bitcoin/sync.py:43-47`
  (`chosen` is `settings.saved(s, "bitcoinSource")`, a row existing); `ui/settings.py:118-120`:
  ```text
          changed = [k for k, v in clean.items() if settings.get(s, k) != v]
          for k in changed:
              settings.put(s, k, clean[k], c.id)
  ```
  `settings.py:223-224`: the defaults are `bitcoinSource` `"esplora"` and `bitcoinEsploraUrl`
  `"https://mempool.space/api"`, exactly what `web/ui/screens/settings.js:887-893` sends for **Public:
  mempool.space**.
- **What goes wrong:** an admin opens Settings › Bitcoin, leaves the suggested mempool.space
  (or picks it) and presses Save: every value equals its default, so nothing is written, no
  `bitcoinSource` row exists, and `chosen` stays false. The toast says "Saved", the section
  looks saved, and the hourly task never reads a wallet; Blockstream, a node, or any other
  value works. A household whose first choice is the default never sees its wallets' balances.
- **Run:** yes, `/home/dev/.claude/jobs/b8ac83ff/tmp/u10/t/test_u10_bitcoin_saved.py` (run
  with `PYTHONPATH=tests uv run pytest -p conftest …`, output `bitcoin_saved.txt`): the PATCH
  the screen sends answered 200, and `settings.saved(s, "bitcoinSource")` and `sync.chosen`
  were both False.
- **Remedy:** the Bitcoin section saves through a route of its own that writes
  `bitcoinSource` whatever its value (or `change_settings` writes every key sent, not only
  those that differ from the default); a test that saving the defaults makes `chosen` true.
- **Alternatives:** make "saved" a key of its own (`bitcoinChosenAt`) written by any save of
  the section.
- **Check:** confirmed. Ran a copy of `test_u10_bitcoin_saved.py`: the PATCH answered 200, `settings.saved(s, "bitcoinSource")` and `sync.chosen` both False. `change_settings` writes only keys that differ from the default (`ui/settings.py:118-120`), and nothing else writes `bitcoinSource` outside dev seeding.

### U10-8: a failure after the database opens leaves the server neither locked nor serving, and a restore's follow-up is lost with it

- **Kind:** bug. **Severity:** Low. **Req:** S15.4.3, S15.4.5 (a refused unlock leaves the
  server locked), S15.6.8 ("At the unlock the server … reports anything it cannot open … and
  each link's copy starts again, pulled in full").
- **Code:** `web/server/src/moolakata/runtime.py:184-206`: `server.store = store` (`:186`) is
  set before `ensure_categories`, `register_tasks`, `apply_egress`, `take_host_events`,
  `after_restore`/`check_restored` and `load_copy_folders` run; `_open` (`:369-393`) sets
  `ready` only after the Activity record, `Reader(server)` and the tasks start.
  `ui/unlock.py:87-88`:
  ```text
      if srv.store is not None:
          raise Problem(409, "unlocked-already", "MoolaKata is already unlocked.")
  ```
  and `store/maintenance.py:439-447` (`after_restore` deletes `restored.json` as it reads it,
  before `check_restored` has done its work).
- **What goes wrong:** any exception after `:186` (a secret row `open_sealed` fails on with
  something other than `SecretError`, a host-events file the server's account can't unlink, a
  worker that won't start) reaches the locked screen as a 500. The server now holds the store
  but is not ready: `GET /ui/api/unlock` says locked, and every further unlock is answered
  "already unlocked"; no task runs, and only a restart gets out. When the failure is in
  `check_restored`, `restored.json` is already gone, so after the restart nothing resets the
  links' copy state or writes the restore report: the links keep the backup's
  `copyPublicKey` and `gotSeq` (review 2's K9.4 again) and nothing says what didn't open.
- **Run:** no; rests on reading.
- **Remedy:** set `server.store` only once `build` has finished (or clear it, dispose the
  engine and stop any tasks on failure, so the server is locked again with the error shown);
  remove `restored.json` only after `check_restored` has written its report and reset the
  links.
- **Alternatives:** none needed.
- **Check:** confirmed. Read `runtime.build` (`server.store` set before `ensure_categories`, the tasks, `check_restored`), `_open` (`ready` last), `ui/unlock.py:87-88`, `state` and `app.py:287` (the `Locked` middleware lets requests through once `store` is set, and `_complete` catches a failure only on the re-encryption path), and `maintenance.after_restore` (`restored.json` unlinked before `check_restored`).

### U10-9: copies the host keeps that Key storage never lists: a backup cut off part-way, a set-aside `keyring.next`, `keyring.old`

- **Kind:** differs. **Severity:** Low. **Req:** S15.6.7 ("**Know where every copy is**: the
  copies on this host are listed in Settings › Key storage, with how each opens"), S16.13,
  S14.6 (backup pruning), S15.8.2.3.
- **Code:** `web/server/src/moolakata/store/maintenance.py:192-195`:
  ```text
      part = config.backup_dir / (name + ".part")
      if part.exists():
          shutil.rmtree(part)
      part.mkdir(mode=0o700)
  ```
  `maintenance.backups` (`:221-228`) and `copies.copies` (`store/copies.py:62-64`) skip any
  name ending `.part`; `reencrypt.run` sets an unexplained `keyring.next` aside as
  `keyring.next.set-aside-<time>` (`store/reencrypt.py:224-228`) and keeps `keyring.old` while
  a run is unfinished (`:303-306`).
- **What goes wrong:** a backup stopped part-way (the server killed during the daily backup, a
  full disk) leaves `moolakata-<time>.part`, often a whole exported database, in the backup
  directory. Only a later backup with the very same second's name removes it, so it stays for
  good: never listed in Key storage or Backups, never pruned, never re-encrypted or offered for
  deletion at a rotation. After a leak, the admin deletes "every copy on this host" from the
  list and this one stays, under the old data key, in the directory the host snapshots and
  syncs. A set-aside `keyring.next` (a data key wrapped under a phrase) is likewise kept and
  never shown.
- **Run:** no; rests on reading.
- **Remedy:** remove any `.part` at the start of each backup (and at start-up); list a set-aside
  keyring in Key storage with **Remove**, as the copies are.
- **Alternatives:** list a `.part` as a copy ("cut off part-way") with **Remove**.
- **Check:** confirmed. `maintenance.backup:192-195` removes a `.part` only of the same second's name; `backups` and `copies.copies` skip every `.part`; nothing at start-up or in `prune` removes one, and a set-aside `keyring.next` is listed nowhere (`grep` of `.part` and `set-aside` across `src/`).

### U10-10: the old copy-rotation and re-encryption code is still there, unused: `copies.apply_rotation` re-wraps without re-encrypting

- **Kind:** untraced. **Severity:** Low. **Req:** — (S15.7.1 says a rotation always
  re-encrypts, which this code doesn't).
- **Code:** `web/server/src/moolakata/store/copies.py:172-176` (`rewrap`), `:179-182`
  (`data_key_of`), `:185-197` (`reencrypt`), `:225-232` (`can_open`), `:235-269`
  (`apply_rotation`, choices `rewrap`, `delete`, `leave`), `:277-301` (`apply_reencryption`);
  `store/maintenance.py:118-131` (`reencrypt`, used only by `tests/test_store.py` and
  `tests/test_receipts.py`). No module under `src/` calls any of them; `reencrypt.py` and
  `maintenance.rotate_running` replaced them.
- **What goes wrong:** nothing today; but `apply_rotation`'s `rewrap` choice is the rotation
  without re-encryption that S15.7.1 rules out, a caller added later would bring it back, and
  the tests that drive `maintenance.reencrypt` exercise a path the server no longer takes.
  `can_open` also catches every exception (`except ValueError, WrongKey, Exception`).
- **Run:** no; found by search (`grep` for each name across `src/` and `tests/`).
- **Remedy:** delete them, and move the tests onto `reencrypt.at_once`/`run`.
- **Alternatives:** none needed.
- **Check:** corrected. Severity unchanged. The `copies.py` functions are unused as the claim says (`rewrap`, `data_key_of`, `reencrypt`, `can_open`, `apply_rotation`, `apply_reencryption`, `_needs`; no caller in `src/` or `tests/` besides each other), but `maintenance.reencrypt` (`:118-131`) is not old code: it schedules and runs the journaled `reencrypt.run`, the path the server takes, so the tests that drive it do exercise it. Drop it and "move the tests" from the claim and the remedy.

### U10-11: the rotation reminder's period, which S16.13 makes Key storage's one setting, can't be changed in the browser

- **Kind:** not built. **Severity:** Low. **Req:** S16.13 ("read-only but for **Verify key** and
  the rotation reminder's period (12 months by default; off is allowed, S15.8.4)"), S15.8.4
  ("reminds admins after a configurable period").
- **Code:** `web/server/src/moolakata/settings.py:271`: `_d("keyReminderMonths", "keys", 12,
  _int(0, 120))`; `web/ui/screens/settings.js:1232-1234` (Key storage): "Read only here, but
  for Verify key. …", and the section only shows the period (`:1240-1242`, "rotation reminder
  at ${v.reminderMonths} months"); no form anywhere in `settings.js` sends `keyReminderMonths`.
- **What goes wrong:** an admin who wants the reminder off, or every 24 months, has no field
  for it; only a PATCH to the API changes it. The screen and its guide (`settings-keys.md:3`,
  "Read only, but for **Verify key**") say the same as the code, not S16.13.
- **Run:** no; rests on reading (search of `settings.js`).
- **Remedy:** a number field (months, 0 for off) in Key storage that PATCHes
  `keyReminderMonths`; the screen's line and guide say "but for Verify key and the reminder's
  period".
- **Alternatives:** drop the period from S16.13 and fix it at 12 months.
- **Check:** confirmed. No `keyReminderMonths` in `settings.js` beyond the read-only text (`:1240-1242`); S16.13 names the period as the section's one setting, and the hand-written mockup has a **Rotation reminder** select (`MoolaKata-mock.html:1656`) with its guide.

### U10-12: the household's avatar can only be initials and a colour in the browser; S16.1 and the mockup offer an image

- **Kind:** not built. **Severity:** Low. **Req:** S16.1 ("the **household name and avatar**
  (an image, or initials; …)"); the mockup's General section ("Change avatar").
- **Code:** `web/ui/screens/settings.js:110-147`: the General form edits `householdAvatar` as
  `{ kind: 'initials', initials, color }` only; `settings.py:159-174` (`_avatar`) accepts
  `{"kind": "image", "image": "data:image/…"}`, which no screen sends.
- **What goes wrong:** a household can't set its picture, which linked servers would show (S12.10);
  the API takes any `data:image/` string with no type or size check beyond the 1 MB body.
- **Run:** no; rests on reading.
- **Remedy:** an image upload in General (checked from its content as receipts' images are, a
  small fixed size, re-encoded), stored as the `image` kind.
- **Alternatives:** drop "an image" from S16.1 and the mockup.
- **Check:** confirmed. `settings.js:110-147` sends only `kind: 'initials'`; `_avatar` accepts `data:image/` with no check beyond the prefix; the mockup has **Change avatar** (`MoolaKata-mock.html:1639`); S16.1 says "an image, or initials".

### U10-13: Settings lists Linked servers and Connector before Imports; S16 puts Imports first

- **Kind:** differs. **Severity:** Low. **Req:** S16 ("In the order below, except Storage (17),
  which follows Backups, and Connector (18), which follows Linked servers": … 7 Bitcoin,
  8 Imports, 9 Linked servers, 18 Connector, 10 Receipts …).
- **Code:** `web/ui/screens/settings.js:22-40`: `… ['bitcoin', 'Bitcoin'], ['links', 'Linked
  servers'], ['connector', 'Connector'], ['imports', 'Imports'], ['receipts', 'Receipts'], …`.
- **What goes wrong:** the section list differs from the order S16 fixes (and the mockup the
  requirements follow); small, but S12.9's two mockups then disagree on it.
- **Run:** no; rests on reading.
- **Remedy:** move `imports` after `bitcoin`.
- **Alternatives:** change S16's order to the code's.
- **Check:** corrected. Severity unchanged (Low). The app's order differs from S16 as claimed (Imports after Connector; S16 has it after Bitcoin). But the claim's "the mockup the requirements follow" is wrong: the mockup's `SETTINGS_SECS` (`MoolaKata-mock.html:2823`) lists Imports before Bitcoin, so it follows neither S16 nor the app. The remedy then also moves Imports in the mockup (CLAUDE.md keeps them in step), or S16's order changes to the mockup's.

### U10-14: Settings › Alerts offers four thresholds; S16.16's 1 to 336 hours can't be chosen (D2-12 in the app)

- **Kind:** differs. **Severity:** Low. **Req:** S16.16 ("how long a source may fail before it
  raises an alert (48 hours by default, 1 to 336)"); D2-12.
- **Code:** `web/ui/screens/settings.js:306-315`: a `Select` with options `24`, `48`, `72`
  and `168` hours; `settings.py:268` checks `_int(1, 24 * 14)`.
- **What goes wrong:** an admin can't set 12 hours or two weeks from the screen; a value set
  through the API (say 100) shows in a select that has no such option. The other ranged
  settings (sessions, lockout, sizes) are number fields. Settings › Linked servers' **Release
  linked keys after** is unit 08's.
- **Run:** no; rests on reading.
- **Remedy:** a number field (hours, 1 to 336) as the other ranged settings have.
- **Alternatives:** S16.16 names the four choices.
- **Check:** confirmed. `settings.js:306-315` offers 24, 48, 72 hours and 1 week; `settings.py:268` accepts 1 to 336; S16.16 gives the range. D2-12 is confirmed in its own file.

### U10-15: `db shell` writes what a query returns to standard output, which Docker's log keeps, as the recovery sheet once did

- **Kind:** security. **Severity:** Low. **Req:** S15.1.7 ("the logs, which must never hold
  amounts, names or secrets"), S15.4.4 (the sheet "on the terminal, never on standard output,
  so that no log keeps it"), S14.7; review 2's K10.2.
- **Code:** `web/server/src/moolakata/store/maintenance.py:486-494`:
  ```text
          try:
              cur = conn.execute(buf)
              rows = cur.fetchall()
              if cur.description:
                  print(" | ".join(d[0] for d in cur.description))
              for r in rows:
                  print(" | ".join("" if v is None else str(v) for v in r))
  ```
- **What goes wrong:** `docker compose run --rm moolakata db shell` keeps the container's
  standard output in Docker's log while it runs, and for good where the daemon's log driver is
  journald, syslog or a shipper: `SELECT * FROM "Transaction"` puts payees and amounts there,
  outside the encrypted database. `keys init` and `keys rotate` moved to `/dev/tty` for this
  reason; the shell, which shows the data itself, did not.
- **Run:** no; rests on reading.
- **Remedy:** read and write the shell on the controlling terminal (`keys.cli.Terminal`), and
  refuse without one, as `keys init` does.
- **Alternatives:** say in S14.7 and `operations.md` that the shell's output is in Docker's log
  for as long as the daemon keeps it.
- **Check:** plausible. **Question:** does S15.1.7's "the logs … must never hold amounts, names or secrets" cover what an interactive `db shell` prints (the data itself, by S14.7's design), or only the server's own log? The code prints as quoted (`maintenance.py:486-494`). Remedy note: I ran a throwaway container with a tty and text written to `/dev/tty` reached `docker logs` just as standard output did, so moving the shell to `keys.cli.Terminal` would not keep it out of the log under `docker compose run` (see U10-F1).

### U10-16: a host command's event written while the server takes the queue is lost

- **Kind:** bug. **Severity:** Low. **Req:** S15.4.7 ("What a one-off command did is queued in
  the data directory and reaches Activity within a quarter of an hour"), S15.6.5.
- **Code:** `web/server/src/moolakata/store/maintenance.py:153-158`:
  ```text
      path = config.data_dir / HOST_EVENTS
      try:
          text = path.read_text()
      except FileNotFoundError:
          return []
      path.unlink()
  ```
- **What goes wrong:** a `keys verify` (or `db backup`, `db restore`) appending its line between
  the server's `read_text` and `unlink` loses it: the check never reaches Activity, so Key
  storage and the yearly alert don't count it. The window is short (every 15 minutes, a read
  and an unlink), so it is rare.
- **Run:** no; rests on reading.
- **Remedy:** rename the file to a private name first (`os.replace` to `host-events.taking`),
  then read and delete that, so an append after the rename starts a new file.
- **Alternatives:** none needed.
- **Check:** confirmed. `take_host_events:153-158` reads then unlinks; `queue_host_event` appends with `O_APPEND`, so a line appended between the two is removed unread.

### U10-17: the guides say other than the screens and sections in four places

- **Kind:** differs. **Severity:** Low. **Req:** S12.7 (each screen's guide), S16.13, S16.2,
  S15.1.7, S16.18.
- **Code and what differs:**
  1. `web/ui/guides/settings-keys.md:47`: "**Remove** deletes one, after your password", but
     Remove asks for the phrase too (`ui/settings.py:926-954`; `dialog-remove-copy.md` says so).
  2. `settings-keys.md:13-16`, "## Unlocked: When the phrase was last entered": the section
     has no such row; it shows "Last confirmed by the unlock …" under **Recovery phrase**
     (`settings.js:1308-1316`).
  3. `dialog-written-email.md:5`: the link "works once, for a day at most", but an invitation's
     works a week (S16.2, S15.1.7; `settings-email.md` says so).
  4. `settings-connector.md:58`: a Connection's driver "(Folder, OFX Direct Connect or
     Schwab)": the Folder driver was taken out (rejected idea 21).
- **Run:** no; rests on reading.
- **Remedy:** correct each line.
- **Alternatives:** none needed.
- **Check:** confirmed. Read all four: `settings-keys.md:47` against `ui/settings.py` Remove and `dialog-remove-copy.md`; `settings-keys.md:13-16` has no row on the screen (only "Last confirmed …" under Recovery phrase); `dialog-written-email.md:5` against S16.2 (invitation a week); `settings-connector.md:58` names a Folder driver, and `connector/moolakata_connector/drivers/` holds only `ofx_direct.py` and `schwab.py`.

### U10-18: no test interrupts a re-encryption past its secrets, damages a file past its first chunk, or fails a rotation part-way

- **Kind:** test gap. **Severity:** Low. **Req:** S15.7.1, S15.7.2, S16.7; review 2's K5.
- **Code:** `web/server/tests/test_store.py:297-328` interrupts only at `rewrap_files`;
  `:331-352` sets aside only a file that fails at its first chunk (`b"not sealed at all"`);
  `tests/test_keys.py:183-200` and `test_unlock.py:78-110` run rotations that succeed; nothing
  tests saving Settings › Bitcoin at its defaults, and two withheld claims have no test either.
- **What goes wrong:** U10-1, U10-2, U10-5 and U10-7 all pass the suite, as do two withheld claims.
- **Run:** no; rests on reading the tests' names and the two journal tests whole.
- **Remedy:** a test per step of `reencrypt.run` that stops after the step is taken and before
  it is recorded, and resumes; a file damaged in its last chunk; `rotate_running` failing
  after the keyring is written; Bitcoin saved at its defaults; a test with each withheld claim's fix.
- **Alternatives:** none needed.
- **Check:** corrected. Severity unchanged. "Two withheld claims" in the body is three (U10-3, U10-4, U10-21): none has a test. The rest holds: `test_store.py:297-328` crashes only at `rewrap_files`, `:331-352` sets aside only a file broken at its first chunk, `test_keys.py:189-199` and `test_unlock.py` run rotations that finish, and nothing in `test_wallets.py` saves Bitcoin at its defaults.

### U10-19: Settings › Network doesn't show how the listener runs (S16.15's one statement, uncited)

- **Kind:** not built. **Severity:** Low. **Req:** S16.14 ("The section also shows, read only,
  how the listener runs: its mode (`proxy` or `tls`), its port, and the trusted proxies'
  addresses (S13.3)"), S16.15 ("Settings › Network shows how the listener runs").
- **Code:** `web/ui/screens/settings.js:220-270` (the Network section: the three range lists
  and two notes, nothing else); no route under `ui/` returns the configuration's `mode`,
  `port` or `trusted_proxies` (search of `src/moolakata/ui/` for them finds none).
- **What goes wrong:** an admin checking whether the server runs behind the proxy it should
  (the very question D2-3 and DC-2 turn on), or which proxy address it trusts for
  `X-Forwarded-For` (which the ranges in this same section are checked against, S16.14), has
  to read `moolakata.toml` on the host. S16.15 is a first-level item no code cites, and the
  statement it makes isn't built.
- **Run:** no; rests on reading.
- **Remedy:** `GET /settings` (or a small `GET /settings/network`) adds `mode`, `port` and
  `trustedProxies` from `server.config`, and the section shows them read only.
- **Alternatives:** drop the sentence from S16.14 and S16.15.
- **Check:** confirmed. S16.14 says the section shows the mode, port and trusted proxies; `settings.js:220-270` shows none, and no route under `ui/` returns them.

### U10-20: Key storage shows the last re-encryption only when it set something aside; which copies it left is never shown

- **Kind:** differs. **Severity:** Low. **Req:** S16.13 ("the last re-encryption's progress
  and outcome, and anything that cannot be opened"), S15.7.1 ("The outcome of each is
  recorded in Activity with the rotation").
- **Code:** `web/ui/screens/settings.js:1353-1366`:
  ```js
    v.lastReencryption &&
      (v.lastReencryption.receiptsSetAside.length || v.lastReencryption.secretsSetAside.length)
      ? html`
  ```
  `ui/settings.py:701-713` (`_last`) sends `finishedAt`, `why` and `copies` (each copy's
  outcome), which the screen never shows.
- **What goes wrong:** after a rotation's re-encryption the admin sees nothing in Key storage:
  not when it finished, nor that a copy was "left: needs the phrase of mk-…" or left,
  which is what S15.7.1.4 asks them to act on (keep the previous phrase,
  delete the copy). Activity has it, as a count-free detail.
- **Run:** no; rests on reading.
- **Remedy:** always show the last re-encryption (when, why) with each copy's outcome, and mark
  the ones left under an old key.
- **Alternatives:** none needed.
- **Check:** corrected. Severity unchanged (Low). "Which copies it left is never shown" overstates: the copies list shows how each copy opens (`opensWith`, `settings.js:1125-1135`: "needs a previous phrase", "an earlier data key"), so copies still under an old key are visible. What is missing is as quoted: `lastReencryption`'s time, reason and per-copy outcome are shown only when something was set aside (`:1353-1366`), against S16.13's "the last re-encryption's progress and outcome".

### U10-21: withheld

- **Kind:** security. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).
- **Check:** confirmed.

### U10-22: Verify key counts wrong phrases against fixed figures, not Settings › Sign-in and sessions (D2-17's other half)

- **Kind:** differs. **Severity:** Low. **Req:** S15.6.5 ("a wrong phrase counts toward the
  lockout, as at the unlock"), S13.7.5.1, S16.3 ("the lockout of an address after failed
  sign-ins (10 failures, 3 to 100, for 15 minutes, 1 to 1,440)"); D2-17.
- **Code:** `web/server/src/moolakata/ui/settings.py:748` and `:754`:
  `guard.failed(LOGIN, address)`, with `ratelimit.SignInGuard.failed`'s defaults
  `threshold: int = 10, lock_minutes: int = 15`; Remove copy counts through
  `session.count_failure` (`ui/settings.py:944-946`), which reads `lockoutFailures` and
  `lockoutMinutes`.
- **What goes wrong:** with the server unlocked, Settings can be read, yet an admin who set the
  lockout to 3 failures for a day gets 10 for 15 minutes on Verify key, while Remove (the same
  phrase, the next button) follows the setting. At the unlock itself the fixed figures are
  D2-17's proposed reading (the defaults while locked), which the code follows.
- **Run:** no; rests on reading.
- **Remedy:** Verify key passes the settings' figures (`count_failure`, or
  `guard.failed(LOGIN, address, failures, minutes)` read from the database); S16.3 says the
  unlock uses the defaults (D2-17's remedy).
- **Alternatives:** none needed.
- **Check:** confirmed. `ui/settings.py:748,754` call `guard.failed(LOGIN, address)` with the defaults (`ratelimit.py:123-125`), Remove goes through `count_failure` with the settings' figures; S15.4.2 and S15.6.5 name the lockout of S13.7.5.1, whose figures S16.3 sets, and Settings is readable here.

### U10-23: the generic settings PATCH writes state the server keeps for itself: the Electrum certificate pin unchecked, and the certificate key told to linked servers

- **Kind:** bug. **Severity:** Low. **Req:** S1.6.2.4 (the certificate confirmed from what
  Test showed), S16.7, `link-protocol.md` §4.5; R3.7 (every key checked before any is saved).
- **Code:** `web/server/src/moolakata/settings.py:229-237`: `bitcoinNodeCert`,
  `bitcoinNodeCertOffered` (`_optional_text(64)`) and `linkCertificate` are `DEFINITIONS`
  like any admin setting, so `PATCH /ui/api/settings` (`ui/settings.py:73-136`) writes them;
  the dedicated route checks the pin as 64 hex digits (`ui/settings.py:364-370`), the PATCH
  takes any text of up to 64 characters. `links/manage.py:174-188` sends the certificate
  announcement only when `linkCertificate` differs from the key in use.
- **What goes wrong:** a PATCH (a script, or a screen built later over `values`) can set the
  Electrum pin to text that matches no certificate, so every read fails "another certificate",
  or clear `bitcoinNodeCertOffered` so the change alert closes unconfirmed; setting
  `linkCertificate` to the current key after a change means the peers are never told of it
  (the case U08-11 describes, by another way).
- **Run:** no; rests on reading.
- **Remedy:** keep these three out of `DEFINITIONS` (a table or keys of their own that only
  their routes and tasks write), or mark them internal so `coerce` refuses them in the PATCH.
- **Alternatives:** none needed.
- **Check:** confirmed. `bitcoinNodeCert`, `bitcoinNodeCertOffered` and `linkCertificate` are plain `DEFINITIONS` (`settings.py:229-237`), `coerce` has no internal marker, and `change_settings` writes any defined key; the dedicated route's 64-hex check (`ui/settings.py:364-370`) is bypassed, and `announce_certificate` compares against the stored `linkCertificate` (`links/manage.py:174-188`).

## Earlier findings re-checked

- **K5** (re-encryption or rotation failing part-way): half holds. The journal, the set-aside of
  files and secrets under neither key, the refusal by name of a run pending under another
  phrase, and never running while serving are built. Still open: a file that opens by its first
  chunk but fails later stops the run at every unlock (**U10-2**); the step that puts the new
  keyring in place is taken before it is recorded, and a stop there loses the data key
  (**U10-1**); a rotation writes its keyring before its journal and reports a failure after it
  changed (**U10-5**, K5.3 in a smaller window). K5.2 (old engine after the rekey) no longer
  applies; K5.4 holds (a copy's keyring is written aside first, `copies.reencrypt_with`); K5.5
  holds (Forget under `maintenance_lock`).
- **K6** (host commands against the live directory): holds. `db backup` goes over the socket or
  takes the lock and opens read only with nothing pending run; offline `keys rotate`,
  `keys reencrypt` and `db restore` take the lock; an unexplained `keyring.next` is set aside.
- **K9** (restore after a re-encryption): holds, with **U10-8** beside it (the links' reset and
  the report are lost if the first unlock fails after taking `restored.json`).
- **K10** (the phrase leaking): holds for the sheet (`/dev/tty`, refused without a terminal) and
  the locked screen's field; **U10-15** is the same leak for `db shell`'s output.
- **K11**: the requirements now make every rotation re-encrypt and the code schedules it; but a
  rotation's re-encryption can be lost (**U10-5**).
- **K13**: holds for the host (a new SMTP or node host clears the stored password);
  **U10-6** is a new case beside it (security lowered to None).
- **K23**: holds (Remove asks for the phrase; Network's text says the proxy limits the locked
  screen).
- **K25** (`verify-backup` and the manifest's `made`): holds (`made_of`, shown and compared).
- **C5**: holds (a restore leaves the receipts in place); `copies.reencrypt_with` still rewrites
  a `before-restore-*/receipts/` that no restore makes any more (harmless).
- **C11**: holds (`key.unlocked` counts in Key storage and the yearly alert).
- **C36**: holds in the code (`sync.chosen` is "saved"), but saving the default never saves
  (**U10-7**).
- **A13, A14, A15**: as they stand; A15's bounds match `settings.py`.

## Phase 1 claims judged against the code

- **DC-2 / D2-3** (`tls` mode for testing vs the TrueNAS catalog): the code has nothing that
  depends on the reading; under either, the phrase at the locked screen crosses the `tls/` pair
  S15.1.7 calls plain, and Settings › Network doesn't show the mode at all (**U10-19**). Left to
  the walk-through.
- **D2-12** (selects for ranges): in the app, sessions, lockout, sizes and backups are number
  fields as S16 says; Alerts is a select (**U10-14**); jobs 1–4 matches S16.10.
- **D2-13** (Key storage's Test): the code checks that the keyring on disk is the one unlocked,
  that the database opens and that one secret opens, and writes only an Activity line, which
  is D2-13's remedy.
- **D2-15** (the phrase from the browser): Verify key and Remove send it, as D2-15's remedy
  would write into S15.3.1.
- **D2-17**: the unlock uses the fixed defaults (D2-17's proposed reading); Verify key does too
  while Settings is readable (**U10-22**).
- **D2-18**: the welcome keeps 20 phrases for an hour each (`keys/welcome.py:131-132`), the
  connector's figures, D2-18's proposed reading.
- **D2-24**: S15.6.7's "no longer carries the key" is still in the text; nothing in the code.
- **DC-13**: the connector's files are limited by Settings › Imports (`connector/files.py:67`,
  `importMaxMb`), DC-13's proposed reading; the request cap is the larger of the two limits.
- **DC-14**: the federal due date is in the tax tables as month and day
  (`projections/taxtables.py:44-45`, "Federal return due (month, day)"), a later year taking
  the latest's: DC-14's proposed reading; S16.11 doesn't list it.
- **DC-16**: the code reads both as settings (`linkReleaseMinutes`, `alertSourceHours`), the
  S16 reading.
- **DC-1** (S16.10's 100 MB): `receiptMaxMb` is 1–100 as S16.10 says; what crosses a link is
  unit 08's (U08-1).
- **DC-18**: not judged here (secrets' rows are `store/repos/secrets.py`, outside this unit).

## Uncited first-level items

- **S15.1** (what is encrypted): built under other words: SQLCipher keyed from the database key
  (`maintenance.open_store`), receipt files (`keys/files.py`), each secret (`keys/secrets.py`),
  backups as copies of the encrypted database with its keyring; the mail folder and `tls/` plain.
- **S15.2** (no external key service, no key file): built in the negative; no key file, no
  automatic unlock, nothing reads a key from the environment or configuration.
- **S15.5** (losing the phrase): S15.5.1's restore and the report at the unlock
  (`maintenance.restore`, `runtime.check_restored`), S15.5.2's rotation through the running
  server with no old phrase (`host.rotate`, `maintenance.rotate_running`) are built.
- **S16.15**: its one statement (Network shows how the listener runs) is not built: **U10-19**.

## Checked and sound

- Key hierarchy: 128-bit master from `os.urandom`, HKDF-SHA256 labels as S15.3.2, AES-256-GCM
  wrap with a random 96-bit nonce and the master's id as associated data; key ids and
  fingerprints as S15.3.5 (`keys/master.py`).
- The BIP39 encoding: checksum, 4-letter prefixes, the word list's SHA-256 pinned
  (`keys/phrase.py`).
- Secrets: a fresh data key and nonce per secret, wrapped under the secrets key, associated data
  naming type, id and field; a re-encryption gives each a fresh data key (`keys/secrets.py`).
- The streaming file format: per-chunk nonce with counter and last flag, the name and counter as
  associated data, truncation at a chunk boundary caught (`keys/files.py`).
- The recovery sheet and the three words typed back on `/dev/tty` only, refused without one
  (`keys/cli.py` `Terminal`); `keys unlock` reads with `getpass`.
- The data directory lock (`flock`) held by the server and taken by restore, offline backup,
  offline rotate and `keys reencrypt`; files written 0600 in 0700 directories; keyrings written
  atomically and synced.
- The host socket's directory made 0700 and refused when another account owns it; the socket
  0600 (`host.py`).
- Backups: verified, HMAC-signed manifests under a key derived from the data key, the name
  checked against `made`, a restore under an earlier phrase named and asked, a newer revision
  refused (`store/maintenance.py`).
- The unlock: wrong and invalid phrases counted and logged with the address; a pending
  re-encryption under another phrase refused by name; the master key not kept in `Unlocked`.
- The welcome's phrases: held in memory, 20 at most for an hour, cleared once one is confirmed;
  the keyring written only after three words.
- Re-authentication on the SMTP and node passwords, the SMTP host and public URL, Network's
  ranges, Re-encrypt, Remove, Forget and written emails' Open (`ui/settings.py`).
- Settings' checks and bounds (`settings.py`) against S16's figures.

## Read lightly or not read

- `web/ui/screens/settings.js`'s Prices section (S16.6) and the sections other units read
  (Linked servers, Connector, Storage): skimmed only.
- `tests/test_keys.py` and `tests/test_unlock.py`: by test name and a few bodies; the two
  journal tests in `tests/test_store.py` read whole.
- `store/copy.py` (export, verify, rekey) and `store/migrate.py`: outside the unit, read only
  where called.

## Work pad: severity, confirmations, status

| Id | Kind | Req | Sev | Conf | Status | Description |
|---|---|---|---|---|---|---|
| U10-1 | bug | S15.7.2 | Med | 0 | open | A re-encryption stopped just after `keyring.next` replaces the keyring makes a third data key on resume: database and receipts lost |
| U10-2 | bug | S15.7.2 | Med | 0 | open | A receipt file damaged past its first 64 KiB stops the re-encryption at every unlock; the server stays locked (K5 half holds) |
| U10-3 | security | S15.7.2, S15.7.1, S15.8.2 | Med | 0 | open | Withheld (`withheld.md`) |
| U10-4 | security | S15.7.1, S16.13, S13.7.2 | Med | 0 | open | Withheld (`withheld.md`) |
| U10-5 | bug | S15.7.1, S15.7.2 | Low | 0 | open | A rotation writes the new keyring before its journal: a stop between leaves a rotation that only re-wrapped, unrecorded |
| U10-6 | security | S16.2, S13.7.2 | Low | 0 | open | SMTP security set to None needs no password again and sends the stored password in the clear |
| U10-7 | bug | S16.7, R3.5 | Med | 0 | open | Saving Settings › Bitcoin with mempool.space, the default, never marks it saved: no wallet is ever read |
| U10-8 | bug | S15.4.5, S15.6.8 | Low | 0 | open | A failure after the database opens leaves the server neither locked nor serving, and loses a restore's follow-up |
| U10-9 | differs | S15.6.7, S16.13 | Low | 0 | open | A backup cut off part-way (`.part`) and a set-aside `keyring.next` stay on the host, never listed or pruned |
| U10-10 | untraced | — | Low | 0 | open | The old copy rotation and re-encryption functions are unused; `apply_rotation` re-wraps without re-encrypting |
| U10-11 | not built | S16.13, S15.8.4 | Low | 0 | open | The rotation reminder's period can't be changed in the browser |
| U10-12 | not built | S16.1 | Low | 0 | open | The household avatar can only be initials and a colour; S16.1 and the mockup offer an image |
| U10-13 | differs | S16 | Low | 0 | open | Settings lists Linked servers and Connector before Imports |
| U10-14 | differs | S16.16, D2-12 | Low | 0 | open | Settings › Alerts offers four thresholds; 1 to 336 hours can't be chosen |
| U10-15 | security | S15.1.7, S14.7 | Low | 0 | open | `db shell` prints query results to standard output, which Docker's log keeps |
| U10-16 | bug | S15.4.7 | Low | 0 | open | A host command's event appended while the server takes the queue is lost |
| U10-17 | differs | S12.7, S16.13, S16.2, S16.18 | Low | 0 | open | Four guide lines say other than the screens and sections (Remove's phrase, Unlocked, a week's invitation, the Folder driver) |
| U10-18 | test gap | S15.7.1, S15.7.2, S16.7 | Low | 0 | open | No test stops a re-encryption at its keyring step, damages a later chunk or fails a rotation part-way |
| U10-19 | not built | S16.14, S16.15 | Low | 0 | open | Settings › Network doesn't show the listener's mode, port and trusted proxies |
| U10-20 | differs | S16.13, S15.7.1 | Low | 0 | open | Key storage shows the last re-encryption only when it set something aside, never which copies it left |
| U10-21 | security | S16.13, S13.7.2, S14.6 | Med | 0 | open | Withheld (`withheld.md`) |
| U10-22 | differs | S15.6.5, S16.3, D2-17 | Low | 0 | open | Verify key counts wrong phrases against fixed 10 / 15 minutes, not Settings › Sign-in |
| U10-23 | bug | S1.6.2.4, S16.7 | Low | 0 | open | The settings PATCH writes the Electrum pin unchecked and the certificate key told to peers |

Totals: 23 claims. High 0; Med 6 (U10-1, U10-2, U10-3, U10-4, U10-7, U10-21); Low 17. By kind:
bug 7, differs 6, security 5 (U10-3, U10-4, U10-21 Med and withheld; U10-6, U10-15 Low),
not built 3, untraced 1, test gap 1. None needs the user (DC-2 left to the walk-through).

Scratch runs: `/home/dev/.claude/jobs/b8ac83ff/tmp/u10/` (`rewrap_damaged.py`/`.txt`,
`crash_keyring_step.py`/`.txt`, `t/test_u10_bitcoin_saved.py` with `bitcoin_saved.txt`).

## Found while checking

Unverified: nothing here enters the review on the word of the context that found it (REVIEW.md §8).

### U10-F1: withheld

- **Kind:** security. **Severity:** Low as found, unverified; withheld until the sweep rates it
  (`withheld.md`, REVIEW.md §2).

### U10-F2: the host events queue is removed before its events are recorded, so a failed record loses them

- **Kind:** bug. **Severity:** Low. **Req:** S15.4.7 ("What a one-off command did is queued … and
  reaches Activity within a quarter of an hour").
- **Code:** `web/server/src/moolakata/store/maintenance.py:151-158` unlinks the file as it
  reads it; `web/server/src/moolakata/runtime.py:307-322` records the events afterwards in
  `with server.db.tx() as s:`.
- **What goes wrong:** an error in the record (a locked or full database, a failed write) after
  the unlink loses every queued event: a `keys verify` never reaches Activity, so Key storage
  and the yearly alert do not count it, and nothing says it was lost.
- **Run:** no; rests on reading.
- **Remedy:** rename the file to a private name, record, then delete the renamed file (this
  also closes U10-16's window).
- **Alternatives:** none needed.
