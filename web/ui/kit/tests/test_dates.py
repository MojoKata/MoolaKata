"""Dates and times of day (requirements S12.18.10, S12.18.11), driven on the kit's page: typed
as people write them, the calendar's keys, the focus coming back, the bounds, the marks."""

import datetime as dt

from conftest import open_page
from playwright.sync_api import expect


def field(page, demo: str):
    return page.locator(f"[data-demo='{demo}'] input")


def report(page, demo: str):
    return page.locator(f"[data-report='{demo}'] code")


def test_a_date_typed_as_people_write_it_reads_back_as_a_date(page, kit):
    open_page(page, kit, "dates")
    f = field(page, "date")
    year = dt.datetime.now(dt.UTC).year
    for typed, iso in (("10/12/2026", "2026-10-12"), ("3/4/19", "2019-03-04"),
                       ("oct 12", f"{year}-10-12"), ("12 sept 2025", "2025-09-12")):  # fmt: skip
        f.fill("")
        f.click()
        page.keyboard.type(typed)
        expect(report(page, "date")).to_have_text(f'"{iso}"')
        page.keyboard.press("Tab")
        y, m, d = map(int, iso.split("-"))
        expect(f).to_have_value(dt.date(y, m, d).strftime("%b ") + f"{d}, {y}")


def test_today_is_the_viewers_today(page, kit):
    open_page(page, kit, "dates")
    f = field(page, "date")
    f.click()
    page.keyboard.type("today")
    expect(report(page, "date")).to_have_text(f'"{dt.datetime.now(dt.UTC).date().isoformat()}"')


def test_what_doesnt_read_as_a_date_is_marked_when_left(page, kit):
    open_page(page, kit, "dates")
    f = field(page, "date")
    f.click()
    page.keyboard.type("10/45")
    expect(report(page, "date")).to_have_text('"10/45"')
    page.keyboard.press("Tab")
    expect(f).to_have_attribute("aria-invalid", "true")
    expect(f).to_have_attribute("data-tip", "Type a date, such as 10/12/2026.")
    expect(f).to_have_value("10/45")


def test_down_opens_the_calendar_on_the_fields_date_and_its_keys_move_the_day(page, kit):
    open_page(page, kit, "dates")
    f = field(page, "date-filled")
    f.click()
    page.keyboard.press("ArrowDown")
    cal = page.locator("[data-demo='date-filled'] .cal-pop")
    expect(cal).to_be_visible()
    expect(cal.locator("b")).to_have_text("October 2026")
    expect(page.locator("[data-day='2026-10-12']")).to_be_focused()
    for key, day in (("ArrowRight", "2026-10-13"), ("ArrowDown", "2026-10-20"),
                     ("ArrowLeft", "2026-10-19"), ("ArrowUp", "2026-10-12"),
                     ("Home", "2026-10-11"), ("End", "2026-10-17"),
                     ("PageDown", "2026-11-17")):  # fmt: skip
        page.keyboard.press(key)
        expect(page.locator(f"[data-day='{day}']")).to_be_focused()
    expect(cal.locator("b")).to_have_text("November 2026")
    # Six weeks whatever the month, so the grid keeps its size.
    assert cal.locator(".cal-row").count() == 7  # its weekdays and six weeks
    page.keyboard.press("Enter")
    expect(cal).to_have_count(0)
    expect(f).to_be_focused()
    expect(f).to_have_value("Nov 17, 2026")
    expect(report(page, "date-filled")).to_have_text('"2026-11-17"')


def test_escape_closes_the_calendar_and_the_focus_comes_back(page, kit):
    open_page(page, kit, "dates")
    f = field(page, "date")
    f.click()
    page.keyboard.press("Alt+ArrowDown")
    cal = page.locator("[data-demo='date'] .cal-pop")
    expect(cal).to_be_visible()
    page.keyboard.press("Escape")
    expect(cal).to_have_count(0)
    expect(f).to_be_focused()
    expect(f).to_have_value("")


def test_the_button_opens_it_and_a_click_picks_a_day(page, kit):
    open_page(page, kit, "dates")
    page.click("[data-demo='date-filled'] button[aria-label='Open the calendar']")
    page.click("[data-day='2026-10-03']")
    expect(field(page, "date-filled")).to_have_value("Oct 3, 2026")
    expect(field(page, "date-filled")).to_be_focused()


def test_days_outside_the_bounds_are_off_and_a_typed_one_is_refused(page, kit):
    open_page(page, kit, "dates")
    f = field(page, "date-bounded")
    f.click()
    page.keyboard.press("ArrowDown")
    off = page.locator("[data-day='2026-10-04']")
    expect(off).to_have_attribute("aria-disabled", "true")
    off.click(force=True)
    expect(page.locator("[data-demo='date-bounded'] .cal-pop")).to_be_visible()
    # The keys stop at the bounds.
    page.keyboard.press("PageUp")
    expect(page.locator("[data-day='2026-10-05']")).to_be_focused()
    page.keyboard.press("Escape")
    f.fill("")
    page.keyboard.type("11/1/2026")
    page.keyboard.press("Tab")
    expect(f).to_have_attribute("data-tip", "On or before Oct 25, 2026.")


def test_a_time_typed_as_people_write_it(page, kit):
    open_page(page, kit, "dates")
    f = field(page, "time")
    cases = (("530p", "17:30", "5:30 PM"), ("7:05 am", "07:05", "7:05 AM"),
             ("noon", "12:00", "12:00 PM"), ("17:30", "17:30", "5:30 PM"))  # fmt: skip
    for typed, hm, shown in cases:
        f.fill("")
        f.click()
        page.keyboard.type(typed)
        expect(report(page, "time")).to_have_text(f'"{hm}"')
        page.keyboard.press("Tab")
        expect(f).to_have_value(shown)
    f.fill("")
    f.click()
    page.keyboard.type("25:00")
    page.keyboard.press("Tab")
    expect(f).to_have_attribute("data-tip", "Type a time, such as 5:30 PM.")


def test_read(page, kit):
    open_page(page, kit, "dates")
    expect(page.locator("[data-demo='date-read'] .in.read")).to_have_text("Oct 12, 2026")
    expect(page.locator("[data-demo='time-read'] .in.read")).to_have_text("7:00 AM")


def test_the_month_buttons_move_the_calendar_and_a_click_outside_closes_it(page, kit):
    open_page(page, kit, "dates")
    page.click("[data-demo='date-filled'] button[aria-label='Open the calendar']")
    cal = page.locator("[data-demo='date-filled'] .cal-pop")
    page.click("[data-demo='date-filled'] button[aria-label='Next month']")
    expect(cal.locator("b")).to_have_text("November 2026")
    page.click("[data-demo='date-filled'] button[aria-label='Previous month']")
    page.click("[data-demo='date-filled'] button[aria-label='Previous month']")
    expect(cal.locator("b")).to_have_text("September 2026")
    page.click(".kit-page h1")
    expect(cal).to_have_count(0)
    # The button closes what it opened.
    b = page.locator("[data-demo='date'] button[aria-label='Open the calendar']")
    b.click()
    expect(page.locator("[data-demo='date'] .cal-pop")).to_be_visible()
    b.click()
    expect(page.locator("[data-demo='date'] .cal-pop")).to_have_count(0)


def test_a_time_is_picked_from_the_list_by_the_keys_or_the_pointer(page, kit):
    open_page(page, kit, "dates")
    f = field(page, "time-filled")
    f.click()
    page.keyboard.press("ArrowDown")
    expect(f).to_have_attribute("aria-expanded", "true")
    # On the field's time: 5:30 PM, every 15 minutes.
    active = f.get_attribute("aria-activedescendant")
    expect(page.locator(f"#{active}")).to_have_text("5:30 PM")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(f).to_have_value("5:45 PM")
    expect(report(page, "time-filled")).to_have_text('"17:45"')
    expect(f).to_have_attribute("aria-expanded", "false")
    expect(f).to_be_focused()
    # The clock button lists them too; a click picks one; Escape closes without a pick.
    page.click("[data-demo='time'] button[aria-label='List the times']")
    page.click("[data-demo='time'] [role='option']:has-text('12:15 AM')")
    expect(field(page, "time")).to_have_value("12:15 AM")
    expect(report(page, "time")).to_have_text('"00:15"')
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Escape")
    expect(field(page, "time")).to_have_attribute("aria-expanded", "false")
    expect(field(page, "time")).to_have_value("12:15 AM")
