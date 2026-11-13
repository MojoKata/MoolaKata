"""Clicking on everything (requirements S17.5.13): on each of the kit's pages, every control in
every card is clicked, and points across each card, the page answering after each click and
whatever opened closed again. A page that crashes, stops answering, or reports an error fails.
"""

import pytest
from conftest import PAGES_IN_ORDER, open_page
from playwright.sync_api import Error

# What a person clicks: controls, chips, the boxes they sit in, labels, options. Links are left
# out: they go to another page of the kit, which its own run clicks through.
TARGETS = "button, input, select, textarea, [tabindex], .tag, .tag-box, label, li, .unit"
POINTS = [(x / 10, y / 10) for x in (1, 3, 5, 7, 9) for y in (3, 6, 9)]


def settle(page) -> None:
    """Whatever a click opened, closed: a question answered No, a dialog left, a menu shut."""
    for _ in range(3):
        page.keyboard.press("Escape")
    for sel in (
        ".dialog-ask-buttons button:has-text('Discard')",
        ".dialog-ask-buttons button:has-text('No')",
    ):
        b = page.locator(sel)
        if b.count():
            b.first.click(force=True, timeout=1000)
    page.keyboard.press("Escape")


@pytest.mark.parametrize("width", [1440, 1180, 980])
@pytest.mark.parametrize("name", PAGES_IN_ORDER)
def test_clicking_everything_breaks_nothing(page, kit, name, width):
    # Layout moves with the window: a control that only misbehaves at one width shows here.
    page.set_viewport_size({"width": width, "height": 900})
    open_page(page, kit, name)
    crashed = []
    page.on("crash", lambda *_: crashed.append(name))
    demos = page.locator(".kit-page .demo")
    for i in range(demos.count()):
        demo = demos.nth(i)
        targets = demo.locator(TARGETS)
        for j in range(min(targets.count(), 60)):
            t = targets.nth(j)
            try:
                if t.is_visible():
                    t.click(force=True, timeout=1000, no_wait_after=True)
            except Error:
                pass  # gone by now: a chip removed, a list closed
            assert page.title(), "the page answers"
        box = demo.bounding_box()
        if box:
            for fx, fy in POINTS:
                page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
                assert page.title(), "the page answers"
        settle(page)
    assert crashed == []
    assert page.locator(".kit-page h1").is_visible()


@pytest.mark.parametrize("width", [1440, 1180, 980])
@pytest.mark.parametrize("name", PAGES_IN_ORDER)
def test_scrolling_everything_breaks_nothing(page, kit, name, width):
    """Every part of a card that scrolls is scrolled across a few pixels at a time, the page
    answering after each step: a control that redraws as it scrolls (a count of what is out of
    sight) and moves what it counts would loop here and stop the page."""
    page.set_viewport_size({"width": width, "height": 900})
    page.set_default_timeout(5000)
    open_page(page, kit, name)
    scrollers = page.locator(".kit-page .demo *").evaluate_all(
        """(els) => els.map((e, i) => [i, e.scrollWidth - e.clientWidth,
            e.scrollHeight - e.clientHeight]).filter(([, w, h]) => w > 4 || h > 4)"""
    )
    every = page.locator(".kit-page .demo *")
    for i, w, h in scrollers:
        el = every.nth(i)
        far = max(w, h)
        # Fine over the first stretch, where a loop shows; then in at most a hundred steps, so a
        # long note's text doesn't take thousands.
        steps = [*range(0, min(far, 150) + 1, 3), *range(150, far + 1, max(3, far // 100)), far]
        for step in steps:
            el.evaluate(f"e => {{ e.scrollLeft = {min(step, w)}; e.scrollTop = {min(step, h)}; }}")
        assert page.title(), "the page answers"
