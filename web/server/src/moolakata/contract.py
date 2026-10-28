"""The generated contract (requirements R3.9, S17.5): the OpenAPI document comes from the
routes, and the browser app's JSDoc types and its drafts' fields (S17.3.9.2) come from it.
`web/check` fails when any of the files is out of date.

    python -m moolakata.contract write    regenerate the files
    python -m moolakata.contract check    fail if any differs from what the routes give
"""

import json
import re
import sys
from pathlib import Path

from . import paths

OPENAPI_FILE = paths.UI / "api" / "openapi.json"
TYPES_FILE = paths.UI / "api" / "types.js"
FIELDS_FILE = paths.UI / "api" / "fields.js"


def openapi_document() -> dict:
    from fastapi.openapi.utils import get_openapi

    from .app import Server, create_app
    from .config import Config

    config = Config(
        name="contract",
        mode="proxy",
        data_dir=Path("/nonexistent/data"),
        backup_dir=Path("/nonexistent/backups"),
    )
    app = create_app(Server(config=config))
    doc = get_openapi(
        title="MoolaKata",
        version=app.version,
        routes=app.routes,
        description="The browser app's API, /ui/api (requirements S13.8). It is "
        "served with the app and carries no version of its own.",
    )
    # The release, from web/VERSION (S13.8.9): a version bump changes the document too.
    _problems(doc)
    _created(doc)
    _saved(doc)
    return doc


def _saved(doc: dict) -> None:
    """The fields of each kind of record the save takes (S13.8.11), as schemas of their own
    marked with the kind's prefix, so the browser's drafts have their types (S17.3.9.2)."""
    from .ui import save

    schemas = doc.setdefault("components", {}).setdefault("schemas", {})
    for prefix, kind in sorted(save.KINDS.items()):
        schema = kind.fields.model_json_schema(ref_template="#/components/schemas/{model}")
        for name, sub in schema.pop("$defs", {}).items():
            schemas.setdefault(name, sub)
        schemas[kind.fields.__name__] = {**schema, "x-entity": prefix}


PROBLEM_CALLS = {"Problem", "refuse", "FieldError", "_send_problem", "problem_response"}
# What the error handlers answer beyond the calls above: an HTTP error by its status
# (errors.py's on_http), and a field refused by its validation type, `invalid-<type>`.
HANDLER_CODES = ("http-error", "method-not-allowed", "not-found")
FIELD_CODE = "^invalid-[a-z0-9-]+$"


def problem_codes() -> list[str]:
    """Every stable code the server answers a problem with (S13.8.3), read from its source:
    the second argument of Problem(), refuse(), FieldError() and the middleware's problems."""
    import ast

    codes: set[str] = set()
    for path in paths.PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or len(node.args) < 2:
                continue
            f = node.func
            name = (
                f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            )
            arg = node.args[1]
            if (
                name in PROBLEM_CALLS
                and isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
            ):
                codes.add(arg.value)
    return sorted(codes | set(HANDLER_CODES))


def _problems(doc: dict) -> None:
    """The problem document (RFC 9457) as a schema, its codes listed, and as every
    operation's default response."""
    codes = problem_codes()
    schemas = doc.setdefault("components", {}).setdefault("schemas", {})
    schemas["ProblemFieldError"] = {
        "type": "object",
        "required": ["field", "code", "message"],
        "properties": {
            "field": {"type": ["string", "null"]},
            # The record a save's refusal is about (S13.8.11.4); other refusals leave it out.
            "id": {"type": "string"},
            # One of the codes, or a field refused by its validation type (`invalid-<type>`).
            "code": {
                "anyOf": [
                    {"type": "string", "enum": codes},
                    {"type": "string", "pattern": FIELD_CODE},
                ]
            },
            "message": {"type": "string"},
        },
    }
    schemas["Problem"] = {
        "type": "object",
        "description": "A refusal (S13.8.3): its code is one of those listed, and stable.",
        "required": ["type", "title", "status", "detail", "code", "errorId", "errors"],
        "properties": {
            "type": {"type": "string", "format": "uri"},
            "title": {"type": "string"},
            "status": {"type": "integer"},
            "detail": {"type": "string"},
            "code": {"type": "string", "enum": codes},
            "errorId": {"type": "string"},
            "errors": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/ProblemFieldError"},
            },
        },
    }
    doc["components"].setdefault("responses", {})["Problem"] = {
        "description": "A refusal, as application/problem+json.",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    }
    for ops in doc.get("paths", {}).values():
        for op in ops.values():
            if isinstance(op, dict) and "responses" in op:
                op["responses"].setdefault("default", {"$ref": "#/components/responses/Problem"})
                # A request refused for its fields is a problem document too, never FastAPI's
                # own shape (S13.8.3).
                if "422" in op["responses"]:
                    op["responses"]["422"] = {"$ref": "#/components/responses/Problem"}
    for name in ("HTTPValidationError", "ValidationError"):
        schemas.pop(name, None)


def _created(doc: dict) -> None:
    """A 201 names what it made in `Location` (S13.8.4), unless nothing reads it."""
    for ops in doc.get("paths", {}).values():
        for op in ops.values():
            made = op.get("responses", {}).get("201") if isinstance(op, dict) else None
            if made is not None:
                made.setdefault("headers", {})["Location"] = {
                    "description": "Where what was made is read: its own path, or the list "
                    "or record that holds it. Left out when nothing reads it.",
                    "schema": {"type": "string"},
                }


def openapi_json(doc: dict | None = None) -> str:
    return (
        json.dumps(doc or openapi_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def _js_type(schema: dict) -> str:
    if "$ref" in schema:
        return _ident(schema["$ref"].rsplit("/", 1)[-1])
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        return "(" + " | ".join(json.dumps(v) for v in schema["enum"]) + ")"
    for key in ("anyOf", "oneOf"):
        if key in schema:
            parts = []
            for s in schema[key]:
                t = _js_type(s)
                if t not in parts:
                    parts.append(t)
            return "(" + " | ".join(parts) + ")" if len(parts) > 1 else parts[0]
    if "allOf" in schema and len(schema["allOf"]) == 1:
        return _js_type(schema["allOf"][0])
    t = schema.get("type")
    if t == "number" and schema.get("format") in ("money", "decimal"):
        # An exact number (S13.8.2): the client decodes it as a Dec, never a float.
        return "import('../app/dec.js').Dec"
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        return f"Array<{_js_type(schema.get('items', {}))}>"
    if t == "object":
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            return f"Object<string, {_js_type(extra)}>"
        return "Object<string, unknown>"
    return "unknown"


def _ident(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_$]", "_", name)


def types_js(doc: dict | None = None) -> str:
    doc = doc or openapi_document()
    lines = [
        "// Generated from the API's OpenAPI document by `python -m moolakata.contract write`.",
        "// Do not edit: web/check fails when this file differs from what the routes give.",
        "",
    ]
    schemas = doc.get("components", {}).get("schemas", {})
    for name in sorted(schemas):
        schema = schemas[name]
        lines.append("/**")
        if schema.get("description"):
            for d in schema["description"].strip().splitlines():
                lines.append(f" * {d}".rstrip())
        if schema.get("type") == "object" or "properties" in schema:
            lines.append(f" * @typedef {{Object}} {_ident(name)}")
            required = set(schema.get("required", []))
            for prop, ps in schema.get("properties", {}).items():
                optional = prop not in required
                label = f"[{prop}]" if optional else prop
                lines.append(f" * @property {{{_js_type(ps)}}} {label}")
        else:
            lines.append(f" * @typedef {{{_js_type(schema)}}} {_ident(name)}")
        lines.append(" */")
        lines.append("")
    lines.append("export {};")
    return "\n".join(lines) + "\n"


def _field(schema: dict, schemas: dict) -> dict:
    """A field's type for the browser's drafts (S12.15.2), from its schema: what it is, whether
    it may be empty, its choices, what a reference refers to, a list's items."""
    for key in ("anyOf", "oneOf"):
        if key in schema:
            parts = [s for s in schema[key] if s.get("type") != "null"]
            nullable = len(parts) < len(schema[key])
            out = _field(parts[0], schemas) if len(parts) == 1 else {"type": "json"}
            return {**out, "nullable": True} if nullable else out
    if "allOf" in schema and len(schema["allOf"]) == 1:
        return _field(schema["allOf"][0], schemas)
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        target = schemas.get(name, {})
        return _field(target, schemas) if "enum" in target else {"type": "json", "schema": name}
    if "enum" in schema or "const" in schema:
        return {"type": "choice", "choices": schema.get("enum", [schema.get("const")])}
    if "x-kind" in schema:
        return {"type": schema["x-kind"]}
    t, fmt = schema.get("type"), schema.get("format")
    if t == "string":
        if "x-prefix" in schema:
            return {"type": "ref", "prefix": schema["x-prefix"]}
        return {"type": {"date": "date", "date-time": "timestamp"}.get(fmt, "text")}
    if t == "number":
        return {"type": "money" if fmt == "money" else "quantity"}
    if t == "integer":
        return {"type": "int"}
    if t == "boolean":
        return {"type": "bool"}
    if t == "array":
        out = {"type": "list", "items": _field(schema.get("items", {}), schemas)}
        return {**out, "set": True} if schema.get("uniqueItems") else out
    return {"type": "json"}


def fields_js(doc: dict | None = None) -> str:
    """Every schema's fields as the browser's drafts type them (S17.3.9.2)."""
    doc = doc or openapi_document()
    schemas = doc.get("components", {}).get("schemas", {})
    out = {}
    for name in sorted(schemas):
        props = schemas[name].get("properties")
        if props:
            out[name] = {p: _field(ps, schemas) for p, ps in props.items()}
    lines = [
        "// Generated from the API's OpenAPI document by `python -m moolakata.contract write`.",
        "// Do not edit: web/check fails when this file differs from what the routes give.",
        "",
        "/** @type {Record<string, Record<string, import('../app/draft.js').FieldSpec>>} */",
        "export const FIELDS = {",
    ]
    for name, fields in out.items():
        lines.append(f"  {_ident(name)}: {{")
        for prop, spec in fields.items():
            key = prop if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", prop) else json.dumps(prop)
            lines.append(f"    {key}: {json.dumps(spec, ensure_ascii=False)},")
        lines.append("  },")
    lines.append("};")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    doc = openapi_document()
    wanted = {
        OPENAPI_FILE: openapi_json(doc),
        TYPES_FILE: types_js(doc),
        FIELDS_FILE: fields_js(doc),
    }
    if command == "write":
        for path, text in wanted.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return 0
    if command == "check":
        stale = [p for p, text in wanted.items() if not p.exists() or p.read_text() != text]
        for p in stale:
            print(
                f"{p.relative_to(paths.ROOT)} is out of date: run "
                "`python -m moolakata.contract write`",
                file=sys.stderr,
            )
        return 1 if stale else 0
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
