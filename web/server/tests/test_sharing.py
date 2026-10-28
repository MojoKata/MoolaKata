import re

from conftest import make_user, sign_in
from edits import change, saved
from test_accounts import add, new_account


def share(c, kind, item, users=None, groups=None, too=False):
    r = c.put(
        f"/ui/api/shares/{kind}/{item}",
        json={"users": users or {}, "groups": groups or {}, "shareAccountsToo": too},
    )
    assert r.status_code == 200, r.text
    return r.json()


def setup(server):
    users = {n: make_user(server, n) for n in ("alice", "bob", "carol")}
    return users, {n: sign_in(server, n) for n in users}


def test_read_and_write_shares(server):
    u, c = setup(server)
    a = new_account(c["alice"], openingBalance="100.00", openingDate="2026-08-31")
    add(c["alice"], a["id"], "-10.00", payee="Shop")
    assert c["bob"].get(f"/ui/api/accounts/{a['id']}").status_code == 404
    share(c["alice"], "account", a["id"], users={u["bob"].id: "read"})
    seen = c["bob"].get("/ui/api/accounts").json()["items"]
    assert len(seen) == 1 and seen[0]["level"] == "read" and seen[0]["ownerName"] == "Alice"
    assert seen[0]["counted"] is False  # Count in my totals is off by default (S10.7)
    assert c["alice"].get("/ui/api/accounts").json()["items"][0]["sharedWith"] == 1
    assert len(c["bob"].get("/ui/api/transactions").json()["items"]) == 1
    r = c["bob"].post(
        "/ui/api/transactions", json={"accountId": a["id"], "date": "2026-09-02", "amount": "-1.00"}
    )
    assert r.status_code == 403 and r.json()["code"] == "share-read-only"
    assert c["bob"].get(f"/ui/api/shares/account/{a['id']}").status_code == 403
    share(c["alice"], "account", a["id"], users={u["bob"].id: "write"})
    add(c["bob"], a["id"], "-2.00", payee="Bob's coffee")
    acct = c["bob"].get(f"/ui/api/accounts/{a['id']}").json()
    r = c["bob"].patch(
        f"/ui/api/accounts/{a['id']}",
        json={"lotMethod": "lifo"},
        headers={"If-Match": str(acct["version"])},
    )
    assert r.status_code == 403  # a write share doesn't change the account's settings
    r = c["bob"].delete(f"/ui/api/accounts/{a['id']}", headers={"If-Match": str(acct["version"])})
    assert r.status_code == 403 and r.json()["code"] == "owner-only"


def test_groups_via_and_the_higher_level(server, admin_client):
    u, c = setup(server)
    g = admin_client.post(
        "/ui/api/groups", json={"name": "Household", "memberIds": [u["bob"].id, u["carol"].id]}
    ).json()
    a = new_account(c["alice"])
    view = share(
        c["alice"], "account", a["id"], users={u["bob"].id: "write"}, groups={g["id"]: "read"}
    )["view"]
    bob = next(x for x in view["users"] if x["id"] == u["bob"].id)
    carol = next(x for x in view["users"] if x["id"] == u["carol"].id)
    assert bob["level"] == "write" and bob["via"][0]["groupName"] == "Household"
    assert carol["level"] == "none" and carol["via"][0]["level"] == "read"
    assert c["carol"].get("/ui/api/accounts").json()["items"][0]["level"] == "read"
    assert c["bob"].get("/ui/api/accounts").json()["items"][0]["level"] == "write"
    r = admin_client.patch(
        f"/ui/api/groups/{g['id']}", json={"active": False}, headers={"If-Match": str(g["version"])}
    )
    assert r.status_code == 200
    assert (
        c["carol"].get("/ui/api/accounts").json()["items"] == []
    )  # an inactive group gives nothing


def test_removing_a_share_ends_access_and_drops_their_tags(server):
    u, c = setup(server)
    a = new_account(c["alice"])
    t = add(c["alice"], a["id"], "-5.00", payee="Shop")
    share(c["alice"], "account", a["id"], users={u["bob"].id: "write"})
    r = change(c["bob"], "Txn", t, tags={"add": ["bobs"], "remove": []})
    assert saved(r)["tags"] == ["bobs"]
    assert c["alice"].get("/ui/api/transactions").json()["items"][0]["tags"] == []
    share(c["alice"], "account", a["id"], users={u["bob"].id: "none"})
    assert c["bob"].get(f"/ui/api/accounts/{a['id']}").status_code == 404
    share(c["alice"], "account", a["id"], users={u["bob"].id: "read"})
    assert c["bob"].get("/ui/api/transactions").json()["items"][0]["tags"] == []


def test_inactive_users_cant_be_added(server, admin_client):
    u, c = setup(server)
    a = new_account(c["alice"])
    row = next(
        x for x in admin_client.get("/ui/api/users").json()["items"] if x["username"] == "carol"
    )
    admin_client.patch(
        f"/ui/api/users/{row['id']}",
        json={"active": False},
        headers={"If-Match": str(row["version"])},
    )
    r = c["alice"].put(
        f"/ui/api/shares/account/{a['id']}", json={"users": {u["carol"].id: "read"}, "groups": {}}
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "user-inactive"


def test_count_in_my_totals_and_all_my_accounts(server):
    u, c = setup(server)
    mine = new_account(c["bob"], name="Bob's", openingBalance="10.00", openingDate="2026-01-01")
    hers = new_account(c["alice"], openingBalance="1000.00", openingDate="2026-01-01")
    share(c["alice"], "account", hers["id"], users={u["bob"].id: "read"})
    everything = c["bob"].get("/ui/api/portfolios").json()["items"][0]
    assert everything["implicit"] and everything["accountIds"] == [mine["id"]]
    assert everything["value"] == "10.00"
    assert (
        c["bob"].put(f"/ui/api/accounts/{hers['id']}/counted", json={"counted": True}).status_code
        == 204
    )
    everything = c["bob"].get("/ui/api/portfolios/all").json()
    assert sorted(everything["accountIds"]) == sorted([mine["id"], hers["id"]])
    assert everything["value"] == "1010.00"
    assert (
        c["alice"].put(f"/ui/api/accounts/{hers['id']}/counted", json={"counted": True}).status_code
        == 409
    )


def test_portfolio_viewers_see_only_their_accounts(server):
    u, c = setup(server)
    checking = new_account(c["alice"], openingBalance="100.00", openingDate="2026-01-01")
    brokerage = new_account(
        c["alice"],
        name="Brokerage",
        type="brokerage",
        mask="9999",
        openingBalance="500.00",
        openingDate="2026-01-01",
    )
    p = (
        c["alice"]
        .post(
            "/ui/api/portfolios",
            json={"name": "Family", "accountIds": [checking["id"], brokerage["id"]]},
        )
        .json()
    )
    assert p["value"] == "600.00"
    share(c["alice"], "account", checking["id"], users={u["bob"].id: "read"})
    saved = share(c["alice"], "portfolio", p["id"], users={u["bob"].id: "read"})
    assert saved["view"]["hidden"] == {u["bob"].id: [brokerage["id"]]}
    seen = c["bob"].get(f"/ui/api/portfolios/{p['id']}").json()
    assert seen["accountIds"] == [checking["id"]] and seen["value"] == "100.00"
    saved = share(c["alice"], "portfolio", p["id"], users={u["bob"].id: "read"}, too=True)
    assert saved["alsoShared"] == 1 and saved["view"]["hidden"] == {}
    seen = c["bob"].get(f"/ui/api/portfolios/{p['id']}").json()
    assert seen["value"] == "600.00"
    r = c["bob"].patch(
        f"/ui/api/portfolios/{p['id']}",
        json={"name": "Mine now"},
        headers={"If-Match": str(seen["version"])},
    )
    assert r.status_code == 403
    r = c["alice"].post(
        "/ui/api/portfolios", json={"name": "Not mine", "accountIds": ["Acct_nope"]}
    )
    assert r.json()["errors"][0]["field"] == "accountIds"


def test_activity_goes_to_the_people_concerned_without_amounts(server, admin_client):
    u, c = setup(server)
    a = new_account(c["alice"], name="Joint checking")
    private = new_account(c["alice"], name="Secret savings", type="savings", mask="0001")
    t = add(c["alice"], a["id"], "-1234.56", payee="Shop")
    add(c["alice"], private["id"], "-9.99", payee="Hidden")
    cats = {x["path"]: x["id"] for x in c["alice"].get("/ui/api/categories").json()["items"]}
    c["alice"].post(
        "/ui/api/transactions/categorise",
        json={"ids": [t["id"]], "categoryId": cats["Food › Groceries"]},
    )
    share(c["alice"], "account", a["id"], users={u["bob"].id: "read"})
    bob = [x["text"] for x in c["bob"].get("/ui/api/activity").json()["items"]]
    assert "Alice changed the category of 1 transaction in Joint checking" in bob
    assert "Alice shared Joint checking with Bob (read)" in bob
    assert not any("Secret savings" in x for x in bob)
    alice = [x["text"] for x in c["alice"].get("/ui/api/activity").json()["items"]]
    assert any("Secret savings" in x for x in alice)
    assert not any(re.search(r"\d+\.\d\d", x) for x in alice)  # never an amount
    admin = [x["text"] for x in admin_client.get("/ui/api/activity").json()["items"]]
    assert any("Ada Admin" in x and "set up" in x for x in admin)
    assert not any("Joint checking" in x for x in admin)  # admins see only what is shared
    page = c["alice"].get("/ui/api/activity", params={"limit": 1}).json()
    newest = page["items"][0]["id"]
    add(c["alice"], a["id"], "-1.00", payee="x")
    c["alice"].post(
        "/ui/api/transactions/categorise",
        json={"ids": [t["id"]], "categoryId": cats["Food › Dining out"]},
    )
    assert c["alice"].get("/ui/api/activity/newer", params={"since": newest}).json()["count"] == 1
    filtered = c["alice"].get("/ui/api/activity", params={"account": private["id"]}).json()
    assert all("Secret savings" in x["text"] for x in filtered["items"])


def test_receivers_see_what_happens_to_what_is_shared_and_its_removal(server):
    """S10.8: whoever a projection or a person is shared with sees its entries in Activity,
    and someone whose share is removed keeps the one entry that says so."""
    u, c = setup(server)
    p = (
        c["alice"]
        .post(
            "/ui/api/projections",
            json={
                "name": "Retire early",
                "goal": "savings",
                "builtOn": {"kind": "typed", "amount": "1000"},
                "inputs": {"target": 5000, "date": "2031-01-01"},
            },
        )
        .json()
    )
    share(c["alice"], "projection", p["id"], users={u["bob"].id: "read"})
    texts = [e["text"] for e in c["bob"].get("/ui/api/activity").json()["items"]]
    assert any("shared Retire early with Bob" in t for t in texts), texts
    share(c["alice"], "projection", p["id"], users={u["bob"].id: "none"})
    texts = [e["text"] for e in c["bob"].get("/ui/api/activity").json()["items"]]
    assert any("stopped sharing Retire early with Bob" in t for t in texts), texts
    carols = [e["text"] for e in c["carol"].get("/ui/api/activity").json()["items"]]
    assert not any("Retire early" in t for t in carols)
