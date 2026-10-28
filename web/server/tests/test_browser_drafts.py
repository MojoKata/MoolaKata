"""Forms that edit a draft, driven in headless Chromium (requirements S12.15, S17.5.2).

Saved unchanged, every form changes nothing: one table, a row per form. What every draft form
does (the question before discarding, Back, a click outside, typed text, questions, a reload
after a 412) is tested once, on the shared form pieces, through the budget's plan dialog."""

from collections.abc import Callable
from dataclasses import dataclass

import pytest
from browser import Household, made, months_back, signed_in, wait
from test_budgets import save_plan

pytestmark = pytest.mark.browser


def plan_of(h: Household, b: dict) -> list[dict]:
    r = h.c.get(f"/ui/api/budgets/{b['id']}/plan", params={"month": months_back(0)})
    assert r.status_code == 200, r.text
    return sorted(r.json()["lines"], key=lambda x: x["id"])


@dataclass
class Form:
    """A form in the table: where it is, how it opens (a button's text), and what reads its
    records back."""

    name: str
    path: Callable[[Household], str]
    ready: str
    opens: str
    reads: Callable[[Household], object]


def txn_of(h: Household, name: str) -> dict:
    return h.c.get(f"/ui/api/transactions/{h.extra[name]['id']}").json()


def paid_back(h: Household) -> tuple:
    """The bill as read, and what is still awaited of it: nothing, its part paid back."""
    paid = h.c.get(f"/ui/api/budgets/{h.budget['id']}/reimbursements").json()["items"]
    return txn_of(h, "bill"), paid


def holding(h: Household) -> tuple:
    """The shares moved in as read, and the holding they make, basis and all."""
    t = txn_of(h, "moved")
    return t, h.c.get(f"/ui/api/accounts/{t['accountId']}/holdings").json()


FORMS = [
    Form(
        "the plan, tracking with reserves and moves",
        lambda h: f"/ui/budgets/{h.budget['id']}/month",
        'button:has-text("Edit plan")',
        'button:has-text("Edit plan")',
        lambda h: plan_of(h, h.budget),
    ),
    Form(
        "the plan, envelope with a yearly line",
        lambda h: f"/ui/budgets/{h.envelope['id']}/month",
        'button:has-text("Edit plan")',
        'button:has-text("Edit plan")',
        lambda h: plan_of(h, h.envelope),
    ),
    Form(
        "a transaction split, a part paid back (CR3-29)",
        lambda h: f"/ui/accounts/{h.checking['id']}/transactions",
        'button.linklike:has-text("Grand Hotel")',
        'button.linklike:has-text("Grand Hotel")',
        paid_back,
    ),
    Form(
        "shares moved in, with their basis",
        lambda h: f"/ui/accounts/{h.extra['brokerage']['id']}/transactions",
        'button.linklike:has-text("transfer-in VTI")',
        'button.linklike:has-text("transfer-in VTI")',
        holding,
    ),
]


@pytest.mark.parametrize("form", FORMS, ids=[f.name for f in FORMS])
def test_saved_unchanged_a_form_changes_nothing(browser, household, form):
    """CR3-2 and its kind: what a form shows (moves, carried remainders, a reserve's balance, a
    yearly line) never flows back into its records when it is saved untouched."""
    h = household
    before = form.reads(h)
    page, problems = signed_in(browser, h, form.path(h), form.ready)
    page.click(form.opens)
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    assert form.reads(h) == before
    assert problems == []
    page.close()


def test_a_plan_from_history_leaves_the_lines_it_doesnt_propose(browser, household):
    """CR3-2's fourth case: the estimate keeps the reserve it doesn't propose, target and all."""
    h = household
    b = fresh_budget(h, "Estimated")
    before = {x["categoryId"]: x for x in plan_of(h, b)}
    page, problems = signed_in(browser, h, f"/ui/budgets/{b['id']}/month", EDIT)
    page.click('button:has-text("Estimate from history")')
    wait(page, ".dialog table.plan tbody tr", problems)
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    after = {x["categoryId"]: x for x in plan_of(h, b)}
    assert h.cats["Food › Groceries"] in set(after) - set(before), "groceries proposed, planned"
    for cat, line in before.items():
        assert after[cat] == line, "a line not proposed stays exactly as it was"
    assert problems == []
    page.close()


# ---------- what every draft form does, tested once on the shared pieces ----------

EDIT = 'button:has-text("Edit plan")'


def fresh_budget(h: Household, name: str) -> dict:
    """A budget of the test's own, so what it saves touches no other test: a reserve planned
    from two months back (it holds money now), and a line for dining out."""
    b = made(h.c.post("/ui/api/budgets", json={"name": name, "accountIds": [h.checking["id"]]}))
    v = h.c.get(f"/ui/api/budgets/{b['id']}").json()["version"]
    made(
        h.c.patch(
            f"/ui/api/budgets/{b['id']}", json={"reserves": True}, headers={"If-Match": str(v)}
        )
    )
    b = h.c.get(f"/ui/api/budgets/{b['id']}").json()
    repair, dining = h.cats["Transportation › Car maintenance"], h.cats["Food › Dining out"]
    lines = [{"categoryId": repair, "amount": "100.00", "target": "1000.00"},
             {"categoryId": dining, "amount": "300.00"}]  # fmt: skip
    made(save_plan(h.c, b, f"{months_back(2)}-01", lines))
    return b


def opened(browser, h: Household, b: dict):
    page, problems = signed_in(browser, h, f"/ui/budgets/{b['id']}/month", EDIT)
    page.click(EDIT)
    wait(page, ".dialog table.plan tbody tr", problems)
    return page, problems


def besides(problems: list, expected: str) -> list:
    """What the page reported, but for the answer the test brought about."""
    return [p for p in problems if not p.startswith(expected)]


def amount_of(page, n: int = 0):
    return page.locator('.dialog input[aria-label="Amount"]').nth(n)


def test_a_form_holding_changes_asks_before_discarding_them(browser, household):
    """S12.15.6: Escape asks; Keep editing keeps the dialog and what was typed; a click on the
    dimmed content does nothing; ✕ asks too, and Discard closes, saving nothing."""
    h = household
    b = fresh_budget(h, "Discarded")
    before = plan_of(h, b)
    page, problems = opened(browser, h, b)
    amount_of(page).fill("12.")
    page.keyboard.press("Escape")
    wait(page, "text=Discard your changes?", problems)
    page.click('button:has-text("Keep editing")')
    assert page.locator(".dialog-ask").count() == 0
    assert amount_of(page).input_value() == "12.", "what was typed stays as typed"
    page.mouse.click(5, 5)
    assert page.locator(".dialog").count() == 1, "a click outside doesn't close it"
    page.click(".dialog-x")
    page.click('button:has-text("Discard")')
    wait(page, ".dialog", problems, state="detached")
    assert plan_of(h, b) == before
    assert problems == []
    page.close()


def test_a_form_set_back_closes_without_asking(browser, household):
    """S12.15.1: a field set back to the value it had is unchanged, so Escape just closes."""
    h = household
    b = fresh_budget(h, "Set back")
    page, problems = opened(browser, h, b)
    was = amount_of(page).input_value()
    amount_of(page).fill("12.00")
    amount_of(page).fill(was.replace(",", ""))
    page.keyboard.press("Escape")
    wait(page, ".dialog", problems, state="detached")
    assert problems == []
    page.close()


def test_back_asks_and_text_that_doesnt_read_counts_as_a_change(browser, household):
    """S12.15.6, S12.15.2: text typed that doesn't read yet is a change; Back asks before it
    goes, Discard lets it go; and Save sends nothing while it is there."""
    h = household
    b = fresh_budget(h, "Unread")
    before = plan_of(h, b)
    page, problems = opened(browser, h, b)
    amount_of(page).fill("twelve")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog .notice", problems)
    assert "Correct the fields marked first." in page.inner_text(".dialog")
    page.go_back()
    wait(page, "text=Discard your changes?", problems)
    page.click('button:has-text("Discard")')
    wait(page, ".dialog", problems, state="detached")
    assert plan_of(h, b) == before
    assert problems == []
    page.close()


def test_a_question_is_listed_and_save_anyway_confirms_it(browser, household):
    """S12.15.4: a reserve that stops being kept while it holds money asks first; the
    question shows above the buttons, the button becomes Save anyway, and that saves."""
    h = household
    b = fresh_budget(h, "Asked")
    page, problems = opened(browser, h, b)
    row = page.locator(".dialog tr", has_text="Car maintenance")
    target = row.locator('input[aria-label="Target"]')
    target.fill("")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog .notice ol.asks li", problems)
    assert "stops being kept" in page.inner_text(".dialog .notice")
    assert page.inner_text(".dialog footer button.primary") == "Save anyway"
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    repair = h.cats["Transportation › Car maintenance"]
    line = next(x for x in plan_of(h, b) if x["categoryId"] == repair)
    assert line["target"] is None
    assert besides(problems, "409 for") == []
    page.close()


def test_a_record_changed_meanwhile_saves_nothing_and_reloads(browser, household):
    """S12.15.5: a line changed elsewhere after the dialog read it: nothing saved, the dialog
    says so, and Reload opens it again from the records as they stand."""
    h = household
    b = fresh_budget(h, "Stale")
    page, problems = opened(browser, h, b)
    repair, dining = h.cats["Transportation › Car maintenance"], h.cats["Food › Dining out"]
    lines = [{"categoryId": repair, "amount": "100.00", "target": "1000.00"},
             {"categoryId": dining, "amount": "333.00"}]  # fmt: skip
    made(save_plan(h.c, b, f"{months_back(0)}-01", lines))
    amount_of(page, 0).fill("150.00")
    page.click(".dialog footer button.primary")
    wait(page, "text=changed since you opened it", problems)
    after = {x["categoryId"]: x["amount"] for x in plan_of(h, b)}
    assert float(after[dining]) == 333, "nothing saved"
    page.click('.dialog footer button:has-text("Reload")')
    from playwright.sync_api import expect

    expect(amount_of(page, 0)).to_have_value("333.00")
    assert besides(problems, "412 for") == []
    page.close()


# ---------- what the transaction dialog alone does ----------


def test_an_edited_split_transaction_keeps_its_parts_and_their_payback(browser, household):
    """CR3-29: a memo added in the dialog leaves the parts as they were, ids and all, so the
    part paid back stays paid back."""
    h = household
    before, _ = paid_back(h)
    path = f"/ui/accounts/{h.checking['id']}/transactions"
    page, problems = signed_in(browser, h, path, 'button.linklike:has-text("Grand Hotel")')
    page.click('button.linklike:has-text("Grand Hotel")')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.fill("#f-memo", "two nights")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    after, awaited = paid_back(h)
    assert after["memo"] == "two nights"
    assert [x["id"] for x in after["splits"]] == [x["id"] for x in before["splits"]]
    assert awaited == []
    assert problems == []
    page.close()


def test_an_add_dialog_left_untouched_closes_without_asking(browser, household):
    """S12.15.6: a new transaction's starting values are no change of the person's."""
    h = household
    path = f"/ui/accounts/{h.checking['id']}/transactions"
    page, problems = signed_in(browser, h, path, 'button:has-text("Add")')
    page.click('main button:has-text("Add")')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.keyboard.press("Escape")
    wait(page, ".dialog", problems, state="detached")
    assert problems == []
    page.close()
