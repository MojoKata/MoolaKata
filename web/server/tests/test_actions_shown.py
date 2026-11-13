"""An action not open to the reader is shown off with its reason, never hidden (S12.19.1).

Reads the browser app's source: an expression that draws a button only when the record allows
it (`access.writable`, `canWrite`, `canAdd(…)`, …) hides the action from one who may not; and a
button switched off by access, with `disabled`, gives no reason. Each is drawn with `<Action
why=…>` instead (`kit/state.js`). A form one may only read draws its read persona
(S12.18.6), never a disabled fieldset. A writer's list of tasks is theirs alone: those are
named below, each with why.
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

# A writer's lists of tasks (S12.19.1): what only the record's writer can do, theirs alone.
KEPT = {
    ("components/loan.js", "Candidates"),  # bank transactions offered to link: the writer's
    ("screens/account.js", "TransferPairs"),  # transfers to pair: the owner's task list
}
# A form switched off whole: what it reads is drawn in its read persona instead.
FIELDSET_OFF = re.compile(r"<fieldset\b[^>]*\bdisabled=", re.S)


def sources():
    root = paths.WEB / "ui"
    for sub in ("kit", "components", "screens"):
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


def test_no_form_is_switched_off_whole():
    found = [
        f"{name}:{src.count(chr(10), 0, m.start()) + 1}"
        for name, src in sources()
        for m in FIELDSET_OFF.finditer(src)
    ]
    assert not found, f"forms switched off with a disabled fieldset (use Reading): {found}"


def test_kept_task_lists_are_still_there():
    """Each task list named above is still drawn by access, so the list can't go stale."""
    for name, comp in KEPT:
        src = (paths.WEB / "ui" / name).read_text()
        assert f"<${{{comp}}}" in src, f"{name} no longer draws {comp}: take it off KEPT"
