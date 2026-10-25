# Code review 3, unit 06: receipts-storage

**Session:** Oct 24, 09:11 PM to 09:26 PM (Chicago). **Commit read:** `6916954`. **Scope:** full.
**Checking:** quick (no §8 checker; every claim at 0 confirmations, status open).

## Brief (docs/REVIEW.md §7)

### 1. Sections, code and tests (map.md)

- **Sections:** S9 (receipts: upload S9.1, storage S9.2, links S9.3, viewing S9.4, thumbnails
  S9.5, sharing S9.6, deletion and retention S9.7, reading S9.8: text layer and OCR, models,
  the worker's sandbox S9.8.4, text and search S9.8.5, reading again S9.8.6, Settings ›
  Receipts S9.8.7) and S14 (storage and secrets: the database layer S14.1, receipt files'
  ownership S14.2, money in cents S14.3, secrets S14.4, the master key S14.5, backups S14.6,
  `db shell` S14.7, the user's export S14.8 (L4), time zones S14.9, retention and pruning
  S14.10), with the README lines they rely on (R1.9 money never a float, R1.12 receipts are
  files, R1.13 encrypted at rest, R1.17 the reader sandboxed, R1.24 nothing removed, R2.14
  file types).
- **Code (9,412 lines, 51 files):** `src/receipts/` (`__init__` 577, `ocr` 207, `parser` 196,
  `reading` 340, `retention` 339, `worker` 155), `src/sandbox.py` 179, `src/parsing.py` 178,
  `src/clock.py`, `exactjson.py`, `ids.py`, `money.py`, `paths.py`, `timezones.py`;
  `src/store/` (`db.py`, `copy.py`, `mapping.py`, `migrate.py`, `types.py`, `views.py`,
  `schema_check.py`, `entities/{__init__,core,receipts}.py`, `tables/{__init__,_base,core,
  receipts}.py`, `repos/secrets.py`, `alembic/env.py`, `script.py.mako`); migrations 0001
  (3,022 lines, read against `schema.md` by search), 0002, 0006, 0010–0016, 0020, 0024–0027;
  `src/ui/receipts.py` 550; `ui/components/receipt.js` 345, `ui/components/storage.js` 333,
  `ui/screens/receipts.js` 86.
- **Tests (1,736 lines):** `test_ids_money.py`, `test_reading.py`, `test_receipts.py`,
  `test_retention.py`, `test_store.py`, `test_timezones.py`.
- **Guides:** `receipts.md`, `settings-receipts.md`, `settings-storage.md`,
  `dialog-receipt.md`, `dialog-statement*.md` (as far as the receipt file goes),
  `linked-receipts.md` (the receipts screen's linked view).
- **Cites no section** (judged when read): `src/ids.py`, `src/paths.py`,
  `src/store/schema_check.py`, `src/store/views.py`, `ui/screens/receipts.js`.

### 2. Delta since review 2 (`294792b`..`6916954`)

Content changed: 1,866 lines (19%); 11 new files. New whole: `sandbox.py` (179),
`parsing.py` (178), `receipts/worker.py` (155), `timezones.py` (138), migrations 0015, 0016,
0020, 0024–0027, `tests/test_timezones.py`. Changed most: `receipts/reading.py` (+125/−66),
`ui/receipts.py` (+109/−16), `receipts/__init__.py` (+95/−6), `tests/test_store.py`
(+349/−62), `test_reading.py` (+88), `store/db.py` (+24), `ocr.py` (+23/−9),
`tables/core.py` (+19), `entities/core.py` (+12), `mapping.py` (+9), `receipt.js` (+13/−5),
`retention.py` (+6/−1). The rest is the rename. Read first: the sandbox, the worker and
parsing (milestone 8 part 3 and milestone 9 part 5, never reviewed), the reading changes, and
the receipts routes.

### 3. Earlier reviews' findings in this area

Review 2 (§12.2 marks each done unless said):

| Finding | What | State per review 2 | To re-check |
|---|---|---|---|
| K4 | the reader's worker no sandbox; hostile files parsed in the server; HEIC/thumbnails in the request; 40 Mpx cap on PDF pages | done (part 3, part 5) | sandbox.py, worker.py, ocr.py, ui/receipts.py |
| K9 / C2 | a receipt file's header names no key; restore after re-encryption | done | retention / copies (unit 10 holds copies) |
| K19 | a read error's `detail` can hold a host path (`ui/receipts.py`) | done | ui/receipts.py |
| K25 | uploads spooled in memory, `/tmp` tmpfs | done (part 5) | upload route |
| P3 | attaching needs write on the receipt | done | `receipts.to_attach` |
| N13 | tax docs, gifts, donations through `ReceiptLink` | done | `receipts.level` kinds |
| B39 / C1 | Settings › Receipts said receipts go into backups | done | settings-receipts.md, settings.js text |
| C3 | prune keeps a file while a deleted receipt names it | done (part 5) | retention.py prune_files |
| C31 | `money.py` docstring said strings | done | money.py |
| B23 | money columns as decimal text | done (0024, 0026) | tables, migrations |
| B28 | the server's zone in the container | done | timezones.py |

Review 1: F4 and its C2/C3 (S14.4 against S15.3.3), F11 (plaintext over a pipe): documents,
done. C1 (OCR text crosses a link): documents.

### 4. Phase 1 claims and decisions on S9 and S14

- **D1-25** (Med, needs the user): who sees a tax document's file (filers only by S9.6, or
  helpers by S8.14.3/S10.3), and S9.6 says nothing of receipts on items, loans, 529
  expenses and statements. U04-14 has judged the tax-document half; here: the other kinds.
- **D1-13** (Med, needs the user): who owns a category; U05-20 judged the category routes;
  here: who sets **Keep receipts for** (S14.10.1.1 says an admin, in Settings › Storage).
- **D3-21** (Low, needs the user): `schema.md` §3.2's "not declared yet" list (`Posn`).
- **DC-12** (Low): a local receipt file's key label and associated data are unstated; judge
  what the code writes against both readings.
- **D2-20** (Low): S14.1.5 cites `schema.md` "(S1)", S14.10 says no record is removed though
  sessions and tokens are pruned.
- **D2-24** (Low): status words in S14.1.3 ("Until the first release …").
- **DC-6** (Low): S14.3's half-even except tax rules vs a loan's half-up interest; U02 judged
  the loan code (follows S1.9.2); here only `money.py`'s context.
- **DC-1** (Med): receipts over ~20 MB across a link: unit 08's; noted only.
- **DC-5 / DC-9** (schema's queues and counters): noted where the store's tables are read.
- **DC-15** (daily emails' zone): S14.9 against operations; noted.

### 5. Untraced candidates and uncited first-level items

- Untraced candidates: `src/ids.py`, `src/paths.py`, `src/store/schema_check.py`,
  `src/store/views.py`, `ui/screens/receipts.js`.
- Uncited first-level items: **S14.2** (receipt files' owner and modes), **S14.5** (the master
  key), **S14.8** (the user's export, L4): built under other words, scheduled, or not built.

## Claims

### U06-1: withheld

- **Kind:** privacy. **Severity:** Med. Withheld (`withheld.md`, REVIEW.md §2).
- **Check:** confirmed.

### U06-2: an upload holds the database's write lock while the worker draws its thumbnail, so one slow file fails every other write for up to a minute

- **Kind:** bug. **Req:** S9.5 (thumbnails made on upload, in the reader's worker), S9.8.4.2
  ("a hostile or broken file cannot take down the server"), S14.1.4 (`Database.tx()` is
  `BEGIN IMMEDIATE`, 10-second busy timeout).
- **Code:** `web/server/src/moolakata/ui/receipts.py:326-327`:
  ```text
      with srv.db.tx() as s:
          stored = receipts.store(s, srv, c.id, file.filename or "receipt", data)
  ```
  and `receipts/__init__.py:177-188`, inside that transaction:
  ```text
      r = Receipt(
          ...
          # Drawn in the reader's worker, never here (S9.5, S9.8.4.2).
          thumbnail=_parsing().thumbnail(data, media),
  ```
  `parsing._call` (`parsing.py:20-27`) waits on the one quick worker's lock, starts the worker
  if it isn't running (`reading.py:84`, up to 120 s for its hello), and gives the job
  `LIMIT = 60` seconds. `store/db.py:95` opens every `tx()` with `BEGIN IMMEDIATE`, and
  `BUSY_MS = 10_000` (`store/db.py:16`). The same holds for a statement kept by an import
  (`ui/imports.py:925`) and by the connector (`connector/files.py:142`).
- **What goes wrong:** Alice uploads a PDF whose first page takes the worker 50 seconds to draw
  (a page of millions of vector paths; or any file while the quick worker is busy decoding a
  large HEIC photo for someone's viewer, `ui/receipts.py:499`, or reading an OFX import). For
  those 50 seconds her upload holds the write lock; every other write on the server (Bob's
  transaction edit, a price refresh, a session's touch, the reading queue's own
  `read_one`) waits 10 seconds and fails with *database is locked*, a 500. A first upload after
  a start also pays the worker's start-up inside the lock. The reading queue was kept out of
  requests for this reason (S9.8.4); the thumbnail brings it back.
- **Run:** no, reading alone (the timings are the code's limits, not measured).
- **Remedy:** draw the thumbnail before the transaction (the bytes and type are known), or after
  it, in the reading queue's job, storing it with what was read; keep `files.write` before the
  transaction too, with the orphan check (S14.6) cleaning up a file whose row never commits.
- **Alternatives:** keep it in the request but outside the transaction, with a short limit
  (5 s) for thumbnails, so a slow one is skipped and drawn later by the queue.
- **Check:** corrected. Holds, with a wider consequence; severity unchanged (Med). `upload` is
  `async def` (`ui/receipts.py:314`) and calls `db.tx()` and `receipts.store` with no `await` or
  thread hand-off, so the worker's draw (up to 60 s, 120 s cold) also stands the event loop still:
  new requests aren't dispatched until it ends, and only writers already in the threadpool or the
  reading queue's threads fail on the 10 s busy timeout. The same remedy fixes both.

### U06-3: withheld

- **Kind:** security. **Severity:** High. Withheld (`withheld.md`, REVIEW.md §2).
- **Check:** confirmed.

### U06-4: one worker reads every user's files in turn, so a file that takes it sees the household's later files and can answer with them

- **Kind:** privacy. **Req:** S9.8.4.2 (the worker as a sandbox "for a file that exploits the
  libraries that read it"), S10 (a user sees only what is theirs).
- **Code:** `web/server/src/moolakata/parsing.py:20-27`:
  ```text
  def _call(op: str, data: bytes, **params) -> dict:
      global _worker
      from .receipts.reading import Worker

      with _lock:
          if _worker is None:
              _worker = Worker(_data_dir)
          return _worker.call(op, data, LIMIT, **params)
  ```
  one process for every thumbnail, HEIC view, OFX and CSV of every user, kept until it crashes
  or times out; the reading queue's workers likewise (`reading.py:204-209`, one `Worker` per
  thread for the server's life, restarted only after a failure, `reading.py:111-141`).
- **What goes wrong:** Alice uploads a receipt crafted to exploit the HEIC decoder; the code it
  runs stays in the quick worker and keeps each later request's bytes: Bob's OFX download,
  Carol's photos. When Alice next uploads a CSV, the worker's `csv-propose` answer carries
  Bob's transactions as its sample rows (500 cells of 500 characters pass `propose_csv`'s
  checks), or a later receipt's OCR lines carry Carol's statement text, which is stored as
  Alice's receipt text and shown to her. Nothing in the server can tell. Only an exploit
  makes this possible, which is the threat S9.8.4.2 is written for.
- **Run:** no, reading alone.
- **Remedy:** a fresh worker for each file brought by a different user than the last (or for
  every file in the reading queue, where a minute's job dwarfs the start), and for imports;
  the quick jobs may keep one worker per user.
- **Alternatives:** restart every worker after N files or M minutes, which narrows the window
  without closing it.
- **Check:** confirmed. Read `parsing._call` (one global `_worker` for every quick job of every
  user, replaced only after a failure or `use_data_dir`) and `Reader.start`/`_loop` (one `Worker`
  per thread for the server's life); nothing restarts a worker between users, and `propose_csv`
  passes up to 8 rows of 500 cells of 500 characters.

### U06-5: on an x86_64 kernel with the x32 ABI, the seccomp filter lets a network socket through

- **Kind:** security. **Req:** S9.8.4.2 ("a seccomp filter denies it network sockets").
- **Code:** `web/server/src/moolakata/sandbox.py:79-86`:
  ```text
              ins(ld, 0, 0, 4),  # 0: the call's architecture
              ins(jeq, 1, 0, arch),  # 1: ours: on to 3
              ins(ret, 0, 0, SECCOMP_RET_ERRNO | errno.EPERM),  # 2
              ins(ld, 0, 0, 0),  # 3: the call's number
              ins(jeq, 0, 1, io_uring_nr),  # 4: io_uring_setup: refused at 5
              ins(ret, 0, 0, SECCOMP_RET_ERRNO | errno.EPERM),  # 5
              ins(jeq, 1, 0, socket_nr),  # 6: socket: on to 8
              ins(ret, 0, 0, SECCOMP_RET_ALLOW),  # 7: anything else
  ```
- **What goes wrong:** x32 system calls arrive with the x86_64 architecture and the number with
  bit 30 set (`socket` is `0x40000000 + 41`). On a kernel built with `CONFIG_X86_X32_ABI` and
  x32 enabled, code a hostile file runs in the worker calls `socket(AF_INET, …)` through the
  x32 entry: the number isn't 41, so step 7 allows it, and the worker has the network S9.8.4.2
  denies it (to fetch more code, or send what it read out). Most distribution kernels ship x32
  off, so this is a hardening gap rather than an open door.
- **Run:** no, reading alone (this host's kernel has no x32 to try).
- **Remedy:** after loading the number, refuse anything at or above `0x40000000` (the usual
  `JGE 0x40000000 → ERRNO` line), so only native calls are judged.
- **Alternatives:** an allow-list filter of the calls the four libraries need, which closes
  this and more besides.
- **Check:** confirmed. Read `sandbox._filter`: the architecture word is checked, then the number
  compared with 41 and 425 exactly, so an x32 call (arch x86_64, number `0x40000000 | 41`) reaches
  the allow at step 7; the usual bit-30 refusal is absent. Low stands: x32 is off in most kernels.

### U06-6: *Read again* on a pruned receipt leaves it *Reading…* for good

- **Kind:** bug. **Req:** S9.8.6 (**Read again** queues the job), S9.8.4.4 (a receipt that fails
  is marked *couldn't read it*), S14.10.5 (a pruned record keeps its row).
- **Code:** `web/server/src/moolakata/ui/receipts.py:392-396` queues any receipt the caller can
  write, pruned or not:
  ```text
      with srv.db.tx() as s:
          r, lvl = receipts.get(s, c.id, receipt_id, "write")
          if not settings.get(s, "readReceipts"):
              raise Problem(409, "reading-off", "Reading receipts is off in Settings › Receipts.")
          reading.read_again(s, r)
  ```
  and `receipts/reading.py:242-248` skips it without changing its state:
  ```text
              if (
                  r is None
                  or r.deleted
                  or r.filePrunedAt is not None
                  or r.readStatus not in ("waiting", "reading")
              ):
                  return
  ```
  The dialog offers the button on a pruned receipt (`web/ui/components/receipt.js:219`,
  `canEdit && !reading`). `Reader.start` (`reading.py:195-203`) queues every `waiting` receipt
  again at each start, to the same end.
- **What goes wrong:** an admin prunes an expired receipt; its owner opens it and presses
  **Read again**: it answers 200 with `readStatus: waiting`, and the receipt shows *Reading…* in
  the grid, the dialog and the Receipts toolbar's count for ever.
- **Run:** yes, `tmp/u06/t/test_u06.py::test_read_again_on_a_pruned_receipt`: `POST
  /receipts/{id}/read` gives `waiting`, and `Reader.read_one` leaves it `waiting`.
- **Remedy:** refuse *Read again* on a pruned receipt (409 `file-pruned`, as the file route's
  410), hide the button with the file, and have `read_one` mark a pruned one `failed` with "its
  file was pruned" rather than return.
- **Check:** confirmed. Read the route, `reading.read_again` and `read_one`'s early return;
  `receipt.js:182-221` shows the button on a pruned receipt (the toolbar sits outside the
  `filePrunedAt` branch). Ran the claim's scratch test (copy): *Read again* answers 200 `waiting`,
  and `read_one` leaves it `waiting`.

### U06-7: deleting an account makes a lot's receipt expire from the buy's date at once, not from the deletion

- **Kind:** wrong figure. **Req:** S14.10.2 ("at the latest end of the records it is attached
  to"), `schema.md` §6.2 ("A deleted record's own end is the earlier of its declared end and its
  `effectiveDeletedAt`").
- **Code:** `web/server/src/moolakata/receipts/retention.py:117-121, 128-132`:
  ```text
  def _deleted(row, end: dt.date | None) -> dt.date | None:
      if row.deletedAt is None:
          return end
      gone = row.deletedAt.date()
      return gone if end is None else min(end, gone)
  ```
  ```text
      end: dt.date | None = t.date
      for lot in ctx.s.scalars(select(Lot).where(Lot.transactionId == t.id)):
          lot_end = ctx.lot_ends(t.accountId).get(lot.id, t.date)
          end = None if lot_end is None or end is None else max(end, lot_end)
      end = _deleted(t, end)
  ```
  Only the row's own `deletedAt` is read, never its `effectiveDeletedAt` (the account's
  deletion, through `TransactionEffective`); and `lot_ends` replays the deleted account, whose
  lots `live()` leaves out (`store/repos/ledger.py:73`), so an open lot's end falls back to the
  buy's date.
- **What goes wrong:** Alice's brokerage account holds a 2020 buy of VTI, still open, with its
  trade confirmation attached (category kept 2 years): *Kept while the lot is open*. On
  Mar 1, 2033 she deletes the account (it moved to another broker). The receipt at once shows
  *Expired Jan 2022, prunable*, and the next prune removes it. By §6.2 it ended with the
  deletion and is kept until Mar 2035.
- **Run:** yes, `tmp/u06/t/test_u06.py::test_a_lot_in_a_deleted_account`: before the delete
  `('open', 'Kept while the lot is open')`, after it `('expired', 'Expired Jan 2022, prunable')`.
- **Remedy:** read each record's end through its `Effective` view: the end is the earlier of the
  declared end (none for an open lot) and `effectiveDeletedAt`; an item in a deleted account
  likewise.
- **Check:** confirmed. Read `retention._transaction`, `_deleted` and `lot_ends`, and `schema.md`
  §6.2 (an open lot, with no declared end, ends when effectively deleted). Ran the scratch test
  (copy): `('open', 'Kept while the lot is open')` before the account's deletion, `('expired',
  'Expired Jan 2022, prunable')` after.

### U06-8: the test of review 2's C3 (a deleted receipt doesn't keep a file) can't fail: both uploads are one receipt

- **Kind:** test gap. **Req:** S14.10.5 ("A file several receipts share is removed once no live
  receipt needs it (a deleted one doesn't count)"), S9.7; review 2's C3.
- **Code:** `web/server/tests/test_retention.py:180-188`:
  ```text
      first = upload(c, png((9, 8, 7))).json()["id"]
      second = upload(c, png((9, 8, 7))).json()["id"]
      with server.db.tx() as s:
          a, b = s.get(Receipt, first), s.get(Receipt, second)
          assert a.fileId == b.fileId, "one file for the same bytes"
          b.mark_deleted(None)
  ```
  The same user's second upload of the same bytes gives back the first receipt
  (`receipts/__init__.py:153-162`; `test_receipts.py:73-74` asserts it), so `a` and `b` are one
  row: the test deletes the receipt it then prunes, and never has a live receipt beside a
  deleted one.
- **What goes wrong:** if `prune_files` counted deleted rows again (C3's old fault), this test
  would still pass: nothing holds the rule.
- **Run:** no, reading alone (the identity follows from `store`'s same-owner rule).
- **Remedy:** the second upload by another user (or a second receipt row made directly), the
  other's receipt deleted, then the first pruned and the file asserted gone; and a case where
  a live other receipt keeps the file.
- **Check:** confirmed. `test_retention.py:180-188` uploads the same bytes twice as one user, and
  `test_receipts.py:73-74` asserts the second upload returns the first receipt, so `a` and `b` are
  one row; with C3's old fault `prune_files` would still find no row, since the one row has
  `filePrunedAt` set.

### U06-9: file pruning removes files before its transaction commits, and prunes the rows it finds again, not the count the admin typed

- **Kind:** bug. **Req:** S14.10.5 (asks the admin to type the count; each record keeps its row
  and shows *File pruned*).
- **Code:** `web/server/src/moolakata/ui/settings.py:1136-1153`:
  ```text
      with srv.db.read() as s:
          rows = retention.prunable(s, body.categories)
      if not rows:
          raise refuse("categories", "nothing-to-prune", "No expired files in what is ticked.")
      if body.count != len(rows):
          raise refuse("count", "count-mismatch", f"Type {len(rows):,} to prune them.")
      with srv.db.tx() as s:
          rows = retention.prunable(s, body.categories)
          freed = retention.prune_files(s, srv.config.receipts_dir, rows, c.id)
          activity.record(
  ```
  and `receipts/retention.py:333-336` unlinks each file inside that transaction:
  ```text
          p = file_path(receipts_dir, file_id)
          try:
              freed += p.stat().st_size
              p.unlink()
  ```
- **What goes wrong:** (1) the files are gone before `activity.record` and the commit; if
  either fails (the database busy past its 10 s, a full disk), the rows roll back to *not
  pruned* while their files no longer exist, and each such receipt's file answers 500
  *can't be read*, its retention still showing *Expired …, prunable*. (2) The count is checked
  against one read and the rows pruned are found again in the write: a category's period
  shortened by another admin, or midnight passing, between the two prunes more files than
  the admin typed.
- **Run:** no, reading alone.
- **Remedy:** find the rows once inside the transaction and refuse when their count isn't the
  one typed; mark them and commit first, then remove the files whose receipts are all pruned
  (a removal that fails leaves a file the orphan count or a later prune picks up).
- **Check:** confirmed. Read `ui/settings.py:1126-1153` (the count checked against a `read()`
  transaction, `prunable` run again inside the write) and `retention.prune_files` (`p.unlink()`
  before the transaction commits and `activity.record` runs); the file route answers 500 for a
  missing file of an unpruned row.

### U06-10: after a prune, an identical file uploaded again by two people is stored twice

- **Kind:** bug. **Req:** S9.2 ("Identical files are stored once, found by the hash in the
  database").
- **Code:** `web/server/src/moolakata/receipts/__init__.py:163-170`:
  ```text
      any_row = s.scalars(select(Receipt).where(Receipt.sha256 == digest)).first()
      path = None
      if any_row is not None:
          file_id = any_row.fileId
          path = file_path(server.config.receipts_dir, file_id)
      if path is None or not path.exists():
          file_id = secrets.token_hex(16)
  ```
  `first()` takes any row with the hash, pruned or not (the oldest, by id); when its file was
  pruned, a new file is written even though another row's file holds the same bytes.
- **What goes wrong:** Alice's receipt X is pruned (its file F1 removed). She uploads X again:
  a new receipt over a new file F2, as S14.10.5 says. Bob then uploads X: `any_row` is Alice's
  pruned row, F1 is missing, and a third file F3 is written beside F2. Each later prune or
  re-upload can add another.
- **Run:** yes, `tmp/u06/t/test_u06.py::test_a_third_copy_after_a_prune`: three file ids, two
  `.mkr` files on disk for one content.
- **Remedy:** look for a row with the hash whose file is not pruned (`filePrunedAt IS NULL`,
  deleted or not) before writing a new file.
- **Check:** confirmed. Read `receipts.store`: `.first()` takes any row with the hash, pruned or
  not, and writes a new file when that row's file is gone. Ran the scratch test (copy): three file
  ids for Alice's, her re-upload and Bob's upload, two `.mkr` files on disk.

### U06-11: a receipt's merchant is never matched against the payees its owner already has

- **Kind:** not built. **Req:** S9.8.2.5.3 ("**merchant**: from the top lines, normalised by
  the user's payee rules (S2.7) and matched against payees they already have").
- **Code:** `web/server/src/moolakata/receipts/reading.py:299-303`:
  ```text
      if values["payee"]:
          # The merchant as the uploader's payee rules show it (S2.7.7, S9.8.2.5.3).
          from ..store.repos.rules import Rules

          values["payee"] = Rules(s, r.ownerId).rename(values["payee"])
  ```
  The rules are applied; nothing compares the result with the owner's existing payees
  (`parser.find_merchant`, `parser.py:171-185`, returns the top line as it is, title-cased when
  all capitals). The only use of payees is the match score's word overlap
  (`receipts/__init__.py:560, 565-573`).
- **What goes wrong:** the reader gives *Blue Bottle Coffee #042* → *Blue Bottle Coffee*;
  Alice's transactions say *BLUE BOTTLE COFFEE SF*, and with no rule for it the receipt's payee
  stays as read, so her receipts and transactions name one merchant two ways, and search by
  her payee name misses the receipt.
- **Run:** no, reading alone.
- **Remedy:** after the rules, pick the owner's existing payee (from her transactions' payees)
  that the read name best matches above a threshold (word overlap, as `_alike`), and keep the
  read name otherwise.
- **Alternatives:** S9.8.2.5.3 drops "matched against payees they already have", leaving the
  rules to do it.
- **Check:** confirmed. Read `save_reading`, `Rules.rename` (rules only) and
  `parser.find_merchant`; nothing compares the merchant with the owner's existing payees, and
  `_alike` at `receipts/__init__.py:560` ranks a transaction match, it never renames the merchant.

### U06-12: a receipt can't be kept with a loan, other than as an imported statement

- **Kind:** not built. **Req:** S9.3 ("a receipt can be attached to … loans (a closing
  disclosure, a statement)").
- **Code:** `web/server/src/moolakata/store/tables/receipts.py:76-79`:
  ```text
      CheckConstraint(
          "kind IN ('transaction', 'account', 'item', 'expense', 'gift', 'donation')",
          name="kind",
      ),
  ```
  A loan's documents could ride on `account` (the loan is an account), but
  `receipts.attach_account` is called only for statements, by an import
  (`ui/imports.py:935`) and the connector (`connector/files.py:146`); no route attaches an
  uploaded receipt to an account or loan, and the loan screens offer none.
- **What goes wrong:** Alice uploads her mortgage's closing disclosure: she can attach it to a
  transaction (the closing's), an item (the house, S1.10) or nothing; not to the loan, as S9.3
  promises, so it isn't found from the loan and its retention isn't the loan's.
- **Run:** no, reading alone.
- **Remedy:** `POST /loans/{id}/receipts` (or `/accounts/{id}/receipts`) attaching with kind
  `account`, a detach beside it, and the loan's Overview listing its documents; retention for
  a non-statement document on an account follows the loan's end (paid off) rather than the
  statements' period.
- **Alternatives:** S9.3 names loans only for their statements, and a closing disclosure goes
  on the house's item.
- **Check:** confirmed. Read the `kind` CHECK, every caller of `attach_account` (the import and
  the connector, both statements only) and the attach routes (`to_attach` callers: transactions,
  gifts, donations, items, expenses, tax documents); none attaches an uploaded receipt to an
  account or loan, and S9.3 names a closing disclosure.

### U06-13: *Jobs at a time* changes nothing until a restart, and receipts uploaded while reading was off are never read when it comes back on

- **Kind:** differs. **Req:** S9.8.7 (Settings › Receipts: **Read receipts** on or off, the
  number of jobs at a time), S9.8.4.1 (an upload queues the receipt).
- **Code:** `web/server/src/moolakata/receipts/reading.py:190-209`: the thread count is read
  once, when the reader starts at the unlock:
  ```text
          with self.server.db.read() as s:
              n = self.count or settings.get(s, "receiptReadJobs")
  ```
  nothing calls `Reader.start` or `stop` when the setting changes (`runtime.py:390-392` is
  the only start). And `receipts/__init__.py:187` stores an upload made while reading is off as
  `"off"`, which nothing queues again when it is turned on (only *Read again* or *Re-read all*).
- **What goes wrong:** an admin on a Raspberry Pi raises *Jobs at a time* from 1 to 2 for a
  batch of 300 receipts: the queue keeps one thread until the server restarts (which locks it
  until someone types the phrase). An admin who turned reading off for a week of heavy imports
  turns it back on: the week's receipts stay unread, with no *Reading…* or failure to say so,
  and the guide (`settings-receipts.md`) says neither.
- **Run:** no, reading alone.
- **Remedy:** a change of `receiptReadJobs` stops and starts the reader's threads (the queue's
  ids kept); turning **Read receipts** on queues every `off` receipt not pruned.
- **Alternatives:** the guide says the number applies from the next start, and turning reading
  on asks whether to read what came in meanwhile.
- **Check:** confirmed. `Reader.start` reads `receiptReadJobs` once and `runtime.py:390-392` is
  the only caller (`grep` of `reader`); `store()` stores `off` and only `read_again` and
  `reread_all` queue it again; `settings-receipts.md` says nothing of either.

### U06-14: statements go through the receipt reader: *Re-read all* reads a scanned one's first 3 pages and gives it an amount, and one kept by the connector waits *Reading…* until a restart

- **Kind:** bug. **Req:** S9.8.6 (only empty or OCR-suggested fields are replaced), S1.3.3.2
  (a statement read to 30 pages within five minutes), S9.8.4.1.
- **Code:** `web/server/src/moolakata/ui/settings.py:505-510` marks every receipt row
  `waiting`, statements kept on accounts included:
  ```text
          for r in s.query(Receipt).filter(
              Receipt.deleted.is_(False), Receipt.filePrunedAt.is_(None)
          ):
              r.readStatus, r.readError = "waiting", None
  ```
  and `receipts/reading.py:259` reads each as a receipt, `worker.read(data, media)` with the
  default 3 pages (`ocr.MAX_PAGES`) and 60 s; `save_reading` (`:289, 304-309`) replaces
  `text` and fills the empty `amount` with the parser's total (the largest amount when no
  TOTAL line). A statement the connector keeps (`connector/files.py:142-146`) is stored by
  `receipts.store` as `waiting` and never queued (only `ui/receipts.py:332, 400` and
  `ui/settings.py:517` queue), so it waits for `Reader.start` at the next unlock.
- **What goes wrong:** a scanned 12-page bank statement imported by photo has its 12 pages'
  text; after **Re-read all receipts** it has 3 pages' text (search misses the rest) and an
  amount of, say, $14,210.55 (its largest figure), so its dialog proposes attaching it to a
  transaction of that size. A statement the connector fetched shows *Reading…* in the grid for
  days, then is OCR'd as a receipt.
- **Run:** no, reading alone.
- **Remedy:** the reader knows a statement (a receipt with an `account` link, or a flag set
  when it is kept) and reads it as one (`pages=ocr.STATEMENT_PAGES`, `STATEMENT_TIME_LIMIT`),
  filling no amount; a statement kept without reading is stored `read` (or `off`), not
  `waiting`.
- **Check:** confirmed. Read `reread_all` (every unpruned row `waiting`, statements included),
  `read_one` (`worker.read(data, media)`, the default 3 pages and 60 s) and `save_reading` (fills
  an empty `amount`); the connector's `receipts.store` leaves `waiting` with no queueing, while
  the import path sets `read` when it has lines.

### U06-15: a PDF with a text layer on one page is never OCR'd on its scanned pages

- **Kind:** differs. **Req:** S9.8.2.1 ("A page counts as having a text layer when it gives at
  least 20 characters"), S9.8.2.2 (scanned PDFs are rendered and OCR'd).
- **Code:** `web/server/src/moolakata/receipts/ocr.py:159-164`:
  ```text
          texts = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
      finally:
          pdf.close()
      if not any(len(t.strip()) >= TEXT_LAYER_CHARS for t in texts):
          return None
      return [ln.strip() for t in texts for ln in t.splitlines() if ln.strip()]
  ```
  One page with 20 characters makes the whole file a text-layer read.
- **What goes wrong:** an emailed invoice whose first page is a typed cover letter and whose
  second is the scanned receipt: the reader keeps the letter's text only, finds no total, and
  the scan is never read or searchable. A requirement that judges per page reads page 2 by OCR.
- **Run:** no, reading alone.
- **Remedy:** per page: take a page's text layer when it has 20 characters, else render and
  OCR that page (within the page cap), and keep the method as `text`, `ocr` or both.
- **Alternatives:** S9.8.2.1 says the file is read from its text layer when any page has one.
- **Check:** plausible. **Question:** for a PDF where only some pages have a text layer (20
  characters), is the whole file read from the text layer, or is each page judged and the scanned
  ones OCR'd? The code does the first (`ocr.text_layer`: `any(...)` over the pages); S9.8.2.1 says
  "a page counts as having a text layer", but S9.8.2.1-2 speak of "a PDF with a text layer" and
  "scanned PDFs" as whole files and don't address a mixed one.

### U06-16: Settings › Storage leaves deleted receipts' files out of its groups, and nothing can ever remove them

- **Kind:** differs. **Req:** S14.10.4 (the size of the receipts directory and a pie of expired,
  expiring later and kept for ever), S14.10.2 (a file attached to nothing never expires),
  S9.7 ("a deleted receipt doesn't keep it from file pruning").
- **Code:** `web/server/src/moolakata/receipts/retention.py:257-260` and `:308`, both
  `select(Receipt).where(Receipt.deleted == false())`:
  ```text
      out = Storage(_dir_bytes(receipts_dir), Group(), Group(), Group(), 0)
      years: dict[int, dict[str, Group]] = defaultdict(lambda: defaultdict(Group))
      seen_files: set[str] = set()
      for r in s.scalars(select(Receipt).where(Receipt.deleted == false())):
  ```
  while `orphan_files` (`:286-291`) counts only files no row names, "deleted rows included".
- **What goes wrong:** Alice uploads 40 mistaken 25 MB scans and deletes
  them (nothing links to them). Their 1 GB stays in *Receipts and statements* (the directory's
  size) but in no part of the pie, so the pie's three parts add up to less than the size shown,
  and no button frees it: not prunable (deleted rows aren't looked at), not an orphan (a row
  names it). By S14.10.2 such a file is *kept for ever* and belongs in that part; by S9.7 it
  shouldn't hold its file at all.
- **Run:** no, reading alone.
- **Remedy:** count a file named only by deleted receipts in its own group (*Deleted receipts,
  can be removed*) and let the prune remove it like an expired one (the rows stay, marked
  *File pruned*).
- **Alternatives:** count them under *Kept for ever* and say in S14.10.2 that a deleted
  receipt's file stays until the receipt is restored or for good.
- **Check:** confirmed. Read `retention.storage`, `prunable` and `orphan_files` (both loops filter
  `deleted == false()`, the orphan check names every row's file), `receipts.delete` (marks
  deleted, never unlinks) and `prune_files`: a file only deleted receipts name is in no group and
  no prune reaches it, short of a live receipt of the same bytes being pruned.

### U06-17: comments and docstrings still state rules the requirements changed

- **Kind:** differs. **Req:** S14.10.5 (a deleted receipt doesn't keep a file; no backup is made
  before pruning), S9.7.
- **Code:**
  1. `web/server/src/moolakata/receipts/__init__.py:14-15`: "Its file stays while any receipt row
     names it, deleted or not (schema.md §4)." (`prune_files` does the opposite, rightly.)
  2. `web/server/src/moolakata/receipts/retention.py:3-4`: "file pruning, which removes expired
     files after a verified backup" (`ui/settings.py:1131-1133` makes none, rightly).
  3. `web/server/tests/test_retention.py:1-3`: "pruning after a verified backup".
  4. `web/server/src/moolakata/store/tables/receipts.py:83-84`: "A virtual table, made by
     revision 0007" (it is made in 0001, `0001_the_initial_schema.py:3018`; 0007 is
     `strategies`).
  5. `web/server/src/moolakata/receipts/__init__.py:11-13`: who sees a receipt is "its owner
     always, and whoever can read an account one of its transactions is in", which leaves out
     the gifts, donations, items, expenses, statements and tax documents `level` handles.
  6. `web/server/src/moolakata/money.py:23-26`, seen by a client: `parse` is "A decimal from its
     JSON form, a string", and refuses with "amounts are decimal strings, such as "1234.50""
     (review 2's C31 fixed the module's docstring only; R1.9 and S13.8.2 say exact number
     literals, which `exactjson.loads` reads as `Decimal`).
- **What goes wrong:** a reader of the code (or the next fix) takes the old rule for the rule:
  review 2's C3 came from exactly such a reading.
- **Run:** no, reading alone.
- **Remedy:** correct the six texts (the refusal: "amounts are exact numbers, such as 1234.50").
- **Check:** confirmed. Read each of the six places: the two docstrings and the test's, the `0007`
  comment (`ReceiptSearch` is created at `0001_the_initial_schema.py:3018`; 0007 is strategies),
  the owner/transaction sentence against `level`, and `money.parse` (accepts `Decimal` and `int`,
  refuses with "decimal strings").

### U06-18: S14.1.2 says the mapping includes relationships; it maps none

- **Kind:** differs. **Req:** S14.1.2 ("`store/mapping.py` maps each one onto its table
  (`registry.map_imperatively`), relationships included").
- **Code:** `web/server/src/moolakata/store/mapping.py:59-73, 81-173`: every call is
  `mapper_registry.map_imperatively(entity, table, …)` with no `properties=` and no
  `relationship()`; every join is written as a query.
- **What goes wrong:** nothing at run time; a reader of S14.1.2 looks for relationships that
  aren't there, and a new entity's author may add one where the code's habit is a query.
- **Run:** no, reading alone.
- **Remedy:** S14.1.2 reads "maps each one onto its table (`registry.map_imperatively`); what
  records belong to is read by queries".
- **Check:** confirmed. `mapping.py` has only `map_imperatively` calls (`_map`, `_versioned`) and
  no caller passes `properties` or builds a `relationship()` (`grep` over `store/`).

### U06-19: the receipts guide narrows who sees a receipt and what *All* lists

- **Kind:** differs. **Req:** S9.6 (a receipt is seen through every kind it is kept with: a
  transaction, a gift's plans, a donation's giving plan, a tax book's filers), S9.3.
- **Code:** `web/ui/guides/receipts.md:16-18`: "**All** your receipts, and those attached to
  transactions in accounts shared with you"; `:28-31`: "A receipt is seen by whoever can read a
  transaction it is attached to." And `web/server/src/moolakata/receipts/__init__.py:329-391`
  (`visible`) lists the owner's receipts and those on transactions, statements (`account`),
  items and expenses in readable accounts, but not those seen through a gift, a donation or a
  tax document, which `level` (`:222-251`) lets the same user open.
- **What goes wrong:** Bob, a co-filer, opens Alice's W-2 from the tax book, and a gift's receipt
  from a shared gift plan; neither is in his Receipts screen's *All*, and the guide says
  neither should be visible at all, while statements and item photos shared with him are listed
  though the guide names only transactions.
- **Run:** no, reading alone.
- **Remedy:** decide whether *All* lists every receipt the user can open (then `visible` adds
  gifts, donations and tax documents) or those of accounts only; the guide says which, and its
  *Sharing* paragraph follows S9.6.
- **Check:** confirmed. Read the guide's *Show* and *Sharing*, `visible` (own, transaction,
  statement, item and expense links in readable accounts; no gift, donation or tax document) and
  `level`, which opens those three; the guide and the list each narrow S9.6 in their own way.

### U06-20: no test holds S14.2's modes for receipt files and their directory

- **Kind:** test gap. **Req:** S14.2 ("owned by the server's account, mode 0600 in a 0700
  directory").
- **Code:** `web/server/src/moolakata/keys/files.py:102-104` builds it:
  ```text
      path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
      tmp = path.with_suffix(".tmp")
      fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
  ```
  but no test checks a receipt file's or `receipts/`'s mode (`grep 0o600|0o700` in the tests
  finds the keyring, the queued host commands, a pre-upgrade copy and the socket only), and
  `mkdir(…, exist_ok=True)` leaves an existing directory's mode as it was.
- **What goes wrong:** a change to the writer (or a `receipts/` made by an image or restore
  with 0755) goes unnoticed; the files stay encrypted, so what leaks is sizes, times and count.
- **Run:** no, reading alone.
- **Remedy:** a test that uploads a receipt and asserts 0600 on the file and 0700 on
  `receipts/`; `files.write` sets the directory's mode when it differs, as `host.prepare` does
  for the socket's.
- **Check:** confirmed. `files.write` makes the directory 0700 (when it makes it) and the file
  0600; `grep` of the tests for `0o600|0o700|st_mode|S_IMODE` finds only the keyring, the queued
  host commands, a pre-upgrade copy and the socket.

### U06-21: a statement imported by a write sharer stays his receipt, seen in full after the share ends

- **Kind:** privacy. **Req:** S9.6 ("Sharing follows what the receipt is attached to"; silent on
  statements, Phase 1's D1-25), S1.3.3 (the statement "kept as a receipt on the account"),
  S10 (removing a share ends what it showed). **Needs the user**, with D1-25.
- **Code:** `web/server/src/moolakata/ui/imports.py:925` (unit 01's, noted there for this unit):
  ```text
      stored = receipts.store(s, srv, c.id, held.fileName or "statement.pdf", held.data)
  ```
  makes the importer the receipt's owner, and `receipts/__init__.py:226-227` gives an owner
  everything, whatever the account:
  ```text
      if r.ownerId == user_id:
          return "owner"
  ```
- **What goes wrong:** Alice gives Bob write on her checking account to help with the
  bookkeeping; he imports twelve monthly statements. In March she removes his share: her
  transactions disappear from his screens, but the twelve statement PDFs and their full text
  stay in his Receipts (*All*, his own), searchable, and he can still open each. Alice, the
  account's owner, can't delete them (only their owner can), and Activity names Bob as their
  uploader. Under D1-25's proposed reading (a statement is seen by whoever can read the
  account) the account decides; under the code's, the importer keeps a copy for good.
- **Run:** no, reading alone.
- **Remedy:** a kept statement is owned by the account's owner (`account.ownerId`), with
  `linkedById` naming the importer, as the connector's path does with the connection's owner
  (`connector/files.py:142`).
- **Alternatives:** keep the importer as owner but have `level` give an `account`-linked
  receipt only the account's level to anyone but the account's owner.
- **Check:** plausible. **Question:** when a user with write on an account imports its statements,
  does he own those receipts (and keep them after his share ends), or does the account's owner?
  S9.6 and S1.3.3 are silent. The code does what the claim says (`_keep_file` stores them under
  the importer, `level` gives an owner everything, only the owner deletes), and it is the same
  question as D1-25.

### U06-22: writing a job to the worker has no deadline, so a worker that stops reading hangs its caller and every quick job behind it

- **Kind:** security. **Req:** S9.8.4.2 ("restarted after a crash or a timeout, so a hostile or
  broken file cannot take down the server").
- **Code:** `web/server/src/moolakata/receipts/reading.py:120-126`:
  ```text
          head = json.dumps({"op": op, **params, "length": len(data)}).encode()
          try:
              stdin = self.proc.stdin
              stdin.write(len(head).to_bytes(4, "big") + head + len(data).to_bytes(4, "big"))
              stdin.write(data)
              stdin.flush()
              out = self._recv(time.monotonic() + limit)
  ```
  The deadline and memory watch start only in `_recv`; a blocking write of up to 110 MB into
  the pipe (64 KiB of buffer) waits as long as the worker doesn't read. `parsing._call`
  (`parsing.py:24-27`) holds the quick worker's lock across it.
- **What goes wrong:** code a hostile file runs in the worker (or a worker wedged in a library
  call between jobs) stops reading its stdin. The next upload's thumbnail blocks in `write`
  with no limit, holding `parsing._lock`: every later thumbnail, HEIC view, OFX and CSV import
  waits behind it for good, and with U06-2 the first of them holds the database's write lock
  too. Nothing restarts the worker, since no deadline passes.
- **Run:** no, reading alone.
- **Remedy:** write through `select` on the pipe (non-blocking) under the same deadline as the
  answer, killing the worker when it passes.
- **Check:** confirmed. Read `Worker.call`: `stdin.write` and `flush` run before `_recv`, the only
  place the deadline and memory watch live, and `parsing._call` holds `_lock` across `call`; a
  worker that stops reading blocks the writer in the pipe for good (the reading queue's own worker
  only blocks its thread).

### U06-23: `parsing.MAPPING_KEYS` is used nowhere

- **Kind:** untraced. **Req:** —.
- **Code:** `web/server/src/moolakata/parsing.py:141-146`:
  ```text
  MAPPING_KEYS = {
      "delimiter",
      "skipRows",
      "negateAmounts",
      "dateFormat",
  }
  ```
  No module reads it (`grep -rn MAPPING_KEYS` finds only this). `propose_csv` (`:149-178`)
  checks the worker's proposed mapping by type and length, not by these keys.
- **What goes wrong:** nothing at run time; it reads as a check of the mapping's keys that
  doesn't run, so a worker's proposal may carry any key the browser then sends back.
- **Run:** no, reading alone.
- **Remedy:** check the proposal's keys against it (with the column keys the mapping also
  carries), or remove it.
- **Check:** confirmed. `grep -rn MAPPING_KEYS` over the repository (outside the review's files)
  finds only the definition at `parsing.py:141`; `propose_csv` checks the mapping's types and
  lengths, not its keys.

## Phase 1 items judged against the code

- **D1-25** (who sees a receipt kept on something other than a transaction; tax documents are
  U04-14's): items, 529 expenses and statements give whoever reads the account read (write for
  write) through `receipts.level` (`receipts/__init__.py:234-248`), and `visible` lists them:
  the code matches D1-25's proposed reading (the account decides), which S9.6 leaves unsaid. A
  statement's owner is its importer, not the account's owner (U06-21, needs the user with
  D1-25). Gifts and donations follow S9.6 (`_kept_level`).
- **D1-13** (who sets **Keep receipts for**): `PATCH /categories/{id}` is an admin's and changes
  only `keepReceiptsYears` (`ui/transactions.py:984-992`, U05-20), reached from Settings ›
  Storage (`components/storage.js:200-271`): S14.10.1.1 as written, under every reading of
  who owns a category.
- **D3-21** (`schema.md` §3.2 *Reserved*): no `Position` table; `schema_check.check_metadata`
  (`store/schema_check.py:53-63`) reads §3.2 as a standing list (a table under it fails as
  "still under Reserved"). The code is consistent with either reading; the wording is the
  document's.
- **DC-12** (a local receipt file's label and associated data): `keys/files.py:31, 49-50, 56-60`
  derives the file key under `moolakata receipt` and binds each chunk to `"{fileId}\x1f{n}"`,
  with a last-chunk flag in the nonce: exactly DC-12's proposed remedy. Only the document is
  missing it.
- **D2-20** (S14.10's "never removed" against the prunes): `repos/secrets.py:44-49` removes a
  secret's old ciphertext outright, as `schema.md` §4.4.2 says; the code follows `schema.md`.
- **DC-6** (half-even except tax rules): `money.py:7-10` sets `HALF_EVEN` at 34 digits; the
  loans' half up is U02's (it follows S1.9.2).
- **D2-24**, **DC-1**, **DC-5**, **DC-9**, **DC-15**: documents, or other units' code; nothing
  here contradicts them.

## Earlier findings re-checked

| Finding | State (review 2) | Holds? |
|---|---|---|
| K4 (worker no sandbox; parsing in the server; HEIC and thumbnails in the request; PDF pages uncapped) | done | yes: every file is parsed in the worker (`parsing.py`, `worker.py:75-113`), length-prefixed JSON checked field by field (`reading.py:143-163`, `parsing.py:74-178`), seccomp and Landlock applied before reading (`worker.py:59-68`), pages and images capped at 40 Mpx (`ocr.py:167-174, 199-201`, `receipts/__init__.py:75-106`). New holes beside it: U06-5 (x32), U06-22 (write without deadline), U06-4 (one worker for every user) |
| K19 (a read error's `detail` names a host path) | done | yes: `ui/receipts.py:505-511` logs the reason with an error id; the reader stores only the exception's type (`reading.py:261`, `worker.py:111-112`) |
| P3 (attaching needs write on the receipt) | done | yes: every attach route calls `receipts.to_attach` (`ui/receipts.py:421`, `gifts.py:737`, `giving.py:690`, `items.py:634`, `education.py:473`, `taxes.py:920`) |
| N13 (gifts, donations, tax documents through links) | done | yes for gifts and donations (`ReceiptLink` kinds, `_kept_level`, `detach_kept`); tax documents keep `TaxDocument.receiptId` and `level` reads it (U04-14 for who) |
| B39 / C1 (Settings › Receipts said receipts go into backups) | done | yes: `settings-receipts.md:3-4` and `screens/settings.js:1096` say backups hold the database alone |
| C3 (pruning kept a file while a deleted receipt named it) | done | the code holds (`retention.py:322-330`); its test can't fail (U06-8) |
| C31 (`money.py` said strings) | done | half: the module's docstring is fixed; `parse`'s docstring and refusal still say strings (U06-17, 6) |
| B23 (money as decimal text) | done | yes: 0024 and 0026 convert the last columns; no money-named column outside `Cents` remains but prices and quantities (`Dec`) and `TaxFigure.value` (a figure, text) |
| B28 (the server's zone in the container) | done | this unit's part holds: `timezones.zone_from` reads `TZ`, then what `/etc/localtime` holds (`timezones.py:19-47`); the mount is unit 11's |
| K9 / C2 (restore after a re-encryption) | done | unit 10's code (`store/reencrypt.py`, `copies.py`); here only that `runtime.py:212-240` reports receipts the restored keys can't open |
| K25 (uploads in memory) | done | the receipt route reads the upload into memory (`ui/receipts.py:321`); `test_an_upload_is_held_in_memory` holds it; the tmpfs check is unit 09's |

## The uncited first-level items and the untraced candidates

- **S14.2** (receipt files' owner and modes): built under other words in `keys/files.py:102-104`
  (0600 file, 0700 directory on creation); no test (U06-20).
- **S14.5** (the master key): built in unit 10's `keys/` (phrase, master, keyring); nothing here
  stores it. Not a claim.
- **S14.8** (a user's export): later work L4; not built, as scheduled. Not a claim.
- `src/ids.py`: `schema.md` §2's ids (UUIDv7, Crockford base-32, the prefix); traced through
  S14.1's "the schema follows `schema.md`".
- `src/paths.py`: the app's own files (the UI, `VERSION`, the mockup for `/demo`, S12.9 and
  S17); traced.
- `src/store/schema_check.py`: `schema.md` §5's checks, which S14.1 says a test enforces;
  traced.
- `src/store/views.py`: `schema.md` §4.2's `<Table>Effective` views (S14.1.5); traced.
- `ui/screens/receipts.js`: the Receipts screen (S9.1, S9.4, S9.8.5's search); traced.
- New untraced found: `parsing.MAPPING_KEYS` (U06-23).

## Checked and sound

- `keys/files.py`'s stream format as receipts use it: a one-time X25519 key per file, HKDF with
  a random salt, a 7-byte random nonce prefix with counter and last-chunk flag, the file id and
  chunk number as associated data; truncation at a chunk boundary, reordering and a file copied
  under another id all fail to open; files written to a temporary name, synced and renamed.
- `read_file` checks the plaintext's SHA-256 against the row; the file route serves the sniffed
  type, `inline` with a RFC 5987 file name, `CSP: sandbox`, `no-store`, and `nosniff` from the
  middleware (`middleware.py:27`); a pruned file answers 410.
- Type sniffing from the first bytes for the five types, and a CHECK on `mediaType` in the table.
- Deduplication per owner (same owner gets their receipt, 200; another gets their own over one
  file); a pruned receipt's re-upload is a new receipt with its file (S14.10.5).
- `level`, `to_attach`, `detach`, `detach_kept`, `delete`: attaching needs write on the receipt
  and on the target; detaching needs write on what it is detached from; deleting is the owner's
  and refused while anything (a tax document included) links to it.
- Search: FTS5 with each word quoted, intersected with what the caller may see, so the index
  leaks no other user's receipt ids.
- The field parser against S9.8.2.5: TOTAL-like labels, SUBTOTAL/TAX/CHANGE/CASH/TIP skipped,
  the last such line, the largest amount as fallback; label on one line and amount on the next;
  split amounts joined; four date shapes, none in the future or before the owner's first
  account; card last four in three spellings.
- `save_reading`: only empty or still-suggested fields filled; a person's edit removes the field
  from `filled`, so reading again never overwrites it; text indexed, never logged.
- The worker: `-I`, empty environment, `close_fds`, stderr to /dev/null, no pickles, answers
  bounded (64 MB, 20,000 lines of 2,000 characters), restarted after a timeout, a crash or an
  answer out of shape; the server's resident-memory watch at 1.5 GB; ONNX Runtime at 2 threads
  and `nice 10`; models checked by SHA-256 and loaded by path; ONNX telemetry switched off.
- Retention: a subcategory takes its parent's period (5 levels at most); splits take the
  longest; transfers and uncategorised keep for ever; a lot's receipt open until the last
  share is sold; a statement from its date, or the closed account's last transaction; Keep and
  "attached to nothing" keep for ever; 90-day bold; Feb 29 handled.
- Pruning asks the password again (`recent_auth`) and the count; orphans are files no row,
  deleted or not, names; both admin-only and recorded in Activity with counts only.
- The store: `tx()` is `BEGIN IMMEDIATE`, `read()` sets `query_only` and the pool resets it on
  check-in; WAL, foreign keys, 10 s busy timeout; `hide_parameters`; soft-delete `deleted` a
  virtual generated column with its CHECK; WITHOUT ROWID and id CHECKs; the prefixes in code and
  `schema.md` §3.1 agree (scratch `tmp/u06/s/prefixes.py`: none missing either way).
- Migrations: one transaction per revision, foreign keys off with a `foreign_key_check` after,
  views dropped first and regenerated, a verified pre-upgrade copy with its keyring, three kept;
  a newer database refuses the start; 0024 and 0026 convert decimal text to cents half-even
  before rebuilding.
- Money: `Cents` refuses floats and rounds half-even to cents; `Dec` refuses more than 18
  places; `UtcTimestamp` refuses naive datetimes; `Day` refuses datetimes; `exactjson` writes
  decimals as number literals through a per-process random mark and reads numbers with a point
  as `Decimal`.
- Ids: UUIDv7 with a 12-bit in-millisecond counter that never goes backwards; one spelling per
  id; prefix checked.
- Time zones: `TZ`, then the content of `/etc/localtime` (so a host file mounted over the
  image's link is known), then the names, then UTC; UTC names kept as such.
- Secrets repository: replace removes the old ciphertext; values only through `use`; the UI
  gets `setAt` and `setById` only.
- Settings › Storage's figures are sizes and counts only; *Keep statements for* 1–100 years;
  a category's period from 1 with the under-7 warning.

## Read lightly or not read

- `mig/0001_the_initial_schema.py` read by search only, as map.md says (the virtual table, the
  prefixes through the metadata check); migrations 0002, 0006, 0010–0014 read only for their
  rebuild pattern; 0015, 0016, 0020, 0025, 0027 skimmed (their tables are units 07, 08, 10, 12's).
- S14.4 and S14.6–S14.7's code lives in unit 10's files (`keys/secrets.py`, `store/maintenance.py`,
  `copies.py`, `reencrypt.py`); here only `store/copy.py` and `repos/secrets.py` were read.
- `ui/components/receipt.js` and `storage.js` read whole; not run in a browser. Whether
  Chromium's and Firefox's PDF viewers render a PDF served with `CSP: sandbox` was not tried
  (headless Chromium has no PDF viewer).
- The tests were read by their names and the parts the claims cite; `test_store.py` (915 lines)
  not read whole.
- Landlock never ran (this host's kernel is 4.18).

## Work pad: severity, confirmations, status

| Id | Kind | Req | Sev | Conf | Status | Description |
|---|---|---|---|---|---|---|
| U06-1 | privacy | S9.6, S9.3 | Med | 0 | open | Withheld (`withheld.md`) |
| U06-2 | bug | S9.5, S9.8.4.2, S14.1.4 | Med | 0 | open | An upload holds the database's write lock while the worker draws its thumbnail; one slow file fails every other write for up to a minute |
| U06-3 | security | S9.8.4.2 | High | 0 | open | Withheld (`withheld.md`) |
| U06-4 | privacy | S9.8.4.2, S10 | Low | 0 | open | One worker reads every user's files in turn, so a file that takes it sees later files and can answer with them |
| U06-5 | security | S9.8.4.2 | Low | 0 | open | On a kernel with the x32 ABI, the seccomp filter lets a network socket through |
| U06-6 | bug | S9.8.6 | Low | 0 | open | *Read again* on a pruned receipt leaves it *Reading…* for good |
| U06-7 | wrong figure | S14.10.2, schema.md §6.2 | Low | 0 | open | Deleting an account makes a lot's receipt expire from the buy's date at once, not from the deletion |
| U06-8 | test gap | S14.10.5 | Low | 0 | open | The test of C3 can't fail: both uploads are one receipt |
| U06-9 | bug | S14.10.5 | Low | 0 | open | Pruning removes files before its transaction commits, and prunes the rows it finds again, not the count typed |
| U06-10 | bug | S9.2 | Low | 0 | open | After a prune, an identical file uploaded again by two people is stored twice |
| U06-11 | not built | S9.8.2.5.3 | Low | 0 | open | A receipt's merchant is never matched against the payees its owner already has |
| U06-12 | not built | S9.3 | Low | 0 | open | A receipt can't be kept with a loan, other than as an imported statement |
| U06-13 | differs | S9.8.7, S9.8.4.1 | Low | 0 | open | *Jobs at a time* changes nothing until a restart; receipts uploaded while reading was off are never read when it comes back on |
| U06-14 | bug | S9.8.6, S1.3.3.2 | Low | 0 | open | Statements go through the receipt reader: *Re-read all* cuts a scanned one to 3 pages and gives it an amount; one the connector keeps waits *Reading…* until a restart |
| U06-15 | differs | S9.8.2.1 | Low | 0 | open | A PDF with a text layer on one page is never OCR'd on its scanned pages |
| U06-16 | differs | S14.10.4, S14.10.2, S9.7 | Low | 0 | open | Settings › Storage leaves deleted receipts' files out of its groups, and nothing can remove them |
| U06-17 | differs | S14.10.5, S9.7, R1.9 | Low | 0 | open | Comments, docstrings and a refusal still state rules the requirements changed |
| U06-18 | differs | S14.1.2 | Low | 0 | open | S14.1.2 says the mapping includes relationships; it maps none |
| U06-19 | differs | S9.6 | Low | 0 | open | The receipts guide narrows who sees a receipt and what *All* lists |
| U06-20 | test gap | S14.2 | Low | 0 | open | No test holds S14.2's modes for receipt files and their directory |
| U06-21 | privacy | S9.6, S1.3.3, S10 | Low | 0 | open (needs the user, with D1-25) | A statement imported by a write sharer stays his receipt, seen in full after the share ends |
| U06-22 | security | S9.8.4.2 | Low | 0 | open | Writing a job to the worker has no deadline, so a worker that stops reading hangs its caller and every quick job behind it |
| U06-23 | untraced | — | Low | 0 | open | `parsing.MAPPING_KEYS` is used nowhere |

Scratch runs: `/home/dev/.claude/jobs/b8ac83ff/tmp/u06/` (`t/test_u06.py`,
`s/prefixes.py`, `s/money_cols.py`, and their outputs `run1.txt`–`run3.txt`).
