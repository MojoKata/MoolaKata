# Unit 05 (S7: budgets, gifts, giving): three runs compared

**Written:** Oct 25, 12:05 AM (Chicago), by a session that read the three runs and re-ran their
scratch tests. Runs B and C were calibration runs: their unit files stay in the coordinating
job's scratch folder, outside the repository, as they hold withheld claims' ids beside their
work; what they found that holds enters the review through unit 05's checking. **Code judged at:** `6916954` (the working tree's `web/` equals it).

- **A** is the review's own run: Opus 5.5 at the default effort. It is
  `docs/reviews/code-review-0003-2026-10-24/unit-05-budgets-gifts-giving.md`, with 26 claims.
- **B** is Sonnet 5.5 at high effort, with 28 claims (one withheld). B saw A's claim counts and
  the ids of A's High and Med claims, but not what they said.
- **C** is Opus 5.5 at medium effort, with 24 claims (one withheld).

**How the claims were checked.** All three runs' scratch tests were run again here, with the
same results each run reported:

- A: 12 tests. One fails on purpose: the IntegrityError of its claim U05-3.
- B: 19 files. Two fail on purpose: the StopIteration of U05-6 and the IntegrityError of U05-9.
- C: 9 tests.

Every claim that only one or two runs made was checked against the cited code and S7 by
reading. Wherever a run's test already reproduced the claim, no new scratch test was written.

**Verdicts:**

- **holds**: the claim is right as written.
- **in part**: the claim is right, but part of what it describes is wrong or narrower.
- **plausible**: the code does what the claim says, but whether that is wrong depends on how
  the requirement is read.
- **doubtful**: the claim rests on no evidence, such as a cost that was never measured.

No claim from any run turned out false.

## 1. Every distinct defect

In the "Found by" column, the run letter comes before the claim id, and the severity the run
gave is in brackets.

| # | Defect | Found by | Verdict | My sev |
|---|---|---|---|---|
| D1 | The Edit plan and Estimate dialogs pre-fill each line with *planned − carried*. Saving with nothing changed bakes the month's moves into the plan, makes reserve lines negative (a 422), and cuts an envelope budget's yearly lines to a twelfth | A U05-17 (High), B U05-13 (High) | holds (both runs checked it through the API) | **High** |
| D2 | Spending paid from the account a reserve is held in makes *to move* ask for that money to be moved out again | A U05-1 (Med) | holds (A's test) | Med |
| D3 | A reserve set to put in $0 disappears with its balance, and nothing asks first | A U05-26 (Med) | holds (A's test) | Med |
| D4 | Saving a gift plan deletes its custom occasions and anniversaries and recreates them with new ids, so gifts lose their occasion | A U05-11 (Med) | holds (A's test; `gifts.js` always sends `occasions`) | Med |
| D5 | The month cache files figures worked out between a write's flush and its commit under the new generation, so they stay stale | A U05-8 (Med), B U05-17 (Med), C U05-7 (Med) | holds (**B reproduced it**; A and C argued it from the code) | Med |
| D6 | The cache doesn't watch `UserGroup` (A also names `Holding` and `Import`) | A U05-8 (part), B U05-18 (Low, privacy) | holds, from the code | Low |
| D7 | In an envelope budget, a plan with a line on both a parent and its child takes spending from both, and To Budget rises | A U05-6 (Med), B U05-3 (Med), C U05-22 (Med) | holds (all three ran it). B also found that a card's line sets aside the charge twice | Med |
| D8 | Compare over a range adds each month's *available*, so rolled-over money is counted again in every month | A U05-4 (Low), B U05-5 (Med), C U05-4 (Med) | holds (all three ran it) | Med |
| D9 | *Cash before payday* counts each recurring payment once, so a weekly bill is taken only once, and a payment due today is left out | A U05-22 (Low), B U05-8 (Med), C U05-3 (Med) | holds (B and C ran it) | Med |
| D10 | *Cash before payday* reaches only one of the users who follow a budget: the cause's key leaves out the user | B U05-19 (Med), C U05-2 (Med) | holds (both ran it; reran here) | Med |
| D11 | The *uncategorised* count includes every split transaction and every transaction left out of the budget, and sorting never clears it | B U05-1 (Med), C U05-5 (Med) | holds (both ran it) | Med |
| D12 | *Changed since reviewed* misses unplanned spending, uncategorised transactions and transfers to sort | A U05-5 (Low), B U05-2 (Med), C U05-6 (Low) | holds (all three ran it) | Low |
| D13 | A review keeps the reviewer's own figures, so it shows a receiver figures they can't otherwise see, and the flag never clears for them | A U05-21.1 (Low, privacy), C U05-6 (second half) | holds, from the code | Low |
| D14 | withheld (a privacy claim) | A U05-21 (part), B, C | holds | Med, withheld |
| D15 | Move labels name any credit card on the server | A U05-21.3, C U05-11 (part) | holds, from the code (`ui/budgets.py:888`) | Low |
| D16 | Envelope card lines name the owner's accounts, and reserve rows give their ids, to a viewer those accounts aren't shared with. P6 again, in new code | A U05-25 (Low, privacy) | holds, from the code. The recurring rows beside them hide the same accounts | Low |
| D17 | Copy as scenario drops a move's `cardId`: a move from To Budget into a card's line gives a 500, and a move from a category into the card's line becomes a move to To Budget. A tracking copy also drops landed-money moves | A U05-3 (Low), B U05-9 (Med), C U05-14 (Low) | A and B hold (both ran it). C holds **in part**: it says a To Budget→card move is copied "with no side at all", when the copy actually fails with a 500 | Low |
| D18 | Copy as scenario keeps a line's `heldInId` for an account the copy doesn't include | B U05-12 (part), C U05-14 (part) | holds, from the code (`ui/budgets.py:1316`) | Low |
| D19 | *Spread* among reserves that all stand at zero gives everything to the last one | A U05-7, B U05-22, C U05-15 (all Low) | holds (A ran it) | Low |
| D20 | Landed money is listed as unassigned only in the month it landed | B U05-21 (Low), C U05-16 (Low) | holds, from the code (`reserves.py:197`) | Low |
| D21 | In an envelope budget, landed money given to a reserve changes Where the money is, but not the reserve's row or To Budget | B U05-11 (Low), C U05-10 (Low) | holds (B ran it) | Low |
| D22 | A move to or from a yearly line changes only the other side, so the money vanishes or appears from nowhere | B U05-14 (Low), C U05-8 (Med) | holds (both ran it) | Low |
| D23 | A reserve's balance is carried into its line after the target is taken off | A U05-2 (Low) | holds (A's test) | Low |
| D24 | Turning reserves off changes nothing: lines with targets go on working as reserves | A U05-18, B U05-15, C U05-13 (all Low) | holds (B ran it) | Low |
| D25 | The estimate keeps one recurring series per category, and it overwrites the category's average. A also found that an income series is offered as a reserve | A U05-9 (Low), B U05-7 (Med); C U05-17 (Low) only on the "monthly series never offered as their own line" point, which A also mentions | holds (B ran it) | Low |
| D26 | A HELOC draw counted *whole* lowers the loan's spending; counted *split*, it counts nowhere and is never listed | A U05-10 (Med), C U05-12 (Low). B saw it and left it unclaimed | holds, from the code (`budgets/__init__.py:205`, `loans/__init__.py:202`) | Low (rare; the default *split* case only drops the listing) |
| D27 | Deleting an account outside the budget removes past transfers to it from the budget's months (R3.10) | A U05-24 (Low), B U05-4 (Med) | holds (both ran it) | Med |
| D28 | A gift plan shared with the person it is for shows them its notes and budget | A U05-12 (Low, privacy) | holds, from the code (`people_view` blanks only `lastGift`) | Low |
| D29 | Spending by person leaves out a deleted person, and a plan budgeted per occasion shows no budget | A U05-13 (Low) | holds, from the code (`gifts/__init__.py:393`) | Low |
| D30 | A birthday or wedding anniversary can't carry a budget of its own | C U05-24 (Low) | holds, from the code (`dates_in` gives them `None`) | Low |
| D31 | Giving misses split transactions and Giving's subcategories, in donations and (B, C) in income too | A U05-14 (Low, donations only), B U05-16 (Med), C U05-18 (Low) | holds (B ran it: a split paycheck gives a $0 target) | Med |
| D32 | The pledge alert ignores transactions that the Giving screen counts toward the pledge. A also found that a month's alert lapses unpaid | A U05-15 (Low), B U05-10 (Med), C U05-19 (first half, Low) | holds (B ran it) | Low |
| D33 | The projected year end leaves out this month's unpaid monthly pledge | A U05-23 (Low), C U05-19 (second half) | holds, from the code | Low |
| D34 | A giving plan's receivers: a write receiver can't change or delete a donation; adding an organisation gives a 500; a read receiver's DAF contribution gives a 500; and no receiver can have a plan of their own that year | A U05-16 (Low), B U05-6 (Med) | B holds (B ran it). A holds **in part**: it says a receiver's organisation "never shows", when the request actually fails with a 500 | Med |
| D35 | A pending DAF grant counts toward the target when the plan counts the fund "when it grants" | B U05-24 (Low) | plausible: depends on whether "grants" means when the grant is recorded or when the fund pays it | Low |
| D36 | Categories: any user adds one through the API, the browser can't, and nobody renames or removes one (D1-13) | A U05-20 (Med, not built), B U05-20 (Low), C U05-21 (Low) | holds; needs the user | Med (pending D1-13) |
| D37 | Compare shows no totals, no To Budget and no reserve balances, and doesn't mark where the two budgets part | A U05-19.1 (Low) | holds, from `budgets.js:766-799` | Low |
| D38 | A reserve held nowhere doesn't say *in the budget's accounts* | A U05-19.2 | holds | Low |
| D39 | The card note says "paying the card moves nothing in a tracking budget" in an envelope budget too | A U05-19.4 | holds | Low |
| D40 | Guide: the donation guide says *basis* for shares held under a year | A U05-23, B U05-26.2, C U05-23.1 | holds | Low |
| D41 | Guide: the settings guide says turning reserves off makes them *ordinary lines* | A U05-18 (cited), B U05-26.4, C U05-23.2 | holds | Low |
| D42 | Guide: the month guide says "only assigning money takes from" To Budget | A U05-19.3, C U05-23.3 | holds | Low |
| D43 | Guide: the recurring guide leaves out *twice a month* | B U05-26.3, C U05-23.4 | holds | Low |
| D44 | Guide: the giving guide says "a household gives toward one target" | B U05-26.1 | in part: a group plan does that, a shared per-user plan doesn't | Low |
| D45 | Guide: the upcoming guide says "everyone's birthdays" | B U05-26.5 | in part: a wording nit | Low |
| D46 | Edit plan opened on a past month rewrites that month and every month since | B U05-25 (Low) | plausible: depends on how "the month it is made in" is read. C judged the same code sound | Low |
| D47 | A budget's receivers see the name and monthly figure of the owner's projection, and a copy keeps `projectionId` | B U05-23 (Low, privacy) | plausible, by S7.2.1 against S10.3 | Low |
| D48 | In an envelope budget, the Gifts and Giving yearly lines are shown but never assigned a twelfth | B U05-28 (Low) | holds (B ran it) | Low |
| D49 | Test gaps: the cache's inputs, Compare over a range, copying with moves, the review's flags beyond planned rows, a second follower, and shared giving plans | B U05-27 (Low) | holds | Low |
| D50 | An envelope category overspent on a card shows only what it held as spent, and its state is *near*, never red | C U05-9 (Low) | plausible: S7.13.2 keeps the balance at nothing, but whether *actual* should still show $250 depends on how that is read | Low |
| D51 | A month view re-reads every earlier month once per rollover line and per reserve | C U05-20 (Low, cost) | doubtful as a claim: the code does this, but nothing was measured. A listed it under "not measured, no claim" | Low |
| D52 | C's withheld claim: a privacy claim (withheld) | C U05-1 (Med, withheld) | holds (C's test reran here) | Med |

**Totals.** There are 52 distinct defects. 16 are true High or Med: D1 is High, and the Med
ones are D2, D3, D4, D5, D7, D8, D9, D10, D11, D14, D27, D31, D34, D36 and D52.

## 2. Each run's findings

In the true findings below, "doubtful" covers the plausible claims and D51.

| | A (Opus, default effort) | B (Sonnet, high effort) | C (Opus, medium effort) |
|---|---|---|---|
| Claims written | 26 | 28 | 24 |
| Distinct defects covered | 34 | 33 | 31 |
| True High (my severity) | 1 (D1) | 1 (D1) | 0 |
| True Med | 12 | 11 | 10 |
| True Low | 21 | 18 | 19 |
| Doubtful or plausible only | 0 | 3 (D35, D46, D47) | 2 (D50, D51) |
| False | 0 | 0 | 0 |
| Partly misdescribed | 1 (D34: the organisation case is a 500, not a silent drop) | 0 | 1 (D17: the To Budget→card copy is a 500, not "no side") |
| Share of the 16 true High+Med | **13/16 (81%)** | 12/16 (75%) | 10/16 (62%) |
| High or Med missed that another run found | D10, D11, D52 | D2, D3, D4, D52 | **D1 (High)**, D2, D3, D4, D27, D34 |
| Claims backed by a run | 11 of 26 | about 20 of 28 | 9 of 24 |
| Tokens / time / tool calls | 377k / 17 min / 128 | 443k / 23 min / 142 | 287k / 13 min / 94 |

**How each run rated severity, against mine:**

- **A** rated five defects lower than I would: D8, D9, D14, D27 and D31 as Low where I give
  Med, and D34 as Low. It rated D26 higher (Med where I give Low).
- **B** rated more claims Med than I would: 14 Med where I give 11. D12, D17, D22 (via C),
  D25 and D32 are Low by my reading. B rated D14 as Med, as I do.
- **C** was closest to my calls. It rated D22 higher (Med) and D14 lower (Low).

## 3. Cost

The token counts are totals, and mostly cached context read again. The assumption used here is
95% input and 5% output, with a range from 98% to 90% input.

| Run | Price per million tokens (in / out) | Cost at 95% input | Range (98% to 90% input) | Per true High+Med |
|---|---|---|---|---|
| A, Opus default | $4 / $20 | **$1.81** | $1.63 to $2.11 | $0.14 |
| B, Sonnet high | $2 / $10 | **$1.06** | $0.96 to $1.24 | $0.09 |
| C, Opus medium | $4 / $20 | **$1.38** | $1.24 to $1.61 | $0.14 |

What pairs of runs cover, of the 16 true High+Med defects:

| Pair | Cost | Covers | Misses |
|---|---|---|---|
| A and C | about $3.19 | **all 16** | none: C adds D10, D11 and D52 to A's 13 |
| A and B | about $2.87 | 15 | D52 |
| B and C | about $2.44 | 13 | D2, D3, D4 |

## 4. What each run did that the others didn't

### A (Opus, default effort)

- **Reserve arithmetic and gifts, in depth.** Three Med defects only A found, each one run:
  D2 (*to move* after spending from the held-in account), D3 (a $0 reserve) and D4 (a gift
  plan's save loses its occasions).
- **The most screen and text findings.** Compare's missing totals, the reserve held nowhere,
  and the card note (D37 to D39).
- **The widest privacy sweep.** Five privacy items (D13 to D16, D28), all rated Low and none
  withheld.
- **Re-checked every earlier finding** with its state, and reasoned across several files (the
  links' `serve.py` for D16).
- **Missed:** the alert reaching only one follower (D10) and the uncategorised count (D11),
  which both other runs found. It even listed "splits through their splits" as checked and
  sound.
- **Severity:** it rated several real Med defects Low.

### B (Sonnet, high effort)

- **Reproduced the most.** About 20 claims rest on a scratch test, including the only
  reproduction of the cache race (D5). It ran each part of the giving-plan share claim and
  found the two 500s that A had only read (D34). It also found that the card line counts the
  charge twice (D7) and that the Gifts and Giving lines are never assigned in an envelope
  budget (D48).
- **The only test-gap claim** (D49), and the most guide mismatches (five, two of them nits).
- **Rated D14 Med and withheld it.** A and C rated it Low. This is the call §2 makes the
  withholding turn on.
- **Weaker spots:** three claims rest on how a requirement is read (D35, D46, D47), and it
  rates claims higher than I do overall. It saw it but didn't claim D26.
- **Missed** every gifts defect (D4, D28, D29) and both reserve-arithmetic defects (D2, D3).
- **Caveat:** B knew A's counts and the ids of A's High and Med claims. That may have pushed
  it towards one High and many Meds, though not towards their content.

### C (Opus, medium effort)

- **The only find of D52**, a Med privacy defect: it found it, ran it and withheld it.
- **Found D30**, and cost (D51), which it raised without measuring.
- **The fewest claims backed by a run** (9). One description, resting on reading, is partly
  wrong: D17's To Budget case, which is a 500.
- **Missed the High (D1).** It read the plan editor's reserve fields but not the pre-fill.
  It also missed D2, D3, D4, D27 and D34.
- **Severity:** its ratings were the best calibrated of the three.

### Shared by all three

Each run found Med defects that neither of the others found: A found D2, D3 and D4, and C
found D52. B's Meds were all also found by A or C, but B found D10 and D11 with C, which A
missed. **No single run found everything; a second, independent run adds real Med finds.**

## 5. A consequence for the review

D14 is published in the review at Low (A's U05-21, part 2). B rates it Med; I would too, since
it is a privacy defect of the kind §2 withholds.

If the review adopts Med, §2's withholding applies, and A's published details of it would need
to move to `withheld.md`. A decision for the user, before the review's pull request goes
public.

## 6. Recommendations

One unit is one sample. Each point below says where the evidence is thin.

1. **Discovery units: Opus at the default effort.** It found the most true High+Med (81%) and
   the only High it shares with B. Opus at medium effort missed that High and five Meds, and
   saved only $0.43. For milestone code never reviewed before, add a second, independent run.
   Opus default with Opus medium reached all 16 for about $3.19; Opus default with Sonnet high
   reached 15 for about $2.87. **Thin:** one unit, and B's knowledge of A's counts muddies the
   Sonnet numbers.
2. **Units that keys, sign-in, links or secrets depend on: Opus at the default effort, plus a
   second independent run (Opus medium or Sonnet high).** The privacy finds were spread across
   the runs: C alone
   found D52, B alone rated D14 at the severity that triggers withholding, and A swept the
   most. **Thin:** S7 is not a keys or sign-in unit. These are privacy claims, with no
   security claim among them.
3. **Phase 1's document blocks: Sonnet at high effort.** Comparing guide and requirement text
   to the code went about as well in all three runs, and B found the most mismatches (with
   two nits) at about 60% of Opus's cost. **Thin:** no Phase 1 block was run. This is drawn
   from the guide-text claims alone.
4. **The checking pass (§8): Sonnet at high effort, as a model other than the one that
   discovered.** B reproduced the most (the cache race, the 500s), and refuting a claim is
   mostly that kind of work. A different model also brings independent eyes. The checker's
   severity corrections need review, since B rates high. **Thin:** no checker was run in this
   experiment.
5. **Assembly: Opus at the default effort.** Assembly makes calls across units on severity
   and on withholding (D14 shows they matter), and the Opus runs' severities were steadier
   than Sonnet's. **Thin:** no assembly was compared.
