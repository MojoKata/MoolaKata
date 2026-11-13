"""The ui-kit's pages (requirements S17.3.10.4, S17.5.13): each opens with no page or console
error, in both themes, every state drawn."""

import pytest
from conftest import PAGES_IN_ORDER, open_page, shot


@pytest.mark.parametrize("name", PAGES_IN_ORDER)
def test_each_page_opens_in_both_themes(page, kit, name):
    open_page(page, kit, name)
    assert page.locator(".kit-link.on").get_attribute("href") == f"#{name}"
    assert page.locator(".kit-page .demo, .kit-page section").count() > 0
    shot(page, f"{name}-dark")
    page.click(".kit-theme")
    # Waits go through locators: the page's CSP, the app's, refuses a string evaluated.
    page.locator("html[data-theme='light']").wait_for(state="attached")
    shot(page, f"{name}-light")
