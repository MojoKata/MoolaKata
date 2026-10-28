"""The MCP endpoint (requirements S10.9): read-only tools through a user's access token, limited
to the token's chosen items, rate limited, and recorded in Activity."""

import pytest
from conftest import make_user, new_client, sign_in
from edits import remove, saved
from test_accounts import add, new_account

from moolakata import mcp


@pytest.fixture
def alice(server):
    make_user(server, "alice")
    return sign_in(server, "alice")


def token(c, **body) -> str:
    r = c.post("/ui/api/profile/tokens", json={"name": "Claude", **body})
    assert r.status_code == 201, r.text
    return r.json()["secret"]


def rpc(client, secret, method, params=None, id_=1, **headers):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
        headers={"Authorization": f"Bearer {secret}", "Origin": "", **headers},
    )


def call(client, secret, name, **args):
    r = rpc(client, secret, "tools/call", {"name": name, "arguments": args})
    assert r.status_code == 200, r.text
    return r.json()["result"]


@pytest.fixture
def agent(server):
    with new_client(server) as c:
        c.headers.pop("Origin", None)
        yield c


def test_an_assistant_initialises_and_lists_read_only_tools(alice, agent):
    secret = token(alice)
    r = rpc(agent, secret, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18" and res["serverInfo"]["name"] == "MoolaKata"
    note = agent.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert note.status_code == 202
    tools = rpc(agent, secret, "tools/list").json()["result"]["tools"]
    assert {"list_accounts", "list_transactions", "get_tax_panels"} <= {t["name"] for t in tools}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    assert rpc(agent, secret, "resources/list").json()["error"]["code"] == -32601


def test_tools_read_what_the_user_can_see_and_record_each_call(server, alice, agent):
    a = new_account(alice, name="Everyday checking", type="checking")
    add(alice, a["id"], amount="-42.50", payee="Blue Bottle Coffee")
    make_user(server, "bob")
    bob = sign_in(server, "bob")
    hidden = new_account(bob, name="Bob's own", type="checking")
    secret = token(alice)
    out = call(agent, secret, "list_accounts")
    assert not out["isError"]
    names = [x["name"] for x in out["structuredContent"]["result"]]
    assert names == ["Everyday checking"]
    txns = call(agent, secret, "list_transactions", account_id=a["id"])
    assert [t["payee"] for t in txns["structuredContent"]["result"]] == ["Blue Bottle Coffee"]
    refused = call(agent, secret, "get_account_holdings", account_id=hidden["id"])
    assert refused["isError"]
    assert call(agent, secret, "list_transactions", nonsense=1)["isError"]
    for wrong in ({"limit": -1}, {"limit": 100000}, {"limit": "5"}, {"from": "yesterday"}):
        assert call(agent, secret, "list_transactions", **wrong)["isError"], wrong
    assert call(agent, secret, "list_positions", kind="bonds")["isError"]
    assert call(agent, secret, "get_budget_month", budget_id="x", month="Oct")["isError"]
    feed = alice.get("/ui/api/activity").json()
    texts = [e["text"] for e in (feed["items"] if isinstance(feed, dict) else feed)]
    assert any("access token Claude read list accounts" in x for x in texts), texts[:5]
    listed = alice.get("/ui/api/profile/tokens").json()["items"][0]
    assert listed["lastUsedAt"]


def test_a_chosen_items_token_reads_only_its_items(server, alice, agent):
    a = new_account(alice, name="Brokerage", type="brokerage")
    b = new_account(alice, name="Checking", type="checking")
    add(alice, b["id"], amount="-10.00", payee="Hidden payee")
    secret = token(alice, scope="chosen", items=[{"kind": "account", "id": a["id"]}])
    names = [x["name"] for x in call(agent, secret, "list_accounts")["structuredContent"]["result"]]
    assert names == ["Brokerage"]
    assert call(agent, secret, "list_transactions")["structuredContent"]["result"] == []
    assert call(agent, secret, "list_transactions", account_id=b["id"])["isError"]
    whole = call(agent, secret, "list_budgets")
    assert whole["isError"] and "chosen" in whole["content"][0]["text"]


def test_the_endpoint_refuses_without_a_live_token_or_from_a_web_page(server, alice, agent):
    assert rpc(agent, "mkt_nope.nope", "ping").status_code == 401
    r = agent.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and "Bearer" in r.headers["www-authenticate"]
    secret = token(alice)
    assert rpc(agent, secret, "ping").json()["result"] == {}
    assert rpc(agent, secret, "ping", Origin="https://evil.example").status_code == 403
    assert agent.get("/mcp", headers={"Authorization": f"Bearer {secret}"}).status_code == 405
    # A token is never a way into the app's own API.
    r = agent.get("/ui/api/accounts", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 401
    saved(remove(alice, "Token", alice.get("/ui/api/profile/tokens").json()["items"][0]))
    assert rpc(agent, secret, "ping").status_code == 401


def test_calls_are_limited_to_60_a_minute_per_token(server, alice, agent, monkeypatch):
    monkeypatch.setattr(mcp, "LIMIT", mcp.ratelimit.Window(60, 60))
    secret = token(alice)
    for _ in range(60):
        assert rpc(agent, secret, "ping").status_code == 200
    r = rpc(agent, secret, "ping")
    assert r.status_code == 429 and r.headers["retry-after"]
    assert rpc(agent, token(alice, name="Another"), "ping").status_code == 200


def test_every_tool_is_in_the_api_reference():
    """docs/api.md lists each MCP tool (S10.9): a new tool without its row fails here."""
    from moolakata import paths
    from moolakata.mcp import TOOLS

    text = (paths.ROOT / "docs" / "api.md").read_text()
    missing = [name for name in TOOLS if f"| `{name}`" not in text]
    assert missing == []
