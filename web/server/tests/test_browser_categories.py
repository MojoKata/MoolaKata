"""The household's categories in the browser (requirements S7.2.3, S7.2.4, S12.2.6), in headless
Chromium: Budgets › Categories lists the tree and adds one; a category's dialog renames it and
shows what is locked, with why; New category… at the end of a transaction's list makes one in
the same save, and in a row's list in a dialog of its own; and an admin's merge maps each of the
category's own categories, starting from the names they share."""

import pytest
from browser import Household, made, months_back, signed_in, wait
from edits import make

pytestmark = pytest.mark.browser

TAB = "/ui/budgets/none/categories"


def cats(h: Household) -> dict[str, dict]:
    return {x["path"]: x for x in h.c.get("/ui/api/categories").json()["items"]}


def new(h: Household, name: str, **kw) -> dict:
    return made(make(h.c, "Cat", name=name, kind=kw.pop("kind", "expense"), **kw))


def test_the_tab_lists_the_tree_and_adds_a_category(browser, household):
    h = household
    page, problems = signed_in(browser, h, TAB, 'table.categories td:has-text("Groceries")')
    assert page.locator("[role=tab][aria-selected=true]").inner_text().strip() == "Categories"
    page.click('main button:has-text("Add a Category")')
    wait(page, ".dialog #f-name", problems)
    page.fill(".dialog #f-name", "Browser pets")
    page.select_option(".dialog #f-tax-tag", "medical")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    wait(page, 'table.categories td:has-text("Browser pets")', problems)
    got = cats(h)["Browser pets"]
    assert got["taxTag"] == "medical" and got["parentId"] is None and not got["shipped"]
    row = page.locator('table.categories tr:has-text("Browser pets")')
    assert "you" in row.inner_text()
    assert problems == []
    page.close()


def test_a_category_is_renamed_and_what_stays_is_locked(browser, household):
    h = household
    page, problems = signed_in(browser, h, TAB, 'table.categories td:has-text("Gifts")')
    # The server counts in Gifts by its own rules: its kind stays, even for an admin.
    page.click('button[aria-label="Edit Gifts"]')
    wait(page, ".dialog #f-name", problems)
    assert page.is_disabled(".dialog #f-kind") and not page.is_disabled(".dialog #f-under")
    assert page.locator('.dialog button:has-text("Delete")').count() == 0
    page.keyboard.press("Escape")
    wait(page, ".dialog", problems, state="detached")
    mine = new(h, "Browser hobbies")
    page.reload()
    wait(page, 'button[aria-label="Edit Browser hobbies"]', problems)
    page.click('button[aria-label="Edit Browser hobbies"]')
    wait(page, ".dialog #f-name", problems)
    page.fill(".dialog #f-name", "Browser crafts")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    wait(page, 'table.categories td:has-text("Browser crafts")', problems)
    assert cats(h)["Browser crafts"]["id"] == mine["id"]
    assert problems == []
    page.close()


def test_a_category_nothing_uses_is_deleted_from_its_dialog(browser, household):
    h = household
    new(h, "Browser spare")
    page, problems = signed_in(browser, h, TAB, 'button[aria-label="Edit Browser spare"]')
    page.click('button[aria-label="Edit Browser spare"]')
    wait(page, '.dialog button:has-text("Delete")', problems)
    page.click('.dialog button:has-text("Delete")')
    wait(page, '.dialog-ask-box button:text-is("Yes")', problems)
    page.click('.dialog-ask-box button:text-is("Yes")')
    wait(page, ".dialog", problems, state="detached")
    assert "Browser spare" not in cats(h)
    assert problems == []
    page.close()


TOP = ".dialog-layer:not([inert])"


def until(page, expr: str) -> None:
    """Poll an expression from outside the page (the app's CSP refuses a string evaluated
    inside it), for up to 30 s."""
    for _ in range(600):
        if page.evaluate(expr):
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"never true: {expr}")


def test_a_new_category_from_a_dialog_opens_over_it_and_is_chosen(browser, household):
    """S12.15.7: New category… opens New category over the transaction's dialog, which waits
    as it was; saved there, the category is chosen in the field that offered it. Cancelled,
    the choice is as it was."""
    h = household
    path = f"/ui/accounts/{h.checking['id']}/transactions"
    page, problems = signed_in(browser, h, path, 'main button:has-text("Add")')
    page.click('main button:has-text("Add")')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.fill(".dialog #f-date", f"{months_back(1)}-14")
    page.fill(".dialog #f-amount", "-31.00")
    page.fill(".dialog #f-payee", "Browser vet")
    page.select_option(".dialog #f-category", "new-category")
    wait(page, f"{TOP} #d1-f-name", problems)
    assert page.locator(".dialog").count() == 2
    page.keyboard.press("Escape")
    wait(page, ".dialog-layer", problems, state="attached")
    until(page, "document.querySelectorAll('.dialog').length === 1")
    until(page, "document.querySelector('.dialog #f-category').value === ''")
    assert page.input_value(".dialog #f-payee") == "Browser vet", "the dialog beneath waits"
    page.select_option(".dialog #f-category", "new-category")
    wait(page, f"{TOP} #d1-f-name", problems)
    page.fill(f"{TOP} #d1-f-name", "Browser vet bills")
    page.select_option(f"{TOP} #d1-f-under", label="Health")
    page.select_option(f"{TOP} #d1-f-tax-tag", "medical")
    page.click(f"{TOP} footer button.primary")
    until(page, "document.querySelectorAll('.dialog').length === 1")
    made_cat = cats(h)["Health › Browser vet bills"]
    assert made_cat["taxTag"] == "medical"
    until(page, f"document.querySelector('.dialog #f-category').value === {made_cat['id']!r}")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    rows = h.c.get("/ui/api/transactions", params={"payee": "Browser vet"}).json()["items"]
    assert [t["categoryId"] for t in rows] == [made_cat["id"]]
    assert problems == []
    page.close()


def test_a_new_category_from_a_rows_list_opens_its_own_dialog(browser, household):
    h = household
    t = made(
        make(
            h.c,
            "Txn",
            accountId=h.checking["id"],
            date=f"{months_back(1)}-16",
            amount="-12.00",
            payee="Browser florist",
        )
    )
    path = f"/ui/accounts/{h.checking['id']}/transactions"
    picker = 'select[aria-label="Category of Browser florist"]'
    page, problems = signed_in(browser, h, path, picker)
    page.select_option(picker, "new-category")
    wait(page, ".dialog #f-name", problems)
    page.fill(".dialog #f-name", "Browser flowers")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    wait(page, ".toast:has-text('categorised')", problems)
    assert (
        h.c.get(f"/ui/api/transactions/{t['id']}").json()["categoryId"]
        == cats(h)["Browser flowers"]["id"]
    )
    assert problems == []
    page.close()


def test_a_merge_maps_each_of_its_categories(browser, household):
    h = household
    pet = new(h, "Browser pet")
    dog = new(h, "Dog", parentId=pet["id"])
    cat = new(h, "Cat", parentId=pet["id"])
    pets = new(h, "Browser pets two")
    dogs = new(h, "dog", parentId=pets["id"])
    new(h, "Birds", parentId=pets["id"])
    page, problems = signed_in(browser, h, TAB, 'button[aria-label="Merge Browser pet"]')
    page.click('button[aria-label="Merge Browser pet"]')
    wait(page, ".dialog #f-merge-into", problems)
    page.select_option(".dialog #f-merge-into", label="Browser pets two")
    dog_pick, cat_pick = (
        f".dialog #x-merge-child-{dog['id']}",
        f".dialog #x-merge-child-{cat['id']}",
    )
    wait(page, dog_pick, problems)
    # Dog meets dog, whatever the case; Cat has no namesake, so it moves across.
    assert page.input_value(dog_pick) == dogs["id"]
    assert page.input_value(cat_pick) == cat["id"]
    wait(page, '.dialog [data-help="merge-budgets"]', problems)
    page.click(".dialog footer button.danger")
    wait(page, '.dialog-ask-box button:text-is("Yes")', problems)
    page.click('.dialog-ask-box button:text-is("Yes")')
    wait(page, ".dialog", problems, state="detached")
    now = cats(h)
    assert "Browser pet" not in now and "Browser pets two › Cat" in now
    assert now["Browser pets two › dog"]["id"] == dogs["id"]
    assert problems == []
    page.close()
