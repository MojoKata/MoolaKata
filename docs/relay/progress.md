# Relay progress: H1.8's ledger survivors

Batches 1-7 (860 survivors, fork run 44505709314): 1-5 `ui/transactions.py`, 6 `ui/accounts.py`'s
`change`, 7 the rest of `ui/accounts.py` and `ledger/balances.py`. The rest round's survivors
(fork run 44561996257) come as batches 8 on. One agent at a time; the coordinator checks each
batch before the next starts.
