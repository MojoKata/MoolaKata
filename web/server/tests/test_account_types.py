"""The browser's account-type modules against the server's rules (requirements S1.1).

The New account dialog needs a type's flags before any account exists, so each module in
`ui/account-types/` carries them. The server decides the same things; a flag the two disagree
on shows a tab or a field the server won't serve, as a Reconcile tab once did (CR3-17). What
only the account's own row can say (its Reconcile tab) comes from the row, not a module."""

import re
from pathlib import Path

import pytest

from moolakata.ledger import types as atypes
from moolakata.loans import is_loan

TYPES = Path(__file__).resolve().parents[2] / "ui" / "account-types"
FIELD = re.compile(r"^  (\w+): (.+),$", re.M)


def module(path: Path) -> dict[str, str]:
    """A module's top-level fields, each value as written."""
    return dict(FIELD.findall(path.read_text()))


MODULES = {p.stem: module(p) for p in sorted(TYPES.glob("*.js")) if p.stem != "index"}


def test_there_is_a_module_for_every_type_and_no_other():
    assert set(MODULES) == set(atypes.GROUPS)


@pytest.mark.parametrize("name", sorted(atypes.GROUPS))
def test_a_module_agrees_with_the_server(name):
    m = MODULES[name]

    def flag(key: str) -> bool:
        return m.get(key, "false") != "false"

    assert m["type"] == f"'{name}'"
    assert m["group"] == f"'{atypes.GROUPS[name]}'"
    assert flag("investing") == atypes.investing(name)
    assert flag("contributions") == atypes.retirement(name)
    assert flag("loan") == is_loan(name)
    assert flag("education") == (atypes.GROUPS[name] == "education")
    assert flag("wallet") == (name == "crypto-wallet")
    assert flag("physical") == (atypes.GROUPS[name] == "physical-assets")


def test_no_module_says_which_accounts_have_a_reconcile_tab():
    """The tab follows the account's `reconcilable`, which the server sends (S1.11)."""
    assert not [n for n, m in MODULES.items() if "reconcilable" in m]
