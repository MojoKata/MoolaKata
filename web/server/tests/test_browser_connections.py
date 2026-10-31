"""Profile › Connections in headless Chromium (requirements S18.7.1, S18.7.3): new credentials
for an OFX Connection are sealed in the browser for the host the dialog shows, and a server
address changed in the same dialog is saved first, so the credentials are bound to the new
one. A connector paired over HTTP opens what the browser sealed."""

import json

import httpx
import pytest
from browser import PASSWORD, client, made, open_page, stop, unlocked, wait
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from edits import make, save_settings
from test_connector import FakeConnector

from moolakata.connector import sealed
from moolakata.links import keys
from moolakata.links.signing import Ed25519PrivateKey

pytestmark = pytest.mark.browser


def connector_for(base: str) -> FakeConnector:
    """A connector calling the server over HTTP, as the real one does."""
    fake = FakeConnector.__new__(FakeConnector)
    fake.key, fake.status = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    fake.client = httpx.Client(base_url=base, timeout=30)
    fake.server_key = keys.unb64(fake.client.get("/connector/v1/hello").json()["key"])
    fake.fp = keys.fingerprint(fake.server_key)
    fake.sealing_private = X25519PrivateKey.generate()
    return fake


def test_change_credentials_shows_and_seals_the_host_and_takes_a_new_address(tmp_path, browser):
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
        made(save_settings(c, {"publicUrl": base}))
        fake = connector_for(base)
        code = made(c.post("/ui/api/settings/connector/pairings"))["code"]
        raw = fake.sealing_private.public_key().public_bytes_raw()
        assert fake.call("/connector/v1/pair", fake.pair_body(code, raw)).status_code == 200
        made(c.post("/ui/api/settings/connector/confirm"))
        settings = {"url": "https://ofx.cu.example/ofx", "org": "CU", "fid": "1",
                    "accountType": "CHECKING", "accountId": "4417"}  # fmt: skip
        conn = made(make(c, "Conn", driver="ofx-direct", label="Credit union", settings=settings))

        page, problems = open_page(browser, base + "/ui/")
        r = page.request.post(
            base + "/ui/api/session",
            data={"login": "admin", "password": PASSWORD},
            headers={"Origin": base},
        )
        assert r.ok, r.text()
        page.goto(base + "/ui/profile")
        wait(page, 'button:has-text("Change credentials")', problems)
        page.click('button:has-text("Change credentials")')
        wait(page, 'text="Sealed for"', problems)
        # The dialog shows the address and the host the sign-in is sealed for (S18.7.1).
        assert page.input_value("#f-ofx-url") == settings["url"]
        assert "ofx.cu.example" in page.inner_text('[data-help="sealed-for"]')
        # The institution moved its server: the new address is shown as it is typed.
        page.fill("#f-ofx-url", "https://ofx2.cu.example/ofx")
        assert "ofx2.cu.example" in page.inner_text('[data-help="sealed-for"]')
        page.fill("#f-username", "alice")
        page.fill("#f-password", "pw")
        page.click('button:has-text("Seal and send")')
        wait(page, 'text="Credit union: sealed for the connector"', problems)
        assert problems == []

        mine = c.get("/ui/api/profile/connections").json()["items"]
        assert mine[0]["address"] == "https://ofx2.cu.example/ofx"
        assert mine[0]["host"] == "ofx2.cu.example" and mine[0]["credentialWaiting"]
        # The connector gets the new address and a box sealed for its host alone.
        out = fake.call("/connector/v1/report", {"locked": False, "connections": []}).json()
        (got,) = out["connections"]
        assert got["settings"]["url"] == "https://ofx2.cu.example/ofx"
        box = json.loads(
            sealed.open_box(got["sealed"]["ciphertext"], fake.sealing_private, conn["id"])
        )
        assert box["host"] == "ofx2.cu.example"
        assert box["credentials"] == {"username": "alice", "password": "pw"}
        # Admins see where each Connection's credentials go (S16.18), never its settings.
        admin_view = c.get("/ui/api/settings/connector").json()["connections"][0]
        assert admin_view["host"] == "ofx2.cu.example" and admin_view["settings"] is None
        page.close()
    finally:
        stop(proc)
