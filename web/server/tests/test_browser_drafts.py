"""Forms that edit a draft, driven in headless Chromium (requirements S12.15, S17.5.2).

Saved unchanged, every form changes nothing: one table, a row per form. What every draft form
does (the question before discarding, Back, a click outside, typed text, questions, a reload
after a 412) is tested once, on the shared form pieces, through the budget's plan dialog."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import pytest
from browser import Household, made, months_back, signed_in, wait
from edits import (
    change,
    create,
    edit,
    make,
    option_trade,
    remove,
    save_settings,
    saved,
    terms,
)
from test_budgets import save_plan

pytestmark = pytest.mark.browser


def plan_of(h: Household, b: dict) -> list[dict]:
    r = h.c.get(f"/ui/api/budgets/{b['id']}/plan", params={"month": months_back(0)})
    assert r.status_code == 200, r.text
    return sorted(r.json()["lines"], key=lambda x: x["id"])


@dataclass
class Form:
    """A form in the table: where it is, how it opens (a button's text), and what reads its
    records back. A screen's form (`opens` empty) is the one `ready` names, with its own Save."""

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


def gift_plan(h: Household) -> tuple:
    """Emma's plan as read, and the gifts with their occasions (CR3-43)."""
    plan = h.c.get(f"/ui/api/gift-plans/{h.extra['emma']['id']}").json()
    gifts = h.c.get("/ui/api/gifts").json()["items"]
    return plan, [(g["description"], g["occasion"], g["occasionLabel"]) for g in gifts]


def filings(h: Household) -> list:
    """The book's filings as read, payments and carried figures with them (CR3-35)."""
    return h.c.get(f"/ui/api/tax-books/{h.extra['book']['id']}").json()["filings"]


def giving_of(h: Household) -> tuple:
    """The year's giving as read: the plan, the organisations, the donations."""
    c = h.c
    return (c.get("/ui/api/giving").json()["plan"],
            c.get("/ui/api/giving/organisations").json()["items"],
            c.get("/ui/api/giving/donations").json()["items"],
            c.get("/ui/api/gifts").json()["items"])  # fmt: skip


def users_of(h: Household) -> tuple:
    """The users and groups as an admin reads them; the admin's own row moves with each
    sign-in, so it is left out."""
    users = [u for u in h.c.get("/ui/api/users").json()["items"] if u["username"] != "admin"]
    return users, h.c.get("/ui/api/groups").json()["items"]


def book_of(h: Household) -> dict:
    """The tax book as read: its dependents and documents with it."""
    return h.c.get(f"/ui/api/tax-books/{h.extra['book']['id']}").json()


def account(h: Household, name: str) -> tuple:
    """An account as read, and a loan's terms with it."""
    a = h.c.get(f"/ui/api/accounts/{h.extra[name]['id']}").json()
    loan = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json() if a["type"] == "mortgage" else None
    return a, loan and loan["terms"]


def home(h: Household) -> dict:
    """The home as read, with its valuation, improvement, sale and documents."""
    return h.c.get(f"/ui/api/items/{h.extra['home']['id']}").json()


def budget_of(h: Household) -> dict:
    """The budget as read: its accounts, options and roles."""
    return h.c.get(f"/ui/api/budgets/{h.budget['id']}").json()


def receipt_of(h: Household) -> dict:
    """The receipt's fields as read; what reading it adds is the server's, not the form's."""
    r = h.c.get(f"/ui/api/receipts/{h.extra['receipt']['id']}").json()
    return {k: r[k] for k in ("date", "amount", "payee", "notes", "tags", "keep", "links")}


def profile_of(h: Household) -> dict:
    """The profile as read, but its version, which each sign-in moves."""
    return {k: v for k, v in h.c.get("/ui/api/profile").json().items() if k != "version"}


def settings_of(h: Household) -> dict:
    """The settings as read: every key, at the version they share."""
    return h.c.get("/ui/api/settings").json()


# What a section's background task records of its own runs (the mail queue, the wallets'
# sync): it moves whenever the task runs, as the server's first run can during a test, and a
# save neither reads nor writes it.
RUNS = ("waiting", "setAside", "lastRun", "lastError")


def settings_form(name: str, section: str, ready: str, also: str | None = None) -> Form:
    """A Settings section's form, saved untouched: its keys, and what its route reads but for
    its task's runs."""

    def reads(h):
        answer = also and h.c.get(f"/ui/api{also}").json()
        return settings_of(h), answer and {k: v for k, v in answer.items() if k not in RUNS}

    return Form(name, lambda h: f"/ui/settings/{section}", ready, "", reads)


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
        "a budget's settings, with its accounts and their roles",
        lambda h: f"/ui/budgets/{h.budget['id']}/month",
        'button:has-text("Settings")',
        'button:has-text("Settings")',
        budget_of,
    ),
    Form(
        "a transaction split, a part paid back (CR3-29)",
        lambda h: f"/ui/accounts/{h.checking['id']}/transactions",
        'tr:has-text("Grand Hotel") .row-tool',
        'tr:has-text("Grand Hotel") .row-tool',
        paid_back,
    ),
    Form(
        "shares moved in, with their basis",
        lambda h: f"/ui/accounts/{h.extra['brokerage']['id']}/transactions",
        'tr:has-text("transfer-in VTI") .row-tool',
        'tr:has-text("transfer-in VTI") .row-tool',
        holding,
    ),
    Form(
        "a portfolio of a brokerage account on a 60/40 benchmark",
        lambda h: f"/ui/portfolios/{h.extra['portfolio']['id']}/holdings",
        'button:has-text("Edit")',
        'button:has-text("Edit")',
        lambda h: h.c.get(f"/ui/api/portfolios/{h.extra['portfolio']['id']}").json(),
    ),
    Form(
        "a receipt kept for ever, with its notes and tags",
        lambda h: "/ui/receipts",
        'button[aria-label="Receipt Blue Bottle"]',
        'button[aria-label="Receipt Blue Bottle"]',
        receipt_of,
    ),
    Form(
        "an active retirement projection's inputs, a fixed withdrawal among them",
        lambda h: f"/ui/projections/{h.extra['retire']['id']}",
        'form.card:has-text("Inputs")',
        "",
        lambda h: {
            k: v
            for k, v in h.c.get(f"/ui/api/projections/{h.extra['retire']['id']}").json().items()
            if k in ("name", "inputs", "builtOn", "baselineAt", "version")
        },
    ),
    Form(
        "a portfolio's shares, Bob at Read",
        lambda h: f"/ui/portfolios/{h.extra['portfolio']['id']}/holdings",
        'button:has-text("Share")',
        'button:has-text("Share")',
        lambda h: h.c.get(f"/ui/api/shares/portfolio/{h.extra['portfolio']['id']}").json(),
    ),
    Form(
        "a gift plan with a graduation and a gift for it (CR3-43)",
        lambda h: "/ui/gifts/people",
        'tr:has-text("Emma Griffin") .row-tool',
        'tr:has-text("Emma Griffin") .row-tool',
        gift_plan,
    ),
    Form(
        "a filed return with a matched payment and carried figures",
        lambda h: "/ui/taxes/filings",
        'h3:has-text("Form 1040") .row-tool',
        'h3:has-text("Form 1040") .row-tool',
        filings,
    ),
    Form(
        "a user invited into a group",
        lambda h: "/ui/users",
        'tr:has-text("Bob Griffin") .row-tool',
        'tr:has-text("Bob Griffin") .row-tool',
        users_of,
    ),
    Form(
        "a group with a member",
        lambda h: "/ui/users",
        'tr:has-text("Household") .row-tool',
        'tr:has-text("Household") .row-tool',
        users_of,
    ),
    Form(
        "a gift planned for an occasion, with its cost",
        lambda h: "/ui/gifts/gifts",
        'tr:has-text("Watch") .row-tool',
        'tr:has-text("Watch") .row-tool',
        giving_of,
    ),
    Form(
        "an organisation with causes and a monthly pledge",
        lambda h: "/ui/giving/organisations",
        'tr:has-text("St. Mark") .row-tool',
        'tr:has-text("St. Mark") .row-tool',
        giving_of,
    ),
    Form(
        "a donation recorded, with its notes",
        lambda h: "/ui/giving/donations",
        'tr:has-text("St. Mark") .row-tool',
        'tr:has-text("St. Mark") .row-tool',
        giving_of,
    ),
    Form(
        "the year's giving plan on gross income",
        lambda h: "/ui/giving",
        '.card button:has-text("Edit")',
        '.card button:has-text("Edit")',
        giving_of,
    ),
    Form(
        "a dependent with the months they lived with the filers",
        lambda h: "/ui/taxes/summary",
        '.list-item:has-text("Emma Griffin") .row-tool',
        '.list-item:has-text("Emma Griffin") .row-tool',
        book_of,
    ),
    Form(
        "a W-2 kept with its file and notes (CR3-36)",
        lambda h: "/ui/taxes/documents",
        'tr:has-text("Acme Corp") .row-tool',
        'tr:has-text("Acme Corp") .row-tool',
        book_of,
    ),
    Form(
        "a savings account's settings, with a withdrawals limit",
        lambda h: f"/ui/accounts/{h.extra['savings']['id']}/settings",
        "form.draft-form",
        "",
        lambda h: account(h, "savings"),
    ),
    Form(
        "a mortgage's settings and terms, a reset among them",
        lambda h: f"/ui/accounts/{h.extra['mortgage']['id']}/settings",
        'form.draft-form:has-text("Loan terms")',
        "",
        lambda h: account(h, "mortgage"),
    ),
    Form(
        "a wallet's settings, its key watched past a gap of 25",
        lambda h: f"/ui/accounts/{h.extra['cold']['id']}/settings",
        'form.draft-form:has-text("Keys and addresses")',
        "",
        lambda h: (
            account(h, "cold"),
            h.c.get(f"/ui/api/accounts/{h.extra['cold']['id']}/wallet").json(),
        ),
    ),
    Form(
        "a home with its valuation and improvement",
        lambda h: f"/ui/accounts/{h.extra['homes']['id']}/items",
        'tr:has-text("1428 Elm St") .row-tool',
        'tr:has-text("1428 Elm St") .row-tool',
        home,
    ),
    Form(
        "the profile, a birthday and a time zone among it",
        lambda h: "/ui/profile",
        'form.card:has-text("Display name")',
        "",
        profile_of,
    ),
    Form(
        "the assumptions, the shipped figures still",
        lambda h: "/ui/profile",
        'form.card:has-text("Expected return")',
        "",
        lambda h: h.c.get("/ui/api/assumptions").json(),
    ),
    settings_form("Settings › General", "general", 'form.card:has-text("Household name")'),
    settings_form("Settings › Sign-up", "signup", 'form.card:has-text("Allowed email domains")'),
    settings_form(
        "Settings › Email, its password kept",
        "email",
        'form.card:has-text("From address")',
        "/settings/email",
    ),
    # Settings › Bitcoin's untouched save writes its source the first time (CR3-62): its own
    # test below, on a server of its own, so no wallet of the household is ever read.
    settings_form("Settings › Prices' refresh time", "prices", 'form:has-text("Daily refresh")'),
    settings_form(
        "Settings › Tax tables",
        "tax-tables",
        'form.card:has-text("Tax tables")',
        "/settings/tax-tables",
    ),
    settings_form("Settings › Backups", "backups", 'form.card:has-text("Copies kept")'),
    settings_form(
        "Settings › Key storage's reminder", "keys", 'form.card:has-text("Remind admins")'
    ),
    settings_form("Settings › Storage", "storage", 'form.card:has-text("Keep statements for")'),
    settings_form("Settings › Linked servers' address", "links", 'form:has-text("link address")'),
]


@pytest.mark.parametrize("form", FORMS, ids=[f.name for f in FORMS])
def test_saved_unchanged_a_form_changes_nothing(browser, household, form):
    """CR3-2 and its kind: what a form shows (moves, carried remainders, a reserve's balance, a
    yearly line) never flows back into its records when it is saved untouched."""
    h = household
    before = form.reads(h)
    page, problems = signed_in(browser, h, form.path(h), form.ready)
    if form.opens:
        page.click(form.opens)
        wait(page, ".dialog footer button.primary:enabled", problems)
        page.click(".dialog footer button.primary")
        wait(page, ".dialog", problems, state="detached")
    else:
        page.click(f"{form.ready} button.primary:enabled")
        wait(page, ".toast", problems)
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
    b = made(make(h.c, "Bdgt", name=name, accountIds=[h.checking["id"]]))
    made(edit(h.c, "Bdgt", f"/ui/api/budgets/{b['id']}", reserves=True))
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
    wait(page, "text=Save your changes?", problems)
    # Keep editing, focused and what Escape answers; Discard, in red; and Save.
    buttons = page.locator(".dialog-ask-buttons button")
    assert buttons.all_inner_texts() == ["Keep editing", "Discard", "Save"]
    assert "danger" in (buttons.nth(1).get_attribute("class") or "")
    assert page.evaluate("document.activeElement.textContent.trim()") == "Keep editing"
    page.keyboard.press("Escape")
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


def test_save_in_the_question_saves_and_closes(browser, household):
    """S12.15.6: Save in the question saves the draft, and the dialog goes as its own Save
    would take it; one refused stays, showing why."""
    h = household
    b = fresh_budget(h, "Saved from the question")
    page, problems = opened(browser, h, b)
    amount_of(page).fill("1.2.3")
    page.keyboard.press("Escape")
    wait(page, "text=Save your changes?", problems)
    page.click('.dialog-ask-buttons button:has-text("Save")')
    wait(page, ".dialog .notice", problems)
    assert page.locator(".dialog-ask").count() == 0, "a refusal shows in the dialog"
    assert "Correct the fields marked first." in page.inner_text(".dialog")
    amount_of(page).fill("12.00")
    page.keyboard.press("Escape")
    wait(page, "text=Save your changes?", problems)
    page.click('.dialog-ask-buttons button:has-text("Save")')
    wait(page, ".dialog", problems, state="detached")
    assert 12 in [float(x["amount"]) for x in plan_of(h, b)]
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
    amount_of(page).fill("1.2.3")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog .notice", problems)
    assert "Correct the fields marked first." in page.inner_text(".dialog")
    page.go_back()
    wait(page, "text=Save your changes?", problems)
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
    page, problems = signed_in(browser, h, path, 'tr:has-text("Grand Hotel") .row-tool')
    page.click('tr:has-text("Grand Hotel") .row-tool')
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


def test_an_ira_contribution_is_marked_deductible_or_not_whole_or_part_by_part(browser, household):
    """S8.6: a traditional IRA contribution is Not decided until marked; split, each part is
    marked instead (a contribution deducted in part)."""
    from test_accounts import add, new_account

    h = household
    ira = new_account(h.c, name="Drafts IRA", type="ira")["id"]
    t = add(h.c, ira, "7000.00", months_back(1) + "-10", kind="deposit", payee="Backdoor")
    path = f"/ui/accounts/{ira}/transactions"
    page, problems = signed_in(browser, h, path, 'tr:has-text("Backdoor") .row-tool')
    page.click('tr:has-text("Backdoor") .row-tool')
    wait(page, ".dialog footer button.primary:enabled", problems)
    seg = '.dialog [role=radiogroup][aria-label="Deductible"]'
    assert page.get_attribute(f'{seg} button:has-text("Not decided")', "aria-checked") == "true"
    page.click(f'{seg} button:has-text("Not deductible")')
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    assert h.c.get(f"/ui/api/transactions/{t['id']}").json()["deductible"] is False
    page.click('tr:has-text("Backdoor") .row-tool')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.click('.dialog button:has-text("Split…")')
    page.fill("#x-split-0-amount", "3000.00")
    page.click('.dialog button:has-text("Add a part")')
    page.fill("#x-split-1-amount", "4000.00")
    assert page.locator(seg).count() == 0
    page.click('.dialog [aria-label="Part 1 deductible"] button:has-text("Deductible")')
    page.click('.dialog [aria-label="Part 2 deductible"] button:has-text("Not deductible")')
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    got = h.c.get(f"/ui/api/transactions/{t['id']}").json()
    assert got["deductible"] is None
    assert sorted((Decimal(str(x["amount"])), x["deductible"]) for x in got["splits"]) == [
        (Decimal(3000), True), (Decimal(4000), False)]  # fmt: skip
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


# ---------- what the gift plan's dialog alone does ----------


def test_a_gift_plan_changed_keeps_its_gifts_occasions(browser, household):
    """CR3-43: a holiday added and the notes changed; the graduation keeps its id, and the
    watch planned for it keeps the graduation."""
    h = household
    before, gifts = gift_plan(h)
    page, problems = signed_in(browser, h, "/ui/gifts/people", 'tr:has-text("Emma Griffin")')
    page.click('tr:has-text("Emma Griffin")')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.click('.dialog button.chip:has-text("Thanksgiving")')
    page.fill("#f-notes", "likes paints and puzzles")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    after, gifts_after = gift_plan(h)
    assert after["notes"] == "likes paints and puzzles"
    kept = {o["id"] for o in before["occasions"]}
    assert kept < {o["id"] for o in after["occasions"]}
    assert "thanksgiving" in {o["holiday"] for o in after["occasions"]}
    assert gifts_after == gifts
    assert problems == []
    page.close()


def test_a_new_gift_plan_for_a_new_person(browser, household):
    h = household
    page, problems = signed_in(browser, h, "/ui/gifts/people", 'button:has-text("Add a gift plan")')
    page.click('button:has-text("Add a gift plan")')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.fill("#f-name", "Leo Griffin")
    page.select_option("#f-sex", "male")
    page.fill("#f-birthday", "2021-03-04")
    page.click('.dialog button.chip:has-text("Christmas")')
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    leo = next(p for p in h.c.get("/ui/api/persons").json()["items"] if p["name"] == "Leo Griffin")
    assert (leo["birthYear"], leo["birthMonth"], leo["birthDay"]) == (2021, 3, 4)
    plans = h.c.get("/ui/api/gift-plans").json()["items"]
    plan = next(p for p in plans if p["personId"] == leo["id"])
    assert [o["holiday"] for o in plan["occasions"]] == ["christmas"]
    assert problems == []
    page.close()


def test_a_filing_changed_keeps_its_payments_match(browser, household):
    """A confirmation and a carried figure changed: the estimated payment keeps its id and the
    transaction it was matched to, which the dialog once dropped on every save."""
    h = household
    (before,) = filings(h)
    page, problems = signed_in(browser, h, "/ui/taxes/filings", 'h3:has-text("Form 1040")')
    page.click('h3:has-text("Form 1040") .row-tool')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.fill("#f-confirmation", "IRS-456")
    page.fill("#x-carried-agi", "98,100")
    # Form 8606 is the filer's own: their basis is typed in a field of theirs (S8.17).
    me = h.c.get("/ui/api/session").json()["user"]["id"]
    page.fill(f"#x-carried-basis8606-{me}", "6,500")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    (after,) = filings(h)
    assert after["confirmation"] == "IRS-456"
    assert float(after["carried"]["agi"]) == 98100
    assert {u: float(v) for u, v in after["carried"]["basis8606"].items()} == {me: 6500}
    assert after["payments"] == before["payments"]
    assert problems == []
    page.close()


def test_a_screens_form_holding_changes_asks_before_moving_elsewhere(browser, household):
    """S12.15.6: a link in the app, or Back, asks before a screen's form loses its changes;
    Keep editing stays, Discard goes."""
    h = household
    at = f"/ui/accounts/{h.extra['savings']['id']}"
    page, problems = signed_in(browser, h, at, 'a.tab:has-text("Settings")')
    page.click('a.tab:has-text("Settings")')
    path = at + "/settings"
    wait(page, "form.draft-form", problems)
    page.fill("#f-name", "Rainy day")
    page.click('a.nav-item:has-text("Budgets")')
    wait(page, "text=Save your changes?", problems)
    page.click('button:has-text("Keep editing")')
    assert page.url.endswith(path) and page.input_value("#f-name") == "Rainy day"
    page.go_back()
    wait(page, "text=Save your changes?", problems)
    page.click('button:has-text("Discard")')
    page.wait_for_url(f"**{at}")
    assert account(h, "savings")[0]["name"] == "Savings"
    assert problems == []
    page.close()


def test_save_in_a_screens_question_saves_and_moves_on(browser, household):
    """S12.15.6: on a screen's form, Save in the question saves, then goes where the link
    led."""
    h = household
    at = f"/ui/accounts/{h.extra['savings']['id']}"
    page, problems = signed_in(browser, h, at + "/settings", "form.draft-form #f-name")
    page.fill("#f-name", "Rainy day fund")
    page.click('a.nav-item:has-text("Budgets")')
    wait(page, "text=Save your changes?", problems)
    page.click('.dialog footer button:has-text("Save")')
    page.wait_for_url("**/ui/budgets**")
    assert account(h, "savings")[0]["name"] == "Rainy day fund"
    assert problems == []
    page.close()


# ---------- what the accounts' forms alone do ----------


def test_a_new_mortgage_is_made_with_its_terms_in_one_save(browser, household):
    h = household
    page, problems = signed_in(browser, h, "/ui/accounts", 'button:has-text("New account")')
    page.click('button:has-text("New account")')
    page.click('button.type-card:has-text("Mortgage")')
    page.fill("#f-name", "Cabin mortgage")
    page.fill("#f-original-principal", "200000")
    page.fill("#f-start-date", "2024-06-01")
    page.fill("#f-interest-rate", "6.5")
    page.click(".dialog footer button.primary")
    page.wait_for_url("**/ui/accounts/Acct_*")
    a = next(
        x for x in h.c.get("/ui/api/accounts").json()["items"] if x["name"] == "Cabin mortgage"
    )
    t = h.c.get(f"/ui/api/accounts/{a['id']}/loan").json()["terms"]
    assert (t["principal"], t["termMonths"], t["rate"]) == (200000, 360, 6.5)
    assert problems == []
    page.close()


def test_a_new_wallet_is_made_with_its_keys_in_one_save(browser, household):
    from test_wallets import ZPUB

    h = household
    page, problems = signed_in(browser, h, "/ui/accounts", 'button:has-text("New account")')
    page.click('button:has-text("New account")')
    page.click('button.type-card:has-text("Self-custody")')
    page.fill("#f-name", "Hardware wallet")
    page.fill("#f-wallet-keys", ZPUB)
    page.click(".dialog footer button.primary")
    page.wait_for_url("**/ui/accounts/Acct_*")
    a = next(
        x for x in h.c.get("/ui/api/accounts").json()["items"] if x["name"] == "Hardware wallet"
    )
    assert h.c.get(f"/ui/api/accounts/{a['id']}/wallet").json()["watched"] == 40
    assert problems == []
    page.close()


def test_an_items_valuation_and_sale_are_saved_with_it(browser, household):
    h = household
    coll = make(h.c, "Acct", name="Watches", type="collectables").json()
    watch = make(
        h.c,
        "Item",
        accountId=coll["id"],
        name="Speedmaster",
        acquiredOn="2020-01-10",
        costBasis="5000",
    ).json()
    path = f"/ui/accounts/{coll['id']}/items"
    page, problems = signed_in(browser, h, path, 'tr:has-text("Speedmaster") .row-tool')
    page.click('tr:has-text("Speedmaster") .row-tool')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.fill("#x-valuation-value", "6200")
    page.click('.dialog button:has-text("Add")')
    page.click('.dialog button:has-text("Record the sale…")')
    page.fill("#x-proceeds", "6100")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    it = h.c.get(f"/ui/api/items/{watch['id']}").json()
    assert [float(v["value"]) for v in it["valuations"]] == [6200]
    assert float(it["sale"]["proceeds"]) == 6100
    assert problems == []
    page.close()


# ---------- what the receipts' dialog alone does ----------


def test_a_receipt_is_attached_and_detached_with_save(browser, household):
    """Attach and Detach change its draft; the link is made, or taken away, on Save."""
    h = household
    r = h.extra["receipt"]
    t = made(make(h.c, "Txn", accountId=h.checking["id"], date=r["date"], amount="-6.40",
                  payee="Blue Bottle Coffee"))  # fmt: skip
    links = lambda: h.c.get(f"/ui/api/receipts/{r['id']}").json()["links"]  # noqa: E731
    card = 'button[aria-label="Receipt Blue Bottle"]'
    page, problems = signed_in(browser, h, "/ui/receipts", card)
    page.click(card)
    wait(page, '.dialog button:has-text("Attach")', problems)
    page.click('.dialog button:has-text("Attach")')
    wait(page, "text=attached when you save", problems)
    assert links() == [], "nothing is sent before Save"
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    assert [x["itemId"] for x in links()] == [t["id"]]
    page.click(card)
    wait(page, '.dialog button:has-text("Detach")', problems)
    page.click('.dialog button:has-text("Detach")')
    wait(page, "text=Nothing yet: it waits in the inbox.", problems)
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    assert links() == []
    assert problems == []
    page.close()


def test_a_receipt_added_to_a_transaction_is_attached_on_save(browser, household):
    """Uploaded at once, into the inbox; attached by the transaction's draft on Save."""
    h = household
    t = made(make(h.c, "Txn", accountId=h.checking["id"], date=f"{months_back(1)}-03",
                  amount="-18.00", payee="Corner Bakery"))  # fmt: skip
    path = f"/ui/accounts/{h.checking['id']}/transactions"
    page, problems = signed_in(browser, h, path, 'tr:has-text("Corner Bakery") .row-tool')
    page.click('tr:has-text("Corner Bakery") .row-tool')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.set_input_files("#f-add-receipt", files=[
        {"name": "bakery.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 bakery"}
    ])  # fmt: skip
    wait(page, '.dialog .pill:has-text("bakery.pdf")', problems)
    receipts = lambda: h.c.get(f"/ui/api/transactions/{t['id']}/receipts").json()["items"]  # noqa: E731
    assert receipts() == [], "uploaded, not yet attached"
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    assert [x["fileName"] for x in receipts()] == ["bakery.pdf"]
    assert problems == []
    page.close()


# ---------- what is saved at once, a record's field changed ----------


def test_a_rule_moved_and_a_budget_made_active_are_saved_at_once(browser, household):
    """↑ moves a rule to its new position, and Make active sets the budget followed, each a
    change of a record through the save."""
    h = household
    first = made(make(h.c, "Rule", payeeMatch="bakery", categoryId=h.cats["Food › Groceries"]))
    second = made(make(h.c, "Rule", payeeMatch="bagel", categoryId=h.cats["Food › Groceries"]))
    order = lambda: [x["id"] for x in h.c.get("/ui/api/rules").json()["items"]]  # noqa: E731
    up = f'button[aria-label="Move rule {order().index(second["id"]) + 1} up"]'
    page, problems = signed_in(browser, h, "/ui/transactions/rules", up)
    page.click(up)
    wait(page, f"{up}:enabled", problems)
    assert order().index(second["id"]) < order().index(first["id"])
    for gone in (first["id"], second["id"]):  # each read anew: a delete renumbers the rest
        r = next(x for x in h.c.get("/ui/api/rules").json()["items"] if x["id"] == gone)
        saved(remove(h.c, "Rule", r))
    page.goto(f"{h.base}/ui/budgets/{h.budget['id']}/list")
    item = '.list-item:has-text("Envelopes")'
    wait(page, f'{item} button:has-text("Make active")', problems)
    page.click(f'{item} button:has-text("Make active")')
    page.click('.dialog footer button:has-text("Make active")')
    wait(page, ".dialog", problems, state="detached")
    assert h.c.get("/ui/api/profile").json()["activeBudgetId"] == h.envelope["id"]
    saved(change(h.c, "User", h.c.get("/ui/api/profile").json(), activeBudgetId=h.budget["id"]))
    assert problems == []
    page.close()


def test_not_a_transfer_undoes_the_match_through_the_save(browser, household):
    """The match undone is a change of the transaction's draft: both halves let go."""
    h = household
    savings = made(make(h.c, "Acct", name="Rainy day", type="savings"))
    day = f"{months_back(1)}-20"
    out = made(make(h.c, "Txn", accountId=h.checking["id"], date=day, amount="-250.00",
                    payee="To Rainy day"))  # fmt: skip
    into = made(make(h.c, "Txn", accountId=savings["id"], date=day, amount="250.00",
                     payee="From checking", kind="deposit"))  # fmt: skip
    pair = lambda: h.c.get(f"/ui/api/transactions/{into['id']}").json()["transferId"]  # noqa: E731
    assert pair() == out["id"], "matched when it was added"
    path = f"/ui/accounts/{savings['id']}/transactions"
    page, problems = signed_in(browser, h, path, 'tr:has-text("From checking") .row-tool')
    page.click('tr:has-text("From checking") .row-tool')
    wait(page, '.dialog button:has-text("Not a transfer"):enabled', problems)
    page.click('.dialog button:has-text("Not a transfer")')
    wait(page, ".dialog", problems, state="detached")
    assert pair() is None
    assert h.c.get(f"/ui/api/transactions/{out['id']}").json()["transferId"] is None
    assert problems == []
    page.close()


def test_a_delete_asks_first_and_no_leaves_everything_as_it_was(browser, household):
    """S12.16: No is focused, so Enter and Escape answer it, and the dialog stays open; Yes
    deletes through the save."""
    h = household
    day = f"{months_back(1)}-21"
    t = made(make(h.c, "Txn", accountId=h.checking["id"], date=day, amount="-12.34",
                  payee="Corner bakery"))  # fmt: skip
    path = f"/ui/accounts/{h.checking['id']}/transactions"
    page, problems = signed_in(browser, h, path, 'tr:has-text("Corner bakery") .row-tool')
    page.click('tr:has-text("Corner bakery") .row-tool')
    wait(page, '.dialog button:has-text("Delete"):enabled', problems)
    for key in ("Enter", "Escape"):
        page.click('.dialog button:has-text("Delete")')
        wait(page, '[role=alertdialog]:has-text("Delete this transaction?")', problems)
        wait(page, '[role=alertdialog] button:focus:has-text("No")', problems)
        page.keyboard.press(key)
        wait(page, "[role=alertdialog]", problems, state="detached")
        assert page.is_visible(".dialog"), f"{key} answers No and leaves the dialog open"
    assert h.c.get(f"/ui/api/transactions/{t['id']}").status_code == 200
    page.click('.dialog button:has-text("Delete")')
    page.click('[role=alertdialog] button:has-text("Yes, delete")')
    wait(page, ".dialog", problems, state="detached")
    assert h.c.get(f"/ui/api/transactions/{t['id']}").status_code == 404
    assert problems == []
    page.close()


# ---------- what the taxes' dialogs alone do ----------


def test_a_kept_document_opens_to_change_it_and_to_remove_it(browser, household):
    """CR3-36: a document kept is changed, then removed, from its row."""
    h = household
    b = h.extra["book"]["id"]
    make(h.c, "TxDoc", bookId=b, form="1098", issuer="Rocket")
    page, problems = signed_in(browser, h, "/ui/taxes/documents", 'tr:has-text("Rocket") .row-tool')
    page.click('tr:has-text("Rocket") .row-tool')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.fill("#f-notes", "for the home in Utah")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    got = next(x for x in book_of(h)["received"] if x["issuer"] == "Rocket")
    assert got["notes"] == "for the home in Utah"
    page.click('tr:has-text("Rocket") .row-tool')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.click('.dialog footer button:has-text("Remove")')
    page.click('[role=alertdialog] button:has-text("Yes, remove")')
    wait(page, ".dialog", problems, state="detached")
    assert "Rocket" not in {x["issuer"] for x in book_of(h)["received"]}
    assert problems == []
    page.close()


# ---------- what the gifts' and giving's dialogs alone do ----------


def test_a_donations_acknowledgement_is_kept_with_save(browser, household):
    """Its file uploaded, the acknowledgement counts as received once the dialog saves."""
    h = household
    opener = 'tr:has-text("St. Mark") .row-tool'
    page, problems = signed_in(browser, h, "/ui/giving/donations", opener)
    page.click(opener)
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.set_input_files("#f-ack-files", files=[
        {"name": "ack.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 thank you"}
    ])  # fmt: skip
    wait(page, "text=1 acknowledgement to keep on Save", problems)
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    (d,) = giving_of(h)[2]
    assert d["acknowledged"]
    assert problems == []
    page.close()


def test_cancel_asks_before_discarding_too(browser, household):
    """S12.15.6: a dialog's Cancel asks as Escape does."""
    h = household
    path = f"/ui/accounts/{h.checking['id']}/transactions"
    page, problems = signed_in(browser, h, path, 'tr:has-text("Grand Hotel") .row-tool')
    page.click('tr:has-text("Grand Hotel") .row-tool')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.fill("#f-memo", "not kept")
    page.click('.dialog footer button:has-text("Cancel")')
    wait(page, "text=Save your changes?", problems)
    page.click('button:has-text("Discard")')
    wait(page, ".dialog", problems, state="detached")
    assert txn_of(h, "bill")["memo"] != "not kept"
    assert problems == []
    page.close()


def test_a_new_access_token_shows_its_secret_once(browser, household):
    h = household
    page, problems = signed_in(browser, h, "/ui/profile", 'button:has-text("New token")')
    page.click('button:has-text("New token")')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.fill("#f-token-name", "Reports")
    page.click(".dialog footer button.primary")
    wait(page, "text=Your new access token", problems)
    assert page.locator(".dialog code.mono").inner_text().startswith("mkt_")
    names = [t["name"] for t in h.c.get("/ui/api/profile/tokens").json()["items"]]
    assert "Reports" in names
    assert problems == []
    page.close()


def test_a_529s_contribution_and_expense_recorded_and_tagged(browser, household):
    h = household
    a = made(make(h.c, "Acct", name="Emma's 529", type="529"))
    path = f"/ui/accounts/{a['id']}/contributions"
    page, problems = signed_in(browser, h, path, 'form:has-text("Record a contribution")')
    page.fill("#f-amount", "2500")
    page.click('form:has-text("Record a contribution") button.primary')
    wait(page, '.toast:has-text("Contribution recorded")', problems)
    url = f"/ui/api/accounts/{a['id']}/contributions"
    (row,) = h.c.get(url).json()["rows"]
    assert (row["amount"], row["contributor"]) == (2500, "owner")
    wait(page, 'select[aria-label^="Who the"]', problems)
    page.select_option('select[aria-label^="Who the"]', label="Emma Griffin")
    wait(page, '.toast:has-text("Saved")', problems)
    assert h.c.get(url).json()["rows"][0]["name"] == "Emma Griffin"
    page.goto(page.url.replace("/contributions", "/withdrawals"))
    wait(page, 'form:has-text("Add a qualified expense")', problems)
    page.fill("#f-amount", "800")
    page.fill("#f-description", "Books")
    page.click('form:has-text("Add a qualified expense") button.primary')
    wait(page, '.toast:has-text("Expense added")', problems)
    (e,) = h.c.get(f"/ui/api/accounts/{a['id']}/withdrawals").json()["expenses"]
    assert (e["amount"], e["description"], e["kind"]) == (800, "Books", "tuition")
    assert problems == []
    page.close()


def test_an_active_projections_new_inputs_ask_about_its_baseline(browser, household):
    h = household
    p = h.extra["retire"]
    was = h.c.get(f"/ui/api/projections/{p['id']}").json()
    page, problems = signed_in(browser, h, f"/ui/projections/{p['id']}", "#f-fees")
    page.fill("#f-fees", "0.3")
    page.click('form.card:has-text("Inputs") button.primary')
    wait(page, '.dialog:has-text("Re-baseline?")', problems)
    page.click('.dialog button:has-text("Keep the baseline")')
    wait(page, '.toast:has-text("Recomputed")', problems)
    now = h.c.get(f"/ui/api/projections/{p['id']}").json()
    assert now["inputs"]["fees"] == 0.3 and now["baselineAt"] == was["baselineAt"]
    assert problems == []
    page.close()


def test_a_settings_section_saves_its_keys_and_a_password_with_them(browser, household):
    h = household
    page, problems = signed_in(
        browser, h, "/ui/settings/email", 'form.card:has-text("From address")'
    )
    page.fill("#f-smtp-host", "smtp.home.lan")
    page.fill("#f-smtp-password", "app password")
    page.click('form.card:has-text("From address") button.primary')
    wait(page, '.toast:has-text("Saved")', problems)
    values = h.c.get("/ui/api/settings").json()["values"]
    assert values["smtpHost"] == "smtp.home.lan" and "smtpPassword" not in values
    assert h.c.get("/ui/api/settings/email").json()["password"]["setBy"]
    # Put back as it was, so other tests' emails are written to the folder.
    r = save_settings(h.c, {"smtpHost": None, "smtpPassword": None})
    assert r.status_code == 200, r.text
    assert problems == []
    page.close()


def test_a_statement_ticked_off_and_reconciled_through_the_save(browser, household):
    h = household
    a = made(
        make(
            h.c,
            "Acct",
            name="Ticked",
            type="checking",
            openingBalance="0.00",
            openingDate=f"{months_back(2)}-28",
        )
    )
    made(
        make(
            h.c,
            "Txn",
            accountId=a["id"],
            date=f"{months_back(1)}-03",
            amount="100.00",
            kind="deposit",
            payee="Paycheck",
        )
    )
    path = f"/ui/accounts/{a['id']}/reconcile"
    page, problems = signed_in(browser, h, path, 'button:has-text("Tick off against")')
    page.click('button:has-text("Tick off against")')
    page.fill("#f-statement-date", f"{months_back(1)}-28")
    page.fill("#f-statement-balance", "100")
    page.click(".dialog footer button.primary")
    wait(page, 'input[aria-label="Cleared: Paycheck"]', problems)
    page.check('input[aria-label="Cleared: Paycheck"]')
    wait(page, '.dialog footer button.primary:has-text("Mark reconciled"):enabled', problems)
    page.click(".dialog footer button.primary")
    wait(page, '.toast:has-text("reconciled")', problems)
    (rec,) = h.c.get(f"/ui/api/accounts/{a['id']}/reconcile").json()["reconciliations"]
    assert rec["finishedAt"] and rec["difference"] == 0
    assert problems == []
    page.close()


def test_a_share_given_and_taken_away_saves_its_grants(browser, household):
    h = household
    b = made(make(h.c, "Bdgt", name="Joint", accountIds=[]))
    page, problems = signed_in(
        browser, h, f"/ui/budgets/{b['id']}/month", 'button:has-text("Share")'
    )
    page.click('button:has-text("Share")')
    wait(page, '[aria-label="Access for Household"]', problems)
    page.click('[aria-label="Access for Household"] button:has-text("Write")')
    page.click('[aria-label="Access for Bob Griffin"] button:has-text("Read")')
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    v = h.c.get(f"/ui/api/shares/budget/{b['id']}").json()
    assert {g["name"]: g["allow"] for g in v["groups"]}["Household"] == "write"
    assert {u["displayName"]: u["allow"] for u in v["users"]}["Bob Griffin"] == "read"
    page.click('button:has-text("Share")')
    wait(page, '[aria-label="Access for Bob Griffin"]', problems)
    page.click('[aria-label="Access for Bob Griffin"] button:has-text("None")')
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    v = h.c.get(f"/ui/api/shares/budget/{b['id']}").json()
    assert {u["displayName"]: u["allow"] for u in v["users"]}["Bob Griffin"] == "none"
    assert problems == []
    page.close()


def test_tags_typed_are_made_with_the_save_and_a_rename_reaches_them(browser, household):
    h = household
    path = f"/ui/accounts/{h.checking['id']}/transactions"
    page, problems = signed_in(browser, h, path, 'tr:has-text("Grand Hotel") .row-tool')
    page.click('tr:has-text("Grand Hotel") .row-tool')
    wait(page, "#f-tags", problems)
    page.fill("#f-tags", "Travel, work trip")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    t = next(
        x
        for x in h.c.get("/ui/api/transactions", params={"account": h.checking["id"]}).json()[
            "items"
        ]
        if x["payee"] == "Grand Hotel"
    )
    assert t["tags"] == ["travel", "work trip"]
    mine = {x["name"]: x for x in h.c.get("/ui/api/tags").json()["items"]}
    saved(change(h.c, "Tag", mine["work trip"], name="conference"))
    t = h.c.get(f"/ui/api/transactions/{t['id']}").json()
    assert t["tags"] == ["conference", "travel"]
    assert problems == []
    page.close()


def test_a_tax_books_account_left_out_and_counted_again(browser, household):
    h = household
    name = h.checking["name"]
    row = f'.list-item:has-text("{name}") button'
    page, problems = signed_in(browser, h, "/ui/taxes/summary", f'{row}:has-text("Leave out")')
    page.click(f'{row}:has-text("Leave out")')
    wait(page, f'{row}:has-text("Count it")', problems)
    assert name in [a["name"] for a in book_of(h)["leftOut"]]
    page.click(f'{row}:has-text("Count it")')
    wait(page, f'{row}:has-text("Leave out")', problems)
    b = book_of(h)
    assert name in [a["name"] for a in b["accounts"]]
    assert name not in [a["name"] for a in b["leftOut"]]
    assert problems == []
    page.close()


def test_a_choice_that_takes_effect_when_made_saves_its_record(browser, household):
    # The theme toggle (one field of the user's own record) and a link setting chosen from a
    # list (a setting's record), each a draft saved at once.
    h = household
    page, problems = signed_in(browser, h, "/ui/settings/links", "#f-link-release")
    before = h.c.get("/ui/api/profile").json()["theme"]
    page.click('button[aria-label^="Theme: "]')
    for _ in range(50):
        if h.c.get("/ui/api/profile").json()["theme"] != before:
            break
        page.wait_for_timeout(100)
    assert h.c.get("/ui/api/profile").json()["theme"] != before
    page.select_option("#f-link-release", "240")
    wait(page, '.toast:has-text("Saved")', problems)
    assert h.c.get("/ui/api/settings").json()["values"]["linkReleaseMinutes"] == 240
    assert problems == []
    page.close()


def test_a_loan_payment_is_recorded_split_with_its_bank_half(browser, household):
    # S1.9.3: the loan's transaction, its parts and the bank's half, in one save; a bank
    # transaction that looks like a payment linked as the other half.
    h = household
    loan = made(make(h.c, "Acct", name="Boat loan", type="auto-loan"))
    saved(terms(h.c, loan["id"], principal="20000", startDate=f"{months_back(3)}-01",
                termMonths=60, rate="6"))  # fmt: skip
    due = h.c.get(f"/ui/api/accounts/{loan['id']}/loan").json()
    page, problems = signed_in(
        browser, h, f"/ui/accounts/{loan['id']}", 'button:has-text("Record a payment")'
    )
    page.click('button:has-text("Record a payment")')
    wait(page, "#f-from-account", problems)
    page.select_option("#f-from-account", label=h.checking["name"])
    page.click('button:has-text("Show the split")')
    wait(page, "#x-part-principal", problems)
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    (t,) = h.c.get("/ui/api/transactions", params={"account": loan["id"]}).json()["items"]
    assert t["transferAccountName"] == h.checking["name"]
    assert t["amount"] == due["total"] and len(t["splits"]) >= 2
    assert sum(Decimal(str(x["amount"])) for x in t["splits"]) == Decimal(str(due["total"]))
    day = f"{months_back(0)}-02"
    owed = f"-{due['total']}"
    bill = saved(create(h.c, "Txn", accountId=h.checking["id"], date=day, amount=owed,
                        kind="withdrawal", payee="BOAT LOAN"))  # fmt: skip
    page.reload()
    wait(page, 'button:has-text("Link")', problems)
    page.click('button:has-text("Link")')
    wait(page, '.toast:has-text("Linked")', problems)
    paid = h.c.get(f"/ui/api/transactions/{bill['id']}").json()
    assert paid["transferAccountName"] == "Boat loan"
    assert problems == []
    page.close()


def test_an_option_trade_is_saved_as_a_transaction_with_its_contract(browser, household):
    # S3.2: the trade's kind, the contract and the cash it comes to, one record of the save.
    h = household
    acct = h.extra["brokerage"]["id"]
    page, problems = signed_in(
        browser, h, f"/ui/accounts/{acct}/holdings", 'button:has-text("Record an option")'
    )
    page.click('button:has-text("Record an option")')
    wait(page, "#f-underlying", problems)
    page.fill("#f-underlying", "MSFT")
    page.fill("#f-strike", "480")
    page.fill("#f-expiry", f"{int(months_back(0)[:4]) + 1}-01-15")
    page.fill("#f-premium", "6.40")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    items = h.c.get("/ui/api/transactions", params={"account": acct}).json()["items"]
    (t,) = [x for x in items if x["kind"] == "sell-to-open"]
    assert t["symbol"].startswith("MSFT ") and t["symbol"].endswith(" 480 P")
    assert t["amount"] == 639.35, "100 × 6.40 less 0.65"
    assert problems == []
    page.close()


def test_a_corporate_action_is_a_record_its_transactions_made_from(browser, household):
    # S2.4: a symbol change typed in its dialog, its pair of transactions made from it.
    h = household
    acct = made(make(h.c, "Acct", name="Renamed", type="brokerage"))
    saved(create(h.c, "Txn", accountId=acct["id"], date=f"{months_back(2)}-03", kind="buy",
                 symbol="OLDCO", quantity="5", price="10", amount="-50.00"))  # fmt: skip
    page, problems = signed_in(
        browser, h, "/ui/positions/open", 'button:has-text("Corporate action")'
    )
    page.click('button:has-text("Corporate action")')
    wait(page, "#f-holding", problems)
    page.select_option("#f-holding", label="OLDCO in Renamed")
    page.select_option("#f-action", "symbol-change")
    wait(page, "#f-new-symbol", problems)
    page.fill("#f-new-symbol", "NEWCO")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    items = h.c.get("/ui/api/transactions", params={"account": acct["id"]}).json()["items"]
    assert sorted(x["kind"] for x in items) == ["buy", "symbol-change", "symbol-change"]
    held = h.c.get(f"/ui/api/accounts/{acct['id']}/holdings").json()["holdings"]
    assert [x["symbol"] for x in held] == ["NEWCO"]
    assert problems == []
    page.close()


def test_legs_proposed_together_are_grouped_or_turned_down_as_a_strategy(browser, household):
    # S3.5: Group them makes a strategy of the proposal's legs; Not a strategy keeps the
    # proposal turned down, so it isn't proposed again.
    h = household
    acct = made(make(h.c, "Acct", name="Spreads", type="brokerage"))
    expiry = f"{int(months_back(0)[:4]) + 1}-03-19"
    day = f"{months_back(0)}-01"
    for sym, action, strike, premium in (
        ("QQQ", "sell-to-open", "540", "2.00"), ("QQQ", "buy-to-open", "530", "1.20"),
        ("IWM", "sell-to-open", "240", "2.00"), ("IWM", "buy-to-open", "230", "1.20"),
    ):  # fmt: skip
        saved(option_trade(h.c, acct["id"], day, action, sym, "put", strike, expiry, "1",
                           premium))  # fmt: skip
    page, problems = signed_in(
        browser, h, "/ui/positions/strategies", 'button:has-text("Group them")'
    )
    page.locator('.notice:has-text("on QQQ")').locator('button:has-text("Group them")').click()
    wait(page, '.toast:has-text("Grouped")', problems)
    page.locator('.notice:has-text("on IWM")').locator('button:has-text("Not a strategy")').click()
    wait(page, '.toast:has-text("Left as they are")', problems)
    v = h.c.get("/ui/api/positions/strategies").json()
    mine = [x for x in v["strategies"] if x["accountId"] == acct["id"]]
    assert [x["underlying"] for x in mine] == ["QQQ"]
    assert not [p for p in v["proposals"] if p["accountId"] == acct["id"]]
    assert problems == []
    page.close()


def test_a_sale_picks_its_lots_in_the_dialog(browser, household):
    # CR3-389, S2.3: a sale lists the lots held on its day; the quantity typed against one is
    # a pick, saved as a record of the sale, and the rest goes oldest first.
    h = household
    acct = made(make(h.c, "Acct", name="Picked", type="brokerage"))
    for day, price in ((f"{months_back(6)}-03", "100"), (f"{months_back(4)}-03", "300")):
        saved(create(h.c, "Txn", accountId=acct["id"], date=day, kind="buy", symbol="IBM",
                     quantity="10", price=price, amount=f"-{int(price) * 10}.00"))  # fmt: skip
    newer = f"{months_back(4)}-03"
    path = f"/ui/accounts/{acct['id']}/transactions"
    page, problems = signed_in(browser, h, path, 'main button:has-text("Add")')
    page.click('main button:has-text("Add")')
    wait(page, ".dialog footer button.primary:enabled", problems)
    page.select_option("#f-kind", "sell")
    page.fill("#f-date", f"{months_back(1)}-03")
    page.fill("#f-symbol", "IBM")
    page.fill("#f-quantity", "12")
    page.fill("#f-price", "250")
    page.fill("#f-amount", "3000.00")
    take = f'[aria-label="Take from the lot bought {newer}"]'
    wait(page, take, problems)
    page.fill(take, "8")
    wait(page, '.dialog :text("8 of 12 picked")', problems)
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    items = h.c.get("/ui/api/transactions", params={"account": acct["id"]}).json()["items"]
    (sale,) = [x for x in items if x["kind"] == "sell"]
    lots = h.c.get(f"/ui/api/accounts/{acct['id']}/lots", params={"date": newer}).json()["items"]
    (lot,) = [x for x in lots if x["acquiredOn"] == newer]
    assert [(p["lotId"], p["quantity"]) for p in sale["picks"]] == [(lot["lotId"], 8)]
    assert problems == []
    page.close()


def test_an_options_end_takes_a_count_from_1_to_those_held(browser, household):
    # CR3-403, R3.11: the settle dialog's Contracts starts empty; 0 is marked when the field is
    # left (and refused if saved); All fills in the contracts held and greys out; Record settles
    # them.
    h = household
    acct = made(make(h.c, "Acct", name="Settled", type="brokerage"))
    expiry = f"{months_back(1)}-15"
    saved(option_trade(h.c, acct["id"], f"{months_back(2)}-01", "sell-to-open", "KO", "put",
                       "60", expiry, "2", "1.10"))  # fmt: skip
    page, problems = signed_in(browser, h, "/ui/positions/open", "text=KO")
    page.get_by_role("row", name=re.compile(r"KO .* 60 P")).locator("button.linklike").click()
    page.get_by_role("button", name="Expired, assigned or exercised…").click()
    wait(page, ".dialog .value-input input", problems)
    field = page.locator(".dialog .value-input input")
    assert field.input_value() == ""
    field.fill("0")
    assert page.locator(".dialog .value-input input.bad").count() == 0, "not while typed"
    page.keyboard.press("Tab")
    wait(page, ".dialog .value-input input.bad", problems)
    page.get_by_role("button", name="All: 2 contracts").click()
    assert field.input_value() == "2"
    assert page.get_by_role("button", name="All: 2 contracts").is_disabled()
    assert page.locator(".dialog .value-input input.bad").count() == 0
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    held = h.c.get(f"/ui/api/accounts/{acct['id']}/holdings").json()["holdings"]
    assert [x["symbol"] for x in held if x["symbol"].startswith("KO ")] == []
    assert problems == []
    page.close()


def test_a_529s_beneficiary_added_in_a_dialog_over_its_settings(browser, household):
    """S12.15.7: Add a person… opens Add a person over the 529's Settings; cancelled, the
    choice is as it was; saved, the person is made and chosen, and the plan saves with them."""
    h = household
    a = made(make(h.c, "Acct", name="Browser 529", type="529"))
    path = f"/ui/accounts/{a['id']}/settings"
    page, problems = signed_in(browser, h, path, "#f-beneficiary")
    page.select_option("#f-beneficiary", "new")
    wait(page, ".dialog #f-their-name", problems)
    page.keyboard.press("Escape")
    wait(page, ".dialog", problems, state="detached")
    for _ in range(600):  # the choice goes back once the dialog has gone
        if page.input_value("#f-beneficiary") == "":
            break
        page.wait_for_timeout(50)
    assert page.input_value("#f-beneficiary") == ""
    page.select_option("#f-beneficiary", "new")
    wait(page, ".dialog #f-their-name", problems)
    page.fill(".dialog #f-their-name", "Browser Wren")
    page.fill(".dialog #f-year-of-birth", "2019")
    page.click(".dialog footer button.primary")
    wait(page, '.dialog .err:has-text("Female or male.")', problems)  # refused at its field
    problems.clear()  # the refused save's 422, expected
    page.select_option(".dialog #f-sex", "female")
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    people = {p["name"]: p["id"] for p in h.c.get("/ui/api/persons").json()["items"]}
    wren = people["Browser Wren"]
    for _ in range(600):
        if page.input_value("#f-beneficiary") == wren:
            break
        page.wait_for_timeout(50)
    assert page.input_value("#f-beneficiary") == wren
    page.click("form.draft-form button.primary")
    wait(page, ".toast", problems)
    plan = h.c.get(f"/ui/api/accounts/{a['id']}/plan529").json()
    assert plan["beneficiaryId"] == wren
    assert problems == []
    page.close()
