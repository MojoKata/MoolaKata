"""Every screen, tab and dialog of the browser app has its guide, and each field's label finds a
heading in it, in the page's order (S12.7.6), on a seeded dev server in headless Chromium
(requirements S17.5). The screens and dialogs are split into parts, each with a page and a
session of its own, so the parts run on several workers at once; each worker starts the dev
server once for this module."""

import re

import pytest
from devapp import (
    SETTINGS_SECTIONS,
    account_ids,
    as_alice,
    check_guide,
    close_dialog,
    open_dialog,
    visit,
    wait_guide,
)

pytestmark = pytest.mark.browser

# Parts of about half a minute each on a standard CI runner.
SCREEN_PARTS = 6
DIALOG_PARTS = 3


@pytest.fixture
def fresh(dev_server):
    """A page of its own, signed in as alice."""
    with as_alice(dev_server) as pg:
        yield pg


def screens(page) -> list[str]:
    """Every screen and tab, from the seed's accounts, portfolios, projections and budgets."""
    ids = account_ids(page)
    ports = page.evaluate("""async () => (await (await fetch('/ui/api/portfolios')).json()).items
        .map((p) => p.id)""")
    paths = [
        "/ui/",
        "/ui/accounts",
        "/ui/transactions",
        "/ui/portfolios",
        "/ui/positions/open",
        "/ui/positions/closed",
        "/ui/positions/trades",
        "/ui/positions/gains",
        "/ui/activity",
        "/ui/alerts",
        "/ui/receipts",
        "/ui/projections",
        "/ui/gifts/upcoming",
        "/ui/gifts/people",
        "/ui/gifts/gifts",
        "/ui/gifts/spending",
        "/ui/giving/overview",
        "/ui/giving/donations",
        "/ui/giving/organisations",
        "/ui/giving/fund",
        "/ui/taxes/summary",
        "/ui/taxes/filings",
        "/ui/taxes/documents",
        "/ui/taxes/gains",
        "/ui/taxes/income",
        "/ui/taxes/retirement",
        "/ui/taxes/deductions",
        "/ui/taxes/giving",
        "/ui/taxes/education",
        "/ui/taxes/property",
        "/ui/taxes/issues",
        "/ui/users",
        "/ui/profile",
    ]
    for t in ("checking", "brokerage", "401k", "credit-card"):
        for tab in ("overview", "holdings", "transactions", "reconcile", "sharing", "settings"):
            paths.append(f"/ui/accounts/{ids[t]}/{tab}")
    for t in ("mortgage", "auto-loan"):
        for tab in ("overview", "schedule", "payoff", "transactions", "sharing", "settings"):
            paths.append(f"/ui/accounts/{ids[t]}/{tab}")
    for tab in ("overview", "holdings", "settings"):
        paths.append(f"/ui/accounts/{ids['daf']}/{tab}")
    for tab in ("overview", "holdings", "contributions", "withdrawals", "goal", "settings"):
        paths.append(f"/ui/accounts/{ids['529']}/{tab}")
    for t in ("precious-metals", "collectables", "real-estate", "vehicle"):
        for tab in ("overview", "items", "transactions", "sharing", "settings"):
            paths.append(f"/ui/accounts/{ids[t]}/{tab}")
    for tab in ("overview", "holdings", "transactions", "sharing", "settings"):
        paths.append(f"/ui/accounts/{ids['crypto-wallet']}/{tab}")
    for p in ports:
        paths += [f"/ui/portfolios/{p}/{t}" for t in ("performance", "holdings", "projections")]
    budgets = page.evaluate("""async () => (await (await fetch('/ui/api/budgets')).json()).items
        .map((b) => b.id)""")
    for x in page.evaluate("""async () => (await (await fetch('/ui/api/projections')).json()).items
        .map((p) => p.id)"""):
        paths.append(f"/ui/projections/{x}")
    for b in budgets:
        paths += [f"/ui/budgets/{b}/{t}" for t in ("month", "cash-flow", "trends", "recurring")]
    for s in SETTINGS_SECTIONS:
        paths.append(f"/ui/settings/{s}")
    return paths


@pytest.mark.parametrize("part", range(SCREEN_PARTS))
def test_every_screen_and_tab_has_its_guide(fresh, part):
    for path in screens(fresh)[part::SCREEN_PARTS]:
        visit(fresh, path)
        check_guide(fresh, ".content", path)
    assert fresh.problems == []


def dialogs(page) -> list[tuple[str, str, str]]:
    """Every dialog a screen's button opens: the screen, the button, the dialog's guide."""
    ids = account_ids(page)
    return [
        ("/ui/accounts", "New account", "dialog-new-account"),
        ("/ui/accounts", "Import", "dialog-import"),
        ("/ui/accounts", "Share Everyday checking", "dialog-share"),
        ("/ui/transactions", "Add", "dialog-transaction"),
        ("/ui/transactions", "Rules", "dialog-rules"),
        (
            f"/ui/accounts/{ids['checking']}/reconcile",
            "Type today's balance",
            "dialog-type-balance",
        ),
        (
            f"/ui/accounts/{ids['checking']}/reconcile",
            "Tick off against a statement",
            "dialog-tick-off",
        ),
        (f"/ui/accounts/{ids['mortgage']}", "Record a payment", "dialog-loan-payment"),
        (f"/ui/accounts/{ids['mortgage']}", "Type it", "dialog-servicer-balance"),
        ("/ui/portfolios", "New portfolio", "dialog-portfolio"),
        ("/ui/budgets", "New budget", "dialog-budget"),
        ("/ui/budgets", "Edit plan", "dialog-plan"),
        ("/ui/budgets", "Settings", "dialog-budget-settings"),
        ("/ui/budgets", "Estimate from history…", "dialog-estimate"),
        ("/ui/budgets/x/reimbursements", "Pair a payback", "dialog-pair"),
        ("/ui/budgets/x/where", "Assign", "dialog-assign"),
        ("/ui/budgets", "Move", "dialog-move"),
        ("/ui/budgets/x/list", "Copy as scenario", "dialog-copy"),
        ("/ui/budgets/x/list", "Make active", "dialog-make-active"),
        ("/ui/receipts", "Receipt Blue Bottle Coffee", "dialog-receipt"),
        ("/ui/projections", "New projection", "dialog-new-projection"),
        ("/ui/gifts/people", "Add a gift plan", "dialog-person"),
        ("/ui/gifts/gifts", "Add a gift", "dialog-gift"),
        ("/ui/giving/donations", "Record a donation", "dialog-donation"),
        ("/ui/positions/open", "Record an option trade", "dialog-option-trade"),
        ("/ui/positions/open", "Corporate action…", "dialog-corporate-action"),
        ("/ui/giving/organisations", "Add an organisation", "dialog-organisation"),
        ("/ui/taxes/summary", "New tax book", "dialog-tax-book"),
        ("/ui/taxes/filings", "Add a filing", "dialog-filing"),
        ("/ui/taxes/documents", "Add a document", "dialog-tax-document"),
        ("/ui/profile", "Compare models", "dialog-bitcoin-models"),
        ("/ui/profile", "New token", "dialog-new-token"),
        ("/ui/profile", "New connection", "dialog-connection"),
        ("/ui/users", "New user", "dialog-new-user"),
        ("/ui/users", "New group", "dialog-group"),
        ("/ui/settings/prices", "Add a source", "dialog-add-source"),
        ("/ui/settings/links", "Enter a link code", "dialog-link-join"),
        ("/ui/settings/connector", "Pair a replacement…", "dialog-connector-pair"),
    ]


@pytest.mark.parametrize("part", range(DIALOG_PARTS))
def test_every_dialog_has_its_guide(fresh, part):
    for path, button, guide in dialogs(fresh)[part::DIALOG_PARTS]:
        open_dialog(fresh, path, button, guide)
        close_dialog(fresh)
    assert fresh.problems == []


def test_every_dialog_reached_through_another_has_its_guide(fresh):
    """A dialog, or a part of one, reached from another or by what is typed in it; some save
    (a token, a linked copy's reset, a link address), so on this module's own server."""
    page = fresh
    ids = account_ids(page)
    # The rules' list leads to a rule.
    open_dialog(page, "/ui/transactions", "Rules", "dialog-rules")
    page.get_by_role("button", name="Add a rule").click()
    wait_guide(page, "dialog-rule")
    check_guide(page, ".dialog", "a rule")
    page.keyboard.press("Escape")  # back to the list, then closed
    wait_guide(page, "dialog-rules")
    close_dialog(page)
    # The type picker leads to the form.
    open_dialog(page, "/ui/accounts", "New account", "dialog-new-account")
    page.get_by_role("button", name=re.compile("^Brokerage")).click()
    wait_guide(page, "dialog-account-form")
    check_guide(page, ".dialog", "the account form")
    close_dialog(page)
    for loan in ("Mortgage", "HELOC"):
        open_dialog(page, "/ui/accounts", "New account", "dialog-new-account")
        page.get_by_role("button", name=re.compile(f"^{loan}")).click()
        wait_guide(page, "dialog-account-form")
        check_guide(page, ".dialog", f"the {loan} form")
        close_dialog(page)
    # A payment's split names its heading; an ARM's resets add rows that do too.
    open_dialog(page, f"/ui/accounts/{ids['mortgage']}", "Record a payment", "dialog-loan-payment")
    page.get_by_role("button", name="Show the split").click()
    page.wait_for_selector(".dialog #x-part-principal")
    check_guide(page, ".dialog", "a payment's split")
    close_dialog(page)
    visit(page, f"/ui/accounts/{ids['auto-loan']}/settings")
    page.get_by_role("button", name="Add a reset").click()
    page.get_by_role("button", name="Add a recast").click()
    check_guide(page, ".content", "a loan's resets and recasts")
    # The planner's lump sums add rows, and a recast its fee.
    visit(page, f"/ui/accounts/{ids['mortgage']}/payoff")
    page.get_by_role("button", name="Add a lump sum").click()
    page.get_by_role("switch", name="Recast after the lump sums").click()
    page.wait_for_selector("#f-recast-fee")
    check_guide(page, ".content", "a payoff plan with a lump sum and a recast")
    # Each kind of item opens in its dialog, with valuations, improvements and the sale.
    for t, name in (
        ("precious-metals", "Silver bar"),
        ("collectables", "Rolex"),
        ("real-estate", "1428 Elm St"),
        ("vehicle", "Outback"),
    ):
        visit(page, f"/ui/accounts/{ids[t]}/items")
        page.get_by_role("row", name=re.compile(name)).click()
        page.wait_for_selector(".dialog")
        wait_guide(page, "dialog-item")
        if page.get_by_role("button", name="Record the sale…").count():
            page.get_by_role("button", name="Record the sale…").click()
        check_guide(page, ".dialog", f"a {t} item")
        close_dialog(page)
    open_dialog(page, f"/ui/accounts/{ids['collectables']}/items", "Add an item", "dialog-item")
    close_dialog(page)
    # A person with their dates, and a gift with its purchase.
    visit(page, "/ui/gifts/people")
    page.get_by_role("row", name=re.compile("Bob Griffin")).click()
    wait_guide(page, "dialog-person")
    check_guide(page, ".dialog", "a person with dates")
    close_dialog(page)
    visit(page, "/ui/gifts/gifts")
    page.get_by_role("row", name=re.compile("Riding lessons")).click()
    wait_guide(page, "dialog-gift")
    check_guide(page, ".dialog", "a planned gift")
    close_dialog(page)
    # The giving plan, a donation of shares, a recorded donation and an organisation.
    visit(page, "/ui/giving/overview")
    page.get_by_role("link", name="Edit").click()
    wait_guide(page, "dialog-giving-plan")
    check_guide(page, ".dialog", "the giving plan")
    close_dialog(page)
    open_dialog(page, "/ui/giving/donations", "Record a donation", "dialog-donation")
    page.select_option(".dialog #f-kind", "securities")
    page.select_option(".dialog #f-from-account", label="Taxable brokerage")
    page.wait_for_selector(".dialog #f-lot")
    check_guide(page, ".dialog", "a donation of shares")
    close_dialog(page)
    visit(page, "/ui/giving/donations")
    page.get_by_role("row", name=re.compile("American Red Cross")).click()
    wait_guide(page, "dialog-donation")
    check_guide(page, ".dialog", "a recorded donation")
    close_dialog(page)
    visit(page, "/ui/giving/organisations")
    page.get_by_role("row", name=re.compile("Goodwill")).click()
    wait_guide(page, "dialog-organisation")
    check_guide(page, ".dialog", "an organisation")
    close_dialog(page)
    # A filed return, with its payments and carried figures; a filed document.
    visit(page, "/ui/taxes/filings")
    page.get_by_role("button", name="Edit").first.click()
    wait_guide(page, "dialog-filing")
    page.get_by_role("button", name="Add a payment").click()
    check_guide(page, ".dialog", "a filing")
    close_dialog(page)
    open_dialog(page, "/ui/taxes/documents", "Add a filed document", "dialog-tax-document")
    close_dialog(page)
    # An open option's end.
    visit(page, "/ui/positions/open")
    page.get_by_role("row", name=re.compile("MSFT .* 480 P")).click()
    page.get_by_role("button", name="Expired, assigned or exercised…").click()
    page.wait_for_selector(".dialog")
    wait_guide(page, "dialog-option-settle")
    check_guide(page, ".dialog", "an option's end")
    close_dialog(page)
    page.get_by_role("button", name="Type a mark…").click()
    page.wait_for_selector(".dialog")
    wait_guide(page, "dialog-option-mark")
    check_guide(page, ".dialog", "an option's mark")
    close_dialog(page)
    # A 529's form, with a person added in it.
    open_dialog(page, "/ui/accounts", "New account", "dialog-new-account")
    page.get_by_role("button", name=re.compile("^529 plan")).click()
    wait_guide(page, "dialog-account-form")
    page.select_option(".dialog #f-beneficiary", "new")
    page.wait_for_selector(".dialog #f-new-name")
    check_guide(page, ".dialog", "the 529 form")
    close_dialog(page)
    # A token's chosen items, then the token shown once.
    open_dialog(page, "/ui/profile", "New token", "dialog-new-token")
    page.select_option(".dialog #f-can-read", "chosen")
    check_guide(page, ".dialog", "a token's chosen items")
    page.fill(".dialog #f-token-name", "A test token")
    page.select_option(".dialog #f-can-read", "all")
    page.get_by_role("button", name="Create token").click()
    wait_guide(page, "dialog-token-shown")
    check_guide(page, ".dialog", "a token shown once")
    assert "mkt_" in page.inner_text(".dialog")
    close_dialog(page)
    # A linked copy's access key, shown once (after a reset: the seeded copy has its key).
    visit(page, "/ui/settings/links")
    page.get_by_role("button", name="Reset copy").click()
    page.get_by_role("button", name="Yes, reset").click()
    page.wait_for_selector("text=Copy reset")
    open_dialog(page, "/ui/settings/links", "Create the access key", "dialog-copy-key")
    page.wait_for_selector(".dialog .words")
    check_guide(page, ".dialog", "a linked copy's access key")
    close_dialog(page)
    # Sharing with a linked server's people, and its Include receipts.
    open_dialog(page, "/ui/accounts", "Share Everyday checking", "dialog-share")
    page.get_by_role("radiogroup", name="Access for Margaret Griffin").get_by_role(
        "radio", name="Read"
    ).click()
    page.wait_for_selector(".dialog [data-help=include-receipts]")
    check_guide(page, ".dialog", "a share with a linked server's people")
    close_dialog(page)
    # An invitation, once this server has a link address.
    visit(page, "/ui/settings/links")
    page.fill(".content #f-link-address", page.url.split("/ui/")[0])
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_selector("text=Saved")
    open_dialog(page, "/ui/settings/links", "Invite a server", "dialog-link-invite")
    page.wait_for_selector(".dialog code")
    check_guide(page, ".dialog", "an invitation's code")
    assert "mkl1." in page.inner_text(".dialog")
    close_dialog(page)
    # Settings › Bitcoin with each kind of node's fields.
    visit(page, "/ui/settings/bitcoin")
    for node in ("esplora", "electrum", "core"):
        page.select_option(".content #f-explorer-or-node", node)
        check_guide(page, ".content", f"Settings › Bitcoin ({node})")
    # A wallet's form, which clears a seed phrase at once.
    open_dialog(page, "/ui/accounts", "New account", "dialog-new-account")
    page.get_by_role("button", name=re.compile("^Self-custody wallet")).click()
    wait_guide(page, "dialog-account-form")
    check_guide(page, ".dialog", "the wallet form")
    # On one line: Playwright fills a textarea's lines with extra input events, which a paste
    # doesn't send.
    numbered = " ".join(f"{i}. {w}" for i, w in enumerate(["abandon"] * 11 + ["about"], 1))
    wif = "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ"
    for secret in ("abandon " * 11 + "about", numbered, f"wpkh({wif})#qwer1234"):
        page.fill(".dialog #f-wallet-keys", secret)
        assert page.input_value(".dialog #f-wallet-keys") == "", secret
        assert "never accepts one" in page.inner_text(".dialog #f-wallet-keys-err"), secret
    close_dialog(page)
    # An education projection's inputs.
    open_dialog(page, "/ui/projections", "New projection", "dialog-new-projection")
    page.get_by_role("radio", name="Education").click()
    check_guide(page, ".dialog", "a new education projection")
    close_dialog(page)
    # Splits add rows that name their heading.
    open_dialog(page, "/ui/transactions", "Add", "dialog-transaction")
    page.select_option(".dialog #f-account", label="Everyday checking")
    page.get_by_role("button", name="Split…").click()
    check_guide(page, ".dialog", "a split transaction")
    close_dialog(page)
    assert page.problems == []
