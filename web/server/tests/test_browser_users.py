"""Edit user's Save, as the dialog says what came of it (requirements S10.1.3, CR3-49), in
headless Chromium: a corrected address on an invited user sends the invitation again and says
where; any other change says Saved. With no public URL the toast says no invitation went (the
server's tests hold that case, which needs a server without one)."""

import pytest
from browser import Household, made, signed_in, wait
from edits import make

pytestmark = pytest.mark.browser


def invite(h: Household, username: str, email: str) -> dict:
    return made(make(h.c, "User", displayName=username.title(), username=username, email=email,
                     sex="female"))  # fmt: skip


def edit(browser, h: Household, name: str, fields: dict[str, str]) -> str:
    """The toast once the user's row is edited and saved."""
    page, problems = signed_in(browser, h, "/ui/users", f'tr:has-text("{name}")')
    page.click(f'tr:has-text("{name}") .row-tool')
    dialog = page.locator(".dialog")
    wait(page, '.dialog :text("Email address")', problems)
    for label, value in fields.items():
        dialog.get_by_label(label, exact=True).fill(value)
    page.click(".dialog footer button.primary:enabled")
    wait(page, ".toast", problems)
    said = page.locator(".toast").first.inner_text()
    assert problems == []
    page.close()
    return said


def test_a_corrected_address_says_where_the_invitation_went(browser, household):
    invite(household, "zed", "zed@hme.lan")
    assert edit(browser, household, "Zed", {"Email address": "zed@home.lan"}) == (
        "Saved. Invitation sent to zed@home.lan"
    )


def test_a_change_to_the_name_alone_says_saved(browser, household):
    invite(household, "yve", "yve@home.lan")
    assert edit(browser, household, "Yve", {"Name": "Yve Shaw"}) == "Saved"
