"""The MCP endpoint (requirements S10.9): read-only tools through a user's access token, limited
to the token's chosen items, rate limited, and recorded in Activity."""

import pytest
from conftest import make_user, new_client, sign_in
from edits import giving_plan, make, remove, saved
from test_accounts import add, new_account

from moolakata import mcp
from moolakata.ui.accounts import AccountRow


@pytest.fixture
def jane(server):
    make_user(server, "jane")
    return sign_in(server, "jane")


def token(c, **body) -> str:
    r = make(c, "Token", **{"name": "Claude", **body})
    assert r.status_code == 200, r.text
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


def test_an_assistant_initialises_and_lists_read_only_tools(jane, agent):
    secret = token(jane)
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


def test_tools_read_what_the_user_can_see_and_record_each_call(server, jane, agent):
    a = new_account(jane, name="Everyday checking", type="checking")
    add(jane, a["id"], amount="-42.50", payee="Blue Bottle Coffee")
    make_user(server, "john")
    john = sign_in(server, "john")
    hidden = new_account(john, name="John's own", type="checking")
    secret = token(jane)
    out = call(agent, secret, "list_accounts")
    assert not out["isError"]
    names = [x["name"] for x in out["structuredContent"]["result"]]
    assert names == ["Everyday checking"]
    # An account's row, never its detail: its notes stay on its page (S10.9).
    assert set(out["structuredContent"]["result"][0]) == set(AccountRow.model_fields)
    txns = call(agent, secret, "list_transactions", account_id=a["id"])
    assert [t["payee"] for t in txns["structuredContent"]["result"]] == ["Blue Bottle Coffee"]
    refused = call(agent, secret, "get_account_holdings", account_id=hidden["id"])
    assert refused["isError"]
    assert call(agent, secret, "list_transactions", nonsense=1)["isError"]
    for wrong in ({"limit": -1}, {"limit": 100000}, {"limit": "5"}, {"from": "yesterday"}):
        assert call(agent, secret, "list_transactions", **wrong)["isError"], wrong
    assert call(agent, secret, "list_positions", kind="bonds")["isError"]
    assert call(agent, secret, "get_budget_month", budget_id="x", month="Oct")["isError"]
    feed = jane.get("/ui/api/activity").json()
    texts = [e["text"] for e in (feed["items"] if isinstance(feed, dict) else feed)]
    assert any("access token Claude read list accounts" in x for x in texts), texts[:5]
    listed = jane.get("/ui/api/profile/tokens").json()["items"][0]
    assert listed["lastUsedAt"]


def test_giving_reads_the_users_own_plan(jane, agent):
    saved(giving_plan(jane, 2026, targetKind="amount", amount="5000"))
    out = call(agent, token(jane), "get_giving", year=2026)
    assert not out["isError"], out
    assert out["structuredContent"]["result"]["plan"]["targetKind"] == "amount"


def test_giving_reads_a_plan_shared_with_the_user_and_refuses_another(server, jane, agent):
    """S7.9.1, S10.9: `plan` chooses a giving plan the user reads, as the Giving screen's
    choice does; none, their own; one they don't read is refused as the route refuses it."""
    from edits import share

    make_user(server, "john")
    john = sign_in(server, "john")
    john_id = john.get("/ui/api/session").json()["user"]["id"]
    hers = saved(giving_plan(jane, 2026, targetKind="amount", amount="5000"))
    his = saved(giving_plan(john, 2026, targetKind="amount", amount="700"))
    secret = token(john)
    own = call(agent, secret, "get_giving", year=2026)["structuredContent"]["result"]
    assert own["plan"]["id"] == his["id"]
    assert call(agent, secret, "get_giving", year=2026, plan=hers["id"])["isError"]
    assert john.get("/ui/api/giving", params={"year": 2026, "plan": hers["id"]}).status_code == 404
    share(jane, "giving-plan", hers["id"], users={john_id: "read"})
    out = call(agent, secret, "get_giving", year=2026, plan=hers["id"])
    assert not out["isError"], out
    assert out["structuredContent"]["result"]["plan"]["id"] == hers["id"]
    tools = rpc(agent, secret, "tools/list").json()["result"]["tools"]
    (giving,) = [t for t in tools if t["name"] == "get_giving"]
    assert "plan" in giving["inputSchema"]["properties"]


def test_a_chosen_items_token_reads_only_its_items(server, jane, agent):
    a = new_account(jane, name="Brokerage", type="brokerage")
    b = new_account(jane, name="Checking", type="checking")
    add(jane, b["id"], amount="-10.00", payee="Hidden payee")
    secret = token(jane, scope="chosen", items=[{"kind": "account", "id": a["id"]}])
    names = [x["name"] for x in call(agent, secret, "list_accounts")["structuredContent"]["result"]]
    assert names == ["Brokerage"]
    assert call(agent, secret, "list_transactions")["structuredContent"]["result"] == []
    assert call(agent, secret, "list_transactions", account_id=b["id"])["isError"]
    whole = call(agent, secret, "list_budgets")
    assert whole["isError"] and "chosen" in whole["content"][0]["text"]


def test_the_endpoint_refuses_without_a_live_token_or_from_a_web_page(server, jane, agent):
    assert rpc(agent, "mkt_nope.nope", "ping").status_code == 401
    r = agent.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and "Bearer" in r.headers["www-authenticate"]
    secret = token(jane)
    assert rpc(agent, secret, "ping").json()["result"] == {}
    assert rpc(agent, secret, "ping", Origin="https://evil.example").status_code == 403
    assert agent.get("/mcp", headers={"Authorization": f"Bearer {secret}"}).status_code == 405
    # A token is never a way into the app's own API.
    r = agent.get("/ui/api/accounts", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 401
    saved(remove(jane, "Token", jane.get("/ui/api/profile/tokens").json()["items"][0]))
    assert rpc(agent, secret, "ping").status_code == 401


def test_calls_are_limited_to_60_a_minute_per_token(server, jane, agent, monkeypatch):
    monkeypatch.setattr(mcp, "LIMIT", mcp.ratelimit.Window(60, 60))
    secret = token(jane)
    for _ in range(60):
        assert rpc(agent, secret, "ping").status_code == 200
    r = rpc(agent, secret, "ping")
    assert r.status_code == 429 and r.headers["retry-after"]
    assert rpc(agent, token(jane, name="Another"), "ping").status_code == 200


def test_every_tool_is_in_the_api_reference():
    """docs/api.md lists each MCP tool (S10.9): a new tool without its row fails here."""
    from moolakata import paths
    from moolakata.mcp import TOOLS

    text = (paths.ROOT / "docs" / "api.md").read_text()
    missing = [name for name in TOOLS if f"| `{name}`" not in text]
    assert missing == []


def test_tool_names_and_arguments_are_snake_case():
    """MCP's spelling for names and arguments, the one exception to camelCase (S13.8.2)."""
    import re

    from moolakata.mcp import TOOLS

    names = [*TOOLS, *(a for t in TOOLS.values() for a in t.params)]
    assert [n for n in names if not re.fullmatch(r"[a-z]+(_[a-z]+)*", n)] == []


@pytest.mark.parametrize(
    "method, params",
    [
        ("initialize", [1]),
        ("tools/call", [1]),
        ("tools/call", "list_accounts"),
        ("tools/call", {"name": ["list_accounts"]}),
        ("tools/call", {"name": "list_accounts", "arguments": [{"a": 1}]}),
        ("tools/call", {"name": "list_accounts", "arguments": "x"}),
    ],
)
def test_params_name_or_arguments_of_the_wrong_type_are_invalid_params(jane, agent, method, params):
    """JSON-RPC's -32602 for params, a tool's name or its arguments not of their type (S10.9.6)."""
    secret = token(jane)
    r = agent.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["error"]["code"] == -32602


def _made(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def test_every_tool_answers_a_whole_token_as_its_screen_does(server, jane, agent):
    """S10.9: each tool reads with the screens' own code: positions, portfolios, budgets and
    their months, gifts coming up, tax books and their panels."""
    acct = new_account(jane, name="Taxable", type="brokerage")
    p = _made(make(jane, "Portf", name="Growth", accountIds=[acct["id"]], benchmark="60-40"))
    b = _made(make(jane, "Bdgt", name="Household", accountIds=[acct["id"]]))
    me = jane.get("/ui/api/session").json()["user"]["id"]
    book = _made(make(jane, "TaxBk", year=2026, filers=[me]))["id"]
    secret = token(jane)

    def result(name, **args):
        out = call(agent, secret, name, **args)
        assert not out["isError"], (name, out)
        return out["structuredContent"]["result"]

    assert result("list_transactions") == []  # every account the user reads: none has any
    assert {"open", "closed", "summary"} <= set(result("list_positions"))
    assert set(result("list_positions", kind="options")) >= {"open", "closed"}
    # Every account together, as the Portfolios screen lists it first, and the one made.
    assert [x["id"] for x in result("list_portfolios")] == ["all", p["id"]]
    one = result("get_portfolio", portfolio_id=p["id"])
    assert one["portfolio"]["id"] == p["id"] and {"holdings", "returns"} <= set(one)
    assert b["id"] in [x["id"] for x in result("list_budgets")]
    month = result("get_budget_month", budget_id=b["id"], month="2026-10")
    assert month["month"] == "2026-10-01"
    assert result("list_upcoming_gifts") == []  # nobody with a birthday or holiday yet
    assert [x["id"] for x in result("list_tax_books")["books"]] == [book]
    assert result("get_tax_panels", book_id=book)


def test_a_chosen_items_token_reads_only_its_portfolios_and_positions(server, jane, agent):
    """S10.9: a chosen-items token's positions are its accounts' alone, without the totals of
    every account; its portfolios are those chosen, and another is refused."""
    a = new_account(jane, name="Chosen", type="brokerage")
    b = new_account(jane, name="Other", type="brokerage")
    mine = _made(make(jane, "Portf", name="Mine", accountIds=[a["id"]], benchmark="60-40"))
    other = _made(make(jane, "Portf", name="Other", accountIds=[b["id"]], benchmark="60-40"))
    items = [{"kind": "account", "id": a["id"]}, {"kind": "portfolio", "id": mine["id"]}]
    secret = token(jane, scope="chosen", items=items)
    positions = call(agent, secret, "list_positions")["structuredContent"]["result"]
    assert "summary" not in positions
    listed = call(agent, secret, "list_portfolios")["structuredContent"]["result"]
    assert [x["id"] for x in listed] == [mine["id"]], "never every account's together"
    refused = call(agent, secret, "get_portfolio", portfolio_id=other["id"])
    assert refused["isError"]
    assert refused["content"][0]["text"] == "This token doesn't read that portfolio."
    assert not call(agent, secret, "get_portfolio", portfolio_id=mine["id"])["isError"]


@pytest.mark.parametrize(
    ("name", "args", "said"),
    [
        ("get_account_holdings", {}, "get_account_holdings needs account_id."),
        ("get_account_holdings", {"account_id": ""}, "get_account_holdings needs account_id."),
        ("list_accounts", {"limit": 5}, "list_accounts takes nothing."),
        (
            "list_transactions",
            {"wrong": 1},
            "list_transactions takes account_id, from, to, payee, limit.",
        ),
        ("list_transactions", {"payee": "x" * 201}, "payee is a string of at most 200 characters."),
        ("list_transactions", {"payee": 5}, "payee is a string of at most 200 characters."),
        ("list_transactions", {"limit": True}, "limit is a whole number."),
        ("list_transactions", {"limit": "5"}, "limit is a whole number."),
        ("list_transactions", {"limit": 0}, "limit is from 1 to 500."),
        ("list_transactions", {"limit": 501}, "limit is from 1 to 500."),
        ("list_transactions", {"from": "2026-13-01"}, "from is a date such as 2026-10-14."),
        ("list_positions", {"kind": "bonds"}, "kind is one of all, stocks, options, crypto."),
        (
            "get_budget_month",
            {"budget_id": "Bdgt_x", "month": "2026-1"},
            "month doesn't have the form ^\\d{4}-\\d{2}$.",
        ),
        ("get_giving", {"year": 1899}, "year is from 1900 to 2200."),
    ],
)
def test_a_tools_arguments_are_checked_against_its_schema(jane, agent, name, args, said):
    """S10.9.5: arguments a tool doesn't take, one it needs left out or blank, or one not of
    its schema are refused as the tool's error, saying which and why."""
    out = call(agent, token(jane), name, **args)
    assert out == {"content": [{"type": "text", "text": said}], "isError": True}


def test_a_date_not_of_its_form_is_refused_where_a_tool_reads_it():
    """A date the schema let through (checked there too) is still refused where it is read."""
    from moolakata.errors import Problem

    assert mcp._date(None) is None and mcp._date("") is None
    with pytest.raises(Problem) as e:
        mcp._date("14/10/2026")
    assert (e.value.code, e.value.detail) == (
        "date-invalid",
        "'14/10/2026' is not a date such as 2026-10-14.",
    )


def test_a_body_not_json_or_not_one_request_is_a_parse_or_request_error(jane, agent):
    """JSON-RPC 2.0: a body that isn't JSON is -32700; JSON that isn't one request is -32600;
    a response sent to the server (no id) is taken and not answered."""
    secret = token(jane)
    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
    r = agent.post("/mcp", content=b"{not json", headers=headers)
    assert r.status_code == 400
    assert r.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Not JSON."},
    }
    for body in ([{"jsonrpc": "2.0", "id": 1, "method": "ping"}], {"jsonrpc": "1.0", "id": 1,
                 "method": "ping"}, {"jsonrpc": "2.0", "id": 1}):  # fmt: skip
        r = agent.post("/mcp", json=body, headers=headers)
        assert r.status_code == 400 and r.json()["error"] == {
            "code": -32600,
            "message": "One JSON-RPC 2.0 request.",
        }
    r = agent.post("/mcp", json={"jsonrpc": "2.0", "method": "ping"}, headers=headers)
    assert r.status_code == 202 and r.content == b""
