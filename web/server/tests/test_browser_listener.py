"""Settings › Network's Listener rows as an admin sees them (requirements S16.14, CR3-12,
CR3-308), in headless Chromium, on servers of their own in each way the listener runs: behind a
proxy with none trusted yet or with one, and serving HTTPS with a certificate given to it. (Its
own self-signed one is drawn by the generated mockup's server.)"""

import pytest
from browser import PASSWORD, client, made, open_page, stop, unlocked, wait

from moolakata import paths
from moolakata.listener import self_signed

pytestmark = pytest.mark.browser

ROWS = 'form.card:has-text("Network") .list-item, form.card:has-text("Network") p.small'


def rows(browser, base: str) -> str:
    c = client(base)
    admin = {"password": PASSWORD, "email": "admin@home.lan", "displayName": "Admin",
             "sex": "female"}  # fmt: skip
    made(c.post("/ui/api/welcome/admin", json=admin))
    page, problems = open_page(browser, base + "/ui/")
    r = page.request.post(base + "/ui/api/session", data={"login": "admin", "password": PASSWORD},
                          headers={"Origin": base})  # fmt: skip
    assert r.ok, r.text()
    page.goto(base + "/ui/settings/network")
    wait(page, ':text("Listener")', problems)
    shown = " | ".join(t.strip() for t in page.locator(ROWS).all_inner_texts())
    assert problems == []
    page.close()
    c.close()
    return " ".join(shown.split())


@pytest.mark.parametrize(
    ("config", "said", "not_said"),
    [
        ({}, ["proxy mode", "Trusted proxies none"], ["Certificate"]),
        (
            {"server": 'trusted_proxies = ["127.0.0.2", "fd00:37::7"]'},
            ["Trusted proxies 127.0.0.2, fd00:37::7"],
            ["Certificate"],
        ),
        (
            {"mode": "tls", "more": "given"},
            ["tls mode", "Certificate given in moolakata.toml"],
            ["for testing", "Trusted proxies"],
        ),
    ],
    ids=["proxy, none trusted", "proxy, two trusted", "tls, a given certificate"],
)
def test_the_listener_rows_say_how_it_runs(browser, tmp_path, config, said, not_said):
    if config.get("more") == "given":
        cert, key = self_signed(tmp_path / "certs", ["127.0.0.1"])
        config = {**config, "more": f'[tls]\ncert = "{cert}"\nkey = "{key}"'}
    base, proc = unlocked(tmp_path, **config)
    try:
        shown = rows(browser, base)
    finally:
        stop(proc)
    for text in said:
        assert text in shown, shown
    for text in not_said:
        assert text not in shown, shown


def test_the_listener_explains_itself_in_the_guide():
    """What the rows leave out is in Settings › Network's guide (R3.12)."""
    guide = (paths.UI / "guides" / "settings-network.md").read_text()
    for text in ["each proxy's own address, never a whole range", "A renewed certificate"]:
        assert text in " ".join(guide.split()), text
