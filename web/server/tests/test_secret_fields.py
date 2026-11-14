"""A password field is the person's own password, nothing else (requirements S12.1.3): every
other secret (a recovery phrase, an API key, a bank's password for the connector) is the kit's
`secret`, plain text drawn blurred, so a password manager neither offers to fill it nor fills
the person's MoolaKata password into it."""

import re

from moolakata import paths

PASSWORD_FIELD = re.compile(r"""type=(?:"password"|\$\{[^}]*'password'[^}]*\})""")
LABEL = re.compile(r"""label=(?:"([^"]*)"|\$\{`([^`]*)`\}|\$\{'([^']*)'\})""")


def test_every_password_field_holds_the_persons_own_password():
    root = paths.WEB / "ui"
    found, seen = [], 0
    for sub in ("components", "screens"):
        for f in sorted((root / sub).glob("*.js")):
            src = f.read_text()
            for m in PASSWORD_FIELD.finditer(src):
                seen += 1
                labels = LABEL.findall(src[max(0, m.start() - 600) : m.start()])
                label = next((x for x in reversed(labels) for x in x if x), "")
                if "password" not in label.lower():
                    line = src.count("\n", 0, m.start()) + 1
                    found.append(f"{f.relative_to(root)}:{line} ({label or 'no label'})")
    # The person's own: signing in, setting up, a new password, confirming who they are.
    assert seen >= 10, "the fields are found"
    assert found == []
