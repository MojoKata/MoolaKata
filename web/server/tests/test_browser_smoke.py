"""One smoke test drives a running server in headless Chromium (requirements S17.5)."""

import httpx
import pytest
from browser import open_page, start, stop, unlocked

from moolakata.keys import phrase

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def running(tmp_path_factory):
    base, proc = unlocked(tmp_path_factory.mktemp("smoke"))
    yield base
    stop(proc)


def test_app_loads_under_its_csp(running, browser):
    page, problems = open_page(browser, running + "/ui/")
    page.wait_for_selector("#app > *")
    assert problems == []
    page.close()


def test_demo_runs_in_its_sandbox(running, browser):
    page, problems = open_page(browser, running + "/demo#/dashboard")
    page.wait_for_timeout(300)
    assert page.evaluate("typeof window.MOCK_INDEX") == "object"
    assert problems == []
    page.close()


def test_the_welcome_makes_the_key_and_the_first_admin(tmp_path, browser):
    """A new server, no keyring: the welcome in the browser shows a phrase, takes three of its
    words back, and sets up the first admin, who lands on the Dashboard (S12.14.1, S10.1.2)."""
    import re

    base, proc, _ = start(tmp_path, keyed=False)
    try:
        page, problems = open_page(browser, base + "/ui/")
        page.get_by_role("button", name="Show my recovery phrase").click()
        page.locator("ol.phrase").wait_for()
        words = page.locator("ol.phrase li").all_inner_texts()
        assert len(words) == 12 and phrase.from_words(words)
        page.get_by_role("button", name="I've written them down").click()
        page.get_by_role("button", name="Make the key").wait_for()
        asked = [
            int(re.search(r"\d+", label).group())
            for label in page.locator("label").all_inner_texts()
            if label.startswith("Word")
        ]
        for n in asked:
            page.locator(f"#x-word-{n}").fill(words[n - 1][:4])
        page.get_by_role("button", name="Make the key").click()
        page.get_by_text("Set up the admin account").wait_for(timeout=60000)
        assert httpx.get(base + "/healthz").status_code == 200
        page.locator("#f-your-name").fill("Pat Tester")
        page.locator("select").select_option("female")
        page.locator("#f-email-address").fill("pat@home.lan")
        page.locator("#f-password").fill("a long admin passphrase")
        page.get_by_role("button", name="Save and continue").click()
        page.get_by_role("heading", name="Dashboard").first.wait_for(timeout=30000)
        assert problems == []
        page.close()
    finally:
        stop(proc)
