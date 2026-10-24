# Code review 3: log

One line per session (docs/REVIEW.md §2, §3.8). Times are Chicago.

**Commit read:** `6916954` (branch `review-process`, PR #15; its squash onto `main` has the same
tree). **Measured from:** `294792b` (review 2). **Branch:** `code-review-0003`.
**Choices:** full, quick (to be checked later, §11.4), serial. Asked for by the user on Oct 24;
the numbers (§4.3) recommend full; §1 advises checked, as milestone 9 changed code that keys,
sign-in and secrets depend on, and the user chose to check later.

| Start | End | Phase or unit | Wrote | Left |
|---|---|---|---|---|
| Oct 24, 06:29 PM | Oct 24, 06:33 PM | Phase 0 | `doccheck.txt` (0 problems, 31 words to read, 25 uncited first-level items), `cites.tsv`, `map.md` (12 units), `map-spec.py` (the units' paths), `delta.txt` | Phase 1, block `docs-1-money` (§5) |

**Phase 0's recommendation.** Code read as units: 101,892 lines in 487 files (generated and data,
54,086 lines, and the guides, 6,062, apart). Changed since `294792b`: 75% counting the
product rename's 255 moves whole as §1 asks, 24% by content alone, with unit 05 (budgets) at 53%
by content. Either way past §1's line (~25%, no unit over ~50%), so **full**. Checking: §1
recommends **checked**, as units 07, 08, 10 and 12 (sign-in, links, keys, the connector) changed
by 13–39% in content. **The user's choice: full, quick, serial**, with a checking pass later
(§11.4), so every claim starts at 0 confirmations.
