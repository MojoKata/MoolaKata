"""The API conventions every route keeps (requirements S13.8), checked on the routes themselves
so a new route can't drift from them."""

from fastapi.routing import APIRoute

from moolakata.app import Server, create_app
from moolakata.ui.conventions import Deleted, if_match

# Changes to what has no version of its own (S13.8.6): the key files outside the database
# (S15). Signing out ends a session, not a record.
NO_VERSION = {
    ("DELETE", "/ui/api/settings/keys/reencrypt"): "a key file: the scheduled re-encryption",
    ("DELETE", "/ui/api/settings/keys/copies/{name}"): "a key file: a copy, by password and phrase",
    ("DELETE", "/ui/api/settings/keys/previous/{fingerprint}"): "a key file: the keyring's list",
    ("DELETE", "/ui/api/session"): "signing out",
}


def api_routes(routes):
    """Every APIRoute, those of included routers too: FastAPI keeps an included router as one
    entry of the app's routes, holding its own."""
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from api_routes(inner.routes)
        elif isinstance(r, APIRoute):
            yield r


def _routes(store, keyed_config):
    app = create_app(Server(config=keyed_config, store=store, ready=True))
    for r in api_routes(app.routes):
        if r.path.startswith("/ui/api") and r.path != "/ui/api/{rest:path}":  # not found
            for m in r.methods & {"PATCH", "PUT", "DELETE"}:
                yield m, r


def _calls(dep) -> set:
    out = {dep.call}
    for d in dep.dependencies:
        out |= _calls(d)
    return out


def test_every_change_sends_the_version_it_was_made_against(store, keyed_config):
    """Every PATCH, PUT and DELETE requires If-Match (S13.8.6), but for the few with no
    version, each listed with why."""
    missing, needless = [], []
    walked = list(_routes(store, keyed_config))
    # Every route comes from an included router; the save took the rest (S13.8.1).
    assert walked, "the app's routes, those of included routers too"
    for method, r in walked:
        has = if_match in _calls(r.dependant)
        exempt = (method, r.path) in NO_VERSION
        if not has and not exempt:
            missing.append(f"{method} {r.path}")
        if has and exempt:
            needless.append(f"{method} {r.path}")
    assert missing == [] and needless == []


def test_every_delete_answers_what_went_and_its_parent(store, keyed_config):
    """Every DELETE answers {deleted, parent} (S13.8.1), signing out and cancelling the
    scheduled re-encryption aside, which answers the key storage it changed."""
    wrong = []
    for method, r in _routes(store, keyed_config):
        if method != "DELETE" or r.path in (
            "/ui/api/session",
            "/ui/api/settings/keys/reencrypt",
        ):
            continue
        model = r.response_model
        if not (isinstance(model, type) and issubclass(model, Deleted)):
            wrong.append(r.path)
    assert wrong == []


def test_every_list_is_paged(store, keyed_config):
    """Every GET that answers a list takes offset and limit and answers a Page (S13.8.5)."""
    app = create_app(Server(config=keyed_config, store=store, ready=True))
    doc = app.openapi() if app.openapi_url else None
    from moolakata import contract

    doc = doc or contract.openapi_document()
    bare = [
        p
        for p, ops in doc["paths"].items()
        for m, op in ops.items()
        if m == "get"
        and op.get("responses", {})
        .get("200", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("type")
        == "array"
    ]
    assert bare == []


def test_the_document_lists_the_problems_and_their_codes():
    # N16: the problem document and its stable codes are in the OpenAPI document (S13.8.3).
    from moolakata import contract

    doc = contract.openapi_document()
    codes = doc["components"]["schemas"]["Problem"]["properties"]["code"]["enum"]
    for code in ("closed-year", "version-required", "rule-sets-nothing", "uploads-in-flight"):
        assert code in codes, code
    for path, ops in doc["paths"].items():
        for method, op in ops.items():
            assert op["responses"]["default"] == {"$ref": "#/components/responses/Problem"}, (
                method,
                path,
            )


def test_every_201_names_what_it_made_and_every_202_is_a_job(store, keyed_config):
    """S13.8.4, S13.8.7: Location on every 201 (the document says so, and the server adds it
    where a route doesn't), and a job resource for every 202."""
    from moolakata import contract
    from moolakata.ui.imports import JobOut

    app = create_app(Server(config=keyed_config, store=store, ready=True))
    routes = list(api_routes(app.routes))
    assert len(routes) > 200, "the app's routes, those of included routers too"
    not_jobs = [r.path for r in routes if r.status_code == 202 and r.response_model is not JobOut]
    assert not_jobs == []
    doc = contract.openapi_document()
    assert doc["info"]["version"] == app.version, "the document states the release (S13.8.9)"
    for path, ops in doc["paths"].items():
        for method, op in ops.items():
            if "201" in op["responses"]:
                assert "Location" in op["responses"]["201"].get("headers", {}), (method, path)


def test_a_201_without_its_own_location_is_given_one():
    from moolakata.middleware import location_of

    assert location_of("/ui/api/rules", b'{"items": []}') == "/ui/api/rules"
    assert location_of("/ui/api/persons", b'{"id": "Prsn_1"}') == "/ui/api/persons/Prsn_1"
    book = b'{"id": "TxBk_1", "filings": []}'
    assert location_of("/ui/api/tax-books/TxBk_1/filings", book) == "/ui/api/tax-books/TxBk_1"


def test_every_problem_code_and_every_422_is_in_the_openapi_document():
    # S13.8.3, N16: the codes the error handlers answer are listed too, a field's own codes by
    # their pattern, and a 422 is a problem document, never FastAPI's shape.
    from moolakata import contract

    doc = contract.openapi_document()
    codes = set(doc["components"]["schemas"]["Problem"]["properties"]["code"]["enum"])
    assert {"invalid-request", "server-error", "method-not-allowed", "http-error"} <= codes
    assert "HTTPValidationError" not in doc["components"]["schemas"]
    for ops in doc["paths"].values():
        for op in ops.values():
            if isinstance(op, dict) and "422" in op.get("responses", {}):
                assert op["responses"]["422"] == {"$ref": "#/components/responses/Problem"}
