"""The MCP endpoint (requirements S10.9): `/mcp`, the Model Context Protocol over Streamable
HTTP, for an AI assistant holding one of a user's access tokens.

1. **Read only.** Every tool reads, through the user's shares at the moment of the call, with
   the same code the screens use. A token caller is never an admin, so nothing reaches
   Settings or other users' data; secrets are never in what the screens read either.
2. **A chosen-items token** reads only its accounts and portfolios: lists are filtered to them,
   and the tools about the whole household (budgets, gifts, giving, taxes) refuse it.
3. **Each call** is limited to 60 a minute per token, notes the token's last use, and is
   recorded in Activity under the token's name.
4. JSON-RPC 2.0 over POST, answered as JSON; there is no server-sent stream, so GET is refused.
   A request with an Origin header from elsewhere (a web page) is refused, as the protocol asks.
"""

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from . import activity, clock, exactjson, ratelimit, tokens
from .errors import Problem
from .store.entities.users import AccessToken

router = APIRouter(tags=["mcp"], include_in_schema=False)  # not part of the UI's contract
VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LIMIT = ratelimit.Window(60, 60)
INSTRUCTIONS = (
    "MoolaKata is a household's finances: accounts, holdings, transactions, portfolios, "
    "budgets, gifts, giving and taxes. Every tool reads; nothing can be changed here. Amounts "
    "are US dollars, as exact JSON numbers; dates are ISO 8601 (2026-10-14)."
)


@dataclass
class Tool:
    name: str
    description: str
    params: dict  # JSON Schema properties
    required: list[str]
    run: Callable
    whole: bool = False  # about the whole household: refused to a chosen-items token


@dataclass
class Who:
    token: AccessToken
    caller: object  # ui.deps.Caller
    chosen: dict[str, set[str]] | None  # None: everything the user can see


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, params: dict | None = None, required=(), whole=False):
    def add(fn):
        TOOLS[name] = Tool(name, description, params or {}, list(required), fn, whole)
        return fn

    return add


def _req(srv):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(server=srv)))


def _dump(x):
    if isinstance(x, list):
        return [_dump(i) for i in x]
    if isinstance(x, dict):
        return {k: _dump(v) for k, v in x.items()}
    return x.model_dump(mode="json") if hasattr(x, "model_dump") else x


def _account_ok(w: Who, account_id: str) -> None:
    if w.chosen is not None and account_id not in w.chosen["account"]:
        raise Problem(404, "not-found", "This token doesn't read that account.")


def _portfolio_ok(w: Who, portfolio_id: str) -> None:
    if w.chosen is not None and portfolio_id not in w.chosen["portfolio"]:
        raise Problem(404, "not-found", "This token doesn't read that portfolio.")


def _accounts_of(w: Who, rows: list[dict]) -> list[dict]:
    if w.chosen is None:
        return rows
    return [r for r in rows if r.get("id", r.get("accountId")) in w.chosen["account"]]


# ---------- the tools


@tool("list_accounts", "Every account the token reads: its type, balance and 30-day change.")
def _list_accounts(srv, w, args):
    from .ui import accounts

    rows = _dump(accounts.list_accounts(_req(srv), w.caller))
    return _accounts_of(w, rows)


@tool(
    "get_account_holdings",
    "What an investing account holds: each instrument's quantity, value, cost and gain.",
    {"account_id": {"type": "string"}},
    ["account_id"],
)
def _holdings(srv, w, args):
    from .ui import accounts

    _account_ok(w, args["account_id"])
    return _dump(accounts.account_holdings(args["account_id"], _req(srv), w.caller))


@tool(
    "list_transactions",
    "Transactions, newest first, in one account or all of them, between two dates, optionally "
    "matching a payee. At most 500.",
    {
        "account_id": {"type": "string"},
        "from": {"type": "string", "format": "date"},
        "to": {"type": "string", "format": "date"},
        "payee": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
    },
)
def _transactions(srv, w, args):
    from .ui import transactions
    from .ui.conventions import Paging

    if args.get("account_id"):
        _account_ok(w, args["account_id"])
        wanted = [args["account_id"]]
    elif w.chosen is not None:
        wanted = sorted(w.chosen["account"]) or ["-"]
    else:
        wanted = []
    page = transactions.list_transactions(
        _req(srv),
        w.caller,
        Paging(offset=0, limit=int(args.get("limit") or 100)),
        account=wanted,
        category=None,
        start=_date(args.get("from")),
        end=_date(args.get("to")),
        min_amount=None,
        max_amount=None,
        payee=args.get("payee"),
        tag=None,
        sort="-date",
    )
    return _dump(page)["items"]


@tool(
    "list_positions",
    "Open and closed positions across investing accounts, with realized and unrealized gains.",
    {"kind": {"type": "string", "enum": ["all", "stocks", "options", "crypto"]}},
)
def _positions(srv, w, args):
    from .ui import positions

    v = _dump(positions.list_positions(_req(srv), args.get("kind") or "all", w.caller))
    if w.chosen is not None:
        v["open"] = _accounts_of(w, v["open"])
        v["closed"] = _accounts_of(w, v["closed"])
        v.pop("summary", None)
    return v


@tool("list_portfolios", "The portfolios the token reads: each one's accounts and value.")
def _portfolios(srv, w, args):
    from .ui import portfolios

    rows = _dump(portfolios.list_portfolios(_req(srv), w.caller))
    if w.chosen is not None:
        rows = [r for r in rows if r.get("id") in w.chosen["portfolio"]]
    return rows


@tool(
    "get_portfolio",
    "One portfolio: its value, holdings added up by instrument, and returns by period.",
    {"portfolio_id": {"type": "string"}},
    ["portfolio_id"],
)
def _portfolio(srv, w, args):
    from .ui import portfolios

    pid = args["portfolio_id"]
    _portfolio_ok(w, pid)
    return {
        "portfolio": _dump(portfolios.get_portfolio(pid, _req(srv), w.caller)),
        "holdings": _dump(portfolios.portfolio_holdings(pid, _req(srv), w.caller)),
        "returns": _dump(portfolios.portfolio_returns(pid, _req(srv), w.caller)),
    }


@tool("list_budgets", "The budgets the user can see.", whole=True)
def _budgets(srv, w, args):
    from .ui import budgets

    return _dump(budgets.list_budgets(_req(srv), w.caller))


@tool(
    "get_budget_month",
    "One budget's month: planned and spent by category, income, and what wasn't planned.",
    {"budget_id": {"type": "string"}, "month": {"type": "string", "pattern": "^\\d{4}-\\d{2}$"}},
    ["budget_id"],
    whole=True,
)
def _budget_month(srv, w, args):
    from .ui import budgets

    return _dump(budgets.budget_month(args["budget_id"], _req(srv), w.caller, args.get("month")))


@tool("list_upcoming_gifts", "Birthdays and holidays coming up, with gift plans.", whole=True)
def _gifts(srv, w, args):
    from .ui import gifts

    return _dump(gifts.list_upcoming(_req(srv), w.caller))


@tool(
    "get_giving",
    "A year's giving: donations by organisation, the giving plan and what is left of it.",
    {"year": {"type": "integer", "minimum": 1900, "maximum": 2200}},
    whole=True,
)
def _giving(srv, w, args):
    from .ui import giving

    return _dump(giving.get_giving(_req(srv), args.get("year"), w.caller))


@tool("list_tax_books", "The tax books the user can see: one a tax year.", whole=True)
def _books(srv, w, args):
    from .ui import taxes

    return _dump(taxes.list_books(_req(srv), w.caller))


@tool(
    "get_tax_panels",
    "A tax book's panels: gains (Form 8949, Schedule D), income, retirement, deductions, giving, "
    "education, gifts, loans and property, and what is missing.",
    {"book_id": {"type": "string"}},
    ["book_id"],
    whole=True,
)
def _panels(srv, w, args):
    from .ui import taxpanels

    return _dump(taxpanels.get_panels(args["book_id"], _req(srv), w.caller))


def _date(v):
    if not v:
        return None
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        raise Problem(422, "date-invalid", f"{v!r} is not a date such as 2026-10-14.") from None


# ---------- the protocol


def _who(srv, request: Request) -> Who:
    from .ui.deps import Caller

    auth = request.headers.get("authorization", "")
    raw = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    with srv.db.read(unscoped="mcp: who") as s:
        found = tokens.find(s, raw) if raw else None
    if found is None:
        raise Problem(
            401,
            "token-refused",
            "An access token from Profile › Access tokens is needed, as a bearer token.",
            headers={"WWW-Authenticate": 'Bearer realm="MoolaKata MCP"'},
        )
    t, user = found
    LIMIT.check(t.id, "calls")
    return Who(t, Caller(user, None, False), None if t.scope == "all" else tokens.chosen(t))


def _result(id_, result) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _tools_list() -> dict:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": {
                    "type": "object",
                    "properties": t.params,
                    "required": t.required,
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            }
            for t in TOOLS.values()
        ]
    }


def _call(srv, w: Who, params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    t = TOOLS.get(name)
    if t is None:
        raise KeyError(name)
    unknown = set(args) - set(t.params)
    if unknown or not isinstance(args, dict):
        return _tool_error(f"{name} takes {', '.join(t.params) or 'nothing'}.")
    if missing := [r for r in t.required if not args.get(r)]:
        return _tool_error(f"{name} needs {', '.join(missing)}.")
    if wrong := _invalid(t, args):
        return _tool_error(wrong)
    if t.whole and w.chosen is not None:
        return _tool_error("This token reads only its chosen accounts and portfolios.")
    with srv.db.tx(unscoped="mcp: call") as s:
        tok = s.get(AccessToken, w.token.id)
        tok.lastUsedAt = clock.now()
        activity.record(
            s,
            "mcp.called",
            actor=w.caller.id,
            owner=w.caller.id,
            via="mcp",
            detail={"name": w.token.name, "tool": name},
        )
    try:
        out = t.run(srv, w, args)
    except Problem as e:
        return _tool_error(e.detail)
    return {
        "content": [{"type": "text", "text": exactjson.dumps(out)}],
        "structuredContent": {"result": out},
        "isError": False,
    }


def _invalid(t: Tool, args: dict) -> str | None:
    """What is wrong with a call's arguments against its tool's schema, or None (S10.9.5)."""
    for key, value in args.items():
        schema = t.params[key]
        if schema["type"] == "integer":
            low, high = schema.get("minimum"), schema.get("maximum")
            if isinstance(value, bool) or not isinstance(value, int):
                return f"{key} is a whole number."
            if (low is not None and value < low) or (high is not None and value > high):
                return f"{key} is from {low} to {high}."
        elif not isinstance(value, str) or len(value) > 200:
            return f"{key} is a string of at most 200 characters."
        elif "enum" in schema and value not in schema["enum"]:
            return f"{key} is one of {', '.join(schema['enum'])}."
        elif "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            return f"{key} doesn't have the form {schema['pattern']}."
        elif schema.get("format") == "date":
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                return f"{key} is a date such as 2026-10-14."
    return None


def _tool_error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    return origin == f"{request.url.scheme}://{request.headers.get('host', '')}"


@router.post("/mcp")
async def mcp_post(request: Request):
    srv = request.app.state.server
    if not _origin_ok(request):
        raise Problem(403, "origin-refused", "MCP calls don't come from web pages.")
    w = _who(srv, request)
    try:
        msg = exactjson.loads(await request.body())
    except ValueError:
        return JSONResponse(_error(None, -32700, "Not JSON."), status_code=400)
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return JSONResponse(_error(None, -32600, "One JSON-RPC 2.0 request."), status_code=400)
    method, id_, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if id_ is None:  # a notification, or a response: nothing to answer
        return Response(status_code=202)
    if method == "initialize":
        asked = params.get("protocolVersion")
        return JSONResponse(
            _result(
                id_,
                {
                    "protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "MoolaKata", "version": srv.version},
                    "instructions": INSTRUCTIONS,
                },
            )
        )
    if method == "ping":
        return JSONResponse(_result(id_, {}))
    if method == "tools/list":
        return JSONResponse(_result(id_, _tools_list()))
    if method == "tools/call":
        from starlette.concurrency import run_in_threadpool

        try:
            out = await run_in_threadpool(_call, srv, w, params)
        except KeyError:
            return JSONResponse(_error(id_, -32602, f"No tool {params.get('name')!r}."))
        return JSONResponse(_result(id_, out))
    return JSONResponse(_error(id_, -32601, f"MoolaKata's MCP doesn't do {method!r}."))


@router.get("/mcp")
@router.delete("/mcp")
def mcp_other():
    return Response(status_code=405, headers={"Allow": "POST"})
