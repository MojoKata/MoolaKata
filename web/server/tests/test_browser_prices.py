"""Settings › Prices as an admin sees it, in headless Chromium (requirements S4.2.3, R1.6): the
symbols no price source knows are named only where the admin sees an account holding them, and
the rest are counted under the list, or under the heading alone when none is named. The view
is the server's, its unknown symbols set in the browser, so the household's records stay as
they are."""

import pytest
from browser import signed_in, wait

pytestmark = pytest.mark.browser

VTIX = {"instrumentId": "Instr_vtix", "symbol": "VTIX", "instrumentClass": "equity",
        "missedAt": "2026-10-12T22:00:00Z"}  # fmt: skip


@pytest.mark.parametrize(
    ("unknown", "elsewhere", "named", "counted"),
    [
        ([VTIX], 3, ["VTIX"], "and 3 more in accounts you don't see"),
        ([VTIX], 0, ["VTIX"], None),
        ([], 1, [], "and 1 more in accounts you don't see"),
        ([], 0, None, None),
    ],
)
def test_settings_prices_names_what_the_admin_sees_and_counts_the_rest(
    browser, household, unknown, elsewhere, named, counted
):
    def answer(route):
        got = route.fetch()
        route.fulfill(response=got, json={**got.json(), "unknown": unknown,
                                          "unknownElsewhere": elsewhere})  # fmt: skip

    page, problems = signed_in(browser, household, "/ui/", "main")
    page.route("**/ui/api/price-sources", answer)
    page.goto(household.base + "/ui/settings/prices")
    wait(page, 'label:has-text("Daily refresh at")', problems)
    heading = page.locator("main h3", has_text="Symbols No Source Knows")
    assert heading.count() == (0 if named is None else 1)
    table = page.locator("table:has(caption:has-text('Symbols no price source knows'))")
    assert table.count() == (1 if named else 0)
    if named:
        assert table.locator("tbody td b").all_inner_texts() == named
    line = page.locator("main p", has_text="in accounts you don't see")
    assert line.all_inner_texts() == ([counted] if counted else [])
    assert problems == []
    page.close()
