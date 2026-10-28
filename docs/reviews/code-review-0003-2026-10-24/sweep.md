# Code review 3: the sweep

The sweep of docs/REVIEW.md §8 (last paragraph): every item the checkers wrote under *Found
while checking*, checked as a checker checks. **Started:** Oct 25, 01:48 AM (Chicago). Model:
Sonnet 5.5, high effort (§14.5), a fresh context that made none of what it checks.

**Read:** REVIEW.md §2, §3, §7, §8, §9; `log.md`'s header and rows; each item in its file and
the code and requirement it cites, whole around the cited lines; the claims it might repeat
(searched by their headings); `withheld.md` for the withheld items. Scratch runs are in the
job's `tmp/check/sweep/` (`test_f1.py`, `test_f2.py`, `test_f3.py`), run from the server's
fixtures; nothing over a minute, no `web/check`.

Each verdict is also written under its item, in its own file. A confirmed or corrected item
takes the next free CR3 number at the next assembly (§10).

**21 items: 15 confirmed, 4 corrected, 0 plausible, 2 rejected.** By severity now (confirmed
and corrected): Med 1 (U08-F1), Low 18. Withheld: U08-F1 and U10-F1.

## Documents

- **D1-F1** (the phone PWA "comes later" with no L id): **rejected**. Already D2-25 (same lines
  quoted, same missing L id); DC-4 joins it with D1-5.
- **D1-F2** (S9.6 cites S8.16 for the tax book's filers): **corrected, Low**. The citation is
  to the tax documents, which the sentence is about; what is missing is a pointer to the
  filers and readers (S8.14.1, S8.14.3). D1-25 is the same sentence, and its remedy covers it.
- **D2-F1** (no ceiling for a receipt's body on a link): **rejected**. Already D2-1's checked
  scope and remedy (the `deliver` body "undecided", state its ceiling); DC-1 and U08-1 carry it.
- **D3-F1** (a locked copy's inbox cap of 500 MB against a 2 GB first change): **confirmed,
  Low**. `links/changes.py:126-133` counts every part against the cap and discards the inbox;
  S11.9.5.4 and the protocol's example disagree, and nothing says parts count.
- **DC-F1** (S17.1's `mockups/` entry names one of three files): **corrected, Low**. Line is
  `:13`, not `:12`; the rest holds; fix it with DC-21.

## Units

- **U01-F1** (the account page has no Positions or Receipts tab): **confirmed, Low**. S12.2.2
  and the mockup list both; the page, the guides and the milestones have neither.
- **U01-F2** (the mockup's rule gives `cash` a Reconcile tab): **corrected, Low**. The rule is
  wrong, but no sample account is `cash`, so no screen shows it.
- **U01-F3** (every file's positions are saved as snapshots, also for an account with trades):
  **confirmed, Low**. `store/repos/ledger.py:433-453` writes the `Holding` whether or not
  `checked`; replay ignores it until the trades go.
- **U02-F1** (a loan payment linked to a row of the loan's own account): **confirmed, Low**.
  `ui/loans.py:480-484` never compares `other.accountId` with the loan or any loan account.
- **U03-F1** (two picks of one lot take more than the lot holds): **confirmed, Low**.
  Reproduced: picks of 6 and 6 on a 10-share lot leave -2 shares, basis -200.00, no problem.
- **U03-F2** (an adjusted contract's deliverable weighted by any user's last trade):
  **confirmed, Low**. `options/__init__.py:202` passes no owner; S4.10 says the viewer's own.
- **U04-F1** (a typed amount of `NaN` or `inf` answers 500): **confirmed, Low**. Reproduced:
  `InvalidOperation` for both; `-inf` is a 422.
- **U05-F1** (a changed review names at most one of the totals): **confirmed, Low**. The
  `and not out` in `ui/budgets.py:1438`; U05-5 quotes the lines but is about other figures.
- **U07-F1** (PATCH `/persons/{id}` sets `private` false when the body leaves it out):
  **confirmed, Low**. More than stated: the PATCH replaces the whole record (`diedOn` too) and
  `PersonRow` has no `private`, so a client cannot send it back; only the API reaches it.
- **U07-F2** (sign-in and re-authentication hash under the write lock): **confirmed, Low**.
  `ui/session.py:187-189, 418-420`; `sign_in` has no `_throttle`; one hash is about 0.1 s.
- **U08-F1**: security, **confirmed, Med, withheld** (`withheld.md`).
- **U09-F1** (the middleware's problems carry their own title table): **corrected, Low**. The
  tables differ, but S13.8.3 asks for a `title`, not a wording, and the browser shows `detail`;
  it is consistency (differs), not a fault.
- **U10-F1**: security, **confirmed, Low, withheld** (`withheld.md`). Withheld because I am not
  sure that publishing it tells no one how to attack a server.
- **U10-F2** (the host events queue is removed before its events are recorded): **confirmed,
  Low**. `store/maintenance.py:151-158` against `runtime.py:307-322`; not U10-16's window.
- **U11-F1** (the no-network test's loopback tests are prefixes and a suffix): **confirmed,
  Low**. Contrived next to U11-1, as the item says, and as written.
- **U12-F1** (a failed `sign-in` call abandons the rest of that round): **confirmed, Low**.
  Both calls are outside any `try`; in the second place the run's files are also dropped.
