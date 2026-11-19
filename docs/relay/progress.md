# Relay progress: H1.8's ledger survivors

Batches 1-7 (860 survivors, fork run 44505709314): 1-5 `ui/transactions.py`, 6 `ui/accounts.py`'s
`change`, 7 the rest of `ui/accounts.py` and `ledger/balances.py`. The rest round's survivors
(fork run 44561996257) come as batches 8 on. One agent at a time; the coordinator checks each
batch before the next starts.

## Batch 1

Test files touched: `tests/test_txn_save.py`, `tests/test_options.py`, `tests/test_adjusted.py`,
`tests/test_accounts.py`.

Counts: killed 95, equivalent 8, bug 0, unreachable 2, slow 0, still surviving 0.

Equivalent:
- `x_delete_txn__mutmut_36`: `s.get(Transaction, None)` returns None (with a warning only), as the `else None` does.
- `x_delete_txn__mutmut_78`: a leg is deleted only with its assignment or exercise (alone it is refused), so a live end never has a deleted leg for the filter to leave out.
- `x__set_left_out__mutmut_38`: the viewer filter in `budgets.members` keeps every account the viewer reads, and the caller reads the transaction's account (`_txn_editable`), so it is never dropped.
- `x__set_left_out__mutmut_71`, `_72`, `_73`: `was` is every live leave-out of a budget the caller sees, and a budget written is seen, so a budget being left out has no live row and one counted again has one: the changed conditions decide every reachable case the same.
- `x__reconciled__mutmut_3`: `s.get(Reconciliation, None)` returns None, as the `else None` does.
- `x__pick_create__mutmut_15`: `createdAt`'s default is `clock.now()`, the value passed.

Mutation check: 95 killed, the 9 survivors exactly the equivalent and unreachable ones above;
`x__pick_create__mutmut_15` showed as no tests (the picks' tests are in `test_taxpanels.py`, untouched).

Unreachable:
- `x_delete_txn__mutmut_67`, `_68`: the refusal's `'an option'` fallback: an assignment's or exercise's payee is always set by `options.settle` (the route's and an import's), and the save refuses any change to it (`option-kind`).

Doubts:
- In a reconciled period, a save that deletes one part and adds another answers 422 `splits-unbalanced` rather than asking: the created part's question rolls it back, and the parts check then runs on what is left (`ui/save.py` `apply`). The test adds a part to a transaction without parts instead; this looks like a bug for S2.7 and S13.8.11.5.
- `_split_delete` doesn't call `_reconciled`: deleting a part of a transaction in a reconciled period asks nothing, where adding or changing one asks (S2.7). Not pinned.
- The made-by-an-assignment refusal reads "the assignment of Assigned MSFT 20NOV26 480 P" (the end's payee repeats the word). Pinned as it is; the wording may want a look.

## Batch 2

Test files touched: `tests/test_txn_save.py`, `tests/test_accounts.py`.

Counts: killed 101, equivalent 3, bug 0, unreachable 0, slow 0, still surviving 0.

Equivalent:
- `x__transfer_lots__mutmut_6`: every body has `transferLots`: a `TxnRecord` (from `_make`) or the `SimpleNamespace` `_change` builds with it, so `getattr` without a default never misses.
- `x__transfer_lots__mutmut_13`: `sum` starting from `0` rather than `Decimal(0)` over Decimals gives the same Decimal, and the lots are never empty there (`if lots_in`).
- `x__transfer_lots__mutmut_59`: every body has `costBasis` (`TxnRecord`, and `_change`'s `SimpleNamespace` sets it to None), so `getattr` without a default never misses.

Mutation check: 101 killed, the 3 survivors exactly the equivalent ones above.

Doubts:
- A reward's price typed with it counts as the owner's price for that day (the trade tier of `valuation.prices` reads the reward itself, flushed before `_reward_basis`), so with no close or typed price, a reward without a price on the same day as one with a price takes that one's price. The reward test puts a typed price (S4.7) before the priced reward so that the typed-with-it price is what decides. Looks right for S8.5, but worth knowing.
- A half paired by hand with another user's transaction (write share) reads `transferId` None for the account's owner, who can't see the caller's account; only the caller sees the pair. Not pinned; looks like the intended read filter.

## Batch 3

Test files touched: `tests/test_txn_save.py`, `tests/test_accounts.py`, `tests/test_positions.py`,
`tests/test_adjusted.py`.

Counts: killed 102, equivalent 7, bug 2, unreachable 0, slow 0, still surviving 0.

Equivalent:
- `x__change__mutmut_3`: an update's fields are put onto the record as it is (`save._merged`), so a kind not sent is the transaction's own: `body.kind == t.kind`.
- `x__change__mutmut_8`, `_9`, `_10`, `_12`: likewise an amount not sent is the transaction's own, so a copy without the update (or with a key no field has, or always the body's) checks the same amount.
- `x__change__mutmut_101`: the user's session reads lots through their access view, which never returns a deleted lot (tried by hand: the second retype's query brings only the live one), so `Lot.deleted == false()` drops nothing.
- `x__change__mutmut_127`: `_transfer_lots` reads the namespace's `costBasis` with `getattr(..., None)`, so leaving it out gives the same None.

Bug:
- `x__change__mutmut_132`, `_136`: a transfer-in's lot is written only when it is made and by this branch, so the condition tells apart only through a lot a kind change leaves behind: a transfer-in changed to another kind (say transfer-out) keeps its lot, and changed back, that lot returns at its old day, out of step with the trade until its quantity or day changes. A test would pin a lot left by a kind change (S2.2, the lot follows its trade).

Mutation check: 102 killed, the 9 survivors exactly the equivalent and bug ones above.

Doubts:
- Pairing or unpairing a transfer by hand in a reconciled period asks nothing (`_txn_update` leaves `transferWithId` out of the change that asks); pinned as it is, since the pairing changes neither amount nor day, but S1's "editing a transaction inside a reconciled period asks first" could be read either way.
- An assignment's shares bought with a deliverable's cash have a basis below their amount (S3.10.4); a change to their quantity, amount or day sets the lot's basis to `-t.amount`, dropping that cash (by reading `_change`; not pinned). A memo change keeps it (pinned).
- `_txn_current` takes a transfer-in's `costBasis` from the first lot of any state (`.first()`, no deleted filter, no order) - after lots are typed again it may read a deleted lot; not pinned.
- Two waiting loops left from batch 2 (`until ! pgrep -f "mutate run moolakata/ui/transactions.py"`) never end: `pgrep -f` matches their own command line. Not mine; left for the coordinator.
- `--only-file docs/relay/batch-N.names` must be an absolute path: `mutate run` reads it from another directory.

## Batch 4

Test files touched: `tests/test_taxpanels.py`.

Counts: killed 118, equivalent 2, bug 1, unreachable 1, slow 0, still surviving 0.

Equivalent:
- `x__picks_fit__mutmut_7`: the caller's session reads picks through their access view, which never returns a deleted one (a pick taken away and another made in its place saves either way), so `LotPick.deleted == false()` drops nothing.
- `x__picks_fit__mutmut_14`: `sum` starting from `0` rather than `Decimal(0)` over Decimals gives the same Decimal, and over no picks `0 > abs(...)` decides as `Decimal(0)` does.

Bug:
- `x__picks_fit__mutmut_20`: tells apart only through a sale of no shares, and a sale's quantity can be changed to `0` or cleared (both answer 200, tried by hand), though making one without it is refused (`trade-incomplete`); a test would pin a sale with no quantity (R3.11, S2.3).

Unreachable:
- `x__pick_checked__mutmut_13`: the save's create check (`may_create`, LotPick seen through `lotId`) answers 404 for a lot unknown or typed over before `_pick_checked` runs; on an update, a pick whose lot was typed over is itself not found (404), so `lot` is never None or deleted there.

Mutation check: 118 killed, the 4 survivors exactly the equivalent, bug and unreachable ones above.

Doubts:
- A sale's quantity changed to `0` or cleared is saved (see the bug above); the create refuses both.
- A pick of a lot typed over afterwards (S2.2) drops out of the sale's picks unseen (the access view hides it, the row stays live); the sale falls back to its method without saying so. Not pinned.
- `_pick_sale`'s write check only decides when the lot named is of an account the caller writes and the sale's is one they only read (else `may_create` refuses on the lot first); the test names the caller's own lot for that.

## Batch 5

Test files touched: `tests/test_accounts.py`, `tests/test_txn_save.py`, `tests/test_taxpanels.py`.

Counts: killed 118, equivalent 4, bug 0, unreachable 11, slow 0, still surviving 0.

Equivalent:
- `x__lots_of__mutmut_7`: the caller's session reads lots through their access view, which never returns a deleted lot (as batch 3's `x__change__mutmut_101`), so `Lot.deleted == false()` drops nothing.
- `x__txn_current__mutmut_8`: for a transaction of no holding, `s.get(Instrument, None)` returns None (with a warning only), as the `else None` does.
- `x_lot_choices__mutmut_13`: every lot is made by a transaction (S2.2; `lots.replay` raises on one without), so `transactionId is None` is never true, and a lot of a transaction left out is never reached: the replay reads lots only through the transactions it replays.
- `x_lot_choices__mutmut_28`: the replay drops every lot of no shares (`out.open = [... if lot.quantity]`), so `> 0` and `>= 0` keep the same lots.

Unreachable:
- `x__set_of__mutmut_1` to `_8`: `_set_of()` runs once, at import, building `TxnRecord`'s fields; mutmut's workers fork from a process that has already imported the module, so the change is never the one in force. (A test of the contract, `uniqueItems` and the `[]` default on `tagIds`/`leftOutOf`, would hold it, but no run can show it killed.)
- `x_lot_choices__mutmut_66`, `_68`, `_69`: the `"?"` fallback: an open lot's instrument is one its transaction names, and instruments are never deleted and read by every signed-in user (schema.md §7), so the symbol is always found.

Mutation check: 118 killed, the 15 survivors exactly the equivalent and unreachable ones above.

Doubts:
- Lots carried in by a transfer paired with another account's transfer out (S2.2, S1.7.1) have no lot id in the replay, so `lot_choices` never offers them: a sale of carried shares can't pick its lots (S2.3). Not pinned; the test of what is offered uses a bought option for the lot without an id instead.
- One who only reads an account may send a transaction's fields as they are with a leave-out (S7.3.5) and is refused nothing: `_txn_update` asks the account's write only for fields that differ. Pinned (`test_one_who_reads_an_account_leaves_a_trade_out_with_its_draft_as_it_is`), as `_txn_editable`'s docstring says.
- Any function called only at import (as `_set_of`, from a model's class body) leaves survivors no test can kill; worth a line in mutation-testing.md if the coordinator agrees.

## Batch 6

Test files touched: `tests/test_accounts.py`, `tests/test_connections.py`.

Counts: killed 122, equivalent 17, bug 2, unreachable 0, slow 0, still surviving 0.

Equivalent:
- `x__change__mutmut_86`, `_186`: an update's `sent` is the fields that differ from the account as it is (`_account_update`), and on a create `later` holds `withdrawalsAMonth` and `statementInterval` only when not None, where a new account's are None: `in sent or differs` decides as `in sent and differs`.
- `x__change__mutmut_106`, `_107`, `_114` to `_118`: the limit's Problem carries its field error, and the save answers with the field errors alone (`save._Outcome`), dropping the Problem's own code and words; `_change` is called only through the save.
- `x__change__mutmut_160`, `_161`, `_168`, `_169`: likewise the coverage Problem's own code and words (its field error keeps `message`, which is held).
- `x__change__mutmut_202`: the body is always an `AccountRecord`, which has `statementIntervalDismissed`, so `getattr` without a default never misses.
- `x__change__mutmut_241`: `connectionId` not in `sent` means the body's is the account's (update) or None as the new account's (create), so `body.connectionId` is `a.connectionId`.
- `x__change__mutmut_253`: a connection is deleted only by Remove, which also makes it `removed` (or with its user), and the caller's view shows only their own: `deleted` never decides alone.
- `x__change__mutmut_276`: `syncAccount` not in `sent` means the body's is the account's, which is only ever kept stripped (or None, which `not which` refuses as `""` is).

Bug:
- `x__change__mutmut_138`, `_206`: tell apart only through an account made with `hsaCoverage` or `statementIntervalDismissed` and a field of `later`: `_make` and `later` leave both out, so a create drops them silently, an invalid dismissed interval included (refused on a change). A test would pin a value sent and dropped unrefused (S8.6, R3.11). New account's dialog never sends either.

Mutation check: 122 killed, the 19 survivors exactly the equivalent and bug ones above.

Doubts:
- A write share changes an account's notes (and opening balance and date): `settings_fields` leaves them out. Pinned for notes (`test_a_write_share_changes_an_accounts_notes_and_none_of_its_settings`) as S10.3 names only the name and method among an account's settings; worth a look if notes count as a setting.
- `REFUSED_WORDS` in `test_accounts.py` holds the words of every refusal in `test_an_accounts_settings_are_refused_on_their_own_field` (the existing test now checks field, code and message).
- `logged` in `test_accounts.py` (imported by `test_connections.py`) reads an account's Activity entries other than its creation and its sharing.

## Batch 7

Test files touched: `tests/test_accounts.py`, `tests/test_ledger.py`.

Counts: killed 131, equivalent 13, bug 0, unreachable 0, slow 0, still surviving 0.

Equivalent:
- `x_balance_on__mutmut_5`, `x_daily__mutmut_18`, `x__reconciliation_row__mutmut_5`: `sum` starting from `0` rather than a Decimal zero over Decimals, added to a Decimal opening balance, gives the same value and places.
- `x__reconciliation_row__mutmut_12`, `x__finish__mutmut_28`: both run only in the caller's session, which reads transactions through their access view, never a deleted one (as batch 3's `x__change__mutmut_101`).
- `x__recon_update__mutmut_2`: `_recon_current` never reads its `ctx`.
- `x__recon_update__mutmut_34`, `x__account_update__mutmut_69`: the mapping's `before_update` hook (`store/mapping.py` `_touch`) sets `updatedAt` to `clock.now()` on every flush of a changed record, and setting it to None changes the record too, so the version moves the same.
- `x__account_current__mutmut_8`: `keptBy` is NOT NULL (default `'["manual"]'`) and always written as a list's JSON, never empty, so the fallback is never read.
- `x__account_update__mutmut_30`, `_32`: `_check(body, None)` checks a change as a new account (name, type, the opening pair always); the fields not sent are the account's own, which passed those checks when made and at every change that touched them (the type never changes, and the table holds it to `ACCOUNT_TYPES`), so they refuse nothing more.
- `x__account_update__mutmut_37`, `_41`: `_account_editable` has already asked for write, so the permissions read without asking are the same `Perms`.

Mutation check: 131 killed (3 in `balances.py`, 128 in `accounts.py`), the 13 survivors exactly the equivalent ones above. `x__account_update__mutmut_17`, `_25` to `_27` (the type-fixed words) were already killed by batch 6's `REFUSED_WORDS`.

Doubts:
- `refusals(r)` in `test_accounts.py` reads a save's refusals as (field, code, words); earlier tests still spell it out inline.
- A read share changing a typed balance or a reconciliation is refused by `_anchor_editable`/`_recon_editable` as `share-read-only`; without that check the flush's own guard refuses it as `write-refused` in other words, so the tests hold the words.

## Batch 8

Test files touched: `tests/test_accounts.py`, `tests/test_txn_save.py`, `tests/test_taxpanels.py`,
`tests/test_adjusted.py`.

Counts: killed 71, equivalent 9, bug 2, unreachable 1, slow 0, still surviving 0.

Equivalent:
- `x__make__mutmut_5`, `_9`: the save's create check (`save.may_create`, Txn seen through `accountId`) asks the account's write before `_make` runs (a read share is refused there as `share-read-only`, one unknown or unread 404), so `access.account` without asking returns the same account and `Perms`.
- `x__txn_create__mutmut_14`: `_make`'s `confirm` is read only by `if confirm`, where `None` is `False`.
- `x__make__mutmut_212`, `_214`: a transaction just made has no tag links, so `set_on`'s owner (the query for current links) and `by` (only for one taken away) never decide.
- `x__raise__mutmut_3`: every `_raise` (transactions, items, options) runs inside the save, which answers a Problem with errors by its field errors alone, never its detail (`save._Outcome.attempt`).
- `x_shape__mutmut_28`: every caller's session reads splits through the access view, which never returns a deleted one (as batch 3's lots): `test_a_part_changed_or_taken_away_keeps_the_others_and_their_paybacks` reads a part deleted and the change still survives.
- `x_shape__mutmut_46`: picks of sales outside the rows are keyed by their own sale and never read for these rows.
- `x_shape__mutmut_43`: the caller's session reads picks joined to their access view, and the read without `ORDER BY` came back in id order however the picks were sent (ids against the ops' order, and against the lots' order); a test of the order kills nothing, so none is kept.

Bug:
- `x__make__mutmut_193`: tells apart only through a transfer-in or -out that could pair but was never offered: one whose day a change moves within a pair's days (or one freed when its partner goes) isn't offered (`propose` runs only when a transfer is made, never on a change; tried by hand), so a buy that ran `propose` would offer it. A test would pin a pair not offered (S1.7.1).
- `x__make__mutmut_229`: tells apart only through a trade other than a split sent with a `splitRatio`, which is saved with it, unrefused (a buy with `splitRatio` 2 answers 200 and keeps it; tried by hand); a test would pin a stray ratio accepted (R3.11, S2.4).

Unreachable:
- `x__make__mutmut_23`: `_make`'s only caller (`_txn_create`) passes `confirm=False`, so `closed.confirm` there never runs (the save asks the closed-year question itself).

Mutation check (`--tests` the four files above): 71 killed, the 12 survivors exactly the equivalent, bug and unreachable ones above (`x_shape__mutmut_43` rerun with `--only` after a second try at its order: still surviving). A baseline run with batches 1-7's tests (7 files) killed 10 of the 83 (`_make` 120, 163, 165, 166, 179, 187; `_txn_create` 21, 22, 26, 27).

Doubts:
- A transfer whose day is changed into a pair's days isn't offered as a pair until another transfer is made (the bug above); S1.7.1 reads as if it should be.
- A non-split trade keeps a `splitRatio` sent with it (the bug above); the lot replay ignores it, so it changes no figure.
- `_make`'s `confirm` parameter and its `closed.confirm` branch are dead: the save asks S2.8's question for every op.
- The batch's mutation runs are slow here (about 2 changes a minute with 4 to 7 whole test files); the baseline took 50 minutes.

## Batch 9

Test files touched: `tests/test_accounts.py`, `tests/test_txn_save.py`.

Counts: killed 93, equivalent 6, bug 0, unreachable 0, slow 0, still surviving 0.

Equivalent:
- `x__check_reimbursable__mutmut_6`: tells apart only with no amount, and a transaction's and a part's `amount` is a required `Money` (an update's fields are validated as the model after `save._merged`), so it is never None.
- `x__check_reimbursable__mutmut_11`, `_12`: with `r > 0`, an amount of 0 or more is refused by `r > -amount` anyway, so `amount >= 0` decides nothing of its own.
- `x__instrument__mutmut_23`: `repo.instrument` looks a symbol up by `.upper()` and makes one with `.upper()`, and the length check doesn't care about case, so a lowered symbol finds and makes the same instrument.
- `x__parts_add_up__mutmut_7`: the caller's session reads splits through their access view, which never returns a deleted one (as batch 8's `x_shape__mutmut_28`): `test_a_part_changed_or_taken_away_keeps_the_others_and_their_paybacks` deletes a part and adds up the rest, and the change still survives.
- `x__parts_add_up__mutmut_21`: `sum` starting from `0` rather than `Decimal(0)` over Decimals gives the same Decimal, and the parts are never empty there.

Mutation check (`--tests` the two files above): 93 killed, the 6 survivors exactly the equivalent ones above. No baseline run: nearly every survivor was a refusal's words, which no test held.

Doubts:
- `TXN_REFUSED_WORDS` in `test_accounts.py` holds the words of each refusal in `test_a_transactions_fields_are_refused_on_their_own`, which now checks every refusal's field, code and words (it read the first one's field and code only).
- `_check_reimbursable`'s `amount is None or amount >= 0` is redundant with `r > -amount` for a positive `r`; left as it is.
