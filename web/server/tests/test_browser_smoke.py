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


def test_rotate_restarts_the_server_and_it_opens_with_the_new_phrase(tmp_path, browser):
    """S15.7.1, S15.7.2: Rotate in Settings › Key storage shows a new phrase and takes three
    of its words back; the server restarts itself, in the same process, locked; the new
    phrase unlocks it, re-encrypting first, and the old one no longer does."""
    import re

    base, proc, key = start(tmp_path, keyed=True)
    try:
        old = " ".join(phrase.to_words(key))
        r = httpx.post(base + "/ui/api/unlock", json={"phrase": old}, headers={"Origin": base})
        assert r.status_code == 200, r.text
        page, problems = open_page(browser, base + "/ui/")
        r = page.request.post(
            base + "/ui/api/welcome/admin",
            data={
                "displayName": "Pat Tester",
                "sex": "female",
                "email": "pat@home.lan",
                "password": "a long admin passphrase",
            },
            headers={"Origin": base},
        )
        assert r.ok, r.text()
        page.goto(base + "/ui/settings/keys")
        page.get_by_role("button", name="Rotate", exact=True).click()
        page.get_by_label("Current recovery phrase").fill(old)
        page.get_by_role("button", name="Show the new phrase").click()
        page.locator(".dialog ol.phrase").wait_for()
        words = page.locator(".dialog ol.phrase li").all_inner_texts()
        assert len(words) == 12
        page.get_by_role("button", name="I've written them down").click()
        page.get_by_role("button", name="Rotate and restart").wait_for()
        asked = [
            int(re.search(r"\d+", label).group())
            for label in page.locator(".dialog label").all_inner_texts()
            if label.startswith("Word")
        ]
        for n in asked:
            page.get_by_label(f"Word {n}", exact=True).fill(words[n - 1][:4])
        page.get_by_role("button", name="Rotate and restart").click()
        page.get_by_text("MoolaKata is locked").wait_for(timeout=60000)
        assert proc.poll() is None, "the same process, started again"
        page.locator("#f-recovery-phrase").fill(old)
        page.get_by_role("button", name="Unlock").click()
        page.get_by_text("Those words").or_(page.get_by_text("not this server")).first.wait_for()
        page.locator("#f-recovery-phrase").fill(" ".join(words))
        page.get_by_role("button", name="Unlock").click()
        page.get_by_role("heading", name="Key storage", exact=True).wait_for(timeout=60000)
        assert httpx.get(base + "/healthz").status_code == 200
        page.get_by_text("with a rotation").wait_for()
        # The wrong phrase above answered 403, as it should.
        assert [p for p in problems if "403" not in p] == []
        page.close()
    finally:
        stop(proc)
