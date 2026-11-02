# Walk: budgets' money moves

Review 3's open Med claims on budgets (S7): CR3-39, CR3-40, CR3-41, CR3-42, CR3-44, CR3-45,
CR3-46, walked on branch `cr3-budgets` from main `913bafb`.

**Found before the walk.** CR3-5 (a budget's receiver sees a held-in account shared with the
owner only) no longer holds: the access views (PR #27, `2d9269d`) scope the receiver's session,
so `held_in` finds no such account and *Where the money is* lists nothing for it (reproduced
against the current API: Alice sees the account, its balance and its landed deposit; Bob, the
budget's receiver, gets `heldIn: []`). Its row is set fixed by `2d9269d`, with no walk item.
The other seven still hold: each claim's cited code is unchanged.

## Decisions

1. **CR3-39, *to move* and the held-in account's own flows (locked Nov 1, 6:50 PM).** The
   weighing the user set before deciding: correctness, architecture, clarity and testability
   first; cost and ripple effects last.
   1. One classification of every transaction in a held-in account since its reserves began,
      each in exactly one class: *moved* (a transfer to or from one of the budget's accounts,
      unless kept as the account's own); *the reserves' own flow* (spending or a refund, either
      sign, in the category of a reserve held there); *landed* (given, kept as the account's
      own, or unassigned); *the account's own* (the rest: a fee, other categories' spending, a
      transfer to an account outside the budget). *To move* = total − (moved + the reserves'
      own flow + given); *unassigned* lists landed money only. `moved_in`, `unassigned` and
      `transfers` read from it.
   2. Tests: a table test of each kind of transaction's class, and an invariant over generated
      flows: doing what *to move* says leaves the account backed.
   3. S7.10.4 and S7.10.5 say it (*spending or a refund in a reserve's category, in the
      account it is held in, is the reserve's own, never landed money*); the guide and the
      mockup's `GUIDES` follow. No screen or schema change.
   4. (1.1) Spending from one held-in account in the category of a reserve held in another:
      the advice is a move between the two (*$700 to move from Marcus to Ally*), which S7.10.4
      describes.
   5. Found while walking: a refund in a reserve's category landing in its account is listed
      as unassigned landed money, and giving it counts it twice in the reserve's balance (once
      as less spending, once as a move). Reproduced against the current API; a new claim, fixed
      by the same change.
   6. Rejected: patching *to move* alone (leaves the refund and any other unclassified flow
      wrong); working from the account's balance with a stored baseline (a stored derived
      figure goes stale on edits to past transactions, against S7.10.1).
2. **CR3-40, Compare over a range, and one identity for a month's rows (locked Nov 1, 6:55
   PM).**
   1. Every row, of every kind (tracking, envelope, reserve), carries *carried*, *put in*,
      *moved*, *spent* and *remaining*, with remaining = carried + put in + moved − spent;
      `planned` is *available* (carried + put in + moved) for every kind (a reserve's row,
      `putIn` only today, changes; the browser's reserve row keeps reading `putIn`).
   2. Compare over a range: available = carried into its first month + each month's put in and
      moved; spent summed; remaining = available − spent. S7.12.3 says so.
   3. Tests: the identity for every row of every month the budget tests make; and, over
      generated plans of every kind, a carrying line's range remaining equals its last month's.
   4. (2.1) The month's *Spent* card (budget screen and Dashboard): *of $Y available*, $Y the
      expense rows' available, reserves included; *left* = the rows' remaining less unplanned
      spending, so a repair a reserve covers is never shown over (S7.10.2). The word changes in
      the mockup and the guide in the same commit.
   5. Rejected: subtracting carries in Compare alone (leaves `planned` meaning three things,
      and 2.1 wrong); the last month's available with the range's spending (subtracts spending
      whose money isn't counted).
3. **CR3-41, one line per transaction (locked Nov 1, 6:57 PM).**
   1. Each transaction counts against exactly one line: its category's own line, else its
      parent's, else none (unplanned). A parent line covers only children without a line of
      their own, in both methods and for reserves.
   2. One function assigns spending to lines; `_actual`, `_carry`, `reserves.reserve`, the
      envelope and the unplanned list read from it.
   3. Tests, over generated category trees, plans and transactions: each month's rows' spent
      plus unplanned is the month's spending; in an envelope budget, To Budget plus the
      categories' balances is the accounts' cash (S7.13.1).
   4. S7.1.2: *a plan line on a parent category counts its children that have no line of
      their own*; the guide and the mockup's `GUIDES` follow; the mockup's sample plan checked
      for a parent and child both planned. No schema change.
   5. Rejected: a parent line as a cap over its group (a second kind of envelope relation S7.13
      doesn't describe); refusing a parent and child both planned (takes away a reasonable plan
      and leaves four readers with their own rules).
4. **CR3-42, the month cache keyed by a data version in the database (locked Nov 1, 6:59
   PM).**
   1. One counter row, bumped by triggers on every write to every table but those declared
      *not a figure input* (a table declaration beside `seen=`: sign-in sessions, Activity,
      alerts, the email queue, each with its reason). A month's figures are read and stored
      under the counter read in the same read transaction (one SQLite snapshot), with the
      database's identity in the key so a restored or copied database never meets old entries.
   2. `cache.py` loses its event listeners and its list of input tables; `schema.md` §7 gets
      the declaration; S7.3.10 and its Refresh unchanged.
   3. Tests: a static check that every table has the trigger or the declaration with a reason;
      a generated test that a write to each input table moves the version; a differential run
      of the budget tests' month views with the cache on and bypassed, identical.
   4. Rejected: the claim's remedy (keeps an unchecked list of inputs; misses writes outside
      the ORM and restores); no cache (only after a measurement says the month view is fast
      enough without it).
5. **CR3-44, a calendar schedule per recurring series (locked Nov 1, 7:01 PM).**
   1. A series' anchor is found from its history: a weekday (weekly, two-weekly), days of the
      month (monthly, twice-monthly: *1st and 15th*, *15th and last*), a month and day
      (quarterly, yearly), month ends clamped. `occurrences(from, to)` gives its dates; `next`
      is the first. Found while walking: `next` is *last + a fixed number of days* today, so a
      salary on the 15th is expected Nov 14 and a 1st-and-15th bill Oct 30; the Recurring list
      (S7.5) and the alert both read it.
   2. *Cash before payday* is a day-by-day running balance from today to the next money in:
      every expected payment counted, payments out before money in on the same day; it names
      the first day below zero.
   3. (5.1) Late ones, both directions: inside the *missed* window (the interval's tolerance)
      a payment or income is expected today; past it, it is *missed*, flagged on Recurring and
      not expected.
   4. Tests: property tests of the generator per interval (month ends, February, leap years);
      a round trip from generated schedules with jittered dates through detection to the same
      schedule and next date; table tests of the alert (the weekly case, due today, late,
      twice-monthly before a monthly payday, no income series).
   5. S7.5.1 says a series has a calendar schedule; S7.6.1 that every payment due before money
      in counts; the mockup's Recurring sample checked.
   6. Rejected: stepping by the interval in the alert (leaves the drift and a second copy of the
      interval logic).
6. **CR3-45, past months read history as it was (locked Nov 1, 7:06 PM).** Reproduced the
   claim and found three siblings against the current API: a budget's own account deleted
   (September's $80 on the card becomes $0 spent); an account taken out of the budget (the
   same); a receiver who can't see the other account (Bob reads Alice's $300 to Ally as $0
   saved and not moved, the missing half taken as inside the budget).
   1. One rule for what counts in a month, read by every budget read: a transaction counts
      unless it was itself deleted (a correction); its account's deletion ends the account,
      not its past. A transfer's other half is judged by its account id, read as a column even
      when that account is deleted or not visible to the viewer: inside the budget's accounts
      that month, it is internal; otherwise money moved in or out, counted by its category,
      named *(deleted)* or *an account not shared*. A payment to a loan the viewer can't see
      counts whole in its category (the split would show the loan).
   2. (6.1) The budget's accounts are dated like plan lines: adding or taking one out applies
      from a month (this month unless another is chosen); past months keep the accounts they
      had. `BudgetAccount` gains its months (migration); Edit budget's accounts say *from
      {month}*; the guide and `GUIDES` follow.
   3. `amounts`, `_other_halves` and `account_ids` read the one rule; R3.10 and S7.3.2 name it.
   4. Tests: over generated sequences, nothing done after month M (an account deleted: the
      budget's own, another, a loan, a cash account; an account taken out) changes M's
      figures; deleting or editing a transaction does change its month, and flags a reviewed
      month (S7.14).
   5. Rejected: the claim's remedy alone (fixes the first case only).
   6. **Revised (Nov 1, 7:12 PM): close and delete are different.** Asked whether they are the
      same in the code: no. Close is the account's `active` switch, with no date, read by
      alerts, the Dashboard's reconcile card and the account screens only; delete is a soft
      delete taking everything *deleted with* the account out of every read, past included.
      R3.10 and `schema.md` §6.3 treated both as an end. Keeping a deleted account's past (as
      first locked) would leave a duplicate account, deleted, counted twice in every past month.
      The user: "Delete is a delete, not the same as close."
      1. **Close** ends an account: a **closed date**, stored (S1.2's switch becomes the date,
         with 6.1's migration); it counts up to that date and shows after as *UMB Checking
         (closed)* (§6.3).
      2. **Delete** is a correction: the account and what is deleted with it leave every
         figure, past included; reviewed months are flagged (S7.14). The delete confirm says
         *Its transactions leave every past figure too. To keep its history, close it
         instead.* (mockup). R3.10 says *ends* is closing, for an account.
      3. Item 1's first rule becomes: a transaction counts unless it, or its account, is
         deleted; a closed account counts up to its closed date. A transfer whose other half is
         gone (deleted, or its account deleted) is money moved in or out, so the claim's
         October $300 from Checking still counts as saved; the reproduced card sibling (a
         deleted card's $80 leaving September) is then right.
      4. **Widened (Nov 1, 7:15 PM)**, from a survey of where an end and a delete meet:
         the rule is written once as a design principle (R3.10 and `schema.md` §6): an end
         (an account closed, an item sold, a loan paid off) is a dated state and keeps the
         past; a delete is a correction that takes the record, and what is deleted with it,
         out of every figure, past included; records that only keep its name or ref (a gift
         keeping a deleted person) stay. A portfolio's returns follow it: `with_deleted`
         (`ui/portfolios.py`) goes, and a closed account counts up to its closed date. Items'
         and loans' delete confirms get the accounts' wording. Noted for the filed-tax-years
         walk: deleting an account with sales in a filed year is asked first and listed under
         *Changed after filing* (with CR3-33). Left with CR3-75: retiring vs deleting a
         category.
      5. **Words (Nov 1, 7:17 PM).** The past-keeping state is **closed** (an account
         closed, an item sold, a loan paid off), against **deleted** (a correction), in
         R3.10 and `schema.md` §6.3. `endedAt` keeps its retention meaning (§6.1): it covers
         both closing and deletion, serves retention only, and no figure reads it; §6.1 says
         so in a sentence.
7. **CR3-46, taking a category out of the plan is explicit (locked Nov 1, 7:08 PM).** The plan
   line's $0 means both *put nothing in* and *out of the plan*. Since the review, a reserve set
   to $0 asks first, but its only answer loses the balance. Siblings: a rollover line set to $0
   drops its carried balance without a question (reproduced: *Entertainment*'s $200); an
   envelope category set to $0 assigned disappears and its balance goes back to To Budget
   unsaid (read in `envelope.py`).
   1. A plan line is *in the plan* (any amount, $0 included) or *out of the plan* from a month
      on, a state of its own. $0 pauses a reserve, a rollover line or an envelope and keeps
      the balance.
   2. Taking out a line that holds a balance (reserve, rollover, envelope) asks first and names
      the balance (S7.10.3, widened).
   3. `BudgetLine` gains the state; a migration turns today's $0 lines into *out*; `in_force`
      stops filtering on the amount; the plan dialog's Remove saves *out* and it may say *Pause:
      set to $0 and the balance is kept* (mockup, guide, `GUIDES`); S7.1.2 and S7.10.3 say both.
   4. Tests: over generated plan edits, the categories' balances change only by put in, moved,
      spent, or a confirmed taking out; in an envelope budget it joins decision 3's To Budget
      invariant.
   5. Rejected: a target keeping a $0 line in force (fixes the reserve only); refusing $0 with a
      target (forbids a reasonable pause, leaves the siblings).

**Final approval** given Nov 1, 7:18 PM, with the build order: 4 first (its differential test
guards the rest), then 6 (with the closed date and portfolio returns), 3, 7 and 2, then 1, then
5; one commit or more per decision, each pushed as made, on a regular PR from `cr3-budgets`.

## Applied

