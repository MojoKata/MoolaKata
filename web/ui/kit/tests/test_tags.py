"""Several of a list (requirements S12.18.12), driven through the keyboard and the pointer on the
kit's page: matches listed as typed, the arrows and Enter, a comma, Backspace, Escape, new names
where the list may grow and refused where it can't, the focus after a chip goes, and many chips
in rows or on one line behind a count."""

from conftest import open_page
from playwright.sync_api import expect


def box(page, demo: str):
    return page.locator(f"[data-demo='{demo}'] .tag-box input")


def chips(page, demo: str) -> list[str]:
    return page.locator(f"[data-demo='{demo}'] .tag .tag-name").all_inner_texts()


def report(page, demo: str):
    return page.locator(f"[data-report='{demo}'] code")


def options(page, demo: str) -> list[str]:
    found = page.locator(f"[data-demo='{demo}'] [role='option']").all_inner_texts()
    return [t.split("\n")[0] for t in found]


def test_typing_lists_the_matches_best_first_and_enter_adds_the_one_reached(page, kit):
    open_page(page, kit, "tags")
    b = box(page, "tags")
    b.click()
    page.keyboard.type("wo")
    expect(b).to_have_attribute("aria-expanded", "true")
    # The start of the name first, in the order given; then a new one may be made.
    assert options(page, "tags") == ["work", "work trips", "woodworking", "Make the tag “wo”"]
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    active = b.get_attribute("aria-activedescendant")
    assert active and page.locator(f"#{active}").inner_text().startswith("work trips")
    page.keyboard.press("Enter")
    assert chips(page, "tags") == ["work trips"]
    expect(report(page, "tags")).to_have_text('["work trips"]')
    expect(b).to_be_focused()
    expect(b).to_have_value("")


def test_nothing_typed_lists_the_most_used_first(page, kit):
    open_page(page, kit, "tags")
    box(page, "tags").click()
    page.keyboard.press("ArrowDown")
    assert options(page, "tags")[:3] == ["work", "coffee", "2026"]


def test_a_comma_adds_what_is_typed_and_a_new_name_is_made(page, kit):
    open_page(page, kit, "tags")
    b = box(page, "tags")
    b.click()
    page.keyboard.type("Coffee,")
    page.keyboard.type("road trip")
    page.keyboard.press("Enter")
    # Case aside, an item there is the item; a name that matches none is made.
    assert chips(page, "tags") == ["coffee", "road trip"]
    expect(report(page, "tags")).to_have_text('["coffee","road trip"]')
    # Typed again, it isn't added twice.
    page.keyboard.type("COFFEE,")
    assert chips(page, "tags") == ["coffee", "road trip"]


def test_a_paste_of_names_adds_each(page, kit):
    open_page(page, kit, "tags")
    b = box(page, "tags")
    b.click()
    page.keyboard.insert_text("medical, gifts, 2026")
    assert chips(page, "tags") == ["medical", "gifts"]
    expect(b).to_have_value("2026")


def test_backspace_in_the_empty_box_takes_off_the_last_chip(page, kit):
    open_page(page, kit, "tags")
    b = box(page, "tags-filled")
    b.click()
    page.keyboard.press("Backspace")
    assert chips(page, "tags-filled") == ["work"]
    expect(report(page, "tags-filled")).to_have_text('["work"]')


def test_escape_closes_the_list_and_goes_no_further(page, kit):
    open_page(page, kit, "tags")
    b = box(page, "tags")
    b.click()
    page.keyboard.type("w")
    expect(b).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Escape")
    expect(b).to_have_attribute("aria-expanded", "false")
    expect(b).to_have_value("w")


def test_a_chip_removed_leaves_the_focus_in_the_box(page, kit):
    open_page(page, kit, "tags")
    page.click("[data-demo='tags-filled'] button[aria-label='Remove work']")
    assert chips(page, "tags-filled") == ["coffee"]
    expect(box(page, "tags-filled")).to_be_focused()
    expect(page.locator("[data-demo='tags-filled'] [role='status']")).to_have_text("Removed work")


def test_people_are_picked_only_and_a_name_matching_none_is_refused(page, kit):
    open_page(page, kit, "tags")
    b = box(page, "people")
    b.click()
    page.keyboard.type("zz")
    expect(page.locator("[data-demo='people'] .tag-list .none")).to_have_text("No match")
    page.keyboard.press("Enter")
    expect(b).to_have_attribute("aria-invalid", "true")
    expect(b).to_have_attribute("data-tip", "No match.")
    assert chips(page, "people") == ["Emma Griffin"]
    b.fill("")
    page.keyboard.type("noah")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert chips(page, "people") == ["Emma Griffin", "Noah Griffin"]


def test_many_chips_grow_to_three_rows_and_then_scroll(page, kit):
    open_page(page, kit, "tags")
    tags = page.locator("[data-demo='many'] .tag-box")
    h = tags.evaluate("e => [e.clientHeight, e.scrollHeight]")
    assert h[0] < h[1], "past three rows it scrolls"
    rows = tags.evaluate(
        "e => new Set([...e.querySelectorAll('.tag')].filter((t) => t.offsetTop < e.clientHeight)"
        ".map((t) => t.offsetTop)).size"
    )
    assert rows == 3


def test_one_line_counts_the_chips_out_of_sight_and_goes_back_to_the_first(page, kit):
    open_page(page, kit, "tags")
    b = box(page, "one-line")
    before = page.locator("[data-demo='one-line'] .before")
    expect(before).to_have_count(0)
    b.click()
    expect(before).to_be_visible()
    n = int(before.inner_text().strip())
    assert n > 0
    assert before.get_attribute("aria-label") == f"{n} tags before"
    before.click()
    expect(before).to_have_count(0)


def test_off_and_read(page, kit):
    open_page(page, kit, "tags")
    expect(box(page, "tags-off")).to_be_disabled()
    expect(page.locator("[data-demo='tags-read'] .in.read")).to_have_text("work, medical")
