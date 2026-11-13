"""What one who can only read sees (requirements S12.19.1), driven in headless Chromium: an
action not open to them is shown off, its reason its tooltip, and pressing it does nothing;
never hidden. A user is invited for the test, joins through the invitation's written email,
and is given the household's checking account to read."""

import re

import httpx
import pytest
from browser import PASSWORD, made, months_back, open_page, wait
from edits import make, plan529, remove, saved, share

# One after another on one worker: the reader and what it is given are undone after them, so
# the household the other browser tests share is as it was.
pytestmark = [pytest.mark.browser, pytest.mark.xdist_group("reader")]

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
    rita = {user["id"]: "read"}
    plan = h.c.get("/ui/api/giving", params={"year": int(months_back(0)[:4])}).json()["plan"]
    given = [("account", h.checking["id"]), ("account", h.extra["homes"]["id"]),
             ("budget", h.budget["id"]), ("gift-plan", h.extra["emma"]["id"]),
             ("giving-plan", plan["id"]), ("projection", h.extra["retire"]["id"])]  # fmt: skip
    # And a 529 of its own, for its contributions and expenses.
    a529 = made(make(h.c, "Acct", name="Reader's 529", type="529", institution="my529"))
    emma = h.c.get(f"/ui/api/persons/{h.extra['emma']['personId']}").json()
    saved(plan529(h.c, a529["id"], planState="Utah", planName="my529", beneficiaryId=emma["id"],
                  openedOn="2018-05-02", stateDeduction="2410"))  # fmt: skip
    made(make(h.c, "Txn", accountId=a529["id"], date=f"{months_back(1)}-05", kind="deposit",
              amount="2500"))  # fmt: skip
    given.append(("account", a529["id"]))
    for kind, item in given:
        made(share(h.c, kind, item, users=rita))
    user["a529"] = a529
    yield user
    # Undone: nothing shared with the reader any more, and the 529 gone.
    for kind, item in given:
        made(share(h.c, kind, item, users={user["id"]: "none"}))
    made(remove(h.c, "Acct", h.c.get(f"/ui/api/accounts/{a529['id']}").json(), confirm=True))


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


def test_a_reader_opens_a_transaction_its_changes_off(browser, household, reader):
    """S12.19.1: the dialog shows the transaction; Delete and Save are off, saying why, and
    Add a receipt too; Close closes it."""
    h = household
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/accounts/{h.checking['id']}/transactions", "table tbody tr"
    )
    # The eye at the row's end opens it read (S12.19.5).
    tool = page.locator("table tbody tr .row-tool").first
    assert tool.get_attribute("aria-label").startswith("View ")
    tool.click()
    wait(page, ".dialog", problems)
    assert page.locator("#dialog-title").inner_text() == "Transaction"
    for name in ("Delete", "Save", "Add a receipt"):
        b = page.locator(".dialog").get_by_role("button", name=name, exact=True)
        assert b.get_attribute("aria-disabled") == "true", name
        assert b.get_attribute("data-tip") == "Shared with you to read", name
    # Read, every field is its read persona (S12.18.6): no control to type in or choose from.
    dialog = page.locator(".dialog .body")
    assert dialog.locator("input:not([type=file]), select, textarea").count() == 0
    assert dialog.locator(".in.read").count() >= 4
    date = dialog.locator("#f-date")
    assert date.get_attribute("role") == "textbox"
    assert date.get_attribute("aria-readonly") == "true"
    assert date.get_attribute("aria-labelledby") == "f-date-label"
    assert re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", date.inner_text())
    assert dialog.locator("#f-amount").inner_text().startswith(("$", "−$"))
    # Tab reaches a read value, and the help pane follows it.
    date.focus()
    assert page.evaluate("document.activeElement.id") == "f-date"
    page.screenshot(
        path="/tmp/claude-1000/-home-dev-kata-MoolaKata/fceeb2e9-8ad1-4304-bb0d-696ee67b0a32/scratchpad/read-txn.png"
    )
    page.locator('.dialog footer button:has-text("Close")').click()
    wait(page, ".dialog", problems, state="detached")
    assert problems == []
    page.close()


def test_a_readers_reconcile_tab_shows_its_checks_off(browser, household, reader):
    h = household
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/accounts/{h.checking['id']}/reconcile", "h3:has-text('Balance checks')"
    )
    for name in ("Type today's balance", "Tick off against a statement"):
        b = page.get_by_role("button", name=name, exact=True).first
        assert b.get_attribute("aria-disabled") == "true", name
        assert b.get_attribute("data-tip") == "Shared with you to read", name
    assert problems == []
    page.close()


READ = "Shared with you to read"


def off(scope, name: str, why: str = READ) -> None:
    """The action is shown, off, its reason its tooltip (S12.19.1)."""
    b = scope.get_by_role("button", name=name, exact=True).first
    assert b.get_attribute("aria-disabled") == "true", name
    assert b.get_attribute("data-tip") == why, (name, b.get_attribute("data-tip"))


def read_only(dialog) -> None:
    """Every field of the dialog is its read persona (S12.18.6): nothing to type or choose."""
    assert dialog.locator("input:not([type=file]), select, textarea, .chip").count() == 0
    assert dialog.locator(".in.read").count() >= 3


def test_a_readers_item_shows_its_changes_off(browser, household, reader):
    h = household
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/accounts/{h.extra['homes']['id']}/items", "text=1428 Elm St"
    )
    off(page, "Add an item")
    page.click('button[aria-label="View 1428 Elm St"]')
    wait(page, ".dialog", problems)
    dialog = page.locator(".dialog")
    for name in ("Save", "Add a valuation", "Add improvement", "Add", "Record the sale…"):
        off(dialog, name)
    off(dialog, "Remove Kitchen remodel")
    read_only(dialog)
    assert dialog.locator("#f-name").inner_text() == "1428 Elm St"
    # A yes or no keeps the switch's footprint, a check or a dash in it, never a live switch.
    home = dialog.locator("#f-primary-residence")
    assert home.get_attribute("role") == "switch"
    assert home.get_attribute("aria-readonly") == "true"
    assert home.get_attribute("aria-checked") == "true"
    page.screenshot(
        path="/tmp/claude-1000/-home-dev-kata-MoolaKata/fceeb2e9-8ad1-4304-bb0d-696ee67b0a32/scratchpad/read-item.png"
    )
    assert problems == []
    page.close()


def test_a_readers_529_shows_its_contribution_and_expense_off(browser, household, reader):
    h = household
    a = reader["a529"]
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/accounts/{a['id']}/contributions", "text=Record a contribution"
    )
    off(page, "Record a contribution")
    # Who each came from reads, its tag a value, never a list to change it (S12.18.6).
    who = page.locator('[aria-label^="Who the"]').first
    wait(page, '[aria-label^="Who the"]', problems)
    assert who.get_attribute("role") == "textbox"
    assert who.inner_text() == "Admin"
    assert page.locator("table select").count() == 0
    page.goto(h.base + f"/ui/accounts/{a['id']}/withdrawals")
    wait(page, "text=Add a qualified expense", problems)
    off(page, "Add a qualified expense")
    assert problems == []
    page.close()


def test_a_readers_budget_shows_its_changes_off(browser, household, reader):
    h = household
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/budgets/{h.budget['id']}/month", "text=Edit plan"
    )
    off(page, "Share", "Only its owner shares it")
    for name in ("Settings", "Estimate from history…", "Edit plan"):
        off(page, name)
    page.goto(h.base + f"/ui/budgets/{h.budget['id']}/review")
    wait(page, "#f-month-reviewed", problems)
    page.wait_for_selector("button:has-text('Mark reviewed'), button:has-text('Review again')")
    b = page.locator("button:has-text('Mark reviewed'), button:has-text('Review again')").first
    assert b.get_attribute("aria-disabled") == "true"
    assert b.get_attribute("data-tip") == READ
    assert problems == []
    page.close()


def test_a_readers_gift_plan_and_giving_plan_show_their_changes_off(browser, household, reader):
    h = household
    page, problems = signed_in_as_reader(browser, h, "/ui/giving", "text=shared by")
    off(page, "Edit")
    page.goto(h.base + "/ui/gifts/people")
    wait(page, "text=Emma Griffin", problems)
    page.click('button[aria-label="View the gift plan for Emma Griffin"]')
    wait(page, ".dialog", problems)
    dialog = page.locator(".dialog")
    off(dialog, "Save")
    off(dialog, "Share", "Only its owner shares it")
    off(dialog, "Delete plan", "Only its owner deletes it")
    off(dialog, "Add a date")
    read_only(dialog)
    assert dialog.locator("#f-name").inner_text() == "Emma Griffin"
    page.screenshot(
        path="/tmp/claude-1000/-home-dev-kata-MoolaKata/fceeb2e9-8ad1-4304-bb0d-696ee67b0a32/scratchpad/read-plan.png"
    )
    assert problems == []
    page.close()


def test_a_category_another_may_delete_shows_delete_off_with_why(browser, household, reader):
    """S12.19.1: a shipped category nothing uses is an admin's to delete; for anyone else its
    Delete is shown off, saying so, never replaced by a line."""
    h = household
    items = h.c.get("/ui/api/categories").json()["items"]
    cat = next(c for c in items if c["shipped"] and not c["inUse"] and not c["serverNamed"])
    page, problems = signed_in_as_reader(
        browser, h, "/ui/budgets/none/categories", "table.categories"
    )
    page.click(f'button[aria-label="Edit {cat["path"]}"]')
    wait(page, ".dialog #f-name", problems)
    off(page.locator(".dialog"), "Delete", "Only admins delete a shipped category")
    assert "Only admins delete" not in page.locator(".dialog .body").inner_text()
    assert problems == []
    page.close()


def test_a_readers_projection_shows_its_inputs_read_and_run_off(browser, household, reader):
    """S12.18.6: the inputs one may only read are read values; Run is off, saying why."""
    h = household
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/projections/{h.extra['retire']['id']}", "h3:has-text('Inputs')"
    )
    card = page.locator("form.card:has(h3:has-text('Inputs'))")
    off(card, "Run")
    read_only(card)
    assert card.locator("#f-retirement-age").inner_text() == "62"
    assert card.locator("#f-contribution").inner_text() == "$30,000.00"
    # The portfolio it is built on isn't shared with the reader: said so, never its id.
    assert card.locator("#f-built-on").inner_text() == "Not shared with you"
    page.screenshot(
        path="/tmp/claude-1000/-home-dev-kata-MoolaKata/fceeb2e9-8ad1-4304-bb0d-696ee67b0a32/scratchpad/read-proj.png"
    )
    assert problems == []
    page.close()
