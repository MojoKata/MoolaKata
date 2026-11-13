"""The kit's other controls (requirements S12.18.6, S12.19, S12.15.6, S12.16), driven on their
pages: a list, a switch, a switch off saying why, a count with All, a value's × and ↺, an action
off, a dialog that asks before losing changes and one over it, the question before a delete, a
menu, the pager; and the theme's tokens and icons."""

import itertools
import re

import pytest
from conftest import open_page
from playwright.sync_api import expect


def report(page, demo: str):
    return page.locator(f"[data-report='{demo}'] code")


def test_a_list_takes_its_choice_and_reads_as_its_words(page, kit):
    open_page(page, kit, "fields")
    s = page.locator("[data-demo='select'] select")
    s.select_option("savings")
    expect(report(page, "select")).to_have_text('"savings"')
    expect(page.locator("[data-demo='select-read'] .in.read")).to_have_text("Roth IRA")


def test_a_switch_turns_over_and_one_off_says_why(page, kit):
    open_page(page, kit, "fields")
    sw = page.locator("[data-demo='switch'] [role='switch']")
    sw.focus()
    page.keyboard.press("Space")
    expect(sw).to_have_attribute("aria-checked", "true")
    expect(report(page, "switch")).to_have_text("true")
    off = page.locator("[data-demo='switch-off'] [role='switch']")
    off.focus()
    page.keyboard.press("Space")
    expect(off).to_have_attribute("aria-checked", "true")
    expect(off).to_have_attribute("aria-description", "Only its owner changes it.")
    expect(page.locator(".tooltip")).to_have_text("Only its owner changes it.")


def test_a_count_fills_in_all_and_a_value_clears_and_resets(page, kit):
    open_page(page, kit, "fields")
    page.click("[data-demo='count'] button:has-text('All')")
    expect(report(page, "count")).to_have_text('"5"')
    page.click("[data-demo='value'] button[aria-label='Clear']")
    expect(report(page, "value")).to_have_text('""')
    page.click("[data-demo='value'] button[aria-label='Use the default: 30 days']")
    expect(report(page, "value")).to_have_text('"30"')
    expect(page.locator("[data-demo='value'] .unit.post")).to_have_text("days")


def test_a_refusal_is_at_its_field(page, kit):
    open_page(page, kit, "fields")
    err = page.locator("[data-demo='field-error'] .err")
    expect(err).to_have_attribute("role", "alert")
    described = "f-field-error-err"
    expect(page.locator("#f-field-error")).to_have_attribute("aria-describedby", described)


def test_an_action_off_is_reached_and_does_nothing(page, kit):
    open_page(page, kit, "state")
    off = page.locator("[data-demo='actions'] button:has-text('Delete')")
    expect(off).to_have_attribute("aria-disabled", "true")
    off.click(force=True)
    expect(report(page, "actions")).to_have_text("nothing yet")
    page.click("[data-demo='actions'] button[aria-label='Edit Whole Foods']")
    expect(report(page, "actions")).to_have_text('"Edit Whole Foods"')


def test_a_dialog_asks_before_its_changes_go_and_gives_the_focus_back(page, kit):
    open_page(page, kit, "overlays")
    opener = page.locator("[data-demo='dialog'] button")
    opener.click()
    note = page.locator(".dialog #f-note")
    expect(note).to_be_focused()
    page.keyboard.type("x")
    page.keyboard.press("Escape")
    expect(page.locator("text=Save your changes?")).to_be_visible()
    page.click(".dialog-ask-buttons button:has-text('Keep editing')")
    expect(note).to_have_value("x")
    # One opened over it: the one beneath waits, and is back as it was.
    page.click(".dialog button:has-text('Open one over it')")
    expect(page.locator(".dialog")).to_have_count(2)
    expect(page.locator(".dialog-layer").last.locator("input")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator(".dialog")).to_have_count(1)
    expect(page.locator(".dialog button:has-text('Open one over it')")).to_be_focused()
    page.click(".dialog button[data-cancel]")
    page.click(".dialog-ask-buttons button:has-text('Discard')")
    expect(page.locator(".dialog")).to_have_count(0)
    expect(opener).to_be_focused()


def test_the_question_before_a_delete_has_no_as_its_default(page, kit):
    open_page(page, kit, "overlays")
    page.click("[data-demo='confirm'] button")
    expect(page.locator("text=Delete this rule?")).to_be_visible()
    expect(page.locator(".dialog-ask-buttons button:has-text('No')")).to_be_focused()
    page.keyboard.press("Enter")
    expect(report(page, "confirm")).to_have_text("false")
    page.click("[data-demo='confirm'] button")
    page.click(".dialog-ask-buttons button:text-is('Yes')")
    expect(report(page, "confirm")).to_have_text("true")


def test_a_menu_opens_under_its_button_and_gives_the_focus_back(page, kit):
    open_page(page, kit, "overlays")
    b = page.locator("[data-demo='menu'] button")
    b.click()
    page.click(".menu button:has-text('Export CSV')")
    expect(report(page, "menu")).to_have_text('"Export CSV"')
    expect(b).to_be_focused()


def test_the_pager_moves_and_its_size_changes(page, kit):
    open_page(page, kit, "overlays")
    page.click("[data-demo='pager'] button[aria-label='Next page']")
    expect(report(page, "pager")).to_have_text("2")
    page.locator("[data-demo='pager'] select").select_option("500")
    expect(report(page, "pager")).to_have_text("1")
    page.click("[data-demo='pager'] .pill.new")
    expect(report(page, "pager")).to_have_text("1")


def test_the_theme_lists_its_tokens_and_icons(page, kit):
    open_page(page, kit, "theme")
    expect(page.locator(".token code", has_text="--accent").first).to_be_visible()
    expect(page.locator(".glyph code", has_text="calendar")).to_be_visible()


def test_a_secret_is_text_drawn_blurred_and_its_eye_shows_it(page, kit):
    open_page(page, kit, "fields")
    f = page.locator("#f-secret")
    # Plain text, so no password manager offers or fills it; blurred until shown.
    assert f.get_attribute("type") == "text"
    assert f.get_attribute("autocomplete") == "off"
    assert f.get_attribute("data-1p-ignore") == "true"
    f.fill("sk-live-123")
    expect(f).to_have_class(re.compile(r"\bveiled\b"))
    page.click("[data-demo='secret'] button[aria-label='Show it']")
    expect(f).not_to_have_class(re.compile(r"\bveiled\b"))
    expect(f).to_have_value("sk-live-123")
    page.click("[data-demo='secret'] button[aria-label='Hide it']")
    expect(f).to_have_class(re.compile(r"\bveiled\b"))


def test_the_question_is_yes_or_no_and_nothing_more(page, kit):
    open_page(page, kit, "overlays")
    page.click("[data-demo='confirm'] button")
    buttons = page.locator(".dialog-ask-buttons button")
    expect(buttons).to_have_text(["Yes", "No"])
    box = page.locator(".dialog-ask-box")
    assert box.evaluate("e => getComputedStyle(e).backgroundColor") != "rgba(0, 0, 0, 0)"
    yes, no = (b.bounding_box() for b in buttons.all())
    assert no["x"] > yes["x"] + yes["width"], "at the right, a gap between them"
    page.keyboard.press("Escape")


def test_a_toast_slides_up_and_back_down(page, kit):
    open_page(page, kit, "overlays")
    page.click("[data-demo='toast'] button:has-text('Save')")
    t = page.locator(".toast")
    expect(t).to_have_text("Saved")
    assert t.evaluate("e => getComputedStyle(e).animationName") == "toast-in"
    expect(page.locator(".toast.leaving")).to_have_count(1, timeout=6000)
    assert (
        page.locator(".toast.leaving").evaluate("e => getComputedStyle(e).animationName")
        == "toast-out"
    )
    expect(t).to_have_count(0, timeout=3000)


def test_a_secret_shows_nothing_of_itself_until_its_eye(page, kit):
    open_page(page, kit, "fields")
    f = page.locator("#f-secret")
    f.fill("sk-live-123")
    assert f.evaluate("e => getComputedStyle(e).webkitTextSecurity") == "disc"


def test_the_words_and_clear_hand_the_focus_to_the_field(page, kit):
    open_page(page, kit, "numbers")
    f = page.locator("[data-demo='amount-bounded'] input")
    page.click("[data-demo='amount-bounded'] button:has-text('max')")
    expect(f).to_be_focused()
    expect(f).to_have_value("500.00")
    page.click("[data-demo='amount-bounded'] button:has-text('min')")
    expect(f).to_be_focused()
    open_page(page, kit, "fields")
    v = page.locator("[data-demo='value'] input")
    page.click("[data-demo='value'] button[aria-label='Clear']")
    expect(v).to_be_focused()
    page.click("[data-demo='value'] button:has-text('default')")
    expect(v).to_be_focused()


def test_a_pick_from_any_list_leaves_the_focus_in_its_field(page, kit):
    open_page(page, kit, "tags")
    b = page.locator("[data-demo='tags'] .tag-box input")
    b.click()
    page.keyboard.press("ArrowDown")
    page.locator("[data-demo='tags'] [role='option']").first.click()
    expect(b).to_be_focused()
    page.locator("[data-demo='tags'] .tag button").first.click()
    expect(b).to_be_focused()
    open_page(page, kit, "dates")
    page.click("[data-demo='date'] button[aria-label='Open the calendar']")
    page.locator("[data-demo='date'] .cal-row button").nth(3).click()
    expect(page.locator("[data-demo='date'] input")).to_be_focused()
    page.click("[data-demo='time'] button[aria-label='Choose a time']")
    page.locator("[data-demo='time'] [data-time='09:15']").click()
    expect(page.locator("[data-demo='time'] input")).to_be_focused()
    assert page.evaluate("document.activeElement !== document.body")


def test_stacked_dialogs_darken_the_page_once(page, kit):
    open_page(page, kit, "overlays")
    page.click("[data-demo='dialog'] button")
    page.click(".dialog button:has-text('Open one over it')")
    expect(page.locator(".dialog")).to_have_count(2)
    expect(page.locator(".dialog-layer").last.locator("input")).to_be_focused()
    scrims = page.locator(".scrim")
    bg = [s.evaluate("e => getComputedStyle(e).backgroundColor") for s in scrims.all()]
    assert bg[0] == "rgba(0, 0, 0, 0)" and bg[1] != "rgba(0, 0, 0, 0)", bg
    page.keyboard.press("Escape")
    expect(page.locator(".dialog")).to_have_count(1)
    assert scrims.first.evaluate("e => getComputedStyle(e).backgroundColor") != "rgba(0, 0, 0, 0)"
    page.keyboard.press("Escape")


def test_a_small_count_steps_within_its_bounds(page, kit):
    open_page(page, kit, "fields")
    f = page.locator("#f-spin")
    assert f.get_attribute("role") == "spinbutton"
    up = page.locator("[data-demo='spin'] button.up")
    down = page.locator("[data-demo='spin'] button.down")
    up.click()
    expect(f).to_have_value("4")
    expect(f).to_be_focused()
    expect(page.locator("[data-report='spin'] code")).to_have_text('"4"')
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    expect(f).to_have_value("2")
    page.keyboard.press("PageUp")
    expect(f).to_have_value("12")
    expect(up).to_be_disabled()
    page.keyboard.press("PageDown")
    expect(f).to_have_value("2")
    down.click()
    expect(f).to_have_value("1")
    expect(down).to_be_disabled()
    f.fill("")
    up.click()
    expect(f).to_have_value("1")
    expect(page.locator("[data-demo='spin-read'] .in.read")).to_have_text("20")


def _apart(a, b) -> bool:
    """Two boxes that don't overlap."""
    return a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]


@pytest.mark.parametrize(
    ("demo", "other", "cleared"),
    [
        ("password-clear", ".pw > .icon-btn", ""),
        ("secret-clear", ".pw > .icon-btn", ""),
        ("select-clear", None, ""),
        ("spin-clear", ".spin-btns", ""),
        ("spin-unit-clear", ".unit.post", ""),
        ("value", ".unit.post", ""),
    ],
)
def test_clear_sits_beside_the_fields_other_tools_and_hands_back_the_focus(
    page, kit, demo, other, cleared
):
    open_page(page, kit, "fields")
    d = f"[data-demo='{demo}']"
    x = page.locator(f"{d} button[aria-label='Clear']")
    box = x.bounding_box()
    if other:
        assert _apart(box, page.locator(f"{d} {other}").first.bounding_box()), "× clear of it"
    if demo == "spin-unit-clear":
        assert _apart(
            page.locator(f"{d} .unit.post").bounding_box(),
            page.locator(f"{d} .spin-btns").bounding_box(),
        ), "the unit clear of the chevrons"
    field = page.locator(f"{d} input, {d} select").first
    if demo == "select-clear":
        # Left of the list's chevron, drawn at its end inside the list's padding.
        f = field.bounding_box()
        pad, chev = field.evaluate(
            "e => [getComputedStyle(e).paddingRight, getComputedStyle(e, '::picker-icon').width]"
            ".map(parseFloat)"
        )
        assert box["x"] + box["width"] <= f["x"] + f["width"] - pad - chev
    x.click()
    expect(field).to_be_focused()
    expect(field).to_have_value(cleared)
    expect(x).to_have_count(0)


def test_tabs_choose_in_place_and_cross_fade(page, kit):
    open_page(page, kit, "state")
    tabs = page.locator("[data-demo='tabs'] .tab")
    tabs.nth(2).click()
    expect(page).to_have_url(re.compile(r"#state$"))
    expect(tabs.nth(2)).to_have_class(re.compile(r"\bon\b"))
    expect(page.locator("[data-report='tabs'] code")).to_have_text("numbers")
    assert "background-color" in tabs.first.evaluate("e => getComputedStyle(e).transitionProperty")
    assert tabs.first.evaluate("e => getComputedStyle(e).textDecorationLine") == "none"
    # Chips cross-fade the same way.
    fade = page.locator("[data-demo='chips'] .chip").first.evaluate(
        "e => getComputedStyle(e).transitionProperty"
    )
    assert "background-color" in fade


def test_the_pager_marks_its_gaps(page, kit):
    open_page(page, kit, "overlays")
    jump = page.locator("[data-demo='pager'] .jump")
    # 24 pages from page 1: 1 2 3 · 11 · 23 24.
    expect(jump.locator("button[aria-label^='Page']")).to_have_text(
        ["1", "2", "3", "11", "23", "24"]
    )
    expect(jump.locator(".sep")).to_have_count(2)
    fade = jump.locator("button").first.evaluate("e => getComputedStyle(e).transitionProperty")
    assert "background-color" in fade


def test_dialogs_stack_three_deep_each_narrower_and_taller_and_close_one_at_a_time(page, kit):
    open_page(page, kit, "overlays")
    page.click("[data-demo='dialog'] button")
    for depth in (1, 2):
        expect(page.locator(".dialog-layer").last.locator("input")).to_be_focused()
        page.locator(".dialog-layer").last.locator("button:has-text('Open one over it')").click()
        expect(page.locator(".dialog")).to_have_count(depth + 1)
    expect(page.locator(".dialog-layer").last.locator("input")).to_be_focused()
    boxes = [d.bounding_box() for d in page.locator(".dialog").all()]
    for under, over in itertools.pairwise(boxes):
        assert over["width"] < under["width"] and over["height"] > under["height"]
    bg = [
        s.evaluate("e => getComputedStyle(e).backgroundColor") for s in page.locator(".scrim").all()
    ]
    assert bg[:2] == ["rgba(0, 0, 0, 0)"] * 2 and bg[2] != "rgba(0, 0, 0, 0)"
    # Back takes the top one alone, and each Escape the next; none takes two.
    page.go_back()
    expect(page.locator(".dialog")).to_have_count(2)
    for depth in (1, 0):
        expect(page.locator(".dialog-layer").last.locator(":focus")).to_have_count(1)
        page.keyboard.press("Escape")
        expect(page.locator(".dialog")).to_have_count(depth)
        page.wait_for_timeout(200)
        expect(page.locator(".dialog")).to_have_count(depth)
