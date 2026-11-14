"""Transactions › Rules in the browser (requirements S2.7, S12.2.3.2), in headless Chromium: each
rule at its own address, chosen from the list beside it; Discard and Save only while it holds
changes, and what acts on the saved rules off meanwhile, saying why; leaving it asks Keep editing,
Discard or Save; Add rule puts a new one in the list until it is saved or discarded; and Make a
rule opens New rule over a transaction's dialog, which stays as it was (S2.7.6, S12.15.7)."""

import pytest
from browser import Household, made, months_back, signed_in, wait
from edits import make, remove, saved

pytestmark = pytest.mark.browser

RULES = "/ui/transactions/rules"
PANE = ".rule-pane"
TOP = ".dialog-layer:not([inert])"


def rules(h: Household) -> list[dict]:
    return h.c.get("/ui/api/rules").json()["items"]


def rule(h: Household, rule_id: str) -> dict | None:
    return next((x for x in rules(h) if x["id"] == rule_id), None)


def new_rule(h: Household, payee: str) -> dict:
    return made(make(h.c, "Rule", payeeMatch=payee, categoryId=h.cats["Food › Groceries"]))


def drop(h: Household, *ids: str) -> None:
    for rule_id in ids:  # each read anew: a delete renumbers the rest
        r = rule(h, rule_id)
        if r:
            saved(remove(h.c, "Rule", r))


def until(page, expr: str) -> None:
    """Poll an expression from outside the page (the app's CSP refuses a string evaluated
    inside it), for up to 30 s."""
    for _ in range(600):
        if page.evaluate(expr):
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"never true: {expr}")


def buttons(page) -> list[str]:
    """The pane's buttons, as drawn."""
    return [x.strip() for x in page.locator(f"{PANE} .toolbar button").all_inner_texts()]


def held(page) -> list[bool]:
    """Whether each button that acts on the saved rules is off and says why."""
    return page.evaluate(
        """[...document.querySelectorAll('.rules-layout .card:first-child button')]
          .filter((b) => b.textContent.includes('Apply') || /^[↑↓]$/.test(b.textContent.trim()))
          .map((b) => b.disabled && b.parentElement.dataset.tip === 'Save changes first')"""
    )


def test_a_rule_at_its_address_saves_only_while_changed(browser, household):
    """S12.2.3.2.1, S12.2.3.2.4: the rule chosen by its address; Discard and Save show while it
    holds changes and go when it is put back; ↑, ↓ and Apply wait for a save, saying why."""
    h = household
    first, second = new_rule(h, "browser bakery"), new_rule(h, "browser bagels")
    page, problems = signed_in(browser, h, f"{RULES}/{first['id']}", f"{PANE} #f-payee-contains")
    assert page.input_value(f"{PANE} #f-payee-contains") == "browser bakery"
    assert (
        page.locator('a.rule-link[aria-current="true"]').inner_text().startswith("“browser bakery”")
    )
    assert buttons(page) == ["Delete"]
    assert not any(held(page))
    page.fill(f"{PANE} #f-payee-contains", "browser bakery shop")
    until(page, "!!document.querySelector('.rule-pane .toolbar button.primary')")
    assert buttons(page) == ["Delete", "Discard", "Save"]
    assert held(page) and all(held(page))
    page.fill(f"{PANE} #f-payee-contains", "browser bakery")
    until(page, "!document.querySelector('.rule-pane .toolbar button.primary')")
    assert buttons(page) == ["Delete"]
    assert not any(held(page))
    page.fill(f"{PANE} #f-payee-contains", "browser bakery shop")
    page.click(f"{PANE} .toolbar button:has-text('Discard')")
    until(page, "!document.querySelector('.rule-pane .toolbar button.primary')")
    assert page.input_value(f"{PANE} #f-payee-contains") == "browser bakery"
    page.fill(f"{PANE} #f-payee-contains", "browser bakery shop")
    page.click(f"{PANE} .toolbar button.primary")
    wait(page, ".toast:has-text('Rule saved')", problems)
    until(page, "!document.querySelector('.rule-pane .toolbar button.primary')")
    assert rule(h, first["id"])["payeeMatch"] == "browser bakery shop"
    drop(h, first["id"], second["id"])
    assert problems == []
    page.close()


def test_leaving_a_changed_rule_asks_first(browser, household):
    """S12.2.3.2.3, S12.15.6: another rule, or the other tab, asks: Keep editing stays with what
    was typed, Discard goes on and saves nothing, Save saves and goes on."""
    h = household
    first, second = new_rule(h, "browser cheese"), new_rule(h, "browser chocolate")
    page, problems = signed_in(browser, h, f"{RULES}/{first['id']}", f"{PANE} #f-payee-contains")
    page.fill(f"{PANE} #f-rename-to", "Cheese shop")
    page.click(f'a.rule-link[href$="{second["id"]}"]')
    wait(page, "text=Save your changes?", problems)
    page.click('.dialog footer button:has-text("Keep editing")')
    wait(page, ".dialog", problems, state="detached")
    assert page.url.endswith(first["id"])
    assert page.input_value(f"{PANE} #f-rename-to") == "Cheese shop"
    page.click(f'a.rule-link[href$="{second["id"]}"]')
    wait(page, "text=Save your changes?", problems)
    page.click('.dialog footer button:has-text("Discard")')
    page.wait_for_url(f"**{RULES}/{second['id']}")
    until(
        page,
        "document.querySelector('.rule-pane #f-payee-contains')?.value === 'browser chocolate'",
    )
    assert not rule(h, first["id"]).get("payee")
    page.fill(f"{PANE} #f-rename-to", "Chocolatier")
    page.click('a.tab:has-text("Transactions")')
    wait(page, "text=Save your changes?", problems)
    page.click('.dialog footer button:has-text("Save")')
    page.wait_for_url("**/ui/transactions")
    assert rule(h, second["id"])["payee"] == "Chocolatier"
    drop(h, first["id"], second["id"])
    assert problems == []
    page.close()


def test_add_rule_is_in_the_list_until_saved_or_discarded(browser, household):
    """S12.2.3.2.2: Add rule puts a new rule at the end, not saved, with Discard and Save;
    Discard takes it out; saved, it takes its own address; Delete asks, then removes it."""
    h = household
    before = len(rules(h))
    page, problems = signed_in(browser, h, RULES, "a.btn:has-text('Add rule')")
    assert "Choose a rule" in page.inner_text(".rules-layout")
    page.click("a.btn:has-text('Add rule')")
    page.wait_for_url(f"**{RULES}/new")
    wait(page, ".rule-row:has-text('not saved')", problems)
    assert page.locator(".rule-row").count() == before + 1
    assert buttons(page) == ["Discard", "Save"]
    page.click(f"{PANE} .toolbar button:has-text('Discard')")
    page.wait_for_url(f"**{RULES}")
    until(page, "!document.querySelector('.rule-row.sel')")
    assert page.locator(".rule-row").count() == before
    page.click("a.btn:has-text('Add rule')")
    wait(page, f"{PANE} #f-payee-contains", problems)
    page.fill(f"{PANE} #f-payee-contains", "browser florist")
    page.select_option(f"{PANE} #f-category", h.cats["Food › Groceries"])
    page.click(f"{PANE} .toolbar button.primary")
    wait(page, ".toast:has-text('Rule added')", problems)
    added = next(x for x in rules(h) if x["payeeMatch"] == "browser florist")
    page.wait_for_url(f"**{RULES}/{added['id']}")
    until(page, "!document.querySelector('.rule-row .pill.new')")
    page.click(f"{PANE} .toolbar button:has-text('Delete')")
    page.click('button:text-is("Yes")')
    page.wait_for_url(f"**{RULES}")
    assert rule(h, added["id"]) is None
    assert problems == []
    page.close()


def test_make_a_rule_opens_new_rule_over_the_transaction(browser, household):
    """S2.7.6, S12.15.7: Make a rule opens New rule over the transaction's dialog, filled from
    it; saved there, the rule is made, and the transaction's dialog is as it was."""
    h = household
    t = made(
        make(
            h.c,
            "Txn",
            accountId=h.checking["id"],
            date=f"{months_back(1)}-17",
            amount="-6.50",
            payee="Browser pretzels",
            categoryId=h.cats["Food › Groceries"],
        )
    )
    path = f"/ui/accounts/{h.checking['id']}/transactions"
    opener = 'tr:has-text("Browser pretzels") .row-tool'
    page, problems = signed_in(browser, h, path, opener)
    page.click(opener)
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.fill(".dialog #f-memo", "kept while the rule is made")
    page.click('.dialog button:has-text("Make a rule")')
    wait(page, f"{TOP} #d1-f-payee-contains", problems)
    assert page.locator(f"{TOP} h2").inner_text() == "New Rule"
    assert page.input_value(f"{TOP} #d1-f-payee-contains") == "Browser pretzels"
    # The categories come as the dialog opens: their list may arrive after the field.
    until(
        page, f"document.querySelector('#d1-f-category')?.value === {h.cats['Food › Groceries']!r}"
    )
    page.click(f"{TOP} footer button.primary")
    until(page, "document.querySelectorAll('.dialog').length === 1")
    assert page.input_value(".dialog #f-memo") == "kept while the rule is made"
    made_rule = next(x for x in rules(h) if x["payeeMatch"] == "Browser pretzels")
    page.click('.dialog footer button:has-text("Cancel")')
    wait(page, "text=Save your changes?", problems)
    page.click('.dialog-ask-buttons button:has-text("Discard")')
    wait(page, ".dialog", problems, state="detached")
    assert (
        h.c.get(f"/ui/api/transactions/{t['id']}").json()["memo"] != "kept while the rule is made"
    )
    drop(h, made_rule["id"])
    assert problems == []
    page.close()
