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
