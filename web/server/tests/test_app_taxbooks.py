"""A tax book someone else named you on, in the browser app (requirements S8.14.1; the filed
tax years walk, decision 2): Accept counts it among your books, Decline takes you off it and
its owner is told. Bob makes the books on the seeded dev server; Alice answers them in her
page. The books are for years nothing else reads, and are taken away after.
"""

import httpx
import pytest
from devapp import as_alice
from edits import new_id

pytestmark = [pytest.mark.browser, pytest.mark.xdist_group("app")]


def _bob(base: str) -> httpx.Client:
    c = httpx.Client(base_url=base, headers={"Origin": base}, timeout=30, verify=False)
    r = c.post("/ui/api/session", json={"login": "bob", "password": "moolakata-dev"})
    assert r.status_code == 200, r.text
    return c


def _joint(bob: httpx.Client, year: int) -> str:
    me = bob.get("/ui/api/session").json()["user"]["id"]
    alice = bob.get("/ui/api/profile").json()["spouse"]["id"]
    book_id = new_id("TaxBk")
    op = {"op": "create", "entity": "TaxBk", "id": book_id,
          "fields": {"year": year, "filers": [me, alice], "fromLastYear": False}}  # fmt: skip
    r = bob.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 200, r.text
    return book_id


def test_a_book_youre_named_on_is_accepted_or_declined(dev_server):
    bob = _bob(dev_server)
    declined, accepted = _joint(bob, 2018), _joint(bob, 2017)
    try:
        with as_alice(dev_server) as pg:
            pg.goto(dev_server + "/ui/taxes")
            notice = '.notice:has-text("2018")'
            pg.wait_for_selector(notice)
            pg.click(f'{notice} button:has-text("Decline")')
            pg.click('[role=alertdialog] button:text-is("Yes")')
            pg.wait_for_selector(notice, state="detached")
            other = '.notice:has-text("2017")'
            pg.click(f'{other} button:has-text("Accept")')
            pg.wait_for_selector(other, state="detached")
            assert pg.problems == []
        d = bob.get(f"/ui/api/tax-books/{declined}").json()
        assert len(d["filers"]) == 1, "Alice taken off the book she declined"
        told = bob.get("/ui/api/activity").json()["items"]
        assert any(a["kind"] == "tax-book.declined" for a in told)
        d = bob.get(f"/ui/api/tax-books/{accepted}").json()
        assert all(f["accepted"] for f in d["filers"]), "both filers of the book she accepted"
    finally:
        for b in (declined, accepted):
            got = bob.get(f"/ui/api/tax-books/{b}").json()
            op = {"op": "delete", "entity": "TaxBk", "id": b, "version": got["version"]}
            bob.post("/ui/api/save", json={"ops": [op]})
        bob.close()  # an open connection holds the dev server's shutdown
