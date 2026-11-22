# Relay progress: settling H1.9's mutation survivors

13 batches, 877 survivors and 31 no-tests changes, from the fork's CI runs 44963061557 and
44989210873 (mutmut on `af202cf5`): batches 1–4 `loans/__init__.py` and `loans/payoff.py`,
5–11 `ui/loans.py`, 12–13 `assets/__init__.py` and `ui/items.py`. One agent at a time; the
coordinator checks each batch before the next starts.
