"""The code generator (R3.9, S17.5), in-process: the JSDoc types and the drafts' fields from a
small OpenAPI document, and `write` and `check` on a temporary copy. `web/check static` runs it
as a process on the real routes; these run its branches where the tests measure them."""

import json

import pytest

from moolakata import contract

T = contract._js_type
F = contract._field


@pytest.mark.parametrize(
    ("schema", "js"),
    [
        ({"$ref": "#/components/schemas/A-b.c"}, "A_b_c"),
        ({"const": "x"}, '"x"'),
        ({"enum": ["a", 1]}, '("a" | 1)'),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "(string | null)"),
        # The same type twice is named once, and one alone needs no brackets.
        ({"oneOf": [{"type": "string"}, {"type": "string"}]}, "string"),
        ({"allOf": [{"type": "boolean"}]}, "boolean"),
        ({"type": "number", "format": "money"}, "import('../kit/dec.js').Dec"),
        ({"type": "number", "format": "decimal"}, "import('../kit/dec.js').Dec"),
        ({"type": "number"}, "number"),
        ({"type": "integer"}, "number"),
        ({"type": "null"}, "null"),
        ({"type": "array", "items": {"type": "integer"}}, "Array<number>"),
        ({"type": "array"}, "Array<unknown>"),
        ({"type": "object", "additionalProperties": {"type": "string"}}, "Object<string, string>"),
        ({"type": "object", "additionalProperties": True}, "Object<string, unknown>"),
        ({"type": "object"}, "Object<string, unknown>"),
        # Two of allOf aren't merged: the type is left unknown.
        ({"allOf": [{"type": "string"}, {"type": "integer"}]}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_a_schema_is_typed_for_jsdoc(schema, js):
    assert T(schema) == js


SCHEMAS = {"Colour": {"enum": ["red", "blue"]}, "Thing": {"type": "object"}}


@pytest.mark.parametrize(
    ("schema", "spec"),
    [
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, {"type": "text", "nullable": True}),
        ({"oneOf": [{"type": "integer"}]}, {"type": "int"}),
        # Two types besides null are a value the draft keeps as it is.
        ({"anyOf": [{"type": "string"}, {"type": "integer"}]}, {"type": "json"}),
        ({"allOf": [{"type": "boolean"}]}, {"type": "bool"}),
        # A reference to an enumeration is its choices; to anything else, its schema's name.
        ({"$ref": "#/components/schemas/Colour"}, {"type": "choice", "choices": ["red", "blue"]}),
        ({"$ref": "#/components/schemas/Thing"}, {"type": "json", "schema": "Thing"}),
        ({"$ref": "#/components/schemas/Missing"}, {"type": "json", "schema": "Missing"}),
        ({"const": "only"}, {"type": "choice", "choices": ["only"]}),
        ({"x-kind": "percent", "type": "number"}, {"type": "percent"}),
        ({"type": "string", "x-prefix": "acc"}, {"type": "ref", "prefix": "acc"}),
        ({"type": "string", "format": "date"}, {"type": "date"}),
        ({"type": "string", "format": "date-time"}, {"type": "timestamp"}),
        ({"type": "string", "format": "email"}, {"type": "text"}),
        ({"type": "number", "format": "money"}, {"type": "money"}),
        ({"type": "number", "format": "decimal"}, {"type": "quantity"}),
        (
            {"type": "array", "items": {"type": "integer"}},
            {"type": "list", "items": {"type": "int"}},
        ),
        (
            {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
            {"type": "list", "items": {"type": "text"}, "set": True},
        ),
        ({"type": "array"}, {"type": "list", "items": {"type": "json"}}),
        ({"type": "object"}, {"type": "json"}),
    ],
)
def test_a_field_is_typed_for_the_drafts(schema, spec):
    assert F(schema, SCHEMAS) == spec


def test_refs_are_found_however_deep():
    found: set[str] = set()
    contract._refs(
        {"a": [{"$ref": "#/x/One"}, {"b": {"$ref": "#/x/Two"}}], "$ref": 3, "c": [[1, "s"]]},
        found,
    )
    assert found == {"One", "Two"}


def _doc() -> dict:
    """A small document: one kind of record the save takes, the schemas it refers to (one of
    them only through another), and one nothing refers to."""
    return {
        "paths": {
            "/x": {
                "parameters": [{"name": "id"}],  # not an operation: left alone
                "summary": "a path's own summary",
                "get": {"responses": {"200": {}}},
                "post": {"responses": {"201": {}}},
                "put": {"summary": "no responses"},
            }
        },
        "components": {
            "schemas": {
                "AccountFields": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {"$ref": "#/components/schemas/Kind"},
                        "two-words": {"$ref": "#/components/schemas/Nested"},
                    },
                    "x-entity": "acc",
                    "x-creates": {"who": "admin"},
                },
                "Kind": {"enum": ["a", "b"], "description": "A kind.\n\nOf account.  "},
                "Nested": {"type": "object", "properties": {"deep": {"$ref": "#/x/Deeper"}}},
                "Deeper": {"type": "object"},
                "Unused": {"type": "object", "properties": {"z": {"type": "integer"}}},
            }
        },
    }


def test_the_types_list_every_schema_with_its_properties():
    js = contract.types_js(_doc())
    assert js.startswith("// Generated from the API's OpenAPI document")
    assert " * @typedef {Object} AccountFields\n * @property {string} name\n" in js
    assert " * @property {Kind} [kind]\n * @property {Nested} [two-words]\n" in js
    # A description's lines, each with no trailing space; a schema with no properties is typed.
    assert '/**\n * A kind.\n *\n * Of account.\n * @typedef {("a" | "b")} Kind\n */' in js
    assert " * @typedef {Object} Deeper\n" in js
    assert js.endswith("export {};\n")


def test_the_fields_are_the_kinds_and_what_they_refer_to_however_deep():
    js = contract.fields_js(_doc())
    assert "  AccountFields: {\n    name: " in js
    # A property that isn't a JavaScript name is quoted.
    assert '    "two-words": {"type": "json", "schema": "Nested"},' in js
    assert "  Nested: {\n    deep: " in js
    # Deeper is wanted but has no properties; Unused is referred to by no kind.
    assert "Deeper:" not in js and "Unused" not in js
    assert '  acc: {"who": "admin"},\n};\n' in js


def test_a_document_with_no_schemas_gives_empty_files():
    empty = {"paths": {}}  # an empty dict would be read as none given, and the routes' taken
    assert contract.types_js(empty).endswith("the routes give.\n\nexport {};\n")
    assert "export const FIELDS = {\n};" in contract.fields_js(empty)
    assert "export const CREATES = {\n};" in contract.fields_js(empty)


def test_the_problems_skip_what_isnt_an_operation_and_a_201_names_its_location():
    doc = _doc()
    contract._problems(doc)
    contract._created(doc)
    ops = doc["paths"]["/x"]
    assert ops["parameters"] == [{"name": "id"}] and ops["summary"] == "a path's own summary"
    assert "responses" not in ops["put"]
    assert ops["get"]["responses"]["default"] == {"$ref": "#/components/responses/Problem"}
    assert "Location" in ops["post"]["responses"]["201"]["headers"]
    assert "headers" not in ops["get"]["responses"]["200"]


def test_the_openapi_json_is_sorted_and_ends_with_a_line():
    assert contract.openapi_json({"b": 1, "a": "é"}) == '{\n  "a": "é",\n  "b": 1\n}\n'


@pytest.fixture
def generated(tmp_path, monkeypatch):
    """The generator writing to a temporary copy of the repository's layout."""
    monkeypatch.setattr(contract, "openapi_document", _doc)
    monkeypatch.setattr(contract.paths, "ROOT", tmp_path)
    files = {
        name: tmp_path / "web" / "ui" / "api" / f"{name}"
        for name in ("openapi.json", "types.js", "fields.js")
    }
    monkeypatch.setattr(contract, "OPENAPI_FILE", files["openapi.json"])
    monkeypatch.setattr(contract, "TYPES_FILE", files["types.js"])
    monkeypatch.setattr(contract, "FIELDS_FILE", files["fields.js"])
    return files


def test_write_makes_the_files_and_check_then_passes(generated, capsys):
    assert contract.main(["contract", "check"]) == 1  # none there yet
    err = capsys.readouterr().err
    assert "web/ui/api/openapi.json is out of date: run `web/dev.sh codegen`" in err
    assert contract.main(["contract", "write"]) == 0
    assert json.loads(generated["openapi.json"].read_text()) == _doc()
    assert generated["types.js"].read_text() == contract.types_js(_doc())
    assert contract.main(["contract", "check"]) == 0
    assert capsys.readouterr().err == ""


def test_check_names_only_the_file_that_differs(generated, capsys):
    contract.main(["contract", "write"])
    generated["fields.js"].write_text("// edited by hand\n")
    assert contract.main(["contract", "check"]) == 1
    assert capsys.readouterr().err.splitlines() == [
        "web/ui/api/fields.js is out of date: run `web/dev.sh codegen`"
    ]


@pytest.mark.parametrize("argv", [["contract"], ["contract", "wrte"]])
def test_no_command_or_an_unknown_one_prints_the_usage(generated, capsys, argv):
    assert contract.main(argv) == 2
    assert "python -m moolakata.contract check" in capsys.readouterr().out
    assert not generated["openapi.json"].exists()
