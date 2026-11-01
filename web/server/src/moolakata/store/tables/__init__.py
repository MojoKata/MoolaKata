"""Every table, on one MetaData, one module per area (requirements S14.1.1)."""

from . import (  # noqa: F401 - each adds its tables
    accounts,
    activity,
    alerts,
    assets,
    budgets,
    connector,
    core,
    education,
    giving,
    links,
    loans,
    options,
    people,
    prices,
    projections,
    receipts,
    shares,
    sharing,
    taxes,
    users,
    wallets,
)
from ._base import metadata

__all__ = ["metadata"]
