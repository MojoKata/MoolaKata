"""A budget world's spending worked out apart from the app (requirements S7.3.1–S7.3.5), as
plainly as possible, from the world's description alone (`worlds.budget`): it imports nothing
of MoolaKata. What the owner's month says was spent is held to it, so a rule the app gets
wrong everywhere (its own figures still adding up) shows.
"""

from decimal import Decimal

from worlds import budget as bw

D = Decimal


def spent(w: bw.World, month: str) -> D:
    """What the budget's month counts spent, as its owner reads it: the spending of its
    accounts that month by their categories (S7.3.1), a split through its splits, a refund
    lowering it; a transfer between two of its accounts never (S7.3.1), one out of the budget
    by its category (S7.3.2), and one to a cash account without a category of its own as Cash;
    otherwise a transfer category, an uncategorised transaction and one left out (S7.3.5) count
    nowhere; reimbursable spending only the part not awaited (S7.3.4)."""
    total = D(0)
    for t in w.txns:
        if t.month != month or not w.counts(t.account, month):
            continue
        if t.shape == "left-out":
            continue
        if t.other in ("inside", "held-in"):
            continue  # between two of the budget's accounts
        if t.shape in ("uncategorised", "transfer-cat"):
            # Cash taken out to a cash account is spent, as Cash, without a category of its
            # own to count by (S7.3.2); any other such transfer counts nowhere.
            if t.other == "cash":
                total -= D(t.amount)
            continue
        if t.shape == "split":
            total -= sum((D(a) for _, a in t.parts), D(0))
        elif t.shape == "reimbursable":
            total -= D(t.amount) + D(t.reimbursable)
        else:
            total -= D(t.amount)
    return total
