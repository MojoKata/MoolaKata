"""An action not open to the reader is shown off with its reason, never hidden (S12.19.1).

Reads the browser app's source: an expression that draws a button only when the record allows
it (`access.writable`, `canWrite`, `canAdd(…)`, …) hides the action from one who may not; and a
button switched off by access, with `disabled`, gives no reason. Each is drawn with `<Action
why=…>` instead (`components/state.js`). A whole form or panel shown only to its writer is a
read view kept apart; those are named below, each with why.
"""

import re

from moolakata import paths

ACCESS = (
    r"(?:\.access\??\.(?:writable|shareable|deletable|configurable)"
    r"|\bcanWrite\b|\bcanEdit\b|\breadOnly\b|\bcanAdd\([^()]*\))"
)
# `<access> ? html`…<button…` up to the branch's end: the button drawn for some readers only.
HIDDEN = re.compile(
    ACCESS + r"\s*(?:&&[^?]{0,60})?\?\s*html`(?P<body>[^`]{0,600})`\s*:\s*null", re.S
)
OFF = re.compile(r"<button[^>]*\bdisabled=\$\{[^}]*" + ACCESS, re.S)

# Read views kept apart (S12.19.1: what a person can only read is shown as read): each a form
# or a panel whose every control edits, not an action beside what is read.
KEPT = {
    ("components/edu.js", "Retag"),  # a contribution's tag, a choice inside the row's edit
    ("components/loan.js", "Candidates"),  # bank transactions offered to link: the writer's
    ("components/wallet.js", "WalletFields"),  # the wallet's keys: its settings form
    ("screens/projections.js", "Inputs"),  # the inputs form; one who reads sees why instead
    ("screens/account.js", "TransferPairs"),  # transfers to pair: the owner's task list
}


def sources():
    root = paths.WEB / "ui"
    for sub in ("components", "screens"):
        for f in sorted((root / sub).glob("*.js")):
            yield f.relative_to(root).as_posix(), f.read_text()


def test_no_action_is_hidden_for_lack_of_access():
    found = []
    for name, src in sources():
        for m in HIDDEN.finditer(src):
            body = m.group("body")
            if "<button" not in body and 'class="btn' not in body:
                continue
            if any(n == name and f"<${{{c}}}" in body for n, c in KEPT):
                continue
            found.append(f"{name}:{src.count(chr(10), 0, m.start()) + 1}")
    assert not found, f"actions hidden for lack of access (draw them with <Action why>): {found}"


def test_no_action_is_off_for_lack_of_access_without_a_reason():
    found = [
        f"{name}:{src.count(chr(10), 0, m.start()) + 1}"
        for name, src in sources()
        for m in OFF.finditer(src)
    ]
    assert not found, f"buttons off for lack of access with no reason (use <Action why>): {found}"


def test_kept_read_views_are_still_there():
    """Each read view named above is still drawn by access, so the list can't go stale."""
    for name, comp in KEPT:
        src = (paths.WEB / "ui" / name).read_text()
        assert f"<${{{comp}}}" in src, f"{name} no longer draws {comp}: take it off KEPT"
