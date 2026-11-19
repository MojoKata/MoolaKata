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
