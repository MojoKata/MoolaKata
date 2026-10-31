# Walk-through: review 3's receipt claims

Started Oct 31, 2026. Decisions log; nothing is applied until the final approval. The claims are
unit 6's (receipts, S9) and unit 9's upload ceiling: CR3-47, CR3-48, CR3-56.

## Items

1. CR3-47 (Med): a receipt's dialog names every thing it is kept with, readable or not
2. CR3-48 (Med): an upload holds the write lock while the worker draws its thumbnail
3. CR3-56 (Med): an upload is read whole into memory before anyone is signed in

## Decisions

**Oct 31, 2:09 PM, the user:** CR3-47 rides on access views, built on this PR as its first
commit(s): every table seen by some users but not all gets a `<Table>Access` view, joined by the
row's id and the user (`… join <Table>Access A on T.id = A.targetId and A.userId = ?`). Their
design is walked first (part A below), then items 1–3 resume. CR3-47's display, as far as it
went: only readable links, the owner included, and *Also kept with N things not shared with
you*; `keptWhy` and the search from readable links only (not yet locked).

Probe (SQLite 3.53.1, `$CLAUDE_JOB_DIR/tmp/plan.py`): a view that collapses owner, direct and
group shares with `GROUP BY` is computed whole per query (`userId = ?` isn't pushed into it);
a child view joined through it keeps the child on its own index.

**Oct 31, 2:11 PM, paused** by the user until the access views are designed and built
([`access-views-walk.md`](access-views-walk.md)); items 1–3 resume after.

**Oct 31, 5:52 PM: resumed** after the access views (PR #27 commits d0512ad to 1294824).

1. **CR3-47 (1 of 3).** Its leak is closed by the access views: a receipt's links, and what
   they name, are read through the reader's views, so a reader sees only the links to what
   they read. Decided:
   1. Under them, *Also kept with N things not shared with you*, the count read as the server
      and naming nothing; the owner sees it too (why *Delete* is refused, S9.7). The
      mockup's receipt dialog and its guide show it.
   2. *Kept until…* is the file's own date, worked out as the server over every link; its
      reason (*Groceries keeps receipts 3 years*) is named only when the link it comes from
      is readable, else *Kept for something not shared with you*.
   3. The receipts list's search matches rows built from readable links only, as it does:
      no change.
2. **CR3-48 (2 of 3).** `receipts.store` splits: *prepare*, outside any transaction (type,
   hash, the same file kept already, the thumbnail drawn in the reader's worker, the
   encrypted file written under a hold the orphan sweep respects), and *record*, a short
   transaction (the duplicate checked again, the row added, the hold released at commit; a
   row that never commits leaves its file to the sweep, S14.6). The upload, an import's
   statement and the connector all use it. A thumbnail that fails or times out leaves the
   receipt with its file-type icon and the upload succeeds; *Read again* tries it again. A
   test holds the worker slow and sees another user's write go through. Weighed: the
   thumbnail in the reading queue's job (waits on *Read receipts*); a 5-second limit with the
   queue catching up (two paths).
3. **CR3-56 (3 of 3).** An upload to `/ui/api` (multipart, or a body past 64 KB) has its
   session looked up by its token's hash, as the server, before a byte of its body is read;
   no live session answers 401 on the headers, and the in-flight cap counts by user. The
   link and connector routes keep their own gates. A server-wide ceiling of 256 MB of
   uploads in flight, past which 503 with `Retry-After: 30`; the 100 MB per user stays.
   S13.7.6 says both; tests for each (a forged cookie with 5 MB read almost none of it).
   Weighed: 128 MB.

## Final approval

Given by the user Oct 31, 5:55 PM, for all three as written above.

## Applied
