"""Numbers as they are typed (requirements S12.18.8, S12.18.9), driven through the keyboard on
the kit's numbers page: dollars from the cents, quantities as written, the caret kept by its
digits, a paste read whole, and what each way of holding a number reports."""

from conftest import open_page
from playwright.sync_api import expect


def field(page, demo: str):
    return page.locator(f"[data-demo='{demo}'] input")


def report(page, demo: str):
    return page.locator(f"[data-report='{demo}'] code")


def caret(f) -> int:
    return f.evaluate("e => e.selectionStart")


def test_an_amount_comes_in_from_the_cents(page, kit):
    open_page(page, kit, "numbers")
    f = field(page, "amount")
    f.click()
    for key, shown in (("1", "0.01"), ("2", "0.12"), ("3", "1.23"), ("4", "12.34"),
                       ("5", "123.45"), ("6", "1,234.56")):  # fmt: skip
        page.keyboard.press(key)
        expect(f).to_have_value(shown)
    expect(report(page, "amount")).to_have_text('"1234.56"')
    assert caret(f) == len("1,234.56"), "the caret stays at the end"
    page.keyboard.press(".")
    expect(f).to_have_value("1,234.56")
    page.keyboard.press("Backspace")
    expect(f).to_have_value("123.45")
    page.keyboard.press("-")
    expect(f).to_have_value("-123.45")
    expect(report(page, "amount")).to_have_text('"-123.45"')
    page.keyboard.press("-")
    expect(f).to_have_value("123.45")


def test_the_dollar_sign_is_in_the_field_and_not_in_its_value(page, kit):
    open_page(page, kit, "numbers")
    unit = page.locator("[data-demo='amount'] .unit.pre")
    expect(unit).to_have_text("$")
    assert unit.get_attribute("aria-hidden") == "true"
    # A click on the unit is the field's.
    unit.click(force=True)
    page.keyboard.press("7")
    expect(field(page, "amount")).to_have_value("0.07")
    expect(report(page, "amount")).to_have_text('"0.07"')


def test_a_paste_is_read_as_a_whole_amount(page, kit):
    open_page(page, kit, "numbers")
    f = field(page, "amount")
    f.click()
    f.evaluate(
        """(e, text) => {
            const data = new DataTransfer();
            data.setData('text/plain', text);
            e.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true,
              cancelable: true }));
        }""",
        "$1,234.5",
    )
    expect(f).to_have_value("1,234.50")
    expect(report(page, "amount")).to_have_text('"1234.50"')
    # A letter is refused and marked with what the field takes.
    page.keyboard.press("x")
    expect(f).to_have_value("1,234.50")
    expect(f).to_have_attribute("data-tip", "Digits, . and - only.")


def test_typed_as_written_the_commas_appear_and_the_caret_keeps_its_digits(page, kit):
    open_page(page, kit, "numbers")
    f = field(page, "quantity")
    f.click()
    page.keyboard.type("1234567")
    expect(f).to_have_value("1,234,567")
    expect(report(page, "quantity")).to_have_text('"1234567"')
    # Into the middle: after "1,23" (four digits to the caret's right stay to its right).
    f.evaluate("e => e.setSelectionRange(4, 4)")
    page.keyboard.press("9")
    expect(f).to_have_value("12,394,567")
    assert caret(f) == 5, "the caret stays before the same four digits"
    # Backspace just after a comma takes the digit before it.
    f.evaluate("e => e.setSelectionRange(3, 3)")
    page.keyboard.press("Backspace")
    expect(f).to_have_value("1,394,567")
    # A minus is no quantity's here: refused and marked.
    page.keyboard.press("-")
    expect(f).to_have_value("1,394,567")
    expect(f).to_have_attribute("data-tip", "Digits and . only.")


def test_leaving_a_field_typed_as_written_pads_its_places(page, kit):
    open_page(page, kit, "numbers")
    f = field(page, "amount-natural")
    f.click()
    page.keyboard.type("1234.5")
    expect(f).to_have_value("1,234.5")
    page.keyboard.press("Tab")
    expect(f).to_have_value("1,234.50")
    expect(report(page, "amount-natural")).to_have_text('"1234.50"')


def test_bounds_fill_in_and_refuse(page, kit):
    open_page(page, kit, "numbers")
    f = field(page, "amount-bounded")
    page.click("[data-demo='amount-bounded'] button:has-text('Max')")
    expect(f).to_have_value("500.00")
    f.click()
    page.keyboard.press("0")
    expect(f).to_have_value("5,000.00")
    page.keyboard.press("Tab")
    expect(f).to_have_attribute("aria-invalid", "true")
    assert "or less" in (f.get_attribute("data-tip") or "")


def test_off_and_read(page, kit):
    open_page(page, kit, "numbers")
    expect(field(page, "off")).to_be_disabled()
    read = page.locator("[data-demo='read'] .in.read")
    expect(read).to_have_text("$1,234.50")
    assert read.get_attribute("tabindex") == "0", "a read value is reached by Tab"


def test_each_way_of_holding_a_number_reports_what_it_holds(page, kit):
    open_page(page, kit, "numbers")
    f = field(page, "held-number")
    f.click()
    page.keyboard.type("12.5")
    expect(report(page, "held-number")).to_have_text("12.5")
    page.keyboard.type("1234567890123")
    expect(f).to_have_attribute("data-tip", "At most 15 digits.")
    # Cents: a BigInt of the smallest unit.
    cents = field(page, "held-minor")
    expect(cents).to_have_value("1,234.56")
    cents.click()
    page.keyboard.press("7")
    expect(report(page, "held-minor")).to_have_text("1234567n")
    # Bitcoin held in BTC, shown and typed in sats.
    sats = field(page, "btc-in-sats")
    expect(sats).to_have_value("12,345,678")
    sats.click()
    page.keyboard.press("End")
    page.keyboard.press("9")
    expect(sats).to_have_value("123,456,789")
    expect(report(page, "btc-in-sats")).to_have_text('"1.23456789"')
    # Bitcoin held in sats, shown and typed in BTC.
    btc = field(page, "sats-in-btc")
    expect(btc).to_have_value("0.12345678")
    btc.select_text()
    page.keyboard.type("1.5")
    expect(report(page, "sats-in-btc")).to_have_text("150000000n")
