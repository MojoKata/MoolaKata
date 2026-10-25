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
| Oct 24, 07:27 PM | Oct 24, 07:38 PM | Phase 1 `docs-compare` | `docs-compare.md`: 22 claims (High 0, Med 2: DC-1, DC-2; Low 20); 5 joins (DC-1 = D2-1 + D3-1, DC-2 = D2-3 + DEPLOY/operations, DC-3 = D2-4 + D3-6, DC-4 = D1-5 + D2-25, DC-5 = D2-19 + schema.md); 1 within block 2 found outside scope (DC-22); none withheld; no §6 gate candidate; the to-decide list (9 rows: D1-1, D1-12, D1-13, D1-25, DC-1, D2-2, DC-2, DC-4, D3-21) | the walk through the to-decide list with the user, then unit 01 (§7) |
| Oct 24, 07:43 PM | Oct 24, 07:58 PM | Unit 01 accounts-imports | `unit-01-accounts-imports.md`: 16 claims (High 1: U01-4; Med 7: U01-1, U01-2, U01-3, U01-5, U01-9, U01-10, U01-11; Low 8); by kind bug 5, differs 5, wrong figure 4, not built 1, test gap 1; none withheld, none needing the user; earlier findings B33/C43 and C44 found to half hold (U01-9, U01-4, U01-5); scratch runs in the job's `tmp/u01/` | unit 02 items-loans-education-bitcoin (§7) |
| Oct 24, 08:00 PM | Oct 24, 08:12 PM | Unit 02 items-loans-education-bitcoin | `unit-02-items-loans-education-bitcoin.md`: 17 claims (High 0; Med 3: U02-1, U02-4, U02-15; Low 14); by kind wrong figure 9, bug 4, differs 2, not built 1, untraced 1; none withheld, none needing the user; earlier finding B21 found to half hold (U02-5), B22 and B35 hold with new cases beside them (U02-12, U02-1, U02-2); scratch runs in the job's `tmp/u02/` | unit 03 lots-positions-prices-portfolios (§7) |
| Oct 24, 08:17 PM | Oct 24, 08:33 PM | Unit 03 lots-positions-prices-portfolios | `unit-03-lots-positions-prices-portfolios.md`: 18 claims (High 0; Med 9: U03-1, U03-2, U03-3, U03-4, U03-5, U03-6, U03-7, U03-9, U03-16; Low 9); by kind differs 8, wrong figure 5, bug 3, security 1 (U03-3, Med, withheld in `withheld.md`), not built 1; none needing the user (D1-1, D1-12 judged against both readings, left to the walk-through); earlier findings B34 found to half hold (U03-1), P7 and C45 to hold but for U03-2 and U03-11; scratch runs in the job's `tmp/u03/` | unit 04 projections-taxes (§7) |
| Oct 24, 08:35 PM | Oct 24, 08:50 PM | Unit 04 projections-taxes | `unit-04-projections-taxes.md`: 26 claims (High 0; Med 9: U04-1, U04-2, U04-10, U04-11, U04-12, U04-13, U04-14, U04-15, U04-17; Low 17); by kind differs 12, wrong figure 6, not built 3, bug 3, privacy 2 (both Low, none withheld); 1 needing the user (U04-14, D1-25 judged against both readings); earlier findings P7 and C40 found to half hold (U04-8, U04-23), P1 and N5 to hold with new cases beside them (U04-11, U04-10, U04-12); scratch runs in the job's `tmp/u04/` | unit 05 budgets-gifts-giving (§7) |
| Oct 24, 08:53 PM | Oct 24, 09:10 PM | Unit 05 budgets-gifts-giving | `unit-05-budgets-gifts-giving.md`: 26 claims (High 1: U05-17; Med 7: U05-1, U05-6, U05-8, U05-10, U05-11, U05-20, U05-26; Low 18); by kind wrong figure 9, differs 7, bug 6, privacy 3 (all Low, none withheld), not built 1; 1 needing the user (U05-20, D1-13 judged against both readings); D1-2 judged (the code alerts each follower); earlier findings P6 and C39 found to half hold (U05-25, U05-21); scratch runs in the job's `tmp/u05/` | unit 06 receipts-storage (§7) |

**Phase 0's recommendation.** Code read as units: 101,892 lines in 487 files (generated and data,
54,086 lines, and the guides, 6,062, apart). Changed since `294792b`: 75% counting the
product rename's 255 moves whole as §1 asks, 24% by content alone, with unit 05 (budgets) at 53%
by content. Either way past §1's line (~25%, no unit over ~50%), so **full**. Checking: §1
recommends **checked**, as units 07, 08, 10 and 12 (sign-in, links, keys, the connector) changed
by 13–39% in content. **The user's choice: full, quick, serial**, with a checking pass later
(§11.4), so every claim starts at 0 confirmations.
