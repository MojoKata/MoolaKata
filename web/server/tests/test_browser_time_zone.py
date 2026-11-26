"""Profile's time zone in headless Chromium (requirements S14.9.2): changing it asks Since when?,
today where the new time zone is by default; a blank date is refused at the field, never read as
today; saved, the new time zone is the one in effect, and the form reads it again."""

import datetime as dt

import pytest
from browser import made, signed_in, wait
from edits import create

pytestmark = pytest.mark.browser

ZONE = "Pacific/Kiritimati"  # UTC+14: often a day ahead of the browser


def _today(page, zone: str) -> str:
    return page.evaluate(
        "z => new Intl.DateTimeFormat('en-CA', { timeZone: z }).format(new Date())", zone
    )


def test_changing_the_time_zone_asks_since_when(browser, household):
    h = household
    was = h.c.get("/ui/api/profile").json()["timeZone"]
    try:
        page, problems = signed_in(browser, h, "/ui/profile", "#f-time-zone")
        assert page.locator("#f-since-when").count() == 0, "asked only when it changes"
        page.select_option("#f-time-zone", "America/Denver")
        wait(page, "#f-since-when", problems)
        page.select_option("#f-time-zone", was)
        page.wait_for_selector("#f-since-when", state="detached")
        page.select_option("#f-time-zone", ZONE)
        wait(page, "#f-since-when", problems)
        today = _today(page, ZONE)
        shown = page.evaluate(
            "z => new Intl.DateTimeFormat('en-US', { timeZone: z, dateStyle: 'medium' })"
            ".format(new Date())",
            ZONE,
        )
        assert page.input_value("#f-since-when") == shown, "a move: today, where it is now"
        page.fill("#f-since-when", "")
        page.get_by_role("button", name="Save", exact=True).first.click()
        wait(page, '.field:has(#f-since-when) .err:has-text("The date it is in effect from.")',
             problems)  # fmt: skip
        assert h.c.get("/ui/api/profile").json()["timeZone"] == was, "nothing saved"
        assert [x for x in problems if "422" not in x] == []
        problems.clear()  # the refusal asked for
        page.fill("#f-since-when", today)
        page.get_by_role("button", name="Save", exact=True).first.click()
        wait(page, "text=Saved", problems)
        page.wait_for_selector("#f-since-when", state="detached")
        assert page.input_value("#f-time-zone") == ZONE
        assert h.c.get("/ui/api/profile").json()["timeZone"] == ZONE
        assert problems == []
        page.close()
    finally:
        # The shared household's admin back as they were, from yesterday (UTC) on: begun
        # already in every time zone, and replacing what this test saved.
        since = (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1)).isoformat()
        made(create(h.c, "UsrTz", True, timeZone=was, since=since))
