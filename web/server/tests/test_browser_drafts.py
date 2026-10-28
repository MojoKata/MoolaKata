"""Dialogs that edit a draft, driven in headless Chromium (requirements S12.15, S17.5): saved
unchanged, a dialog changes nothing; holding changes, it asks before discarding them (CR3-2)."""

import datetime as dt

import httpx
import pytest
from test_browser_smoke import browser, open_page, running  # noqa: F401 - fixtures

pytestmark = pytest.mark.browser

PASSWORD = "a long admin passphrase"


def months_back(n: int) -> str:
    today = dt.date.today()
    y, m = divmod(today.year * 12 + today.month - 1 - n, 12)
    return f"{y:04d}-{m + 1:02d}"


@pytest.fixture(scope="module")
def household(running):  # noqa: F811
    """An admin with a checking account and groceries bought in each of the last three months,
    and two budgets from this month: a tracking one with reserves and moves (a rolling line, a
    move between two lines, a reserve with its target) and an envelope one with a yearly line.
    Months count from today: the server's clock."""
    c = httpx.Client(base_url=running, headers={"Origin": running}, timeout=30)

    # The session cookie is Secure, which httpx won't send over http: carried by hand.
    def keep(response: httpx.Response) -> None:
        for v in response.headers.get_list("set-cookie"):
            name, _, rest = v.partition("=")
            token = rest.split(";", 1)[0]
            c.headers["Cookie"] = f"{name}={token}"

    c.event_hooks["response"] = [keep]
    r = c.post(
        "/ui/api/welcome/admin",
        json={"password": PASSWORD, "email": "admin@home.lan", "displayName": "Admin",
              "sex": "female"},
    )  # fmt: skip
    if r.status_code == 409:
        r = c.post("/ui/api/session", json={"login": "admin", "password": PASSWORD})
    assert r.status_code == 200, r.text
    acct = c.post("/ui/api/accounts", json={"name": "Checking", "type": "checking"}).json()
    cats = {x["path"]: x["id"] for x in c.get("/ui/api/categories").json()["items"]}
    dining, fun = cats["Food › Dining out"], cats["Entertainment"]
    repair, groceries = cats["Transportation › Car maintenance"], cats["Food › Groceries"]
    for n in (1, 2, 3):
        r = c.post(
            "/ui/api/transactions",
            json={"accountId": acct["id"], "date": f"{months_back(n)}-05", "amount": "-120.00",
                  "payee": "Kroger", "categoryId": groceries},
        )  # fmt: skip
        assert r.status_code == 201, r.text
    b = c.post("/ui/api/budgets", json={"name": "Household", "accountIds": [acct["id"]]}).json()
    v = c.get(f"/ui/api/budgets/{b['id']}").json()["version"]
    r = c.patch(
        f"/ui/api/budgets/{b['id']}",
        json={"reserves": True, "moves": True},
        headers={"If-Match": str(v)},
    )
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    r = c.put(
        f"/ui/api/budgets/{b['id']}/plan",
        json={"month": f"{months_back(0)}-01",
              "lines": [{"categoryId": dining, "amount": "300.00", "rollover": True},
                        {"categoryId": fun, "amount": "200.00"},
                        {"categoryId": repair, "amount": "100.00", "target": "1000.00"}]},
        headers={"If-Match": str(v)},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    r = c.post(
        f"/ui/api/budgets/{b['id']}/moves",
        json={"month": f"{months_back(0)}-01", "fromCategoryId": fun, "toCategoryId": dining,
              "amount": "40.00"},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    env = c.post(
        "/ui/api/budgets",
        json={"name": "Envelopes", "method": "envelope", "accountIds": [acct["id"]]},
    ).json()
    r = c.put(
        f"/ui/api/budgets/{env['id']}/plan",
        json={"month": f"{months_back(0)}-01",
              "lines": [{"categoryId": fun, "amount": "1200.00", "cadence": "year"}]},
        headers={"If-Match": str(env["version"])},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    yield c, b, env
    c.close()


def wait(page, selector: str, problems: list, **kw) -> None:
    """Wait for a selector; a timeout names what the page reported on the way."""
    from playwright.sync_api import TimeoutError as Late

    try:
        page.wait_for_selector(selector, **kw)
    except Late:
        import os

        shot = os.environ.get("MK_FAIL_SHOT")
        if shot:
            page.screenshot(path=shot)
        pytest.fail(f"{selector} {kw}: never; the page said {problems}")


def plan_of(c, b) -> list[dict]:
    r = c.get(f"/ui/api/budgets/{b['id']}/plan", params={"month": months_back(0)})
    assert r.status_code == 200, r.text
    return sorted(r.json()["lines"], key=lambda x: x["id"])


def signed_in(browser, running, b):  # noqa: F811
    page, problems = open_page(browser, running + "/ui/")
    r = page.request.post(
        running + "/ui/api/session",
        data={"login": "admin", "password": PASSWORD},
        headers={"Origin": running},
    )
    assert r.ok, r.text()
    page.goto(f"{running}/ui/budgets/{b['id']}/month")
    wait(page, 'button:has-text("Edit plan")', problems)
    return page, problems


@pytest.mark.parametrize("which", ["Household", "Envelopes"])
def test_the_plan_saved_unchanged_changes_nothing(browser, running, household, which):  # noqa: F811
    """CR3-2: moves, carried remainders, a reserve's balance and a yearly line all survive a
    plan dialog opened and saved untouched."""
    c, b, env = household
    budget = b if which == "Household" else env
    before = plan_of(c, budget)
    page, problems = signed_in(browser, running, budget)
    page.click('button:has-text("Edit plan")')
    wait(page, ".dialog table.plan tbody tr", problems)
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    assert plan_of(c, budget) == before
    assert problems == []
    page.close()


def test_a_plan_from_history_leaves_the_lines_it_doesnt_propose(browser, running, household):  # noqa: F811
    """CR3-2's fourth case: the estimate keeps the reserve it doesn't propose, target and all."""
    c, b, _ = household
    before = {x["categoryId"]: x for x in plan_of(c, b)}
    page, problems = signed_in(browser, running, b)
    page.click('button:has-text("Estimate from history")')
    wait(page, ".dialog table.plan tbody tr", problems)
    page.click(".dialog footer button.primary")
    wait(page, ".dialog", problems, state="detached")
    after = {x["categoryId"]: x for x in plan_of(c, b)}
    assert len(after) == len(before) + 1, "groceries proposed and planned"
    for cat, line in before.items():
        assert after[cat] == line, "a line not proposed stays exactly as it was"
    assert problems == []
    page.close()


def test_a_dialog_holding_changes_asks_before_discarding_them(browser, running, household):  # noqa: F811
    """S12.15.6: Escape asks; Keep editing keeps the dialog and its change; a click on the
    dimmed content does nothing; Discard closes, saving nothing."""
    c, b, _ = household
    before = plan_of(c, b)
    page, problems = signed_in(browser, running, b)
    page.click('button:has-text("Edit plan")')
    wait(page, ".dialog table.plan tbody tr", problems)
    amount = page.locator('.dialog input[aria-label="Amount"]').first
    amount.fill("12.")
    page.keyboard.press("Escape")
    wait(page, "text=Discard your changes?", problems)
    page.click('button:has-text("Keep editing")')
    assert page.locator(".dialog-ask").count() == 0
    assert amount.input_value() == "12.", "what was typed stays as typed"
    page.mouse.click(5, 5)
    assert page.locator(".dialog").count() == 1, "a click outside doesn't close it"
    page.click(".dialog-x")
    page.click('button:has-text("Discard")')
    wait(page, ".dialog", problems, state="detached")
    assert plan_of(c, b) == before
    assert problems == []
    page.close()
