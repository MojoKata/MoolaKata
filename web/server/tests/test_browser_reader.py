"""What one who can only read sees (requirements S12.19.1), driven in headless Chromium: an
action not open to them is shown off, its reason its tooltip, and pressing it does nothing;
never hidden. A user is invited for the test, joins through the invitation's written email,
and is given the household's checking account to read."""

import re

import httpx
import pytest
from browser import PASSWORD, made, open_page, wait
from edits import make, share

pytestmark = pytest.mark.browser

READER_PW = "a long reader passphrase"


@pytest.fixture(scope="module")
def reader(household):
    """A user who reads the household's checking account, signed in by their own password."""
    h = household
    # Reading a written email asks for the password again (S13.7.2): a fresh sign-in.
    r = h.c.post("/ui/api/session", json={"login": "admin", "password": PASSWORD})
    assert r.status_code == 200, r.text
    user = made(make(h.c, "User", displayName="Rita Reader", username="rita",
                     email="rita@home.lan", sex="female"))  # fmt: skip
    written = h.c.get("/ui/api/settings/email/written").json()["items"]
    [mail] = [m for m in written if "rita@home.lan" in m["to"]]
    text = h.c.get(f"/ui/api/settings/email/written/{mail['name']}").json()["text"]
    token = re.search(r"https?://\S+#(\S+)", text).group(1)
    with httpx.Client(base_url=h.base, verify=False, headers={"Origin": h.base}) as anon:
        r = anon.post("/ui/api/invitations/accept", json={"token": token, "password": READER_PW})
        assert r.status_code == 200, r.text
    made(share(h.c, "account", h.checking["id"], users={user["id"]: "read"}))
    return user


def signed_in_as_reader(browser, h, path: str, ready: str):
    page, problems = open_page(browser, h.base + "/ui/")
    r = page.request.post(h.base + "/ui/api/session",
                          data={"login": "rita", "password": READER_PW},
                          headers={"Origin": h.base})  # fmt: skip
    assert r.ok, r.text()
    page.goto(h.base + path)
    wait(page, ready, problems)
    return page, problems


def test_actions_not_open_to_a_reader_are_shown_off_with_why(browser, household, reader):
    h = household
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/accounts/{h.checking['id']}/transactions", "table tbody tr"
    )
    for name in ("Import", "Add"):
        b = page.get_by_role("button", name=name, exact=True)
        assert b.get_attribute("aria-disabled") == "true", name
        assert b.get_attribute("data-tip") == "Shared with you to read", name
        assert b.get_attribute("aria-description") == "Shared with you to read", name
    # Pressed, it opens nothing; reached by Tab, it shows its reason.
    page.get_by_role("button", name="Add", exact=True).click(force=True)
    page.wait_for_timeout(200)
    assert page.locator(".dialog").count() == 0
    page.get_by_role("button", name="Add", exact=True).focus()
    wait(page, '.tooltip:has-text("Shared with you to read")', problems)
    # On Accounts, the account it can only read: Share is shown, off, saying whose it is.
    page.goto(h.base + "/ui/accounts")
    share_btn = page.get_by_role("button", name="Share Checking")
    wait(page, "table", problems)
    assert share_btn.get_attribute("aria-disabled") == "true"
    assert share_btn.get_attribute("data-tip") == "Only its owner shares it"
    assert problems == []
    page.close()
