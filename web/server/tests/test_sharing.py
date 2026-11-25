import re

from conftest import make_user, sign_in
from edits import change, create, make, remove, saved, tag
from edits import share as shared
from test_accounts import add, new_account


def share(c, kind, item, users=None, groups=None, too=False):
    """Shared as the dialog shares it; the shares as read after, with how many accounts
    Share these accounts too shared."""
    before = c.get(f"/ui/api/shares/{kind}/{item}").json()
    r = shared(c, kind, item, users=users, groups=groups, too=too)
    assert r.status_code == 200, r.text
    v = c.get(f"/ui/api/shares/{kind}/{item}").json()
    hidden = sum(len(x) for x in before["hidden"].values()) if too else 0
    return {"view": v, "alsoShared": len(r.json()["saved"]) if too and hidden else 0}


def setup(server):
    users = {n: make_user(server, n) for n in ("jane", "john", "bart")}
    return users, {n: sign_in(server, n) for n in users}


def test_read_and_write_shares(server):
    u, c = setup(server)
    a = new_account(c["jane"], openingBalance="100.00", openingDate="2026-08-31")
    add(c["jane"], a["id"], "-10.00", payee="Shop")
    assert c["john"].get(f"/ui/api/accounts/{a['id']}").status_code == 404
    share(c["jane"], "account", a["id"], users={u["john"].id: "read"})
    seen = c["john"].get("/ui/api/accounts").json()["items"]
    assert len(seen) == 1 and not seen[0]["access"]["writable"] and seen[0]["ownerName"] == "Jane"
    assert seen[0]["counted"] is False  # Count in my totals is off by default (S10.7)
    assert c["jane"].get("/ui/api/accounts").json()["items"][0]["sharedWith"] == 1
    assert len(c["john"].get("/ui/api/transactions").json()["items"]) == 1
    r = make(c["john"], "Txn", accountId=a["id"], date="2026-09-02", amount="-1.00")
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "share-read-only"
    assert c["john"].get(f"/ui/api/shares/account/{a['id']}").status_code == 403
    share(c["jane"], "account", a["id"], users={u["john"].id: "write"})
    add(c["john"], a["id"], "-2.00", payee="John's coffee")
    acct = c["john"].get(f"/ui/api/accounts/{a['id']}").json()
    r = change(c["john"], "Acct", acct, lotMethod="lifo")
    assert r.status_code == 403  # a write share doesn't change the account's settings
    r = remove(c["john"], "Acct", acct)
    assert r.status_code == 403 and r.json()["errors"][0]["code"] == "owner-only"


def test_groups_via_and_the_higher_level(server, admin_client):
    u, c = setup(server)
    g = make(admin_client, "Group", name="Household", memberIds=[u["john"].id, u["bart"].id]).json()
    a = new_account(c["jane"])
    view = share(
        c["jane"], "account", a["id"], users={u["john"].id: "write"}, groups={g["id"]: "read"}
    )["view"]
    john = next(x for x in view["users"] if x["id"] == u["john"].id)
    bart = next(x for x in view["users"] if x["id"] == u["bart"].id)
    assert john["allow"] == "write" and john["via"][0]["groupName"] == "Household"
    assert bart["allow"] == "none" and bart["via"][0]["allow"] == "read"
    assert not c["bart"].get("/ui/api/accounts").json()["items"][0]["access"]["writable"]
    assert c["john"].get("/ui/api/accounts").json()["items"][0]["access"]["writable"]
    saved(change(admin_client, "Group", g, active=False))
    assert (
        c["bart"].get("/ui/api/accounts").json()["items"] == []
    )  # an inactive group gives nothing


def test_removing_a_share_ends_access_and_drops_their_tags(server):
    u, c = setup(server)
    a = new_account(c["jane"])
    t = add(c["jane"], a["id"], "-5.00", payee="Shop")
    share(c["jane"], "account", a["id"], users={u["john"].id: "write"})
    r = change(c["john"], "Txn", t, tagIds={"add": [tag(c["john"], "johns")], "remove": []})
    assert saved(r)["tags"] == ["johns"]
    assert c["jane"].get("/ui/api/transactions").json()["items"][0]["tags"] == []
    share(c["jane"], "account", a["id"], users={u["john"].id: "none"})
    assert c["john"].get(f"/ui/api/accounts/{a['id']}").status_code == 404
    share(c["jane"], "account", a["id"], users={u["john"].id: "read"})
    assert c["john"].get("/ui/api/transactions").json()["items"][0]["tags"] == []


def test_inactive_users_cant_be_added(server, admin_client):
    u, c = setup(server)
    a = new_account(c["jane"])
    row = next(
        x for x in admin_client.get("/ui/api/users").json()["items"] if x["username"] == "bart"
    )
    saved(change(admin_client, "User", row, active=False))
    r = shared(c["jane"], "account", a["id"], users={u["bart"].id: "read"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "user-inactive"


def test_count_in_my_totals_and_all_my_accounts(server):
    u, c = setup(server)
    mine = new_account(c["john"], name="John's", openingBalance="10.00", openingDate="2026-01-01")
    hers = new_account(c["jane"], openingBalance="1000.00", openingDate="2026-01-01")
    share(c["jane"], "account", hers["id"], users={u["john"].id: "read"})
    everything = c["john"].get("/ui/api/portfolios").json()["items"][0]
    assert everything["implicit"] and everything["accountIds"] == [mine["id"]]
    assert everything["value"] == "10.00"
    saved(create(c["john"], "CntAc", accountId=hers["id"], counted=True))
    everything = c["john"].get("/ui/api/portfolios/all").json()
    assert sorted(everything["accountIds"]) == sorted([mine["id"], hers["id"]])
    assert everything["value"] == "1010.00"
    r = create(c["jane"], "CntAc", accountId=hers["id"], counted=True)
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "owner-counts"


def test_portfolio_viewers_see_only_their_accounts(server):
    u, c = setup(server)
    checking = new_account(c["jane"], openingBalance="100.00", openingDate="2026-01-01")
    brokerage = new_account(
        c["jane"],
        name="Brokerage",
        type="brokerage",
        mask="9999",
        openingBalance="500.00",
        openingDate="2026-01-01",
    )
    p = make(c["jane"], "Portf", name="Family", accountIds=[checking["id"], brokerage["id"]]).json()
    assert p["value"] == "600.00"
    share(c["jane"], "account", checking["id"], users={u["john"].id: "read"})
    saved = share(c["jane"], "portfolio", p["id"], users={u["john"].id: "read"})
    assert saved["view"]["hidden"] == {u["john"].id: [brokerage["id"]]}
    seen = c["john"].get(f"/ui/api/portfolios/{p['id']}").json()
    assert seen["accountIds"] == [checking["id"]] and seen["value"] == "100.00"
    saved = share(c["jane"], "portfolio", p["id"], users={u["john"].id: "read"}, too=True)
    assert saved["alsoShared"] == 1 and saved["view"]["hidden"] == {}
    seen = c["john"].get(f"/ui/api/portfolios/{p['id']}").json()
    assert seen["value"] == "600.00"
    r = change(c["john"], "Portf", seen, name="Mine now")
    assert r.status_code == 403
    r = make(c["jane"], "Portf", name="Not mine", accountIds=["Acct_00000000000000000000000000"])
    assert r.json()["errors"][0]["field"] == "accountIds"


def test_share_these_accounts_too_gives_a_person_their_own_only_what_no_group_gives():
    """S5.1.2: John holds the portfolio through Household and by his own share, Eve by hers:
    what John can't see goes to Household alone; Eve's goes to her."""
    from moolakata.ui.sharing import _share_too

    got = _share_too({"john": ["a", "b"], "eve": ["b"]}, ["hh"], ["john", "eve"],
                     {"hh": ["john"], "other": ["eve"]})  # fmt: skip
    assert [(x.groupId, x.userId, x.accountIds) for x in got] == [
        ("hh", None, ["a", "b"]),
        (None, "eve", ["b"]),
    ]


def test_share_these_accounts_too_shares_with_the_group_the_portfolio_is_shared_with(
    server, admin_client
):
    """S5.1.2, S10.5: Jane's portfolio shared with the group Household; Share these accounts
    too shares her brokerage with the group, not with each member: John, leaving the group,
    loses both, and Bart, joining it, gains both. Bart's own share of the portfolio asks for
    nothing the group's doesn't already give him."""
    u, c = setup(server)
    g = make(admin_client, "Group", name="Household", memberIds=[u["john"].id]).json()
    brokerage = new_account(c["jane"], name="Brokerage", type="brokerage",
                            openingBalance="500.00", openingDate="2026-01-01")  # fmt: skip
    p = make(c["jane"], "Portf", name="Family", accountIds=[brokerage["id"]]).json()
    v = share(c["jane"], "portfolio", p["id"], groups={g["id"]: "read"})["view"]
    assert v["shareToo"] == [{"groupId": g["id"], "userId": None, "accountIds": [brokerage["id"]]}]
    share(c["jane"], "portfolio", p["id"], groups={g["id"]: "read"}, too=True)
    held = c["jane"].get(f"/ui/api/shares/account/{brokerage['id']}").json()
    assert [x["id"] for x in held["groups"] if x["allow"] == "read"] == [g["id"]]
    assert [x["id"] for x in held["users"] if x["allow"] != "none"] == []

    def sees(who):
        return c[who].get(f"/ui/api/portfolios/{p['id']}").json().get("value")

    assert sees("john") == "500.00"
    g = saved(change(admin_client, "Group", g, memberIds={"add": [u["bart"].id],
                                                          "remove": [u["john"].id]}))  # fmt: skip
    assert sees("john") is None and c["john"].get("/ui/api/accounts").json()["items"] == []
    assert sees("bart") == "500.00"
    v = share(c["jane"], "portfolio", p["id"], users={u["bart"].id: "read"})["view"]
    assert v["hidden"] == {} and v["shareToo"] == []


def test_activity_goes_to_the_people_concerned_without_amounts(server, admin_client):
    u, c = setup(server)
    a = new_account(c["jane"], name="Joint checking")
    private = new_account(c["jane"], name="Secret savings", type="savings", mask="0001")
    t = add(c["jane"], a["id"], "-1234.56", payee="Shop")
    add(c["jane"], private["id"], "-9.99", payee="Hidden")
    cats = {x["path"]: x["id"] for x in c["jane"].get("/ui/api/categories").json()["items"]}
    c["jane"].post(
        "/ui/api/transactions/categorise",
        json={"ids": [t["id"]], "categoryId": cats["Food › Groceries"]},
    )
    share(c["jane"], "account", a["id"], users={u["john"].id: "read"})
    john = [x["text"] for x in c["john"].get("/ui/api/activity").json()["items"]]
    assert "Jane changed the category of 1 transaction in Joint checking" in john
    assert "Jane shared Joint checking with John (read)" in john
    assert not any("Secret savings" in x for x in john)
    jane = [x["text"] for x in c["jane"].get("/ui/api/activity").json()["items"]]
    assert any("Secret savings" in x for x in jane)
    assert not any(re.search(r"\d+\.\d\d", x) for x in jane)  # never an amount
    admin = [x["text"] for x in admin_client.get("/ui/api/activity").json()["items"]]
    assert any("Ada Admin" in x and "set up" in x for x in admin)
    assert not any("Joint checking" in x for x in admin)  # admins see only what is shared
    page = c["jane"].get("/ui/api/activity", params={"limit": 1}).json()
    newest = page["items"][0]["id"]
    add(c["jane"], a["id"], "-1.00", payee="x")
    c["jane"].post(
        "/ui/api/transactions/categorise",
        json={"ids": [t["id"]], "categoryId": cats["Food › Dining out"]},
    )
    assert c["jane"].get("/ui/api/activity/newer", params={"since": newest}).json()["count"] == 1
    filtered = c["jane"].get("/ui/api/activity", params={"account": private["id"]}).json()
    assert all("Secret savings" in x["text"] for x in filtered["items"])


def test_receivers_see_what_happens_to_what_is_shared_and_its_removal(server):
    """S10.8: whoever a projection or a person is shared with sees its entries in Activity,
    and someone whose share is removed keeps the one entry that says so."""
    u, c = setup(server)
    p = make(
        c["jane"],
        "Prjct",
        name="Retire early",
        goal="savings",
        builtOn={"kind": "typed", "amount": "1000"},
        inputs={"target": 5000, "date": "2031-01-01", "monthly": 0, "fees": 0.1},
    ).json()
    share(c["jane"], "projection", p["id"], users={u["john"].id: "read"})
    texts = [e["text"] for e in c["john"].get("/ui/api/activity").json()["items"]]
    assert any("shared Retire early with John" in t for t in texts), texts
    share(c["jane"], "projection", p["id"], users={u["john"].id: "none"})
    texts = [e["text"] for e in c["john"].get("/ui/api/activity").json()["items"]]
    assert any("stopped sharing Retire early with John" in t for t in texts), texts
    barts = [e["text"] for e in c["bart"].get("/ui/api/activity").json()["items"]]
    assert not any("Retire early" in t for t in barts)
