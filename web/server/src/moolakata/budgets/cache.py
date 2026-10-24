"""A budget's month figures, kept once worked out (requirements S7.3.10). Any write to what
they come from (a transaction, a split, a plan line, a move, a leave-out, a reimbursement, an
account, a category, a loan, a share, a plan elsewhere) moves the generation on, and a month
worked out before it is worked out again; Refresh forgets a budget's months at once."""

import threading
from collections import OrderedDict

from sqlalchemy import event

KEEP = 512  # months kept, the least recently used dropped first

_lock = threading.Lock()
_months: OrderedDict = OrderedDict()
_generation = 0
_watching = False


def _inputs() -> tuple[type, ...]:
    from ..store.entities import accounts as acc
    from ..store.entities import budgets as bd
    from ..store.entities import education as ed
    from ..store.entities import giving as gv
    from ..store.entities import projections as pj
    from ..store.entities import sharing as sh

    return (
        acc.Transaction,
        acc.Split,
        acc.Reimbursement,
        acc.Account,
        acc.Category,
        acc.Loan,
        acc.Anchor,
        bd.Budget,
        bd.BudgetAccount,
        bd.BudgetLine,
        bd.BudgetMove,
        bd.BudgetLeaveOut,
        ed.GiftPlan,
        ed.Occasion,
        gv.GivingPlan,
        pj.Projection,
        sh.Share,  # what a viewer's figures count follows what is shared with them
    )


def _written(_mapper, _connection, _target) -> None:
    global _generation
    with _lock:
        _generation += 1


def watch() -> None:
    """Listen for writes to what the figures come from: a row inserted, updated or deleted in
    one of those tables moves the generation on. Per table, so other writes cost nothing."""
    global _watching
    if _watching:
        return
    with _lock:
        if _watching:
            return
        for kind in _inputs():
            for name in ("after_insert", "after_update", "after_delete"):
                event.listen(kind, name, _written)
        _watching = True


def get(key: tuple):
    with _lock:
        hit = _months.get((_generation, *key))
        if hit is not None:
            _months.move_to_end((_generation, *key))
        return hit


def put(key: tuple, value) -> None:
    with _lock:
        _months[(_generation, *key)] = value
        while len(_months) > KEEP:
            _months.popitem(last=False)


def forget(budget_id: str) -> None:
    """Refresh: the budget's months are worked out again on their next read."""
    with _lock:
        for k in [k for k in _months if k[1] == budget_id]:
            del _months[k]
