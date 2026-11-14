"""What one who can only read sees (requirements S12.19.1), driven in headless Chromium: an
action not open to them is shown off, its reason its tooltip, and pressing it does nothing;
never hidden. A user is invited for the test, joins through the invitation's written email,
and is given the household's checking account to read."""

import re

import httpx
import pytest
from browser import PASSWORD, made, months_back, open_page, signed_in, wait
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
             ("giving-plan", plan["id"]), ("projection", h.extra["retire"]["id"]),
             ("tax-book", h.extra["book"]["id"]),
             ("account", h.extra["brokerage"]["id"])]  # fmt: skip
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
    # A budget the reader may change, counting the account it only reads: its leave-outs are
    # the reader's own (S12.19.5).
    theirs = made(make(h.c, "Bdgt", name="Rita's spending", accountIds=[h.checking["id"]]))
    made(share(h.c, "budget", theirs["id"], users={user["id"]: "write"}))
    user["a529"] = a529
    yield user
    made(remove(h.c, "Bdgt", h.c.get(f"/ui/api/budgets/{theirs['id']}").json(), confirm=True))
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


def test_a_reader_with_a_budget_of_their_own_leaves_a_transaction_out_of_it(
    browser, household, reader
):
    """S12.19.5: on an account the reader only reads, counted in a budget they may change,
    the tool is a pencil for what is theirs: the dialog names the transaction once, then its
    budgets, theirs to leave it out of, the others off saying why; nothing the row shows."""
    h = household
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/accounts/{h.checking['id']}/transactions", "table tbody tr .row-tool"
    )
    # The hotel bill, split in two: what it holds beyond its row is one line.
    tool = page.locator('tr:has-text("Grand Hotel") .row-tool')
    assert tool.get_attribute("aria-label") == "Leave Grand Hotel out of your budgets"
    tool.click()
    wait(page, ".dialog [role=switch]", problems)
    dialog = page.locator(".dialog")
    beyond = dialog.locator(".body p.small").first.inner_text()
    said, parts = beyond.split(" · split: ")
    assert said == "Money out", beyond
    assert sorted(parts.split(", ")) == ["Travel −$100.00", "Travel −$200.00"], beyond
    assert re.fullmatch(r".+ · [A-Z][a-z]{2} \d{1,2}, \d{4} · −?\$[\d,]+\.\d\d",
                        page.locator("#dialog-title").inner_text())  # fmt: skip
    assert dialog.locator(".in.read, input:not([type=file]), select, textarea").count() == 0
    theirs = dialog.get_by_role("switch", name="Leave out of Rita's spending")
    household_ = dialog.get_by_role("switch", name="Leave out of Household")
    assert theirs.get_attribute("aria-disabled") is None
    assert household_.get_attribute("aria-disabled") == "true"
    assert household_.get_attribute("data-tip") == READ
    save = dialog.locator("footer button.primary")
    assert save.is_disabled()
    theirs.click()
    assert save.is_enabled()
    theirs.click()
    assert save.is_disabled()
    dialog.locator('footer button:has-text("Close")').click()
    wait(page, ".dialog", problems, state="detached")
    assert problems == []
    page.close()


def test_a_reader_views_a_transaction_without_what_its_row_shows(browser, household, reader):
    """S12.18.6, S12.19.5: shares moved in, on an account read only: the eye opens it read,
    leaving out what the row shows and what is blank; its own actions off, saying why."""
    h = household
    page, problems = signed_in_as_reader(
        browser,
        h,
        f"/ui/accounts/{h.extra['brokerage']['id']}/transactions",
        'tr:has-text("transfer-in VTI") .row-tool',
    )
    tool = page.locator('tr:has-text("transfer-in VTI") .row-tool')
    assert tool.get_attribute("aria-label") == "View transfer-in VTI"
    tool.click()
    wait(page, ".dialog #f-kind", problems)
    dialog = page.locator(".dialog")
    assert page.locator("#dialog-title").inner_text() == "Transaction"
    for name in ("Delete", "Save", "Add a Lot", "Add a Receipt"):
        off(dialog, name)
    # Read, every field is its read persona: no control to type in or choose from.
    body = dialog.locator(".body")
    assert body.locator("input:not([type=file]), select, textarea").count() == 0
    # What its row shows is left out; a blank field isn't shown.
    for gone in ("#f-date", "#f-symbol", "#f-quantity", "#f-amount", "#f-account"):
        assert body.locator(gone).count() == 0, gone
    assert not body.locator("#f-memo").is_visible()
    kind = body.locator("#f-kind")
    assert kind.get_attribute("role") == "textbox"
    assert kind.get_attribute("aria-readonly") == "true"
    assert kind.get_attribute("aria-labelledby") == "lbl-f-kind"
    assert kind.inner_text() != "—"
    # Tab reaches a read value, and the help pane follows it.
    kind.focus()
    assert page.evaluate("document.activeElement.id") == "f-kind"
    dialog.locator('footer button:has-text("Close")').click()
    wait(page, ".dialog", problems, state="detached")
    assert problems == []
    page.close()


def test_a_readers_reconcile_tab_shows_its_checks_off(browser, household, reader):
    h = household
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/accounts/{h.checking['id']}/reconcile", "h3:has-text('Balance Checks')"
    )
    for name in ("Type Today's Balance", "Tick Off against a Statement"):
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
    off(page, "Add an Item")
    page.click('button[aria-label="View 1428 Elm St"]')
    wait(page, ".dialog", problems)
    dialog = page.locator(".dialog")
    for name in ("Save", "Add a Valuation", "Add Improvement", "Add", "Record the Sale…"):
        off(dialog, name)
    off(dialog, "Remove Kitchen remodel")
    read_only(dialog)
    # Its row shows its name; the address isn't on the row; a blank condition isn't shown.
    assert dialog.locator("#f-name").count() == 0
    assert dialog.locator("#f-address").inner_text() == "1428 Elm St"
    assert not dialog.locator("#f-condition").is_visible()
    # A yes or no keeps the switch's footprint, a check or a dash in it, never a live switch.
    home = dialog.locator("#f-primary-residence")
    assert home.get_attribute("role") == "switch"
    assert home.get_attribute("aria-readonly") == "true"
    assert home.get_attribute("aria-checked") == "true"
    assert problems == []
    page.close()


def test_a_readers_529_shows_its_contribution_and_expense_off(browser, household, reader):
    h = household
    a = reader["a529"]
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/accounts/{a['id']}/contributions", "text=Record a contribution"
    )
    off(page, "Record a Contribution")
    # Who each came from reads, its tag a value, never a list to change it (S12.18.6).
    who = page.locator('[aria-label^="Who the"]').first
    wait(page, '[aria-label^="Who the"]', problems)
    assert who.get_attribute("role") == "textbox"
    assert who.inner_text() == "Admin"
    assert page.locator("table select").count() == 0
    page.goto(h.base + f"/ui/accounts/{a['id']}/withdrawals")
    wait(page, "text=Add a qualified expense", problems)
    off(page, "Add a Qualified Expense")
    assert problems == []
    page.close()


def test_a_readers_budget_shows_its_changes_off(browser, household, reader):
    h = household
    page, problems = signed_in_as_reader(
        browser, h, f"/ui/budgets/{h.budget['id']}/month", "text=Edit plan"
    )
    off(page, "Share", "Only its owner shares it")
    for name in ("Settings", "Estimate from History…", "Edit Plan"):
        off(page, name)
    page.goto(h.base + f"/ui/budgets/{h.budget['id']}/review")
    wait(page, "#f-month-reviewed", problems)
    page.wait_for_selector("button:has-text('Mark Reviewed'), button:has-text('Review Again')")
    b = page.locator("button:has-text('Mark Reviewed'), button:has-text('Review Again')").first
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
    off(dialog, "Delete Plan", "Only its owner deletes it")
    off(dialog, "Add a Date")
    read_only(dialog)
    # Her row shows her name and the plan's budget; her birthday and the notes aren't on it.
    assert dialog.locator("#f-name").count() == 0
    assert dialog.locator("#f-gift-budget").count() == 0
    assert dialog.locator("#f-birthday").inner_text() == "2018-10-20"
    assert dialog.locator("#f-notes").inner_text() == "likes paints"
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
    assert problems == []
    page.close()


def test_a_readers_tax_book_opens_what_holds_more_than_its_row(browser, household, reader):
    """S12.19.5: a dependent whose line shows all of them has no tool; a tax document with
    notes, and a filing, open read through the eye, leaving out what their row or card shows."""
    h = household
    page, problems = signed_in_as_reader(browser, h, "/ui/taxes/summary", "text=Emma Griffin")
    assert page.locator('button[aria-label="View Emma Griffin"]').count() == 0
    page.goto(h.base + "/ui/taxes/documents")
    wait(page, 'button[aria-label="View W-2"]', problems)
    page.click('button[aria-label="View W-2"]')
    wait(page, ".dialog #f-notes", problems)
    dialog = page.locator(".dialog")
    assert dialog.locator("#f-notes").inner_text() == "the corrected copy"
    for gone in ("#f-form", "#f-issuer", "#x-direction", "#f-file"):
        assert dialog.locator(gone).count() == 0, gone
    off(dialog, "Remove")
    off(dialog, "Save")
    dialog.locator('footer button:has-text("Close")').click()
    wait(page, ".dialog", problems, state="detached")
    page.goto(h.base + "/ui/taxes/filings")
    tool = page.locator('h3:has-text("1040") .row-tool')
    wait(page, 'h3:has-text("1040") .row-tool', problems)
    assert tool.get_attribute("aria-label").startswith("View ")
    tool.click()
    wait(page, ".dialog #f-confirmation", problems)
    dialog = page.locator(".dialog")
    assert dialog.locator("#f-confirmation").inner_text() == "IRS-123"
    for gone in ("#f-form", "#x-progress", "#f-filed-on"):
        assert dialog.locator(gone).count() == 0, gone
    off(dialog, "Add a Payment")
    off(dialog, "Remove the payment")
    assert problems == []
    page.close()


def test_a_readers_giving_rows_that_show_all_have_no_tool(browser, household, reader):
    """S12.19.5: an organisation with nothing more than its row, read, has no tool."""
    h = household
    page, problems = signed_in_as_reader(
        browser, h, "/ui/giving/organisations", 'tr:has-text("St. Mark")'
    )
    assert page.locator('tr:has-text("St. Mark") .row-tool').count() == 0
    assert problems == []
    page.close()


def test_a_group_and_a_written_email_open_from_their_tools(browser, household, reader):
    """S12.19.5: Users › Groups and Settings › Email open from the pencil and the eye."""
    h = household
    page, problems = signed_in(browser, h, "/ui/users", 'button[aria-label="Edit Household"]')
    page.click('button[aria-label="Edit Household"]')
    wait(page, ".dialog", problems)
    page.keyboard.press("Escape")
    wait(page, ".dialog", problems, state="detached")
    page.goto(h.base + "/ui/settings/email")
    eye = page.locator('[data-help="written-emails"] .row-tool').first
    wait(page, '[data-help="written-emails"] .row-tool', problems)
    assert eye.get_attribute("aria-label").startswith("View ")
    eye.click()
    wait(page, ".dialog", problems)
    assert problems == []
    page.close()
