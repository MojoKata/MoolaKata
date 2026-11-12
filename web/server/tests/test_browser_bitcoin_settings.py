"""Settings › Bitcoin in headless Chromium (requirements S16.7, CR3-62): no wallet is read
until an admin saves the section, so its first Save writes the source even at the suggested
default, and until then the section says it isn't saved. A server of its own, with no wallet,
so nothing is ever read from an explorer."""

import pytest
from browser import PASSWORD, client, made, open_page, save, stop, unlocked, wait

pytestmark = pytest.mark.browser

FORM = 'form.card:has-text("Test asks")'
UNSAVED = "text=Not saved yet: no wallet is read until you save this section."


def test_the_first_save_writes_the_source_and_a_saved_section_saves_nothing(tmp_path, browser):
    base, proc = unlocked(tmp_path)
    try:
        c = client(base)
        made(
            c.post(
                "/ui/api/welcome/admin",
                json={"password": PASSWORD, "email": "admin@home.lan", "displayName": "Admin",
                      "sex": "female"},
            )
        )  # fmt: skip
        page, problems = open_page(browser, base + "/ui/")
        r = page.request.post(
            base + "/ui/api/session",
            data={"login": "admin", "password": PASSWORD},
            headers={"Origin": base},
        )
        assert r.ok, r.text()

        def settings() -> dict:
            return c.get("/ui/api/settings").json()

        def save_untouched() -> None:
            page.click(f"{FORM} button.primary:enabled")
            wait(page, ".toast", problems)
            page.locator(".toast").first.wait_for(state="detached", timeout=30_000)

        # Untouched, at the suggested mempool.space: the source alone is written.
        before = settings()
        page.goto(base + "/ui/settings/bitcoin")
        wait(page, UNSAVED, problems)
        save_untouched()
        after = settings()
        assert set(after["records"]) - set(before["records"]) == {"bitcoinSource"}
        assert after["values"] == before["values"], "written at the value it stood at"
        wait(page, f'{FORM} .notice:has-text("Checked every hour")', problems)
        assert page.locator(UNSAVED).count() == 0

        # Saved, then saved untouched again: nothing changes (CR3-2).
        save_untouched()
        assert settings() == after

        # Back to unsaved, then Blockstream picked: a URL alone would leave the source at its
        # default, and the source is written all the same.
        ref = after["records"]["bitcoinSource"]
        made(save(c, [{"op": "delete", "entity": "Setng", "id": ref["id"],
                       "version": ref["version"]}]))  # fmt: skip
        page.reload()
        wait(page, UNSAVED, problems)
        page.get_by_label("Explorer or node").select_option("blockstream")
        save_untouched()
        got = settings()
        assert "bitcoinSource" in got["records"] and got["values"]["bitcoinSource"] == "esplora"
        assert got["values"]["bitcoinEsploraUrl"] == "https://blockstream.info/api"
        assert problems == []
        page.close()
    finally:
        stop(proc)


# Each own node, as its form is filled: the field set (by its id), and what the first Save
# must write.
OWN_NODES = [
    ("esplora", "#f-esplora-url", "http://192.168.1.20:3000/api",
     {"bitcoinSource": "esplora", "bitcoinEsploraUrl": "http://192.168.1.20:3000/api"}),
    ("electrum", "#f-node-host", "192.168.1.20",
     {"bitcoinSource": "electrum", "bitcoinNodeHost": "192.168.1.20"}),
    ("core", "#f-node-host", "192.168.1.21",
     {"bitcoinSource": "core", "bitcoinNodeHost": "192.168.1.21"}),
]  # fmt: skip


def test_the_first_save_of_an_own_node_writes_its_source_and_address(tmp_path, browser):
    """CR3-62 across the sources: whichever own node is chosen, the section's first Save
    writes the source with its address, and the section stops saying it isn't saved."""
    base, proc = unlocked(tmp_path)
    try:
        c = client(base)
        made(
            c.post(
                "/ui/api/welcome/admin",
                json={"password": PASSWORD, "email": "admin@home.lan", "displayName": "Admin",
                      "sex": "female"},
            )
        )  # fmt: skip
        page, problems = open_page(browser, base + "/ui/")
        r = page.request.post(
            base + "/ui/api/session",
            data={"login": "admin", "password": PASSWORD},
            headers={"Origin": base},
        )
        assert r.ok, r.text()
        for node, field, value, want in OWN_NODES:
            got = c.get("/ui/api/settings").json()
            if "bitcoinSource" in got["records"]:
                ref = got["records"]["bitcoinSource"]
                made(save(c, [{"op": "delete", "entity": "Setng", "id": ref["id"],
                               "version": ref["version"]}]))  # fmt: skip
            page.goto(base + "/ui/settings/bitcoin")
            wait(page, UNSAVED, problems)
            page.get_by_label("Explorer or node").select_option(node)
            page.locator(f"{FORM} {field}").fill(value)
            page.click(f"{FORM} button.primary:enabled")
            wait(page, ".toast", problems)
            page.locator(".toast").first.wait_for(state="detached", timeout=30_000)
            values = c.get("/ui/api/settings").json()["values"]
            assert {k: values[k] for k in want} == want, node
            assert page.locator(UNSAVED).count() == 0, node
        assert problems == []
        page.close()
    finally:
        stop(proc)


def test_an_own_esplora_left_blank_is_refused_not_read_as_the_public_one(tmp_path, browser):
    """Choosing an own Esplora keeps the choice and shows its address field (it snapped back to
    mempool.space while the address was the public one's); left blank, Save refuses it at the
    field, since a blank would be read as the public default, and nothing is sent. Another
    choice clears the refusal."""
    base, proc = unlocked(tmp_path)
    try:
        c = client(base)
        made(
            c.post(
                "/ui/api/welcome/admin",
                json={"password": PASSWORD, "email": "admin@home.lan", "displayName": "Admin",
                      "sex": "female"},
            )
        )  # fmt: skip
        page, problems = open_page(browser, base + "/ui/")
        r = page.request.post(
            base + "/ui/api/session",
            data={"login": "admin", "password": PASSWORD},
            headers={"Origin": base},
        )
        assert r.ok, r.text()
        page.goto(base + "/ui/settings/bitcoin")
        wait(page, UNSAVED, problems)
        choice = page.get_by_label("Explorer or node")
        choice.select_option("esplora")
        assert choice.input_value() == "esplora"
        page.locator(f"{FORM} #f-esplora-url").wait_for()
        # Nothing is said while it is being filled; Save is when a blank is refused.
        assert page.locator(f'{FORM} :text("Your Esplora’s address.")').count() == 0
        page.click(f"{FORM} button.primary:enabled")
        wait(page, f'{FORM} .err:has-text("Your Esplora’s address.")', problems)
        assert "bitcoinSource" not in c.get("/ui/api/settings").json()["records"]
        choice.select_option("blockstream")
        assert page.locator(f'{FORM} :text("Your Esplora’s address.")').count() == 0
        page.click(f"{FORM} button.primary:enabled")
        wait(page, ".toast", problems)
        page.locator(".toast").first.wait_for(state="detached", timeout=30_000)
        values = c.get("/ui/api/settings").json()["values"]
        assert values["bitcoinEsploraUrl"] == "https://blockstream.info/api"
        assert problems == []
        page.close()
    finally:
        stop(proc)
