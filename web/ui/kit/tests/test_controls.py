"""The kit's other controls (requirements S12.18.6, S12.19, S12.15.6, S12.16), driven on their
pages: a list, a switch, a switch off saying why, a count with All, a value's × and ↺, an action
off, a dialog that asks before losing changes and one over it, the question before a delete, a
menu, the pager; and the theme's tokens and icons."""

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
    page.click("button:has-text('Yes, delete')")
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
