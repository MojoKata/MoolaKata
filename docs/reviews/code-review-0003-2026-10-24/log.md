# Code review 3: log

One line per session (docs/REVIEW.md §2, §3.8). Times are Chicago.

**Commit read:** `6916954` (branch `review-process`, PR #15; its squash onto `main` has the same
tree). **Measured from:** `294792b` (review 2). **Branch:** `code-review-0003`.
**Choices:** full, quick (to be checked later, §11.4), serial, as the user chose on Oct 24.
Each session is a subagent with a fresh context, run one at a time from a coordinating session.
The numbers (§4.3) recommend full; §1 advises checked, as milestone 9 changed code that keys,
sign-in and secrets depend on, and the user chose to check later.

| Start | End | Phase or unit | Wrote | Left |
|---|---|---|---|---|
| Oct 24, 06:29 PM | Oct 24, 06:33 PM | Phase 0 | `doccheck.txt` (0 problems, 31 words to read, 25 uncited first-level items), `cites.tsv`, `map.md` (12 units), `map-spec.py` (the units' paths), `delta.txt` | Phase 1, block `docs-1-money` (§5) |
| Oct 24, 06:43 PM | Oct 24, 06:53 PM | Phase 1 `docs-1-money` | `docs-1-money.md`: 25 claims (High 0, Med 4: D1-1, D1-13, D1-14, D1-25; Low 21), 4 needing the user (D1-5, D1-12, D1-13, D1-25), no §6 gate claim; the claims digest for README, S1–S9, later, gaps, questions | Phase 1, block `docs-2-platform` (§5) |
| Oct 24, 06:54 PM | Oct 24, 07:08 PM | Phase 1 `docs-2-platform` | `docs-2-platform.md`: 26 claims (High 0, Med 3: D2-1, D2-2, D2-3; Low 23), 3 needing the user (D2-2, D2-3, D2-25; D2-25 with D1-5), none withheld, no §6 gate claim; the claims digest for S10–S18, out-of-scope and rejected ideas (R1–R3 left to `docs-1-money`'s) | Phase 1, block `docs-3-protocols` (§5) |
| Oct 24, 07:10 PM | Oct 24, 07:23 PM | Phase 1 `docs-3-protocols` | `docs-3-protocols.md`: 23 claims (High 0, Med 1: D3-1; Low 22), 1 needing the user (D3-21), none withheld, no §6 gate claim; the claims digest for schema, the link and connector protocols, api, operations, DEPLOY, RELEASE, GENESIS, test-plan, dependencies and external/README (GENESIS and external/README read too: §5 lists neither) | Phase 1 `docs-compare` (§5) |

**Phase 0's recommendation.** Code read as units: 101,892 lines in 487 files (generated and data,
54,086 lines, and the guides, 6,062, apart). Changed since `294792b`: 75% counting the
product rename's 255 moves whole as §1 asks, 24% by content alone, with unit 05 (budgets) at 53%
by content. Either way past §1's line (~25%, no unit over ~50%), so **full**. Checking: §1
recommends **checked**, as units 07, 08, 10 and 12 (sign-in, links, keys, the connector) changed
by 13–39% in content. **The user's choice: full, quick, serial**, with a checking pass later
(§11.4), so every claim starts at 0 confirmations.
